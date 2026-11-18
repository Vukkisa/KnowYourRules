"""Stage 4G: how Rule 6 answer wording fares against the validator, layer by layer. Offline; Rule 6 is quoted from the index.

For every wording two things are pinned independently, because the penalty gate only runs when every earlier check is
clean and would otherwise hide itself behind grounding errors:
  * penalty verdict: server.answer_drift_reason(eligibility_status.mask(text, [Rule 6 passage]))
  * full validator verdict: grounded_answer.answer(...) for a "direct" and for an "interpretation" claim citing Rule 6.
Nothing here relaxes the validator. See eval/latency/STAGE-4G-REPORT.md for the reasoning behind each row.
"""
import json
import unittest

from test_eligibility_status import RULE6, RULE6_SENTENCE, chunk, srv

from backend import eligibility_status as es
from backend import grounded_answer as ga

Q = "What happens when a driving licence application is received?"
RULE437 = "437. Every rider of a two-wheeler shall wear protective headgear, except a person exempted under sub-rule (2)."

# (label, text, penalty_verdict_is_clear, accepted_as_interpretation_claim)
VARIANTS = [
    ("exact short", "The applicant is not disqualified.", True, False),
    ("short with tail", "The applicant is not disqualified or liable to be disqualified.", True, False),
    ("noun: does not fall under a disqualification", "The applicant does not fall under a disqualification.", False, False),
    ("noun: eligible from the disqualification standpoint",
     "The applicant is eligible from the disqualification standpoint.", False, False),
    ("restates the sentence, with tail",
     "The licensing authority may make enquiries to ascertain that the applicant is not disqualified or liable to be "
     "disqualified for holding a Licence.", True, True),
    ("restates the sentence, head only",
     "The licensing authority may make such enquiries as are reasonably necessary to establish the identity of the "
     "applicant and to ascertain that the applicant is not disqualified.", True, True),
    ("contraction",
     "The licensing authority may make enquiries to ascertain that the applicant isn't disqualified or liable to be "
     "disqualified.", True, True),
    ("different tense: has not been", "The licensing authority checks that the applicant has not been disqualified.",
     False, False),
    ("modal: must not be", "The applicant must not be disqualified.", False, False),
    ("inserted 'is': changes the logic",
     "The authority may enquire whether the applicant is not disqualified or is liable to be disqualified.", False, False),
    ("added word: not currently",
     "The licensing authority may make enquiries to ascertain that the applicant is not currently disqualified.",
     False, False),
    ("markdown breaks the phrase",
     "The licensing authority may make enquiries to ascertain that the applicant is **not** disqualified.", False, False),
    ("non-negated", "An applicant who is disqualified cannot hold a Licence.", False, False),
    ("negated, plus an unsupported consequence",
     "The applicant is not disqualified, so the licence will be granted.", True, False),
    ("negated, plus a penalty", "The applicant is not disqualified, otherwise the licence is suspended.", False, False),
]


def verdict(text, kind, docs=None, question=Q, cite="E1"):
    raw = json.dumps({"answer": text, "evidence_sufficiency": "sufficient",
                      "claims": [{"text": text, "kind": kind, "evidence_ids": [cite]}], "citations": [cite],
                      "refusal_reason": None, "clarification_question": None})
    return ga.answer(question, docs or [chunk("Rule 6", RULE6)], ga.MockGenerator(raw),
                     penalty_reason=srv.answer_drift_reason, request_id="req-1")


