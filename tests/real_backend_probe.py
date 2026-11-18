"""Run by tests/test_view_source_real.py in its own process, because the other tests replace Chroma, Ollama and
Groq with fakes before importing the server. Here nothing is replaced: the real backend.server, a real Chroma
index (TG_DB_DIR, always a throw-away copy) and real Ollama embeddings. Prints one JSON document.

What is NOT real, and why:
  - Grounded answers need a signed legal approval that does not exist yet. As in tests/test_server.py, the gate
    is opened in this process only and every indexed document is treated as approved. Nothing is written.
  - No model is called. The grounded generator is deterministic: it cites the 2nd and the last usable evidence
    passage, each with one whole sentence of that passage, so the real validator and renderer still run.
    Development output uses a fixed string. Which passages are listed never depends on the model's wording.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from langchain_core.runnables import RunnableLambda  # noqa: E402

import backend.server as srv  # noqa: E402
from backend import meaning_checks  # noqa: E402

QUESTIONS = [
    "What are the helmet rules in Telangana?",
    "How do I apply for a learner's licence in Telangana?",
    "What badge must the driver of a transport vehicle wear and what badge must a conductor wear?",
    "How do I transfer ownership of a vehicle in Telangana?",
]


class SubsetGenerator:
    def generate(self, prompt, contract):
        def sentence(e):
            body = e.passage.partition("\n")[2] or e.passage
            ok = [x for x in meaning_checks.sentences(body) if 40 <= len(x) <= 500 and not srv.answer_drift_reason(x)]
            return ok[0] if ok else None

        usable = [e for e in contract.evidence if sentence(e)]
        picked = [usable[1], usable[-1]] if len(usable) > 2 else usable[:1]
        claims = [{"text": sentence(e), "kind": "direct", "evidence_ids": [e.evidence_id]} for e in picked]
        if not claims:
            return json.dumps({"answer": "", "evidence_sufficiency": "insufficient", "claims": [], "citations": [],
                               "refusal_reason": "no quotable sentence", "clarification_question": None})
        return json.dumps({"answer": " ".join(c["text"] for c in claims), "evidence_sufficiency": "sufficient",
                           "claims": claims, "citations": [e.evidence_id for e in picked],
                           "refusal_reason": None, "clarification_question": None})


def chunk_key(meta, text):
    return [meta.get("sha256"), meta.get("provision_id") or None, text.partition("\n")[2]]


def ask(client, question, sid):
    r = client.post("/chat", json={"message": question, "session_id": sid})
    retrieved = [chunk_key(d.metadata, d.page_content) for d in srv.retrieve(question)]
    return {"question": question, "status": r.status_code, "body": r.json(), "retrieved": retrieved}


def open_grounded_gate(stored):
    srv.GROUNDED_ANSWERS_ENABLED, srv.ANSWER_MODE = True, "grounded"
    srv.grounded_gate_errors = lambda: []
    for m in stored["metadatas"]:
        if srv.chunk_hash(m):
            srv.SOURCES.setdefault(srv.chunk_hash(m), (m.get("title") or m.get("source_file"), m.get("document_type")))


def main():
    client = TestClient(srv.app)
    stored = srv.vector_store.get(include=["metadatas", "documents"])
    out = {"vector_search": srv.VECTOR_SEARCH, "status": client.get("/status").json(),
           "stored": [chunk_key(m, t) + [srv.source_passage(type("D", (), {"metadata": m, "page_content": t})())["label"]]
                      for m, t in zip(stored["metadatas"], stored["documents"])]}

    out["as_is"] = [ask(client, q, "as-is") for q in QUESTIONS[:2]]

    open_grounded_gate(stored)
    srv.ANSWER_GENERATOR = SubsetGenerator()
    out["grounded"] = [ask(client, q, f"grounded-{i}") for i, q in enumerate(QUESTIONS)]

    srv.GROUNDED_ANSWERS_ENABLED, srv.ANSWER_MODE = False, "legacy_dev"
    srv.llm = RunnableLambda(lambda prompt: "Fixed development text.")
    out["development"] = [ask(client, q, f"dev-{i}") for i, q in enumerate(QUESTIONS[:2])]
    print(json.dumps(out))


# ---- Tax section (tests/test_life_tax_real.py) -------------------------------------------------------------------
# Same rules as above: the gate is opened in this process only, no model is called. Three deterministic generators:
#   quoting:    SubsetGenerator (quotes stored sentences; it does not judge relevance, so it "answers" anything);
#   refusing:   always reports insufficient evidence, as an honest model would for unsupported questions;
#   fabricated: states two-wheeler life-tax rates that no answer-eligible evidence contains, cited to real evidence.
TAX_QUESTIONS = {
    "life_tax": [
        "How is life tax calculated for a new two-wheeler in Telangana?",
        "What is the life tax on a new motorcycle in Telangana?",
        "How much road tax do I pay when I buy a new bike in Telangana?",
    ],
    "related": [
        "What is the life tax for a new car in Telangana?",
        "When is quarterly tax payable in Telangana?",
        "Can I get a refund of life tax in Telangana?",
    ],
    "unsupported": [
        "What is the green tax in Telangana?",
        "Is there a life tax exemption for electric two-wheelers in Telangana?",
    ],
    "penalty": [
        "What is the penalty for not paying life tax on a two-wheeler in Telangana?",
    ],
}
FABRICATED_RATES = ("Life tax for a new two-wheeler costing below Rs. 50,000 is 9% of the cost of the vehicle.",
                    "Life tax for a new two-wheeler costing above Rs. 2 lakh is 18% of the cost of the vehicle.")


class Recording:
    """Wraps a generator and records the evidence it was shown."""
    def __init__(self, inner):
        self.inner, self.seen = inner, []

    def generate(self, prompt, contract):
        self.seen.append([[e.chunk_id, e.passage] for e in contract.evidence])
        return self.inner.generate(prompt, contract)


class RefusingGenerator:
    def generate(self, prompt, contract):
        return json.dumps({"answer": "", "evidence_sufficiency": "insufficient", "claims": [], "citations": [],
                           "refusal_reason": "the evidence does not state this", "clarification_question": None})


class FabricatedRateGenerator:
    def generate(self, prompt, contract):
        if not contract.evidence:
            return RefusingGenerator().generate(prompt, contract)
        cite = contract.evidence[0].evidence_id
        claims = [{"text": t, "kind": "direct", "evidence_ids": [cite]} for t in FABRICATED_RATES]
        return json.dumps({"answer": " ".join(FABRICATED_RATES), "evidence_sufficiency": "sufficient",
                           "claims": claims, "citations": [cite], "refusal_reason": None,
                           "clarification_question": None})


def tax_key(meta, text):
    return [meta.get("manifest_id"), meta.get("provision_id") or None, meta.get("answer_eligible"),
            text.partition("\n")[2]]


def tax_ask(client, question, sid, generator):
    srv.ANSWER_GENERATOR = recorder = Recording(generator)
    r = client.post("/chat", json={"message": question, "session_id": sid})
    return {"question": question, "status": r.status_code, "body": r.json(), "evidence_seen": recorder.seen,
            "vector": [tax_key(d.metadata, d.page_content) for d, _ in srv.vector_search(question)],
            "retrieved": [tax_key(d.metadata, d.page_content) for d in srv.retrieve(question)]}


def main_tax():
    client = TestClient(srv.app)
    stored = srv.vector_store.get(include=["metadatas", "documents"])
    out = {"vector_search": srv.VECTOR_SEARCH, "status": client.get("/status").json(),
           "stored": [tax_key(m, t) for m, t in zip(stored["metadatas"], stored["documents"])]}
    open_grounded_gate(stored)
    every = [q for qs in TAX_QUESTIONS.values() for q in qs]
    out["quoting"] = {g: [tax_ask(client, q, f"tax-q-{g}-{i}", SubsetGenerator()) for i, q in enumerate(qs)]
                      for g, qs in TAX_QUESTIONS.items()}
    out["refusing"] = [tax_ask(client, q, f"tax-r-{i}", RefusingGenerator()) for i, q in enumerate(every)]
    out["fabricated"] = [tax_ask(client, q, f"tax-f-{i}", FabricatedRateGenerator())
                         for i, q in enumerate(TAX_QUESTIONS["life_tax"])]

    srv.GROUNDED_ANSWERS_ENABLED, srv.ANSWER_MODE = False, "legacy_dev"
    srv.llm = RunnableLambda(lambda prompt: "Fixed development text.")
    out["development_penalty"] = [tax_ask(client, q, f"tax-dev-{i}", RefusingGenerator())
                                  for i, q in enumerate(TAX_QUESTIONS["penalty"])]
    print(json.dumps(out))


if __name__ == "__main__":
    main_tax() if sys.argv[1:] == ["tax"] else main()
