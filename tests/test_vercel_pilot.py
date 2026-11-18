"""Offline checks of the Vercel Hobby pilot configuration (pyproject.toml, vercel.json, .vercelignore, deploy/vercel/, backend/vercel_app.py,
backend/vercel_runtime.py, and the opt-in TG_CLIENT_IP_SOURCE=vercel mode of backend/api_protection.py).

What these tests can and cannot show (also stated in eval/deployment/VERCEL-PILOT-READINESS.md):
  - They check the entry point, the configuration files and their relationships to the application, the start-up validation, the model
    download and its integrity checks (with an injected fake network, never a real one), the read-only snapshot restore, and the client
    identity rules.
  - They do NOT show that Vercel accepts the entry point, installs the dependencies, keeps the bundle under 500 MB, lets /tmp hold the model,
    or sends the headers the documentation describes. Only a real deployment can.
Nothing here deploys anything, contacts a network, or touches either Chroma index."""
import asyncio
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import importlib.util  # noqa: E402

import test_index_snapshot as tis  # noqa: E402
from backend import api_protection as ap  # noqa: E402
from backend import index_snapshot as snap  # noqa: E402
from backend import nomic_local, vercel_runtime as vr  # noqa: E402

spec = importlib.util.spec_from_file_location("build_pages_vercel", ROOT / "scripts" / "build_pages.py")
bp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bp)

PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
VERCEL_JSON = json.loads((ROOT / "vercel.json").read_text("utf-8"))
ENV_EXAMPLE = ROOT / "deploy" / "vercel" / "vercel.env.example"
PIN = "ab" * 32