class ParaphraseMatrixTests(unittest.TestCase):
    def test_penalty_verdict_per_wording(self):
        for label, text, clear, _ in VARIANTS:
            with self.subTest(label=label):
                got = srv.answer_drift_reason(es.mask(text, [RULE6]))
                self.assertEqual(got is None, clear, (label, got))

    def test_a_direct_claim_must_restate_a_whole_cited_sentence_so_every_short_wording_is_rejected(self):
        for label, text, _c, _a in VARIANTS:
            with self.subTest(label=label):
                self.assertNotEqual(verdict(text, "direct").kind, "answer", label)

    def test_interpretation_claims_are_accepted_only_for_supported_restatements(self):
        for label, text, clear, accepted in VARIANTS:
            with self.subTest(label=label):
                res = verdict(text, "interpretation")
                self.assertEqual(res.kind == "answer", accepted, (label, res.errors))
                if accepted:
                    self.assertTrue(clear)

    def test_the_verbatim_sentence_is_the_accepted_direct_control(self):
        res = verdict(f"Lincensing authority may make enquiries :- {RULE6_SENTENCE}", "direct")
        self.assertEqual((res.kind, res.errors), ("answer", []))

    def test_wording_rejected_by_the_penalty_gate_names_it(self):
        # run the gate on its own for the rows whose only objection should be penalty wording
        for label, text in [("has not been", "The applicant has not been disqualified"),
                            ("non-negated", "The applicant is disqualified"),
                            ("markdown", "The applicant is **not** disqualified")]:
            with self.subTest(label=label):
                self.assertEqual(srv.answer_drift_reason(es.mask(text, [RULE6])), "penalty_term")

    def test_citation_validity(self):
        full = f"Lincensing authority may make enquiries :- {RULE6_SENTENCE}"
        # unknown evidence id
        self.assertNotEqual(verdict(full, "direct", cite="E9").kind, "answer")
        # phrase present in Rule 6 but the claim cites Rule 437: ungrounded AND not masked
        docs = [chunk("Rule 6", RULE6), chunk("Rule 437", RULE437)]
        res = verdict(full, "direct", docs=docs, cite="E2")
        self.assertNotEqual(res.kind, "answer")
        self.assertEqual(srv.answer_drift_reason(es.mask(full, [RULE437])), "penalty_term")
        # claim cites Rule 6 only: accepted even when other, unrelated passages are in context
        res = verdict(full, "direct", docs=docs, cite="E1")
        self.assertEqual((res.kind, res.errors), ("answer", []), res.errors)

    def test_curly_apostrophe_negation_is_read_like_the_straight_one(self):
        # Stage 4G fix in meaning_checks._NEG_RE: "isn’t" was not seen as a negation, so a faithful restatement was
        # rejected as "claim reads as 'permission' but the cited sentence reads as 'prohibition'".
        base = ("The licensing authority may make enquiries to ascertain that the applicant {} disqualified or liable "
                "to be disqualified.")
        for neg in ("isn't", "isn’t"):
            with self.subTest(neg=neg):
                res = verdict(base.format(neg), "interpretation")
                self.assertEqual((res.kind, res.errors), ("answer", []), res.errors)
        # and the fix does not make a flipped meaning acceptable: dropping the negation is still rejected
        flipped = verdict(base.format("is"), "interpretation")
        self.assertNotEqual(flipped.kind, "answer")
        # a curly-apostrophe negation in the CLAIM against a non-negated source sentence is still a mismatch
        self.assertNotEqual(verdict("The authority may make enquiries to ascertain that the applicant isn’t "
                                    "liable to pay.", "interpretation").kind, "answer")

    @unittest.expectedFailure
    def test_KNOWN_GAP_an_unsupported_eligibility_conclusion_is_accepted_as_an_interpretation(self):
        # Stage 4G finding, independent of the penalty guard (the sentence has no penalty wording): Rule 6 lets the
        # authority ENQUIRE whether the applicant is disqualified; it does not say the applicant "is eligible to hold a
        # licence". The meaning-preservation layer accepts it at 50% word overlap. Left unfixed on purpose: raising the
        # interpretation threshold is outside this stage and would change every provision. When it is fixed this test
        # starts passing and unittest reports an unexpected success, which is the cue to delete the decorator.
        res = verdict("The applicant is eligible to hold a licence.", "interpretation")
        self.assertNotEqual(res.kind, "answer")


if __name__ == "__main__":
    unittest.main()
