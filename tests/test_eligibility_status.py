"""Stage 4F: Rule 6 false rejection. Offline tests for backend/eligibility_status.py and its use in the validator.

Rule 6 / Rule 52 text is quoted from the Telangana Motor Vehicles Rules, 1989 as stored in the index (unofficial web
copy). Every other passage here is synthetic. The penalty guard itself (server.answer_drift_reason) is NOT changed and
is used unmodified; these tests pin both what the new exception allows and, more importantly, what it must not.
"""
import json
import unittest

from langchain_core.documents import Document

import test_server as ts  # noqa: F401  (fakes Chroma/Ollama/Groq before backend.server is imported, as test_providers)
from test_server import srv

from backend import eligibility_status as es
from backend import grounded_answer as ga

RULE6_SENTENCE = ("Upon the receipt of an application for a driving Licence or for an authorization to drive a "
                  "transport vehicle, the licensing authority may make such enquiries as may reasonably be necessary "
                  "to establish the identity of the applicant and to ascertain that the applicant is not "
                  "disqualified or liable to be disqualified for holding a Licence.")
RULE52_SENTENCE = ("Upon receipt of an application for a conductor's Licence, the licensing authority may make such "
                   "enquiries as may be necessary to establish the identity of the applicant and to ascertain that "
                   "the applicant is not disqualified for holding a Licence.")
RULE6 = f"6. Lincensing authority may make enquiries :- {RULE6_SENTENCE}"
RULE52 = f"52. Licensing Authority to make enquiry :- {RULE52_SENTENCE}"


def chunk(pid, text):
    return Document(page_content=text, metadata={
        "manifest_id": "tmvr-1989-chap-2", "provision_id": pid, "part": 1, "parts": 1, "title": "Synthetic Motor Rules",
        "document_number": "", "location": f"chap2.htm#{pid}", "page_start": -1, "page_end": -1,
        "jurisdiction": "Telangana", "state": "Telangana", "verification_status": "unverified",
        "answer_eligible": True, "extraction_warning": "", "sha256": "a" * 64})


def raw(claims, answer=None):
    """claims: [(text, evidence_id)]"""
    return json.dumps({"answer": answer if answer is not None else " ".join(t for t, _ in claims),
                       "evidence_sufficiency": "sufficient",
                       "claims": [{"text": t, "kind": "direct", "evidence_ids": [e]} for t, e in claims],
                       "citations": sorted({e for _, e in claims}), "refusal_reason": None,
                       "clarification_question": None})


def validate(docs, claims, question="What happens when a driving licence application is received?"):
    gen = ga.MockGenerator(raw(claims))
    return ga.answer(question, docs, gen, penalty_reason=srv.answer_drift_reason, request_id="req-1")


