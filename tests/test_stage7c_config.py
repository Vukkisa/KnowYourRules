"""Stage 7C: production CORS policy, the mandatory snapshot pin and the cloud environment checker. Offline; no network."""
import importlib.util
import unittest
from pathlib import Path

from backend import runtime_config as rc

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_cloud_env_7c", ROOT / "scripts" / "check_cloud_env.py")
cce = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cce)

PAGES = "https://someone.github.io"
PROD = {"TG_ENVIRONMENT": "production"}
GOOD = {"TG_ENVIRONMENT": "production", "TG_GROUNDED_ANSWERS": "1", "OLLAMA_ENABLED": "false", "TG_SNAPSHOT_STORE": "r2", "R2_ACCOUNT_ID": "acct",
        "R2_BUCKET": "b", "R2_ACCESS_KEY_ID": "k", "R2_SECRET_ACCESS_KEY": "s", "EMBEDDING_PROVIDER": "nomic_atlas", "EMBEDDING_MODEL": "nomic-embed-text-v1.5",
        "EMBEDDING_API_KEY": "fakefakefake", "TG_CORS_ORIGINS": PAGES, "TG_SNAPSHOT_PIN_SHA256": "ab" * 32, "GROQ_API_KEY": "fakefakefake"}


class CorsPolicyTests(unittest.TestCase):
    def cors(self, value=None, env="production"):
        e = {"TG_ENVIRONMENT": env} if env else {}
        if value is not None:
            e["TG_CORS_ORIGINS"] = value
        return rc.cors_origins(e), rc.cors_problems(e)

    def test_an_explicit_pages_origin_is_accepted_in_production(self):
        (ok, bad), problems = self.cors(PAGES)
        self.assertEqual((ok, bad, problems), ([PAGES], [], []))

    def test_a_trailing_slash_is_normalised_but_a_path_is_refused(self):
        self.assertEqual(self.cors(PAGES + "/")[0], ([PAGES], []))
        (ok, bad), problems = self.cors(PAGES + "/repo")
        self.assertEqual((ok, bad), ([], [PAGES + "/repo"]))
        self.assertEqual(len(problems), 2)                       # a bad entry, and nothing valid left

    def test_missing_or_empty_configuration_is_an_error_in_production_and_staging(self):
        for env in ("production", "staging"):
            for value in (None, "", "   ", " , ,"):
                (ok, bad), problems = self.cors(value, env)
                self.assertEqual((ok, bad), ([], []), (env, value))
                self.assertTrue(any("required in production" in p for p in problems), (env, value))

    def test_nothing_is_required_in_development_or_when_the_environment_is_unset(self):
        for env in ("development", None, "test"):
            self.assertEqual(self.cors(None, env)[1], [], env)

    def test_wildcards_are_refused_everywhere(self):
        for value in ("*", "https://*.github.io", "https://someone.github.io,*"):
            for env in ("production", "development"):
                (ok, bad), _ = self.cors(value, env)
                self.assertNotIn("*", ok)
                self.assertTrue(any("*" in b for b in bad), (value, env))

    def test_localhost_and_loopback_are_refused_in_production_and_allowed_in_development(self):
        local = ("http://localhost:5173", "http://127.0.0.1:8000", "http://[::1]:3000", "https://localhost", "http://app.localhost:3000")
        for item in local:
            (ok, bad), problems = self.cors(item, "production")
            self.assertEqual((ok, bad), ([], [item]), item)
            self.assertTrue(problems, item)
        for item in ("http://localhost:5173", "http://127.0.0.1:8000", "http://[::1]:3000", "http://app.localhost:3000"):
            (ok, bad), problems = self.cors(item, "development")
            self.assertEqual((ok, bad, problems), ([item], [], []), item)

    def test_a_mixed_list_keeps_only_the_valid_production_origins(self):
        (ok, bad), problems = self.cors(f"{PAGES}, http://localhost:5173, https://other.example, *", "production")
        self.assertEqual(ok, [PAGES, "https://other.example"])
        self.assertEqual(sorted(bad), ["*", "http://localhost:5173"])
        self.assertEqual(len(problems), 1)                       # the rejected entries are reported; a valid origin remains

    def test_malformed_origins_are_refused(self):
        for bad in ("someone.github.io", "ftp://someone.github.io", "https://", "https://user:pw@someone.github.io", "https://someone.github.io?x=1",
                    "https://someone.github.io#frag", "http://someone.github.io", "https://someone.github.io:0", "javascript:alert(1)", 'https://a"b.example'):
            (ok, rej), problems = self.cors(bad, "production")
            self.assertEqual(ok, [], bad)
            self.assertTrue(problems, bad)

    def test_duplicates_are_collapsed(self):
        self.assertEqual(self.cors(f"{PAGES}, {PAGES}/, {PAGES}")[0][0], [PAGES])

    def test_a_dotenv_file_cannot_open_production_cors(self):
        # the policy reads only the process environment passed in; there is no default that substitutes a permissive value
        self.assertEqual(rc.cors_origins({"TG_ENVIRONMENT": "production"}), ([], []))


class CheckerPolicyTests(unittest.TestCase):
    def errs(self, **change):
        env = {**GOOD, **change}
        r = cce.check({k: v for k, v in env.items() if v is not None})
        return {e["name"] for e in r["errors"]}, r

    def test_the_complete_environment_passes(self):
        names, r = self.errs()
        self.assertEqual(names, set())
        self.assertTrue(r["ok"])

    def test_missing_cors_pin_and_localhost_are_startup_errors(self):
        self.assertIn("TG_CORS_ORIGINS", self.errs(TG_CORS_ORIGINS=None)[0])
        self.assertIn("TG_CORS_ORIGINS", self.errs(TG_CORS_ORIGINS="")[0])
        self.assertIn("TG_CORS_ORIGINS", self.errs(TG_CORS_ORIGINS="http://localhost:5173")[0])
        self.assertIn("TG_CORS_ORIGINS", self.errs(TG_CORS_ORIGINS="*")[0])
        self.assertIn("TG_SNAPSHOT_PIN_SHA256", self.errs(TG_SNAPSHOT_PIN_SHA256=None)[0])
        self.assertIn("TG_SNAPSHOT_PIN_SHA256", self.errs(TG_SNAPSHOT_PIN_SHA256="short")[0])

    def test_restore_settings_are_validated_by_the_checker(self):
        self.assertIn("TG_SNAPSHOT_*", self.errs(TG_SNAPSHOT_STARTUP_TIMEOUT_SECONDS="0")[0])
        self.assertNotIn("TG_SNAPSHOT_*", self.errs(TG_SNAPSHOT_STARTUP_TIMEOUT_SECONDS="45")[0])

    def test_the_checker_never_prints_values(self):
        _, r = self.errs(TG_CORS_ORIGINS="http://localhost:5173", EMBEDDING_API_KEY="SENTINEL-SECRET-VALUE-1234")
        self.assertNotIn("SENTINEL-SECRET-VALUE-1234", repr(r))
        self.assertNotIn("localhost:5173", repr(r["errors"]))


if __name__ == "__main__":
    unittest.main()
