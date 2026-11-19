"""Offline tests for the optional "In simple terms" summary (backend/plain_summary.py).

Every model response is a fixture; no provider is called. Passages are fixtures worded like the Motor Vehicles Act
so the questions the app is judged on (age, validity, failed test, helmet, renewal, documents) can be exercised
offline; they are not a legal source. The contract under test: a summary is shown only when every fact is supported
by its quoted evidence AND the legal claims are fully covered; otherwise it is dropped silently and the legal answer
and citations are exactly what they were without it."""

import json
import unittest

from backend import grounded_answer as ga
from backend import plain_summary as ps
from backend import providers
from test_grounded_answer import chunk, penalty_reason

AGE_4 = ("(1) No person under the age of eighteen years shall drive a motor vehicle in any public place: Provided "
         "that a motor cycle with engine capacity not exceeding 50cc may be driven in a public place by a person "
         "after attaining the age of sixteen years.")
AGE_4_MAIN = "No person under the age of eighteen years shall drive a motor vehicle in any public place:"
AGE_4_PROVISO = ("Provided that a motor cycle with engine capacity not exceeding 50cc may be driven in a public "
                 "place by a person after attaining the age of sixteen years.")
AGE_7 = ("(2) No person under the age of eighteen years shall be granted a learner’s licence to drive a motor cycle "
         "without gear except with the consent in writing of the person having the care of the person desiring the "
         "learner’s licence.")
AGE_7_CLAIM = AGE_7.replace("(2) ", "")
VALID = ("A learner’s licence issued under this Act shall, subject to the other provisions of this Act, be effective "
         "for a period of six months from the date of issue of the licence.")
TEST_P1 = ("Where the applicant does not pass the test; he may be permitted to re-appear for the test after a period "
           "of seven days:")
TEST_P2 = ("Provided that where the applicant does not pass the test even after three appearances, he shall not be "
           "qualified to re-appear for such test before the expiry of a period of sixty days from the date of last "
           "such test and such applicant shall be required to complete a remedial driver training course from any "
           "school or establishment under section 12.")
TEST_TEXT = f"(5) {TEST_P1} {TEST_P2}"
HELMET_1 = ("Every person driving or riding (or being carried on) a motor cycle of any class or description shall, "
            "while in a public place, wear protective headgear conforming to the standards of the Bureau of Indian "
            "Standards:")
HELMET_2 = "Provided that the provisions of this section shall not apply to a Sikh, if he is wearing a turban."
RENEW_1 = ("Any licensing authority may, on application made to it, renew a driving licence issued under this Act "
           "with effect from the date of its expiry:")
RENEW_2 = ("Provided that where the application for the renewal of a licence is made more than thirty days after the "
           "date of its expiry, the driving licence shall be renewed with effect from the date of its renewal.")
DOCS = ("The driver of a motor vehicle in a public place shall, on demand by a police officer in uniform, produce his "
        "driving licence, the certificate of registration and the certificate of insurance.")


def doc(provision, text):
    return chunk("mva-1988", provision, text, jurisdiction="Central", title="Motor Vehicles Act, 1988")


def go(passages, claims, summary, *, kind="direct", sufficiency="sufficient", penalty=penalty_reason):
    """claims: [(text, [evidence ids])]. Returns the GroundedResult of the whole pipeline."""
    docs = [doc(f"Section {n}", t) for n, t in passages]
    cl = [{"text": t, "kind": kind, "evidence_ids": ids} for t, ids in claims]
    body = {"answer": " ".join(c["text"] for c in cl), "evidence_sufficiency": sufficiency, "claims": cl,
            "citations": sorted({i for c in cl for i in c["evidence_ids"]}), "refusal_reason": None,
            "clarification_question": None}
    if summary is not ...:
        body["summary"] = summary
    return ga.answer("question", docs, ga.MockGenerator(json.dumps(body)), penalty_reason=penalty, request_id="r")


def fact(text, ids, *quotes):
    return {"text": text, "evidence_ids": list(ids), "quotes": list(quotes)}


