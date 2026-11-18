"""Stage 7B: the zero-cost cloud embedding path. Offline: mocked HTTP (requests-shaped), fake clocks, no Ollama, no network, no account.
Nothing here proves that a real provider serves the index's model; it proves that, whichever provider is configured, an incompatible,
unavailable or misconfigured one can never produce a query vector, and that a cloud process never falls back to Ollama."""
import logging
import unittest

import requests

import test_embedding_provider as tep
from backend import embedding_provider as ep

KEY = "nk-test-0123456789-THIS-MUST-NEVER-APPEAR"
ATLAS = {"EMBEDDING_PROVIDER": "nomic_atlas", "EMBEDDING_MODEL": "nomic-embed-text-v1.5", "EMBEDDING_API_KEY": KEY}
DIMS = tep.DIMS
unit, Resp, FakeHttp, Clock = tep.unit, tep.Resp, tep.FakeHttp, tep.Clock


def atlas_ok(vectors):
    return Resp(200, {"embeddings": vectors, "usage": {"prompt_tokens": 1, "total_tokens": 1}, "model": "nomic-embed-text-v1.5"})


def guard(env=None, http=None, clock=None, dims=DIMS, probes=None, family=None, ollama_factory=None):
    s = ep.EmbeddingSettings.from_env({**ATLAS, **(env or {})})
    sleeps = []
    g = ep.build_embeddings(s, http=http, sleep=sleeps.append, clock=clock or Clock(), ollama_factory=ollama_factory)
    g.sleeps = sleeps
    g.configure_index(dims=dims, family=family, probes=probes)
    return g


class CloudConfigurationTests(unittest.TestCase):
    CLOUD = ({"TG_SNAPSHOT_STORE": "r2"}, {"TG_CLOUD": "1"}, {"RENDER": "true"})

    def test_local_development_is_unchanged_and_needs_nothing(self):
        for env in ({}, {"TG_SNAPSHOT_STORE": "local"}, {"TG_ENVIRONMENT": "development"}, {"EMBEDDING_PROVIDER": "ollama"}):
            s = ep.EmbeddingSettings.from_env(env)
            self.assertEqual((s.provider, s.model, s.problems, s.hosted), ("ollama", "nomic-embed-text", (), False), env)

    def test_a_cloud_deployment_has_no_default_provider(self):
        for trigger in self.CLOUD:
            s = ep.EmbeddingSettings.from_env(trigger)
            self.assertTrue(any("EMBEDDING_PROVIDER must be set explicitly" in p for p in s.problems), trigger)
            g = ep.build_embeddings(s, ollama_factory=lambda **k: self.fail("Ollama must not be built"))
            self.assertEqual(g.state, "misconfigured")
            with self.assertRaises(ep.EmbeddingUnavailable) as cm:
                g.embed_query("q")
            self.assertEqual(cm.exception.reason, ep.NOT_CONFIGURED)

    def test_a_cloud_deployment_refuses_ollama_even_when_asked(self):
        for trigger in self.CLOUD:
            s = ep.EmbeddingSettings.from_env({**trigger, "EMBEDDING_PROVIDER": "ollama"})
            self.assertTrue(any("local development only" in p for p in s.problems), trigger)
            built = []
            g = ep.build_embeddings(s, ollama_factory=lambda **k: built.append(k))
            with self.assertRaises(ep.EmbeddingUnavailable):
                g.embed_query("q")
            self.assertEqual((built, g.state), ([], "misconfigured"))

    def test_hosted_providers_are_allowed_in_the_cloud(self):
        for env in (ATLAS, tep.BASE):
            self.assertEqual(ep.EmbeddingSettings.from_env({**env, "TG_SNAPSHOT_STORE": "r2"}).problems, (), env["EMBEDDING_PROVIDER"])

    def test_the_atlas_adapter_defaults_to_nomics_https_endpoint_and_assumes_no_model(self):
        s = ep.EmbeddingSettings.from_env(ATLAS)
        self.assertEqual((s.provider, s.hosted, s.api_url, s.problems), ("nomic_atlas", True, "https://api-atlas.nomic.ai", ()))
        self.assertEqual((s.family, s.verification_required), ("nomic-embed-text-v1.5", True))
        self.assertEqual(s.describe()["endpoint_host"], "api-atlas.nomic.ai")
        no_model = ep.EmbeddingSettings.from_env({k: v for k, v in ATLAS.items() if k != "EMBEDDING_MODEL"})
        self.assertTrue(any("EMBEDDING_MODEL is required" in p for p in no_model.problems))

    def test_missing_credentials_and_unsafe_endpoints_are_misconfigurations(self):
        for env, needle in (({"EMBEDDING_API_KEY": ""}, "EMBEDDING_API_KEY"), ({"EMBEDDING_API_KEY": "your-nomic-key"}, "EMBEDDING_API_KEY"),
                            ({"EMBEDDING_API_URL": "http://api-atlas.nomic.ai"}, "https")):
            s = ep.EmbeddingSettings.from_env({**ATLAS, **env})
            self.assertTrue(any(needle in p for p in s.problems), env)
            g = ep.build_embeddings(s, http=lambda *a, **k: self.fail("a misconfigured provider must not call out"))
            self.assertEqual(g.state, "misconfigured")
            with self.assertRaises(ep.EmbeddingUnavailable):
                g.embed_query("search_query: q")

    def test_a_cloud_process_never_builds_ollama_whatever_the_hosted_provider_does(self):
        for failing in (Resp(500), Resp(429), Resp(401), requests.Timeout(), requests.ConnectionError()):
            g = guard({"EMBEDDING_VERIFY": "off", "TG_SNAPSHOT_STORE": "r2"}, http=FakeHttp(failing),
                      ollama_factory=lambda **k: self.fail("Ollama must not be built"))
            for _ in range(4):
                with self.assertRaises(ep.EmbeddingUnavailable):
                    g.embed_query("search_query: q")


