"""Query-embedding providers, independent of the generation providers (backend/providers.py).

The active ChromaDB index was built with Ollama's `nomic-embed-text` (nomic-embed-text-v1.5, 768 dimensions, unit length, squared-L2
space, the "structured" profile's search_document:/search_query: prefixes). A query must be embedded by the SAME model, or its
distances to the stored vectors mean nothing. This module only chooses and guards how the query vector is produced; it never
touches ranking, fusion, thresholds or the index.

Providers (EMBEDDING_PROVIDER):
  ollama             default. Local development. Exactly the previous behaviour: langchain_ollama.OllamaEmbeddings(model=...),
                     default host unless EMBEDDING_OLLAMA_BASE_URL is set, no retries, no timeout unless one is configured.
  openai_compatible  hosted. POST {EMBEDDING_API_URL}/embeddings with a Bearer key (any OpenAI-compatible host or a self-hosted TEI).
                     Needs EMBEDDING_API_URL (https), EMBEDDING_MODEL and EMBEDDING_API_KEY. NEVER falls back to Ollama.
  nomic_atlas        hosted (Stage 7B). Nomic's own API: POST {base}/v1/embedding/text with task_type. Same model as the index
                     (nomic-embed-text-v1.5); base defaults to https://api-atlas.nomic.ai. NEVER falls back to Ollama.
No hosted provider is approved by default. In a cloud deployment (TG_SNAPSHOT_STORE=r2, TG_CLOUD=1 or RENDER=true) the provider
must be named explicitly and cannot be ollama: otherwise the embedding guard is "misconfigured" and the corpus is not ready.

Fail-safe rules:
  * Every failure (missing key, timeout, rate limit, 5xx, malformed body, wrong dimensions, wrong norm, incompatible model) raises
    EmbeddingUnavailable with a fixed, secret-free message. Nothing returns a made-up or substituted vector.
  * Dimensions are checked on every call against the index (or the snapshot manifest). A hosted provider must also pass a
    compatibility check before its first query vector is used: it embeds the manifest's probe texts and each result must match the
    reference vector produced by the index's own model (cosine >= EMBEDDING_MIN_COSINE). Same dimensions are not enough: other
    768-dimensional models exist.
  * A circuit breaker stops hammering a failing provider (free-tier threads are scarce), and a semaphore bounds concurrent calls.
  * The API key is read from the environment, sent only in an Authorization header, and never logged, returned or put in an
    exception message.
"""
from __future__ import annotations

import json
import logging
import math
import re
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urlparse

import requests

log = logging.getLogger("kyr.embeddings")

PROVIDER_OLLAMA = "ollama"
PROVIDER_HOSTED = "openai_compatible"
PROVIDER_ATLAS = "nomic_atlas"          # Stage 7B: Nomic's own hosted API (the only provider of the index's exact model that was found)
PROVIDER_INPROCESS = "inprocess_nomic"  # Stage 7C: the index's own model (nomic-embed-text-v1.5 F16 GGUF) run inside this process (backend/nomic_local.py)
PROVIDERS = (PROVIDER_OLLAMA, PROVIDER_HOSTED, PROVIDER_ATLAS, PROVIDER_INPROCESS)
HOSTED_PROVIDERS = (PROVIDER_HOSTED, PROVIDER_ATLAS)
ATLAS_DEFAULT_URL = "https://api-atlas.nomic.ai"

# The vectors in the active index come from this model family. (provider, model) pairs known to serve it. A label is a CLAIM about
# the provider; what proves it is the probe check against the vectors stored in the snapshot manifest (cosine >= min_cosine).
INDEX_FAMILY = "nomic-embed-text-v1.5"
KNOWN_FAMILIES = {
    (PROVIDER_OLLAMA, "nomic-embed-text"): INDEX_FAMILY,
    (PROVIDER_OLLAMA, "nomic-embed-text:latest"): INDEX_FAMILY,
    (PROVIDER_HOSTED, "nomic-ai/nomic-embed-text-v1.5"): INDEX_FAMILY,
    (PROVIDER_HOSTED, "nomic-embed-text-v1.5"): INDEX_FAMILY,
    (PROVIDER_ATLAS, "nomic-embed-text-v1.5"): INDEX_FAMILY,
    (PROVIDER_INPROCESS, "nomic-embed-text-v1.5"): INDEX_FAMILY,
}

# Task prefixes -> the Nomic API's task_type. The Nomic API applies the task itself; it has no "no task" mode.
ATLAS_TASKS = {"search_query: ": "search_query", "search_document: ": "search_document",
               "clustering: ": "clustering", "classification: ": "classification"}