LEGAL_LABEL = f"**{ps.LEGAL_LABEL}**"


def legal_part(result):
    return result.text.split(LEGAL_LABEL + "\n\n", 1)[1] if LEGAL_LABEL in result.text else result.text


class AcceptedSummaries(unittest.TestCase):
    def assert_shown(self, result, *figures):
        self.assertEqual(result.kind, "answer")
        self.assertIsNone(result.summary_note, result.summary_note)
        self.assertTrue(result.text.startswith(f"**{ps.LABEL}:** "), result.text)
        head = result.text.split(LEGAL_LABEL)[0]
        for f in figures:
            self.assertIn(f"**{f}**", head)

    def assert_legal_answer_unchanged(self, passages, claims, result):
        plain = go(passages, claims, ...)  # the same answer from a model that offered no summary
        self.assertEqual(legal_part(result), plain.text)
        self.assertEqual([e.evidence_id for e in result.cited], [e.evidence_id for e in plain.cited])
        self.assertEqual(result.kind, plain.kind)

    def test_learners_licence_validity(self):
        passages, claims = [(15, VALID)], [(VALID, ["E1"])]
        r = go(passages, claims, [fact("Subject to the other provisions of the Act, a learner’s licence is valid for "
                                       "six months from the date of issue.", ["E1"], VALID)])
        self.assert_shown(r, "six months")
        self.assertIn("[1]", r.text.split(LEGAL_LABEL)[0])
        self.assert_legal_answer_unchanged(passages, claims, r)

    def test_failed_driving_test_keeps_the_waiting_period_and_the_remedial_course(self):
        passages, claims = [(9, TEST_TEXT)], [(TEST_P1, ["E1"]), (TEST_P2, ["E1"])]
        r = go(passages, claims, [
            fact("If you fail the test, you can re-appear for the test after seven days.", ["E1"], TEST_P1),
            fact("But if you do not pass even after three appearances, you may not re-appear before sixty days from "
                 "the last test, and you must complete a remedial driver training course from any school or "
                 "establishment.", ["E1"], TEST_P2)])
        self.assert_shown(r, "seven days", "sixty days")
        self.assert_legal_answer_unchanged(passages, claims, r)

    def test_minimum_age_keeps_the_sixteen_year_50cc_exception_and_the_consent(self):
        passages = [(4, AGE_4), (7, AGE_7)]
        claims = [(AGE_4_MAIN, ["E1"]), (AGE_4_PROVISO, ["E1"]), (AGE_7_CLAIM, ["E2"])]
        r = go(passages, claims, [
            fact("You must be at least 18 years old to drive a motor vehicle in a public place.", ["E1"], AGE_4_MAIN),
            fact("But a motor cycle with engine capacity not exceeding 50cc may be driven in a public place from 16 years of age.",
                 ["E1"], AGE_4_PROVISO),
            fact("You must be at least 18 years old to be granted a learner’s licence to drive a motor cycle without "
                 "gear, unless the person having the care of you consents in writing.", ["E2"], AGE_7_CLAIM)])
        self.assert_shown(r, "18 years", "16 years of age")
        self.assert_legal_answer_unchanged(passages, claims, r)

    def test_helmet_requirement_keeps_the_turban_exception(self):
        passages, claims = [(129, f"{HELMET_1} {HELMET_2}")], [(HELMET_1, ["E1"]), (HELMET_2, ["E1"])]
        r = go(passages, claims, [
            fact("Every person driving or riding (or being carried on) a motor cycle must wear protective headgear "
                 "conforming to the standards of the Bureau of Indian Standards, while in a public place.",
                 ["E1"], HELMET_1),
            fact("But this does not apply to a Sikh, if he is wearing a turban.", ["E1"], HELMET_2)])
        self.assert_shown(r)
        self.assert_legal_answer_unchanged(passages, claims, r)

    def test_licence_renewal_keeps_the_thirty_day_condition(self):
        passages, claims = [(15, f"{RENEW_1} {RENEW_2}")], [(RENEW_1, ["E1"]), (RENEW_2, ["E1"])]
        r = go(passages, claims, [
            fact("The licensing authority may, on application, renew a driving licence with effect from the date of "
                 "its expiry.", ["E1"], RENEW_1),
            fact("But where the application for the renewal of a licence is made more than thirty days after the "
                 "date of its expiry, the driving licence is renewed with effect from the date of its renewal.",
                 ["E1"], RENEW_2)])
        self.assert_shown(r, "thirty days")
        self.assert_legal_answer_unchanged(passages, claims, r)

    def test_documents_to_carry_lists_every_document_and_the_demand_condition(self):
        passages, claims = [(139, DOCS)], [(DOCS, ["E1"])]
        r = go(passages, claims, [
            fact("On demand by a police officer in uniform, the driver of a motor vehicle in a public place must "
                 "produce his driving licence, the certificate of registration and the certificate of insurance.",
                 ["E1"], DOCS)])
        self.assert_shown(r)
        self.assert_legal_answer_unchanged(passages, claims, r)

    def test_fail_retake_and_allowed_restate_does_not_pass_re_appear_and_permitted(self):
        passages, claims = [(9, f"(5) {TEST_P1}")], [(TEST_P1, ["E1"])]
        r = go(passages, claims, [fact("If you fail the driving test, you may be allowed to retake it after seven days.",
                                       ["E1"], TEST_P1)])
        self.assert_shown(r, "seven days")
        self.assert_legal_answer_unchanged(passages, claims, r)

    def test_a_hedge_is_allowed_only_when_a_claim_states_an_exception(self):
        passages = [(4, AGE_4)]
        claims = [(AGE_4_MAIN, ["E1"]), (AGE_4_PROVISO, ["E1"])]
        facts = [fact("Generally, you must be at least 18 years old to drive a motor vehicle in a public place.",
                      ["E1"], AGE_4_MAIN),
                 fact("But a motor cycle with engine capacity not exceeding 50cc may be driven in a public place from 16 years of age.",
                      ["E1"], AGE_4_PROVISO)]
        self.assertIsNone(go(passages, claims, facts).summary_note)
        r = go([(139, DOCS)], [(DOCS, ["E1"])], [fact(
            "Generally, on demand by a police officer in uniform, the driver of a motor vehicle in a public place "
            "must produce his driving licence, the certificate of registration and the certificate of insurance.",
            ["E1"], DOCS)])
        self.assertIn("hedges", r.summary_note)


