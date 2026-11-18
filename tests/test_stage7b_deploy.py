"""Stage 7B: deployment configuration. Offline: reads the Render blueprint, the Pages workflow and the frontend build; runs the
environment validator and the Pages build in temporary directories. Nothing is deployed, contacted or paid for."""
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

import test_cloud_readiness as tcr
from backend import providers

ROOT = Path(__file__).resolve().parent.parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cce = load("check_cloud_env", "scripts/check_cloud_env.py")
bp = load("build_pages_7b", "scripts/build_pages.py")

SENTINELS = {"EMBEDDING_API_KEY": "nk-SENTINEL-embedding-0123456789abcdef", "R2_SECRET_ACCESS_KEY": "SENTINEL-r2-secret-0123456789",
             "R2_ACCESS_KEY_ID": "SENTINELr2keyid0123", "GROQ_API_KEY": "gsk_SENTINEL0123456789abcdefghij",
             "GEMINI_API_KEY": "AIzaSENTINEL0123456789abcdefghijklmnop"}
GOOD = {"TG_ENVIRONMENT": "production", "TG_GROUNDED_ANSWERS": "1", "OLLAMA_ENABLED": "false", "TG_SNAPSHOT_STORE": "r2",
        "R2_ACCOUNT_ID": "acct123", "R2_BUCKET": "kyr-test", "EMBEDDING_PROVIDER": "nomic_atlas", "EMBEDDING_MODEL": "nomic-embed-text-v1.5",
        "TG_CORS_ORIGINS": "https://someone.github.io", "TG_SNAPSHOT_PIN_SHA256": "ab" * 32,   # a test fixture, not a real digest
        **SENTINELS}


def blueprint():
    doc = yaml.safe_load((ROOT / "deploy" / "render.yaml").read_text("utf-8"))
    return doc["services"][0], {e["key"]: e for e in doc["services"][0]["envVars"]}


class CloudEnvironmentValidatorTests(unittest.TestCase):
    def check(self, **change):
        env = {**GOOD, **change}
        return cce.check({k: v for k, v in env.items() if v is not None})

    def names(self, result):
        return {e["name"] for e in result["errors"]}

    def test_a_complete_cloud_environment_passes_and_only_warns_about_notable_states(self):
        r = self.check()
        self.assertEqual((r["ok"], r["errors"]), (True, []))
        self.assertFalse({"TG_APPROVAL_FILE", "TG_TRUSTED_KEYS_FILE"} & {w["name"] for w in r["warnings"]})   # no approval material is needed

    def test_each_unsafe_or_missing_setting_is_an_error(self):
        cases = {
            "TG_ENVIRONMENT": {"TG_ENVIRONMENT": "development"}, "TG_GROUNDED_ANSWERS": {"TG_GROUNDED_ANSWERS": "0"},
            "TG_SNAPSHOT_STORE": {"TG_SNAPSHOT_STORE": "s3"}, "R2_*": {"R2_BUCKET": None},
            "TG_DB_DIR": {"TG_DB_DIR": "/tmp/x"}, "TG_LIFECYCLE_DIR": {"TG_LIFECYCLE_DIR": "/tmp/y"},
            "OLLAMA_ENABLED": {"OLLAMA_ENABLED": None}, "TG_LEGACY_DEV_ANSWERS": {"TG_LEGACY_DEV_ANSWERS": "1"},
            "TG_SNAPSHOT_ALLOW_STALE": {"TG_SNAPSHOT_ALLOW_STALE": "1"}, "EMBEDDING_VERIFY": {"EMBEDDING_VERIFY": "off"},
            "TG_ENABLE_APPROVAL_REFRESH": {"TG_ENABLE_APPROVAL_REFRESH": "1"}, "TG_SNAPSHOT_PIN_SHA256": {"TG_SNAPSHOT_PIN_SHA256": "xyz"},
            "TG_CORS_ORIGINS": {"TG_CORS_ORIGINS": "*"},
            "EMBEDDING_*": {"EMBEDDING_PROVIDER": None},
        }
        for name, change in cases.items():
            r = self.check(**change)
            self.assertFalse(r["ok"], name)
            self.assertIn(name, self.names(r), name)

    def test_embeddings_have_no_default_and_never_resolve_to_ollama_in_the_cloud(self):
        for change in ({"EMBEDDING_PROVIDER": None}, {"EMBEDDING_PROVIDER": "ollama"}, {"EMBEDDING_API_KEY": None},
                       {"EMBEDDING_MODEL": None}, {"EMBEDDING_API_KEY": "your-embedding-key"}):
            r = self.check(**change)
            self.assertFalse(r["ok"], change)
            self.assertIn("EMBEDDING_*", self.names(r), change)
        self.assertTrue(self.check(EMBEDDING_PROVIDER="openai_compatible", EMBEDDING_API_URL="https://embeddings.example/v1")["ok"])

    def test_wildcard_path_and_plain_http_cors_origins_are_refused(self):
        for bad in ("*", "https://someone.github.io/repo", "http://someone.github.io", "https://*.github.io"):
            self.assertIn("TG_CORS_ORIGINS", self.names(self.check(TG_CORS_ORIGINS=bad)), bad)

    def test_the_report_never_contains_a_secret_value(self):
        for env in (GOOD, {**GOOD, "TG_ENVIRONMENT": "development", "R2_BUCKET": None, "EMBEDDING_PROVIDER": "ollama", "TG_DB_DIR": "/x"}):
            lines = []
            cce.main([], out=lines.append, env={k: v for k, v in env.items() if v is not None})
            cce.main(["--json"], out=lines.append, env={k: v for k, v in env.items() if v is not None})
            text = "\n".join(lines)
            for value in SENTINELS.values():
                self.assertNotIn(value, text)
            for part in ("SENTINEL",):
                self.assertNotIn(part, text)

    def test_the_script_blocks_a_bad_start_and_allows_a_good_one(self):
        script = str(ROOT / "scripts" / "check_cloud_env.py")
        bad = subprocess.run([sys.executable, script], env={"PATH": "/usr/bin:/bin"}, capture_output=True, text=True, timeout=60, cwd=ROOT)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("not starting", bad.stdout)
        good = subprocess.run([sys.executable, script], env={"PATH": "/usr/bin:/bin", **{k: v for k, v in GOOD.items() if v is not None}},
                              capture_output=True, text=True, timeout=60, cwd=ROOT)
        self.assertEqual(good.returncode, 0, good.stdout)
        self.assertNotIn("SENTINEL", good.stdout + good.stderr)


