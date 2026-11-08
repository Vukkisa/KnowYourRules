"""Offline regression tests for backend/server.py.

Groq, Chroma and Ollama are replaced with in-memory fakes before the server is imported, so these
tests need no API key, no network and no vector index. Run from the project root:
    python -m unittest discover -s tests -v
"""

import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.documents import Document  # noqa: E402
from langchain_core.runnables import RunnableLambda  # noqa: E402

TG_RULES_FILE = "tg-mv-rules-1989-fixture.pdf"
TG_TAX_FILE = "tg-go-ms-53-2025-fixture.pdf"
CENTRAL_FILE = "central-mv-act-fixture.pdf"
# Synthetic SHA-256 values for the fixture documents (not hashes of any real file).
TG_RULES_SHA = "a" * 64
TG_TAX_SHA = "b" * 64

# Fixture text only - not legal text.
CORPUS = [
    Document(page_content="Rule 5. Learner's licence application.", metadata={"state": "Telangana", "source_file": TG_RULES_FILE, "sha256": TG_RULES_SHA}),
    Document(page_content="Life tax schedule for two-wheelers.", metadata={"state": "Telangana", "source_file": TG_TAX_FILE, "sha256": TG_TAX_SHA}),
]
CENTRAL_DOC = Document(page_content="184. Driving dangerously.", metadata={"state": "Central", "source_file": CENTRAL_FILE})


# Distances the fake store reports. By default every matching chunk is close (relevant); tests can
# set FAKE_SEARCH["fn"](question, state, docs) to return any list they like, including malformed ones.
RELEVANT_DISTANCE = 0.3
FAKE_SEARCH = {"fn": None}
SEARCH_LOG = []


class FakeChroma:
    def __init__(self, **kwargs):
        pass

    def similarity_search_with_score(self, query, k=4, filter=None):
        SEARCH_LOG.append(filter)
        state = (filter or {}).get("state")
        docs = [d for d in CORPUS if d.metadata["state"] == state][:k]
        if FAKE_SEARCH["fn"]:
            return FAKE_SEARCH["fn"](query, state, docs)
        return [(d, RELEVANT_DISTANCE) for d in docs]

    def get(self, include=None):
        return {"ids": [str(i) for i in range(len(CORPUS))], "metadatas": [d.metadata for d in CORPUS]}


class FakeStore:
    """Stand-in for load_indexed_states() tests."""

    def __init__(self, metadatas=None, error=None):
        self.metadatas, self.error = metadatas or [], error

    def get(self, include=None):
        if self.error:
            raise self.error
        return {"ids": [str(i) for i in range(len(self.metadatas))], "metadatas": self.metadatas}


# Every prompt the server sends goes through FAKE_LLM["fn"]; tests swap it per case.
FAKE_LLM = {"fn": lambda prompt: "stub answer"}


def _import_server_with_fakes(extra_env=None):
    chat_models = types.ModuleType("langchain.chat_models")
    chat_models.init_chat_model = lambda *a, **k: RunnableLambda(lambda pv: FAKE_LLM["fn"](pv.to_string()))
    chroma = types.ModuleType("langchain_chroma")
    chroma.Chroma = FakeChroma
    ollama = types.ModuleType("langchain_ollama")
    ollama.OllamaEmbeddings = lambda **k: None
    fakes = {"langchain.chat_models": chat_models, "langchain_chroma": chroma, "langchain_ollama": ollama}
    saved = {name: sys.modules.get(name) for name in fakes}
    sys.modules.update(fakes)
    try:
        # patch.dict restores os.environ afterwards, including anything the server's load_dotenv() set.
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "offline-test-not-a-real-key",
                                       "TG_DB_DIR": str(Path(__file__).resolve().parent),
                                       "TG_KB_APPROVED": "", "TG_PENALTY_ANSWERS": "",
                                       "TG_APPROVAL_FILE": str(Path(__file__).resolve().parent / "no-approval-record.json"),
                                       **(extra_env or {})}):
            import backend.server as server
    finally:
        # Restore the real modules, and forget this fake-backed server, so other tests are unaffected.
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        sys.modules.pop("backend.server", None)
        if hasattr(sys.modules.get("backend"), "server"):
            delattr(sys.modules["backend"], "server")
    return server


srv = _import_server_with_fakes()
from fastapi.testclient import TestClient  # noqa: E402

REWRITE_MARKER = "Respond with ONLY the rewritten"


def fake_llm(answer="stub answer", fail=False, log=None):
    """Fake LLM: rewrites return the message unchanged; everything else is logged and gets `answer`."""
    log = log if log is not None else {}

    def fn(prompt):
        if fail:
            raise RuntimeError("simulated provider outage")
        if REWRITE_MARKER in prompt:
            log.setdefault("rewrite", []).append(prompt)
            return prompt.split('New message: "', 1)[1].rsplit('"', 1)[0]
        log.setdefault("answer", []).append(prompt)
        return answer

    return fn


class Base(unittest.TestCase):
    def setUp(self):
        srv.sessions.clear()
        SEARCH_LOG.clear()
        self.addCleanup(FAKE_SEARCH.update, {"fn": None})
        self.log = {}
        self.use()
        self.client = TestClient(srv.app, raise_server_exceptions=False)

    def use(self, **kw):
        FAKE_LLM["fn"] = fake_llm(log=self.log, **kw)

    def post(self, message, sid="s"):
        return self.client.post("/chat", json={"message": message, "session_id": sid})

    def assert_no_model_answer(self):
        self.assertNotIn("answer", self.log)


