"""Stage 7A: query-embedding providers. Offline: mocked HTTP, fake clocks, no Ollama, no network, no key.
The hosted-provider code is exercised through requests-shaped fakes; nothing here contacts any service."""
import json
import logging
import math
import unittest

import requests

from backend import embedding_provider as ep
from backend import runtime_config

KEY = "sk-test-0123456789-THIS-MUST-NEVER-APPEAR"
BASE = {"EMBEDDING_PROVIDER": "openai_compatible", "EMBEDDING_API_URL": "https://embeddings.example/v1",
        "EMBEDDING_MODEL": "nomic-ai/nomic-embed-text-v1.5", "EMBEDDING_API_KEY": KEY}
DIMS = 8


def unit(seed, dims=DIMS):
    v = [math.sin(seed * (i + 1)) + 0.1 for i in range(dims)]
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


class Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def ok(vectors):
    return Resp(200, {"data": [{"index": i, "embedding": v} for i, v in enumerate(vectors)]})


class FakeHttp:
    """Scripted responses; each item is a Resp or an exception to raise."""

    def __init__(self, *script):
        self.script, self.calls = list(script), []

    def __call__(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        return item


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def guard(env=None, http=None, clock=None, dims=DIMS, probes=None, family=None, **kw):
    s = ep.EmbeddingSettings.from_env({**BASE, **(env or {})})
    sleeps = []
    g = ep.build_embeddings(s, http=http, sleep=sleeps.append, clock=clock or Clock())
    g.sleeps = sleeps
    g.configure_index(dims=dims, family=family, probes=probes)
    return g


def probes_for(vectors_by_text):
    return [{"input": t, "vector": v} for t, v in vectors_by_text.items()]


class SettingsTests(unittest.TestCase):
    def test_local_defaults_keep_the_previous_behaviour(self):
        s = ep.EmbeddingSettings.from_env({})
        self.assertEqual((s.provider, s.model, s.ollama_base_url, s.timeout_seconds, s.max_retries), ("ollama", "nomic-embed-text", "", None, 0))
        self.assertEqual(s.family, "nomic-embed-text-v1.5")
        self.assertEqual(s.problems, ())
        self.assertFalse(s.verification_required)

    def test_ollama_is_built_exactly_as_before(self):
        built = []
        ep.build_embeddings(ep.EmbeddingSettings.from_env({}), ollama_factory=lambda **k: built.append(k) or object())
        self.assertEqual(built, [{"model": "nomic-embed-text"}])  # same constructor call as the old OllamaEmbeddings(model=...)

    def test_ollama_url_model_and_timeout_are_configurable_and_separate_from_generation(self):
        built = []
        env = {"EMBEDDING_OLLAMA_BASE_URL": "http://10.0.0.5:11434/", "EMBEDDING_MODEL": "nomic-embed-text:latest",
               "EMBEDDING_TIMEOUT_SECONDS": "7", "OLLAMA_BASE_URL": "http://generation-host:1", "OLLAMA_MODEL": "llama3.2"}
        ep.build_embeddings(ep.EmbeddingSettings.from_env(env), ollama_factory=lambda **k: built.append(k) or object())
        self.assertEqual(built, [{"model": "nomic-embed-text:latest", "base_url": "http://10.0.0.5:11434", "client_kwargs": {"timeout": 7.0}}])

    def test_hosted_requires_url_model_and_key_and_never_defaults_a_model(self):
        for drop in ("EMBEDDING_API_URL", "EMBEDDING_MODEL", "EMBEDDING_API_KEY"):
            env = {k: v for k, v in BASE.items() if k != drop}
            s = ep.EmbeddingSettings.from_env(env)
            self.assertTrue(s.problems, drop)
            g = ep.build_embeddings(s, http=FakeHttp(ok([unit(1)])))
            self.assertEqual(g.state, "misconfigured")
            with self.assertRaises(ep.EmbeddingUnavailable) as cm:
                g.embed_query("x")
            self.assertEqual(cm.exception.reason, ep.NOT_CONFIGURED)

    def test_placeholder_key_counts_as_missing(self):
        for placeholder in ("your-embedding-key", "placeholder-key", ""):
            s = ep.EmbeddingSettings.from_env({**BASE, "EMBEDDING_API_KEY": placeholder})
            self.assertIn("EMBEDDING_API_KEY is not set", s.problems)

    def test_plain_http_and_url_tricks_are_refused_except_loopback(self):
        for url in ("http://embeddings.example/v1", "https://u:p@embeddings.example/v1", "https://e.example/v1?key=1", "ftp://e.example/v1"):
            self.assertTrue(ep.EmbeddingSettings.from_env({**BASE, "EMBEDDING_API_URL": url}).problems, url)
        self.assertFalse(ep.EmbeddingSettings.from_env({**BASE, "EMBEDDING_API_URL": "http://127.0.0.1:9/v1"}).problems)

    def test_unknown_provider_is_misconfigured_not_ollama(self):
        built = []
        g = ep.build_embeddings(ep.EmbeddingSettings.from_env({"EMBEDDING_PROVIDER": "cohere"}), ollama_factory=lambda **k: built.append(k))
        self.assertEqual(g.state, "misconfigured")
        self.assertEqual(built, [])
        with self.assertRaises(ep.EmbeddingUnavailable):
            g.embed_query("x")

    def test_bad_numbers_are_reported_and_clamped(self):
        s = ep.EmbeddingSettings.from_env({**BASE, "EMBEDDING_TIMEOUT_SECONDS": "soon", "EMBEDDING_MAX_RETRIES": "99"})
        self.assertTrue(any("EMBEDDING_TIMEOUT_SECONDS" in p for p in s.problems))
        self.assertEqual(s.max_retries, 5)

    def test_describe_and_repr_never_show_the_key_or_the_full_url(self):
        s = ep.EmbeddingSettings.from_env({**BASE, "EMBEDDING_API_URL": "https://embeddings.example/v1/secret-path"})
        for text in (repr(s), json.dumps(s.describe())):
            self.assertNotIn(KEY, text)
            self.assertNotIn("secret-path", text)
        self.assertEqual(s.describe()["endpoint_host"], "embeddings.example")

    def test_cors_origins_accept_exact_https_origins_only(self):
        ok_, bad = runtime_config.cors_origins({"TG_CORS_ORIGINS": "https://user.github.io, http://localhost:5173,https://a.example/"})
        self.assertEqual(ok_, ["https://user.github.io", "http://localhost:5173", "https://a.example"])
        self.assertEqual(bad, [])
        for item in ("*", "https://*.github.io", "http://evil.example", "https://user.github.io/app", "user.github.io", "https://u@x.example",
                     "https://x.example?a=1"):
            self.assertEqual(runtime_config.cors_origins({"TG_CORS_ORIGINS": item}), ([], [item.rstrip("/")]), item)
        self.assertEqual(runtime_config.cors_origins({}), ([], []))


class HostedRequestTests(unittest.TestCase):
    def test_request_shape_and_credentials_only_in_the_authorization_header(self):
        http = FakeHttp(ok([unit(1)]))
        g = guard(http=http, env={"EMBEDDING_VERIFY": "off"})
        self.assertEqual(g.embed_query("search_query: helmet"), unit(1))
        call = http.calls[0]
        self.assertEqual(call["url"], "https://embeddings.example/v1/embeddings")
        self.assertEqual(call["json"], {"model": "nomic-ai/nomic-embed-text-v1.5", "input": ["search_query: helmet"]})
        self.assertEqual(call["headers"]["Authorization"], f"Bearer {KEY}")
        self.assertNotIn(KEY, call["url"] + json.dumps(call["json"]))
        self.assertEqual(call["timeout"], 10.0)

    def test_dimensions_are_sent_only_when_asked_for(self):
        http = FakeHttp(ok([unit(1)]))
        guard(http=http, env={"EMBEDDING_VERIFY": "off", "EMBEDDING_DIMENSIONS": str(DIMS), "EMBEDDING_SEND_DIMENSIONS": "1"}).embed_query("q")
        self.assertEqual(http.calls[0]["json"]["dimensions"], DIMS)
        http2 = FakeHttp(ok([unit(1)]))
        guard(http=http2, env={"EMBEDDING_VERIFY": "off"}).embed_query("q")
        self.assertNotIn("dimensions", http2.calls[0]["json"])

    def test_url_already_ending_in_embeddings_is_not_doubled(self):
        http = FakeHttp(ok([unit(1)]))
        guard(http=http, env={"EMBEDDING_VERIFY": "off", "EMBEDDING_API_URL": "https://e.example/v1/embeddings"}).embed_query("q")
        self.assertEqual(http.calls[0]["url"], "https://e.example/v1/embeddings")

    def test_batch_rows_are_reordered_by_index(self):
        a, b = unit(1), unit(2)
        http = FakeHttp(Resp(200, {"data": [{"index": 1, "embedding": b}, {"index": 0, "embedding": a}]}))
        g = guard(http=http, env={"EMBEDDING_VERIFY": "off"})
        self.assertEqual(g.embed_documents(["x", "y"]), [a, b])

    def test_malformed_responses_are_bad_response_not_a_vector(self):
        for body in ({}, {"data": []}, {"data": [{"embedding": "AAAA"}]}, {"data": [{"embedding": [1, "x"]}]}, {"data": "x"},
                     {"data": [{"embedding": [float("nan")] * DIMS}]}, ValueError("not json")):
            g = guard(http=FakeHttp(Resp(200, body)), env={"EMBEDDING_VERIFY": "off"})
            with self.assertRaises(ep.EmbeddingUnavailable) as cm:
                g.embed_query("q")
            self.assertEqual(cm.exception.reason, ep.BAD_RESPONSE, body)
            self.assertNotIsInstance(cm.exception, ValueError)


class FailureTests(unittest.TestCase):
    def failing(self, *script, **env):
        http = FakeHttp(*script)
        return guard(http=http, env={"EMBEDDING_VERIFY": "off", **env}), http

    def test_timeout_is_a_safe_failure_and_is_not_retried(self):
        g, http = self.failing(requests.Timeout("slow KEY=" + KEY))
        with self.assertRaises(ep.EmbeddingUnavailable) as cm:
            g.embed_query("q")
        self.assertEqual((cm.exception.reason, len(http.calls)), (ep.TIMEOUT, 1))
        self.assertNotIn(KEY, str(cm.exception))

    def test_rate_limit_waits_the_advised_time_then_succeeds(self):
        g, http = self.failing(Resp(429, {}, {"Retry-After": "2"}), ok([unit(3)]))
        self.assertEqual(g.embed_query("q"), unit(3))
        self.assertEqual((len(http.calls), g.sleeps), (2, [2.0]))

    def test_rate_limit_asking_for_a_long_wait_fails_fast(self):
        g, http = self.failing(Resp(429, {}, {"Retry-After": "120"}))
        with self.assertRaises(ep.EmbeddingUnavailable) as cm:
            g.embed_query("q")
        self.assertEqual((cm.exception.reason, cm.exception.status, len(http.calls), g.sleeps), (ep.RATE_LIMITED, 429, 1, []))

    def test_server_errors_and_connection_errors_are_retried_a_bounded_number_of_times(self):
        g, http = self.failing(Resp(503), requests.ConnectionError("down"), Resp(502))
        with self.assertRaises(ep.EmbeddingUnavailable) as cm:
            g.embed_query("q")
        self.assertEqual((cm.exception.reason, len(http.calls), g.sleeps), (ep.UNAVAILABLE, 3, [0.5, 1.0]))  # 1 + EMBEDDING_MAX_RETRIES(2)

    def test_auth_and_bad_request_are_not_retried(self):
        for status, reason in ((401, ep.AUTH), (403, ep.AUTH), (400, ep.BAD_REQUEST), (404, ep.BAD_REQUEST)):
            g, http = self.failing(Resp(status, {"error": "KEY " + KEY}))
            with self.assertRaises(ep.EmbeddingUnavailable) as cm:
                g.embed_query("q")
            self.assertEqual((cm.exception.reason, len(http.calls)), (reason, 1), status)
            self.assertNotIn(KEY, str(cm.exception))   # provider text is never copied into the error

    def test_unexpected_exception_from_a_backend_is_contained(self):
        class Boom:
            def embed(self, texts):
                raise RuntimeError("secret " + KEY)
        g = ep.GuardedEmbeddings(ep.EmbeddingSettings.from_env({**BASE, "EMBEDDING_VERIFY": "off"}), Boom())
        with self.assertRaises(ep.EmbeddingUnavailable) as cm:
            g.embed_query("q")
        self.assertNotIn(KEY, str(cm.exception))

    def test_circuit_breaker_stops_calling_a_failing_provider_and_recovers(self):
        clock = Clock()
        http = FakeHttp(Resp(500), Resp(500), Resp(500), ok([unit(1)]))
        g = guard(http=http, clock=clock, env={"EMBEDDING_VERIFY": "off", "EMBEDDING_MAX_RETRIES": "0", "EMBEDDING_BREAKER_FAILURES": "3"})
        for _ in range(3):
            with self.assertRaises(ep.EmbeddingUnavailable):
                g.embed_query("q")
        self.assertEqual(g.state, "unavailable")
        before = len(http.calls)
        with self.assertRaises(ep.EmbeddingUnavailable) as cm:
            g.embed_query("q")
        self.assertEqual((cm.exception.reason, len(http.calls)), (ep.CIRCUIT_OPEN, before))   # no call made
        clock.t += 31
        self.assertEqual(g.embed_query("q"), unit(1))
        self.assertEqual(g.state, "ok")


class CompatibilityTests(unittest.TestCase):
    def test_wrong_dimension_is_incompatible_and_sticky(self):
        http = FakeHttp(ok([unit(1, DIMS + 4)]), ok([unit(1)]))
        g = guard(http=http, env={"EMBEDDING_VERIFY": "off"})
        with self.assertRaises(ep.EmbeddingIncompatible) as cm:
            g.embed_query("q")
        self.assertEqual(cm.exception.reason, ep.DIMENSION_MISMATCH)
        self.assertEqual(g.state, "incompatible")
        n = len(http.calls)
        with self.assertRaises(ep.EmbeddingIncompatible):
            g.embed_query("q")                         # refuses without asking the provider again
        self.assertEqual(len(http.calls), n)

    def test_configured_dimensions_contradicting_the_index_are_incompatible(self):
        g = guard(http=FakeHttp(ok([unit(1)])), env={"EMBEDDING_DIMENSIONS": "768"})
        self.assertEqual(g.state, "incompatible")
        with self.assertRaises(ep.EmbeddingIncompatible):
            g.embed_query("q")

    def test_vector_that_is_not_unit_length_is_refused_unless_normalising_is_chosen(self):
        big = [x * 3 for x in unit(1)]
        g = guard(http=FakeHttp(ok([big])), env={"EMBEDDING_VERIFY": "off"})
        with self.assertRaises(ep.EmbeddingIncompatible) as cm:
            g.embed_query("q")
        self.assertEqual(cm.exception.reason, ep.NOT_NORMALIZED)
        g2 = guard(http=FakeHttp(ok([big])), env={"EMBEDDING_VERIFY": "off", "EMBEDDING_NORMALIZE": "1"})
        got = g2.embed_query("q")
        self.assertAlmostEqual(math.sqrt(sum(x * x for x in got)), 1.0, places=9)
        self.assertAlmostEqual(ep.cosine(got, unit(1)), 1.0, places=9)

    def test_different_model_family_is_incompatible_even_with_the_right_dimensions(self):
        g = guard(http=FakeHttp(ok([unit(1)])), env={"EMBEDDING_MODEL": "BAAI/bge-base-en-v1.5"}, family="nomic-embed-text-v1.5")
        self.assertEqual(g.state, "incompatible")
        self.assertIn("not known to be that model", " ".join(g.health()["problems"]))
        self.assertEqual(guard(env={"EMBEDDING_MODEL": "BAAI/bge-base-en-v1.5", "EMBEDDING_MODEL_FAMILY": "nomic-embed-text-v1.5"},
                               http=FakeHttp(ok([unit(1)])), family="nomic-embed-text-v1.5").state, "unverified")  # operator asserts, probes decide

    def test_hosted_provider_is_unusable_until_it_matches_the_probes(self):
        texts = ["search_document: probe one", "search_document: probe two"]
        ref = {t: unit(i + 1) for i, t in enumerate(texts)}
        http = FakeHttp(ok(list(ref.values())), ok([unit(9)]))
        g = guard(http=http, probes=probes_for(ref))
        self.assertEqual((g.state, g.ready()), ("unverified", False))
        self.assertEqual(g.embed_query("q"), unit(9))          # the first query verifies first
        self.assertEqual([c["json"]["input"] for c in http.calls], [texts, ["q"]])
        self.assertEqual((g.state, g.ready()), ("ok", True))
        self.assertTrue(g.health()["verification"]["ok"])

    def test_probe_mismatch_means_another_model_and_no_query_vector_is_returned(self):
        texts = ["search_document: probe one"]
        http = FakeHttp(ok([unit(50)]), ok([unit(1)]))   # right size and length, wrong direction
        g = guard(http=http, probes=probes_for({texts[0]: unit(1)}))
        with self.assertRaises(ep.EmbeddingIncompatible) as cm:
            g.embed_query("q")
        self.assertEqual(cm.exception.reason, ep.INCOMPATIBLE)
        self.assertEqual(g.state, "incompatible")
        self.assertEqual(len(http.calls), 1)               # the query itself was never sent
        with self.assertRaises(ep.EmbeddingIncompatible):
            g.embed_query("q")
        self.assertEqual(len(http.calls), 1)

    def test_hosted_without_probes_fails_closed_unless_the_operator_turns_verification_off(self):
        g = guard(http=FakeHttp(ok([unit(1)])))
        with self.assertRaises(ep.EmbeddingUnavailable) as cm:
            g.embed_query("q")
        self.assertEqual(cm.exception.reason, ep.NOT_VERIFIED)
        self.assertEqual((g.state, g.ready()), ("unverified", False))
        off = guard(http=FakeHttp(ok([unit(1)])), env={"EMBEDDING_VERIFY": "off"})
        self.assertEqual(off.embed_query("q"), unit(1))

    def test_transient_outage_during_verification_is_retried_later_not_marked_incompatible(self):
        clock = Clock()
        ref = {"search_document: p": unit(1)}
        http = FakeHttp(Resp(500), Resp(500), Resp(500), ok([unit(1)]), ok([unit(2)]))
        g = guard(http=http, clock=clock, probes=probes_for(ref))
        with self.assertRaises(ep.EmbeddingUnavailable):
            g.embed_query("q")
        self.assertEqual(g.state, "unavailable")
        with self.assertRaises(ep.EmbeddingUnavailable):
            g.embed_query("q")                      # inside the re-verify window: not asked again
        clock.t += 61
        self.assertEqual(g.embed_query("q"), unit(2))
        self.assertEqual(g.state, "ok")

    def test_ollama_default_checks_dimensions_but_needs_no_probes(self):
        class Fake:
            def embed_documents(self, texts):
                return [unit(1, DIMS + 1) for _ in texts]
        g = ep.build_embeddings(ep.EmbeddingSettings.from_env({}), ollama_factory=lambda **k: Fake())
        g.configure_index(dims=DIMS)
        self.assertEqual(g.state, "ok")
        with self.assertRaises(ep.EmbeddingIncompatible):
            g.embed_query("q")


class NoLocalFallbackTests(unittest.TestCase):
    def test_hosted_mode_never_builds_or_calls_ollama_even_when_every_hosted_call_fails(self):
        built = []
        s = ep.EmbeddingSettings.from_env({**BASE, "EMBEDDING_VERIFY": "off"})
        g = ep.build_embeddings(s, http=FakeHttp(Resp(500)), sleep=lambda x: None, ollama_factory=lambda **k: built.append(k))
        g.configure_index(dims=DIMS)
        for _ in range(5):
            with self.assertRaises(ep.EmbeddingUnavailable):
                g.embed_query("q")
        self.assertEqual(built, [])

    def test_misconfigured_hosted_mode_does_not_fall_back_to_ollama_either(self):
        built = []
        g = ep.build_embeddings(ep.EmbeddingSettings.from_env({"EMBEDDING_PROVIDER": "openai_compatible"}), ollama_factory=lambda **k: built.append(k))
        with self.assertRaises(ep.EmbeddingUnavailable):
            g.embed_query("q")
        self.assertEqual(built, [])

    def test_ollama_failure_is_a_safe_failure(self):
        class Down:
            def embed_documents(self, texts):
                raise ConnectionRefusedError("[Errno 61] Connection refused")
        g = ep.build_embeddings(ep.EmbeddingSettings.from_env({}), ollama_factory=lambda **k: Down())
        with self.assertRaises(ep.EmbeddingUnavailable) as cm:
            g.embed_query("q")
        self.assertEqual(cm.exception.reason, ep.CONNECTION)

    def test_missing_langchain_ollama_package_is_reported_not_raised_at_startup(self):
        def missing(**k):
            raise ImportError("No module named langchain_ollama")
        g = ep.build_embeddings(ep.EmbeddingSettings.from_env({}), ollama_factory=missing)
        with self.assertRaises(ep.EmbeddingUnavailable) as cm:
            g.embed_query("q")
        self.assertEqual(cm.exception.reason, ep.NOT_CONFIGURED)


class SecretHygieneTests(unittest.TestCase):
    def test_key_never_reaches_logs_health_or_exceptions(self):
        records = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())
        handler = Capture()
        logger = logging.getLogger("kyr")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        self.addCleanup(logger.removeHandler, handler)
        texts = []
        for script in ([Resp(401, {"error": KEY})], [requests.Timeout(KEY)], [requests.ConnectionError(KEY)], [Resp(200, {"data": [{"embedding": [KEY]}]})]):
            g = guard(http=FakeHttp(*script), env={"EMBEDDING_VERIFY": "off", "EMBEDDING_MAX_RETRIES": "0"})
            try:
                g.embed_query("q")
            except ep.EmbeddingUnavailable as err:
                texts += [str(err), repr(err)]
            texts.append(json.dumps(g.health()))
        self.assertTrue(records)  # failures were logged...
        for text in texts + records:
            self.assertNotIn(KEY, text)  # ...without the key


if __name__ == "__main__":
    unittest.main()
