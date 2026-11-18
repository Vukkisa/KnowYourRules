"""Roadmap Step 3: decision-record checks (`backend/validity_decisions.py`) and their use in the acceptance gate.

Offline. The decision register, reviewers, evidence files and hashes used here are SYNTHETIC (LD-012 onward, never an id of
the real Stage 22 register). The real register is only READ, and a test proves its bytes did not change. Nothing here
creates or implies a real legal decision or an advocate approval."""

import copy
import datetime as dt
import hashlib
import inspect
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_provision_validity as tpv  # noqa: E402
import test_source_status_ledger_binding as tb  # noqa: E402
import validity_decisions_support as sup  # noqa: E402
from backend import evidence_manifest as em, ledger_acceptance as gate, provision_validity as pv, validity_decisions as vd  # noqa: E402

REAL_SHA_BEFORE = "a853ccde67f8e929fb940ad713345a83511294a83f698e1031e80ffd0580206e"        # pinned: the real Stage 22 register
TODAY = dt.date(2026, 11, 8)


def tearDownModule():
    assert hashlib.sha256(sup.REAL_REGISTER.read_bytes()).hexdigest() == REAL_SHA_BEFORE, "the real register changed"


def base(**kw):
    """(ledger object, register, held-file table, ledger) for a synthetic ledger with a linked closer, LD-012 onward."""
    obj = tpv.with_closer("delete", link=True)
    led, reg, files = sup.decorate(obj, **kw)
    return led, reg, sup.held_table(files), pv.load_ledger(json.dumps(led).encode())


def check(ledger, register, held, **kw):
    return vd.check_decisions(ledger, register, corpus_files=held, today=kw.pop("today", TODAY), **kw)


def codes(problems):
    return sorted({p.code for p in problems})


def text(problems):
    return " | ".join(f"{p.code} {p.subject}: {p.message}" for p in problems)


class Base(unittest.TestCase):
    def setUp(self):
        self.led_obj, self.reg, self.held, self.ledger = base()
        self.start = "LD-012"                                  # the commencement decision of the synthetic ledger

    def rec(self, did=None):
        return sup.register_record(self.reg, did or self.start)

    def run_check(self, **kw):
        return check(self.ledger, self.reg, kw.pop("held", self.held), **kw)

    def assertClean(self, problems=None):
        problems = self.run_check() if problems is None else problems
        self.assertEqual(problems, [], text(problems))

    def assertRejects(self, code, fragment=None, problems=None):
        problems = self.run_check() if problems is None else problems
        self.assertIn(code, codes(problems), text(problems))
        if fragment:
            self.assertIn(fragment, text(problems))


# ------------------------------------------------------------------------------------------------ numbering and fixtures

class NumberingAndFixtureTests(Base):
    def test_the_synthetic_ledger_and_register_use_only_ids_from_lD_012(self):
        ids = {d["decision_id"] for d in self.reg["decisions"]}
        self.assertTrue(ids)
        for did in ids:
            self.assertGreaterEqual(int(did[3:]), vd.FIRST_VALIDITY_ID, did)
        real = {d["decision_id"] for d in sup.real_register()["decisions"]}
        self.assertEqual(sorted(real), [f"LD-{i:03d}" for i in range(1, 12)])
        self.assertFalse(ids & real)

    def test_renumber_moves_low_ids_up_and_keeps_high_ones(self):
        self.assertEqual(sup.renumber({"a": ["LD-001", "LD-011", "LD-050", "LD-901", "x", "LD-12"]}),
                         {"a": ["LD-012", "LD-022", "LD-061", "LD-901", "x", "LD-12"]})

    def test_the_static_fixtures_match_the_code_that_builds_them(self):
        ledger, register, files = sup.build_fixture_set(tpv.with_closer("delete", link=True))
        self.assertEqual((sup.FIX / "ledger.json").read_text(), sup.dump(ledger))
        self.assertEqual((sup.FIX / "register.json").read_text(), sup.dump(register))
        for rel, data in files.items():
            self.assertEqual((sup.FIX / rel).read_bytes(), data)

    def test_the_static_fixtures_are_flagged_synthetic_and_pass_every_check(self):
        led = pv.load_ledger(sup.FIX / "ledger.json", allow_fixture=True)
        reg = json.loads((sup.FIX / "register.json").read_text())
        self.assertTrue(led.fixture)
        self.assertTrue(vd.register_is_fixture(reg))
        held = {rel: sup.sha_of((sup.FIX / rel).read_bytes()) for rel in vd.cited_files(led, reg)}
        self.assertEqual(sorted(held), ["evidence/gazette-print.txt", "evidence/instrument-clause.txt"])
        self.assertEqual(check(led, reg, held), [])
        self.assertFalse([p for p in pv.validate(led) if p.severity == "error"])

    def test_the_fixture_ledger_cannot_load_without_the_test_keyword(self):
        with self.assertRaises(pv.LedgerError):
            pv.load_ledger(sup.FIX / "ledger.json")

    def test_a_clean_ledger_has_no_problems(self):
        self.assertClean()


# ------------------------------------------------------------------------------------------------ the real register (read only)