# Failure reasons (stable strings; shown in /status and logs, never carrying provider text).
NOT_CONFIGURED, AUTH, RATE_LIMITED, UNAVAILABLE, TIMEOUT, CONNECTION = (
    "not_configured", "auth_error", "rate_limited", "unavailable", "timeout", "connection_error")
BAD_REQUEST, BAD_RESPONSE, DIMENSION_MISMATCH, NOT_NORMALIZED, INCOMPATIBLE = (
    "bad_request", "bad_response", "dimension_mismatch", "not_normalized", "incompatible_model")
NOT_VERIFIED, CIRCUIT_OPEN, BUSY = "not_verified", "circuit_open", "busy"
RETRYABLE = frozenset({RATE_LIMITED, UNAVAILABLE, CONNECTION})
PERMANENT = frozenset({DIMENSION_MISMATCH, NOT_NORMALIZED, INCOMPATIBLE, NOT_CONFIGURED})


class EmbeddingUnavailable(RuntimeError):
    """The query could not be embedded safely. Deliberately NOT a ValueError: vector_search() treats ValueError as 'exact search
    cannot be used' and would retry through Chroma, which would embed again."""

    def __init__(self, reason: str, detail: str = "", status: int | None = None):
        super().__init__(f"{reason}{f' (HTTP {status})' if status else ''}{f': {detail}' if detail else ''}")
        self.reason, self.detail, self.status = reason, detail, status


class EmbeddingIncompatible(EmbeddingUnavailable):
    """The provider's vectors cannot be compared with the index's (wrong size, wrong model, wrong scale)."""


# ---------------------------------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------------------------------
def _num(env, name, default, lo, hi, cast=float, problems=None):
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = cast(raw)
    except ValueError:
        if problems is not None:
            problems.append(f"{name} is not a number")
        return default
    return min(max(value, lo), hi)


def _flag(env, name, default=False):
    raw = (env.get(name) or "").strip().lower()
    return default if not raw else raw in ("1", "true", "yes", "on")


def cloud_mode(env=None) -> bool:
    """True when this process is a cloud deployment: its index comes from an object store (R2), it was told so explicitly, or the
    platform says so (Render sets RENDER=true). Local development sets none of these."""
    env = os.environ if env is None else env
    return ((env.get("TG_SNAPSHOT_STORE") or "").strip().lower() == "r2" or _flag(env, "TG_CLOUD")
            or (env.get("RENDER") or "").strip().lower() == "true")


def _secret(env, name):
    value = (env.get(name) or "").strip()
    return "" if not value or "placeholder" in value.lower() or value.startswith("your-") else value


def _loopback(host: str) -> bool:
    return host in ("localhost", "127.0.0.1", "::1") or host.endswith(".localhost")


