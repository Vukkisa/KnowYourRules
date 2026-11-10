"""Conflict-aware retry in grounded answering. Every model response is a fixture (MockGenerator); no provider is
called. Passage text is synthetic, not legal text. Adversarial cases, controls and documented limitations are kept
in separate classes."""

import json
import unittest

from langchain_core.documents import Document

from backend import grounded_answer as ga


def chunk(pid, text):
    return Document(page_content=text, metadata={
        "manifest_id": "synthetic-rules", "provision_id": pid, "part": 1, "parts": 1, "title": "Synthetic Rules",
        "document_number": "", "location": f"synthetic.htm#{pid}", "page_start": -1, "page_end": -1,
        "jurisdiction": "Telangana", "state": "Telangana", "verification_status": "unverified",
        "answer_eligible": True, "extraction_warning": "", "sha256": "b" * 64})


RULE = chunk("Rule 1", "Synthetic Rule 1. Every rider of a two-wheeler shall wear protective headgear.")
EXEMPT = chunk("Rule 2", "Synthetic Rule 2. Riders of a two-wheeler on rural roads are exempt from protective "
                         "headgear.")
NEED_NOT = chunk("Rule 3", "Synthetic Rule 3. A rider of a two-wheeler need not wear protective headgear within "
                           "municipal limits.")
SAME_POLARITY = chunk("Rule 4", "Synthetic Rule 4. Every pillion rider of a two-wheeler shall wear protective "
                                "headgear.")
UNRELATED = chunk("Rule 5", "Synthetic Rule 5. The registering authority shall not register a vehicle without a "
                            "valid certificate of insurance.")
SYNONYM = chunk("Rule 6", "Synthetic Rule 6. Helmets are optional for motorcyclists outside towns.")

R1 = "Every rider of a two-wheeler shall wear protective headgear."
R2 = "Riders of a two-wheeler on rural roads are exempt from protective headgear."
R3 = "A rider of a two-wheeler need not wear protective headgear within municipal limits."
Q = "Must riders wear helmets on rural roads?"


def resp(claims, sufficiency="sufficient"):
    return {"answer": " ".join(t for t, _ in claims), "evidence_sufficiency": sufficiency,
            "claims": [{"text": t, "kind": "direct", "evidence_ids": ids} for t, ids in claims],
            "citations": sorted({i for _, ids in claims for i in ids}, key=lambda i: int(i[1:])),
            "refusal_reason": None, "clarification_question": None}


ONE_SIDED = resp([(R1, ["E1"])])
CONFLICT = resp([(R1, ["E1"]), (R2, ["E2"])], "conflicting")


def sequence(*outputs):
    """A generator returning outputs in order (the last one repeats)."""
    gen = ga.MockGenerator(fn=lambda _p, _c: json.dumps(outputs[min(len(gen.calls), len(outputs)) - 1]))
    return gen


