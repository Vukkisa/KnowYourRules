"""Qualifier checks across a cross-reference ("except a person exempted under sub-rule (2)" + "(2) ...") and across
the claims of one answer. Found in the controlled real-model run (RG-02, RG-03, RG-10, RG-14): faithful answers were
rejected. Synthetic text. Lexical heuristics: passing does not show that meaning is preserved."""

import json
import unittest

from langchain_core.documents import Document

from backend import grounded_answer as ga
from backend import meaning_checks as mc

HELMET = ("Synthetic Rule 437. Every rider of a two-wheeler shall wear protective headgear, except a person exempted "
          "under sub-rule (2). (2) A Sikh wearing a turban is exempted.")
GOODS = "Synthetic Rule 245. A goods vehicle shall not carry passengers, except the owner or hirer travelling with the goods."
HIGHWAY = "Synthetic Rule 306. Notwithstanding anything in rule 305, a learner shall not drive on a national highway."
QUALIFIER = {"qualifier_omitted", "qualifier_altered", "exemption"}


def found(claim, passage=HELMET, siblings=(), cited_id="E1", other=None, checks=QUALIFIER):
    """siblings: texts (citing E1) or (text, evidence IDs) pairs."""
    cited = {cited_id: passage}
    if other:
        cited.update(other)
    sibs = tuple((x, ("E1",)) if isinstance(x, str) else x for x in siblings)
    return sorted({c for c, _m in mc.check_claim(claim, "direct", cited, {}, strip=ga.strip_identifiers,
                                                 definitive=True, siblings=sibs)} & set(checks))


R437 = ("Synthetic Rule 437. Every rider of a two-wheeler shall wear protective headgear, except a person exempted "
        "under sub-rule (2). ")
INLINE = "Every rider of a two-wheeler shall wear protective headgear, except a Sikh wearing a turban."
BASE = "Every rider of a two-wheeler shall wear protective headgear."


class CrossReferenceTests(unittest.TestCase):
    """Fix 1: an exception that names a sub-rule of the same passage may be stated by that sub-rule's content."""

    def test_referent_stated_inside_the_except_clause(self):
        for claim in ("Every rider of a two-wheeler shall wear protective headgear, except a Sikh wearing a turban.",
                      "Riders of a two-wheeler must wear protective headgear, except a Sikh wearing a turban.",
                      "Every rider of a two-wheeler shall wear protective headgear, except a Sikh wearing a turban is "
                      "exempted."):
            self.assertEqual(found(claim), [], claim)

    def test_the_reference_itself_is_still_accepted(self):
        self.assertEqual(found("Every rider of a two-wheeler shall wear protective headgear, except a person exempted "
                               "under sub-rule (2)."), [])

    def test_a_different_exception_is_still_altered(self):
        self.assertEqual(found("Every rider of a two-wheeler shall wear protective headgear, except a police officer."),
                         ["qualifier_altered"])

    def test_part_of_the_referent_is_not_enough(self):
        self.assertEqual(found("Every rider of a two-wheeler shall wear protective headgear, except a Sikh."),
                         ["qualifier_altered"])

    def test_dropping_the_exception_is_still_flagged(self):
        self.assertEqual(found("Every rider of a two-wheeler shall wear protective headgear."), ["qualifier_omitted"])

    def test_referent_must_be_in_the_same_passage(self):
        split = "Synthetic Rule 437. Every rider of a two-wheeler shall wear protective headgear, except a person " \
                "exempted under sub-rule (2)."
        self.assertEqual(found("Every rider of a two-wheeler shall wear protective headgear, except a Sikh wearing a "
                               "turban.", passage=split, other={"E2": "(2) A Sikh wearing a turban is exempted."}),
                         ["exemption", "qualifier_altered"])

    def test_reference_to_a_missing_sub_rule_changes_nothing(self):
        missing = "Synthetic Rule 437. Every rider of a two-wheeler shall wear protective headgear, except a person " \
                  "exempted under sub-rule (3). (2) A Sikh wearing a turban is exempted."
        self.assertIn("qualifier_altered", found("Every rider of a two-wheeler shall wear protective headgear, except a "
                                                 "Sikh wearing a turban.", passage=missing))

    def test_negating_the_referent_is_not_hidden(self):
        # "except" kept and the referent's words covered, but the rule is reversed: the deontic check still fires
        found_all = {c for c, _m in mc.check_claim(
            "Every rider of a two-wheeler shall not wear protective headgear, except a Sikh wearing a turban.",
            "direct", {"E1": HELMET}, {}, strip=ga.strip_identifiers, definitive=True)}
        self.assertIn("deontic", found_all)


