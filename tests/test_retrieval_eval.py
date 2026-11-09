import json
import unittest
from pathlib import Path

from backend import retrieval_eval as ev

BENCHMARK = Path(__file__).resolve().parent.parent / "eval" / "telangana-retrieval-benchmark.json"


class MetricTests(unittest.TestCase):
    def test_ranking_metrics(self):
        ranked = ["a", "x", "b", "y", "z"]
        self.assertEqual(ev.recall_at_k(ranked, ["a", "b"], 1), 0.5)
        self.assertEqual(ev.recall_at_k(ranked, ["a", "b"], 3), 1.0)
        self.assertEqual(ev.precision_at_k(ranked, ["a", "b"], 5), 0.4)
        self.assertEqual(ev.precision_at_k(["a"], ["a"], 5), 0.2)  # empty slots are not relevant
        self.assertEqual(ev.reciprocal_rank(ranked, ["b"]), 1 / 3)
        self.assertEqual(ev.reciprocal_rank(ranked, ["q"]), 0.0)
        self.assertFalse(ev.hit_at_k(ranked, ["b"], 2))

    def test_summary_counts_guard_leakage_and_failures(self):
        rows = [
            {"id": "1", "category": "direct_lookup", "outcome": "retrieve", "relevant": ["a"], "ranked": ["a"],
             "retrieved_chunks": 1, "guard_blocked": False, "missing": [], "penalty_locked": False, "leaked": []},
            {"id": "2", "category": "direct_lookup", "outcome": "retrieve", "relevant": ["a"], "ranked": ["b"],
             "retrieved_chunks": 1, "guard_blocked": False, "missing": [], "penalty_locked": False, "leaked": ["x"]},
            {"id": "3", "category": "missing_provision", "outcome": "missing_provision", "relevant": [], "ranked": [],
             "retrieved_chunks": 0, "guard_blocked": True, "missing": ["186"], "penalty_locked": False, "leaked": []},
            {"id": "4", "category": "guard_control", "outcome": "retrieve", "relevant": ["a"], "ranked": ["a"],
             "retrieved_chunks": 2, "guard_blocked": True, "missing": ["9"], "penalty_locked": False, "leaked": []},
        ]
        s = ev.summarise(rows)
        self.assertEqual(s["retrieval"]["scored_cases"], 3)
        self.assertEqual([f["id"] for f in s["failures"]], ["2"])
        self.assertEqual(s["guard"], {"cases": 2, "correct": 1, "accuracy": 0.5})
        self.assertEqual(s["leakage"]["excluded_chunks_retrieved"], 1)
        self.assertEqual(s["leakage"]["cases_with_leak"], ["2"])


class BenchmarkSchemaTests(unittest.TestCase):
    REQUIRED = {"id", "category", "question", "expected_documents", "expected_provisions", "expected_chunks",
                "excluded_chunks", "expected_retrieval_outcome", "expected_answer_eligible", "expected_behaviour",
                "notes", "label_source", "reviewer_status", "reviewed_by", "reviewed_on"}

    def test_cases_are_well_formed_and_unreviewed_labels_are_marked(self):
        data = json.loads(BENCHMARK.read_text(encoding="utf-8"))
        ids = [c["id"] for c in data["cases"]]
        self.assertEqual(len(ids), len(set(ids)))
        for c in data["cases"]:
            self.assertEqual(set(c), self.REQUIRED, c["id"])
            self.assertIn(c["reviewer_status"], data["reviewer_status_values"])
            if c["reviewer_status"] == "pending_human_review":
                self.assertIsNone(c["reviewed_by"])
                self.assertEqual(c["label_source"], "machine_candidate")
            else:  # a confirmed or rejected case must name its reviewer and date
                self.assertTrue(c["reviewed_by"] and c["reviewed_on"], c["id"])
            if c["expected_retrieval_outcome"] == "retrieve":
                self.assertTrue(c["expected_chunks"] and c["expected_answer_eligible"], c["id"])
            if c["expected_retrieval_outcome"] == "excluded_no_context":
                self.assertTrue(c["excluded_chunks"] and not c["expected_chunks"], c["id"])
            for ch in c["expected_chunks"] + c["excluded_chunks"]:
                self.assertTrue(ch["source_passage"] and ch["chunk_id"].startswith(ch["document"]), c["id"])


if __name__ == "__main__":
    unittest.main()
