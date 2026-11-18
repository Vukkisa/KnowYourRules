"""Stage 7A: the application with cloud configuration. Offline: the fake-backed server of tests/test_server.py (no Chroma, no Ollama,
no model), mocked embedding HTTP, local-directory snapshots. Nothing contacts a service."""
import json
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from unittest import mock

import yaml
from fastapi.testclient import TestClient

import test_index_snapshot as tis
import test_server as ts
from backend import embedding_provider as ep
from backend import index_snapshot as snap

ROOT = Path(__file__).resolve().parent.parent
KEY = "sk-test-server-0123456789-MUST-NOT-APPEAR"
HOSTED = {"EMBEDDING_PROVIDER": "openai_compatible", "EMBEDDING_API_URL": "https://embeddings.example/v1", "EMBEDDING_API_KEY": KEY,
          "EMBEDDING_MODEL": "nomic-ai/nomic-embed-text-v1.5", "EMBEDDING_VERIFY": "off"}
Q = "How do I apply for a learner's licence?"


class Failing:
    def __init__(self, *items):
        self.items, self.calls = list(items), 0

    def __call__(self, url, headers=None, json=None, timeout=None):
        self.calls += 1
        item = self.items[min(self.calls, len(self.items)) - 1]
        if isinstance(item, Exception):
            raise item
        return item


class ServerCase(unittest.TestCase):
    def server(self, **env):
        srv = ts._import_server_with_fakes(env)
        ts.FAKE_LLM["fn"] = ts.fake_llm()
        ts.FAKE_SEARCH["fn"] = None
        self.addCleanup(ts.FAKE_SEARCH.update, {"fn": None})
        return srv, TestClient(srv.app, raise_server_exceptions=False)


class EmbeddingServerTests(ServerCase):
    def test_default_configuration_is_unchanged_local_ollama(self):
        srv, client = self.server()
        self.assertEqual((srv.EMBEDDING.provider, srv.EMBEDDING.model), ("ollama", "nomic-embed-text"))
        self.assertIs(srv.embeddings_model.base, srv.EMBEDDING)
        e = client.get("/status").json()["embedding"]
        self.assertEqual((e["provider"], e["state"], e["hosted"]), ("ollama", "ok", False))

    def test_status_reports_the_embedding_provider_without_secrets(self):
        srv, client = self.server(**HOSTED)
        text = client.get("/status").text
        self.assertNotIn(KEY, text)
        self.assertNotIn("/v1", text)
        e = json.loads(text)["embedding"]
        self.assertEqual((e["provider"], e["endpoint_host"], e["api_key_set"]), ("openai_compatible", "embeddings.example", True))

    def test_health_never_implies_corpus_readiness(self):
        for env in ({}, HOSTED, {"EMBEDDING_PROVIDER": "openai_compatible"}):
            srv, client = self.server(**env)
            self.assertEqual(client.get("/health").json(), {"status": "ok"})
            self.assertNotIn("corpus_ready", client.get("/health").json())      # liveness says nothing about the corpus

    def test_corpus_ready_needs_every_component(self):
        srv, client = self.server()
        self.assertTrue(srv.corpus_ready())      # no signed approval is part of readiness
        with mock.patch.dict(srv.INDEX_INFO, {"index": "missing"}):
            self.assertFalse(srv.corpus_ready())
        with mock.patch.object(srv.EMBEDDING, "_incompatible", "wrong model"):
            self.assertFalse(srv.corpus_ready())
        with mock.patch.object(srv, "SNAPSHOT", snap.SnapshotStatus(state="checksum_mismatch")):
            self.assertFalse(srv.corpus_ready())
        with mock.patch.object(srv, "LIFECYCLE", mock.Mock(ready=lambda: False)):
            self.assertFalse(srv.corpus_ready())

    def test_hosted_provider_that_is_not_verified_is_not_ready_and_a_misconfigured_one_blocks_grounded_answers(self):
        srv, client = self.server(**{**HOSTED, "EMBEDDING_VERIFY": "auto"})
        self.assertEqual(client.get("/status").json()["embedding"]["state"], "unverified")
        srv, client = self.server(EMBEDDING_PROVIDER="openai_compatible")
        e = client.get("/status").json()["embedding"]
        self.assertEqual(e["state"], "misconfigured")
        self.assertTrue(any("EMBEDDING_API_KEY" in p for p in e["problems"]))
        self.assertIn("query embedding provider is misconfigured or incompatible with the index", srv.grounded_gate_errors())

    def test_embedding_failure_is_a_safe_503_that_was_neither_searched_nor_answered(self):
        for failure in (ep.requests.Timeout(KEY), Failing(ep.requests.ConnectionError(KEY))):
            srv, client = self.server(**HOSTED)
            http = failure if callable(failure) else Failing(failure)
            srv.EMBEDDING.backend.http = http
            srv.EMBEDDING.sleep = None
            srv.EMBEDDING.backend.sleep = lambda s: None
            ts.FAKE_SEARCH["fn"] = lambda q, state, docs: (srv.embeddings_model.embed_query(q), [(d, 0.3) for d in docs])[1]
            log = {}
            ts.FAKE_LLM["fn"] = ts.fake_llm(log=log)
            r = client.post("/chat", json={"message": Q, "session_id": "s"})
            self.assertEqual(r.status_code, 503)
            self.assertEqual(r.json()["detail"], srv.EMBEDDING_ERROR)
            self.assertNotIn(KEY, r.text)
            self.assertNotIn("answer", log)                         # no model was asked, nothing was made up
            self.assertGreaterEqual(http.calls, 1)

    def test_incompatible_provider_stops_retrieval_for_good(self):
        srv, client = self.server(**HOSTED)
        bad = ep.GuardedEmbeddings  # noqa: F841
        srv.EMBEDDING.backend.http = Failing(ts.Document and type("R", (), {"status_code": 200, "headers": {}, "json": lambda self: {"data": [{"embedding": [0.6, 0.8]}]}})())
        srv.EMBEDDING.configure_index(dims=8)
        ts.FAKE_SEARCH["fn"] = lambda q, state, docs: (srv.embeddings_model.embed_query(q), [(d, 0.3) for d in docs])[1]
        r = client.post("/chat", json={"message": Q, "session_id": "s"})
        self.assertEqual((r.status_code, r.json()["detail"]), (503, srv.EMBEDDING_ERROR))
        self.assertEqual(client.get("/status").json()["embedding"]["state"], "incompatible")

    def test_cache_epoch_changes_with_the_embedding_provider(self):
        a, _ = self.server()
        b, _ = self.server(**HOSTED)
        self.assertNotEqual(a.cache_epoch(), b.cache_epoch())

    def test_hosted_mode_builds_no_ollama_client(self):
        srv, _ = self.server(**HOSTED)
        self.assertEqual(type(srv.EMBEDDING.backend).__name__, "HostedBackend")