class IndexStatusTests(Base):
    def test_fixture_index_is_ready(self):
        self.assertEqual(srv.INDEX_INFO["index"], "ready")
        self.assertEqual(srv.INDEX_INFO["chunks"], len(CORPUS))

    def test_missing_index_is_reported_not_raised(self):
        self.assertEqual(srv.inspect_index(None)["index"], "missing")

    def test_empty_index_is_reported(self):
        self.assertEqual(srv.inspect_index(FakeStore([]))["index"], "empty")

    def test_unreadable_index_is_reported(self):
        self.assertEqual(srv.inspect_index(FakeStore(error=OSError("disk error")))["index"], "invalid")

    def test_non_telangana_or_untagged_chunks_make_index_invalid(self):
        for metas in ([{"state": "Telangana"}, {"state": "Central"}], [{"state": "Telangana"}, {"source_file": "x"}]):
            self.assertEqual(srv.inspect_index(FakeStore(metas))["index"], "invalid", metas)

    def test_open_store_does_not_create_missing_directory(self):
        missing = Path(__file__).resolve().parent / "no-such-index-dir"
        with mock.patch.object(srv, "TG_DB_DIR", missing):
            self.assertIsNone(srv.open_store())
        self.assertFalse(missing.exists())

    def test_status_endpoint_defaults_to_pending_and_locked(self):
        s = self.client.get("/status").json()
        self.assertEqual(s["state"], "Telangana")
        self.assertEqual(s["index"], "ready")
        self.assertEqual(s["chunks"], len(CORPUS))
        self.assertFalse(s["kb_approved"])
        self.assertEqual(s["legal_review"], "pending")
        self.assertFalse(s["penalty_answers"])

    def test_chat_without_index_is_unavailable_and_skips_model(self):
        with mock.patch.dict(srv.INDEX_INFO, {"index": "missing", "chunks": 0}):
            r = self.post("How do I get a learner's licence?")
            self.assertEqual(self.client.get("/status").json()["index"], "missing")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["kind"], "unavailable")
        self.assert_no_model_answer()


class TelanganaRetrievalTests(Base):
    def test_retrieval_is_always_filtered_to_telangana(self):
        self.post("How do I get a learner's licence?")
        self.assertTrue(SEARCH_LOG)
        self.assertTrue(all(f == {"state": "Telangana"} for f in SEARCH_LOG), SEARCH_LOG)

    def test_central_chunks_never_reach_the_prompt(self):
        FAKE_SEARCH["fn"] = lambda q, state, docs: [(CENTRAL_DOC, 0.1)] + [(d, 0.3) for d in docs]
        self.post("How do I get a learner's licence?")
        prompt = self.log["answer"][-1]
        self.assertIn("Learner's licence application", prompt)
        self.assertNotIn("Driving dangerously", prompt)

    def test_chunks_flagged_not_answer_eligible_never_reach_the_prompt(self):
        flagged = Document(page_content="Flagged synthetic table text.",
                           metadata={"state": "Telangana", "source_file": TG_TAX_FILE, "sha256": TG_TAX_SHA,
                                     "answer_eligible": False})
        FAKE_SEARCH["fn"] = lambda q, state, docs: [(flagged, 0.1), (docs[0], 0.3)]
        r = self.post("How do I get a learner's licence?").json()
        self.assertNotIn("Flagged synthetic table text.", self.log["answer"][-1])
        self.assertEqual([s["file"] for s in r["sources"]], [TG_RULES_FILE])

    def test_prompt_says_central_law_is_not_covered(self):
        self.post("How do I get a learner's licence?")
        self.assertIn("does NOT include the Central Motor Vehicles Act", self.log["answer"][-1])


class OutOfScopeTests(Base):
    def test_other_states_and_cities_get_not_covered_reply(self):
        for msg, place in [("What is the licence process in Karnataka?", "Karnataka"),
                           ("road tax in bangalore", "Karnataka"),
                           ("Telangana vs Andhra Pradesh life tax", "Andhra Pradesh"),
                           ("helmet rules in New Delhi", "Delhi"),
                           ("Jammu & Kashmir registration", "Jammu and Kashmir")]:
            r = self.post(msg).json()
            self.assertEqual(r["kind"], "out_of_scope", msg)
            self.assertIn(place, r["response"], msg)
        self.assertEqual(SEARCH_LOG, [])
        self.assert_no_model_answer()

    def test_telangana_and_its_cities_are_in_scope(self):
        for msg in ("Learner's licence in Hyderabad", "Telangana vehicle registration", "RTO in Warangal"):
            self.assertEqual(srv.other_places(msg), [], msg)

    def test_place_names_inside_words_do_not_match(self):
        self.assertEqual(srv.other_places("Is a cargo carrier allowed? Assamese? punjabi?"), [])


