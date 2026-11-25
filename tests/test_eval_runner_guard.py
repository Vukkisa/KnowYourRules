"""The Preview-only guard in eval/run_final_eval.py: Production is refused before any request, Preview is accepted, nothing overrides it."""
import importlib.util
import io
import json
import re
import threading
import subprocess
import sys
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("run_final_eval", ROOT / "eval" / "run_final_eval.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)

TEAM = "jayanths-projects-93d42e21"
PROD_API = "knowyourrules-api.vercel.app"
PREVIEW_DEPLOYMENT = f"knowyourrules-j4s7e0629-{TEAM}.vercel.app"  # a real Preview deployment of this project
PREVIEW_BRANCH_ALIAS = f"knowyourrules-api-git-feature-telangana-assistant-{TEAM}.vercel.app"
SECRET = "TESTONLYnotarealsecret0123456789ab"  # a made-up value, not a credential


class _NoRequest:
    """Fails the test if anything tries to send a request: the guard must refuse first."""

    def __enter__(self):
        self.run = mock.patch.object(runner.subprocess, "run", side_effect=AssertionError("a request was sent"))
        self.conn = mock.patch("socket.create_connection", side_effect=AssertionError("a connection was opened"))
        self.run.start(); self.conn.start()
        return self

    def __exit__(self, *exc):
        self.run.stop(); self.conn.stop()


class ProductionIsRefused(unittest.TestCase):
    def test_the_current_production_api_host_is_listed(self):
        self.assertIn(PROD_API, runner.PRODUCTION_HOSTS)
        self.assertIn(f"knowyourrules-api-{TEAM}.vercel.app", runner.PRODUCTION_HOSTS)

    def test_every_listed_production_host_is_refused_in_every_form(self):
        for host in sorted(runner.PRODUCTION_HOSTS):
            for url in (f"https://{host}", f"https://{host}/", f"https://{host}//", f"https://{host}/chat", f"https://{host}/chat/",
                        f"https://{host}/a/b?x=1#y", f"http://{host}", f"http://{host}/chat", f"HTTPS://{host.upper()}/",
                        f"https://{host}.", f"https://{host}:443", f"https://{host}:8080/chat", f"ftp://{host}", host, f"{host}/chat",
                        f"//{host}", f"https://user:pw@{host}", f"https://{host}@{PREVIEW_DEPLOYMENT}", f"https://x.{host}",
                        f"https://{PREVIEW_DEPLOYMENT}/{host}", f"https://{PREVIEW_DEPLOYMENT}?next={host}"):
                with self.subTest(url=url), self.assertRaises(runner.UnsafeBaseURL) as cm:
                    runner.validate_preview_base_url(url)
                self.assertIn("Production hostname", str(cm.exception))

    def test_production_is_refused_before_any_request_is_sent(self):
        with _NoRequest():
            for url in (f"https://{PROD_API}", f"https://{PROD_API}/", f"http://{PROD_API}/chat"):
                with self.subTest(url=url), self.assertRaises(runner.UnsafeBaseURL):
                    runner.Live(url, 0.0)

    def test_main_prints_a_clear_preview_only_error_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d, _NoRequest():
            out = Path(d) / "out.json"
            for mode in ("live", "local"):  # checked in either mode
                err = io.StringIO()
                with mock.patch.object(sys, "argv", ["run_final_eval.py", "--mode", mode, "--base-url", f"https://{PROD_API}/", "--out", str(out)]), \
                        mock.patch.object(runner, "run", side_effect=AssertionError("the run started")):
                    with self.assertRaises(SystemExit) as cm, redirect_stderr(err):
                        runner.main()
                self.assertNotIn(cm.exception.code, (0, None))
                text = str(cm.exception.code)
                self.assertIn("REFUSED", text)
                self.assertIn("Preview-only", text)
                self.assertIn("Production hostname", text)
                self.assertFalse(out.exists())


class MalformedOrAmbiguousIsRefused(unittest.TestCase):
    def test_refused(self):
        cases = {
            "empty": "", "none": None, "number": 5, "whitespace only": "   ", "no scheme": PREVIEW_DEPLOYMENT, "scheme only": "https://",
            "no host": "https:///chat", "plain words": "not a url", "http preview": f"http://{PREVIEW_DEPLOYMENT}",
            "ftp preview": f"ftp://{PREVIEW_DEPLOYMENT}", "protocol-relative": f"//{PREVIEW_DEPLOYMENT}",
            "leading space": f" https://{PREVIEW_DEPLOYMENT}", "trailing space": f"https://{PREVIEW_DEPLOYMENT} ",
            "inner space": f"https://{PREVIEW_DEPLOYMENT} /x", "newline": f"https://{PREVIEW_DEPLOYMENT}\n", "tab": f"https://{PREVIEW_DEPLOYMENT}\t",
            "backslash": f"https://{PREVIEW_DEPLOYMENT}\\chat", "percent": f"https://{PREVIEW_DEPLOYMENT}/%2e", "non-ascii": f"https://{PREVIEW_DEPLOYMENT}/é",
            "path": f"https://{PREVIEW_DEPLOYMENT}/chat", "root plus path": f"https://{PREVIEW_DEPLOYMENT}/a/", "double slash": f"https://{PREVIEW_DEPLOYMENT}//",
            "query": f"https://{PREVIEW_DEPLOYMENT}?a=1", "fragment": f"https://{PREVIEW_DEPLOYMENT}#a", "bare question mark": f"https://{PREVIEW_DEPLOYMENT}?",
            "params": f"https://{PREVIEW_DEPLOYMENT};a", "port": f"https://{PREVIEW_DEPLOYMENT}:443", "bad port": f"https://{PREVIEW_DEPLOYMENT}:abc",
            "user-info": f"https://user@{PREVIEW_DEPLOYMENT}", "trailing dot": f"https://{PREVIEW_DEPLOYMENT}.",
            "extra suffix": f"https://{PREVIEW_DEPLOYMENT}.evil.com", "extra prefix": f"https://x.{PREVIEW_DEPLOYMENT}",
            "look-alike": f"https://{PREVIEW_DEPLOYMENT.replace('vercel', 'verce1')}", "other host": "https://example.com",
            "localhost": "http://localhost:8000", "ip": "https://127.0.0.1", "other team": "https://knowyourrules-j4s7e0629-someone-else.vercel.app",
            "other project": f"https://deploy-92hk1m864-{TEAM}.vercel.app", "other project alias": "https://deploy-five-roan-83.vercel.app",
            "short hash": f"https://knowyourrules-j4s7e062-{TEAM}.vercel.app", "long hash": f"https://knowyourrules-j4s7e06299-{TEAM}.vercel.app",
            "main branch alias": f"https://knowyourrules-api-git-main-{TEAM}.vercel.app", "master branch alias": f"https://knowyourrules-api-git-master-{TEAM}.vercel.app",
            "empty branch alias": f"https://knowyourrules-api-git--{TEAM}.vercel.app",
        }
        with _NoRequest():
            for name, url in cases.items():
                with self.subTest(case=name), self.assertRaises(runner.UnsafeBaseURL):
                    runner.validate_preview_base_url(url)
                with self.subTest(case=f"{name} (Live)"), self.assertRaises(runner.UnsafeBaseURL):
                    runner.Live(url, 0.0)


class PreviewIsAccepted(unittest.TestCase):
    def test_preview_deployment_urls(self):
        for host in (PREVIEW_DEPLOYMENT, f"knowyourrules-ojpbm6bj2-{TEAM}.vercel.app", f"knowyourrules-mxcwyuodw-{TEAM}.vercel.app"):
            for url in (f"https://{host}", f"https://{host}/", f"HTTPS://{host.upper()}"):
                with self.subTest(url=url):
                    self.assertEqual(runner.validate_preview_base_url(url), f"https://{host}")

    def test_preview_branch_alias(self):
        for host in (PREVIEW_BRANCH_ALIAS, f"knowyourrules-api-git-fix-1-{TEAM}.vercel.app"):
            self.assertEqual(runner.validate_preview_base_url(f"https://{host}/"), f"https://{host}")

    def test_live_posts_only_to_the_preview_chat_url(self):
        live = runner.Live(f"https://{PREVIEW_DEPLOYMENT}/", 0.0, SECRET)
        self.assertEqual(live.url, f"https://{PREVIEW_DEPLOYMENT}/chat")
        fake = mock.Mock(stdout='HTTP/2 200\r\n\r\n{"kind": "answer", "response": "ok"}')
        with mock.patch.object(runner.subprocess, "run", return_value=fake) as run:
            status, data = live.ask("q", "s")
        self.assertEqual((status, data["kind"]), (200, "answer"))
        self.assertIn(f"https://{PREVIEW_DEPLOYMENT}/chat", run.call_args.args[0])

    def test_main_lets_a_preview_url_through_the_guard(self):
        class Started(Exception):
            pass

        with mock.patch.object(sys, "argv", ["run_final_eval.py", "--mode", "live", "--base-url", f"https://{PREVIEW_DEPLOYMENT}/", "--out", "unused.json"]), \
                mock.patch.dict("os.environ", {runner.BYPASS_ENV: SECRET}), mock.patch.object(runner, "run", side_effect=Started) as run:
            with self.assertRaises(Started):
                runner.main()
        self.assertEqual(run.call_args.args[1], f"https://{PREVIEW_DEPLOYMENT}")


class NoOverride(unittest.TestCase):
    def test_no_flag_environment_variable_or_function_bypasses_the_guard(self):
        for flag in ("--allow-production", "--force", "--production", "--unsafe", "--yes", "--skip-guard"):
            with self.subTest(flag=flag), mock.patch.object(sys, "argv", ["run_final_eval.py", "--mode", "live", "--base-url", f"https://{PROD_API}", "--out", "x.json", flag]), \
                    redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                runner.main()
            self.assertEqual(cm.exception.code, 2)  # argparse: unrecognised argument
        source = (ROOT / "eval" / "run_final_eval.py").read_text()
        reads = set(re.findall(r"os\.environ(?:\.get)?\(\s*[\"'](\w+)", source)) | set(re.findall(r"environ\.get\(BYPASS_ENV", source))
        self.assertFalse({"ALLOW_PRODUCTION", "FORCE"} & reads)  # the only variable read to decide anything is the bypass secret, which cannot allow Production

    def test_an_environment_variable_does_not_change_the_result(self):
        with mock.patch.dict("os.environ", {"ALLOW_PRODUCTION": "1", "FORCE": "1", "TG_ALLOW_PRODUCTION_EVAL": "1"}):
            with self.assertRaises(runner.UnsafeBaseURL):
                runner.validate_preview_base_url(f"https://{PROD_API}")


def _reply(status="HTTP/2 200", body=None):
    return mock.Mock(stdout=f"{status}\r\ncontent-type: application/json\r\n\r\n{json.dumps(body if body is not None else {'kind': 'out_of_scope', 'response': 'ok'})}")


class ProtectionBypassHeader(unittest.TestCase):
    def test_the_secret_goes_to_curl_on_stdin_as_the_official_header_and_nowhere_else(self):
        live = runner.Live(f"https://{PREVIEW_DEPLOYMENT}", 0.0, SECRET)
        with mock.patch.object(runner.subprocess, "run", return_value=_reply()) as run:
            live.ask("q", "s")
        argv, kwargs = run.call_args.args[0], run.call_args.kwargs
        self.assertEqual(kwargs["input"], f'header = "x-vercel-protection-bypass: {SECRET}"\n')
        self.assertEqual(argv[argv.index("-K") + 1], "-")  # curl reads that config from stdin
        self.assertFalse([a for a in argv if SECRET in a], "the secret is on the command line")
        self.assertNotIn(SECRET, live.url)
        self.assertNotIn("env", kwargs)
        self.assertNotIn(SECRET, repr(live))

    def test_a_real_curl_delivers_the_header_and_the_secret_is_never_in_its_arguments(self):
        seen = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                seen["header"] = self.headers.get("x-vercel-protection-bypass")
                seen["path"] = self.path
                seen["body"] = self.rfile.read(int(self.headers.get("content-length", 0))).decode()
                out = json.dumps({"kind": "out_of_scope", "response": "ok"}).encode()
                self.send_response(200); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(out)))
                self.end_headers(); self.wfile.write(out)

            def log_message(self, *a):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            live = runner.Live(f"https://{PREVIEW_DEPLOYMENT}", 0.0, SECRET)
            live.url = live._sends_to = f"http://127.0.0.1:{server.server_port}/chat"  # test-only: a loopback server instead of the Preview
            argvs, real = [], subprocess.run
            with mock.patch.object(runner.subprocess, "run", side_effect=lambda argv, **kw: (argvs.append(list(argv)), real(argv, **kw))[1]):
                status, data = live.ask("hello", "sid")
        finally:
            server.shutdown(); server.server_close()
        self.assertEqual((status, data["kind"]), (200, "out_of_scope"))
        self.assertEqual(seen["header"], SECRET)
        self.assertEqual(seen["path"], "/chat")
        self.assertEqual(json.loads(seen["body"]), {"message": "hello", "session_id": "sid"})
        self.assertFalse([a for argv in argvs for a in argv if SECRET in a])

    def test_the_secret_is_only_ever_sent_to_the_validated_preview_address(self):
        live = runner.Live(f"https://{PREVIEW_DEPLOYMENT}", 0.0, SECRET)
        with mock.patch.object(runner.subprocess, "run", side_effect=AssertionError("sent")) as run:
            for other in (f"https://{PROD_API}/chat", "https://example.com/chat", f"https://{PREVIEW_DEPLOYMENT}/other"):
                live.url = other
                with self.subTest(url=other), self.assertRaises(RuntimeError):
                    live.ask("q", "s")
        run.assert_not_called()

    def test_the_header_is_not_followed_across_redirects(self):
        source = Path(runner.__file__).read_text()  # no -L / --location: curl never re-sends the header to a redirect target
        self.assertNotIn("--location", source)
        self.assertNotIn('"-L"', source)


