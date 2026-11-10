"""Uncited-evidence checks: one negative control per root cause found in the real-index residual review, and an
adversarial case per fix showing it does not hide a real opposite position. Synthetic sentences, written for these
tests (not copied from the corpus). Lexical heuristics: passing does not show that a contradiction is or is not
really present."""

import unittest

from backend import grounded_answer as ga
from backend import meaning_checks as mc

UNCITED = {"uncited_conflict", "uncited_qualification"}


def flags(claim, uncited_sentence, definitive=True):
    found = mc.check_claim(claim, "direct", {"E1": claim}, {"E2": uncited_sentence},
                           strip=ga.strip_identifiers, definitive=definitive)
    return [c for c, _m in found if c in UNCITED]


class ResidualRootCauseControls(unittest.TestCase):
    """Each pair states compatible positions; before the fix each one was flagged."""

    def test_number_abbreviation_is_not_a_negation(self):
        self.assertEqual(flags("The applicant shall submit the form named in letter No.115 to the authority.",
                               "The applicant shall submit the form to the authority."), [])
        self.assertEqual(flags("From the Transport Commissioner, letter No.2494, dated",
                               "The Transport Commissioner, Hyderabad."), [])

    def test_title_states_no_position(self):
        self.assertEqual(flags("Provided that no person shall be liable for failure to display the board.",
                               "Telangana Motor Vehicles Rules, 1989 - Rule 421 - Speed of towing vehicle"), [])

    def test_negation_inside_a_leading_condition(self):
        self.assertEqual(flags("When a duplicate licence is issued it shall be stamped in red.",
                               "If the licensing authority which issues a duplicate licence is not the original "
                               "authority it shall intimate the fact to that authority."), [])

    def test_condition_only_fragment(self):
        self.assertEqual(flags("The applicant shall state the particulars of the new vehicle.",
                               "(ii) if the new vehicle is not in his possession"), [])

    def test_definition_states_no_position(self):
        self.assertEqual(flags("“Agent” means a person who sells tickets for public service vehicles.",
                               "The agent shall not permit the licence to be used by any other person."), [])

    def test_negation_inside_a_relative_clause(self):
        self.assertEqual(flags("The Transport Authority may specify in the permit the goods which shall not be "
                               "carried.", "The Transport Authority may specify in the permit the maximum weight "
                                           "of luggage which may be carried."), [])

    def test_object_stated_only_in_an_only_clause(self):
        self.assertEqual(flags("The vehicle shall not be used for hire or reward.",
                               "The vehicle shall be used only on the routes specified in the permit."), [])

    def test_as_the_case_may_be_and_a_trailing_condition(self):
        self.assertEqual(flags("The Secretary or the Additional Secretary, as the case may be, may on application "
                               "sanction the refund of fees.",
                               "The Secretary, as the case may be, may on application sanction the refund of fees "
                               "in case where the remittance is not followed by an appeal."), [])

    def test_negation_inside_a_trailing_condition(self):
        self.assertEqual(flags("No refund of the fee shall be made after the inspection.",
                               "No refund of the fee shall be made if the application is not made within three "
                               "months."), [])

    def test_rank_and_value_bounds(self):
        self.assertEqual(flags("Police officers not below the rank of inspector may inspect the vehicle.",
                               "Police officers may inspect the vehicle."), [])
        self.assertEqual(flags("The gangway shall be 600 millimetres wide.",
                               "The gangway shall not be less that 610 millimetres wide."), [])  # "that" (sic)

    def test_result_clause_is_the_requirement(self):
        self.assertEqual(flags("The fuel tank shall be so placed and shielded that no overflow shall fall upon the "
                               "exhaust.", "No fuel tank shall be placed under any gangway."), [])

    def test_generic_actor_word_with_different_targets(self):
        self.assertEqual(flags("In the case of a transport vehicle the registration mark shall be exhibited in two "
                               "lines.", "Vehicles registered under section 60 need not exhibit the "
                                         "particulars in clause six."), [])