class PenaltyLockTests(Base):
    QUESTIONS = ["What is the fine for riding without a helmet?", "compounding fee for overspeeding",
                 "How many penalty points for drunk driving?", "Is there a challan for no PUC?",
                 "what's the punishment for drunk driving", "Can police seize my bike?"]

    def test_penalty_questions_are_locked_without_calling_model(self):
        for q in self.QUESTIONS:
            r = self.post(q)
            self.assertEqual(r.status_code, 200, q)
            self.assertEqual(r.json()["kind"], "restricted", q)
            self.assertEqual(r.json()["response"], srv.PENALTY_LOCKED_MESSAGE, q)
            self.assertEqual(r.json()["sources"], [], q)
        self.assertEqual(self.log, {})
        self.assertEqual(SEARCH_LOG, [])

    def test_lock_holds_even_when_index_missing(self):
        with mock.patch.dict(srv.INDEX_INFO, {"index": "missing"}):
            self.assertEqual(self.post(self.QUESTIONS[0]).json()["kind"], "restricted")

    def test_rewritten_follow_up_that_becomes_penalty_question_is_locked(self):
        srv.sessions["s"] = {"history": [{"question": "helmet rules", "answer": "Wear a helmet."}]}
        FAKE_LLM["fn"] = lambda p: "What is the fine for not wearing a helmet?" if "rewritten" in p else "x"
        r = self.post("and what happens if I don't?")
        self.assertEqual(r.json()["kind"], "restricted")

    def test_answer_drifting_into_penalties_is_withheld(self):
        self.use(answer="You must carry a licence; the penalty for not doing so is high.")
        r = self.post("Which documents must I carry?")
        self.assertEqual(r.json()["kind"], "restricted")
        self.assertEqual(srv.sessions["s"]["history"], [])

    def test_non_penalty_questions_are_not_locked(self):
        for q in ("How do I get a learner's licence?", "life tax for a new car", "documents to carry"):
            self.assertFalse(srv.is_penalty_question(q), q)

    def test_penalty_answers_need_the_enable_flag(self):
        with mock.patch.object(srv, "PENALTY_ANSWERS_ENABLED", True):
            self.use(answer="grounded answer")
            r = self.post(self.QUESTIONS[0])
        self.assertEqual(r.json()["kind"], "answer")

    def test_penalty_flag_alone_does_not_enable_answers(self):
        with mock.patch.dict(os.environ, {"TG_PENALTY_ANSWERS": "1", "TG_KB_APPROVED": ""}):
            self.assertFalse(srv.env_flag("TG_KB_APPROVED") and srv.env_flag("TG_PENALTY_ANSWERS"))


class PenaltyClassifierTests(unittest.TestCase):
    REQUIRED = [
        "How much do I pay if caught without a helmet?",
        "What happens if I drive without a licence?",
        "Consequences of drunk driving.",
        "What is the penality for this?",
        "What is the fien?",
        "Can police tow my vehicle?",
        "Can my licence be cancelled or disqualified?",
        "What happens if I am booked by police?",
        "What is the jurmana?",
        "What is the fine for riding without a helmet?",
    ]
    MORE_POSITIVE = [
        "panelty for no seatbelt", "penlty for overspeeding", "how many fines for jumping a red light",
        "I got fined yesterday, what now", "e-challan for wrong side driving", "chalan kitna hai",
        "compounding fee for overspeeding", "will I go to jail for drink and drive",
        "can they seize my bike", "my car got impounded", "will my DL get suspended",
        "suspension of licence for rash driving", "is my RC revoked if I don't pay tax",
        "what is the fine amount", "how much fine for no PUC", "the traffic fine for triple riding",
        "how much will I have to pay for not wearing a seat belt", "what if police stop me with no insurance",
        "any trouble if I drive with an expired licence?", "₹500 for no helmet?",
        "penalty points on my licence", "is driving without number plate an offence",
        "will I be punished for using a mobile phone while driving", "case booked against me for drunk driving",
    ]
    MULTILINGUAL = [
        "हेलमेट नहीं पहनने पर जुर्माना कितना है?", "चालान कैसे भरें", "बिना लाइसेंस के क्या सजा है",
        "హెల్మెట్ లేకపోతే జరిమానా ఎంత?", "చలాన్ ఎలా కట్టాలి", "jurmaana kitna hai", "helmet ke bina saza",
        "jarimana entha", "bike japtu chestara",
    ]
    NEGATIVE = [
        "How do I apply for a learner's licence?", "life tax for a new car", "documents to carry",
        "Is it fine to carry a digital copy of my RC?", "Is that fine?", "I'm fine, thanks",
        "Is it fine if I renew my licence online?", "Where can I read the fine print of the registration rules?",
        "How much is the life tax for a new two-wheeler?", "How much does vehicle registration cost?",
        "How do I renew an expired licence?", "How do I get a duplicate RC?",
        "What is the fee for a driving test?", "Which documents are needed to transfer ownership?",
        "What does a red signal mean?", "How do I register a vehicle bought in another district?",
        "Can I get a learner's licence online?", "What is the validity of a learner's licence?",
    ]

    def test_required_examples_are_locked(self):
        for q in self.REQUIRED:
            self.assertIsNotNone(srv.penalty_lock_reason(q), q)

    def test_paraphrases_and_misspellings_are_locked(self):
        for q in self.MORE_POSITIVE:
            self.assertIsNotNone(srv.penalty_lock_reason(q), q)

    def test_hindi_and_telugu_terms_are_locked(self):
        for q in self.MULTILINGUAL:
            self.assertIsNotNone(srv.penalty_lock_reason(q), q)

    def test_ordinary_questions_and_ordinary_fine_are_not_locked(self):
        for q in self.NEGATIVE:
            self.assertIsNone(srv.penalty_lock_reason(q), q)

    def test_reason_codes_name_the_rule(self):
        self.assertEqual(srv.penalty_lock_reason("జరిమానా"), "native_term")
        self.assertEqual(srv.penalty_lock_reason("what is the penalty"), "penalty_term")
        self.assertEqual(srv.penalty_lock_reason("what is the fine"), "fine_in_context")
        self.assertEqual(srv.penalty_lock_reason("can my licence be cancelled"), "licence_action")
        self.assertEqual(srv.penalty_lock_reason("consequences of drunk driving"), "consequence")
        self.assertEqual(srv.penalty_lock_reason("what happens if I drive without a licence"), "indirect_consequence")

    def test_empty_and_whitespace_are_not_locked(self):
        for q in ("", "   ", None):
            self.assertIsNone(srv.penalty_lock_reason(q))