@dataclass(frozen=True)
class EmbeddingSettings:
    provider: str = PROVIDER_OLLAMA
    model: str = "nomic-embed-text"
    family: str = ""                       # declared model family; "" = unknown
    api_url: str = field(default="", repr=False)   # hosted: base URL, e.g. https://api.fireworks.ai/inference/v1 (not shown: some providers put tokens in paths)
    api_key: str = field(default="", repr=False)
    timeout_seconds: float | None = None   # None = the client's own default (ollama only; hosted always has one)
    max_retries: int = 0                   # extra attempts for rate limits / 5xx / connection errors
    retry_backoff_seconds: float = 0.5
    max_retry_wait_seconds: float = 5.0
    ollama_base_url: str = ""              # "" = the client default (OLLAMA_HOST or 127.0.0.1:11434): the previous behaviour
    dimensions: int = 0                    # 0 = take it from the index / manifest
    send_dimensions: bool = False          # also send "dimensions" in the request body (resizable models only)
    normalize: bool = False                # renormalise to unit length instead of refusing a non-unit vector
    verify: str = "auto"                   # auto (hosted: required, ollama: no) | required | off
    min_cosine: float = 0.995
    breaker_failures: int = 3
    breaker_cooldown_seconds: float = 30.0
    max_concurrency: int = 8
    reverify_seconds: float = 60.0
    problems: tuple = ()                   # configuration errors: the provider refuses every call, never falls back
    model_file: str = field(default="", repr=False)   # inprocess_nomic: path of the GGUF weights (never shown)
    model_sha256: str = ""                 # inprocess_nomic: SHA-256 the file must have (mandatory in a cloud deployment)
    model_source: str = "file"             # inprocess_nomic: "file" (EMBEDDING_MODEL_FILE) or "memory" (the verified buffer backend/vercel_runtime.py downloaded)

    @property
    def hosted(self) -> bool:
        return self.provider in HOSTED_PROVIDERS

    @property
    def in_process(self) -> bool:
        return self.provider == PROVIDER_INPROCESS

    @property
    def verification_required(self) -> bool:
        # A hosted or in-process model is only trusted after its vectors match the probe vectors stored with the snapshot.
        return self.verify == "required" or (self.verify == "auto" and (self.hosted or self.in_process))

    @classmethod
    def from_env(cls, env=None) -> "EmbeddingSettings":
        env = os.environ if env is None else env
        problems: list[str] = []
        raw_provider = (env.get("EMBEDDING_PROVIDER") or "").strip().lower()
        provider = raw_provider or PROVIDER_OLLAMA
        if provider not in PROVIDERS:
            problems.append(f"EMBEDDING_PROVIDER must be one of {', '.join(PROVIDERS)}")
            provider = "invalid"
        elif cloud_mode(env):
            # Stage 7B: a cloud deployment never inherits the local default and never talks to an Ollama it did not bring itself.
            if not raw_provider:
                problems.append("EMBEDDING_PROVIDER must be set explicitly in a cloud deployment (there is no default)")
            elif provider == PROVIDER_OLLAMA:
                problems.append("EMBEDDING_PROVIDER=ollama is local development only; a cloud deployment needs a hosted provider")
        hosted = provider in HOSTED_PROVIDERS
        in_process = provider == PROVIDER_INPROCESS
        model = (env.get("EMBEDDING_MODEL") or "").strip() or ("" if hosted else (INDEX_FAMILY if in_process else "nomic-embed-text"))
        api_url = (env.get("EMBEDDING_API_URL") or "").strip().rstrip("/") or (ATLAS_DEFAULT_URL if provider == PROVIDER_ATLAS else "")
        key = _secret(env, "EMBEDDING_API_KEY")
        if hosted:
            if not model:
                problems.append("EMBEDDING_MODEL is required for a hosted provider (no default model is assumed)")
            if not key:
                problems.append("EMBEDDING_API_KEY is not set")
            parsed = urlparse(api_url)
            if not api_url:
                problems.append("EMBEDDING_API_URL is required for a hosted provider")
            elif parsed.scheme != "https" and not (parsed.scheme == "http" and _loopback(parsed.hostname or "")):
                problems.append("EMBEDDING_API_URL must be https (plain http only for loopback)")
            elif not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                problems.append("EMBEDDING_API_URL must be a plain base URL without credentials or a query string")
        model_file, model_sha = "", ""
        model_source = (env.get("EMBEDDING_MODEL_SOURCE") or "").strip().lower() or "file"
        if model_source not in ("file", "memory"):
            problems.append("EMBEDDING_MODEL_SOURCE must be file or memory")
            model_source = "file"
        if model_source == "memory" and not in_process:
            problems.append(f"EMBEDDING_MODEL_SOURCE=memory needs EMBEDDING_PROVIDER={PROVIDER_INPROCESS}")
        if in_process:
            model_file = (env.get("EMBEDDING_MODEL_FILE") or "").strip()
            model_sha = (env.get("EMBEDDING_MODEL_SHA256") or "").strip().lower()
            if model != INDEX_FAMILY:
                problems.append(f"EMBEDDING_MODEL must be {INDEX_FAMILY} for {PROVIDER_INPROCESS}: it runs that one model and no other")
            if model_source == "memory":
                if model_file:
                    problems.append("EMBEDDING_MODEL_FILE must not be set when EMBEDDING_MODEL_SOURCE=memory")
                if not model_sha:
                    problems.append("EMBEDDING_MODEL_SHA256 is required when EMBEDDING_MODEL_SOURCE=memory")
            elif not model_file:
                problems.append("EMBEDDING_MODEL_FILE is required for inprocess_nomic (the path of the nomic-embed-text-v1.5 GGUF file)")
            elif not os.path.isfile(model_file):
                problems.append("EMBEDDING_MODEL_FILE does not name an existing file")
            if model_sha and not re.fullmatch(r"[0-9a-f]{64}", model_sha):
                problems.append("EMBEDDING_MODEL_SHA256 must be 64 hex characters")
            elif not model_sha and cloud_mode(env):
                problems.append("EMBEDDING_MODEL_SHA256 is required in a cloud deployment: the model file must be pinned to the weights the index was built with")
        verify = (env.get("EMBEDDING_VERIFY") or "").strip().lower() or "auto"
        if verify not in ("auto", "required", "off"):
            problems.append("EMBEDDING_VERIFY must be auto, required or off")
            verify = "required"
        family = (env.get("EMBEDDING_MODEL_FAMILY") or "").strip() or KNOWN_FAMILIES.get((provider, model), "")
        timeout = _num(env, "EMBEDDING_TIMEOUT_SECONDS", 10.0 if hosted else (60.0 if in_process else None), 0.5, 120.0, problems=problems)
        return cls(
            provider=provider, model=model, family=family, api_url=api_url, api_key=key, timeout_seconds=timeout,
            max_retries=_num(env, "EMBEDDING_MAX_RETRIES", 2 if hosted else 0, 0, 5, int, problems),
            retry_backoff_seconds=_num(env, "EMBEDDING_RETRY_BACKOFF_SECONDS", 0.5, 0.0, 10.0, problems=problems),
            max_retry_wait_seconds=_num(env, "EMBEDDING_MAX_RETRY_WAIT_SECONDS", 5.0, 0.0, 30.0, problems=problems),
            ollama_base_url=(env.get("EMBEDDING_OLLAMA_BASE_URL") or "").strip().rstrip("/"),
            dimensions=_num(env, "EMBEDDING_DIMENSIONS", 0, 0, 8192, int, problems),
            send_dimensions=_flag(env, "EMBEDDING_SEND_DIMENSIONS"), normalize=_flag(env, "EMBEDDING_NORMALIZE"),
            verify=verify, min_cosine=_num(env, "EMBEDDING_MIN_COSINE", 0.995, 0.98, 1.0, problems=problems),
            breaker_failures=_num(env, "EMBEDDING_BREAKER_FAILURES", 3, 1, 20, int, problems),
            breaker_cooldown_seconds=_num(env, "EMBEDDING_BREAKER_COOLDOWN_SECONDS", 30.0, 1.0, 600.0, problems=problems),
            max_concurrency=_num(env, "EMBEDDING_MAX_CONCURRENCY", 8, 1, 64, int, problems),
            reverify_seconds=_num(env, "EMBEDDING_REVERIFY_SECONDS", 60.0, 5.0, 3600.0, problems=problems),
            problems=tuple(problems), model_file=model_file, model_sha256=model_sha, model_source=model_source)

    def describe(self) -> dict:
        """Safe to show: names, switches and the endpoint HOST. Never the key, never a full URL."""
        return {"provider": self.provider, "model": self.model, "family": self.family or None, "hosted": self.hosted,
                "endpoint_host": (urlparse(self.api_url).hostname if self.hosted else None),
                "api_key_set": bool(self.api_key), "timeout_seconds": self.timeout_seconds, "max_retries": self.max_retries,
                "verify": self.verify, **({"in_process": True, "model_file_set": bool(self.model_file), "model_sha256_pinned": bool(self.model_sha256),
                                           **({"model_source": "memory"} if self.model_source == "memory" else {})}
                                          if self.in_process else {})}


