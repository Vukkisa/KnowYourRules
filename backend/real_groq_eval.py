"""
Controlled real-model evaluation of the grounded answer pipeline (opt-in; never part of the unit tests).

    # mocked responses (default; no network, no key): writes the sample report
    python -m backend.real_groq_eval

    # real Groq calls: BOTH the flag and the environment variable, and a key in the process environment
    KYR_REAL_GROQ_EVAL=1 GROQ_API_KEY=... python -m backend.real_groq_eval --real \
        --max-calls 28 --max-total-tokens 150000 \
        --markdown eval/real-model/REPORT.md --json eval/real-model/results.json

Each case runs through the server's real /chat handler in grounded mode (follow-up handling, penalty lock,
evidence contract, prompt, validator, bounded conflict retry, backend rendering, citations). Substituted, per case
and restored afterwards: the approval gate and index check (forced open, nothing written), retrieval (returns the
case's synthetic passages), the approved-source table (one synthetic hash) and ANSWER_GENERATOR (the recording
adapter below). grounded_answer.validate, conflict_retry_note and answer are wrapped only to RECORD what they return.

The passages are synthetic test text. Nothing here measures legal correctness on real Telangana provisions, and a
validator accepting an answer does not show that the answer is legally correct.

Safeguards: real calls need --real AND KYR_REAL_GROQ_EVAL=1 AND GROQ_API_KEY in the process environment (.env is
never read). The SDK client is built with max_retries=0. Every call is checked against a call limit and a token
budget BEFORE it is made; once either is reached no further call is made and the remaining cases are "not_run".
Infrastructure failures (timeout, network, authentication, rate limit, server) are recorded as such and never scored
as validator rejections; output the provider refused (a 400 carrying failed_generation) and truncated output count as
model cases that did not achieve their expected behaviour, not as rejections or acceptances. The endpoint is pinned
to https://api.groq.com. Keys are removed from everything written.
"""

import argparse
import collections
import contextlib
import datetime
import hashlib
import json
import logging
import math
import os
import re
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from unittest import mock

from backend import answer_quality_eval as aq

BASE_DIR = Path(__file__).resolve().parent.parent
CASES_FILE = BASE_DIR / "eval" / "real-model" / "cases.json"
SAMPLE_REPORT = BASE_DIR / "eval" / "real-model" / "SAMPLE-REPORT.md"
OPT_IN_ENV = "KYR_REAL_GROQ_EVAL"
KEY_ENV = "GROQ_API_KEY"
DEFAULT_MODEL = "openai/gpt-oss-120b"  # the model the server's legacy Groq client uses
HARD_MAX_CALLS = 40
DEFAULT_MAX_CALLS = 28                 # 14 model cases x (first call + at most one conflict retry)
DEFAULT_MAX_TOKENS = 150_000
DEFAULT_MAX_COMPLETION = 4096
DEFAULT_TIMEOUT = 60.0
MAX_CONSECUTIVE_FAILURES = 3
OUTCOMES = ("answer", "conflict", "no_support", "clarification", "restricted", "rejected")
CITING = ("answer", "conflict")
PHRASE_KINDS = ("condition", "content")
_CONDITION_MARKER = re.compile(r"\b(?:except|provided|only|unless|if|when|whenever|subject to|save)\b")
JSON_MODE_REASON = ("grounded_answer.ANSWER_INSTRUCTIONS says 'Respond with ONE JSON object and nothing else' and "
                    "parse_response() applies json.loads to the raw text with no cleanup")
DISCLAIMER = ("All evaluation passages are SYNTHETIC test text (eval/answer-quality/fixtures.json), not Telangana "
              "legal provisions. These results do not measure legal correctness on real Telangana legal provisions. "
              "Validator acceptance does not prove legal correctness; legal meaning preservation needs manual review.")


# ---------------------------------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------------------------------
class CaseError(ValueError):
    pass


def load_cases(path=CASES_FILE) -> tuple[list, dict]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    passages = json.loads((BASE_DIR / doc["passages_file"]).read_text(encoding="utf-8"))["passages"]
    local = doc.get("passages", {})
    validate_local_passages(local, passages)
    passages = dict(passages, **local)
    validate_cases(doc["cases"], passages)
    return doc["cases"], passages


def validate_local_passages(local, shared) -> None:
    """Passages defined in the case file itself: fictional, labelled as such, with no legal identifiers (no rule,
    section, G.O., date, amount ...), and never shadowing a shared fixture passage."""
    from backend.grounded_answer import identifiers
    for key, p in local.items():
        if key in shared:
            raise CaseError(f"local passage {key} would replace a shared fixture passage")
        if not (p.get("manifest_id", "").startswith("synthetic-fictional") and p.get("text", "").startswith("Synthetic")
                and "fictional" in p["text"].lower() and "not legislation" in (p.get("note") or "").lower()):
            raise CaseError(f"local passage {key} is not clearly marked fictional and synthetic")
        if identifiers(p["text"]) or identifiers(p.get("provision_id", "")):
            raise CaseError(f"local passage {key} contains a legal identifier")


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def validate_cases(cases, passages) -> None:
    """Every expectation must be checkable and justified by the case's own synthetic passages."""
    seen = set()
    for c in cases:
        cid = c.get("id")
        def bad(msg):
            raise CaseError(f"{cid}: {msg}")
        if not cid or cid in seen:
            bad("missing or duplicate id")
        seen.add(cid)
        if not (c.get("question") or "").strip():
            bad("empty question")
        if not c.get("evidence"):
            bad("no evidence")
        for key in c["evidence"]:
            p = passages.get(key)
            if p is None:
                bad(f"unknown passage {key}")
            if not (p["manifest_id"].startswith("synthetic-") and p["text"].startswith("Synthetic")):
                bad(f"passage {key} is not marked synthetic")
        ids = {f"E{n}" for n in range(1, len(c["evidence"]) + 1)}
        e = c["expected"]
        if not e["outcomes"] or set(e["outcomes"]) - set(OUTCOMES):
            bad("expected outcomes must be a non-empty subset of " + ", ".join(OUTCOMES))
        cit = e["citations"]
        req, perm, excl = set(cit["required"]), set(cit["permitted"]), set(cit["excluded"])
        if not (req <= perm <= ids) or not excl <= ids or perm & excl:
            bad("citations need required <= permitted <= retrieved IDs, excluded within retrieved and disjoint")
        if set(e["outcomes"]) & set(CITING) and not req:
            bad("a citing outcome needs at least one required citation")
        for ph in e["required_phrases"]:
            if ph["source"] not in perm:
                bad(f"phrase source {ph['source']} is not a permitted citation")
            text = passages[c["evidence"][int(ph["source"][1:]) - 1]]["text"]
            if _norm(ph["text"]) not in _norm(text):
                bad(f"phrase {ph['text']!r} does not appear in {ph['source']}")
            if ph.get("kind") not in PHRASE_KINDS:
                bad(f"phrase {ph['text']!r} needs kind 'condition' or 'content'")
            if ph["kind"] == "condition":
                # a condition is attached by the passage itself: an exception, proviso or restriction marker
                # must come before the phrase in its source passage
                before = _norm(text)[:_norm(text).index(_norm(ph["text"]))]
                if not _CONDITION_MARKER.search(before):
                    bad(f"phrase {ph['text']!r} is marked as a condition but no exception, proviso or restriction "
                        f"precedes it in {ph['source']}")
        if not (e.get("justification") or "").strip():
            bad("no justification")
        if e.get("retry") not in (None, True, False) or e.get("model_calls") not in (None, 0, 1, 2):
            bad("retry must be true/false/null and model_calls 0/1/2/null")
        mocks = c.get("sample_mock_responses", [])
        if len(mocks) > 2 or (e.get("model_calls") == 0 and mocks):
            bad("at most two mock responses, none for a case that expects no model call")
        for h in c.get("history", []):
            if set(h) != {"question", "answer"}:
                bad("history entries need exactly question and answer")