class PenaltyLockFlowTests(Base):
    def test_every_required_example_is_locked_end_to_end_without_model_or_retrieval(self):
        for q in PenaltyClassifierTests.REQUIRED + PenaltyClassifierTests.MULTILINGUAL:
            r = self.post(q, sid="flow")
            self.assertEqual(r.json()["kind"], "restricted", q)
        self.assertEqual(self.log, {})
        self.assertEqual(SEARCH_LOG, [])

    def test_vague_follow_up_after_lock_is_locked_without_any_model_call(self):
        self.post("What is the fine for riding without a helmet?")
        for follow_up in ("and for a bike?", "what about cars", "same for a scooter?", "and if it is my first time?"):
            r = self.post(follow_up)
            self.assertEqual(r.json()["kind"], "restricted", follow_up)
        self.assertEqual(self.log, {})  # no rewrite, no answer
        self.assertEqual(SEARCH_LOG, [])

    def test_lock_is_checked_before_rewrite_even_with_history(self):
        srv.sessions["s"] = {"history": [{"question": "helmet rules", "answer": "Wear a helmet."}]}
        r = self.post("and the penality?")
        self.assertEqual(r.json()["kind"], "restricted")
        self.assertNotIn("rewrite", self.log)

    def test_self_contained_question_after_lock_is_answered_and_clears_lock(self):
        self.post("What is the fine for riding without a helmet?")
        r = self.post("How do I apply for a learner's licence in Hyderabad district?")
        self.assertEqual(r.json()["kind"], "answer")
        self.assertFalse(srv.sessions["s"]["last_locked"])
        self.assertEqual(self.post("and for a bike?").json()["kind"], "answer")

    def test_sticky_lock_is_per_session(self):
        self.post("What is the fine for riding without a helmet?", sid="a")
        self.assertEqual(self.post("and for a bike?", sid="b").json()["kind"], "answer")

    def test_drift_lock_makes_next_vague_follow_up_sticky(self):
        self.use(answer="You must carry a licence; the penalty for not doing so is high.")
        self.assertEqual(self.post("Which documents must I carry?").json()["kind"], "restricted")
        self.log.clear()
        self.assertEqual(self.post("and for a bike?").json()["kind"], "restricted")
        self.assertEqual(self.log, {})

    def test_lock_reason_is_logged_without_message_content(self):
        secret = "What is the fine for riding without a helmet near 12 Banjara Hills Road?"
        with self.assertLogs("knowyourrules.penalty_lock", level="INFO") as cm:
            self.post(secret, sid="private-session-id")
        line = "\n".join(cm.output)
        self.assertIn("stage=message", line)
        self.assertIn("reason=", line)
        self.assertNotIn("Banjara", line)
        self.assertNotIn("helmet", line)
        self.assertNotIn("private-session-id", line)

    def test_sticky_lock_is_logged_with_its_own_stage(self):
        self.post("What is the fine?")
        with self.assertLogs("knowyourrules.penalty_lock", level="INFO") as cm:
            self.post("and for a bike?")
        self.assertIn("stage=sticky_follow_up", cm.output[0])


class AnswerDriftTests(Base):
    DRIFT = [
        "₹1,000 is payable for riding without a helmet.",
        "Rs. 500 must be paid by the rider.",
        "An amount of 2000 rupees is levied on the owner.",
        "The rider is liable to pay five hundred rupees.",
        "Riders caught without a helmet pay Rs 1000.",
        "The vehicle may be towed away.",
    ]
    SAFE = [
        "Life tax of Rs. 5,000 is payable at the time of registration.",
        "A learner's licence must be carried while driving.",
        "The registration fee is ₹600 for a two-wheeler.",
        "Life tax is 12% of the cost; Rs. 500 minimum.",
        "Apply at the RTO with Form 2 and proof of address.",
    ]

    def test_monetary_penalty_statements_are_detected_without_keywords(self):
        for a in self.DRIFT:
            self.assertIsNotNone(srv.answer_drift_reason(a), a)

    def test_tax_fee_and_procedure_answers_are_not_drift(self):
        for a in self.SAFE:
            self.assertIsNone(srv.answer_drift_reason(a), a)

    def test_drifted_answer_is_withheld_end_to_end(self):
        for a in self.DRIFT:
            srv.sessions.clear()
            self.use(answer=a)
            r = self.post("Which documents must I carry?")
            self.assertEqual(r.json()["kind"], "restricted", a)
            self.assertEqual(r.json()["sources"], [], a)
            self.assertNotIn(a, r.json()["response"])

    def test_drift_is_logged_as_answer_stage(self):
        self.use(answer="Rs. 500 must be paid by the rider.")
        with self.assertLogs("knowyourrules.penalty_lock", level="INFO") as cm:
            self.post("Which documents must I carry?")
        self.assertIn("stage=answer_drift", cm.output[0])
        self.assertIn("reason=amount_obligation", cm.output[0])

    def test_penalty_answers_stay_disabled_by_default(self):
        self.assertFalse(srv.PENALTY_ANSWERS_ENABLED)
        self.assertFalse(self.client.get("/status").json()["penalty_answers"])


