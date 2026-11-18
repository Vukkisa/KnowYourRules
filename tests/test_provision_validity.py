"""Provision-level validity ledger library (roadmap Step 1). Offline, synthetic, isolated.

Nothing here is a real legal date, approval or index. Fixture ledgers live in tests/fixtures/provision_validity and carry
"fixture": true. Run: python3 -m unittest discover -s tests -p "test_provision_validity.py"
"""

import ast
import copy
import dataclasses
import datetime as dt
import hashlib
import json
import random
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import provision_validity as pv  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "provision_validity"
FIXTURE_NAMES = ["go53_go16_synthetic", "rule81_conflicting_targets", "same_number_acts", "overlap", "gap",
                 "stale_coverage", "unapproved_and_candidate", "partial_chunk"]
SH = lambda s: hashlib.sha256(s.encode()).hexdigest()  # noqa: E731
FILE_SHA = SH("synthetic-file-bytes")
AUTH_HIST = (pv.AUTHORITATIVE, pv.HISTORICAL)
SENTINEL_PATHS = ["docs/legal-sources/telangana-traffic/DRAFT-telangana-manifest.json", "legal-status/source-status.json",
                  "legal"]
LIVE_INDEX_DIRS = ["chroma_telangana_staging_validity", "chroma_telangana_preview", "chroma_telangana_preview_s11"]


def raw(name):
    return json.loads((FIX / f"{name}.json").read_text())


def build(obj, **kw):
    return pv.load_ledger(json.dumps(obj).encode(), **kw)


def fixture_ledger(name, **mut):
    """A fixture loaded with allow_fixture=True, optionally with `fixture` cleared so it can be trusted in tests."""
    d = raw(name)
    if mut.pop("trusted_copy", False):
        d["fixture"] = False
    d.update(mut)
    return build(d, allow_fixture=True)


# ---- one-provision builder for the design 5.1 rows -------------------------------------------------------------------
ACTK = "TG:ACT:S9/2900"
P = f"{ACTK}#s1"
TXT = "ROW TEXT"
MD = {"manifest_id": "m1", "sha256": FILE_SHA, "provision_id": "SECTION 1", "part": 1, "parts": 1, "page_start": 1,
      "page_end": 1}
TODAY = 29100601