class RealRegisterTests(unittest.TestCase):
    def test_the_eleven_real_records_parse_and_none_is_approved(self):
        reg = sup.real_register()
        self.assertEqual(len(reg["decisions"]), 11)
        self.assertEqual({d["status"] for d in reg["decisions"]}, {"pending", "evidence_incomplete"})
        problems = []
        self.assertEqual(len(vd._index_register(reg, problems)), 11)
        self.assertEqual(problems, [])

    def test_the_register_file_is_unchanged_by_these_tests(self):
        self.assertEqual(hashlib.sha256(sup.REAL_REGISTER.read_bytes()).hexdigest(), REAL_SHA_BEFORE)

    def test_a_ledger_citing_real_records_cannot_carry_an_approved_fact(self):
        led_obj = tpv.with_closer("delete", link=True)                      # LD-001.. : the ids of the real records
        led = pv.load_ledger(json.dumps(led_obj).encode())
        problems = vd.check_decisions(led, sup.real_register(), corpus_files={}, today=TODAY)
        self.assertIn("D14", codes(problems))
        self.assertIn("D5", codes(problems))                               # subjects and status differ from the real records
        self.assertIn("not approved", text(problems))

    def test_every_real_decision_cited_by_an_approved_fact_is_refused(self):
        for did in [d["decision_id"] for d in sup.real_register()["decisions"]]:
            obj = tpv.one()
            for op in obj["operations"]:
                op["effective_from"]["decision_ref"] = did
            obj["decisions"] = [d for d in obj["decisions"]] + ([{"decision_id": did, "status": "approved", "subject": "x"}]
                                                                 if did not in {d["decision_id"] for d in obj["decisions"]} else [])
            for d in obj["decisions"]:
                if d["decision_id"] == did:
                    d["status"] = "approved"
            led = pv.load_ledger(json.dumps(obj).encode())
            with self.subTest(did):
                self.assertIn("D14", codes(vd.check_decisions(led, sup.real_register(), corpus_files={}, today=TODAY)))

    def test_no_helper_can_approve_a_real_record(self):
        for rec in sup.real_register()["decisions"]:
            with self.subTest(rec["decision_id"]):
                with self.assertRaises(vd.DecisionError):
                    vd.propose_status(rec, "approved")

    def test_the_gate_refuses_a_ledger_that_leans_on_the_real_register(self):
        with tempfile.TemporaryDirectory() as d:
            real_sha = hashlib.sha256(sup.REAL_REGISTER.read_bytes()).hexdigest()
            c = tb.make_chain(d, tpv.with_closer("delete", link=True), decorate=False, register_bound=real_sha)
            a = tb.run(c, decision_register=sup.REAL_REGISTER)
            self.assertFalse(a.ok)
            self.assertIn("D14", " ".join(a.problems))
            unbound = tb.run(tb.make_chain(d, tpv.with_closer("delete", link=True), decorate=False), decision_register=sup.REAL_REGISTER)
            self.assertIn("changed since the registry bound it", " ".join(unbound.problems))


# ------------------------------------------------------------------------------------------------ references