class AdversarialPenaltyLockTests(Base):
    """Regression cases from the adversarial review of the penalty lock."""

    CODE_MIXED_LOCK = [
        "helmet lekapothe entha kattali", "helmet lekunda vellithe em avtundi",
        "helmet nahi pehna toh kitna dena padega", "bina licence pakde gaye toh kya hoga",
        "traffic police pattukunte entha", "signal jump chesthe fine entha", "fine kitna hai", "kitna fine lagega",
        "హెల్మెట్ లేకపోతే ఎంత కట్టాలి", "హెల్మెట్ లేకుండా పట్టుకుంటే ఏమవుతుంది",
        "बिना हेलमेट पकड़े गए तो कितना देना होगा", "jurmaanaa", "challaan", "jarimaana entha",
    ]
    DISGUISED_LOCK = [
        "what do I owe for jumping a signal", "how much will it cost me if I'm caught speeding",
        "what's the charge for not wearing a helmet", "what fee do police collect for no helmet",
        "what amount for drunk driving", "cost of getting caught without insurance",
        "how much for riding without helmet", "Rs 1,000/- for no helmet?", "1000 INR for overspeeding?",
        "will police take my bike", "can they take away my licence", "can my vehicle be detained",
        "can i lose my licence for speeding", "fine?",
    ]
    ALLOW = [
        "How much is the tax if I buy a car without a loan", "what if I lose my RC",
        "how do I renew my driving licence", "documents for ownership transfer", "how to transfer RC to my name",
        "registration fee for a bike", "how much is road tax for an EV", "how much does a learner's licence cost",
        "what is the fee for a duplicate RC", "define motor vehicle", "what is meant by transport vehicle",
        "is it fine to drive with a learner's licence and an instructor", "fine, how do I register my car",
        "the RTO staff were fine", "what happens at the driving test", "what if I lose my licence card",
        "do I have to pay life tax again if I move districts",
    ]
    AMOUNT_FORMS = ["₹500", "Rs. 500", "INR 500", "500 rupees", "five hundred rupees", "Rs 1,000/-", "1000 INR"]
    DRIFT_LOCK = [
        "Life tax is 12% of cost. Riding without a helmet attracts Rs. 1,000.",
        "Registration fee is ₹600. If caught without a helmet, ₹1,000 is payable.",
        "A fee of Rs. 1,000 is charged if the rider has no helmet.",
        "An additional charge of ₹2,000 applies to riders without helmets.",
        "An additional fee of ₹2,000 applies to unhelmeted riders.",
        "The tax is Rs 500; for late payment of tax, Rs 2000 is additionally levied as a surcharge.",
        "The driver may be sent to prison for six months.", "The licence can be suspended for three months.",
        "The vehicle may be detained by the police.", "The rider can be taken into custody.",
        "Driving without a helmet attracts a charge of 1000 INR.",
    ]
    DRIFT_ALLOW = [
        "Life tax of Rs. 5,000 is payable at the time of registration.",
        "The test fee is Rs. 300 and the licence fee is Rs. 200.", "Fees for transfer of ownership are Rs. 150.",
        "The smart card fee is Rs. 200.", "A transport vehicle means a public service vehicle or goods carriage.",
    ]

    def test_code_mixed_and_native_questions_are_locked(self):
        for q in self.CODE_MIXED_LOCK:
            self.assertIsNotNone(srv.penalty_lock_reason(q), q)

    def test_disguised_and_indirect_questions_are_locked(self):
        for q in self.DISGUISED_LOCK:
            self.assertIsNotNone(srv.penalty_lock_reason(q), q)

    def test_procedure_tax_definition_and_harmless_fine_are_allowed(self):
        for q in self.ALLOW:
            self.assertIsNone(srv.penalty_lock_reason(q), q)

    def test_every_amount_form_is_recognised(self):
        for a in self.AMOUNT_FORMS:
            self.assertRegex(a, srv.AMOUNT, a)
            self.assertIsNotNone(srv.answer_drift_reason(f"{a} is collected."), a)
            self.assertIsNotNone(srv.penalty_lock_reason(f"{a} for no helmet?"), a)

    def test_bare_amount_answer_is_withheld(self):
        self.assertEqual(srv.answer_drift_reason("₹500"), "unexplained_amount")

    def test_tax_exemption_cannot_hide_a_penalty(self):
        for a in self.DRIFT_LOCK:
            self.assertIsNotNone(srv.answer_drift_reason(a), a)

    def test_tax_and_fee_answers_stay_allowed(self):
        for a in self.DRIFT_ALLOW:
            self.assertIsNone(srv.answer_drift_reason(a), a)

    def test_short_self_contained_question_after_lock_is_answered(self):
        for q in ("is a helmet required for pillion riders", "how do I renew my licence"):
            srv.sessions["s"] = {"history": [], "last_locked": True}
            self.assertEqual(self.post(q).json()["kind"], "answer", q)

    def test_vague_follow_ups_after_lock_stay_locked(self):
        for q in ("and for a bike?", "for cars?", "what about trucks", "how much for a scooter?", "aur car ke liye?",
                  "mari car ki?", "same?", "is it the same for cars?"):
            srv.sessions["s"] = {"history": [], "last_locked": True}
            self.assertEqual(self.post(q).json()["kind"], "restricted", q)
        self.assertEqual(self.log, {})

    def test_logs_contain_no_message_answer_session_or_credentials(self):
        with self.assertLogs("knowyourrules.penalty_lock", level="INFO") as cm:
            self.post("fine for no helmet GROQ_API_KEY=gsk_secret123", sid="sess-SECRET")
            self.use(answer="Rs. 500 must be paid by ANSWERTEXT.")
            self.post("Which documents must I carry while driving in Warangal today?", sid="sess-2")
        out = "\n".join(cm.output)
        for leaked in ("gsk_secret", "GROQ", "SECRET", "sess-2", "helmet", "ANSWERTEXT", "Warangal"):
            self.assertNotIn(leaked, out)
        self.assertEqual(len(cm.output), 2)


