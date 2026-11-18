"""Runtime wrapper for the provision-level validity layer (Step 4): the thin, fail-closed link between the server and
``ledger_acceptance`` / ``provision_validity``.

What it does
------------
* ``TG_PROVISION_VALIDITY`` selects the mode: unset / ``off`` (default: nothing is read, behaviour is exactly as before),
  ``shadow`` (the acceptance gate runs and chunk verdicts are logged, nothing is filtered) or ``restrict``.
  Any other value, including ``enforce`` (which stays locked), is a MISCONFIGURATION and behaves like ``restrict`` with no
  accepted ledger: nothing is served. A typo never switches the layer off.
* In ``restrict`` the signed-ledger acceptance gate (``ledger_acceptance.accept_ledger``) must pass BEFORE any chunk of the
  legal corpus is served. Until it has passed (not configured, rejected, stale, unbound from the server's own approval and
  registry), ``serving_errors()`` is non-empty and ``filter`` returns nothing.
* ``filter`` can only REMOVE chunks the existing retrieval already allowed. A chunk is kept only when the accepted ledger covers
  it exactly (same file hash, text hash and position), covers it as a single provision interval, and says it is in force for
  the question (current law: authoritative; dated question: authoritative or historical). Pending, unapproved, unverified,
  expired, not-yet-commenced, partially covered, stale-coverage and uncovered chunks are removed. The ledger never creates
  authority (``provision_validity`` invariant I3 is untouched): ``Verdict.opinion`` is used only to keep, never to serve.
* ``citation_errors`` checks that every cited passage maps to one approved document and one provision of the stored chunk.

Not here (deferred, recorded as known limitations): replay / freshness protection of the signed set, reviewer authentication,
and the coverage tooling that would produce a real ledger. No real ledger, register or manifest exists, so a ``restrict``
deployment currently refuses to serve (fail closed).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from backend import ledger_acceptance, provision_validity as pv

__all__ = ["ENV_MODE", "Inputs", "ValidityRuntime", "citation_errors", "parse_mode", "from_env"]

ENV_MODE = "TG_PROVISION_VALIDITY"
ENV_LEDGER = "TG_VALIDITY_LEDGER_FILE"
ENV_REGISTER = "TG_VALIDITY_DECISION_REGISTER_FILE"
ENV_MANIFEST = "TG_VALIDITY_EVIDENCE_MANIFEST_FILE"
ENV_EVIDENCE = "TG_VALIDITY_EVIDENCE_DIR"
MODES = ("off", "shadow", "restrict")
MAX_LOGGED = 20
_SHA_RE = re.compile(r"[0-9a-f]{64}")
log = logging.getLogger(__name__)


def parse_mode(raw) -> tuple:
    """(mode, problem). Unset or empty is off. An unknown value (``enforce`` included) is ``restrict`` plus a problem, so the
    layer is never switched off by a typo."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return "off", None
    value = raw.strip().lower() if isinstance(raw, str) else None
    if value in MODES:
        return value, None
    shown = value if value in ("enforce",) else "an unrecognised value"
    return "restrict", f"{ENV_MODE} is {shown}; only off, shadow and restrict exist (enforce is locked): nothing is served"


@dataclass(frozen=True)
class Inputs:
    """Where the signed chain lives. Paths only; nothing is opened until ``ValidityRuntime.load``."""
    ledger: Optional[Path] = None
    decision_register: Optional[Path] = None
    evidence_manifest: Optional[Path] = None
    evidence_dir: Optional[Path] = None
    registry: Optional[Path] = None
    approval: Optional[Path] = None
    trusted_keys: Optional[Path] = None
    corpus_dir: Optional[Path] = None

    def missing(self) -> list:
        names = {"ledger": ENV_LEDGER, "decision_register": ENV_REGISTER, "evidence_manifest": ENV_MANIFEST,
                 "evidence_dir": ENV_EVIDENCE, "registry": "TG_SOURCE_STATUS_FILE", "approval": "TG_APPROVAL_FILE",
                 "trusted_keys": "TG_TRUSTED_KEYS_FILE"}
        return [env for attr, env in names.items() if getattr(self, attr) is None]


def _ymd(d: dt.date) -> int:
    return d.year * 10000 + d.month * 100 + d.day


def _digest(path) -> Optional[str]:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest() if path is not None else None
    except OSError:
        return None