# ---------------------------------------------------------------------------------------------------
# Backends: text list in, list of vectors out. Transport only.
# ---------------------------------------------------------------------------------------------------
def _status_reason(status: int) -> str:
    if status in (401, 403):
        return AUTH
    if status == 408:
        return TIMEOUT
    if status == 429:
        return RATE_LIMITED
    if status >= 500:
        return UNAVAILABLE
    return BAD_REQUEST


def _retry_after(resp):
    try:
        value = (getattr(resp, "headers", None) or {}).get("retry-after") or (getattr(resp, "headers", None) or {}).get("Retry-After")
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class HostedBackend:
    """OpenAI-compatible embeddings endpoint. One HTTP call per batch; every failure becomes EmbeddingUnavailable."""

    def __init__(self, settings: EmbeddingSettings, http: Callable | None = None, sleep: Callable = time.sleep):
        self.s, self.http, self.sleep = settings, http or requests.post, sleep
        base = settings.api_url
        self.url = base if base.endswith("/embeddings") else f"{base}/embeddings"

    def embed(self, texts: list[str]) -> list[list[float]]:
        body = {"model": self.s.model, "input": list(texts)}
        if self.s.send_dimensions and self.s.dimensions:
            body["dimensions"] = self.s.dimensions
        return self._post_retry(body, len(texts))

    def _post_retry(self, body, expected) -> list[list[float]]:
        headers = {"Authorization": f"Bearer {self.s.api_key}", "Content-Type": "application/json", "Accept": "application/json"}
        attempt = 0
        while True:
            try:
                return self._once(headers, body, expected)
            except EmbeddingUnavailable as err:
                if err.reason not in RETRYABLE or attempt >= self.s.max_retries:
                    raise
                wait = self.s.retry_backoff_seconds * (2 ** attempt)
                if err.reason == RATE_LIMITED:
                    advised = getattr(err, "retry_after", None)
                    wait = max(wait, advised or 0.0)
                    if wait > self.s.max_retry_wait_seconds:
                        raise  # the provider asks for a longer wait than is sensible for a user request
                attempt += 1
                self.sleep(min(wait, self.s.max_retry_wait_seconds))

    def _once(self, headers, body, expected) -> list[list[float]]:
        try:
            resp = self.http(self.url, headers=headers, json=body, timeout=self.s.timeout_seconds)
        except requests.Timeout:
            raise EmbeddingUnavailable(TIMEOUT) from None
        except requests.ConnectionError:
            raise EmbeddingUnavailable(CONNECTION) from None
        except requests.RequestException as exc:
            raise EmbeddingUnavailable(CONNECTION, type(exc).__name__) from None
        if resp.status_code != 200:
            err = EmbeddingUnavailable(_status_reason(resp.status_code), status=resp.status_code)
            err.retry_after = _retry_after(resp)
            raise err
        try:
            return self._parse(resp.json(), expected)
        except (ValueError, KeyError, TypeError, AttributeError):
            raise EmbeddingUnavailable(BAD_RESPONSE, "unexpected response shape", status=200) from None

    def _parse(self, data, expected) -> list[list[float]]:
        rows = data["data"]
        if not isinstance(rows, list) or len(rows) != expected:
            raise ValueError
        rows = sorted(rows, key=lambda r: r.get("index", 0)) if all(isinstance(r, dict) and "index" in r for r in rows) else rows
        return [r["embedding"] for r in rows]


