"""End-to-end tests of the release gates, Section 200(1) disclosure and offence-date routing inside POST /chat.

Offline. Everything signed or "approved" here is a SYNTHETIC fixture with a throwaway in-memory key (the same
harness as test_legal_approval); none of it is, or may be used as, a real legal approval, and the rule matrix is
the synthetic one from test_release_gates, not the counsel-approved matrix. Without an approval file the
expected behaviour is fail-closed, and most tests below run exactly that way.

Run from the project root:  python -m unittest discover -s tests -p "test_chat_release_gates.py" -v
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from langchain_core.documents import Document

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_legal_approval as tla  # noqa: E402
import test_release_gates as trg  # noqa: E402
import test_server as ts  # noqa: E402
from backend import chat_guards as cg  # noqa: E402
from backend import offence_date as od  # noqa: E402
from backend import release_gates as rg  # noqa: E402

POST = "2026-09-01"       # after 15 Aug 2026
BETWEEN = "2022-03-10"    # 2019-09-01 .. 2026-08-14
OLD = "2018-05-01"        # before 2019-09-01
ORDINARY = "How do I apply for a learner's licence?"


def chunk(text, provision, **meta):
    base = {"state": "Telangana", "source_file": ts.TG_RULES_FILE, "sha256": ts.TG_RULES_SHA,
            "provision_id": provision, "manifest_id": "tmvr-1989-chap-2", "part": 1, "parts": 1, "title": "Synthetic Motor Rules"}
    base.update(meta)
    return Document(page_content=text, metadata=base)


class ChatBase(ts.Base):
    """The shared fake-backed server (no approval record: every gate blocked) plus helpers."""

    def post_dated(self, message, offence_date=None, sid="s"):
        body = {"message": message, "session_id": sid}
        if offence_date is not None:
            body["offence_date"] = offence_date
        return self.client.post("/chat", json=body)

    def assert_untouched(self):
        """Nothing was retrieved and no model was called."""
        self.assertEqual(ts.SEARCH_LOG, [])
        self.assertEqual(self.log, {})

    def serve(self, *docs):
        ts.FAKE_SEARCH["fn"] = lambda q, state, _docs: [(d, 0.3) for d in docs]


class FailClosedWithoutApprovalTests(ChatBase):
    """No signed approval on this checkout: every gated area is refused before retrieval or any model call."""

    def test_every_gate_is_blocked_on_this_server(self):
        body = self.client.get("/release-gates").json()
        self.assertTrue(all(v == rg.BLOCKED for v in body["gates"].values()), body)

    def test_section_200_question_is_refused_not_answered(self):
        for q in ("Is section 189 compoundable?", "Is section 185 listed in Section 200(1)?"):
            with self.subTest(q):
                r = self.post_dated(q, POST).json()
                self.assertEqual(r["kind"], "restricted")
                self.assertEqual(r["response"], ts.srv.PENALTY_LOCKED_MESSAGE)
                self.assertNotIn("listed in Section 200(1)", r["response"])
                self.assertNotIn("not included", r["response"])
        self.assert_untouched()

    def test_compounding_amounts_are_refused(self):
        for q in ("How much is the compounding fee for section 189?", "What amount can I pay to compound section 184?"):
            with self.subTest(q):
                r = self.post_dated(q, POST).json()
                self.assertEqual((r["kind"], r["response"]), ("restricted", ts.srv.PENALTY_LOCKED_MESSAGE))
        self.assert_untouched()

    def test_fine_and_penalty_questions_stay_locked_even_if_the_flag_is_forced_on(self):
        with mock.patch.object(ts.srv, "PENALTY_ANSWERS_ENABLED", True):
            r = self.post_dated("What is the fine for riding without a helmet?").json()
        self.assertEqual(r["kind"], "restricted")
        self.assertIn("Penalties and compounding fees are not available", r["response"])
        self.assert_untouched()

    def test_follow_up_to_a_compounding_turn_stays_locked(self):
        self.post_dated("Is section 189 compoundable?", POST)
        r = self.post_dated("and for a bike?").json()
        self.assertEqual(r["kind"], "restricted")

    def test_litigation_cmvr_and_central_explanations_are_refused(self):
        for q in ("How do I file a case against the RTO in court?",
                  "Explain the CMVR procedure for registering a vehicle",
                  "Explain section 129 of the Motor Vehicles Act"):
            with self.subTest(q):
                r = self.post_dated(q).json()
                self.assertEqual(r["kind"], "restricted")
                self.assertIn("isn't available yet", r["response"])
        self.assert_untouched()

    def test_earlier_offence_dates_are_refused_before_retrieval(self):
        for date in (OLD, BETWEEN):
            with self.subTest(date):
                r = self.post_dated(ORDINARY, date).json()
                self.assertEqual(r["kind"], "restricted")
                self.assertIn("earlier offence date", r["response"])
        self.assert_untouched()

    def test_unusable_dates_are_refused_never_ignored(self):
        for bad in ("tomorrow", "2026-13-40", "31/12/2999", "٢٠٢٦-٠٩-٠١", "1980-01-01", "x" * 40):
            with self.subTest(bad):
                r = self.post_dated(ORDINARY, bad)
                self.assertEqual(r.status_code if r.status_code != 200 else r.json()["kind"], "clarification" if r.status_code == 200 else 422)
        self.assert_untouched()


class OrdinaryQuestionsStillWorkTests(ChatBase):
    def test_undated_ordinary_question_is_answered_as_before(self):
        self.use(answer="Apply in Form 2.")
        r = self.post_dated(ORDINARY).json()
        self.assertEqual(r["kind"], "development")
        self.assertEqual((r["offence_date"], r["law_band"], r["notes"]), (None, None, []))
        self.assertTrue(r["sources"])

    def test_undated_question_is_answered_even_from_unversioned_chunks(self):
        self.serve(chunk("Rule 5. Learner's licence application.", "Rule 5"))  # no valid_from / valid_to
        self.use(answer="Apply in Form 2.")
        self.assertEqual(self.post_dated(ORDINARY).json()["kind"], "development")
        self.assertIn("answer", self.log)

    def test_ordinary_central_citation_question_is_not_blocked_by_the_cmvr_gate(self):
        # Telangana documents that cite a Central rule are still answered from those documents (existing behaviour).
        self.assertFalse(cg.CMVR_RE.search(ORDINARY))


class OffenceDateRoutingTests(ChatBase):
    """Retrieval honours each chunk's own validity range. Unversioned or malformed chunks are never law for the date."""

    CURRENT = chunk("Rule 5. CURRENT-TEXT learner's licence rule.", "Rule 5", valid_from=20260815, valid_to=od.OPEN_ENDED)
    OLDER = chunk("Rule 5. OLDER-TEXT learner's licence rule.", "Rule 5 (old)", valid_from=20190901, valid_to=20260814)
    UNVERSIONED = chunk("Rule 5. UNVERSIONED-TEXT learner's licence rule.", "Rule 5 (u)")

    def ask(self, *docs, date=POST, answer="Apply in Form 2."):
        self.serve(*docs)
        self.use(answer=answer)
        return self.post_dated(ORDINARY, date).json()

    def prompt(self):
        return self.log["answer"][0]

    def test_dated_chunk_is_used_and_the_response_carries_the_date_and_band(self):
        r = self.ask(self.CURRENT)
        self.assertEqual(r["kind"], "development")
        self.assertEqual((r["offence_date"], r["law_band"]), (POST, od.BAND_POST_2026))
        self.assertIn("CURRENT-TEXT", self.prompt())

    def test_only_the_chunk_valid_on_the_date_reaches_the_model(self):
        r = self.ask(self.CURRENT, self.OLDER, self.UNVERSIONED)
        self.assertIn("CURRENT-TEXT", self.prompt())
        self.assertNotIn("OLDER-TEXT", self.prompt())
        self.assertNotIn("UNVERSIONED-TEXT", self.prompt())
        self.assertEqual(r["kind"], "development")
        self.assertIn(od.UNVERSIONED_NOTE, r["response"])
        self.assertEqual(r["notes"], [od.UNVERSIONED_NOTE])

    def test_unversioned_chunks_alone_are_refused_for_a_dated_question(self):
        r = self.ask(self.UNVERSIONED)
        self.assertEqual(r["kind"], "no_support")
        self.assertIn(POST, r["response"])
        self.assertIn("can't confirm the law", r["response"])
        self.assertNotIn("answer", self.log)  # no model call
        self.assertEqual(r["sources"], [])

    def test_malformed_validity_metadata_is_never_evidence(self):
        bad = {"inverted": dict(valid_from=20300101, valid_to=20200101),
               "strings": dict(valid_from="2026-08-15", valid_to="9999-12-31"),
               "half": dict(valid_from=20260815),
               "bool": dict(valid_from=True, valid_to=True),
               "bad calendar": dict(valid_from=20261340, valid_to=od.OPEN_ENDED)}
        for name, meta in bad.items():
            with self.subTest(name):
                self.log.clear()
                r = self.ask(chunk("Rule 5. BAD-TEXT.", "Rule 5", **meta))
                self.assertEqual(r["kind"], "no_support")
                self.assertNotIn("answer", self.log)

    def test_chunk_that_does_not_cover_the_date_is_refused(self):
        self.assertEqual(self.ask(self.OLDER)["kind"], "no_support")
        self.assertNotIn("answer", self.log)

    def test_validity_range_is_inclusive_at_both_ends(self):
        for meta in (dict(valid_from=20260901, valid_to=od.OPEN_ENDED), dict(valid_from=20260101, valid_to=20260901)):
            with self.subTest(meta):
                self.log.clear()
                self.assertEqual(self.ask(chunk("Rule 5. EDGE-TEXT.", "Rule 5", **meta))["kind"], "development")
                self.assertIn("EDGE-TEXT", self.prompt())
        self.log.clear()
        self.assertEqual(self.ask(chunk("Rule 5. EDGE-TEXT.", "Rule 5", valid_from=20260902, valid_to=od.OPEN_ENDED))["kind"],
                         "no_support")

    def test_date_comes_only_from_the_field_never_the_message(self):
        # The message names a date; with no field, no date-specific claim is made and nothing is date-routed.
        self.serve(self.UNVERSIONED)
        self.use(answer="ok")
        r = self.post_dated("Under the rules in force on 2026-09-01, " + ORDINARY).json()
        self.assertEqual((r["kind"], r["offence_date"]), ("development", None))


