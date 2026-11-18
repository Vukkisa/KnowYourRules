"""Stage 14 integrity checks across the benchmark, the review CSV and the chunk references.

Reads the real (read-only) repository files; synthetic cases are built in memory. Nothing here certifies any
provision as legally correct or current: these are mechanical consistency checks only."""

import collections
import copy
import json
import sys
import types
import unittest
from unittest import mock

from backend import retrieval_eval as ev
from backend import review_import as ri

CASES = json.loads(ri.BENCHMARK.read_text(encoding="utf-8"))["cases"]
REFS = ri.load_references()
_, TEMPLATE_ROWS = ri._read_csv(ri.TEMPLATE)
TEMPLATE = {r["id"]: r for r in TEMPLATE_ROWS}


def _row(rid, category, outcome, blocked, relevant=("a",)):
    return {"id": rid, "category": category, "outcome": outcome, "relevant": list(relevant), "ranked": ["a"],
            "retrieved_chunks": 1, "guard_blocked": blocked, "missing": ["x"] if blocked else [],
            "penalty_locked": False, "leaked": []}


class ExpectedProvisionsExistTests(unittest.TestCase):
    def test_every_expected_provision_is_in_the_references_and_answer_eligible(self):
        eligible = collections.defaultdict(list)
        for c in REFS["chunks"]:
            eligible[f"{c['document']}::{c['provision']}"].append(c["answer_eligible"])
        for case in CASES:
            for p in case["expected_provisions"]:
                self.assertIn(p, eligible, (case["id"], p))
                self.assertTrue(any(eligible[p]), (case["id"], p))

    def test_expected_chunks_cover_exactly_the_expected_provisions(self):
        for case in CASES:
            provs = {f"{e['document']}::{e['provision']}" for e in case["expected_chunks"]}
            self.assertEqual(provs, set(case["expected_provisions"]), case["id"])

    def test_every_part_of_each_expected_provision_is_listed(self):
        parts = collections.defaultdict(set)
        for c in REFS["chunks"]:
            parts[f"{c['document']}::{c['provision']}"].add(c["chunk_id"])
        for case in CASES:
            listed = {e["chunk_id"] for e in case["expected_chunks"]}
            for p in case["expected_provisions"]:
                self.assertLessEqual(parts[p], listed, (case["id"], p))


class UnresolvedChunkTests(unittest.TestCase):
    def test_stale_chunk_id_does_not_resolve(self):
        # TG-GC-002's pre-Stage-14 entry: Rule 185 was six parts before Rule 186 was split out.
        stale = {"chunk_id": "tmvr-1989-chap-5::Rule 185::part6of6",
                 "location": "html-snapshots/tmvr-1989/middle-main-chap-5.htm#58"}
        self.assertEqual(ri.resolve_benchmark_chunk(stale, REFS), [])

    def test_right_chunk_id_at_wrong_location_does_not_resolve(self):
        real = next(c for c in REFS["chunks"] if c["provision"] == "Rule 186")
        self.assertEqual(ri.resolve_benchmark_chunk({"chunk_id": real["chunk_id"], "location": "x.htm#1"}, REFS), [])

    def test_rule_186_resolves_and_rule_185_has_no_186_location(self):
        r185 = [c for c in REFS["chunks"] if c["document"] == "tmvr-1989-chap-5" and c["provision"] == "Rule 185"]
        r186 = [c for c in REFS["chunks"] if c["document"] == "tmvr-1989-chap-5" and c["provision"] == "Rule 186"]
        self.assertEqual(sorted(c["part"] for c in r185), [1, 2, 3, 4, 5])
        self.assertEqual({c["parts"] for c in r185}, {5})
        self.assertFalse(any("#58" in c["location"] for c in r185))
        self.assertEqual(sorted(c["part"] for c in r186), [1, 2])

    def test_rule_12b_is_its_own_provision_sharing_12a_anchor(self):
        # Known source limitation: 12-B has no anchor of its own, so it cites 12-A's #13. Identity must differ.
        b = [c for c in REFS["chunks"] if c["document"] == "tmvtr-1963" and c["provision"] == "Rule 12B"]
        a = [c for c in REFS["chunks"] if c["document"] == "tmvtr-1963" and c["provision"] == "Rule 12A"]
        self.assertEqual(len(b), 1)
        self.assertEqual(len(a), 1)
        self.assertEqual(b[0]["location"], a[0]["location"])
        self.assertNotEqual(b[0]["text_sha256"], a[0]["text_sha256"])
        self.assertNotEqual(b[0]["ref"], a[0]["ref"])