class ResidualFixesStillFlag(unittest.TestCase):
    """The same constructions with a real opposite position are still flagged."""

    def test_generic_actor_with_the_same_passive_target(self):
        self.assertEqual(flags("The following particulars of every transport vehicle shall be exhibited on the "
                               "left side.", "Vehicles registered under section 60 need not exhibit "
                                             "the particulars."), ["uncited_qualification"])

    def test_opposite_relative_clauses(self):
        self.assertEqual(flags("The inspector may direct that a fresh certificate shall be obtained.",
                               "The inspector may direct that a fresh certificate shall not be obtained."),
                         ["uncited_conflict"])

    def test_opposite_positions_after_the_same_leading_condition(self):
        self.assertEqual(flags("If the vehicle is a goods vehicle, the owner shall display the board.",
                               "If the vehicle is a goods vehicle, the owner need not display the board."),
                         ["uncited_conflict"])

    def test_second_position_after_a_trailing_condition(self):
        self.assertEqual(flags("The owner may, and if so required by the tribunal shall, appear in person.",
                               "The owner may, and if so required by the tribunal shall not, appear in person."),
                         ["uncited_conflict"])

    def test_trailing_condition_does_not_hide_the_main_position(self):
        self.assertEqual(flags("No refund of the fee shall be made.",
                               "A refund of the fee shall be made if the application is made within three months."),
                         ["uncited_qualification"])

    def test_no_as_a_determiner_is_still_a_negation(self):
        self.assertEqual(flags("A conductor shall carry passengers on the roof.",
                               "No conductor shall carry passengers on the roof."), ["uncited_conflict"])

    def test_result_clause_with_the_opposite_requirement(self):
        self.assertEqual(flags("The fuel tank shall be so placed that overflow shall fall upon the exhaust.",
                               "The fuel tank shall be so placed that no overflow shall fall upon the exhaust."),
                         ["uncited_conflict"])


class ResultClauseTests(unittest.TestCase):
    """Real-index false positive #14: two "so constructed that" sentences about the same vehicle state two separate
    requirements (who may sit where; what the driver must see). Their result clauses share "driver", "right",
    "hand", "side", but say different things about different subjects, so they are not opposites."""

    def test_complementary_result_clauses_are_separate_requirements(self):
        self.assertEqual(flags("No public service vehicle shall be so constructed that a person may sit on the "
                               "right hand side of the driver.",
                               "Every public service vehicle shall be so constructed that the driver has a clear "
                               "view to the right hand side."), [])

    def test_the_same_result_clause_required_and_forbidden_is_still_a_conflict(self):
        self.assertEqual(flags("Every public service vehicle shall be so constructed that a seat is provided on the "
                               "right hand side of the driver.",
                               "No public service vehicle shall be so constructed that a seat is provided on the "
                               "right hand side of the driver."), ["uncited_conflict"])

    def test_result_clause_that_negates_itself_is_still_a_conflict(self):
        self.assertEqual(flags("Every public service vehicle shall be so constructed that a seat is provided on the "
                               "right hand side of the driver.",
                               "Every public service vehicle shall be so constructed that no seat is provided on "
                               "the right hand side of the driver."), ["uncited_conflict"])

    def test_empty_result_clause_before_a_list_is_not_a_separate_requirement(self):
        # "so constructed that, -" with the items in the next sentence: nothing to compare, the main clause decides
        # (a planted real-index case was lost while an empty clause counted as a different requirement)
        self.assertEqual(flags("Every public service vehicle shall be so constructed that, -",
                               "Every public service vehicle shall not be so constructed that, -"),
                         ["uncited_conflict"])


class ConditionWordsAreNotTheObjectTests(unittest.TestCase):
    """Real-index false positive #17: a ban on crossing the stop line "when a signal to stop is, being given by ...
    a traffic sign" and a duty to obey "any indication given by a traffic sign". The objects compared were
    {given, traffic, sign}: "traffic" and "sign" came from the ban's trailing "when ..." condition (the stray comma
    in "is, being given" ended the condition early), and "given" from both. What each driving rule applies to (the
    stop line; conformity with indications) shares nothing, so a duty and a ban on different objects coexist.

    Filler words added: "given" (NON_LINKING_OBJECT_WORDS in backend/meaning_checks.py). It is a participle
    ("indication given by", "notice given to") that says nothing about which thing the action applies to, so on its
    own it does not link two objects. No other word was added to that list or to GENERIC_ACTOR."""

    def test_stop_line_ban_and_duty_to_obey_signs_coexist(self):
        self.assertEqual(flags("No driver shall drive a motor vehicle beyond the stop line at any time when a signal "
                               "to stop is, being given by a traffic sign.",
                               "Every driver shall drive in conformity with any indication given by a traffic "
                               "sign."), [])

    def test_given_alone_does_not_link_two_objects(self):
        self.assertEqual(flags("The conductor shall issue a receipt given by the depot.",
                               "The conductor shall not issue a pass given at the gate."), [])

    def test_given_with_a_specific_shared_object_still_flags(self):
        self.assertEqual(flags("Every driver shall drive in conformity with any indication given by the sign.",
                               "No driver shall drive in conformity with any indication given by the sign."),
                         ["uncited_conflict"])

    def test_condition_words_removed_from_the_object_do_not_hide_a_shared_object(self):
        self.assertEqual(flags("The conductor shall carry the ticket rack when on duty.",
                               "The conductor shall not carry the ticket rack when on duty."), ["uncited_conflict"])


if __name__ == "__main__":
    unittest.main()