class MissingOrBadSecret(unittest.TestCase):
    def _main(self, argv, env=None):
        err = io.StringIO()
        with mock.patch.object(sys, "argv", ["run_final_eval.py", *argv]), mock.patch.dict("os.environ", env or {}, clear=False), \
                redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            runner.main()
        return str(cm.exception.code)

    def test_a_missing_secret_stops_the_run_before_any_request(self):
        with tempfile.TemporaryDirectory() as d, _NoRequest(), mock.patch.dict("os.environ"), \
                mock.patch.object(runner, "run", side_effect=AssertionError("the run started")):
            runner.os.environ.pop(runner.BYPASS_ENV, None)
            out = Path(d) / "out.json"
            msg = self._main(["--mode", "live", "--base-url", f"https://{PREVIEW_DEPLOYMENT}", "--out", str(out)])
            self.assertFalse(out.exists())
        self.assertIn("STOPPED", msg)
        self.assertIn(runner.BYPASS_ENV, msg)
        self.assertIn("no flag", msg)

    def test_empty_and_malformed_secrets_are_refused_without_echoing_them(self):
        for bad in ("", "   ", "short", f"{SECRET}\n", f"{SECRET} x", f'{SECRET}"', f"{SECRET}\\", "x" * 300, "é" * 20, f"{SECRET}\r\nheader = \"x: y\""):
            with self.subTest(value=repr(bad)), self.assertRaises(runner.MissingBypassSecret) as cm:
                runner.read_bypass_secret({runner.BYPASS_ENV: bad})
            if bad.strip():
                self.assertNotIn(bad.strip(), str(cm.exception))
        with self.assertRaises(runner.MissingBypassSecret):
            runner.read_bypass_secret({})

    def test_there_is_no_command_line_flag_for_the_secret(self):
        for flag in ("--secret", "--bypass-secret", "--protection-bypass", "--token"):
            with self.subTest(flag=flag), mock.patch.object(sys, "argv", ["run_final_eval.py", "--mode", "live", "--base-url", f"https://{PREVIEW_DEPLOYMENT}", "--out", "x.json", flag, SECRET]), \
                    redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                runner.main()
            self.assertEqual(cm.exception.code, 2)

    def test_local_mode_does_not_need_a_secret(self):
        with mock.patch.dict("os.environ"), mock.patch.object(runner, "run", side_effect=RuntimeError("reached run")):
            runner.os.environ.pop(runner.BYPASS_ENV, None)
            with mock.patch.object(sys, "argv", ["run_final_eval.py", "--mode", "local", "--out", "x.json"]), self.assertRaisesRegex(RuntimeError, "reached run"):
                runner.main()