class ReferenceTests(Base):
    def test_a_missing_decision_is_rejected(self):
        self.reg["decisions"] = [r for r in self.reg["decisions"] if r["decision_id"] != self.start]
        self.assertRejects("D4", "not in the decision register")

    def test_every_referenced_decision_must_exist(self):
        for did in [r["decision_id"] for r in self.reg["decisions"]]:
            led, reg, held, ledger = base()
            reg["decisions"] = [r for r in reg["decisions"] if r["decision_id"] != did]
            with self.subTest(did):
                self.assertIn("D4", codes(check(ledger, reg, held)))

    def test_a_duplicate_id_in_the_register_is_rejected(self):
        self.reg["decisions"].append(copy.deepcopy(self.rec()))
        self.assertRejects("D3")
        self.assertIn("D4", codes(self.run_check()))                       # an ambiguous id is as good as missing

    def test_malformed_register_ids_are_rejected(self):
        for bad in ("LD-12", "ld-012", "LD-0120", "LD-012\n", "VD-012", "", None, 12, ["LD-012"]):
            reg = copy.deepcopy(self.reg)
            sup.register_record(reg, self.start)["decision_id"] = bad
            with self.subTest(bad=bad):
                self.assertIn("D2", codes(check(self.ledger, reg, self.held)))

    def test_a_malformed_register_is_rejected(self):
        for name, reg in {"not an object": [], "none": None, "no decisions": {"schema_version": 1},
                          "decisions not a list": {"schema_version": 1, "decisions": {}},
                          "bad schema": {"schema_version": 2, "decisions": []},
                          "bool schema": {"schema_version": True, "decisions": []},
                          "entry not an object": {"schema_version": 1, "decisions": ["LD-012"]}}.items():
            with self.subTest(name):
                self.assertIn("D1", codes(check(self.ledger, reg, self.held)))

    def test_an_unknown_status_in_the_register_is_rejected(self):
        for bad in ("approve", "APPROVED", None, 1, "verified"):
            reg = copy.deepcopy(self.reg)
            sup.register_record(reg, self.start)["status"] = bad
            with self.subTest(bad=bad):
                self.assertIn("D1", codes(check(self.ledger, reg, self.held)))

    def test_a_stale_ledger_copy_is_rejected(self):
        for field, value in (("status", "pending"), ("subject", "another matter"), ("prepared_by", "someone else")):
            reg = copy.deepcopy(self.reg)
            sup.register_record(reg, self.start)[field] = value
            with self.subTest(field):
                self.assertIn("D5", codes(check(self.ledger, reg, self.held)))
        reg = copy.deepcopy(self.reg)
        sup.register_record(reg, self.start)["reviewer"]["name"] = "a different reviewer"
        self.assertIn("D5", codes(check(self.ledger, reg, self.held)))

    def test_a_register_that_approved_more_than_the_ledger_claims_is_also_stale(self):
        led_obj = copy.deepcopy(self.led_obj)
        led_obj["decisions"][0]["status"] = "pending"
        ledger = pv.load_ledger(json.dumps(led_obj).encode())
        self.assertIn("D5", codes(check(ledger, self.reg, self.held)))

    def test_every_non_approved_status_is_refused_for_an_approved_fact(self):
        for st in ("pending", "evidence_incomplete", "evidence_complete", "rejected", "requires_further_review", "revoked"):
            reg = copy.deepcopy(self.reg)
            sup.register_record(reg, self.start)["status"] = st
            with self.subTest(st):
                problems = check(self.ledger, reg, self.held)
                self.assertIn("D14", codes(problems))
                self.assertIn("not approved", text(problems))
        reg = copy.deepcopy(self.reg)
        sup.register_record(reg, self.start)["status"] = "revoked"
        self.assertIn("revoked", text(check(self.ledger, reg, self.held)))

    def test_a_ledger_that_declares_approved_while_the_register_does_not_is_refused(self):
        reg = copy.deepcopy(self.reg)
        sup.register_record(reg, "LD-013")["status"] = "pending"          # the end decision: declared approved, never used by a fact
        problems = check(self.ledger, reg, self.held)
        self.assertIn("D14", codes(problems))
        self.assertIn("D5", codes(problems))

    def test_every_kind_of_reference_must_be_approved(self):
        # the interval rule, freshness window, continuing_verified end and coverage decisions each need approval
        for did in ("LD-014", "LD-015", "LD-016", "LD-017"):
            reg = copy.deepcopy(self.reg)
            sup.register_record(reg, did)["status"] = "pending"
            with self.subTest(did):
                self.assertIn("D14", codes(check(self.ledger, reg, self.held)))

    def test_a_non_approved_fact_citing_an_unapproved_decision_is_refused_too(self):
        obj = copy.deepcopy(self.led_obj)
        obj["operations"][1]["effective_from"] = {"state": "proposed", "kind": "commencement", "candidate": 29050101,
                                                   "decision_ref": "LD-017"}
        reg = copy.deepcopy(self.reg)
        sup.register_record(reg, "LD-017")["status"] = "pending"
        obj["decisions"][[d["decision_id"] for d in obj["decisions"]].index("LD-017")]["status"] = "pending"
        ledger = pv.load_ledger(json.dumps(obj).encode())
        self.assertIn("D14", codes(check(ledger, reg, self.held)))

    def test_replaced_decisions_cannot_be_cited(self):
        reg = copy.deepcopy(self.reg)
        new = sup.synthetic_record("LD-099", "approved", "successor", extra={"replaces": self.start})
        reg["decisions"].append(new)
        problems = check(self.ledger, reg, self.held)
        self.assertIn("D12", codes(problems))
        self.assertIn("D14", codes(problems))
        self.assertIn("superseded", text(problems))

    def test_replaces_must_be_well_formed_acyclic_and_point_at_a_record(self):
        for name, value, did in (("self", "LD-012", "LD-012"), ("missing", "LD-500", "LD-012"), ("malformed", "xyz", "LD-012"),
                                 ("not a string", 7, "LD-012")):
            reg = copy.deepcopy(self.reg)
            sup.register_record(reg, did)["replaces"] = value
            with self.subTest(name):
                self.assertIn("D12", codes(check(self.ledger, reg, self.held)))
        reg = copy.deepcopy(self.reg)
        sup.register_record(reg, "LD-012")["replaces"] = "LD-013"
        sup.register_record(reg, "LD-013")["replaces"] = "LD-012"
        self.assertIn("cycle", text(check(self.ledger, reg, self.held)))

    def test_a_ledger_that_reuses_a_real_id_for_another_subject_is_caught(self):
        reg = sup.real_register()
        led = copy.deepcopy(self.led_obj)
        led["decisions"][0]["decision_id"] = "LD-004"
        for op in led["operations"]:
            f = op.get("effective_from") or {}
            if f.get("decision_ref") == "LD-012":
                f["decision_ref"] = "LD-004"
        ledger = pv.load_ledger(json.dumps(led).encode())
        problems = vd.check_decisions(ledger, reg, corpus_files={}, today=TODAY)
        self.assertIn("different from", text(problems).replace("differs from", "different from"))
        self.assertIn("D14", codes(problems))


# ------------------------------------------------------------------------------------------------ approved records