class MaskHelperTests(unittest.TestCase):
    # Wording that Rule 6 itself contains (Stage 4G: an answer may only use the source's own words and copula).
    SUPPORTED_FORMS = [
        "the applicant is not disqualified",
        "the applicant isn't disqualified",
        "the applicant isn’t disqualified or liable to be disqualified",
        "the applicant is not disqualified or liable to be disqualified for holding a Licence",
        "THE APPLICANT IS NOT DISQUALIFIED",
    ]
    # Stage 4G: accepted in Stage 4F, now rejected unless the cited passage says it in those very words.
    NOT_IN_RULE6 = [
        "applicants are not disqualified",              # different copula
        "the applicant was not disqualified",           # different tense
        "the applicant is not disqualified or is liable to be disqualified",  # inserted "is": changes the logic
    ]

    def test_guard_itself_is_unchanged_and_still_fires_on_the_rule6_sentence(self):
        self.assertEqual(srv.answer_drift_reason(RULE6_SENTENCE), "penalty_term")
        self.assertEqual(srv.answer_drift_reason(RULE52_SENTENCE), "penalty_term")

    def test_negated_status_forms_are_masked_when_the_evidence_says_the_same(self):
        evidence = [RULE6]  # carries the full "or liable to be disqualified" tail
        for text in self.SUPPORTED_FORMS:
            with self.subTest(text=text):
                self.assertIsNone(srv.answer_drift_reason(es.mask(text, evidence)), text)

    def test_wording_the_source_does_not_use_is_not_masked_unless_another_cited_passage_has_it(self):
        for text in self.NOT_IN_RULE6:
            with self.subTest(text=text):
                self.assertEqual(es.mask(text, [RULE6]), text if "is liable" not in text else
                                 "the applicant is eligible or is liable to be disqualified")
                self.assertIsNotNone(srv.answer_drift_reason(es.mask(text, [RULE6])), text)
        plural = "7. Synthetic :- Applicants are not disqualified for holding a Licence."
        self.assertIsNone(srv.answer_drift_reason(es.mask("applicants are not disqualified", [plural])))
        self.assertIsNotNone(srv.answer_drift_reason(es.mask("applicants are not disqualified", [RULE6])))

    def test_other_grammatical_context_around_the_status_is_masked_too(self):
        for text in ["The authority checks that the applicant is not disqualified.",
                     "To ascertain that the applicant is not disqualified or liable to be disqualified.",
                     "Enquiries establish identity and whether the applicant is not disqualified for holding a Licence."]:
            with self.subTest(text=text):
                self.assertIsNone(srv.answer_drift_reason(es.mask(text, [RULE6])), text)

    def test_nothing_is_masked_without_support_in_the_cited_evidence(self):
        unrelated = "437. Every rider of a two-wheeler shall wear protective headgear."
        for text in self.SUPPORTED_FORMS:
            with self.subTest(text=text):
                self.assertEqual(es.mask(text, [unrelated]), text)
                self.assertEqual(es.mask(text, []), text)
                self.assertIsNotNone(srv.answer_drift_reason(es.mask(text, [unrelated])), text)

    def test_the_liable_tail_must_be_in_the_source_too(self):
        text = "the applicant is not disqualified or liable to be disqualified"
        self.assertIsNotNone(srv.answer_drift_reason(es.mask(text, [RULE52])))  # Rule 52 has no tail
        self.assertIsNone(srv.answer_drift_reason(es.mask(text, [RULE6])))
        self.assertIsNone(srv.answer_drift_reason(es.mask("the applicant is not disqualified", [RULE52])))

    def test_non_negated_or_other_forms_of_the_word_are_never_masked(self):
        for text in ["the applicant is disqualified",
                     "a driver who is disqualified shall not drive",
                     "the person shall be disqualified from holding a licence",
                     "the person has been disqualified",
                     "disqualification for six months",
                     "the applicant is not subject to disqualification",
                     "those not disqualified may apply",   # no copula: outside the one construction
                     "the applicant is liable to be disqualified",
                     "the applicant is not disqualified but is liable to be disqualified"]:
            with self.subTest(text=text):
                self.assertIsNotNone(srv.answer_drift_reason(es.mask(text, [RULE6, RULE52])), text)

    def test_penalty_words_beside_the_status_still_trip_the_guard(self):
        for text in ["the applicant is not disqualified and a disqualified person shall be punished",
                     "the applicant is not disqualified, otherwise the licence is suspended",
                     "the applicant is not disqualified; the fine is Rs. 500",
                     "the applicant is not disqualified or the Licence shall be cancelled",
                     "the applicant is not disqualified, else imprisonment up to six months",
                     "the applicant is not disqualified; the offence is compounded"]:
            with self.subTest(text=text):
                self.assertIsNotNone(srv.answer_drift_reason(es.mask(text, [RULE6])), text)

    def test_unrelated_provisions_with_similar_vocabulary_keep_their_existing_verdicts(self):
        # Unchanged behaviour of the existing guard, pinned so the exception cannot be mistaken for a wider loosening.
        for text in ["No person shall be liable to be convicted of an offence under Section 112.",
                     "The conductor shall surrender the badge if he is disqualified from holding a Licence by any Court.",
                     "Those found unsuitable shall be disqualified, reasons being given.",
                     "Purchase by borrowed money shall not be a disqualification by itself.",
                     "A goods vehicle liable to foul the interior shall not be carried."]:
            with self.subTest(text=text):
                self.assertIsNotNone(srv.answer_drift_reason(es.mask(text, [RULE6, RULE52])), text)

    def test_mask_is_per_piece_so_text_cannot_be_glued_into_a_span(self):
        # the validator masks the answer and each claim separately, then joins: "is not" + "disqualified" must not form
        self.assertEqual(es.mask("the applicant is not", [RULE6]), "the applicant is not")
        self.assertEqual(es.mask("disqualified persons", [RULE6]), "disqualified persons")