class DuplicateReferenceTests(unittest.TestCase):
    def _fake_chromadb(self, docs, metas):
        coll = mock.Mock()
        coll.get.return_value = {"documents": docs, "metadatas": metas}
        client = mock.Mock()
        client.get_collection.return_value = coll
        return types.SimpleNamespace(PersistentClient=lambda _p: client)

    def _meta(self, **kw):
        m = {"manifest_id": "d", "provision_id": "Rule 1", "part": 1, "parts": 1, "location": "f#1", "sha256": "h"}
        m.update(kw)
        return m

    def test_identical_chunks_are_refused(self):
        fake = self._fake_chromadb(["same text", "same text"], [self._meta(), self._meta()])
        with mock.patch.dict(sys.modules, {"chromadb": fake}):
            with self.assertRaises(ValueError):
                ri.build_references("unused")

    def test_shared_chunk_id_with_different_text_is_recorded_not_merged(self):
        fake = self._fake_chromadb(["text one", "text two"], [self._meta(location="f#1"), self._meta(location="f#2")])
        with mock.patch.dict(sys.modules, {"chromadb": fake}):
            out = ri.build_references("unused")
        self.assertEqual(len(out["chunks"]), 2)
        self.assertEqual(list(out["duplicate_chunk_ids"]), ["d::Rule 1::part1of1"])

    def test_live_references_have_no_duplicate_refs(self):
        refs = [c["ref"] for c in REFS["chunks"]]
        self.assertEqual(len(refs), len(set(refs)))


class DriftTests(unittest.TestCase):
    def test_live_template_matches_benchmark(self):
        self.assertEqual(ri.check_template(TEMPLATE_ROWS, CASES), [])

    def test_changed_outcome_is_detected(self):
        cases = copy.deepcopy(CASES)
        case = next(c for c in cases if c["id"] == "TG-MP-001")
        case["expected_retrieval_outcome"] = "missing_provision"
        errs = ri.check_template(TEMPLATE_ROWS, cases)
        self.assertTrue(any("TG-MP-001: machine_expected_outcome" in e for e in errs), errs)

    def test_changed_category_is_detected(self):
        cases = copy.deepcopy(CASES)
        next(c for c in cases if c["id"] == "TG-MP-001")["category"] = "missing_provision"
        self.assertTrue(any("TG-MP-001: category" in e for e in ri.check_template(TEMPLATE_ROWS, cases)))

    def test_location_and_passage_columns_match_expected_chunks(self):
        # check_template does not compare these; this test closes that gap.
        for c in CASES:
            row = TEMPLATE[c["id"]]
            locs = "; ".join(f"{e['document']} :: {e['provision']} ({e['location']})" for e in c["expected_chunks"])
            passage = "\n---\n".join(e["source_passage"].strip() for e in c["expected_chunks"])
            self.assertEqual(ri._norm_machine(row["machine_expected_locations"]), locs, c["id"])
            self.assertEqual(ri._norm_machine(row["machine_supporting_passage"]), passage, c["id"])


class GuardControlTests(unittest.TestCase):
    def test_guard_control_is_correct_only_when_not_blocked(self):
        s = ev.summarise([_row("ok", "guard_control", "retrieve", False), _row("bad", "guard_control", "retrieve", True)])
        self.assertEqual(s["guard"], {"cases": 2, "correct": 1, "accuracy": 0.5})

    def test_missing_provision_is_correct_only_when_blocked(self):
        s = ev.summarise([_row("ok", "missing_provision", "missing_provision", True, ()),
                          _row("bad", "missing_provision", "missing_provision", False, ())])
        self.assertEqual(s["guard"], {"cases": 2, "correct": 1, "accuracy": 0.5})

    def test_guard_control_rows_are_also_scored_for_retrieval(self):
        s = ev.summarise([_row("g", "guard_control", "retrieve", False)])
        self.assertEqual(s["retrieval"]["scored_cases"], 1)

    def test_benchmark_guard_rows(self):
        gc = [c for c in CASES if c["category"] == "guard_control"]
        mp = [c for c in CASES if c["category"] == "missing_provision"]
        self.assertEqual(sorted(c["id"] for c in gc), ["TG-GC-001", "TG-GC-002", "TG-GC-003", "TG-GC-004",
                                                      "TG-MP-001", "TG-MP-002", "TG-MP-003", "TG-MP-004", "TG-MP-005"])
        self.assertTrue(all(c["expected_retrieval_outcome"] == "retrieve" and c["expected_provisions"] for c in gc))
        self.assertEqual(sorted(c["id"] for c in mp), ["TG-MP-006", "TG-MP-007", "TG-MP-008"])
        self.assertTrue(all(c["expected_retrieval_outcome"] == "missing_provision" for c in mp))

    def test_corrected_rows_keep_machine_labels_and_pending_review(self):
        for c in CASES:
            if c["id"] in ("TG-MP-001", "TG-MP-002", "TG-MP-003", "TG-MP-004", "TG-MP-005", "TG-GC-002"):
                self.assertEqual(c["label_source"], "machine_candidate", c["id"])
                self.assertEqual(c["reviewer_status"], "pending_human_review", c["id"])
                self.assertIsNone(c["reviewed_by"], c["id"])


if __name__ == "__main__":
    unittest.main()