class ConflictRetryAdversarialTests(unittest.TestCase):
    def test_direct_contradiction_is_retried_and_shown_as_a_conflict(self):
        gen = sequence(ONE_SIDED, CONFLICT)
        r = ga.answer(Q, [RULE, EXEMPT], gen)
        self.assertEqual((r.kind, r.attempts, len(gen.calls)), ("conflict", 2, 2))
        self.assertEqual([e.evidence_id for e in r.cited], ["E1", "E2"])
        self.assertTrue(r.text.startswith(ga.CONFLICT_PREFIX))  # states it is not a definitive answer
        self.assertIn(R1, r.text)
        self.assertIn(R2, r.text)
        # attempt 1's rejection is kept for audit; attempt 2 passed every check
        # rule vs an exemption for a narrower class: detected as a possible qualification, not called a contradiction
        self.assertEqual({(c["attempt"], c["check"]) for c in r.checks}, {(1, "uncited_qualification")})

    def test_retry_prompt_is_the_same_evidence_plus_a_note_naming_the_uncited_passage(self):
        gen = sequence(ONE_SIDED, CONFLICT)
        ga.answer(Q, [RULE, EXEMPT], gen)
        first, second = gen.calls
        self.assertTrue(second.startswith(first))
        note = second[len(first):]
        self.assertIn("E2", note)
        self.assertIn('"conflicting"', note)
        self.assertNotIn("E1", note)  # names only the possibly contradicting passage(s)
        self.assertNotIn(R2, note)    # no evidence or answer text is repeated outside the evidence blocks

    def test_contradiction_in_different_wording_shall_vs_need_not(self):
        gen = sequence(ONE_SIDED, resp([(R1, ["E1"]), (R3, ["E2"])], "conflicting"))
        r = ga.answer("Must riders wear helmets in a town?", [RULE, NEED_NOT], gen)
        self.assertEqual((r.kind, len(gen.calls)), ("conflict", 2))

    def test_model_that_repeats_itself_is_rejected_after_exactly_one_retry(self):
        gen = sequence(ONE_SIDED)
        r = ga.answer(Q, [RULE, EXEMPT], gen)
        self.assertEqual((r.kind, len(gen.calls)), ("rejected", 2))
        self.assertEqual(r.text, ga.REJECTED_MESSAGE)
        self.assertTrue(any(e.startswith("conflict retry: ") and "uncited evidence E2" in e for e in r.errors))

    def test_retry_answer_gets_the_full_unchanged_validator(self):
        flipped = resp([(R1, ["E1"]), ("Riders of a two-wheeler on rural roads are not exempt from protective "
                                       "headgear.", ["E2"])], "conflicting")
        invented = resp([(R1, ["E1"]), ("Riders of a two-wheeler on rural roads are exempt from protective "
                                        "headgear under Rule 9.", ["E2"])], "conflicting")
        one_passage = resp([(R1, ["E1"])], "conflicting")
        for retry, expect in ((flipped, "negation or modality changed"), (invented, "identifiers absent"),
                              (one_passage, "at least two passages")):
            r = ga.answer(Q, [RULE, EXEMPT], sequence(ONE_SIDED, retry))
            self.assertEqual(r.kind, "rejected", expect)
            self.assertTrue(any(e.startswith("conflict retry: ") and expect in e for e in r.errors), r.errors)

    def test_no_retry_for_any_other_rejection(self):
        invented = resp([("Every rider of a two-wheeler shall wear protective headgear under Rule 9.", ["E1"])])
        negated = resp([("Every rider of a two-wheeler shall not wear protective headgear.", ["E1"])])
        for first in (invented, negated, "not json"):
            gen = sequence(first, CONFLICT)
            r = ga.answer(Q, [RULE, EXEMPT], gen)
            self.assertEqual((r.kind, len(gen.calls)), ("rejected", 1), first)

    def test_no_retry_when_conflict_is_mixed_with_another_failure(self):
        mixed = resp([("Every rider of a two-wheeler shall wear protective headgear under Rule 9.", ["E1"])])
        result = ga.validate(json.dumps(mixed), ga.build_contract(Q, [RULE, EXEMPT])[0])
        self.assertIsNone(ga.conflict_retry_note(result))

    def test_no_retry_after_penalty_withholding(self):
        gen = sequence(ONE_SIDED, CONFLICT)
        r = ga.answer(Q, [RULE, EXEMPT], gen, penalty_reason=lambda _t: "penalty")
        self.assertEqual((r.kind, len(gen.calls)), ("rejected", 1))

    def test_generator_failure_on_retry_fails_closed(self):
        def fn(_p, _c):
            if len(gen.calls) == 2:
                raise TimeoutError
            return json.dumps(ONE_SIDED)
        gen = ga.MockGenerator(fn=fn)
        r = ga.answer(Q, [RULE, EXEMPT], gen)
        self.assertEqual((r.kind, len(gen.calls)), ("rejected", 2))
        self.assertIn("conflict retry: generator error: TimeoutError", r.errors)

    def test_conflict_found_on_a_follow_up_question(self):
        """Real /chat path (grounded mode, retrieval and generator substituted, Groq trapped): a restated follow-up
        with history reaches the generator without history, and the retry still applies."""
        from backend import answer_quality_eval as aq
        server, calls = aq.load_pipeline()
        passages = {"rule": {"manifest_id": "synthetic-rules", "provision_id": "Rule 1", "text": RULE.page_content},
                    "exempt": {"manifest_id": "synthetic-rules", "provision_id": "Rule 2",
                               "text": EXEMPT.page_content}}
        case = {"id": "T-FU-CF", "category": "conflicting_evidence", "adversarial": True, "tags": [],
                "question": "Must riders wear helmets on rural roads as well?", "evidence": ["rule", "exempt"],
                "history": [{"question": "Is a helmet compulsory on a two-wheeler?", "answer": "(previous)"}],
                "model_response": ONE_SIDED, "retry_response": CONFLICT, "expected_outcome": "conflict"}
        row = aq.run_case(server, case, passages)
        self.assertEqual((row["outcome"], row["generator_calls"]), ("conflict", 2))
        self.assertIn("Cited:", row["displayed"])
        self.assertEqual(calls["groq"], 0)
        vague = dict(case, question="and on rural roads?")
        row = aq.run_case(server, vague, passages)
        self.assertEqual((row["outcome"], row["generator_calls"]), ("clarification", 0))  # unchanged behaviour