class ApprovedRecordTests(Base):
    def mutate(self, f):
        reg = copy.deepcopy(self.reg)
        f(sup.register_record(reg, self.start))
        return check(self.ledger, reg, self.held)

    @staticmethod
    def on_day(r, day):
        """Move the review date and the approving history entry together (the checker requires them to agree)."""
        r.update(review_date=day)
        r["history"][-1]["date"] = day

    def test_a_null_reviewer_is_rejected(self):
        self.assertIn("D6", codes(self.mutate(lambda r: r.update(reviewer={"name": None, "designation": None, "organisation": None}))))
        self.assertIn("D6", codes(self.mutate(lambda r: r.update(reviewer=None))))
        self.assertIn("D6", codes(self.mutate(lambda r: r.pop("reviewer"))))

    def test_each_reviewer_field_is_required(self):
        for k in ("name", "designation", "organisation"):
            for bad in (None, "", "   ", 5):
                with self.subTest(k=k, bad=bad):
                    self.assertIn("D6", codes(self.mutate(lambda r: r["reviewer"].update({k: bad}))))
            with self.subTest(k=k, missing=True):
                self.assertIn("D6", codes(self.mutate(lambda r: r["reviewer"].pop(k))))

    def test_placeholder_reviewers_are_rejected(self):
        for bad in ("TBD", "to do: TODO", "Example Reviewer", "sample", "test", "N/A", "n/a", "____", "dummy", "xxx", "placeholder"):
            with self.subTest(bad=bad):
                self.assertIn("placeholder", text(self.mutate(lambda r: r["reviewer"].update(name=bad))))
        for k in ("designation", "organisation"):
            self.assertIn("placeholder", text(self.mutate(lambda r: r["reviewer"].update({k: "TBD"}))))

    def test_a_machine_or_assistant_reviewer_is_rejected(self):
        for bad in ("Claude", "AI assistant", "assistant (register created; no human decision)", "ChatGPT", "automated tooling",
                    "the bot", "LLM reviewer"):
            with self.subTest(bad=bad):
                self.assertIn("machine", text(self.mutate(lambda r: r["reviewer"].update(name=bad))))

    def test_self_approval_is_rejected(self):
        for variant in (sup.REVIEWER, sup.REVIEWER.upper(), f"  {sup.REVIEWER}  "):
            reg = copy.deepcopy(self.reg)
            r = sup.register_record(reg, self.start)
            r["prepared_by"] = variant
            led_obj = copy.deepcopy(self.led_obj)
            led_obj["decisions"][0]["prepared_by"] = variant
            ledger = pv.load_ledger(json.dumps(led_obj).encode())
            with self.subTest(variant):
                self.assertIn("self-approval", text(check(ledger, reg, self.held)))

    def test_a_missing_preparer_is_rejected(self):
        self.assertIn("prepared_by is missing", text(self.mutate(lambda r: r.update(prepared_by=None))) + text(
            self.mutate(lambda r: r.pop("prepared_by"))))

    def test_review_dates_must_be_real_and_not_in_the_future(self):
        for bad in ("2026-13-01", "01-02-2026", "2026-1-2", "2026-01-02T00:00:00", "", None, 20260102, "2999-01-01"):
            with self.subTest(bad=bad):
                self.assertIn("D6", codes(self.mutate(lambda r: r.update(review_date=bad))))
        self.assertIn("future", text(self.mutate(lambda r: self.on_day(r, "2026-11-09"))))
        self.assertEqual(self.mutate(lambda r: self.on_day(r, "2026-11-08")), [])      # today is allowed

    def test_the_clock_decides_what_is_the_future(self):
        reg = copy.deepcopy(self.reg)
        self.on_day(sup.register_record(reg, self.start), "2026-06-01")
        self.assertEqual(check(self.ledger, reg, self.held, today=dt.date(2026, 6, 1)), [])
        self.assertIn("future", text(check(self.ledger, reg, self.held, today=dt.date(2026, 5, 31))))

    def test_decision_and_rationale_are_required(self):
        for k in ("decision", "rationale"):
            for bad in (None, "", "   ", "TBD", "n/a", "____", 5):
                with self.subTest(k=k, bad=bad):
                    self.assertIn("D6", codes(self.mutate(lambda r: r.update({k: bad}))))
            with self.subTest(k=k, missing=True):
                self.assertIn("D6", codes(self.mutate(lambda r: r.pop(k))))

    def test_open_conditions_keep_a_decision_inactive(self):
        for bad in (["a condition"], None, "none", {}, [""]):
            with self.subTest(bad=bad):
                self.assertIn("D6", codes(self.mutate(lambda r: r.update(conditions=bad))))
        self.assertIn("D6", codes(self.mutate(lambda r: r.pop("conditions"))))

    def test_history_must_end_in_approved(self):
        for bad in (None, [], "x", [{"status": "pending"}], [None], [{"status": "approved"}, {"status": "revoked"}]):
            with self.subTest(bad=bad):
                self.assertIn("D6", codes(self.mutate(lambda r: r.update(history=bad))))
        self.assertIn("D6", codes(self.mutate(lambda r: r.pop("history"))))

    def test_an_incomplete_record_that_is_not_used_does_not_matter(self):
        reg = copy.deepcopy(self.reg)
        reg["decisions"].append(sup.synthetic_record("LD-300", "pending", "unused", reviewer="x"))
        reg["decisions"].append(sup.synthetic_record("LD-301", "approved", "unused", reviewer="TBD"))
        self.assertEqual(check(self.ledger, reg, self.held), [])


# ------------------------------------------------------------------------------------------------ evidence