class ValidatorTests(unittest.TestCase):
    def test_rule6_statement_is_accepted(self):
        res = validate([chunk("Rule 6", RULE6)], [(RULE6_SENTENCE.replace("Upon", "6. Lincensing authority may make "
                                                                          "enquiries :- Upon"), "E1")])
        self.assertEqual((res.kind, res.errors), ("answer", []), res.errors)

    def test_rule6_statement_is_accepted_for_both_licence_questions(self):
        docs = [chunk("Rule 6", RULE6)]
        for q in ["What happens after I submit a driving licence application?",
                  "What happens when a driving licence application is received?"]:
            with self.subTest(q=q):
                res = validate(docs, [(f"Lincensing authority may make enquiries :- {RULE6_SENTENCE}", "E1")], q)
                self.assertEqual((res.kind, res.errors), ("answer", []), res.errors)

    def test_rule52_statement_is_accepted(self):
        res = validate([chunk("Rule 52", RULE52)], [(f"Licensing Authority to make enquiry :- {RULE52_SENTENCE}", "E1")])
        self.assertEqual((res.kind, res.errors), ("answer", []), res.errors)

    def rejected(self, passage, claim_text, extra_claims=()):
        res = validate([chunk("Rule X", passage)], [(claim_text, "E1")] + list(extra_claims))
        self.assertNotEqual(res.kind, "answer", res.errors)
        return res

    def test_actual_disqualification_penalty_stays_rejected(self):
        p = "99. Disqualification :- A person convicted under this rule shall be disqualified for holding a Licence for six months."
        res = self.rejected(p, "Disqualification :- A person convicted under this rule shall be disqualified for holding a Licence for six months.")
        self.assertTrue(any("penalty content withheld" in e for e in res.errors), res.errors)

    def test_suspension_and_cancellation_stay_rejected(self):
        p = "98. Suspension :- The licensing authority may suspend or cancel the Licence of a driver who contravenes this rule."
        res = self.rejected(p, "Suspension :- The licensing authority may suspend or cancel the Licence of a driver who contravenes this rule.")
        self.assertTrue(any("penalty content withheld" in e for e in res.errors), res.errors)

    def test_fines_stay_rejected(self):
        p = "97. Fine :- A fine of Rs. 500 shall be imposed on any person who contravenes this rule."
        res = self.rejected(p, "Fine :- A fine of Rs. 500 shall be imposed on any person who contravenes this rule.")
        self.assertTrue(any("penalty content withheld" in e for e in res.errors), res.errors)

    def test_mixed_eligibility_and_penalty_in_one_claim_is_rejected(self):
        p = (f"6. Enquiries :- {RULE6_SENTENCE} A person who drives while disqualified shall be punished with "
             "imprisonment.")
        both = f"Enquiries :- {RULE6_SENTENCE} A person who drives while disqualified shall be punished with imprisonment."
        res = self.rejected(p, both)
        self.assertTrue(any("penalty content withheld" in e for e in res.errors), res.errors)

    def test_mixed_across_two_claims_is_rejected_even_though_one_claim_alone_is_fine(self):
        p = (f"6. Enquiries :- {RULE6_SENTENCE} A person who drives while disqualified shall be punished with "
             "imprisonment.")
        c1 = f"Enquiries :- {RULE6_SENTENCE}"
        c2 = "A person who drives while disqualified shall be punished with imprisonment."
        res = self.rejected(p, c1, extra_claims=[(c2, "E1")])
        self.assertTrue(any("penalty content withheld" in e for e in res.errors), res.errors)

    def test_fabricated_penalty_claim_citing_rule6_is_rejected(self):
        for fab in ["An applicant who is disqualified shall be fined Rs. 500 and punished.",
                    "The applicant is not disqualified and no fine is payable.",
                    "A fee of Rs. 4,321 is payable for a driving licence under Rule 99."]:
            with self.subTest(fab=fab):
                res = validate([chunk("Rule 6", RULE6)], [(fab, "E1")])
                self.assertNotEqual(res.kind, "answer", fab)

    def test_unsupported_licence_requirement_claim_is_rejected(self):
        for fab in ["The applicant must submit proof of age and address and pass a medical test.",
                    "The applicant must be at least eighteen years old."]:
            with self.subTest(fab=fab):
                res = validate([chunk("Rule 6", RULE6)], [(fab, "E1")],
                               "What are the requirements for getting a driving licence in Telangana?")
                self.assertNotEqual(res.kind, "answer", fab)

    def test_not_disqualified_without_support_in_cited_evidence_is_rejected(self):
        other = "437. Every rider of a two-wheeler shall wear protective headgear, except a person exempted under sub-rule (2)."
        res = validate([chunk("Rule 437", other)], [("The applicant is not disqualified for holding a Licence.", "E1")])
        self.assertNotEqual(res.kind, "answer")

    def test_question_side_penalty_lock_is_untouched(self):
        for q in ["Can my licence be cancelled or disqualified?", "What happens if I am disqualified?",
                  "Is the applicant not disqualified?", "Who is not disqualified from holding a licence?"]:
            with self.subTest(q=q):
                self.assertIsNotNone(srv.penalty_lock_reason(q), q)
        for q in ["What happens after I submit a driving licence application?",
                  "What happens when a driving licence application is received?",
                  "What are the requirements for getting a driving licence in Telangana?",
                  "What documents are required for a learner's licence?"]:
            with self.subTest(q=q):
                self.assertIsNone(srv.penalty_lock_reason(q), q)


