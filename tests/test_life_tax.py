"""Life-tax question (Stage 2): the validator's handling of verbatim list items, and the withheld rate schedule.

The texts below are the stored chunk texts of the preview index, not fixtures written for the test:
  * Rule 13 of the Telangana Motor Vehicles Taxation Rules, 1963 (manifest id tmvtr-1963);
  * the opening of the Third Schedule substituted by G.O.Ms.No. 53 dated 13.08.2025 (go-ms-53-2025-trb), the
    life-tax rates for motor cycles. Its table extraction is unreliable, so the reviewed chunk flags keep it out of
    answers. tests/test_life_tax_real.py checks both texts against the index. Offline."""

import json
import unittest
from pathlib import Path

from langchain_core.documents import Document

from test_server import srv

from backend import build_telangana_index, grounded_answer, meaning_checks

ROOT = Path(__file__).resolve().parent.parent
FLAGS = ROOT / "docs" / "legal-sources" / "telangana-traffic" / "PREVIEW-CHUNK-FLAGS.json"

RULE_13_ROWS = (
    "(1)Within one month from the beginning of the quarter, half-year or year as the case may be",
    "(2)Within two months from the beginning of the quarter, half-year or year, as the case may be",
    "(3)For over two months from the beginning of the quarter, half year or year, as the case may",
    "(4)For each calendar month or part thereof in respect of motor vehicles for which life time or lumpsum is "
    "prescribed.",
)
RULE_13_TEXT = "\n".join((
    "Telangana Motor Vehicles Taxation Rules, 1963 - Rule 13 - Rates of penalty",
    "13 Rates of penalty : - If the tax due in respect of motor vehicle has not been paid as specified in Section 4, "
    "the Licensing Officer shall impose the penalty under Section 6 of the Act as specified in the table below:",
    "TABLE", "PERIOD", "AMOUNT OF PENALTY", *RULE_13_ROWS,
    "Not exceeding one half of the quarterly tax", "Not exceeding the amount of quarterly tax",
    "Not exceeding twice the quarterly tax",
    "Not exceeding 2% of the life time or lumpsum tax for calendar month or part thereof subject to a maximum of "
    "twice the life time or lumpsum tax due"))
RULE_13 = Document(page_content=RULE_13_TEXT, metadata={
    "manifest_id": "tmvtr-1963", "title": "Telangana Motor Vehicles Taxation Rules, 1963", "document_type": "Rules",
    "document_number": "", "source_file": "middle-ap-mv-tr-1963-main.htm", "sha256": "d" * 64,
    "provision_kind": "Rule", "provision_id": "Rule 13", "provision_heading": "Rates of penalty", "part": 1,
    "parts": 1, "location": "html-snapshots/tmvtr-1963/middle-ap-mv-tr-1963-main.htm#14", "has_table": True,
    "state": "Telangana", "answer_eligible": True})

GO_53_TITLE = ("Amendment to the Third, Sixth and Seventh Schedules under section 3 of Telangana Motor Vehicles "
               "Taxation Act, 1963 (Act No.5 of 1963) for Enhancement of life tax in Transport and Non-Transport "
               "Vehicles - Notification")
THIRD_SCHEDULE_OPENING = "\n".join((
    GO_53_TITLE + " - THIRD SCHEDULE",
    "THE THIRD SCHEDULE",
    "(See Second Proviso to sub-section (2) of section -3)",
    "Motor Cycles including Tri-Cycles, Motor Scooters and Motor",
    "Cycles with or without attachment at the rates specified below on",
    "the Cost of Vehicles.",
    "Sl. | Period/ Class of Whose cost is | Whose cost is | Whose | Whose | Invalid",
    "No. | Ve h i c l e | below | Rs. 50,000 to | cost is Rs. | cost is Carriage",
    "Rs.50,000 | Rs. 1 Lakh | 1 Lakh to | above Rs.",
    "2 Lakh | 2 Lakh",
    "(1) (2) | (3) | (4) | (5) (6) | (7)",
    "1. | At the time of | 9% | 12% | 15% 18%",
    "registration new",
    "vehicles"))