class EvidenceTests(Base):
    def mutate(self, f, held=None):
        reg = copy.deepcopy(self.reg)
        f(sup.register_record(reg, self.start))
        return check(self.ledger, reg, self.held if held is None else held)

    def test_an_approved_decision_needs_supporting_sources(self):
        for bad in (None, [], "x", {}):
            with self.subTest(bad=bad):
                self.assertIn("D7", codes(self.mutate(lambda r: r.update(supporting_sources=bad))))
        self.assertIn("D7", codes(self.mutate(lambda r: r.pop("supporting_sources"))))

    def test_malformed_sources_are_rejected(self):
        good = {"file": sup.EV_FILE, "sha256": sup.EV_SHA}
        for name, src in {"not an object": "x", "no file": {"sha256": sup.EV_SHA}, "empty file": {"file": " ", "sha256": sup.EV_SHA},
                          "no hash": {"file": sup.EV_FILE}, "short hash": {"file": sup.EV_FILE, "sha256": "ab"},
                          "upper hash": {"file": sup.EV_FILE, "sha256": sup.EV_SHA.upper()},
                          "newline hash": {"file": sup.EV_FILE, "sha256": sup.EV_SHA + "\n"},
                          "non-hex hash": {"file": sup.EV_FILE, "sha256": "g" * 64},
                          "bad kind": dict(good, kind="rumour")}.items():
            with self.subTest(name):
                self.assertIn("D7", codes(self.mutate(lambda r: r.update(supporting_sources=[src]))))

    def test_one_file_cannot_carry_two_hashes(self):
        srcs = [{"file": sup.EV_FILE, "sha256": sup.EV_SHA}, {"file": sup.EV_FILE, "sha256": "a" * 64}]
        self.assertIn("two different hashes", text(self.mutate(lambda r: r.update(supporting_sources=srcs))))

    def test_a_cited_file_that_is_not_held_is_rejected(self):
        held = {k: v for k, v in self.held.items() if k != sup.EV_FILE}
        problems = self.run_check(held=held)
        self.assertIn("D8", codes(problems))
        self.assertIn("not a held file", text(problems))

    def test_a_wrong_hash_is_rejected(self):
        held = dict(self.held, **{sup.EV_FILE: "0" * 64})
        self.assertIn("does not match", text(self.run_check(held=held)))
        self.assertIn("D8", codes(self.mutate(lambda r: r["supporting_sources"][0].update(sha256="1" * 64))))

    def test_a_gazette_claim_without_a_file_is_rejected(self):
        src = {"file": sup.GAZ_FILE, "sha256": sup.GAZ_SHA, "kind": "gazette_print"}
        problems = self.mutate(lambda r: r["supporting_sources"].append(src), held={sup.EV_FILE: sup.EV_SHA})
        self.assertIn("D8", codes(problems))
        self.assertIn("Gazette", text(problems))

    def test_a_gazette_claim_with_a_wrong_hash_is_rejected(self):
        src = {"file": sup.GAZ_FILE, "sha256": sup.GAZ_SHA, "kind": "gazette_print"}
        held = {sup.EV_FILE: sup.EV_SHA, sup.GAZ_FILE: "f" * 64}
        self.assertIn("does not match", text(self.mutate(lambda r: r["supporting_sources"].append(src), held=held)))
        src2 = dict(src, sha256="e" * 64)
        held2 = {sup.EV_FILE: sup.EV_SHA, sup.GAZ_FILE: sup.GAZ_SHA}
        self.assertIn("does not match", text(self.mutate(lambda r: r["supporting_sources"].append(src2), held=held2)))

    def test_a_held_gazette_with_a_matching_hash_is_accepted(self):
        src = {"file": sup.GAZ_FILE, "sha256": sup.GAZ_SHA, "kind": "gazette_print"}
        held = {sup.EV_FILE: sup.EV_SHA, sup.GAZ_FILE: sup.GAZ_SHA}
        self.assertEqual(self.mutate(lambda r: r["supporting_sources"].append(src), held=held), [])

    def test_without_a_table_of_held_files_nothing_can_be_verified(self):
        problems = check(self.ledger, self.reg, None)
        self.assertIn("D8", codes(problems))
        self.assertIn("cannot be verified", text(problems))
        self.assertIn("D8", codes(check(self.ledger, self.reg, {})))

    def test_an_approved_fact_needs_evidence_that_its_decision_lists(self):
        for name, ev in {"none": [], "no locator": [{"file": sup.EV_FILE, "sha256": sup.EV_SHA}],
                         "empty locator": [{"file": sup.EV_FILE, "sha256": sup.EV_SHA, "locator": " "}],
                         "no hash": [{"file": sup.EV_FILE, "locator": "cl. 1"}],
                         "bad hash": [{"file": sup.EV_FILE, "sha256": "zz", "locator": "cl. 1"}],
                         "file not listed": [{"file": "evidence/other.txt", "sha256": sup.EV_SHA, "locator": "cl. 1"}],
                         "hash not listed": [{"file": sup.EV_FILE, "sha256": "2" * 64, "locator": "cl. 1"}]}.items():
            obj = copy.deepcopy(self.led_obj)
            obj["operations"][0]["effective_from"]["evidence"] = ev
            ledger = pv.load_ledger(json.dumps(obj).encode())
            with self.subTest(name):
                self.assertIn("D9", codes(check(ledger, self.reg, self.held)))

    def test_evidence_cited_by_a_fact_must_also_be_held(self):
        obj = copy.deepcopy(self.led_obj)
        obj["operations"][0]["effective_from"]["evidence"] = [{"file": sup.EV_FILE, "sha256": sup.EV_SHA, "locator": "cl. 1"}]
        ledger = pv.load_ledger(json.dumps(obj).encode())
        self.assertIn("D8", codes(check(ledger, self.reg, {sup.EV_FILE: "3" * 64})))

    def test_continuing_verified_needs_the_recorded_search(self):
        did = "LD-013"                                         # the end decision of `one()`: a continuing_verified version
        led_obj, reg0, files = sup.decorate(tpv.one())
        held, ledger = sup.held_table(files), pv.load_ledger(json.dumps(led_obj).encode())
        self.assertEqual(check(ledger, reg0, held), [])
        for name, f in {"missing": lambda r: r.pop("search_record"), "not an object": lambda r: r.update(search_record="x"),
                        "no scope": lambda r: r["search_record"].update(scope=""),
                        "no searcher": lambda r: r["search_record"].pop("searcher"),
                        "no result": lambda r: r["search_record"].update(result=None),
                        "no sources": lambda r: r["search_record"].update(sources=[]),
                        "sources not text": lambda r: r["search_record"].update(sources=[1]),
                        "wrong date": lambda r: r["search_record"].update(searched_on=29000101),
                        "bool date": lambda r: r["search_record"].update(searched_on=True),
                        "string date": lambda r: r["search_record"].update(searched_on="29100101")}.items():
            reg = copy.deepcopy(reg0)
            f(sup.register_record(reg, did))
            with self.subTest(name):
                self.assertIn("D10", codes(check(ledger, reg, held)))

    def test_a_coverage_decision_needs_its_confirmation(self):
        did = "LD-014"
        for name, f in {"missing": lambda r: r.pop("coverage_confirmation"),
                        "wrong chunk hash": lambda r: r["coverage_confirmation"][0].update(text_sha256="9" * 64),
                        "wrong provisions": lambda r: r["coverage_confirmation"][0].update(provisions=["TG:ACT:S9/2900#other"]),
                        "extra provision": lambda r: r["coverage_confirmation"][0]["provisions"].append("TG:ACT:S9/2900#x"),
                        "not a list": lambda r: r.update(coverage_confirmation="x"),
                        "empty list": lambda r: r.update(coverage_confirmation=[])}.items():
            reg = copy.deepcopy(self.reg)
            f(sup.register_record(reg, did))
            with self.subTest(name):
                self.assertIn("D11", codes(check(self.ledger, reg, self.held)))

    def test_a_single_confirmation_object_is_accepted(self):
        reg = copy.deepcopy(self.reg)
        r = sup.register_record(reg, "LD-014")
        r["coverage_confirmation"] = r["coverage_confirmation"][0]
        self.assertEqual(check(self.ledger, reg, self.held), [])