class RenderBlueprintTests(unittest.TestCase):
    def test_free_plan_one_web_service_nothing_that_costs_money(self):
        doc = yaml.safe_load((ROOT / "deploy" / "render.yaml").read_text("utf-8"))
        self.assertEqual(set(doc), {"services"})
        self.assertEqual(len(doc["services"]), 1)
        svc = doc["services"][0]
        self.assertEqual((svc["type"], svc["plan"]), ("web", "free"))
        for forbidden in ("disk", "numInstances", "scaling", "databases", "autoDeploy"):
            self.assertNotIn(forbidden, svc)
        self.assertEqual(svc["autoDeployTrigger"], "off")            # nothing deploys by itself

    def test_start_command_validates_then_execs_one_uvicorn_worker_on_the_platform_port(self):
        svc, _ = blueprint()
        cmd = svc["startCommand"]
        self.assertLess(cmd.index("scripts/check_cloud_env.py"), cmd.index("uvicorn"))
        self.assertIn("&& exec uvicorn", cmd)
        for needle in ("backend.server:app", "--host 0.0.0.0", "--port $PORT", "--workers 1", "--timeout-graceful-shutdown"):
            self.assertIn(needle, cmd)
        self.assertNotIn("--reload", cmd)
        self.assertEqual(svc["healthCheckPath"], "/ready")    # Stage 7C: the platform health check is the readiness route
        self.assertTrue((ROOT / "scripts" / "check_cloud_env.py").is_file())

    def test_no_paid_or_unapproved_embedding_host_is_configured_anywhere_in_deployment_files(self):
        paths = [p for d in ("deploy", ".github", "scripts") for p in (ROOT / d).rglob("*") if p.is_file()]
        paths += [ROOT / "requirements-cloud.txt", ROOT / ".env.example"]
        for p in paths:
            text = p.read_text("utf-8", errors="ignore").lower()
            for host in ("fireworks.ai", "deepinfra.com", "together.ai", "together.xyz", "api.openai.com", "api.cohere", "voyageai.com"):
                self.assertNotIn(host, text, f"{p.name}: {host}")

    def test_the_blueprint_alone_is_blocked_until_the_operator_supplies_the_approved_embedding_and_r2_settings(self):
        _, env = blueprint()
        fixed = {k: v["value"] for k, v in env.items() if "value" in v}
        r = cce.check({**fixed, "RENDER": "true"})
        self.assertFalse(r["ok"])
        self.assertTrue({"R2_*", "EMBEDDING_*"} <= {e["name"] for e in r["errors"]})
        supplied = {k: GOOD[k] for k in GOOD if k in env and "value" not in env[k]}
        self.assertTrue({"EMBEDDING_PROVIDER", "EMBEDDING_MODEL", "EMBEDDING_API_KEY", "R2_BUCKET", "TG_CORS_ORIGINS"} <= set(supplied))
        self.assertTrue(cce.check({**fixed, **supplied})["ok"], cce.check({**fixed, **supplied})["errors"])

    def test_every_sync_false_variable_is_a_deliberate_operator_input_and_none_has_a_value(self):
        _, env = blueprint()
        for key, entry in env.items():
            if entry.get("sync") is False:
                self.assertEqual(set(entry), {"key", "sync"}, key)
        self.assertFalse([k for k in env if k in ("TG_DB_DIR", "TG_LIFECYCLE_DIR", "TG_ENABLE_APPROVAL_REFRESH", "EMBEDDING_VERIFY")])


class PagesWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = (ROOT / ".github" / "workflows" / "pages.yml").read_text("utf-8")
        cls.text, cls.doc = text, yaml.safe_load(text)

    def triggers(self):
        return self.doc.get("on", self.doc.get(True))      # YAML 1.1 reads a bare `on` as True

    def test_it_is_valid_yaml_with_exactly_a_manual_trigger(self):
        self.assertEqual(set(self.triggers()), {"workflow_dispatch"})

    def test_permissions_are_the_minimum_for_pages(self):
        self.assertEqual(self.doc["permissions"], {"contents": "read", "pages": "write", "id-token": "write"})
        for job in self.doc["jobs"].values():
            self.assertNotIn("secrets", json.dumps(job).lower().replace("secrets.", "secrets."), "no secret is read")

    def test_build_then_deploy_through_the_github_pages_environment(self):
        jobs = self.doc["jobs"]
        self.assertEqual(set(jobs), {"build", "deploy"})
        self.assertEqual(jobs["deploy"]["needs"], "build")
        self.assertEqual(jobs["deploy"]["environment"]["name"], "github-pages")
        self.assertEqual(self.doc["concurrency"], {"group": "pages", "cancel-in-progress": False})

    def test_every_action_is_a_pinned_major_version_and_none_is_unexpected(self):
        uses = [s["uses"] for j in self.doc["jobs"].values() for s in j["steps"] if "uses" in s]
        self.assertTrue(uses)
        for u in uses:
            self.assertRegex(u, r"^actions/[a-z\-]+@v\d+$", u)
        self.assertEqual({u.split("@")[0] for u in uses},
                         {"actions/checkout", "actions/setup-python", "actions/configure-pages", "actions/upload-pages-artifact", "actions/deploy-pages"})

    def test_the_published_directory_is_the_one_the_build_script_writes_and_the_build_demands_an_api_base(self):
        steps = self.doc["jobs"]["build"]["steps"]
        build = next(s for s in steps if "run" in s and "build_pages.py" in s["run"])
        upload = next(s for s in steps if s.get("uses", "").startswith("actions/upload-pages-artifact"))
        out = re.search(r"--out (\S+)", build["run"]).group(1)
        self.assertEqual(upload["with"]["path"], out)
        self.assertIn("--require-api-base", build["run"])
        self.assertEqual(build["env"], {"KYR_API_BASE_URL": "${{ vars.KYR_API_BASE_URL }}",         # public variables, not secrets
                                        "KYR_REQUEST_TIMEOUT_SECONDS": "${{ vars.KYR_REQUEST_TIMEOUT_SECONDS }}"})
        order = [i for i, s in enumerate(steps) if ("run" in s and "build_pages.py" in s["run"]) or s.get("uses", "").startswith("actions/upload-pages")]
        self.assertEqual(order, sorted(order))
        self.assertTrue(any("test_pages_build" in s.get("run", "") for s in steps), "the build is tested in CI before it is published")

    def test_no_other_hosting_service_is_referenced(self):
        self.assertNotRegex(self.text.lower(), r"vercel|netlify|surge\.sh|cloudflare pages|render\.com/deploy")


