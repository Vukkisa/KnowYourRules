"""Stage 7C: the cold-start experience of the page and its build. Offline: static checks of frontend/index.html and the Pages build output.
(The behaviour in a real browser was checked separately against a local stand-in backend; see the Stage 7C report.)"""
import importlib.util
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "frontend" / "index.html").read_text("utf-8")
spec = importlib.util.spec_from_file_location("build_pages_7c", ROOT / "scripts" / "build_pages.py")
bp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bp)


class ColdStartPageTests(unittest.TestCase):
    def test_there_is_an_accessible_connection_notice_and_a_labelled_retry_button(self):
        self.assertRegex(INDEX, r'<div class="conn" id="conn" role="status" aria-live="polite" hidden>')
        self.assertRegex(INDEX, r'<button type="button" id="conn-retry" hidden>Try again</button>')
        self.assertRegex(INDEX, r"\.conn button\{[^}]*min-height:44px")                 # a comfortable touch target
        self.assertRegex(INDEX, r"\.conn\{[^}]*flex-wrap:wrap")                          # wraps on a narrow screen
        self.assertIn(".conn button:focus-visible", INDEX)

    def test_the_wait_is_bounded_by_a_configurable_timeout_and_uses_abort(self):
        self.assertIn('<meta name="kyr-timeout-seconds" content="">', INDEX)
        self.assertRegex(INDEX, r"Math\.min\(300, Math\.max\(5, raw\)\) : 120\) \* 1000")
        self.assertRegex(INDEX, r"new AbortController\(\)")
        self.assertRegex(INDEX, r"setTimeout\(\(\) => ctl\.abort\(\), ms\)")
        self.assertRegex(INDEX, r"fetchWithTimeout\(API_BASE \+ '/chat'")
        self.assertRegex(INDEX, r"fetchWithTimeout\(API_BASE \+ '/status'")

    def test_the_wording_is_honest_and_promises_no_duration(self):
        notes = " ".join(re.findall(r"showConn\('([^']+)'", INDEX))
        for needle in ("Connecting to the service", "may be waking up", "nothing has been answered", "was not answered"):
            self.assertIn(needle.lower(), (notes + " " + INDEX).lower())
        self.assertNotRegex(notes, r"\b\d+\s*(seconds?|secs?|minutes?|mins?)\b")           # no promised startup time
        self.assertNotRegex(notes.lower(), r"takes about|usually|will be ready in")

    def test_a_failed_request_is_a_connection_problem_not_an_answer(self):
        self.assertIn("connection: 'Connection problem'", INDEX)
        self.assertRegex(INDEX, r"addCard\('connection', timedOut")
        self.assertIn("and nothing below is an answer", INDEX)
        # the service's own refusals arrive as normal replies of their own kinds and are not mistaken for connection failures
        for kind in ("restricted", "unavailable", "no_support", "out_of_scope"):
            self.assertIn(f"{kind}:", INDEX)
        self.assertIn("not a legal refusal", INDEX)

    def test_a_question_is_never_re_sent_by_itself(self):
        calls = re.findall(r"\bask\(", INDEX)
        # the definition, the submit handler, and the user's click on "Try again": nothing else (no timer, no loop)
        self.assertEqual(len(calls), 3)
        retry = re.search(r"connRetry\.addEventListener\('click'.*?\n  \}\);", INDEX, re.S).group(0)
        self.assertIn("ask(q)", retry)
        self.assertRegex(retry, r"if\(busy \|\| starting\) return")
        for timer in re.findall(r"setTimeout\(([^;]*)\);", INDEX):
            self.assertNotIn("ask(", timer)
        self.assertRegex(INDEX, r"failedQuestion = null;")                                 # cleared before each new question: at most one retry candidate

    def test_status_is_read_once_with_the_full_wait_and_never_retried_by_itself(self):
        # a retry while a cold service is still starting could start another copy of it and spend the CPU quota twice
        self.assertNotIn("attempt", INDEX)
        self.assertNotRegex(INDEX, r"setTimeout\([^;]*loadStatus")
        self.assertEqual(len(re.findall(r"loadStatus\(", INDEX)), 3)                       # the definition, the page load, the user's "Try again"
        self.assertRegex(INDEX, r"fetchWithTimeout\(API_BASE \+ '/status', \{\}, REQUEST_TIMEOUT_MS\)")
        polls = re.findall(r"fetchWithTimeout\(API_BASE \+ '/(\w+)'", INDEX)
        self.assertEqual(sorted(polls), ["chat", "status"])

    def test_the_default_wait_covers_a_cold_start_and_the_service_start_message_is_shown(self):
        self.assertIn("const START_MESSAGE = 'The service is starting; the first request may take a little longer.';", INDEX)
        self.assertGreaterEqual(INDEX.count("START_MESSAGE"), 3)                            # defined, shown while waiting for /status, shown while waiting for /chat
        self.assertNotRegex(INDEX, r"START_MESSAGE[^;\n]*(ready|is up|online)")             # never claims readiness before the API answers

    def test_nothing_can_be_sent_while_a_request_or_the_first_status_check_is_pending(self):
        self.assertRegex(INDEX, r"if\(!text \|\| busy \|\| starting\) return;")
        submit = re.search(r"form\.addEventListener\('submit'.*?\n  \}\);", INDEX, re.S).group(0)
        self.assertLess(submit.index("if(busy || starting) return;"), submit.index("input.value = ''"))     # the typed text is kept, not lost
        self.assertRegex(INDEX, r"starting = true; sendBtn\.disabled = true;")
        self.assertRegex(INDEX, r"finally \{\s*starting = false;")

    def test_a_timeout_gives_a_useful_error_and_a_manual_retry_only(self):
        self.assertIn("The service did not respond in time. It may still be starting.", INDEX)
        self.assertIn("The service did not answer in time. It may still be starting.", INDEX)
        self.assertIn("use Try again when you are ready", INDEX)

    def test_nothing_new_writes_unsanitised_html(self):
        stripped = INDEX.replace("dots.innerHTML = '<span></span><span></span><span></span>';", "")
        assigned = re.findall(r"innerHTML\s*=\s*([^;]+);", stripped)
        self.assertEqual(assigned, ["html"])                                               # the pre-existing, sanitised path only
        self.assertIn("connText.textContent = text", INDEX)

    def test_reduced_motion_and_the_live_region_are_kept(self):
        self.assertIn("prefers-reduced-motion: reduce", INDEX)
        self.assertIn('aria-live="polite"', INDEX)