# ------------------------------------------------------------------------------------------------ authority

class NoAuthorityTests(Base):
    def test_unapproved_decisions_never_create_authority(self):
        # a ledger that claims approval while the register says otherwise is rejected by the check ...
        reg = copy.deepcopy(self.reg)
        for r in reg["decisions"]:
            r["status"] = "pending"
        problems = check(self.ledger, reg, self.held)
        self.assertIn("D14", codes(problems))
        # ... and the resolver, even on the ledger's own claims, never serves authority (restrict/shadow cap)
        for mode in ("shadow", "restrict"):
            v = pv.resolve_chunk(self.ledger, tpv.MD, tpv.TXT, None, tpv.TODAY, mode, bound=True)
            self.assertNotIn(v.cls, (pv.AUTHORITATIVE, pv.HISTORICAL))

    def test_the_check_changes_nothing_it_is_given(self):
        reg, held = copy.deepcopy(self.reg), dict(self.held)
        before = (copy.deepcopy(reg), dict(held), self.ledger)
        check(self.ledger, reg, held)
        self.assertEqual((reg, held), (before[0], before[1]))
        self.assertIs(before[2], self.ledger)

    def test_check_decisions_returns_only_errors_and_never_approves(self):
        for p in check(self.ledger, {"schema_version": 1, "decisions": []}, self.held):
            self.assertEqual(p.severity, "error")
        self.assertFalse([n for n in dir(vd) if not n.startswith("_") and "approv" in n.lower()])

    def test_it_never_raises(self):
        for ledger in (None, object(), 5):
            for reg in (None, {}, 5, self.reg):
                with self.subTest(ledger=type(ledger).__name__, reg=type(reg).__name__):
                    out = vd.check_decisions(ledger, reg, corpus_files=self.held, today=TODAY)
                    self.assertTrue(out)
        self.assertTrue(vd.check_decisions(self.ledger, self.reg, corpus_files=self.held, today="2026-11-08"))
        self.assertTrue(vd.check_decisions(self.ledger, self.reg, corpus_files=5, today=TODAY))
        self.assertEqual(vd.cited_files(None, None), [])
        self.assertEqual(vd.cited_files(self.ledger, 5), [sup.EV_FILE])        # only the ledger's own evidence names


class ProposeStatusTests(unittest.TestCase):
    REC = {"decision_id": "LD-012", "status": "pending", "history": [{"date": "2026-01-01", "status": "pending", "by": "x"}]}

    def test_tooling_can_write_the_three_tooling_statuses(self):
        for st in vd.TOOLING_STATUSES:
            out = vd.propose_status(self.REC, st, by="tooling", date=dt.date(2026, 2, 3))
            self.assertEqual(out["status"], st)
            self.assertEqual(out["history"][-1], {"date": "2026-02-03", "status": st, "by": "tooling"})
            self.assertEqual(len(out["history"]), 2)

    def test_approved_and_every_human_only_status_are_refused(self):
        for st in ("approved", "rejected", "requires_further_review", "revoked", "APPROVED", "Approved", "", None, 1):
            with self.subTest(st=st), self.assertRaises(vd.DecisionError):
                vd.propose_status(self.REC, st)

    def test_a_decided_record_is_never_edited(self):
        for st in ("approved", "rejected", "requires_further_review", "revoked"):
            with self.subTest(st=st), self.assertRaises(vd.DecisionError):
                vd.propose_status(dict(self.REC, status=st), "pending")

    def test_it_does_not_mutate_its_input_and_validates_arguments(self):
        rec = copy.deepcopy(self.REC)
        vd.propose_status(rec, "evidence_complete")
        self.assertEqual(rec, self.REC)
        with self.assertRaises(vd.DecisionError):
            vd.propose_status(rec, "pending", by="")
        with self.assertRaises(vd.DecisionError):
            vd.propose_status("not a record", "pending")

    def test_no_function_in_the_module_writes_a_file_or_an_approved_status(self):
        src = inspect.getsource(vd)
        for needle in ("open(", ".write", "write_text", "write_bytes", "os.remove", "unlink", "shutil"):
            self.assertNotIn(needle, src)
        self.assertNotIn('"status"] = "approved"', src)
        self.assertNotIn("status='approved'", src)


# ------------------------------------------------------------------------------------------------ the acceptance gate

