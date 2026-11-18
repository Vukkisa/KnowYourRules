"""Offline checks of deploy/oci/ (systemd unit, Caddyfile, environment example) for the OCI Always Free A1 deployment.

What these tests can and cannot show (also stated in eval/deployment/OCI-DEPLOYMENT-READINESS-AUDIT.md):
  - They check STRUCTURE and the relationships between the three files and the application: ports, paths, limits, timeouts, routes.
  - `systemd-analyze verify` and `caddy validate` run only when those programs exist on the machine; otherwise those two tests are
    skipped, not passed. Neither exists on a development Mac, so real syntax validation needs the VM.
  - One test starts a real uvicorn on 127.0.0.1 with the unit's own flags to check the address it binds and what --no-proxy-headers does.
Nothing is installed, started on a fixed port, or contacted."""
import importlib
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
import http.client
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OCI = ROOT / "deploy" / "oci"
UNIT_PATH, CADDY_PATH, ENV_PATH = OCI / "kyr.service", OCI / "Caddyfile", OCI / "kyr.env.example"


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cce = load("check_cloud_env_oci", "scripts/check_cloud_env.py")
bp = load("build_pages_oci", "scripts/build_pages.py")
ap = importlib.import_module("backend.api_protection")


def parse_unit(text):
    """{section: {key: [values...]}} with systemd's rules for the subset used here; fails on anything that is not Key=Value."""
    sections, current = {}, None
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line[0] in "#;":
            continue
        if line.startswith("["):
            assert line.endswith("]"), f"line {n}: bad section header"
            current = sections.setdefault(line[1:-1], {})
            continue
        assert current is not None and "=" in line and not line.endswith("\\"), f"line {n}: not Key=Value: {line!r}"
        key, _, value = line.partition("=")
        current.setdefault(key.strip(), []).append(value.strip())
    return sections


def parse_caddyfile(text):
    """A minimal Caddyfile reader: nested blocks as (name, args, children) and plain directives as (name, args, None)."""
    root, stack = [], []
    current = root
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line == "{":
            node = ("{global}", "", [])
            current.append(node); stack.append(current); current = node[2]
        elif line.endswith(" {"):
            head = line[:-2].strip()
            name, _, args = head.partition(" ")
            node = (name, args.strip(), [])
            current.append(node); stack.append(current); current = node[2]
        elif line == "}":
            assert stack, f"line {n}: unbalanced }}"
            current = stack.pop()
        else:
            name, _, args = line.partition(" ")
            current.append((name, args.strip(), None))
    assert not stack, "unbalanced {"
    return root


def find(nodes, name):
    out = []
    for node in nodes:
        if node[0] == name:
            out.append(node)
        if node[2]:
            out.extend(find(node[2], name))
    return out


def seconds(value):
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s|m|h)", value.strip())
    assert m, value
    return float(m.group(1)) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[m.group(2)]


def size_bytes(value):
    m = re.fullmatch(r"(\d+)(B|KB|MB|KiB|MiB)?", value.strip(), re.I)
    assert m, value
    unit = (m.group(2) or "B").upper()
    return int(m.group(1)) * {"B": 1, "KB": 1000, "KIB": 1024, "MB": 1_000_000, "MIB": 1024 ** 2}[unit]


UNIT_TEXT = UNIT_PATH.read_text("utf-8")
UNIT = parse_unit(UNIT_TEXT)
CADDY_TEXT = CADDY_PATH.read_text("utf-8")
CADDY = parse_caddyfile(CADDY_TEXT)
ENV_TEXT = ENV_PATH.read_text("utf-8")


def env_example(text=ENV_TEXT):
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k] = v
    return out


ENV = env_example()


def exec_start_args():
    cmd = UNIT["Service"]["ExecStart"][0].split()
    return cmd[0], cmd[1:]


