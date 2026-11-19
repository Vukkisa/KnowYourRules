"""Answer presentation: a lead sentence, bullets for details, bold figures, and a clean Sources list that says whether
each source is Central or Telangana. Presentation only: claim words, citations and refusals are unchanged. Offline."""

import re
import unittest
from pathlib import Path

from langchain_core.documents import Document

from test_grounded_answer import HELMET, HELMET_OLD, SUPPORTED, response, run
from test_server import srv

from backend import grounded_answer as ga

INDEX = (Path(__file__).resolve().parent.parent / "frontend" / "index.html").read_text(encoding="utf-8")
PROVISO = "A Sikh wearing a turban is exempted."


class EmphasisTests(unittest.TestCase):
    def test_bolds_amounts_ages_periods_and_dates(self):
        text = ("No person under the age of eighteen years shall drive. A fee of Rs. 2000/- is payable for 20 years "
                "from 01-04-2026 or 1 April 2026, at not over twenty-five kilometre per hour.")
        out = ga.emphasise(text)
        for bold in ("**eighteen years**", "**Rs. 2000/-**", "**20 years**", "**01-04-2026**", "**1 April 2026**",
                     "**twenty-five kilometre per hour**"):
            self.assertIn(bold, out)

    def test_only_adds_markers_never_changes_a_word(self):
        text = "A person of sixteen years of age may drive a 50cc motor cycle; the fee is Rs. 500 for 3 months."
        self.assertEqual(ga.emphasise(text).replace("**", ""), text)

    def test_text_without_figures_is_untouched(self):
        self.assertEqual(ga.emphasise(SUPPORTED), SUPPORTED)


class RenderTests(unittest.TestCase):
    def test_single_claim_is_one_plain_sentence(self):
        r, _ = run("Helmet?", [HELMET], response(claims=[(SUPPORTED, "direct", ["E1"])]))
        self.assertEqual(r.text, SUPPORTED + " [1]")

    def test_first_claim_leads_and_the_rest_are_bullets(self):
        raw = response(claims=[(SUPPORTED, "direct", ["E1"]), (PROVISO, "direct", ["E1"])])
        r, _ = run("Helmet?", [HELMET], raw)
        self.assertEqual(r.kind, "answer", r.errors)
        self.assertEqual(r.text, f"{SUPPORTED} [1]\n\n- {PROVISO} [1]")

    def test_interpretation_label_and_markers_are_kept_on_bullets(self):
        raw = response(claims=[(SUPPORTED, "direct", ["E1"]), (PROVISO, "interpretation", ["E1"])])
        r, _ = run("Helmet?", [HELMET], raw)
        self.assertTrue(r.text.splitlines()[-1].endswith("(interpretation) [1]"), r.text)

    def test_conflict_still_says_it_is_not_definitive(self):
        raw = response(sufficiency="conflicting",
                       claims=[(SUPPORTED, "direct", ["E1"]),
                               ("Riders are exempt from protective headgear on rural roads.", "direct", ["E2"])])
        r, _ = run("Helmet on rural roads?", [HELMET, HELMET_OLD], raw)
        self.assertEqual(r.kind, "conflict", r.errors)
        self.assertTrue(r.text.startswith(ga.CONFLICT_PREFIX))
        self.assertEqual(len(re.findall(r"^- ", r.text, re.M)), 2)