class GateDecisionTests(tb.GateCase):
    def test_a_ledger_whose_decisions_are_all_in_the_register_is_accepted(self):
        a = self.accept(tpv.with_closer("delete", link=True))
        self.assertTrue(a.ok, a.problems)
        self.assertIsNotNone(a.register_sha256)
        self.assertEqual((a.fixture, a.production), (False, True))

    def test_register_problems_reject_through_the_gate(self):
        cases = {
            "missing decision": (lambda r: r["decisions"].pop(0), "D4"),
            "unapproved decision": (lambda r: r["decisions"][0].update(status="pending"), "D14"),
            "revoked decision": (lambda r: r["decisions"][0].update(status="revoked"), "D14"),
            "self-approval": (lambda r: r["decisions"][0].update(prepared_by=r["decisions"][0]["reviewer"]["name"]), "D6"),
            "placeholder reviewer": (lambda r: r["decisions"][0]["reviewer"].update(name="TBD"), "D6"),
            "future review date": (lambda r: r["decisions"][0].update(review_date="2999-01-01"), "D6"),
            "no rationale": (lambda r: r["decisions"][0].update(rationale=""), "D6"),
            "no evidence": (lambda r: r["decisions"][0].update(supporting_sources=[]), "D7"),
            "duplicate id": (lambda r: r["decisions"].append(copy.deepcopy(r["decisions"][0])), "D3"),
            "malformed id": (lambda r: r["decisions"][0].update(decision_id="LD-12"), "D2"),
            "register without a jurisdiction": (lambda r: r.clear(), "jurisdiction"),
            "wrong schema version": (lambda r: r.update(schema_version=2), "D1"),
        }
        for name, (mut, code) in cases.items():
            with self.subTest(name):
                a = self.accept(tpv.with_closer("delete", link=True), register_mut=mut)
                self.assertRejected(a, code)

    def test_evidence_problems_reject_through_the_gate(self):
        led = tpv.with_closer("delete", link=True)
        self.assertRejected(self.accept(led, evidence_mut=lambda f: f.clear()), "not in the signed evidence manifest")
        self.assertRejected(self.accept(led, evidence_mut=lambda f: f.update({sup.EV_FILE: b"tampered"})), "does not match")
        c = self.chain(led)
        self.assertRejected(tb.run(c, evidence_dir=None), "cannot be verified")
        self.assertRejected(tb.run(c, evidence_dir=c.dir / "nowhere"), "not a held file")

    def test_an_evidence_file_replaced_after_the_chain_was_built_is_rejected(self):
        c = self.chain(tpv.with_closer("delete", link=True))
        (c.evidence / sup.EV_FILE).write_bytes(b"changed on disk")
        self.assertRejected(tb.run(c), "different size from the manifest")

    def test_unsafe_evidence_names_are_never_held(self):
        for bad in ("../outside.txt", "/etc/hosts", "evidence/../../x", "a\\b", "", ".", "evidence//x", "nul\0byte", "C:x", "a/ b",
                    "tab\tx", "x.", "caf\u00e9.txt"):
            self.assertFalse(em.safe_relative(bad), repr(bad))
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "held"
            root.mkdir()
            (Path(d) / "outside.txt").write_bytes(b"secret")
            (root / "sub").mkdir()
            (root / "sub" / "ok.txt").write_bytes(b"fine")
            (root / "link.txt").symlink_to(Path(d) / "outside.txt")          # a link that escapes the directory
            (root / "inside.txt").symlink_to(root / "sub" / "ok.txt")        # a link that stays inside: still refused
            (Path(d) / "elsewhere").mkdir()
            (Path(d) / "elsewhere" / "ok.txt").write_bytes(b"fine")
            (root / "dirlink").symlink_to(Path(d) / "elsewhere")             # a directory link: refused, not followed
            names = ["sub/ok.txt", "link.txt", "inside.txt", "missing.txt", "sub", "../outside.txt", "dirlink/ok.txt"]
            files = {"sub/ok.txt": b"fine", "link.txt": b"secret", "inside.txt": b"fine", "missing.txt": b"x", "sub": b"x",
                     "dirlink/ok.txt": b"fine"}
            manifest = em.parse(sup.manifest_bytes(files))
            problems, held = em.verify_files(manifest, str(root), names)
            self.assertEqual(sorted(held), ["sub/ok.txt"])
            self.assertEqual(held["sub/ok.txt"], hashlib.sha256(b"fine").hexdigest())
            self.assertEqual(len(problems), len(names) - 1, problems)

    def test_a_fifo_evidence_name_does_not_hang(self):
        import os
        with tempfile.TemporaryDirectory() as d:
            os.mkfifo(Path(d) / "pipe")
            manifest = em.parse(sup.manifest_bytes({"pipe": b""}))
            problems, held = em.verify_files(manifest, d, ["pipe"])
            self.assertEqual(held, {})
            self.assertTrue(problems)

    def test_c3b_still_rejects_when_every_decision_is_fine(self):
        a = self.accept(tpv.with_closer("delete", link=False))
        self.assertRejected(a, "C3b")
        self.assertTrue(all(p.startswith("C3b") for p in a.problems), a.problems)       # nothing but the closure error

    def test_both_the_ledger_errors_and_the_decision_errors_are_reported_before_rejection(self):
        a = self.accept(tpv.with_closer("delete", link=False), register_mut=lambda r: r["decisions"][0].update(status="pending"))
        self.assertFalse(a.ok)

    def test_the_register_and_manifest_are_each_opened_once_and_hashed_from_those_bytes(self):
        c = self.chain(tpv.with_closer("delete", link=True))
        watched = {os.path.realpath(c.register): "register", os.path.realpath(c.manifest): "manifest"}
        opened, live = [], [True]

        def hook(event, args):
            if live[0] and event == "open" and isinstance(args[0], (str, bytes)) and not isinstance(args[0], bytes):
                name = watched.get(os.path.realpath(args[0]))
                if name:
                    opened.append(name)

        sys.addaudithook(hook)
        try:
            a = tb.run(c)
        finally:
            live[0] = False
        self.assertTrue(a.ok, a.problems)
        self.assertEqual(sorted(opened), ["manifest", "register"])
        self.assertEqual(a.register_sha256, hashlib.sha256(c.register.read_bytes()).hexdigest())
        self.assertEqual(a.manifest_sha256, hashlib.sha256(c.manifest.read_bytes()).hexdigest())

    def test_a_register_replaced_after_it_was_read_cannot_change_what_is_accepted(self):
        c = self.chain(tpv.with_closer("delete", link=True))
        before = c.register.read_bytes()
        with tb.hook_after(gate.validity_decisions, "cited_files", lambda: c.register.write_bytes(b"{}")):
            a = tb.run(c)
        self.assertTrue(a.ok, a.problems)
        self.assertEqual(a.register_sha256, hashlib.sha256(before).hexdigest())

    def test_malformed_or_missing_registers_reject(self):
        c = self.chain(tpv.with_closer("delete", link=True))
        for name, data in {"empty": b"", "not json": b"{", "bad utf8": b"\xff\xfe", "array": b"[]", "null": b"null",
                           "duplicate keys": b'{"schema_version": 1, "schema_version": 1, "decisions": []}',
                           "deep": b"[" * 200000 + b"]" * 200000}.items():
            c.register.write_bytes(data)
            with self.subTest(name):
                self.assertFalse(tb.run(c).ok)
        self.assertRejected(tb.run(c, decision_register=c.dir / "missing.json"), "cannot read the decision register")
        self.assertRejected(tb.run(c, decision_register=c.dir), "cannot read the decision register")

    def test_a_synthetic_register_is_refused_unless_fixtures_are_allowed_and_is_then_flagged(self):
        led = tpv.with_closer("delete", link=True)
        a = self.accept(led, fixture_register=True)
        self.assertRejected(a, "synthetic fixture")
        b = self.accept(led, fixture_register=True, allow_fixture=True)
        self.assertTrue(b.ok, b.problems)
        self.assertEqual((b.fixture, b.production), (True, False))

    def test_a_non_fixture_ledger_is_not_made_a_production_acceptance_by_a_fixture_register(self):
        b = self.accept(tpv.one(), fixture_register=True, allow_fixture=True)
        self.assertFalse(b.production)

    def test_unapproved_decisions_are_never_accepted_even_for_fixtures(self):
        raw = (tpv.FIX / "unapproved_and_candidate.json").read_bytes()
        a = self.accept(raw, allow_fixture=True)
        self.assertRejected(a, "D14")

    def test_the_decision_register_path_is_resolved_once(self):
        c = self.chain(tpv.with_closer("delete", link=True))
        p = tb.CountingPath(c.register)
        self.assertTrue(tb.run(c, decision_register=p).ok)
        self.assertEqual(p.calls, 1)

    def test_a_shifting_register_path_cannot_mix_two_registers(self):
        c1, c2 = self.chain(tpv.with_closer("delete", link=True)), self.chain(tpv.one())
        shifting = tb.ShiftingPath(c1.register, c2.register)
        self.assertTrue(tb.run(c1, decision_register=shifting).ok)
        self.assertEqual(shifting.calls, 1)

    def test_every_register_replacement_after_the_ledger_is_loaded_is_rejected(self):
        for kind in tb.KINDS:
            c, other = self.chain(tpv.with_closer("delete", link=True)), self.chain(tpv.one())
            with self.subTest(kind=kind), tb.hook_after(gate.provision_validity, "load_ledger",
                                                        tb.replace_with(kind, c.register, other.register, other.register.read_bytes())):
                a = tb.run(c)
                self.assertFalse(a.ok, kind)          # the replacement is what gets read: another ledger's register, or nothing

    def test_the_gate_still_requires_every_earlier_link(self):
        led = tpv.with_closer("delete", link=True)
        self.assertRejected(self.accept(led, sign=False), "not signed")
        self.assertRejected(self.accept(led, listed=False), "approval is not valid")
        self.assertRejected(self.accept(led, bound="2" * 64), "changed since the registry bound it")
        self.assertRejected(self.accept(led, binding=False), "does not bind")


