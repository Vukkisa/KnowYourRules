"""Action-aware uncited-conflict detection (backend/meaning_checks.py). Lexical heuristics only: these tests pin
behaviour on synthetic sentences; passing them does not show that a real contradiction is or is not present.
Adversarial cases (must be flagged), controls (must not be flagged) and documented limitations are kept apart."""

import unittest

from backend import grounded_answer as ga
from backend import meaning_checks as mc

UNCITED = {"uncited_conflict", "uncited_qualification"}


def flags(claim, uncited_sentence, cited=None, definitive=True):
    """Uncited-evidence findings for a verbatim claim cited to itself (other checks cannot fire on it)."""
    found = mc.check_claim(claim, "direct", {"E1": cited or claim}, {"E2": uncited_sentence},
                           strip=ga.strip_identifiers, definitive=definitive)
    return [c for c, _m in found if c in UNCITED]


class ConflictAdversarialTests(unittest.TestCase):
    def test_same_subject_and_action_opposite_negation(self):
        self.assertEqual(flags("A rider shall wear a helmet.", "A rider need not wear a helmet."),
                         ["uncited_conflict"])
        self.assertEqual(flags("A rider shall wear a helmet.", "A rider shall not wear a helmet."),
                         ["uncited_conflict"])

    def test_same_proposition_required_vs_not_required(self):
        self.assertEqual(flags("A rider is required to wear a helmet.", "A rider is not required to wear a helmet."),
                         ["uncited_conflict"])

    def test_prohibition_vs_permission_on_the_same_object(self):
        self.assertEqual(flags("A goods vehicle shall not carry passengers.", "A goods vehicle may carry passengers."),
                         ["uncited_conflict"])

    def test_exemption_of_the_same_class_from_the_same_action(self):
        self.assertEqual(flags("Every rider shall wear a helmet.", "Riders are exempt from wearing a helmet."),
                         ["uncited_conflict"])

    def test_definitive_status_only(self):
        self.assertEqual(flags("A rider shall wear a helmet.", "A rider need not wear a helmet.", definitive=False),
                         [])


class QualificationAdversarialTests(unittest.TestCase):
    """Still flagged (a definitive one-sided answer is rejected), but not called a contradiction."""

    def test_exemption_for_a_narrower_class(self):
        self.assertEqual(flags("Every rider shall wear a helmet.", "Riders on rural roads are exempt from helmets."),
                         ["uncited_qualification"])

    def test_release_under_a_condition_clause(self):
        self.assertEqual(flags("A rider shall wear a helmet.",
                               "A rider need not wear a helmet if the rider is a Sikh wearing a turban."),
                         ["uncited_qualification"])

    def test_release_in_a_narrower_place(self):
        self.assertEqual(flags("A rider shall wear a helmet.", "A rider need not wear a helmet within municipal "
                                                                "limits."), ["uncited_qualification"])

    def test_permission_carving_out_a_different_object(self):
        # "farm labourers" are not lexically "passengers": flagged as a possible carve-out, not a contradiction
        self.assertEqual(flags("A goods vehicle shall not carry passengers.",
                               "A goods vehicle may carry farm labourers with the goods."),
                         ["uncited_qualification"])

    def test_claim_without_a_parsable_proposition_keeps_the_older_test(self):
        # no modal or verb anchor in the claim: the subject-word fallback still flags it (no new false negative)
        self.assertEqual(flags("Protective headgear compulsory for every two-wheeler rider.",
                               "Every two-wheeler rider need not wear protective headgear."), ["uncited_conflict"])


class ConflictControlTests(unittest.TestCase):
    def test_same_subject_different_actions(self):
        self.assertEqual(flags("The licensing authority shall issue the licence within seven days.",
                               "The licensing authority shall not retain the original documents."), [])
        self.assertEqual(flags("The licensing authority shall issue a licence.",
                               "The licensing authority shall maintain licence records."), [])

    def test_same_action_different_subjects(self):
        self.assertEqual(flags("The driver shall carry the document.",
                               "The vehicle owner shall not carry the document."), [])

    def test_duty_and_ban_on_different_objects(self):
        self.assertEqual(flags("The vehicle shall carry a first-aid box.",
                               "The vehicle shall not carry more persons than the seating capacity of the vehicle."),
                         [])

    def test_value_bounds_are_not_negations(self):
        self.assertEqual(flags("The depth of the seat shall be 406 millimetres.",
                               "The depth of the seat shall not be less than 400 millimetres."), [])

    def test_heading_states_no_position(self):
        self.assertEqual(flags("A towing vehicle shall not exceed the speed limit.",
                               "Telangana Motor Vehicles Rules, 1989 - Rule 421 - Speed of towing vehicle"), [])

    def test_negation_inside_a_condition_about_someone_else(self):
        self.assertEqual(flags("The licensing authority shall send an intimation.",
                               "If the licensing authority which issues a duplicate licence is not the original "
                               "authority, it shall send an intimation."), [])

    def test_same_polarity_and_complementary_rules(self):
        self.assertEqual(flags("Every rider shall wear a helmet.", "Every rider shall fasten the helmet securely."),
                         [])
        self.assertEqual(flags("Every rider shall wear a helmet.", "Every pillion rider shall wear a helmet."), [])

    def test_proposition_parts(self):
        p = mc.proposition("Stamping of duplicate Licence:- The licensing authority shall not be issuing licences.")
        self.assertEqual((p.actor, p.action, p.polarity), ({"licens", "authority"}, "issu", "prohibition"))
        self.assertIsNone(mc.proposition("Speed of towing vehicle"))
        self.assertIsNone(mc.proposition("shall be the Transport Commissioner."))  # no actor before the anchor


class ConflictKnownLimitationTests(unittest.TestCase):
    """CURRENT behaviour that is not desirable, pinned so that a change is noticed. Not targets."""

    def test_passive_restatement_is_not_aligned(self):
        self.assertEqual(flags("The licensing authority shall issue a licence.",
                               "A licence shall not be issued by the licensing authority."), [])

    def test_synonyms_are_not_aligned(self):
        self.assertEqual(flags("A rider shall wear a helmet.", "A motorcyclist need not wear protective headgear."),
                         [])

    def test_generic_actor_word_plus_the_same_target_is_enough(self):
        # "vehicle" links two different classes of vehicle; with the same thing exhibited ("registration mark") the
        # pair is flagged as a qualification, though the classes may simply be different
        self.assertEqual(flags("The goods vehicle shall exhibit the registration mark.",
                               "Vehicles registered by the Government need not exhibit the registration mark."),
                         ["uncited_qualification"])


if __name__ == "__main__":
    unittest.main()