class Section200DisclosureTests(unittest.TestCase):
    """Synthetic matrix through the real gates. record="valid" only means the penalty switch is set on in the test."""

    start = tla.ServerApprovalTests.start
    matrix_path = trg.ReleaseGateEndpointTests.matrix_path

    def server(self, record="valid", matrix=None, no_matrix=False):
        env = {}
        if no_matrix:
            env["TG_RULE_MATRIX_FILE"] = str(Path(tempfile.gettempdir()) / "definitely-missing-rule-matrix.json")
        else:
            env["TG_RULE_MATRIX_FILE"] = str(self.matrix_path(matrix))
        rec = tla.synthetic_record(penalty_answers_approved=True) if record == "valid" else record
        self.srv, self.client = self.start(rec, extra_env=env)
        self.assertEqual(self.client.get("/status").json()["approval"], "not_required")   # no record is read or needed
        # Nothing in production can switch penalty answers on (the signed record that used to is gone). Section 200 replies need
        # the penalty gate open, so the "valid" cases set the switch directly, as a test double for a deliberate future enable.
        self.srv.PENALTY_ANSWERS_ENABLED = (record == "valid")

    def ask(self, message, date=None):
        ts.SEARCH_LOG.clear()
        ts.FAKE_LLM["fn"] = ts.fake_llm(answer="MODEL-SHOULD-NOT-BE-CALLED")
        body = {"message": message, "session_id": "s"}
        if date:
            body["offence_date"] = date
        r = self.client.post("/chat", json=body).json()
        self.assertEqual(ts.SEARCH_LOG, [], "Section 200 replies are deterministic: no retrieval")
        self.assertNotIn("MODEL-SHOULD-NOT-BE-CALLED", r["response"])
        return r

    def test_listed_provision_is_disclosed_with_its_caveat_and_no_amount(self):
        self.server()
        r = self.ask("Is section 189 compoundable?", POST)
        self.assertEqual(r["kind"], "answer")
        self.assertIn("189 is listed in Section 200(1)", r["response"])
        self.assertIn(rg.LISTED_CAVEAT, r["response"])
        self.assertEqual((r["offence_date"], r["law_band"]), (POST, od.BAND_POST_2026))
        self.assertNotRegex(r["response"], r"(?i)₹|\brs\b|rupee|\binr\b")

    def test_not_listed_uses_the_required_phrase_and_caveat(self):
        self.server()
        r = self.ask("Is section 185 listed in Section 200(1)?", POST)
        self.assertEqual(r["kind"], "answer")
        self.assertIn(rg.NOT_LISTED_PHRASE, r["response"])
        self.assertIn(rg.NOT_LISTED_CAVEAT, r["response"])
        self.assertEqual(rg.phrasing_problems(r["response"]), [])

    def test_repeat_offence_conditions(self):
        self.server()
        unknown = self.ask("Is section 190(2)(i) compoundable?", POST)["response"]
        self.assertIn("only for a second or subsequent offence", unknown)
        self.assertIn("whether this is one was not stated", unknown)
        repeat = self.ask("Is section 192 compoundable if I did it again?", POST)["response"]
        self.assertIn("192 is listed in Section 200(1).", repeat)
        # "second offence" reads as penalty vocabulary to the classifier, so it is refused rather than interpreted.
        self.assertEqual(self.ask("Is section 192 compoundable for a second offence?", POST)["kind"], "restricted")

    def test_no_offence_date_asks_for_it(self):
        self.server()
        r = self.ask("Is section 189 compoundable?")
        self.assertEqual(r["kind"], "clarification")
        self.assertIn(od.DATE_REQUIRED_NOTE, r["response"])
        self.assertNotIn("is listed", r["response"])

    def test_offence_before_commencement_is_not_answered_from_the_new_list(self):
        self.server()
        for date in (BETWEEN, "2026-08-14"):
            with self.subTest(date):
                r = self.ask("Is section 189 compoundable?", date)
                self.assertEqual(r["kind"], "no_support")
                self.assertNotIn("is listed", r["response"])
                self.assertNotIn(rg.NOT_LISTED_PHRASE, r["response"])
        self.assertEqual(self.ask("Is section 189 compoundable?", "2026-08-15")["kind"], "answer")

    def test_unclear_provision_is_never_read_as_not_listed(self):
        self.server()
        self.assertEqual(self.ask("Is it compoundable?", POST)["kind"], "clarification")
        for q in ("Are sections 184 and 189 compoundable?", "Is section 184, 189 compoundable?"):
            self.assertEqual(self.ask(q, POST)["kind"], "clarification", q)

    def test_amounts_stay_refused_even_with_the_penalty_switch_on_and_a_permissive_matrix(self):
        self.server()
        for q in ("How much is the compounding fee for section 189?", "Is section 189 compoundable and what is the penalty?",
                  "Section 189 compounding amount"):
            with self.subTest(q):
                r = self.ask(q, POST)
                self.assertEqual(r["kind"], "restricted")
                self.assertNotIn("is listed", r["response"])
        body = self.client.get("/release-gates").json()["gates"]
        self.assertEqual((body[rg.TG_FINE], body[rg.TG_COMPOUNDING]), (rg.BLOCKED, rg.BLOCKED))

    def test_fine_questions_stay_locked_with_the_penalty_switch_on(self):
        self.server()
        r = self.ask("What is the fine for riding without a helmet?")
        self.assertEqual(r["kind"], "restricted")

    def test_penalty_switch_off_means_refusal_even_with_a_matrix_on_disk(self):
        self.server(record=None)
        r = self.ask("Is section 189 compoundable?", POST)
        self.assertEqual(r["kind"], "restricted")
        self.assertNotIn("is listed", r["response"])

    def test_a_record_that_approves_penalty_answers_changes_nothing(self):
        self.server(record=tla.synthetic_record(penalty_answers_approved=True))
        self.assertEqual(self.ask("Is section 189 compoundable?", POST)["kind"], "restricted")

    def test_missing_matrix_refuses(self):
        self.server(no_matrix=True)
        self.assertEqual(self.ask("Is section 189 compoundable?", POST)["kind"], "restricted")

    def test_incomplete_matrix_never_yields_not_listed(self):
        data = trg.synthetic_matrix()
        data["section_200_post_2026_08_15_rules"][0]["verification_status"] = "UNVERIFIED"
        self.server(matrix=data)
        r = self.ask("Is section 185 listed in Section 200(1)?", POST)
        self.assertEqual(r["kind"], "restricted")
        self.assertNotIn(rg.NOT_LISTED_PHRASE, r["response"])

    def test_matrix_that_blocks_the_penalty_gate_refuses(self):
        data = trg.synthetic_matrix()
        data["feature_release_gates"][rg.CENTRAL_PENALTY] = "BLOCKED"
        self.server(matrix=data)
        self.assertEqual(self.ask("Is section 189 compoundable?", POST)["kind"], "restricted")

    def test_other_gated_areas_follow_the_matrix(self):
        self.server()
        # CENTRAL_EXPLANATION and CMVR/HISTORICAL are open in the synthetic matrix; LITIGATION is "BOGUS" => blocked.
        self.assertEqual(self.ask("Can I challenge this challan in court?")["kind"], "restricted")
        gates = self.client.get("/release-gates").json()["gates"]
        self.assertNotEqual(gates[rg.CENTRAL_EXPLANATION], rg.BLOCKED)
        self.assertEqual(gates[rg.LITIGATION], rg.BLOCKED)


