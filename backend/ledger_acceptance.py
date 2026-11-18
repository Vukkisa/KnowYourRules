"""Ledger acceptance gate (roadmap Step 2, review finding M1).

Step 4: the ONLY module that calls this gate is backend/provision_validity_runtime.py (the server imports that wrapper, never this
file). It is the only bridge between the pure validity library and
the approval machinery, so the library itself stays free of application imports.

What this gate guarantees, and what it does not
------------------------------------------------
``accept_ledger`` takes FILE PATHS, never a ``Registry`` or ``ApprovalStatus`` object, and rebuilds the whole trust chain
itself from the existing mechanisms (no new signing scheme):

    trusted-keys file --signature--> approval record --source_status_sha256--> registry file --validity_ledger_sha256--> ledger file
                                                                                  |--validity_decision_register_sha256--> decision register
                                                                                  `--validity_evidence_manifest_sha256--> evidence manifest --> evidence files

1. ``legal_approval.evaluate`` verifies the record's Ed25519 signature against the trusted-keys file, the index metadata,
   unresolved conditions and (if given) the corpus. It must report ``valid``. It is not given the registry path.
2. The registry file is read ONCE. Those bytes are hashed, the hash must equal the verified record's
   ``source_status_sha256`` (``legal_approval.source_status_errors``, the same check ``evaluate`` would run), and the same
   bytes are parsed by ``source_status.load_bytes``. The registry must be ``valid``.
3. The ledger file is read ONCE. Its SHA-256 must equal the registry's ``validity_ledger_sha256``.
4. The ledger must load and ``validate()`` must report no ``error``-severity problem (C3b, overlaps, ...).
5. (Step 3 review M1) The decision register is read ONCE (a regular file, size-capped); its SHA-256 must equal the registry's
   ``validity_decision_register_sha256``, so a changed register no longer matches the signed chain. Its ``jurisdiction`` must
   equal the approval record's, the registry's and the evidence manifest's.
6. The evidence manifest is read ONCE; its SHA-256 must equal ``validity_evidence_manifest_sha256`` and it must be in the
   canonical form of ``evidence_manifest.parse``. Every file a decision or fact cites must be listed in it and, below
   ``evidence_dir`` (opened without following any link), be a regular file with the listed size and SHA-256.
7. (Step 3) The register is compared with the ledger by ``validity_decisions.check_decisions``: every decision the ledger
   declares or relies on must exist, match, and be ``approved`` with a complete record and held evidence. Any problem rejects.

What the signed binding means (interim "Option A", see docs/approval-trust-model.md)
------------------------------------------------------------------------------------
The register and manifest are ATTESTED by the offline approval authority: it signed a record that binds these exact bytes.
That does NOT authenticate the named reviewer. No reviewer key, identity or signature exists; the reviewer's name, history and
date are text the authority attested, and the plausibility checks in ``validity_decisions`` filter careless records only. This
gate never claims that a reviewer's identity or personal approval was cryptographically verified.

Time and paths
--------------
* The clock is the gate's own ``_today()`` (the system date), read once per call. There is NO date parameter: a caller
  cannot make a future-dated approval valid. Tests that need a fixed date replace ``_today`` with ``unittest.mock``; that
  is in-process patching, the same trust boundary as replacing any function, and no production call path offers it.
* Every input path is resolved once with ``os.fspath`` at entry, and only the resulting string is used afterwards, so a
  path-like object cannot mean different files at different steps. Each file's bytes are read once and the hash and the
  parse use those same bytes; a file replaced during acceptance can only cause a mismatch and a rejection.
* Not addressed here (roadmap m4): replay of an older, still validly signed approval/registry/ledger set. A freshness
  policy is a required decision before any runtime integration.

``Acceptance.ok`` means these checks passed. It does NOT mean the ledger's content is legally approved: the decisions inside
a ledger are checked against the decision register in Step 3, and the resolver still never returns an authoritative verdict.
An accepted fixture ledger is flagged ``fixture=True`` and ``production`` is False. The ``UNSIGNED_TEST_ONLY`` sentinel is
refused here; tests use real throwaway keys.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from dataclasses import dataclass
from typing import Optional

from backend import evidence_manifest, legal_approval, provision_validity, source_status, validity_decisions

__all__ = ["Acceptance", "accept_ledger"]

MAX_REGISTER_BYTES = 8 << 20
MAX_REGISTRY_BYTES = 8 << 20
MAX_LEDGER_BYTES = 32 << 20


@dataclass(frozen=True)
class Acceptance:
    """Outcome of ``accept_ledger``. ``ledger`` is set only when every check passed."""
    ledger: Optional[provision_validity.Ledger] = None
    problems: tuple = ()
    fixture: bool = False                 # the accepted ledger is synthetic test data
    registry_sha256: Optional[str] = None
    ledger_sha256: Optional[str] = None
    register_sha256: Optional[str] = None
    manifest_sha256: Optional[str] = None

    @property
    def ok(self) -> bool:
        """The acceptance checks passed. Not a statement that the ledger is legally approved."""
        return self.ledger is not None and not self.problems

    @property
    def production(self) -> bool:
        """Accepted and not a fixture. Still not a legal approval of the ledger's content."""
        return self.ok and not self.fixture