class AnswerLevelQualifierTests(unittest.TestCase):
    """Fix 2: a qualifier stated by another claim of the same answer, citing the same passage, is not omitted."""

    def test_exception_split_into_its_own_claim(self):
        self.assertEqual(found("Every rider of a two-wheeler shall wear protective headgear.",
                               siblings=("A Sikh wearing a turban is exempted.",)), [])

    def test_exception_clause_restated_by_a_sibling(self):
        self.assertEqual(found("A goods vehicle shall not carry passengers.", passage=GOODS,
                               siblings=("The owner or hirer travelling with the goods may travel in it.",)), [])

    def test_unrelated_sibling_does_not_count(self):
        self.assertEqual(found("A goods vehicle shall not carry passengers.", passage=GOODS,
                               siblings=("A goods vehicle shall carry a permit.",)), ["qualifier_omitted"])

    def test_sibling_with_a_partial_exception_does_not_count(self):
        self.assertEqual(found("Every rider of a two-wheeler shall wear protective headgear.",
                               siblings=("A Sikh is exempted.",)), ["qualifier_omitted"])

    def test_notwithstanding_omission_is_still_flagged(self):
        self.assertEqual(found("A learner shall not drive on a national highway.", passage=HIGHWAY,
                               siblings=("A learner may drive a motor car.",)), ["qualifier_omitted"])


def chunk(pid, text):
    return Document(page_content=text, metadata={
        "manifest_id": "synthetic-rules", "provision_id": pid, "part": 1, "parts": 1, "title": "Synthetic Rules",
        "document_number": "", "location": f"synthetic.htm#{pid}", "page_start": -1, "page_end": -1,
        "jurisdiction": "Telangana", "state": "Telangana", "verification_status": "unverified",
        "answer_eligible": True, "extraction_warning": "", "sha256": "c" * 64})


def response(claims):
    return json.dumps({"answer": " ".join(t for t, _ in claims), "evidence_sufficiency": "sufficient",
                       "claims": [{"text": t, "kind": "direct", "evidence_ids": ids} for t, ids in claims],
                       "citations": sorted({i for _, ids in claims for i in ids}),
                       "refusal_reason": None, "clarification_question": None})


class ValidatorIntegrationTests(unittest.TestCase):
    """grounded_answer.validate passes the other claims citing the same passage as siblings."""

    def contract(self, docs):
        return ga.build_contract("Is protective headgear compulsory?", docs)[0]

    def test_split_exception_accepted_when_both_claims_cite_the_passage(self):
        c = self.contract([chunk("Rule 437", HELMET)])
        r = ga.validate(response([("Every rider of a two-wheeler shall wear protective headgear.", ["E1"]),
                                  ("A Sikh wearing a turban is exempted.", ["E1"])]), c)
        self.assertTrue(r.ok, r.errors)

    def test_sibling_citing_another_passage_does_not_count(self):
        other = "Synthetic Rule 900. A Sikh wearing a turban is exempted."
        c = self.contract([chunk("Rule 437", HELMET), chunk("Rule 900", other)])
        r = ga.validate(response([("Every rider of a two-wheeler shall wear protective headgear.", ["E1"]),
                                  ("A Sikh wearing a turban is exempted.", ["E2"])]), c)
        self.assertFalse(r.ok)
        self.assertIn("qualifier_omitted", {x["check"] for x in r.checks})

    def test_inlined_referent_accepted(self):
        c = self.contract([chunk("Rule 437", HELMET)])
        r = ga.validate(response([("Every rider of a two-wheeler shall wear protective headgear, except a Sikh "
                                   "wearing a turban.", ["E1"])]), c)
        self.assertTrue(r.ok, r.errors)