def _next(n):
    d = dt.date(n // 10000, n // 100 % 100, n % 100) + dt.timedelta(days=1)
    return d.year * 10000 + d.month * 100 + d.day


def fct(date, ref, approved=True):
    if approved:
        return {"state": "approved", "kind": "commencement", "date": date, "candidate": date, "decision_ref": ref}
    return {"state": "proposed", "kind": "commencement", "candidate": date, "decision_ref": ref}


def one(*, start=29000101, start_ok=True, end=("cv", 29100101), rule=True, fresh=365, held=True, with_version=True,
        status=None, cov=True):
    """Single provision, single chunk. `status` overrides decision statuses by role."""
    st = {"start": "approved", "end": "approved", "cov": "approved", "rule": "approved", "fresh": "approved",
          "close": "approved"}
    st.update(status or {})
    ids = {"start": "LD-001", "end": "LD-002", "cov": "LD-003", "rule": "LD-004", "fresh": "LD-005", "close": "LD-006"}
    d = {"schema_version": 1,
         "instruments": [{"key": ACTK, "kind": "ACT", "jurisdiction": "TG", "manifest_ids": ["m1"]}],
         "provisions": [{"key": P}],
         "decisions": [{"decision_id": ids[r], "status": st[r], "subject": r, "prepared_by": "synthetic a",
                        "reviewer": {"name": "synthetic b"}} for r in ids]}
    if rule:
        d["interval_rule"] = {"rule": pv.INTERVAL_RULE, "decision_ref": ids["rule"]}
    if fresh is not None:
        d["freshness_window"] = {"days": fresh, "decision_ref": ids["fresh"]}
    ops = [{"id": "OP-A", "type": "insert", "source": ACTK, "targets": [P], "effective_from": fct(start, ids["start"], start_ok)}]
    ver = {"key": f"{P}@1", "provision": P, "text": "held" if held else "not_held", "created_by_op": "OP-A"}
    if end[0] == "cv":
        ver["end"] = {"state": "continuing_verified", "checked_through": end[1], "decision_ref": ids["end"]}
    elif end[0] == "closed":
        ops.append({"id": "OP-B", "type": "delete", "source": ACTK, "targets": [P],
                    "effective_from": fct(_next(end[1]), ids["close"])})
        ver.update(closed_by_op="OP-B", end={"state": "closed"})
    else:
        ver["end"] = {"state": "unverified"}
    d["operations"] = ops
    d["versions"] = [ver] if with_version else []
    d["coverage"] = ([{"selector": dict(MD, text_sha256=SH(TXT)), "provisions": [P], "decision_ref": ids["cov"]}]
                     if cov else [])
    return d


def res(L, qd, today=TODAY, mode="restrict", bound=True, md=MD, text=TXT):
    return pv.resolve_chunk(L, md, text, qd, today, mode, bound=bound)


def opin(obj, qd, today=TODAY, bound=True):
    return res(build(obj), qd, today, bound=bound).opinion


# =========================================================================================================== loader

class LoaderTests(unittest.TestCase):
    def test_every_fixture_is_marked_and_refused_without_allow_fixture(self):
        for n in FIXTURE_NAMES:
            with self.subTest(n):
                text = (FIX / f"{n}.json").read_text()
                self.assertTrue(json.loads(text)["fixture"] is True)
                with self.assertRaisesRegex(pv.LedgerError, "fixture"):
                    pv.load_ledger(FIX / f"{n}.json")          # the call the server path will make (Step 6)
                with self.assertRaisesRegex(pv.LedgerError, "fixture"):
                    pv.load_ledger(text.encode())
                self.assertTrue(pv.load_ledger(FIX / f"{n}.json", allow_fixture=True).fixture)

    def test_allow_fixture_must_be_exactly_true_and_keyword_only(self):
        p = FIX / "gap.json"
        for v in (1, "yes", "True", [1], None, 0):
            with self.subTest(v), self.assertRaises(pv.LedgerError):
                pv.load_ledger(p, allow_fixture=v)
        with self.assertRaises(TypeError):
            pv.load_ledger(p, True)  # type: ignore[misc]  (positional is impossible)

    def test_fixtures_use_obviously_synthetic_dates_and_names(self):
        for n in FIXTURE_NAMES:
            text = (FIX / f"{n}.json").read_text()
            for m in re.finditer(r'"(?:date|candidate|checked_through)": (\d+)', text):
                self.assertRegex(m.group(1), r"^2[89]\d{6}$", f"{n}: {m.group(0)}")
            self.assertIn("SYNTHETIC", text)
            self.assertNotRegex(text, r'"(?:date|candidate)": 20[12]\d{5}')

    def test_sha256_is_over_the_raw_bytes(self):
        b = (FIX / "gap.json").read_bytes()
        self.assertEqual(pv.load_ledger(b, allow_fixture=True).sha256, hashlib.sha256(b).hexdigest())
        self.assertEqual(pv.load_ledger(FIX / "gap.json", allow_fixture=True).sha256, hashlib.sha256(b).hexdigest())

    def test_a_fixture_ledger_is_never_trusted_even_when_loaded_and_bound(self):
        d = raw("go53_go16_synthetic")
        L = build(d, allow_fixture=True)
        for qd in (None, 29010401, 29020601, 29000101):
            r = res(L, qd, bound=True, md=self.md53(), text=self.t53())
            self.assertNotIn(r.opinion, AUTH_HIST + (pv.NOT_IN_FORCE,), qd)
        d["fixture"] = False                                    # same content, no fixture flag: trust is possible
        self.assertEqual(res(build(d), None, md=self.md53(), text=self.t53()).opinion, pv.BLOCKED)

    @staticmethod
    def md53():
        return {"manifest_id": "synthetic-go53", "sha256": FILE_SHA, "provision_id": "SEVENTH SCHEDULE", "part": 1,
                "parts": 1, "page_start": 3, "page_end": 4}

    @staticmethod
    def t53():
        return "SYNTHETIC SEVENTH SCHEDULE TABLE (columns 1 and 8)"

    def test_malformed_ledgers_are_refused(self):
        base = one()
        cases = {
            "not json": b"{nope",
            "list": b"[]",
            "duplicate key": b'{"schema_version":1,"schema_version":1}',
            "bad utf8": b"\xff\xfe",
            "unknown top key": dict(base, extra=1),
            "bad schema_version": dict(base, schema_version=2),
            "bool schema_version": dict(base, schema_version=True),
        }
        for name, c in cases.items():
            with self.subTest(name), self.assertRaises(pv.LedgerError):
                pv.load_ledger(c if isinstance(c, bytes) else json.dumps(c).encode())
        with self.assertRaises(pv.LedgerError):
            pv.load_ledger(12345)  # type: ignore[arg-type]
        with self.assertRaises(pv.LedgerError):
            pv.load_ledger("/nonexistent/ledger.json")

    def mutate(self, f):
        d = copy.deepcopy(one())
        f(d)
        with self.assertRaises(pv.LedgerError):
            build(d)

    def test_only_commencement_may_feed_validity(self):
        for kind in ("gazette_direction", "publication", "issue", "effective", ""):
            with self.subTest(kind):
                self.mutate(lambda d, k=kind: d["operations"][0]["effective_from"].update(kind=k))

    def test_fact_rules(self):
        self.mutate(lambda d: d["operations"][0]["effective_from"].pop("date"))                    # approved, no date
        self.mutate(lambda d: d["operations"][0]["effective_from"].pop("decision_ref"))            # approved, no decision
        self.mutate(lambda d: d["operations"][0]["effective_from"].update(state="proposed"))       # date on a proposed fact
        self.mutate(lambda d: d["operations"][0]["effective_from"].update(date=20260230))          # not a calendar date
        self.mutate(lambda d: d["operations"][0]["effective_from"].update(date="29000101"))        # string
        self.mutate(lambda d: d["operations"][0]["effective_from"].update(date=True))              # bool
        self.mutate(lambda d: d["operations"][0]["effective_from"].update(date=29000101.0))        # float
        self.mutate(lambda d: d["operations"][0]["effective_from"].update(candidate=20261301))     # bad candidate
        self.mutate(lambda d: d["operations"][0]["effective_from"].update(decision_ref="LD-099"))  # dangling
        self.mutate(lambda d: d["operations"][0]["effective_from"].update(decision_ref="VD-001"))  # wrong prefix
        self.mutate(lambda d: d["operations"][0]["effective_from"].update(state="maybe"))
        self.mutate(lambda d: d["operations"][0]["effective_from"].update(note="x"))               # unknown key

    def test_structure_rules(self):
        self.mutate(lambda d: d["versions"][0].update(provision=f"{ACTK}#nope"))
        self.mutate(lambda d: d["versions"][0].update(key="wrong@1"))
        self.mutate(lambda d: d["versions"][0].update(created_by_op="OP-NOPE"))
        self.mutate(lambda d: d["versions"][0].update(start=fct(29000101, "LD-001")))              # start AND created_by_op
        self.mutate(lambda d: d["versions"][0]["end"].update(state="closed"))                      # closed w/o closing op
        self.mutate(lambda d: d["versions"][0]["end"].pop("checked_through"))                      # cv w/o horizon
        self.mutate(lambda d: d["versions"][0]["end"].update(state="unverified"))                  # stray cv fields
        self.mutate(lambda d: d["operations"][0].update(targets=[]))
        self.mutate(lambda d: d["operations"][0].update(targets=[f"{ACTK}#missing"]))
        self.mutate(lambda d: d["operations"][0].update(type="invent"))
        self.mutate(lambda d: d["operations"][0].update(source="TG:ACT:S1/1900"))
        self.mutate(lambda d: d["operations"].append(dict(d["operations"][0])))                    # duplicate op id
        self.mutate(lambda d: d["provisions"].append({"key": P}))                                  # duplicate provision
        self.mutate(lambda d: d["provisions"].append({"key": f"{ACTK}#x", "parent": f"{ACTK}#y"}))
        self.mutate(lambda d: d["provisions"].extend([{"key": f"{ACTK}#c1", "parent": f"{ACTK}#c2"},
                                                      {"key": f"{ACTK}#c2", "parent": f"{ACTK}#c1"}]))
        self.mutate(lambda d: d["instruments"][0].update(jurisdiction="IN"))                       # prefix mismatch
        self.mutate(lambda d: d["instruments"][0].update(key="5/1963", kind="ACT"))
        self.mutate(lambda d: d["coverage"][0]["selector"].pop("text_sha256"))
        self.mutate(lambda d: d["coverage"][0]["selector"].update(text_sha256="ABC"))
        self.mutate(lambda d: d["coverage"][0]["selector"].update(part=True))
        self.mutate(lambda d: d["coverage"][0].update(provisions=[]))
        self.mutate(lambda d: d["coverage"][0].update(provisions=[f"{ACTK}#missing"]))
        self.mutate(lambda d: d["coverage"].append(copy.deepcopy(d["coverage"][0])))               # duplicate selector
        self.mutate(lambda d: d["interval_rule"].update(rule="guess"))
        self.mutate(lambda d: d["freshness_window"].update(days=-1))
        self.mutate(lambda d: d["decisions"][0].update(status="signed"))
        self.mutate(lambda d: d["decisions"][0].update(decision_id="LD-0001"))

    def test_chunks_sharing_a_label_but_differing_in_pages_or_text_are_distinct_coverage_entries(self):
        """The two "SCHEDULE" chunks of G.O. 53 share manifest, file, label, part and parts; only pages and text differ."""
        d = one()
        for pages, text in (((1, 2), "OTHER TEXT"), ((1, 1), "SAME PAGES, OTHER TEXT")):
            extra = copy.deepcopy(d["coverage"][0])
            extra["selector"].update(page_start=pages[0], page_end=pages[1], text_sha256=SH(text))
            d["coverage"].append(extra)
        L = build(d)
        self.assertTrue(res(L, None).covered)
        self.assertNotIn("stale_coverage", res(L, None).reasons)
        self.assertNotIn("stale_coverage", res(L, None, md=dict(MD, page_end=2), text="OTHER TEXT").reasons)
        self.assertNotIn("stale_coverage", res(L, None, text="SAME PAGES, OTHER TEXT").reasons)
        # mixing one entry's pages with another's text matches neither: stale, never covered by accident
        self.assertIn("stale_coverage", res(L, None, md=dict(MD, page_end=2), text=TXT).reasons)
        self.assertIn("stale_coverage", res(L, None, text="neither").reasons)

    def test_an_entry_identical_in_every_field_is_still_a_duplicate(self):
        d = one()
        d["coverage"].append(copy.deepcopy(d["coverage"][0]))
        with self.assertRaises(pv.LedgerError):
            build(d)
        d = one()
        d["coverage"].append(copy.deepcopy(d["coverage"][0]))
        d["coverage"][1]["decision_ref"] = None
        with self.assertRaises(pv.LedgerError):                 # a different decision does not make the selector different
            build(d)

    def test_load_has_no_side_effects_on_input(self):
        b = (FIX / "go53_go16_synthetic.json").read_bytes()
        before = hashlib.sha256(b).hexdigest()
        pv.load_ledger(b, allow_fixture=True)
        self.assertEqual(hashlib.sha256(b).hexdigest(), before)


# =========================================================================================================== validate

class ValidateTests(unittest.TestCase):
    def codes(self, L):
        return sorted((p.code, p.severity) for p in pv.validate(L))

    def test_clean_ledgers(self):
        for n in ("go53_go16_synthetic", "partial_chunk", "same_number_acts", "stale_coverage"):
            self.assertEqual(self.codes(fixture_ledger(n)), [], n)

    def test_c1_overlap_is_an_error_for_known_intervals(self):
        self.assertIn(("C1", "error"), self.codes(fixture_ledger("overlap")))

    def test_c1_overlap_is_a_warning_when_an_end_is_only_unverified(self):
        d = raw("overlap")
        for v in d["versions"]:
            v["end"] = {"state": "unverified"}
        self.assertIn(("C1", "warning"), self.codes(build(d, allow_fixture=True)))

    def test_c2_gap(self):
        self.assertIn(("C2", "warning"), self.codes(fixture_ledger("gap")))

    def test_c3_orphan_operation(self):
        d = raw("go53_go16_synthetic")
        d["versions"] = [v for v in d["versions"] if not v["key"].endswith("col8@0")]
        d["versions"] = [v for v in d["versions"] if "col8" not in v["key"]]
        d["versions"] = [{k: x for k, x in v.items() if k != "closed_by_op"} if "col8" in v["key"] else v for v in d["versions"]]
        self.assertIn("C3", [c for c, _ in self.codes(build(d, allow_fixture=True))])

    def test_c4_same_day_ordering(self):
        got = [p for p in pv.validate(fixture_ledger("rule81_conflicting_targets")) if p.code == "C4"]
        self.assertEqual(sorted(p.subject.rsplit("#", 1)[1] for p in got), ["r81.sr3", "r81.sr6"])

    def test_c5_target_absent_from_every_coverage_record(self):
        d = raw("go53_go16_synthetic")
        d["coverage"][0]["provisions"] = [d["coverage"][0]["provisions"][0]]    # col1 only; col8 targeted but uncovered
        got = [p for p in pv.validate(build(d, allow_fixture=True)) if p.code == "C5"]
        self.assertTrue(any("col8" in p.message for p in got))

    def test_c8_same_number_instruments_stay_apart(self):
        L = fixture_ledger("same_number_acts")
        self.assertEqual([p for p in pv.validate(L) if p.code == "C8"], [])
        keys = {i.key for i in L.instruments}
        self.assertEqual(keys, {"IN:ACT:S8/2899", "TG:ACT:S8/2899"})

    def test_c8_cross_jurisdiction_operation_and_coverage_and_manifest_mapping(self):
        d = raw("same_number_acts")
        d["operations"][0]["targets"] = ["TG:ACT:S8/2899#s1"]                     # central op reaching a Telangana provision
        self.assertIn(("C8", "error"), self.codes(build(d, allow_fixture=True)))
        d = raw("same_number_acts")
        d["coverage"][0]["provisions"] = ["TG:ACT:S8/2899#s1"]                    # central file mapped to a TG provision
        self.assertIn(("C8", "error"), self.codes(build(d, allow_fixture=True)))
        d = raw("same_number_acts")
        d["instruments"][1]["manifest_ids"] = ["synthetic-central-8"]            # one manifest id, two instruments
        self.assertIn(("C8", "error"), self.codes(build(d, allow_fixture=True)))

    def test_s1_inverted_interval(self):
        d = raw("go53_go16_synthetic")
        for o in d["operations"]:
            if o["id"] == "OP-S16-1":
                o["effective_from"]["date"] = 29000101   # before G.O. 53 starts
        self.assertIn(("S1", "error"), self.codes(build(d, allow_fixture=True)))

    def test_c11_candidates_without_approval_are_informational(self):
        self.assertEqual(self.codes(fixture_ledger("unapproved_and_candidate")), [("C11", "info"), ("C11", "info")])

    def test_validate_does_not_raise_or_mutate(self):
        L = fixture_ledger("rule81_conflicting_targets")
        a = pv.validate(L)
        self.assertEqual(a, pv.validate(L))


# ====================================================================================== design 5.1 rows (opinion)

class RowTests(unittest.TestCase):
    """Every row of design section 5.1. `opin` is the ledger's opinion under full trust; resolve_chunk then caps it."""

    # ---- dated
    def test_dated_before_known_start_is_not_in_force(self):
        self.assertEqual(opin(one(start=29000601), 29000101), pv.NOT_IN_FORCE)

    def test_dated_inside_closed_interval_is_historical(self):
        d = one(end=("closed", 29010630))
        self.assertEqual(opin(d, 29000101), pv.HISTORICAL)                    # first day, inclusive
        self.assertEqual(opin(d, 29010630), pv.HISTORICAL)                    # last day, inclusive
        self.assertEqual(opin(d, 29010701), pv.NOT_IN_FORCE)                  # day after the end
        self.assertEqual(opin(d, 28991231), pv.NOT_IN_FORCE)                  # day before the start

    def test_dated_inside_continuing_verified_is_authoritative_up_to_checked_through(self):
        d = one(end=("cv", 29050101))
        self.assertEqual(opin(d, 29000101), pv.AUTHORITATIVE)
        self.assertEqual(opin(d, 29050101), pv.AUTHORITATIVE)
        self.assertEqual(opin(d, 29050102), pv.UNVERIFIED)                    # beyond the verified horizon

    def test_dated_with_unverified_end_is_unverified(self):
        self.assertEqual(opin(one(end=("unverified",)), 29000601), pv.UNVERIFIED)

    def test_dated_with_unknown_start_is_unverified(self):
        d = one(start_ok=False, status={"start": "pending"})
        self.assertEqual(opin(d, 29000601), pv.UNVERIFIED)
        self.assertIn("start_unknown", res(build(d), 29000601).reasons)

    def test_dated_with_no_version_or_no_text_is_unverified(self):
        v = res(build(one(with_version=False)), 29000601)
        self.assertEqual((v.cls, "no_version" in v.reasons), (pv.UNVERIFIED, True))
        v = res(build(one(held=False)), 29000601)
        self.assertEqual((v.opinion, "text_not_held" in v.reasons), (pv.UNVERIFIED, True))

    # ---- undated
    def test_undated_continuing_verified_and_fresh_is_authoritative(self):
        self.assertEqual(opin(one(), None), pv.AUTHORITATIVE)

    def test_undated_cv_not_fresh_is_unverified(self):
        self.assertEqual(opin(one(end=("cv", 29000101)), None, today=29100601), pv.UNVERIFIED)   # older than 365 days
        self.assertIn("not_fresh", res(build(one(end=("cv", 29000101))), None).reasons)

    def test_undated_with_no_freshness_window_nothing_is_fresh(self):
        self.assertEqual(opin(one(fresh=None), None), pv.UNVERIFIED)
        self.assertEqual(opin(one(status={"fresh": "pending"}), None), pv.UNVERIFIED)

    def test_undated_freshness_boundary_and_future_horizon(self):
        d = one(end=("cv", 29100101), fresh=151)
        self.assertEqual(opin(d, None, today=29100601), pv.AUTHORITATIVE)     # exactly 151 days
        self.assertEqual(opin(d, None, today=29100602), pv.UNVERIFIED)        # 152
        self.assertEqual(opin(one(end=("cv", 29200101)), None, today=29100601), pv.UNVERIFIED)  # horizon in the future

    def test_undated_unverified_end_is_unverified(self):
        self.assertEqual(opin(one(end=("unverified",)), None), pv.UNVERIFIED)

    def test_undated_not_yet_started_is_not_in_force(self):
        self.assertEqual(opin(one(start=29200101), None), pv.NOT_IN_FORCE)

    def test_undated_closed_is_never_current_I6(self):
        self.assertEqual(opin(one(end=("closed", 29010630)), None), pv.NOT_IN_FORCE)          # ended before today
        self.assertEqual(opin(one(end=("closed", 29200630)), None), pv.UNVERIFIED)            # not yet ended: not promoted
        for end in (("closed", 29010630), ("closed", 29200630)):
            self.assertNotIn(opin(one(end=end), None), AUTH_HIST)

    # ---- tri-state ends and the derivation rule
    def test_tri_state_end(self):
        for end, qd, want in ((("closed", 29010630), 29000601, pv.HISTORICAL),
                              (("cv", 29100101), 29000601, pv.AUTHORITATIVE),
                              (("unverified",), 29000601, pv.UNVERIFIED)):
            self.assertEqual(opin(one(end=end), qd), want, end)

    def test_derived_end_requires_the_approved_interval_rule(self):
        for kw in ({"rule": False}, {"status": {"rule": "pending"}}, {"status": {"rule": "rejected"}}):
            d = one(end=("closed", 29010630), **kw)
            self.assertEqual(opin(d, 29000601), pv.UNVERIFIED, kw)       # end stays unverified, never guessed
            self.assertEqual(opin(d, 29020101), pv.UNVERIFIED, kw)       # and nothing is dropped on a guessed end
        self.assertEqual(opin(one(end=("closed", 29010630)), 29000601), pv.HISTORICAL)

    def test_closing_operation_must_itself_be_approved(self):
        d = one(end=("closed", 29010630), status={"close": "pending"})
        self.assertEqual(opin(d, 29020101), pv.UNVERIFIED)

    # ---- query-time conflict handling
    def test_gap_never_returns_the_nearest_version(self):
        v = res(fixture_ledger("gap", trusted_copy=True), 29010201, md=self.gap_md(), text="SYNTHETIC GAP TEXT")
        self.assertEqual((v.opinion, "gap" in v.reasons), (pv.UNVERIFIED, True))
        self.assertEqual(res(fixture_ledger("gap", trusted_copy=True), 28991231, md=self.gap_md(), text="SYNTHETIC GAP TEXT").opinion,
                         pv.HISTORICAL)

    def test_overlap_is_unverified_at_query_time(self):
        L = fixture_ledger("overlap", trusted_copy=True)
        v = res(L, 29000801, md=self.gap_md(), text="SYNTHETIC OVERLAP TEXT")
        self.assertEqual((v.opinion, "overlap" in v.reasons), (pv.UNVERIFIED, True))

    @staticmethod
    def gap_md():
        return {"manifest_id": "synthetic-s9", "sha256": FILE_SHA, "provision_id": "SECTION 1", "part": 1, "parts": 1,
                "page_start": 3, "page_end": 4}

    def test_same_day_closing_operations_make_the_provision_unverified(self):
        L = fixture_ledger("rule81_conflicting_targets", trusted_copy=True)
        md = {"manifest_id": "synthetic-rules-ch4", "sha256": FILE_SHA, "provision_id": "RULE 81", "part": 1,
              "parts": 1, "page_start": 10, "page_end": 11}
        v = res(L, 29000601, md=md, text="SYNTHETIC RULE 81 SNAPSHOT")
        self.assertIn("ordering_ambiguity", v.reasons)
        self.assertNotIn(v.opinion, AUTH_HIST)

    # ---- the G.O. 53 / G.O. 16 shape, with synthetic dates
    def test_go53_go16_shape(self):
        L = fixture_ledger("go53_go16_synthetic", trusted_copy=True)
        md, t = LoaderTests.md53(), LoaderTests.t53()
        undated = res(L, None, md=md, text=t)
        self.assertTrue(undated.partial)                                      # col1 current, col8 deleted
        self.assertEqual(undated.cls, pv.BLOCKED)                             # a partial chunk never answers current law
        self.assertIn(res(L, 29010401, md=md, text=t).cls, (pv.UNVERIFIED,))
        self.assertTrue(res(L, 29010401, md=md, text=t).partial)
        self.assertEqual(res(L, 29000101, md=md, text=t).cls, pv.UNVERIFIED)  # before G.O. 53: no text held for that date
        self.assertIn("text_not_held", res(L, 29000101, md=md, text=t).reasons)
        for qd in (None, 29000101, 29010301, 29010401, 29020531, 29020601, 29100101):
            self.assertNotIn(res(L, qd, md=md, text=t).cls, AUTH_HIST + (pv.NOT_IN_FORCE,) if qd is None else AUTH_HIST)

    def test_unapproved_go53_go16_restricts_without_any_approval(self):
        L = fixture_ledger("unapproved_and_candidate", trusted_copy=True)
        md, t = LoaderTests.md53(), LoaderTests.t53()
        for qd in (None, 29000101, 29010401, 29020601, 29100101):
            v = res(L, qd, md=md, text=t)
            self.assertIn(v.cls, (pv.UNVERIFIED, pv.BLOCKED), qd)
            self.assertNotIn(v.opinion, AUTH_HIST + (pv.NOT_IN_FORCE,), qd)
            self.assertIn("pending_operation", v.reasons)
        self.assertEqual(res(L, None, md=md, text=t).cls, pv.BLOCKED)         # marked partial: blocked as current law
        self.assertTrue(res(L, None, md=md, text=t).partial)


# =============================================================================================== I4: unapproved facts

class TrustTests(unittest.TestCase):
    """Remove any one condition for authority and the chunk is never authoritative or historical."""

    def full(self, **kw):
        d = one(**kw)
        self.assertEqual(opin(d, None), pv.AUTHORITATIVE, "baseline must be authoritative under full trust")
        return d

    def test_baseline_needs_every_condition(self):
        base = one()
        self.assertEqual(opin(base, None), pv.AUTHORITATIVE)
        self.assertEqual(opin(one(end=("closed", 29010630)), 29000601), pv.HISTORICAL)

    def test_not_bound_means_nothing_is_trusted(self):
        for bound in (False, None, 1, "true", "yes", [1], object()):
            with self.subTest(bound):
                L = build(one())
                self.assertNotIn(res(L, None, bound=bound).opinion, AUTH_HIST + (pv.NOT_IN_FORCE,))
                self.assertNotIn(res(L, 29000601, bound=bound).opinion, AUTH_HIST + (pv.NOT_IN_FORCE,))
        L = build(one(end=("closed", 29010630)))
        self.assertEqual(res(L, 29020101, bound=False).opinion, pv.UNVERIFIED)      # a drop needs trust too
        self.assertEqual(res(L, 29020101, bound=True).opinion, pv.NOT_IN_FORCE)
        self.assertEqual(pv.resolve_chunk(L, MD, TXT, 29020101, TODAY, "restrict").opinion, pv.UNVERIFIED)  # default bound=False

    def test_decision_status_other_than_approved_never_authorises(self):
        for role in ("start", "end", "cov", "fresh"):
            for status in ("pending", "evidence_incomplete", "evidence_complete", "rejected", "revoked"):
                with self.subTest(role=role, status=status):
                    d = one(status={role: status})
                    self.assertNotIn(opin(d, None), AUTH_HIST)
        for status in ("pending", "rejected", "revoked"):
            self.assertNotIn(opin(one(end=("closed", 29010630), status={"close": status}), 29000601), AUTH_HIST)
            self.assertNotIn(opin(one(end=("closed", 29010630), status={"rule": status}), 29000601), AUTH_HIST)
            self.assertNotIn(opin(one(end=("closed", 29010630), status={"start": status}), 29000601), AUTH_HIST)

    def test_proposed_facts_never_authorise_and_candidate_is_never_read(self):
        d = one(start_ok=False)
        self.assertNotIn(opin(d, None), AUTH_HIST)
        self.assertNotIn(opin(d, 29000601), AUTH_HIST)
        for cand in (1, 29000101, 29991231, None):
            e = copy.deepcopy(d)
            if cand is None:
                e["operations"][0]["effective_from"].pop("candidate")
            else:
                e["operations"][0]["effective_from"]["candidate"] = cand if cand != 1 else 29000102
            self.assertEqual(res(build(e), 29000601), res(build(d), 29000601))
        # A candidate carried by an APPROVED fact is not the date used either.
        e = one()
        e["operations"][0]["effective_from"]["candidate"] = 29990101
        self.assertEqual(res(build(e), 29000601), res(build(one()), 29000601))

    def test_a_non_commencement_fact_object_is_ignored_even_if_constructed_in_code(self):
        L = build(one())
        ops = tuple(dataclasses.replace(o, effective_from=dataclasses.replace(o.effective_from, kind="publication"))
                    for o in L.operations)
        versions = tuple(dataclasses.replace(v, interval=dataclasses.replace(
            v.interval, start=dataclasses.replace(v.interval.start, kind="gazette_direction"))) for v in L.versions)
        bad = dataclasses.replace(L, operations=ops, versions=versions)
        for qd in (None, 29000601):
            self.assertNotIn(res(bad, qd).opinion, AUTH_HIST)

    def test_unapproved_coverage_cannot_authorise(self):
        d = one(status={"cov": "pending"})
        v = res(build(d), None)
        self.assertEqual(v.opinion, pv.UNVERIFIED)
        self.assertIn("coverage_unapproved", v.reasons)
        d = one()
        d["coverage"][0].pop("decision_ref")
        self.assertEqual(res(build(d), None).opinion, pv.UNVERIFIED)

    def test_unapproved_ledger_fixture_never_authorises_or_drops(self):
        L = fixture_ledger("unapproved_and_candidate")
        md, t = LoaderTests.md53(), LoaderTests.t53()
        for bound in (True, False):
            for qd in (None, 29000101, 29010301, 29010302, 29020601, 29020602, 29100101, 29991231):
                v = res(L, qd, bound=bound, md=md, text=t)
                self.assertIn(v.opinion, (pv.UNVERIFIED, pv.BLOCKED))
                self.assertIn(v.cls, (pv.UNVERIFIED, pv.BLOCKED))

    def test_candidate_dates_alone_never_drop_a_chunk(self):
        d = one(start=29000101, start_ok=False)
        d["operations"][0]["effective_from"]["candidate"] = 29900101       # "starts in the far future"
        self.assertEqual(opin(d, None), pv.UNVERIFIED)                     # not NOT_IN_FORCE

    def test_shadow_and_restrict_never_return_authority_even_with_full_trust(self):
        for mode in ("shadow", "restrict", "SHADOW", " restrict "):
            for qd in (None, 29000601):
                for d in (one(), one(end=("closed", 29010630))):
                    v = res(build(d), qd, mode=mode)
                    self.assertNotIn(v.cls, AUTH_HIST, (mode, qd))
                    if v.opinion in AUTH_HIST:
                        self.assertEqual(v.cls, pv.UNVERIFIED)
                        self.assertIn("ledger_cannot_create_authority", v.reasons)

    def test_off_and_enforce_and_garbage_modes_do_not_read_the_ledger(self):
        self.assertIs(pv.ENFORCE_LOCKED, True)
        self.assertNotIn("enforce", pv.MODES)
        self.assertEqual(pv.MODES, ("off", "shadow", "restrict"))
        for mode in ("off", "enforce", "ENFORCE", "", None, 3, "on", "restrict ;", ["restrict"]):
            with self.subTest(mode):
                v = res(build(one(end=("closed", 29010630))), 29020101, mode=mode)
                if mode in ("off",) or pv.normalize_mode(mode) == "off":
                    self.assertFalse(v.covered)
                    self.assertIsNone(v.opinion)
                self.assertNotIn(v.cls, AUTH_HIST)
        self.assertEqual(pv.normalize_mode("enforce"), "off")

    def test_module_never_branches_on_enforce(self):
        src = (ROOT / "backend" / "provision_validity.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                for c in node.comparators:
                    self.assertFalse(isinstance(c, ast.Constant) and c.value == "enforce")
            if isinstance(node, ast.If):
                self.assertNotIn("ENFORCE_LOCKED", ast.dump(node.test))


# ================================================================================================ I3: only restrict

class MonotoneTests(unittest.TestCase):
    def verdicts(self):
        out = [pv.Verdict(c, (), (), covered=True) for c in pv.CLASSES]
        out += [pv.Verdict(c, (), (), covered=False) for c in pv.CLASSES]
        return out

    def test_combine_is_never_better_than_legacy(self):
        for legacy in pv.CLASSES:
            for v in self.verdicts():
                got = pv.combine(legacy, v)
                self.assertLessEqual(pv.rank(got), pv.rank(legacy), (legacy, v))
                if not v.covered:
                    self.assertEqual(got, legacy)
                if got in AUTH_HIST:
                    self.assertEqual(got, legacy)

    def test_combine_can_demote_but_a_verdict_cannot_promote(self):
        self.assertEqual(pv.combine(pv.AUTHORITATIVE, pv.Verdict(pv.NOT_IN_FORCE, covered=True)), pv.NOT_IN_FORCE)
        self.assertEqual(pv.combine(pv.AUTHORITATIVE, pv.Verdict(pv.UNVERIFIED, covered=True)), pv.UNVERIFIED)
        self.assertEqual(pv.combine(pv.UNVERIFIED, pv.Verdict(pv.AUTHORITATIVE, covered=True)), pv.UNVERIFIED)
        self.assertEqual(pv.combine(pv.NOT_IN_FORCE, pv.Verdict(pv.AUTHORITATIVE, covered=True)), pv.NOT_IN_FORCE)
        self.assertEqual(pv.combine(pv.BLOCKED, pv.Verdict(pv.UNVERIFIED, covered=True)), pv.BLOCKED)
        self.assertEqual(pv.combine(pv.UNVERIFIED, pv.Verdict(pv.HISTORICAL, covered=True)), pv.UNVERIFIED)
        self.assertEqual(pv.combine(pv.AUTHORITATIVE, pv.Verdict(pv.HISTORICAL, covered=True)), pv.AUTHORITATIVE)  # positive = no restriction

    def test_combine_fails_closed_on_junk(self):
        self.assertEqual(pv.combine("whatever", pv.Verdict(pv.UNVERIFIED, covered=True)), pv.BLOCKED)
        self.assertEqual(pv.combine(pv.AUTHORITATIVE, pv.Verdict("whatever", covered=True)), pv.BLOCKED)
        self.assertEqual(pv.combine(pv.AUTHORITATIVE, None), pv.AUTHORITATIVE)   # nothing to say = legacy (covered False)

    def test_adding_an_unapproved_restriction_never_improves_the_class(self):
        base = one()
        for kind in pv.CLOSING_OPS:
            d = copy.deepcopy(base)
            d["decisions"].append({"decision_id": "LD-099", "status": "pending", "subject": "x"})
            d["operations"].append({"id": "OP-X", "type": kind, "source": ACTK, "targets": [P],
                                    "effective_from": fct(29000102, "LD-099", approved=False)})
            for qd in (None, 29000601):
                a, b = res(build(base), qd), res(build(d), qd)
                self.assertLessEqual(pv.rank(b.opinion), pv.rank(a.opinion), (kind, qd))
        d = copy.deepcopy(base)
        d["decisions"].append({"decision_id": "LD-099", "status": "pending", "subject": "x"})
        d["operations"].append({"id": "OP-X", "type": "delete", "source": ACTK, "targets": [P],
                                "effective_from": fct(29000102, "LD-099", approved=False)})
        self.assertEqual(res(build(d), None).opinion, pv.UNVERIFIED)      # was AUTHORITATIVE: restriction applied
        self.assertIn("pending_operation", res(build(d), None).reasons)

    def test_withdrawing_an_approval_never_adds_authority(self):
        for end in (("cv", 29100101), ("closed", 29010630)):
            for qd in (None, 29000601):
                full = opin(one(end=end), qd)
                for role in ("start", "end", "cov", "rule", "fresh", "close"):
                    got = opin(one(end=end, status={role: "revoked"}), qd)
                    self.assertLessEqual(pv.rank(got) >= 3, pv.rank(full) >= 3, (end, qd, role))


# ================================================================================================ I5: partial chunks

class PartialTests(unittest.TestCase):
    MD = {"manifest_id": "synthetic-s9", "sha256": FILE_SHA, "provision_id": "TABLE", "part": 1, "parts": 1,
          "page_start": 3, "page_end": 4}
    T = "SYNTHETIC PARTIAL TEXT"

    def r(self, qd, **kw):
        return res(fixture_ledger("partial_chunk", trusted_copy=True), qd, md=self.MD, text=self.T, **kw)

    def test_a_partial_chunk_is_blocked_for_current_law(self):
        v = self.r(None)
        self.assertTrue(v.partial)
        self.assertEqual((v.cls, v.opinion), (pv.BLOCKED, pv.BLOCKED))
        self.assertIn("partial", v.reasons)

    def test_a_partial_chunk_is_never_authoritative_for_any_date(self):
        for qd in [None] + [d for d in (28991231, 29000101, 29000615, 29001231, 29010101, 29010102, 29050101, 29100101, 29100102)]:
            for mode in ("shadow", "restrict"):
                for bound in (True, False):
                    v = self.r(qd, mode=mode, bound=bound)
                    self.assertNotIn(v.cls, AUTH_HIST, (qd, mode, bound))
                    self.assertNotIn(v.opinion, AUTH_HIST, (qd, mode, bound))
                    if v.partial:
                        self.assertIn(v.cls, (pv.BLOCKED, pv.UNVERIFIED, pv.NOT_IN_FORCE))
                        if qd is None:
                            self.assertIn(v.cls, (pv.BLOCKED, pv.NOT_IN_FORCE))

    def test_partial_for_a_dated_question_is_not_better_than_unverified(self):
        v = self.r(29000615)                      # both provisions in force that day, different intervals
        self.assertTrue(v.partial)
        self.assertEqual(v.cls, pv.UNVERIFIED)

    def test_a_partial_chunk_cannot_reach_the_current_law_path_after_combine(self):
        v = self.r(None)
        for legacy in pv.CLASSES:
            self.assertIn(pv.combine(legacy, v), (pv.BLOCKED, pv.NOT_IN_FORCE))

    def test_one_shared_interval_is_not_partial(self):
        d = one()
        d["provisions"].append({"key": f"{ACTK}#s2"})
        d["operations"][0]["targets"].append(f"{ACTK}#s2")
        d["versions"].append({"key": f"{ACTK}#s2@1", "provision": f"{ACTK}#s2", "text": "held", "created_by_op": "OP-A",
                              "end": {"state": "continuing_verified", "checked_through": 29100101, "decision_ref": "LD-002"}})
        d["coverage"][0]["provisions"].append(f"{ACTK}#s2")
        v = res(build(d), None)
        self.assertFalse(v.partial)
        self.assertEqual(v.opinion, pv.AUTHORITATIVE)

    def test_there_is_no_switch_to_let_a_partial_chunk_through(self):
        import inspect
        params = set(inspect.signature(pv.resolve_chunk).parameters)
        self.assertEqual(params, {"ledger", "metadata", "text", "query_date", "today", "mode", "bound"})
        self.assertFalse([n for n in dir(pv) if "partial" in n.lower() and n not in ("Verdict",)])

    def test_every_provision_not_in_force_is_not_in_force_even_when_partial(self):
        d = copy.deepcopy(raw("partial_chunk"))
        d["fixture"] = False
        for o in d["operations"]:
            o["targets"] = [f"{ACTK}#a", f"{ACTK}#b"] if o["id"] == "OP-B" else o["targets"]
        L = build(d)
        v = res(L, 28991231, md=self.MD, text=self.T)               # before everything started
        self.assertNotIn(v.cls, AUTH_HIST)


# ================================================================================================ coverage selectors

class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.L = build(one())

    def test_exact_match(self):
        v = res(self.L, None)
        self.assertTrue(v.covered)
        self.assertEqual(v.provisions, (P,))

    def test_stale_when_any_selector_field_or_the_text_changes(self):
        changes = [{"sha256": SH("other")}, {"page_start": 2}, {"page_end": 9}, {"part": 2}, {"parts": 2}]
        for ch in changes:
            with self.subTest(ch):
                v = res(self.L, None, md=dict(MD, **ch))
                self.assertEqual((v.cls, v.covered, v.reasons), (pv.UNVERIFIED, True, ("stale_coverage",)))
                self.assertNotIn(v.opinion, AUTH_HIST)
        v = res(self.L, None, text=TXT + " ")
        self.assertEqual((v.cls, v.reasons), (pv.UNVERIFIED, ("stale_coverage",)))
        v = res(self.L, None, text="")
        self.assertEqual(v.reasons, ("stale_coverage",))

    def test_selector_types_are_strict(self):
        for ch in ({"part": "1"}, {"part": True}, {"parts": 1.0}, {"page_start": "1"}):
            with self.subTest(ch):
                self.assertEqual(res(self.L, None, md=dict(MD, **ch)).reasons, ("stale_coverage",))

    def test_stale_fixture(self):
        L = fixture_ledger("stale_coverage", trusted_copy=True)
        md = {"manifest_id": "synthetic-s9", "sha256": FILE_SHA, "provision_id": "SECTION 1", "part": 1, "parts": 1,
              "page_start": 3, "page_end": 4}
        self.assertEqual(res(L, 29000601, md=md, text="SYNTHETIC ORIGINAL TEXT").opinion, pv.AUTHORITATIVE)
        v = res(L, 29000601, md=md, text="SYNTHETIC CHANGED TEXT")
        self.assertEqual((v.cls, v.reasons), (pv.UNVERIFIED, ("stale_coverage",)))

    def test_uncovered_chunks_are_left_to_the_legacy_path(self):
        for md in (dict(MD, provision_id="OTHER"), dict(MD, manifest_id="other"),
                   {k: v for k, v in MD.items() if k != "manifest_id"}, {}):
            v = res(self.L, None, md=md)
            self.assertEqual((v.covered, v.reasons, v.opinion), (False, ("no_coverage",), None))
            for legacy in pv.CLASSES:
                self.assertEqual(pv.combine(legacy, v), legacy)

    def test_a_stale_chunk_demotes_a_legacy_authoritative_chunk(self):
        self.assertEqual(pv.combine(pv.AUTHORITATIVE, res(self.L, None, text="changed")), pv.UNVERIFIED)

    def test_same_number_acts_cannot_touch_each_other_C8(self):
        L = fixture_ledger("same_number_acts", trusted_copy=True)
        cen = {"manifest_id": "synthetic-central-8", "sha256": FILE_SHA, "provision_id": "SECTION 1", "part": 1,
               "parts": 1, "page_start": 3, "page_end": 4}
        tg = dict(cen, manifest_id="synthetic-telangana-8")
        vc = res(L, None, today=29000601, md=cen, text="SYNTHETIC CENTRAL TEXT")
        vt = res(L, None, today=29000601, md=tg, text="SYNTHETIC TELANGANA TEXT")
        self.assertEqual(vc.provisions, ("IN:ACT:S8/2899#s1",))
        self.assertEqual(vt.provisions, ("TG:ACT:S8/2899#s1",))
        vc = res(L, 29000101, today=29000601, md=cen, text="SYNTHETIC CENTRAL TEXT")
        vt = res(L, 29000101, today=29000601, md=tg, text="SYNTHETIC TELANGANA TEXT")
        self.assertEqual((vc.opinion, vt.opinion), (pv.AUTHORITATIVE, pv.AUTHORITATIVE))
        # Swapping the texts or manifest ids finds only stale coverage, never the other Act's provision.
        self.assertEqual(res(L, None, today=29000601, md=cen, text="SYNTHETIC TELANGANA TEXT").provisions, ())
        self.assertEqual(res(L, None, today=29000601, md=tg, text="SYNTHETIC CENTRAL TEXT").provisions, ())
        # A different commencement per Act: the Telangana one started earlier and does not borrow the central date.
        self.assertEqual(res(L, 28990401, md=tg, text="SYNTHETIC TELANGANA TEXT").opinion, pv.AUTHORITATIVE)
        self.assertEqual(res(L, 28990401, md=cen, text="SYNTHETIC CENTRAL TEXT").opinion, pv.NOT_IN_FORCE)


class BadInputTests(unittest.TestCase):
    def test_bad_inputs_fail_closed_without_raising(self):
        L = build(one())
        cases = [dict(query_date=20260230), dict(query_date="29000101"), dict(query_date=True), dict(today=None),
                 dict(today=20261301), dict(today=0)]
        for kw in cases:
            args = dict(query_date=None, today=TODAY)
            args.update(kw)
            with self.subTest(kw):
                v = pv.resolve_chunk(L, MD, TXT, args["query_date"], args["today"], "restrict", bound=True)
                self.assertEqual((v.cls, v.covered), (pv.BLOCKED, True))
        for md, text in ((None, TXT), (MD, None), (MD, b"x"), ([], TXT)):
            v = pv.resolve_chunk(L, md, text, None, TODAY, "restrict", bound=True)
            self.assertEqual((v.cls, v.covered), (pv.BLOCKED, True))
        for ledger in (None, {}, "ledger"):
            v = pv.resolve_chunk(ledger, MD, TXT, None, TODAY, "restrict", bound=True)
            self.assertEqual((v.cls, v.covered, v.reasons), (pv.UNVERIFIED, False, ("no_ledger",)))

    def test_resolution_is_deterministic(self):
        L = build(one())
        self.assertEqual(res(L, 29000601), res(L, 29000601))


# ============================================================================== M1: closure links must agree

CLOSER_ID = "LD-050"


def with_closer(op_type="delete", *, link=True, date=29050101, status="approved", fact_approved=True):
    """`one()` (P@1 open from 29000101) plus an approved closing operation, linked to P@1 through closed_by_op or not."""
    d = one()
    d["decisions"].append({"decision_id": CLOSER_ID, "status": status, "subject": "closer"})
    d["operations"].append({"id": "OP-DEL", "type": op_type, "source": ACTK, "targets": [P],
                            "effective_from": fct(date, CLOSER_ID, fact_approved)})
    if link:
        d["versions"][0].update(closed_by_op="OP-DEL", end={"state": "closed"})
    return d


def c3b(L):
    return sorted((p.subject, p.severity) for p in pv.validate(L) if p.code == "C3b")


class ClosureLinkTests(unittest.TestCase):
    """Review finding M1: an approved closing operation that closes nothing must be an error and never leave the
    provision authoritative. Before the fix the ledger below reported `authoritative` and `validate()` was silent."""

    TYPES = ("delete", "repeal", "omit", "substitute", "amend_words")   # the model's closing types (CLOSING_OPS)

    def test_the_model_has_no_other_closing_types(self):
        self.assertEqual(set(pv.CLOSING_OPS), set(self.TYPES))

    def test_unlinked_approved_closer_is_a_validation_error(self):
        for typ in self.TYPES:
            with self.subTest(typ):
                L = build(with_closer(typ, link=False))
                self.assertEqual(c3b(L), [(P, "error")])
                msg = next(p.message for p in pv.validate(L) if p.code == "C3b")
                self.assertIn("OP-DEL", msg)
                self.assertIn("not linked", msg)

    def test_unlinked_approved_closer_never_leaves_the_provision_authoritative(self):
        for typ in self.TYPES:
            L = build(with_closer(typ, link=False))
            for qd in (None, 29000601, 29041231, 29050101, 29060101, 29100101):
                for bound in (True, False):
                    with self.subTest(typ=typ, qd=qd, bound=bound):
                        v = res(L, qd, bound=bound)
                        self.assertNotIn(v.opinion, AUTH_HIST)
                        self.assertNotIn(v.cls, AUTH_HIST)
                        if bound:
                            self.assertEqual(v.opinion, pv.UNVERIFIED)
                            self.assertIn("closure_unlinked", v.reasons)
                        self.assertEqual(pv.combine(pv.AUTHORITATIVE, v), pv.UNVERIFIED)

    def test_the_m1_reproduction_after_the_deletion_date(self):
        L = build(with_closer("delete", link=False, date=29050101))
        self.assertEqual(opin(with_closer("delete", link=False, date=29050101), 29060101), pv.UNVERIFIED)
        self.assertEqual(res(L, None).opinion, pv.UNVERIFIED)

    def test_a_correctly_linked_closer_behaves_as_before(self):
        for typ in self.TYPES:
            d = with_closer(typ, link=True)
            L = build(d)
            with self.subTest(typ):
                self.assertEqual(c3b(L), [])
                self.assertEqual([p for p in pv.validate(L) if p.severity == "error"], [])
                self.assertEqual(opin(d, 29000101), pv.HISTORICAL)          # first day
                self.assertEqual(opin(d, 29041231), pv.HISTORICAL)          # last day: day before the operation
                self.assertEqual(opin(d, 29050101), pv.NOT_IN_FORCE)        # the operation's own day
                self.assertEqual(opin(d, None), pv.NOT_IN_FORCE)            # undated: closed, ended before today
                self.assertNotIn("closure_unlinked", res(L, 29000601).reasons)

    def test_linked_ledger_matches_the_plain_closed_builder(self):
        a, b = build(with_closer("delete", link=True, date=29050101)), build(one(end=("closed", 29041231)))
        for qd in (None, 28991231, 29000101, 29041231, 29050101):
            self.assertEqual(res(a, qd).opinion, res(b, qd).opinion, qd)

    def test_a_closing_link_to_an_operation_that_does_not_target_the_version(self):
        """The link exists, but on the wrong provision's version: P stays open and Q is closed by an operation that
        never targeted it. Both are errors, and neither may be authoritative or historical."""
        d = with_closer("delete", link=False)
        q = f"{ACTK}#s2"
        d["provisions"].append({"key": q})
        d["operations"][0]["targets"].append(q)                           # OP-A creates versions of both
        d["versions"].append({"key": f"{q}@1", "provision": q, "text": "held", "created_by_op": "OP-A",
                              "closed_by_op": "OP-DEL", "end": {"state": "closed"}})
        d["coverage"].append({"selector": dict(MD, provision_id="SECTION 2", text_sha256=SH("Q TEXT")),
                              "provisions": [q], "decision_ref": "LD-003"})
        L = build(d)
        self.assertEqual(c3b(L), [(P, "error"), (q, "error")])
        kinds = " | ".join(p.message for p in pv.validate(L) if p.code == "C3b")
        self.assertIn("not linked", kinds)
        self.assertIn("does not target it", kinds)
        md2 = dict(MD, provision_id="SECTION 2")
        for qd in (None, 29000601, 29060101):
            self.assertNotIn(res(L, qd).opinion, AUTH_HIST, qd)
            self.assertNotIn(res(L, qd, md=md2, text="Q TEXT").opinion, AUTH_HIST, qd)   # no fabricated HISTORICAL for Q
        self.assertIn("closure_unlinked", res(L, 29000601, md=md2, text="Q TEXT").reasons)

    def test_a_closing_link_swapped_onto_the_earlier_version_of_the_same_provision(self):
        def chain(first_closed_by, second_closed_by):
            d = one()
            d["decisions"] += [{"decision_id": "LD-051", "status": "approved", "subject": "b"},
                               {"decision_id": "LD-052", "status": "approved", "subject": "c"}]
            d["operations"] = [
                {"id": "OP-A", "type": "insert", "source": ACTK, "targets": [P], "effective_from": fct(29000101, "LD-001")},
                {"id": "OP-B", "type": "substitute", "source": ACTK, "targets": [P], "effective_from": fct(29010101, "LD-051")},
                {"id": "OP-DEL", "type": "delete", "source": ACTK, "targets": [P], "effective_from": fct(29020101, "LD-052")}]
            v1 = {"key": f"{P}@1", "provision": P, "text": "held", "created_by_op": "OP-A", "closed_by_op": first_closed_by,
                  "end": {"state": "closed"}}
            v2 = {"key": f"{P}@2", "provision": P, "text": "held", "created_by_op": "OP-B"}
            if second_closed_by:
                v2.update(closed_by_op=second_closed_by, end={"state": "closed"})
            else:
                v2["end"] = {"state": "continuing_verified", "checked_through": 29100101, "decision_ref": "LD-002"}
            d["versions"] = [v1, v2]
            return d

        good = chain("OP-B", "OP-DEL")
        self.assertEqual(c3b(build(good)), [])
        self.assertEqual(opin(good, 29000601), pv.HISTORICAL)
        self.assertEqual(opin(good, 29010601), pv.HISTORICAL)
        self.assertEqual(opin(good, 29020601), pv.NOT_IN_FORCE)

        bad = chain("OP-DEL", None)                       # the deletion closes version 1; version 2 is left open
        L = build(bad)
        self.assertEqual(c3b(L), [(P, "error"), (P, "error")])     # OP-B closes nothing; OP-DEL leaves version 2 open
        for qd in (None, 29000601, 29010601, 29020601, 29100101):
            self.assertNotIn(res(L, qd).opinion, AUTH_HIST, qd)

    def test_what_is_not_flagged(self):
        # Unapproved or unbound closers are not "approved": they restrict through the pending-operation rule instead.
        for kw in ({"status": "pending"}, {"status": "rejected"}, {"fact_approved": False}):
            d = with_closer("delete", link=False, **kw)
            L = build(d)
            with self.subTest(kw):
                self.assertEqual(c3b(L), [])
                v = res(L, None)
                self.assertEqual(v.opinion, pv.UNVERIFIED)
                self.assertIn("pending_operation", v.reasons)
                self.assertNotIn("closure_unlinked", v.reasons)
        # An operation dated before the version starts does not touch it.
        self.assertEqual(c3b(build(with_closer("delete", link=False, date=28990101))), [])
        # Unbound: nothing is trusted, so no approved closer exists to be unlinked, and nothing is authoritative.
        v = res(build(with_closer("delete", link=False)), None, bound=False)
        self.assertNotIn("closure_unlinked", v.reasons)
        self.assertNotIn(v.opinion, AUTH_HIST)

    def test_shipped_fixtures_have_no_closure_inconsistency(self):
        for n in FIXTURE_NAMES:
            self.assertEqual(c3b(fixture_ledger(n)), [], n)

    def test_the_fix_cannot_create_authority(self):
        """Linking correctly never yields AUTHORITATIVE from the resolver; trust conditions are unchanged."""
        d = with_closer("delete", link=True)
        for qd in (None, 29000601, 29060101):
            self.assertNotIn(res(build(d), qd).cls, AUTH_HIST)
        fx = dict(with_closer("delete", link=False), fixture=True)
        L = pv.load_ledger(json.dumps(fx).encode(), allow_fixture=True)
        for qd in (None, 29000601, 29060101):
            self.assertNotIn(res(L, qd).opinion, AUTH_HIST + (pv.NOT_IN_FORCE,))


# ================================================================================ seeded property tests (>= 2000)

POOL = [29000101, 29000601, 29010101, 29010601, 29020101, 29030101]
TODAYS = [29050101, 29100601, 29200101]
STATUSES = ["approved"] * 6 + ["pending", "rejected", "revoked", "evidence_complete", "evidence_incomplete"]


def rand_case(rng):
    """A random but loadable ledger plus a chunk, query and legacy class."""
    decisions = []
    ok = rng.random() < 0.45        # a fully approved ledger, so authoritative and historical outcomes are reached

    def dec(status=None):
        did = f"LD-{len(decisions) + 1:03d}"
        decisions.append({"decision_id": did, "status": "approved" if ok else (status or rng.choice(STATUSES)), "subject": "r"})
        return did

    def fact(date):
        ref = dec()
        if ok or rng.random() < 0.8:
            return {"state": "approved", "kind": "commencement", "date": date, "candidate": rng.choice(POOL), "decision_ref": ref}
        return {"state": rng.choice(["proposed", "unknown"]), "kind": "commencement", "candidate": rng.choice(POOL), "decision_ref": ref}

    provs, ops, versions = [], [], []
    for pi in range(rng.randint(1, 4)):
        key = f"{ACTK}#p{pi}"
        provs.append({"key": key})
        k = 0 if rng.random() < 0.08 else rng.randint(1, 3)
        dates = sorted(rng.sample(POOL, k + 1))
        for i in range(k):
            ops.append({"id": f"OP-{pi}-{i}", "type": "insert" if i == 0 else "substitute", "source": ACTK,
                        "targets": [key], "effective_from": fact(dates[i])})
        closer = None
        if k and rng.random() < 0.4:
            closer = {"id": f"OP-{pi}-end", "type": rng.choice(["delete", "omit", "repeal"]), "source": ACTK,
                      "targets": [key], "effective_from": fact(dates[k])}
            ops.append(closer)
        for i in range(k):
            nxt = f"OP-{pi}-{i + 1}" if i + 1 < k else (closer["id"] if closer else None)
            v = {"key": f"{key}@{i + 1}", "provision": key, "text": "held" if rng.random() < 0.9 else "not_held",
                 "created_by_op": f"OP-{pi}-{i}"}
            if nxt:
                v.update(closed_by_op=nxt, end={"state": "closed"})
            elif rng.random() < 0.75:
                v["end"] = {"state": "continuing_verified", "checked_through": rng.choice([29030101, 29100101, 29100101]),
                            "decision_ref": dec()}
            else:
                v["end"] = {"state": "unverified"}
            versions.append(v)
    text = rng.choice(["T1", "T2"])
    covered = rng.sample([p["key"] for p in provs], 1 if rng.random() < 0.75 else rng.randint(1, len(provs)))
    sel = {"manifest_id": "m1", "sha256": FILE_SHA, "provision_id": "S", "part": 1, "parts": 1, "page_start": 1,
           "page_end": 2, "text_sha256": SH(text)}
    d = {"schema_version": 1, "instruments": [{"key": ACTK, "kind": "ACT", "jurisdiction": "TG", "manifest_ids": ["m1"]}],
         "provisions": provs, "operations": ops, "versions": versions,
         "coverage": [{"selector": sel, "provisions": covered, "decision_ref": dec()}]}
    if ok or rng.random() < 0.85:
        d["interval_rule"] = {"rule": pv.INTERVAL_RULE, "decision_ref": dec()}
    if ok or rng.random() < 0.7:
        d["freshness_window"] = {"days": rng.choice([0, 30, 365, 5000, 5000]), "decision_ref": dec()}
    if rng.random() < 0.03:
        d["fixture"] = True
    d["decisions"] = decisions
    md = {k: v for k, v in sel.items() if k != "text_sha256"}
    if rng.random() < 0.08:
        md[rng.choice(["sha256", "part", "page_end"])] = rng.choice([7, "x", FILE_SHA[::-1]])
    if rng.random() < 0.08:
        text = "CHANGED"
    qd = None if rng.random() < 0.4 else rng.choice(POOL + [28991231, 29000102, 29010102, 29120101])
    return d, md, text, qd, rng.choice(TODAYS), rng.choice(list(pv.MODES) + ["enforce", "bogus"]), \
        rng.choice([True, True, True, False, None, 1]), rng.choice(pv.CLASSES)


def randomise_candidates(obj, rng):
    if isinstance(obj, dict):
        return {k: (rng.choice(POOL + [29991231]) if k == "candidate" and v is not None else randomise_candidates(v, rng))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [randomise_candidates(x, rng) for x in obj]
    return obj


class PropertyTests(unittest.TestCase):
    N = 6000

    def test_invariants_over_random_ledgers_and_chunks(self):
        rng = random.Random(20260314)
        stats = dict(auth=0, hist=0, nif=0, partial=0, covered=0, fixture=0, stale=0, capped=0, m1=0)
        for case in range(self.N):
            d, md, text, qd, today, mode, bound, legacy = rand_case(rng)
            L = build(d, allow_fixture=True)
            v = pv.resolve_chunk(L, md, text, qd, today, mode, bound=bound)
            ctx = (case, mode, bound, qd, v)
            trusted = bound is True and not L.fixture
            # I3: the verdict itself is never authority; combine never improves on legacy.
            self.assertNotIn(v.cls, AUTH_HIST, ctx)
            got = pv.combine(legacy, v)
            self.assertLessEqual(pv.rank(got), pv.rank(legacy), ctx)
            if got in AUTH_HIST:
                self.assertEqual(got, legacy, ctx)
            if pv.normalize_mode(mode) == "off":
                self.assertEqual((v.covered, v.opinion), (False, None), ctx)
                self.assertEqual(got, legacy, ctx)
                continue
            self.assertEqual(v, pv.resolve_chunk(L, md, text, qd, today, mode, bound=bound), ctx)   # deterministic
            if not v.covered:
                self.assertEqual(got, legacy, ctx)
                continue
            stats["covered"] += 1
            stats["fixture"] += L.fixture
            stats["stale"] += "stale_coverage" in v.reasons
            # I4: no trust, no authority and no drop.
            if not trusted:
                self.assertNotIn(v.opinion, AUTH_HIST + (pv.NOT_IN_FORCE,), ctx)
            # I6: a closed or historical version never answers an undated question.
            if qd is None:
                self.assertNotEqual(v.opinion, pv.HISTORICAL, ctx)
            # I5: partial chunks never answer current law and are never authoritative.
            if v.partial:
                stats["partial"] += 1
                self.assertNotIn(v.opinion, AUTH_HIST, ctx)
                self.assertIn(v.cls, (pv.BLOCKED, pv.NOT_IN_FORCE) if qd is None else (pv.UNVERIFIED, pv.NOT_IN_FORCE), ctx)
            stats["auth"] += v.opinion == pv.AUTHORITATIVE
            stats["hist"] += v.opinion == pv.HISTORICAL
            stats["nif"] += v.opinion == pv.NOT_IN_FORCE
            stats["capped"] += "ledger_cannot_create_authority" in v.reasons
            # Candidates are never read.
            d2 = randomise_candidates(d, random.Random(case))
            self.assertEqual(v, pv.resolve_chunk(build(d2, allow_fixture=True), md, text, qd, today, mode, bound=bound), ctx)
            # Restrictions only reduce: an unapproved closing operation never improves the opinion.
            if d["provisions"]:
                d3 = copy.deepcopy(d)
                d3["decisions"].append({"decision_id": "LD-999", "status": "pending", "subject": "x"})
                d3["operations"].append({"id": "OP-XTRA", "type": rng.choice(["delete", "substitute", "repeal", "amend_words"]),
                                         "source": ACTK, "targets": [rng.choice(d3["provisions"])["key"]],
                                         "effective_from": {"state": "proposed", "kind": "commencement",
                                                            "candidate": rng.choice(POOL), "decision_ref": "LD-999"}})
                v3 = pv.resolve_chunk(build(d3, allow_fixture=True), md, text, qd, today, mode, bound=bound)
                if v3.covered and v.covered and v.opinion is not None and v3.opinion is not None:
                    self.assertLessEqual(pv.rank(v3.opinion), pv.rank(v.opinion), ctx + (v3,))
            # M1: an approved closing operation that closes nothing never leaves its provision authoritative.
            open_provs = [k for k, vs in L._ver.items() if any(x.interval.end_state != "closed" for x in vs)]
            if open_provs:
                target = rng.choice(open_provs)
                d5 = copy.deepcopy(d)
                d5["decisions"].append({"decision_id": "LD-998", "status": "approved", "subject": "x"})
                d5["operations"].append({"id": "OP-UNLINKED", "type": rng.choice(sorted(pv.CLOSING_OPS)), "source": ACTK,
                                         "targets": [target],
                                         "effective_from": {"state": "approved", "kind": "commencement", "date": 29040101,
                                                            "candidate": 29040101, "decision_ref": "LD-998"}})
                L5 = build(d5, allow_fixture=True)
                self.assertIn(("C3b", target, "error"), [(x.code, x.subject, x.severity) for x in pv.validate(L5)], ctx)
                v5 = pv.resolve_chunk(L5, md, text, qd, today, mode, bound=bound)
                if v5.covered and target in v5.provisions:
                    stats["m1"] += 1
                    self.assertNotIn(v5.opinion, AUTH_HIST, ctx + (target, v5))
            # Withdrawing one approval never adds authority.
            approved = [x for x in d["decisions"] if x["status"] == "approved"]
            if approved:
                d4 = copy.deepcopy(d)
                pick = rng.choice(approved)["decision_id"]
                for x in d4["decisions"]:
                    if x["decision_id"] == pick:
                        x["status"] = "revoked"
                v4 = pv.resolve_chunk(build(d4, allow_fixture=True), md, text, qd, today, mode, bound=bound)
                if v4.opinion is not None and v.opinion is not None:
                    self.assertLessEqual(pv.rank(v4.opinion) >= 3, pv.rank(v.opinion) >= 3, ctx + (pick, v4))
        # The generator must actually reach the interesting classes, or the properties above prove nothing.
        self.assertGreater(stats["auth"], 40, stats)
        self.assertGreater(stats["hist"], 15, stats)
        self.assertGreater(stats["nif"], 40, stats)
        self.assertGreater(stats["partial"], 100, stats)
        self.assertGreater(stats["stale"], 50, stats)
        self.assertGreater(stats["fixture"], 5, stats)
        self.assertGreater(stats["capped"], 40, stats)
        self.assertGreater(stats["m1"], 100, stats)

    def test_case_count_floor(self):
        self.assertGreaterEqual(self.N, 2000)


# ============================================================================== isolation, sentinel, no side effects

def _py_files(*dirs):
    out = []
    for d in dirs:
        p = ROOT / d
        if p.is_file():
            out.append(p)
        elif p.exists():
            out.extend(sorted(p.rglob("*.py")))
    return out


def _tree_hash(rel):
    p = ROOT / rel
    h = hashlib.sha256()
    if p.is_file():
        h.update(p.read_bytes())
    elif p.is_dir():
        for f in sorted(x for x in p.rglob("*") if x.is_file()):
            h.update(str(f.relative_to(p)).encode())
            h.update(f.read_bytes())
    return h.hexdigest()


def _dir_stat(rel):
    p = ROOT / rel
    return sorted((str(f.relative_to(p)), f.stat().st_size, f.stat().st_mtime_ns) for f in p.rglob("*") if f.is_file()) if p.exists() else None


def _snapshot():
    return ({r: _tree_hash(r) for r in SENTINEL_PATHS}, {r: _dir_stat(r) for r in LIVE_INDEX_DIRS})


_BEFORE = None


def setUpModule():
    global _BEFORE
    _BEFORE = _snapshot()


def tearDownModule():
    assert _snapshot() == _BEFORE, "I8: protected data changed while the provision_validity tests ran"


class IsolationTests(unittest.TestCase):
    def test_no_runtime_module_imports_or_references_the_library(self):
        offenders = []
        for f in _py_files("backend", "scripts", "api", "deploy", "eval"):
            if f.name in ("provision_validity.py", "ledger_acceptance.py", "validity_decisions.py"):   # ledger_acceptance.py is the one sanctioned bridge (Step 2, M1)
                continue
            if f.name == "provision_validity_runtime.py":          # Step 4: the one sanctioned runtime wrapper (others may import only it)
                continue
            src = f.read_text(errors="replace")
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    offenders += [(str(f), a.name) for a in node.names if "provision_validity" in a.name
                                  and a.name != "backend.provision_validity_runtime"]
                elif isinstance(node, ast.ImportFrom):
                    names = [a.name for a in node.names if a.name != "provision_validity_runtime"]    # the wrapper, by exact name
                    if "provision_validity" in (node.module or "") or "provision_validity" in names:
                        offenders.append((str(f), node.module, names))
                elif isinstance(node, ast.Constant) and isinstance(node.value, str) and "provision_validity" in node.value:
                    offenders.append((str(f), node.value[:60]))
        self.assertEqual(offenders, [])
        for f in ROOT.glob("*.py"):
            self.assertNotIn("provision_validity", f.read_text(errors="replace"), f)

    def test_the_server_path_cannot_reach_a_fixture(self):
        for f in _py_files("backend", "scripts"):
            if f.name in ("provision_validity.py", "ledger_acceptance.py", "validity_decisions.py"):   # ledger_acceptance.py is the one sanctioned bridge (Step 2, M1)
                continue
            src = f.read_text(errors="replace")
            self.assertNotIn("allow_fixture", src, f)
            self.assertNotIn("fixtures/provision_validity", src, f)

    def test_library_imports_only_the_standard_library(self):
        allowed = {"__future__", "datetime", "hashlib", "json", "os", "re", "dataclasses", "typing"}
        tree = ast.parse((ROOT / "backend" / "provision_validity.py").read_text())
        seen = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                seen |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                seen.add((node.module or "").split(".")[0])
        self.assertLessEqual(seen, allowed, seen - allowed)

    def test_library_only_reads_files(self):
        tree = ast.parse((ROOT / "backend" / "provision_validity.py").read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
                mode = node.args[1].value if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) else None
                self.assertEqual(mode, "rb")
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, {"write", "write_text", "write_bytes", "unlink", "remove", "rmdir", "rename",
                                             "replace", "mkdir", "makedirs", "rmtree", "environ", "getenv"}, node.attr)

    def test_importing_the_library_loads_nothing_heavy(self):
        import subprocess
        code = ("import sys; sys.path.insert(0, %r); import backend.provision_validity; "
                "bad=[m for m in ('chromadb','langchain_core','flask','fastapi','backend.server','backend.legal_approval',"
                "'backend.source_status') if m in sys.modules]; print(bad)") % str(ROOT)
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.stdout.strip(), "[]", out.stderr)

    def test_no_new_environment_flag_is_read(self):
        src = (ROOT / "backend" / "provision_validity.py").read_text()
        self.assertNotIn("TG_PROVISION_VALIDITY", src.replace("roadmap", ""))
        self.assertNotIn("environ", src)


class SentinelTests(unittest.TestCase):
    """I8: exercising the library changes none of the protected data."""

    def test_protected_data_is_unchanged_by_loading_validating_and_resolving(self):
        before = _snapshot()
        for n in FIXTURE_NAMES:
            L = fixture_ledger(n)
            pv.validate(L)
            for qd in (None, 29010401):
                for mode in pv.MODES:
                    pv.resolve_chunk(L, {}, "x", qd, TODAY, mode, bound=True)
        rng = random.Random(7)
        for _ in range(50):
            d, md, text, qd, today, mode, bound, _legacy = rand_case(rng)
            pv.resolve_chunk(build(d, allow_fixture=True), md, text, qd, today, mode, bound=bound)
        self.assertEqual(_snapshot(), before)

    def test_sentinel_paths_that_exist_are_hashed(self):
        snap, _ = _snapshot()
        present = [r for r in SENTINEL_PATHS if (ROOT / r).exists()]
        self.assertTrue(present, "no protected path found: the sentinel would prove nothing")
        for r in present:
            self.assertRegex(snap[r], r"^[0-9a-f]{64}$")

    def test_the_task_added_only_new_files(self):
        import subprocess
        out = subprocess.run(["git", "status", "--porcelain", "--", "backend/provision_validity.py",
                              "tests/test_provision_validity.py", "tests/fixtures/provision_validity"],
                             cwd=ROOT, capture_output=True, text=True)
        if out.returncode != 0:
            self.skipTest("git unavailable")
        for line in out.stdout.splitlines():
            self.assertTrue(line.startswith("??") or line.startswith("A "), line)  # untracked/new, never a modification


if __name__ == "__main__":
    unittest.main()