class CorsAndAdminTests(ServerCase):
    ORIGIN = "https://someone.github.io"

    def preflight(self, client, origin):
        return client.options("/chat", headers={"Origin": origin, "Access-Control-Request-Method": "POST",
                                                "Access-Control-Request-Headers": "content-type"})

    def test_off_by_default(self):
        _, client = self.server()
        r = self.preflight(client, self.ORIGIN)
        self.assertNotIn("access-control-allow-origin", r.headers)

    def test_only_listed_origins_get_headers_and_never_credentials_or_wildcards(self):
        _, client = self.server(TG_CORS_ORIGINS=f"{self.ORIGIN}, *, http://evil.example")
        r = self.preflight(client, self.ORIGIN)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["access-control-allow-origin"], self.ORIGIN)
        self.assertNotIn("access-control-allow-credentials", r.headers)
        self.assertEqual(sorted(x.strip() for x in r.headers["access-control-allow-methods"].split(",")), ["GET", "POST"])
        for other in ("https://evil.example", "http://evil.example", "https://someone.github.io.evil.example"):
            self.assertNotIn("access-control-allow-origin", self.preflight(client, other).headers, other)
        actual = client.get("/status", headers={"Origin": self.ORIGIN})
        self.assertEqual(actual.headers["access-control-allow-origin"], self.ORIGIN)

    def test_approval_refresh_is_not_a_public_endpoint_outside_development(self):
        for env in ("production", "staging"):
            srv, client = self.server(TG_ENVIRONMENT=env, TG_LEGACY_DEV_ANSWERS="", TG_GROUNDED_ANSWERS="")
            self.assertEqual(client.post("/approval/refresh").status_code, 404, env)
        srv, client = self.server(TG_ENVIRONMENT="production", TG_ENABLE_APPROVAL_REFRESH="1", TG_LEGACY_DEV_ANSWERS="")
        self.assertEqual(client.post("/approval/refresh").status_code, 200)
        srv, client = self.server()
        self.assertEqual(client.post("/approval/refresh").status_code, 200)

    def test_no_lifecycle_administration_route_exists(self):
        srv, _ = self.server()
        paths = {getattr(r, "path", "") for r in srv.app.routes}
        self.assertEqual(paths - {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"},
                         {"/", "/health", "/ready", "/status", "/chat", "/approval/refresh", "/static",
                          "/release-gates"})  # reviewed: read-only diagnostics, not wired to /chat


class SnapshotServerTests(ServerCase, tis.Fixture):
    """Fixture (tiny index + registry) + the fake-backed server importing with a snapshot store."""

    def snapshot_env(self, **extra):
        return {"TG_SNAPSHOT_STORE": "local", "TG_SNAPSHOT_LOCAL_DIR": str(self.tmp / "store"), "TG_SNAPSHOT_PREFIX": "",
                "TG_SNAPSHOT_WORK_DIR": str(self.tmp / "srvwork"), "TG_DB_DIR": None, "TG_LIFECYCLE_DIR": None, **extra}

    def test_missing_snapshot_serves_nothing_and_creates_nothing(self):
        srv, client = self.server(**self.snapshot_env())
        self.assertEqual((srv.SNAPSHOT.state, srv.SNAPSHOT.ready), ("manifest_missing", False))
        self.assertIsNone(srv.vector_store)
        self.assertEqual(srv.INDEX_INFO["index"], "missing")
        self.assertTrue(srv.LIFECYCLE.enabled and not srv.LIFECYCLE.ready())
        s = client.get("/status").json()
        self.assertEqual((s["snapshot"]["state"], s["corpus_ready"], s["lifecycle"]["corpus_ready"]), ("manifest_missing", False, False))
        self.assertEqual(client.get("/health").json(), {"status": "ok"})
        r = client.post("/chat", json={"message": Q, "session_id": "s"})
        self.assertEqual(r.json()["kind"], "unavailable")
        self.assertFalse(srv._UNAVAILABLE_DIR.exists())
        self.assertIn("index snapshot is not loaded and verified", srv.grounded_gate_errors())

    def test_corrupt_snapshot_is_reported_and_serves_nothing(self):
        m = self.publish()
        (self.tmp / "store" / m["lifecycle"]["archive"]).write_bytes(b"corrupt")
        srv, client = self.server(**self.snapshot_env())
        s = client.get("/status").json()
        self.assertEqual((s["snapshot"]["state"], s["snapshot"]["ready"], s["corpus_ready"]), ("checksum_mismatch", False, False))
        self.assertIsNone(srv.vector_store)

    def test_verified_snapshot_supplies_the_index_and_the_lifecycle_registry(self):
        m = self.publish()
        srv, client = self.server(**self.snapshot_env())
        self.assertTrue(srv.SNAPSHOT.ready)
        self.assertEqual(srv.TG_DB_DIR, srv.SNAPSHOT.db_dir)
        self.assertEqual(srv.LIFECYCLE.path.parent, srv.SNAPSHOT.lifecycle_dir)
        s = client.get("/status").json()
        self.assertEqual((s["snapshot"]["state"], s["snapshot"]["version"], s["snapshot"]["chunks"]), ("ready", m["version"], 3))
        self.assertEqual(srv.EMBEDDING.expected_dims, 8)
        self.assertEqual(len(srv.EMBEDDING.probes), 3)

    def test_explicit_directories_are_refused_in_snapshot_mode(self):
        self.publish()
        srv, _ = self.server(**self.snapshot_env(TG_DB_DIR=str(self.db)))
        self.assertEqual(srv.SNAPSHOT.state, "misconfigured")
        self.assertIsNone(srv.vector_store)


class DeploymentConfigTests(unittest.TestCase):
    SECRETS = {"GROQ_API_KEY", "GEMINI_API_KEY", "EMBEDDING_API_KEY", "R2_ACCOUNT_ID", "R2_BUCKET", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
               "TG_SNAPSHOT_PIN_SHA256", "TG_CORS_ORIGINS"}

    @classmethod
    def setUpClass(cls):
        cls.blueprint = yaml.safe_load((ROOT / "deploy" / "render.yaml").read_text("utf-8"))
        cls.svc = cls.blueprint["services"][0]
        cls.env = {e["key"]: e for e in cls.svc["envVars"]}

    def test_render_service_shape(self):
        s = self.svc
        self.assertEqual((s["type"], s["runtime"], s["plan"], s["healthCheckPath"], s["autoDeployTrigger"]), ("web", "python", "free", "/ready", "off"))
        self.assertIn("backend.server:app", s["startCommand"])
        self.assertIn("--workers 1", s["startCommand"])
        self.assertIn("$PORT", s["startCommand"])
        self.assertIn("requirements-cloud.txt", s["buildCommand"])
        self.assertNotIn("--reload", s["startCommand"])

    def test_secrets_are_never_given_a_value_in_the_blueprint(self):
        for key in self.SECRETS:
            self.assertIn(key, self.env, key)
            self.assertEqual(self.env[key], {"key": key, "sync": False}, key)

    def test_cloud_provider_chain_and_embedding_settings(self):
        v = lambda k: self.env[k].get("value")   # noqa: E731
        self.assertEqual((v("TG_ENVIRONMENT"), v("TG_GROUNDED_ANSWERS"), v("OLLAMA_ENABLED")), ("production", "1", "false"))
        # Stage 7B: no embedding provider is approved, so none has a default in the blueprint (and none is a paid host)
        for key in ("EMBEDDING_PROVIDER", "EMBEDDING_MODEL", "EMBEDDING_API_URL", "EMBEDDING_API_KEY"):
            self.assertEqual(self.env[key], {"key": key, "sync": False}, key)
        self.assertEqual(v("TG_SNAPSHOT_STORE"), "r2")
        for forbidden in ("TG_DB_DIR", "TG_LIFECYCLE_DIR", "TG_LEGACY_DEV_ANSWERS", "TG_KB_APPROVED", "TG_PENALTY_ANSWERS", "EMBEDDING_OLLAMA_BASE_URL",
                          "EMBEDDING_VERIFY", "EMBEDDING_NORMALIZE", "TG_SNAPSHOT_ALLOW_STALE"):
            self.assertNotIn(forbidden, self.env, forbidden)

    def test_cloud_env_example_has_placeholders_only(self):
        for line in (ROOT / "deploy" / "cloud.env.example").read_text("utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                if any(w in key for w in ("KEY", "SECRET", "TOKEN")) or key in ("R2_ACCOUNT_ID", "R2_BUCKET"):
                    self.assertTrue(value.startswith("your-"), line)

    def test_cloud_requirements_exclude_the_heavy_and_local_only_packages(self):
        names = {l.split("==")[0].lower() for l in (ROOT / "requirements-cloud.txt").read_text().splitlines() if l and not l.startswith("#")}
        for heavy in ("torch", "transformers", "sentence-transformers", "faiss-cpu", "unstructured", "jupyter", "langchain-ollama", "boto3",
                      "langchain-community", "langgraph", "tiktoken"):
            self.assertNotIn(heavy, names)
        self.assertTrue({"fastapi", "uvicorn", "chromadb", "langchain-chroma", "cryptography", "requests"} <= names)

    def test_server_imports_and_serves_health_without_the_heavy_packages(self):
        """The cloud dependency set has no transformers/torch/langchain-ollama/boto3: the app must not need them."""
        code = textwrap.dedent("""
            import sys, importlib.abc
            BLOCKED = {"transformers", "torch", "sentence_transformers", "langchain_ollama", "ollama", "boto3", "botocore", "faiss",
                       "unstructured", "tiktoken", "langchain_community", "langgraph", "jupyter", "nbconvert"}
            class Block(importlib.abc.MetaPathFinder):
                def find_spec(self, name, path, target=None):
                    if name.split(".")[0] in BLOCKED:
                        raise ImportError("blocked for the cloud-dependency check: " + name)
            sys.meta_path.insert(0, Block())
            import backend.server as srv
            from fastapi.testclient import TestClient
            c = TestClient(srv.app)
            assert c.get("/health").json() == {"status": "ok"}
            s = c.get("/status").json()
            assert s["corpus_ready"] is False and s["embedding"]["provider"] == "openai_compatible", s
            leaked = sorted(m for m in sys.modules if m.split(".")[0] in BLOCKED)
            assert not leaked, leaked
            print("OK")
        """)
        env = {"PATH": "/usr/bin:/bin", "TG_DB_DIR": str(ROOT / "no-such-index"), "EMBEDDING_PROVIDER": "openai_compatible",
               "EMBEDDING_API_URL": "https://embeddings.example/v1", "EMBEDDING_MODEL": "nomic-ai/nomic-embed-text-v1.5",
               "EMBEDDING_API_KEY": KEY, "ANONYMIZED_TELEMETRY": "False", "HOME": str(Path.home())}
        run = subprocess.run([sys.executable, "-W", "ignore", "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
        self.assertEqual(run.returncode, 0, run.stderr[-2000:])
        self.assertIn("OK", run.stdout)
        self.assertNotIn(KEY, run.stdout + run.stderr)       # not in output or logs

    def test_no_credentials_in_any_deployment_file(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import importlib.util
        spec = importlib.util.spec_from_file_location("bp2", ROOT / "scripts" / "build_pages.py")
        bp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bp)
        import re
        value_patterns = [p for p in bp.FORBIDDEN_PATTERNS if p[1] != "secret variable name"]
        for d in ("deploy", ".github", "frontend", "scripts"):
            for f in (ROOT / d).rglob("*"):
                if f.is_file():
                    text = f.read_text("utf-8", errors="ignore")
                    for pattern, label in value_patterns:
                        self.assertIsNone(re.search(pattern, text), f"{f}: {label}")
        for name in (".env.example", "requirements-cloud.txt"):
            text = (ROOT / name).read_text("utf-8")
            for pattern, label in value_patterns:
                self.assertIsNone(re.search(pattern, text), f"{name}: {label}")


if __name__ == "__main__":
    unittest.main()
