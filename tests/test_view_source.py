"""The "View source" passages listed with each source: stored chunk text, labelled from metadata. Offline."""

import json
import unittest
from pathlib import Path
from unittest import mock

from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda

from test_server import srv

from backend import grounded_answer

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def shown(passage):
    """What the dialog shows of a passage; its provenance fields are covered in test_logical_documents.py."""
    return {k: passage[k] for k in ("provision_id", "label", "text", "cited")}


def chunk(text, **meta):
    return Document(page_content=text, metadata={"source_file": "rules.html", "sha256": "a" * 64, **meta})


class SourcePassageTests(unittest.TestCase):
    def test_label_comes_from_metadata_and_header_line_is_dropped(self):
        d = chunk("Some Rules, 1989 - Rule 9 - Badges\n9. Badges:- (1) Every driver shall wear a badge.\n(2) It is metal.",
                  provision_id="Rule 9", provision_heading="Badges", part=1, parts=1)
        self.assertEqual(shown(srv.source_passage(d)), {
            "provision_id": "Rule 9", "label": "Rule 9 - Badges",
            "text": "9. Badges:- (1) Every driver shall wear a badge.\n(2) It is metal.", "cited": False})

    def test_split_provision_names_its_part(self):
        d = chunk("Header\nbody", provision_id="Rule 9", provision_heading="", part=2, parts=3)
        self.assertEqual(srv.source_passage(d)["label"], "Rule 9 (part 2 of 3)")

    def test_chunk_without_provision_or_header_keeps_its_whole_text(self):
        self.assertEqual(shown(srv.source_passage(chunk("only one line"))),
                         {"provision_id": None, "label": "Passage", "text": "only one line", "cited": False})

    def test_header_only_chunk_has_empty_text(self):
        self.assertEqual(srv.source_passage(chunk("Header only\n", provision_id="Rule 9"))["text"], "")

    def test_html_like_and_special_characters_are_returned_unchanged(self):
        text = '<script>alert(1)</script> & "quotes" ₹ 500 § 3 — తెలంగాణ <b>bold</b>'
        self.assertEqual(srv.source_passage(chunk("Header\n" + text, provision_id="Rule 9"))["text"], text)

    def test_passage_does_not_change_the_stored_chunk(self):
        d = chunk("Header\nbody", provision_id="Rule 9")
        before = (d.page_content, dict(d.metadata))
        srv.source_passage(d)
        self.assertEqual((d.page_content, d.metadata), before)


class SourceEntriesPassageTests(unittest.TestCase):
    def test_passages_are_grouped_under_their_source_in_retrieval_order_without_repeats(self):
        a1 = chunk("H\nfirst", provision_id="Rule 1")
        b = chunk("H\nother", provision_id="Rule 7", sha256="b" * 64, source_file="act.html")
        a2 = chunk("H\nsecond", provision_id="Rule 2")
        entries = srv.source_entries([a1, b, a2, a1])
        self.assertEqual([e["file"] for e in entries], ["rules.html", "act.html"])
        self.assertEqual([p["text"] for p in entries[0]["passages"]], ["first", "second"])
        self.assertEqual([p["provision_id"] for p in entries[1]["passages"]], ["Rule 7"])

    def test_api_model_carries_passages(self):
        entry = srv.source_entries([chunk("H\nbody", provision_id="Rule 1")])[0]
        self.assertEqual(srv.Source(**entry).passages[0].text, "body")

    def test_passages_are_only_marked_cited_when_the_caller_says_so(self):
        docs = [chunk("H\none", provision_id="Rule 1"), chunk("H\ntwo", provision_id="Rule 2")]
        self.assertEqual([p["cited"] for p in srv.source_entries(docs)[0]["passages"]], [False, False])
        self.assertEqual([p["cited"] for p in srv.source_entries(docs, cited=True)[0]["passages"]], [True, True])
        self.assertFalse(srv.SourcePassage(label="x", text="y").cited)  # the API default is "not cited"