def _reject(*problems: str) -> Acceptance:
    return Acceptance(None, tuple(problems))


def _today() -> dt.date:
    """The trusted current date: the system clock. The only way to change it is to replace this function (tests do)."""
    return dt.date.today()


def _once(v):
    """Resolve a path argument exactly once to a str, or None if it is not a usable path. Bytes paths are refused."""
    if not isinstance(v, (str, os.PathLike)):
        return None
    out = os.fspath(v)
    return out if isinstance(out, str) else None


def accept_ledger(ledger_path, *, registry_path, approval_path, trusted_keys, decision_register, evidence_manifest,
                  metadatas, corpus_dir=None, evidence_dir=None, allow_fixture: bool = False) -> Acceptance:
    """Accept a ledger only through the genuine approval chain. Never raises on bad data; fails closed.

    ``decision_register`` and ``evidence_manifest`` are the paths of the decision register and the canonical evidence manifest;
    the signed registry must bind the SHA-256 of each. ``evidence_dir`` is the directory whose files are the HELD evidence
    (without it no approved decision can be verified, so a ledger that relies on one is rejected). ``metadatas`` is
    the index metadata the approval is checked against (as the server passes it). There is no date parameter (see the
    module docstring). ``allow_fixture`` must be exactly True to accept a synthetic ledger or a synthetic register
    (``"fixture": true``), which only tests do; the result is then flagged ``fixture``."""
    try:
        return _accept(ledger_path, registry_path, approval_path, trusted_keys, decision_register, evidence_manifest,
                       metadatas, corpus_dir, evidence_dir, allow_fixture)
    except Exception as exc:  # noqa: BLE001 - any surprise is a rejection, never an acceptance
        return _reject(f"ledger rejected: unexpected {exc.__class__.__name__}")


