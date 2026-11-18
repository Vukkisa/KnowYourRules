"""Offline tests for backend/release_gates.py, backend/offence_date.py and GET /release-gates.

Everything signed, approved or "advocate" here is a SYNTHETIC fixture with a throwaway in-memory key. None of it is,
or may be used as, a real legal approval, and the rule matrices below are not the counsel-approved matrix.
The one exception is STATUTE_200_1, a transcription of the Section 200(1) list substituted by Act 8 of 2026
(Gazette of India, e-Gazette CG-DL-E-08042026-271642, Schedule serial 51, item (ZP)), used to test classification
against the statutory enumeration rather than against the matrix.

Run from the project root:  python -m unittest discover -s tests -p "test_release_gates.py" -v
"""

import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_legal_approval as tla  # noqa: E402  (module import: its TestCases are not re-collected here)
from backend import legal_approval as la  # noqa: E402
from backend import offence_date as od  # noqa: E402
from backend import release_gates as rg  # noqa: E402

POST = dt.date(2026, 9, 1)

# Section 200(1) as substituted from 15-08-2026: (provision, frequency).
STATUTE_200_1 = (
    ("180", "ANY"), ("181", "ANY"), ("182(1)", "ANY"),
    ("182A(1)", "ANY"), ("182A(3)", "ANY"), ("182A(4)", "ANY"),
    ("183(1)", "ANY"), ("184:Explanation(c)", "ANY"), ("189", "ANY"),
    ("190(2)(i)", "SECOND_OR_SUBSEQUENT_ONLY"), ("192", "SECOND_OR_SUBSEQUENT_ONLY"),
    ("192B(3)", "ANY"), ("194E", "SECOND_OR_SUBSEQUENT_ONLY"), ("198(b)", "ANY"),
)
# Provisions the Act's list does not name. Omission from s.200(1) says nothing else about them.
NOT_IN_STATUTE_200_1 = ("177", "177A", "178", "179", "182(2)", "182A(2)", "183(2)", "184:Explanation(a)",
                        "184:Explanation(b)", "185", "190(1)", "190(2)(ii)", "192A", "192B(1)", "194D",
                        "198(a)", "199", "112", "128", "129")


def _rule_entries():
    """Matrix entries built from the statute list, grouped the way the Act groups them."""
    return [
        {"rule_id": "S-01", "provision": "s.180", "scope": "WHOLE_SECTION", "frequency": "ANY"},
        {"rule_id": "S-02", "provision": "s.181", "scope": "WHOLE_SECTION", "frequency": "ANY"},
        {"rule_id": "S-03", "provision": "s.182(1)", "scope": "SUBSECTION_1_ONLY", "frequency": "ANY"},
        {"rule_id": "S-04", "provision": "s.182A(1),(3),(4)", "scope": "SUBSECTIONS", "frequency": "ANY"},
        {"rule_id": "S-05", "provision": "s.183(1)", "scope": "SUBSECTION_1_ONLY", "frequency": "ANY"},
        {"rule_id": "S-06", "provision": "s.184:Explanation(c)", "scope": "CLAUSE", "frequency": "ANY"},
        {"rule_id": "S-07", "provision": "s.189", "scope": "WHOLE_SECTION", "frequency": "ANY"},
        {"rule_id": "S-08", "provision": "s.190(2)(i)", "scope": "CLAUSE", "frequency": "SECOND_OR_SUBSEQUENT_ONLY"},
        {"rule_id": "S-09", "provision": "s.192", "scope": "WHOLE_SECTION", "frequency": "SECOND_OR_SUBSEQUENT_ONLY"},
        {"rule_id": "S-10", "provision": "s.192B(3)", "scope": "SUBSECTION_3_ONLY", "frequency": "ANY"},
        {"rule_id": "S-11", "provision": "s.194E", "scope": "WHOLE_SECTION", "frequency": "SECOND_OR_SUBSEQUENT_ONLY"},
        {"rule_id": "S-12", "provision": "s.198(b)", "scope": "CLAUSE", "frequency": "ANY"},
    ]


