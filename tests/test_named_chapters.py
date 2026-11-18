"""Stage 29: when a question names two or more chapters, each named chapter leads with its best candidate.

Unit tests use synthetic chunks only (no Ollama, Chroma, Groq or network). The recorded regression tests read the
Stage 29 evaluation record, produced on scratchpad index copies with local embeddings; they skip when the record
is absent (KYR_REQUIRE_LEGAL_DATA=1 makes that a failure)."""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend import hybrid_retrieval as hr  # noqa: E402
from test_server import srv  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RECORD = ROOT / "eval" / "legal-validation" / "stage-29-evaluation.json"
REQUIRE = os.environ.get("KYR_REQUIRE_LEGAL_DATA") == "1"

ALPHA = "CHAPTER II LICENSING OF PILOTS OF SYNTHETIC CRAFT"
BETA = "CHAPTER III LICENSING OF STEWARDS OF SYNTHETIC CRAFT"
GAMMA = "CHAPTER IX SYNTHETIC HARBOURS"
TITLE = "Synthetic Rules"


def index(rows, title=TITLE):
    """rows: [(provision, chapter, body)] -> LexicalIndex over synthetic chunks."""
    texts, metas = [], []
    for i, (provision, chapter, body) in enumerate(rows):
        header = " - ".join(x for x in (title, chapter, provision, "Heading") if x)
        texts.append(f"{header}\n{body}")
        metas.append({"state": "Telangana", "manifest_id": "synthetic", "provision_id": provision, "part": 1,
                      "location": f"s#{i}", "sha256": "d" * 64, "source_file": "s.htm", "answer_eligible": True,
                      "title": title, "chapter": chapter})
    return hr.LexicalIndex(texts, metas)


ROWS = [("Rule 1", BETA, "steward token one"), ("Rule 2", BETA, "steward token two"),
        ("Rule 3", BETA, "steward token three"), ("Rule 4", ALPHA, "pilot token"),
        ("Rule 5", GAMMA, "harbour dues"), ("Rule 6", "", "no chapter at all")]


def ids(docs):
    return [d.metadata["provision_id"] for d in docs]


class NamingTermTests(unittest.TestCase):
    def test_only_words_unique_to_one_chapter_title_name_it(self):
        terms = {c[1]: t for c, t in index(ROWS).chapter_terms.items()}
        self.assertEqual(terms[ALPHA], {"pilot"})
        self.assertEqual(terms[BETA], {"steward"})
        self.assertEqual(terms[GAMMA], {"harbour"})  # "synthetic" is shared; the chapter number is not a word
        self.assertFalse({"licensing", "craft", "synthetic", "chapter", "ii", "iii", "ix"} &
                         set().union(*terms.values()))

    def test_chunks_without_a_chapter_give_no_terms(self):
        self.assertEqual(index([("Rule 1", "", "a"), ("Rule 2", "", "b")]).chapter_terms, {})


class SpreadNamedChaptersTests(unittest.TestCase):
    def setUp(self):
        self.index = index(ROWS)
        self.docs = self.index.docs

    def test_each_named_chapter_leads_with_its_best_candidate(self):
        out = self.index.spread_named_chapters("What are the token rules for pilots and for stewards?", self.docs)
        self.assertEqual(ids(out), ["Rule 1", "Rule 4", "Rule 2", "Rule 3", "Rule 5", "Rule 6"])

    def test_same_chunks_only_reordered(self):
        out = self.index.spread_named_chapters("pilots and stewards", self.docs)
        self.assertEqual(sorted(map(id, out)), sorted(map(id, self.docs)))

    def test_one_named_chapter_is_unchanged(self):
        for q in ("What tokens do stewards carry?", "pilot token", "What are the harbour dues?"):
            self.assertIs(self.index.spread_named_chapters(q, self.docs), self.docs, q)

    def test_shared_title_words_name_nothing(self):
        self.assertIs(self.index.spread_named_chapters("licensing of synthetic craft", self.docs), self.docs)

    def test_named_chapter_absent_from_the_candidates_is_ignored(self):
        only_beta = self.docs[:3]
        self.assertIs(self.index.spread_named_chapters("pilots and stewards", only_beta), only_beta)

    def test_nothing_moves_ahead_of_the_first_named_candidate(self):
        docs = [self.docs[5], self.docs[4], self.docs[0], self.docs[1], self.docs[3]]  # 6, 5, 1, 2, 4
        out = self.index.spread_named_chapters("pilots and stewards", docs)
        self.assertEqual(ids(out), ["Rule 6", "Rule 5", "Rule 1", "Rule 4", "Rule 2"])

    def test_three_named_chapters(self):
        out = self.index.spread_named_chapters("stewards, harbours and pilots", self.docs)
        self.assertEqual(ids(out), ["Rule 1", "Rule 4", "Rule 5", "Rule 2", "Rule 3", "Rule 6"])

    def test_index_without_chapters_never_reorders(self):
        plain = index([(p, "", b) for p, _c, b in ROWS])
        self.assertIs(plain.spread_named_chapters("pilots and stewards", plain.docs), plain.docs)

    def test_same_chapter_label_in_two_documents_stays_separate(self):
        a, b = index(ROWS[:1], "Synthetic Rules A"), index(ROWS[:1], "Synthetic Rules B")
        self.assertNotEqual(hr.chapter_of(a.docs[0]), hr.chapter_of(b.docs[0]))