class NomicAtlasBackend(HostedBackend):
    """Nomic's own embedding API: POST {base}/v1/embedding/text with {"texts", "model", "task_type"} -> {"embeddings": [...]}.

    The API applies the task prefix itself (task_type), so the 'search_query: ' / 'search_document: ' prefix that the application
    adds is turned back into a task_type and removed from the text, one request per task. A text with no prefix the API can
    reproduce is refused: the API has no 'no task' mode, so it cannot make the vectors the index holds for such text.
    Whether the server's prefixing is byte-identical to the local model's is NOT assumed: the probe check against the snapshot
    manifest decides (cosine >= min_cosine), and a failure keeps the provider switched off."""

    def __init__(self, settings: EmbeddingSettings, http: Callable | None = None, sleep: Callable = time.sleep):
        super().__init__(settings, http=http, sleep=sleep)
        base = settings.api_url
        self.url = base if base.endswith("/v1/embedding/text") else f"{base}/v1/embedding/text"

    def embed(self, texts: list[str]) -> list[list[float]]:
        groups: dict[str, list[tuple[int, str]]] = {}
        for i, text in enumerate(texts):
            for prefix, task in ATLAS_TASKS.items():
                if text.startswith(prefix):
                    groups.setdefault(task, []).append((i, text[len(prefix):]))
                    break
            else:
                raise EmbeddingUnavailable(INCOMPATIBLE, "text has no task prefix that the Nomic API can reproduce")
        out: list = [None] * len(texts)
        for task, items in groups.items():
            body = {"texts": [t for _, t in items], "model": self.s.model, "task_type": task}
            if self.s.send_dimensions and self.s.dimensions:
                body["dimensionality"] = self.s.dimensions
            for (i, _), vector in zip(items, self._post_retry(body, len(items))):
                out[i] = vector
        return out

    def _parse(self, data, expected) -> list[list[float]]:
        rows = data["embeddings"]
        if not isinstance(rows, list) or len(rows) != expected:
            raise ValueError
        return rows


class OllamaBackend:
    """Local Ollama through langchain_ollama, built exactly as before (same class, same defaults)."""

    def __init__(self, settings: EmbeddingSettings, factory: Callable | None = None):
        self.client, self.error = None, None
        try:
            if factory is None:
                from langchain_ollama import OllamaEmbeddings as factory  # imported here, so hosted deployments need not install it
            kwargs = {"model": settings.model}
            if settings.ollama_base_url:
                kwargs["base_url"] = settings.ollama_base_url
            if settings.timeout_seconds:
                kwargs["client_kwargs"] = {"timeout": settings.timeout_seconds}
            self.client = factory(**kwargs)
        except Exception as exc:  # noqa: BLE001 - e.g. langchain-ollama not installed
            self.error = type(exc).__name__

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self.client is None:
            raise EmbeddingUnavailable(NOT_CONFIGURED, f"ollama client unavailable ({self.error or 'not built'})")
        try:
            return self.client.embed_documents(list(texts))
        except EmbeddingUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - connection refused, model not pulled, ...
            raise EmbeddingUnavailable(CONNECTION, type(exc).__name__) from None


