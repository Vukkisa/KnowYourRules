"""Unit tests for the heuristic meaning-preservation layer. Passage text is synthetic, not legal text.
Passing these tests does not show that meaning or law is preserved; it shows the listed surface changes are caught
and the listed faithful paraphrases are not."""

import unittest

from backend import grounded_answer as ga
from backend import meaning_checks as mc

HELMET = ("Synthetic Rule 437. Every rider of a two-wheeler shall wear protective headgear, except a person exempted "
          "under sub-rule (2). (2) A Sikh wearing a turban is exempted.")
GOODS = "Synthetic Rule 245. A goods vehicle shall not carry passengers, except the owner or hirer travelling with goods."
LICENCE = "Synthetic Rule 8. An applicant must be at least 18 years of age."
FEE = "Synthetic Rule 9. The fee is Rs. 1,000/- for a motor car and Rs. 400/- for a motor cycle."
VALIDITY = "Synthetic Rule 10. A temporary permit is valid for one month."
MAY = "Synthetic Rule 11. The licensing authority may refuse the application."
SMOKE = "Synthetic Rule 12. Smoking in a stage carriage is prohibited."


def check(claim, passage, kind="direct", uncited=None, definitive=True):
    return [c for c, _m in mc.check_claim(claim, kind, {"E1": passage}, uncited or {},
                                          strip=ga.strip_identifiers, definitive=definitive)]


class FaithfulParaphrasesPass(unittest.TestCase):
    """False-positive controls: none of these should be rejected."""

    def test_modal_synonyms(self):
        self.assertEqual(check("Every rider of a two-wheeler must wear protective headgear, except a person exempted "
                               "under sub-rule (2).", HELMET), [])
        self.assertEqual(check("Smoking in a stage carriage is not allowed.", SMOKE, "interpretation"), [])
        self.assertEqual(check("Passengers may not be carried in a goods vehicle, except the owner or hirer "
                               "travelling with goods.", GOODS), [])

    def test_qualifier_moved_to_the_front(self):
        self.assertEqual(check("Except a person exempted under sub-rule (2), every rider of a two-wheeler shall wear "
                               "protective headgear.", HELMET), [])

    def test_number_formats(self):
        self.assertEqual(check("An applicant must be at least eighteen years of age.", LICENCE), [])
        self.assertEqual(check("The fee is ₹1000 for a motor car.", FEE), [])
        self.assertEqual(check("A temporary permit is valid for 1 month.", VALIDITY), [])

    def test_partial_claim_about_one_case_of_a_multi_value_sentence(self):
        self.assertEqual(check("The fee is Rs. 400 for a motor cycle.", FEE), [])

    def test_interpretation_of_a_sub_rule(self):
        self.assertEqual(check("A Sikh wearing a turban does not have to wear protective headgear.", HELMET,
                               "interpretation"), ["deontic", "exemption"])  # documented: conservative
        self.assertEqual(check("A Sikh wearing a turban is exempted from wearing protective headgear.", HELMET,
                               "interpretation"), [])

    def test_uncited_passage_with_same_polarity_or_other_subject(self):
        same = {"E2": "Synthetic Rule 439. Every rider of a two-wheeler shall fasten the protective headgear."}
        other = {"E2": GOODS}
        claim = "Every rider of a two-wheeler shall wear protective headgear, except a person exempted under sub-rule (2)."
        self.assertEqual(check(claim, HELMET, uncited=same), [])
        self.assertEqual(check(claim, HELMET, uncited=other), [])

    def test_verbatim_sentences(self):
        for s in mc.sentences(FEE + " " + LICENCE):
            if len(mc.words(s)) >= 3:
                self.assertEqual(check(s, FEE + " " + LICENCE), [], s)


class MeaningChangesRejected(unittest.TestCase):
    def test_negation_and_modality(self):
        self.assertIn("deontic", check("A goods vehicle shall carry passengers, except the owner or hirer travelling "
                                       "with goods.", GOODS))
        self.assertIn("deontic", check("Smoking in a stage carriage is allowed.", SMOKE))
        self.assertIn("deontic", check("The licensing authority must refuse the application.", MAY))
        self.assertIn("deontic", check("The licensing authority may not refuse the application.", MAY))

    def test_exception_omitted_or_altered(self):
        self.assertIn("qualifier_omitted", check("A goods vehicle shall not carry passengers.", GOODS))
        self.assertIn("qualifier_altered", check("A goods vehicle shall not carry passengers, except the driver's "
                                                 "family.", GOODS))

    def test_comparator_value_and_unit(self):
        self.assertIn("numeric_changed", check("An applicant must be 18 years of age.", LICENCE))      # 'at least' lost
        self.assertIn("numeric_changed", check("An applicant must be at least 16 years of age.", LICENCE))
        self.assertIn("numeric_changed", check("A temporary permit is valid for one year.", VALIDITY))  # unit changed
        self.assertTrue({"numeric_omitted", "unverifiable_direct"} & set(check("An applicant must be of age.",
                                                                                 LICENCE)))
        self.assertIn("numeric_association", check("The fee is Rs. 1000 for a motor cycle.", FEE))

    def test_invented_condition_and_composition(self):
        self.assertIn("qualifier_added", check("A temporary permit is valid for one month unless renewed.", VALIDITY))
        found = [c for c, _m in mc.check_claim(
            "Smoking in a stage carriage is prohibited because the licensing authority may refuse the application.",
            "direct", {"E1": SMOKE, "E2": MAY}, {}, strip=ga.strip_identifiers, definitive=True)]
        self.assertIn("composition", found)

    def test_direct_claim_that_restates_nothing_fails_closed(self):
        self.assertIn("unverifiable_direct", check("Headgear protects riders.", HELMET))

    def test_uncited_contradiction_requires_conflict_status(self):
        uncited = {"E2": "Synthetic Rule 440. Riders on rural roads are exempt from protective headgear."}
        claim = "Every rider of a two-wheeler shall wear protective headgear, except a person exempted under sub-rule (2)."
        # a narrower class ("riders on rural roads") exempted: a qualification, not called a contradiction
        self.assertEqual(check(claim, HELMET, uncited=uncited), ["uncited_qualification"])
        self.assertEqual(check(claim, HELMET, uncited=uncited, definitive=False), [])


class ValidatorLayerTests(unittest.TestCase):
    def test_findings_are_labelled_by_layer(self):
        import json
        from langchain_core.documents import Document
        doc = Document(page_content=GOODS, metadata={"manifest_id": "s", "provision_id": "Rule 245", "part": 1,
                                                     "parts": 1, "answer_eligible": True, "location": "s#245"})
        contract, _ = ga.build_contract("q", [doc], "r")
        claim = "A goods vehicle shall carry passengers, except the owner or hirer travelling with goods."
        raw = json.dumps({"answer": claim, "evidence_sufficiency": "sufficient",
                          "claims": [{"text": claim, "kind": "direct", "evidence_ids": ["E1"]}], "citations": ["E1"],
                          "refusal_reason": None, "clarification_question": None})
        v = ga.validate(raw, contract)
        self.assertFalse(v.ok)
        self.assertEqual({(c["layer"], c["check"]) for c in v.checks}, {("heuristic", "deontic")})
        bad = ga.validate("not json", contract)
        self.assertEqual(bad.checks[0]["layer"], "deterministic")


if __name__ == "__main__":
    unittest.main()