class GroundedDatedTests(ts.Base):
    """Grounded mode (the production mode) with an offence date: cache bypassed, no model call without dated evidence.
    The approval is an in-memory test object, as in test_server's grounded tests; no record or signature is created."""

    ELIGIBLE = ts.GroundedAnswerIntegrationTests.ELIGIBLE
    CLAIM = ts.GroundedAnswerIntegrationTests.CLAIM
    QUESTION = ts.GroundedAnswerIntegrationTests.QUESTION
    patch = ts.GroundedAnswerIntegrationTests.patch
    record = ts.GroundedAnswerIntegrationTests.record
    approve = ts.GroundedAnswerIntegrationTests.approve

    def setUp(self):
        super().setUp()
        from backend import grounded_answer, legal_approval
        self.ga, self.la = grounded_answer, legal_approval
        ts.FAKE_SEARCH["fn"] = lambda q, s, docs: [(self.ELIGIBLE, 0.3)]

        def trap(prompt):
            raise AssertionError("unexpected legacy model call")
        ts.FAKE_LLM["fn"] = trap
        self.mock = grounded_answer.MockGenerator(json.dumps({
            "answer": self.CLAIM, "evidence_sufficiency": "sufficient",
            "claims": [{"text": self.CLAIM, "kind": "direct", "evidence_ids": ["E1"]}],
            "citations": ["E1"], "refusal_reason": None, "clarification_question": None}))

    def dated(self, validity, date=POST):
        meta = dict(self.ELIGIBLE.metadata, **validity)
        doc = Document(page_content=self.ELIGIBLE.page_content, metadata=meta)
        ts.FAKE_SEARCH["fn"] = lambda q, s, docs: [(doc, 0.3)]
        self.approve()
        return self.client.post("/chat", json={"message": self.QUESTION, "session_id": "g", "offence_date": date}).json()

    def test_dated_chunk_is_answered_with_citations_and_date_fields(self):
        r = self.dated(dict(valid_from=20260815, valid_to=od.OPEN_ENDED))
        self.assertEqual(r["kind"], "answer", r)
        self.assertEqual((r["offence_date"], r["law_band"]), (POST, od.BAND_POST_2026))
        self.assertEqual(len(self.mock.calls), 1)

    def test_unversioned_chunk_is_refused_without_calling_the_generator(self):
        r = self.dated({})
        self.assertEqual(r["kind"], "no_support")
        self.assertIn("can't confirm the law", r["response"])
        self.assertEqual(self.mock.calls, [])

    def test_dated_question_bypasses_the_answer_cache(self):
        with mock.patch.object(ts.srv, "cache_begin", side_effect=AssertionError("cache must not be used")):
            r = self.dated(dict(valid_from=20260815, valid_to=od.OPEN_ENDED))
        self.assertEqual(r["kind"], "answer", r)

    def test_undated_question_is_unchanged(self):
        self.approve()
        r = self.client.post("/chat", json={"message": self.QUESTION, "session_id": "g"}).json()
        self.assertEqual(r["kind"], "answer", r)
        self.assertIsNone(r["offence_date"])


class GuardUnitTests(unittest.TestCase):
    def test_provisions_in(self):
        self.assertEqual(cg.provisions_in("is section 182a(3) compoundable"), ["182A(3)"])
        self.assertEqual(cg.provisions_in("Sec. 190(2)(i) and s.192"), ["190(2)(i)", "192"])
        self.assertEqual(cg.provisions_in("fine of Rs. 500 under 184"), [])
        self.assertEqual(cg.provisions_in("sub-rule (2) of rule 5"), [])

    def test_evaluate_with_everything_blocked_never_discloses(self):
        report = rg.effective_gates(None, False)
        for q in ("Is section 189 compoundable?", "section 200(1)", "Is 185 compoundable?"):
            g = cg.evaluate(q, None, report, None)
            self.assertEqual((g.kind, g.gate), ("restricted", rg.CENTRAL_PENALTY), q)

    def test_non_gated_message_returns_none(self):
        report = rg.effective_gates(None, False)
        self.assertIsNone(cg.evaluate(ORDINARY, None, report, None))
        self.assertIsNone(cg.evaluate(ORDINARY, None, report, __import__("datetime").date(2026, 9, 1)))


if __name__ == "__main__":
    unittest.main()
