"""Stage 7C (D2), part 3, REAL: the in-process engine against the real nomic-embed-text-v1.5 weights (Ollama's local blob, the file the index
was built with) and against the real Ollama server and the vectors stored in the real index (Stage 7B.1's read-only copy of them).
Needs: a local Ollama with nomic-embed-text (localhost only) and the blob on disk. ~350 MB of memory and a few CPU seconds per text;
run it ONLY when no Linux memory measurement is running. Skipped unless KYR_REAL_INDEX_DIR is set or KYR_REQUIRE_REAL_BACKEND=1
(then a missing Ollama or blob FAILS). Run: KYR_REQUIRE_REAL_BACKEND=1 python3 -W ignore -m unittest discover -s tests -p test_stage7c_nomic_real.py"""
import json
import os
import unittest
from pathlib import Path

import numpy as np
import requests

from backend import embedding_provider as ep
from backend import nomic_local as nl
from backend import rag_profiles as rp

ROOT = Path(__file__).resolve().parent.parent
E71 = ROOT / "eval" / "deployment" / "stage7b1"
REQUIRED = os.environ.get("KYR_REQUIRE_REAL_BACKEND") == "1"


def ollama_blob():
    root = Path.home() / ".ollama" / "models"
    man = json.loads((root / "manifests/registry.ollama.ai/library/nomic-embed-text/latest").read_text())
    layer = next(l for l in man["layers"] if l["mediaType"].endswith("image.model"))
    return root / "blobs" / layer["digest"].replace(":", "-")


def ollama(text):
    r = requests.post("http://127.0.0.1:11434/api/embed", json={"model": "nomic-embed-text", "input": text}, timeout=120).json()
    return np.asarray(r["embeddings"][0], dtype=np.float32)


@unittest.skipUnless(os.environ.get("KYR_REAL_INDEX_DIR") or REQUIRED, "real backend not configured")
class RealModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            requests.get("http://127.0.0.1:11434/api/tags", timeout=3).raise_for_status()
            cls.blob = ollama_blob()
            assert cls.blob.is_file()
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(f"local Ollama and its nomic-embed-text blob are required for this module: {type(exc).__name__}") from None
        cls.eng = nl.NomicEngine(cls.blob, nl.KNOWN_MODEL_SHA256)
        ref = json.loads((E71 / "reference_set.json").read_text())
        cls.questions, cls.docs, cls.ids = ref["questions"], ref["docs"], ref["ids"]
        stored = np.load(E71 / "reference_set.npz")
        assert list(stored["ids"]) == cls.ids
        cls.stored = stored["vecs"]

    def test_the_blob_is_the_known_weights_and_loads_with_the_production_identity(self):
        self.assertEqual(nl.file_sha256(self.blob), nl.KNOWN_MODEL_SHA256)
        self.assertTrue(self.eng.sha256_verified)
        self.assertEqual((self.eng.L, self.eng.H, self.eng.D, self.eng.dimensions), (12, 12, 768, 768))

    def test_queries_match_ollama_far_inside_the_gate(self):
        for q in self.questions[::9]:                                               # 12 queries
            ours = self.eng.embed(["search_query: " + q])[0]
            self.assertGreater(float(ours @ ollama("search_query: " + q)), 0.99999, q)

    def test_documents_match_the_vectors_stored_in_the_real_index(self):
        for i in range(0, len(self.docs), 59):                                      # 10 chunks spread over the corpus
            ours = self.eng.embed(["search_document: " + self.docs[i]])[0]
            self.assertGreater(float(ours @ self.stored[i]), 0.99999, self.ids[i])

    def test_top_one_retrieval_is_identical_to_ollamas_on_the_stored_index(self):
        for q in self.questions[::5]:                                               # 22 questions
            a = int(np.argmin(((self.stored - self.eng.embed(["search_query: " + q])[0]) ** 2).sum(1)))
            b = int(np.argmin(((self.stored - ollama("search_query: " + q)) ** 2).sum(1)))
            self.assertEqual(self.ids[a], self.ids[b], q)

    def test_the_guard_verifies_the_engine_against_probes_taken_from_the_stored_index(self):
        short = [i for i in range(len(self.docs)) if len(self.eng.tok.encode("search_document: " + self.docs[i]).ids) <= 400][::150][:3]
        self.assertEqual(len(short), 3)
        probes = [{"input": "search_document: " + self.docs[i], "vector": [float(x) for x in self.stored[i]]} for i in short]
        env = {"EMBEDDING_PROVIDER": "inprocess_nomic", "EMBEDDING_MODEL_FILE": str(self.blob), "EMBEDDING_MODEL_SHA256": nl.KNOWN_MODEL_SHA256,
               "TG_SNAPSHOT_STORE": "r2"}
        g = ep.build_embeddings(ep.EmbeddingSettings.from_env(env))
        g.configure_index(dims=768, family=ep.INDEX_FAMILY, probes=probes, min_cosine=0.995)
        self.assertEqual(g.state, "unverified")
        report = g.verify()
        self.assertEqual((g.state, report["ok"]), ("ok", True))
        self.assertGreater(report["min_cosine_observed"], 0.99999)
        self.assertEqual(g.min_cosine, 0.995)                                       # the gate was not weakened
        pe = rp.ProfileEmbeddings(g, rp.PROFILES["structured"])
        q = pe.embed_query(self.questions[0])
        self.assertEqual(len(q), 768)
        self.assertGreater(float(np.dot(q, ollama("search_query: " + self.questions[0]))), 0.99999)

    def test_inputs_longer_than_the_token_bound_are_truncated_so_documents_stay_on_the_local_embedder(self):
        # Known, documented limit: the engine embeds at most nl.MAX_TOKENS tokens (bounded memory). The real index holds chunks of up to
        # ~900 tokens embedded whole by Ollama, so for such a chunk the vectors differ. Queries are far shorter. Publishing a snapshot
        # embeds documents and therefore keeps using the local Ollama (backend/index_snapshot.py refuses hosted providers).
        longest = max(range(len(self.docs)), key=lambda i: len(self.docs[i]))
        n = len(self.eng.tok.encode("search_document: " + self.docs[longest]).ids)
        self.assertEqual(n, nl.MAX_TOKENS)                                          # the tokenizer truncated it
        cos = float(self.eng.embed(["search_document: " + self.docs[longest]])[0] @ self.stored[longest])
        self.assertLess(cos, 0.99999)
        self.assertGreater(cos, 0.98)

    def test_a_wrong_pin_on_the_real_file_is_misconfigured_and_never_falls_back(self):
        env = {"EMBEDDING_PROVIDER": "inprocess_nomic", "EMBEDDING_MODEL_FILE": str(self.blob), "EMBEDDING_MODEL_SHA256": "0" * 64}
        g = ep.build_embeddings(ep.EmbeddingSettings.from_env(env))
        self.assertEqual(g.state, "misconfigured")
        with self.assertRaises(ep.EmbeddingUnavailable):
            g.embed_query("search_query: x")

    def test_the_wrong_model_file_is_refused_even_if_someone_pins_it(self):
        other = Path.home() / ".ollama" / "models" / "blobs"
        self.assertTrue(other.is_dir())
        # llama3.2 is a different architecture: it must be refused by identity, not accepted because the pin was computed from it
        import glob
        big = sorted(glob.glob(str(other / "sha256-*")), key=os.path.getsize)
        candidates = [p for p in big if os.path.getsize(p) > 1_000_000_000]
        if not candidates:
            self.skipTest("no other model blob present")
        with self.assertRaises(nl.ModelError):
            nl.NomicEngine(candidates[0], None)


if __name__ == "__main__":
    unittest.main()