def model_cases(cases) -> list:
    return [c for c in cases if c["expected"].get("model_calls") != 0]


# ---------------------------------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------------------------------
_KEY_PATTERN = re.compile(r"gsk_[A-Za-z0-9]{8,}")
_ORG_PATTERN = re.compile(r"\borg_[A-Za-z0-9]{8,}")  # provider error text names the account's organisation


class Redactor:
    def __init__(self, *secrets):
        self.secrets = [s for s in secrets if s and len(s) >= 6]

    def __call__(self, value):
        if isinstance(value, str):
            for s in self.secrets:
                value = value.replace(s, "[REDACTED]")
            return _ORG_PATTERN.sub("[REDACTED_ORG]", _KEY_PATTERN.sub("[REDACTED]", value))
        if isinstance(value, dict):
            return {k: self(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self(v) for v in value]
        return value


# ---------------------------------------------------------------------------------------------------
# Budget and the evaluation-only Groq adapter
# ---------------------------------------------------------------------------------------------------
class EvalStop(Exception):
    """The call limit or token budget would be exceeded: the call was NOT made."""


class EvalCallFailed(Exception):
    """The provider call failed (timeout, HTTP error, connection error)."""


@dataclass
class Budget:
    max_calls: int
    max_tokens: int
    calls: int = 0
    tokens: int = 0

    def reserve(self, estimate: int) -> None:
        if self.calls >= self.max_calls:
            raise EvalStop(f"call limit reached ({self.max_calls})")
        if self.tokens + estimate > self.max_tokens:
            raise EvalStop(f"token budget would be exceeded ({self.tokens} used + {estimate} estimated > "
                           f"{self.max_tokens})")
        self.calls += 1

    def charge(self, tokens: int) -> None:
        self.tokens += tokens


def estimate_tokens(prompt: str, max_completion: int) -> int:
    """Conservative pre-call estimate: about 3 characters per prompt token, plus the whole output allowance."""
    return math.ceil(len(prompt) / 3) + max_completion


# The installed SDK (groq 0.37.1) defaults to this base URL and adds "/openai/v1/chat/completions" per request;
# without an explicit base_url it would honour a GROQ_BASE_URL environment variable instead.
GROQ_BASE_URL = "https://api.groq.com"
GROQ_HOST = "api.groq.com"


def make_groq_client(api_key: str, timeout: float, http_client=None):
    """The only place a real SDK client is built. max_retries=0: a failed call is never retried by the SDK. The
    endpoint is pinned, so no environment variable can send the key to another host."""
    import groq
    kwargs = {"api_key": api_key, "max_retries": 0, "timeout": timeout, "base_url": GROQ_BASE_URL}
    if http_client is not None:
        kwargs["http_client"] = http_client
    client = groq.Groq(**kwargs)
    if client.base_url.host != GROQ_HOST or client.base_url.scheme != "https" or client.max_retries != 0:
        raise RuntimeError("Groq client is not pinned to the expected endpoint without retries")
    return client


PROVIDER_REJECTED = "provider_rejected_output"
INFRA_PREFIXES = ("timeout", "connection_error", "auth_error", "rate_limited", "server_error", "api_error")


def _error_object(exc) -> dict:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        inner = body.get("error", body)
        return inner if isinstance(inner, dict) else {}
    return {}


def _classify(exc) -> str:
    """Model-output rejections are told apart from infrastructure failures by the response body, not the status
    code alone: only a 400 whose error object carries the SDK's `failed_generation` field (or the code
    "json_validate_failed") is provider-rejected model output. Every other 400 stays an API error."""
    try:
        import groq
    except ImportError:  # pragma: no cover
        groq = None
    if isinstance(exc, ReplayMissing):
        return NOT_RECORDED
    if groq is not None:
        if isinstance(exc, groq.APITimeoutError):
            return "timeout"
        if isinstance(exc, groq.BadRequestError):
            err = _error_object(exc)
            if err.get("failed_generation") is not None or err.get("code") == "json_validate_failed":
                return PROVIDER_REJECTED
            return "api_error_http_400"
        if isinstance(exc, (groq.AuthenticationError, groq.PermissionDeniedError)):
            return f"auth_error_http_{exc.status_code}"
        if isinstance(exc, groq.RateLimitError):
            return "rate_limited_http_429"
        if isinstance(exc, groq.InternalServerError):
            return f"server_error_http_{exc.status_code}"
        if isinstance(exc, groq.APIStatusError):
            return f"api_error_http_{exc.status_code}"
        if isinstance(exc, groq.APIConnectionError):
            return "connection_error"
    if isinstance(exc, TimeoutError):
        return "timeout"
    return f"api_error_{type(exc).__name__}"


class GroqAdapter:
    """Implements grounded_answer.AnswerGenerator: generate(prompt, contract) -> str. The prompt is sent verbatim
    as one user message and the response content is returned verbatim (no trimming, no repair)."""

    def __init__(self, client, budget: Budget, *, model=DEFAULT_MODEL, temperature=0.0, seed=7,
                 max_completion_tokens=DEFAULT_MAX_COMPLETION, json_mode=True, redact=None, clock=time.monotonic,
                 min_interval_s=0.0, sleep=time.sleep):
        self.client, self.budget, self.model = client, budget, model
        self.temperature, self.seed, self.max_completion_tokens = temperature, seed, max_completion_tokens
        self.json_mode, self.redact, self.clock = json_mode, redact or Redactor(), clock
        # pacing: at least min_interval_s between the starts of consecutive calls (stays under a provider's
        # tokens-per-minute limit); it delays calls, it never repeats one
        self.min_interval_s, self.sleep, self._last_start = min_interval_s, sleep, None
        self.calls, self.stop_reason, self.case_id = [], None, None

    def begin_case(self, case_id: str) -> None:
        self.case_id, self.calls = case_id, []
        if hasattr(self.client, "begin_case"):
            self.client.begin_case(case_id)

    def generate(self, prompt, contract):
        estimate = estimate_tokens(prompt, self.max_completion_tokens)
        try:
            self.budget.reserve(estimate)
        except EvalStop as exc:
            self.stop_reason = str(exc)
            raise
        record = {"n": len(self.calls) + 1, "prompt_chars": len(prompt),
                  "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()[:16], "estimated_tokens": estimate}
        self.calls.append(record)
        kwargs = {"model": self.model, "messages": [{"role": "user", "content": prompt}],
                  "temperature": self.temperature, "seed": self.seed,
                  "max_completion_tokens": self.max_completion_tokens}
        if self.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if self._last_start is not None and self.min_interval_s > 0:
            wait = self.min_interval_s - (self.clock() - self._last_start)
            if wait > 0:
                self.sleep(wait)
        start = self._last_start = self.clock()
        try:
            resp = self.client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 - every provider failure is recorded, never retried here
            status = _classify(exc)
            record.update(latency_s=round(self.clock() - start, 3), status=status,
                          error=self.redact(f"{type(exc).__name__}: {str(exc)[:300]}"))
            if status == PROVIDER_REJECTED:
                fg = _error_object(exc).get("failed_generation")
                record["failed_generation"] = self.redact(fg[:4000]) if isinstance(fg, str) else None
            self.budget.charge(estimate)  # unknown usage: count the reservation
            raise EvalCallFailed(status) from None
        record["latency_s"] = round(self.clock() - start, 3)
        choice = resp.choices[0]
        content = choice.message.content
        usage = getattr(resp, "usage", None)
        if usage is not None and getattr(usage, "total_tokens", None) is not None:
            record["usage"] = {"prompt_tokens": usage.prompt_tokens, "completion_tokens": usage.completion_tokens,
                               "total_tokens": usage.total_tokens}
            self.budget.charge(usage.total_tokens)
        else:
            record["usage"] = None
            self.budget.charge(estimate)
        record.update(status="truncated" if choice.finish_reason == "length" else "ok",
                      finish_reason=choice.finish_reason, model=getattr(resp, "model", self.model),
                      response=self.redact(content) if isinstance(content, str) else content)
        return content  # verbatim: validation sees exactly what the provider returned


class ScriptedClient:
    """Mock provider: replays each case's scripted responses. A string or dict is a response body; {"raise": X}
    raises X; {"body": B, "usage": {...}, "finish_reason": "length"} adds provider metadata. Used for the sample
    report and the unit tests; it never opens a connection."""

    def __init__(self, script: dict):
        self.script, self.queue, self.requests = script, [], []
        self.chat = type("Chat", (), {})()
        self.chat.completions = type("Completions", (), {})()
        self.chat.completions.create = self._create

    def begin_case(self, case_id):
        self.queue = list(self.script.get(case_id, []))

    def _create(self, **kwargs):
        from types import SimpleNamespace as NS
        self.requests.append(kwargs)
        if not self.queue:
            raise RuntimeError("mock script exhausted")
        item = self.queue.pop(0)
        if isinstance(item, dict) and "raise" in item:
            raise item["raise"]
        finish, usage = "stop", None
        if isinstance(item, dict) and "body" in item:  # {"body": ..., "usage": {...}, "finish_reason": ...}
            usage, finish, item = item.get("usage"), item.get("finish_reason", "stop"), item["body"]
        content = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
        return NS(choices=[NS(message=NS(content=content), finish_reason=finish)], model="mock",
                  usage=NS(**usage) if usage else None)


# ---------------------------------------------------------------------------------------------------
# Offline replay of recorded responses (no client, no network, no key)
# ---------------------------------------------------------------------------------------------------
RECORDING_SCHEMA = "kyr-recorded-responses/1"
NOT_RECORDED = "not_recorded"
REPLAY_LABEL = "OFFLINE REPLAY of recorded responses, not a fresh model evaluation"
_REDACTION_MARK = re.compile(r"\[REDACTED")
_SECRET_LIKE = re.compile(r"gsk_[A-Za-z0-9]{8,}|\borg_[A-Za-z0-9]{8,}")


class RecordingError(ValueError):
    pass


class ReplayMissing(Exception):
    """The case asked for a response that the recording does not hold. Nothing is substituted."""


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def freeze_recording(source_paths, base=BASE_DIR) -> dict:
    """Build a recording from real-run results files. Only responses of COMPLETED cases are taken, exactly as
    stored (the runner stored each response after its key/org redaction pass); a response is marked verbatim only
    if it is a string with no redaction marker, finished with finish_reason 'stop'. A case completed in two
    sources is an error, not a silent choice. Nothing is regenerated, repaired or invented."""
    cases, excluded, sources = {}, [], []
    for src in source_paths:
        path = Path(src)
        raw = path.read_bytes()
        doc = json.loads(raw)
        cfg = doc.get("config", {})
        if cfg.get("mode") != "real":
            raise RecordingError(f"{path.name}: not a real-model run (mode {cfg.get('mode')!r})")
        name = os.path.relpath(path, base)
        sources.append({"file": name, "sha256": hashlib.sha256(raw).hexdigest(), "run_at_utc": cfg.get("run_at_utc"),
                        "model": cfg.get("model"), "json_mode": cfg.get("json_mode"),
                        "temperature": cfg.get("temperature"), "seed": cfg.get("seed")})
        for r in doc.get("records", []):
            if r.get("status") != "completed" or not r.get("calls"):
                if r.get("calls"):
                    excluded.append({"case_id": r["id"], "source_file": name, "status": r.get("status"),
                                     "reason": "no usable model response in this source"})
                continue
            if r["id"] in cases:
                raise RecordingError(f"case {r['id']} is completed in more than one source")
            calls = []
            for c in r["calls"]:
                text = c.get("response")
                verbatim = isinstance(text, str) and not _REDACTION_MARK.search(text) and c.get("finish_reason") == "stop"
                if isinstance(text, str) and _SECRET_LIKE.search(text):
                    raise RecordingError(f"case {r['id']}: response contains a key- or org-like string")
                calls.append({"call_index": c.get("n"), "status": c.get("status"),
                              "finish_reason": c.get("finish_reason"), "verbatim": verbatim,
                              "response": text, "sha256": _sha256(text) if isinstance(text, str) else None})
            cases[r["id"]] = {"source_file": name, "run_at_utc": cfg.get("run_at_utc"), "calls": calls}
    models = {x["model"] for x in sources}
    return {"schema": RECORDING_SCHEMA, "model": models.pop() if len(models) == 1 else sorted(models),
            "note": "Responses copied from the real-run results files listed in sources, as the runner stored them "
                    "(after its key/org redaction pass; no redaction marker is present in any response marked "
                    "verbatim). Not regenerated, edited or repaired.",
            "sources": sources, "excluded": excluded, "cases": dict(sorted(cases.items()))}


def load_recording(path) -> tuple[dict, dict]:
    """(recording, {case_id: [response, ...]}) after checking the schema and EVERY response hash. Any malformed
    entry, non-verbatim response or hash mismatch refuses the whole recording."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RecordingError(f"cannot read recording: {type(exc).__name__}") from None
    if not isinstance(doc, dict) or doc.get("schema") != RECORDING_SCHEMA or not isinstance(doc.get("cases"), dict):
        raise RecordingError("not a recording (schema mismatch)")
    responses = {}
    for cid, entry in doc["cases"].items():
        calls = entry.get("calls") if isinstance(entry, dict) else None
        if not isinstance(calls, list) or not calls:
            raise RecordingError(f"{cid}: no calls")
        out = []
        for c in calls:
            text, digest = c.get("response"), c.get("sha256")
            if not isinstance(text, str) or not isinstance(digest, str):
                raise RecordingError(f"{cid}: call {c.get('call_index')} has no recorded response")
            if c.get("verbatim") is not True:
                raise RecordingError(f"{cid}: call {c.get('call_index')} is not marked verbatim")
            if _sha256(text) != digest:
                raise RecordingError(f"{cid}: call {c.get('call_index')} response does not match its sha256")
            out.append(text)
        responses[cid] = out
    return doc, responses


class ReplayClient(ScriptedClient):
    """Returns each case's recorded responses in order; a call with nothing recorded raises ReplayMissing."""

    def _create(self, **kwargs):
        if not self.queue:
            self.requests.append(kwargs)
            raise ReplayMissing("no recorded response for this call")
        return super()._create(**kwargs)


# Source files on the path a replayed response takes (runner, server handler, validator, meaning checks, the
# pipeline loader). Their content hashes identify the validator exactly, committed or not.
VALIDATOR_FILES = ("backend/real_groq_eval.py", "backend/answer_quality_eval.py", "backend/server.py",
                   "backend/grounded_answer.py", "backend/meaning_checks.py")


def validator_version() -> dict:
    """Read-only git calls. 'commit' is the repository HEAD; 'uncommitted_changes_anywhere' is ANY change in the
    working tree (untracked files and this report included), not a statement about the validator. The validator
    itself is identified by each source file's sha256 and its state against HEAD (committed, modified, untracked)."""
    import subprocess

    def git(*args):
        return subprocess.run(["git", "-C", str(BASE_DIR), *args], capture_output=True, text=True, timeout=10,
                              check=True).stdout
    files = {}
    for rel in VALIDATOR_FILES:
        path = BASE_DIR / rel
        files[rel] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None}
    try:
        commit = git("rev-parse", "HEAD").strip()
        anywhere = bool(git("status", "--porcelain").strip())
        for rel in VALIDATOR_FILES:
            st = git("status", "--porcelain", "--", rel)[:2]
            files[rel]["state"] = "committed" if not st.strip() else "untracked" if st == "??" else "modified"
    except (OSError, subprocess.SubprocessError):
        commit, anywhere = "unknown", "unknown"
        for rel in VALIDATOR_FILES:
            files[rel]["state"] = "unknown"
    return {"commit": commit, "uncommitted_changes_anywhere": anywhere, "validator_files": files}


def sample_client(cases) -> ScriptedClient:
    return ScriptedClient({c["id"]: c.get("sample_mock_responses", []) for c in cases})


# ---------------------------------------------------------------------------------------------------
# Running one case through the real /chat grounded path
# ---------------------------------------------------------------------------------------------------
def _validation_summary(r) -> dict:
    return {"accepted": r.ok, "errors": list(r.errors),
            "checks": [{"layer": c["layer"], "check": c["check"]} for c in r.checks]}


def is_infrastructure_failure(call_status) -> bool:
    return bool(call_status) and call_status.startswith(INFRA_PREFIXES)


def retry_eligibility(first, uncited_checks) -> str:
    if first is None:
        return "no first validation (no model response)"
    if first.ok:
        return "not eligible: first response accepted"
    other = sorted({c["check"] for c in first.checks} - set(uncited_checks))
    if other:
        return f"not eligible: rejected for {', '.join(other)} (retry is only for uncited-evidence findings)"
    return "eligible: the only findings were " + ", ".join(sorted({c["check"] for c in first.checks}))


def run_case(server, case, passages, adapter: GroqAdapter, redact=None) -> dict:
    redact = redact or Redactor()
    ga = server.grounded_answer
    docs = aq.fixture_docs(case, passages)
    validations, notes, results = [], [], []
    real_validate, real_note, real_answer = ga.validate, ga.conflict_retry_note, ga.answer

    def validate_spy(*a, **k):
        r = real_validate(*a, **k)
        validations.append(r)
        return r

    def note_spy(r):
        n = real_note(r)
        notes.append(n)
        return n

    def answer_spy(*a, **k):
        r = real_answer(*a, **k)
        results.append(r)
        return r

    adapter.begin_case(case["id"])
    sid = f"real-model-eval-{case['id']}"
    with contextlib.ExitStack() as stack:
        for target, name, value in (
                (server, "grounded_gate_errors", lambda: []), (server, "retrieve", lambda q: list(docs)),
                (server, "ANSWER_GENERATOR", adapter), (server, "log_lock", lambda *a, **k: None),
                (server, "ANSWER_MODE", "grounded"), (server, "index_ready", lambda: True),
                (server, "ensure_approval_current", lambda: None), (ga, "validate", validate_spy),
                (ga, "conflict_retry_note", note_spy), (ga, "answer", answer_spy)):
            stack.enter_context(mock.patch.object(target, name, value))
        stack.enter_context(mock.patch.dict(server.SOURCES, {aq.FIXTURE_SHA: ("Synthetic fixture document", "Rules")}))
        server.sessions[sid] = {"history": [dict(h) for h in case.get("history", [])]}
        try:
            response = server.chat(server.ChatRequest(message=case["question"], session_id=sid))
        finally:
            server.sessions.pop(sid, None)
    result = results[0] if results else None
    calls = list(adapter.calls)
    statuses = [c.get("status") for c in calls]
    stopped = adapter.stop_reason is not None and result is not None and \
        any("generator error: EvalStop" in e for e in result.errors)
    if stopped:
        status = "not_run" if not calls else "incomplete"
    elif NOT_RECORDED in statuses:
        status = NOT_RECORDED           # replay: the recording holds no response for a call this case made
    elif any(is_infrastructure_failure(x) for x in statuses):
        status = "api_failed"           # infrastructure: timeout, network, auth, rate limit, server, other API error
    elif PROVIDER_REJECTED in statuses:
        status = PROVIDER_REJECTED      # the model's output was refused by the provider (e.g. invalid JSON)
    elif "truncated" in statuses:
        status = "truncated"
    else:
        status = "completed"
    outcome = result.kind if result is not None and result.kind == "rejected" else response.kind
    evidence = []
    keys_by_provision = {passages[k]["provision_id"]: k for k in case["evidence"]}
    if result is not None:
        for e in result.contract.evidence:
            evidence.append({"id": e.evidence_id, "passage": keys_by_provision.get(e.provision_id),
                             "provision": e.provision_id, "text": e.passage})
    else:
        evidence = [{"id": None, "passage": k, "provision": passages[k]["provision_id"], "text": passages[k]["text"]}
                    for k in case["evidence"]]
    uncited_checks = ga.UNCITED_CHECKS
    first = validations[0] if validations else None
    record = {
        "id": case["id"], "purpose": case["purpose"], "question": case["question"],
        "history_turns": len(case.get("history", [])), "status": status,
        "stop_reason": adapter.stop_reason if stopped else None,
        "retrieved": evidence, "model_calls": len(calls), "calls": calls,
        "first_response": calls[0].get("response") if calls else None,
        "first_validation": _validation_summary(first) if first else None,
        "retry_triggered": bool(notes and notes[0]), "retry_eligibility": retry_eligibility(first, uncited_checks),
        "retry_instruction": redact(notes[0]) if notes and notes[0] else None,
        "second_response": calls[1].get("response") if len(calls) > 1 else None,
        "final_validation": _validation_summary(validations[-1]) if validations else None,
        "final_claims": [c.text for c in validations[-1].answer.claims]
        if validations and validations[-1].ok and validations[-1].answer is not None else [],
        "pipeline_errors": redact(list(result.errors)) if result is not None else [],
        "outcome": outcome, "server_kind": response.kind, "displayed": redact(response.response),
        "final_citations": [e.evidence_id for e in result.cited] if result is not None else [],
        "expected": case["expected"],
    }
    record.update(score(record, case))
    return record


# ---------------------------------------------------------------------------------------------------
# Scoring (citations, condition words, expected behaviour). Legal meaning is NOT scored automatically.
# ---------------------------------------------------------------------------------------------------
def score(record, case) -> dict:
    e = case["expected"]
    out = {"citation": None, "conditions": None, "content": None, "legal_meaning": "not assessed (synthetic passages; manual review "
                                                                "required for any real-text claim)",
           "manual_review": "pending", "expected_achieved": None, "expected_reasons": []}
    if record["status"] in ("truncated", PROVIDER_REJECTED):
        # a model response that never reached the validator: the expected behaviour was not achieved
        out["expected_achieved"] = False
        out["expected_reasons"] = [f"not achieved: {record['status']} (no validated model response)"]
        return out
    if record["status"] != "completed":
        out["expected_reasons"] = [f"not scored: case {record['status']}"]
        return out
    reasons = []
    if record["outcome"] not in e["outcomes"]:
        reasons.append(f"outcome {record['outcome']} not in expected {e['outcomes']}")
    if e.get("model_calls") is not None and record["model_calls"] != e["model_calls"]:
        reasons.append(f"{record['model_calls']} model calls, expected {e['model_calls']}")
    if e.get("retry") is not None and record["retry_triggered"] != e["retry"]:
        reasons.append(f"retry {'triggered' if record['retry_triggered'] else 'not triggered'}, expected "
                       f"{'a retry' if e['retry'] else 'none'}")
    if record["outcome"] in CITING:
        cited = set(record["final_citations"])
        c = e["citations"]
        missing = sorted(set(c["required"]) - cited, key=lambda i: int(i[1:]))
        outside = sorted(cited - set(c["permitted"]), key=lambda i: int(i[1:]))
        excluded = sorted(cited & set(c["excluded"]), key=lambda i: int(i[1:]))
        out["citation"] = {"missing_required": missing, "outside_permitted": outside, "excluded_cited": excluded,
                           "correct": not (missing or outside or excluded)}
        if not out["citation"]["correct"]:
            reasons.append(f"citations: missing {missing or '-'}, outside permitted {outside or '-'}")
        text = _norm(" ".join(record.get("final_claims") or []))  # claim text only: not labels or prefixes
        for kind, key, label in (("condition", "conditions", "condition/exception words"),
                                 ("content", "content", "content words of a required position")):
            wanted = [p["text"] for p in e["required_phrases"] if p["kind"] == kind]
            absent = [w for w in wanted if _norm(w) not in text]
            out[key] = {"required": wanted, "missing": absent, "preserved": not absent} if wanted else None
            if absent:
                reasons.append(f"{label} missing: {absent}")
    out["expected_achieved"] = not reasons
    out["expected_reasons"] = reasons
    return out


# ---------------------------------------------------------------------------------------------------
# Running all cases, metrics, report
# ---------------------------------------------------------------------------------------------------
def run_all(cases, passages, adapter, redact=None, server=None) -> list:
    if server is None:
        server, _calls = aq.load_pipeline()
    records, halted, consecutive = [], None, 0
    for case in cases:
        if halted:
            records.append({"id": case["id"], "purpose": case["purpose"], "question": case["question"],
                            "status": "not_run", "stop_reason": halted, "model_calls": 0, "calls": [],
                            "expected": case["expected"], "expected_achieved": None,
                            "expected_reasons": [f"not run: {halted}"]})
            continue
        rec = run_case(server, case, passages, adapter, redact)
        records.append(rec)
        if rec["status"] in ("not_run", "incomplete"):
            halted = rec["stop_reason"]
        consecutive = consecutive + 1 if rec["status"] == "api_failed" else 0  # infrastructure failures only
        if consecutive >= MAX_CONSECUTIVE_FAILURES:
            halted = f"{MAX_CONSECUTIVE_FAILURES} consecutive infrastructure failures"
    return records


def _rate(n, d):
    return {"n": n, "of": d, "rate": round(n / d, 3) if d else None}


def summarise(records, config) -> dict:
    """A: conditional model-case rates (among model cases with a scorable, i.e. validated, response).
    B: no-model guard checks. C: overall achievement over ALL model cases, with every case accounted for."""
    model = [r for r in records if r["expected"].get("model_calls") != 0]
    guards = [r for r in records if r["expected"].get("model_calls") == 0]
    status = collections.Counter(r["status"] for r in model)
    scorable = [r for r in model if r["status"] == "completed"]
    judged = [r for r in scorable if r.get("first_validation") is not None]
    retried = [r for r in judged if r["retry_triggered"]]
    final_ok = [r for r in judged if r["final_validation"]["accepted"]]
    cit = [r for r in scorable if r.get("citation")]
    cond = [r for r in scorable if r.get("conditions")]
    cont = [r for r in scorable if r.get("content")]
    achieved = [r for r in model if r.get("expected_achieved") is True]
    calls = [c for r in records for c in r.get("calls", [])]
    lat = [c["latency_s"] for c in calls if "latency_s" in c]
    usage = [c["usage"] for c in calls if c.get("usage")]
    tokens = {k: sum(u[k] for u in usage) for k in ("prompt_tokens", "completion_tokens", "total_tokens")}
    cost = None
    if usage and config.get("price_in_per_mtok") is not None and config.get("price_out_per_mtok") is not None:
        cost = round(tokens["prompt_tokens"] / 1e6 * config["price_in_per_mtok"] +
                     tokens["completion_tokens"] / 1e6 * config["price_out_per_mtok"], 6)
    return {
        "cases_total": len(records), "model_cases": len(model), "guard_cases": len(guards),
        "model_status": {k: status.get(k, 0) for k in ("completed", PROVIDER_REJECTED, "truncated", "api_failed",
                                                       "incomplete", "not_run", NOT_RECORDED)},
        "conditional": {
            "scorable_model_cases": len(scorable),
            "expected_agreement": _rate(len([r for r in scorable if r["expected_achieved"]]), len(scorable)),
            "first_pass_acceptance": _rate(sum(r["first_validation"]["accepted"] for r in judged), len(judged)),
            "final_acceptance": _rate(len(final_ok), len(judged)),
            "final_accepted_substantive": len([r for r in final_ok if r["outcome"] in CITING]),
            "final_accepted_refusal": len([r for r in final_ok if r["outcome"] not in CITING]),
            "retry_frequency": _rate(len(retried), len(judged)),
            "retry_success": _rate(sum(r["final_validation"]["accepted"] for r in retried), len(retried)),
            "citation_correctness": _rate(sum(r["citation"]["correct"] for r in cit), len(cit)),
            "condition_words_preserved": _rate(sum(r["conditions"]["preserved"] for r in cond), len(cond)),
            "content_words_preserved": _rate(sum(r["content"]["preserved"] for r in cont), len(cont)),
        },
        "overall": {
            "achievement": _rate(len(achieved), len(model)),
            "not_achieved": {"expectation_failed": len([r for r in scorable if r["expected_achieved"] is False]),
                             "truncated": status.get("truncated", 0),
                             PROVIDER_REJECTED: status.get(PROVIDER_REJECTED, 0)},
            "not_scorable": {"infrastructure_failure": status.get("api_failed", 0),
                             NOT_RECORDED: status.get(NOT_RECORDED, 0),
                             "incomplete": status.get("incomplete", 0), "not_run": status.get("not_run", 0)},
        },
        "guards": {"checks": len(guards), "passing": len([r for r in guards if r.get("expected_achieved")]),
                   "unexpected_model_calls": sum(r.get("model_calls", 0) for r in guards),
                   "not_run": len([r for r in guards if r["status"] == "not_run"])},
        "model_calls": len(calls),
        "calls_by_status": dict(collections.Counter(c.get("status") or "unknown" for c in calls)),
        "latency_s": {"mean": round(statistics.mean(lat), 3), "median": round(statistics.median(lat), 3),
                      "max": round(max(lat), 3)} if lat else None,
        "tokens": tokens if usage else None, "calls_with_usage": len(usage), "estimated_cost_usd": cost,
    }


def _fmt_rate(r):
    return "n/a (0 cases)" if r["rate"] is None else f"{r['n']}/{r['of']} ({r['rate']:.0%})"


def _code(text, limit=3000):
    if text is None:
        return "_none_"
    s = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
    try:
        s = json.dumps(json.loads(s), indent=1, ensure_ascii=False)
    except (ValueError, TypeError):
        pass
    if len(s) > limit:
        s = s[:limit] + f"\n... [{len(s) - limit} more characters in the JSON results]"
    return "```\n" + s.replace("```", "'''") + "\n```"


def markdown(summary, records, config) -> str:
    mock_mode = config["mode"] == "mock"
    replay = config["mode"] == "replay"
    title = {"mock": "SAMPLE (mocked responses)", "replay": "OFFLINE REPLAY"}.get(config["mode"], "Real-model")
    L = [f"# {title} evaluation: grounded answers", ""]
    if replay:
        L += [f"> **{REPLAY_LABEL}.** No model calls were made: every response below was recorded during the live "
              f"run(s) listed here and is re-checked by the CURRENT validator. Latency and token figures do not "
              f"apply.", "", "| Provenance | Value |", "|---|---|",
              f"| recording | {config['recording_file']} (sha256 {config['recording_sha256'][:16]}) |",
              f"| recorded model | {config['recording_model']} |"]
        L += [f"| source | {x['file']} (run {x['run_at_utc']} UTC, sha256 {x['sha256'][:16]}) |"
              for x in config["recording_sources"]]
        v = config["validator"]
        L += [f"| repository HEAD commit | {v['commit']} |",
              f"| uncommitted changes anywhere in the repository (untracked files and this report included) | "
              f"{v['uncommitted_changes_anywhere']} |"]
        L += [f"| validator file `{rel}` | {x.get('state')} vs HEAD, sha256 {str(x.get('sha256'))[:16]} |"
              for rel, x in v["validator_files"].items()]
        L += [
              f"| response hashes verified | {config['responses_verified']} of {config['responses_verified']} |",
              f"| replayed at (UTC) | {config['run_at_utc']} |", ""]
        if config.get("recording_excluded"):
            L += ["Excluded from the recording (no usable response in that source): " + ", ".join(
                f"{x['case_id']} in {x['source_file']} ({x['status']})" for x in config["recording_excluded"]), ""]
        L += ["| Case | Recorded response sha256 (verified before use) |", "|---|---|"]
        L += [f"| {cid} | {', '.join(hs)} |" for cid, hs in sorted(config.get("recording_response_sha256", {}).items())]
        L += [""]
    if mock_mode:
        L += ["> **Sample report generated from hand-written mock responses. No model was called.** It shows the "
              "report format and exercises the runner; its numbers say nothing about any model.", ""]
    L += [f"> {DISCLAIMER}", "", "## 1. Configuration", "", "| Setting | Value |", "|---|---|"]
    for k in ("mode", "model", "temperature", "seed", "json_mode", "max_completion_tokens", "max_calls",
              "max_total_tokens", "timeout_s", "min_interval_s", "price_in_per_mtok", "price_out_per_mtok", "cases_file", "run_at_utc"):
        if k in config:
            L.append(f"| {k} | {config.get(k)} |")
    L += ["", f"JSON mode reason: {JSON_MODE_REASON}.", "",
          "Execution path: server.chat -> grounded_answer_question (follow-up and penalty guards) -> fixed synthetic "
          "retrieval -> grounded_answer.answer (evidence contract, prompt, generator call, validate, at most one "
          "conflict retry, validate) -> backend rendering and citations. Approval gate forced open for the run only; "
          "no approval record is read or written.", "",
          "## 2. Cases", "",
          f"{summary['model_cases']} model cases and {summary['guard_cases']} no-model guard checks.", "",
          "| Model-case status | Count |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in summary["model_status"].items()]
    c, o, g = summary["conditional"], summary["overall"], summary["guards"]
    L += ["", "completed = the model response reached the validator. provider_rejected_output = the provider refused "
          "the model's output (e.g. invalid JSON in JSON mode). truncated = output cut at the token limit. "
          "api_failed = infrastructure failure (timeout, network, authentication, rate limit, server). "
          "incomplete / not_run = stopped by the call limit, token budget or repeated infrastructure failures.", "",
          f"## 3. Model-case results among cases with a scorable response ({c['scorable_model_cases']} of "
          f"{summary['model_cases']})", "", "| Measure | Result |", "|---|---|",
          f"| Expected-outcome agreement | {_fmt_rate(c['expected_agreement'])} |",
          f"| First-pass validator acceptance | {_fmt_rate(c['first_pass_acceptance'])} |",
          f"| Final validator acceptance | {_fmt_rate(c['final_acceptance'])}: {c['final_accepted_substantive']} "
          f"substantive (answer or conflict), {c['final_accepted_refusal']} accepted refusal or clarification |",
          f"| Retry frequency | {_fmt_rate(c['retry_frequency'])} |",
          f"| Retry success (accepted after retry) | {_fmt_rate(c['retry_success'])} |",
          f"| Citation correctness (answers and conflicts) | {_fmt_rate(c['citation_correctness'])} |",
          f"| Condition/exception words preserved in claim text (lexical; cases with a condition) | "
          f"{_fmt_rate(c['condition_words_preserved'])} |",
          f"| Content words of required positions in claim text (lexical; cases with such words) | "
          f"{_fmt_rate(c['content_words_preserved'])} |", "",
          f"## 4. Overall model-case achievement (all {summary['model_cases']} model cases)", "",
          f"**Achieved: {_fmt_rate(o['achievement'])}**", "", "| Not achieved | Count |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in o["not_achieved"].items()]
    L += ["", "| Not scorable (counted in the denominator above, shown separately) | Count |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in o["not_scorable"].items()]
    L += ["", "## 5. No-model guard checks", "", "| | Result |", "|---|---|",
          f"| Checks | {g['checks']} |", f"| Passing | {g['passing']} |",
          f"| Unexpected model calls | {g['unexpected_model_calls']} |", f"| Not run | {g['not_run']} |", "",
          "## 6. Calls, latency, tokens, cost", "", "| Measure | Result |", "|---|---|",
          (f"| Recorded responses replayed by status (no model calls) | {summary['model_calls']} "
           f"{summary['calls_by_status']} |" if replay else
           f"| Model calls by status | {summary['model_calls']} {summary['calls_by_status']} |"),
          ("| Latency per call (s) | not applicable (offline replay) |" if replay else
           f"| Latency per call (s) | {summary['latency_s'] or 'n/a'}{' (mock: not meaningful)' if mock_mode else ''} |"),
          f"| Tokens | {summary['tokens'] or 'not reported by provider'} |",
          f"| Estimated cost (USD) | {summary['estimated_cost_usd'] if summary['estimated_cost_usd'] is not None else 'not estimated (no prices given or no usage reported)'} |",
          "", "Validator acceptance, citation correctness, lexical condition-word and content-word checks and "
          "expected-behaviour "
          "agreement are measured automatically. Legal meaning preservation is NOT measured: it is listed per case "
          "as pending manual review.", "",
          "## 7. Case by case", "",
          "| Case | Purpose | Status | Calls | Retry | First | Final | Outcome | Citations | Expected |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for r in records:
        fv, lv = r.get("first_validation"), r.get("final_validation")
        cit = r.get("citation")
        L.append(f"| {r['id']} | {r['purpose']} | {r['status']} | {r['model_calls']} | "
                 f"{'yes' if r.get('retry_triggered') else 'no'} | "
                 f"{'-' if not fv else ('accepted' if fv['accepted'] else 'rejected')} | "
                 f"{'-' if not lv else ('accepted' if lv['accepted'] else 'rejected')} | {r.get('outcome', '-')} | "
                 f"{'-' if not cit else ('ok' if cit['correct'] else 'wrong')} | "
                 f"{'-' if r.get('expected_achieved') is None else ('yes' if r['expected_achieved'] else 'NO')} |")
    misses = [r for r in records if r.get("expected_achieved") is not True]
    L += ["", "### Failures and unscored cases", ""]
    def why(r):
        reasons = "; ".join(r.get("expected_reasons") or []) or "-"
        final = r.get("final_validation") or {}
        if final and not final.get("accepted") and final.get("errors"):
            reasons += ". Validator: " + "; ".join(final["errors"])  # the rejection reasons, as the validator gave them
        return reasons
    L += [f"- **{r['id']}** ({r['status']}): {why(r)}" for r in misses] or ["None."]
    L += ["", "### Full records", ""]
    for r in records:
        if r["status"] == "not_run":
            L += [f"#### {r['id']}: not run ({r.get('stop_reason')})", ""]
            continue
        e = r["expected"]
        L += [f"<details><summary><b>{r['id']}</b> - {r['purpose']} - {r['status']} - outcome {r['outcome']}"
              f"</summary>", "", f"**Question:** {r['question']}  ", f"**History turns:** {r['history_turns']}", "",
              "**Retrieved (synthetic):**", ""]
        L += [f"- {x['id'] or '-'} `{x['passage']}` ({x['provision']}): {x['text']}" for x in r["retrieved"]]
        L += ["", f"**Expected:** outcomes {e['outcomes']}; required {e['citations']['required']}, permitted "
              f"{e['citations']['permitted']}, excluded {e['citations']['excluded']}; condition words "
              f"{[p['text'] for p in e['required_phrases'] if p['kind'] == 'condition']}; content words "
              f"{[p['text'] for p in e['required_phrases'] if p['kind'] == 'content']}; retry {e.get('retry')}; "
              f"model calls "
              f"{e.get('model_calls')}  ", f"**Why:** {e['justification']}", ""]
        for c in r["calls"]:
            L.append(f"- call {c['n']}: status {c.get('status')}, latency {c.get('latency_s')} s, usage "
                     f"{c.get('usage')}, finish {c.get('finish_reason')}" + (f", error {c['error']}"
                                                                            if c.get("error") else ""))
            if c.get("failed_generation"):
                L += ["", "  Provider-rejected generation (redacted):", _code(c["failed_generation"], 1500)]
        L += ["", "**First response:**", _code(r["first_response"]),
              f"**First validation:** {r['first_validation']}", "",
              f"**Retry:** {'triggered' if r['retry_triggered'] else 'not triggered'} - {r['retry_eligibility']}", ""]
        if r["retry_instruction"]:
            L += ["**Retry instruction (appended to the same prompt):**", _code(r["retry_instruction"])]
        if r["second_response"] is not None:
            L += ["**Second response:**", _code(r["second_response"])]
        L += [f"**Final validation:** {r['final_validation']}", "",
              f"**Pipeline errors:** {r['pipeline_errors'] or 'none'}", "",
              "**Displayed answer:**", _code(r["displayed"]),
              f"**Final claims:** {r['final_claims']}  ", f"**Final citations:** {r['final_citations']}  ", f"**Citation check:** {r['citation']}  ",
              f"**Condition words:** {r['conditions']}  ", f"**Content words:** {r['content']}  ", f"**Legal meaning:** {r['legal_meaning']}  ",
              f"**Manual review:** {r['manual_review']}  ",
              f"**Expected behaviour achieved:** {r['expected_achieved']} {r['expected_reasons'] or ''}", "",
              "</details>", ""]
    L += ["## 8. Limitations and recommendations", "",
          "- Synthetic passages only: no result here speaks to real Telangana provisions or legal correctness.",
          "- Expected behaviour is engineering expectation derived from the synthetic text, not a reviewed legal "
          "reference answer; no human-reviewed cases exist yet (all retrieval-review rows are pending).",
          "- Condition-word and content-word checks are lexical (exact words); a faithful paraphrase fails them and "
          "an answer can "
          "contain the words with the meaning changed. Manual review is required before drawing conclusions.",
          "- Retrieval is fixed per case, so retrieval quality is not measured.",
          "- One run at temperature 0 with a fixed seed is not a reliability estimate; provider output can still "
          "vary between runs.",
          "- The Groq adapter exists only in this runner; the server's grounded mode still uses DisabledGenerator.",
          "- Recommendation: before any real-text run, have reviewers fill the human-review sheet and turn reviewed "
          "rows into cases with their own required and permitted citations.", ""]
    return "\n".join(L)


# ---------------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------------
class OptInError(RuntimeError):
    pass


@contextlib.contextmanager
def redacted_logging(redact):
    """Every log record created during the run has secrets removed from its formatted message."""
    previous = logging.getLogRecordFactory()

    def factory(*a, **k):
        rec = previous(*a, **k)
        rec.msg, rec.args = redact(rec.getMessage()), ()
        return rec
    logging.setLogRecordFactory(factory)
    try:
        yield
    finally:
        logging.setLogRecordFactory(previous)


def check_opt_in(real: bool, environ) -> str:
    """Returns the API key when every opt-in condition holds; raises otherwise. Never reads .env."""
    if not real:
        raise OptInError("--real not given")
    if environ.get(OPT_IN_ENV) != "1":
        raise OptInError(f"{OPT_IN_ENV}=1 is not set in the process environment")
    key = (environ.get(KEY_ENV) or "").strip()
    if not key or "placeholder" in key.lower():
        raise OptInError(f"{KEY_ENV} is not set in the process environment")
    return key


def parse_args(argv):
    p = argparse.ArgumentParser(description="Controlled grounded-answer evaluation (mock by default; real Groq "
                                            f"calls only with --real and {OPT_IN_ENV}=1).")
    p.add_argument("--real", action="store_true", help="make real Groq calls (also needs the env opt-in)")
    p.add_argument("--replay", default=None, metavar="FILE",
                   help="offline replay of a recording (eval/real-model/recorded/*.json) through the current "
                        "validator; no client, no network, no key")
    p.add_argument("--cases", default=str(CASES_FILE))
    p.add_argument("--only", default="", help="comma-separated case IDs")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS)
    p.add_argument("--max-total-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    p.add_argument("--max-completion-tokens", type=int, default=DEFAULT_MAX_COMPLETION)
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    p.add_argument("--min-interval-s", type=float, default=0.0,
                   help="minimum seconds between the starts of consecutive model calls (rate-limit pacing)")
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--no-json-mode", action="store_true")
    p.add_argument("--price-in-per-mtok", type=float, default=None, help="USD per million input tokens")
    p.add_argument("--price-out-per-mtok", type=float, default=None, help="USD per million output tokens")
    p.add_argument("--markdown", default=None)
    p.add_argument("--json", default=None)
    a = p.parse_args(argv)
    if not 1 <= a.max_calls <= HARD_MAX_CALLS:
        p.error(f"--max-calls must be between 1 and {HARD_MAX_CALLS}")
    if a.max_total_tokens < 1 or a.max_completion_tokens < 1:
        p.error("token limits must be positive")
    return a


def main(argv=None, environ=None, client_factory=make_groq_client, server=None) -> int:
    a = parse_args(argv)
    if a.replay and a.real:
        print("Refusing: --replay and --real cannot be combined. Nothing was called.")
        return 2
    environ = os.environ if environ is None else environ
    cases, passages = load_cases(a.cases)
    if a.only:
        wanted = {x.strip() for x in a.only.split(",")}
        cases = [c for c in cases if c["id"] in wanted]
    if a.replay:
        return _replay_main(a, cases, passages, server)
    key = None
    if a.real:
        try:
            key = check_opt_in(True, environ)
        except OptInError as exc:
            print(f"Refusing to make real model calls: {exc}. Nothing was called.")
            return 2
    redact = Redactor(key)
    config = {"mode": "real" if key else "mock", "model": a.model if key else f"mock ({a.model} not called)",
              "temperature": a.temperature, "seed": a.seed, "json_mode": not a.no_json_mode,
              "max_completion_tokens": a.max_completion_tokens, "max_calls": a.max_calls,
              "max_total_tokens": a.max_total_tokens, "timeout_s": a.timeout, "min_interval_s": a.min_interval_s, "price_in_per_mtok": a.price_in_per_mtok,
              "price_out_per_mtok": a.price_out_per_mtok, "cases_file": os.path.relpath(a.cases, BASE_DIR),
              "run_at_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")}
    client = client_factory(key, a.timeout) if key else sample_client(cases)
    budget = Budget(a.max_calls, a.max_total_tokens)
    adapter = GroqAdapter(client, budget, model=a.model, temperature=a.temperature, seed=a.seed,
                          max_completion_tokens=a.max_completion_tokens, json_mode=not a.no_json_mode, redact=redact,
                          min_interval_s=a.min_interval_s)
    with redacted_logging(redact):  # server log lines can quote model text
        records = run_all(cases, passages, adapter, redact, server=server)
    summary = summarise(records, config)
    md = redact(markdown(summary, records, config))
    out_md = a.markdown or (None if key else str(SAMPLE_REPORT))  # the sample path is only for mock runs
    if out_md:
        Path(out_md).write_text(md + "\n", encoding="utf-8")
    if a.json:
        Path(a.json).write_text(redact(json.dumps({"config": config, "summary": summary, "records": records},
                                                  indent=1, ensure_ascii=False, default=str)) + "\n",
                                encoding="utf-8")
    st = summary["model_status"]
    print(redact(f"{config['mode']} run: model cases achieved {_fmt_rate(summary['overall']['achievement'])}; "
                 f"status {st}; guards {summary['guards']['passing']}/{summary['guards']['checks']}; "
                 f"{summary['model_calls']} model calls"))
    return 0 if st["api_failed"] == 0 and st["incomplete"] == 0 and st["not_run"] == 0 else 1


def _replay_main(a, cases, passages, server) -> int:
    """--replay: the recorded responses through the same run_all / run_case / validator path as a real run, with
    ReplayClient in place of the provider. Reads no environment variable and builds no SDK client."""
    try:
        recording, responses = load_recording(a.replay)
    except RecordingError as exc:
        print(f"Refusing to replay: {exc}. Nothing was run.")
        return 2
    path = Path(a.replay)
    config = {"mode": "replay", "model": f"recorded {recording.get('model')} (not called)",
              "cases_file": os.path.relpath(a.cases, BASE_DIR), "run_at_utc":
              datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M"),
              "recording_file": os.path.relpath(path.resolve(), BASE_DIR) if path.resolve().is_relative_to(BASE_DIR)
              else path.name, "recording_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
              "recording_model": recording.get("model"), "recording_sources": recording.get("sources", []),
              "recording_excluded": recording.get("excluded", []),
              "recording_response_sha256": {cid: [c["sha256"] for c in e["calls"]]
                                            for cid, e in recording["cases"].items()},
              "responses_verified": sum(len(v) for v in responses.values()), "validator": validator_version(),
              "label": REPLAY_LABEL}
    adapter = GroqAdapter(ReplayClient(responses), Budget(HARD_MAX_CALLS, 10 ** 12), model=str(recording.get("model")))
    records = run_all(cases, passages, adapter, server=server)
    summary = summarise(records, config)
    if a.markdown:
        Path(a.markdown).write_text(markdown(summary, records, config) + "\n", encoding="utf-8")
    if a.json:
        Path(a.json).write_text(json.dumps({"config": config, "summary": summary, "records": records}, indent=1,
                                           ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    st = summary["model_status"]
    print(f"{REPLAY_LABEL}: model cases achieved {_fmt_rate(summary['overall']['achievement'])}; status {st}; "
          f"guards {summary['guards']['passing']}/{summary['guards']['checks']}; "
          f"{config['responses_verified']} recorded responses verified; no model calls")
    return 0 if all(st[k] == 0 for k in ("api_failed", "incomplete", "not_run", NOT_RECORDED)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
