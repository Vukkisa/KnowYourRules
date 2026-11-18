"""Stage 4G: "custody of badge" and "liable to" in the penalty check of a model answer (backend/benign_wording.py).

Traced triggers: `custody` is in PENALTY_STRONG (meant for police detention); `liable\\s+to` is CONSEQUENCE_STRONG (meant
for legal liability). Both also occur in ordinary senses. Passages below are quoted from the Telangana Motor Vehicles Rules,
1989 as indexed (unofficial web copy). The guard itself is unchanged; these tests pin what the evidence-bound exception
neutralises and, above all, what it must leave locked.
"""
import unittest

from test_eligibility_status import chunk, raw, srv, validate

from backend import benign_wording as bw
from backend import grounded_answer as ga  # noqa: F401

R40 = "Custody and production of badge :- No driver shall lend or transfer the badge prescribed in these rules to any person."
R70 = "Custody of badge :- No conductor shall lend or transfer the badge prescribed in these rules to any other person."
R185 = ("The Driver or conductor having custody of the trip sheets shall produce them for inspection on demand by any "
        "person authorised in this behalf under the rules.")
R201 = ("Stage and contract carriages, carriage of goods restriction :- (1) No goods liable to foul the interior of the "
        "vehicle or to render it in sanitary, shall be carried at any time in any stage carriage or contract carriage ;")
R343 = ("Fixed steps shall not be less than 229 millimeters wide and shall in no case project laterally beyond the body "
        "of the vehicle unless they are so protected that they are not liable to injure pedestrians.")
R405 = ("(iii)if the vehicle has been stationary in one place for a continuous period of twenty four hours and adequate "
        "steps have not been taken for its repair or removal by the owner or his representative, remove the vehicle and "
        "its contents to a place of safe custody.")
R407 = ("Vehicle in parking place :- If a motor vehicle has been stationery in a duly appointed parking place for a period "
        "exceeding that specified by the competent authority in respect of the said place, or if no such period has been "
        "specified for a period exceeding six hours, any Police Officer may remove the vehicle to a place of safe custody.")
R297 = ("(ii) shall be liable to indemnify the consignee for any loss or damage to goods while in his control or "
        "possession but not for loss or damage due to an act of God or as natural calamity or due to inherent defect of "
        "goods or for reasons beyond his control ;")

CLEARED = {"R40": R40, "R70": R70, "R185": R185, "R201": R201, "R343": R343}
STILL_LOCKED = {"R405 (place of safe custody)": R405, "R407 (police removal to safe custody)": R407,
                "R297 (liable to indemnify)": R297}


class BenignMaskTests(unittest.TestCase):
    def test_the_guard_flags_all_of_them_unmodified(self):
        for name, text in {**CLEARED, **STILL_LOCKED}.items():
            with self.subTest(name=name):
                self.assertIsNotNone(srv.answer_drift_reason(text), name)

    def test_ordinary_sense_phrases_are_neutralised_when_the_cited_passage_has_them(self):
        for name, text in CLEARED.items():
            with self.subTest(name=name):
                self.assertIsNone(srv.answer_drift_reason(bw.mask(text, [text])), name)

    def test_nothing_is_neutralised_without_support_in_the_cited_evidence(self):
        unrelated = "437. Every rider of a two-wheeler shall wear protective headgear."
        for name, text in CLEARED.items():
            with self.subTest(name=name):
                self.assertEqual(bw.mask(text, [unrelated]), text)
                self.assertEqual(bw.mask(text, []), text)
                self.assertIsNotNone(srv.answer_drift_reason(bw.mask(text, [unrelated])), name)

    def test_the_wording_must_be_the_sources_wording(self):
        # different object or different verb than the cited passage: not neutralised
        self.assertIsNotNone(srv.answer_drift_reason(bw.mask("A driver has custody of the badge.", [R185])))
        self.assertIsNotNone(srv.answer_drift_reason(bw.mask("Goods liable to injure pedestrians.", [R201])))

    def test_enforcement_and_legal_liability_senses_stay_locked(self):
        for name, text in STILL_LOCKED.items():
            with self.subTest(name=name):
                self.assertIsNotNone(srv.answer_drift_reason(bw.mask(text, [text])), name)
        for text in ["The vehicle was taken into custody by the police.", "Police may hold the vehicle in custody.",
                     "The owner is in police custody.", "The vehicle is released from custody on payment.",
                     "The driver is liable to pay the arrears of tax.", "The owner shall be liable to make good the expenses.",
                     "The permit is liable to be suspended or cancelled.", "No person shall be liable to be convicted of an offence.",
                     "The holder is liable to be disqualified.", "He shall be liable to indemnify the consignee."]:
            with self.subTest(text=text):
                self.assertIsNotNone(srv.answer_drift_reason(bw.mask(text, [text])), text)

    def test_penalty_wording_beside_a_cleared_phrase_still_trips_the_guard(self):
        for text in [R40 + " The driver shall be fined Rs. 500 for lending it.",
                     R40 + " The badge shall be seized and the driver punished.",
                     R343 + " The licence may be suspended.",
                     R185 + " Failure is an offence."]:
            with self.subTest(text=text):
                self.assertIsNotNone(srv.answer_drift_reason(bw.mask(text, [text])), text)

    def test_hyphen_and_case_differences_do_not_break_the_match_but_do_not_widen_it(self):
        src = "Custody of trip-sheet :- Trip-sheets shall be kept."
        self.assertIsNone(srv.answer_drift_reason(bw.mask("CUSTODY OF TRIP SHEET :- kept.", [src])))
        self.assertIsNotNone(srv.answer_drift_reason(bw.mask("custody of the trip sheets", [src])))  # 'the', plural


class ValidatorTests(unittest.TestCase):
    def test_cleared_passages_are_accepted_as_verbatim_claims(self):
        for name, text in CLEARED.items():
            with self.subTest(name=name):
                res = validate([chunk("Rule X", text)], [(text, "E1")], "What does the rule say?")
                self.assertEqual((res.kind, res.errors), ("answer", []), (name, res.errors))

    def test_locked_passages_are_still_rejected_by_the_penalty_gate(self):
        for name, text in STILL_LOCKED.items():
            with self.subTest(name=name):
                res = validate([chunk("Rule X", text)], [(text, "E1")], "What does the rule say?")
                self.assertNotEqual(res.kind, "answer", name)
                self.assertTrue(any(e.startswith("penalty content withheld") for e in res.errors), (name, res.errors))

    def test_a_cleared_phrase_cited_to_the_wrong_passage_is_not_masked(self):
        docs = [chunk("Rule 40", R40), chunk("Rule 437", "437. Every rider shall wear protective headgear.")]
        res = validate(docs, [(R40, "E2")], "What does the rule say?")
        self.assertNotEqual(res.kind, "answer")


if __name__ == "__main__":
    unittest.main()