def _accept(ledger_path, registry_path, approval_path, trusted_keys, decision_register, evidence_manifest_path, metadatas,
            corpus_dir, evidence_dir, allow_fixture) -> Acceptance:
    paths = {}
    for name, v in (("ledger_path", ledger_path), ("registry_path", registry_path), ("approval_path", approval_path),
                    ("trusted_keys", trusted_keys), ("decision_register", decision_register),
                    ("evidence_manifest", evidence_manifest_path)):
        paths[name] = _once(v)                                  # each path object is resolved here, once
        if paths[name] is None:
            return _reject(f"{name} must be a file path; objects are never trusted (including the unsigned test sentinel)")
    corpus = None
    if corpus_dir is not None:
        corpus = _once(corpus_dir)
        if corpus is None:
            return _reject("corpus_dir must be a directory path")
    evidence = None
    if evidence_dir is not None:
        evidence = _once(evidence_dir)
        if evidence is None:
            return _reject("evidence_dir must be a directory path")
    if not isinstance(metadatas, (list, tuple)):
        return _reject("index metadata is required")
    metas = list(metadatas)
    today = _today()                                            # one trusted reading of the clock for the whole call
    if not isinstance(today, dt.date) or isinstance(today, dt.datetime):
        return _reject("trusted current date is unavailable")

    # 1. The signed approval record, verified by the existing mechanism.
    approval = legal_approval.evaluate(paths["approval_path"], metas, today, paths["trusted_keys"], corpus)
    if not isinstance(approval, legal_approval.ApprovalStatus) or approval.state != "valid" or approval.record is None:
        return _reject("approval is not valid", *[str(e) for e in getattr(approval, "errors", [])][:5])

    # 2. The registry file is read once; the verified record must bind exactly these bytes, and these bytes are parsed.
    try:
        registry_raw = evidence_manifest.read_regular_file(paths["registry_path"], MAX_REGISTRY_BYTES)
    except (OSError, ValueError) as exc:
        return _reject(f"cannot read the source-status registry: {exc.__class__.__name__}")
    registry_digest = hashlib.sha256(registry_raw).hexdigest()
    problems = legal_approval.source_status_errors(approval.record, registry_digest)
    if problems:
        return _reject("source-status registry is not the one the approval record binds", *problems)
    registry = source_status.load_bytes(registry_raw, metas, corpus_dir=corpus, today=today)
    if not isinstance(registry, source_status.Registry) or registry.state != "valid":
        return _reject("source-status registry is not valid", *[str(e) for e in getattr(registry, "errors", [])][:5])
    if registry.sha256 != registry_digest:
        return _reject("source-status registry is not the one the approval record binds")

    # 3. The ledger bytes are read once; their hash must be the one the verified registry binds.
    try:
        raw = evidence_manifest.read_regular_file(paths["ledger_path"], MAX_LEDGER_BYTES)
    except (OSError, ValueError) as exc:
        return _reject(f"cannot read the ledger: {exc.__class__.__name__}")
    sha = hashlib.sha256(raw).hexdigest()
    problems = source_status.verify_ledger_binding(registry, sha)
    if problems:
        return _reject(*problems)

    # 4. The ledger loads (fixtures only with allow_fixture is True) and has no validation error of any kind.
    try:
        ledger = provision_validity.load_ledger(raw, allow_fixture=allow_fixture)
    except provision_validity.LedgerError as exc:
        return _reject(f"ledger rejected: {exc}")
    errors = sorted(f"{p.code} {p.subject}: {p.message}" for p in provision_validity.validate(ledger)
                    if p.severity == "error")
    if errors:
        return _reject(*errors)

    # 5. The decision register is read once; the signed registry must bind exactly these bytes, and these bytes are parsed.
    try:
        register_raw = evidence_manifest.read_regular_file(paths["decision_register"], MAX_REGISTER_BYTES)
    except (OSError, ValueError) as exc:
        return _reject(f"cannot read the decision register: {exc.__class__.__name__}")
    register_sha = hashlib.sha256(register_raw).hexdigest()
    problems = source_status.verify_register_binding(registry, register_sha)
    if problems:
        return _reject(*problems)
    try:
        register = json.loads(register_raw.decode("utf-8"), object_pairs_hook=_no_duplicate_keys)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        return _reject(f"decision register is not valid JSON ({exc.__class__.__name__})")
    synthetic_register = validity_decisions.register_is_fixture(register)
    if synthetic_register and allow_fixture is not True:
        return _reject("decision register is a synthetic fixture and is refused")

    # 6. The evidence manifest is read once; the signed registry must bind exactly these bytes, and they must be canonical.
    try:
        manifest_raw = evidence_manifest.read_regular_file(paths["evidence_manifest"], evidence_manifest.MAX_MANIFEST_BYTES)
    except (OSError, ValueError) as exc:
        return _reject(f"cannot read the evidence manifest: {exc.__class__.__name__}")
    manifest_sha = hashlib.sha256(manifest_raw).hexdigest()
    problems = source_status.verify_manifest_binding(registry, manifest_sha)
    if problems:
        return _reject(*problems)
    try:
        manifest = evidence_manifest.parse(manifest_raw)
    except evidence_manifest.ManifestError as exc:
        return _reject(f"evidence manifest rejected: {exc}")

    # Every jurisdiction in the chain must agree: a register or manifest made for another jurisdiction is not accepted.
    want = approval.record.jurisdiction
    got = {"source-status registry": source_status.JURISDICTION,
           "decision register": register.get("jurisdiction") if isinstance(register, dict) else None,
           "evidence manifest": manifest.jurisdiction}
    wrong = [f"{who} jurisdiction {j!r} differs from the approval record's {want!r}" for who, j in got.items() if j != want]
    if wrong:
        return _reject(*wrong)

    # 7. The decision records are compared with the ledger; evidence must be held exactly as the manifest lists it.
    evidence_problems, held = [], None
    if evidence is not None:
        cited = validity_decisions.cited_files(ledger, register)
        evidence_problems, held = evidence_manifest.verify_files(manifest, evidence, cited)
    found = [p for p in validity_decisions.check_decisions(ledger, register, corpus_files=held, today=today)
             if p.severity == "error"]
    if found or evidence_problems:
        return _reject(*(sorted(f"{p.code} {p.subject}: {p.message}" for p in found)
                         + [f"E1 evidence: {m}" for m in evidence_problems]))
    return Acceptance(ledger, (), ledger.fixture or synthetic_register, registry.sha256, sha, register_sha, manifest_sha)


def _no_duplicate_keys(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError(f"duplicate JSON key {k!r}")
        out[k] = v
    return out
