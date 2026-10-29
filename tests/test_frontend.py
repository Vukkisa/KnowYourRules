"""Static regression checks for F-11 (frontend HTML sanitization). Offline, no browser.

The behaviour itself (malicious HTML, event handlers, javascript: URLs, ordinary Markdown) is
checked by tests/frontend/sanitize_test.html, which runs the real frontend/render.js in a browser.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
RENDER = (ROOT / "frontend" / "render.js").read_text(encoding="utf-8")
TEST_PAGE = (ROOT / "tests" / "frontend" / "sanitize_test.html").read_text(encoding="utf-8")


def script_tags(html):
    return re.findall(r"<script\b[^>]*\bsrc=\"([^\"]+)\"[^>]*>", html), re.findall(r"<script\b[^>]*\bsrc=[^>]*>", html)


class FrontendSanitizationTests(unittest.TestCase):
    def test_marked_output_is_never_assigned_to_innerHTML_directly(self):
        self.assertNotRegex(INDEX, r"innerHTML\s*=\s*marked\.parse")
        self.assertNotRegex(RENDER, r"innerHTML")

    def test_every_innerHTML_assignment_is_static_or_sanitized(self):
        assignments = re.findall(r"innerHTML\s*=\s*([^;]+);", INDEX)
        allowed = {"html", "'<span></span><span></span><span></span>'"}
        self.assertTrue(assignments)
        for value in assignments:
            self.assertIn(value.strip(), allowed, value)

    def test_render_sanitizes_with_dompurify_and_refuses_without_it(self):
        self.assertIn("DOMPurify.sanitize(marked.parse(text)", RENDER)
        self.assertIn("FORBID_TAGS: FORBIDDEN_TAGS", RENDER)
        for tag in ("form", "input", "button"):
            self.assertIn(f"'{tag}'", RENDER)
        self.assertRegex(RENDER, r"!window\.DOMPurify[^)]*\)\s*return null")
        self.assertIn("typeof renderAssistantMarkdown === 'function'", INDEX)
        self.assertRegex(INDEX, r"if\(html === null\) el\.textContent = text;")

    def test_cdn_scripts_are_pinned_with_integrity_and_load_before_render(self):
        srcs, tags = script_tags(INDEX)
        self.assertEqual(srcs, [
            "https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js",
            "https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.4.16/purify.min.js",
            "/static/render.js",
        ])
        for tag in tags[:2]:
            self.assertRegex(tag, r'integrity="sha512-[A-Za-z0-9+/=]+"')
            self.assertIn('crossorigin="anonymous"', tag)

    def test_browser_test_page_uses_the_same_pinned_scripts(self):
        index_cdn = [t for t in script_tags(INDEX)[1] if "cdnjs" in t]
        page_cdn = [t for t in script_tags(TEST_PAGE)[1] if "cdnjs" in t]
        self.assertEqual(index_cdn, page_cdn)
        self.assertIn('src="../../frontend/render.js"', TEST_PAGE)


if __name__ == "__main__":
    unittest.main()
