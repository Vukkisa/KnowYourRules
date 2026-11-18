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


def ref_check(claim, passage, siblings=()):
    return [c for c, _m in mc.check_claim(claim, "direct", {"E1": passage}, {}, strip=ga.strip_identifiers,
                                          definitive=True, siblings=siblings, id_fn=ga.identifiers)]


class OmittedReferences(unittest.TestCase):
    """Stage 3D: reference_omitted, per reference kind. Quantities and qualifiers keep their own checks."""
    CASES = [("Synthetic Rule 900. Every rider shall wear protective headgear conforming to Section 129.",
              "Every rider shall wear protective headgear."),
             ("Synthetic Rule 900. A person exempted under sub-rule (2) need not wear protective headgear.",
              "A person exempted need not wear protective headgear."),
             ("Synthetic Rule 900. The registering authority shall issue the certificate in accordance with Rule 81.",
              "The registering authority shall issue the certificate."),
             ("Synthetic Rule 900. The application for renewal shall be made in Form 25.",
              "The application for renewal shall be made."),
             ("Synthetic Rule 900. The tax shall be levied at the rates specified in the Second Schedule.",
              "The tax shall be levied at the rates specified."),
             ("Synthetic Rule 900. The amended fee shall come into force from 01-04-2026.",
              "The amended fee shall come into force.")]

    def test_each_omitted_reference_flagged(self):
        for passage, claim in self.CASES:
            self.assertIn("reference_omitted", ref_check(claim, passage), claim)

    def test_kept_references_pass(self):
        kept = ["Every rider shall wear protective headgear conforming to Section 129.",
                "A person exempted under Rule 900(2) need not wear protective headgear.",
                "The registering authority shall issue the certificate in accordance with Rule 81.",
                "The application for renewal shall be made in Form 25.",
                "The tax shall be levied at the rates specified in the Second Schedule.",
                "The amended fee shall come into force from 1 April 2026."]
        for (passage, _), claim in zip(self.CASES, kept):
            self.assertEqual(ref_check(claim, passage), [], claim)

    def test_reference_stated_by_a_sibling_citing_the_same_passage(self):
        passage, claim = self.CASES[0]
        self.assertNotIn("reference_omitted", ref_check(claim, passage, (("The headgear must conform to Section 129.",
                                                                          ("E1",)),)))
        self.assertIn("reference_omitted", ref_check(claim, passage, (("The headgear must conform to Section 129.",
                                                                       ("E2",)),)))

    def test_resolved_sub_rule_pointer_may_be_inlined(self):
        # the existing cross-reference checks require the referent itself; repeating "sub-rule (2)" is not needed
        self.assertEqual(ref_check("Every rider of a two-wheeler shall wear protective headgear, except a Sikh "
                                   "wearing a turban.", HELMET), [])
        self.assertIn("qualifier_omitted", ref_check("Every rider of a two-wheeler shall wear protective headgear.",
                                                     HELMET))

    def test_off_without_identifier_function(self):
        passage, claim = self.CASES[0]
        self.assertNotIn("reference_omitted", check(claim, passage))


class FusedHeadingComparison(unittest.TestCase):
    """Stage 3C: _quoted_heading_body separates a title-like heading only, and only for an exact quotation."""
    FUSED = "Crash helmets to be worn : - The protective headgear under Section 129 shall be a standard one."
    BODY = "The protective headgear under Section 129 shall be a standard one."

    def test_exact_body_separated(self):
        self.assertEqual(mc._quoted_heading_body(self.BODY, self.FUSED), self.BODY)
        self.assertEqual(mc._quoted_heading_body(self.BODY.upper(), self.FUSED), self.BODY)
        self.assertEqual(check(self.BODY, self.FUSED), [])

    def test_no_separation_for_anything_but_an_exact_quotation(self):
        for claim in ("The protective headgear shall be a standard one.",
                      "The protective headgear under Section 128 shall be a standard one.",
                      "The headgear under Section 129 shall be a standard one.",
                      self.BODY + " Riders must also wear gloves."):
            self.assertIsNone(mc._quoted_heading_body(claim, self.FUSED), claim)
            self.assertIn("unverifiable_direct", check(claim, self.FUSED), claim)

    def test_no_separation_without_a_title_like_heading(self):
        follows = "The fee shall be as follows : - Rs. 500 for a motor cycle."
        self.assertIsNone(mc._quoted_heading_body("Rs. 500 for a motor cycle.", follows))  # strong modal: not a title
        self.assertIsNone(mc._quoted_heading_body(self.BODY, self.BODY))                  # nothing fused
        self.assertIsNone(mc._quoted_heading_body(self.BODY, "Crash helmets: " + self.BODY))  # plain colon, no dash


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