def synthetic_matrix(**overrides):
    rules = [dict(r, commencement_date="2026-08-15", verification_status="VERIFIED") for r in _rule_entries()]
    data = {
        "matrix_metadata": {"matrix_id": "SYNTHETIC-TEST-FIXTURE", "signed_advocate_opinion_on_file": True,
                            "telangana_fee_calculation_enabled": True,
                            "telangana_compounding_calculation_enabled": True},
        "feature_release_gates": {
            rg.CENTRAL_EXPLANATION: "APPROVED_FOR_CONTROLLED_DEMONSTRATION",
            rg.CENTRAL_PENALTY: "APPROVED_WITH_RESTRICTIONS",
            rg.TG_FINE: "APPROVED_FOR_CONTROLLED_DEMONSTRATION",
            rg.TG_COMPOUNDING: "APPROVED_WITH_RESTRICTIONS",
            rg.HISTORICAL: "APPROVED_WITH_RESTRICTIONS",
            rg.CMVR_PROCEDURAL: "APPROVED_WITH_RESTRICTIONS",
            rg.LITIGATION: "BOGUS",
        },
        "section_200_post_2026_08_15_rules": rules,
    }
    data.update(overrides)
    return data


def parse(data):
    return rg.parse_matrix(json.dumps(data).encode())


def open_report(matrix, penalty=True):
    return rg.effective_gates(matrix, penalty)