class ValidityRuntime:
    """Never raises from ``load`` / ``filter`` / ``status``. All state is in this object; nothing is written anywhere."""

    def __init__(self, mode: str = "off", inputs: Optional[Inputs] = None, *, mode_problem: Optional[str] = None,
                 clock: Callable[[], dt.date] = dt.date.today, accept: Callable = ledger_acceptance.accept_ledger):
        self.mode = mode if mode in MODES else "restrict"
        self.inputs = inputs or Inputs()
        self._clock, self._accept = clock, accept
        self._bad_mode = bool(mode_problem)
        self.state = "off" if self.mode == "off" else ("misconfigured" if self._bad_mode else "not_loaded")
        self.problems: list = [mode_problem] if mode_problem else []
        self._ledger = None
        self._acceptance = None
        self._demoted = 0

    # ---- state ---------------------------------------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    @property
    def accepted(self) -> bool:
        return self.state == "accepted" and self._ledger is not None

    def invalidate(self, why: str = "validity inputs changed since the last acceptance; revalidation required") -> None:
        """Called when an input changed. Only ``load`` can accept again; this never re-approves."""
        if self.enabled and not self._bad_mode:
            self._ledger, self._acceptance = None, None
            self.state, self.problems = "stale", [why]

    def load(self, metadatas, *, registry_sha256: Optional[str], approval_valid: bool) -> "ValidityRuntime":
        """Run the acceptance gate once. ``registry_sha256`` is the registry the SERVER uses and ``approval_valid`` says the
        server's own approval record is valid and binds it; the gate's chain must be bound to that same registry."""
        if not self.enabled:
            return self
        self._ledger, self._acceptance = None, None
        if self._bad_mode:
            self.state = "misconfigured"
            return self
        absent = self.inputs.missing()
        if absent:
            self.state, self.problems = "misconfigured", [f"not configured: {', '.join(absent)}"]
            return self
        if not approval_valid or not isinstance(registry_sha256, str) or not _SHA_RE.fullmatch(registry_sha256):
            self.state, self.problems = "rejected", ["the server's own approval is not valid or does not bind the registry in use"]
            return self
        try:
            i = self.inputs
            acc = self._accept(i.ledger, registry_path=i.registry, approval_path=i.approval, trusted_keys=i.trusted_keys,
                               decision_register=i.decision_register, evidence_manifest=i.evidence_manifest,
                               metadatas=list(metadatas or []), corpus_dir=i.corpus_dir, evidence_dir=i.evidence_dir)
        except Exception as exc:  # noqa: BLE001 - the gate does not raise, but nothing here may turn a surprise into serving
            self.state, self.problems = "rejected", [f"acceptance failed unexpectedly ({exc.__class__.__name__})"]
            return self
        if not getattr(acc, "ok", False) or getattr(acc, "ledger", None) is None:
            self.state = "rejected"
            self.problems = [str(p)[:300] for p in (getattr(acc, "problems", ()) or ("not accepted",))][:5]
            return self
        if getattr(acc, "fixture", False):
            self.state, self.problems = "rejected", ["a synthetic (fixture) ledger or register is never served"]
            return self
        if acc.registry_sha256 != registry_sha256:
            self.state, self.problems = "rejected", ["the accepted chain is bound to a different registry than the one in use"]
            return self
        self._ledger, self._acceptance, self.state, self.problems = acc.ledger, acc, "accepted", []
        return self

    def fingerprint(self):
        """Cheap change detector for the chain's small files (hashes, never paths). None while the layer is off."""
        if not self.enabled:
            return None
        i = self.inputs
        return tuple(_digest(p) for p in (i.ledger, i.decision_register, i.evidence_manifest))

    def digest(self) -> Optional[str]:
        """What the answer cache must be keyed on. None while off (so existing cache epochs do not change)."""
        if not self.enabled:
            return None
        a = self._acceptance
        return hashlib.sha256("|".join(str(x) for x in (
            self.mode, self.state, getattr(a, "registry_sha256", None), getattr(a, "ledger_sha256", None),
            getattr(a, "register_sha256", None), getattr(a, "manifest_sha256", None))).encode()).hexdigest()

    # ---- serving -------------------------------------------------------------------------------------------------

    def serving_errors(self) -> list:
        """Blocks serving in ``restrict`` until the signed chain has been accepted. Empty when off or shadow."""
        if self.mode != "restrict" or self.accepted:
            return []
        why = "; ".join(self.problems[:2]) if self.problems else self.state
        return [f"provision validity is {self.state}: no legal chunk may be served ({why[:300]})"]

    def verdict(self, doc, offence_date=None) -> tuple:
        """(keep, reasons) for one chunk. Fails closed on anything unexpected."""
        if not self.accepted:
            return False, ("ledger_not_accepted",)
        try:
            md = getattr(doc, "metadata", None)
            text = getattr(doc, "page_content", None)
            qd = _ymd(offence_date) if offence_date is not None else None
            v = pv.resolve_chunk(self._ledger, md, text, qd, _ymd(self._clock()), "restrict", bound=True)
        except Exception:  # noqa: BLE001
            return False, ("verdict_error",)
        allowed = (pv.AUTHORITATIVE,) if offence_date is None else (pv.AUTHORITATIVE, pv.HISTORICAL)
        if not v.covered:
            return False, tuple(v.reasons) or ("no_coverage",)
        if v.partial:
            return False, tuple(v.reasons) + ("partial",)
        if v.opinion not in allowed:
            return False, tuple(v.reasons) or (str(v.opinion),)
        return True, ()

    def filter(self, docs, offence_date=None) -> list:
        """The chunks that may be served. Off: unchanged. Shadow: unchanged, differences logged. Restrict: removes only."""
        docs = list(docs or [])
        if not self.enabled:
            return docs
        if self.mode == "shadow":
            if self.accepted:
                self._log_differences(docs, offence_date)
            return docs
        if not self.accepted:
            self._demoted += len(docs)
            return []
        kept = []
        for d in docs:
            keep, reasons = self.verdict(d, offence_date)
            if keep:
                kept.append(d)
            else:
                self._demoted += 1
        return kept

    def _log_differences(self, docs, offence_date) -> None:
        shown = 0
        for d in docs:
            keep, reasons = self.verdict(d, offence_date)
            if not keep and shown < MAX_LOGGED:
                shown += 1
                m = getattr(d, "metadata", None) or {}
                log.info("validity-shadow: would remove %s %s reasons=%s", str(m.get("manifest_id"))[:60],
                         str(m.get("provision_id"))[:60], ",".join(reasons)[:120])

    def status(self) -> dict:
        """Safe to show: no file paths and no file contents."""
        a = self._acceptance
        return {"mode": self.mode, "state": self.state, "accepted": self.accepted,
                "ledger_sha256": getattr(a, "ledger_sha256", None), "chunks_removed": self._demoted,
                "problems": [str(p)[:200] for p in self.problems[:3]]}


