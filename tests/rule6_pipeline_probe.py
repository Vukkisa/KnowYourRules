"""Run by tests/test_rule6_pipeline_real.py (and by hand for eval/latency/stage4f/) in its own process: the real
backend.server on a throw-away COPY of a real Telangana index (TG_DB_DIR) with real Ollama embeddings, the real /chat
route, real retrieval, real context assembly and the real validator. The legal gate is opened in this process only
(as in tests/real_backend_probe.py). No provider and no network model is called: the model is a scripted generator,
so every run is deterministic. Prints one JSON document as its last stdout line.

Scripts (what the "model" returns for the evidence it was given):
  quote       one verbatim claim: the sentence of the retrieved Rule 6 (or Rule 52) passage that says "not disqualified"
  penalty     that sentence plus an invented disqualification punishment, in one claim
  fabricate   an invented licence requirement / fee, cited to the Rule 6 passage
  refuse      an honest "the passages do not state this" refusal
"""
import json
import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
logging.disable(logging.INFO)

import real_backend_probe as probe  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import eligibility_status, grounded_answer, meaning_checks  # noqa: E402

srv = probe.srv
Q_AFTER = "What happens after I submit a driving licence application?"
Q_RECEIVED = "What happens when a driving licence application is received?"
Q_REQS = "What are the requirements for getting a driving licence in Telangana?"
Q_LEARNER = "What documents are required for a learner's licence?"
Q_LIFE = "How is life tax calculated for a new two-wheeler in Telangana?"
PENALTY_TAIL = " A person who drives while disqualified shall be punished with imprisonment and a fine of Rs. 500."
FABRICATED = "The applicant must submit proof of age and address and pass a medical test, and a fee of Rs. 4,321 is payable."


def status_sentence(contract):
    """(evidence, sentence) for the retrieved passage that contains a negated 'disqualified' construction."""
    for e in contract.evidence:
        for s in meaning_checks.sentences(e.passage.partition("\n")[2] or e.passage):
            if eligibility_status.constructions(s):
                return e, s
    return None, None


class Scripted:
    def __init__(self, script):
        self.script, self.seen = script, None

    def generate(self, prompt, contract):
        self.seen = {"provisions": [e.provision_id for e in contract.evidence],
                     "has_rule6_text": any("not disqualified or liable to be disqualified" in e.passage
                                           for e in contract.evidence),
                     "third_schedule": any("THE THIRD SCHEDULE" in e.passage for e in contract.evidence),
                     "withheld": any(e.provision_id == "THIRD SCHEDULE" for e in contract.evidence)}
        e, s = status_sentence(contract)
        first = contract.evidence[0].evidence_id if contract.evidence else "E1"
        refuse = {"answer": "", "evidence_sufficiency": "insufficient", "claims": [], "citations": [],
                  "refusal_reason": "The passages do not state this.", "clarification_question": None}

        def one(text, eid):
            return {"answer": text, "evidence_sufficiency": "sufficient",
                    "claims": [{"text": text, "kind": "direct", "evidence_ids": [eid]}], "citations": [eid],
                    "refusal_reason": None, "clarification_question": None}
        flagged = next(((x, t) for x in contract.evidence
                        for t in meaning_checks.sentences(x.passage.partition("\n")[2] or x.passage)
                        if 40 <= len(t) <= 500 and srv.answer_drift_reason(t) and not eligibility_status.constructions(t)),
                       (None, None))
        self.seen["flagged_provision"] = flagged[0].provision_id if flagged[0] else None
        if self.script == "grounded_penalty" and flagged[0]:
            out = one(flagged[1], flagged[0].evidence_id)
        elif self.script == "mixed_two_claims" and e and flagged[0]:
            out = {"answer": s + " " + flagged[1], "evidence_sufficiency": "sufficient",
                   "claims": [{"text": s, "kind": "direct", "evidence_ids": [e.evidence_id]},
                              {"text": flagged[1], "kind": "direct", "evidence_ids": [flagged[0].evidence_id]}],
                   "citations": sorted({e.evidence_id, flagged[0].evidence_id}), "refusal_reason": None,
                   "clarification_question": None}
        elif self.script == "quote" and e:
            out = one(s, e.evidence_id)
        elif self.script == "penalty" and e:
            out = one(s + PENALTY_TAIL, e.evidence_id)
        elif self.script == "fabricate":
            out = one(FABRICATED, (e.evidence_id if e else first))
        else:
            out = refuse
        return json.dumps(out)


LAST = {}
_validate = grounded_answer.validate


def _spy(raw, contract, **kw):
    result = _validate(raw, contract, **kw)
    LAST["errors"] = list(result.errors)
    return result


grounded_answer.validate = _spy


def chat(client, question, script, sid):
    LAST.clear()
    gen = Scripted(script)
    srv.ANSWER_GENERATOR = gen
    r = client.post("/chat", json={"message": question, "session_id": sid})
    body = r.json()
    return {"question": question, "script": script, "http": r.status_code, "kind": body.get("kind"),
            "answer": body.get("response", "")[:600], "n_sources": len(body.get("sources", [])),
            "source_warnings": len(body.get("source_warnings", [])), "context": gen.seen,
            "validation_errors": LAST.get("errors")}


def main():
    client = TestClient(srv.app)
    stored = srv.vector_store.get(include=["metadatas", "documents"])
    probe.open_grounded_gate(stored)
    out = {"vector_search": srv.VECTOR_SEARCH, "runs": []}

    def run_all(label):
        rows = []
        for i, (q, script) in enumerate([
                (Q_AFTER, "quote"), (Q_RECEIVED, "quote"), (Q_AFTER, "penalty"), (Q_RECEIVED, "penalty"),
                (Q_AFTER, "grounded_penalty"), (Q_RECEIVED, "grounded_penalty"),
                (Q_AFTER, "mixed_two_claims"), (Q_RECEIVED, "mixed_two_claims"),
                (Q_AFTER, "fabricate"), (Q_RECEIVED, "fabricate"), (Q_REQS, "refuse"), (Q_REQS, "fabricate"),
                (Q_LEARNER, "refuse"), (Q_LEARNER, "fabricate"), (Q_LIFE, "fabricate")]):
            row = chat(client, q, script, f"{label}-{i}")
            row["label"] = label
            rows.append(row)
        return rows

    out["after"] = run_all("after")  # the change as shipped
    real_mask = eligibility_status.mask
    eligibility_status.mask = lambda text, evidence: text  # "before": the exception switched off
    try:
        out["before"] = run_all("before")
    finally:
        eligibility_status.mask = real_mask

    # corpus-wide effect: every answer-eligible sentence, penalty verdict with and without the exception
    changed = []
    for text, meta in zip(stored["documents"], stored["metadatas"]):
        if meta.get("answer_eligible") is False:
            continue
        for s in meaning_checks.sentences(text.partition("\n")[2] or text):
            before = srv.answer_drift_reason(s)
            after = srv.answer_drift_reason(eligibility_status.mask(s, [text]))
            if before != after:
                changed.append({"provision": meta.get("provision_id"), "before": before, "after": after,
                                "sentence": s[:240]})
    out["corpus_changed_sentences"] = changed
    out["corpus_sentences_with_negated_status"] = sorted({
        meta.get("provision_id") for text, meta in zip(stored["documents"], stored["metadatas"])
        if meta.get("answer_eligible") is not False and eligibility_status.constructions(text)})
    print(json.dumps(out))


if __name__ == "__main__":
    main()