class AtlasBackendTests(unittest.TestCase):
    def test_request_shape_task_type_replaces_the_prefix_and_the_key_is_only_a_header(self):
        http = FakeHttp(atlas_ok([unit(1)]))
        g = guard({"EMBEDDING_VERIFY": "off"}, http=http)
        self.assertEqual(g.embed_query("search_query: how do I renew a licence?"), unit(1))
        call = http.calls[0]
        self.assertEqual(call["url"], "https://api-atlas.nomic.ai/v1/embedding/text")
        self.assertEqual(call["json"], {"texts": ["how do I renew a licence?"], "model": "nomic-embed-text-v1.5", "task_type": "search_query"})
        self.assertEqual(call["headers"]["Authorization"], f"Bearer {KEY}")
        self.assertNotIn(KEY, repr(call["json"]) + call["url"])
        self.assertEqual(call["timeout"], 10.0)

    def test_documents_use_the_document_task_and_mixed_batches_keep_their_order(self):
        http = FakeHttp(atlas_ok([unit(1), unit(3)]), atlas_ok([unit(2)]))
        g = guard({"EMBEDDING_VERIFY": "off"}, http=http)
        out = g.embed_documents(["search_document: a", "search_query: b", "search_document: c"])
        self.assertEqual(out, [unit(1), unit(2), unit(3)])
        self.assertEqual([(c["json"]["task_type"], c["json"]["texts"]) for c in http.calls],
                         [("search_document", ["a", "c"]), ("search_query", ["b"])])

    def test_text_without_a_task_prefix_is_refused_before_anything_is_sent(self):
        http = FakeHttp(atlas_ok([unit(1)]))
        g = guard({"EMBEDDING_VERIFY": "off"}, http=http)
        with self.assertRaises(ep.EmbeddingUnavailable) as cm:
            g.embed_query("a query the index profile left unprefixed")
        self.assertEqual(cm.exception.reason, ep.INCOMPATIBLE)
        self.assertEqual(http.calls, [])

    def test_dimensionality_is_sent_only_when_asked_for(self):
        http = FakeHttp(atlas_ok([unit(1)]))
        guard({"EMBEDDING_VERIFY": "off", "EMBEDDING_DIMENSIONS": str(DIMS)}, http=http).embed_query("search_query: q")
        self.assertNotIn("dimensionality", http.calls[0]["json"])
        http = FakeHttp(atlas_ok([unit(1)]))
        guard({"EMBEDDING_VERIFY": "off", "EMBEDDING_DIMENSIONS": str(DIMS), "EMBEDDING_SEND_DIMENSIONS": "1"}, http=http).embed_query("search_query: q")
        self.assertEqual(http.calls[0]["json"]["dimensionality"], DIMS)

    def test_malformed_responses_are_a_bad_response_never_a_vector(self):
        for body in ({"data": [{"embedding": unit(1)}]}, {"embeddings": "x"}, {"embeddings": []}, {"embeddings": [unit(1), unit(2)]}, [], None,
                     {"embeddings": [["a", "b"]]}, ValueError("not json")):
            g = guard({"EMBEDDING_VERIFY": "off"}, http=FakeHttp(Resp(200, body)))
            with self.assertRaises(ep.EmbeddingUnavailable) as cm:
                g.embed_query("search_query: q")
            self.assertEqual(cm.exception.reason, ep.BAD_RESPONSE, body)

    def test_rate_limit_timeout_and_server_errors_are_bounded_and_safe(self):
        # 429 with Retry-After: waits the advised time, then succeeds
        g = guard({"EMBEDDING_VERIFY": "off"}, http=FakeHttp(Resp(429, headers={"Retry-After": "2"}), atlas_ok([unit(1)])))
        self.assertEqual(g.embed_query("search_query: q"), unit(1))
        self.assertEqual(g.sleeps, [2.0])
        # a provider asking for a long wait fails fast (a user is waiting)
        http = FakeHttp(Resp(429, headers={"Retry-After": "600"}), atlas_ok([unit(1)]))
        with self.assertRaises(ep.EmbeddingUnavailable) as cm:
            guard({"EMBEDDING_VERIFY": "off"}, http=http).embed_query("search_query: q")
        self.assertEqual((cm.exception.reason, len(http.calls)), (ep.RATE_LIMITED, 1))
        # 5xx: retried a bounded number of times (default 2), then reported
        http = FakeHttp(Resp(503))
        with self.assertRaises(ep.EmbeddingUnavailable) as cm:
            guard({"EMBEDDING_VERIFY": "off"}, http=http).embed_query("search_query: q")
        self.assertEqual((cm.exception.reason, len(http.calls)), (ep.UNAVAILABLE, 3))
        # timeout: a safe failure and not retried
        http = FakeHttp(requests.Timeout())
        with self.assertRaises(ep.EmbeddingUnavailable) as cm:
            guard({"EMBEDDING_VERIFY": "off"}, http=http).embed_query("search_query: q")
        self.assertEqual((cm.exception.reason, len(http.calls)), (ep.TIMEOUT, 1))
        # bad credentials and bad requests are never retried
        for status, reason in ((401, ep.AUTH), (403, ep.AUTH), (422, ep.BAD_REQUEST)):
            http = FakeHttp(Resp(status))
            with self.assertRaises(ep.EmbeddingUnavailable) as cm:
                guard({"EMBEDDING_VERIFY": "off"}, http=http).embed_query("search_query: q")
            self.assertEqual((cm.exception.reason, len(http.calls)), (reason, 1), status)

    def test_after_the_free_allowance_runs_out_the_service_degrades_to_a_503_and_recovers(self):
        clock = Clock()
        http = FakeHttp(Resp(429), Resp(429), Resp(429), Resp(429), Resp(429), Resp(429), atlas_ok([unit(7)]))
        g = guard({"EMBEDDING_VERIFY": "off", "EMBEDDING_BREAKER_FAILURES": "2", "EMBEDDING_BREAKER_COOLDOWN_SECONDS": "30"}, http=http, clock=clock)
        for _ in range(2):
            with self.assertRaises(ep.EmbeddingUnavailable):
                g.embed_query("search_query: q")
        calls = len(http.calls)
        with self.assertRaises(ep.EmbeddingUnavailable) as cm:     # breaker open: the provider is not even asked
            g.embed_query("search_query: q")
        self.assertEqual((cm.exception.reason, len(http.calls)), (ep.CIRCUIT_OPEN, calls))
        self.assertEqual(g.state, "unavailable")
        clock.t += 31
        http.script = [atlas_ok([unit(7)])]
        self.assertEqual(g.embed_query("search_query: q"), unit(7))
        self.assertEqual(g.state, "ok")

    def test_the_key_never_reaches_health_exceptions_or_logs(self):
        records = []

        class H(logging.Handler):
            def emit(self, r):
                records.append(r.getMessage())
        handler = H(logging.DEBUG)
        logging.getLogger().addHandler(handler)
        self.addCleanup(logging.getLogger().removeHandler, handler)
        for failing in (Resp(401), Resp(500, {"error": KEY}), requests.ConnectionError(KEY), Resp(200, {"embeddings": KEY})):
            g = guard({"EMBEDDING_VERIFY": "off"}, http=FakeHttp(failing))
            with self.assertRaises(ep.EmbeddingUnavailable) as cm:
                g.embed_query("search_query: q")
            self.assertNotIn(KEY, str(cm.exception) + repr(g.health()) + repr(g.settings))
        self.assertFalse([m for m in records if KEY in m])


