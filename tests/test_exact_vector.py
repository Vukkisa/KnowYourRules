"""Tests for backend/exact_vector.py (Stage 16). Synthetic vectors and fixture text only; no Ollama, Chroma or
model calls. The server-level tests import the server with fakes via tests/test_server.py's helper."""

import json
import math
import types
import unittest
from pathlib import Path

import numpy as np
from langchain_core.documents import Document

from backend import exact_vector as xv
from backend import hybrid_retrieval as hr


class FakeEmbeddings:
    def __init__(self, table):
        self.table, self.calls = table, []

    def embed_query(self, text):
        self.calls.append(text)
        return self.table[text]


def meta(i, state="Telangana", **kw):
    m = {"state": state, "manifest_id": "doc", "provision_id": f"Rule {i}", "part": 1, "parts": 1,
         "location": f"f.htm#{i}", "sha256": "h"}
    m.update(kw)
    return m


def make(vectors, metas=None, ids=None, table=None):
    ids = ids or [f"id{i}" for i in range(len(vectors))]
    metas = metas or [meta(i) for i in range(len(vectors))]
    docs = [f"text {i}" for i in range(len(vectors))]
    return xv.ExactVectorIndex(ids, vectors, docs, metas, FakeEmbeddings(table or {}))


class DistanceTests(unittest.TestCase):
    def test_squared_l2_matches_manual_calculation(self):
        idx = make([[1.0, 0.0], [0.0, 1.0], [0.6, 0.8]])
        d = idx.distances([1.0, 0.0])
        self.assertTrue(np.allclose(d, [0.0, 2.0, 0.16 + 0.64]))

    def test_squared_l2_not_cosine_or_plain_l2(self):
        idx = make([[3.0, 4.0]])
        self.assertAlmostEqual(float(idx.distances([0.0, 0.0])[0]), 25.0)  # not 5 (L2) and not cosine

    def test_results_ascending_with_scores(self):
        idx = make([[0.0, 3.0], [0.0, 1.0], [0.0, 2.0]])
        out = idx.search_by_vector([0.0, 0.0], 3)
        self.assertEqual([d.id for d, _ in out], ["id1", "id2", "id0"])
        self.assertEqual([s for _, s in out], [1.0, 4.0, 9.0])

    def test_k_limits_results(self):
        idx = make([[float(i), 0.0] for i in range(10)])
        self.assertEqual(len(idx.search_by_vector([0.0, 0.0], 3)), 3)


class TieBreakAndDeterminismTests(unittest.TestCase):
    def test_equal_distances_break_ties_by_chunk_id(self):
        idx = make([[1.0, 0.0], [-1.0, 0.0], [0.0, 1.0]], ids=["c", "a", "b"])
        self.assertEqual([d.id for d, _ in idx.search_by_vector([0.0, 0.0], 3)], ["a", "b", "c"])

    def test_tie_break_is_independent_of_storage_order(self):
        vecs, ids = [[1.0, 0.0], [-1.0, 0.0], [0.0, 1.0]], ["c", "a", "b"]
        a = make(vecs, ids=ids).search_by_vector([0.0, 0.0], 3)
        b = make(vecs[::-1], ids=ids[::-1], metas=[meta(i) for i in (2, 1, 0)]).search_by_vector([0.0, 0.0], 3)
        self.assertEqual([d.id for d, _ in a], [d.id for d, _ in b])

    def test_repeated_queries_are_identical(self):
        rng = np.random.default_rng(7)
        vecs = rng.normal(size=(200, 16)).tolist()
        q = rng.normal(size=16).tolist()
        idx = make(vecs, table={"q": q})
        runs = [json.dumps([(d.id, s) for d, s in idx.similarity_search_with_score("q", 10)]) for _ in range(5)]
        self.assertEqual(len(set(runs)), 1)
        fresh = make(vecs, table={"q": q})
        self.assertEqual(runs[0], json.dumps([(d.id, s) for d, s in fresh.similarity_search_with_score("q", 10)]))