class IsolationTests(unittest.TestCase):
    def test_only_the_gate_uses_the_decision_checker(self):
        import ast
        for d in ("backend", "scripts", "api", "deploy", "eval"):
            for p in sorted((ROOT / d).rglob("*.py")) if (ROOT / d).is_dir() else []:
                if p.name in ("validity_decisions.py", "ledger_acceptance.py"):
                    continue
                tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
                for n in ast.walk(tree):
                    names = []
                    if isinstance(n, ast.Import):
                        names = [a.name for a in n.names]
                    elif isinstance(n, ast.ImportFrom):
                        names = [n.module or ""] + [a.name for a in n.names]
                    with self.subTest(str(p.relative_to(ROOT))):
                        self.assertFalse([x for x in names if "validity_decisions" in x])

    def test_the_checker_imports_nothing_outside_the_standard_library_except_two_sibling_modules(self):
        import ast
        tree = ast.parse((ROOT / "backend" / "validity_decisions.py").read_text(encoding="utf-8"))
        seen = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                seen |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                seen.add((n.module or "").split(".")[0])
        self.assertEqual(seen - {"__future__", "copy", "datetime", "re", "typing", "backend"}, set())

    def test_the_runtime_still_does_not_know_the_new_modules(self):
        for p in sorted((ROOT / "backend").glob("*.py")):
            if p.name in ("validity_decisions.py", "ledger_acceptance.py", "provision_validity.py", "evidence_manifest.py",
                          "provision_validity_runtime.py"):     # Step 4: the wrapper calls the gate; server.py still knows only the wrapper
                continue
            text_ = p.read_text(encoding="utf-8", errors="replace")
            with self.subTest(p.name):
                self.assertNotIn("validity_decisions", text_)
                self.assertIsNone(re.search(r"from backend import[^\n]*\bevidence_manifest\b|import backend\.evidence_manifest|"
                                            r"from backend\.evidence_manifest|import evidence_manifest", text_))
                if p.name != "source_status.py":                  # the loader's docstring points at the gate by name
                    self.assertNotIn("ledger_acceptance", text_)


if __name__ == "__main__":
    unittest.main()