class AtlasCompatibilityTests(unittest.TestCase):
    """Same dimensions are not the same model. The index decides; the provider is checked against it."""

    def test_a_model_that_is_not_the_index_family_is_incompatible_before_any_call(self):
        for model in ("nomic-embed-text-v1", "bge-base-en-v1.5", "text-embedding-3-small"):
            http = FakeHttp(atlas_ok([unit(1)]))
            g = guard({"EMBEDDING_MODEL": model, "EMBEDDING_VERIFY": "off"}, http=http, family="nomic-embed-text-v1.5")
            self.assertEqual(g.state, "incompatible", model)
            with self.assertRaises(ep.EmbeddingIncompatible):
                g.embed_query("search_query: q")
            self.assertEqual(http.calls, [], model)

    def test_dimension_mismatch_is_incompatible_and_permanent(self):
        http = FakeHttp(atlas_ok([unit(1, DIMS * 2)]), atlas_ok([unit(1)]))
        g = guard({"EMBEDDING_VERIFY": "off"}, http=http)
        with self.assertRaises(ep.EmbeddingIncompatible) as cm:
            g.embed_query("search_query: q")
        self.assertEqual(cm.exception.reason, ep.DIMENSION_MISMATCH)
        with self.assertRaises(ep.EmbeddingIncompatible):          # even once the provider "behaves": no mixing within a process
            g.embed_query("search_query: q")
        self.assertEqual((g.state, len(http.calls)), ("incompatible", 1))

    def test_unscaled_vectors_are_refused_not_rescaled(self):
        g = guard({"EMBEDDING_VERIFY": "off"}, http=FakeHttp(atlas_ok([[x * 3 for x in unit(1)]])))
        with self.assertRaises(ep.EmbeddingIncompatible) as cm:
            g.embed_query("search_query: q")
        self.assertEqual((cm.exception.reason, g.state), (ep.NOT_NORMALIZED, "incompatible"))

    def test_the_probe_check_against_the_snapshot_decides_compatibility(self):
        probes = tep.probes_for({"search_document: probe one": unit(1), "search_document: probe two": unit(2)})
        http = FakeHttp(atlas_ok([unit(1), unit(2)]), atlas_ok([unit(9)]))
        g = guard(http=http, probes=probes)
        self.assertEqual((g.state, g.ready()), ("unverified", False))
        self.assertEqual(g.embed_query("search_query: q"), unit(9))
        self.assertEqual(http.calls[0]["json"], {"texts": ["probe one", "probe two"], "model": "nomic-embed-text-v1.5", "task_type": "search_document"})
        self.assertEqual((g.state, g.ready()), ("ok", True))

    def test_a_provider_whose_vectors_differ_from_the_stored_ones_never_answers_a_query(self):
        probes = tep.probes_for({"search_document: probe one": unit(1)})
        http = FakeHttp(atlas_ok([unit(40)]), atlas_ok([unit(1)]))   # right size, unit length, wrong direction: another model
        g = guard(http=http, probes=probes)
        for _ in range(3):
            with self.assertRaises(ep.EmbeddingIncompatible):
                g.embed_query("search_query: q")
        self.assertEqual((g.state, len(http.calls)), ("incompatible", 1))   # only the probe was sent; the query never was

    def test_without_probes_a_hosted_provider_is_not_trusted(self):
        g = guard(http=FakeHttp(atlas_ok([unit(1)])))
        with self.assertRaises(ep.EmbeddingUnavailable) as cm:
            g.embed_query("search_query: q")
        self.assertEqual((cm.exception.reason, g.state, g.ready()), (ep.NOT_VERIFIED, "unverified", False))

    def test_local_ollama_still_works_exactly_as_before_outside_the_cloud(self):
        class Fake:
            def embed_documents(self, texts):
                return [unit(1) for _ in texts]
        g = ep.build_embeddings(ep.EmbeddingSettings.from_env({}), ollama_factory=lambda **k: Fake())
        g.configure_index(dims=DIMS)
        self.assertEqual((g.state, g.embed_query("search_query: q")), ("ok", unit(1)))


if __name__ == "__main__":
    unittest.main()