# Motor Vehicles Act 1988 s.11(1) (India Code extract), worded "is not for the time being disqualified".
S11_SENTENCE = ("Any person holding a driving licence to drive any class or description of motor vehicles, who is not "
                "for the time being disqualified for holding or obtaining a driving licence to drive any other class "
                "or description of motor vehicles, may apply to any licensing authority in the State in which he "
                "resides or carries on his business in such form and accompanied by such documents and with such "
                "fees as may be prescribed by the Central Government for the addition of such other class or "
                "description of motor vehicles to the licence.")
S11 = f"11. Additions to driving licence.\u2014(1) {S11_SENTENCE}"


def chunk_mva(pid, text):
    d = chunk(pid, text)
    d.metadata.update({"manifest_id": "mva-1988", "jurisdiction": "Central", "state": "Central"})
    return d


class TimeBeingEligibilityTests(unittest.TestCase):
    """'is not for the time being disqualified' is an eligibility check (Act ss.8, 9, 11), not a penalty."""
    FORMS = ["who is not for the time being disqualified for holding or obtaining a driving licence",
             "the applicant is not for the time being disqualified",
             "A PERSON WHO IS NOT FOR THE TIME BEING DISQUALIFIED MAY APPLY"]

    def test_guard_itself_is_unchanged_and_still_fires_on_the_s11_sentence(self):
        self.assertEqual(srv.answer_drift_reason(S11_SENTENCE), "penalty_term")

    def test_the_phrase_is_masked_only_when_the_cited_evidence_has_it(self):
        for text in self.FORMS:
            with self.subTest(text=text):
                self.assertIsNone(srv.answer_drift_reason(es.mask(text, [S11])), text)
                self.assertIsNotNone(srv.answer_drift_reason(es.mask(text, [])), text)
                self.assertIsNotNone(srv.answer_drift_reason(es.mask(text, [RULE52])), text)  # other wording

    def test_dropping_or_adding_the_time_being_words_is_not_supported_by_the_other_wording(self):
        self.assertIsNotNone(srv.answer_drift_reason(es.mask("who is not disqualified", [S11])))
        self.assertIsNotNone(srv.answer_drift_reason(es.mask("who is not for the time being disqualified", [RULE52])))

    def test_affirmative_and_other_disqualification_wording_is_never_masked(self):
        for text in ["who is for the time being disqualified",
                     "a person for the time being disqualified shall not apply",
                     "not for the time being disqualified persons may apply",  # no copula
                     "who is not for the time being disqualified from holding a licence, and is disqualified for six months",
                     "who is not for the time being disqualified; the licence shall be suspended",
                     "who is not for the time being disqualified; the fine is Rs. 500",
                     "who is not for the time being disqualified, else imprisonment up to three months",
                     "who is not for the time being disqualified or the licence shall be cancelled"]:
            with self.subTest(text=text):
                self.assertIsNotNone(srv.answer_drift_reason(es.mask(text, [S11])), text)

    def test_the_user_question_lock_is_unaffected(self):
        for q in ["What is the penalty for driving while for the time being disqualified?",
                  "What is the fine if I am disqualified?",
                  "Can my licence be suspended or cancelled?"]:
            with self.subTest(q=q):
                self.assertIsNotNone(srv.penalty_lock_reason(q), q)

    def test_s11_statement_is_accepted_for_the_class_addition_question(self):
        res = validate([chunk_mva("Section 11", S11)], [(S11_SENTENCE, "E1")],
                       "How do I add another class of vehicle to my driving licence?")
        self.assertEqual((res.kind, res.errors), ("answer", []), res.errors)

    def test_a_penalty_claim_citing_s11_is_still_rejected(self):
        for claim in [S11_SENTENCE + " A disqualified person shall be punished with a fine.",
                      "The licence of a person who is not for the time being disqualified shall be suspended.",
                      "The fine for driving without the added class is Rs. 500."]:
            with self.subTest(claim=claim):
                res = validate([chunk_mva("Section 11", S11)], [(claim, "E1")],
                               "How do I add another class of vehicle to my driving licence?")
                self.assertNotEqual(res.kind, "answer", res.errors)


if __name__ == "__main__":
    unittest.main()