class MisleadingOrIncompleteSummariesAreDropped(unittest.TestCase):
    def assert_dropped(self, result, reason):
        self.assertEqual(result.kind, "answer")                 # the legal answer is still shown
        self.assertNotIn(ps.LABEL, result.text)
        self.assertNotIn(LEGAL_LABEL, result.text)
        self.assertIn(reason, result.summary_note or "")

    AGE = [(4, AGE_4)]
    AGE_CLAIMS = [(AGE_4_MAIN, ["E1"]), (AGE_4_PROVISO, ["E1"])]

    def age(self, *facts):
        return go(self.AGE, self.AGE_CLAIMS, list(facts))

    def test_a_prohibition_turned_into_a_permission(self):
        r = self.age(fact("A person under eighteen years may drive a motor vehicle in a public place.", ["E1"],
                          AGE_4_MAIN),
                     fact("A motor cycle with engine capacity not exceeding 50cc may be driven in a public place from 16 years "
                          "of age.", ["E1"], AGE_4_PROVISO))
        self.assert_dropped(r, "comparison words")

    def test_a_permission_stated_without_the_evidence_permitting_it(self):
        r = go([(15, VALID)], [(VALID, ["E1"])], [fact(
            "Subject to the other provisions of the Act, you can use a learner’s licence for six months from the "
            "date of issue.", ["E1"], VALID)])
        self.assert_dropped(r, "permission")

    def test_an_obligation_invented_from_a_permission(self):
        r = go([(15, f"{RENEW_1} {RENEW_2}")], [(RENEW_1, ["E1"]), (RENEW_2, ["E1"])], [
            fact("The licensing authority must renew a driving licence on application with effect from the date of "
                 "its expiry.", ["E1"], RENEW_1),
            fact("But where the application for the renewal of a licence is made more than thirty days after the "
                 "date of its expiry, the driving licence is renewed with effect from the date of its renewal.",
                 ["E1"], RENEW_2)])
        self.assert_dropped(r, "obligation")

    def test_a_changed_number(self):
        r = go([(15, VALID)], [(VALID, ["E1"])], [fact(
            "Subject to the other provisions of the Act, a learner’s licence is valid for one year from the date "
            "of issue.", ["E1"], VALID)])
        self.assert_dropped(r, "numbers differ")

    def test_a_changed_age(self):
        r = self.age(fact("You must be at least 21 years old to drive a motor vehicle in a public place.", ["E1"],
                          AGE_4_MAIN),
                     fact("But a motor cycle with engine capacity not exceeding 50cc may be driven in a public place "
                          "from 16 years of age.", ["E1"], AGE_4_PROVISO))
        self.assert_dropped(r, "numbers differ")

    def test_a_changed_comparison(self):
        r = go([(9, TEST_TEXT)], [(TEST_P1, ["E1"]), (TEST_P2, ["E1"])], [
            fact("If you fail the test, you can re-appear for the test within seven days.", ["E1"], TEST_P1),
            fact("But if you do not pass even after three appearances, you may not re-appear before sixty days from "
                 "the last test, and you must complete a remedial driver training course.", ["E1"], TEST_P2)])
        self.assert_dropped(r, "comparison words")

    def test_a_missing_exception_or_proviso(self):
        r = self.age(fact("You must be at least 18 years old to drive a motor vehicle in a public place.", ["E1"],
                          AGE_4_MAIN))
        self.assert_dropped(r, "legal claim 2")        # the 16-year / 50cc proviso is not covered
        r = go([(9, TEST_TEXT)], [(TEST_P1, ["E1"]), (TEST_P2, ["E1"])], [
            fact("If you fail the test, you can re-appear for the test after seven days.", ["E1"], TEST_P1)])
        self.assert_dropped(r, "legal claim 2")        # the sixty-day wait and remedial course are not covered

    def test_a_missing_remedial_course_condition(self):
        r = go([(9, TEST_TEXT)], [(TEST_P1, ["E1"]), (TEST_P2, ["E1"])], [
            fact("If you fail the test, you can re-appear for the test after seven days.", ["E1"], TEST_P1),
            fact("But if you do not pass even after three appearances, you may not re-appear before sixty days from "
                 "the last test.", ["E1"], TEST_P2.split(" and such applicant")[0])])
        self.assert_dropped(r, "legal claim 2")

    def test_a_dropped_subject_to_clause(self):
        r = go([(15, VALID)], [(VALID, ["E1"])], [fact(
            "A learner’s licence is valid for six months from the date of issue.", ["E1"], VALID)])
        self.assert_dropped(r, "subject_to")

    def test_a_dropped_turban_exception_cannot_pass_as_a_complete_summary(self):
        r = go([(129, f"{HELMET_1} {HELMET_2}")], [(HELMET_1, ["E1"]), (HELMET_2, ["E1"])], [
            fact("Every person driving or riding (or being carried on) a motor cycle must wear protective headgear "
                 "conforming to the standards of the Bureau of Indian Standards, while in a public place.",
                 ["E1"], HELMET_1)])
        self.assert_dropped(r, "legal claim 2")

    def test_an_exception_turned_into_a_general_rule(self):
        r = go([(129, f"{HELMET_1} {HELMET_2}")], [(HELMET_1, ["E1"]), (HELMET_2, ["E1"])], [
            fact("Every person driving or riding (or being carried on) a motor cycle must wear protective headgear "
                 "conforming to the standards of the Bureau of Indian Standards, while in a public place.",
                 ["E1"], HELMET_1),
            fact("But this applies to a Sikh, if he is wearing a turban.", ["E1"], HELMET_2)])
        self.assert_dropped(r, "negation differs")

    def test_a_list_with_a_document_missing(self):
        r = go([(139, DOCS)], [(DOCS, ["E1"])], [fact(
            "On demand by a police officer in uniform, the driver of a motor vehicle in a public place must produce "
            "his driving licence and the certificate of registration.", ["E1"], DOCS)])
        self.assert_dropped(r, "certificate of insurance")

    def test_a_dropped_demand_condition(self):
        r = go([(139, DOCS)], [(DOCS, ["E1"])], [fact(
            "The driver of a motor vehicle in a public place must produce his driving licence, the certificate of "
            "registration and the certificate of insurance.", ["E1"], DOCS)])
        self.assert_dropped(r, "on demand")

    def test_and_turned_into_or(self):
        r = go([(139, DOCS)], [(DOCS, ["E1"])], [fact(
            "On demand by a police officer in uniform, the driver of a motor vehicle in a public place must produce "
            "his driving licence, the certificate of registration or the certificate of insurance.", ["E1"], DOCS)])
        self.assert_dropped(r, "alternative")

    def test_a_rule_widened_to_everyone(self):
        r = go([(129, f"{HELMET_1} {HELMET_2}")], [(HELMET_1, ["E1"]), (HELMET_2, ["E1"])], [
            fact("Every person driving or riding (or being carried on) a motor cycle must wear protective headgear "
                 "conforming to the standards of the Bureau of Indian Standards, while in a public place.",
                 ["E1"], HELMET_1),
            fact("But this does not apply to every Sikh, if he is wearing a turban.", ["E1"], HELMET_2)])
        self.assert_dropped(r, "every")

    def test_a_dropped_place_or_while_condition(self):
        r = go([(129, f"{HELMET_1} {HELMET_2}")], [(HELMET_1, ["E1"]), (HELMET_2, ["E1"])], [
            fact("Every person driving or riding (or being carried on) a motor cycle must wear protective headgear "
                 "conforming to the standards of the Bureau of Indian Standards.", ["E1"], HELMET_1),
            fact("But this does not apply to a Sikh, if he is wearing a turban.", ["E1"], HELMET_2)])
        self.assertIn("public", r.summary_note)
        self.assertNotIn(ps.LABEL, r.text)

    def test_a_dropped_parenthetical_inclusion_such_as_pillion_riders(self):
        r = go([(129, f"{HELMET_1} {HELMET_2}")], [(HELMET_1, ["E1"]), (HELMET_2, ["E1"])], [
            fact("Every person driving or riding a motorcycle in a public place must wear protective headgear "
                 "conforming to the standards of the Bureau of Indian Standards.", ["E1"], HELMET_1),
            fact("But this does not apply to a Sikh, if he is wearing a turban.", ["E1"], HELMET_2)])
        self.assertIn("being carried on", r.summary_note)
        self.assertNotIn(ps.LABEL, r.text)

    def test_in_a_public_place_may_restate_while_in_a_public_place(self):
        r = go([(129, f"{HELMET_1} {HELMET_2}")], [(HELMET_1, ["E1"]), (HELMET_2, ["E1"])], [
            fact("Every person driving or riding (or being carried on) a motorcycle in a public place must wear "
                 "protective headgear conforming to the standards of the Bureau of Indian Standards.", ["E1"],
                 HELMET_1),
            fact("But this does not apply to a Sikh, if he is wearing a turban.", ["E1"], HELMET_2)])
        self.assertIsNone(r.summary_note, r.summary_note)
        self.assertIn(ps.LABEL, r.text)

    def test_an_invented_fact_or_word(self):
        r = go([(139, DOCS)], [(DOCS, ["E1"])], [fact(
            "On demand by a police officer in uniform, the driver of a motor vehicle in a public place must produce "
            "his driving licence, the certificate of registration and the certificate of insurance, or pay a fine.",
            ["E1"], DOCS)])
        self.assertIsNotNone(r.summary_note)
        self.assertNotIn(ps.LABEL, r.text)

    def test_an_invented_condition(self):
        r = go([(15, VALID)], [(VALID, ["E1"])], [fact(
            "Subject to the other provisions of the Act, a learner’s licence is valid for six months only if it is "
            "used from the date of issue.", ["E1"], VALID)])
        self.assertIn("only", r.summary_note)

    def test_a_hedge_without_an_exception(self):
        r = go([(139, DOCS)], [(DOCS, ["E1"])], [fact(
            "Generally, on demand by a police officer in uniform, the driver of a motor vehicle in a public place "
            "must produce his driving licence, the certificate of registration and the certificate of insurance.",
            ["E1"], DOCS)])
        self.assert_dropped(r, "hedges")

    def test_a_quote_that_is_not_in_the_evidence(self):
        r = go([(15, VALID)], [(VALID, ["E1"])], [fact(
            "Subject to the other provisions of the Act, a learner’s licence is valid for six months from the date "
            "of issue.", ["E1"], "A learner’s licence shall be valid for a period of six months from the date of "
                                "issue of the licence.")])
        self.assert_dropped(r, "verbatim")

    def test_a_summary_may_not_cite_evidence_the_legal_claims_do_not_cite(self):
        r = go([(15, VALID), (139, DOCS)], [(VALID, ["E1"])], [fact(
            "On demand by a police officer in uniform, the driver of a motor vehicle in a public place must produce "
            "his driving licence, the certificate of registration and the certificate of insurance.", ["E2"], DOCS)])
        self.assert_dropped(r, "do not cite")

    def test_markup_links_and_citation_markers_are_refused(self):
        for text in ("**Valid** for six months [1].", "Valid for six months, see https://example.org.",
                     "Valid for six months (interpretation)."):
            r = go([(15, VALID)], [(VALID, ["E1"])], [fact(text, ["E1"], VALID)])
            self.assert_dropped(r, "markup")

    def test_too_many_facts_or_malformed_facts(self):
        f = fact("Subject to the other provisions of the Act, a learner’s licence is valid for six months from the "
                 "date of issue.", ["E1"], VALID)
        self.assertIn("short list", go([(15, VALID)], [(VALID, ["E1"])], [f] * 5).summary_note)
        self.assertIn("malformed", go([(15, VALID)], [(VALID, ["E1"])], [{"text": "x"}]).summary_note)
        self.assertIn("malformed", go([(15, VALID)], [(VALID, ["E1"])], [{**f, "quotes": ["short"]}]).summary_note)

    def test_an_interpretation_claim_is_never_summarised(self):
        r = go([(15, VALID)], [(VALID, ["E1"])], [fact(
            "Subject to the other provisions of the Act, a learner’s licence is valid for six months from the date "
            "of issue.", ["E1"], VALID)], kind="interpretation")
        self.assert_dropped(r, "interpretation")

    def test_penalty_wording_is_refused_by_the_penalty_check(self):
        passages = [doc("Section 15", VALID)]
        contract, _ = ga.build_contract("q", passages)
        claim = ga.Claim(text=VALID, kind="direct", evidence_ids=["E1"])
        answer = ga.GroundedAnswer(answer=VALID, evidence_sufficiency="sufficient", claims=[claim], citations=["E1"],
                                   refusal_reason=None, clarification_question=None)
        f = fact("Subject to the other provisions of the Act, a learner’s licence is valid for six months from the "
                 "date of issue.", ["E1"], VALID)
        facts, why = ps.check([f], answer, contract, penalty_reason=lambda t: "amount")
        self.assertIsNone(facts)
        self.assertIn("penalty", why)
        facts, why = ps.check([f], answer, contract, penalty_reason=lambda t: None)
        self.assertIsNotNone(facts)


