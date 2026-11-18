"""Stage 7C (D2), part 1: the in-process nomic engine (backend/nomic_local.py). Offline: a tiny synthetic GGUF, no model, no Ollama, no
network. The agreement of the engine with the REAL model and with Ollama is tested in test_stage7c_nomic_real.py (needs the real file)."""
import hashlib
import tempfile
import unittest
from pathlib import Path

import numpy as np

import gguf_fixture as gf
from backend import nomic_local as nl


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = gf.write(Path(cls.tmp.name) / "tiny.gguf")
        cls.sha = hashlib.sha256(cls.path.read_bytes()).hexdigest()
        cls.eng = nl.NomicEngine(cls.path, cls.sha, spec=gf.TINY)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_embeds_unit_vectors_of_the_model_width(self):
        v = self.eng.embed(["search_query: hello world", "search_document: abc"])
        self.assertEqual(v.shape, (2, 16))
        np.testing.assert_allclose(np.linalg.norm(v, axis=1), 1.0, atol=1e-5)
        self.assertEqual(self.eng.dimensions, 16)

    def test_batching_and_padding_do_not_change_a_vector(self):
        a, b = "search_query: hello", "search_query: a much longer query about registration of a vehicle"
        single = [self.eng.embed([t])[0] for t in (a, b)]
        batch = self.eng.embed([a, b])
        for s, m in zip(single, batch):
            np.testing.assert_allclose(s, m, atol=1e-5)

    def test_result_matches_an_independent_straightforward_implementation(self):
        text = "search_document: rule six licence"
        np.testing.assert_allclose(self.eng.embed([text])[0], reference_embed(self.eng, text), atol=1e-5)

    def test_it_is_deterministic(self):
        np.testing.assert_array_equal(self.eng.embed(["search_query: x"]), self.eng.embed(["search_query: x"]))

    def test_query_and_document_prefixes_give_different_vectors(self):
        q, d = self.eng.embed(["search_query: hello"])[0], self.eng.embed(["search_document: hello"])[0]
        self.assertLess(float(q @ d), 0.9999)

    def test_text_without_a_task_prefix_is_refused(self):
        for bad in ("hello", "Search_query: x", "query: x", ""):
            with self.assertRaises(nl.ModelError):
                self.eng.embed([bad])
        with self.assertRaises(nl.ModelError):
            self.eng.embed([None])

    def test_very_long_input_is_truncated_not_expanded(self):
        long = "search_query: " + "word " * 5000
        self.assertLessEqual(len(self.eng.tok.encode(long).ids), nl.MAX_TOKENS)
        v = self.eng.embed([long])
        self.assertEqual(v.shape, (1, 16))

    def test_the_model_is_opened_once_not_per_call(self):
        opened = []
        orig = nl.Gguf.__init__

        def counting(self_, path):
            opened.append(1)
            orig(self_, path)
        nl.Gguf.__init__ = counting
        try:
            eng = nl.NomicEngine(self.path, self.sha, spec=gf.TINY)
            n = len(opened)
            for _ in range(5):
                eng.embed(["search_query: hello"])
        finally:
            nl.Gguf.__init__ = orig
        self.assertEqual((n, len(opened)), (1, 1))


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, path, sha=None, spec=gf.TINY):
        return nl.NomicEngine(path, sha, spec=spec)

    def assertRefused(self, path, sha=None, spec=gf.TINY, text=None):
        with self.assertRaises(nl.ModelError) as cm:
            self.load(path, sha, spec)
        self.assertNotIn(str(self.dir), str(cm.exception))          # no filesystem paths in messages
        if text:
            self.assertIn(text, str(cm.exception))

    def test_a_missing_file_is_refused_with_a_clear_message(self):
        self.assertRefused(self.dir / "absent.gguf", text="does not exist")

    def test_a_directory_or_garbage_or_truncated_file_is_refused(self):
        self.assertRefused(self.dir)
        junk = self.dir / "junk.gguf"
        junk.write_bytes(b"not a model at all" * 10)
        self.assertRefused(junk, text="not a GGUF")
        good = gf.write(self.dir / "good.gguf")
        cut = self.dir / "cut.gguf"
        cut.write_bytes(good.read_bytes()[:400])
        self.assertRefused(cut)
        cut2 = self.dir / "cut2.gguf"
        cut2.write_bytes(good.read_bytes()[:-500])
        self.assertRefused(cut2, text="truncated")

    def test_a_wrong_pin_is_refused_before_the_file_is_parsed(self):
        good = gf.write(self.dir / "m.gguf")
        self.assertRefused(good, sha="0" * 64, text="pinned SHA-256")
        sha = hashlib.sha256(good.read_bytes()).hexdigest()
        self.assertTrue(self.load(good, sha).sha256_verified)
        self.assertTrue(self.load(good, sha.upper()).sha256_verified)

    def test_a_file_that_is_another_model_is_refused_even_with_its_own_correct_pin(self):
        for name, over, what in (("name", {"general.name": "bge-small-en-v1.5"}, "general.name"),
                                 ("arch", {"general.architecture": "bert"}, "general.architecture"),
                                 ("pool", {"nomic-bert.pooling_type": 2}, "pooling_type"),
                                 ("heads", {"nomic-bert.attention.head_count": 4}, "head_count")):
            p = gf.write(self.dir / f"{name}.gguf", **over)
            self.assertRefused(p, sha=hashlib.sha256(p.read_bytes()).hexdigest(), text=what)

    def test_wrong_dimensions_or_layers_or_vocabulary_are_refused(self):
        p = gf.write(self.dir / "a.gguf")
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        for spec, what in ((nl.ModelSpec(layers=2, width=32, heads=2, vocab=57), "embedding_length"),
                           (nl.ModelSpec(layers=3, width=16, heads=2, vocab=57), "block_count"),
                           (nl.ModelSpec(layers=2, width=16, heads=2, vocab=100), "vocabulary size")):
            self.assertRefused(p, sha=sha, spec=spec, text=what)

    def test_the_production_spec_is_the_real_models_identity(self):
        s = nl.NOMIC_SPEC
        self.assertEqual((s.name, s.arch, s.layers, s.width, s.heads, s.pooling, s.vocab), ("nomic-embed-text-v1.5", "nomic-bert", 12, 768, 12, 1, 30522))
        self.assertEqual(nl.KNOWN_MODEL_SHA256, "970aa74c0a90ef7482477cf803618e776e173c007bf957f635f1015bfcfef0e6")
        # the tiny fixture must not pass as the production model
        p = gf.write(self.dir / "t.gguf")
        self.assertRefused(p, sha=hashlib.sha256(p.read_bytes()).hexdigest(), spec=nl.NOMIC_SPEC)

    def test_a_missing_tensor_or_a_missing_special_token_is_refused(self):
        toks = gf.tokens()
        toks[2] = "[XXX]"
        p = gf.write(self.dir / "tok.gguf", **{"tokenizer.ggml.tokens": toks})
        self.assertRefused(p, sha=hashlib.sha256(p.read_bytes()).hexdigest(), text="special tokens")