GO_53_PARAGRAPH_1 = (GO_53_TITLE + " - Paragraph 1 - For the Third Schedule, the following shall be substituted, namely\n"
                     "1. For the Third Schedule, the following shall be substituted, namely:-")


def go_53_chunk(text, provision_kind, provision_id):
    return Document(page_content=text, metadata={
        "manifest_id": "go-ms-53-2025-trb", "title": GO_53_TITLE, "document_type": "G.O.",
        "document_number": "G.O.Ms.No. 53", "source_file": "13082025TRB_MS53.PDF", "sha256": "a" * 64,
        "provision_kind": provision_kind, "provision_id": provision_id, "provision_heading": "", "part": 1,
        "parts": 1, "location": "goir/13082025TRB_MS53.PDF#page=1", "has_table": provision_kind == "Schedule",
        "state": "Telangana", "answer_eligible": True, "extraction_warning": ""})


def response(*claims):
    """A model response whose claims are (text, evidence id) pairs, all direct."""
    return json.dumps({"answer": " ".join(t for t, _ in claims), "evidence_sufficiency": "sufficient",
                       "claims": [{"text": t, "kind": "direct", "evidence_ids": [e]} for t, e in claims],
                       "citations": sorted({e for _, e in claims}), "refusal_reason": None,
                       "clarification_question": None})


def answer(docs, raw, question="How is life tax calculated for a new two-wheeler in Telangana?"):
    generator = grounded_answer.MockGenerator(raw)
    return grounded_answer.answer(question, docs, generator, penalty_reason=srv.answer_drift_reason), generator


class VerbatimListItemTests(unittest.TestCase):
    """Root cause: the period rows of Rule 13 differ only in a number, and number words are not content words."""

    def test_rows_are_separate_sentences_with_the_same_content_words(self):
        body = RULE_13_TEXT.partition("\n")[2]
        self.assertEqual(meaning_checks.sentences(body)[2:6], list(RULE_13_ROWS))
        self.assertEqual(meaning_checks.words(RULE_13_ROWS[0]), meaning_checks.words(RULE_13_ROWS[1]))

    def test_each_row_quoted_verbatim_is_accepted_and_cited(self):
        for row in RULE_13_ROWS:
            result, _ = answer([RULE_13], response((row, "E1")))
            self.assertEqual((result.kind, result.errors), ("answer", []), row)
            self.assertEqual([e.chunk_id for e in result.cited], ["tmvtr-1963::Rule 13::part1of1"])
            self.assertEqual(result.cited_docs, [RULE_13])

    def test_spacing_and_case_do_not_matter_but_the_words_do(self):
        row = RULE_13_ROWS[0]
        self.assertEqual(answer([RULE_13], response(("  " + row.upper().replace(" ", "  "), "E1")))[0].kind, "answer")

    def test_a_changed_number_is_still_rejected(self):
        for changed in (RULE_13_ROWS[0].replace("one month", "two months"),
                        RULE_13_ROWS[0].replace("one month", "three months"),
                        RULE_13_ROWS[1].replace("two months", "one month"),
                        RULE_13_ROWS[1].replace("two months", "six months")):
            result, _ = answer([RULE_13], response((changed, "E1")))
            self.assertEqual(result.kind, "rejected", changed)
            self.assertTrue(any("drops value" in e for e in result.errors), result.errors)

    def test_a_row_restated_without_its_number_is_still_rejected(self):
        vague = "Within the month from the beginning of the quarter, half-year or year as the case may be"
        result, _ = answer([RULE_13], response((vague, "E1")))
        self.assertEqual(result.kind, "rejected")
        self.assertTrue(any("drops value" in e for e in result.errors), result.errors)

    def test_a_row_merged_with_text_it_does_not_contain_is_still_rejected(self):
        merged = RULE_13_ROWS[0] + " and the tax is 9% of the cost of the vehicle"
        self.assertEqual(answer([RULE_13], response((merged, "E1")))[0].kind, "rejected")

    def test_only_an_identical_sentence_narrows_the_restated_set(self):
        ev = [meaning_checks.analyse("E1", s) for s in RULE_13_ROWS[:2]]
        words = meaning_checks.words(RULE_13_ROWS[0])
        self.assertEqual(meaning_checks._restated(words, ev, RULE_13_ROWS[0]), [ev[0]])
        self.assertEqual(meaning_checks._restated(words, ev, RULE_13_ROWS[1]), [ev[1]])
        for other in ("", "Within one month from the beginning", RULE_13_ROWS[0].replace("one", "two")):
            self.assertEqual(meaning_checks._restated(words, ev, other), ev, other)


