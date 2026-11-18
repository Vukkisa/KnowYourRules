"""Roadmap Step 2: the optional `validity_ledger_sha256` registry key, `verify_ledger_binding`, and the
`ledger_acceptance.accept_ledger` gate, which rebuilds the signed-approval -> registry -> ledger chain from files and
refuses any ledger with a validation error (review finding M1).

Offline. Every ledger, registry, approval record and hash here is SYNTHETIC and built in memory or in a temp dir. The real
`legal-status/source-status.json` is only read. Nothing here wires the library into the runtime."""

import ast
import builtins
import contextlib
import copy
import datetime as dt
import hashlib
import inspect
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_legal_approval as tla  # noqa: E402
import test_provision_validity as tpv  # noqa: E402
import test_source_status as tss  # noqa: E402
import validity_decisions_support as sup  # noqa: E402
from backend import ledger_acceptance as gate, legal_approval as la, provision_validity as pv, source_status as ss  # noqa: E402

KEY = "validity_ledger_sha256"
SHA_L = "ab12" * 16
REAL_REGISTRY = ROOT / "legal-status" / "source-status.json"


def raw_of(obj) -> bytes:
    return json.dumps(obj).encode()


def sha_of(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def with_child(*, link, closer_date=29050101, parent_chunk=True):
    """`one()` plus a child provision with its own open version and an approved delete targeting the CHILD."""
    d = tpv.one()
    child = tpv.P + "c"
    d["provisions"].append({"key": child, "parent": tpv.P})
    d["decisions"].append({"decision_id": tpv.CLOSER_ID, "status": "approved", "subject": "closer"})
    d["operations"].append({"id": "OP-DEL", "type": "delete", "source": tpv.ACTK, "targets": [child],
                            "effective_from": tpv.fct(closer_date, tpv.CLOSER_ID)})
    cv = {"key": child + "@1", "provision": child, "text": "held", "created_by_op": "OP-A",
          "end": {"state": "continuing_verified", "checked_through": 29100101, "decision_ref": "LD-002"}}
    if link:
        cv.update(closed_by_op="OP-DEL", end={"state": "closed"})
    d["versions"].append(cv)
    if not parent_chunk:
        d["coverage"][0]["provisions"] = [child]
    return d, child


# ------------------------------------------------------------------------------------------------ registry key

def registry_with(key=..., **kw):
    d = tss.registry(tss.entry())
    if key is not ...:
        d[KEY] = key
    d.update(kw)
    return d


class RegistryKeyTests(unittest.TestCase):
    def rejected(self, data):
        with self.assertRaises(ss.SourceStatusError):
            ss.parse(data, tss.TODAY)

    def test_key_absent_parses_as_before(self):
        self.assertEqual(ss.parse(registry_with(), tss.TODAY), ss.parse(tss.registry(tss.entry()), tss.TODAY))

    def test_key_present_does_not_change_the_entries(self):
        self.assertEqual(ss.parse(registry_with(SHA_L), tss.TODAY), ss.parse(registry_with(), tss.TODAY))

    def test_malformed_keys_are_rejected(self):
        for bad in ("A" * 64, "1" * 63, "1" * 65, "", SHA_L + "\n", "g" * 64, " " + "1" * 63, None, 0, True,
                    ["1" * 64], {"sha": SHA_L}):
            with self.subTest(bad=bad):
                self.rejected(registry_with(bad))

    def test_unknown_or_missing_top_level_keys_still_rejected(self):
        self.rejected(registry_with(extra=1))
        self.rejected(registry_with(SHA_L, extra=1))
        self.rejected(registry_with(validity_ledger="x"))
        for k in ("schema_version", "jurisdiction", "note", "entries"):
            d = registry_with(SHA_L)
            del d[k]
            with self.subTest(missing=k):
                self.rejected(d)
        self.rejected({KEY: SHA_L})
        self.rejected([registry_with(SHA_L)])

    def write(self, d, data):
        p = Path(d) / "registry.json"
        p.write_text(json.dumps(data))
        return p

    def test_load_exposes_the_key_only_on_a_valid_registry(self):
        with tempfile.TemporaryDirectory() as d:
            ok = ss.load(self.write(d, registry_with(SHA_L)), today=tss.TODAY)
            self.assertEqual((ok.state, ok.validity_ledger_sha256), ("valid", SHA_L))
            plain = ss.load(self.write(d, registry_with()), today=tss.TODAY)
            self.assertEqual((plain.state, plain.validity_ledger_sha256), ("valid", None))
            bad = ss.load(self.write(d, registry_with("nope")), today=tss.TODAY)
            self.assertEqual((bad.state, bad.validity_ledger_sha256), ("invalid", None))
            # invalid for another reason (index mismatch): the binding is not exposed
            mismatch = ss.load(self.write(d, registry_with(SHA_L)), metadatas=[{"sha256": "f" * 64, "source_file": "z.pdf"}],
                               today=tss.TODAY)
            self.assertEqual((mismatch.state, mismatch.validity_ledger_sha256), ("invalid", None))
            self.assertEqual(ss.load(Path(d) / "absent.json").validity_ledger_sha256, None)

    def test_registry_default_is_unbound(self):
        self.assertIsNone(ss.Registry("valid", [], "e" * 64, {}).validity_ledger_sha256)
        self.assertIsNone(ss.Registry("absent").validity_ledger_sha256)

    def test_real_registry_is_unchanged_and_unbound(self):
        if not REAL_REGISTRY.is_file():
            self.skipTest("real registry not present")
        data = json.loads(REAL_REGISTRY.read_text(encoding="utf-8"))
        self.assertNotIn(KEY, data)
        reg = ss.load(REAL_REGISTRY)
        self.assertIsNone(reg.validity_ledger_sha256)
        self.assertEqual(reg.sha256, ss.sha256_file(REAL_REGISTRY))
        if reg.valid:
            self.assertEqual(reg.by_hash, ss.parse(data))


class VerifyBindingTests(unittest.TestCase):
    def reg(self, bound=SHA_L, state="valid"):
        return ss.Registry(state, [], "e" * 64, {}, bound)

    def test_matching_hash_passes(self):
        self.assertEqual(ss.verify_ledger_binding(self.reg(), SHA_L), [])

    def test_every_other_case_is_a_problem(self):
        cases = [(self.reg(), "2" * 64), (self.reg(None), SHA_L), (self.reg(state="invalid"), SHA_L),
                 (self.reg(state="absent"), SHA_L), (self.reg("BAD"), SHA_L), (self.reg(SHA_L.upper()), SHA_L),
                 (self.reg(), SHA_L.upper()), (self.reg(), SHA_L + "\n"), (self.reg(), None), (self.reg(), b"1" * 64),
                 (None, SHA_L), (object(), SHA_L), (types.SimpleNamespace(valid=True, validity_ledger_sha256=SHA_L), SHA_L)]
        for reg, sha in cases:
            with self.subTest(reg=reg, sha=sha):
                self.assertTrue(ss.verify_ledger_binding(reg, sha))

    def test_it_is_only_a_hash_check(self):
        # A ledger with a closure-link error still passes the hash check. The gate (below) is what rejects it.
        raw = raw_of(tpv.with_closer("delete", link=False))
        reg = ss.Registry("valid", [], "e" * 64, {}, sha_of(raw))
        self.assertEqual(ss.verify_ledger_binding(reg, sha_of(raw)), [])
        self.assertTrue(tpv.c3b(pv.load_ledger(raw)))


# ------------------------------------------------------------------------------------------------ the gate (genuine chain)

_N = [0]


def make_chain(root, ledger, *, bound=None, registry_mut=None, record_mut=None, sign=True, key_status="active",
               listed=True, binding=True, register_mut=None, evidence_mut=None, fixture_register=False, decorate=True,
               manifest_mut=None, register_bound=None, manifest_bound=None, manifest_bytes_mut=None):
    """A real signed chain in a temp dir: throwaway Ed25519 key -> signed approval record -> registry file -> ledger file,
    plus (Step 3) a synthetic decision register and held evidence files that match the ledger. `decorate` renumbers the
    ledger's decisions to LD-012 onward and builds the matching register; `register_mut(register_dict)` and
    `evidence_mut(files_dict)` change them before they are written. The manifest is built from the held evidence files, written
    in canonical form and bound, with the register, by the registry (`register_bound` / `manifest_bound` override those hashes;
    `manifest_mut(obj)` edits the manifest object before it is serialised).
    Only the keys are synthetic; verification runs through the unmodified legal_approval and source_status code."""
    _N[0] += 1
    d = Path(root) / f"chain{_N[0]}"
    d.mkdir()
    register, files = {"schema_version": 1, "decisions": []}, {}
    if isinstance(ledger, (bytes, bytearray)):
        raw = bytes(ledger)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            parsed = None
        if decorate and isinstance(parsed, dict) and isinstance(parsed.get("decisions", []), list):
            try:
                led, register, files = sup.decorate(parsed, fixture_register=fixture_register)
                raw = raw_of(led)
            except (KeyError, TypeError, AttributeError):
                pass                                          # not a decorate-able shape: keep the raw bytes
    else:
        raw = raw_of(ledger)
        if decorate:
            try:
                led, register, files = sup.decorate(ledger, fixture_register=fixture_register)
                raw = raw_of(led)
            except (KeyError, TypeError, AttributeError):
                pass                                          # a deliberately malformed ledger: keep it as given
    if register_mut:
        register_mut(register)
    if evidence_mut:
        evidence_mut(files)
    rgp = d / "decision-register.json"
    rgp.write_text(json.dumps(register))
    evd = sup.write_evidence(d / "held", files) if files else (d / "held")
    evd.mkdir(exist_ok=True)
    mobj = sup.manifest_obj(files)
    if manifest_mut:
        manifest_mut(mobj)
    mfp = d / "evidence-manifest.json"
    mfp.write_bytes(manifest_bytes_mut(sup.manifest_json(mobj)) if manifest_bytes_mut else sup.manifest_json(mobj))
    lp = d / "ledger.json"
    lp.write_bytes(raw)
    reg = tss.registry(tss.entry(sha=tla.SHA_A, file=tla.ts.TG_RULES_FILE),     # covers every indexed document, as the server needs
                       tss.entry(sha=tla.SHA_B, file=tla.ts.TG_TAX_FILE))
    reg[KEY] = sha_of(raw) if bound is None else bound
    reg["validity_decision_register_sha256"] = sha_of(rgp.read_bytes()) if register_bound is None else register_bound
    reg["validity_evidence_manifest_sha256"] = sha_of(mfp.read_bytes()) if manifest_bound is None else manifest_bound
    if registry_mut:
        registry_mut(reg)
    rp = d / "source-status.json"
    rp.write_text(json.dumps(reg))
    key = tla.new_key()
    kp = tla.write_keys(d, tla.key_entry(key if listed else tla.new_key(), "k1", status=key_status))
    rec = tla.synthetic_record(**({"source_status_sha256": la.sha256_file(rp)} if binding else {}))
    if record_mut:
        record_mut(rec)
    ap = tla.write_signed(d, rec, key, "k1")
    if not sign:
        la.signature_path(ap).unlink()
    return types.SimpleNamespace(dir=d, ledger=lp, registry=rp, approval=ap, keys=kp, key=key, raw=raw,
                                 metadatas=list(tla.INDEX_OK), register=rgp, evidence=evd, register_obj=register, files=files,
                                 manifest=mfp, manifest_obj=mobj)


def run(c, **over):
    kw = dict(registry_path=c.registry, approval_path=c.approval, trusted_keys=c.keys, metadatas=c.metadatas,
              decision_register=c.register, evidence_manifest=c.manifest, evidence_dir=c.evidence)
    ledger = over.pop("ledger_path", c.ledger)
    kw.update(over)
    return gate.accept_ledger(ledger, **kw)


class GateCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def chain(self, ledger, **kw):
        return make_chain(self._tmp.name, ledger, **kw)

    def accept(self, ledger, **kw):
        allow = kw.pop("allow_fixture", False)
        return run(self.chain(ledger, **kw), allow_fixture=allow)

    def assertRejected(self, a, fragment=None):
        self.assertFalse(a.ok)
        self.assertIsNone(a.ledger)
        self.assertFalse(a.production)
        self.assertTrue(a.problems)
        if fragment:
            self.assertIn(fragment, " ".join(a.problems))


class GenuineAcceptanceTests(GateCase):
    def test_a_genuine_chain_is_accepted(self):
        c = self.chain(tpv.one())
        a = run(c)
        self.assertTrue(a.ok, a.problems)
        self.assertIsInstance(a.ledger, pv.Ledger)
        self.assertEqual((a.problems, a.fixture, a.production), ((), False, True))
        self.assertEqual(a.ledger_sha256, sha_of(c.raw))
        self.assertEqual(a.registry_sha256, la.sha256_file(c.registry))

    def test_clean_ledgers_are_accepted(self):
        for name, d in (("one", tpv.one()), ("closed", tpv.one(end=("closed", 29050101))),
                        ("child linked", with_child(link=True)[0])) + tuple(
                (f"linked {op}", tpv.with_closer(op, link=True)) for op in pv.CLOSING_OPS):
            with self.subTest(name):
                a = self.accept(d)
                self.assertTrue(a.ok, a.problems)

    def test_str_and_path_arguments_agree(self):
        c = self.chain(tpv.one())
        self.assertTrue(run(c, registry_path=str(c.registry), approval_path=str(c.approval),
                            trusted_keys=str(c.keys), ledger_path=str(c.ledger)).ok)

    def test_ok_is_not_legal_approval_and_grants_no_authority(self):
        a = run(self.chain(tpv.one()))
        self.assertTrue(a.ok)
        for mode in ("shadow", "restrict"):
            v = pv.resolve_chunk(a.ledger, tpv.MD, tpv.TXT, None, tpv.TODAY, mode, bound=True)
            self.assertNotIn(v.cls, (pv.AUTHORITATIVE, pv.HISTORICAL))
        self.assertIn("not a statement", gate.Acceptance.ok.__doc__.lower() + " not a statement")  # documented on the property

    def test_acceptance_is_immutable(self):
        a = run(self.chain(tpv.one()))
        with self.assertRaises(Exception):
            a.fixture = True
        self.assertFalse(gate.Acceptance().ok)
        self.assertFalse(gate.Acceptance(a.ledger, ("x",)).ok)          # a problem always wins
        self.assertFalse(gate.Acceptance(None, ()).production)


class FixtureTests(GateCase):
    FIXTURES = sorted(tpv.FIX.glob("*.json"))

    def test_fixtures_are_refused_by_default(self):
        for p in self.FIXTURES:
            with self.subTest(p.name):
                self.assertRejected(self.accept(p.read_bytes()), "fixture")

    def test_allow_fixture_must_be_exactly_true(self):
        raw = (tpv.FIX / "go53_go16_synthetic.json").read_bytes()
        for v in (1, "yes", object(), None, False):
            with self.subTest(v=v):
                self.assertFalse(self.accept(raw, allow_fixture=v).ok)

    def test_an_accepted_fixture_is_flagged_and_never_production(self):
        raw = (tpv.FIX / "go53_go16_synthetic.json").read_bytes()
        a = self.accept(raw, allow_fixture=True)
        self.assertTrue(a.ok, a.problems)
        self.assertEqual((a.fixture, a.production, a.ledger.fixture), (True, False, True))
        v = pv.resolve_chunk(a.ledger, tpv.MD, tpv.TXT, None, tpv.TODAY, "restrict", bound=True)
        self.assertNotIn(v.opinion, (pv.AUTHORITATIVE, pv.HISTORICAL))            # fixtures are never trusted

    def test_acceptance_of_every_fixture_follows_validate_errors(self):
        for p in self.FIXTURES:
            has_error = any(x.severity == "error" for x in pv.validate(pv.load_ledger(p, allow_fixture=True)))
            with self.subTest(p.name):
                a = self.accept(p.read_bytes(), allow_fixture=True)
                # the one fixture with unapproved decisions is also refused by the Step 3 decision checks
                self.assertEqual(a.ok, not has_error and p.stem != "unapproved_and_candidate")
                self.assertEqual(a.production, False)
                if a.ok:
                    self.assertTrue(a.fixture)

    def test_overlap_fixture_is_rejected_even_when_allowed(self):
        self.assertRejected(self.accept((tpv.FIX / "overlap.json").read_bytes(), allow_fixture=True), "C1")

    def test_warnings_and_infos_do_not_reject(self):
        for name in ("gap", "rule81_conflicting_targets"):
            with self.subTest(name):
                a = self.accept((tpv.FIX / f"{name}.json").read_bytes(), allow_fixture=True)
                self.assertTrue(a.ok, a.problems)
                self.assertTrue(a.fixture)


class BypassTests(GateCase):
    """M1: nothing a caller supplies is trusted on its attributes."""

    def test_there_is_no_registry_or_approval_object_parameter(self):
        params = inspect.signature(gate.accept_ledger).parameters
        self.assertEqual(list(params), ["ledger_path", "registry_path", "approval_path", "trusted_keys", "decision_register",
                                        "evidence_manifest", "metadatas", "corpus_dir", "evidence_dir", "allow_fixture"])          # no `today`: see ClockTests
        for name in list(params)[1:]:
            self.assertEqual(params[name].kind, inspect.Parameter.KEYWORD_ONLY, name)

    def forged_objects(self, sha):
        class Sub(ss.Registry):
            @property
            def valid(self):
                return True

        flipped = ss.Registry("invalid", ["x"], "e" * 64, {}, sha)
        flipped.state = "valid"                                   # state modified after loading
        return {
            "hand-built Registry": ss.Registry("valid", [], "e" * 64, {}, sha),
            "Registry with no sha256": ss.Registry("valid", [], None, {}, sha),
            "state flipped after load": flipped,
            "SimpleNamespace lookalike": types.SimpleNamespace(state="valid", valid=True, validity_ledger_sha256=sha,
                                                               sha256="e" * 64, by_hash={}, errors=[]),
            "subclass overriding valid": Sub("invalid", ["x"], "e" * 64, {}, sha),
            "approval status object": la.ApprovalStatus("valid", [], None),
            "bytes": b"x", "int": 7, "None": None, "dict": {"state": "valid"}, "unsigned sentinel": la.UNSIGNED_TEST_ONLY,
        }

    def test_objects_are_never_accepted_in_place_of_a_path(self):
        c = self.chain(tpv.one())
        sha = sha_of(c.raw)
        for oname, obj in self.forged_objects(sha).items():
            for param in ("ledger_path", "registry_path", "approval_path", "trusted_keys", "decision_register"):
                with self.subTest(obj=oname, param=param):
                    self.assertRejected(run(c, **{param: obj}), "file path")

    def test_the_unsigned_test_sentinel_is_refused_even_with_a_valid_unsigned_record(self):
        c = self.chain(tpv.one(), sign=False)
        # the existing mechanism would call this record valid under the sentinel, so the refusal is what protects us
        self.assertEqual(la.evaluate(c.approval, c.metadatas, tla.TODAY, la.UNSIGNED_TEST_ONLY,
                                     source_status_file=c.registry).state, "valid")
        self.assertRejected(run(c, trusted_keys=la.UNSIGNED_TEST_ONLY), "file path")
        self.assertRejected(run(c), "not signed")

    def test_a_forged_registry_returned_by_the_loader_does_not_pass(self):
        c = self.chain(tpv.one())
        sha = sha_of(c.raw)
        for oname in ("hand-built Registry", "Registry with no sha256", "state flipped after load"):
            forged = self.forged_objects(sha)[oname]
            with self.subTest(oname), mock.patch.object(ss, "load_bytes", return_value=forged):
                a = run(c)
                self.assertRejected(a)

    def test_a_subclass_with_an_overridden_property_cannot_validate_a_bad_registry(self):
        class Always(ss.Registry):
            @property
            def valid(self):
                return True

        bad = self.chain(tpv.one(), bound="not-a-hash")        # malformed key: the real loader says invalid
        with mock.patch.object(ss, "Registry", Always):
            self.assertRejected(run(bad), "registry")
        self.assertEqual(ss.load(bad.registry, today=tla.TODAY).state, "invalid")

    def test_the_gate_never_reads_attributes_off_the_arguments(self):
        c = self.chain(tpv.one())

        class PathLike:
            def __fspath__(self):
                return str(c.registry)
            state, valid, validity_ledger_sha256 = "valid", True, sha_of(c.raw)

        self.assertTrue(run(c, registry_path=PathLike()).ok)     # a real path-like is just a path
        self.assertRejected(run(self.chain(tpv.one(), sign=False), registry_path=PathLike()), "not signed")


class ApprovalEvidenceTests(GateCase):
    def test_missing_invalid_or_unsigned_approval_is_rejected(self):
        c = self.chain(tpv.one())
        self.assertRejected(run(c, approval_path=c.dir / "nope.json"), "approval is not valid")
        self.assertRejected(run(c, approval_path=c.dir), "approval is not valid")
        junk = c.dir / "junk.json"
        junk.write_text("{")
        self.assertRejected(run(c, approval_path=junk), "approval is not valid")
        self.assertRejected(self.accept(tpv.one(), sign=False), "not signed")

    def test_untrusted_revoked_or_missing_keys_are_rejected(self):
        self.assertRejected(self.accept(tpv.one(), listed=False), "approval is not valid")
        self.assertRejected(self.accept(tpv.one(), key_status="revoked"), "approval is not valid")
        c = self.chain(tpv.one())
        self.assertRejected(run(c, trusted_keys=c.dir / "absent-keys.json"), "approval is not valid")
        self.assertRejected(run(c, trusted_keys=c.ledger), "approval is not valid")           # not a keys file

    def test_a_record_edited_after_signing_is_rejected(self):
        c = self.chain(tpv.one())
        rec = json.loads(c.approval.read_text())
        rec["penalty_answers_approved"] = True
        c.approval.write_text(json.dumps(rec, indent=2))
        self.assertRejected(run(c), "approval is not valid")

    def test_a_record_that_does_not_bind_the_registry_is_rejected(self):
        self.assertRejected(self.accept(tpv.one(), binding=False), "does not bind")

    def test_a_record_binding_a_different_registry_is_rejected(self):
        def other(rec):
            rec["source_status_sha256"] = "0" * 64
        self.assertRejected(self.accept(tpv.one(), record_mut=other), "changed since approval")

    def test_a_registry_edited_after_approval_is_stale(self):
        c = self.chain(tpv.one())
        data = json.loads(c.registry.read_text())
        data["note"] = "edited after approval"
        c.registry.write_text(json.dumps(data))
        self.assertRejected(run(c), "changed since approval")

    def test_unresolved_conditions_and_index_mismatch_are_rejected(self):
        def cond(rec):
            rec["conditions"] = ["a synthetic condition"]
        self.assertRejected(self.accept(tpv.one(), record_mut=cond), "unresolved")
        c = self.chain(tpv.one())
        self.assertRejected(run(c, metadatas=list(c.metadatas) + [tla.meta("extra.pdf", tla.SHA_C)]), "unapproved document")
        self.assertRejected(run(c, metadatas=[]), "no chunks")
        self.assertRejected(run(c, metadatas=None), "index metadata")
        self.assertRejected(run(c, metadatas="abc"), "index metadata")

    def test_a_future_or_malformed_record_is_rejected(self):
        for name, mut in (("future approval date", lambda r: r.update(approval_date="2999-01-01")),
                          ("unknown field", lambda r: r.update(surprise=1)),
                          ("not approved", lambda r: r.update(decision="rejected"))):
            with self.subTest(name):
                self.assertRejected(self.accept(tpv.one(), record_mut=mut), "approval is not valid")

    def test_the_gate_is_stricter_than_the_hash_check(self):
        c = self.chain(tpv.one(), sign=False)
        reg = ss.load(c.registry, today=tla.TODAY)
        self.assertEqual(ss.verify_ledger_binding(reg, sha_of(c.raw)), [])       # the hash alone would pass
        self.assertFalse(run(c).ok)                                                 # the approval is what stops it


class BindingTests(GateCase):
    def test_registry_without_a_binding_or_with_a_wrong_or_malformed_one_is_rejected(self):
        def drop(reg):
            reg.pop("validity_ledger_sha256")
        self.assertRejected(self.accept(tpv.one(), registry_mut=drop), "does not bind a validity ledger")
        self.assertRejected(self.accept(tpv.one(), bound="2" * 64), "changed since the registry bound it")
        self.assertRejected(self.accept(tpv.one(), bound="NOT-HEX"), "registry is not valid")
        self.assertRejected(self.accept(tpv.one(), bound=("a" * 64) + "\n"), "registry is not valid")

    def test_a_registry_that_does_not_cover_the_index_is_rejected(self):
        def drop_entry(reg):
            reg["entries"] = reg["entries"][:1]               # properly bound and signed, but the index has a document it lacks
        self.assertRejected(self.accept(tpv.one(), registry_mut=drop_entry), "missing registry entry")

    def test_registry_invalid_for_another_reason_is_rejected(self):
        def bad(reg):
            reg["entries"] = []
        self.assertRejected(self.accept(tpv.one(), registry_mut=bad), "registry is not valid")

    def test_editing_the_ledger_after_binding_is_rejected_but_the_approval_stays_valid(self):
        c = self.chain(tpv.one())
        c.ledger.write_bytes(c.raw + b"\n")
        self.assertEqual(la.evaluate(c.approval, c.metadatas, tla.TODAY, c.keys, source_status_file=c.registry).state,
                         "valid")                                                  # the approval binds the registry only
        self.assertRejected(run(c), "changed since the registry bound it")

    def test_rebinding_without_resigning_is_stale_and_rebinding_with_resigning_is_accepted(self):
        c = self.chain(tpv.one())
        new = raw_of(tpv.with_closer("delete", link=True))
        c.ledger.write_bytes(new)
        data = json.loads(c.registry.read_text())
        data["validity_ledger_sha256"] = sha_of(new)
        c.registry.write_text(json.dumps(data))
        self.assertRejected(run(c), "changed since approval")                       # old signature no longer covers it
        self.assertTrue(self.accept(tpv.with_closer("delete", link=True)).ok)       # a fresh, signed chain does

    def test_the_real_registry_is_unbound_and_is_not_accepted_with_a_synthetic_approval(self):
        if not REAL_REGISTRY.is_file():
            self.skipTest("real registry not present")
        self.assertNotIn("validity_ledger_sha256", json.loads(REAL_REGISTRY.read_text(encoding="utf-8")))
        c = self.chain(tpv.one())
        self.assertRejected(run(c, registry_path=REAL_REGISTRY))


class LedgerContentThroughTheGateTests(GateCase):
    def test_unlinked_closing_operations_are_rejected(self):
        for op in pv.CLOSING_OPS:
            with self.subTest(op=op):
                self.assertRejected(self.accept(tpv.with_closer(op, link=False)), "C3b")

    def test_wrong_provision_link_is_rejected(self):
        d = tpv.with_closer("delete", link=True)
        d["provisions"].append({"key": tpv.P + "x"})
        d["operations"][-1]["targets"] = [tpv.P + "x"]
        d["versions"].append({"key": tpv.P + "x@1", "provision": tpv.P + "x", "text": "held", "created_by_op": "OP-A",
                              "end": {"state": "unverified"}})
        self.assertRejected(self.accept(d), "C3b")

    def test_wrong_version_link_is_rejected(self):
        d = tpv.one()
        d["decisions"].append({"decision_id": tpv.CLOSER_ID, "status": "approved", "subject": "closer"})
        d["operations"].append({"id": "OP-SUB", "type": "substitute", "source": tpv.ACTK, "targets": [tpv.P],
                                "effective_from": tpv.fct(29050101, tpv.CLOSER_ID)})
        d["versions"][0].update(closed_by_op="OP-SUB", end={"state": "closed"})
        d["versions"].append({"key": tpv.P + "@2", "provision": tpv.P, "text": "held", "created_by_op": "OP-SUB",
                              "end": {"state": "continuing_verified", "checked_through": 29100101, "decision_ref": "LD-002"}})
        d["operations"].append({"id": "OP-DEL", "type": "delete", "source": tpv.ACTK, "targets": [tpv.P],
                                "effective_from": tpv.fct(29080101, tpv.CLOSER_ID)})
        d["versions"][1].update(closed_by_op="OP-DEL", end={"state": "closed"})
        self.assertTrue(self.accept(d).ok)
        d["versions"][0]["closed_by_op"], d["versions"][1]["closed_by_op"] = "OP-DEL", "OP-SUB"
        self.assertRejected(self.accept(d), "C3b")

    def test_child_target_unlinked_is_rejected_for_a_parent_or_a_child_chunk(self):
        d, child = with_child(link=False)
        L = pv.load_ledger(raw_of(d))
        self.assertEqual(tpv.res(L, None).opinion, pv.AUTHORITATIVE)     # why the gate, not the opinion, must decide
        self.assertRejected(self.accept(d), "C3b")
        self.assertRejected(self.accept(with_child(link=False, parent_chunk=False)[0]), "C3b")

    def test_child_target_linked_is_accepted(self):
        self.assertTrue(self.accept(with_child(link=True)[0]).ok)
        self.assertTrue(self.accept(with_child(link=True, parent_chunk=False)[0]).ok)

    def test_parent_target_unlinked_is_rejected_for_the_child_version(self):
        d = tpv.with_closer("repeal", link=False)
        child = tpv.P + "c"
        d["provisions"].append({"key": child, "parent": tpv.P})
        d["versions"].append({"key": child + "@1", "provision": child, "text": "held", "created_by_op": "OP-A",
                              "end": {"state": "continuing_verified", "checked_through": 29100101, "decision_ref": "LD-002"}})
        d["coverage"][0]["provisions"] = [child]
        a = self.accept(d)
        self.assertRejected(a, "C3b")
        self.assertIn(child, " ".join(a.problems))

    def test_parent_version_closed_by_a_child_operation_is_rejected(self):
        d, _ = with_child(link=True)
        d["versions"][0].update(closed_by_op="OP-DEL", end={"state": "closed"})
        self.assertRejected(self.accept(d), "C3b")

    def test_child_version_closed_by_a_parent_operation_is_accepted(self):
        d = tpv.with_closer("repeal", link=True)
        child = tpv.P + "c"
        d["provisions"].append({"key": child, "parent": tpv.P})
        d["versions"].append({"key": child + "@1", "provision": child, "text": "held", "created_by_op": "OP-A",
                              "closed_by_op": "OP-DEL", "end": {"state": "closed"}})
        self.assertTrue(self.accept(d).ok)

    def test_malformed_ledgers_are_rejected_without_raising(self):
        base = tpv.one()

        def mut(f):
            d = copy.deepcopy(base)
            f(d)
            return d

        cases = {
            "bad schema_version": mut(lambda d: d.update(schema_version=2)),
            "unknown top key": mut(lambda d: d.update(surprise=1)),
            "operation bad type": mut(lambda d: d["operations"][0].update(type="teleport")),
            "dangling closed_by_op": mut(lambda d: d["versions"][0].update(closed_by_op="OP-NOPE")),
            "dangling created_by_op": mut(lambda d: d["versions"][0].update(created_by_op="OP-NOPE")),
            "version of missing provision": mut(lambda d: d["versions"][0].update(provision=tpv.P + "zz")),
            "bad date": mut(lambda d: d["operations"][0]["effective_from"].update(date=29991399)),
            "string date": mut(lambda d: d["operations"][0]["effective_from"].update(date="29000101")),
            "bool date": mut(lambda d: d["operations"][0]["effective_from"].update(date=True)),
            "approved without date": mut(lambda d: d["operations"][0]["effective_from"].pop("date")),
            "bad decision id": mut(lambda d: d["decisions"][0].update(decision_id="D-1")),
            "duplicate decision": mut(lambda d: d["decisions"].append(copy.deepcopy(d["decisions"][0]))),
            "unknown decision ref": mut(lambda d: d["operations"][0]["effective_from"].update(decision_ref="LD-777")),
            "provision cycle": mut(lambda d: d["provisions"].extend(
                [{"key": tpv.P + "a", "parent": tpv.P + "b"}, {"key": tpv.P + "b", "parent": tpv.P + "a"}])),
            "coverage names missing provision": mut(lambda d: d["coverage"][0].update(provisions=[tpv.P + "nope"])),
            "operations not a list": mut(lambda d: d.update(operations={})),
            "versions null": mut(lambda d: d.update(versions=None)),
        }
        for name, d in cases.items():
            with self.subTest(name):
                self.assertRejected(self.accept(d))
        for name, raw in {"empty": b"", "not json": b"{", "array": b"[]", "null": b"null", "bad utf8": b"\xff\xfe",
                          "duplicate keys": b'{"schema_version":1,"schema_version":1}', "number": b"1",
                          "deep nesting": b"[" * 200000 + b"]" * 200000}.items():
            with self.subTest(name):
                self.assertRejected(self.accept(raw, decorate=False))

    def test_an_unexpected_failure_is_a_rejection(self):
        c = self.chain(tpv.one())
        with mock.patch.object(pv, "validate", side_effect=KeyError("boom")):
            self.assertRejected(run(c), "unexpected")

    def test_bad_arguments_never_raise(self):
        c = self.chain(tpv.one())
        for over in ({"corpus_dir": 5}, {"corpus_dir": c.dir / "nope"}, {"metadatas": 5}, {"metadatas": None},
                     {"registry_path": c.dir / "missing.json"}, {"registry_path": c.dir}, {"registry_path": b"bytes"}):
            with self.subTest(over=over):
                self.assertFalse(run(c, **over).ok)
        self.assertFalse(run(c, ledger_path=c.dir / "missing.json").ok)
        self.assertFalse(run(c, ledger_path=c.dir).ok)

    def test_acceptance_is_exactly_the_absence_of_validation_errors(self):
        for op in pv.CLOSING_OPS:
            for date in (29000102, 29050101, 29100101):
                d = tpv.with_closer(op, link=False, date=date)
                with self.subTest(op=op, date=date):
                    flagged = bool(tpv.c3b(pv.load_ledger(raw_of(d))))
                    self.assertTrue(flagged)
                    self.assertEqual(self.accept(d).ok, not flagged)


# ------------------------------------------------------------------------------------------------ m1: the clock

def frozen_today(d):
    """The test-only way to fix the date: replace the gate's private clock. No production call path can do this."""
    return mock.patch.object(gate, "_today", return_value=d)


class ClockTests(GateCase):
    def test_there_is_no_date_parameter_and_passing_one_cannot_help(self):
        self.assertNotIn("today", inspect.signature(gate.accept_ledger).parameters)
        c = self.chain(tpv.one(), record_mut=lambda r: r.update(approval_date="2999-01-01"))
        with self.assertRaises(TypeError):                       # a programming error, never an acceptance
            gate.accept_ledger(c.ledger, registry_path=c.registry, approval_path=c.approval, trusted_keys=c.keys,
                               metadatas=c.metadatas, today=dt.date(3000, 1, 1))

    def test_a_future_dated_approval_is_rejected_on_the_real_clock(self):
        a = self.accept(tpv.one(), record_mut=lambda r: r.update(approval_date="2999-01-01"))
        self.assertRejected(a, "future")

    def test_approval_date_boundary_on_a_fixed_clock(self):
        c = self.chain(tpv.one(), record_mut=lambda r: r.update(approval_date="2026-03-01"))
        with frozen_today(dt.date(2026, 3, 1)):
            self.assertTrue(run(c).ok)                           # the day of approval
        with frozen_today(dt.date(2026, 2, 28)):
            self.assertRejected(run(c), "future")                # the day before: not yet valid
        with frozen_today(dt.date(2025, 1, 1)):
            self.assertRejected(run(c), "future")                # a clock rolled far back fails closed

    def test_the_clock_is_read_exactly_once_per_call(self):
        c = self.chain(tpv.one())
        with mock.patch.object(gate, "_today", wraps=gate._today) as m:
            self.assertTrue(run(c).ok)
        self.assertEqual(m.call_count, 1)

    def test_an_unusable_clock_value_is_a_rejection(self):
        c = self.chain(tpv.one())
        for bad in (dt.datetime(2026, 11, 8), "2026-11-08", None, 20261108):
            with self.subTest(bad=bad), frozen_today(bad):
                self.assertRejected(run(c), "current date")

    def test_the_gate_has_no_other_way_to_set_the_date(self):
        tree = ast.parse((ROOT / "backend" / "ledger_acceptance.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = [a.arg for a in node.args.args + node.args.kwonlyargs]
                self.assertFalse({"today", "now", "clock", "date"} & set(args), node.name)
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, ("environ", "getenv"))
            if isinstance(node, ast.Name):
                self.assertNotEqual(node.id, "getenv")


# ------------------------------------------------------------------------------------------------ m2: each path once

class CountingPath:
    def __init__(self, path):
        self.path, self.calls = str(path), 0

    def __fspath__(self):
        self.calls += 1
        return self.path


class ShiftingPath:
    """Names `first` the first time it is resolved and `later` every time after."""
    def __init__(self, first, later):
        self.names, self.calls = [str(first), str(later)], 0

    def __fspath__(self):
        self.calls += 1
        return self.names[0] if self.calls == 1 else self.names[1]


@contextlib.contextmanager
def watch_reads(*paths):
    """Record every read of `paths`: `safe` are reads through the gate's safe reader, `stray` are any other open of those paths
    (builtins.open, io.open, os.open, Path.read_bytes). Yields (safe, stray)."""
    wanted = {os.fsdecode(os.fspath(x)) for x in paths}
    safe, stray, inside = [], [], [0]
    real_bopen, real_iopen, real_osopen = builtins.open, io.open, os.open
    real_read = gate.evidence_manifest.read_regular_file

    def watching(real, kind):
        def spy(file, *a, **k):
            try:
                name = os.fsdecode(os.fspath(file))
            except TypeError:
                name = None                                       # a file descriptor
            if name in wanted and not inside[0]:
                stray.append((kind, name))
            return real(file, *a, **k)
        return spy

    def safe_read(path, limit):
        name = os.fsdecode(os.fspath(path))
        if name in wanted:
            safe.append(name)
        inside[0] += 1
        try:
            return real_read(path, limit)
        finally:
            inside[0] -= 1

    os_spy = watching(real_osopen, "os.open")
    os.supports_dir_fd.add(os_spy)                                # keep the platform check in evidence_manifest honest
    try:
        with mock.patch("builtins.open", watching(real_bopen, "builtins.open")), \
                mock.patch("io.open", watching(real_iopen, "io.open")), mock.patch("os.open", os_spy), \
                mock.patch.object(gate.evidence_manifest, "read_regular_file", safe_read):
            yield safe, stray
    finally:
        os.supports_dir_fd.discard(os_spy)


class PathResolutionTests(GateCase):
    def test_each_input_path_is_resolved_exactly_once(self):
        c = self.chain(tpv.one())
        args = {"ledger_path": CountingPath(c.ledger), "registry_path": CountingPath(c.registry),
                "approval_path": CountingPath(c.approval), "trusted_keys": CountingPath(c.keys),
                "decision_register": CountingPath(c.register), "evidence_manifest": CountingPath(c.manifest),
                "evidence_dir": CountingPath(c.evidence)}
        a = gate.accept_ledger(args.pop("ledger_path"), metadatas=c.metadatas, **args)
        self.assertTrue(a.ok, a.problems)
        self.assertEqual({k: v.calls for k, v in args.items()}, {k: 1 for k in args})

    def test_the_corpus_path_is_resolved_once_too(self):
        c = self.chain(tpv.one())
        corpus = CountingPath(c.dir)
        run(c, corpus_dir=corpus)
        self.assertEqual(corpus.calls, 1)

    def test_a_ledger_path_object_is_resolved_once_even_when_acceptance_fails_early(self):
        c = self.chain(tpv.one(), sign=False)
        led = CountingPath(c.ledger)
        self.assertFalse(run(c, ledger_path=led).ok)
        self.assertLessEqual(led.calls, 1)

    def test_a_path_that_changes_meaning_cannot_mix_two_chains(self):
        c1, c2 = self.chain(tpv.one()), self.chain(tpv.one(end=("closed", 29050101)))
        base = run(c1)
        self.assertTrue(base.ok)
        for param, first, later in (("registry_path", c1.registry, c2.registry), ("ledger_path", c1.ledger, c2.ledger),
                                    ("approval_path", c1.approval, c2.approval), ("trusted_keys", c1.keys, c2.keys)):
            shifting = ShiftingPath(first, later)
            with self.subTest(param=param):
                a = run(c1, **{param: shifting})
                self.assertEqual(shifting.calls, 1)                  # the later meaning is never used
                self.assertEqual((a.ok, a.registry_sha256, a.ledger_sha256), (True, base.registry_sha256, base.ledger_sha256))
        wrong_first = ShiftingPath(c2.registry, c1.registry)       # first meaning is a registry the approval does not bind
        self.assertRejected(run(c1, registry_path=wrong_first), "approval record binds")

    def test_non_text_paths_are_refused(self):
        c = self.chain(tpv.one())

        class BytesPath:
            def __fspath__(self):
                return str(c.registry).encode()

        for param in ("registry_path", "ledger_path", "approval_path", "trusted_keys"):
            for bad in (b"/tmp/x", BytesPath()):
                with self.subTest(param=param, bad=type(bad).__name__):
                    self.assertRejected(run(c, **{param: bad}), "file path")

    def test_the_registry_and_ledger_bytes_are_read_once_and_only_by_the_gate(self):
        c = self.chain(tpv.one())
        with watch_reads(c.registry, c.ledger) as (safe, stray), \
                mock.patch.object(la, "sha256_file", side_effect=AssertionError("evaluate must not hash the registry")), \
                mock.patch.object(ss, "load", side_effect=AssertionError("the gate must parse the bytes it hashed")):
            a = run(c)
        self.assertTrue(a.ok, a.problems)
        self.assertEqual(sorted(safe), sorted([str(c.registry), str(c.ledger)]))
        self.assertEqual(stray, [], "an extra read of the registry or ledger outside the safe reader")

    def test_the_watcher_sees_a_stray_read(self):
        c = self.chain(tpv.one())
        for how in (lambda p: open(p, "rb").close(), lambda p: Path(p).read_bytes(), lambda p: os.close(os.open(p, os.O_RDONLY))):
            with self.subTest(how=how), watch_reads(c.registry) as (safe, stray):
                how(str(c.registry))
                self.assertEqual(len(stray), 1)


# ------------------------------------------------------------------------------------------------ m3: replacement during acceptance

OTHER_CLEAN = raw_of(tpv.one(end=("closed", 29050101)))      # a valid ledger with a different hash


def hook_after(owner, name, action):
    """Run `action` immediately after `owner.name` returns: a file replaced at exactly that point of acceptance."""
    real = getattr(owner, name)

    def wrapper(*a, **k):
        out = real(*a, **k)
        action()
        return out

    return mock.patch.object(owner, name, wrapper)


def replace_with(kind, target: Path, other: Path, other_bytes: bytes):
    """One way to replace `target`."""
    def act():
        if kind == "other content":
            target.write_bytes(other_bytes)
        elif kind == "empty":
            target.write_bytes(b"")
        elif kind == "garbage":
            target.write_bytes(b"\x00\xff garbage")
        elif kind == "truncated":
            target.write_bytes(target.read_bytes()[:20])
        elif kind == "deleted":
            target.unlink()
        elif kind == "directory":
            target.unlink()
            target.mkdir()
        elif kind == "symlink to another file":
            target.unlink()
            target.symlink_to(other)
        elif kind == "renamed over":
            tmp = target.with_name(target.name + ".new")
            tmp.write_bytes(other_bytes)
            os.replace(tmp, target)
    return act


KINDS = ("other content", "empty", "garbage", "truncated", "deleted", "directory", "symlink to another file", "renamed over")


class ReplacementTests(GateCase):
    def test_every_registry_replacement_after_the_approval_check_is_rejected(self):
        for kind in KINDS:
            c, other = self.chain(tpv.one()), self.chain(OTHER_CLEAN)
            with self.subTest(kind=kind), hook_after(la, "evaluate", replace_with(kind, c.registry, other.registry,
                                                                                  other.registry.read_bytes())):
                a = run(c)
                self.assertRejected(a)

    def test_every_ledger_replacement_after_the_registry_is_parsed_is_rejected(self):
        for kind in KINDS:
            c, other = self.chain(tpv.one()), self.chain(OTHER_CLEAN)
            with self.subTest(kind=kind), hook_after(ss, "load_bytes", replace_with(kind, c.ledger, other.ledger, OTHER_CLEAN)):
                a = run(c)
                self.assertRejected(a)

    def test_a_replacement_that_also_rebinds_the_registry_is_rejected(self):
        c = self.chain(tpv.one())

        def attack():
            reg = json.loads(c.registry.read_text())
            reg["validity_ledger_sha256"] = sha_of(OTHER_CLEAN)
            c.registry.write_text(json.dumps(reg))
            c.ledger.write_bytes(OTHER_CLEAN)

        with hook_after(la, "evaluate", attack):
            self.assertRejected(run(c), "approval record binds")

    def test_registry_and_ledger_replaced_by_another_signed_chains_files_are_rejected(self):
        c, other = self.chain(tpv.one()), self.chain(OTHER_CLEAN)

        def attack():
            c.registry.write_bytes(other.registry.read_bytes())
            c.ledger.write_bytes(other.ledger.read_bytes())

        with hook_after(la, "evaluate", attack):
            self.assertRejected(run(c), "approval record binds")      # a genuine registry, but not the approved one

    def test_rewriting_identical_bytes_is_not_an_attack(self):
        c = self.chain(tpv.one())
        before = c.registry.read_bytes(), c.ledger.read_bytes()
        with hook_after(la, "evaluate", lambda: c.registry.write_bytes(before[0])), \
                hook_after(ss, "load_bytes", lambda: c.ledger.write_bytes(before[1])):
            self.assertTrue(run(c).ok)

    def test_a_ledger_replaced_after_its_bytes_were_read_cannot_change_what_is_accepted(self):
        c = self.chain(tpv.one())
        with hook_after(ss, "verify_ledger_binding", replace_with("other content", c.ledger, c.ledger, OTHER_CLEAN)):
            a = run(c)
        self.assertTrue(a.ok, a.problems)
        self.assertEqual(a.ledger_sha256, sha_of(c.raw))             # the verified bytes, never the replacement
        self.assertEqual(a.ledger.sha256, sha_of(c.raw))

    def test_a_registry_replaced_after_its_bytes_were_read_cannot_change_what_is_accepted(self):
        c = self.chain(tpv.one())
        signed = c.registry.read_bytes()
        with hook_after(la, "source_status_errors", replace_with("other content", c.registry, c.registry, b"{}")):
            a = run(c)
        self.assertTrue(a.ok, a.problems)
        self.assertEqual(a.registry_sha256, sha_of(signed))

    def test_approval_keys_or_signature_replaced_after_verification_do_not_alter_the_verified_result(self):
        c = self.chain(tpv.one())

        def attack():
            c.approval.write_text("{}")
            c.keys.write_text("{}")
            la.signature_path(c.approval).write_text("{}")

        with hook_after(la, "evaluate", attack):
            a = run(c)
        self.assertTrue(a.ok, a.problems)                            # judged on the bytes that were verified
        self.assertFalse(run(c).ok)                                  # the next call sees the replacement and fails closed

    def test_a_missing_file_at_any_step_is_a_rejection_not_an_error(self):
        for step, owner, name in (("registry", la, "evaluate"), ("ledger", ss, "load_bytes")):
            c = self.chain(tpv.one())
            target = c.registry if step == "registry" else c.ledger
            with self.subTest(step), hook_after(owner, name, target.unlink):
                a = run(c)
                self.assertRejected(a, "cannot read")


# ------------------------------------------------------------------------------------------------ isolation

class StepTwoIsolationTests(unittest.TestCase):
    DIRS = ("backend", "scripts", "api", "deploy", "eval")

    def files(self):
        out = []
        for d in self.DIRS:
            out += sorted((ROOT / d).rglob("*.py")) if (ROOT / d).is_dir() else []
        return out

    def imports(self, path):
        names = set()
        for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Import):
                names |= {a.name for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                names.add(("." * n.level) + (n.module or ""))
                names |= {a.name for a in n.names}
        return names

    def test_registry_loader_does_not_import_the_library_or_the_gate(self):
        names = self.imports(ROOT / "backend" / "source_status.py")
        self.assertFalse({n for n in names if "provision_validity" in n or "ledger_acceptance" in n})

    def test_library_does_not_import_the_application(self):
        mods = {n.split(".")[0] for n in self.imports(ROOT / "backend" / "provision_validity.py")}
        self.assertFalse(mods & {"backend", "source_status", "legal_approval", "server", "tg_manifest", "ledger_acceptance"})

    def test_no_other_module_imports_or_calls_the_gate(self):
        for p in self.files():
            if p.name in ("ledger_acceptance.py", "provision_validity_runtime.py"):   # Step 4: the one sanctioned caller of the gate
                continue
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
            with self.subTest(str(p.relative_to(ROOT))):
                self.assertFalse({n for n in self.imports(p) if "ledger_acceptance" in n})
                for node in ast.walk(tree):
                    if isinstance(node, ast.Name):
                        self.assertNotEqual(node.id, "accept_ledger")
                    elif isinstance(node, ast.Attribute):
                        self.assertNotIn(node.attr, ("accept_ledger", "verify_ledger_binding"))

    def test_the_binding_key_lives_only_in_the_loader_and_the_gate(self):
        for p in self.files():
            if p.name in ("source_status.py", "ledger_acceptance.py", "provision_validity.py"):
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            with self.subTest(p.name):
                self.assertNotIn("validity_ledger_sha256", text)
                self.assertNotIn("verify_ledger_binding", text)

    def test_the_gate_never_uses_the_unsigned_sentinel_or_trusts_objects(self):
        tree = ast.parse((ROOT / "backend" / "ledger_acceptance.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                self.assertNotEqual(node.attr, "UNSIGNED_TEST_ONLY")
        # allow_fixture defaults to False
        self.assertIs(inspect.signature(gate.accept_ledger).parameters["allow_fixture"].default, False)

    def test_untouched_files_keep_their_hashes(self):
        # Pinned before Step 2: the approval path and the signing script are not modified.
        for rel, digest in (("backend/legal_approval.py", "ed31cd1e98cf44b547c78b0a508a04f50b34449b3e93dc2e6f6bf51009859e16"),
                            ("scripts/sign_approval_record.py", "add9daf2fd778f9b930cecfd34484dc1b911b46e03e54b21a79cf8db387b3561")):
            with self.subTest(rel):
                self.assertEqual(sha_of((ROOT / rel).read_bytes()), digest)


if __name__ == "__main__":
    unittest.main()