def reference_embed(eng, text):
    """One sequence, plain loops over heads: shares nothing with the batched implementation except the weights."""
    ids = eng.tok.encode(text).ids
    T, D, H, hd = len(ids), eng.D, eng.H, eng.hd
    ln = lambda x, w, b: (x - x.mean(-1, keepdims=True)) / np.sqrt(x.var(-1, keepdims=True) + eng.eps) * w + b  # noqa: E731
    x = ln(eng.emb[ids].astype(np.float32) + eng.tt, eng.enw, eng.enb)
    inv = 1.0 / (eng.base ** (np.arange(0, hd, 2) / hd))
    for blk in eng.blocks:
        qkv = x @ blk["qkv"].astype(np.float32).T
        q, k, v = qkv[:, :D], qkv[:, D:2 * D], qkv[:, 2 * D:]
        ctx = np.zeros((T, D), dtype=np.float32)
        for h in range(H):
            sl = slice(h * hd, (h + 1) * hd)
            qh, kh, vh = q[:, sl].copy(), k[:, sl].copy(), v[:, sl]
            for arr in (qh, kh):
                for pos in range(T):
                    a, b = arr[pos, :hd // 2].copy(), arr[pos, hd // 2:].copy()
                    c, s = np.cos(pos * inv), np.sin(pos * inv)
                    arr[pos, :hd // 2], arr[pos, hd // 2:] = a * c - b * s, b * c + a * s
            sc = qh @ kh.T / np.sqrt(hd)
            sc = np.exp(sc - sc.max(-1, keepdims=True))
            ctx[:, sl] = (sc / sc.sum(-1, keepdims=True)) @ vh
        x = ln(x + ctx @ blk["o"].astype(np.float32).T, blk["n1w"], blk["n1b"])
        up, gate = x @ blk["up"].astype(np.float32).T, x @ blk["gate"].astype(np.float32).T
        x = ln(x + (up * (gate / (1 + np.exp(-gate)))) @ blk["down"].astype(np.float32).T, blk["n2w"], blk["n2b"])
    p = x.mean(0)
    return p / np.linalg.norm(p)


if __name__ == "__main__":
    unittest.main()