class GateTests(unittest.TestCase):
    def test_all_seven_gates_exist_and_default_blocked(self):
        self.assertEqual(len(rg.ALL_GATES), 7)
        for rep in (rg.effective_gates(None, False), rg.effective_gates(None, True)):
            self.assertEqual(set(rep.gates), set(rg.ALL_GATES))
            self.assertTrue(all(v == rg.BLOCKED for v in rep.gates.values()))

    def test_everything_blocked_without_a_matrix_whatever_the_flag(self):
        for flag in (False, True, "yes", None):
            rep = rg.effective_gates(None, flag)
            self.assertTrue(all(v == rg.BLOCKED for v in rep.gates.values()), flag)

    def test_truthy_non_bool_penalty_flag_does_not_open_the_penalty_gate(self):
        m = parse(synthetic_matrix())
        for flag in ("yes", 1, [1], {"a": 1}):
            rep = rg.effective_gates(m, flag)
            self.assertEqual(rep.gates[rg.CENTRAL_PENALTY], rg.BLOCKED, flag)

    def test_telangana_gates_locked_even_with_a_permissive_matrix(self):
        rep = open_report(parse(synthetic_matrix()))
        self.assertEqual(rep.gates[rg.TG_FINE], rg.BLOCKED)
        self.assertEqual(rep.gates[rg.TG_COMPOUNDING], rg.BLOCKED)
        self.assertFalse(rg.gate_open(rep, rg.TG_FINE))
        self.assertFalse(rg.gate_open(rep, rg.TG_COMPOUNDING))

    def test_central_gates_follow_the_matrix_and_the_penalty_switch(self):
        m = parse(synthetic_matrix())
        rep = open_report(m)
        self.assertEqual(rep.gates[rg.CENTRAL_EXPLANATION], rg.CONTROLLED_DEMO)
        self.assertEqual(rep.gates[rg.CENTRAL_PENALTY], rg.RESTRICTED)
        self.assertEqual(rg.effective_gates(m, False).gates[rg.CENTRAL_PENALTY], rg.BLOCKED)

    def test_unrecognised_gate_value_is_blocked_and_warned(self):
        m = parse(synthetic_matrix())
        self.assertEqual(m.gates[rg.LITIGATION], rg.BLOCKED)
        self.assertTrue(any("unrecognised" in w for w in m.warnings))

    def test_matrix_claim_of_advocate_approval_is_ignored_and_reported(self):
        m = parse(synthetic_matrix())
        text = " ".join(m.warnings)
        self.assertIn("signed_advocate_opinion_on_file", text)
        self.assertIn("telangana_fee_calculation_enabled", text)
        self.assertIn("forced to blocked", text)
        # ...and the claim changes nothing: the code locks and the unrecognised value stay blocked.
        rep = rg.effective_gates(m, False)
        self.assertEqual((rep.gates[rg.TG_FINE], rep.gates[rg.TG_COMPOUNDING], rep.gates[rg.CENTRAL_PENALTY]),
                         (rg.BLOCKED, rg.BLOCKED, rg.BLOCKED))

    def test_matrix_cannot_open_a_gate_the_file_marks_blocked(self):
        d = synthetic_matrix()
        d["feature_release_gates"][rg.CMVR_PROCEDURAL] = "BLOCKED"
        self.assertEqual(open_report(parse(d)).gates[rg.CMVR_PROCEDURAL], rg.BLOCKED)

    def test_matrix_cannot_add_a_gate(self):
        d = synthetic_matrix()
        d["feature_release_gates"]["telangana_everything"] = "APPROVED_FOR_CONTROLLED_DEMONSTRATION"
        rep = open_report(parse(d))
        self.assertNotIn("telangana_everything", rep.gates)

    def test_malformed_matrices_rejected(self):
        for raw in (b"not json", b"[]", b"{}", b"\xff\xfe", b'{"matrix_metadata": {}, "feature_release_gates": []}'):
            with self.assertRaises(rg.MatrixError, msg=raw):
                rg.parse_matrix(raw)
        bad = []
        d = synthetic_matrix(); d["section_200_post_2026_08_15_rules"][0]["commencement_date"] = "2026-08-16"; bad.append(d)
        d = synthetic_matrix(); d["section_200_post_2026_08_15_rules"][1]["rule_id"] = "S-01"; bad.append(d)
        d = synthetic_matrix(); d["section_200_post_2026_08_15_rules"][0]["frequency"] = "SOMETIMES"; bad.append(d)
        d = synthetic_matrix(); d["section_200_post_2026_08_15_rules"][0] = "not an object"; bad.append(d)
        d = synthetic_matrix(); del d["section_200_post_2026_08_15_rules"][0]["provision"]; bad.append(d)
        for d in bad:
            with self.assertRaises(rg.MatrixError):
                parse(d)

    def test_load_matrix_failure_codes_leak_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(rg.load_matrix(Path(tmp) / "secret-name.json"), (None, rg.ERR_NOT_FOUND))
            self.assertEqual(rg.load_matrix(tmp)[1], rg.ERR_UNREADABLE)  # a directory
            p = Path(tmp) / "m.json"
            p.write_text("{not json /Users/someone/secret")
            self.assertEqual(rg.load_matrix(p), (None, rg.ERR_INVALID))
            p.write_bytes(b" " * (rg.MAX_MATRIX_BYTES + 1))
            self.assertEqual(rg.load_matrix(p), (None, rg.ERR_TOO_LARGE))
            p.write_text(json.dumps(synthetic_matrix()))
            m, err = rg.load_matrix(p)
            self.assertIsNone(err)
            self.assertEqual(len(m.rules_200), 12)