class AcceptancePenaltyLockTests(Base):
    """Regression cases from the final acceptance review of the penalty lock."""

    LOCK = [
        "licence lekunda drive chesthe emi chestharu", "seatbelt pettakapothe em avutundi",
        "drunk and drive lo pattukunte", "license nahi hai to police kya karegi",
        "लाइसेंस नहीं है तो क्या होगा", "ఫైన్ ఎంత", "फाइन कितना है",
        "helmet pettukokapothe entha fine", "bina helmet ke kitna lagta hai", "हेलमेट के बिना कितना फाइन",
        "లైసెన్స్ లేకుండా డ్రైవ్ చేస్తే ఏమవుతుంది", "Rupees five hundred for no helmet?",
    ]
    ALLOW = [
        "licence renewal ki emi documents kavali", "RC transfer kaise kare", "road tax entha", "registration fee kitna hai",
        "learner licence ela apply cheyali", "लाइसेंस कैसे बनवाएं", "లైసెన్స్ ఎలా పొందాలి", "life tax kitna hai car ka",
    ]
    DRIFT_LOCK = [
        "Three thousand is payable by the rider.", "fifteen hundred rupees is collected.", "1.5 lakh is payable.",
        "Life tax is Rs 5,000. Interest at 2% per month is charged on unpaid tax.",
        "Registration fee Rs 600; Rs 300 more if registration is not done within 7 days.",
        "Tax of Rs 5,000; failure to pay within the due date attracts Rs 1,000.",
        "Life tax ₹5,000. Riders without helmets pay ₹1,000 fee.",
        "The quarterly tax is Rs 500 and an extra 50% is collected when paid late.",
        "The licence fee is Rs 200, and the driver may be arrested.",
    ]
    DRIFT_ALLOW = [
        "Life tax is Rs 5,000 for two-wheelers costing up to Rs 50,000.", "The fee for a learner's licence test is Rs 150.",
    ]

    def test_new_code_mixed_and_native_questions_are_locked(self):
        for q in self.LOCK:
            self.assertIsNotNone(srv.penalty_lock_reason(q), q)

    def test_code_mixed_procedural_questions_are_allowed(self):
        for q in self.ALLOW:
            self.assertIsNone(srv.penalty_lock_reason(q), q)

    def test_tax_answers_cannot_hide_default_or_traffic_penalties(self):
        for a in self.DRIFT_LOCK:
            self.assertIsNotNone(srv.answer_drift_reason(a), a)
        for a in self.DRIFT_ALLOW:
            self.assertIsNone(srv.answer_drift_reason(a), a)

    def test_definitions_of_penalty_terms_stay_locked_by_design(self):
        for q in ("what is the meaning of compounding", "definition of offence"):
            self.assertIsNotNone(srv.penalty_lock_reason(q), q)

    def test_short_procedural_questions_after_lock_reach_the_answer_path(self):
        for q in ("is it mandatory to carry RC?", "RC transfer process", "documents for learner licence"):
            srv.sessions["s"] = {"history": [], "last_locked": True}
            self.assertEqual(self.post(q).json()["kind"], "answer", q)

    def test_referential_and_one_word_follow_ups_stay_locked_without_groq(self):
        for q in ("is it valid in Hyderabad?", "can I pay road tax online there?", "licence?", "ok thanks", "inka car ki?"):
            srv.sessions["s"] = {"history": [], "last_locked": True}
            self.assertEqual(self.post(q).json()["kind"], "restricted", q)
        self.assertEqual(self.log, {})

    def test_approval_flags_are_the_only_unlock(self):
        self.assertFalse(srv.KB_APPROVED)
        self.assertFalse(srv.PENALTY_ANSWERS_ENABLED)
        with mock.patch.object(srv, "KB_APPROVED", True):  # approval alone does not unlock penalties
            self.assertEqual(self.post("What is the fine?").json()["kind"], "restricted")