class BuildTimeoutTests(unittest.TestCase):
    def build(self, **kw):
        out = Path(tempfile.mkdtemp(prefix="kyr-7c-pages-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(out, ignore_errors=True))
        bp.build(out / "site", "https://api.example.invalid", env={}, **kw)
        return (out / "site" / "index.html").read_text("utf-8")

    def test_the_default_build_keeps_the_pages_default(self):
        html = self.build()
        self.assertIn('<meta name="kyr-timeout-seconds" content="">', html)

    def test_a_valid_timeout_is_written_into_the_page(self):
        self.assertIn('<meta name="kyr-timeout-seconds" content="45">', self.build(timeout_seconds="45"))
        self.assertIn('content="12.5"', self.build(timeout_seconds="12.5"))

    def test_an_invalid_timeout_fails_the_build(self):
        for bad in ("0", "4", "301", "abc", "-5", "nan", "1e9"):
            with self.assertRaises(bp.BuildError, msg=bad):
                self.build(timeout_seconds=bad)

    def test_the_build_still_refuses_credentials_and_keeps_relative_assets(self):
        html = self.build()
        self.assertIn('src="static/render.js"', html)
        self.assertNotIn('src="/static/', html)
        self.assertIn("connect-src 'self' https://api.example.invalid;", html)

    def test_the_cli_flag_and_environment_variable_are_wired(self):
        src = (ROOT / "scripts" / "build_pages.py").read_text("utf-8")
        self.assertIn("KYR_REQUEST_TIMEOUT_SECONDS", src)
        self.assertIn("--request-timeout-seconds", src)
        wf = (ROOT / ".github" / "workflows" / "pages.yml").read_text("utf-8")
        self.assertIn("KYR_REQUEST_TIMEOUT_SECONDS: ${{ vars.KYR_REQUEST_TIMEOUT_SECONDS }}", wf)

    def test_no_placeholder_api_origin_is_part_of_the_production_workflow(self):
        wf = (ROOT / ".github" / "workflows" / "pages.yml").read_text("utf-8")
        self.assertNotRegex(wf, r"onrender\.com|example\.(com|invalid)|\.invalid")
        self.assertIn("--require-api-base", wf)


if __name__ == "__main__":
    unittest.main()