class Section200Tests(unittest.TestCase):
    """All seven outcomes, tested against the statute list (STATUTE_200_1), not against the matrix."""

    def setUp(self):
        self.m = parse(synthetic_matrix())
        self.rep = open_report(self.m)

    def disclose(self, prov, date=POST, repeat=None, rep=None, matrix="default"):
        return rg.section_200_disclosure(self.m if matrix == "default" else matrix, rep or self.rep, prov, date, repeat)

    def test_matrix_fixture_covers_exactly_the_statute_list(self):
        got = set()
        for r in self.m.rules_200:
            got.update(r.paths)
        # whole-section rules are stored as the bare section; expand the statute list to compare
        want = set()
        for prov, _ in STATUTE_200_1:
            sec = rg.section_of(prov)
            want.add(sec if any(rule.whole_section and sec in rule.paths for rule in self.m.rules_200) else prov)
        self.assertEqual(got, want)
        self.assertEqual(len(_rule_entries()), 12)

    def test_outcome_unavailable(self):
        closed = rg.effective_gates(self.m, False)
        r = self.disclose("180", rep=closed)
        self.assertEqual((r.status, r.text), ("unavailable", None))
        self.assertEqual(self.disclose("180", matrix=None).status, "unavailable")
        # an unverified or empty list cannot support "not listed"
        d = synthetic_matrix(); d["section_200_post_2026_08_15_rules"][0]["verification_status"] = "DRAFT"
        self.assertEqual(self.disclose("999", matrix=parse(d)).status, "unavailable")
        d = synthetic_matrix(); d["section_200_post_2026_08_15_rules"] = []
        self.assertEqual(self.disclose("177", matrix=parse(d)).status, "unavailable")
        # a closed penalty gate (no penalty approval) is also unavailable
        self.assertEqual(self.disclose("180", rep=open_report(self.m, penalty=False)).status, "unavailable")

    def test_unparseable_provision_is_unavailable_never_not_listed(self):
        for bad in ("", "   ", "section", "184 Explanation (c)", "184Explanation(c)", "182a(1)", "180;DROP", "1" * 40,
                    "../180", None, 180, "٣", "180 (1) x"):
            r = self.disclose(bad)
            self.assertEqual(r.status, "unavailable", repr(bad))
            self.assertIsNone(r.text)

    def test_whitespace_is_normalised_not_rejected(self):
        self.assertEqual(self.disclose(" 180\n").status, "listed")
        self.assertEqual(self.disclose("s. 182A (3)").status, "listed")

    def test_outcome_date_required(self):
        r = self.disclose("180", date=None)
        self.assertEqual(r.status, "date_required")
        self.assertNotIn(rg.NOT_LISTED_PHRASE, r.text)

    def test_outcome_pre_commencement_boundary(self):
        last_day_before = self.disclose("177", date=dt.date(2026, 8, 14))
        self.assertEqual(last_day_before.status, "pre_commencement")
        self.assertEqual(self.disclose("177", date=dt.date(2026, 8, 15)).status, "not_listed")
        self.assertEqual(self.disclose("180", date=dt.date(2026, 8, 15)).status, "listed")
        for d in (dt.date(2019, 8, 31), dt.date(2019, 9, 1), dt.date(1995, 1, 1)):
            r = self.disclose("180", date=d)
            self.assertEqual(r.status, "pre_commencement", d)
            # a provision listed after commencement must not be called listed before it, nor "not included"
            self.assertNotIn("is listed", r.text)
            self.assertNotIn(rg.NOT_LISTED_PHRASE, r.text)
            self.assertIn("does not cover the earlier text", r.text)

    def test_every_statute_item_is_listed_for_a_post_commencement_offence(self):
        for prov, freq in STATUTE_200_1:
            first = self.disclose(prov, repeat=False)
            repeat = self.disclose(prov, repeat=True)
            if freq == "ANY":
                self.assertEqual((first.status, repeat.status), ("listed", "listed"), prov)
            else:
                self.assertEqual((first.status, repeat.status), ("listed_conditionally", "listed"), prov)
                self.assertEqual(self.disclose(prov, repeat=None).status, "listed_conditionally", prov)

    def test_deeper_clauses_of_a_listed_provision_are_listed(self):
        for prov in ("180(1)", "182(1)(a)", "182A(3)(b)", "183(1)(ii)", "184:Explanation(c)(i)", "198(b)(ii)"):
            self.assertEqual(self.disclose(prov).status, "listed", prov)

    def test_every_non_statute_provision_is_not_listed(self):
        for prov in NOT_IN_STATUTE_200_1:
            r = self.disclose(prov)
            self.assertEqual(r.status, "not_listed", prov)
            self.assertIn(rg.NOT_LISTED_PHRASE, r.text)

    def test_section_numbers_do_not_collide_by_prefix(self):
        for prov in ("18", "1", "19", "182B", "192C", "194", "194EA"):
            self.assertEqual(self.disclose(prov).status, "not_listed", prov)

    def test_outcome_partially_listed(self):
        for prov in ("182", "182A", "183", "184", "190", "190(2)", "192B", "198"):
            r = self.disclose(prov)
            self.assertEqual(r.status, "partially_listed", prov)
            self.assertNotIn(rg.NOT_LISTED_PHRASE, r.text)
            self.assertTrue(r.rule_ids)

    def test_no_output_implies_not_punishable_or_no_other_enforcement(self):
        provs = [p for p, _ in STATUTE_200_1] + list(NOT_IN_STATUTE_200_1) + ["182", "190(2)"]
        for prov in provs:
            for date in (None, dt.date(2026, 8, 14), POST):
                for repeat in (None, True, False):
                    r = self.disclose(prov, date=date, repeat=repeat)
                    text = r.text or ""
                    self.assertEqual(rg.phrasing_problems(text), [], (prov, date, repeat, text))
                    self.assertNotRegex(text, r"₹|\bRs\.?\s*\d|\brupee|\bfine of\b|\bpenalty of\b", prov)
                    if r.status == "not_listed":
                        self.assertIn("does not mean the conduct is not an offence", text)
                        self.assertIn("no other enforcement mechanism exists", text)
                    if r.status in ("listed", "listed_conditionally"):
                        self.assertIn("separate from the statutory penalty", text)

    def test_phrasing_guard(self):
        for bad in ("This is not punishable.", "There is no fine for it.", "It is not an offence.",
                    "You cannot be fined for this.", "It is not illegal."):
            self.assertTrue(rg.phrasing_problems(bad), bad)
        self.assertFalse(rg.phrasing_problems("The provision is not included in Section 200(1)."))
        r = self.disclose("177")
        self.assertTrue(rg.phrasing_problems(r.text + " So it is not punishable."))