class WithheldRateScheduleTests(unittest.TestCase):
    """The life-tax rates for motor cycles are in the Third Schedule, which the reviewed flags keep out of answers."""

    def flagged(self, *chunks):
        """Applies the project's reviewed flags file. Flags for chunks not passed in are reported and ignored."""
        build_telangana_index.apply_chunk_flags(list(chunks), build_telangana_index.load_chunk_flags(FLAGS))

    def test_reviewed_flags_withhold_the_third_schedule_but_not_the_paragraph_that_introduces_it(self):
        schedule = go_53_chunk(THIRD_SCHEDULE_OPENING, "Schedule", "THIRD SCHEDULE")
        paragraph = go_53_chunk(GO_53_PARAGRAPH_1, "Paragraph", "Paragraph 1")
        self.flagged(schedule, paragraph)
        self.assertIs(schedule.metadata["answer_eligible"], False)
        self.assertIn("rate-table extraction is unreliable", schedule.metadata["extraction_warning"])
        self.assertIs(paragraph.metadata["answer_eligible"], True)

    def test_the_withheld_schedule_is_never_evidence_and_no_model_is_called_for_it(self):
        schedule = go_53_chunk(THIRD_SCHEDULE_OPENING, "Schedule", "THIRD SCHEDULE")
        self.flagged(schedule)
        contract, kept = grounded_answer.build_contract("life tax for a motor cycle", [schedule])
        self.assertEqual((list(contract.evidence), kept), ([], []))
        result, generator = answer([schedule], response(("At the time of registration new vehicles 9%", "E1")))
        self.assertEqual((result.kind, generator.calls, result.model_called), ("no_support", [], False))

    def test_a_rate_from_the_withheld_schedule_cannot_be_cited_to_other_evidence(self):
        schedule = go_53_chunk(THIRD_SCHEDULE_OPENING, "Schedule", "THIRD SCHEDULE")
        paragraph = go_53_chunk(GO_53_PARAGRAPH_1, "Paragraph", "Paragraph 1")
        self.flagged(schedule, paragraph)
        for claim, evidence_id in (
                ("The life tax for a new motor cycle costing below Rs.50,000 is 9% of the cost of the vehicle.", "E1"),
                ("At the time of registration new vehicles 9%", "E1"),
                ("At the time of registration new vehicles 9%", "E2"),       # E2 is the rule, not the schedule
                ("At the time of registration new vehicles 9%", "E3")):      # no such evidence
            result, _ = answer([paragraph, schedule, RULE_13], response((claim, evidence_id)))
            self.assertEqual(result.kind, "rejected", (claim, evidence_id))
            self.assertEqual(result.cited_docs, [])

    def test_a_refusal_for_missing_rates_is_no_support(self):
        refusal = json.dumps({"answer": "", "evidence_sufficiency": "insufficient", "claims": [], "citations": [],
                              "refusal_reason": "The evidence does not state the life-tax rates.",
                              "clarification_question": None})
        paragraph = go_53_chunk(GO_53_PARAGRAPH_1, "Paragraph", "Paragraph 1")
        self.assertEqual(answer([paragraph, RULE_13], refusal)[0].kind, "no_support")


if __name__ == "__main__":
    unittest.main()