class InProcessBackend:
    """The index's own model, loaded ONCE here (the engine memory-maps the weights and verifies them against the pin), then used for every
    call. A model that cannot be loaded or verified leaves `load_error` set: the guard reports 'misconfigured' and refuses every call;
    nothing is substituted. Error text is fixed and contains no paths."""

    def __init__(self, settings: EmbeddingSettings, engine_factory: Callable | None = None):
        self.engine, self.load_error = None, None
        from backend import nomic_local
        self._error_type = nomic_local.ModelError
        try:
            factory = engine_factory or nomic_local.NomicEngine
            if settings.model_source == "memory":
                buffer = nomic_local.get_memory_model()
                if buffer is None:
                    raise nomic_local.ModelError("the model was not loaded into memory at start-up")
                self.engine = factory(None, settings.model_sha256 or None, buffer=buffer)
            else:
                self.engine = factory(settings.model_file, settings.model_sha256 or None)
        except nomic_local.ModelError as exc:
            self.load_error = str(exc)
        except Exception as exc:  # noqa: BLE001 - e.g. numpy/tokenizers missing, out of memory while mapping
            self.load_error = f"the embedding model could not be loaded ({type(exc).__name__})"
        if self.load_error:
            log.error("in-process embedding model not loaded: %s", self.load_error)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self.engine is None:
            raise EmbeddingUnavailable(NOT_CONFIGURED, self.load_error or "the embedding model is not loaded")
        try:
            return [[float(x) for x in v] for v in self.engine.embed(texts)]
        except self._error_type as exc:          # e.g. text without a task prefix: not this index's space
            raise EmbeddingIncompatible(INCOMPATIBLE, str(exc)) from None


class DisabledBackend:
    """Misconfigured provider: every call refuses. There is no fallback to another provider."""

    def embed(self, texts):
        raise EmbeddingUnavailable(NOT_CONFIGURED, "embedding provider is not configured correctly")


def cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# ---------------------------------------------------------------------------------------------------
# The guard: what the rest of the application talks to (it is the `base` of rag_profiles.ProfileEmbeddings)
# ---------------------------------------------------------------------------------------------------
class GuardedEmbeddings:
    UNIT_TOLERANCE = 1e-3

    def __init__(self, settings: EmbeddingSettings, backend, clock: Callable = time.monotonic):
        self.settings, self.backend, self.clock = settings, backend, clock
        self.provider = settings.provider
        self.model = settings.model          # an attribute (not a property): the cache epoch reads it
        self.expected_dims: int | None = settings.dimensions or None
        self.expected_family: str | None = None
        self.probes: list[dict] = []
        self.min_cosine = settings.min_cosine
        self.index_problems: list[str] = []
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(settings.max_concurrency)
        self._failures, self._open_until = 0, 0.0
        self._verified, self._incompatible = False, None
        self._last_error, self._last_verify_try = None, -1e9
        self._verify_report: dict | None = None

    # ---- what the index requires -------------------------------------------------------------------------------------------
    def configure_index(self, dims=None, family=None, probes=None, min_cosine=None):
        """Called once the index (or the snapshot manifest) is known. A configured size or model that contradicts it is permanent."""
        self.index_problems = []
        if dims:
            if self.settings.dimensions and self.settings.dimensions != dims:
                self.index_problems.append(f"EMBEDDING_DIMENSIONS={self.settings.dimensions} but the index holds {dims}-dimensional vectors")
            self.expected_dims = dims
        if family:
            self.expected_family = family
            if self.settings.hosted and self.settings.family != family:
                self.index_problems.append(
                    f"the index was built with {family}; model {self.settings.model!r} is not known to be that model "
                    "(set EMBEDDING_MODEL_FAMILY only after verifying it)")
            elif not self.settings.hosted and self.settings.family and self.settings.family != family:
                self.index_problems.append(f"the index was built with {family}; model {self.settings.model!r} is a different model")
        self.probes = [p for p in (probes or []) if isinstance(p, dict) and isinstance(p.get("input"), str) and isinstance(p.get("vector"), list)]
        if min_cosine:
            self.min_cosine = max(float(min_cosine), self.settings.min_cosine)
        if self.index_problems:
            self._incompatible = "; ".join(self.index_problems)

    # ---- state --------------------------------------------------------------------------------------------------------------
    @property
    def state(self) -> str:
        if self.settings.problems or self.settings.provider == "invalid" or getattr(self.backend, "load_error", None):
            return "misconfigured"
        if self._incompatible:
            return "incompatible"
        if self.settings.verification_required and self.settings.verify != "off" and not self._verified:
            return "unverified" if self._last_error in (None, NOT_VERIFIED) else "unavailable"
        if self._last_error and self._failures >= self.settings.breaker_failures:
            return "unavailable"
        return "ok"

    def ready(self) -> bool:
        return self.state == "ok"

    def health(self) -> dict:
        problems = list(self.settings.problems) + list(self.index_problems)
        if getattr(self.backend, "load_error", None):
            problems.append(self.backend.load_error)
        if self._incompatible and not self.index_problems:
            problems.append(self._incompatible)
        if self.settings.verification_required and not self._verified and not self.probes and not self._incompatible:
            problems.append("no embedding probes are available to verify the provider (publish a snapshot manifest with probes)")
        return {**self.settings.describe(), "state": self.state, "ready": self.ready(),
                "expected_dimensions": self.expected_dims, "expected_family": self.expected_family,
                "verified": self._verified, "probes": len(self.probes), "last_error": self._last_error,
                "problems": problems, "verification": self._verify_report}

    # ---- calls --------------------------------------------------------------------------------------------------------------
    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(list(texts))

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if self.settings.problems or self.settings.provider == "invalid" or getattr(self.backend, "load_error", None):
            raise EmbeddingUnavailable(NOT_CONFIGURED, "embedding provider is not configured correctly")
        if self._incompatible:
            raise EmbeddingIncompatible(INCOMPATIBLE, "the embedding provider is not compatible with the index")
        self._ensure_verified()
        return self._call(texts)

    def _call(self, texts: list[str]) -> list[list[float]]:
        now = self.clock()
        if now < self._open_until:
            raise EmbeddingUnavailable(CIRCUIT_OPEN, "recent embedding failures; not calling the provider yet")
        if not self._slots.acquire(timeout=max(self.settings.timeout_seconds or 5.0, 1.0)):
            raise EmbeddingUnavailable(BUSY, "too many concurrent embedding calls")
        try:
            try:
                vectors = self.backend.embed(texts)
            except EmbeddingUnavailable as err:
                self._record_failure(err)
                raise
            except Exception as exc:  # noqa: BLE001 - nothing escapes unclassified
                err = EmbeddingUnavailable(BAD_RESPONSE, type(exc).__name__)
                self._record_failure(err)
                raise err from None
        finally:
            self._slots.release()
        try:
            vectors = self._check(vectors, len(texts))
        except EmbeddingIncompatible as err:
            self._incompatible = str(err)  # permanent for this process: the provider returns the wrong kind of vector
            self._last_error = err.reason
            raise
        self._failures, self._last_error = 0, None
        return vectors

    def _record_failure(self, err: EmbeddingUnavailable):
        with self._lock:
            self._failures += 1
            self._last_error = err.reason
            if err.reason in PERMANENT or self._failures >= self.settings.breaker_failures:
                self._open_until = self.clock() + self.settings.breaker_cooldown_seconds
        log.warning("embedding provider call failed: provider=%s reason=%s status=%s", self.provider, err.reason, err.status)

    def _check(self, vectors, expected) -> list[list[float]]:
        if not isinstance(vectors, list) or len(vectors) != expected:
            raise EmbeddingUnavailable(BAD_RESPONSE, "wrong number of vectors")
        out = []
        for v in vectors:
            if not isinstance(v, (list, tuple)) or not v or not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in v):
                raise EmbeddingUnavailable(BAD_RESPONSE, "vector is not a finite list of numbers")
            if self.expected_dims and len(v) != self.expected_dims:
                raise EmbeddingIncompatible(DIMENSION_MISMATCH, f"provider returned {len(v)} dimensions, the index holds {self.expected_dims}")
            if self.settings.hosted or self.settings.in_process:
                norm = math.sqrt(sum(x * x for x in v))
                if abs(norm - 1.0) > self.UNIT_TOLERANCE:
                    if not self.settings.normalize or norm == 0:
                        raise EmbeddingIncompatible(NOT_NORMALIZED, f"vector length {norm:.3f}, the index holds unit vectors")
                    v = [x / norm for x in v]
            out.append(list(v))
        return out

    # ---- compatibility with the index ----------------------------------------------------------------------------------------
    def _ensure_verified(self):
        s = self.settings
        if not s.verification_required or s.verify == "off" or self._verified:
            return
        with self._lock:
            if self._verified:
                return
            if not self.probes:
                self._last_error = NOT_VERIFIED
                raise EmbeddingUnavailable(NOT_VERIFIED, "no embedding probes to verify the provider against the index")
            if self.clock() - self._last_verify_try < s.reverify_seconds:
                raise EmbeddingUnavailable(NOT_VERIFIED, "embedding provider is not verified yet; retrying shortly")
            self._last_verify_try = self.clock()
        self.verify()

    def verify(self) -> dict:
        """Embed the manifest's probe texts and compare with the reference vectors. Sets the verified/incompatible state."""
        report = {"probes": len(self.probes), "min_cosine_required": self.min_cosine, "cosines": [], "ok": False}
        if not self.probes:
            raise EmbeddingUnavailable(NOT_VERIFIED, "no embedding probes to verify the provider against the index")
        try:
            got = self._call([p["input"] for p in self.probes])
        except EmbeddingIncompatible as err:
            report.update(error=err.reason)
            self._verify_report = report
            raise
        except EmbeddingUnavailable as err:
            report.update(error=err.reason)
            self._verify_report = report
            raise
        cos = [round(cosine(a, p["vector"]), 6) for a, p in zip(got, self.probes)]
        report.update(cosines=cos, min_cosine_observed=min(cos))
        if min(cos) < self.min_cosine:
            self._incompatible = (f"the provider's vectors do not match the index's embedding model "
                                  f"(lowest probe cosine {min(cos):.4f} < {self.min_cosine})")
            report["ok"] = False
            self._verify_report = report
            raise EmbeddingIncompatible(INCOMPATIBLE, self._incompatible)
        report["ok"] = True
        self._verified, self._last_error = True, None
        self._verify_report = report
        return report