def from_env(env, *, approval_file, trusted_keys, source_status_file, corpus_dir, **kw) -> ValidityRuntime:
    """Build the runtime from environment-style settings. Nothing is opened here."""
    mode, problem = parse_mode(env.get(ENV_MODE))

    def path(name):
        v = env.get(name)
        return Path(v) if isinstance(v, str) and v.strip() else None

    inputs = Inputs(ledger=path(ENV_LEDGER), decision_register=path(ENV_REGISTER), evidence_manifest=path(ENV_MANIFEST),
                    evidence_dir=path(ENV_EVIDENCE), registry=source_status_file, approval=approval_file,
                    trusted_keys=trusted_keys, corpus_dir=corpus_dir)
    return ValidityRuntime(mode, inputs, mode_problem=problem, **kw)


# ------------------------------------------------------------------------------------------------ citation mapping

def citation_errors(cited, cited_docs, approved) -> list:
    """Problems that stop a citation from mapping to exactly one approved source document and one provision of the stored
    chunk. ``cited`` are the validated Evidence items (in citation order), ``cited_docs`` the stored chunks they came from,
    ``approved`` maps an approved file SHA-256 to ``(title, instrument)``. Empty means every citation maps."""
    from backend import grounded_answer
    errors = []
    cited, cited_docs = list(cited or []), list(cited_docs or [])
    if len(cited) != len(cited_docs):
        return ["the number of citations differs from the number of cited passages"]
    for n, (e, d) in enumerate(zip(cited, cited_docs), 1):
        m = getattr(d, "metadata", None) or {}
        h = m.get("sha256")
        if not isinstance(h, str) or not _SHA_RE.fullmatch(h):
            errors.append(f"[{n}] the cited passage has no valid source-file hash")
        elif h not in approved:
            errors.append(f"[{n}] the cited passage's document is not an approved source")
        elif getattr(e, "sha256", None) != h:
            errors.append(f"[{n}] the citation's document hash is not the cited passage's")
        pid = m.get("provision_id")
        if not isinstance(pid, str) or not pid.strip():
            errors.append(f"[{n}] the cited passage has no provision")
        elif getattr(e, "provision_id", None) != pid:
            errors.append(f"[{n}] the citation names a different provision than the cited passage")
        if not isinstance(m.get("manifest_id"), str) or not m.get("manifest_id").strip():
            errors.append(f"[{n}] the cited passage has no manifest identity")
        if getattr(e, "chunk_id", None) != grounded_answer.chunk_id_of(m):
            errors.append(f"[{n}] the citation is not for the cited passage")
    return errors