def env_example():
    out = {}
    for line in ENV_EXAMPLE.read_text("utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            out[key.strip()] = value.split("  #")[0].strip()
    return out


def vercel_env(tmp, **change):
    """A complete, valid Vercel environment (after apply_defaults) with the writable root at `tmp`."""
    env = {"TG_ENVIRONMENT": "production", "TG_CLIENT_IP_SOURCE": "vercel", "TG_SNAPSHOT_PIN_SHA256": PIN, "VERCEL": "1",
           "TG_CORS_ORIGINS": "https://someone.github.io", "KYR_MODEL_URL": "https://models.example/nomic.gguf"}
    env.update(change)
    vr.apply_defaults(env, pid=4242, tmp_root=Path(tmp) / "kyr")
    return {k: v for k, v in env.items() if v is not None}


class TmpCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kyr-vercel-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def check(self, env=None, **change):
        e = {**(env or vercel_env(self.tmp)), **change}
        e = {k: v for k, v in e.items() if v is not None}
        return vr.validate(e, tmp_root=self.tmp, project_root=ROOT)


# ------------------------------------------------------------------------------------------------------------ files and entry point
class EntryPointAndFilesTests(unittest.TestCase):
    def test_the_dependencies_are_the_cloud_requirements_pin_for_pin(self):
        cloud = [ln.strip() for ln in (ROOT / "requirements-cloud.txt").read_text("utf-8").splitlines()
                 if ln.strip() and not ln.lstrip().startswith("#")]
        self.assertEqual(sorted(PYPROJECT["project"]["dependencies"]), sorted(cloud))
        for dep in PYPROJECT["project"]["dependencies"]:
            self.assertRegex(dep, r"^[A-Za-z0-9_.-]+==\d")           # every pin exact

    def test_no_research_package_can_be_installed(self):
        names = " ".join(PYPROJECT["project"]["dependencies"]).lower()
        for banned in ("torch", "transformers", "jupyter", "sentence-transformers", "faiss", "unstructured", "ollama", "boto3"):
            self.assertNotIn(banned, names)

    def test_python_is_exactly_the_version_every_pinned_wheel_exists_for(self):
        # numpy 1.26.4 has a Linux wheel only for 3.12 (PyPI, checked 2026-11-15); a range that allowed 3.13/3.14 would need a source build
        self.assertEqual(PYPROJECT["project"]["requires-python"], ">=3.12,<3.13")

    def test_the_entry_point_is_documented_syntax_and_resolves_to_the_unchanged_application(self):
        entry = PYPROJECT["tool"]["vercel"]["entrypoint"]
        module, _, attr = entry.partition(":")
        self.assertEqual((module, attr), ("backend.vercel_app", "app"))
        source = (ROOT / "backend" / "vercel_app.py").read_text("utf-8")
        self.assertIn("from backend.server import app", source)
        self.assertLess(source.index("vercel_runtime.prepare()"), source.index("from backend.server import app"))

    def test_the_api_contract_is_untouched(self):
        server = (ROOT / "backend" / "server.py").read_text("utf-8")
        for decorator in ('@app.post("/chat"', '@app.get("/status")', '@app.get("/health")', '@app.get("/ready")'):
            self.assertIn(decorator, server)
        self.assertNotIn("vercel", server.lower())            # the server knows nothing about the platform

    def test_the_project_is_not_packaged_as_a_library(self):
        self.assertIs(PYPROJECT["tool"]["uv"]["package"], False)
        self.assertEqual(PYPROJECT["tool"]["setuptools"]["packages"], [])

    def test_vercel_json_sets_only_the_duration_within_the_hobby_limit(self):
        self.assertEqual(set(VERCEL_JSON), {"functions"})                 # no rewrites, headers or routes that could bypass the app
        (key, cfg), = VERCEL_JSON["functions"].items()
        self.assertTrue((ROOT / key).is_file())
        self.assertEqual(key, "backend/vercel_app.py")
        self.assertEqual(set(cfg), {"maxDuration"})
        self.assertLessEqual(cfg["maxDuration"], 300)             # documented Hobby maximum

    def allowed(self):
        lines = [ln.strip() for ln in (ROOT / ".vercelignore").read_text("utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
        self.assertEqual(lines[0], "/*")
        return [ln[1:] for ln in lines if ln.startswith("!")]

    def test_vercelignore_is_an_allow_list_of_exactly_what_the_function_needs(self):
        self.assertEqual(sorted(self.allowed()), sorted(["backend", "frontend", "legal", "legal-status", "snapshot-store", "pyproject.toml", "vercel.json"]))
        for name in self.allowed():
            if name != "snapshot-store":                      # created by the operator when the snapshot is published
                self.assertTrue((ROOT / name).exists(), name)

    def test_the_upload_is_small_and_holds_no_model_index_or_research_dependencies(self):
        total = 0
        for name in self.allowed():
            base = ROOT / name
            for p in ([base] if base.is_file() else base.rglob("*") if base.exists() else []):
                if p.is_dir() or "__pycache__" in p.parts or p.suffix == ".pyc":
                    continue
                total += p.stat().st_size
                self.assertNotIn(p.suffix, (".gguf", ".sqlite3", ".bin"), str(p))
                self.assertNotEqual(p.name, "requirements.txt")
        self.assertLess(total, 64 * 1024 * 1024)                   # source upload (four snapshot generations, the lifecycle registry); the 500 MB limit is about dependencies + this
        text = (ROOT / ".vercelignore").read_text("utf-8")
        for excluded in ("requirements.txt", "chroma_telangana_preview", "eval", "tests", "research", "notebooks"):
            self.assertNotRegex(text, rf"(?m)^!{re.escape(excluded)}\b")

    def test_the_allow_listed_files_are_enough_to_import_the_application(self):
        """Copy only the allow-listed paths and import backend.server there: a path the server needs but the list omits fails here."""
        with tempfile.TemporaryDirectory(prefix="kyr-bundle-") as d:
            for name in self.allowed():
                src = ROOT / name
                if src.is_dir():
                    shutil.copytree(src, Path(d) / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                elif src.is_file():
                    shutil.copy2(src, Path(d) / name)
            code = "import backend.server as s; print(sorted(r.path for r in s.app.routes if hasattr(r, 'methods')))"
            env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "PYTHONPATH": d, "PYTHONDONTWRITEBYTECODE": "1", "TG_ENVIRONMENT": "development"}
            out = subprocess.run([sys.executable, "-c", code], cwd=d, env=env, capture_output=True, text=True, timeout=180)
            self.assertEqual(out.returncode, 0, out.stderr[-800:])
            for route in ("/chat", "/status", "/health", "/ready"):
                self.assertIn(route, out.stdout)

    def test_the_env_example_is_placeholders_only_and_passes_validation_once_filled_in(self):
        text = ENV_EXAMPLE.read_text("utf-8")
        for pattern, label in bp.FORBIDDEN_PATTERNS[:-1]:
            self.assertIsNone(re.search(pattern, text), label)
        self.assertNotRegex(text, r"(?m)^\s*(?:[A-Z_]*(?:KEY|SECRET|TOKEN|PASSWORD)[A-Z_]*)=(?!your-)\S")
        env = env_example()
        for name in ("TG_ENVIRONMENT", "TG_CLIENT_IP_SOURCE", "TG_SNAPSHOT_PIN_SHA256", "KYR_MODEL_URL", "TG_CORS_ORIGINS"):
            self.assertIn(name, env)
        for forbidden in ("TG_DB_DIR", "TG_LIFECYCLE_DIR", "EMBEDDING_VERIFY", "TG_TRUSTED_PROXIES", "TG_APPROVAL_FILE", "TG_TRUSTED_KEYS_FILE",
                          "TG_RATE_LIMIT_REQUESTS", "TG_MAX_CONCURRENT_QUESTIONS", "TG_SESSION_MAX", "TG_MAX_REQUEST_BYTES"):
            self.assertNotIn(forbidden, env)                      # protections keep their application defaults
        self.assertEqual(env["PROVIDER_MAX_RETRIES"], "0")
        self.assertLessEqual(float(env["PROVIDER_TIMEOUT_SECONDS"]), 25)
        with tempfile.TemporaryDirectory() as d:
            filled = {**env, "TG_SNAPSHOT_PIN_SHA256": PIN, "VERCEL": "1"}
            vr.apply_defaults(filled, pid=1, tmp_root=Path(d) / "kyr")
            self.assertEqual(vr.validate(filled, tmp_root=Path(d), project_root=ROOT), [])

    def test_the_pin_in_the_env_example_is_the_published_manifest_when_a_snapshot_is_present(self):
        store = ROOT / "snapshot-store" / "kyr"
        if not (store / "active.json").is_file():
            self.skipTest("no snapshot published in this checkout")
        pointer = json.loads((store / "active.json").read_text("utf-8"))
        manifest = (store / pointer["manifest_key"]).read_bytes()
        digest = hashlib.sha256(manifest).hexdigest()
        self.assertEqual(pointer["manifest_sha256"], digest)
        self.assertEqual(env_example()["TG_SNAPSHOT_PIN_SHA256"], digest)

    def test_no_paid_or_extra_service_is_configured(self):
        text = (ENV_EXAMPLE.read_text("utf-8") + (ROOT / "vercel.json").read_text("utf-8") + (ROOT / "pyproject.toml").read_text("utf-8")).lower()
        for word in ("redis", "upstash", "postgres", "kv_rest", "blob_read_write", "stripe", "openai", "pay as you go", "pro plan"):
            self.assertNotIn(word, text)


# ------------------------------------------------------------------------------------------------------------ validation
class ValidationTests(TmpCase):
    def test_a_complete_environment_is_accepted(self):
        self.assertEqual(self.check(), [])

    def test_every_safeguard_weakening_is_refused(self):
        cases = {
            "OLLAMA_ENABLED": "true", "EMBEDDING_VERIFY": "off", "TG_SNAPSHOT_PIN_SHA256": None, "TG_ENVIRONMENT": "development",
            "EMBEDDING_MODEL_SHA256": "0" * 64, "EMBEDDING_PROVIDER": "ollama", "TG_SNAPSHOT_STORE": "r2", "TG_DB_DIR": "/somewhere",
            "TG_LIFECYCLE_DIR": "/somewhere", "TG_CLIENT_IP_SOURCE": None, "VERCEL": None, "TG_GROUNDED_ANSWERS": "0",
            "TG_LEGACY_DEV_ANSWERS": "1", "TG_CLOUD": "0", "TG_SNAPSHOT_EXPECT_FAMILY": "bge-small",
        }
        for name, value in cases.items():
            with self.subTest(name):
                errors = self.check(**{name: value})
                self.assertTrue(any(name.split("_")[0] in e or name in e for e in errors) or errors, name)
                self.assertTrue(errors, f"{name}={value} was accepted")

    def test_the_pin_must_be_64_hex(self):
        for bad in ("", "abc", "g" * 64, "ab" * 33):
            self.assertTrue(self.check(TG_SNAPSHOT_PIN_SHA256=bad), bad)

    def test_paths_must_be_where_vercel_allows_writes_and_reads(self):
        self.assertTrue(self.check(TG_SNAPSHOT_WORK_DIR=str(ROOT / "work")))                    # inside the read-only bundle
        self.assertTrue(self.check(EMBEDDING_MODEL_FILE=str(ROOT / "model.gguf")))
        self.assertTrue(self.check(TG_SNAPSHOT_LOCAL_DIR=str(self.tmp / "snapshot-store")))     # the snapshot must ship in the bundle, not /tmp
        self.assertTrue(self.check(TG_SNAPSHOT_LOCAL_DIR=str(Path(tempfile.gettempdir()).parent / "elsewhere")))

    def test_the_model_url_must_be_https_without_credentials(self):
        for url in ("http://models.example/m.gguf", "ftp://x/y", "https://user:pw@models.example/m", "https:///nohost", "not a url"):
            self.assertTrue(self.check(KYR_MODEL_URL=url), url)
        self.assertEqual(self.check(KYR_MODEL_URL="https://models.example/m.gguf?sig=abc"), [])

    def test_messages_name_variables_and_never_echo_values(self):
        secret = "SECRET-VALUE-0123456789-MUST-NOT-APPEAR"
        errors = self.check(KYR_MODEL_URL=f"https://user:{secret}@models.example/m", OLLAMA_ENABLED=secret, TG_SNAPSHOT_PIN_SHA256=secret)
        self.assertTrue(errors)
        self.assertNotIn(secret, " ".join(errors))

    def test_defaults_never_overwrite_the_operator_and_never_invent_a_safeguard(self):
        env = {"EMBEDDING_MODEL_FILE": "/tmp/mine.gguf", "TG_SNAPSHOT_STORE": "r2"}
        vr.apply_defaults(env, pid=7, tmp_root=self.tmp)
        self.assertEqual(env["EMBEDDING_MODEL_FILE"], "/tmp/mine.gguf")
        self.assertEqual(env["TG_SNAPSHOT_STORE"], "r2")
        for name in ("TG_ENVIRONMENT", "TG_SNAPSHOT_PIN_SHA256", "KYR_MODEL_URL", "TG_CLIENT_IP_SOURCE", "GROQ_API_KEY", "GEMINI_API_KEY",
                     "TG_APPROVAL_FILE", "TG_TRUSTED_KEYS_FILE", "EMBEDDING_VERIFY"):
            self.assertNotIn(name, env)
        self.assertEqual(env["EMBEDDING_MODEL_SHA256"], nomic_local.KNOWN_MODEL_SHA256)
        self.assertEqual(env["TG_CLOUD"], "1")

    def test_the_corpus_directory_defaults_to_the_bundled_source_files_only_when_they_are_there(self):
        root = Path(self.tmp) / "project"
        (root / "legal" / "source-documents").mkdir(parents=True)
        env, bare = {}, {}
        vr.apply_defaults(env, pid=1, tmp_root=self.tmp, project_root=root)
        self.assertEqual(env["TG_CORPUS_DIR"], str(root / "legal" / "source-documents"))
        vr.apply_defaults(bare, pid=1, tmp_root=self.tmp, project_root=Path(self.tmp) / "empty")
        self.assertNotIn("TG_CORPUS_DIR", bare)   # never invented: with no files the hash check keeps blocking answers
        mine = {"TG_CORPUS_DIR": "/elsewhere"}
        vr.apply_defaults(mine, pid=1, tmp_root=self.tmp, project_root=root)
        self.assertEqual(mine["TG_CORPUS_DIR"], "/elsewhere")

    def test_each_process_gets_its_own_snapshot_work_directory_and_the_model_is_held_in_memory(self):
        a, b = {}, {}
        vr.apply_defaults(a, pid=1, tmp_root=self.tmp)
        vr.apply_defaults(b, pid=2, tmp_root=self.tmp)
        self.assertNotEqual(a["TG_SNAPSHOT_WORK_DIR"], b["TG_SNAPSHOT_WORK_DIR"])
        for env in (a, b):
            self.assertEqual(env["EMBEDDING_MODEL_SOURCE"], "memory")
            self.assertNotIn("EMBEDDING_MODEL_FILE", env)

    def test_the_pinned_model_constants_match_the_engine_and_the_verified_file(self):
        self.assertEqual(vr.MODEL_SHA256, nomic_local.KNOWN_MODEL_SHA256)
        self.assertEqual(vr.MODEL_SHA256, "970aa74c0a90ef7482477cf803618e776e173c007bf957f635f1015bfcfef0e6")
        self.assertEqual(vr.MODEL_BYTES, 274290656)
        self.assertEqual(vr.EXPECT_FAMILY, "nomic-embed-text-v1.5")


# ------------------------------------------------------------------------------------------------------------ model download
DATA = b"fake-model-bytes-" * 5000
SHA = hashlib.sha256(DATA).hexdigest()


class Resp:
    def __init__(self, data=DATA, headers=None):
        self.b, self.closed = io.BytesIO(data), False
        self.headers = {"Content-Length": str(len(data))} if headers is None else headers

    def read(self, n):
        return self.b.read(n)

    def close(self):
        self.closed = True


class Opener:
    """Replays a script of responses or exceptions (the last item repeats); counts calls; never touches a network."""

    def __init__(self, *script, delay=0.0):
        self.script, self.calls, self.delay, self.urls = list(script), 0, delay, []

    def __call__(self, request, timeout=None):
        self.calls += 1
        self.urls.append(request.full_url)
        if self.delay:
            time.sleep(self.delay)
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, BaseException):
            raise item
        return item() if callable(item) else item


URL = "https://models.example/nomic.gguf?sig=PRESIGNED-SECRET"


class ModelDownloadTests(TmpCase):
    def setUp(self):
        super().setUp()
        self.path = self.tmp / "kyr" / "model" / "m.gguf"

    def ensure(self, opener, url=URL, **kw):
        return vr.ensure_model(self.path, url, sha256=SHA, size=len(DATA), opener=opener, **kw)

    def leftovers(self):
        return [p.name for p in self.path.parent.iterdir() if ".part" in p.name]

    def fails(self, opener, code, url=URL, **kw):
        with self.assertRaises(vr.ModelFetchError) as cm:
            self.ensure(opener, url, **kw)
        self.assertEqual(cm.exception.code, code)
        self.assertNotIn("PRESIGNED-SECRET", str(cm.exception))
        self.assertNotIn("models.example", str(cm.exception))
        self.assertFalse(self.path.exists())
        self.assertEqual(self.leftovers(), [])
        return cm.exception

    def test_a_verified_download_lands_atomically(self):
        op = Opener(lambda: Resp())
        result = self.ensure(op)
        self.assertTrue(result["downloaded"])
        self.assertEqual(self.path.read_bytes(), DATA)
        self.assertEqual(self.leftovers(), [])
        self.assertEqual(op.calls, 1)

    def test_a_present_verified_file_is_reused_without_any_request(self):
        self.ensure(Opener(lambda: Resp()))
        op = Opener(RuntimeError("must not be called"))
        self.assertFalse(self.ensure(op)["downloaded"])
        self.assertEqual(op.calls, 0)

    def test_a_present_corrupt_file_is_replaced_never_trusted(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(DATA[:-1] + b"X")
        self.assertTrue(self.ensure(Opener(lambda: Resp()))["downloaded"])
        self.assertEqual(self.path.read_bytes(), DATA)

    def test_wrong_bytes_are_refused_and_not_retried(self):
        op = Opener(lambda: Resp(b"y" * len(DATA)))
        self.fails(op, "checksum_mismatch")
        self.assertEqual(op.calls, 1)

    def test_a_truncated_download_is_refused(self):
        self.fails(Opener(lambda: Resp(DATA[:100], headers={})), "checksum_mismatch")

    def test_an_oversized_stream_is_cut_off(self):
        self.fails(Opener(lambda: Resp(DATA + b"extra", headers={})), "size_mismatch")

    def test_a_server_announcing_another_size_is_refused_before_reading(self):
        self.fails(Opener(lambda: Resp(DATA, headers={"Content-Length": "999"})), "size_mismatch")

    def test_one_retry_for_a_transient_failure_then_success(self):
        op = Opener(urllib.error.URLError("reset"), lambda: Resp())
        self.assertTrue(self.ensure(op)["downloaded"])
        self.assertEqual(op.calls, 2)

    def test_two_failures_give_up_with_a_safe_message(self):
        op = Opener(TimeoutError("slow"))
        self.fails(op, "download_failed")
        self.assertEqual(op.calls, 2)

    def test_a_client_error_is_not_retried(self):
        op = Opener(urllib.error.HTTPError(URL, 404, "Not Found", {}, None))
        self.fails(op, "download_failed")
        self.assertEqual(op.calls, 1)

    def test_a_server_error_is_retried_once(self):
        op = Opener(urllib.error.HTTPError(URL, 503, "Unavailable", {}, None), lambda: Resp())
        self.assertTrue(self.ensure(op)["downloaded"])

    def test_no_file_and_no_url_is_a_clear_failure(self):
        self.fails(Opener(RuntimeError("never")), "model_missing", url=None)

    def test_plain_http_is_never_contacted(self):
        op = Opener(RuntimeError("never"))
        self.fails(op, "bad_url", url="http://models.example/m.gguf")
        self.assertEqual(op.calls, 0)

    def test_the_time_budget_is_enforced(self):
        self.fails(Opener(lambda: Resp()), "deadline", deadline_seconds=-1)

    def test_not_enough_free_space_is_refused_before_downloading(self):
        op = Opener(RuntimeError("never"))
        with mock.patch("backend.vercel_runtime.shutil.disk_usage", return_value=SimpleNamespace(free=10)):
            self.fails(op, "no_space")
        self.assertEqual(op.calls, 0)

    def test_the_response_is_always_closed(self):
        r = Resp(b"y" * len(DATA))
        self.fails(Opener(lambda: r), "checksum_mismatch")
        self.assertTrue(r.closed)

    def test_concurrent_processes_download_the_file_once(self):
        op = Opener(lambda: Resp(), delay=0.3)
        results, errors = [], []

        def run():
            try:
                results.append(self.ensure(op)["downloaded"])
            except Exception as exc:   # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=run) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertEqual(errors, [])
        self.assertEqual(op.calls, 1)
        self.assertEqual(sorted(results), [False, False, False, True])
        self.assertEqual(self.path.read_bytes(), DATA)

    def test_a_stuck_lock_holder_cannot_block_start_up_forever(self):
        self.path.parent.mkdir(parents=True)
        with vr._Lock(self.path.with_name(self.path.name + ".lock"), 5):
            self.fails(Opener(RuntimeError("never")), "lock_timeout", lock_timeout=0.4)

    def test_redirects_may_not_leave_https(self):
        handler = vr._HttpsOnlyRedirects()
        req = urllib.request.Request("https://a.example/x")
        with self.assertRaises(urllib.error.URLError):
            handler.redirect_request(req, None, 302, "Found", {}, "http://evil.example/x")
        self.assertIsNotNone(handler.redirect_request(req, None, 302, "Found", {}, "https://cdn.example/x"))

    def test_prepare_validates_before_it_downloads_anything(self):
        op = Opener(RuntimeError("never"))
        env = vercel_env(self.tmp, OLLAMA_ENABLED="true")
        with self.assertRaises(vr.VercelConfigError) as cm:
            vr.prepare(env, opener=op, tmp_root=self.tmp / "kyr", project_root=ROOT)
        self.assertIn("OLLAMA_ENABLED", str(cm.exception))
        self.assertEqual(op.calls, 0)

    def test_prepare_refuses_bytes_that_are_not_the_pinned_model_and_leaves_nothing_behind(self):
        env = vercel_env(self.tmp)
        nomic_local.set_memory_model(None)
        with self.assertRaises(vr.ModelFetchError) as cm:                 # prepare() always uses the real pinned size and hash
            vr.prepare(env, opener=Opener(lambda: Resp()), tmp_root=self.tmp / "kyr", project_root=ROOT)
        self.assertIn(cm.exception.code, ("size_mismatch", "checksum_mismatch"))
        self.assertNotIn("EMBEDDING_MODEL_FILE", env)
        self.assertIsNone(nomic_local.get_memory_model())                 # nothing half-loaded is left for the engine to find
        self.assertEqual([p for p in self.tmp.rglob("*") if p.is_file()], [])      # and nothing was written to disk

    def test_the_import_of_the_entry_point_fails_closed_without_configuration(self):
        env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
        out = subprocess.run([sys.executable, "-c", "import backend.vercel_app"], cwd=str(self.tmp), env=env, capture_output=True, text=True, timeout=120)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("VercelConfigError", out.stderr)
        for name in ("TG_ENVIRONMENT", "TG_SNAPSHOT_PIN_SHA256", "TG_CLIENT_IP_SOURCE"):
            self.assertIn(name, out.stderr)
        self.assertNotIn("backend.server", out.stderr.replace("backend.vercel_app", ""))     # the server was never imported


# ------------------------------------------------------------------------------------------------------------ client identity
class ClientIdentityTests(unittest.TestCase):
    def cfg(self, **env):
        return ap.config_from_env({"TG_RATE_LIMIT_REQUESTS": "2", **env})

    def test_the_default_is_unchanged(self):
        c = self.cfg()
        self.assertEqual(c.client_ip_source, "")
        self.assertEqual(c.public()["client_ip_source"], "peer")

    def test_vercel_mode_needs_the_platform_variable(self):
        self.assertEqual(self.cfg(TG_CLIENT_IP_SOURCE="vercel", VERCEL="1").client_ip_source, "vercel")
        c = self.cfg(TG_CLIENT_IP_SOURCE="vercel")
        self.assertEqual(c.client_ip_source, "")
        self.assertTrue(any("only valid on Vercel" in p for p in c.problems))
        c = self.cfg(TG_CLIENT_IP_SOURCE="cloudflare", VERCEL="1")
        self.assertEqual(c.client_ip_source, "")
        self.assertTrue(c.problems)

    def test_resolve_accepts_exactly_one_valid_address(self):
        r = ap.resolve_vercel_client
        self.assertEqual(r([b"203.0.113.9"]), "203.0.113.9")
        self.assertEqual(r([b" 203.0.113.9 "]), "203.0.113.9")
        self.assertEqual(r([b"::ffff:203.0.113.9"]), "203.0.113.9")
        self.assertEqual(r([b"2001:db8:1:2:aaaa::1"]), r([b"2001:db8:1:2:bbbb::9"]))       # IPv6 shares a /64
        for bad in ([], [b"1.1.1.1", b"2.2.2.2"], [b"9.9.9.9, 1.1.1.1"], [b"not-an-ip"], [b""], [b"1.1.1.1\x00"]):
            self.assertEqual(r(bad), ap.UNIDENTIFIED_CLIENT, bad)

    def drive(self, mw, headers, peer="10.0.0.1"):
        scope = {"type": "http", "method": "POST", "path": "/chat", "headers": headers, "client": (peer, 5555)}
        sent = []

        async def receive():
            return {"type": "http.request", "body": b"{}", "more_body": False}

        async def send(message):
            sent.append(message)

        asyncio.run(mw(scope, receive, send))
        return sent[0]["status"]

    def middleware(self, **env):
        async def app(scope, receive, send):
            await receive()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        return ap.ProtectionMiddleware(app, config=self.cfg(**env))

    @staticmethod
    def xff(value):
        return [(b"x-forwarded-for", value)]

    def test_visitors_get_separate_buckets_behind_the_platform(self):
        mw = self.middleware(TG_CLIENT_IP_SOURCE="vercel", VERCEL="1")
        a, b = self.xff(b"198.51.100.1"), self.xff(b"198.51.100.2")
        self.assertEqual([self.drive(mw, a), self.drive(mw, a), self.drive(mw, a)], [200, 200, 429])
        self.assertEqual(self.drive(mw, b), 200)

    def test_a_forged_list_cannot_buy_a_fresh_bucket(self):
        mw = self.middleware(TG_CLIENT_IP_SOURCE="vercel", VERCEL="1")
        forged = [self.xff(b"9.9.9.9, 198.51.100.1"), self.xff(b"7.7.7.7, 198.51.100.1"), self.xff(b"1.2.3.4, 5.6.7.8, 198.51.100.1")]
        self.assertEqual([self.drive(mw, h) for h in forged], [200, 200, 429])         # one shared, stricter bucket

    def test_a_missing_or_repeated_header_is_one_shared_bucket(self):
        mw = self.middleware(TG_CLIENT_IP_SOURCE="vercel", VERCEL="1")
        self.assertEqual([self.drive(mw, []), self.drive(mw, [(b"x-forwarded-for", b"1.1.1.1"), (b"x-forwarded-for", b"2.2.2.2")]),
                          self.drive(mw, self.xff(b"garbage"))], [200, 200, 429])

    def test_the_peer_address_is_ignored_in_vercel_mode(self):
        mw = self.middleware(TG_CLIENT_IP_SOURCE="vercel", VERCEL="1")
        h = self.xff(b"198.51.100.1")
        self.assertEqual([self.drive(mw, h, peer="10.0.0.1"), self.drive(mw, h, peer="10.9.9.9"), self.drive(mw, h, peer="10.7.7.7")], [200, 200, 429])

    def test_without_the_mode_a_forwarded_header_still_buys_nothing(self):
        mw = self.middleware()                                     # default: peer only, no trusted proxy
        self.assertEqual([self.drive(mw, self.xff(b"1.1.1.1")), self.drive(mw, self.xff(b"2.2.2.2")), self.drive(mw, self.xff(b"3.3.3.3"))], [200, 200, 429])

    def test_without_the_platform_variable_the_header_is_never_honoured(self):
        mw = self.middleware(TG_CLIENT_IP_SOURCE="vercel")        # VERCEL unset: the mode is refused, the peer is used
        self.assertEqual([self.drive(mw, self.xff(b"1.1.1.1")), self.drive(mw, self.xff(b"2.2.2.2")), self.drive(mw, self.xff(b"3.3.3.3"))], [200, 200, 429])


# ------------------------------------------------------------------------------------------------------------ snapshot integrity
class BundledSnapshotTests(tis.Fixture):
    """The snapshot ships inside the (read-only) bundle and is restored into a per-process /tmp directory. Fake index and embedder
    (as in the other snapshot tests); the real s11 snapshot has not been published."""

    def setUp(self):
        super().setUp()
        self.manifest = self.publish()
        self.env = {"TG_SNAPSHOT_STORE": "local", "TG_SNAPSHOT_LOCAL_DIR": str(self.tmp / "store"), "TG_SNAPSHOT_PREFIX": ""}

    def restore(self, n=1, **change):
        env = {**self.env, "TG_SNAPSHOT_WORK_DIR": str(self.tmp / f"work-{n}"), **change}
        return snap.activate_from_env(env)

    def make_read_only(self):
        for p in [self.tmp / "store", *(self.tmp / "store").rglob("*")]:
            os.chmod(p, 0o555 if p.is_dir() else 0o444)
        self.addCleanup(lambda: [os.chmod(p, 0o755 if p.is_dir() else 0o644) for p in [self.tmp / "store", *(self.tmp / "store").rglob("*")]])

    def test_a_read_only_bundle_restores_into_a_writable_work_directory(self):
        self.make_read_only()
        st = self.restore()
        self.assertTrue(st.ready, st.problems)
        self.assertEqual(st.version, self.manifest["version"])
        self.assertTrue(str(st.db_dir).startswith(str(self.tmp / "work-1")))

    def test_the_bundle_is_never_written_to(self):
        before = {str(p): p.stat().st_mtime_ns for p in (self.tmp / "store").rglob("*")}
        self.restore()
        self.assertEqual(before, {str(p): p.stat().st_mtime_ns for p in (self.tmp / "store").rglob("*")})
        self.assertEqual(set(before), {str(p) for p in (self.tmp / "store").rglob("*")})

    def test_concurrent_processes_each_restore_a_verified_copy(self):
        """Separate processes (what separate instances or workers are), not threads: chromadb's client creation is not thread-safe
        (observed: intermittent KeyError when two threads of ONE process restore at once). The server restores once per process, at import."""
        self.make_read_only()
        code = ("import json, sys; from backend import index_snapshot as s; st = s.activate_from_env(json.loads(sys.argv[1])); "
                "print(json.dumps({'ready': st.ready, 'state': st.state, 'db': str(st.db_dir)}))")
        base = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
        procs = [subprocess.Popen([sys.executable, "-c", code, json.dumps({**self.env, "TG_SNAPSHOT_WORK_DIR": str(self.tmp / f"proc-{n}")})],
                                  env=base, cwd=str(self.tmp), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for n in range(3)]
        results = []
        for proc in procs:
            out, err = proc.communicate(timeout=120)
            self.assertEqual(proc.returncode, 0, err[-500:])
            results.append(json.loads(out.strip().splitlines()[-1]))
        self.assertTrue(all(r["ready"] for r in results), results)
        self.assertEqual(len({r["db"] for r in results}), 3)                              # no directory is shared

    def test_a_tampered_archive_is_refused(self):
        archive = self.tmp / "store" / self.manifest["index"]["archive"]
        archive.write_bytes(archive.read_bytes()[:-8] + b"tampered")
        st = self.restore()
        self.assertFalse(st.ready)
        self.assertEqual(st.state, "checksum_mismatch")

    def test_a_missing_archive_fails_closed(self):
        (self.tmp / "store" / self.manifest["lifecycle"]["archive"]).unlink()
        st = self.restore()
        self.assertFalse(st.ready)

    def test_a_wrong_pin_is_refused_and_the_right_pin_accepted(self):
        pin = snap.sha256_bytes((self.tmp / "store" / f"manifests/{self.manifest['version']}.json").read_bytes())
        self.assertFalse(self.restore(1, TG_SNAPSHOT_PIN_SHA256="cd" * 32).ready)
        self.assertTrue(self.restore(2, TG_SNAPSHOT_PIN_SHA256=pin).ready)

    def test_an_unexpected_embedding_family_is_refused(self):
        st = self.restore(1, TG_SNAPSHOT_EXPECT_FAMILY="nomic-embed-text-v1.5")          # the fixture is "fake-family"
        self.assertFalse(st.ready)
        self.assertEqual(st.state, "embedding_incompatible")

    def test_an_empty_bundle_means_not_ready_not_a_crash(self):
        shutil.rmtree(self.tmp / "store")
        (self.tmp / "store").mkdir()
        st = self.restore()
        self.assertFalse(st.ready)

    def test_a_missing_bundle_directory_is_a_configuration_failure_not_a_crash(self):
        shutil.rmtree(self.tmp / "store")
        try:
            st = self.restore()
        except snap.SnapshotError as err:
            self.assertEqual(err.state, "misconfigured")
        else:
            self.assertFalse(st.ready)


if __name__ == "__main__":
    unittest.main()