class TheLegalAnswerIsNeverAtRisk(unittest.TestCase):
    F = fact("Subject to the other provisions of the Act, a learner’s licence is valid for six months from the date "
             "of issue.", ["E1"], VALID)

    def baseline(self):
        return go([(15, VALID)], [(VALID, ["E1"])], ...)

    def test_no_summary_is_exactly_the_previous_answer(self):
        for absent in (..., None, []):
            r = go([(15, VALID)], [(VALID, ["E1"])], absent)
            self.assertEqual(r.text, self.baseline().text)
            self.assertIsNone(r.summary_note)
            self.assertNotIn(ps.LABEL, r.text)

    def test_a_garbage_summary_cannot_reject_the_answer(self):
        for junk in ("not a list", {"a": 1}, 7, [1, 2], [{"text": 5}], [None], ["x"] * 21):
            r = go([(15, VALID)], [(VALID, ["E1"])], junk)
            self.assertEqual(r.kind, "answer", junk)
            self.assertEqual(r.text, self.baseline().text, junk)

    def test_a_dropped_summary_leaves_text_citations_and_cache_replay_unchanged(self):
        bad = {**self.F, "quotes": ["A learner’s licence shall be valid for ever and ever."]}
        r = go([(15, VALID)], [(VALID, ["E1"])], [bad])
        self.assertEqual(r.text, self.baseline().text)
        self.assertEqual([e.evidence_id for e in r.cited], ["E1"])
        # The cached model output is validated again on every replay and reaches the same decision.
        again = ga.validate(r.raw, r.contract)
        self.assertTrue(again.ok)
        self.assertEqual(ga.render(again.answer, r.contract)[0], r.text)

    def test_the_answer_must_still_equal_the_claims(self):
        body = {"answer": VALID + " Extra words.", "evidence_sufficiency": "sufficient",
                "claims": [{"text": VALID, "kind": "direct", "evidence_ids": ["E1"]}], "citations": ["E1"],
                "refusal_reason": None, "clarification_question": None, "summary": [self.F]}
        contract, _ = ga.build_contract("q", [doc("Section 15", VALID)])
        self.assertFalse(ga.validate(json.dumps(body), contract).ok)

    def test_a_conflict_or_refusal_never_carries_a_summary(self):
        docs = [doc("Section 15", VALID), doc("Section 16", VALID)]
        claims = [{"text": VALID, "kind": "direct", "evidence_ids": ["E1"]},
                  {"text": VALID, "kind": "direct", "evidence_ids": ["E2"]}]
        body = {"answer": f"{VALID} {VALID}", "evidence_sufficiency": "conflicting", "claims": claims,
                "citations": ["E1", "E2"], "refusal_reason": None, "clarification_question": None,
                "summary": [self.F]}
        r = ga.answer("q", docs, ga.MockGenerator(json.dumps(body)), request_id="r")
        self.assertEqual(r.kind, "conflict")
        self.assertNotIn(ps.LABEL, r.text)
        self.assertIn("summaries are shown only", r.summary_note)
        refusal = {"answer": "", "evidence_sufficiency": "insufficient", "claims": [], "citations": [],
                   "refusal_reason": "not in the evidence", "clarification_question": None, "summary": [self.F]}
        r = ga.answer("q", docs, ga.MockGenerator(json.dumps(refusal)), request_id="r")
        self.assertEqual(r.kind, "no_support")
        self.assertEqual(r.text, ga.NO_EVIDENCE_MESSAGE)

    def test_provider_schema_and_prompt_offer_the_optional_summary(self):
        self.assertIn("summary", providers.ANSWER_SCHEMA["required"])
        item = providers.ANSWER_SCHEMA["properties"]["summary"]["items"]
        self.assertEqual(set(item["properties"]), set(ps.SummaryFact.model_fields))
        self.assertFalse(item["additionalProperties"])
        self.assertIn("Plain-English summary", ga.ANSWER_INSTRUCTIONS)
        self.assertIn('"summary"', ga.ANSWER_INSTRUCTIONS)

    def test_echallan_answers_never_get_a_summary(self):
        from backend import echallan_fines
        self.assertFalse(hasattr(echallan_fines, "plain_summary"))
        with open(echallan_fines.__file__, encoding="utf-8") as fh:
            self.assertNotIn(ps.LABEL, fh.read())


