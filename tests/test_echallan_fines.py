"""Telangana Police e-Challan fine tables as a secondary source of WEBSITE-DISPLAYED amounts (backend/echallan_fines.py).

Offline. No model, no provider, no network. These tests pin the contract: the 162 scraped rows are preserved verbatim, the answer
says the amount is the one the website displays, cites the exact page, shows both tables when they disagree, never invents or
corrects a figure, never claims legal verification, and leaves the grounded-answer penalty lock as it was (the feature is OFF
unless TG_ECHALLAN_FINES is set)."""

import copy
import hashlib
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend import echallan_fines as ef  # noqa: E402

RESEARCH = ROOT / "research" / "echallan-fines-unverified.json"
WHEEL_URL = "https://echallan.tspolice.gov.in/htp/mv-act-rules.html"
PLAIN_URL = "https://echallan.tspolice.gov.in/htp/mvact.html"


def on():
    return mock.patch.dict(os.environ, {ef.ENV_SWITCH: "1"})


def answer_text(question, **kw):
    m = ef.find(question)
    assert m.kind == "answer", (question, m.kind)
    return m, ef.render(m)


class DataIsPreserved(unittest.TestCase):
    def test_all_162_entries_are_present(self):
        s = ef.load()
        self.assertTrue(s.ready, s.error)
        self.assertEqual(len(s.entries), 162)
        by_table = {}
        for e in s.entries:
            by_table[e["table"]] = by_table.get(e["table"], 0) + 1
        self.assertEqual(by_table, {"mv-act-rules": 112, "mvact": 50})

    @unittest.skipUnless(RESEARCH.exists(), "research file not present")
    def test_every_row_equals_the_scraped_file_exactly(self):
        src = json.loads(RESEARCH.read_text())["rows"]
        s = ef.load()
        for key in ("mv-act-rules", "mvact"):
            mine = [[e["offence"], e["section"], e["amount_displayed"]] for e in s.entries if e["table"] == key]
            self.assertEqual(mine, src[key], key)

    @unittest.skipUnless(RESEARCH.exists(), "research file not present")
    def test_provenance_records_the_source_hashes_and_urls(self):
        p = ef.load().provenance
        self.assertEqual(p["scraped_file_sha256"], hashlib.sha256(RESEARCH.read_bytes()).hexdigest())
        self.assertEqual(p["tables"]["mv-act-rules"]["url"], WHEEL_URL)
        self.assertEqual(p["tables"]["mvact"]["url"], PLAIN_URL)
        for key in ("audit_json_sha256", "audit_md_sha256", "rows_sha256"):
            self.assertRegex(p[key], r"^[0-9a-f]{64}$")
        self.assertEqual(p["entry_count"], 162)

    def test_an_edited_amount_switches_the_feature_off(self):
        data = json.loads(ef.DATA_PATH.read_text())
        data["entries"][0]["amount_displayed"] = data["entries"][0]["amount_displayed"].replace("500", "5000")
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "d.json"
            p.write_text(json.dumps(data))
            s = ef.load(p)
        self.assertFalse(s.ready)
        self.assertIn("hash", s.error)

    def test_a_missing_data_file_switches_the_feature_off(self):
        self.assertFalse(ef.load(Path("/nonexistent/echallan.json")).ready)

    def test_the_audit_files_were_not_altered_by_the_build(self):
        p = ef.load().provenance
        for name, key in (("echallan-fines-audit.json", "audit_json_sha256"), ("echallan-fines-audit.md", "audit_md_sha256")):
            f = ROOT / "research" / name
            if f.exists():
                self.assertEqual(hashlib.sha256(f.read_bytes()).hexdigest(), p[key], name)


