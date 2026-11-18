"""OCI pilot Stage 1: API protection (rate limit, request-size cap, concurrency cap, configuration). Offline and deterministic:
an injected clock replaces time, the middleware is driven directly as ASGI, and the real server runs on the fake-backed import of
tests/test_server.py (no Chroma, no Ollama, no model, no network). Nothing here calls Groq or Gemini."""
import asyncio
import ipaddress
import json
import logging
import threading
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import test_server as ts
from backend import api_protection as ap

Q = "How do I apply for a learner's licence?"


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def cfg(**kw):
    return ap.ProtectionConfig(**kw)


async def downstream(scope, receive, send):
    """Stand-in for the application: reads the whole body, answers 200 with its length."""
    if scope["type"] != "http":
        return
    size = 0
    while True:
        message = await receive()
        size += len(message.get("body", b""))
        if not message.get("more_body", False):
            break
    downstream.calls.append((scope["path"], size))
    body = json.dumps({"bytes": size}).encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": body})


downstream.calls = []


def call(app, method="POST", path="/chat", client=("203.0.113.5", 1234), headers=(), chunks=(b"{}",), with_length=True):
    """Drive one HTTP request through an ASGI app. Returns (status, response headers dict, body bytes, request bytes pulled)."""
    hdrs = [(k.lower().encode(), v.encode()) for k, v in headers]
    total = sum(len(c) for c in chunks)
    if with_length and not any(k == b"content-length" for k, _ in hdrs):
        hdrs.append((b"content-length", str(total).encode()))
    scope = {"type": "http", "method": method, "path": path, "headers": hdrs, "client": client}
    queue = [{"type": "http.request", "body": c, "more_body": i < len(chunks) - 1} for i, c in enumerate(chunks)]
    pulled, out = [0], {"status": None, "headers": {}, "body": b""}

    async def receive():
        if queue:
            message = queue.pop(0)
            pulled[0] += len(message["body"])
            return message
        await asyncio.sleep(0)
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            out["status"] = message["status"]
            out["headers"] = {k.decode().lower(): v.decode() for k, v in message["headers"]}
        else:
            out["body"] += message.get("body", b"")

    asyncio.run(app(scope, receive, send))
    return out["status"], out["headers"], out["body"], pulled[0]


def middleware(config=None, clock=None, **kw):
    config = config or cfg(**kw)
    limiter = ap.RateLimiter(config.rate_requests, config.rate_window_seconds, config.max_clients, clock=clock or Clock())
    return ap.ProtectionMiddleware(downstream, config, limiter)