class ProductionStaysBlockedWithASecret(unittest.TestCase):
    def test_production_is_refused_whatever_the_environment_holds(self):
        with _NoRequest(), mock.patch.dict("os.environ", {runner.BYPASS_ENV: SECRET}):
            for url in (f"https://{PROD_API}", f"https://{PROD_API}/", f"http://{PROD_API}/chat", f"https://knowyourrules-fmn74wo39-{TEAM}.vercel.app"):
                with self.subTest(url=url):
                    with self.assertRaises(runner.UnsafeBaseURL):
                        runner.Live(url, 0.0)
                    with self.assertRaises(runner.UnsafeBaseURL):
                        runner.Live(url, 0.0, SECRET)
                    err = io.StringIO()
                    with mock.patch.object(sys, "argv", ["run_final_eval.py", "--mode", "live", "--base-url", url, "--out", "x.json"]), \
                            redirect_stderr(err), self.assertRaises(SystemExit) as cm:
                        runner.main()
                    self.assertIn("Preview-only", str(cm.exception.code))
                    self.assertNotIn(SECRET, str(cm.exception.code) + err.getvalue())

    def test_production_is_refused_first_even_when_the_secret_is_missing(self):
        with _NoRequest(), mock.patch.dict("os.environ"):
            runner.os.environ.pop(runner.BYPASS_ENV, None)
            with self.assertRaises(runner.UnsafeBaseURL):
                runner.Live(f"https://{PROD_API}", 0.0)


