"""Stage 7A: the cloud configuration against the REAL index, the REAL lifecycle registry and real Ollama vectors, everything on
temporary COPIES (digests of the real index and registry are checked before and after).

  - The "hosted embedding provider" is a LOCAL FAKE of an OpenAI-compatible API that relays real Ollama vectors and can be told to
    fail in many ways. It proves the plumbing, the verification and the failure behaviour. It does NOT prove a real provider's
    numerics: that is the operator preflight (`python -m backend.embedding_provider preflight`). No external host is contacted.
  - The "R2" is a local HTTP server that serves a snapshot directory path-style and checks for a SigV4 Authorization header.
  - A canary socket stands in for the local Ollama of the server process: hosted mode must never touch it.
  - No generation provider is called. No approval record, key or signature is created for the real corpus; the 2-of-20 partial
    registry is a throwaway-key fixture on a COPY.

Run: RAG_VECTOR_SEARCH=exact|hnsw KYR_REAL_INDEX_DIR=<index> KYR_REQUIRE_REAL_BACKEND=1 python3 -m unittest discover -s tests -p test_cloud_embedding_real.py"""
import hashlib
import json
import os
import random
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import chromadb
import requests
from lifecycle_fixtures import BASIS, status_file_for
from test_view_source_real import INDEX_DIR, REQUIRED, missing  # noqa: E402

from backend import document_lifecycle as dl
from backend import index_snapshot as snap
from backend.embedding_provider import INDEX_FAMILY

ROOT = Path(__file__).resolve().parent.parent
REAL_REGISTRY = ROOT / "legal" / "lifecycle"
APPROVED_IDS = ("tmvr-1989-chap-2", "tmvr-1989-chap-8")
API_KEY = "kyr-test-key-0123456789abcdef"      # a made-up value: the fake accepts exactly this one
HOSTED_MODEL = "nomic-ai/nomic-embed-text-v1.5"
OLLAMA = os.environ.get("OLLAMA_HOST_FOR_FAKE", "http://127.0.0.1:11434")
MODE = os.environ.get("RAG_VECTOR_SEARCH", "exact")


def release_chroma():
    """Collect garbage so this module's Chroma clients are released before its temp directories are deleted. (Clearing Chroma's
    global client cache was tried and breaks other tests' clients in the same process, so it is deliberately not done.)"""
    import gc
    gc.collect()


def local_embed(texts):
    """What built the index: Ollama nomic-embed-text, vectors as the server's own /api/embed returns them."""
    r = requests.post(OLLAMA + "/api/embed", json={"model": "nomic-embed-text", "input": list(texts)}, timeout=120)
    r.raise_for_status()
    return r.json()["embeddings"]