class CrossReferenceAdversarialTests(unittest.TestCase):
    """Audit: material changes behind a cross-reference must not be accepted."""

    def test_negated_referent_is_not_an_exception(self):
        self.assertIn("qualifier_altered", found(INLINE, R437 + "(2) A Sikh wearing a turban is not exempted."))

    def test_discretionary_referent_is_not_resolved(self):
        self.assertIn("qualifier_altered", found(INLINE, R437 + "(2) A Sikh wearing a turban may be exempted by the "
                                                                 "licensing authority."))

    def test_conditional_referent_is_not_resolved(self):
        self.assertIn("qualifier_altered", found(INLINE, R437 + "(2) A Sikh wearing a turban is exempted if he holds "
                                                                 "a medical certificate."))

    def test_referent_with_a_value_is_not_resolved(self):
        self.assertIn("qualifier_altered", found("Every rider of a two-wheeler shall wear protective headgear, except "
                                                 "a child below years of age.",
                                                 R437 + "(2) A child below 4 years of age is exempted."))

    def test_place_of_the_exception_cannot_be_dropped(self):
        self.assertIn("qualifier_altered", found(INLINE, R437 + "(2) A Sikh wearing a turban in Hyderabad is "
                                                                 "exempted."))

    def test_actor_of_the_exception_cannot_change(self):
        self.assertIn("qualifier_altered", found("Every rider of a two-wheeler shall wear protective headgear, except "
                                                 "a person wearing a turban.", R437 + "(2) A Sikh wearing a turban "
                                                                                      "is exempted."))

    def test_negation_inside_the_claimed_exception(self):
        self.assertIn("qualifier_altered", found("Every rider of a two-wheeler shall wear protective headgear, except "
                                                 "a Sikh not wearing a turban.", HELMET))

    def test_every_referenced_sub_rule_must_be_stated(self):
        two = ("Synthetic Rule 437. Every rider of a two-wheeler shall wear protective headgear, except a person "
               "exempted under sub-rule (2) or sub-rule (3). (2) A Sikh wearing a turban is exempted. (3) A rider on "
               "a farm track is exempted.")
        self.assertIn("qualifier_altered", found(INLINE, two))
        self.assertEqual(found("Every rider of a two-wheeler shall wear protective headgear, except a Sikh wearing a "
                               "turban or a rider on a farm track.", two), [])

    def test_duplicate_numbering_is_not_resolved(self):
        self.assertIn("qualifier_altered", found(INLINE, R437 + "(2) A Sikh wearing a turban is exempted. (2) A police "
                                                                 "officer on duty is exempted."))

    def test_reference_outside_the_qualifier_clause_is_ignored(self):
        p = ("Synthetic Rule 9. Except in an emergency, the driver shall stop as required by sub-rule (2). (2) A Sikh "
             "wearing a turban is exempted.")
        self.assertIn("qualifier_altered", found("Except a Sikh wearing a turban, the driver shall stop as required.", p))

    def test_reference_inside_quotation_marks_is_ignored(self):
        def resolved(text):
            ss = mc.sentences(text)
            return mc._cross_references(ss[1], ss, ga.strip_identifiers)[0]
        tail = " (2) A Sikh wearing a turban is exempted."
        self.assertEqual(resolved("Synthetic Order. The words \u201cexcept a person exempted under sub-rule (2)\u201d "
                                  "shall be inserted." + tail), {})
        self.assertEqual(resolved('Synthetic Order. The words "except a person exempted under sub-rule (2)" shall be '
                                  'inserted.' + tail), {})
        self.assertTrue(resolved("Synthetic Order. Every rider shall wear headgear, except a person exempted under "
                                 "sub-rule (2)." + tail))

    def test_referent_words_in_the_main_clause_do_not_cover_the_exception(self):
        # Stage 4 audit: "Sikh" moved into the main clause ("Every Sikh rider") does not state the exception
        self.assertIn("qualifier_altered", found("Every Sikh rider of a two-wheeler shall wear protective headgear, "
                                                 "except a person wearing a turban.", HELMET))
        self.assertIn("exemption", found("Every Sikh rider of a two-wheeler shall wear protective headgear, except a "
                                         "person wearing a turban.", HELMET, checks={"exemption"}))

    def test_changed_main_rule_is_still_caught_by_the_deontic_check(self):
        for claim in ("Every rider of a two-wheeler shall not wear protective headgear, except a Sikh wearing a "
                      "turban.", "Every rider of a two-wheeler may wear protective headgear, except a Sikh wearing a "
                                 "turban."):
            self.assertIn("deontic", found(claim, HELMET, checks={"deontic"}), claim)

    def test_missing_object_is_still_caught(self):
        self.assertTrue(found("Every rider of a two-wheeler shall wear, except a Sikh wearing a turban.", HELMET,
                              checks={"deontic", "exemption", "qualifier_added", "qualifier_altered"}))