class SourcesBlockTests(unittest.TestCase):
    def evidence(self, docs):
        contract, kept = ga.build_contract("q", docs, "r")
        return list(contract.evidence), kept

    def central(self, **extra):
        meta = dict(HELMET.metadata, jurisdiction="Central", state="Central", manifest_id="mva-1988",
                    title="Motor Vehicles Act, 1988 (Central Act) - extract of selected sections, India Code",
                    document_number="Act No. 59 of 1988", provision_id="Section 129",
                    source_url="https://indiacode.gov.in/act/1", **extra)
        return Document(page_content=HELMET.page_content, metadata=meta)

    def test_names_the_source_provision_and_jurisdiction_without_file_paths(self):
        cited, docs = self.evidence([HELMET])
        block = srv.sources_block(cited, docs)
        self.assertEqual(block, "\n\n**Sources**\n- [1] **Telangana** · Synthetic Motor Rules – Rule 437")
        self.assertNotIn(".htm", block)

    def test_title_is_short_and_readable_with_a_link_and_the_act_number(self):
        cited, docs = self.evidence([self.central()])
        self.assertEqual(srv.sources_block(cited, docs).splitlines()[-1],
                         "- [1] **Central** · Motor Vehicles Act, 1988 (Act No. 59 of 1988) – Section 129"
                         " · [View official source](https://indiacode.gov.in/act/1)")

    def test_sources_are_numbered_in_citation_order_and_keep_central_and_telangana_apart(self):
        cited, docs = self.evidence([self.central(), HELMET])
        lines = srv.sources_block(cited, docs).splitlines()
        self.assertTrue(lines[-2].startswith("- [1] **Central** · "))
        self.assertEqual(lines[-1], "- [2] **Telangana** · Synthetic Motor Rules – Rule 437")

    def test_each_source_states_its_caveat_once_in_a_few_words(self):
        cited, docs = self.evidence([self.central(), HELMET])
        warnings = [{"status": "official_text_commencement_unconfirmed", "citations": [1]},
                    {"status": "unverified_snapshot", "citations": [2]}]
        block = srv.sources_block(cited, docs, warnings)
        self.assertIn("  _Official text · latest amendments not fully confirmed_", block)
        self.assertIn("  _Unofficial web copy of unknown date · may not include later amendments_", block)
        self.assertNotIn("Source status", block)

    def test_an_identical_caveat_is_shown_once_for_all_sources(self):
        cited, docs = self.evidence([self.central(), HELMET])
        warnings = [{"status": "unverified_snapshot", "citations": [1, 2]}]
        block = srv.sources_block(cited, docs, warnings)
        self.assertEqual(block.count("Unofficial web copy"), 1)

    def test_an_unresolved_amendment_names_the_amending_order_and_says_current_law_is_unconfirmed(self):
        text = srv.short_status({"status": "known_amendments_unresolved", "related_instruments": ["G.O.Ms.No. 77"]})
        self.assertIn("G.O.Ms.No. 77", text)
        self.assertIn("not established", text)
        self.assertIn("not confirmed", srv.SHORT_STATUS["known_amendments_unresolved"])

    def test_every_status_has_a_short_caveat(self):
        for status in ("official_text_commencement_unconfirmed", "unverified_snapshot", "known_amendments_unresolved",
                       "status_not_recorded", "verified_current_not_approved"):
            self.assertTrue(srv.SHORT_STATUS[status], status)

    def test_old_separate_status_block_is_only_for_development_output(self):
        out = srv.with_status_block("answer", [{"text": "Check the current text.", "citations": [1], "numbered": True}])
        self.assertEqual(out, "answer\n\n**Source status**\n- Check the current text. [1]")


class SourceRowTests(unittest.TestCase):
    def test_row_carries_jurisdiction_and_an_http_link(self):
        self.assertEqual(srv.source_jurisdiction({"jurisdiction": "Central"}), "Central")
        self.assertEqual(srv.source_link({"source_url": "https://indiacode.gov.in/act/1"}),
                         "https://indiacode.gov.in/act/1")

    def test_unknown_jurisdiction_and_unsafe_links_are_dropped(self):
        self.assertIsNone(srv.source_jurisdiction({"jurisdiction": "Karnataka"}))
        for bad in ("javascript:alert(1)", "data:text/html,x", "ftp://x.gov", "", None, "https://a b", "https://a\"b"):
            self.assertIsNone(srv.source_link({"source_url": bad}), bad)

    def test_api_model_keeps_the_new_fields(self):
        row = srv.Source(title="t", verified=True, file="f", jurisdiction="Central", url="https://x.gov").model_dump()
        self.assertEqual((row["jurisdiction"], row["url"]), ("Central", "https://x.gov"))

    def test_frontend_links_only_http_pages_in_a_new_tab_without_opener(self):
        self.assertIn("/^https?:\\/\\//.test(s.url)", INDEX)
        self.assertIn("link.rel = 'noopener noreferrer'", INDEX)
        self.assertIn("s.jurisdiction ? s.jurisdiction + ' · ' : ''", INDEX)

    def test_answer_links_open_in_a_new_tab_and_rows_hide_file_names(self):
        render_js = (Path(__file__).resolve().parent.parent / "frontend" / "render.js").read_text(encoding="utf-8")
        self.assertIn("afterSanitizeAttributes", render_js)
        self.assertIn("'noopener noreferrer'", render_js)
        self.assertIn("text.includes('**Sources**')", INDEX)  # rows are only the way into the cited text
        self.assertNotIn("'Unverified · ' + (n > 1 ? n + ' files' : s.file)", INDEX)  # no raw file name before the button


class LimitationTests(unittest.TestCase):
    def test_no_support_says_what_it_cannot_confirm_and_never_guesses(self):
        self.assertIn("can't confirm", srv.NO_SUPPORT_MESSAGE)
        self.assertIn("won't guess", srv.NO_SUPPORT_MESSAGE)
        self.assertNotIn("₹", srv.NO_SUPPORT_MESSAGE)

    def test_penalty_lock_message_is_unchanged_in_substance(self):
        for phrase in ("not available yet", "legal counsel", "fine amounts", "compounding fees"):
            self.assertIn(phrase, srv.PENALTY_LOCKED_MESSAGE)


if __name__ == "__main__":
    unittest.main()