class RateLimitTests(unittest.TestCase):
    def test_default_is_ten_per_minute(self):
        c = ap.config_from_env({})
        self.assertEqual((c.rate_requests, c.rate_window_seconds), (10, 60))
        self.assertEqual((c.max_request_bytes, c.max_concurrent, c.trusted_proxies, c.problems), (8192, 2, (), ()))
        self.assertEqual((c.max_sessions, c.session_ttl_seconds), (500, 1800))

    def test_requests_below_the_limit_pass(self):
        app = middleware(rate_requests=10)
        for _ in range(5):
            self.assertEqual(call(app)[0], 200)

    def test_the_boundary_request_passes_and_the_next_is_refused(self):
        app = middleware(rate_requests=10)
        statuses = [call(app)[0] for _ in range(11)]
        self.assertEqual(statuses, [200] * 10 + [429])

    def test_requests_over_the_limit_are_refused_with_a_fixed_body(self):
        app = middleware(rate_requests=3)
        for _ in range(3):
            call(app)
        for _ in range(4):
            status, headers, body, _ = call(app)
            self.assertEqual(status, 429)
            self.assertEqual(json.loads(body), {"detail": ap.GENERIC_RATE})
            self.assertEqual(headers["content-type"], "application/json")

    def test_a_refused_request_never_reaches_the_application(self):
        downstream.calls.clear()
        app = middleware(rate_requests=1)
        call(app)
        call(app)
        self.assertEqual(len(downstream.calls), 1)

    def test_retry_after_is_whole_seconds_and_accurate(self):
        clock = Clock()
        app = middleware(clock=clock, rate_requests=2, rate_window_seconds=60)
        call(app)                                  # t=0
        clock.advance(10)
        call(app)                                  # t=10
        clock.advance(5)                           # t=15: the oldest hit (t=0) leaves the window at t=60
        status, headers, _, _ = call(app)
        self.assertEqual((status, headers["retry-after"]), (429, "45"))
        clock.advance(44.5)                        # t=59.5: half a second left rounds UP, never down to 0
        self.assertEqual(call(app)[1]["retry-after"], "1")
        clock.advance(0.5)                         # t=60: the first hit has expired
        self.assertEqual(call(app)[0], 200)

    def test_refused_requests_are_not_counted_so_backing_off_works(self):
        clock = Clock()
        app = middleware(clock=clock, rate_requests=1, rate_window_seconds=60)
        call(app)
        for _ in range(20):                        # hammering must not extend the penalty
            clock.advance(1)
            self.assertEqual(call(app)[0], 429)
        clock.advance(40)                          # 60s after the single accepted request
        self.assertEqual(call(app)[0], 200)

    def test_clients_have_independent_limits(self):
        app = middleware(rate_requests=2)
        a, b = ("198.51.100.1", 1), ("198.51.100.2", 1)
        self.assertEqual([call(app, client=a)[0] for _ in range(3)], [200, 200, 429])
        self.assertEqual([call(app, client=b)[0] for _ in range(3)], [200, 200, 429])

    def test_ipv6_clients_share_a_quota_per_slash_64(self):
        app = middleware(rate_requests=2)
        same_net = [("2001:db8:1:2::1", 1), ("2001:db8:1:2:ffff::9", 1), ("2001:db8:1:2:abcd::5", 1)]
        self.assertEqual([call(app, client=c)[0] for c in same_net], [200, 200, 429])
        self.assertEqual(call(app, client=("2001:db8:1:3::1", 1))[0], 200)

    def test_ipv4_mapped_ipv6_is_the_ipv4_client(self):
        app = middleware(rate_requests=1)
        self.assertEqual(call(app, client=("203.0.113.9", 1))[0], 200)
        self.assertEqual(call(app, client=("::ffff:203.0.113.9", 1))[0], 429)

    def test_a_missing_or_non_ip_peer_still_gets_one_bucket(self):
        app = middleware(rate_requests=1)
        self.assertEqual(call(app, client=None)[0], 200)
        self.assertEqual(call(app, client=None)[0], 429)
        self.assertEqual(call(app, client=("testclient", 5))[0], 200)
        self.assertEqual(call(app, client=("testclient", 6))[0], 429)

    def test_only_the_chat_post_is_limited(self):
        app = middleware(rate_requests=1)
        call(app)
        self.assertEqual(call(app)[0], 429)
        for method, path in [("GET", "/health"), ("GET", "/ready"), ("GET", "/status"), ("GET", "/"), ("OPTIONS", "/chat"),
                             ("GET", "/chat"), ("POST", "/other"), ("GET", "/static/app.js")]:
            for _ in range(5):
                self.assertEqual(call(app, method, path)[0], 200, (method, path))

    def test_non_http_scopes_pass_through(self):
        seen = []

        async def inner(scope, receive, send):
            seen.append(scope["type"])

        app = ap.ProtectionMiddleware(inner, cfg())
        asyncio.run(app({"type": "lifespan"}, None, None))
        self.assertEqual(seen, ["lifespan"])

    def test_concurrent_checks_never_overshoot_the_limit(self):
        limiter = ap.RateLimiter(10, 60, 100, clock=Clock())
        allowed, barrier = [], threading.Barrier(50)

        def hit():
            barrier.wait()
            allowed.append(limiter.check("k")[0])

        threads = [threading.Thread(target=hit) for _ in range(50)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sum(allowed), 10)

    def test_the_default_clock_is_monotonic(self):
        limiter = ap.RateLimiter()
        self.assertIs(limiter._clock, ap.time.monotonic)
        with mock.patch("time.time", side_effect=AssertionError("wall clock must not be used")):
            self.assertTrue(limiter.check("k")[0])