class OffenceDateTests(unittest.TestCase):
    TODAY = dt.date(2026, 11, 16)

    def test_bands_and_boundaries_inclusive_exclusive(self):
        d = dt.date
        cases = [(d(1989, 7, 1), od.BAND_PRE_2019), (d(2019, 8, 31), od.BAND_PRE_2019),
                 (d(2019, 9, 1), od.BAND_2019_2026), (d(2026, 8, 14), od.BAND_2019_2026),
                 (d(2026, 8, 15), od.BAND_POST_2026), (d(2026, 11, 16), od.BAND_POST_2026),
                 (None, od.BAND_UNSPECIFIED)]
        for day, band in cases:
            self.assertEqual(od.band_for(day), band, day)

    def test_parse_valid_forms(self):
        for text in ("2026-08-15", "15-08-2026", "15/08/2026", "15.08.2026", " 2026-8-15 ", "2026-08-15"):
            self.assertEqual(od.parse_offence_date(text, self.TODAY), dt.date(2026, 8, 15), text)
        self.assertEqual(od.parse_offence_date(dt.datetime(2026, 8, 15, 23, 59), self.TODAY), dt.date(2026, 8, 15))
        self.assertEqual(od.parse_offence_date(dt.date(2026, 8, 15), self.TODAY), dt.date(2026, 8, 15))
        self.assertEqual(od.parse_offence_date(self.TODAY.isoformat(), self.TODAY), self.TODAY)

    def test_missing_date_is_none_not_today(self):
        for v in (None, "", "   "):
            self.assertIsNone(od.parse_offence_date(v, self.TODAY))

    def test_invalid_dates_raise(self):
        for bad in ("2026-13-01", "2026-02-30", "31/02/2026", "29-02-2025", "yesterday", "2026/08/15", "15-8-26",
                    "2026-12-01", "2026-11-17", "1950-01-01", "1988-12-31", "٢٠٢٦-٠٨-١٥", "2026-08-15T00:00",
                    20260815, 1.5, True, ["2026-08-15"], {"d": 1}):
            with self.assertRaises(od.OffenceDateError, msg=repr(bad)):
                od.parse_offence_date(bad, self.TODAY)

    def test_leap_day(self):
        self.assertEqual(od.parse_offence_date("29-02-2024", self.TODAY), dt.date(2024, 2, 29))

    def test_chroma_where_is_integer_inclusive_and_two_sided(self):
        w = od.chroma_where(dt.date(2026, 8, 15))
        self.assertEqual(w, {"$and": [{"valid_from": {"$lte": 20260815}}, {"valid_to": {"$gte": 20260815}}]})
        for clause in w["$and"]:
            self.assertIsInstance(list(list(clause.values())[0].values())[0], int)

    def doc(self, **meta):
        return SimpleNamespace(metadata=meta)

    def test_historical_version_selection_at_boundaries(self):
        v1 = self.doc(valid_from=20190901, valid_to=20260814, tag="2019 text")
        v2 = self.doc(valid_from=20260815, valid_to=od.OPEN_ENDED, tag="2026 text")
        old = self.doc(valid_from=19890701, valid_to=20190831, tag="pre-2019 text")
        docs = [old, v1, v2]
        for day, want in ((dt.date(2019, 8, 31), old), (dt.date(2019, 9, 1), v1), (dt.date(2026, 8, 14), v1),
                          (dt.date(2026, 8, 15), v2), (dt.date(2026, 11, 16), v2), (dt.date(1989, 7, 1), old)):
            routed = od.route_documents(docs, day)
            self.assertEqual(list(routed.authoritative), [want], day)
            self.assertEqual(routed.dropped, 2)
            self.assertTrue(routed.temporally_established)
            self.assertEqual(routed.notes, ())

    def test_unversioned_chunks_are_never_authoritative(self):
        unv = self.doc()
        valid = self.doc(valid_from=20190901, valid_to=od.OPEN_ENDED)
        routed = od.route_documents([unv, valid], dt.date(2020, 1, 1))
        self.assertEqual(list(routed.authoritative), [valid])
        self.assertEqual(list(routed.unverified), [unv])
        self.assertIn(od.UNVERSIONED_NOTE, routed.notes)
        self.assertIn("not temporal evidence", od.UNVERSIONED_NOTE)

    def test_only_unversioned_chunks_do_not_establish_the_law_on_the_date(self):
        routed = od.route_documents([self.doc(), self.doc(source="x")], dt.date(2015, 5, 5))
        self.assertEqual(routed.authoritative, ())
        self.assertEqual(len(routed.unverified), 2)
        self.assertFalse(routed.temporally_established)
        self.assertIn(od.NO_DATED_TEXT_NOTE, routed.notes)

    def test_missing_offence_date_makes_everything_unverified(self):
        dated = self.doc(valid_from=20190901, valid_to=od.OPEN_ENDED)
        routed = od.route_documents([dated, self.doc()], None)
        self.assertEqual(routed.authoritative, ())
        self.assertEqual(len(routed.unverified), 2)
        self.assertFalse(routed.offence_date_given)
        self.assertFalse(routed.temporally_established)
        self.assertEqual(routed.notes, (od.DATE_REQUIRED_NOTE,))

    def test_malformed_validity_metadata_is_unverified_not_valid(self):
        bad = [self.doc(valid_from=20260815), self.doc(valid_to=20260815), self.doc(valid_from=20260815, valid_to=20190901),
               self.doc(valid_from="20190901", valid_to=20260814), self.doc(valid_from=True, valid_to=20260814),
               self.doc(valid_from=20261340, valid_to=20270101), self.doc(valid_from=20190901, valid_to=20261399),
               self.doc(valid_from=20190901, valid_to=None), self.doc(valid_from=1.5, valid_to=2.5)]
        routed = od.route_documents(bad, dt.date(2020, 1, 1))
        self.assertEqual(routed.authoritative, ())
        self.assertEqual(len(routed.unverified), len(bad))
        for d in bad:
            self.assertIn(od.temporal_status(d.metadata, dt.date(2020, 1, 1)), od.UNVERIFIED_STATUSES)

    def test_documents_without_metadata_attribute(self):
        routed = od.route_documents([object(), SimpleNamespace(metadata=None)], dt.date(2020, 1, 1))
        self.assertEqual(len(routed.unverified), 2)

    def test_open_ended_end_is_valid_and_other_nines_are_not_special(self):
        self.assertEqual(od.temporal_status({"valid_from": 20190901, "valid_to": od.OPEN_ENDED}, dt.date(2030, 1, 1)), od.VALID)
        self.assertEqual(od.temporal_status({"valid_from": 20190901, "valid_to": 99991230}, dt.date(2030, 1, 1)), od.VALID)


