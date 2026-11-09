import unittest

from langchain_core.documents import Document

from backend import hybrid_retrieval as hr

# Fixture chunks modelled on the preview index's metadata. Text is synthetic, not legal text.
CHUNKS = [
    ("tmvr-1989-chap-2", "Rule 10", "Synthetic Motor Rules - Rule 10 - Appeal against refusal\n10. Appeal filler.", True),
    ("tmvtr-1963", "Rule 10", "Synthetic Taxation Rules - Rule 10 - Seizure of vehicles\n10. Seizure filler.", True),
    ("tmvtr-1963", "Rule 13A", "Synthetic Taxation Rules - Rule 13A - Manner of payment\n13-A. Payment filler.", True),
    ("tmvr-1989-chap-8", "Rule 437", "Synthetic Motor Rules - Rule 437 - Crash helmets\n437. Helmet filler.", True),
    ("go-ms-16-2026-trb", "Preamble", "Synthetic schedule amendment - Preamble\nG.O.Ms.No. 16 Dated: 20-03-2026", True),
    ("go-ms-16-2026-trb", "SEVENTH SCHEDULE", "Synthetic schedule amendment - SEVENTH SCHEDULE\ncolumn deleted", False),
    ("go-ms-10-2026-trb", "Order", "Synthetic commencement - Order\nG.O.Ms.No. 10 Dated: 25-02-2026", True),
    ("go-ms-16-2025-trb", "Preamble", "Synthetic older order - Preamble\nG.O.Ms.No. 16 Dated: 01-01-2025", True),
    ("go-ms-32-2026-trb", "Paragraph 4", "Synthetic authority - Paragraph 4\n4. Members filler.", True),
    ("go-ms-32-2026-trb", "Paragraph 5", "Synthetic authority - Paragraph 5\n5. Powers filler.", True),
]


def make_index():
    docs = [c[2] for c in CHUNKS]
    metas = [{"manifest_id": m, "provision_id": p, "part": 1, "location": f"{m}#{i}", "sha256": m,
              "answer_eligible": e, "title": "Synthetic", "provision_heading": "", "document_number": ""}
             for i, (m, p, _t, e) in enumerate(CHUNKS)]
    return hr.LexicalIndex(docs, metas)


def ids(docs):
    return [(d.metadata["manifest_id"], d.metadata["provision_id"]) for d in docs]


class TokenizerTests(unittest.TestCase):
    def test_inserted_rule_variants_fold_to_one_token(self):
        for text in ("Rule 13A", "Rule 13-A", "rule 13 - a", "What does Rule 13 A?"):
            self.assertIn("13a", hr.tokenize(text), text)
        self.assertNotIn("5a", hr.tokenize("Rule 5 A person shall"))  # "A" starts a sentence here

    def test_go_reference_variants(self):
        for text in ("G.O.Ms.No. 16/2026", "G.O. 16 of 2026", "GO Ms No 16 dated 20-03-2026", "GO 16/2026",
                     "G.O.Ms.No. 16 Dated: 20-03-2026"):
            toks = hr.tokenize(text)
            self.assertIn("go16", toks, text)
            self.assertIn("go16y2026", toks, text)
        self.assertNotIn("go16", hr.tokenize("we go 16 km"))  # the verb "go" is not a G.O.


class LookupTests(unittest.TestCase):
    def setUp(self):
        self.ix = make_index()

    def test_rule_number_only_lookup(self):
        self.assertEqual(ids(self.ix.lookup("What does Rule 437 say?", ["Rule 437"], None).documents),
                         [("tmvr-1989-chap-8", "Rule 437")])

    def test_rule_in_both_instruments_is_ambiguous_without_scope(self):
        out = self.ix.lookup("What does Rule 10 say?", ["Rule 10"], None)
        self.assertEqual(out.documents, [])
        self.assertEqual(out.ambiguous[0][0], "Rule 10")
        self.assertEqual(len(out.ambiguous[0][1]), 2)

    def test_instrument_scope_is_preserved(self):
        self.assertEqual(ids(self.ix.lookup("TMVR Rule 10", ["Rule 10"], "tmvr-1989").documents),
                         [("tmvr-1989-chap-2", "Rule 10")])
        self.assertEqual(ids(self.ix.lookup("TMVTR Rule 10", ["Rule 10"], "tmvtr-1963").documents),
                         [("tmvtr-1963", "Rule 10")])

    def test_inserted_rule_identifier(self):
        self.assertEqual(ids(self.ix.lookup("TMVTR rule 13-A", ["Rule 13A"], "tmvtr-1963").documents),
                         [("tmvtr-1963", "Rule 13A")])

    def test_go_number_and_year(self):
        got = self.ix.lookup("What did G.O. 16/2026 change?", [], None)
        self.assertEqual({m for m, _ in ids(got.documents)}, {"go-ms-16-2026-trb"})  # never 10/2026 or 16/2025
        self.assertEqual(ids(self.ix.lookup("G.O.Ms.No. 10 of 2026", [], None).documents),
                         [("go-ms-10-2026-trb", "Order")])
        both = self.ix.lookup("What is G.O. 16 about?", [], None)
        self.assertEqual(both.documents, [])
        self.assertEqual(both.ambiguous, [("G.O.Ms.No. 16", ["G.O.Ms.No. 16/2025", "G.O.Ms.No. 16/2026"])])
        self.assertEqual(self.ix.lookup("G.O. 16/2024", [], None).missing_gos, ["G.O.Ms.No. 16/2024"])

    def test_go_paragraph_reference(self):
        self.assertEqual(ids(self.ix.lookup("paragraph 5 of G.O. 32/2026", [], None).documents),
                         [("go-ms-32-2026-trb", "Paragraph 5")])

    def test_excluded_chunks_are_not_dropped_here(self):
        # Eligibility is enforced once, in the server's filter; lookup and BM25 return raw candidates.
        got = self.ix.lookup("G.O. 16/2026", [], None)
        self.assertIn(("go-ms-16-2026-trb", "SEVENTH SCHEDULE"), ids(got.documents))


class BM25AndFusionTests(unittest.TestCase):
    def test_bm25_ranks_exact_terms(self):
        ix = make_index()
        self.assertEqual(ids(ix.search("crash helmets", 3))[0], ("tmvr-1989-chap-8", "Rule 437"))
        self.assertEqual(ix.search("zzzz nothing matches", 3), [])

    def test_rrf_keeps_distinct_provisions_with_identical_text(self):
        a = Document(page_content="same text", metadata={"manifest_id": "x", "provision_id": "Rule 1", "part": 1})
        b = Document(page_content="same text", metadata={"manifest_id": "x", "provision_id": "Rule 2", "part": 1})
        fused = hr.reciprocal_rank_fusion([[a], [b], [b, a]])
        self.assertEqual(len(fused), 2)
        self.assertEqual(fused[0].metadata["provision_id"], "Rule 2")
        # b: 1/61 + 1/61, a: 1/61 + 1/62 -> b first; both kept, identity preserved.

    def test_rrf_counts_each_list_once_per_chunk(self):
        a = Document(page_content="t", metadata={"manifest_id": "x", "provision_id": "Rule 1"})
        self.assertEqual(len(hr.reciprocal_rank_fusion([[a, a, a]])), 1)


if __name__ == "__main__":
    unittest.main()