class MissingProvisionGuardTests(Base):
    """Explicit references to rules absent from the index are answered deterministically (catalogue modelled
    on the preview index: TMVR has 185, 187, 188, 80A but not 186; TMVTR has rules 1-17 with 13A/13B)."""

    CATALOGUE = {"Rule 185": {"tmvr-1989-chap-5"}, "Rule 187": {"tmvr-1989-chap-5"}, "Rule 188": {"tmvr-1989-chap-5"},
                 "Rule 80A": {"tmvr-1989-chap-4"}, "Rule 12": {"tmvr-1989-chap-2", "tmvtr-1963"},
                 "Rule 13A": {"tmvtr-1963"}, "Rule 13B": {"tmvtr-1963"}, "Rule 81": {"tmvr-1989-chap-4"}}

    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(srv.PROVISION_CATALOGUE, self.CATALOGUE, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def assert_missing(self, message, missing):
        r = self.post(message).json()
        self.assertEqual(r["kind"], "missing_provision", message)
        for ref in missing:
            self.assertIn(ref, r["response"], message)
        self.assertEqual(r["sources"], [], message)
        return r

    def test_direct_and_phrased_references_to_a_missing_rule(self):
        for q in ("Rule 186", "rules 186", "TMVR Rule 186", "What does Rule 186 say?", "Explain Rule 186",
                  "explain rule no. 186 of the Telangana Motor Vehicles Rules", "and rule 186?"):
            self.assert_missing(q, ["Rule 186"])
        self.assertEqual(self.log, {})          # no rewrite, no answer: no model call at all
        self.assertEqual(SEARCH_LOG, [])        # and no retrieval

    def test_valid_references_are_not_blocked(self):
        for q in ("What does Rule 188 say?", "Explain rule 185", "rule 187 conditions", "Rule 80A", "rule 81(3)",
                  "TMVTR Rule 13-A", "Taxation Rules rule 13B"):
            self.assertEqual(self.post(q).json()["kind"], "answer", q)

    def test_multiple_references_never_drop_the_missing_one(self):
        r = self.assert_missing("Compare rules 185, 186 and 187", ["Rule 186"])
        self.assertIn("Rule 185, Rule 187 are available", r["response"])
        self.assert_missing("rules 185 to 188", ["Rule 186"])
        self.assert_missing("Rule 188 and Rule 999", ["Rule 999"])
        self.assertEqual(srv.missing_rule_references("rules 186 and 190"), (["Rule 186", "Rule 190"], []))

    def test_instrument_scope(self):
        self.assert_missing("TMVTR rule 185", ["Rule 185"])          # 185 exists only in the TMVR
        self.assertEqual(self.post("TMVR rule 12").json()["kind"], "answer")
        self.assertEqual(self.post("Taxation Rules rule 12").json()["kind"], "answer")
        self.assert_missing("Motor Vehicles Rules rule 13A", ["Rule 13A"])

    def test_ordinary_numbers_and_sub_rules_are_not_provision_references(self):
        for q in ("How much is life tax on a 2 wheeler costing 50000?", "documents for 186 cc bike registration",
                  "Is sub-rule 186 relevant?", "what are the rules of the road", "under the rules, how many days?",
                  "registration for vehicles over 186 kg"):
            self.assertEqual(srv.rule_references(q) if "sub-rule" not in q else [], [], q)
            self.assertEqual(self.post(q).json()["kind"], "answer", q)

    def test_reference_parsing(self):
        self.assertEqual(srv.rule_references("rules 185, 186 & 187"), ["Rule 185", "Rule 186", "Rule 187"])
        self.assertEqual(srv.rule_references("rule 12-A and rule 13 b"), ["Rule 12A", "Rule 13B"])
        self.assertEqual(srv.rule_references("Rule 5 A person shall apply"), ["Rule 5"])
        self.assertEqual(srv.rule_references("rule 81(3) and sub-rule 2"), ["Rule 81"])
        self.assertEqual(srv.rule_references("rules 1 to 100"), ["Rule 1", "Rule 100"])  # long ranges not expanded

    def test_penalty_lock_still_runs_first(self):
        r = self.post("What is the fine under Rule 186?").json()
        self.assertEqual(r["kind"], "restricted")

    def test_guard_is_off_without_provision_metadata(self):
        with mock.patch.dict(srv.PROVISION_CATALOGUE, {}, clear=True):
            self.assertEqual(self.post("What does Rule 186 say?").json()["kind"], "answer")


class RelevanceGateTests(Base):
    def setUp(self):
        super().setUp()
        self.use(answer="grounded answer")

    def ask(self):
        return self.post("How do I apply for a learner's licence?")

    def assert_fallback(self, r):
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["kind"], "no_support")
        self.assertEqual(r.json()["response"], srv.NO_SUPPORT_MESSAGE)
        self.assert_no_model_answer()

    def test_relevant_chunks_allow_answer_generation(self):
        r = self.ask()
        self.assertEqual(r.json()["response"], "grounded answer")
        self.assertIn("Learner's licence application", self.log["answer"][-1])

    def test_irrelevant_chunks_trigger_fallback(self):
        FAKE_SEARCH["fn"] = lambda q, state, docs: [(d, 1.4) for d in docs]
        self.assert_fallback(self.ask())

    def test_empty_retrieval_triggers_fallback(self):
        FAKE_SEARCH["fn"] = lambda q, state, docs: []
        self.assert_fallback(self.ask())

    def test_missing_or_malformed_scores_are_never_treated_as_relevant(self):
        def malformed(q, state, docs):
            d = docs[0]
            return [(d, None), (d, float("nan")), (d, float("inf")), (d, "0.1"), (d, True), (d,), "garbage",
                    (None, 0.1), (Document(page_content="", metadata=d.metadata), 0.1), None]
        FAKE_SEARCH["fn"] = malformed
        self.assert_fallback(self.ask())

    def test_none_result_list_triggers_fallback(self):
        FAKE_SEARCH["fn"] = lambda q, state, docs: None
        self.assert_fallback(self.ask())

    def test_only_chunks_within_threshold_reach_the_prompt(self):
        FAKE_SEARCH["fn"] = lambda q, state, docs: [(docs[0], 0.3), (docs[1], 1.4)]
        self.ask()
        prompt = self.log["answer"][-1]
        self.assertIn("Learner's licence application", prompt)
        self.assertNotIn("Life tax schedule", prompt)

    def test_threshold_is_inclusive_and_configurable(self):
        doc = CORPUS[0]
        with mock.patch.object(srv, "MAX_DISTANCE", 0.5):
            self.assertEqual(srv.relevant_docs([(doc, 0.5)]), [doc])
            self.assertEqual(srv.relevant_docs([(doc, 0.51)]), [])

    def test_threshold_setting_is_parsed_safely(self):
        for raw in (None, "", "abc", "-1", "0", "nan", "inf"):
            self.assertEqual(srv.parse_max_distance(raw), srv.DEFAULT_MAX_DISTANCE, raw)
        self.assertEqual(srv.parse_max_distance("0.7"), 0.7)


