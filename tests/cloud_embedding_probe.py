"""Stage 7A probe, run by tests/test_cloud_embedding_real.py in its own process: the REAL backend.server (TestClient), a real
Chroma index COPY (in snapshot mode it comes out of a verified snapshot), real retrieval, real validator and cache. Query
embeddings come either from local Ollama (control) or from a LOCAL FAKE of an OpenAI-compatible hosted API that relays real Ollama
vectors (EMBEDDING_PROVIDER=openai_compatible). The answering model is a deterministic stand-in; no generation provider is called.
Nothing here proves a real hosted provider's numerics, only that the plumbing, the safety checks and the failure behaviour work.

usage: cloud_embedding_probe.py retrieval|faults|startup_down|startup_incompat|status
env:   FAKE_CONTROL=http://127.0.0.1:port  (the fake hosted API's control endpoint; used to switch fault modes)"""
import json
import logging
import os
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


class Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        try:
            self.lines.append(record.getMessage())
        except Exception:   # noqa: BLE001
            self.lines.append(str(record.msg))


CAPTURE = Capture()
logging.getLogger().addHandler(CAPTURE)
logging.getLogger().setLevel(logging.DEBUG)

import real_backend_probe as probe  # noqa: E402
import requests  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import document_lifecycle as dl  # noqa: E402
from backend import legal_approval as la  # noqa: E402

srv = probe.srv
client = TestClient(srv.app)
CASES = json.loads((ROOT / "eval" / "telangana-retrieval-benchmark.json").read_text())["cases"]
APPROVED_IDS = [x for x in os.environ.get("APPROVED_IDS", "").split(",") if x]
CONTROL = os.environ.get("FAKE_CONTROL", "")
API_KEY = os.environ.get("EMBEDDING_API_KEY", "")
out = {"scenario": sys.argv[1], "vector_search": srv.VECTOR_SEARCH, "violations": []}


class CountingGen(probe.SubsetGenerator):
    def __init__(self):
        self.calls = 0

    def generate(self, prompt, contract):
        self.calls += 1
        return super().generate(prompt, contract)


GEN = CountingGen()


def set_mode(mode):
    requests.post(CONTROL + "/_mode", json={"mode": mode}, timeout=5).raise_for_status()


def satisfy_gate():
    """Everything grounded_gate_errors() demands except the lifecycle/embedding/snapshot clauses (real code), as a test fixture."""
    srv.GROUNDED_ANSWERS_ENABLED, srv.ANSWER_MODE = True, "grounded"
    srv.CORPUS_DIR = Path("/nonexistent/fixture-corpus")
    srv._FINGERPRINT = srv.approval_fingerprint()
    srv._STALE = False


def chat(q, sid="s"):
    r = client.post("/chat", json={"message": q, "session_id": sid})
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    return r.status_code, body, r.text


def needs_retrieval(q):
    """True when /chat will reach retrieval (i.e. no deterministic pre-retrieval reply, lock or catalogue answer applies)."""
    if srv.other_places(q) or srv.penalty_lock_reason(q):
        return False
    missing, _ = srv.missing_references(q)
    return not (missing or srv.classify_rule_references(q).central_text or srv.ambiguous_references(q))


def approved_questions():
    ids = set(APPROVED_IDS)
    return [c["question"] for c in CASES if c.get("expected_documents") and set(c["expected_documents"]) <= ids and needs_retrieval(c["question"])]


def find_answerable(qs, n):
    """Questions the stand-in model answers when the provider is healthy (they get cached, so each is used once)."""
    found, tried = [], set()
    for q in qs:
        tried.add(q)
        code, body, _ = chat(q, "warm")
        if code == 200 and body.get("kind") == "answer":
            found.append(q)
        if len(found) == n:
            break
    return found, [c["question"] for c in CASES if needs_retrieval(c["question"]) and c["question"] not in tried]


def status_block():
    st = client.get("/status").json()
    return {"corpus_ready": st.get("corpus_ready"), "embedding": st.get("embedding"), "snapshot": st.get("snapshot"),
            "index": st.get("index"), "chunks": st.get("chunks"), "lifecycle_ready": (st.get("lifecycle") or {}).get("ready"),
            "lifecycle_corpus_ready": (st.get("lifecycle") or {}).get("corpus_ready")}


def leaks():
    """Anything that must never appear in a response or in a log line."""
    if not API_KEY:
        return 0
    return sum(API_KEY in line for line in CAPTURE.lines)


def base():
    out["health"] = client.get("/health").json()
    out["status"] = status_block()
    out["embedding_provider"] = srv.EMBEDDING.provider
    out["index_dir_exists"] = Path(srv.TG_DB_DIR).exists()


def retrieval():
    """Per benchmark question: the chunks the retriever returns with the lifecycle filter as configured, and with no filter."""
    base()
    res, unfiltered = {}, {}
    for c in CASES:
        res[c["id"]] = [probe.chunk_key(d.metadata, d.page_content) for d in srv.retrieve(c["question"])]
    configured, srv.LIFECYCLE = srv.LIFECYCLE, dl.ServeFilter(None)
    try:
        for c in CASES:
            unfiltered[c["id"]] = [probe.chunk_key(d.metadata, d.page_content) for d in srv.retrieve(c["question"])]
    finally:
        srv.LIFECYCLE = configured
    out["filtered"], out["unfiltered"] = res, unfiltered
    out["filtered_shas"] = sorted({k[0] for v in res.values() for k in v})
    out["embedding_after"] = srv.EMBEDDING.health()
    out["key_leaks"] = leaks()