class FilterAndEligibilityTests(unittest.TestCase):
    def test_equality_filter_excludes_other_states(self):
        idx = make([[0.0, 0.0], [0.1, 0.0], [0.2, 0.0]],
                   metas=[meta(0, state="Central"), meta(1), meta(2, state="Andhra Pradesh")])
        out = idx.search_by_vector([0.0, 0.0], 5, {"state": "Telangana"})
        self.assertEqual([d.metadata["state"] for d, _ in out], ["Telangana"])

    def test_unsupported_filters_raise_so_caller_can_fall_back(self):
        idx = make([[0.0, 0.0]])
        for bad in ({"$and": [{"state": "Telangana"}]}, {"state": {"$eq": "Telangana"}}, ["state"]):
            with self.assertRaises(ValueError):
                idx.search_by_vector([0.0, 0.0], 1, bad)

    def test_ineligible_chunks_are_returned_with_metadata_for_the_server_to_drop(self):
        # Like Chroma, the vector layer does not drop answer_eligible=False; server.retrieve() does.
        idx = make([[0.0, 0.0], [1.0, 0.0]], metas=[meta(0, answer_eligible=False), meta(1)])
        out = idx.search_by_vector([0.0, 0.0], 2, {"state": "Telangana"})
        self.assertIs(out[0][0].metadata["answer_eligible"], False)

    def test_returned_metadata_is_a_copy(self):
        idx = make([[0.0, 0.0]])
        idx.search_by_vector([0.0, 0.0], 1)[0][0].metadata["state"] = "changed"
        self.assertEqual(idx.metadatas[0]["state"], "Telangana")


class InputValidationTests(unittest.TestCase):
    def test_empty_and_blank_queries_return_nothing_without_embedding(self):
        idx = make([[0.0, 0.0]])
        for q in ("", "   ", None, 5):
            self.assertEqual(idx.similarity_search_with_score(q, 3), [])
        self.assertEqual(idx.embedding_function.calls, [])

    def test_non_positive_or_invalid_k(self):
        idx = make([[0.0, 0.0]])
        for k in (0, -1, None, 1.5, True):
            self.assertEqual(idx.search_by_vector([0.0, 0.0], k), [])

    def test_wrong_dimension_or_non_finite_query(self):
        idx = make([[0.0, 0.0]])
        for q in ([0.0], [0.0, 0.0, 0.0], [math.nan, 0.0], [[0.0, 0.0]]):
            with self.assertRaises(ValueError):
                idx.search_by_vector(q, 1)

    def test_empty_index(self):
        idx = xv.ExactVectorIndex([], [], [], [], FakeEmbeddings({}))
        self.assertEqual(idx.search_by_vector([0.0, 0.0], 3), [])

    def test_bad_construction(self):
        with self.assertRaises(ValueError):
            make([[0.0, 0.0], [1.0, 1.0]], ids=["x", "x"])
        with self.assertRaises(ValueError):
            xv.ExactVectorIndex(["a"], [[0.0]], [], [{}], None)
        with self.assertRaises(ValueError):
            make([[math.inf, 0.0]])
        with self.assertRaises(ValueError):
            xv.ExactVectorIndex(["a"], [[0.0]], ["t"], [{}], None, space="cosine")


