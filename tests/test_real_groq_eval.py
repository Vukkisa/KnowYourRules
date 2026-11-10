"""The opt-in real-model evaluation runner (backend/real_groq_eval.py), with every provider call mocked. No test here
can reach Groq: groq.Groq is patched to fail for the whole module except in the transport tests, which use an
httpx MockTransport, and the network is blocked while the runner's command line runs."""

import contextlib
import copy
import io
import json
import logging
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import groq
import httpx

from backend import answer_quality_eval as aq
from backend import real_groq_eval as rge

SERVER = None
CASES, PASSAGES = rge.load_cases()
BY_ID = {c["id"]: c for c in CASES}
FAKE_KEY = "gsk_TESTONLYnotarealkey0123456789"
REQ = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
_REAL_GROQ = groq.Groq


def setUpModule():
    global SERVER, _patch
    SERVER, _calls = aq.load_pipeline()
    _patch = mock.patch.object(groq, "Groq", side_effect=AssertionError("a real Groq client was created"))
    _patch.start()


def tearDownModule():
    _patch.stop()


def mocks(cid):
    return copy.deepcopy(BY_ID[cid]["sample_mock_responses"])


def run(case_ids, script, *, max_calls=28, max_tokens=150_000, max_completion=200):
    client = rge.ScriptedClient(script)
    adapter = rge.GroqAdapter(client, rge.Budget(max_calls, max_tokens), max_completion_tokens=max_completion)
    records = rge.run_all([BY_ID[i] for i in case_ids], PASSAGES, adapter, server=SERVER)
    return records, client, adapter


def status_error(cls, code, body):
    return cls(f"Error code: {code} - {body}", response=httpx.Response(code, request=REQ), body=body)


def json_rejected(generation='{"answer": "unterminated'):
    return status_error(groq.BadRequestError, 400, {"error": {
        "message": "Failed to generate JSON. Please adjust your prompt.", "type": "invalid_request_error",
        "code": "json_validate_failed", "failed_generation": generation}})


@contextlib.contextmanager
def no_network():
    def refuse(*_a, **_k):
        raise AssertionError("network access attempted")
    with mock.patch.object(socket.socket, "connect", refuse), mock.patch.object(socket, "create_connection", refuse):
        yield


class CaseSetTests(unittest.TestCase):
    def test_fourteen_model_cases_and_two_without_a_model_call(self):
        self.assertEqual(len(rge.model_cases(CASES)), 14)
        self.assertEqual(sorted(c["id"] for c in CASES if c["expected"]["model_calls"] == 0), ["RG-Z1", "RG-Z2"])

    def test_every_passage_is_synthetic_and_every_case_is_justified(self):
        for c in CASES:
            for k in c["evidence"]:
                self.assertTrue(PASSAGES[k]["text"].startswith("Synthetic"), k)
                self.assertTrue(PASSAGES[k]["manifest_id"].startswith("synthetic-"), k)
            self.assertTrue(c["expected"]["justification"].strip(), c["id"])

    def test_rg01_is_a_flat_contradiction_between_fictional_passages(self):
        a, b = (PASSAGES[k] for k in BY_ID["RG-01"]["evidence"])
        body_a, body_b = (p["text"].split(". ", 1)[1] for p in (a, b))
        self.assertEqual(body_a.replace("shall stamp", "shall not stamp"), body_b)  # same actor, action, object, scope
        for p in (a, b):
            self.assertTrue(p["manifest_id"].startswith("synthetic-fictional"))
            self.assertIn("not legislation", p["note"].lower())
            self.assertFalse(SERVER.grounded_answer.identifiers(p["text"]))  # no rule, section or other identifier
        self.assertEqual(BY_ID["RG-01"]["expected"]["outcomes"], ["conflict"])
        self.assertEqual(BY_ID["RG-01"]["expected"]["citations"]["required"], ["E1", "E2"])
        # "blue ink" and "shall not stamp" are what each side says, not conditions attached to it
        self.assertEqual({p["kind"] for p in BY_ID["RG-01"]["expected"]["required_phrases"]}, {"content"})

    def test_phrase_kinds_condition_only_where_the_passage_attaches_one(self):
        conditions = {(c["id"], p["text"]) for c in CASES for p in c["expected"]["required_phrases"]
                      if p["kind"] == "condition"}
        self.assertEqual(conditions, {("RG-03", "turban"), ("RG-04", "licensed instructor sits beside"),
                                      ("RG-06", "all seats are occupied"), ("RG-07", "owner or hirer"),
                                      ("RG-08", "owner or hirer"), ("RG-09", "pick up or set down passengers"),
                                      ("RG-10", "turban")})

    def test_rg05_requires_the_override(self):
        e = BY_ID["RG-05"]["expected"]
        self.assertEqual((e["outcomes"], e["citations"]["required"]), (["answer"], ["E2"]))
        self.assertEqual(e["required_phrases"], [{"text": "not drive on a national highway", "source": "E2",
                                                  "kind": "content"}])

    def test_schema_rejects_unjustified_expectations(self):
        def broken(change):
            c = copy.deepcopy(BY_ID["RG-08"])
            change(c)
            with self.assertRaises(rge.CaseError):
                rge.validate_cases([c], PASSAGES)
        broken(lambda c: c["expected"]["required_phrases"].append({"text": "seat belts", "source": "E1"}))
        broken(lambda c: c["expected"]["citations"].update(required=["E1", "E3"]))
        broken(lambda c: c["expected"]["citations"].update(permitted=["E1"]))          # required not permitted
        broken(lambda c: c["expected"]["citations"].update(excluded=["E2"]))           # permitted and excluded
        broken(lambda c: c["expected"].update(outcomes=["legal"]))
        broken(lambda c: c["expected"].update(justification=" "))
        broken(lambda c: c["expected"]["required_phrases"][0].pop("kind"))
        broken(lambda c: c["expected"]["required_phrases"][1].update(kind="condition"))  # "farm labourers": no marker
        p = dict(PASSAGES, real={"manifest_id": "tmvr-1989", "provision_id": "Rule 1", "text": "Rule 1. Text."})
        c = copy.deepcopy(BY_ID["RG-04"])
        c["evidence"] = ["real"]
        with self.assertRaises(rge.CaseError):
            rge.validate_cases([c], p)

    def test_local_passages_must_be_fictional_unlabelled_by_law_and_not_shadow_fixtures(self):
        good = {"manifest_id": "synthetic-fictional-x", "provision_id": "Fictional Clause C",
                "text": "Synthetic Clause C, fictional test text. A keeper shall file the card.",
                "note": "Fictional. Not legislation."}
        rge.validate_local_passages({"c": good}, PASSAGES)
        for bad in ({"text": good["text"] + " See Rule 12."}, {"provision_id": "Section 60"},
                    {"note": "test"}, {"manifest_id": "tmvr-1989"}):
            with self.assertRaises(rge.CaseError):
                rge.validate_local_passages({"c": dict(good, **bad)}, PASSAGES)
        with self.assertRaises(rge.CaseError):
            rge.validate_local_passages({"helmet": good}, PASSAGES)

    def test_not_every_retrieved_passage_must_be_cited(self):
        e = BY_ID["RG-02"]["expected"]["citations"]
        self.assertEqual((e["required"], e["permitted"]), (["E2"], ["E1", "E2"]))


