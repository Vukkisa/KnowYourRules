"""Stage 7A (corrected target): the static frontend build for GitHub Pages (scripts/build_pages.py) and its workflow. Offline."""
import importlib.util
import re
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("build_pages", ROOT / "scripts" / "build_pages.py")
bp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bp)
API = "https://kyr-api.example.onrender.com"
INDEX = (ROOT / "frontend" / "index.html").read_text("utf-8")


class PagesBuildTests(unittest.TestCase):
    def build(self, api=API, **kw):
        out = Path(tempfile.mkdtemp(prefix="kyr-pages-"))
        self.addCleanup(shutil.rmtree, out, ignore_errors=True)
        files = bp.build(out / "site", api, env=kw.pop("env", {}), **kw)
        return out / "site", files

    def test_output_is_exactly_the_page_its_script_and_nojekyll(self):
        site, files = self.build()
        self.assertEqual(sorted(files), [".nojekyll", "index.html", "static/render.js"])
        self.assertEqual((site / "static" / "render.js").read_bytes(), (ROOT / "frontend" / "render.js").read_bytes())

    def test_api_origin_lands_in_the_meta_tag_and_csp_and_nowhere_else(self):
        site, _ = self.build()
        html = (site / "index.html").read_text("utf-8")
        self.assertIn(f'<meta name="kyr-api-base" content="{API}">', html)
        csp = re.search(r'Content-Security-Policy" content="([^"]+)"', html).group(1)
        self.assertIn(f"connect-src 'self' {API}", csp)
        self.assertIn("form-action 'none'", csp)
        self.assertEqual(html.count(API), 2)       # meta + CSP, nothing hard-coded in script text

    def test_paths_work_from_a_repository_subpath(self):
        site, _ = self.build()
        html = (site / "index.html").read_text("utf-8")
        local = re.findall(r'(?:src|href)="(/[^"]*)"', html)          # root-absolute references would break under /<repo>/
        self.assertEqual(local, [])
        self.assertIn('src="static/render.js"', html)
        self.assertIn("API_BASE + '/chat'", html)
        self.assertIn("API_BASE + '/status'", html)
        self.assertNotRegex(html, r"fetch\('/")

    def test_page_has_no_client_side_routing(self):
        # a refresh reloads the same file; there is nothing for a 404 fallback to rescue
        self.assertNotRegex(INDEX, r"history\.(pushState|replaceState)|hashchange|popstate")
        # Stage 7C: one raw fetch (inside the timeout wrapper) and exactly two call sites, both prefixed with the API base
        self.assertEqual(len(re.findall(r"\bfetch\(", INDEX)), 1)
        self.assertEqual(len(re.findall(r"fetchWithTimeout\(API_BASE \+ '/(?:chat|status)'", INDEX)), 2)
        self.assertEqual(len(re.findall(r"fetchWithTimeout\(", INDEX)), 3)      # the definition and the two calls

    def test_same_origin_build_is_the_default_for_the_api_served_page(self):
        self.assertIn('<meta name="kyr-api-base" content="">', INDEX)   # the source file, as FastAPI serves it
        site, _ = self.build("")
        html = (site / "index.html").read_text("utf-8")
        self.assertIn('content=""', html)
        self.assertIn("connect-src 'self';", html)

    def test_api_base_must_be_a_public_https_origin(self):
        for bad in ("http://kyr.example.com", "https://kyr.example.com/api", "https://u:p@kyr.example.com", "https://kyr.example.com?x=1",
                    'https://kyr.example.com"><script>', "https://localhost:8000", "kyr.example.com", "javascript:alert(1)"):
            with self.assertRaises(bp.BuildError, msg=bad):
                bp.check_api_base(bad)
        self.assertEqual(bp.check_api_base("https://kyr.example.com/"), "https://kyr.example.com")
        self.assertEqual(bp.check_api_base("http://localhost:8000", allow_local=True), "http://localhost:8000")

    def test_build_refuses_to_publish_anything_that_looks_like_a_credential(self):
        out = Path(tempfile.mkdtemp(prefix="kyr-scan-"))
        self.addCleanup(shutil.rmtree, out, ignore_errors=True)
        samples = {"groq": "gsk_" + "a" * 40, "google": "AIza" + "b" * 35, "aws": "AKIA" + "C" * 16, "name": "GROQ_API_KEY",
                   "bearer": "Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123", "pem": "-----BEGIN PRIVATE KEY-----",
                   "embedding": "EMBEDDING_API_KEY", "r2": "R2_SECRET_ACCESS_KEY"}
        for label, text in samples.items():
            (out / "x.js").write_text(f"var a = '{text}';")
            self.assertTrue(bp.scan(out, env={}), label)
        (out / "x.js").write_text("var a = 'hello';")
        self.assertEqual(bp.scan(out, env={}), [])
        (out / "x.js").write_text("var a = 'a-very-specific-value-1234';")
        self.assertTrue(bp.scan(out, env={"SOME_API_TOKEN": "a-very-specific-value-1234"}))   # the value of a secret-looking variable

    def test_shipped_frontend_contains_no_secret_names_or_values(self):
        for f in (ROOT / "frontend").rglob("*"):
            if f.is_file():
                text = f.read_text("utf-8", errors="ignore")
                for pattern, label in bp.FORBIDDEN_PATTERNS:
                    self.assertIsNone(re.search(pattern, text), f"{f.name}: {label}")

    def test_workflow_is_manual_read_only_and_uses_no_secrets_or_other_hosts(self):
        wf = (ROOT / ".github" / "workflows" / "pages.yml").read_text("utf-8")
        body = "\n".join(line for line in wf.splitlines() if not line.lstrip().startswith("#"))
        self.assertRegex(body, r"(?m)^on:\n  workflow_dispatch:\n")
        self.assertNotRegex(body, r"(?m)^\s+(push|pull_request|pull_request_target|schedule|workflow_run):")
        self.assertNotIn("secrets.", body)
        self.assertIn("vars.KYR_API_BASE_URL", body)
        self.assertRegex(body, r"(?m)^  contents: read$")
        self.assertIn("actions/deploy-pages", body)
        self.assertNotRegex(wf.lower(), r"vercel|netlify|surge|cloudflare pages")

    def test_pages_and_the_other_deployments_do_not_depend_on_vercel(self):
        """The GitHub Pages frontend, the scripts and the Render/OCI files stay free of Vercel. The Vercel backend pilot (decided later)
        lives only in vercel.json, pyproject.toml, .vercelignore, backend/vercel_*.py and deploy/vercel/ (tests/test_vercel_pilot.py)."""
        paths = [p for d in ("deploy", ".github", "scripts") for p in (ROOT / d).rglob("*") if p.is_file() and "vercel" not in p.relative_to(ROOT).parts]
        paths += [ROOT / "requirements-cloud.txt", ROOT / ".env.example"]
        for p in paths:
            self.assertNotIn("vercel", p.read_text("utf-8", errors="ignore").lower(), str(p))


if __name__ == "__main__":
    unittest.main()