class DiagnosticLogging(unittest.TestCase):
    GOOD = fact("Subject to the other provisions of the Act, a learner’s licence is valid for six months from the "
                "date of issue.", ["E1"], VALID)

    def logged(self, summary):
        with self.assertLogs("kyr.summary", level="INFO") as cm:
            go([(15, VALID)], [(VALID, ["E1"])], summary)
        return cm.output

    def test_none_supplied_shown_and_dropped_are_each_logged_once(self):
        self.assertEqual(len(self.logged(...)), 1)
        self.assertIn("model supplied none", self.logged([])[0])
        self.assertIn("supplied, shown", self.logged([self.GOOD])[0])
        out = self.logged([{**self.GOOD, "text": self.GOOD["text"].replace("six", "nine")}])
        self.assertEqual(len(out), 1)
        self.assertIn("supplied, dropped by check=numbers_differ fact=1", out[0])

    def test_logs_never_contain_summary_question_or_evidence_text(self):
        bad = [
            {**self.GOOD, "text": "Subject to the other provisions of the Act, a learner’s licence is valid for "
                                  "nine months zebra from the date of issue."},
            {**self.GOOD, "quotes": ["A learner’s licence shall be valid for ever and ever and ever."]},
            {**self.GOOD, "text": "Valid for six months [1] https://example.org"},
            {**self.GOOD, "text": "Subject to the other provisions of the Act, a learner’s licence is valid for six "
                                  "months from the date of issue, or you pay a fine."},
        ]
        for item in bad:
            line = " ".join(self.logged([item]))
            for secret in ("zebra", "nine", "ever and ever", "example.org", "learner", "licence", "months", "fine",
                           "question", "issue", "Act"):
                self.assertNotIn(secret, line)
            self.assertRegex(line, r"^INFO:kyr\.summary:summary \S+: supplied, dropped by check=[a-z_]+( fact=\d)?$")

    def test_reasons_map_to_fixed_check_names(self):
        reasons = ["fact 1: numbers differ from the quoted evidence", "legal claim 2 states ['16'] that the summary "
                   "leaves out", "fact 2: drops the 'subject_to' condition of the quoted evidence",
                   "fact 1: uses words that are not in the quoted evidence: ['x']",
                   "penalty content withheld (amount)", "an interpretation claim is not summarised"]
        self.assertEqual([ps.check_name(r) for r in reasons],
                         ["numbers_differ", "claim_number_missing", "condition_dropped", "unlicensed_words",
                          "penalty", "interpretation_claim"])
        self.assertIsNone(ps.check_name(None))
        self.assertEqual(ps.check_name("something new"), "other")

    def test_logging_does_not_change_the_decision(self):
        r = go([(15, VALID)], [(VALID, ["E1"])], [self.GOOD])
        self.assertIsNone(r.summary_note)
        self.assertIn(ps.LABEL, r.text)


