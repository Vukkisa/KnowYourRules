"""Model providers for grounded answers: Groq (primary) -> Cerebras -> Gemini -> Ollama (local fallback).

Scope: transport only. A provider turns the prompt built by grounded_answer.build_prompt() into raw model text.
It never sees retrieval, never edits evidence and never judges legal validity: every response, from whichever
provider, goes back through grounded_answer.answer(), which runs the unchanged validator (grounding, meaning
checks, identifiers, citations, penalty drift) and the refusal handling.

Fallback rules (ProviderSession):
  * Only transport failures move to the next provider: quota exhaustion, rate limits (HTTP 429), temporary
    unavailability (5xx, overloaded), connection errors, timeouts, and a misconfigured provider (bad key, unknown
    model, rejected request).
  * A model response is never a transport failure. A refusal or "insufficient evidence" is returned as is and
    becomes the user's answer; no other model is asked.
  * A provider-side content block (e.g. Gemini SAFETY) ends the request (ProviderBlocked): it is not routed to a
    different model.
  * Retries are bounded (max_retries per provider, only for short-lived failures, capped waits). Nothing loops.
  * When every provider fails, ProvidersUnavailable is raised; the server turns it into a safe "unavailable"
    reply, never an ungrounded answer.

Secrets: API keys are read from the environment, sent only in request headers, and never logged, returned by
status(), or included in exception text.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import requests

log = logging.getLogger("kyr.providers")


# ---------------------------------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------------------------------
# Reasons a provider call failed. RETRYABLE ones may be retried on the same provider (bounded); all of them
# move on to the next provider once retries are used up.
QUOTA_EXHAUSTED = "quota_exhausted"      # free-tier daily/monthly quota: retrying today will not help
RATE_LIMITED = "rate_limited"            # short-window 429: may clear within seconds
UNAVAILABLE = "unavailable"              # 5xx / overloaded / capacity
TIMEOUT = "timeout"
CONNECTION = "connection_error"
AUTH = "auth_error"                      # 401/403: missing or rejected key
BAD_REQUEST = "bad_request"              # 400/404/413/422: model id, request shape, context length
BAD_RESPONSE = "bad_response"            # 200 without usable text
NOT_CONFIGURED = "not_configured"        # enabled but no key / model
RETRYABLE = frozenset({RATE_LIMITED, UNAVAILABLE, CONNECTION})


class ProviderError(Exception):
    """A transport failure of one provider. The message is a fixed, secret-free description."""

    def __init__(self, reason: str, detail: str = "", status: int | None = None, retry_after: float | None = None):
        super().__init__(f"{reason}{f' (HTTP {status})' if status else ''}{f': {detail}' if detail else ''}")
        self.reason, self.detail, self.status, self.retry_after = reason, detail, status, retry_after


class ProviderBlocked(RuntimeError):
    """The provider refused to produce content (safety block). Not a transport failure: no fallback."""


class ProvidersUnavailable(RuntimeError):
    """No provider produced a response."""


# ---------------------------------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------------------------------
def _flag(env, name, default):
    value = env.get(name, "").strip().lower()
    return default if not value else value in ("1", "true", "yes", "on")


def _num(env, name, default, lo, hi, cast=float):
    try:
        value = cast(env.get(name, "").strip() or default)
    except ValueError:
        log.warning("%s is not a number; using %s", name, default)
        value = cast(default)
    return min(max(value, lo), hi)


def _secret(env, name):
    value = env.get(name, "").strip()
    return "" if not value or "placeholder" in value.lower() or value.startswith("your-") else value


@dataclass(frozen=True)
class ProviderSettings:
    groq_enabled: bool = True
    groq_api_key: str = field(default="", repr=False)
    groq_model: str = "openai/gpt-oss-120b"
    cerebras_enabled: bool = True
    cerebras_api_key: str = field(default="", repr=False)
    cerebras_model: str = "gpt-oss-120b"
    gemini_enabled: bool = True
    gemini_api_key: str = field(default="", repr=False)
    gemini_model: str = "gemini-2.5-flash"
    ollama_enabled: bool = True
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2"
    timeout_seconds: float = 30.0
    ollama_timeout_seconds: float = 120.0
    max_retries: int = 1
    retry_backoff_seconds: float = 0.5
    max_retry_wait_seconds: float = 5.0
    max_output_tokens: int = 4096
    validation_fallbacks: int = 1
    # Structured output (Stage 3B): the provider enforces the response shape; the validator still checks all of it.
    groq_structured: bool = True        # response_format json_schema (strict)
    cerebras_structured: bool = True    # response_format json_schema (strict)
    gemini_structured: bool = True      # generationConfig.responseJsonSchema
    ollama_format: str = "shapes"       # shapes | schema | json

    @classmethod
    def from_env(cls, env=None) -> "ProviderSettings":
        env = os.environ if env is None else env
        d = cls()
        return cls(
            groq_enabled=_flag(env, "GROQ_ENABLED", d.groq_enabled),
            groq_api_key=_secret(env, "GROQ_API_KEY"),
            groq_model=env.get("GROQ_MODEL", "").strip() or d.groq_model,
            cerebras_enabled=_flag(env, "CEREBRAS_ENABLED", d.cerebras_enabled),
            cerebras_api_key=_secret(env, "CEREBRAS_API_KEY"),
            cerebras_model=env.get("CEREBRAS_MODEL", "").strip() or d.cerebras_model,
            gemini_enabled=_flag(env, "GEMINI_ENABLED", d.gemini_enabled),
            gemini_api_key=_secret(env, "GEMINI_API_KEY"),
            gemini_model=env.get("GEMINI_MODEL", "").strip() or d.gemini_model,
            ollama_enabled=_flag(env, "OLLAMA_ENABLED", d.ollama_enabled),
            ollama_base_url=(env.get("OLLAMA_BASE_URL", "").strip() or d.ollama_base_url).rstrip("/"),
            ollama_model=env.get("OLLAMA_MODEL", "").strip() or d.ollama_model,
            timeout_seconds=_num(env, "PROVIDER_TIMEOUT_SECONDS", d.timeout_seconds, 1, 300),
            ollama_timeout_seconds=_num(env, "OLLAMA_TIMEOUT_SECONDS", d.ollama_timeout_seconds, 1, 900),
            max_retries=_num(env, "PROVIDER_MAX_RETRIES", d.max_retries, 0, 3, int),
            retry_backoff_seconds=_num(env, "PROVIDER_RETRY_BACKOFF_SECONDS", d.retry_backoff_seconds, 0, 10),
            max_retry_wait_seconds=_num(env, "PROVIDER_MAX_RETRY_WAIT_SECONDS", d.max_retry_wait_seconds, 0, 30),
            max_output_tokens=_num(env, "PROVIDER_MAX_OUTPUT_TOKENS", d.max_output_tokens, 256, 32768, int),
            validation_fallbacks=_num(env, "PROVIDER_VALIDATION_FALLBACKS", d.validation_fallbacks, 0, 2, int),
            groq_structured=_flag(env, "GROQ_STRUCTURED_OUTPUT", d.groq_structured),
            cerebras_structured=_flag(env, "CEREBRAS_STRUCTURED_OUTPUT", d.cerebras_structured),
            gemini_structured=_flag(env, "GEMINI_STRUCTURED_OUTPUT", d.gemini_structured),
            ollama_format=(env.get("OLLAMA_FORMAT", "").strip().lower()
                           if env.get("OLLAMA_FORMAT", "").strip().lower() in ("shapes", "schema", "json")
                           else d.ollama_format),
        )


# ---------------------------------------------------------------------------------------------------
# Response shapes for structured output. They mirror grounded_answer.GroundedAnswer and only constrain FORM; the
# validator re-checks everything. Field order puts the decision first and "answer" last, so a model writes its
# claims before the answer string that must repeat them.
# ---------------------------------------------------------------------------------------------------
_FIELDS = ("evidence_sufficiency", "refusal_reason", "clarification_question", "claims", "citations", "answer")


def _answer_schema(eid: dict) -> dict:
    claim = {"type": "object", "additionalProperties": False, "required": ["text", "kind", "evidence_ids"],
             "properties": {"text": {"type": "string"}, "kind": {"type": "string", "enum": ["direct", "interpretation"]},
                            "evidence_ids": {"type": "array", "items": eid}}}
    return {"type": "object", "additionalProperties": False, "required": list(_FIELDS), "properties": {
        "evidence_sufficiency": {"type": "string",
                                 "enum": ["sufficient", "insufficient", "conflicting", "not_applicable"]},
        "refusal_reason": {"type": ["string", "null"]},
        "clarification_question": {"type": ["string", "null"]},
        "claims": {"type": "array", "items": claim},
        "citations": {"type": "array", "items": eid},
        "answer": {"type": "string"}}}


# Groq strict mode and Gemini accept this flat form (no regex keywords).
ANSWER_SCHEMA = _answer_schema({"type": "string"})


def _shape(base, sufficiency, items, answer, refusal, clarification):
    props = dict(base["properties"], evidence_sufficiency={"type": "string", "enum": sufficiency},
                 refusal_reason=refusal, clarification_question=clarification, answer=answer,
                 claims=dict(base["properties"]["claims"], **items),
                 citations=dict(base["properties"]["citations"], **items))
    return dict(base, properties=props)


_TEXT, _NULL, _EMPTY = {"type": "string", "minLength": 1}, {"type": "null"}, {"type": "string", "maxLength": 0}
_OLLAMA_BASE = _answer_schema({"type": "string", "pattern": "^E[1-9][0-9]{0,2}$"})
# Ollama (llama.cpp grammars): one of three legal shapes, so a refusal cannot carry claims or an answer.
ANSWER_SHAPES = {"anyOf": [
    _shape(_OLLAMA_BASE, ["sufficient", "conflicting"], {"minItems": 1}, _TEXT, _NULL, _NULL),
    _shape(_OLLAMA_BASE, ["insufficient"], {"maxItems": 0}, _EMPTY, _TEXT, _NULL),
    _shape(_OLLAMA_BASE, ["not_applicable"], {"maxItems": 0}, _EMPTY, _TEXT, _TEXT)]}
OLLAMA_FORMATS = {"shapes": ANSWER_SHAPES, "schema": _OLLAMA_BASE, "json": "json"}


# ---------------------------------------------------------------------------------------------------
# Providers: one common contract
# ---------------------------------------------------------------------------------------------------
def _json(resp) -> dict:
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _retry_after(resp) -> float | None:
    value = (getattr(resp, "headers", None) or {}).get("retry-after") or \
            (getattr(resp, "headers", None) or {}).get("Retry-After")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _status_reason(status: int) -> str:
    if status in (401, 403):
        return AUTH
    if status == 408:
        return TIMEOUT
    if status in (500, 502, 503, 504, 498, 529):
        return UNAVAILABLE
    return BAD_REQUEST


class Provider:
    """Common contract. Subclasses build the request and read the response; send() maps every transport failure
    to ProviderError, so the orchestrator never sees a provider-specific exception."""

    name = "provider"

    def __init__(self, model: str, timeout: float, max_output_tokens: int, enabled: bool = True,
                 http: Callable | None = None):
        self.model, self.timeout, self.max_output_tokens, self.enabled = model, timeout, max_output_tokens, enabled
        self.http = http or requests.post

    def configured(self) -> bool:
        return bool(self.model)

    def describe(self) -> dict:
        return {"name": self.name, "model": self.model, "enabled": self.enabled, "configured": self.configured()}

    # subclass hooks
    def request(self, prompt: str) -> tuple[str, dict, dict]:  # url, headers, json body
        raise NotImplementedError

    def classify(self, resp) -> ProviderError:
        status = resp.status_code
        return ProviderError(_status_reason(status), status=status, retry_after=_retry_after(resp))

    def extract(self, data: dict) -> str:
        raise NotImplementedError

    def usage(self, data: dict) -> dict | None:
        """Token counts as {"input", "output", "total"} where the provider reports them."""
        return None

    def send(self, prompt: str) -> str:
        return self.send_full(prompt)[0]

    def send_full(self, prompt: str) -> tuple[str, dict | None]:
        if not self.configured():
            raise ProviderError(NOT_CONFIGURED)
        url, headers, body = self.request(prompt)
        try:
            resp = self.http(url, headers=headers, json=body, timeout=self.timeout)
        except requests.Timeout:
            raise ProviderError(TIMEOUT) from None
        except requests.ConnectionError:
            raise ProviderError(CONNECTION) from None
        except requests.RequestException as exc:
            raise ProviderError(CONNECTION, type(exc).__name__) from None
        if resp.status_code != 200:
            raise self.classify(resp)
        data = _json(resp)
        if not data:
            raise ProviderError(BAD_RESPONSE, "body is not a JSON object", status=200)
        text = self.extract(data)
        if not isinstance(text, str) or not text.strip():
            raise ProviderError(BAD_RESPONSE, "no text in response", status=200)
        try:
            usage = self.usage(data)
        except (AttributeError, TypeError, ValueError):
            usage = None
        return text, usage


def _tokens(input_, output, total=None, **extra) -> dict | None:
    if input_ is None and output is None and total is None:
        return None
    if total is None and isinstance(input_, int) and isinstance(output, int):
        total = input_ + output
    return dict({"input": input_, "output": output, "total": total}, **{k: v for k, v in extra.items() if v is not None})


class GroqProvider(Provider):
    """OpenAI-compatible chat completions. 429 bodies name the exhausted window: per-day (RPD/TPD) is a quota,
    per-minute (RPM/TPM) is a rate limit."""

    name = "groq"
    URL = "https://api.groq.com/openai/v1/chat/completions"
    _DAILY = re.compile(r"per day|\((?:rpd|tpd|asd)\)|quota", re.I)

    def __init__(self, api_key: str, model: str, timeout: float, max_output_tokens: int, enabled=True, http=None,
                 structured: bool = True):
        super().__init__(model, timeout, max_output_tokens, enabled, http)
        self._key, self.structured = api_key, structured

    def configured(self):
        return bool(self._key and self.model)

    def request(self, prompt):
        fmt = ({"type": "json_schema", "json_schema": {"name": "grounded_answer", "strict": True,
                                                        "schema": ANSWER_SCHEMA}}
               if self.structured else {"type": "json_object"})
        return (self.URL, {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                {"model": self.model, "messages": [{"role": "user", "content": prompt}], "temperature": 0,
                 "max_tokens": self.max_output_tokens, "response_format": fmt})

    def classify(self, resp):
        status = resp.status_code
        if status == 429:
            err = _json(resp).get("error") or {}
            message = str(err.get("message", "")) if isinstance(err, dict) else ""
            reason = QUOTA_EXHAUSTED if self._DAILY.search(message) else RATE_LIMITED
            return ProviderError(reason, status=status, retry_after=_retry_after(resp))
        return super().classify(resp)

    def extract(self, data):
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return ""

    def usage(self, data):
        u = data.get("usage") or {}
        details = u.get("completion_tokens_details") or {}
        return _tokens(u.get("prompt_tokens"), u.get("completion_tokens"), u.get("total_tokens"),
                       reasoning=details.get("reasoning_tokens"))


class CerebrasProvider(GroqProvider):
    """Cerebras Inference: the same OpenAI-compatible chat completions API and the same model family as Groq, so the
    prompt, response shape and 429 handling are shared. Skipped when no key is configured."""

    name = "cerebras"
    URL = "https://api.cerebras.ai/v1/chat/completions"
    _DAILY = re.compile(r"per day|daily|\((?:rpd|tpd|asd)\)|quota", re.I)


class GeminiProvider(Provider):
    """Gemini generateContent. The key goes in the x-goog-api-key header, never in the URL. 429
    RESOURCE_EXHAUSTED carries QuotaFailure details: a per-day quota id means the free-tier quota is used up."""

    name = "gemini"
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    BLOCKED_FINISH = frozenset({"SAFETY", "RECITATION", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII",
                                "IMAGE_SAFETY"})

    def __init__(self, api_key: str, model: str, timeout: float, max_output_tokens: int, enabled=True, http=None,
                 structured: bool = True):
        super().__init__(model, timeout, max_output_tokens, enabled, http)
        self._key, self.structured = api_key, structured

    def configured(self):
        return bool(self._key and self.model)

    def request(self, prompt):
        config = {"temperature": 0, "maxOutputTokens": self.max_output_tokens, "responseMimeType": "application/json"}
        if self.structured:
            config["responseJsonSchema"] = ANSWER_SCHEMA
        return (self.URL.format(model=self.model), {"x-goog-api-key": self._key, "Content-Type": "application/json"},
                {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": config})

    def classify(self, resp):
        status = resp.status_code
        err = _json(resp).get("error") or {}
        err = err if isinstance(err, dict) else {}
        state = str(err.get("status", ""))
        details = err.get("details") if isinstance(err.get("details"), list) else []
        if status == 429 or state == "RESOURCE_EXHAUSTED":
            quota_ids = [str(v.get("quotaId", "")) for d in details if isinstance(d, dict)
                         for v in (d.get("violations") or []) if isinstance(v, dict)]
            delay = None
            for d in details:
                if isinstance(d, dict) and str(d.get("@type", "")).endswith("RetryInfo"):
                    m = re.fullmatch(r"(\d+(?:\.\d+)?)s", str(d.get("retryDelay", "")))
                    delay = float(m.group(1)) if m else None
            daily = any("PerDay" in q for q in quota_ids)
            return ProviderError(QUOTA_EXHAUSTED if daily else RATE_LIMITED, status=status,
                                 retry_after=delay if delay is not None else _retry_after(resp))
        if state == "DEADLINE_EXCEEDED":
            return ProviderError(TIMEOUT, status=status)
        if state in ("UNAVAILABLE", "INTERNAL"):
            return ProviderError(UNAVAILABLE, status=status)
        if state == "FAILED_PRECONDITION":  # e.g. free tier not available for this project or region
            return ProviderError(UNAVAILABLE, "failed precondition", status=status)
        if state in ("PERMISSION_DENIED", "UNAUTHENTICATED"):
            return ProviderError(AUTH, status=status)
        # Gemini answers an invalid key with 400 INVALID_ARGUMENT, reason API_KEY_INVALID - not a bad request.
        reasons = {str(d.get("reason", "")) for d in details if isinstance(d, dict)}
        if "API_KEY_INVALID" in reasons or "api key not valid" in str(err.get("message", "")).lower():
            return ProviderError(AUTH, status=status)
        return super().classify(resp)

    def extract(self, data):
        feedback = data.get("promptFeedback") or {}
        if isinstance(feedback, dict) and feedback.get("blockReason"):
            raise ProviderBlocked(f"gemini blocked the prompt: {feedback.get('blockReason')}")
        candidates = data.get("candidates") or []
        if not candidates or not isinstance(candidates[0], dict):
            return ""
        first = candidates[0]
        if first.get("finishReason") in self.BLOCKED_FINISH:
            raise ProviderBlocked(f"gemini blocked the response: {first.get('finishReason')}")
        parts = (first.get("content") or {}).get("parts") or []
        return "".join(p.get("text", "") for p in parts if isinstance(p, dict) and not p.get("thought"))

    def usage(self, data):
        u = data.get("usageMetadata") or {}
        return _tokens(u.get("promptTokenCount"), u.get("candidatesTokenCount"), u.get("totalTokenCount"),
                       reasoning=u.get("thoughtsTokenCount"))


class OllamaProvider(Provider):
    """Local Ollama /api/chat, non-streaming, JSON format."""

    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout: float, max_output_tokens: int, enabled=True, http=None,
                 response_format: str = "shapes"):
        super().__init__(model, timeout, max_output_tokens, enabled, http)
        self.base_url = base_url
        self.response_format = response_format if response_format in OLLAMA_FORMATS else "shapes"

    def configured(self):
        return bool(self.base_url and self.model)

    def describe(self):
        return dict(super().describe(), base_url=self.base_url, format=self.response_format)

    def request(self, prompt):
        return (f"{self.base_url}/api/chat", {"Content-Type": "application/json"},
                {"model": self.model, "messages": [{"role": "user", "content": prompt}], "stream": False,
                 "format": OLLAMA_FORMATS[self.response_format],
                 "options": {"temperature": 0, "num_predict": self.max_output_tokens}})

    def classify(self, resp):
        if resp.status_code == 404:  # model not pulled
            return ProviderError(BAD_REQUEST, "model not found", status=404)
        return super().classify(resp)

    def extract(self, data):
        if data.get("error"):
            return ""
        message = data.get("message") or {}
        return message.get("content", "") if isinstance(message, dict) else ""

    def usage(self, data):
        return _tokens(data.get("prompt_eval_count"), data.get("eval_count"))


# ---------------------------------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------------------------------
@dataclass
class Attempt:
    provider: str
    model: str
    outcome: str            # ok | failed | blocked | skipped
    reason: str | None
    http_status: int | None
    latency_ms: int
    usage: dict | None = None   # {"input", "output", "total", ["reasoning"]} tokens when the provider reports them

    def as_dict(self):
        return dict(self.__dict__)


class ProviderOrchestrator:
    """Holds the provider order, settings and aggregate counters. Thread safe. Per-request state lives in a
    ProviderSession (session()), so concurrent requests never share fallback state."""

    def __init__(self, providers: list[Provider], settings: ProviderSettings | None = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        self.providers, self.settings = list(providers), settings or ProviderSettings()
        self.sleep, self.clock = sleep, clock
        self._lock = threading.Lock()
        self._stats = {p.name: {"successes": 0, "failures": 0, "last_failure": None} for p in self.providers}
        self._last = None

    @classmethod
    def from_settings(cls, s: ProviderSettings, http=None, **kw) -> "ProviderOrchestrator":
        return cls([GroqProvider(s.groq_api_key, s.groq_model, s.timeout_seconds, s.max_output_tokens,
                                 s.groq_enabled, http, s.groq_structured),
                    CerebrasProvider(s.cerebras_api_key, s.cerebras_model, s.timeout_seconds, s.max_output_tokens,
                                     s.cerebras_enabled, http, s.cerebras_structured),
                    GeminiProvider(s.gemini_api_key, s.gemini_model, s.timeout_seconds, s.max_output_tokens,
                                   s.gemini_enabled, http, s.gemini_structured),
                    OllamaProvider(s.ollama_base_url, s.ollama_model, s.ollama_timeout_seconds, s.max_output_tokens,
                                   s.ollama_enabled, http, s.ollama_format)], s, **kw)

    def session(self) -> "ProviderSession":
        return ProviderSession(self)

    def generate(self, prompt, contract):
        """Plain AnswerGenerator use (no per-request record kept by the caller)."""
        return self.session().generate(prompt, contract)

    def _record(self, attempt: Attempt):
        with self._lock:
            stats = self._stats.setdefault(attempt.provider, {"successes": 0, "failures": 0, "last_failure": None})
            if attempt.outcome == "ok":
                stats["successes"] += 1
            elif attempt.outcome in ("failed", "blocked"):
                stats["failures"] += 1
                stats["last_failure"] = attempt.reason

    def record_request(self, summary: dict):
        with self._lock:
            self._last = dict(summary)

    def status(self) -> dict:
        """Secret-free: names, models, switches, whether a key is present (never the key), counters."""
        with self._lock:
            return {"order": [p.name for p in self.providers],
                    "providers": [dict(p.describe(), **self._stats.get(p.name, {})) for p in self.providers],
                    "available": any(p.enabled and p.configured() for p in self.providers),
                    "last_request": self._last}


class ProviderSession:
    """One user request. Walks the provider order from `position`, pins to the provider that answered (so the
    validator's conflict retry goes to the same model), and can be advanced past it once validation rejects its
    answer (advance())."""

    def __init__(self, orchestrator: ProviderOrchestrator):
        self.o = orchestrator
        self.position = 0
        self.attempts: list[Attempt] = []
        self.fallback_reasons: list[str] = []
        self.selected: Provider | None = None
        self.generation_ms = 0
        self.wait_ms = 0  # retry back-off sleeps (not part of generation_ms)
        self.exhausted = False
        self.blocked = False

    def _wait(self, err: ProviderError, retry: int) -> float | None:
        s = self.o.settings
        if err.reason not in RETRYABLE or retry >= s.max_retries:
            return None
        wait = err.retry_after if err.retry_after is not None else s.retry_backoff_seconds * (2 ** retry)
        return wait if wait <= s.max_retry_wait_seconds else None  # a long wait means: try the next provider

    def _call(self, p: Provider, prompt: str) -> str:
        retry = 0
        while True:
            start = self.o.clock()
            try:
                text, usage = p.send_full(prompt)
            except ProviderError as err:
                ms = int((self.o.clock() - start) * 1000)
                self.generation_ms += ms
                attempt = Attempt(p.name, p.model, "failed", err.reason, err.status, ms)
                self.attempts.append(attempt)
                self.o._record(attempt)
                wait = self._wait(err, retry)
                if wait is None:
                    raise
                log.info("provider %s %s, retrying in %.1fs", p.name, err.reason, wait)
                self.wait_ms += int(wait * 1000)
                self.o.sleep(wait)
                retry += 1
                continue
            except ProviderBlocked:
                ms = int((self.o.clock() - start) * 1000)
                self.generation_ms += ms
                attempt = Attempt(p.name, p.model, "blocked", "content_blocked", 200, ms)
                self.attempts.append(attempt)
                self.o._record(attempt)
                raise
            ms = int((self.o.clock() - start) * 1000)
            self.generation_ms += ms
            attempt = Attempt(p.name, p.model, "ok", None, 200, ms, usage)
            self.attempts.append(attempt)
            self.o._record(attempt)
            return text

    def generate(self, prompt, contract):
        if self.blocked:
            raise ProviderBlocked("request already blocked by a provider")
        if self.selected is not None:
            # Pinned: the validator's conflict retry of one candidate stays with its model. If that model is now
            # down, the candidate fails closed (the caller may still advance() to a fresh candidate).
            try:
                return self._call(self.selected, prompt)
            except ProviderError as err:
                self.fallback_reasons.append(f"{self.selected.name}: {err.reason} (retry)")
                raise
        while self.position < len(self.o.providers):
            p = self.o.providers[self.position]
            if not p.enabled:
                self.position += 1
                continue
            if not p.configured():
                self.attempts.append(Attempt(p.name, p.model, "skipped", NOT_CONFIGURED, None, 0))
                self.fallback_reasons.append(f"{p.name}: {NOT_CONFIGURED}")
                self.position += 1
                continue
            try:
                text = self._call(p, prompt)
            except ProviderError as err:
                self.fallback_reasons.append(f"{p.name}: {err.reason}")
                self.position += 1
                continue
            except ProviderBlocked:
                self.blocked = True
                raise
            self.selected = p
            return text
        self.exhausted = True
        raise ProvidersUnavailable("no provider produced a response")

    def advance(self, reason: str) -> bool:
        """Move past the provider whose answer failed validation. False when no later provider is usable."""
        if self.selected is None or self.blocked:
            return False
        if not any(p.enabled and p.configured() for p in self.o.providers[self.position + 1:]):
            return False  # nothing left: keep the record of who produced the (rejected) answer
        self.fallback_reasons.append(f"{self.selected.name}: {reason}")
        self.selected = None
        self.position += 1
        return True

    def summary(self) -> dict:
        calls = [a for a in self.attempts if a.outcome != "skipped"]
        last_ok = next((a for a in reversed(self.attempts) if a.outcome == "ok"), None)
        used = [a.usage for a in self.attempts if a.usage]
        tokens = {k: sum(u.get(k) or 0 for u in used) for k in ("input", "output", "total")} if used else None
        return {"provider": last_ok.provider if last_ok else None,   # the provider whose response was validated
                "model": last_ok.model if last_ok else None,
                "attempts": len(calls), "fallback_reasons": list(self.fallback_reasons),
                "generation_ms": self.generation_ms, "wait_ms": self.wait_ms, "tokens": tokens,
                "exhausted": self.exhausted, "blocked": self.blocked,
                "calls": [a.as_dict() for a in self.attempts]}


def from_env(env=None, **kw) -> ProviderOrchestrator:
    return ProviderOrchestrator.from_settings(ProviderSettings.from_env(env), **kw)


def safe_json(summary: dict) -> str:
    return json.dumps(summary, sort_keys=True, default=str)