def build_embeddings(settings: EmbeddingSettings | None = None, *, http=None, sleep=time.sleep, ollama_factory=None,
                     clock=time.monotonic, engine_factory=None) -> GuardedEmbeddings:
    """The guarded embeddings for the configuration. A bad configuration yields a guard that refuses every call; it never
    builds a different provider than the one asked for."""
    s = settings or EmbeddingSettings.from_env()
    if s.problems or s.provider not in PROVIDERS:
        backend = DisabledBackend()
    elif s.provider == PROVIDER_ATLAS:
        backend = NomicAtlasBackend(s, http=http, sleep=sleep)
    elif s.in_process:
        backend = InProcessBackend(s, engine_factory=engine_factory)
    elif s.hosted:
        backend = HostedBackend(s, http=http, sleep=sleep)
    else:
        backend = OllamaBackend(s, factory=ollama_factory)
    return GuardedEmbeddings(s, backend, clock=clock)


def make_probes(embed: Callable[[list[str]], list[list[float]]], texts: list[str], doc_prefix: str) -> list[dict]:
    """Reference vectors for the manifest: the index's own model embeds `doc_prefix + text`. Used when publishing a snapshot."""
    inputs = [doc_prefix + t for t in texts]
    return [{"input": i, "vector": [float(x) for x in v]} for i, v in zip(inputs, embed(inputs))]


# Neutral sentences: no corpus text leaves the machine when a hosted provider is verified.
PROBE_TEXTS = (
    "A person who drives a vehicle on a public road shall carry the documents required by the rules.",
    "The authority may issue a notice to the owner of a registered vehicle after an inspection.",
    "Every application shall be made in the prescribed form and accompanied by the prescribed fee.",
)


def main(argv=None, out=print) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Embedding provider preflight (operator tool; uses the configured provider and key).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("config", help="show the effective configuration (no secrets)")
    pf = sub.add_parser("preflight", help="verify the configured provider against a snapshot manifest's probes")
    pf.add_argument("--manifest", required=True)
    args = ap.parse_args(argv)
    guard = build_embeddings()
    if args.cmd == "config":
        out(json.dumps(guard.health(), indent=1))
        return 0 if guard.state != "misconfigured" else 2
    manifest = json.loads(open(args.manifest, encoding="utf-8").read())
    emb = manifest.get("embedding", {})
    guard.configure_index(emb.get("dimensions"), emb.get("family"), emb.get("probes"), emb.get("min_cosine"))
    try:
        report = guard.verify()
        out(json.dumps({"verdict": "compatible", **report}, indent=1))
        return 0
    except EmbeddingUnavailable as err:
        out(json.dumps({"verdict": "incompatible" if isinstance(err, EmbeddingIncompatible) else "unavailable",
                        "reason": err.reason, "detail": err.detail, "health": guard.health()}, indent=1))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