class ExecutionPathTests(unittest.TestCase):
    """The real server.chat grounded path, with scripted provider responses."""

    def expected_prompt(self, cid):
        case = BY_ID[cid]
        contract, _kept = SERVER.grounded_answer.build_contract(case["question"], aq.fixture_docs(case, PASSAGES))
        return SERVER.grounded_answer.build_prompt(contract)

    def test_ordinary_question_and_the_exact_prompt(self):
        (r,), client, _ = run(["RG-04"], {"RG-04": mocks("RG-04")})
        self.assertEqual((r["status"], r["outcome"], r["model_calls"], r["retry_triggered"]),
                         ("completed", "answer", 1, False))
        self.assertTrue(r["first_validation"]["accepted"] and r["expected_achieved"])
        self.assertEqual(r["citation"], {"missing_required": [], "outside_permitted": [], "excluded_cited": [],
                                         "correct": True})
        sent = client.requests[0]
        self.assertEqual(sent["messages"], [{"role": "user", "content": self.expected_prompt("RG-04")}])
        self.assertEqual((sent["temperature"], sent["seed"], sent["max_completion_tokens"], sent["response_format"]),
                         (0.0, 7, 200, {"type": "json_object"}))

    def test_direct_conflict_with_successful_retry_and_exact_retry_prompt(self):
        (r,), client, _a = run(["RG-01"], {"RG-01": mocks("RG-01")})
        self.assertEqual((r["outcome"], r["model_calls"], r["retry_triggered"]), ("conflict", 2, True))
        self.assertEqual({c["check"] for c in r["first_validation"]["checks"]}, {"uncited_conflict"})
        self.assertTrue(r["final_validation"]["accepted"] and r["expected_achieved"])
        first, second = (q["messages"][0]["content"] for q in client.requests)
        self.assertEqual(first, self.expected_prompt("RG-01"))
        self.assertEqual(second, first + r["retry_instruction"])

    def test_override_ignored_is_not_achieved(self):
        both = mocks("RG-05")[0]
        conflicting = dict(both, evidence_sufficiency="conflicting")
        (r,), _c, _a = run(["RG-05"], {"RG-05": [conflicting]})
        self.assertEqual(r["outcome"], "conflict")
        self.assertFalse(r["expected_achieved"])
        e1_only = copy.deepcopy(both)
        e1_only["claims"], e1_only["citations"] = both["claims"][:1], ["E1"]
        e1_only["answer"] = both["claims"][0]["text"]
        (r,), _c, _a = run(["RG-05"], {"RG-05": [e1_only, e1_only]})
        self.assertFalse(r["expected_achieved"])

    def test_qualifying_evidence_retried_and_both_cited(self):
        (r,), _c, _a = run(["RG-08"], {"RG-08": mocks("RG-08")})
        self.assertEqual({c["check"] for c in r["first_validation"]["checks"]}, {"uncited_qualification"})
        self.assertEqual((r["outcome"], r["final_citations"]), ("answer", ["E1", "E2"]))
        self.assertTrue(r["conditions"]["preserved"] and r["content"]["preserved"] and r["expected_achieved"])

    def test_unsuccessful_retry(self):
        (r,), _c, _a = run(["RG-03"], {"RG-03": mocks("RG-03")})
        self.assertEqual((r["status"], r["outcome"], r["model_calls"]), ("completed", "rejected", 2))
        self.assertFalse(r["final_validation"]["accepted"])
        self.assertFalse(r["expected_achieved"])

    def test_retry_not_triggered_for_an_accepted_control(self):
        (r,), _c, _a = run(["RG-10"], {"RG-10": mocks("RG-10")})
        self.assertEqual((r["retry_triggered"], r["retry_eligibility"]), (False, "not eligible: first response accepted"))
        self.assertTrue(r["expected_achieved"])

    def test_retry_not_triggered_for_another_rejection(self):
        (r,), _c, _a = run(["RG-06"], {"RG-06": mocks("RG-06")})
        self.assertEqual((r["outcome"], r["model_calls"], r["retry_triggered"]), ("rejected", 1, False))
        self.assertIn("not eligible: rejected for", r["retry_eligibility"])

    def test_vague_follow_up_and_penalty_make_no_call(self):
        records, client, _ = run(["RG-Z1", "RG-Z2"], {})
        self.assertEqual([(r["outcome"], r["model_calls"]) for r in records],
                         [("clarification", 0), ("restricted", 0)])
        self.assertTrue(all(r["expected_achieved"] for r in records))
        self.assertEqual(client.requests, [])

    def test_insufficient_evidence(self):
        (r,), _c, _a = run(["RG-12"], {"RG-12": mocks("RG-12")})
        self.assertEqual((r["outcome"], r["citation"], r["expected_achieved"]), ("no_support", None, True))

    def test_patched_state_is_restored_after_every_case(self):
        ga = SERVER.grounded_answer
        before = (SERVER.ANSWER_GENERATOR, SERVER.retrieve, SERVER.grounded_gate_errors, SERVER.ANSWER_MODE,
                  ga.validate, ga.answer, ga.conflict_retry_note, dict(SERVER.SOURCES))
        run(["RG-01", "RG-Z1"], {"RG-01": mocks("RG-01")})
        after = (SERVER.ANSWER_GENERATOR, SERVER.retrieve, SERVER.grounded_gate_errors, SERVER.ANSWER_MODE,
                 ga.validate, ga.answer, ga.conflict_retry_note, dict(SERVER.SOURCES))
        self.assertEqual(before, after)
        self.assertFalse([s for s in SERVER.sessions if s.startswith("real-model-eval-")])