class ClauseCoverageTests(unittest.TestCase):
    """The pre-existing 75% rule for a claim's own qualifier clause (found in this audit; also in the committed
    code): a clause word that also occurs in the sentence's main clause ("goods" in "A goods vehicle ...") counted
    towards the clause even when the claim dropped it from the clause."""

    def test_clause_word_borrowed_from_the_main_clause_does_not_count(self):
        self.assertEqual(found("A goods vehicle shall not carry passengers, except the owner or hirer.", GOODS),
                         ["qualifier_altered"])

    def test_full_clause_is_accepted(self):
        self.assertEqual(found("A goods vehicle shall not carry passengers, except the owner or hirer travelling with "
                               "the goods.", GOODS), [])

    def test_restructured_clause_with_all_its_words_is_accepted(self):
        self.assertEqual(found("A goods vehicle shall not carry passengers, except an owner or hirer who travels with "
                               "the goods.", GOODS), [])


class SiblingAdversarialTests(unittest.TestCase):
    GOODS_CLAIM = "A goods vehicle shall not carry passengers."

    def test_negated_sibling_does_not_state_the_exception(self):
        self.assertEqual(found(BASE, siblings=("A Sikh wearing a turban is not exempted.",)), ["qualifier_omitted"])
        self.assertEqual(found(self.GOODS_CLAIM, GOODS, siblings=(
            "The owner or hirer travelling with the goods may not travel.",)), ["qualifier_omitted"])

    def test_sibling_must_cite_the_qualifiers_own_passage(self):
        self.assertEqual(found(BASE, siblings=(("A Sikh wearing a turban is exempted.", ("E2",)),)),
                         ["qualifier_omitted"])

    def test_pointer_words_alone_do_not_state_a_referenced_exception(self):
        # "a person ... exempted" matches the words of "except a person exempted under sub-rule (2)", not its content
        self.assertEqual(found(BASE, siblings=("A person wearing a turban is exempted.",)), ["qualifier_omitted"])

    def test_siblings_do_not_combine(self):
        self.assertEqual(found(BASE, siblings=("A Sikh is exempted.", "A rider wearing a turban is exempted.")),
                         ["qualifier_omitted"])

    def test_duplicate_siblings_do_not_inflate_coverage(self):
        self.assertEqual(found(BASE, siblings=("A Sikh is exempted.",) * 3), ["qualifier_omitted"])

    def test_three_quarters_of_the_clause_is_not_enough(self):
        # "with the goods" restricts who may travel; a sibling that leaves it out does not state the exception
        self.assertEqual(found(self.GOODS_CLAIM, GOODS, siblings=("The owner or hirer may travel.",)),
                         ["qualifier_omitted"])

    def test_unrelated_condition_words_do_not_count(self):
        self.assertEqual(found(self.GOODS_CLAIM, GOODS, siblings=("A goods vehicle shall carry the goods of the owner "
                                                                  "only.",)), ["qualifier_omitted"])


class SiblingValidatorAdversarialTests(unittest.TestCase):
    def contract(self, docs):
        return ga.build_contract("Is protective headgear compulsory?", docs)[0]

    def test_a_rejected_sibling_rejects_the_whole_answer(self):
        c = self.contract([chunk("Rule 437", HELMET)])
        r = ga.validate(response([("Every rider of a two-wheeler shall wear protective headgear.", ["E1"]),
                                  ("A Sikh wearing a turban is not exempted.", ["E1"])]), c)
        self.assertFalse(r.ok)

    def test_sibling_citing_two_passages_counts_only_for_the_passage_it_shares(self):
        other = "Synthetic Rule 900. A Sikh wearing a turban is exempted."
        c = self.contract([chunk("Rule 437", HELMET.replace("(2) A Sikh wearing a turban is exempted.", "")),
                           chunk("Rule 900", other)])
        r = ga.validate(response([("Every rider of a two-wheeler shall wear protective headgear.", ["E1"]),
                                  ("A Sikh wearing a turban is exempted.", ["E1", "E2"])]), c)
        self.assertFalse(r.ok)


