"""Stage 3: multi-provider grounded generation (Groq -> Gemini -> Ollama). Offline and deterministic.

No network: every provider's HTTP call goes to FakeHTTP, which returns responses shaped like each provider's real
success and error bodies (Groq OpenAI-style 429 messages, Gemini RESOURCE_EXHAUSTED with QuotaFailure details,
Ollama /api/chat). Sleeps and clocks are injected, so retries cost no time.

Two layers:
  * ProviderUnitTests: fallback order, error classification, bounded retries, configuration, secrets.
  * ProviderServerTests: the real /chat grounded path with the real validator; providers are the only fake.
"""

import json
import logging
import unittest
from unittest import mock

import requests
from langchain_core.documents import Document

import test_server as ts
from test_server import FAKE_LLM, FAKE_SEARCH, srv

from backend import grounded_answer, legal_approval, providers

GROQ_KEY = "test-groq-key-SECRET-1111"
GEMINI_KEY = "test-gemini-key-SECRET-2222"
SECRETS = (GROQ_KEY, GEMINI_KEY)


# ---------------------------------------------------------------------------------------------------
# Fake HTTP
# ---------------------------------------------------------------------------------------------------
class FakeResponse:
    def __init__(self, status, body=None, headers=None, text=None):
        self.status_code, self._body, self.headers = status, body, headers or {}
        self.text = text if text is not None else json.dumps(body)

    def json(self):
        if self._body is None:
            raise ValueError("no JSON")
        return self._body


def provider_of(url):
    if "api.groq.com" in url:
        return "groq"
    if "generativelanguage.googleapis.com" in url:
        return "gemini"
    return "ollama"


class FakeHTTP:
    """Scripted per provider: each call pops the next item (the last one repeats). An item is a FakeResponse or
    an exception instance to raise."""

    def __init__(self, **script):
        self.script = {k: list(v) for k, v in script.items()}
        self.calls = []

    def __call__(self, url, headers=None, json=None, timeout=None):
        name = provider_of(url)
        self.calls.append({"provider": name, "url": url, "headers": dict(headers or {}), "body": json,
                           "timeout": timeout})
        items = self.script.get(name)
        if not items:
            raise AssertionError(f"unexpected call to {name}")
        item = items.pop(0) if len(items) > 1 else items[0]
        if isinstance(item, BaseException):
            raise item
        return item

    def names(self):
        return [c["provider"] for c in self.calls]


def groq_ok(text):
    return FakeResponse(200, {"choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                                           "finish_reason": "stop"}]})


def gemini_ok(text):
    return FakeResponse(200, {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]},
                                              "finishReason": "STOP"}]})


def ollama_ok(text):
    return FakeResponse(200, {"model": "llama3.2", "message": {"role": "assistant", "content": text}, "done": True})


def groq_429(window="tokens per day (TPD)", retry_after="600"):
    return FakeResponse(429, {"error": {
        "message": f"Rate limit reached for model `openai/gpt-oss-120b` in organization `org_x` service tier "
                   f"`on_demand` on {window}: Limit 100000, Used 99990, Requested 900. Please try again in 9m.",
        "type": "tokens", "code": "rate_limit_exceeded"}}, headers={"retry-after": retry_after})


def gemini_429(quota_id="GenerateRequestsPerDayPerProjectPerModel-FreeTier", delay="39s"):
    return FakeResponse(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                                        "message": "You exceeded your current quota, please check your plan.",
                                        "details": [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                                                     "violations": [{"quotaId": quota_id}]},
                                                    {"@type": "type.googleapis.com/google.rpc.RetryInfo",
                                                     "retryDelay": delay}]}})


def unavailable(status=503):
    return FakeResponse(status, {"error": {"code": status, "status": "UNAVAILABLE",
                                           "message": "The model is overloaded. Please try again later."}})


def settings(**kw):
    base = dict(groq_api_key=GROQ_KEY, gemini_api_key=GEMINI_KEY, max_retries=1, retry_backoff_seconds=0.5,
                max_retry_wait_seconds=5, validation_fallbacks=1)
    base.update(kw)
    return providers.ProviderSettings(**base)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 0.25
        return self.t


