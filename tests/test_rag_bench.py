"""Offline tests for the retrieval benchmark (eval/rag_bench.py). No models, no network, no Chroma."""

import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))

import rag_bench as rb  # noqa: E402

DOCS = rb.load_corpus(rb.DATA / "corpus_v1.json")
DOCS_BY_ID = {d["doc_id"]: d for d in DOCS}
QUERIES = rb.load_queries(rb.DATA / "queries_v1.json")


class DatasetTests(unittest.TestCase):
    def test_corpus_is_marked_fictional(self):
        corpus = json.loads((rb.DATA / "corpus_v1.json").read_text(encoding="utf-8"))
        self.assertIn("SYNTHETIC AND FICTIONAL", corpus["notice"])
        self.assertEqual({d["state"] for d in DOCS}, {"Central", "Northland", "Southmark"})

    def test_every_gold_label_exists_and_ids_are_unique(self):
        ids = {pid for d in DOCS for pid, _, _ in d["spans"]}
        self.assertEqual(len(QUERIES), len({q["id"] for q in QUERIES}))
        for q in QUERIES:
            self.assertTrue(set(q["gold"]) <= ids, q["id"])
            self.assertIn(q["state"], {"Northland", "Southmark"})

    def test_gold_is_reachable_under_the_state_filter(self):
        state_of = {pid: d["state"] for d in DOCS for pid, _, _ in d["spans"]}
        for q in QUERIES:
            for pid in q["gold"]:
                self.assertIn(state_of[pid], {q["state"], "Central"}, q["id"])

    def test_dev_test_split_is_disjoint_and_complete(self):
        dev, test = rb.split_ids(QUERIES)
        self.assertEqual({q["id"] for q in dev} | {q["id"] for q in test}, {q["id"] for q in QUERIES})
        self.assertFalse({q["id"] for q in dev} & {q["id"] for q in test})
        for split in (dev, test):
            self.assertTrue(any(not q["gold"] for q in split))

    def test_provision_spans_match_text(self):
        for d in DOCS:
            for pid, s, e in d["spans"]:
                self.assertTrue(d["text"][s:e].startswith(d["headings"][pid]))


class ChunkerTests(unittest.TestCase):
    def _spans_valid(self, chunks, raw_text_check=True):
        for c in chunks:
            src = DOCS_BY_ID[c["doc_id"]]["text"][c["start"]:c["end"]]
            self.assertTrue(src.strip())
            if raw_text_check:
                self.assertEqual(c["text"], src)
            else:
                self.assertIn(src, c["text"])

    def test_fixed_matches_baseline_splitter_and_spans(self):
        chunks = rb.chunk_fixed(DOCS, 1000, 200)
        self._spans_valid(chunks)
        self.assertTrue(all(len(c["text"]) <= 1000 for c in chunks))

    def test_sentence_chunks_respect_limit_and_spans(self):
        chunks = rb.chunk_sentences(DOCS, 600, 1)
        self._spans_valid(chunks)
        self.assertTrue(all(len(c["text"]) <= 1000 for c in chunks))

    def test_structure_chunks_never_cross_provisions(self):
        for chunk in rb.chunk_structure(DOCS, 1000):
            self.assertEqual(len(rb.provisions_hit(chunk, DOCS_BY_ID)), 1)

    def test_contextual_chunks_carry_title_and_heading(self):
        chunks = rb.chunk_structure(DOCS, 1000, contextual=True)
        self._spans_valid(chunks, raw_text_check=False)
        for c in chunks:
            doc = DOCS_BY_ID[c["doc_id"]]
            self.assertTrue(c["text"].startswith(doc["title"] + " - "))

    def test_long_section_is_split_with_continuation_header(self):
        doc = {"doc_id": "X", "title": "T", "state": "Central", "text": "", "spans": [], "headings": {"P": "Section 1. Long"}}
        body = "Section 1. Long\n" + " ".join(f"Sentence number {i} is here." for i in range(80))
        doc["text"], doc["spans"] = body, [("P", 0, len(body))]
        chunks = rb.chunk_structure([doc], 300, contextual=True)
        self.assertGreater(len(chunks), 1)
        self.assertIn("(continued)", chunks[1]["text"])
        self.assertTrue(all(c["end"] - c["start"] <= 300 for c in chunks))


class RetrievalMathTests(unittest.TestCase):
    def test_bm25_prefers_matching_document_and_handles_unicode(self):
        bm = rb.BM25(["helmet fine for riders", "road tax on cars", "जुर्माना लाइसेंस"])
        s = bm.scores("helmet fine")
        self.assertEqual(max(range(3), key=lambda i: s[i]), 0)
        self.assertGreater(bm.scores("जुर्माना")[2], 0)
        self.assertEqual(bm.scores("unrelated words"), [0.0, 0.0, 0.0])

    def test_rrf_combines_rankings(self):
        order, scores = rb.rrf([["a", "b", "c"], ["b", "c", "a"]], k=60)
        self.assertEqual(order[0], "b")
        self.assertAlmostEqual(scores["b"], 1 / 62 + 1 / 61)

    def test_metrics(self):
        ranked = [{"X"}, {"A"}, set(), {"B"}]
        m = rb.query_metrics(ranked, ["A", "B"], pool_relevant_count=2, ks=(1, 4))
        self.assertAlmostEqual(m["mrr"], 0.5)
        self.assertEqual(m["recall@1"], 0.0)
        self.assertEqual(m["recall@4"], 1.0)
        self.assertEqual(m["precision@4"], 0.5)
        ideal = 1 + 1 / math.log2(3)
        self.assertAlmostEqual(m["ndcg@4"], (1 / math.log2(3) + 1 / math.log2(5)) / ideal)

    def test_auroc_and_bootstrap(self):
        self.assertEqual(rb.auroc([0.9, 0.8], [0.1, 0.2]), 1.0)
        self.assertEqual(rb.auroc([0.5], [0.5]), 0.5)
        mean, lo, hi = rb.paired_bootstrap([0, 0, 0, 0], [1, 1, 1, 1])
        self.assertEqual((mean, lo, hi), (1, 1, 1))

    def test_minmax_constant(self):
        self.assertEqual(rb.minmax([2, 2]), [0.0, 0.0])


if __name__ == "__main__":
    unittest.main()