class ResponseShapeTests(Base):
    def test_answer_has_kind_sources_and_approval_flag(self):
        r = self.post("How do I apply for a learner's licence?").json()
        self.assertEqual(set(r), {"response", "kind", "sources", "kb_approved"})
        self.assertEqual(r["kind"], "answer")
        self.assertFalse(r["kb_approved"])
        self.assertEqual([s["file"] for s in r["sources"]], [TG_RULES_FILE, TG_TAX_FILE])

    def test_unlisted_sources_are_marked_unverified(self):
        r = self.post("How do I apply for a learner's licence?").json()
        self.assertTrue(all(not s["verified"] and s["title"] == "Unverified source" for s in r["sources"]))

    def test_listed_sources_carry_verified_title(self):
        # Changed for hash-based verification: SOURCES is keyed by the document's SHA-256, not its file name.
        with mock.patch.dict(srv.SOURCES, {TG_RULES_SHA: ("The Telangana Motor Vehicles Rules, 1989", "Rules")}):
            r = self.post("How do I apply for a learner's licence?").json()
            prompt = self.log["answer"][-1]
        self.assertEqual(r["sources"][0], {"title": "The Telangana Motor Vehicles Rules, 1989", "instrument": "Rules",
                                           "verified": True, "file": TG_RULES_FILE, "sha256": TG_RULES_SHA})
        self.assertIn("Source: The Telangana Motor Vehicles Rules, 1989 (Rules)", prompt)
        self.assertIn("Unverified source", prompt)  # the second, unlisted file

    def test_provider_failure_returns_503(self):
        self.use(fail=True)
        r = self.post("How do I apply for a learner's licence?")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["detail"], srv.PROVIDER_ERROR)

    def test_history_is_kept_and_capped(self):
        for i in range(srv.MAX_HISTORY_TURNS + 2):
            self.post(f"licence question {i}")
        self.assertEqual(len(srv.sessions["s"]["history"]), srv.MAX_HISTORY_TURNS)
        self.assertIn("rewrite", self.log)


class StaticFrontendTests(unittest.TestCase):
    def test_index_and_sanitizing_renderer_are_served(self):
        client = TestClient(srv.app)
        index, render = client.get("/"), client.get("/static/render.js")
        self.assertEqual((index.status_code, render.status_code), (200, 200))
        self.assertIn('src="/static/render.js"', index.text)
        self.assertIn("Telangana Traffic Rules Assistant", index.text)
        self.assertIn("DOMPurify.sanitize", render.text)
        self.assertIn("javascript", render.headers["content-type"])


class PenaltyNoteTests(unittest.TestCase):
    def test_amounts_in_digits_get_note(self):
        for text in ["Life tax of ₹1,000 applies.", "Pay Rs. 500.", "INR 2000 is payable."]:
            self.assertTrue(srv.with_penalty_note(text).endswith(srv.PENALTY_NOTE), text)

    def test_amounts_in_words_get_note(self):
        for text in ["one thousand rupees", "five hundred rupees", "two lakh"]:
            self.assertTrue(srv.with_penalty_note(text).endswith(srv.PENALTY_NOTE), text)

    def test_non_money_answer_is_unchanged(self):
        text = "A learner's licence must be carried while driving."
        self.assertEqual(srv.with_penalty_note(text), text)

    def test_note_does_not_claim_text_is_outdated(self):
        self.assertNotIn("outdated", srv.PENALTY_NOTE.lower())
        self.assertIn("has not been verified", srv.PENALTY_NOTE)

    def test_tax_answer_with_amount_gets_note_in_response_not_history(self):
        client = TestClient(srv.app)
        srv.sessions.clear()
        FAKE_LLM["fn"] = fake_llm(answer="Life tax is 12% of the cost; Rs. 500 minimum.")
        r = client.post("/chat", json={"message": "life tax for a two-wheeler", "session_id": "t"})
        self.assertTrue(r.json()["response"].endswith(srv.PENALTY_NOTE))
        self.assertNotIn(srv.PENALTY_NOTE, srv.sessions["t"]["history"][-1]["answer"])


if __name__ == "__main__":
    unittest.main()