class ForwardedHeaderTests(unittest.TestCase):
    PROXY = ("10.0.0.7", 4000)

    def trusted(self, **kw):
        return middleware(rate_requests=2, trusted_proxies=(ipaddress.ip_network("10.0.0.0/24"),), **kw)

    def test_a_spoofed_forwarding_header_is_ignored_without_a_trusted_proxy(self):
        app = middleware(rate_requests=2)
        # one real client rotating a forged X-Forwarded-For per request must stay in ONE bucket
        statuses = [call(app, headers=[("X-Forwarded-For", f"192.0.2.{i}")])[0] for i in range(1, 6)]
        self.assertEqual(statuses, [200, 200, 429, 429, 429])

    def test_forged_x_real_ip_and_forwarded_headers_are_never_used(self):
        for app in (middleware(rate_requests=1), self.trusted()):
            peer = self.PROXY if app.config.trusted_proxies else ("203.0.113.5", 1)
            self.assertEqual(call(app, client=peer, headers=[("X-Real-IP", "192.0.2.1"), ("Forwarded", "for=192.0.2.1")])[0], 200)
            self.assertEqual(call(app, client=peer, headers=[("X-Real-IP", "192.0.2.2"), ("Forwarded", "for=192.0.2.2")])[0], 200
                             if app.config.trusted_proxies else 429)

    def test_a_forged_header_from_an_untrusted_peer_is_ignored_even_when_proxies_are_configured(self):
        app = self.trusted()
        statuses = [call(app, client=("203.0.113.5", 1), headers=[("X-Forwarded-For", f"192.0.2.{i}")])[0] for i in range(1, 5)]
        self.assertEqual(statuses, [200, 200, 429, 429])

    def test_a_trusted_proxy_separates_the_real_clients(self):
        app = self.trusted()
        a, b = [("X-Forwarded-For", "198.51.100.1")], [("X-Forwarded-For", "198.51.100.2")]
        self.assertEqual([call(app, client=self.PROXY, headers=a)[0] for _ in range(3)], [200, 200, 429])
        self.assertEqual([call(app, client=self.PROXY, headers=b)[0] for _ in range(3)], [200, 200, 429])

    def test_a_trusted_proxy_without_the_header_limits_the_proxy_address(self):
        app = self.trusted()
        self.assertEqual([call(app, client=self.PROXY)[0] for _ in range(3)], [200, 200, 429])

    def test_a_client_cannot_prepend_a_forged_address_through_a_trusted_proxy(self):
        # The proxy appends the address it saw. The client's own forged leftmost entries are never reached.
        app = self.trusted()
        for i in range(1, 5):
            forged = f"192.0.2.{i}, 198.51.100.9"           # proxy saw 198.51.100.9; the rest is client-supplied
            status = call(app, client=self.PROXY, headers=[("X-Forwarded-For", forged)])[0]
            self.assertEqual(status, 200 if i <= 2 else 429)

    def test_trusted_hops_are_skipped_right_to_left(self):
        t = (ipaddress.ip_network("10.0.0.0/24"),)
        self.assertEqual(ap.resolve_client("10.0.0.7", "198.51.100.1, 10.0.0.3", t), "198.51.100.1")
        self.assertEqual(ap.resolve_client("10.0.0.7", "10.0.0.3, 10.0.0.4", t), "10.0.0.3")   # all trusted: leftmost

    def test_malformed_forwarding_values_fall_back_to_the_peer(self):
        t = (ipaddress.ip_network("10.0.0.0/24"),)
        for bad in ("not-an-ip", "198.51.100.1, garbage", "", " ", ",", "198.51.100.1,", "999.1.1.1", "unknown",
                    "198.51.100.1:8080", "<script>"):
            self.assertEqual(ap.resolve_client("10.0.0.7", bad, t), "10.0.0.7", bad)

    def test_several_forwarding_header_lines_are_combined_in_order(self):
        app = self.trusted()
        hdrs = [("X-Forwarded-For", "192.0.2.77"), ("X-Forwarded-For", "198.51.100.1")]
        for _ in range(2):
            self.assertEqual(call(app, client=self.PROXY, headers=hdrs)[0], 200)
        self.assertEqual(call(app, client=self.PROXY, headers=hdrs)[0], 429)

    def test_ipv6_forwarded_clients_are_bucketed_by_slash_64(self):
        t = (ipaddress.ip_network("10.0.0.0/24"),)
        self.assertEqual(ap.resolve_client("10.0.0.7", "2001:db8:1:2::1", t), ap.resolve_client("10.0.0.7", "2001:db8:1:2::2", t))

    def test_no_forwarding_header_is_read_when_no_proxy_is_trusted(self):
        self.assertEqual(ap.resolve_client("203.0.113.5", "198.51.100.1", ()), "203.0.113.5")