def p(body):
    return "Synthetic Rule 1. " + body


GOODS_TRAVEL = "A goods vehicle shall not carry passengers, except the owner or hirer travelling with the goods."
OFFICER = "Every rider shall wear protective headgear, except a Sikh police officer on duty."
VALID = "A learner may drive a motor car, provided that the learner holds a valid learner licence."
MEDICAL = "A conductor licence may be renewed, provided that the holder produces a medical fitness certificate."
DARK = "Vehicles shall not use the horn, except during the hours of darkness on highways."
CITY = "Vehicles may halt at a bus bay only within municipal limits of Hyderabad city."
DISTRICT = "Riders shall wear protective headgear, except riders on rural roads in Adilabad district."
NUMBER = "A goods vehicle shall not carry passengers, unless the vehicle carries fewer than 6 farm labourers."
INSTRUCTOR = "Every learner shall wear a helmet, provided a licensed instructor sits beside the learner."


def all_found(claim, source):
    return {c for c, _m in mc.check_claim(claim, "direct", {"E1": p(source)}, {}, strip=ga.strip_identifiers,
                                          definitive=True)}


class OwnQualifierCoverageTests(unittest.TestCase):
    """Stage 1 of the final review: a claim's own qualifier clause must keep every content word of the source's
    clause (was 75%). The nine reviewed omissions each change who or what the qualifier covers."""

    def assert_finding(self, claim, source, finding):
        self.assertIn(finding, all_found(claim, source), claim)

    def test_1_object_with_the_goods(self):
        self.assert_finding("A goods vehicle shall not carry passengers, except the owner or hirer travelling.",
                            GOODS_TRAVEL, "qualifier_altered")

    def test_2_actor_characteristic_sikh(self):
        self.assert_finding("Every rider shall wear protective headgear, except a police officer on duty.", OFFICER,
                            "qualifier_altered")

    def test_3_actor_condition_on_duty(self):
        self.assert_finding("Every rider shall wear protective headgear, except a Sikh police officer.", OFFICER,
                            "qualifier_altered")

    def test_4_eligibility_valid(self):
        self.assert_finding("A learner may drive a motor car, provided that the learner holds a learner licence.",
                            VALID, "qualifier_altered")

    def test_5_eligibility_medical(self):
        self.assert_finding("A conductor licence may be renewed, provided that the holder produces a fitness "
                            "certificate.", MEDICAL, "qualifier_altered")

    def test_6_time_of_darkness(self):
        self.assert_finding("Vehicles shall not use the horn, except during the hours on highways.", DARK,
                            "qualifier_altered")

    def test_7_place_of_hyderabad_city(self):
        self.assert_finding("Vehicles may halt at a bus bay only within municipal limits.", CITY, "qualifier_altered")

    def test_8_place_in_adilabad_district(self):
        self.assert_finding("Riders shall wear protective headgear, except riders on rural roads.", DISTRICT,
                            "qualifier_altered")

    def test_9_numeric_restriction(self):
        self.assert_finding("A goods vehicle shall not carry passengers, unless the vehicle carries farm labourers.",
                            NUMBER, "numeric_omitted")

    def test_main_clause_words_do_not_fill_the_qualifier(self):
        # "valid" moved out of the qualifier into the main clause does not keep the eligibility requirement
        self.assert_finding("A valid learner may drive a motor car, provided that the learner holds a learner licence.",
                            VALID, "qualifier_altered")

    def test_fully_preserved_qualifier(self):
        self.assertEqual(all_found(GOODS_TRAVEL, GOODS_TRAVEL) & QUALIFIER, set())
        self.assertEqual(all_found(INSTRUCTOR, INSTRUCTOR) & QUALIFIER, set())

    def test_faithful_qualifier_without_a_pronoun(self):
        self.assertEqual(all_found("A goods vehicle shall not carry passengers, except an owner or hirer who travels "
                                   "with the goods.", GOODS_TRAVEL) & QUALIFIER, set())

    def test_inflection_is_not_an_omission(self):
        # "travelling" and "travels" stem differently ("travell", "travel"); the doubled consonant is collapsed
        self.assertEqual(mc._inflection_free({"travell", "pass", "good"}), {"travel", "pas", "good"})

    def test_rule_subject_replaced_by_a_pronoun(self):
        self.assertEqual(all_found("Every learner shall wear a helmet, provided a licensed instructor sits beside them.",
                                   INSTRUCTOR) & QUALIFIER, set())