def faults():
    base()
    srv.ANSWER_GENERATOR = GEN
    satisfy_gate()
    out["gate_errors"] = srv.grounded_gate_errors()
    set_mode("ok")
    qs = approved_questions()
    answerable, rest = find_answerable(qs, 2)
    out["questions_available"], out["answerable"] = len(qs), len(answerable)
    steps, used = [], iter(rest)

    def ask(label, mode, q=None, settle=0.0):
        set_mode(mode)
        if settle:
            time.sleep(settle)
        q = q or next(used)
        before = GEN.calls
        code, body, text = chat(q, f"s-{label}")
        steps.append({"label": label, "mode": mode, "status": code, "kind": body.get("kind"),
                      "detail": body.get("detail"), "generator_calls": GEN.calls - before,
                      "sources": len(body.get("sources", []) or []), "key_in_response": bool(API_KEY and API_KEY in text),
                      "state": srv.EMBEDDING.health().get("state"), "corpus_ready": srv.corpus_ready()})

    cool = float(os.environ.get("EMBEDDING_BREAKER_COOLDOWN_SECONDS", "1")) + 0.3
    # a healthy answer first, so every later 503 is about the provider and not about the question
    ask("healthy", "ok", answerable[0])
    # transient faults: a safe 503 each, then the provider returns and the very next question is answered
    for mode in ("http401", "http429", "http500", "timeout", "bad_json", "empty_data"):
        ask(mode, mode, settle=cool)
    ask("recovered", "ok", answerable[1], settle=cool)
    # incompatible vectors: a safe 503, and the process refuses the provider from then on (no mixing), even once it behaves again
    ask("wrong_dims", "wrong_dims")
    ask("after_wrong_dims_ok", "ok", settle=cool)
    ask("unscaled", "unscaled")
    out["steps"] = steps
    out["embedding_after"] = srv.EMBEDDING.health()
    out["key_leaks"] = leaks()
    out["error_constant"] = srv.EMBEDDING_ERROR
    out["health_after"] = client.get("/health").json()


def startup_down():
    """The provider is down while the server starts: not ready, 503, never an Ollama fallback; recovers without a restart."""
    base()
    srv.ANSWER_GENERATOR = GEN
    satisfy_gate()
    qs = approved_questions()
    out["gate_errors"] = srv.grounded_gate_errors()
    code, body, text = chat(qs[0], "down-1")
    out["down"] = {"status": code, "detail": body.get("detail"), "generator_calls": GEN.calls, "status_block": status_block()}
    set_mode("ok")
    time.sleep(float(os.environ.get("EMBEDDING_REVERIFY_SECONDS", "5")) + 0.7)
    code, body, text = chat(qs[1], "down-2")
    out["recovered"] = {"status": code, "kind": body.get("kind"), "generator_calls": GEN.calls, "status_block": status_block()}
    out["key_leaks"] = leaks()


def startup_incompat():
    """A provider whose vectors are not the index's model: refused at startup AND for the rest of the process (no mixing)."""
    base()
    srv.ANSWER_GENERATOR = GEN
    satisfy_gate()
    qs = approved_questions()
    out["gate_errors"] = srv.grounded_gate_errors()
    code, body, text = chat(qs[0], "inc-1")
    out["incompatible"] = {"status": code, "kind": body.get("kind"), "detail": body.get("detail"), "generator_calls": GEN.calls, "status_block": status_block()}
    set_mode("ok")   # the provider now returns the right vectors: the process must STILL refuse (a model was already seen to differ)
    time.sleep(float(os.environ.get("EMBEDDING_REVERIFY_SECONDS", "5")) + 0.7)
    code, body, text = chat(qs[1], "inc-2")
    out["after_switch"] = {"status": code, "kind": body.get("kind"), "detail": body.get("detail"), "generator_calls": GEN.calls, "status_block": status_block()}
    out["q1"] = qs[1]
    out["key_leaks"] = leaks()


def status_only():
    """Snapshot problems: the app must come up, say it is not ready, serve nothing, and create nothing."""
    base()
    srv.ANSWER_GENERATOR = GEN
    satisfy_gate()
    out["gate_errors"] = srv.grounded_gate_errors()
    out["status_gated"] = status_block()
    code, body, text = chat(CASES[0]["question"], "snap-1")
    out["chat"] = {"status": code, "kind": body.get("kind"), "detail": body.get("detail"), "sources": len(body.get("sources", []) or []),
                   "generator_calls": GEN.calls}
    unavailable = Path(srv.TG_DB_DIR).parent
    out["unavailable_dir_entries"] = sorted(p.name for p in unavailable.iterdir()) if unavailable.exists() and unavailable.name == ".snapshot-unavailable" else []
    out["retrieval_empty"] = all(not srv.retrieve(c["question"]) for c in CASES[:5])
    out["key_leaks"] = leaks()


def main():
    {"retrieval": retrieval, "faults": faults, "startup_down": startup_down, "startup_incompat": startup_incompat,
     "status": status_only}[sys.argv[1]]()
    print(json.dumps(out, default=str))


if __name__ == "__main__":
    main()