class PagesBuildTests(unittest.TestCase):
    API = "https://kyr-api.onrender.com"

    def build(self, api=None, **kw):
        out = Path(tempfile.mkdtemp(prefix="kyr-pages7b-"))
        self.addCleanup(shutil.rmtree, out, ignore_errors=True)
        bp.build(out / "site", self.API if api is None else api, **kw)
        return out / "site"

    def test_production_output_points_at_the_https_backend_and_nowhere_local(self):
        site = self.build()
        for f in site.rglob("*"):
            if f.is_file():
                text = f.read_text("utf-8", errors="ignore")
                self.assertNotIn("localhost", text, f.name)
                self.assertNotIn("127.0.0.1", text, f.name)
                self.assertNotIn("0.0.0.0", text, f.name)
                for url in re.findall(r"http://[^\s\"'<>)]+", text):
                    self.assertTrue(url.startswith("http://www.w3.org/"), f"{f.name}: {url}")
        html = (site / "index.html").read_text("utf-8")
        self.assertIn(f'<meta name="kyr-api-base" content="{self.API}">', html)
        self.assertIn(f"connect-src 'self' {self.API};", html)

    def test_the_publishing_build_refuses_to_run_without_an_api_base(self):
        out = Path(tempfile.mkdtemp(prefix="kyr-pages7b-"))
        self.addCleanup(shutil.rmtree, out, ignore_errors=True)
        with self.assertRaises(bp.BuildError):
            bp.build(out / "site", "", require_api_base=True)
        self.assertFalse((out / "site").exists())
        self.assertEqual(bp.main(["--out", str(out / "s2"), "--api-base", "", "--require-api-base"]), 1)
        self.assertEqual(bp.main(["--out", str(out / "s3"), "--api-base", self.API, "--require-api-base"]), 0)

    def test_no_secret_in_the_build_environment_reaches_the_output(self):
        site = self.build(env=dict(SENTINELS))        # the build is handed every secret; it must neither read nor publish them
        blob = "\n".join(f.read_text("utf-8", errors="ignore") for f in site.rglob("*") if f.is_file())
        for value in SENTINELS.values():
            self.assertNotIn(value, blob)
        self.assertEqual(bp.scan(site, env=dict(SENTINELS)), [])

    def test_a_nomic_key_in_the_output_fails_the_build(self):
        out = Path(tempfile.mkdtemp(prefix="kyr-scan7b-"))
        self.addCleanup(shutil.rmtree, out, ignore_errors=True)
        (out / "x.js").write_text("var k='nk-" + "a" * 30 + "';")
        self.assertTrue(bp.scan(out, env={}))

    def test_there_is_nothing_that_needs_client_side_routing_so_refresh_and_deep_links_work(self):
        site = self.build()
        self.assertEqual(sorted(p.relative_to(site).as_posix() for p in site.rglob("*") if p.is_file()), [".nojekyll", "index.html", "static/render.js"])
        html = (site / "index.html").read_text("utf-8")
        self.assertNotRegex(html + (site / "static" / "render.js").read_text("utf-8"), r"history\.(pushState|replaceState)|location\.hash|hashchange|popstate")
        for ref in re.findall(r'(?:src|href)="([^"#]+)"', html):
            if not ref.startswith(("http://", "https://", "data:", "mailto:")):
                self.assertFalse(ref.startswith("/"), f"root-absolute asset path breaks a project subpath: {ref}")


class LocalDevelopmentStillWorksTests(tcr.ServerCase):
    def test_the_api_server_still_serves_the_same_page_for_same_origin_local_use(self):
        srv, client = self.server(TG_ENVIRONMENT="development")
        r = client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn('<meta name="kyr-api-base" content="">', r.text)        # empty = same origin: no backend URL is baked in
        self.assertEqual(client.get("/static/render.js").status_code, 200)
        self.assertEqual(client.get("/health").json(), {"status": "ok"})


class GenerationChainUnchangedTests(unittest.TestCase):
    def test_the_cloud_configuration_keeps_groq_then_gemini_then_unavailable_and_never_ollama(self):
        calls = []

        def no_network(*a, **k):
            calls.append((a, k))
            raise AssertionError("no provider may be called by a configuration test")
        orch = providers.ProviderOrchestrator.from_settings(providers.ProviderSettings.from_env(GOOD), http=no_network)
        st = orch.status()
        self.assertEqual(st["order"], ["groq", "cerebras", "gemini", "ollama"])
        by = {p["name"]: p for p in st["providers"]}
        self.assertTrue(by["groq"]["enabled"] and by["gemini"]["enabled"])
        self.assertFalse(by["ollama"]["enabled"])
        self.assertTrue(st["available"])
        none = providers.ProviderOrchestrator.from_settings(
            providers.ProviderSettings.from_env({k: v for k, v in GOOD.items() if k not in ("GROQ_API_KEY", "GEMINI_API_KEY")}), http=no_network)
        self.assertFalse(none.status()["available"])        # no key, Ollama off: the safe "unavailable" answer
        self.assertEqual(calls, [])

    def test_provider_secrets_stay_server_side(self):
        for f in (ROOT / "frontend").rglob("*"):
            if f.is_file():
                text = f.read_text("utf-8", errors="ignore")
                for name in ("GROQ_API_KEY", "GEMINI_API_KEY", "EMBEDDING_API_KEY"):
                    self.assertNotIn(name, text, f.name)


class NoPublicAdministrationTests(tcr.ServerCase):
    def test_approval_refresh_and_lifecycle_administration_are_not_reachable_in_production(self):
        srv, client = self.server(TG_ENVIRONMENT="production")
        self.assertEqual(client.post("/approval/refresh").status_code, 404)
        paths = {getattr(r, "path", "") for r in srv.app.routes}
        for forbidden in ("/lifecycle", "/approve", "/withdraw", "/admin", "/reject", "/supersede"):
            self.assertFalse([p for p in paths if p.startswith(forbidden)], forbidden)


if __name__ == "__main__":
    unittest.main()