class FailureTests(unittest.TestCase):
    """Provider failures and limits are recorded as such, never as validator rejections."""

    def assert_infrastructure(self, r, call_status):
        self.assertEqual((r["status"], r["calls"][-1]["status"]), ("api_failed", call_status))
        self.assertIsNone(r["expected_achieved"])
        self.assertIsNone(r.get("citation"))

    def test_api_timeout(self):
        (r,), _c, _a = run(["RG-04"], {"RG-04": [{"raise": groq.APITimeoutError(request=REQ)}]})
        self.assert_infrastructure(r, "timeout")
        s = rge.summarise([r], {})
        self.assertEqual((s["model_status"]["api_failed"], s["conditional"]["first_pass_acceptance"]["of"],
                          s["overall"]["achievement"]), (1, 0, {"n": 0, "of": 1, "rate": 0.0}))

    def test_genuine_api_errors_stay_infrastructure_failures(self):
        for exc, call_status in (
                (status_error(groq.BadRequestError, 400, {"error": {"message": "model not found",
                                                                    "type": "invalid_request_error"}}),
                 "api_error_http_400"),
                (status_error(groq.AuthenticationError, 401, {"error": {"message": "Invalid API Key"}}),
                 "auth_error_http_401"),
                (status_error(groq.RateLimitError, 429, {"error": {"message": "slow down"}}), "rate_limited_http_429"),
                (status_error(groq.InternalServerError, 503, {"error": {"message": "unavailable"}}),
                 "server_error_http_503"),
                (groq.APIConnectionError(request=REQ), "connection_error")):
            (r,), _c, _a = run(["RG-04"], {"RG-04": [{"raise": exc}]})
            self.assert_infrastructure(r, call_status)

    def test_provider_rejected_output_is_a_model_failure(self):
        (r,), client, _a = run(["RG-04"], {"RG-04": [{"raise": json_rejected('{"answer": ' + FAKE_KEY)}]})
        self.assertEqual((r["status"], r["calls"][0]["status"]), ("provider_rejected_output", "provider_rejected_output"))
        self.assertEqual(len(client.requests), 1)                   # no automatic retry of the request
        self.assertIsNone(r["first_validation"])                    # not a validator rejection
        self.assertFalse(r["expected_achieved"])                    # not an acceptance either
        self.assertEqual(r["calls"][0]["failed_generation"], '{"answer": [REDACTED]')
        s = rge.summarise([r], {})
        self.assertEqual(s["overall"]["not_achieved"]["provider_rejected_output"], 1)
        self.assertEqual(s["overall"]["not_scorable"]["infrastructure_failure"], 0)
        self.assertEqual(s["conditional"]["scorable_model_cases"], 0)

    def test_provider_rejected_output_does_not_stop_the_run(self):
        script = {c["id"]: [{"raise": json_rejected()}] for c in CASES}
        records, client, _ = run([c["id"] for c in rge.model_cases(CASES)], script)
        self.assertEqual(len(client.requests), 14)
        self.assertEqual({r["status"] for r in records}, {"provider_rejected_output"})

    def test_api_failure_on_the_retry_call(self):
        (r,), _c, _a = run(["RG-01"], {"RG-01": [mocks("RG-01")[0], {"raise": groq.APITimeoutError(request=REQ)}]})
        self.assertEqual(r["model_calls"], 2)
        self.assert_infrastructure(r, "timeout")

    def test_truncated_output_is_not_achieved_and_not_a_validator_verdict(self):
        body = mocks("RG-04")[0]
        (r,), _c, _a = run(["RG-04"], {"RG-04": [{"body": json.dumps(body)[:40], "finish_reason": "length"}]})
        self.assertEqual((r["status"], r["expected_achieved"]), ("truncated", False))
        self.assertEqual(rge.summarise([r], {})["conditional"]["scorable_model_cases"], 0)

    def test_token_budget_exhausted_before_the_first_call(self):
        records, client, _ = run(["RG-04", "RG-07"], {"RG-04": mocks("RG-04"), "RG-07": mocks("RG-07")},
                                 max_tokens=50)
        self.assertEqual([r["status"] for r in records], ["not_run", "not_run"])
        self.assertEqual(client.requests, [])

    def test_token_budget_exhausted_before_the_retry(self):
        first = {"body": mocks("RG-01")[0], "usage": {"prompt_tokens": 3000, "completion_tokens": 900,
                                                      "total_tokens": 3900}}
        records, client, adapter = run(["RG-01", "RG-04"], {"RG-01": [first, mocks("RG-01")[1]],
                                                            "RG-04": mocks("RG-04")}, max_tokens=5000)
        self.assertEqual([r["status"] for r in records], ["incomplete", "not_run"])
        self.assertEqual(len(client.requests), 1)
        self.assertIn("token budget", records[0]["stop_reason"])
        self.assertEqual(adapter.budget.tokens, 3900)

    def test_call_limit_stops_further_calls(self):
        records, client, _ = run(["RG-01", "RG-04"], {"RG-01": mocks("RG-01"), "RG-04": mocks("RG-04")},
                                 max_calls=1)
        self.assertEqual([r["status"] for r in records], ["incomplete", "not_run"])
        self.assertEqual(len(client.requests), 1)

    def test_no_run_exceeds_the_call_limit(self):
        one_sided = {c["id"]: [mocks("RG-03")[0]] * 2 for c in CASES}
        records, client, _ = run([c["id"] for c in CASES], one_sided, max_calls=5)
        self.assertLessEqual(len(client.requests), 5)
        self.assertTrue(any(r["status"] == "not_run" for r in records))

    def test_consecutive_infrastructure_failures_halt_the_run(self):
        script = {c["id"]: [{"raise": groq.APITimeoutError(request=REQ)}] for c in CASES}
        records, client, _ = run([c["id"] for c in rge.model_cases(CASES)], script)
        self.assertEqual(len(client.requests), rge.MAX_CONSECUTIVE_FAILURES)
        self.assertEqual(sum(r["status"] == "not_run" for r in records), 14 - rge.MAX_CONSECUTIVE_FAILURES)


