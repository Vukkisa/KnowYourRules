"""Stage 7B.1 real-backend test: the exact existing model run on CPU from the weights Ollama holds, agreeing with Ollama's own output.
Needs: a local Ollama with nomic-embed-text (localhost only; no hosted service) and the torch-free numpy engine under
eval/deployment/stage7b1/. Skipped unless KYR_REAL_INDEX_DIR is set or KYR_REQUIRE_REAL_BACKEND=1 (then a missing Ollama FAILS).
Run: KYR_REQUIRE_REAL_BACKEND=1 python3 -W ignore -m unittest discover -s tests -p test_stage7b1_numpy_real.py"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import requests

ROOT = Path(__file__).resolve().parent.parent
E71 = ROOT / "eval" / "deployment" / "stage7b1"
REQUIRED = os.environ.get("KYR_REQUIRE_REAL_BACKEND") == "1"
OLLAMA = "http://127.0.0.1:11434/api/embed"


def ollama(text):
    r = requests.post(OLLAMA, json={"model": "nomic-embed-text", "input": text}, timeout=60).json()
    return np.asarray(r["embeddings"][0], dtype=np.float32), r["prompt_eval_count"]


@unittest.skipUnless(os.environ.get("KYR_REAL_INDEX_DIR") or REQUIRED, "real backend not configured")
class NumpyEngineAgreesWithOllama(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            requests.get("http://127.0.0.1:11434/api/tags", timeout=3).raise_for_status()
        except Exception as exc:   # noqa: BLE001
            raise AssertionError(f"local Ollama is required for this module: {type(exc).__name__}") from None
        sys.path.insert(0, str(E71))
        import nomic_runtime as nr
        from nomic_numpy import NomicNumpy
        g, cls.blob, tok = nr.load()
        cls.tmp = tempfile.TemporaryDirectory()
        tok_path = Path(cls.tmp.name) / "tokenizer.json"
        tok.save(str(tok_path))
        cls.tok = tok
        from gguf_reader import ollama_blob
        cls.eng = NomicNumpy(ollama_blob()[0], str(tok_path))
        ref = json.loads((E71 / "reference_set.json").read_text())
        cls.questions, cls.docs = ref["questions"][::9], ref["docs"][::60]       # 12 queries, 10 documents: a spread, quick

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_weights_are_the_nomic_embed_text_v1_5_blob(self):
        self.assertTrue(self.blob.startswith("sha256:970aa74c0a90"))
        self.assertEqual(self.eng.g.meta["general.name"], "nomic-embed-text-v1.5")
        self.assertEqual((self.eng.L, self.eng.H, self.eng.D, self.eng.g.meta["nomic-bert.pooling_type"]), (12, 12, 768, 1))

    def test_queries_match_ollama_to_better_than_the_servers_compatibility_gate_by_orders_of_magnitude(self):
        for q in self.questions:
            ref, _ = ollama("search_query: " + q)
            ours = self.eng.embed(["search_query: " + q])[0]
            self.assertGreater(float(ours @ ref), 0.99999, q)
            self.assertAlmostEqual(float(np.linalg.norm(ours)), 1.0, places=4)

    def test_documents_match_ollama_too(self):
        for d in self.docs:
            ref, _ = ollama("search_document: " + d)
            self.assertGreater(float(self.eng.embed(["search_document: " + d])[0] @ ref), 0.99999)

    def test_the_tokenizer_counts_the_same_tokens_as_ollama(self):
        for t in ["search_query: Rule 427", "search_query: What is Rule 389A about?", "The vehicle's café—naïve 3.5 tonnes (GVW)", "a, b."]:
            self.assertEqual(len(self.tok.encode(t).ids), ollama(t)[1], t)

    def test_query_and_document_prefixes_give_different_vectors_and_a_missing_prefix_is_a_third_space(self):
        a, b, c = (self.eng.embed([p + "Rule 427 permits"])[0] for p in ("search_query: ", "search_document: ", ""))
        self.assertLess(float(a @ b), 0.999)
        self.assertLess(float(a @ c), 0.999)

    def test_batching_does_not_change_a_vector(self):
        texts = ["search_query: " + q for q in self.questions[:4]]
        batch = self.eng.embed(texts)
        for i, t in enumerate(texts):
            self.assertGreater(float(batch[i] @ self.eng.embed([t])[0]), 0.99999)

    def test_a_missing_weights_file_is_an_error_not_a_vector(self):
        from nomic_numpy import NomicNumpy
        with self.assertRaises(Exception):
            NomicNumpy(str(Path(self.tmp.name) / "absent.gguf"), str(Path(self.tmp.name) / "tokenizer.json"))


if __name__ == "__main__":
    unittest.main()
