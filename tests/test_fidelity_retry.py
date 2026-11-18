"""Retry policy in grounded answering: only a rejection caused by uncited evidence is retried (tests/test_conflict_retry.py).
A claim that does not faithfully restate its cited sentence (a dropped qualifier, a changed value, a wrong evidence id) is
NOT retried with the validator's findings; the validator rejects it and the server may offer the question to the next
provider instead. Every model response is a fixture (MockGenerator); no provider is called. Passage text is synthetic."""

import json
import unittest

from langchain_core.documents import Document

from backend import grounded_answer as ga

PASSAGE = Document(page_content=("Synthetic Rule 1. Subject to the provisions of Rule 9, no person under the age of twenty "
                                 "years shall drive a transport vehicle in any public place."),
                   metadata={"manifest_id": "synthetic-rules", "provision_id": "Rule 1", "part": 1, "parts": 1,
                             "title": "Synthetic Rules", "document_number": "", "location": "synthetic.htm#Rule-1",
                             "page_start": -1, "page_end": -1, "jurisdiction": "Telangana", "state": "Telangana",
                             "verification_status": "unverified", "answer_eligible": True, "extraction_warning": "",
                             "sha256": "c" * 64})
SENTENCE = ("Subject to the provisions of Rule 9, no person under the age of twenty years shall drive a transport vehicle "
            "in any public place.")
DROPPED = "No person under the age of twenty years shall drive a transport vehicle in any public place."
Q = "What is the minimum age to drive a transport vehicle?"


def resp(text, sufficiency="sufficient"):
    return {"answer": text, "evidence_sufficiency": sufficiency,
            "claims": [{"text": text, "kind": "direct", "evidence_ids": ["E1"]}], "citations": ["E1"],
            "refusal_reason": None, "clarification_question": None}


def sequence(*outputs):
    gen = ga.MockGenerator(fn=lambda _p, _c: json.dumps(outputs[min(len(gen.calls), len(outputs)) - 1]))
    return gen


class NoFidelityRetryTests(unittest.TestCase):
    def test_a_dropped_qualifier_is_rejected_without_a_retry(self):
        gen = sequence(resp(DROPPED), resp(SENTENCE))
        r = ga.answer(Q, [PASSAGE], gen)
        self.assertEqual((r.kind, r.attempts, len(gen.calls)), ("rejected", 1, 1))
        self.assertNotIn("Validator note", "".join(gen.calls))

    def test_a_wrong_evidence_id_is_rejected_without_a_retry(self):
        wrong = resp(SENTENCE)
        wrong["claims"][0]["evidence_ids"] = ["E128"]
        wrong["citations"] = ["E128"]
        r = ga.answer(Q, [PASSAGE], sequence(wrong, resp(SENTENCE)))
        self.assertEqual((r.kind, r.attempts), ("rejected", 1))

    def test_a_faithful_answer_is_accepted_first_time(self):
        gen = sequence(resp(SENTENCE))
        r = ga.answer(Q, [PASSAGE], gen)
        self.assertEqual((r.kind, r.attempts, len(gen.calls)), ("answer", 1, 1))

    def test_penalty_content_is_never_retried(self):
        gen = ga.MockGenerator(response=resp("The licensing authority may impose a fine on the driver."))
        r = ga.answer(Q, [PASSAGE], gen, penalty_reason=lambda t: "penalty_term" if "fine" in t else None)
        self.assertEqual(len(gen.calls), 1)
        self.assertNotEqual(r.kind, "answer")


if __name__ == "__main__":
    unittest.main()
