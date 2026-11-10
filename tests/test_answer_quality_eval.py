"""Tests for the offline grounded-answer quality evaluation. Fixtures are synthetic engineering data."""

import json
import unittest

from backend import answer_quality_eval as aq

REQUIRED_CATEGORIES = {
    "direct_explanation", "multi_provision", "insufficient_evidence", "conflicting_evidence", "missing_exception",
    "negation_reversal", "unsupported_date", "unsupported_amount", "unsupported_percentage",
    "unsupported_rule_number", "unsupported_schedule", "incorrect_citation", "missing_citation", "prompt_injection",
    "central_vs_telangana", "penalty", "follow_up", "changed_condition", "combined_provisions",
    "same_rule_different_claim", "negation_variation", "exception_omission", "numeric_change", "composition",
    "uncited_conflict"}
KNOWN_GAPS = set()  # AQ-CF-002 now reaches 'conflict' through the bounded conflict-aware retry
RESOLVED_GAPS = {"AQ-EX-001", "AQ-EX-002", "AQ-NG-001", "AQ-NG-002", "AQ-CD-001", "AQ-CD-002", "AQ-CB-001"}


class FixtureTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(aq.FIXTURES.read_text(encoding="utf-8"))

    def test_fixtures_are_marked_synthetic(self):
        self.assertIn("SYNTHETIC ENGINEERING FIXTURES", self.data["status"])
        self.assertIn("not legal reference answers", self.data["status"])
        for p in self.data["passages"].values():
            self.assertTrue(p["text"].startswith("Synthetic "), p)
            self.assertTrue(p["manifest_id"].startswith("synthetic-"), p)

    def test_cases_are_well_formed_and_cover_required_categories(self):
        cases = self.data["cases"]
        self.assertEqual(len({c["id"] for c in cases}), len(cases))
        self.assertTrue(REQUIRED_CATEGORIES <= {c["category"] for c in cases})
        for c in cases:
            self.assertIn(c["expected_outcome"], self.data["outcomes"], c["id"])
            self.assertTrue(set(c["evidence"]) <= set(self.data["passages"]), c["id"])
        self.assertEqual({c["id"] for c in cases if c.get("known_gap")}, KNOWN_GAPS)


class MetricTests(unittest.TestCase):
    def row(self, **kw):
        base = {"id": "X", "category": "c", "adversarial": False, "tags": [], "expected": "answer", "outcome": "answer",
                "server_kind": "answer", "generator_calls": 1, "errors": [], "displayed": "", "known_gap": None,
                "expected_error_contains": None, "schema_valid": True}
        base.update(kw)
        return base

    def test_rate_and_pass_rules(self):
        self.assertEqual(aq.rate(1, 4)["rate"], 0.25)
        self.assertIsNone(aq.rate(0, 0)["rate"])
        self.assertTrue(aq.passed(self.row()))
        self.assertFalse(aq.passed(self.row(outcome="rejected")))
        r = self.row(expected="rejected", outcome="rejected", expected_error_contains="identifiers", errors=["x"])
        self.assertFalse(aq.passed(r))  # right outcome, wrong reason

    def test_summary_separates_known_gaps(self):
        rows = [self.row(id="A", expected="rejected", outcome="answer", known_gap="semantic"),
                self.row(id="B", expected="rejected", outcome="answer"),
                self.row(id="C", expected="rejected", outcome="rejected", known_gap="closed now")]
        s = aq.summarise(rows, {"A": True, "B": True, "C": False})
        self.assertEqual(s["unexpected_failures"], ["B"])
        self.assertEqual(s["known_gaps_still_open"], ["A"])
        self.assertEqual(s["known_gaps_now_passing"], ["C"])
        self.assertEqual(s["metrics"]["answer_consistency"]["numerator"], 2)
        self.assertNotIn("legal_accuracy", s["metrics"])
        self.assertIn("Nothing here is a legal accuracy score", s["disclaimer"])


class OfflineRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = aq.evaluate()

    def test_no_external_model_calls(self):
        self.assertEqual(self.result["external_model_calls"], {"groq": 0})
        self.assertEqual(self.result["server_answer_mode"], "disabled")
        self.assertFalse(self.result["server_llm_client"])

    def test_no_unexpected_failures_and_gaps_are_reported(self):
        self.assertEqual(self.result["unexpected_failures"], [])
        self.assertEqual(set(self.result["known_gaps_still_open"]), KNOWN_GAPS)
        self.assertEqual(self.result["known_gaps_now_passing"], [])

    def test_core_metrics(self):
        m = self.result["metrics"]
        for name in ("malformed_output_rejection_rate", "citation_validity_rate", "invalid_citation_rejection_rate",
                     "citation_completeness", "claim_to_evidence_mapping", "correct_refusal_rate",
                     "identifier_validation_rate", "answer_consistency", "displayed_text_from_claims_only",
                     "guarded_cases_without_generation"):
            self.assertEqual(m[name]["rate"], 1.0, name)
        for name in ("negation_change_rejection_rate", "exception_omission_rejection_rate",
                     "condition_change_rejection_rate", "numeric_change_rejection_rate", "composition_rejection_rate",
                     "uncited_conflict_rejection_rate"):
            self.assertEqual(m[name]["rate"], 1.0, name)
        self.assertEqual(m["false_positive_rate_on_controls"]["rate"], 0.0)
        self.assertEqual(m["over_refusal_rate"]["numerator"], 0)
        self.assertEqual(m["conflict_detection_rate"]["rate"], 1.0)
        # retries happen only after an uncited_conflict-only rejection, at most once per question
        self.assertEqual(m["generator_calls_total"], sum(r["generator_calls"] for r in self.result["rows"]))
        self.assertTrue(all(r["generator_calls"] <= 2 for r in self.result["rows"]))

    def test_resolved_gaps_are_rejected_by_the_heuristic_layer(self):
        rows = {r["id"]: r for r in self.result["rows"]}
        for cid in RESOLVED_GAPS:
            self.assertEqual(rows[cid]["outcome"], "rejected", cid)
            self.assertTrue(any(c["layer"] == "heuristic" for c in rows[cid]["checks"]), cid)
        # AQ-CF-002: the one-sided answer is still rejected (attempt 1); the retry answer is shown as a conflict
        cf = rows["AQ-CF-002"]
        self.assertEqual((cf["outcome"], cf["generator_calls"]), ("conflict", 2))
        self.assertEqual({c["check"] for c in cf["checks"]}, {"uncited_qualification"})  # rule vs narrower exemption
        for r in self.result["rows"]:
            if r["generator_calls"] == 2:
                self.assertTrue(any(c["check"] in ("uncited_conflict", "uncited_qualification")
                                    for c in r["checks"]), r["id"])
        lb = self.result["rejections_by_layer"]
        self.assertEqual(lb["rejected_cases"], lb["deterministic_only"] + lb["heuristic_only"] + lb["both"])

    def test_guarded_cases_never_reach_the_generator(self):
        rows = {r["id"]: r for r in self.result["rows"]}
        for cid in ("AQ-PN-001", "AQ-FU-001", "AQ-FU-003"):
            self.assertEqual(rows[cid]["generator_calls"], 0, cid)
        self.assertEqual(rows["AQ-FU-003"]["outcome"], "restricted")

    def test_markdown_report(self):
        md = aq.markdown(self.result)
        self.assertIn("Synthetic engineering evaluation", md)
        self.assertIn("conflict retries", md)
        self.assertIn("Which layer rejected", md)


if __name__ == "__main__":
    unittest.main()