class ReleaseGateEndpointTests(unittest.TestCase):
    """GET /release-gates on the real server module (offline fakes) with SYNTHETIC signed fixtures."""

    start = tla.ServerApprovalTests.start  # reuses the signed-fixture harness without re-collecting its tests

    def matrix_path(self, data=None, raw=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = Path(tmp.name) / "synthetic-rule-matrix.json"
        p.write_text(raw if raw is not None else json.dumps(data if data is not None else synthetic_matrix()))
        return p

    def server(self, record=None, matrix=None, raw_matrix=None, no_matrix=False, **kw):
        env = dict(kw.pop("extra_env", {}) or {})
        if no_matrix:
            env["TG_RULE_MATRIX_FILE"] = str(Path(tempfile.gettempdir()) / "definitely-missing-rule-matrix.json")
        else:
            self.mpath = self.matrix_path(matrix, raw_matrix)
            env["TG_RULE_MATRIX_FILE"] = str(self.mpath)
        return self.start(record, extra_env=env, **kw)

    def gates(self, client):
        r = client.get("/release-gates")
        self.assertEqual(r.status_code, 200)
        return r.json()

    def assert_all_blocked(self, body):
        self.assertEqual(set(body["gates"]), set(rg.ALL_GATES))
        self.assertTrue(all(v == rg.BLOCKED for v in body["gates"].values()), body)

    def assert_locked(self, body):
        """What no input may ever open: the Telangana gates (code locks), the penalty gate (switch off), unrecognised values."""
        self.assertEqual(set(body["gates"]), set(rg.ALL_GATES))
        for g in (rg.TG_FINE, rg.TG_COMPOUNDING, rg.CENTRAL_PENALTY, rg.LITIGATION):
            self.assertEqual(body["gates"][g], rg.BLOCKED, g)

    def test_no_approval_record_is_needed_central_gates_follow_the_matrix(self):
        srv, client = self.server(record=None)
        body = self.gates(client)
        self.assertFalse(body["approval_valid"])
        self.assertEqual(body["gates"][rg.CENTRAL_EXPLANATION], rg.CONTROLLED_DEMO)
        self.assert_locked(body)

    def test_a_signed_record_changes_nothing_here(self):
        srv, client = self.server(tla.synthetic_record(penalty_answers_approved=True))
        body = self.gates(client)
        self.assertEqual(body["gates"][rg.CENTRAL_EXPLANATION], rg.CONTROLLED_DEMO)
        self.assert_locked(body)       # a record's penalty flag cannot open the penalty gate

    def test_changed_approval_inputs_are_irrelevant(self):
        srv, client = self.server(tla.synthetic_record())
        before = self.gates(client)
        self.record_path.write_text(self.record_path.read_text() + " ")
        tla.write_keys(self.tmpdir, tla.key_entry(tla.new_key(), "some-other-key"))
        client.post("/approval/refresh")
        self.assertEqual(self.gates(client), before)

    def test_missing_matrix_blocks_everything(self):
        srv, client = self.server(tla.synthetic_record(penalty_answers_approved=True), no_matrix=True)
        body = self.gates(client)
        self.assert_all_blocked(body)
        self.assertEqual((body["matrix_loaded"], body["matrix_problem"]), (False, True))

    def test_malformed_matrix_blocks_everything(self):
        for raw in ("{", "[]", "{}", json.dumps(synthetic_matrix(feature_release_gates=[]))):
            srv, client = self.server(tla.synthetic_record(), raw_matrix=raw)
            body = self.gates(client)
            self.assert_all_blocked(body)
            self.assertTrue(body["matrix_problem"], raw)

    def test_matrix_trying_to_enable_telangana_gates_is_ignored(self):
        d = synthetic_matrix()
        d["feature_release_gates"][rg.TG_FINE] = "APPROVED_FOR_CONTROLLED_DEMONSTRATION"
        d["feature_release_gates"][rg.TG_COMPOUNDING] = "APPROVED_FOR_CONTROLLED_DEMONSTRATION"
        srv, client = self.server(tla.synthetic_record(penalty_answers_approved=True), matrix=d)
        body = self.gates(client)
        self.assertEqual((body["gates"][rg.TG_FINE], body["gates"][rg.TG_COMPOUNDING]), (rg.BLOCKED, rg.BLOCKED))

    def test_matrix_claiming_advocate_approval_cannot_open_locked_gates(self):
        d = synthetic_matrix()
        d["matrix_metadata"].update(signed_advocate_opinion_on_file=True, release_status="GREEN_LIT_CONTROLLED_DEMONSTRATION")
        srv, client = self.server(record=None, matrix=d)
        self.assert_locked(self.gates(client))

    def test_env_vars_cannot_open_locked_gates(self):
        srv, client = self.server(record=None, extra_env={"TG_KB_APPROVED": "1", "TG_PENALTY_ANSWERS": "1",
                                                          "TG_RELEASE_GATES": "open"})
        self.assert_locked(self.gates(client))

    def test_endpoint_exposes_minimum_information(self):
        srv, client = self.server(tla.synthetic_record(penalty_answers_approved=True))
        r = client.get("/release-gates")
        self.assertEqual(set(r.json()), {"gates", "approval_valid", "matrix_loaded", "matrix_problem"})
        text = r.text
        for secret in (str(self.tmpdir), str(self.mpath), self.mpath.name, "Synthetic Reviewer Fixture",
                       "synthetic-corpus-1", "SYNTHETIC-TEST-FIXTURE", "test-key-1", la.sha256_file(self.mpath),
                       "advocate", "/Users", "approval.json"):
            self.assertNotIn(secret, text)
        srv2, client2 = self.server(raw_matrix="{secret /Users/x")
        self.assertNotIn("secret", client2.get("/release-gates").text)
        self.assertNotIn("/Users", client2.get("/release-gates").text)

    def test_direct_requests_cannot_change_state(self):
        srv, client = self.server(record=None)
        self.assertEqual(client.post("/release-gates", json={"gates": "open"}).status_code, 405)
        self.assertEqual(client.put("/release-gates").status_code, 405)
        self.assertEqual(client.delete("/release-gates").status_code, 405)
        for path in ("/release-gates?gate=open", "/release-gates?approved=1&matrix=/etc/passwd",
                     "/release-gates/", "/release-gates/%2e%2e/status"):
            r = client.get(path, headers={"X-Forwarded-For": "127.0.0.1", "X-Approved": "1"})
            if r.status_code == 200 and "gates" in r.json():
                self.assert_locked(r.json())

    def test_head_options_do_not_leak_or_open(self):
        srv, client = self.server(record=None)
        self.assertLess(client.options("/release-gates").status_code, 500)
        self.assertLess(client.head("/release-gates").status_code, 500)

    def test_chat_is_connected_to_the_gates(self):
        # Superseded: /chat now enforces the gates (end-to-end behaviour is in test_chat_release_gates.py). This only
        # pins that server.py reaches the pure modules and does not duplicate Section 200 logic itself.
        srv, client = self.server(record=None)
        r = client.post("/chat", json={"message": "What is the fine for no helmet?", "session_id": "g"}).json()
        self.assertEqual(r["kind"], "restricted")
        source = Path(srv.__file__).read_text()
        for name in ("chat_guards.evaluate", "route_documents", "retrieve_dated"):
            self.assertIn(name, source)
        for name in ("section_200_disclosure", "phrasing_problems"):
            self.assertNotIn(name, source)

    def test_route_set_is_reviewed(self):
        srv, client = self.server(record=None)
        self.assertIn(("GET", "/release-gates"), {(m, r.path) for r in srv.app.routes
                                                  for m in (getattr(r, "methods", None) or ())})


if __name__ == "__main__":
    unittest.main()
