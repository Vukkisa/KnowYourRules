"""Deterministic stand-in for a provider used by the Stage 5 cache probe and benchmark: it quotes a sentence of the
evidence it was sent, but only one the real validator accepts, so what it returns is always a validated answer unless a
failure mode is requested. It counts calls and can add a fixed, clearly simulated generation delay."""
import json
import re
import time

from backend import grounded_answer as ga
from backend import meaning_checks


class Gen:
    def __init__(self, srv, delay_ms=0.0):
        self.srv, self.delay_ms, self.calls, self.mode = srv, delay_ms, 0, "quote"

    def _doc(self, text, eid, extra=""):
        return {"answer": text + extra, "evidence_sufficiency": "sufficient",
                "claims": [{"text": text + extra, "kind": "direct", "evidence_ids": [eid]}], "citations": [eid],
                "refusal_reason": None, "clarification_question": None}

    def _quotable(self, contract):
        """Quotable sentences, the one sharing most words with the question first (as a model would pick it)."""
        q = {w for w in re.findall(r"[a-z]{4,}", contract.user_question.lower())}
        found = []
        for n, e in enumerate(contract.evidence):
            body = e.passage.partition("\n")[2] or e.passage
            for s in meaning_checks.sentences(body):
                if 40 <= len(s) <= 500:
                    found.append((-len(q & set(re.findall(r"[a-z]{4,}", s.lower()))), n, e, s))
        for _, _, e, s in sorted(found, key=lambda t: t[:2]):
            yield e, s

    def generate(self, prompt, contract):
        self.calls += 1
        if self.delay_ms:
            time.sleep(self.delay_ms / 1000.0)
        if self.mode == "malformed":
            return "this is not json"
        if self.mode == "refuse":
            return json.dumps({"answer": "", "evidence_sufficiency": "insufficient", "claims": [], "citations": [],
                               "refusal_reason": "The passages do not state this.", "clarification_question": None})
        for e, s in self._quotable(contract):
            if self.mode == "fabricate":
                return json.dumps(self._doc(s, e.evidence_id, " The fee is Rs. 9999 for every applicant."))
            if self.mode == "penalty":
                if self.srv.answer_drift_reason(s):
                    return json.dumps(self._doc(s, e.evidence_id))
                continue
            raw = json.dumps(self._doc(s, e.evidence_id))
            res = ga.validate(raw, contract, penalty_reason=self.srv.answer_drift_reason)
            if res.ok:
                return raw
        return json.dumps({"answer": "", "evidence_sufficiency": "insufficient", "claims": [], "citations": [],
                           "refusal_reason": "No quotable sentence.", "clarification_question": None})