class Helpers(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual(ps.number_values("eighteen years"), ps.number_values("18 years"))
        self.assertEqual(ps.number_values("twenty-one days"), {"21"})
        self.assertEqual(ps.number_values("50cc and ₹1,000"), {"50", "1000"})
        self.assertEqual(ps.number_values("the third time"), ps.number_values("the 3rd time"))
        self.assertEqual(ps.number_values("one of the following"), set())
        self.assertEqual(ps.number_values("one year"), {"1"})

    def test_a_negative_limit_equals_the_positive_limit(self):
        under = ps._flags("No person under the age of eighteen years shall drive")
        least = ps._flags("You must be at least 18 years old to drive")
        self.assertEqual((under["cmp"], under["neg"], under["ob"]), (least["cmp"], least["neg"], least["ob"]))
        self.assertNotEqual(ps._flags("may drive under the age of eighteen years")["cmp"], least["cmp"])

    def test_bare_prepositions_are_not_limits(self):
        self.assertEqual(ps._flags("issued under this Act within the meaning of section 2")["cmp"], set())
        self.assertEqual(ps._flags("within thirty days")["cmp"], {"within"})

    def test_may_not_is_a_prohibition_not_a_permission(self):
        f = ps._flags("you may not re-appear")
        self.assertTrue(f["neg"])
        self.assertFalse(f["perm"])


if __name__ == "__main__":
    unittest.main()