class RequestSizeTests(unittest.TestCase):
    def setUp(self):
        downstream.calls.clear()

    def app(self, cap=1000, **kw):
        return middleware(max_request_bytes=cap, rate_requests=1000, **kw)

    def test_a_declared_oversized_body_is_refused_without_reading_it(self):
        status, headers, body, pulled = call(self.app(1000), chunks=(b"x" * 5000,))
        self.assertEqual((status, pulled), (413, 0))
        self.assertEqual(json.loads(body), {"detail": ap.GENERIC_TOO_LARGE})
        self.assertEqual(downstream.calls, [])

    def test_a_body_exactly_at_the_cap_is_accepted_and_one_byte_more_is_not(self):
        self.assertEqual(call(self.app(1000), chunks=(b"x" * 1000,))[0], 200)
        self.assertEqual(call(self.app(1000), chunks=(b"x" * 1001,))[0], 413)

    def test_a_chunked_body_without_content_length_is_cut_off_at_the_cap(self):
        chunks = tuple(b"x" * 400 for _ in range(1000))            # 400 KB offered
        status, _, _, pulled = call(self.app(1000), chunks=chunks, with_length=False)
        self.assertEqual(status, 413)
        self.assertLessEqual(pulled, 1000 + 400)                   # never more than the cap plus the chunk that crossed it
        self.assertEqual(downstream.calls, [])

    def test_an_understated_content_length_cannot_smuggle_a_large_body(self):
        status, _, _, pulled = call(self.app(1000), chunks=(b"x" * 600, b"x" * 600, b"x" * 600),
                                    headers=[("Content-Length", "10")])
        self.assertEqual(status, 413)
        self.assertLessEqual(pulled, 1200)

    def test_invalid_or_duplicate_content_length_is_a_400(self):
        for value in ("abc", "-5", "1e3", "12 34", "٣"):
            self.assertEqual(call(self.app(), headers=[("Content-Length", value)])[0], 400, value)
        self.assertEqual(call(self.app(), headers=[("Content-Length", "2"), ("Content-Length", "2")])[0], 400)
        self.assertEqual(downstream.calls, [])

    def test_a_normal_body_reaches_the_application_intact(self):
        body = json.dumps({"message": Q, "session_id": "s"}).encode()
        status, _, out, _ = call(self.app(), chunks=(body[:10], body[10:]))
        self.assertEqual((status, json.loads(out)), (200, {"bytes": len(body)}))

    def test_an_empty_body_is_passed_on_for_the_application_to_validate(self):
        self.assertEqual(call(self.app(), chunks=(b"",))[0], 200)

    def test_the_cap_is_not_applied_to_other_routes(self):
        big = (b"x" * 100_000,)
        self.assertEqual(call(self.app(1000), path="/other", chunks=big)[0], 200)
        self.assertEqual(call(self.app(1000), method="POST", path="/approval/refresh", chunks=big)[0], 200)
        self.assertEqual(call(self.app(1000), method="GET", path="/status", chunks=big)[0], 200)

    def test_an_oversized_request_still_counts_against_the_rate_limit(self):
        app = middleware(max_request_bytes=256, rate_requests=2)
        self.assertEqual([call(app, chunks=(b"x" * 999,))[0] for _ in range(3)], [413, 413, 429])

    def test_a_client_that_disconnects_mid_body_gets_no_application_call(self):
        scope = {"type": "http", "method": "POST", "path": "/chat", "headers": [], "client": ("203.0.113.5", 1)}
        sent = []

        async def receive():
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)

        asyncio.run(self.app()(scope, receive, send))
        self.assertEqual((sent, downstream.calls), ([], []))


