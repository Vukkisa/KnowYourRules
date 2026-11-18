"""The Vercel model is held in memory (no file, no lock file, nothing in /tmp). Offline and deterministic.

Covers: the in-memory download (size, SHA-256, truncation, network failure, no disk writes), the buffer-backed engine (bit-identical to the
file-backed engine, 768/16 dimensions per spec, task prefixes, malformed input, buffer lifetime), the provider wiring (EMBEDDING_MODEL_SOURCE=memory,
fail-closed when the buffer is missing or wrong, the probe check still decides readiness) and the runtime validation. A tiny synthetic GGUF
(tests/gguf_fixture.py) stands in for the 262 MiB model; one optional test uses the real model when a local Ollama blob is present."""
import gc
import hashlib
import io
import json
import mmap
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import gguf_fixture as gf  # noqa: E402
from backend import embedding_provider as ep  # noqa: E402
from backend import nomic_local as nl  # noqa: E402
from backend import vercel_runtime as vr  # noqa: E402

URL = "https://models.example/nomic.gguf?sig=PRESIGNED-SECRET-123"
PIN = "ab" * 32


class Resp:
    def __init__(self, data, headers="auto", fail_after=None):
        self.b, self.closed, self.fail_after, self.read_bytes = io.BytesIO(data), False, fail_after, 0
        self.headers = {"Content-Length": str(len(data))} if headers == "auto" else headers

    def read(self, n):
        if self.fail_after is not None and self.read_bytes >= self.fail_after:
            raise ConnectionResetError("reset")
        block = self.b.read(n)
        self.read_bytes += len(block)
        return block

    def close(self):
        self.closed = True


class Opener:
    def __init__(self, *script):
        self.script, self.calls = list(script), 0

    def __call__(self, request, timeout=None):
        self.calls += 1
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, BaseException):
            raise item
        return item() if callable(item) else item


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp_ctx = tempfile.TemporaryDirectory()
        d = Path(cls.tmp_ctx.name)
        cls.model = gf.write(d / "tiny.gguf", seed=1)
        cls.other = gf.write(d / "other.gguf", seed=2)
        cls.data = cls.model.read_bytes()
        cls.other_data = cls.other.read_bytes()
        cls.sha = hashlib.sha256(cls.data).hexdigest()
        cls.other_sha = hashlib.sha256(cls.other_data).hexdigest()
        cls.size = len(cls.data)

    @classmethod
    def tearDownClass(cls):
        cls.tmp_ctx.cleanup()

    def setUp(self):
        nl.set_memory_model(None)
        self.addCleanup(nl.set_memory_model, None)

    def fetch(self, opener, data=None, **kw):
        kw.setdefault("sha256", self.sha)
        kw.setdefault("size", self.size)
        return vr.fetch_model_to_memory(URL, opener=opener, **kw)

    def buffer_of(self, data):
        buf = mmap.mmap(-1, len(data))
        buf.write(data)
        buf.seek(0)
        return buf