class OffByDefault(unittest.TestCase):
    def test_the_switch_is_off_unless_set(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(ef.ENV_SWITCH, None)
            self.assertFalse(ef.enabled())
            self.assertEqual(ef.find("What is the fine for not wearing a helmet?").kind, "none")

    def test_only_explicit_truthy_values_switch_it_on(self):
        for v, expect in (("1", True), ("true", True), ("ON", True), ("0", False), ("", False), ("maybe", False)):
            with mock.patch.dict(os.environ, {ef.ENV_SWITCH: v}):
                self.assertEqual(ef.enabled(), expect, v)


@mock.patch.dict(os.environ, {ef.ENV_SWITCH: "1"})
class RequiredQuestions(unittest.TestCase):
    def test_helmet(self):
        m, t = answer_text("What is the fine for not wearing a helmet?")
        self.assertIn("₹100/-", t)
        self.assertIn("Rs. 200/-", t)
        self.assertIn(WHEEL_URL, t)
        self.assertIn(PLAIN_URL, t)
        self.assertIn("The two website tables disagree", t)

    def test_driving_without_a_licence(self):
        m, t = answer_text("What is the challan amount for driving without a licence?")
        self.assertIn("₹500/-", t)
        self.assertIn("Rs. 500/-", t)
        self.assertNotIn("disagree", t)  # both tables print 500: nothing to flag
        self.assertIn("W/o Driving License", "".join(e["offence"] for e in m.entries))

    def test_parking_in_a_no_parking_area_shows_both_tables_and_the_disagreement(self):
        m, t = answer_text("What is the fine for parking in a no-parking area?")
        self.assertIn("₹100/-", t)
        self.assertIn("Rs. 1000/-", t)
        self.assertIn("The two website tables disagree", t)
        self.assertIn(WHEEL_URL, t)
        self.assertIn(PLAIN_URL, t)


@mock.patch.dict(os.environ, {ef.ENV_SWITCH: "1"})
class SectionQuestions(unittest.TestCase):
    def test_section_122_lists_every_entry_and_flags_the_disagreement(self):
        m, t = answer_text("What is the fine under section 122?")
        ids = {e["id"] for e in m.entries}
        expect = {e["id"] for e in ef.store().entries if "122" in e["act_sections"]}
        self.assertEqual(ids, expect)
        self.assertGreaterEqual(len(expect), 14)
        self.assertIn("disagree", t)
        self.assertIn("Rs. 1000/-", t)  # the plain table's no-parking-board row

    def test_section_129(self):
        m, t = answer_text("fine under section 129")
        self.assertIn("₹100/-", t)
        self.assertIn("Rs. 200/-", t)
        self.assertIn("disagree", t)

    def test_section_132(self):
        m, t = answer_text("Section 132 challan amount")
        self.assertIn("₹100/-", t)
        self.assertIn("Rs. 200/-", t)
        self.assertIn("disagree", t)

    def test_section_181_is_shown_as_displayed_and_not_called_current(self):
        m, t = answer_text("What is the fine under section 181?")
        self.assertIn("₹500/-", t)
        self.assertIn("Rs. 500/-", t)
        self.assertNotIn("2019", t)         # no outside amount is added
        self.assertNotIn("5000", t.replace("1000", ""))
        self.assertIn("not independently verified", t)

    def test_a_section_the_tables_do_not_cite_is_unavailable_not_guessed(self):
        m = ef.find("What is the fine under section 999?")
        self.assertEqual(m.kind, "clarify")
        self.assertIn("no website amount", ef.render_clarification(m))

    def test_section_search_does_not_match_rule_numbers(self):
        # "High Beam Light" cites CMVR 106 and "Dazzling Light" TSMV 430: those are rules, not Act sections
        self.assertEqual(ef.find("fine under section 106").kind, "clarify")
        self.assertEqual(ef.find("fine under section 430").kind, "clarify")


@mock.patch.dict(os.environ, {ef.ENV_SWITCH: "1"})
class CommonOffences(unittest.TestCase):
    CASES = [("fine for signal jumping", "₹1,000/-"), ("What is the fine for jumping a red light?", "₹1,000/-"),
             ("fine for using mobile phone while driving", "Rs. 1000/-"), ("fine for not wearing seat belt", "₹100/-"),
             ("fine for triple riding on a bike", "₹1,200/-"), ("fine for driving without insurance", "Rs. 1000/-"),
             ("fine for no PUC certificate", "Rs. 1000/-"), ("fine for wrong side driving", "Rs. 1100/-"),
             ("fine for no number plate", "₹200/-"), ("fine for drunk driving", "Court."),
             ("fine for over speeding", "Rs. 1400/-"), ("fine for violating one way", "Rs. 200/-")]

    def test_each_returns_the_displayed_amount_and_both_urls_when_both_tables_match(self):
        for q, shown in self.CASES:
            with self.subTest(q):
                m, t = answer_text(q)
                self.assertIn(shown, t)
                self.assertIn(ef.AMOUNT_LABEL, t)
                self.assertIn(ef.DISCLAIMER, t)
                self.assertIn(WHEEL_URL if any(e["table"] == "mv-act-rules" for e in m.entries) else PLAIN_URL, t)

    def test_a_named_vehicle_picks_that_column_without_hiding_a_zero(self):
        m, t = answer_text("fine for not wearing a helmet on a car")
        self.assertIn("4 Wheeler: ₹0/-", t)
        self.assertIn("does not say whether it means no fine or not applicable", t)
        m2, t2 = answer_text("fine for no helmet on a bike")
        self.assertIn("2 Wheeler: **₹100/-**", t2)


@mock.patch.dict(os.environ, {ef.ENV_SWITCH: "1"})
class NothingIsInventedOrOverclaimed(unittest.TestCase):
    QUESTIONS = ["What is the fine for not wearing a helmet?", "driving without a licence fine", "fine for parking in a no-parking area",
                 "fine under section 122", "fine under section 129", "fine under section 132", "fine under section 181",
                 "fine for signal jumping", "fine for triple riding", "fine for drunk driving", "fine for over speeding",
                 "fine for no seat belt", "fine for wrong side driving", "fine for no insurance"]

    def test_every_rupee_figure_in_an_answer_is_in_a_matched_source_row(self):
        for q in self.QUESTIONS:
            with self.subTest(q):
                m, t = answer_text(q)
                body = t.split("**The two website tables disagree.**")[0]
                shown = {int(x.replace(",", "")) for x in re.findall(r"(?:₹|Rs\.?)\s*([\d,]+)", t)}
                source = set()
                for e in m.entries:
                    source |= {int(x.replace(",", "")) for x in re.findall(r"(?:₹|Rs\.?)\s*([\d,]+)", e["amount_displayed"])}
                self.assertTrue(shown <= source, (shown - source, q))

    def test_no_answer_claims_verification_or_a_statutory_or_compounding_amount(self):
        for q in self.QUESTIONS:
            with self.subTest(q):
                _, t = answer_text(q)
                low = t.lower()
                self.assertIn("not independently verified", low)
                self.assertIn("are not telangana compounding amounts", low)
                self.assertNotIn("legally verified", low)
                self.assertNotIn("approved by", low)
                self.assertNotIn("the statutory fine is", low)
                self.assertNotIn("the compounding amount is", low)
                self.assertTrue(t.rstrip().endswith("_" + ef.DISCLAIMER + "_"))

    def test_both_tables_are_never_merged_into_one_figure(self):
        _, t = answer_text("What is the fine for not wearing a helmet?")
        self.assertIn("₹100/-", t)
        self.assertIn("Rs. 200/-", t)
        self.assertNotIn("₹150", t)
        self.assertNotRegex(t, r"between\s+(?:₹|Rs)")


@mock.patch.dict(os.environ, {ef.ENV_SWITCH: "1"})
class UnmatchedAndOutOfScope(unittest.TestCase):
    def test_an_offence_not_in_the_tables_is_not_answered(self):
        for q in ["What is the fine for flying a kite?", "what is the fine for blocking the road", "fine?", "How much is the fine?"]:
            self.assertEqual(ef.find(q).kind, "none", q)

    def test_a_weak_match_asks_which_offence(self):
        m = ef.find("fine for using horn")
        self.assertEqual(m.kind, "clarify")
        self.assertIn("Did you mean", ef.render_clarification(m))

    def test_questions_the_tables_cannot_answer_are_left_to_the_locks(self):
        for q in ["What is the imprisonment for drunk driving fine?", "how many penalty points for no helmet",
                  "will my licence be suspended after the helmet fine", "compounding fee for helmet",
                  "what is the minimum age for a licence", "How do I add a class to my licence?"]:
            self.assertEqual(ef.find(q).kind, "none", q)

    def test_the_source_rows_name_the_exact_pages_and_are_unverified(self):
        m = ef.find("What is the fine for not wearing a helmet?")
        rows = ef.sources(m)
        self.assertEqual({r["file"] for r in rows}, {WHEEL_URL, PLAIN_URL})
        for r in rows:
            self.assertFalse(r["verified"])
            self.assertIn("not independently verified", r["instrument"])
            self.assertTrue(all(p["cited"] and p["location"] == r["file"] for p in r["passages"]))
            self.assertRegex(r["sha256"], r"^[0-9a-f]{64}$")


@mock.patch.dict(os.environ, {ef.ENV_SWITCH: "1"})
class AnswersAreEasyToRead(unittest.TestCase):
    """The first lines must say the answer; the long detail comes after it."""

    def head(self, q):
        _, t = answer_text(q)
        return t.split("\n\n")[0]  # the amount is the first thing shown

    def test_the_amount_comes_before_the_website_label_and_the_table_links_are_clickable(self):
        _, t = answer_text("What is the fine for not wearing a helmet?")
        self.assertTrue(t.startswith("**Result: "), t[:60])
        self.assertLess(t.index("₹100/-"), t.index(ef.AMOUNT_LABEL))
        self.assertIn("](https://echallan.tspolice.gov.in/htp/mv-act-rules.html)", t)
        self.assertIn("](https://echallan.tspolice.gov.in/htp/mvact.html)", t)

    def test_the_headline_gives_both_figures_with_the_vehicle_class(self):
        h = self.head("What is the fine for not wearing a helmet?")
        self.assertIn("wheel-wise table: 2 Wheeler ₹100/-", h)
        self.assertIn("plain table: Rs. 200/-", h)

    def test_the_disagreement_sentence_follows_the_headline(self):
        _, t = answer_text("What is the fine for no parking?")
        self.assertLess(t.index("Rs. 1000/-"), t.index("The two website tables disagree"))
        self.assertLess(t.index("The two website tables disagree"), t.index("https://echallan"))

    def test_equal_figures_are_reported_as_equal(self):
        _, t = answer_text("What is the fine under section 181?")
        self.assertIn("Both website tables show the same figure.", t)
        self.assertNotIn("disagree", t)

    def test_a_zero_and_a_court_entry_are_not_called_the_same_figure(self):
        _, t = answer_text("fine for drunk driving")
        self.assertNotIn("show the same figure", t)
        self.assertIn("Neither table prints a rupee amount", t)

    def test_a_named_car_does_not_get_a_two_or_three_wheeler_row(self):
        m, t = answer_text("how much for wrong side driving in a car")
        self.assertNotIn("2 or 3 Wheeler", t)
        self.assertIn("₹1,700/-", t)

    def test_riding_in_the_question_does_not_hide_the_plain_table_entry(self):
        m = ef.find("how much fine if I ride without helmet")
        self.assertEqual({e["table"] for e in m.entries}, {"mv-act-rules", "mvact"})

    def test_a_phone_question_matches_the_wheel_wise_entry_too(self):
        m = ef.find("fine for using phone while riding")
        self.assertEqual({e["id"] for e in m.entries}, {"W018", "P032"})

    def test_a_general_word_asks_which_offence_instead_of_picking_one(self):
        m = ef.find("fine for parking")
        self.assertEqual(m.kind, "clarify")
        self.assertIn("Did you mean", ef.render_clarification(m))

    def test_every_entry_can_be_found_by_its_own_name_except_the_generic_ones(self):
        missed = []
        for e in ef.store().entries:
            off = re.sub(r"\(.*?\)", "", e["offence"]).strip(" .")
            m = ef.find(f"What is the fine for {off}?")
            if not (m.kind == "answer" and e["id"] in {x["id"] for x in m.entries}):
                missed.append(e["id"])
        # the misses are rows whose name is a bare category or contains a locked word (disqualification, punishment)
        self.assertLessEqual(len(missed), 8, missed)


# ---- through the real /chat route (offline fakes) -------------------------------------------------------------------------
class MatchingRegressions(unittest.TestCase):
    """Three questions that used to miss or mix entries: speeding, triple riding, and a red light without the word "fine"."""

    def setUp(self):
        p = on()
        p.start()
        self.addCleanup(p.stop)

    def ids(self, q):
        m = ef.find(q)
        self.assertEqual(m.kind, "answer", q)
        return {e["id"] for e in m.entries}, m

    def test_speeding_returns_only_speeding_entries_never_racing(self):
        for q in ("Fine for speeding", "What is the fine for over speeding?", "overspeeding challan"):
            ids, m = self.ids(q)
            offences = " ".join(e["offence"].lower() for e in m.entries)
            self.assertIn("W064", ids, q)
            self.assertIn("P036", ids, q)
            self.assertNotIn("W066", ids, q)
            self.assertNotIn("racing", offences, q)
            _, text = answer_text(q)
            self.assertNotIn("Racing", text, q)
            self.assertNotIn("₹500/-", text, q)

    def test_the_speeding_answer_keeps_exact_amounts_urls_and_the_disagreement(self):
        _, text = answer_text("Fine for speeding")
        self.assertIn("wheel-wise table: ₹1,000/-; plain table: Rs. 1400/-", text)
        self.assertIn("The two website tables disagree", text)
        self.assertIn(WHEEL_URL, text)
        self.assertIn(PLAIN_URL, text)
        self.assertIn(ef.AMOUNT_LABEL, text)
        self.assertIn(ef.NOT_VERIFIED, text)
        self.assertIn(ef.DISCLAIMER, text)

    def test_racing_is_still_found_when_the_question_asks_for_it(self):
        for q in ("fine for racing", "fine for racing and trail of speed"):
            ids, _ = self.ids(q)
            self.assertIn("W066", ids, q)
        ids, _ = self.ids("fine for racing and speeding")
        self.assertIn("W066", ids)

    def test_three_people_on_a_bike_is_triple_riding(self):
        for q in ("Carrying 3 people on a bike", "What is the fine for carrying 3 people on a bike?", "fine for 3 persons on a motorcycle",
                  "three people on a scooter challan", "fine for 3 passengers on a bike"):
            ids, m = self.ids(q)
            self.assertEqual(ids, {"W092", "P024"}, q)
            self.assertEqual(m.vehicle, "2 Wheeler", q)

    def test_the_triple_riding_answer_keeps_amounts_class_label_and_sources(self):
        _, text = answer_text("Carrying 3 people on a bike")
        self.assertIn("wheel-wise table: ₹1,200/-; plain table: Rs. 1200/-", text)
        self.assertIn("2 Wheeler: **₹1,200/-**", text)
        self.assertIn("Both website tables show the same figure", text)
        self.assertIn(WHEEL_URL, text)
        self.assertIn(PLAIN_URL, text)
        self.assertIn(ef.DISCLAIMER, text)
        self.assertNotIn("4 Wheeler: ₹0", text)

    def test_three_people_in_a_car_is_not_called_triple_riding(self):
        self.assertEqual(ef.find("fine for 3 people in a car").kind, "none")

    def test_a_red_light_question_without_fine_or_amount_finds_signal_jumping(self):
        for q in ("What if I jump a red light?", "what happens if I jump the signal", "what if i jumped the red light", "I got caught jumping a red light"):
            ids, _ = self.ids(q)
            self.assertEqual(ids, {"W058", "P029"}, q)

    def test_the_red_light_answer_keeps_amounts_sources_and_disclaimer(self):
        _, text = answer_text("What if I jump a red light?")
        self.assertIn("wheel-wise table: ₹1,000/-; plain table: Rs. 1000/-", text)
        self.assertIn("Both website tables show the same figure", text)
        self.assertIn(WHEEL_URL, text)
        self.assertIn(PLAIN_URL, text)
        self.assertIn(ef.AMOUNT_LABEL, text)
        self.assertIn(ef.NOT_VERIFIED, text)
        self.assertIn(ef.DISCLAIMER, text)

    def test_the_wider_gate_does_not_catch_rule_or_permission_questions(self):
        for q in ("Can I carry 3 people on a bike?", "Is it legal to jump a red light?", "What is the rule for red light?",
                  "How do I renew my driving licence?", "Is helmet mandatory?", "helmet", "What is the speed limit?",
                  "Who can ride a bike with three people?"):
            self.assertEqual(ef.find(q).kind, "none", q)

    def test_the_wider_gate_leaves_locked_topics_locked(self):
        for q in ("What if I jump a red light, will I go to jail?", "What happens if I jump a red light, how many points?",
                  "what if i jump a red light and get my licence suspended", "red light compounding fee",
                  "carrying 3 people on a bike imprisonment"):
            self.assertEqual(ef.find(q).kind, "none", q)

    def test_a_bare_phrase_is_never_turned_into_a_clarification(self):
        self.assertEqual(ef.find("parking at the mall").kind, "none")


import test_server as ts  # noqa: E402


class ChatRoute(ts.Base):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, {ef.ENV_SWITCH: "1"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_default_leaves_fine_questions_locked(self):
        with mock.patch.dict(os.environ, {ef.ENV_SWITCH: ""}):
            r = self.post("What is the fine for not wearing a helmet?").json()
        self.assertEqual(r["kind"], "restricted")
        self.assertEqual(r["response"], ts.srv.PENALTY_LOCKED_MESSAGE)

    def test_a_fine_question_returns_the_website_amount_without_a_model_or_retrieval(self):
        r = self.post("What is the fine for not wearing a helmet?").json()
        self.assertEqual(r["kind"], "website_amount")
        self.assertIn("Amount displayed on the Telangana Police e-Challan website.", r["response"])
        self.assertIn(ef.DISCLAIMER, r["response"])
        self.assertEqual({s["file"] for s in r["sources"]}, {WHEEL_URL, PLAIN_URL})
        self.assertTrue(all(s["verified"] is False for s in r["sources"]))
        self.assertFalse(r["kb_approved"])
        self.assertEqual(self.log, {})
        self.assertEqual(ts.SEARCH_LOG, [])

    def test_it_works_without_a_loaded_index(self):
        with mock.patch.dict(ts.srv.INDEX_INFO, {"index": "missing"}):
            self.assertEqual(self.post("fine under section 181").json()["kind"], "website_amount")

    def test_the_four_required_sections_through_chat(self):
        for q in ("fine under section 122", "fine under section 129", "fine under section 132", "fine under section 181"):
            r = self.post(q).json()
            self.assertEqual(r["kind"], "website_amount", q)
            self.assertIn(WHEEL_URL, r["response"])

    def test_the_disagreement_is_stated_in_the_reply(self):
        r = self.post("What is the fine for parking in a no-parking area?").json()
        self.assertIn("The two website tables disagree", r["response"])

    def test_compounding_imprisonment_and_points_stay_locked(self):
        for q in ("compounding fee for helmet", "what is the imprisonment for drunk driving", "How many penalty points for no helmet?"):
            self.assertEqual(self.post(q).json()["kind"], "restricted", q)

    def test_an_unmatched_fine_question_keeps_the_existing_lock(self):
        r = self.post("What is the fine for flying a kite?").json()
        self.assertEqual(r["kind"], "restricted")
        self.assertEqual(r["response"], ts.srv.PENALTY_LOCKED_MESSAGE)

    def test_a_weak_match_asks_which_offence(self):
        r = self.post("fine for using horn").json()
        self.assertEqual(r["kind"], "clarification")
        self.assertIn("Did you mean", r["response"])

    def test_an_offence_date_is_not_pretended_to_apply(self):
        r = self.client.post("/chat", json={"message": "fine for not wearing a helmet", "session_id": "d", "offence_date": "2026-09-01"}).json()
        self.assertEqual(r["kind"], "website_amount")
        self.assertIn("do not say which date their figures apply to", r["response"])

    def test_status_reports_the_secondary_source_as_unverified(self):
        s = self.client.get("/status").json()["echallan_fines"]
        self.assertEqual(s["entries"], 162)
        self.assertIn("not independently verified", s["label"])
        self.assertRegex(s["rows_sha256"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