class MetricTests(unittest.TestCase):
    def test_denominators_with_failed_truncated_rejected_incomplete_and_guard_cases(self):
        script = {"RG-04": mocks("RG-04"),                                            # achieved
                  "RG-06": mocks("RG-06"),                                            # completed, expectation failed
                  "RG-07": [{"body": "{\"answer\": \"A goods", "finish_reason": "length"}],  # truncated
                  "RG-09": [{"raise": json_rejected()}],                              # provider-rejected output
                  "RG-12": [{"raise": groq.APITimeoutError(request=REQ)}],            # infrastructure
                  "RG-01": [mocks("RG-01")[0]]}                                       # incomplete (call limit)
        records, client, _ = run(["RG-Z1", "RG-04", "RG-06", "RG-07", "RG-09", "RG-12", "RG-01", "RG-02", "RG-Z2"],
                                 script, max_calls=6)
        s = rge.summarise(records, {})
        self.assertEqual((s["model_cases"], s["guard_cases"]), (7, 2))
        self.assertEqual(s["model_status"], {"completed": 2, "provider_rejected_output": 1, "truncated": 1,
                                             "api_failed": 1, "incomplete": 1, "not_run": 1, "not_recorded": 0})
        self.assertEqual(s["overall"]["achievement"], {"n": 1, "of": 7, "rate": 0.143})
        self.assertEqual(s["overall"]["not_achieved"],
                         {"expectation_failed": 1, "truncated": 1, "provider_rejected_output": 1})
        self.assertEqual(s["overall"]["not_scorable"], {"infrastructure_failure": 1, "not_recorded": 0, "incomplete": 1,
                                                        "not_run": 1})
        c = s["conditional"]
        self.assertEqual((c["scorable_model_cases"], c["expected_agreement"]["of"], c["expected_agreement"]["n"]),
                         (2, 2, 1))
        self.assertEqual((c["final_acceptance"]["n"], c["final_accepted_substantive"], c["final_accepted_refusal"]),
                         (1, 1, 0))
        # the guard cases after the stop are not run, and never inflate the model-case figures
        self.assertEqual(s["guards"], {"checks": 2, "passing": 1, "unexpected_model_calls": 0, "not_run": 1})
        self.assertLessEqual(len(client.requests), 6)

    def test_accepted_refusals_are_reported_apart_from_substantive_answers(self):
        records, _c, _a = run(["RG-04", "RG-12", "RG-13"], {k: mocks(k) for k in ("RG-04", "RG-12", "RG-13")})
        c = rge.summarise(records, {})["conditional"]
        self.assertEqual((c["final_acceptance"]["n"], c["final_accepted_substantive"], c["final_accepted_refusal"]),
                         (3, 1, 2))

    def test_report_shows_both_rates_and_every_status(self):
        records, _c, _a = run(["RG-04", "RG-Z1"], {"RG-04": mocks("RG-04")})
        md = rge.markdown(rge.summarise(records, {}), records, {"mode": "mock"})
        for text in ("Model-case results among cases with a scorable response (1 of 1)",
                     "Overall model-case achievement (all 1 model cases)", "No-model guard checks",
                     "| provider_rejected_output | 0 |", "| infrastructure_failure | 0 |", "accepted refusal",
                     "Condition/exception words preserved", "Content words of required positions"):
            self.assertIn(text, md)