class ConflictRetryControlTests(unittest.TestCase):
    def test_related_passage_with_the_same_polarity_is_not_a_conflict(self):
        gen = sequence(ONE_SIDED, CONFLICT)
        r = ga.answer("Must a rider wear a helmet?", [RULE, SAME_POLARITY], gen)
        self.assertEqual((r.kind, len(gen.calls)), ("answer", 1))

    def test_unrelated_passage_with_opposite_polarity_is_not_a_conflict(self):
        gen = sequence(ONE_SIDED, CONFLICT)
        r = ga.answer("Must a rider wear a helmet?", [RULE, UNRELATED], gen)
        self.assertEqual((r.kind, len(gen.calls), r.errors), ("answer", 1, []))

    def test_insufficient_evidence_is_not_retried(self):
        insufficient = {"answer": "", "evidence_sufficiency": "insufficient", "claims": [], "citations": [],
                        "refusal_reason": "The passages do not cover pillion riders.", "clarification_question": None}
        gen = sequence(insufficient, CONFLICT)
        r = ga.answer(Q, [RULE, EXEMPT], gen)
        self.assertEqual((r.kind, len(gen.calls)), ("no_support", 1))

    def test_no_evidence_means_no_generation_and_no_retry(self):
        gen = sequence(ONE_SIDED, CONFLICT)
        r = ga.answer(Q, [], gen)
        self.assertEqual((r.kind, len(gen.calls)), ("no_support", 0))

    def test_complementary_provisions_cited_together_are_accepted_without_retry(self):
        both = resp([(R1, ["E1"]), (SAME_POLARITY.page_content.split(". ", 1)[1], ["E2"])])
        gen = sequence(both, CONFLICT)
        r = ga.answer("Who must wear a helmet?", [RULE, SAME_POLARITY], gen)
        self.assertEqual((r.kind, len(gen.calls)), ("answer", 1))

    def test_a_declared_conflict_is_accepted_first_time(self):
        gen = sequence(CONFLICT)
        r = ga.answer(Q, [RULE, EXEMPT], gen)
        self.assertEqual((r.kind, len(gen.calls)), ("conflict", 1))


class ConflictRetryKnownLimitationTests(unittest.TestCase):
    """These assert CURRENT behaviour that is not desirable, so that a change is noticed. They are not targets."""

    def test_synonym_contradiction_is_not_detected(self):
        # "helmets ... optional" vs "shall wear protective headgear": too few shared words for the lexical check.
        gen = sequence(ONE_SIDED, CONFLICT)
        r = ga.answer(Q, [RULE, SYNONYM], gen)
        self.assertEqual((r.kind, len(gen.calls)), ("answer", 1))

    def test_rule_and_exemption_cited_together_as_sufficient_is_accepted(self):
        # The validator cannot tell whether a separate exemption conflicts with or qualifies a general rule.
        gen = sequence(resp([(R1, ["E1"]), (R2, ["E2"])]))
        r = ga.answer(Q, [RULE, EXEMPT], gen)
        self.assertEqual((r.kind, len(gen.calls)), ("answer", 1))


if __name__ == "__main__":
    unittest.main()