class SubjectPronounAllowanceTests(unittest.TestCase):
    """The pronoun allowance covers only the head word of the source's rule-subject, with exactly one pronoun in
    the claim's qualifier clause that agrees in number. Everything else stays strict."""

    def flagged(self, claim, source):
        self.assertIn("qualifier_altered", all_found(claim, source), claim)

    def test_cannot_hide_an_object(self):
        # "goods" modifies the rule-subject ("A goods vehicle") but is not its head; here it names the load
        self.flagged("A goods vehicle shall not carry passengers, except the owner or hirer travelling with them.",
                     GOODS_TRAVEL)

    def test_cannot_hide_an_eligibility_word(self):
        self.flagged("A learner may drive a motor car, provided that they hold a learner licence.", VALID)

    def test_cannot_hide_an_actor_characteristic(self):
        self.flagged("Every rider shall wear protective headgear, except a police officer on duty in their uniform.",
                     OFFICER)

    def test_cannot_hide_a_time_restriction(self):
        self.flagged("Vehicles shall not use the horn, except during their hours on highways.", DARK)

    def test_it_does_not_clearly_refer_to_the_rule_subject(self):
        # Stage 4 audit: "beside it" may mean the vehicle; "it"/"its" never receive the allowance
        self.flagged("Every learner shall wear a helmet, provided a licensed instructor sits beside it.", INSTRUCTOR)

    def test_two_pronouns_are_ambiguous(self):
        self.flagged("Every learner shall wear a helmet, provided a licensed instructor sits beside them with their "
                     "licence.", INSTRUCTOR)

    def test_pronoun_must_agree_with_a_plural_subject(self):
        plural = "Learners shall wear a helmet, provided a licensed instructor sits beside the learner."
        self.flagged("Learners shall wear a helmet, provided a licensed instructor sits beside him.", plural)
        self.assertEqual(all_found("Learners shall wear a helmet, provided a licensed instructor sits beside them.",
                                   plural) & QUALIFIER, set())

    def test_pronoun_outside_the_qualifier_clause_does_not_count(self):
        self.flagged("Every learner shall wear their helmet, provided a licensed instructor sits beside.", INSTRUCTOR)

    def test_no_subject_before_the_modal_means_no_allowance(self):
        # the source sentence opens with its qualifier, so no rule-subject is resolved for the allowance
        source = "Provided a licensed instructor sits beside the learner, every learner shall wear a helmet."
        self.flagged("Provided a licensed instructor sits beside them, every learner shall wear a helmet.", source)


class CrossReferenceKnownLimitationTests(unittest.TestCase):
    """CURRENT behaviour that is not desirable, pinned so that a change is noticed. Not targets."""

    def test_same_words_in_a_different_order(self):
        # "a person wearing a Sikh turban" uses every word of "a Sikh wearing a turban" (plus "person") but may
        # mean something wider; the lexical check cannot tell
        self.assertEqual(found("Every rider of a two-wheeler shall wear protective headgear, except a person wearing "
                               "a Sikh turban.", HELMET), [])

    def test_missing_actor_words_in_the_main_clause(self):
        # pre-existing restatement rule (RESTATE_COVERAGE 0.75): "Riders" for "Every rider of a two-wheeler"
        self.assertEqual(found("Riders shall wear protective headgear, except a Sikh wearing a turban.", HELMET), [])


if __name__ == "__main__":
    unittest.main()
