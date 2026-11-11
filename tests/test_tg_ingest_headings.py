"""Regression tests for rule-heading recognition in backend/tg_ingest.py (Stage 8).

Synthetic fixtures only. The heading SHAPES are copied from the Telangana sources; the body text is
placeholder. Nothing reads the real sources, the corpus or the index.

`HeadingWithoutFullStop` covers the Stage 8 defect, fixed in Stage 9: a rule heading written without the full
stop after its number (TMVR 186, TMVR 295-A, TMVTR 12-B, TMVTR 13) used to be folded into the previous rule.
The fallback accepts such a heading only when the line has the ":-" terminator AND the number is the next in
sequence. `CurrentBehaviourToKeep` pins behaviour that existed before the fix; `FallbackLimits` pins what the
fallback must NOT accept.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import tg_ingest as ti  # noqa: E402

BODY = "Synthetic placeholder text for testing only."


def blocks(*lines):
    return [ti.Block("text", line, f"html/r.htm#{i}") for i, line in enumerate(lines)]


def rules(*lines):
    return {p.identifier: p for p in ti.segment(blocks(*lines), "Rules")}


# Neighbourhood of TMVR Rule 186 (chapter 5): 185 and 187 have full stops, 186 does not.
TMVR_185_187 = (
    "185. Conditions to be attached to all permits :- (1) " + BODY,
    "(2) " + BODY,
    "186 (1) Conditions of permit in respect of a luxury tourist cab :- The following conditions " + BODY,
    "(i) " + BODY,
    "(2) " + BODY,
    "187. Conditions of permit – Maintenance of continuous service :- (1) " + BODY,
)


class CurrentBehaviourToKeep(unittest.TestCase):
    """Must hold before and after any heading fix."""

    def test_full_stop_headings_around_186_are_recognised(self):
        r = rules(*TMVR_185_187)
        self.assertEqual(r["Rule 185"].heading, "Conditions to be attached to all permits")
        self.assertEqual(r["Rule 187"].heading, "Conditions of permit – Maintenance of continuous service")
        self.assertTrue(r["Rule 187"].blocks[0].text.startswith("187."))

    def test_sub_rules_and_clauses_never_open_a_provision(self):
        r = rules("10. Placeholder heading :- " + BODY, "(11) " + BODY, "(xii) " + BODY, "(12A) " + BODY)
        self.assertEqual(list(r), ["Rule 10"])
        self.assertEqual(len(r["Rule 10"].blocks), 4)

    def test_lower_numbered_list_item_stays_inside_the_rule(self):
        r = rules("40. Placeholder heading :- " + BODY, "1. First item " + BODY, "2. Second item " + BODY)
        self.assertEqual(list(r), ["Rule 40"])

    def test_measurement_lines_are_not_headings(self):
        # TMVR Rule 334 lists wheelbase bands as "408 Cms. to 432 Cms": higher numbers, no heading terminator.
        r = rules("334. Placeholder heading :- " + BODY, "408 Cms. to 432 Cms", "433 Cms. to 496 Cms",
                  "535 Cms. and above", "335. Next heading :- " + BODY)
        self.assertEqual(list(r), ["Rule 334", "Rule 335"])
        self.assertEqual(len(r["Rule 334"].blocks), 4)

    def test_hyphenated_insertion_with_full_stop(self):
        r = rules("12. Placeholder :- " + BODY, "12-A. Inserted heading :- " + BODY, "14. Later :- " + BODY)
        self.assertEqual(list(r), ["Rule 12", "Rule 12A", "Rule 14"])

    def test_go_numbered_lines_are_paragraphs_not_rules(self):
        provs = ti.segment(blocks("2. Whereas " + BODY, "186 (1) Placeholder :- " + BODY), "G.O.")
        self.assertNotIn("Rule 186", [p.identifier for p in provs])

    def test_html_anchor_of_unrecognised_heading_is_still_kept(self):
        # The source puts <a name="58"> at the 186 heading; the block keeps that location either way.
        html = (b'<html><body><p><a name="57"></a>185. Heading :- ' + BODY.encode() + b'</p>'
                b'<p><a name="58"></a>186 (1) Heading two :- ' + BODY.encode() + b'</p></body></html>')
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "r.htm").write_bytes(html)
            locs = [b.location for b in ti.load_html(Path(d) / "r.htm", "r.htm")]
        self.assertEqual(locs, ["r.htm#57", "r.htm#58"])


class HeadingWithoutFullStop(unittest.TestCase):
    """Rule headings without a full stop after the number are their own provisions."""

    def test_rule_186_is_its_own_provision(self):
        r = rules(*TMVR_185_187)
        self.assertIn("Rule 186", r)
        self.assertEqual(r["Rule 186"].heading, "Conditions of permit in respect of a luxury tourist cab")
        self.assertFalse(any("186 (1)" in b.text for b in r["Rule 185"].blocks))
        self.assertEqual(len(r["Rule 186"].blocks), 3)

    def test_suffix_with_spaced_full_stop(self):
        # TMVR "295-A . Painting of goods carriages carrying dangerous or hazardous goods:-"
        r = rules("295. Placeholder :- " + BODY, "295-A . Placeholder two:- " + BODY, "296. Next :- " + BODY)
        self.assertEqual(list(r), ["Rule 295", "Rule 295A", "Rule 296"])

    def test_suffix_without_title_and_number_without_full_stop(self):
        # TMVTR "12-B : - Whereby a notification ..." and "13 Rates of penalty : - If the tax ..."
        r = rules("12-A. Placeholder :- " + BODY, "12-B : - " + BODY, "13 Placeholder three : - " + BODY,
                  "13-A. Placeholder four : - " + BODY)
        self.assertEqual(list(r), ["Rule 12A", "Rule 12B", "Rule 13", "Rule 13A"])
        self.assertEqual(r["Rule 12B"].heading, "")  # the source gives 12-B no title; none is invented
        self.assertEqual(r["Rule 13"].heading, "Placeholder three")


class FallbackLimits(unittest.TestCase):
    """Lines the no-full-stop fallback must leave inside the current rule."""

    def test_not_next_in_sequence(self):
        # A skipped number, and a skipped suffix letter written in the spaced form only the fallback reads.
        # ("185-B Title" without spaces is matched by the pre-existing PROVISION_PATTERNS[2], unchanged here.)
        r = rules("185. Placeholder :- " + BODY, "188 (1) Placeholder two :- " + BODY, "185 - B . Item :- " + BODY)
        self.assertEqual(list(r), ["Rule 185"])
        self.assertEqual(len(r["Rule 185"].blocks), 3)

    def test_no_heading_terminator(self):
        r = rules("185. Placeholder :- " + BODY, "186 Placeholder two without terminator " + BODY)
        self.assertEqual(list(r), ["Rule 185"])

    def test_number_followed_by_ordinary_text(self):
        # e.g. a wrapped line "186 of these rules shall apply :- ..." is a reference, not a heading
        r = rules("185. Placeholder :- " + BODY, "186 of these rules shall apply :- " + BODY)
        self.assertEqual(list(r), ["Rule 185"])

    def test_first_rule_of_a_document_still_needs_a_full_stop(self):
        r = rules("Preliminary " + BODY, "1 Placeholder :- " + BODY)
        self.assertEqual(list(r), ["Preamble"])

    def test_not_applied_inside_schedules_or_go(self):
        r = rules("185. Placeholder :- " + BODY, "FIRST SCHEDULE", "186 (1) Placeholder two :- " + BODY)
        self.assertNotIn("Rule 186", r)
        provs = ti.segment(blocks("1. Placeholder :- " + BODY, "2 Placeholder two :- " + BODY), "G.O.")
        self.assertEqual([p.identifier for p in provs], ["Paragraph 1"])


if __name__ == "__main__":
    unittest.main()