# ------------------------------------------------------------------------------------------------------------ the download
class MemoryDownloadTests(Base):
    def test_the_correct_size_and_hash_are_accepted_and_held_in_memory(self):
        buf, info = self.fetch(Opener(lambda: Resp(self.data)))
        self.addCleanup(buf.close)
        self.assertEqual(len(buf), self.size)
        self.assertEqual(bytes(buf[:]), self.data)
        self.assertTrue(info["in_memory"])
        self.assertEqual(nl.buffer_sha256(buf), self.sha)

    def test_the_real_pinned_constants_are_the_defaults(self):
        import inspect
        sig = inspect.signature(vr.fetch_model_to_memory)
        self.assertEqual(sig.parameters["size"].default, 274290656)
        self.assertEqual(sig.parameters["sha256"].default, "970aa74c0a90ef7482477cf803618e776e173c007bf957f635f1015bfcfef0e6")

    def test_a_wrong_expected_size_is_rejected(self):
        for size in (self.size - 1, self.size + 1):
            with self.assertRaises(vr.ModelFetchError) as cm:
                self.fetch(Opener(lambda: Resp(self.data)), size=size)
            self.assertEqual(cm.exception.code, "size_mismatch")

    def test_a_server_that_announces_a_different_size_is_rejected_before_reading(self):
        resp = Resp(self.data, headers={"Content-Length": str(self.size + 5)})
        with self.assertRaises(vr.ModelFetchError) as cm:
            self.fetch(Opener(resp))
        self.assertEqual(cm.exception.code, "size_mismatch")
        self.assertEqual(resp.read_bytes, 0)

    def test_a_download_larger_than_the_model_is_stopped_without_announcing_a_size(self):
        with self.assertRaises(vr.ModelFetchError) as cm:
            self.fetch(Opener(lambda: Resp(self.data + b"extra", headers={})))
        self.assertEqual(cm.exception.code, "size_mismatch")

    def test_a_truncated_download_is_rejected(self):
        with self.assertRaises(vr.ModelFetchError) as cm:
            self.fetch(Opener(lambda: Resp(self.data[:-10], headers={})))          # ends early, announces nothing
        self.assertEqual(cm.exception.code, "size_mismatch")
        with self.assertRaises(vr.ModelFetchError) as cm:                           # announces the full size, then stops
            self.fetch(Opener(lambda: Resp(self.data[:-10], headers={"Content-Length": str(self.size)})))
        self.assertEqual(cm.exception.code, "size_mismatch")

    def test_a_wrong_hash_is_rejected_even_when_the_size_is_right(self):
        tampered = bytearray(self.data)
        tampered[-1] ^= 1
        with self.assertRaises(vr.ModelFetchError) as cm:
            self.fetch(Opener(lambda: Resp(bytes(tampered))))
        self.assertEqual(cm.exception.code, "checksum_mismatch")
        with self.assertRaises(vr.ModelFetchError) as cm:                           # a different model of the same size is not the pinned one
            self.fetch(Opener(lambda: Resp(self.other_data)), size=len(self.other_data))
        self.assertEqual(cm.exception.code, "checksum_mismatch")

    def test_a_network_failure_fails_closed_after_one_retry_and_never_returns_a_buffer(self):
        for err in (urllib.error.URLError("down"), TimeoutError("slow"), ConnectionResetError("reset")):
            op = Opener(err)
            with self.assertRaises(vr.ModelFetchError) as cm:
                self.fetch(op)
            self.assertEqual(cm.exception.code, "download_failed")
            self.assertEqual(op.calls, 2)

    def test_a_connection_that_breaks_mid_download_fails_closed(self):
        op = Opener(lambda: Resp(self.data, fail_after=100))
        with self.assertRaises(vr.ModelFetchError) as cm:
            self.fetch(op)
        self.assertEqual(cm.exception.code, "download_failed")

    def test_a_client_error_is_not_retried_and_a_server_error_is(self):
        err = urllib.error.HTTPError(URL, 403, "no", {}, None)
        op = Opener(err)
        with self.assertRaises(vr.ModelFetchError):
            self.fetch(op)
        self.assertEqual(op.calls, 1)
        op = Opener(urllib.error.HTTPError(URL, 503, "busy", {}, None), lambda: Resp(self.data))
        buf, _ = self.fetch(op)
        self.addCleanup(buf.close)
        self.assertEqual(op.calls, 2)

    def test_the_time_budget_is_enforced(self):
        ticks = iter([0.0] + [999.0] * 10)
        with self.assertRaises(vr.ModelFetchError) as cm:
            self.fetch(Opener(lambda: Resp(self.data)), clock=lambda: next(ticks), deadline_seconds=1)
        self.assertEqual(cm.exception.code, "deadline")

    def test_no_url_or_a_bad_url_is_refused_and_the_url_is_never_in_an_error(self):
        with self.assertRaises(vr.ModelFetchError) as cm:
            vr.fetch_model_to_memory(None, sha256=self.sha, size=self.size)
        self.assertEqual(cm.exception.code, "model_missing")
        for bad in ("http://models.example/m", "https://user:pw@models.example/m"):
            with self.assertRaises(vr.ModelFetchError) as cm:
                vr.fetch_model_to_memory(bad, sha256=self.sha, size=self.size, opener=Opener(Resp(self.data)))
            self.assertEqual(cm.exception.code, "bad_url")
            self.assertNotIn("pw", str(cm.exception))
        with self.assertRaises(vr.ModelFetchError) as cm:
            self.fetch(Opener(lambda: Resp(self.data[:-1])))
        self.assertNotIn("PRESIGNED-SECRET", str(cm.exception))

    def test_a_rejected_buffer_is_released(self):
        made = []
        real = vr._new_buffer

        def spy(size):
            b = real(size)
            made.append(b)
            return b
        vr._new_buffer = spy
        self.addCleanup(setattr, vr, "_new_buffer", real)
        with self.assertRaises(vr.ModelFetchError):
            self.fetch(Opener(lambda: Resp(self.data[:-3])))
        self.assertTrue(made)
        for b in made:
            self.assertTrue(b.closed)

    def test_no_model_file_and_no_lock_file_is_written_anywhere(self):
        with tempfile.TemporaryDirectory() as scratch:
            old_tmp, old_cwd = tempfile.tempdir, os.getcwd()
            tempfile.tempdir = scratch
            os.chdir(scratch)
            try:
                buf, _ = self.fetch(Opener(lambda: Resp(self.data)))
                buf.close()
                with self.assertRaises(vr.ModelFetchError):
                    self.fetch(Opener(lambda: Resp(self.data[:-1])))
                self.assertEqual(list(Path(scratch).rglob("*")), [])
            finally:
                tempfile.tempdir = old_tmp
                os.chdir(old_cwd)
        self.assertEqual(vr.work_root(), Path(tempfile.gettempdir()) / "kyr")