def orchestrator(http, **kw):
    sleeps = []
    o = providers.ProviderOrchestrator.from_settings(settings(**kw), http=http, sleep=sleeps.append, clock=Clock())
    o.sleeps = sleeps
    return o


# A valid grounded response for ts.GroundedAnswerIntegrationTests.ELIGIBLE (claim quoted verbatim, cites E1).
CLAIM = ts.GroundedAnswerIntegrationTests.CLAIM
VALID = json.dumps({"answer": CLAIM, "evidence_sufficiency": "sufficient",
                    "claims": [{"text": CLAIM, "kind": "direct", "evidence_ids": ["E1"]}],
                    "citations": ["E1"], "refusal_reason": None, "clarification_question": None})
REFUSAL = json.dumps({"answer": "", "evidence_sufficiency": "insufficient", "claims": [], "citations": [],
                      "refusal_reason": "The passages do not state this.", "clarification_question": None})
FABRICATED_RATE = "Life tax for a new two-wheeler costing below Rs. 50,000 is 9% of the cost of the vehicle."
FABRICATED = json.dumps({"answer": FABRICATED_RATE, "evidence_sufficiency": "sufficient",
                         "claims": [{"text": FABRICATED_RATE, "kind": "direct", "evidence_ids": ["E1"]}],
                         "citations": ["E1"], "refusal_reason": None, "clarification_question": None})