class FakeHosted:
    """An OpenAI-compatible /v1/embeddings that relays real Ollama vectors; fault modes are switched through POST /_mode."""

    def __init__(self):
        self.mode, self.inputs, self.requests, self.bad_auth, self.atlas_seen = "ok", [], 0, 0, []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="application/json", extra=None):
                raw = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(raw)))
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(n) or b"{}")
                if self.path == "/_mode":
                    outer.mode = data["mode"]
                    return self._send(200, {"mode": outer.mode})
                if self.headers.get("Authorization") != f"Bearer {API_KEY}":
                    outer.bad_auth += 1
                    return self._send(401, {"error": "bad key"})
                outer.requests += 1
                outer.inputs += list(data.get("input") or [])
                m = outer.mode
                if m == "http401":
                    return self._send(401, {"error": "invalid key"})
                if m == "http429":
                    return self._send(429, {"error": "rate limited"}, extra={"Retry-After": "0"})
                if m == "http500":
                    return self._send(500, {"error": "boom"})
                if m == "timeout":
                    import time
                    time.sleep(3.5)
                    return self._send(200, {"data": []})
                if m == "bad_json":
                    return self._send(200, b"<html>not json</html>", "text/html")
                if m == "empty_data":
                    return self._send(200, {"data": []})
                if self.path.endswith("/v1/embedding/text"):
                    # Stage 7B: the Nomic-shaped API. It applies the task prefix itself, as the documentation describes; this fake
                    # relays the real Ollama model for the prefixed text, so only the adapter's plumbing is under test.
                    outer.atlas_seen.append((data.get("task_type"), list(data.get("texts") or [])))
                    prefixed = [f"{data['task_type']}: {t}" for t in data["texts"]]
                    return self._send(200, {"embeddings": local_embed(prefixed), "model": data.get("model"),
                                            "usage": {"prompt_tokens": 1, "total_tokens": 1}})
                texts = list(data["input"])
                if m == "other_model":
                    vecs = []
                    for t in texts:
                        rnd = random.Random(hashlib.sha256(t.encode()).hexdigest())
                        v = [rnd.gauss(0, 1) for _ in range(768)]
                        norm = sum(x * x for x in v) ** 0.5
                        vecs.append([x / norm for x in v])
                else:
                    vecs = local_embed(texts)
                    if m == "wrong_dims":
                        vecs = [v[:384] for v in vecs]
                    elif m == "unscaled":
                        vecs = [[x * 2.0 for x in v] for v in vecs]
                rows = [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vecs)]
                self._send(200, {"object": "list", "data": rows, "model": HOSTED_MODEL, "usage": {"prompt_tokens": 1, "total_tokens": 1}})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.port}"

    def set_mode(self, mode):
        requests.post(self.base + "/_mode", json={"mode": mode}, timeout=5).raise_for_status()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class FakeR2:
    """Path-style object GET/HEAD over HTTP from a directory, requiring a SigV4-shaped Authorization header."""

    def __init__(self, root, bucket, key_id):
        self.root, self.bucket, self.key_id = Path(root), bucket, key_id
        self.log, self.denied = [], 0
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _serve(self, head):
                auth = self.headers.get("Authorization", "")
                if not auth.startswith(f"AWS4-HMAC-SHA256 Credential={outer.key_id}/") or "Signature=" not in auth:
                    outer.denied += 1
                    self.send_response(403)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                outer.log.append((self.command, self.path))
                parts = self.path.lstrip("/").split("/", 1)
                f = outer.root / parts[1] if len(parts) == 2 and parts[0] == outer.bucket else None
                if not f or not f.is_file():
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                size = f.stat().st_size
                self.send_response(200)
                self.send_header("Content-Length", str(size))
                self.end_headers()
                if not head:
                    with open(f, "rb") as fh:
                        shutil.copyfileobj(fh, self.wfile)

            def do_GET(self):
                self._serve(False)

            def do_HEAD(self):
                self._serve(True)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class Canary:
    """A listening socket where a local Ollama would be: counts connections (hosted mode must make none)."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.port = self.sock.getsockname()[1]
        self.connections = 0
        self.stop = False
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        self.sock.settimeout(0.2)
        while not self.stop:
            try:
                conn, _ = self.sock.accept()
                self.connections += 1
                conn.close()
            except OSError:
                continue

    def close(self):
        self.stop = True
        self.sock.close()


def run_probe(scenario, extra_env, timeout=1500):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TG_", "GROQ_", "GEMINI_", "PROVIDER_", "RAG_", "EMBEDDING_", "R2_"))}
    env.update(ANONYMIZED_TELEMETRY="False", GROQ_API_KEY="offline-probe-not-real", TG_CACHE="semantic", RAG_VECTOR_SEARCH=MODE,
               APPROVED_IDS=",".join(APPROVED_IDS))
    env.update(extra_env)
    run = subprocess.run([sys.executable, str(ROOT / "tests" / "cloud_embedding_probe.py"), scenario], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=timeout)
    if run.returncode != 0:
        raise AssertionError(f"probe {scenario} ({MODE}) failed:\n" + run.stderr[-3000:])
    parsed = json.loads(run.stdout.strip().splitlines()[-1])
    parsed["_stderr_has_key"] = API_KEY in run.stderr or API_KEY in run.stdout
    return parsed


def embeddings():
    from langchain_ollama import OllamaEmbeddings

    from backend import build_telangana_index as btx
    from backend import rag_profiles as rp
    return rp.ProfileEmbeddings(OllamaEmbeddings(model="nomic-embed-text"), btx.PROFILE)


@unittest.skipUnless(os.environ.get("KYR_REAL_INDEX_DIR") or REQUIRED, "real backend not configured")
class CloudEmbeddingRealTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("KYR_SKIP_CLOUD_REAL"):
            raise unittest.SkipTest("skipped by KYR_SKIP_CLOUD_REAL (diagnostic)")
        reason = missing()
        if reason and REQUIRED:
            raise AssertionError(f"real backend test required but cannot run: {reason}")
        if reason:
            raise unittest.SkipTest(reason)
        if not (REAL_REGISTRY / "registry.json").is_file():
            raise unittest.SkipTest("no real lifecycle registry (legal/lifecycle) in this checkout")
        cls.before = (dl.tree_digest(INDEX_DIR), dl.tree_digest(REAL_REGISTRY))
        cls.tmp = Path(tempfile.mkdtemp(prefix="kyr-7a-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.addClassCleanup(release_chroma)   # runs BEFORE the rmtree above (cleanups are last-in, first-out)
        cls.addClassCleanup(cls.check_untouched)
        cls.fake = FakeHosted()
        cls.addClassCleanup(cls.fake.close)
        cls.canary = Canary()
        cls.addClassCleanup(cls.canary.close)

        # real index + real registry (all quarantined): copies
        cls.q_index, cls.q_state = cls.tmp / "q-index", cls.tmp / "q-state"
        shutil.copytree(INDEX_DIR, cls.q_index)
        shutil.copytree(REAL_REGISTRY, cls.q_state)
        # throwaway-key partial registry (2 of 20 verified, 18 quarantined) on another copy
        cls.p_index = cls.tmp / "p-index"
        shutil.copytree(INDEX_DIR, cls.p_index)
        peek = cls.tmp / "peek"
        shutil.copytree(INDEX_DIR, peek)
        metas = chromadb.PersistentClient(path=str(peek)).get_collection("telangana-traffic-rules", embedding_function=None) \
            .get(include=["metadatas"])["metadatas"]
        only = {m["sha256"] for m in metas if m["manifest_id"] in APPROVED_IDS}
        status = status_file_for(cls.tmp / "p-status", metas, only)
        cls.p_state = cls.tmp / "p-state"
        res = dl.Lifecycle(cls.p_state, cls.p_index, embeddings=embeddings()).bootstrap("cloud-test", BASIS, source_status_file=status,
                                                                                         allow_quarantine=True)
        assert (res["verified"], res["quarantined"]) == (2, 18), res
        release_chroma()

        # publish both into local stores, and the partial one also behind the R2-like HTTP server
        cls.manifests, cls.stores = {}, {}
        for name, (idx, st) in {"q": (cls.q_index, cls.q_state), "p": (cls.p_index, cls.p_state)}.items():
            root = cls.tmp / f"store-{name}"
            store = snap.PrefixedStore(snap.LocalObjectStore(root), "kyr/")
            cls.manifests[name] = snap.publish(store, idx, st, embed=local_embed, embedding_model="nomic-embed-text",
                                               family=INDEX_FAMILY, created_by="stage7a-test", notes="test snapshot of a COPY")
            cls.stores[name] = root
            release_chroma()
        cls.r2 = FakeR2(cls.stores["p"], "kyr-bucket", "AKIAFAKEKEYID000000")
        cls.addClassCleanup(cls.r2.close)
        cls.runs = {}

    @classmethod
    def check_untouched(cls):
        after = (dl.tree_digest(INDEX_DIR), dl.tree_digest(REAL_REGISTRY))
        assert after == cls.before, "the real index or the real registry was modified"

    # ---- environments -------------------------------------------------------------------------------------------
    def hosted_env(self, store="p", work="w", **extra):
        env = {"EMBEDDING_PROVIDER": "openai_compatible", "EMBEDDING_API_URL": self.fake.base + "/v1", "EMBEDDING_API_KEY": API_KEY,
               "EMBEDDING_MODEL": HOSTED_MODEL, "EMBEDDING_TIMEOUT_SECONDS": "6.0", "EMBEDDING_MAX_RETRIES": "0",
               "EMBEDDING_BREAKER_FAILURES": "20", "EMBEDDING_BREAKER_COOLDOWN_SECONDS": "1", "EMBEDDING_REVERIFY_SECONDS": "5", "OLLAMA_HOST": f"127.0.0.1:{self.canary.port}",
               "OLLAMA_ENABLED": "false", "FAKE_CONTROL": self.fake.base, "TG_ENVIRONMENT": "production",
               "TG_SNAPSHOT_STORE": "local", "TG_SNAPSHOT_LOCAL_DIR": str(self.stores[store]), "TG_SNAPSHOT_WORK_DIR": str(self.tmp / f"work-{work}")}
        env.update(extra)
        return env

    def local_env(self, index, state):
        return {"TG_DB_DIR": str(index), "TG_LIFECYCLE_DIR": str(state), "OLLAMA_HOST": OLLAMA.replace("http://", "")}

    @staticmethod
    def parity(hosted, local):
        ident, overlaps, top1, f_ident, n = 0, [], 0, 0, 0
        for cid, h in hosted["unfiltered"].items():
            l = local["unfiltered"][cid]
            n += 1
            ident += h == l
            f_ident += hosted["filtered"][cid] == local["filtered"][cid]
            hk, lk = {json.dumps(x) for x in h}, {json.dumps(x) for x in l}
            overlaps.append(len(hk & lk) / max(len(hk | lk), 1))
            top1 += bool(h and l and h[0] != l[0]) or (bool(h) != bool(l))
        return {"mode": MODE, "questions": n, "unfiltered_identical_fraction": round(ident / n, 4),
                "filtered_identical_fraction": round(f_ident / n, 4),
                "unfiltered_mean_overlap": round(sum(overlaps) / n, 4), "unfiltered_min_overlap": round(min(overlaps), 4),
                "unfiltered_top1_changed": top1}

    @staticmethod
    def refused(step, detail):
        """A safe refusal: HTTP 503 (embedding failed during the request) or the gate's 'unavailable' reply (the embedding
        guard already marks the corpus not ready, so the question is never searched). Never an answer, never a source."""
        if step["status"] == 503:
            return detail is None or step["detail"] == detail
        return step["status"] == 200 and step.get("kind") == "unavailable" and step.get("sources", 0) == 0

    def faults(self):
        return self.cached("faults", lambda: run_probe("faults", self.hosted_env("p", "faults", EMBEDDING_TIMEOUT_SECONDS="2.0")))

    def cached(self, key, fn):
        if key not in self.runs:
            self.fake.set_mode("ok")
            self.runs[key] = fn()
        return self.runs[key]

    # ---- tests ----------------------------------------------------------------------------------------------------
    def test_01_hosted_retrieval_equals_local_ollama_retrieval(self):
        """Same questions, same index: the hosted-provider path (snapshot + fake hosted API) retrieves exactly what local Ollama does."""
        canary_before = self.canary.connections
        hosted = self.cached("hosted_p", lambda: run_probe("retrieval", self.hosted_env("p", "ret")))
        local = self.cached("local_p", lambda: run_probe("retrieval", self.local_env(self.p_index, self.p_state)))
        self.assertEqual(hosted["embedding_provider"], "openai_compatible")
        self.assertEqual(local["embedding_provider"], "ollama")
        self.assertEqual(len(hosted["unfiltered"]), len(local["unfiltered"]))
        self.assertGreaterEqual(len(hosted["unfiltered"]), 100)
        stats = self.parity(hosted, local)
        out = os.environ.get("KYR_7A_PARITY_OUT")
        if out:
            Path(out).write_text(json.dumps(stats, indent=1))
        if MODE == "exact":
            # exact search is deterministic: the same vectors must give the same chunks in the same order
            self.assertEqual(hosted["unfiltered"], local["unfiltered"], "hosted and local retrieval differ")
            self.assertEqual(hosted["filtered"], local["filtered"], "the lifecycle-filtered result differs")
        else:
            # hnsw is approximate: a last-digit difference in the query vector may change which neighbours the graph walk returns.
            # Require near-identity (not equality) of the unfiltered result and that no top result changed.
            self.assertGreaterEqual(stats["unfiltered_identical_fraction"], 0.9, stats)
            self.assertGreaterEqual(stats["unfiltered_mean_overlap"], 0.97, stats)
            self.assertEqual(stats["unfiltered_top1_changed"], 0, stats)
        self.assertEqual(self.canary.connections, canary_before, "hosted mode touched the local Ollama address")
        self.assertEqual(hosted["key_leaks"], 0)
        self.assertFalse(hosted["_stderr_has_key"])
        self.assertEqual(hosted["status"]["embedding"]["state"], "ok")
        self.assertTrue(hosted["status"]["embedding"]["verified"])

    def test_02_only_approved_documents_are_ever_served_from_a_snapshot(self):
        hosted = self.cached("hosted_p", lambda: run_probe("retrieval", self.hosted_env("p", "ret")))
        approved = {m["sha256"] for m in self.read_metas(self.p_index) if m["manifest_id"] in APPROVED_IDS}
        self.assertTrue(hosted["filtered_shas"])
        self.assertLessEqual(set(hosted["filtered_shas"]), approved)
        everything = {k[0] for v in hosted["unfiltered"].values() for k in v}
        self.assertTrue(everything - approved, "the unfiltered control should reach quarantined documents (else the test proves nothing)")
        self.assertEqual(hosted["status"]["snapshot"]["state"], "ready")
        self.assertEqual(hosted["status"]["chunks"], 590)

    def test_03_the_real_registry_snapshot_serves_nothing_and_says_so(self):
        hosted = self.cached("hosted_q", lambda: run_probe("retrieval", self.hosted_env("q", "retq")))
        self.assertEqual(hosted["filtered_shas"], [], "a quarantined corpus must serve no passage")
        self.assertTrue(all(not v for v in hosted["filtered"].values()))
        st = hosted["status"]
        self.assertFalse(st["corpus_ready"])
        self.assertFalse(st["lifecycle_ready"])
        self.assertEqual(hosted["health"], {"status": "ok"})   # /health never implies corpus readiness

    def test_04_no_corpus_text_is_sent_to_the_hosted_provider(self):
        self.cached("hosted_p", lambda: run_probe("retrieval", self.hosted_env("p", "ret")))
        self.assertTrue(self.fake.inputs)
        probes = {p["input"] for p in self.manifests["p"]["embedding"]["probes"]} | {p["input"] for p in self.manifests["q"]["embedding"]["probes"]}
        others = [i for i in self.fake.inputs if i not in probes]
        self.assertTrue(all(i.startswith("search_query: ") for i in others), "only user queries and the manifest's generic probe sentences may be sent")
        chunk_texts = {d.partition("\n")[2] or d for d in self.chunk_texts()}
        sent_chunks = [i for i in self.fake.inputs if any(c and c[:80] in i for c in chunk_texts)]
        self.assertEqual(sent_chunks, [], "corpus text was sent to the provider")
        self.assertEqual(self.fake.bad_auth, 0)

    def test_05_every_provider_failure_is_a_safe_503_with_no_answer_and_no_leak(self):
        r = self.faults()
        self.assertEqual(r["gate_errors"], [], r["gate_errors"])
        self.assertGreaterEqual(r["answerable"], 2, "the stand-in model answered fewer than two questions: the test would prove nothing")
        steps = {s["label"]: s for s in r["steps"]}
        self.assertEqual((steps["healthy"]["status"], steps["healthy"]["kind"]), (200, "answer"), steps["healthy"])
        for label in ("http401", "http429", "http500", "timeout", "bad_json", "empty_data", "wrong_dims", "unscaled"):
            s = steps[label]
            self.assertTrue(self.refused(s, r["error_constant"]), s)
            self.assertEqual(s["generator_calls"], 0, f"{label}: a provider was called without a search")
            self.assertEqual(s["sources"], 0)
            self.assertFalse(s["key_in_response"])
        self.assertEqual(r["key_leaks"], 0)
        self.assertFalse(r["_stderr_has_key"])
        self.assertEqual(r["health_after"], {"status": "ok"})

    def test_06_transient_failures_recover_but_incompatible_vectors_do_not(self):
        r = self.faults()
        steps = {s["label"]: s for s in r["steps"]}
        self.assertEqual((steps["recovered"]["status"], steps["recovered"]["kind"], steps["recovered"]["state"]), (200, "answer", "ok"), steps["recovered"])
        self.assertTrue(steps["recovered"]["corpus_ready"])
        for label in ("http401", "http429", "http500", "timeout", "bad_json", "empty_data"):
            self.assertNotEqual(steps[label]["state"], "incompatible", label)
        # wrong dimensions: refused, and refused for the rest of the process even after the provider behaves again
        self.assertEqual(steps["wrong_dims"]["state"], "incompatible")
        self.assertTrue(self.refused(steps["after_wrong_dims_ok"], r["error_constant"]), steps["after_wrong_dims_ok"])
        self.assertEqual(steps["after_wrong_dims_ok"]["state"], "incompatible")
        self.assertFalse(steps["after_wrong_dims_ok"]["corpus_ready"])

    def test_07_provider_down_at_startup_is_unready_503_then_recovers_without_a_restart(self):
        self.fake.set_mode("http500")
        canary_before = self.canary.connections
        r = run_probe("startup_down", self.hosted_env("p", "down"))
        self.assertFalse(r["status"]["corpus_ready"])
        self.assertNotEqual(r["status"]["embedding"]["state"], "ok")
        self.assertEqual(r["down"]["status"], 503)
        self.assertEqual(r["down"]["generator_calls"], 0)
        self.assertFalse(r["down"]["status_block"]["corpus_ready"])
        self.assertEqual(r["recovered"]["status"], 200, r["recovered"])
        self.assertTrue(r["recovered"]["status_block"]["corpus_ready"])
        self.assertEqual(r["key_leaks"], 0)
        self.assertEqual(self.canary.connections, canary_before, "no Ollama fallback in hosted mode")
        self.fake.set_mode("ok")

    def test_08_a_provider_with_a_different_model_is_refused_for_the_whole_process(self):
        self.fake.set_mode("other_model")
        canary_before = self.canary.connections
        r = run_probe("startup_incompat", self.hosted_env("p", "inc"))
        self.assertEqual(r["status"]["embedding"]["state"], "incompatible")
        self.assertFalse(r["status"]["corpus_ready"])
        for block in (r["incompatible"], r["after_switch"]):
            self.assertTrue(self.refused(block, None), block)
            self.assertEqual(block["generator_calls"], 0)
            self.assertFalse(block["status_block"]["corpus_ready"])
        self.assertEqual(r["after_switch"]["status_block"]["embedding"]["state"], "incompatible")
        self.assertEqual(self.canary.connections, canary_before)
        self.fake.set_mode("ok")

    def test_09_corrupt_missing_and_repaired_snapshots(self):
        store = self.tmp / "store-bad"
        shutil.copytree(self.stores["p"], store)
        self.stores["bad"] = store
        work = "bad"
        env = lambda: self.hosted_env("bad", work)   # noqa: E731
        self.fake.set_mode("ok")
        good = run_probe("status", env())
        self.assertEqual(good["status"]["snapshot"]["state"], "ready")
        self.assertTrue(good["status_gated"]["corpus_ready"], good["status_gated"])
        # 1) a corrupted archive: the server starts, reports not ready, serves nothing, creates no empty index
        archive = next((store / "kyr" / "snapshots").rglob("index.tar.gz"))
        original = archive.read_bytes()
        archive.write_bytes(original[:-64] + b"\x00" * 64)
        shutil.rmtree(self.tmp / f"work-{work}", ignore_errors=True)
        bad = run_probe("status", env())
        self.assertEqual(bad["status"]["snapshot"]["state"], "checksum_mismatch", bad["status"]["snapshot"])
        self.assertFalse(bad["status"]["corpus_ready"])
        self.assertFalse(bad["status_gated"]["corpus_ready"], "even with every other prerequisite satisfied")
        self.assertFalse(bad["index_dir_exists"])
        self.assertEqual(bad["unavailable_dir_entries"], [])
        self.assertTrue(bad["retrieval_empty"])
        self.assertEqual(bad["chat"]["sources"], 0)
        self.assertEqual(bad["chat"]["generator_calls"], 0)
        self.assertTrue(any("snapshot" in e for e in bad["gate_errors"]), bad["gate_errors"])
        self.assertEqual(bad["health"], {"status": "ok"})
        # 2) a missing manifest pointer
        archive.write_bytes(original)
        pointer = store / "kyr" / "active.json"
        saved = pointer.read_bytes()
        pointer.unlink()
        shutil.rmtree(self.tmp / f"work-{work}", ignore_errors=True)
        gone = run_probe("status", env())
        self.assertEqual(gone["status"]["snapshot"]["state"], "manifest_missing")
        self.assertFalse(gone["status_gated"]["corpus_ready"])
        self.assertFalse(gone["index_dir_exists"])
        # 3) the store is repaired: the next start is ready
        pointer.write_bytes(saved)
        fixed = run_probe("status", env())
        self.assertEqual(fixed["status"]["snapshot"]["state"], "ready")
        self.assertTrue(fixed["status_gated"]["corpus_ready"])

    def test_10_the_snapshot_downloads_over_http_from_an_r2_like_store(self):
        env = self.hosted_env("p", "r2", TG_SNAPSHOT_STORE="r2", R2_ENDPOINT=f"http://127.0.0.1:{self.r2.port}", R2_BUCKET="kyr-bucket",
                              R2_ACCESS_KEY_ID="AKIAFAKEKEYID000000", R2_SECRET_ACCESS_KEY="fake-secret-not-real", TG_SNAPSHOT_PREFIX="kyr/")
        env.pop("TG_SNAPSHOT_LOCAL_DIR")
        r = run_probe("retrieval", env)
        self.assertEqual(r["status"]["snapshot"]["state"], "ready")
        self.assertEqual(r["status"]["chunks"], 590)
        self.assertEqual(self.r2.denied, 0)
        methods = {m for m, _ in self.r2.log}
        self.assertIn("GET", methods)
        self.assertTrue(any(p.endswith("index.tar.gz") for _, p in self.r2.log))
        self.assertEqual(r["filtered_shas"], self.cached("hosted_p", lambda: run_probe("retrieval", self.hosted_env("p", "ret")))["filtered_shas"])
        self.assertFalse(r["_stderr_has_key"])

    def test_12_the_nomic_adapter_round_trips_the_task_prefixes_and_retrieves_what_local_ollama_does(self):
        """Stage 7B. The adapter strips 'search_query: ' into task_type and the (fake) service puts it back: retrieval must equal
        local Ollama's, no text may reach the service still carrying a prefix, and local Ollama must not be touched."""
        canary_before = self.canary.connections
        seen_before = len(self.fake.atlas_seen)
        atlas = self.cached("atlas_p", lambda: run_probe("retrieval", self.hosted_env(
            "p", "atlas", EMBEDDING_PROVIDER="nomic_atlas", EMBEDDING_API_URL=self.fake.base, EMBEDDING_MODEL="nomic-embed-text-v1.5")))
        local = self.cached("local_p", lambda: run_probe("retrieval", self.local_env(self.p_index, self.p_state)))
        self.assertEqual(atlas["embedding_provider"], "nomic_atlas")
        stats = self.parity(atlas, local)
        if MODE == "exact":
            self.assertEqual(atlas["unfiltered"], local["unfiltered"])
            self.assertEqual(atlas["filtered"], local["filtered"])
        else:
            self.assertGreaterEqual(stats["unfiltered_identical_fraction"], 0.9, stats)
            self.assertGreaterEqual(stats["unfiltered_mean_overlap"], 0.97, stats)
            self.assertEqual(stats["unfiltered_top1_changed"], 0, stats)
        seen = self.fake.atlas_seen[seen_before:]
        self.assertTrue(seen)
        self.assertEqual({task for task, _ in seen}, {"search_document", "search_query"})   # probes are documents, questions are queries
        for task, texts in seen:
            for t in texts:
                self.assertFalse(t.startswith(("search_query:", "search_document:")), t)
        self.assertEqual(self.canary.connections, canary_before, "the Nomic adapter touched the local Ollama address")
        self.assertEqual((atlas["status"]["embedding"]["state"], atlas["status"]["embedding"]["verified"]), ("ok", True))
        self.assertEqual(atlas["key_leaks"], 0)

    def test_11_the_published_manifest_describes_the_real_index(self):
        for name in ("q", "p"):
            m = self.manifests[name]
            self.assertEqual((m["index"]["chunk_count"], m["embedding"]["dimensions"]), (590, 768))
            self.assertEqual(m["embedding"]["family"], "nomic-embed-text-v1.5")
            self.assertGreaterEqual(len(m["embedding"]["probes"]), 3)
        self.assertEqual(self.manifests["q"]["index"]["sha256"], self.manifests["p"]["index"]["sha256"],
                         "the index archive is the same for both registries (only the registry differs)")

    @classmethod
    def chunk_texts(cls):
        peek = cls.tmp / "peek3"
        if not peek.exists():
            shutil.copytree(INDEX_DIR, peek)
        return chromadb.PersistentClient(path=str(peek)).get_collection("telangana-traffic-rules", embedding_function=None) \
            .get(include=["documents"])["documents"]

    @classmethod
    def read_metas(cls, index):
        peek = cls.tmp / "peek2"
        if not peek.exists():
            shutil.copytree(index, peek)
        return chromadb.PersistentClient(path=str(peek)).get_collection("telangana-traffic-rules", embedding_function=None) \
            .get(include=["metadatas"])["metadatas"]


if __name__ == "__main__":
    unittest.main()