# ------------------------------------------------------------------------------------------------------------ the engine
class BufferEngineTests(Base):
    def engines(self):
        f = nl.NomicEngine(self.model, self.sha, spec=gf.TINY)
        m = nl.NomicEngine(None, self.sha, spec=gf.TINY, buffer=self.buffer_of(self.data))
        return f, m

    def test_buffer_backed_embeddings_are_bit_identical_to_file_backed_ones(self):
        f, m = self.engines()
        docs = ["search_document: " + t for t in ep.PROBE_TEXTS]
        queries = ["search_query: what is the penalty for a missing licence", "search_query: x"]
        for texts in (docs, queries, docs + queries):
            a, b = f.embed(texts), m.embed(texts)
            self.assertEqual(a.dtype, b.dtype)
            self.assertTrue(np.array_equal(a, b))                     # not close: identical bits

    def test_the_dimension_is_the_models_and_vectors_have_unit_length(self):
        _, m = self.engines()
        v = m.embed(["search_query: hello"])
        self.assertEqual(m.dimensions, gf.TINY.width)
        self.assertEqual(v.shape, (1, gf.TINY.width))
        self.assertAlmostEqual(float(np.linalg.norm(v[0])), 1.0, places=5)
        self.assertTrue(m.sha256_verified)

    def test_the_task_prefixes_are_still_required_and_still_applied_by_the_callers(self):
        _, m = self.engines()
        with self.assertRaises(nl.ModelError):
            m.embed(["no prefix"])
        self.assertNotEqual(m.embed(["search_query: hello"]).tolist(), m.embed(["search_document: hello"]).tolist())
        self.assertIn("search_query: ", nl.TASK_PREFIXES)
        self.assertIn("search_document: ", nl.TASK_PREFIXES)

    def test_the_pin_is_checked_before_parsing_and_a_wrong_pin_is_refused(self):
        with self.assertRaises(nl.ModelError) as cm:
            nl.NomicEngine(None, self.other_sha, spec=gf.TINY, buffer=self.buffer_of(self.data))
        self.assertIn("pinned SHA-256", str(cm.exception))
        nl.NomicEngine(None, self.sha, spec=gf.TINY, buffer=self.buffer_of(self.data))      # the right pin loads

    def test_a_buffer_and_a_path_together_are_refused(self):
        with self.assertRaises(nl.ModelError):
            nl.NomicEngine(self.model, self.sha, spec=gf.TINY, buffer=self.buffer_of(self.data))

    def test_malformed_buffers_are_rejected(self):
        cases = {"garbage": os.urandom(4096), "empty": b"\0", "bad magic": b"XXXX" + self.data[4:], "truncated header": self.data[:30],
                 "truncated tensors": self.data[:len(self.data) // 2], "wrong version": self.data[:4] + (99).to_bytes(4, "little") + self.data[8:]}
        for name, blob in cases.items():
            with self.assertRaises(nl.ModelError, msg=name):
                nl.NomicEngine(None, hashlib.sha256(blob).hexdigest(), spec=gf.TINY, buffer=self.buffer_of(blob))   # the pin matches: parsing must refuse

    def test_a_valid_gguf_of_another_identity_is_refused(self):
        with self.assertRaises(nl.ModelError):
            nl.NomicEngine(None, self.sha, buffer=self.buffer_of(self.data))      # the real 768-wide spec does not fit the tiny model

    def test_the_caller_owned_buffer_is_not_closed_by_the_parser(self):
        buf = self.buffer_of(self.data)
        g = nl.Gguf(buf)
        g.close()
        self.assertFalse(buf.closed)
        buf.close()

    def test_the_engine_keeps_the_buffer_alive_across_repeated_calls_and_garbage_collection(self):
        buf = self.buffer_of(self.data)
        m = nl.NomicEngine(None, self.sha, spec=gf.TINY, buffer=buf)
        expected = m.embed(["search_query: stable"]).copy()
        del buf
        for _ in range(3):
            gc.collect()
            self.assertTrue(np.array_equal(m.embed(["search_query: stable"]), expected))
        self.assertIsNotNone(m._buffer)
        self.assertFalse(m._buffer.closed)


# ------------------------------------------------------------------------------------------------------------ the provider
def tiny_memory_factory(path, sha, buffer=None):
    return nl.NomicEngine(path, sha, spec=gf.TINY, buffer=buffer)


class ProviderTests(Base):
    def env(self, **kw):
        e = {"EMBEDDING_PROVIDER": "inprocess_nomic", "EMBEDDING_MODEL_SOURCE": "memory", "EMBEDDING_MODEL_SHA256": self.sha, "TG_CLOUD": "1"}
        e.update(kw)
        return {k: v for k, v in e.items() if v is not None}

    def probes(self, data=None, sha=None):
        eng = nl.NomicEngine(None, sha or self.sha, spec=gf.TINY, buffer=self.buffer_of(data or self.data))
        texts = ["search_document: " + t for t in ep.PROBE_TEXTS]
        return [{"input": t, "vector": [float(x) for x in v]} for t, v in zip(texts, eng.embed(texts))]

    def guard(self, env=None):
        return ep.build_embeddings(ep.EmbeddingSettings.from_env(env or self.env()), engine_factory=tiny_memory_factory)

    def test_the_memory_configuration_is_valid_without_a_model_file(self):
        s = ep.EmbeddingSettings.from_env(self.env())
        self.assertEqual((s.problems, s.model_source, s.model_file), ((), "memory", ""))
        self.assertTrue(s.verification_required)
        self.assertEqual(s.describe().get("model_source"), "memory")

    def test_the_file_configuration_is_unchanged_for_development(self):
        s = ep.EmbeddingSettings.from_env({"EMBEDDING_PROVIDER": "inprocess_nomic", "EMBEDDING_MODEL_FILE": str(self.model),
                                           "EMBEDDING_MODEL_SHA256": self.sha})
        self.assertEqual((s.problems, s.model_source, s.model_file), ((), "file", str(self.model)))
        self.assertNotIn("model_source", s.describe())
        self.assertTrue(any("EMBEDDING_MODEL_FILE is required" in p for p in ep.EmbeddingSettings.from_env(
            {"EMBEDDING_PROVIDER": "inprocess_nomic", "EMBEDDING_MODEL_SHA256": self.sha}).problems))

    def test_unsafe_memory_configurations_are_refused(self):
        cases = {"a file as well": self.env(EMBEDDING_MODEL_FILE=str(self.model)), "no pin": self.env(EMBEDDING_MODEL_SHA256=None),
                 "wrong provider": self.env(EMBEDDING_PROVIDER="ollama"), "unknown source": self.env(EMBEDDING_MODEL_SOURCE="cloud")}
        for name, env in cases.items():
            s = ep.EmbeddingSettings.from_env(env)
            self.assertTrue(s.problems, name)
            self.assertEqual(ep.build_embeddings(s).state, "misconfigured", name)

    def test_a_missing_buffer_leaves_the_provider_misconfigured_and_refusing(self):
        g = self.guard()                                              # nothing was loaded into memory
        self.assertEqual(g.state, "misconfigured")
        self.assertTrue(any("not loaded into memory" in p for p in g.health()["problems"]))
        with self.assertRaises(ep.EmbeddingUnavailable):
            g.embed_query("search_query: x")

    def test_a_buffer_that_is_not_the_pinned_model_is_refused(self):
        nl.set_memory_model(self.buffer_of(self.other_data))
        g = self.guard()                                              # pinned: self.sha; held: another model
        self.assertEqual(g.state, "misconfigured")
        self.assertTrue(any("pinned SHA-256" in p for p in g.health()["problems"]))

    def test_the_probe_check_passes_for_the_pinned_model_and_decides_readiness(self):
        nl.set_memory_model(self.buffer_of(self.data))
        g = self.guard()
        g.configure_index(dims=gf.TINY.width, family=ep.INDEX_FAMILY, probes=self.probes(), min_cosine=0.995)
        self.assertEqual(g.state, "unverified")
        g.verify()
        self.assertEqual(g.state, "ok")
        self.assertGreater(g._verify_report["min_cosine_observed"], 0.99999)
        self.assertTrue(g.embed_query("search_query: hello"))

    def test_probes_from_a_different_model_make_it_incompatible_not_ready(self):
        nl.set_memory_model(self.buffer_of(self.data))
        g = self.guard()
        g.configure_index(dims=gf.TINY.width, family=ep.INDEX_FAMILY, probes=self.probes(self.other_data, self.other_sha), min_cosine=0.995)
        with self.assertRaises(ep.EmbeddingIncompatible):
            g.verify()
        self.assertEqual(g.state, "incompatible")
        with self.assertRaises(ep.EmbeddingIncompatible):
            g.embed_query("search_query: x")

    def test_without_probes_the_memory_model_is_not_ready(self):
        nl.set_memory_model(self.buffer_of(self.data))
        g = self.guard()
        g.configure_index(dims=gf.TINY.width, family=ep.INDEX_FAMILY, probes=[], min_cosine=0.995)
        with self.assertRaises(ep.EmbeddingUnavailable):
            g.embed_query("search_query: x")
        self.assertNotEqual(g.state, "ok")

    def test_the_embedded_vectors_equal_those_of_the_file_provider(self):
        nl.set_memory_model(self.buffer_of(self.data))
        mem = self.guard()
        fil = ep.build_embeddings(ep.EmbeddingSettings.from_env({"EMBEDDING_PROVIDER": "inprocess_nomic", "EMBEDDING_MODEL_FILE": str(self.model),
                                                                 "EMBEDDING_MODEL_SHA256": self.sha}),
                                  engine_factory=lambda p, s: nl.NomicEngine(p, s, spec=gf.TINY))
        for g in (mem, fil):
            g.configure_index(dims=gf.TINY.width, family=ep.INDEX_FAMILY, probes=self.probes(), min_cosine=0.995)
            g.verify()
        texts = ["search_document: " + t for t in ep.PROBE_TEXTS] + ["search_document: another chunk"]
        self.assertEqual(mem.embed_documents(texts), fil.embed_documents(texts))
        self.assertEqual(mem.embed_query("search_query: hello"), fil.embed_query("search_query: hello"))


# ------------------------------------------------------------------------------------------------------------ the runtime
class RuntimeTests(Base):
    def env(self, tmp, **change):
        env = {"TG_ENVIRONMENT": "production", "TG_CLIENT_IP_SOURCE": "vercel", "TG_SNAPSHOT_PIN_SHA256": PIN, "VERCEL": "1",
               "TG_CORS_ORIGINS": "https://someone.github.io", "KYR_MODEL_URL": "https://models.example/nomic.gguf"}
        env.update(change)
        vr.apply_defaults(env, pid=1, tmp_root=Path(tmp) / "kyr")
        return {k: v for k, v in env.items() if v is not None}

    def test_the_defaults_select_memory_and_set_no_model_file(self):
        with tempfile.TemporaryDirectory() as d:
            env = self.env(d)
            self.assertEqual(env["EMBEDDING_MODEL_SOURCE"], "memory")
            self.assertNotIn("EMBEDDING_MODEL_FILE", env)
            self.assertEqual(vr.validate(env, tmp_root=Path(d), project_root=ROOT), [])

    def test_validation_refuses_a_model_file_or_another_source_on_vercel(self):
        with tempfile.TemporaryDirectory() as d:
            for change in ({"EMBEDDING_MODEL_FILE": str(Path(d) / "m.gguf")}, {"EMBEDDING_MODEL_SOURCE": "file"}, {"EMBEDDING_MODEL_SOURCE": ""}):
                env = self.env(d)
                env.update(change)
                env = {k: v for k, v in env.items() if v != ""}
                self.assertTrue(vr.validate(env, tmp_root=Path(d), project_root=ROOT), change)

    def test_prepare_holds_the_verified_model_in_memory_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            env = self.env(d)
            before = sorted(p for p in Path(d).rglob("*"))
            out = vr.prepare(env, opener=Opener(lambda: Resp(self.data)), tmp_root=Path(d) / "kyr", project_root=ROOT,
                             sha256=self.sha, size=self.size)
            self.assertTrue(out["model"]["in_memory"])
            held = nl.get_memory_model()
            self.assertEqual(bytes(held[:]), self.data)
            self.assertEqual(sorted(p for p in Path(d).rglob("*")), before)
            held.close()

    def test_prepare_with_a_bad_download_leaves_no_model_behind(self):
        with tempfile.TemporaryDirectory() as d:
            env = self.env(d)
            with self.assertRaises(vr.ModelFetchError):
                vr.prepare(env, opener=Opener(lambda: Resp(self.data[:-1])), tmp_root=Path(d) / "kyr", project_root=ROOT,
                           sha256=self.sha, size=self.size)
            self.assertIsNone(nl.get_memory_model())
            self.assertEqual(list(Path(d).rglob("*")), [])

    def test_the_old_file_download_is_still_present_for_a_one_function_rollback(self):
        self.assertTrue(callable(vr.ensure_model))


# ------------------------------------------------------------------------------------------------------------ the real model (optional)
def ollama_blob():
    root = Path.home() / ".ollama" / "models"
    try:
        man = json.loads((root / "manifests/registry.ollama.ai/library/nomic-embed-text/latest").read_text())
        layer = next(l for l in man["layers"] if l["mediaType"].endswith("image.model"))
        blob = root / "blobs" / layer["digest"].replace(":", "-")
        return blob if blob.is_file() and blob.stat().st_size == 274290656 else None
    except Exception:  # noqa: BLE001
        return None


@unittest.skipUnless(ollama_blob(), "the real model is not on this machine (local Ollama blob)")
class RealModelTests(unittest.TestCase):
    def test_the_real_model_from_memory_is_bit_identical_to_the_file_and_768_wide(self):
        blob = ollama_blob()
        fe = nl.NomicEngine(blob, nl.KNOWN_MODEL_SHA256)
        buf = mmap.mmap(-1, blob.stat().st_size)
        with open(blob, "rb") as f:
            while True:
                block = f.read(1 << 20)
                if not block:
                    break
                buf.write(block)
        buf.seek(0)
        me = nl.NomicEngine(None, nl.KNOWN_MODEL_SHA256, buffer=buf)
        texts = ["search_document: " + t for t in ep.PROBE_TEXTS] + ["search_query: What is the penalty for driving without a helmet?"]
        a, b = fe.embed(texts), me.embed(texts)
        self.assertEqual(b.shape, (4, 768))
        self.assertTrue(np.array_equal(a, b))
        with self.assertRaises(nl.ModelError):
            me.embed(["unprefixed"])


if __name__ == "__main__":
    unittest.main()