# ---------------------------------------------------------------------------------------------------
# Unit tests: orchestrator and providers
# ---------------------------------------------------------------------------------------------------
class ProviderUnitTests(unittest.TestCase):
    def run_session(self, http, **kw):
        o = orchestrator(http, **kw)
        s = o.session()
        try:
            text = s.generate("PROMPT", None)
        except (providers.ProvidersUnavailable, providers.ProviderBlocked) as exc:
            text = exc
        return o, s, text

    # --- the required scenarios ---
    def test_1_groq_succeeds_gemini_and_ollama_not_called(self):
        http = FakeHTTP(groq=[groq_ok(VALID)])
        o, s, text = self.run_session(http)
        self.assertEqual(text, VALID)
        self.assertEqual(http.names(), ["groq"])
        self.assertEqual((s.summary()["provider"], s.summary()["attempts"], s.summary()["fallback_reasons"]),
                         ("groq", 1, []))

    def test_2_groq_quota_exhausted_gemini_succeeds_without_retrying_groq(self):
        http = FakeHTTP(groq=[groq_429()], gemini=[gemini_ok(VALID)])
        o, s, text = self.run_session(http)
        self.assertEqual(text, VALID)
        self.assertEqual(http.names(), ["groq", "gemini"])  # a daily quota is not retried
        self.assertEqual(s.fallback_reasons, ["groq: quota_exhausted"])
        self.assertEqual(o.sleeps, [])

    def test_3_groq_unavailable_retried_once_then_gemini_succeeds(self):
        http = FakeHTTP(groq=[unavailable(503)], gemini=[gemini_ok(VALID)])
        o, s, text = self.run_session(http)
        self.assertEqual(text, VALID)
        self.assertEqual(http.names(), ["groq", "groq", "gemini"])  # bounded: max_retries=1
        self.assertEqual(o.sleeps, [0.5])
        self.assertEqual(s.fallback_reasons, ["groq: unavailable"])
        self.assertEqual(s.summary()["provider"], "gemini")

    def test_4_groq_and_gemini_exhausted_ollama_succeeds(self):
        http = FakeHTTP(groq=[groq_429()], gemini=[gemini_429()], ollama=[ollama_ok(VALID)])
        o, s, text = self.run_session(http)
        self.assertEqual(text, VALID)
        self.assertEqual(http.names(), ["groq", "gemini", "ollama"])
        self.assertEqual(s.fallback_reasons, ["groq: quota_exhausted", "gemini: quota_exhausted"])
        self.assertEqual((s.summary()["provider"], s.summary()["model"], s.summary()["attempts"]),
                         ("ollama", "llama3.2", 3))

    def test_5_all_unavailable_is_a_safe_failure(self):
        http = FakeHTTP(groq=[unavailable()], gemini=[unavailable()], ollama=[requests.ConnectionError()])
        o, s, err = self.run_session(http)
        self.assertIsInstance(err, providers.ProvidersUnavailable)
        self.assertTrue(s.exhausted)
        self.assertEqual(len(http.calls), 6)  # each provider: one call + one bounded retry, then stop
        self.assertEqual(s.fallback_reasons, ["groq: unavailable", "gemini: unavailable", "ollama: connection_error"])
        self.assertIsNone(s.summary()["provider"])

    def test_6_timeout_moves_on_without_retrying(self):
        http = FakeHTTP(groq=[requests.Timeout()], gemini=[requests.ReadTimeout()], ollama=[ollama_ok(VALID)])
        o, s, text = self.run_session(http)
        self.assertEqual(text, VALID)
        self.assertEqual(http.names(), ["groq", "gemini", "ollama"])
        self.assertEqual(s.fallback_reasons, ["groq: timeout", "gemini: timeout"])
        self.assertEqual(o.sleeps, [])

    def test_timeouts_are_passed_to_every_call(self):
        http = FakeHTTP(groq=[requests.Timeout()], gemini=[requests.Timeout()], ollama=[ollama_ok(VALID)])
        self.run_session(http, timeout_seconds=12, ollama_timeout_seconds=90)
        self.assertEqual([c["timeout"] for c in http.calls], [12, 12, 90])

    def test_gemini_deadline_exceeded_is_a_timeout(self):
        http = FakeHTTP(groq=[groq_429()], gemini=[FakeResponse(504, {"error": {"status": "DEADLINE_EXCEEDED"}})],
                        ollama=[ollama_ok(VALID)])
        _, s, _ = self.run_session(http)
        self.assertEqual(s.fallback_reasons[1], "gemini: timeout")

    def test_connection_error_retried_once(self):
        http = FakeHTTP(groq=[requests.ConnectionError(), groq_ok(VALID)])
        o, s, text = self.run_session(http)
        self.assertEqual((text, http.names()), (VALID, ["groq", "groq"]))
        self.assertEqual(s.summary()["attempts"], 2)

    # --- rate limits and quota classification ---
    def test_short_rate_limit_waits_retry_after_then_retries(self):
        http = FakeHTTP(groq=[groq_429("tokens per minute (TPM)", retry_after="2"), groq_ok(VALID)])
        o, s, text = self.run_session(http)
        self.assertEqual((text, http.names(), o.sleeps), (VALID, ["groq", "groq"], [2.0]))

    def test_long_retry_after_skips_to_next_provider_instead_of_waiting(self):
        http = FakeHTTP(groq=[groq_429("requests per minute (RPM)", retry_after="45")], gemini=[gemini_ok(VALID)])
        o, s, _ = self.run_session(http)
        self.assertEqual((http.names(), o.sleeps), (["groq", "gemini"], []))
        self.assertEqual(s.fallback_reasons, ["groq: rate_limited"])

    def test_gemini_per_minute_quota_is_a_rate_limit_using_retry_info(self):
        http = FakeHTTP(groq=[groq_429()], gemini=[gemini_429("GenerateRequestsPerMinutePerProjectPerModel-FreeTier",
                                                              "3s"), gemini_ok(VALID)])
        o, s, text = self.run_session(http)
        self.assertEqual((text, o.sleeps), (VALID, [3.0]))

    def test_gemini_daily_quota_is_not_retried(self):
        http = FakeHTTP(groq=[groq_429()], gemini=[gemini_429()], ollama=[ollama_ok(VALID)])
        o, _, _ = self.run_session(http)
        self.assertEqual(http.names().count("gemini"), 1)

    def test_retries_are_bounded_by_setting(self):
        http = FakeHTTP(groq=[unavailable()], gemini=[unavailable()], ollama=[unavailable()])
        o, s, err = self.run_session(http, max_retries=0)
        self.assertEqual(http.names(), ["groq", "gemini", "ollama"])
        self.assertIsInstance(err, providers.ProvidersUnavailable)

    def test_auth_and_bad_request_move_on_without_retry(self):
        http = FakeHTTP(groq=[FakeResponse(401, {"error": {"message": "Invalid API Key"}})],
                        gemini=[FakeResponse(400, {"error": {"status": "INVALID_ARGUMENT"}})],
                        ollama=[FakeResponse(404, {"error": "model 'llama3.2' not found"})])
        _, s, err = self.run_session(http)
        self.assertEqual(http.names(), ["groq", "gemini", "ollama"])
        self.assertEqual(s.fallback_reasons, ["groq: auth_error", "gemini: bad_request", "ollama: bad_request"])

    def test_empty_or_malformed_200_moves_on(self):
        http = FakeHTTP(groq=[FakeResponse(200, None, text="<html>")],
                        gemini=[FakeResponse(200, {"candidates": []})], ollama=[ollama_ok(VALID)])
        _, s, text = self.run_session(http)
        self.assertEqual(text, VALID)
        self.assertEqual(s.fallback_reasons, ["groq: bad_response", "gemini: bad_response"])

    # --- refusals and blocks are not transport failures ---
    def test_model_refusal_is_returned_not_retried_elsewhere(self):
        http = FakeHTTP(groq=[groq_ok(REFUSAL)])
        _, s, text = self.run_session(http)
        self.assertEqual((text, http.names()), (REFUSAL, ["groq"]))

    def test_gemini_safety_block_is_not_sent_to_another_model(self):
        http = FakeHTTP(groq=[groq_429()], gemini=[FakeResponse(200, {"candidates": [{"finishReason": "SAFETY"}]})])
        _, s, err = self.run_session(http)
        self.assertIsInstance(err, providers.ProviderBlocked)
        self.assertEqual(http.names(), ["groq", "gemini"])
        self.assertTrue(s.blocked)
        self.assertFalse(s.advance("validation_rejected"))

    # --- pinning and advance ---
    def test_session_pins_to_the_provider_that_answered(self):
        http = FakeHTTP(groq=[groq_429()], gemini=[gemini_ok(VALID), gemini_ok(REFUSAL)])
        o = orchestrator(http)
        s = o.session()
        s.generate("PROMPT", None)
        self.assertEqual(s.generate("PROMPT + retry note", None), REFUSAL)  # conflict retry: same model
        self.assertEqual(http.names(), ["groq", "gemini", "gemini"])

    def test_pinned_provider_failure_fails_closed_without_switching_model(self):
        http = FakeHTTP(groq=[groq_ok(VALID), unavailable(), unavailable()])
        o = orchestrator(http)
        s = o.session()
        s.generate("PROMPT", None)
        with self.assertRaises(providers.ProviderError):
            s.generate("PROMPT + retry note", None)
        self.assertNotIn("gemini", http.names())

    def test_advance_moves_to_next_usable_provider_only(self):
        http = FakeHTTP(groq=[groq_ok(FABRICATED)], gemini=[gemini_ok(VALID)])
        o = orchestrator(http, ollama_enabled=False)
        s = o.session()
        s.generate("PROMPT", None)
        self.assertTrue(s.advance("validation_rejected"))
        self.assertEqual(s.generate("PROMPT", None), VALID)
        self.assertFalse(s.advance("validation_rejected"))  # Ollama is disabled: nothing left
        # Found live with Ollama: a failed advance must keep the record of who produced the rejected answer.
        self.assertEqual((s.summary()["provider"], s.summary()["fallback_reasons"]),
                         ("gemini", ["groq: validation_rejected"]))

    # --- configuration ---
    def test_disabled_and_unconfigured_providers_are_never_called(self):
        http = FakeHTTP(ollama=[ollama_ok(VALID)])
        o = orchestrator(http, groq_api_key="", gemini_enabled=False)
        s = o.session()
        self.assertEqual(s.generate("PROMPT", None), VALID)
        self.assertEqual(http.names(), ["ollama"])
        self.assertEqual(s.fallback_reasons, ["groq: not_configured"])

    def test_settings_from_env(self):
        s = providers.ProviderSettings.from_env({
            "GROQ_API_KEY": "your-groq-api-key", "GEMINI_API_KEY": GEMINI_KEY, "GEMINI_MODEL": "gemini-2.5-flash-lite",
            "OLLAMA_ENABLED": "false", "OLLAMA_BASE_URL": "http://localhost:11434/", "PROVIDER_MAX_RETRIES": "50",
            "PROVIDER_TIMEOUT_SECONDS": "abc", "PROVIDER_VALIDATION_FALLBACKS": "0"})
        self.assertEqual(s.groq_api_key, "")  # a placeholder is not a key
        self.assertEqual((s.gemini_api_key, s.gemini_model), (GEMINI_KEY, "gemini-2.5-flash-lite"))
        self.assertFalse(s.ollama_enabled)
        self.assertEqual(s.ollama_base_url, "http://localhost:11434")
        self.assertEqual((s.max_retries, s.timeout_seconds, s.validation_fallbacks), (3, 30.0, 0))
        self.assertNotIn(GEMINI_KEY, repr(s))
        defaults = providers.ProviderSettings.from_env({})
        self.assertEqual((defaults.groq_model, defaults.gemini_model, defaults.ollama_model),
                         ("openai/gpt-oss-120b", "gemini-2.5-flash", "llama3.2"))
        self.assertFalse(providers.from_env({}).status()["providers"][0]["configured"])

    def test_requests_carry_prompt_and_structured_output(self):
        http = FakeHTTP(groq=[unavailable()], gemini=[unavailable()], ollama=[ollama_ok(VALID)])
        self.run_session(http, max_retries=0)
        groq, gemini, ollama = http.calls
        self.assertEqual(groq["body"]["messages"], [{"role": "user", "content": "PROMPT"}])
        self.assertEqual(groq["body"]["response_format"],
                         {"type": "json_schema", "json_schema": {"name": "grounded_answer", "strict": True,
                                                                 "schema": providers.ANSWER_SCHEMA}})
        self.assertEqual(gemini["body"]["contents"][0]["parts"][0]["text"], "PROMPT")
        self.assertEqual(gemini["body"]["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(gemini["body"]["generationConfig"]["responseJsonSchema"], providers.ANSWER_SCHEMA)
        self.assertEqual((ollama["url"], ollama["body"]["format"], ollama["body"]["stream"]),
                         ("http://127.0.0.1:11434/api/chat", providers.ANSWER_SHAPES, False))

    def test_structured_output_can_be_switched_off(self):
        http = FakeHTTP(groq=[unavailable()], gemini=[unavailable()], ollama=[ollama_ok(VALID)])
        self.run_session(http, max_retries=0, groq_structured=False, gemini_structured=False, ollama_format="json")
        groq, gemini, ollama = http.calls
        self.assertEqual(groq["body"]["response_format"], {"type": "json_object"})
        self.assertNotIn("responseJsonSchema", gemini["body"]["generationConfig"])
        self.assertEqual(ollama["body"]["format"], "json")
        s = providers.ProviderSettings.from_env({"GROQ_STRUCTURED_OUTPUT": "false", "OLLAMA_FORMAT": "bogus"})
        self.assertEqual((s.groq_structured, s.gemini_structured, s.ollama_format), (False, True, "shapes"))

    def test_answer_schema_matches_the_validator_model(self):
        """The provider schema only constrains form: same fields as GroundedAnswer, all required, nothing extra."""
        fields = set(grounded_answer.GroundedAnswer.model_fields)
        self.assertEqual(set(providers.ANSWER_SCHEMA["properties"]), fields)
        self.assertEqual(set(providers.ANSWER_SCHEMA["required"]), fields)
        self.assertEqual(list(providers.ANSWER_SCHEMA["properties"])[-1], "answer")  # claims are written first
        self.assertEqual(set(providers.ANSWER_SCHEMA["properties"]["claims"]["items"]["properties"]),
                         set(grounded_answer.Claim.model_fields))
        for shape in providers.ANSWER_SHAPES["anyOf"]:
            self.assertEqual(set(shape["properties"]), fields)

    # --- token usage (Stage 3B) ---
    def test_token_usage_is_recorded_per_provider_format(self):
        groq = groq_ok(VALID)
        groq._body["usage"] = {"prompt_tokens": 2300, "completion_tokens": 180, "total_tokens": 2480,
                               "completion_tokens_details": {"reasoning_tokens": 60}}
        down = FakeResponse(503, {"error": {"status": "UNAVAILABLE"}})
        http = FakeHTTP(groq=[groq])
        _, s, _ = self.run_session(http)
        self.assertEqual(s.attempts[0].usage, {"input": 2300, "output": 180, "total": 2480, "reasoning": 60})
        self.assertEqual(s.summary()["tokens"], {"input": 2300, "output": 180, "total": 2480})

        g = gemini_ok(VALID)
        g._body["usageMetadata"] = {"promptTokenCount": 2400, "candidatesTokenCount": 150, "totalTokenCount": 2700,
                                    "thoughtsTokenCount": 150}
        o = ollama_ok(VALID)
        o._body.update(prompt_eval_count=2366, eval_count=110)
        http = FakeHTTP(groq=[down], gemini=[g], ollama=[o])
        _, s, _ = self.run_session(http, max_retries=0)
        self.assertEqual(s.attempts[-1].usage, {"input": 2400, "output": 150, "total": 2700, "reasoning": 150})
        _, s, _ = self.run_session(FakeHTTP(groq=[down], gemini=[down], ollama=[o]), max_retries=0)
        self.assertEqual(s.attempts[-1].usage, {"input": 2366, "output": 110, "total": 2476})

    def test_missing_usage_is_none_not_an_error(self):
        _, s, text = self.run_session(FakeHTTP(groq=[groq_ok(VALID)]))
        self.assertEqual((text, s.attempts[0].usage, s.summary()["tokens"]), (VALID, None, None))

    def test_gemini_invalid_key_400_is_an_auth_error(self):
        bad_key = FakeResponse(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT",
                                               "message": "API key not valid. Please pass a valid API key.",
                                               "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo",
                                                            "reason": "API_KEY_INVALID",
                                                            "domain": "googleapis.com"}]}})
        http = FakeHTTP(groq=[groq_429()], gemini=[bad_key], ollama=[ollama_ok(VALID)])
        _, s, _ = self.run_session(http)
        self.assertEqual(s.fallback_reasons, ["groq: quota_exhausted", "gemini: auth_error"])

    # --- secrets ---
    def test_keys_only_in_auth_headers_never_in_urls_status_summary_or_errors(self):
        http = FakeHTTP(groq=[FakeResponse(401, {"error": {"message": "Invalid API Key"}})],
                        gemini=[unavailable()], ollama=[unavailable()])
        o, s, err = self.run_session(http, max_retries=0)
        groq, gemini, _ = http.calls
        self.assertEqual(groq["headers"]["Authorization"], f"Bearer {GROQ_KEY}")
        self.assertEqual(gemini["headers"]["x-goog-api-key"], GEMINI_KEY)
        exposed = json.dumps([[c["url"] for c in http.calls], o.status(), s.summary(), str(err),
                              [repr(p) for p in o.providers]], default=str)
        for secret in SECRETS:
            self.assertNotIn(secret, exposed)
        self.assertEqual([p["configured"] for p in o.status()["providers"]], [True, True, True])


