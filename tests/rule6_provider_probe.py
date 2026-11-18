"""Run by tests/test_rule6_provider_compat_real.py (and by hand for eval/latency/stage4g/) in its own process: the real
backend.server /chat on a throw-away COPY of a real Telangana index (TG_DB_DIR), real Ollama embeddings, real retrieval,
real context assembly and validator, and the REAL provider abstraction (ProviderOrchestrator, request builders,
response extraction, error classification, retries, validation fallback). Only the provider HTTP is mocked: every
provider "answers" with a deterministic body built from the evidence it was actually sent. NO live provider is called.
Prints one JSON document as its last stdout line.
"""
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
logging.disable(logging.INFO)

import real_backend_probe as probe  # noqa: E402
import requests  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import eligibility_status, grounded_answer, meaning_checks, providers  # noqa: E402

srv = probe.srv
Q = "What happens when a driving licence application is received?"
CUR = {}
_orig_generate = providers.ProviderSession.generate
_orig_validate = grounded_answer.validate
LAST_ERRORS = []


def _spy_generate(self, prompt, contract):
    CUR["contract"], CUR["session"] = contract, self
    return _orig_generate(self, prompt, contract)


def _spy_validate(raw, contract, **kw):
    result = _orig_validate(raw, contract, **kw)
    LAST_ERRORS.append(list(result.errors))
    return result


providers.ProviderSession.generate = _spy_generate
grounded_answer.validate = _spy_validate


class Resp:
    def __init__(self, status, body, headers=None):
        self.status_code, self._b, self.headers = status, body, headers or {}
        self.text = json.dumps(body)

    def json(self):
        return self._b


def provider_of(url):
    return "groq" if "api.groq.com" in url else "gemini" if "generativelanguage.googleapis.com" in url else "ollama"


def envelope(name, text, extra_parts=None):
    if name == "groq":
        return Resp(200, {"choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                                       "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}})
    if name == "gemini":
        parts = (extra_parts or []) + [{"text": text}]
        return Resp(200, {"candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": "STOP"}]})
    return Resp(200, {"model": "llama3.2", "message": {"role": "assistant", "content": text}, "done": True})


def status_sentence(contract):
    for e in contract.evidence:
        for s in meaning_checks.sentences(e.passage.partition("\n")[2] or e.passage):
            if eligibility_status.constructions(s):
                return e, s
    return None, None


def body_for(style, contract):
    e, s = status_sentence(contract)
    eid = e.evidence_id if e else "E1"

    def doc(text, kind="direct", ids=None):
        ids = ids or [eid]
        return {"answer": text, "evidence_sufficiency": "sufficient",
                "claims": [{"text": text, "kind": kind, "evidence_ids": ids}], "citations": ids,
                "refusal_reason": None, "clarification_question": None}
    refuse = {"answer": "", "evidence_sufficiency": "insufficient", "claims": [], "citations": [],
              "refusal_reason": "The passages do not state this.", "clarification_question": None}
    restated = ("The licensing authority may make enquiries to ascertain that the applicant is not disqualified or "
                "liable to be disqualified for holding a Licence.")
    if style == "verbatim":
        return json.dumps(doc(s))
    if style == "whitespace":
        return "\n  " + json.dumps(doc(s), indent=2) + "\n\n"
    if style == "fenced":
        return "```json\n" + json.dumps(doc(s)) + "\n```"
    if style == "prose":
        return "Here is the answer:\n" + json.dumps(doc(s))
    if style == "interp_restated":
        return json.dumps(doc(restated, "interpretation"))
    if style == "interp_contraction":
        return json.dumps(doc(restated.replace("is not", "isn’t"), "interpretation"))
    if style == "interp_nbsp":
        return json.dumps(doc(restated.replace("is not", "is not"), "interpretation"))
    if style == "interp_bold":
        return json.dumps(doc(restated.replace("is not", "is **not**"), "interpretation"))
    if style == "interp_noun":
        return json.dumps(doc("The licensing authority checks that the applicant does not fall under a disqualification.",
                              "interpretation"))
    if style == "penalty_beside":
        return json.dumps(doc(s + " A disqualified person shall be punished.", "interpretation"))
    if style == "refusal":
        return json.dumps(refuse)
    raise KeyError(style)