class ConcurrencyLimiterTests(unittest.TestCase):
    def test_permits_are_limited_and_never_waited_for(self):
        limiter = ap.ConcurrencyLimiter(2)
        with limiter.slot():
            with limiter.slot():
                self.assertEqual(limiter.in_use, 2)
                with self.assertRaises(ap.CapacityExceeded):
                    with limiter.slot():
                        self.fail("a third permit must not be granted")
        self.assertEqual(limiter.in_use, 0)

    def test_the_permit_is_released_after_an_exception(self):
        limiter = ap.ConcurrencyLimiter(1)
        for error in (RuntimeError("boom"), ValueError("x"), TimeoutError("upstream timed out"), OSError("net")):
            with self.assertRaises(type(error)):
                with limiter.slot():
                    raise error
            self.assertEqual(limiter.in_use, 0)
        with limiter.slot():
            pass

    def test_the_permit_is_released_after_cancellation_and_base_exceptions(self):
        limiter = ap.ConcurrencyLimiter(1)
        for error in (asyncio.CancelledError(), KeyboardInterrupt(), SystemExit(1), GeneratorExit()):
            with self.assertRaises(type(error)):
                with limiter.slot():
                    raise error
            self.assertEqual(limiter.in_use, 0, type(error).__name__)

    def test_a_cancelled_task_releases_its_permit(self):
        limiter = ap.ConcurrencyLimiter(1)

        async def scenario():
            started = asyncio.Event()

            async def work():
                with limiter.slot():
                    started.set()
                    await asyncio.sleep(3600)

            task = asyncio.ensure_future(work())
            await started.wait()
            self.assertEqual(limiter.in_use, 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        asyncio.run(scenario())
        self.assertEqual(limiter.in_use, 0)

    def test_a_timeout_wrapper_releases_the_permit(self):
        limiter = ap.ConcurrencyLimiter(1)

        async def work():
            with limiter.slot():
                await asyncio.sleep(3600)

        with self.assertRaises(asyncio.TimeoutError):
            asyncio.run(asyncio.wait_for(work(), 0.01))
        self.assertEqual(limiter.in_use, 0)

    def test_a_double_release_cannot_create_extra_capacity(self):
        limiter = ap.ConcurrencyLimiter(1)
        self.assertTrue(limiter.try_acquire())
        limiter.release()
        limiter.release()
        self.assertTrue(limiter.try_acquire())
        self.assertFalse(limiter.try_acquire())

    def test_threads_never_exceed_the_limit(self):
        limiter = ap.ConcurrencyLimiter(3)
        granted, barrier = [], threading.Barrier(40)

        def worker():
            barrier.wait()
            granted.append(limiter.try_acquire())

        threads = [threading.Thread(target=worker) for _ in range(40)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sum(granted), 3)


class ConfigTests(unittest.TestCase):
    def test_valid_values_are_used(self):
        c = ap.config_from_env({"TG_RATE_LIMIT_REQUESTS": "5", "TG_RATE_LIMIT_WINDOW_SECONDS": "30", "TG_MAX_REQUEST_BYTES": "2048",
                                "TG_MAX_CONCURRENT_QUESTIONS": "4", "TG_RATE_LIMIT_MAX_CLIENTS": "500",
                                "TG_TRUSTED_PROXIES": "10.0.0.1, 192.168.0.0/16, ::1"})
        self.assertEqual((c.rate_requests, c.rate_window_seconds, c.max_request_bytes, c.max_concurrent, c.max_clients),
                         (5, 30, 2048, 4, 500))
        self.assertEqual(len(c.trusted_proxies), 3)
        self.assertEqual(c.problems, ())

    def test_every_invalid_value_falls_back_to_its_default_and_is_reported_by_name_only(self):
        for name in ap.RANGES:
            for bad in ("abc", "0", "-1", "1.5", "1e3", "", "999999999999", "٣", "0x10", "10; rm -rf /"):
                c = ap.config_from_env({name: bad})
                value = {"TG_RATE_LIMIT_REQUESTS": c.rate_requests, "TG_RATE_LIMIT_WINDOW_SECONDS": c.rate_window_seconds,
                         "TG_RATE_LIMIT_MAX_CLIENTS": c.max_clients, "TG_MAX_REQUEST_BYTES": c.max_request_bytes,
                         "TG_MAX_CONCURRENT_QUESTIONS": c.max_concurrent, "TG_SESSION_MAX": c.max_sessions,
                         "TG_SESSION_TTL_SECONDS": c.session_ttl_seconds}[name]
                self.assertEqual(value, ap.DEFAULTS[name], (name, bad))
                if bad.strip():                                    # an empty value is simply "unset"
                    self.assertEqual(len(c.problems), 1, (name, bad))
                    self.assertIn(name, c.problems[0])
                    if len(bad) > 3:
                        self.assertNotIn(bad, c.problems[0])       # the offending value is never echoed

    def test_out_of_range_values_are_rejected_at_both_ends(self):
        for name, (low, high) in ap.RANGES.items():
            self.assertEqual(ap.config_from_env({name: str(low)}).problems, (), name)
            self.assertEqual(ap.config_from_env({name: str(high)}).problems, (), name)
            self.assertEqual(len(ap.config_from_env({name: str(low - 1)}).problems), 1, name)
            self.assertEqual(len(ap.config_from_env({name: str(high + 1)}).problems), 1, name)

    def test_invalid_trusted_proxies_mean_no_trusted_proxy(self):
        for bad in ("*", "0.0.0.0/0", "::/0", "proxy.example.com", "10.0.0.1,,10.0.0.2", "10.0.0.1, nonsense", "10.0.0.300", ","):
            c = ap.config_from_env({"TG_TRUSTED_PROXIES": bad})
            self.assertEqual(c.trusted_proxies, (), bad)
            self.assertEqual(len(c.problems), 1, bad)
            self.assertNotIn(bad, c.problems[0] if bad.strip(",") else "never")

    def test_one_bad_setting_does_not_disturb_the_others(self):
        c = ap.config_from_env({"TG_RATE_LIMIT_REQUESTS": "oops", "TG_MAX_CONCURRENT_QUESTIONS": "3"})
        self.assertEqual((c.rate_requests, c.max_concurrent), (10, 3))

    def test_problems_are_logged_without_values(self):
        with self.assertLogs("backend.api_protection", level="ERROR") as logs:
            ap.config_from_env({"TG_MAX_REQUEST_BYTES": "SECRET-LOOKING-VALUE"})
        self.assertNotIn("SECRET-LOOKING-VALUE", "\n".join(logs.output))

    def test_direct_construction_rejects_impossible_parameters(self):
        for args in ((0, 60, 10), (1, 0, 10), (1, 60, 0), (-1, 60, 10)):
            with self.assertRaises(ap.ConfigError):
                ap.RateLimiter(*args)
        for size in (0, -1):
            with self.assertRaises(ap.ConfigError):
                ap.ConcurrencyLimiter(size)

    def test_the_public_view_has_no_proxy_addresses(self):
        c = ap.config_from_env({"TG_TRUSTED_PROXIES": "10.1.2.3"})
        self.assertNotIn("10.1.2.3", json.dumps(c.public()))
        self.assertEqual(c.public()["trusted_proxies_configured"], 1)


class MemoryTests(unittest.TestCase):
    def test_expired_clients_are_removed_by_a_sweep(self):
        clock = Clock()
        limiter = ap.RateLimiter(5, 60, 1000, clock=clock)
        for i in range(100):
            limiter.check(f"client-{i}")
        self.assertEqual(limiter.tracked_clients(), 100)
        clock.advance(59)
        limiter.sweep()
        self.assertEqual(limiter.tracked_clients(), 100)           # not yet expired
        clock.advance(1)
        limiter.sweep()
        self.assertEqual(limiter.tracked_clients(), 0)

    def test_cleanup_happens_automatically_without_an_explicit_sweep(self):
        clock = Clock()
        limiter = ap.RateLimiter(5, 60, 1000, clock=clock)
        for i in range(200):
            limiter.check(f"client-{i}")
        clock.advance(61)
        limiter.check("fresh")                                     # an ordinary request triggers the periodic sweep
        self.assertEqual(limiter.tracked_clients(), 1)

    def test_partially_expired_history_is_trimmed(self):
        clock = Clock()
        limiter = ap.RateLimiter(5, 60, 1000, clock=clock)
        for _ in range(3):
            limiter.check("k")                                     # hits at t=0, 20, 40
            clock.advance(20)                                      # now t=60: the first hit has just expired
        limiter.sweep()
        self.assertEqual(len(limiter._hits["k"]), 2)

    def test_per_client_history_never_exceeds_the_limit(self):
        limiter = ap.RateLimiter(4, 60, 1000, clock=Clock())
        for _ in range(1000):
            limiter.check("k")
        self.assertEqual(len(limiter._hits["k"]), 4)

    def test_the_number_of_tracked_clients_is_bounded(self):
        limiter = ap.RateLimiter(5, 60, 50, clock=Clock())
        results = [limiter.check(f"c{i}")[0] for i in range(10_000)]
        self.assertLessEqual(limiter.tracked_clients(), 50)
        self.assertEqual(sum(results), 50)

    def test_a_full_table_refuses_new_clients_but_keeps_serving_tracked_ones(self):
        clock = Clock()
        limiter = ap.RateLimiter(5, 60, 3, clock=clock)
        for key in "abc":
            self.assertTrue(limiter.check(key)[0])
        allowed, retry = limiter.check("newcomer")
        self.assertEqual((allowed, retry), (False, 60))
        self.assertTrue(limiter.check("a")[0])
        clock.advance(60)                                          # everything expired: the newcomer fits again
        self.assertTrue(limiter.check("newcomer")[0])

    def test_an_expired_entry_frees_a_slot_in_a_full_table(self):
        clock = Clock()
        limiter = ap.RateLimiter(5, 60, 2, clock=clock)
        limiter.check("a")
        clock.advance(30)
        limiter.check("b")
        clock.advance(31)                                          # "a" has expired, "b" has not
        self.assertTrue(limiter.check("c")[0])
        self.assertEqual(limiter.tracked_clients(), 2)


# ---- the real application -------------------------------------------------------------------------------------------------------
def server(**env):
    srv = ts._import_server_with_fakes({"TG_RATE_LIMIT_REQUESTS": None, "TG_MAX_REQUEST_BYTES": None,
                                        "TG_MAX_CONCURRENT_QUESTIONS": None, "TG_TRUSTED_PROXIES": None,
                                        "TG_SESSION_MAX": None, "TG_SESSION_TTL_SECONDS": None, **env})
    ts.FAKE_LLM["fn"] = ts.fake_llm()
    ts.FAKE_SEARCH["fn"] = None
    return srv, TestClient(srv.app, raise_server_exceptions=False)


class ServerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(ts.FAKE_SEARCH.update, {"fn": None})
        self.addCleanup(ts.FAKE_LLM.update, {"fn": lambda prompt: "stub answer"})

    def chat(self, client, sid="s", message=Q, **kw):
        return client.post("/chat", json={"message": message, "session_id": sid}, **kw)

    def test_normal_questions_are_unchanged(self):
        srv, client = server()
        r = self.chat(client)
        self.assertEqual(r.status_code, 200)
        # additive offence_date, law_band, notes with the /chat release-gate integration
        self.assertEqual(set(r.json()), {"response", "kind", "sources", "kb_approved", "source_warnings",
                                         "offence_date", "law_band", "notes"})
        self.assertEqual(srv.QUESTION_SLOTS.in_use, 0)

    def test_the_default_limit_of_ten_per_minute_applies_to_the_real_app(self):
        _, client = server()
        statuses = [self.chat(client, sid=f"s{i}").status_code for i in range(12)]
        self.assertEqual(statuses[:10], [200] * 10)
        self.assertEqual(statuses[10:], [429, 429])
        r = self.chat(client)
        self.assertGreaterEqual(int(r.headers["retry-after"]), 1)
        self.assertEqual(r.json(), {"detail": ap.GENERIC_RATE})

    def test_other_endpoints_are_not_limited(self):
        _, client = server(TG_RATE_LIMIT_REQUESTS="1")
        self.chat(client)
        self.assertEqual(self.chat(client).status_code, 429)
        for path in ("/health", "/ready", "/status", "/"):
            for _ in range(5):
                self.assertNotEqual(client.get(path).status_code, 429, path)

    def test_oversized_chat_requests_get_413_and_normal_ones_still_work(self):
        srv, client = server(TG_MAX_REQUEST_BYTES="1024")
        r = client.post("/chat", json={"message": "x" * 5000, "session_id": "s"})
        self.assertEqual((r.status_code, r.json()), (413, {"detail": ap.GENERIC_TOO_LARGE}))
        self.assertEqual(self.chat(client).status_code, 200)

    def test_the_default_cap_leaves_room_for_a_long_non_ascii_question(self):
        _, client = server()
        telugu = "డ్రైవింగ్ లైసెన్స్ కోసం ఎలా దరఖాస్తు చేయాలి? " * 20                # about 2.5 KB in UTF-8
        self.assertEqual(self.chat(client, message=telugu).status_code, 200)

    def test_the_cap_does_not_touch_other_routes(self):
        _, client = server(TG_MAX_REQUEST_BYTES="256")
        self.assertEqual(client.post("/approval/refresh", content=b"x" * 5000).status_code, 200)   # development: enabled
        self.assertEqual(client.get("/status").status_code, 200)

    def test_status_shows_limits_and_problems_but_no_client_or_secret_data(self):
        _, client = server(TG_RATE_LIMIT_REQUESTS="banana", TG_TRUSTED_PROXIES="10.9.9.9")
        text = client.get("/status").text
        p = json.loads(text)["protection"]
        self.assertEqual((p["rate_limit_requests"], p["max_request_bytes"], p["max_concurrent_questions"]), (10, 8192, 2))
        self.assertEqual(len(p["problems"]), 1)
        self.assertNotIn("banana", text)
        self.assertNotIn("10.9.9.9", text)

    def test_invalid_configuration_does_not_stop_the_server_and_uses_safe_defaults(self):
        srv, client = server(TG_RATE_LIMIT_REQUESTS="-5", TG_MAX_CONCURRENT_QUESTIONS="lots", TG_TRUSTED_PROXIES="*")
        self.assertEqual((srv.PROTECTION.rate_requests, srv.PROTECTION.max_concurrent, srv.PROTECTION.trusted_proxies), (10, 2, ()))
        self.assertEqual(self.chat(client).status_code, 200)

    def test_a_spoofed_forwarding_header_does_not_escape_the_real_app_limit(self):
        _, client = server(TG_RATE_LIMIT_REQUESTS="2")
        statuses = [self.chat(client, headers={"X-Forwarded-For": f"192.0.2.{i}"}).status_code for i in range(1, 5)]
        self.assertEqual(statuses, [200, 200, 429, 429])

    def test_cors_headers_are_present_on_refusals_so_the_frontend_can_read_them(self):
        origin = "https://example.github.io"
        _, client = server(TG_RATE_LIMIT_REQUESTS="1", TG_CORS_ORIGINS=origin)
        self.chat(client, headers={"Origin": origin})
        r = self.chat(client, headers={"Origin": origin})
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.headers.get("access-control-allow-origin"), origin)
        other = self.chat(client, headers={"Origin": "https://evil.example"})
        self.assertNotIn("access-control-allow-origin", other.headers)
        pre = client.options("/chat", headers={"Origin": origin, "Access-Control-Request-Method": "POST",
                                               "Access-Control-Request-Headers": "content-type"})
        self.assertEqual((pre.status_code, pre.headers.get("access-control-allow-origin")), (200, origin))

    def test_no_new_routes_were_added(self):
        srv, _ = server()
        paths = {getattr(r, "path", "") for r in srv.app.routes}
        self.assertEqual(paths - {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"},
                         {"/", "/health", "/ready", "/status", "/chat", "/approval/refresh", "/static",
                          "/release-gates"})  # reviewed: read-only diagnostics, not wired to /chat

    def test_a_provider_failure_is_a_controlled_503_that_releases_the_permit(self):
        srv, client = server()

        def failing(prompt):
            raise RuntimeError("secret-internal-detail /srv/app/trace")

        ts.FAKE_LLM["fn"] = failing
        r = self.chat(client)
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json(), {"detail": srv.PROVIDER_ERROR})
        self.assertNotIn("secret-internal-detail", r.text)
        self.assertNotIn("Traceback", r.text)
        self.assertEqual(srv.QUESTION_SLOTS.in_use, 0)
        ts.FAKE_LLM["fn"] = ts.fake_llm()
        self.assertEqual(self.chat(client, sid="again").status_code, 200)

    def test_a_timeout_in_the_provider_releases_the_permit(self):
        srv, client = server()

        def slow(prompt):
            raise TimeoutError("provider timed out")

        ts.FAKE_LLM["fn"] = slow
        self.assertEqual(self.chat(client).status_code, 503)
        self.assertEqual(srv.QUESTION_SLOTS.in_use, 0)

    def test_cancellation_inside_the_question_work_releases_the_permit(self):
        srv, client = server()

        def cancelled(prompt):
            raise asyncio.CancelledError()

        ts.FAKE_LLM["fn"] = cancelled
        try:
            self.chat(client)
        except BaseException:
            pass
        self.assertEqual(srv.QUESTION_SLOTS.in_use, 0)

    def test_simultaneous_questions_beyond_the_limit_get_a_controlled_503(self):
        srv, client = server(TG_MAX_CONCURRENT_QUESTIONS="2", TG_RATE_LIMIT_REQUESTS="100")
        entered, release = threading.Semaphore(0), threading.Event()
        lock, inside = threading.Lock(), [0]

        def blocking(prompt):
            with lock:
                inside[0] += 1
            entered.release()
            self.assertTrue(release.wait(15))
            return "stub answer"

        ts.FAKE_LLM["fn"] = blocking
        results = {}
        threads = [threading.Thread(target=lambda n=n: results.__setitem__(n, self.chat(client, sid=f"c{n}"))) for n in (1, 2)]
        [t.start() for t in threads]
        try:
            for _ in range(2):
                self.assertTrue(entered.acquire(timeout=15))
            self.assertEqual(srv.QUESTION_SLOTS.in_use, 2)
            third = self.chat(client, sid="c3")                       # arrives while both permits are taken
            self.assertEqual(third.status_code, 503)
            self.assertEqual(third.json(), {"detail": ap.GENERIC_BUSY})
            self.assertEqual(third.headers["retry-after"], str(ap.BUSY_RETRY_AFTER_SECONDS))
            self.assertEqual(inside[0], 2)                            # the refused one never reached the model path
        finally:
            release.set()
            [t.join(15) for t in threads]
        self.assertEqual([results[n].status_code for n in (1, 2)], [200, 200])
        self.assertEqual(srv.QUESTION_SLOTS.in_use, 0)
        ts.FAKE_LLM["fn"] = ts.fake_llm()
        self.assertEqual(self.chat(client, sid="c4").status_code, 200)   # capacity is back

    def test_deterministic_replies_do_not_take_a_permit(self):
        srv, client = server(TG_MAX_CONCURRENT_QUESTIONS="1", TG_RATE_LIMIT_REQUESTS="100")
        self.assertTrue(srv.QUESTION_SLOTS.try_acquire())             # the only permit is busy
        try:
            r = self.chat(client, message="What is the speed limit in Mumbai?")   # out-of-scope: answered without the model
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["kind"], "out_of_scope")
            self.assertEqual(self.chat(client).status_code, 503)      # a real question is refused
        finally:
            srv.QUESTION_SLOTS.release()

    def test_logs_never_contain_the_question_or_the_client_address(self):
        _, client = server(TG_RATE_LIMIT_REQUESTS="1", TG_MAX_REQUEST_BYTES="256")
        marker = "PRIVATE-QUESTION-TEXT-12345"
        with self.assertLogs("backend.api_protection", level="WARNING") as logs:
            self.chat(client, message=marker)
            client.post("/chat", json={"message": marker * 100, "session_id": "s"})
            self.chat(client, message=marker)
        joined = "\n".join(logs.output)
        self.assertNotIn(marker, joined)
        self.assertNotIn("testclient", joined)

    def test_the_guard_failing_closes_the_door_without_a_traceback(self):
        app = middleware()
        with mock.patch.object(app.limiter, "check", side_effect=RuntimeError("internal /secret/path")):
            status, headers, body, _ = call(app)
        self.assertEqual(status, 503)
        self.assertNotIn(b"internal", body)
        self.assertNotIn(b"Traceback", body)
        self.assertIn("retry-after", headers)


class RenderConfigTests(unittest.TestCase):
    def test_production_still_runs_exactly_one_worker(self):
        from pathlib import Path
        import yaml
        render = yaml.safe_load((Path(__file__).resolve().parent.parent / "deploy" / "render.yaml").read_text())
        start = render["services"][0]["startCommand"]
        self.assertIn("--workers 1", start)


if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)
    unittest.main()