class ModePassageTests(unittest.TestCase):
    """Grounded answers list only the chunks they cite, marked cited; development output lists every retrieved
    chunk, never marked cited."""

    def docs(self):
        return [Document(page_content=f"Synthetic Rules - Rule {n} - Heading {n}\nRule {n} fixture sentence.",
                         metadata={"source_file": "rules.html", "sha256": "a" * 64, "manifest_id": "synthetic-rules",
                                   "provision_id": f"Rule {n}", "provision_heading": f"Heading {n}", "part": 1,
                                   "parts": 1, "answer_eligible": True, "title": "Synthetic Rules",
                                   "state": "Telangana"}) for n in (1, 2, 3)]

    def patch(self, **values):
        for name, value in values.items():
            p = mock.patch.object(srv, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.dict(srv.SOURCES, {"a" * 64: ("Synthetic Rules", "Rules")}, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def test_grounded_answer_lists_only_cited_passages(self):
        cite_second = json.dumps({
            "answer": "Rule 2 fixture sentence.", "evidence_sufficiency": "sufficient",
            "claims": [{"text": "Rule 2 fixture sentence.", "kind": "direct", "evidence_ids": ["E2"]}],
            "citations": ["E2"], "refusal_reason": None, "clarification_question": None})
        self.patch(grounded_gate_errors=lambda: [], retrieve=lambda q: self.docs(),
                   ANSWER_GENERATOR=grounded_answer.MockGenerator(cite_second))
        result = srv.grounded_answer_question("What does the fixture say?", [])
        self.assertEqual(result["kind"], "answer")
        [source] = result["sources"]
        self.assertEqual([shown(p) for p in source["passages"]], [{"provision_id": "Rule 2", "label": "Rule 2 - Heading 2",
                                               "text": "Rule 2 fixture sentence.", "cited": True}])

    def test_grounded_refusal_lists_no_passages(self):
        refuse = json.dumps({"answer": "", "evidence_sufficiency": "insufficient", "claims": [], "citations": [],
                             "refusal_reason": "not covered", "clarification_question": None})
        self.patch(grounded_gate_errors=lambda: [], retrieve=lambda q: self.docs(),
                   ANSWER_GENERATOR=grounded_answer.MockGenerator(refuse))
        self.assertEqual(srv.grounded_answer_question("What does the fixture say?", [])["sources"], [])

    def test_development_output_lists_retrieved_passages_as_not_cited(self):
        self.patch(ANSWER_MODE="legacy_dev", retrieve=lambda q: self.docs(), PENALTY_ANSWERS_ENABLED=False,
                   llm=RunnableLambda(lambda prompt: "Free text that mentions Rule 2 only."))
        result = srv.answer_question("What does the fixture say?", [])
        self.assertEqual(result["kind"], "development")
        passages = result["sources"][0]["passages"]
        self.assertEqual([p["provision_id"] for p in passages], ["Rule 1", "Rule 2", "Rule 3"])
        self.assertFalse(any(p["cited"] for p in passages))


class FrontendViewSourceTests(unittest.TestCase):
    def test_passage_text_is_set_with_textContent_only(self):
        self.assertIn("el('p', '', p.text)", INDEX)
        self.assertIn("el('h3', '', p.label || 'Passage')", INDEX)
        self.assertIn("if(s.passages && s.passages.length){", INDEX)
        self.assertNotRegex(INDEX, r"innerHTML\s*=\s*p\.")

    def test_only_cited_passages_are_offered_as_view_source(self):
        self.assertIn("s.passages.every((p) => p.cited) ? 'View source' : 'View retrieved text'", INDEX)
        self.assertIn("nothing confirms which of these passages it used", INDEX)
        self.assertIn("'Retrieved, not cited'", INDEX)

    def test_empty_passage_text_gets_a_placeholder(self):
        self.assertIn("'No text is stored for this passage.'", INDEX)


if __name__ == "__main__":
    unittest.main()