class Http:
    """script: {provider: [item,...]}; item = style name | Resp | exception. Last item repeats."""

    def __init__(self, script):
        self.script, self.calls, self.sent = {k: list(v) for k, v in script.items()}, [], []

    def __call__(self, url, headers=None, json=None, timeout=None):
        name = provider_of(url)
        self.calls.append(name)
        self.sent.append(__import__("json").dumps(json))
        items = self.script.get(name)
        if not items:
            raise AssertionError(f"unexpected call to {name}")
        item = items.pop(0) if len(items) > 1 else items[0]
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, str):
            extra = [{"text": "internal reasoning", "thought": True}] if name == "gemini" and item.endswith("+thought") else None
            return envelope(name, body_for(item.replace("+thought", ""), CUR["contract"]), extra)
        return item


def err(status, label):
    return Resp(status, {"error": {"code": status, "status": label, "message": label}})


def quota(name):
    if name == "groq":
        return Resp(429, {"error": {"message": "tokens per day (TPD) quota", "type": "tokens",
                                    "code": "rate_limit_exceeded"}}, {"retry-after": "600"})
    return Resp(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "quota",
                                "details": [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                                             "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}})


def run(client, sid, script, only=None):
    http = Http(script)
    s = providers.ProviderSettings(groq_api_key="mock-groq-key-0000", gemini_api_key="mock-gemini-key-0000",
                                   **({f"{n}_enabled": n == only for n in ("groq", "gemini", "ollama")} if only else {}))
    orch = providers.ProviderOrchestrator.from_settings(s, http=http, sleep=lambda x: None)
    srv.ANSWER_GENERATOR = orch
    CUR.clear()
    del LAST_ERRORS[:]
    r = client.post("/chat", json={"message": Q, "session_id": sid}).json()
    summ = CUR["session"].summary() if "session" in CUR else {}
    sent = "\n".join(http.sent)
    return {"kind": r.get("kind"), "provider": summ.get("provider"), "http_order": http.calls,
            "calls": [(c["provider"], c["outcome"], c["reason"]) for c in summ.get("calls", []) if c["outcome"] != "skipped"],
            "fallback_reasons": summ.get("fallback_reasons"), "validation_errors": [e[:1] for e in LAST_ERRORS],
            "n_sources": len(r.get("sources", [])), "source_warnings": len(r.get("source_warnings", [])),
            "answer": r.get("response", "")[:300],
            "rule6_in_request": "not disqualified or liable to be disqualified" in sent,
            "third_schedule_sent": "THE THIRD SCHEDULE" in sent}


def main():
    client = TestClient(srv.app)
    probe.open_grounded_gate(srv.vector_store.get(include=["metadatas"]))
    out = {"vector_search": srv.VECTOR_SEARCH, "rows": []}

    def add(label, **kw):
        row = run(client, f"{label}", **kw)
        row["label"] = label
        out["rows"].append(row)

    for name in ("groq", "gemini", "ollama"):  # each provider alone, every response style
        for style in ("verbatim", "whitespace", "fenced", "prose", "interp_restated", "interp_contraction",
                      "interp_nbsp", "interp_bold", "interp_noun", "penalty_beside", "refusal"):
            add(f"{name}:{style}", script={name: [style]}, only=name)
    add("gemini:verbatim+thought_part", script={"gemini": ["verbatim+thought"]}, only="gemini")
    # full chain, provider order preserved
    add("chain:groq_ok", script={"groq": ["verbatim"]})
    add("chain:groq_quota->gemini", script={"groq": [quota("groq")], "gemini": ["verbatim"]})
    add("chain:groq_503->gemini", script={"groq": [err(503, "UNAVAILABLE")], "gemini": ["verbatim"]})
    add("chain:groq_quota,gemini_quota->ollama", script={"groq": [quota("groq")], "gemini": [quota("gemini")],
                                                         "ollama": ["verbatim"]})
    add("chain:all_down", script={"groq": [err(503, "UNAVAILABLE")], "gemini": [err(503, "UNAVAILABLE")],
                                  "ollama": [requests.ConnectionError("refused")]})
    # validation fallback: a rejected candidate gets exactly one validated candidate from the next provider
    add("chain:groq_penalty_beside->gemini_verbatim", script={"groq": ["penalty_beside"], "gemini": ["verbatim"]})
    add("chain:groq_noun->gemini_verbatim", script={"groq": ["interp_noun"], "gemini": ["verbatim"]})
    add("chain:groq_penalty,gemini_penalty", script={"groq": ["penalty_beside"], "gemini": ["penalty_beside"],
                                                     "ollama": ["verbatim"]})
    print(json.dumps(out))


if __name__ == "__main__":
    main()