class SystemdUnitTests(unittest.TestCase):
    def test_the_unit_has_only_the_three_standard_sections_and_known_keys(self):
        self.assertEqual(set(UNIT), {"Unit", "Service", "Install"})
        known = {"Unit": {"Description", "Documentation", "After", "Wants", "RequiresMountsFor", "AssertPathIsMountPoint",
                          "StartLimitIntervalSec", "StartLimitBurst"},
                 "Install": {"WantedBy"}}
        self.assertLessEqual(set(UNIT["Unit"]), known["Unit"])
        self.assertLessEqual(set(UNIT["Install"]), known["Install"])
        for section in UNIT.values():
            for key, values in section.items():
                self.assertTrue(re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", key), key)
                if key not in ("CapabilityBoundingSet", "AmbientCapabilities"):      # these two are empty on purpose: drop every capability
                    self.assertTrue(all(values), key)
        self.assertEqual(UNIT["Install"]["WantedBy"], ["multi-user.target"])

    def test_uvicorn_runs_one_worker_on_localhost_from_the_virtualenv_without_proxy_headers(self):
        exe, args = exec_start_args()
        self.assertEqual(exe, "/opt/kyr/venv/bin/uvicorn")
        self.assertEqual(args[0], "backend.server:app")
        main = importlib.import_module("uvicorn.main").main
        p = main.make_context("uvicorn", args).params          # uvicorn's own CLI parser, so a wrong flag fails here
        self.assertEqual((p["host"], p["port"], p["workers"], p["proxy_headers"]), ("127.0.0.1", 8000, 1, False))
        self.assertIs(p["server_header"], False)
        self.assertEqual(p["timeout_graceful_shutdown"], 20)
        self.assertFalse(p["reload"])
        text = UNIT["Service"]["ExecStart"][0]
        for bad in ("0.0.0.0", "::", "--reload", "--forwarded-allow-ips", "--uds", "--fd"):
            self.assertNotIn(bad, text)
        self.assertEqual(UNIT["Service"]["WorkingDirectory"], ["/opt/kyr/app"])

    def test_it_waits_for_and_requires_the_persistent_volume_three_ways(self):
        self.assertEqual(UNIT["Unit"]["RequiresMountsFor"], ["/srv/kyr"])
        self.assertEqual(UNIT["Unit"]["AssertPathIsMountPoint"], ["/srv/kyr"])     # an Assert fails the unit; a Condition would skip it silently
        self.assertNotIn("ConditionPathIsMountPoint", UNIT["Unit"])
        pre = UNIT["Service"]["ExecStartPre"]
        self.assertEqual(pre, ["/opt/kyr/venv/bin/python /opt/kyr/app/scripts/check_cloud_env.py"])    # the validator refuses an unmounted volume

    def test_the_environment_file_is_protected_mandatory_and_outside_the_repository(self):
        ef = UNIT["Service"]["EnvironmentFile"]
        self.assertEqual(ef, ["/etc/kyr/kyr.env"])
        self.assertFalse(ef[0].startswith("-"))                 # a leading "-" would make a missing file acceptable
        self.assertFalse(ef[0].startswith(str(ROOT)))
        self.assertIn("0600", UNIT_TEXT)
        for key, values in UNIT["Service"].items():             # no secret or provider setting is written in the unit itself
            for v in values:
                self.assertNotRegex(v, r"(?i)(api_key|secret|token|password)")

    def test_it_runs_as_a_dedicated_non_root_user_and_restarts_only_on_failure(self):
        s = UNIT["Service"]
        self.assertEqual((s["User"], s["Group"]), (["kyr"], ["kyr"]))
        self.assertEqual(s["Restart"], ["on-failure"])
        self.assertGreaterEqual(float(s["RestartSec"][0]), 1)
        self.assertEqual(UNIT["Unit"]["StartLimitBurst"], ["5"])      # a broken configuration stops retrying instead of looping forever
        self.assertEqual(s["Type"], ["simple"])
        self.assertGreaterEqual(int(s["TimeoutStartSec"][0]), 60)      # snapshot restore + model load
        self.assertLessEqual(int(s["TimeoutStopSec"][0]), 60)
        self.assertEqual(s["KillSignal"], ["SIGTERM"])

    def test_hardening_is_present_and_does_not_hide_the_volume(self):
        s = UNIT["Service"]
        for key in ("NoNewPrivileges", "PrivateTmp", "PrivateDevices", "ProtectHome", "ProtectKernelTunables", "ProtectKernelModules",
                    "ProtectKernelLogs", "ProtectControlGroups", "ProtectClock", "ProtectHostname", "RestrictNamespaces", "RestrictRealtime",
                    "RestrictSUIDSGID", "LockPersonality"):
            self.assertEqual(s[key], ["true"], key)
        self.assertEqual(s["ProtectSystem"], ["full"])          # strict + ReadWritePaths would bind-mount /srv/kyr and defeat the mount check
        self.assertNotIn("ReadWritePaths", s)
        self.assertNotIn("ReadOnlyPaths", s)
        self.assertNotIn("InaccessiblePaths", s)
        self.assertIn("AF_INET", s["RestrictAddressFamilies"][0])        # the service must reach Groq and Gemini
        self.assertNotIn("IPAddressDeny", s)
        self.assertNotIn("PrivateNetwork", s)
        self.assertEqual(s["UMask"], ["0077"])
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", s["Environment"])     # the code directory is not writable by the service
        self.assertNotIn("MemoryDenyWriteExecute", s)                    # documented as untested on the VM
        self.assertNotIn("SystemCallFilter", s)

    def test_capabilities_are_dropped_completely(self):
        raw = {line.split("=")[0]: line.split("=", 1)[1] for line in UNIT_TEXT.splitlines() if line.startswith(("CapabilityBoundingSet", "AmbientCapabilities"))}
        self.assertEqual(raw, {"CapabilityBoundingSet": "", "AmbientCapabilities": ""})

    @unittest.skipUnless(shutil.which("systemd-analyze"), "systemd-analyze is not installed here: unit syntax is NOT verified by a real tool")
    def test_systemd_analyze_accepts_the_unit(self):
        p = subprocess.run(["systemd-analyze", "verify", str(UNIT_PATH)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)


class CaddyfileTests(unittest.TestCase):
    def test_braces_balance_and_the_site_is_a_placeholder_not_an_invented_domain(self):
        self.assertTrue(CADDY)
        sites = [n for n in CADDY if n[0] != "{global}"]
        self.assertEqual([s[0] for s in sites], ["{$KYR_DOMAIN}"])
        for host in re.findall(r"[A-Za-z0-9-]+\.duckdns\.org", CADDY_TEXT + UNIT_TEXT + ENV_TEXT):
            self.assertEqual(host, "example.duckdns.org")
        self.assertNotIn("{$KYR_DOMAIN:", CADDY_TEXT)         # no default hostname

    def test_https_is_automatic_and_plain_http_is_not_served(self):
        self.assertEqual(find(CADDY, "tls"), [])              # no certificate files or issuers configured: Caddy's default is Let's Encrypt
        self.assertNotIn("http://", "\n".join(l for l in CADDY_TEXT.splitlines() if not l.strip().startswith("#")))
        self.assertEqual(find(CADDY, "auto_https"), [])      # automatic HTTPS (and the HTTP -> HTTPS redirect) stays on

    def test_the_only_upstream_is_the_local_backend_on_the_units_port(self):
        proxies = find(CADDY, "reverse_proxy")
        self.assertEqual(len(proxies), 1)
        self.assertEqual(proxies[0][1], "127.0.0.1:8000")
        port = int(re.search(r"--port (\d+)", UNIT["Service"]["ExecStart"][0]).group(1))
        self.assertEqual(proxies[0][1].rsplit(":", 1)[1], str(port))
        self.assertEqual(len(re.findall(r"^\s*reverse_proxy\b", CADDY_TEXT, re.M)), 1)
        for host in re.findall(r"reverse_proxy\s+(\S+)", CADDY_TEXT):
            self.assertTrue(host.startswith("127.0.0.1:"), host)

    def test_only_the_pages_routes_are_proxied_and_they_exist_in_the_application(self):
        line = next(l for l in CADDY_TEXT.splitlines() if l.strip().startswith("@api"))
        paths = line.split()[2:]
        self.assertEqual(set(paths), {"/chat", "/status", "/health"})
        routes = set(re.findall(r'^@app\.(?:get|post)\("(/[^"]*)"', (ROOT / "backend" / "server.py").read_text("utf-8"), re.M))
        self.assertTrue(set(paths) <= routes, routes)
        for private in ("/ready", "/approval/refresh", "/docs", "/openapi.json", "/redoc", "/"):
            self.assertNotIn(private, paths)
        fallback = [n for n in find(CADDY, "handle") if n[1] == ""]
        self.assertEqual(len(fallback), 1)
        self.assertEqual(fallback[0][2], [("respond", '"Not found" 404', None)])

    def test_the_body_cap_covers_the_applications_cap_and_stays_small(self):
        cap = size_bytes(find(CADDY, "max_size")[0][1])
        self.assertGreaterEqual(cap, ap.DEFAULT_MAX_REQUEST_BYTES)
        self.assertLessEqual(cap, 64 * 1024)
        self.assertEqual(len(find(CADDY, "request_body")), 1)

    def test_slow_header_and_slow_body_attacks_are_bounded(self):
        timeouts = dict((n, a) for n, a, _ in find(CADDY, "timeouts")[0][2])
        self.assertLessEqual(seconds(timeouts["read_header"]), 30)
        self.assertLessEqual(seconds(timeouts["read_body"]), 30)
        self.assertLessEqual(seconds(timeouts["idle"]), 120)
        self.assertGreaterEqual(seconds(timeouts["read_body"]), 5)        # but long enough for a real phone on a poor link

    def test_the_response_timeouts_cover_the_slowest_legitimate_answer_with_the_documented_provider_settings(self):
        timeouts = dict((n, a) for n, a, _ in find(CADDY, "timeouts")[0][2])
        transport = dict((n, a) for n, a, _ in find(CADDY, "transport")[0][2])
        provider = float(ENV["PROVIDER_TIMEOUT_SECONDS"])
        retries = int(ENV["PROVIDER_MAX_RETRIES"])
        # two providers, each tried (retries + 1) times, plus the application's retry wait, plus a retrieval allowance (6-7 CPU-s, slower under load)
        worst = 2 * provider * (retries + 1) + 2 * retries * 5.0 + 15
        self.assertLess(worst, seconds(transport["response_header_timeout"]))
        self.assertLessEqual(seconds(transport["response_header_timeout"]), seconds(timeouts["write"]))
        self.assertLessEqual(seconds(transport["dial_timeout"]), 10)
        # the page's own default wait (30 s) is shorter than the proxy's, so a slow answer ends at the page, not mid-flight at the proxy
        self.assertLessEqual(30, seconds(transport["response_header_timeout"]))

    def test_proxy_headers_cannot_be_spoofed_by_a_client(self):
        ups = find(CADDY, "header_up")
        self.assertEqual([(n, a) for n, a, _ in ups], [("header_up", "X-Forwarded-For {remote_host}")])    # replaced, never appended
        self.assertEqual(find(CADDY, "trusted_proxies"), [])       # Caddy itself trusts no upstream, so it also overwrites the other forwarded headers

    def test_response_headers_hide_the_server_and_set_basic_protections(self):
        hdr = [n for n, a, _ in find(CADDY, "header")[0][2]]
        self.assertIn("-Server", hdr)
        self.assertIn("X-Content-Type-Options", hdr)

    @unittest.skipUnless(shutil.which("caddy"), "caddy is not installed here: Caddyfile syntax is NOT verified by Caddy itself")
    def test_caddy_validate_accepts_the_file(self):
        env = {**os.environ, "KYR_DOMAIN": "example.duckdns.org"}
        p = subprocess.run(["caddy", "validate", "--config", str(CADDY_PATH), "--adapter", "caddyfile"], env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)


class EnvironmentExampleTests(unittest.TestCase):
    def test_it_keeps_the_local_persistent_snapshot_configuration_and_tg_cloud(self):
        self.assertEqual(ENV["TG_CLOUD"], "1")
        self.assertEqual(ENV["TG_SNAPSHOT_STORE"], "local")
        self.assertEqual(ENV["TG_SNAPSHOT_MOUNT_POINT"], "/srv/kyr")
        self.assertEqual(UNIT["Unit"]["RequiresMountsFor"][0], ENV["TG_SNAPSHOT_MOUNT_POINT"])
        for name in ("TG_SNAPSHOT_LOCAL_DIR", "TG_SNAPSHOT_WORK_DIR", "EMBEDDING_MODEL_FILE"):
            self.assertTrue(ENV[name].startswith("/srv/kyr/"), name)
        for name in ("TG_DB_DIR", "TG_LIFECYCLE_DIR"):
            self.assertNotIn(name, ENV)
        self.assertEqual((ENV["TG_ENVIRONMENT"], ENV["TG_GROUNDED_ANSWERS"], ENV["OLLAMA_ENABLED"]), ("production", "1", "false"))

    def test_the_nomic_embedding_configuration_is_exact(self):
        import backend.nomic_local as nl
        self.assertEqual(ENV["EMBEDDING_PROVIDER"], "inprocess_nomic")
        self.assertEqual(ENV["EMBEDDING_MODEL_SHA256"], nl.KNOWN_MODEL_SHA256)
        self.assertEqual(ENV["TG_SNAPSHOT_EXPECT_FAMILY"], "nomic-embed-text-v1.5")
        for weaker in ("EMBEDDING_VERIFY", "EMBEDDING_MIN_COSINE", "EMBEDDING_NORMALIZE"):
            self.assertNotIn(weaker, ENV)

    def test_no_application_limit_or_legal_safeguard_is_overridden(self):
        for name in ENV:
            self.assertFalse(name.startswith(("TG_RATE_LIMIT_", "TG_SESSION_", "TG_MAX_")), name)
        for name in ("TG_KB_APPROVED", "TG_PENALTY_ANSWERS", "TG_LEGACY_DEV_ANSWERS", "TG_SNAPSHOT_ALLOW_STALE", "TG_ENABLE_APPROVAL_REFRESH"):
            self.assertNotIn(name, ENV)
        self.assertFalse(any(l.strip().startswith(("TG_APPROVAL_FILE", "TG_TRUSTED_KEYS_FILE")) for l in ENV_TEXT.splitlines()))   # only commented examples
        self.assertEqual(ap.parse_trusted_proxies(ENV["TG_TRUSTED_PROXIES"]), ap.parse_trusted_proxies("127.0.0.1,::1"))

    def test_only_placeholders_are_present_and_no_secret_shape_is_committed(self):
        for name in ("GROQ_API_KEY", "GEMINI_API_KEY", "TG_SNAPSHOT_PIN_SHA256"):
            self.assertTrue(ENV[name].startswith("your-"), name)
        self.assertEqual(ENV["TG_CORS_ORIGINS"], "https://your-github-user.github.io")
        for path in (UNIT_PATH, CADDY_PATH, ENV_PATH):
            text = path.read_text("utf-8")
            for pattern, label in bp.FORBIDDEN_PATTERNS[:-1]:      # every key shape; the last entry is variable NAMES, which this file legitimately lists
                self.assertIsNone(re.search(pattern, text), f"{path.name}: {label}")
            self.assertNotRegex(text, r"(?m)^\s*(?:[A-Z_]*(?:KEY|SECRET|TOKEN|PASSWORD)[A-Z_]*)=(?!your-)\S")

    def test_the_provider_settings_bound_the_worst_case_below_the_proxy_limits(self):
        self.assertLessEqual(float(ENV["PROVIDER_TIMEOUT_SECONDS"]), 25)
        self.assertEqual(ENV["PROVIDER_MAX_RETRIES"], "0")

    def test_the_example_passes_the_cloud_validator_once_placeholders_are_filled_in(self):
        tmp = Path(tempfile.mkdtemp(prefix="kyr-oci-env-test-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        for sub in ("snapshots", "work", "model"):
            (tmp / "srv" / sub).mkdir(parents=True)
        (tmp / "srv" / "model" / "nomic-embed-text-v1.5.f16.gguf").write_bytes(b"x")
        env = {k: v.replace("/srv/kyr", str(tmp / "srv")) for k, v in ENV.items()}
        env["TG_SNAPSHOT_PIN_SHA256"] = "ab" * 32

        class Fs:
            def ismount(self, p): return os.path.realpath(p) == os.path.realpath(tmp / "srv")
            def free_bytes(self, p): return 50 * 1024 ** 3
            def writable(self, d): return True
            def temporary_roots(self): return ()
        r = cce.check(env, Fs())
        self.assertEqual((r["ok"], r["errors"], r["snapshot_store"]), (True, [], "local"))
        unmounted = type("U", (Fs,), {"ismount": lambda self, p: False})()
        self.assertFalse(cce.check(env, unmounted)["ok"])         # and with the volume missing the same file is refused


class NoPaidServicesTests(unittest.TestCase):
    def test_no_paid_or_third_party_proxy_service_is_referenced(self):
        banned = ("load balancer", "loadbalancer", "load_balancer", "cloudflare", "ngrok", "amazonaws", "azure", "pay as you go", "elb.", "waf")
        for path in (UNIT_PATH, CADDY_PATH, ENV_PATH):
            text = path.read_text("utf-8").lower()
            for word in banned:
                self.assertNotIn(word, text, f"{path.name}: {word}")

    def test_the_only_public_listener_is_caddy_and_the_backend_has_no_public_address(self):
        self.assertNotIn("0.0.0.0", UNIT_TEXT + CADDY_TEXT + ENV_TEXT)
        self.assertNotIn("8000", [h for h in re.findall(r"^\s*(?:bind|http_port|https_port)\s+(\S+)", CADDY_TEXT, re.M)])


class RealUvicornTests(unittest.TestCase):
    """Starts uvicorn on a free loopback port with the unit's own flags and a tiny ASGI app (never the real backend)."""

    APP = textwrap.dedent('''
        import json
        async def app(scope, receive, send):
            if scope["type"] != "http":
                return
            body = json.dumps({"client": list(scope["client"] or [])}).encode()
            await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": body})
    ''')

    def start(self, flags):
        tmp = Path(tempfile.mkdtemp(prefix="kyr-oci-uvicorn-test-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "tiny.py").write_text(self.APP)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "tiny:app", "--port", str(port), *flags], cwd=tmp,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": ""})
        self.addCleanup(proc.wait)
        self.addCleanup(proc.terminate)
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", port), 0.2).close()
                return port
            except OSError:
                time.sleep(0.1)
        self.fail("uvicorn did not start")

    def client_seen(self, port, forwarded):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            c.request("GET", "/", headers={"X-Forwarded-For": forwarded})
            return json.loads(c.getresponse().read())["client"][0]
        finally:
            c.close()

    def unit_flags(self):
        _, args = exec_start_args()
        flags = args[1:]
        i = flags.index("--port")
        return flags[:i] + flags[i + 2:]

    def test_it_listens_on_loopback_only(self):
        port = self.start(self.unit_flags())
        socket.create_connection(("127.0.0.1", port), 2).close()
        others = {a[4][0] for a in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET) if not a[4][0].startswith("127.")}
        if not others:
            self.skipTest("this machine has no non-loopback IPv4 address to probe")
        for ip in others:
            with self.assertRaises(OSError):
                socket.create_connection((ip, port), 1).close()

    def test_no_proxy_headers_keeps_the_real_peer_and_ignores_a_spoofed_header(self):
        self.assertEqual(self.client_seen(self.start(self.unit_flags()), "203.0.113.9"), "127.0.0.1")

    def test_without_the_flag_uvicorn_would_trust_the_header_from_a_loopback_peer(self):
        flags = [f for f in self.unit_flags() if f != "--no-proxy-headers"]
        self.assertEqual(self.client_seen(self.start(flags), "203.0.113.9"), "203.0.113.9")      # the control: why the flag matters


if __name__ == "__main__":
    unittest.main()