class ServerRetrieveTests(unittest.TestCase):
    """server.retrieve applies the reorder to the chunks it returns, and only reorders them."""

    def retrieve(self, question, rows=ROWS):
        idx = index(rows)
        ranked = [(d, 0.2 + i / 100) for i, d in enumerate(idx.docs)]
        with mock.patch.object(srv, "LEXICAL_INDEX", idx), mock.patch.object(srv, "RETRIEVAL_MODE", "hybrid"), \
                mock.patch.object(srv, "KB_APPROVED", False), \
                mock.patch.object(srv, "vector_search", lambda q: ranked), \
                mock.patch.object(idx, "search", lambda q, k: [d for d, _ in ranked[:k]]), \
                mock.patch.dict(srv.PROVISION_CATALOGUE, {}, clear=True):
            return ids(srv.retrieve(question))

    def test_question_naming_two_chapters_is_reordered(self):
        self.assertEqual(self.retrieve("What are the token rules for pilots and for stewards?"),
                         ["Rule 1", "Rule 4", "Rule 2", "Rule 3", "Rule 5", "Rule 6"])

    def test_other_questions_keep_the_fused_order(self):
        for q in ("What tokens do stewards carry?", "What are the token rules?"):
            self.assertEqual(self.retrieve(q), ["Rule 1", "Rule 2", "Rule 3", "Rule 4", "Rule 5", "Rule 6"], q)

    def test_index_without_chapters_keeps_the_fused_order(self):
        self.assertEqual(self.retrieve("pilots and stewards", [(p, "", b) for p, _c, b in ROWS]),
                         ["Rule 1", "Rule 2", "Rule 3", "Rule 4", "Rule 5", "Rule 6"])


class RecordedRegressionTests(unittest.TestCase):
    """The Stage 29 record: TG-PQ-017 keeps Rule 455, TG-MR-007 recovers Rule 37, nothing else is worse."""

    R455, R37 = "tmvr-1989-chap-11::Rule 455", "tmvr-1989-chap-2::Rule 37"

    @classmethod
    def setUpClass(cls):
        cls.rec = json.loads(RECORD.read_text()) if RECORD.is_file() else None
        cls.cases = {c["id"]: c for c in json.loads(
            (ROOT / "eval" / "telangana-retrieval-benchmark.json").read_text())["cases"]}

    def setUp(self):
        if self.rec is None:
            if REQUIRE:
                self.fail("Stage 29 record not present (KYR_REQUIRE_LEGAL_DATA=1)")
            self.skipTest("Stage 29 record not present")

    def scored(self):
        return [q for q, c in self.cases.items() if c["expected_retrieval_outcome"] == "retrieve"]

    def test_both_target_questions(self):
        for mode in ("exact", "hnsw"):
            new, s28 = self.rec["stage29"][mode]["ranked"], self.rec["stage28"][mode]["ranked"]
            self.assertIn(self.R455, new["TG-PQ-017"][:5], mode)
            self.assertIn(self.R37, new["TG-MR-007"][:5], mode)
            self.assertNotIn(self.R37, s28["TG-MR-007"][:5], mode)
            self.assertNotIn(self.R455, self.rec["baseline"][mode]["ranked"]["TG-PQ-017"][:5], mode)

    def test_metrics_do_not_fall_below_stage_28_and_recall5_beats_stage_17(self):
        for mode in ("exact", "hnsw"):
            base, s28, new = (self.rec[k][mode] for k in ("baseline", "stage28", "stage29"))
            for key in ("recall@1", "recall@3", "recall@5", "hit@5", "precision@5", "mrr"):
                self.assertGreaterEqual(new[key], s28[key], (mode, key))
            self.assertGreater(new["recall@5"], base["recall@5"], mode)
            self.assertEqual(new["hit@5"], 1.0)
            self.assertEqual((new["guard"], new["excluded_chunks_retrieved"], new["model_calls"], new["scored_cases"]),
                             ("12/12", 0, {}, 79))

    def test_no_expected_provision_leaves_the_top_five(self):
        lost = []
        for mode in ("exact", "hnsw"):
            for before in ("baseline", "stage28"):
                for q in self.scored():
                    old, new = self.rec[before][mode]["ranked"][q][:5], self.rec["stage29"][mode]["ranked"][q][:5]
                    lost += [(mode, before, q, p) for p in self.cases[q]["expected_provisions"]
                             if p in old and p not in new]
        self.assertEqual(lost, [])

    def test_exact_mode_only_reorders_the_two_questions_that_name_two_chapters(self):
        s28, new = self.rec["stage28"]["exact"]["ranked"], self.rec["stage29"]["exact"]["ranked"]
        self.assertEqual(sorted(q for q in new if new[q] != s28[q]), ["TG-MR-007", "TG-MR-008"])
        self.assertEqual([q for q in new if sorted(new[q]) != sorted(s28[q])], [])  # same provisions returned

    def test_exact_and_hnsw_agree(self):
        keys = ("recall@1", "recall@3", "recall@5", "hit@5", "precision@5", "mrr")
        e, h = self.rec["stage29"]["exact"], self.rec["stage29"]["hnsw"]
        self.assertEqual({k: e[k] for k in keys}, {k: h[k] for k in keys})
        self.assertEqual([q for q in self.scored() if e["ranked"][q][:5] != h["ranked"][q][:5]], [])


if __name__ == "__main__":
    unittest.main()