# ---------------------------------------------------------------------------------------------------
# Server tests: /chat in grounded mode, real validator, providers mocked
# ---------------------------------------------------------------------------------------------------
WITHHELD_SCHEDULE = Document(
    page_content="Synthetic tax G.O. - THIRD SCHEDULE\nTHE THIRD SCHEDULE\nMotor Cycles: At the time of registration "
                 "new vehicles 9% | 12% | 15% | 18% of the cost of the vehicle.",
    metadata={"state": "Telangana", "manifest_id": "go-ms-53-2025-trb", "provision_id": "THIRD SCHEDULE", "part": 1,
              "parts": 1, "title": "Synthetic tax G.O.", "location": "go.pdf#page=1", "answer_eligible": False,
              "source_file": ts.TG_RULES_FILE, "sha256": ts.TG_RULES_SHA})


class ProviderServerTests(ts.Base):
    # Helpers borrowed from the grounded integration tests (not subclassed, so their tests do not run twice).
    ELIGIBLE = ts.GroundedAnswerIntegrationTests.ELIGIBLE
    QUESTION = ts.GroundedAnswerIntegrationTests.QUESTION
    patch = ts.GroundedAnswerIntegrationTests.patch
    record = ts.GroundedAnswerIntegrationTests.record
    ask = ts.GroundedAnswerIntegrationTests.ask

    def setUp(self):
        super().setUp()
        self.ga, self.la = grounded_answer, legal_approval
        FAKE_SEARCH["fn"] = lambda q, s, docs: [(self.ELIGIBLE, 0.3)]
        self.model_calls = []

        def trap(prompt):
            self.model_calls.append(prompt)
            raise AssertionError("unexpected legacy model call")
        FAKE_LLM["fn"] = trap

    def approve(self, http, **kw):
        self.orch = orchestrator(http, **kw)
        self.mock = self.orch
        ts.GroundedAnswerIntegrationTests.approve(self, generator=self.orch)
        return self.orch

    def last(self):
        return self.orch.status()["last_request"]

    def test_groq_answer_is_validated_and_returned(self):
        http = FakeHTTP(groq=[groq_ok(VALID)])
        self.approve(http)
        r = self.ask()
        self.assertEqual(r["kind"], "answer")
        self.assertIn(CLAIM, r["response"])
        self.assertEqual(http.names(), ["groq"])
        self.assertEqual(self.model_calls, [])
        self.assertEqual({k: self.last()[k] for k in ("provider", "model", "attempts", "validation", "final")},
                         {"provider": "groq", "model": "openai/gpt-oss-120b", "attempts": 1, "validation": "answer",
                          "final": "answer"})

    def test_quota_fallback_answer_still_validated(self):
        http = FakeHTTP(groq=[groq_429()], gemini=[gemini_ok(VALID)])
        self.approve(http)
        r = self.ask()
        self.assertEqual(r["kind"], "answer")
        self.assertEqual((self.last()["provider"], self.last()["fallback_reasons"]),
                         ("gemini", ["groq: quota_exhausted"]))

    def test_all_providers_down_gives_safe_unavailable_reply(self):
        http = FakeHTTP(groq=[unavailable()], gemini=[gemini_429()], ollama=[requests.ConnectionError()])
        self.approve(http)
        r = self.ask()
        self.assertEqual((r["kind"], r["response"], r.get("sources", [])),
                         ("unavailable", srv.PROVIDERS_UNAVAILABLE_MESSAGE, []))
        self.assertEqual(self.last()["final"], "unavailable")
        self.assertTrue(self.last()["exhausted"])

    def test_refusal_is_not_found_and_no_other_provider_is_asked(self):
        http = FakeHTTP(groq=[groq_ok(REFUSAL)], gemini=[gemini_ok(VALID)])
        self.approve(http)
        r = self.ask()
        self.assertEqual(r["kind"], "no_support")
        self.assertEqual(http.names(), ["groq"])

    def test_validation_failure_gets_one_bounded_next_provider_candidate(self):
        http = FakeHTTP(groq=[groq_ok(FABRICATED)], gemini=[gemini_ok(VALID)])
        self.approve(http)
        r = self.ask()
        self.assertEqual(r["kind"], "answer")
        self.assertNotIn("9%", r["response"])
        self.assertEqual(http.names(), ["groq", "gemini"])
        self.assertEqual((self.last()["candidates"], self.last()["fallback_reasons"]),
                         (2, ["groq: validation_rejected"]))

    def test_every_candidate_failing_validation_is_never_returned(self):
        http = FakeHTTP(groq=[groq_ok(FABRICATED)], gemini=[gemini_ok(FABRICATED)], ollama=[ollama_ok(VALID)])
        self.approve(http)  # validation_fallbacks=1: Ollama is not asked
        r = self.ask()
        self.assertEqual((r["kind"], r.get("sources", [])), ("no_support", []))
        self.assertNotIn("9%", r["response"])
        self.assertEqual(http.names(), ["groq", "gemini"])
        self.assertEqual(self.last()["validation"], "rejected")

    def test_validation_fallback_can_be_switched_off(self):
        http = FakeHTTP(groq=[groq_ok(FABRICATED)], gemini=[gemini_ok(VALID)])
        self.approve(http, validation_fallbacks=0)
        self.assertEqual(self.ask()["kind"], "no_support")
        self.assertEqual(http.names(), ["groq"])

    def test_safety_block_ends_request_without_other_models(self):
        http = FakeHTTP(groq=[groq_429()], gemini=[FakeResponse(200, {"promptFeedback": {"blockReason": "OTHER"}})],
                        ollama=[ollama_ok(VALID)])
        self.approve(http)
        r = self.ask()
        self.assertEqual(r["kind"], "no_support")
        self.assertEqual(http.names(), ["groq", "gemini"])

    def test_withheld_schedule_never_reaches_any_provider(self):
        FAKE_SEARCH["fn"] = lambda q, s, docs: [(WITHHELD_SCHEDULE, 0.2), (self.ELIGIBLE, 0.3)]
        http = FakeHTTP(groq=[groq_ok(FABRICATED)], gemini=[gemini_ok(FABRICATED)])
        self.approve(http)
        r = self.ask("How is life tax calculated for a new two-wheeler in Telangana?")
        self.assertEqual(r["kind"], "no_support")  # invented rates fail validation on every provider
        for rate in ("9%", "12%", "15%", "18%"):
            self.assertNotIn(rate, r["response"])
        prompts = [c["body"]["messages"][0]["content"] if c["provider"] == "groq"
                   else c["body"]["contents"][0]["parts"][0]["text"] for c in http.calls]
        self.assertEqual(len(prompts), 2)
        for prompt in prompts:
            self.assertNotIn("THE THIRD SCHEDULE", prompt)
            self.assertNotIn("18%", prompt)
            self.assertIn("Form 2", prompt)

    def test_penalty_question_reaches_no_provider(self):
        http = FakeHTTP(groq=[groq_ok(VALID)])
        self.approve(http)
        r = self.ask("What is the penalty for driving without a helmet?")
        self.assertEqual((r["kind"], http.calls), ("restricted", []))

    def test_status_reports_providers_without_secrets(self):
        http = FakeHTTP(groq=[groq_429()], gemini=[gemini_ok(VALID)])
        self.approve(http)
        self.ask()
        status = self.client.get("/status").json()["providers"]
        self.assertEqual(status["order"], ["groq", "gemini", "ollama"])
        self.assertTrue(status["available"])
        by_name = {p["name"]: p for p in status["providers"]}
        self.assertEqual((by_name["groq"]["failures"], by_name["groq"]["last_failure"]), (1, "quota_exhausted"))
        self.assertEqual(by_name["gemini"]["successes"], 1)
        self.assertEqual(status["last_request"]["provider"], "gemini")
        text = json.dumps(status)
        for secret in SECRETS:
            self.assertNotIn(secret, text)

    def test_status_without_grounded_mode_has_no_providers(self):
        status = self.client.get("/status").json()["providers"]
        self.assertEqual((status["order"], status["available"]), ([], False))

    def test_generation_is_logged_with_observability_fields_and_no_secrets(self):
        http = FakeHTTP(groq=[unavailable()], gemini=[gemini_ok(VALID)])
        self.approve(http)
        with self.assertLogs("kyr.providers", logging.INFO) as logs:
            self.ask()
        line = next(m for m in logs.output if "grounded generation" in m)
        summary = json.loads(line.split("grounded generation ", 1)[1])
        for key in ("provider", "model", "fallback_reasons", "attempts", "generation_ms", "validation", "final"):
            self.assertIn(key, summary)
        self.assertEqual((summary["provider"], summary["attempts"], summary["final"]), ("gemini", 3, "answer"))
        self.assertGreater(summary["generation_ms"], 0)
        for secret in SECRETS:
            self.assertNotIn(secret, "\n".join(logs.output))

    def test_stage_timings_are_logged(self):
        # Stage 4: groq fails once (retryable, 0.5 s back-off on the fake clock), then answers
        http = FakeHTTP(groq=[unavailable(), groq_ok(VALID)])
        self.approve(http)
        with self.assertLogs("kyr.providers", logging.INFO) as logs:
            self.ask()
        line = next(m for m in logs.output if "grounded generation" in m)
        summary = json.loads(line.split("grounded generation ", 1)[1])
        t = summary["timings_ms"]
        self.assertEqual(set(t), {"retrieval", "answer", "generation", "retry_wait", "local", "response", "total"})
        self.assertEqual((summary["wait_ms"], t["retry_wait"]), (500, 500))
        self.assertEqual(t["generation"], summary["generation_ms"])
        self.assertTrue(all(isinstance(v, (int, float)) and v >= 0 for v in t.values()), t)
        self.assertGreaterEqual(t["total"], t["retrieval"])
        self.assertEqual(self.orch.status()["last_request"]["timings_ms"], t)
        stages = summary["local_stages_ms"]
        self.assertEqual(set(stages), {"contract", "prompt", "validate", "render"})
        self.assertTrue(all(isinstance(v, (int, float)) and v >= 0 for v in stages.values()), stages)


if __name__ == "__main__":
    unittest.main()