class StoreAndHybridCompatibilityTests(unittest.TestCase):
    def _store(self, space=None):
        got = {"ids": ["a", "b"], "embeddings": [[0.0, 1.0], [1.0, 0.0]], "documents": ["A text", "B text"],
               "metadatas": [meta(1), meta(2)]}
        coll = types.SimpleNamespace(metadata={"hnsw:space": space} if space else {"rag_profile": "structured"},
                                     get=lambda include: got)
        return types.SimpleNamespace(_collection=coll, embeddings=FakeEmbeddings({"q": [1.0, 0.0]}))

    def test_from_store_uses_default_l2_and_store_embedding_function(self):
        idx = xv.ExactVectorIndex.from_store(self._store())
        out = idx.similarity_search_with_score("q", 2, {"state": "Telangana"})
        self.assertEqual([(d.id, d.page_content, s) for d, s in out], [("b", "B text", 0.0), ("a", "A text", 2.0)])
        self.assertEqual(idx.embedding_function.calls, ["q"])

    def test_from_store_refuses_other_spaces(self):
        with self.assertRaises(ValueError):
            xv.ExactVectorIndex.from_store(self._store(space="cosine"))

    def test_output_shape_matches_langchain_chroma(self):
        out = xv.ExactVectorIndex.from_store(self._store()).similarity_search_with_score("q", 1)
        doc, score = out[0]
        self.assertIsInstance(doc, Document)
        self.assertIsInstance(score, float)
        self.assertEqual(doc.id, "b")

    def test_results_fuse_with_lexical_lists(self):
        out = xv.ExactVectorIndex.from_store(self._store()).similarity_search_with_score("q", 2)
        vec = [d for d, _ in out]
        lexical = [Document(page_content="A text", metadata=meta(1))]
        fused = hr.reciprocal_rank_fusion([[], lexical, vec])
        self.assertEqual([d.page_content for d in fused], ["A text", "B text"])  # same chunk key from both lists
        self.assertEqual(len(fused), 2)


class ServerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import test_server as ts  # imports the server with in-memory fakes (tests/ is the discovery root)
        cls.ts = ts

    def test_default_is_exact_and_falls_back_to_chroma_without_a_collection(self):
        srv = self.ts.srv
        import os
        expected = os.environ.get("RAG_VECTOR_SEARCH", "exact").strip().lower()
        self.assertEqual(srv.VECTOR_SEARCH, expected if expected in ("exact", "hnsw") else "exact")
        self.assertIsNone(srv.EXACT_INDEX)  # the fake store has no collection to snapshot
        self.assertTrue(srv.vector_search("learner licence"))

    def test_exact_index_is_used_when_available(self):
        srv = self.ts.srv
        fake = make([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]],
                    metas=[meta(0), meta(1, state="Central"), meta(2, state="Gujarat")], table={"q": [0.0, 0.0]})
        original = srv.EXACT_INDEX
        try:
            srv.EXACT_INDEX = fake
            out = srv.vector_search("q")
        finally:
            srv.EXACT_INDEX = original
        # Telangana and the separately tagged Central chunks are served; any other state is filtered out
        self.assertEqual([d.id for d, _ in out], ["id0", "id1"])

    def test_unsupported_filter_falls_back(self):
        srv = self.ts.srv
        broken = types.SimpleNamespace(similarity_search_with_score=lambda *a, **k: (_ for _ in ()).throw(ValueError()))
        original = srv.EXACT_INDEX
        try:
            srv.EXACT_INDEX = broken
            self.assertTrue(srv.vector_search("learner licence"))
        finally:
            srv.EXACT_INDEX = original


class RecordedRegressionTests(unittest.TestCase):
    """Regression against existing behaviour: Stage 15 recorded Chroma's l2 distances for 108 real questions.
    Where HNSW returned the true nearest neighbours, exact squared L2 must give the same order and distances."""

    def test_stage15_record_agrees_with_squared_l2(self):
        path = Path(__file__).resolve().parent.parent / "eval" / "legal-validation" / "stage-15-reproducibility.json"
        if not path.exists():
            self.skipTest("Stage 15 record not present")
        rows = json.loads(path.read_text())["per_question_run1"]
        checked = 0
        for r in rows:
            if r["vector_hnsw_equals_exact"]:
                for a, b in zip(r["vector_hnsw"], r["vector_exact"]):
                    self.assertEqual(a["chunk"], b["chunk"])
                    self.assertAlmostEqual(a["distance"], b["distance"], places=6)
                    checked += 1
        self.assertGreater(checked, 500)


if __name__ == "__main__":
    unittest.main()