class SafeguardTests(unittest.TestCase):
    def factory_must_not_run(self, *_a):
        raise AssertionError("client factory called")

    def main(self, argv, environ, factory=None, default_factory=False):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(out):
            md, js = Path(tmp) / "r.md", Path(tmp) / "r.json"
            kwargs = {} if default_factory else {"client_factory": factory or self.factory_must_not_run}
            code = rge.main(argv + ["--markdown", str(md), "--json", str(js)], environ=environ, server=SERVER,
                            **kwargs)
            texts = (md.read_text() if md.exists() else "", js.read_text() if js.exists() else "")
        return code, out.getvalue(), texts

    def test_real_flag_without_env_opt_in_builds_no_client(self):
        for env in ({rge.KEY_ENV: FAKE_KEY}, {rge.OPT_IN_ENV: "yes", rge.KEY_ENV: FAKE_KEY},
                    {rge.OPT_IN_ENV: "1"}, {rge.OPT_IN_ENV: "1", rge.KEY_ENV: "placeholder"}):
            # the real factory is used: groq.Groq is patched to fail, so constructing a client would raise
            code, out, _ = self.main(["--real", "--only", "RG-04"], env, default_factory=True)
            self.assertEqual(code, 2, env)
            self.assertIn("Refusing", out)

    def test_env_opt_in_without_real_flag_builds_no_client(self):
        both = {rge.OPT_IN_ENV: "1", rge.KEY_ENV: FAKE_KEY}
        code, _o, (md, _j) = self.main(["--only", "RG-04"], both, default_factory=True)
        self.assertEqual(code, 0)
        self.assertIn("SAMPLE (mocked responses)", md)

    def test_both_opt_ins_build_exactly_one_client(self):
        built = []

        def factory(key, timeout):
            built.append((key, timeout))
            return rge.ScriptedClient({"RG-04": mocks("RG-04")})
        code, _o, (md, _j) = self.main(["--real", "--only", "RG-04"], {rge.OPT_IN_ENV: "1", rge.KEY_ENV: FAKE_KEY},
                                       factory=factory)
        self.assertEqual((code, built), (0, [(FAKE_KEY, rge.DEFAULT_TIMEOUT)]))
        self.assertIn("Real-model evaluation", md)

    def test_key_is_read_from_the_given_environment_only(self):
        with mock.patch.dict(os.environ, {rge.OPT_IN_ENV: "", rge.KEY_ENV: ""}):
            with self.assertRaises(rge.OptInError):
                rge.check_opt_in(True, os.environ)
        self.assertEqual(rge.check_opt_in(True, {rge.OPT_IN_ENV: "1", rge.KEY_ENV: FAKE_KEY}), FAKE_KEY)
        with self.assertRaises(rge.OptInError):
            rge.check_opt_in(False, {rge.OPT_IN_ENV: "1", rge.KEY_ENV: FAKE_KEY})

    def test_call_limit_is_capped(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            rge.parse_args(["--max-calls", str(rge.HARD_MAX_CALLS + 1)])

    def test_api_keys_never_appear_in_logs_reports_or_output(self):
        echo = mocks("RG-04")[0]
        echo["claims"][0]["text"] += " " + FAKE_KEY
        echo["answer"] = echo["claims"][0]["text"]
        err = status_error(groq.AuthenticationError, 401, {"error": {"message": f"invalid key {FAKE_KEY}"}})
        client = rge.ScriptedClient({"RG-04": [echo], "RG-07": [{"raise": err}], "RG-09": [{"raise": json_rejected(
            FAKE_KEY)}], "RG-12": mocks("RG-12")})
        seen = []
        handler = logging.Handler()
        handler.emit = lambda rec: seen.append(rec.getMessage())
        logging.getLogger().addHandler(handler)
        try:
            code, out, (md, js) = self.main(["--real", "--only", "RG-04,RG-07,RG-09,RG-12"],
                                            {rge.OPT_IN_ENV: "1", rge.KEY_ENV: FAKE_KEY},
                                            factory=lambda key, _t: client)
        finally:
            logging.getLogger().removeHandler(handler)
        self.assertEqual(code, 1)  # one infrastructure failure
        for text in (out, md, js, "\n".join(seen)):
            self.assertNotIn(FAKE_KEY, text)
        self.assertIn("[REDACTED]", js)


class TransportTests(unittest.TestCase):
    """A real SDK client on a fake HTTP transport: nothing leaves the process."""

    def client(self, handler, **env):
        with mock.patch.object(groq, "Groq", _REAL_GROQ), mock.patch.dict(os.environ, env):
            return rge.make_groq_client("gsk_transporttestonly000", 5,
                                        http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    def test_a_failed_call_is_not_retried_by_the_sdk(self):
        for failure, status in ((lambda req: httpx.Response(500, json={"error": {"message": "x"}}),
                                 "server_error_http_500"),
                                (lambda req: (_ for _ in ()).throw(httpx.ReadTimeout("slow", request=req)),
                                 "timeout"),
                                (lambda req: httpx.Response(400, json={"error": {
                                    "message": "Failed to generate JSON", "code": "json_validate_failed",
                                    "failed_generation": "{bad"}}), "provider_rejected_output")):
            sent = []

            def handler(req, failure=failure):
                sent.append(req)
                return failure(req)
            client = self.client(handler)
            adapter = rge.GroqAdapter(client, rge.Budget(5, 100_000), max_completion_tokens=10)
            with self.assertRaises(rge.EvalCallFailed):
                adapter.generate("prompt", None)
            self.assertEqual((len(sent), adapter.calls[0]["status"], client.max_retries), (1, status, 0))

    def test_requests_go_only_to_the_pinned_groq_endpoint_whatever_the_environment_says(self):
        sent = []

        def handler(req):
            sent.append(req)
            return httpx.Response(200, json={
                "id": "x", "object": "chat.completion", "created": 0, "model": "m",
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "{}"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
        client = self.client(handler, GROQ_BASE_URL="https://attacker.example/v1")
        adapter = rge.GroqAdapter(client, rge.Budget(5, 100_000), max_completion_tokens=10)
        self.assertEqual(adapter.generate("prompt", None), "{}")
        (req,) = sent
        self.assertEqual((req.url.scheme, req.url.host, req.url.path),
                         ("https", "api.groq.com", "/openai/v1/chat/completions"))
        self.assertEqual(req.headers["authorization"], "Bearer gsk_transporttestonly000")
        self.assertEqual(adapter.calls[0]["usage"], {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})

    def test_unpinned_sdk_would_follow_the_environment(self):
        # why the pin matters: without base_url the SDK itself honours GROQ_BASE_URL
        with mock.patch.dict(os.environ, {"GROQ_BASE_URL": "https://attacker.example"}):
            self.assertEqual(_REAL_GROQ(api_key="gsk_x0000000", max_retries=0).base_url.host, "attacker.example")

    def test_client_refuses_an_unexpected_endpoint(self):
        with mock.patch.object(rge, "GROQ_BASE_URL", "https://attacker.example"), self.assertRaises(RuntimeError):
            self.client(lambda req: httpx.Response(500))


class NoNetworkTests(unittest.TestCase):
    def test_mock_runs_make_no_network_access(self):
        out = io.StringIO()
        with no_network(), tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(out):
            md = Path(tmp) / "r.md"
            code = rge.main(["--markdown", str(md)], environ={}, server=SERVER)
            text = md.read_text()
        self.assertEqual(code, 0)
        self.assertIn("No model was called", text)
        self.assertIn("do not measure legal correctness on real Telangana legal provisions", text)

    def test_groq_client_construction_fails_in_this_test_module(self):
        with self.assertRaises(AssertionError):
            groq.Groq(api_key=FAKE_KEY)


class ScoringTests(unittest.TestCase):
    def record(self, cited, claims=("text",), displayed="text", outcome="answer"):
        return {"status": "completed", "outcome": outcome, "model_calls": 1, "retry_triggered": False,
                "final_citations": cited, "final_claims": list(claims), "displayed": displayed}

    def test_citation_parts_are_reported_separately(self):
        case = {"expected": {"outcomes": ["answer"], "citations": {"required": ["E1"], "permitted": ["E1", "E2"],
                                                                    "excluded": ["E3"]},
                             "required_phrases": [], "retry": None, "model_calls": None}}
        self.assertEqual(rge.score(self.record(["E2", "E3"]), case)["citation"],
                         {"missing_required": ["E1"], "outside_permitted": ["E3"], "excluded_cited": ["E3"],
                          "correct": False})
        self.assertTrue(rge.score(self.record(["E1"]), case)["citation"]["correct"])
        self.assertTrue(rge.score(self.record(["E1", "E2"]), case)["expected_achieved"])

    def test_condition_words_are_checked_in_claim_text_only(self):
        case = copy.deepcopy(BY_ID["RG-06"])
        s = rge.score(self.record(["E1"], ["A school bus may carry standing passengers."],
                                  displayed="A school bus may carry standing passengers.\n\nCited:\n[1] all seats are "
                                            "occupied"), case)
        self.assertEqual((s["conditions"]["missing"], s["content"]), (["all seats are occupied"], None))
        self.assertFalse(s["expected_achieved"])
        self.assertEqual(s["manual_review"], "pending")

    def test_content_words_are_scored_apart_from_conditions(self):
        case = copy.deepcopy(BY_ID["RG-01"])
        one_side = ["The keeper of a test registry shall stamp the test card in blue ink."]
        s = rge.score(self.record(["E1", "E2"], one_side, outcome="conflict"), case)
        self.assertEqual((s["conditions"], s["content"]["missing"]), (None, ["shall not stamp"]))
        self.assertFalse(s["expected_achieved"])
        both = one_side + ["The keeper of a test registry shall not stamp the test card in blue ink."]
        self.assertTrue(rge.score(self.record(["E1", "E2"], both, outcome="conflict"), case)["expected_achieved"])


class PacingAndOrgRedactionTests(unittest.TestCase):
    def test_calls_are_spaced_by_the_minimum_interval_and_never_repeated(self):
        now, slept = [100.0], []
        clock = lambda: now[0]  # noqa: E731

        def sleep(sec):
            slept.append(round(sec, 3))
            now[0] += sec
        client = rge.ScriptedClient({"RG-04": mocks("RG-04"), "RG-07": mocks("RG-07"), "RG-09": mocks("RG-09")})
        adapter = rge.GroqAdapter(client, rge.Budget(10, 100_000), max_completion_tokens=200, clock=clock,
                                  min_interval_s=15, sleep=sleep)
        now[0] += 0  # first call: no wait
        records = rge.run_all([BY_ID[i] for i in ("RG-04", "RG-07", "RG-09")], PASSAGES, adapter, server=SERVER)
        self.assertEqual(slept, [15.0, 15.0])
        self.assertEqual((len(client.requests), [r["status"] for r in records]), (3, ["completed"] * 3))

    def test_no_pacing_by_default(self):
        slept = []
        client = rge.ScriptedClient({"RG-04": mocks("RG-04"), "RG-07": mocks("RG-07")})
        adapter = rge.GroqAdapter(client, rge.Budget(10, 100_000), max_completion_tokens=200, sleep=slept.append)
        rge.run_all([BY_ID["RG-04"], BY_ID["RG-07"]], PASSAGES, adapter, server=SERVER)
        self.assertEqual(slept, [])

    def test_organisation_ids_are_redacted(self):
        text = "Rate limit reached in organization `org_01abcdefgh1234567890` on tokens per minute"
        self.assertEqual(rge.Redactor()(text), "Rate limit reached in organization `[REDACTED_ORG]` on tokens per minute")
        err = status_error(groq.RateLimitError, 429, {"error": {"message": text}})
        (r,), _c, _a = run(["RG-04"], {"RG-04": [{"raise": err}]})
        self.assertNotIn("org_01abcdefgh", json.dumps(r))
        self.assertEqual(r["calls"][0]["status"], "rate_limited_http_429")


def recording(cases):
    """A local recording: {case_id: [response dict or text, ...]} with correct hashes."""
    out = {}
    for cid, responses in cases.items():
        calls = []
        for n, r in enumerate(responses, 1):
            text = r if isinstance(r, str) else json.dumps(r)
            calls.append({"call_index": n, "status": "ok", "finish_reason": "stop", "verbatim": True,
                          "response": text, "sha256": rge._sha256(text)})
        out[cid] = {"source_file": "local-fixture.json", "run_at_utc": "2026-01-01 00:00", "calls": calls}
    return {"schema": rge.RECORDING_SCHEMA, "model": "fixture-model", "note": "test fixture",
            "sources": [{"file": "local-fixture.json", "sha256": "0" * 64, "run_at_utc": "2026-01-01 00:00",
                         "model": "fixture-model"}], "excluded": [], "cases": out}


class ReplayTests(unittest.TestCase):
    """--replay: recorded responses through the current validator; no client, no network, no key."""

    def factory_must_not_run(self, *_a):
        raise AssertionError("client factory called during replay")

    def replay(self, doc, argv=(), environ=None, raw=None):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(out), no_network():
            rec, md, js = Path(tmp) / "rec.json", Path(tmp) / "r.md", Path(tmp) / "r.json"
            rec.write_text(raw if raw is not None else json.dumps(doc))
            code = rge.main(["--replay", str(rec), "--markdown", str(md), "--json", str(js), *argv],
                            environ={} if environ is None else environ, client_factory=self.factory_must_not_run,
                            server=SERVER)
            texts = (md.read_text() if md.exists() else None, json.loads(js.read_text()) if js.exists() else None)
        return code, out.getvalue(), texts

    def test_valid_recording_replays_through_the_current_validator(self):
        code, out, (md, js) = self.replay(recording({"RG-04": mocks("RG-04"), "RG-06": mocks("RG-06")}),
                                          ["--only", "RG-04,RG-06"])
        self.assertEqual(code, 0)
        by = {r["id"]: r for r in js["records"]}
        self.assertEqual((by["RG-04"]["outcome"], by["RG-04"]["expected_achieved"]), ("answer", True))
        # RG-06's recorded answer drops "only when all seats are occupied": the current validator rejects it
        self.assertEqual(by["RG-06"]["outcome"], "rejected")
        self.assertTrue(any("'only'" in e for e in by["RG-06"]["first_validation"]["errors"]))
        self.assertIn("no model calls", out)

    def test_tampered_response_stops_the_replay(self):
        doc = recording({"RG-04": mocks("RG-04")})
        doc["cases"]["RG-04"]["calls"][0]["response"] = doc["cases"]["RG-04"]["calls"][0]["response"].replace(
            "licensed", "unlicensed")
        code, out, (md, js) = self.replay(doc, ["--only", "RG-04"])
        self.assertEqual((code, md, js), (2, None, None))
        self.assertIn("does not match its sha256", out)

    def test_missing_case_is_not_recorded_and_nothing_is_substituted(self):
        code, _o, (_md, js) = self.replay(recording({"RG-04": mocks("RG-04")}), ["--only", "RG-04,RG-07"])
        self.assertEqual(code, 1)
        r = {x["id"]: x for x in js["records"]}["RG-07"]
        self.assertEqual((r["status"], r["first_response"], r["first_validation"], r["expected_achieved"]),
                         ("not_recorded", None, None, None))
        self.assertEqual(js["summary"]["model_status"]["not_recorded"], 1)
        self.assertEqual(js["summary"]["overall"]["not_scorable"]["not_recorded"], 1)

    def test_retry_with_no_recorded_second_response_is_not_recorded(self):
        # RG-01's recorded first response is one-sided, so the pipeline asks for a retry the recording lacks
        code, _o, (_md, js) = self.replay(recording({"RG-01": mocks("RG-01")[:1]}), ["--only", "RG-01"])
        r = js["records"][0]
        self.assertEqual((code, r["status"], r["model_calls"], r["second_response"]), (1, "not_recorded", 2, None))

    def test_missing_response_is_refused_not_fabricated(self):
        doc = recording({"RG-04": mocks("RG-04")})
        doc["cases"]["RG-04"]["calls"][0]["response"] = None
        code, out, texts = self.replay(doc, ["--only", "RG-04"])
        self.assertEqual((code, texts), (2, (None, None)))
        self.assertIn("has no recorded response", out)

    def test_non_verbatim_response_is_refused(self):
        doc = recording({"RG-04": mocks("RG-04")})
        doc["cases"]["RG-04"]["calls"][0]["verbatim"] = False
        self.assertEqual(self.replay(doc, ["--only", "RG-04"])[0], 2)

    def test_malformed_recordings_are_refused(self):
        for raw in ("{not json", json.dumps({"schema": "other", "cases": {}}), json.dumps([1, 2]),
                    json.dumps({"schema": rge.RECORDING_SCHEMA, "cases": {"RG-04": {"calls": "x"}}})):
            code, out, texts = self.replay(None, ["--only", "RG-04"], raw=raw)
            self.assertEqual((code, texts), (2, (None, None)), raw)
            self.assertIn("Refusing to replay", out)

    def test_replay_needs_no_key_and_ignores_the_env_opt_in(self):
        with mock.patch.dict(os.environ, {rge.KEY_ENV: "", rge.OPT_IN_ENV: ""}):
            self.assertEqual(self.replay(recording({"RG-04": mocks("RG-04")}), ["--only", "RG-04"])[0], 0)
        both = {rge.OPT_IN_ENV: "1", rge.KEY_ENV: FAKE_KEY}  # present but unused: the factory must not be called
        self.assertEqual(self.replay(recording({"RG-04": mocks("RG-04")}), ["--only", "RG-04"], environ=both)[0], 0)

    def test_replay_builds_no_client_with_the_default_factory(self):
        # groq.Groq is patched to fail in this module: building a client would raise
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(out), no_network():
            rec = Path(tmp) / "rec.json"
            rec.write_text(json.dumps(recording({"RG-04": mocks("RG-04")})))
            code = rge.main(["--replay", str(rec), "--only", "RG-04"], environ={}, server=SERVER)
        self.assertEqual(code, 0)

    def test_replay_and_real_together_are_refused(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = rge.main(["--replay", "x.json", "--real"], environ={rge.OPT_IN_ENV: "1", rge.KEY_ENV: FAKE_KEY},
                            client_factory=self.factory_must_not_run, server=SERVER)
        self.assertEqual(code, 2)
        self.assertIn("cannot be combined", out.getvalue())

    def test_report_label_and_provenance(self):
        code, _o, (md, js) = self.replay(recording({"RG-04": mocks("RG-04")}), ["--only", "RG-04,RG-Z1"])
        self.assertEqual(code, 0)
        self.assertIn("# OFFLINE REPLAY evaluation", md)
        self.assertIn(rge.REPLAY_LABEL, md)
        self.assertIn("No model calls were made", md)
        self.assertIn("| response hashes verified | 1 of 1 |", md)
        self.assertIn("| Recorded responses replayed by status (no model calls) |", md)
        self.assertIn("| Latency per call (s) | not applicable (offline replay) |", md)
        self.assertNotIn("| Model calls by status |", md)
        self.assertIn("| repository HEAD commit |", md)
        self.assertIn("| uncommitted changes anywhere in the repository (untracked files and this report included) |",
                      md)
        self.assertIn("| validator file `backend/meaning_checks.py` |", md)
        self.assertNotIn("| uncommitted changes |", md)
        self.assertIn("local-fixture.json (run 2026-01-01 00:00 UTC", md)
        cfg = js["config"]
        self.assertEqual((cfg["mode"], cfg["label"], cfg["responses_verified"]), ("replay", rge.REPLAY_LABEL, 1))
        self.assertEqual(set(cfg["validator"]), {"commit", "uncommitted_changes_anywhere", "validator_files"})
        self.assertEqual(set(cfg["validator"]["validator_files"]), set(rge.VALIDATOR_FILES))
        for x in cfg["validator"]["validator_files"].values():
            self.assertIn(x["state"], ("committed", "modified", "untracked", "unknown"))
            self.assertEqual(len(x["sha256"]), 64)
        self.assertEqual(cfg["recording_response_sha256"]["RG-04"],
                         [rge._sha256(json.dumps(mocks("RG-04")[0]))])
        self.assertEqual(js["summary"]["guards"]["passing"], 1)

    def test_report_lists_each_verified_hash_and_the_validators_rejection_reason(self):
        code, _o, (md, _js) = self.replay(recording({"RG-04": mocks("RG-04"), "RG-06": mocks("RG-06")}),
                                          ["--only", "RG-04,RG-06"])
        self.assertEqual(code, 0)
        self.assertIn(f"| RG-04 | {rge._sha256(json.dumps(mocks('RG-04')[0]))} |", md)
        self.assertIn("- **RG-06** (completed): outcome rejected not in expected ['answer']. Validator: claim 1: claim "
                      "omits the 'only' qualifier", md)

    def test_validator_file_state_and_hash_are_exact(self):
        import hashlib
        v = rge.validator_version()
        for rel, x in v["validator_files"].items():
            self.assertEqual(x["sha256"], hashlib.sha256((rge.BASE_DIR / rel).read_bytes()).hexdigest(), rel)
        # real_groq_eval.py is not in HEAD's tree until it is committed, so it cannot read as "committed" now
        import subprocess
        tracked = subprocess.run(["git", "-C", str(rge.BASE_DIR), "ls-files", "--error-unmatch",
                                  "backend/real_groq_eval.py"], capture_output=True).returncode == 0
        if not tracked:
            self.assertEqual(v["validator_files"]["backend/real_groq_eval.py"]["state"], "untracked")

    def test_replay_does_not_touch_the_sample_report(self):
        before = rge.SAMPLE_REPORT.read_bytes()
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(out):
            rec = Path(tmp) / "rec.json"
            rec.write_text(json.dumps(recording({"RG-04": mocks("RG-04")})))
            rge.main(["--replay", str(rec), "--only", "RG-04"], environ={}, server=SERVER)
        self.assertEqual(rge.SAMPLE_REPORT.read_bytes(), before)


class FreezeRecordingTests(unittest.TestCase):
    def results_file(self, tmp, records, mode="real"):
        path = Path(tmp) / f"results-{len(list(Path(tmp).iterdir()))}.json"
        path.write_text(json.dumps({"config": {"mode": mode, "model": "m", "run_at_utc": "2026-01-01 00:00"},
                                    "records": records}))
        return path

    def rec(self, cid, response, status="completed", finish="stop"):
        return {"id": cid, "status": status, "calls": [{"n": 1, "status": "ok", "finish_reason": finish,
                                                        "response": response}]}

    def test_completed_responses_are_copied_with_hashes_and_failures_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = self.results_file(tmp, [self.rec("RG-04", "{\"a\": 1}"), self.rec("RG-07", None, "api_failed")])
            doc = rge.freeze_recording([f], base=Path(tmp))
        call = doc["cases"]["RG-04"]["calls"][0]
        self.assertEqual((call["response"], call["sha256"], call["verbatim"]),
                         ('{"a": 1}', rge._sha256('{"a": 1}'), True))
        self.assertEqual([x["case_id"] for x in doc["excluded"]], ["RG-07"])
        self.assertNotIn("RG-07", doc["cases"])

    def test_redacted_or_truncated_responses_are_not_marked_verbatim(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = self.results_file(tmp, [self.rec("RG-04", "text [REDACTED] text"),
                                        self.rec("RG-07", "{\"cut", finish="length")])
            doc = rge.freeze_recording([f], base=Path(tmp))
        self.assertEqual([c["calls"][0]["verbatim"] for c in doc["cases"].values()], [False, False])

    def test_refuses_duplicates_secrets_and_non_real_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = self.results_file(tmp, [self.rec("RG-04", "x")])
            b = self.results_file(tmp, [self.rec("RG-04", "y")])
            with self.assertRaises(rge.RecordingError):
                rge.freeze_recording([a, b], base=Path(tmp))
            with self.assertRaises(rge.RecordingError):
                rge.freeze_recording([self.results_file(tmp, [self.rec("RG-04", "org_abcdefgh12345")])], base=Path(tmp))
            with self.assertRaises(rge.RecordingError):
                rge.freeze_recording([self.results_file(tmp, [self.rec("RG-04", "x")], mode="mock")], base=Path(tmp))

    def test_historical_artifacts_match_the_hashes_in_the_readme(self):
        import hashlib
        import re
        folder = rge.BASE_DIR / "eval/real-model"
        rows = re.findall(r"^\| `([^`]+)` \| `([0-9a-f]{64})` \|$", (folder / "README.md").read_text(), re.M)
        self.assertEqual(len(rows), 7)
        for name, digest in rows:
            self.assertEqual(hashlib.sha256((folder / name).read_bytes()).hexdigest(), digest, name)

    def test_the_frozen_recording_in_the_repository_verifies(self):
        doc, responses = rge.load_recording(rge.BASE_DIR / "eval/real-model/recorded/2026-11-10-gpt-oss-120b.json")
        self.assertEqual((len(responses), sum(map(len, responses.values()))), (14, 14))
        self.assertEqual(sorted(responses), [f"RG-{n:02d}" for n in range(1, 15)])


if __name__ == "__main__":
    unittest.main()