class SecretIsNeverLoggedOrWritten(unittest.TestCase):
    ARGS = ["--mode", "live", "--only", "OOS01", "--pace", "0"]

    def _run(self, reply):
        out_buf, err_buf = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.json"
            argv = ["run_final_eval.py", *self.ARGS, "--base-url", f"https://{PREVIEW_DEPLOYMENT}", "--out", str(out)]
            with mock.patch.object(sys, "argv", argv), mock.patch.dict("os.environ", {runner.BYPASS_ENV: SECRET}), \
                    mock.patch.object(runner.subprocess, "run", return_value=reply) as run, \
                    mock.patch("sys.stdout", out_buf), redirect_stderr(err_buf):
                try:
                    runner.main()
                    code = None
                except SystemExit as e:
                    code = str(e.code)
            written = out.read_text() if out.exists() else None
        return code, written, out_buf.getvalue(), err_buf.getvalue(), run

    def test_a_server_that_echoes_the_secret_does_not_reach_the_results_or_the_console(self):
        echo = _reply(body={"kind": "out_of_scope", "response": f"echo of the header: {SECRET}"})
        code, written, stdout, stderr, run = self._run(echo)
        self.assertIsNone(code)
        self.assertIsNotNone(written)
        for name, text in (("results file", written), ("stdout", stdout), ("stderr", stderr)):
            self.assertNotIn(SECRET, text, name)
            self.assertNotIn(runner.BYPASS_HEADER, text, name)
        self.assertEqual(run.call_args.kwargs["input"], f'header = "{runner.BYPASS_HEADER}: {SECRET}"\n')
        self.assertIn(f"https://{PREVIEW_DEPLOYMENT}", json.loads(written)["base_url"])  # the URL is recorded, and it carries no secret

    def test_a_protection_rejection_stops_at_the_first_request_with_a_clear_error(self):
        rejected = mock.Mock(stdout=f"HTTP/2 302\r\nlocation: https://vercel.com/sso-api?note={SECRET}\r\n\r\n")
        code, written, stdout, stderr, run = self._run(rejected)
        self.assertEqual(run.call_count, 1)
        self.assertIsNone(written)
        self.assertIn("STOPPED", code)
        self.assertIn("Deployment Protection", code)
        for text in (code, stdout, stderr):
            self.assertNotIn(SECRET, text)

    def test_every_protection_status_is_treated_as_a_rejection(self):
        for status in (301, 302, 303, 307, 308, 401):
            with self.subTest(status=status):
                live = runner.Live(f"https://{PREVIEW_DEPLOYMENT}", 0.0, SECRET)
                with mock.patch.object(runner.subprocess, "run", return_value=mock.Mock(stdout=f"HTTP/2 {status}\r\n\r\n")), self.assertRaises(runner.ProtectionRejected) as cm:
                    live.ask("q", "s")
                self.assertNotIn(SECRET, str(cm.exception))

    def test_the_runner_source_holds_no_secret_and_never_prints_or_logs_it(self):
        source = (ROOT / "eval" / "run_final_eval.py").read_text()
        self.assertNotRegex(source, r"(?i)print\([^)]*secret")
        self.assertNotRegex(source, r"(?i)(?:logging|log)\.[a-z]+\([^)]*secret")
        self.assertNotIn(SECRET, source)


class PacingIsKept(unittest.TestCase):
    def test_the_default_pace_is_seven_seconds(self):
        self.assertRegex((ROOT / "eval" / "run_final_eval.py").read_text(), r'"--pace",\s*type=float,\s*default=7\.0')

    def test_requests_are_spaced_by_the_pace(self):
        live = runner.Live(f"https://{PREVIEW_DEPLOYMENT}", 7.0, SECRET)
        sleeps = []
        with mock.patch.object(runner.subprocess, "run", return_value=_reply()), mock.patch.object(runner.time, "sleep", side_effect=sleeps.append), \
                mock.patch.object(runner.time, "time", return_value=1000.0):
            live.ask("one", "s"); live.ask("two", "s")
        self.assertEqual(sleeps, [7.0])  # the first request goes at once; the second waits the whole pace on this frozen clock


if __name__ == "__main__":
    unittest.main()
