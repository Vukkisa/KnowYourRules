"""Step 4 integration tests: the signed-ledger acceptance gate and the provision-validity filter inside the application.

Everything is synthetic: throwaway Ed25519 keys, a signed temp-directory chain built by ``test_source_status_ledger_binding``,
fake Chroma/LLM from ``test_server``. No real approval, registry, ledger, decision register or index is read for acceptance
(one test READS the real registry to show a real deployment is refused) and nothing is written outside temp directories.
"""

import datetime as dt
import hashlib
import inspect
import json
import logging
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import test_provision_validity as tpv  # noqa: E402
import test_server as ts  # noqa: E402
import validity_decisions_support as sup  # noqa: E402
import test_source_status_ledger_binding as tb  # noqa: E402
from langchain_core.documents import Document  # noqa: E402

from backend import grounded_answer, ledger_acceptance, legal_approval as la, provision_validity as pv  # noqa: E402
from backend import provision_validity_runtime as vr  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REAL_REGISTRY_SHA256 = "cd463006b2df2928a624ce4f1aee8e60d7fd4d87f39f4c304fd10ca2f99431d6"
REAL_REGISTER_SHA256 = "a853ccde67f8e929fb940ad713345a83511294a83f698e1031e80ffd0580206e"
MID = "tmvr-1989-chap-2"
TEXT = "Rule 5. A learner's licence application is made in Form 2."
SHA = ts.TG_RULES_SHA
QUESTION = "How do I apply for a learner's licence?"
ORIGINAL_ENSURE = ts.srv.ensure_approval_current
CLOCK = lambda: dt.date(2910, 6, 1)  # noqa: E731 - the synthetic ledgers live in the year 2900s


def sha_text(t):
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def chunk(text=TEXT, **meta):
    m = {"state": "Telangana", "manifest_id": MID, "provision_id": "Rule 5", "part": 1, "parts": 1, "page_start": 1, "page_end": 1,
         "title": "Synthetic Motor Rules", "location": "chap-2.htm#5", "answer_eligible": True, "verification_status": "unverified",
         "source_file": ts.TG_RULES_FILE, "sha256": SHA}
    m.update(meta)
    return Document(page_content=text, metadata=m)


def ledger(text=TEXT, **kw):
    """tpv.one() re-pointed at this module's synthetic chunk (same instrument, coverage selector for TEXT)."""
    d = tpv.one(**kw)
    d["instruments"][0]["manifest_ids"] = [MID]
    d["coverage"][0]["selector"].update(manifest_id=MID, sha256=SHA, provision_id="Rule 5", text_sha256=sha_text(text))
    return d


def runtime_for(c, mode="restrict", **kw):
    inputs = vr.Inputs(ledger=c.ledger, decision_register=c.register, evidence_manifest=c.manifest, evidence_dir=c.evidence,
                       registry=c.registry, approval=c.approval, trusted_keys=c.keys)
    kw.setdefault("clock", CLOCK)
    return vr.ValidityRuntime(mode, inputs, **kw)


def registry_sha(c):
    return la.sha256_file(c.registry)


class ChainCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def chain(self, led=None, **kw):
        return tb.make_chain(self._tmp.name, ledger() if led is None else led, **kw)

    def accepted(self, c=None, mode="restrict", **kw):
        c = c or self.chain()
        rt = runtime_for(c, mode, **kw)
        rt.load(c.metadatas, registry_sha256=registry_sha(c), approval_valid=True)
        return c, rt


# ------------------------------------------------------------------------------------------------ the mode

class ModeTests(unittest.TestCase):
    def test_unset_and_empty_are_off(self):
        for raw in (None, "", "  ", "off", "OFF", " Off "):
            self.assertEqual(vr.parse_mode(raw), ("off", None), raw)

    def test_shadow_and_restrict_are_recognised(self):
        self.assertEqual(vr.parse_mode("shadow"), ("shadow", None))
        self.assertEqual(vr.parse_mode(" RESTRICT "), ("restrict", None))

    def test_enforce_and_typos_are_never_off(self):
        for raw in ("enforce", "ENFORCE", "restict", "on", "true", "1", 1, True, ["off"]):
            mode, problem = vr.parse_mode(raw)
            self.assertEqual(mode, "restrict", raw)
            self.assertTrue(problem, raw)

    def test_a_misconfigured_mode_serves_nothing_and_cannot_be_accepted(self):
        for raw in ("enforce", "restict"):
            mode, problem = vr.parse_mode(raw)
            rt = vr.ValidityRuntime(mode, vr.Inputs(), mode_problem=problem, accept=mock.Mock(side_effect=AssertionError("gate")))
            rt.load([], registry_sha256="a" * 64, approval_valid=True)
            self.assertEqual(rt.state, "misconfigured")
            self.assertTrue(rt.serving_errors())
            self.assertEqual(rt.filter([chunk()]), [])
            rt.invalidate()
            self.assertEqual(rt.state, "misconfigured")

    def test_enforce_is_still_locked_in_the_library(self):
        self.assertTrue(pv.ENFORCE_LOCKED)
        self.assertEqual(pv.normalize_mode("enforce"), "off")


class OffTests(unittest.TestCase):
    def test_off_reads_nothing_and_changes_nothing(self):
        gate = mock.Mock(side_effect=AssertionError("the gate must not run while off"))
        rt = vr.ValidityRuntime("off", vr.Inputs(ledger=Path("/nonexistent")), accept=gate)
        rt.load([], registry_sha256=None, approval_valid=False)
        docs = [chunk(), chunk("other text")]
        self.assertEqual(rt.filter(docs), docs)
        self.assertEqual(rt.serving_errors(), [])
        self.assertIsNone(rt.fingerprint())
        self.assertIsNone(rt.digest())
        self.assertFalse(rt.enabled)
        gate.assert_not_called()


# ------------------------------------------------------------------------------------------------ acceptance before serving

class AcceptanceBeforeServingTests(ChainCase):
    def test_restrict_serves_nothing_until_the_gate_has_passed(self):
        rt = runtime_for(self.chain())
        self.assertFalse(rt.accepted)
        self.assertTrue(rt.serving_errors())
        self.assertEqual(rt.filter([chunk()]), [])

    def test_a_genuine_synthetic_chain_is_accepted(self):
        c, rt = self.accepted()
        self.assertTrue(rt.accepted, rt.problems)
        self.assertEqual(rt.serving_errors(), [])
        self.assertEqual(rt.state, "accepted")

    def test_a_missing_input_is_misconfigured_and_never_calls_the_gate(self):
        gate = mock.Mock(side_effect=AssertionError("gate"))
        rt = vr.ValidityRuntime("restrict", vr.Inputs(ledger=Path("x")), accept=gate)
        rt.load([], registry_sha256="a" * 64, approval_valid=True)
        self.assertEqual(rt.state, "misconfigured")
        self.assertIn("TG_VALIDITY_DECISION_REGISTER_FILE", rt.problems[0])
        self.assertEqual(rt.filter([chunk()]), [])

    def test_the_servers_own_approval_must_be_valid(self):
        c = self.chain()
        rt = runtime_for(c)
        rt.load(c.metadatas, registry_sha256=registry_sha(c), approval_valid=False)
        self.assertEqual((rt.state, rt.accepted), ("rejected", False))
        self.assertEqual(rt.filter([chunk()]), [])

    def test_the_chain_must_be_bound_to_the_registry_the_server_uses(self):
        c = self.chain()
        for other in ("0" * 64, None, "not a hash"):
            rt = runtime_for(c)
            rt.load(c.metadatas, registry_sha256=other, approval_valid=True)
            self.assertFalse(rt.accepted, other)
            self.assertEqual(rt.filter([chunk()]), [])

    def test_a_chain_that_fails_the_gate_serves_nothing(self):
        for name, kw in {"unsigned": dict(sign=False), "unbound registry": dict(binding=False),
                         "ledger bytes not the bound ones": dict(bound="f" * 64),
                         "untrusted key": dict(listed=False), "revoked key": dict(key_status="revoked"),
                         "register not bound": dict(register_bound="e" * 64),
                         "manifest not bound": dict(manifest_bound="d" * 64)}.items():
            with self.subTest(name):
                c = self.chain(**kw)
                rt = runtime_for(c)
                rt.load(c.metadatas, registry_sha256=registry_sha(c), approval_valid=True)
                self.assertEqual(rt.state, "rejected")
                self.assertTrue(rt.serving_errors())
                self.assertEqual(rt.filter([chunk()]), [])

    def test_a_pending_decision_behind_a_fact_is_rejected_at_the_gate(self):
        c = self.chain(register_mut=lambda r: r["decisions"][0].update(status="pending"))
        rt = runtime_for(c)
        rt.load(c.metadatas, registry_sha256=registry_sha(c), approval_valid=True)
        self.assertEqual(rt.state, "rejected")
        self.assertEqual(rt.filter([chunk()]), [])

    def test_a_synthetic_fixture_ledger_is_never_served(self):
        c = self.chain(fixture_register=True)
        rt = runtime_for(c)
        rt.load(c.metadatas, registry_sha256=registry_sha(c), approval_valid=True)     # no allow_fixture: the gate refuses it
        self.assertFalse(rt.accepted)
        self.assertEqual(rt.filter([chunk()]), [])
        flagged = mock.Mock(return_value=mock.Mock(ok=True, ledger=object(), fixture=True, problems=(), registry_sha256=registry_sha(c)))
        rt2 = runtime_for(c, accept=flagged)
        rt2.load(c.metadatas, registry_sha256=registry_sha(c), approval_valid=True)
        self.assertEqual(rt2.state, "rejected")

    def test_the_gate_raising_is_a_rejection(self):
        c = self.chain()
        rt = runtime_for(c, accept=mock.Mock(side_effect=RuntimeError("boom")))
        rt.load(c.metadatas, registry_sha256=registry_sha(c), approval_valid=True)
        self.assertEqual(rt.state, "rejected")
        self.assertEqual(rt.filter([chunk()]), [])
        self.assertNotIn("boom", " ".join(rt.problems))

    def test_a_changed_input_withdraws_the_acceptance_and_only_load_restores_it(self):
        c, rt = self.accepted()
        self.assertTrue(rt.accepted)
        before = rt.digest()
        rt.invalidate()
        self.assertEqual(rt.state, "stale")
        self.assertTrue(rt.serving_errors())
        self.assertEqual(rt.filter([chunk()]), [])
        self.assertNotEqual(rt.digest(), before)
        rt.load(c.metadatas, registry_sha256=registry_sha(c), approval_valid=True)
        self.assertTrue(rt.accepted)

    def test_replacing_the_ledger_file_changes_the_fingerprint(self):
        c, rt = self.accepted()
        before = rt.fingerprint()
        c.ledger.write_bytes(c.ledger.read_bytes() + b" ")
        self.assertNotEqual(rt.fingerprint(), before)

    def test_reloading_a_chain_that_no_longer_passes_withdraws_the_acceptance(self):
        c, rt = self.accepted()
        c.ledger.write_bytes(b"{}")
        rt.load(c.metadatas, registry_sha256=registry_sha(c), approval_valid=True)
        self.assertEqual(rt.state, "rejected")
        self.assertEqual(rt.filter([chunk()]), [])

    def test_the_real_deployment_files_are_refused(self):
        """No real ledger, register or manifest exists. Pointed at the real approval/registry, restrict refuses to serve."""
        inputs = vr.Inputs(ledger=ROOT / "legal-status" / "no-such-ledger.json", decision_register=ROOT / "legal-status" / "no-such-register.json",
                           evidence_manifest=ROOT / "legal-status" / "no-such-manifest.json", evidence_dir=ROOT / "legal-status",
                           registry=ROOT / "legal-status" / "source-status.json", approval=ROOT / "legal" / "telangana-approval.json",
                           trusted_keys=ROOT / "legal" / "no-such-keys.json")
        rt = vr.ValidityRuntime("restrict", inputs)
        rt.load([], registry_sha256=REAL_REGISTRY_SHA256, approval_valid=True)
        self.assertFalse(rt.accepted)
        self.assertEqual(rt.filter([chunk()]), [])


# ------------------------------------------------------------------------------------------------ chunk filtering

class FilterTests(ChainCase):
    def kept(self, led, doc=None, offence_date=None, **kw):
        c, rt = self.accepted(self.chain(led, **kw))
        self.assertTrue(rt.accepted, rt.problems)
        return rt.filter([doc or chunk()], offence_date), rt

    def test_a_covered_in_force_chunk_is_kept(self):
        kept, _ = self.kept(ledger())
        self.assertEqual(len(kept), 1)

    def test_an_uncovered_chunk_is_removed(self):
        c, rt = self.accepted()
        for name, doc in {"other text": chunk("Rule 6. Something else."), "other provision": chunk(provision_id="Rule 6"),
                          "other manifest": chunk(manifest_id="another-doc"), "other file hash": chunk(sha256="c" * 64),
                          "other part": chunk(part=2, parts=2), "other pages": chunk(page_start=2, page_end=2),
                          "no metadata": Document(page_content=TEXT, metadata={})}.items():
            with self.subTest(name):
                self.assertEqual(rt.filter([doc]), [])

    def test_a_chunk_whose_text_changed_since_coverage_is_removed(self):
        _, rt = self.accepted()
        self.assertEqual(rt.filter([chunk(TEXT + " (amended)")]), [])

    def test_unapproved_unverified_expired_and_pending_states_are_removed(self):
        cases = {
            "start not approved": ledger(start_ok=False),
            "end unverified": ledger(end=("u", None)),
            "freshness lapsed": ledger(end=("cv", 29000601)),
            "text not held": ledger(held=False),
            "closed (not current)": ledger(end=("closed", 29050101)),
            "no freshness window": ledger(fresh=None),
            "no interval rule, closed": ledger(rule=False, end=("closed", 29050101)),
            "not yet in force": ledger(start=29200101, end=("cv", 29300101)),
        }
        for name, led in cases.items():
            with self.subTest(name):
                kept, _ = self.kept(led)
                self.assertEqual(kept, [], name)

    def test_a_dated_question_may_use_a_closed_version_inside_its_range_only(self):
        led = ledger(end=("closed", 29050101))
        c, rt = self.accepted(self.chain(led))
        self.assertTrue(rt.accepted, rt.problems)
        inside, before, after = dt.date(2903, 1, 1), dt.date(2899, 1, 1), dt.date(2906, 1, 1)
        self.assertEqual(len(rt.filter([chunk()], inside)), 1)
        self.assertEqual(rt.filter([chunk()], before), [])
        self.assertEqual(rt.filter([chunk()], after), [])
        self.assertEqual(rt.filter([chunk()], None), [])            # an undated question never gets a closed version

    def test_the_filter_never_adds_or_reorders(self):
        _, rt = self.accepted()
        a, b, c3 = chunk(), chunk("zzz"), chunk()
        out = rt.filter([a, b, c3])
        self.assertEqual(out, [a, c3])
        self.assertTrue(all(any(o is d for d in (a, b, c3)) for o in out))
        self.assertEqual(rt.filter([]), [])
        self.assertEqual(rt.filter(None), [])

    def test_a_bad_chunk_or_clock_fails_closed(self):
        _, rt = self.accepted()
        for bad in (None, "text", object(), mock.Mock(page_content=TEXT, metadata=None), Document(page_content="", metadata={})):
            self.assertEqual(rt.filter([bad]), [])
        c2 = self.chain()
        rt2 = runtime_for(c2, clock=lambda: None)
        rt2.load(c2.metadatas, registry_sha256=registry_sha(c2), approval_valid=True)
        self.assertEqual(rt2.filter([chunk()]), [])

    def test_shadow_never_removes_and_logs_what_it_would(self):
        c, rt = self.accepted(mode="shadow")
        docs = [chunk(), chunk("uncovered text")]
        with self.assertLogs(vr.log, level="INFO") as logs:
            out = rt.filter(docs)
        self.assertEqual(out, docs)
        self.assertTrue(any("would remove" in line for line in logs.output))
        self.assertEqual(rt.serving_errors(), [])

    def test_shadow_does_not_block_serving_when_the_chain_is_not_accepted(self):
        rt = runtime_for(self.chain(), mode="shadow")
        self.assertEqual(rt.serving_errors(), [])
        docs = [chunk()]
        self.assertEqual(rt.filter(docs), docs)

    def test_status_shows_no_paths(self):
        c, rt = self.accepted()
        text = json.dumps(rt.status())
        self.assertNotIn(self._tmp.name, text)
        self.assertNotIn("/", text.replace("sha256", ""))
        self.assertEqual(rt.status()["mode"], "restrict")


# ------------------------------------------------------------------------------------------------ citation mapping

class Ev:
    def __init__(self, doc, **over):
        m = doc.metadata
        self.sha256, self.provision_id = m.get("sha256"), m.get("provision_id")
        self.chunk_id = grounded_answer.chunk_id_of(m)
        self.__dict__.update(over)


class CitationMappingTests(unittest.TestCase):
    APPROVED = {SHA: ("Synthetic Motor Rules", "Rules")}

    def errors(self, doc=None, ev=None, approved=None):
        doc = doc or chunk()
        return vr.citation_errors([ev or Ev(doc)], [doc], self.APPROVED if approved is None else approved)

    def test_an_exact_mapping_has_no_errors(self):
        self.assertEqual(self.errors(), [])

    def test_each_break_is_reported(self):
        d = chunk()
        cases = {
            "document not approved": self.errors(approved={}),
            "no file hash": self.errors(doc=chunk(sha256=None)),
            "malformed file hash": self.errors(doc=chunk(sha256="ABC")),
            "citation hash differs": self.errors(ev=Ev(d, sha256="c" * 64)),
            "no provision": self.errors(doc=chunk(provision_id="")),
            "provision not a string": self.errors(doc=chunk(provision_id=7)),
            "citation names another provision": self.errors(ev=Ev(d, provision_id="Rule 6")),
            "no manifest identity": self.errors(doc=chunk(manifest_id=None)),
            "citation is for another chunk": self.errors(ev=Ev(d, chunk_id="elsewhere")),
        }
        for name, problems in cases.items():
            with self.subTest(name):
                self.assertTrue(problems, name)

    def test_the_counts_must_match(self):
        d = chunk()
        self.assertTrue(vr.citation_errors([Ev(d), Ev(d)], [d], self.APPROVED))
        self.assertTrue(vr.citation_errors([], [d], self.APPROVED))
        self.assertEqual(vr.citation_errors([], [], self.APPROVED), [])


# ------------------------------------------------------------------------------------------------ the server

class ServerBase(ts.Base):
    """Grounded mode with an in-memory approval (as test_server does) plus a synthetic signed validity chain."""

    CLAIM = "A learner's licence application is made in Form 2."

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.log_calls = []
        FAKE_LLM = ts.FAKE_LLM

        def trap(prompt):
            self.log_calls.append(prompt)
            raise AssertionError("unexpected legacy model call")
        FAKE_LLM["fn"] = trap
        self.mock = grounded_answer.MockGenerator(json.dumps({
            "answer": self.CLAIM, "evidence_sufficiency": "sufficient",
            "claims": [{"text": self.CLAIM, "kind": "direct", "evidence_ids": ["E1"]}], "citations": ["E1"],
            "refusal_reason": None, "clarification_question": None}))
        ts.FAKE_SEARCH["fn"] = lambda q, s, docs: [(chunk(), 0.3)]

    patch = ts.GroundedAnswerIntegrationTests.patch

    def use_chain(self, mode="restrict", accept_chain=True, **chain_kw):
        c = tb.make_chain(self._tmp.name, ledger(), **chain_kw)
        digest = registry_sha(c)
        rt = runtime_for(c, mode)
        if accept_chain:
            rt.load(c.metadatas, registry_sha256=digest, approval_valid=True)
        status = la.ApprovalStatus("valid", [], la.ApprovalRecord(
            jurisdiction="Telangana", reviewer_name="Test Reviewer", reviewer_designation="Test",
            approval_date=dt.date(2026, 1, 1), decision="approved", conditions=(), unresolved_conditions=0,
            corpus_version="test-v1", general_answers_approved=True, penalty_answers_approved=False,
            source_status_sha256=digest,
            documents=(la.ApprovedDocument(ts.TG_RULES_FILE, SHA, "Synthetic Motor Rules", "Rules"),)))
        self.patch(GROUNDED_ANSWERS_ENABLED=True, ANSWER_MODE="grounded",
                   PENALTY_ANSWERS_ENABLED=False, CORPUS_DIR=Path("corpus.test"),
                   ANSWER_GENERATOR=self.mock, ensure_approval_current=lambda: None, _STALE=False,
                   SOURCE_STATUS=ts.fixture_registry(SHA, ts.TG_RULES_FILE, digest=digest), VALIDITY=rt)
        p = mock.patch.dict(ts.srv.SOURCES, {SHA: ("Synthetic Motor Rules", "Rules")}, clear=True)
        p.start()
        self.addCleanup(p.stop)
        return c, rt

    def ask(self, message=QUESTION, sid="v"):
        return self.post(message, sid).json()


class ServerIntegrationTests(ServerBase):
    def test_the_default_is_off_and_nothing_changes(self):
        self.assertEqual(ts.srv.VALIDITY.mode, "off")
        self.assertFalse(ts.srv.VALIDITY.enabled)
        self.assertNotIn("validity", " ".join(ts.srv.grounded_gate_errors()).lower())
        self.assertNotIn("validity_layer", self.client.get("/status").json())

    def test_a_valid_approval_alone_answers_when_the_layer_is_off(self):          # the control for every test below
        self.use_chain(mode="off", accept_chain=False)
        r = self.ask()
        self.assertEqual(r["kind"], "answer", r)

    def test_restrict_without_an_accepted_chain_refuses_before_any_retrieval(self):
        self.use_chain(accept_chain=False)
        ts.SEARCH_LOG.clear()
        r = self.ask()
        self.assertEqual(r["kind"], "unavailable")
        self.assertEqual(ts.SEARCH_LOG, [])                  # nothing was retrieved
        self.assertEqual(self.mock.calls if hasattr(self.mock, "calls") else [], [])
        self.assertEqual(self.log_calls, [])
        self.assertTrue(any("provision validity" in e for e in ts.srv.grounded_gate_errors()))

    def test_retrieval_itself_returns_nothing_until_the_chain_is_accepted(self):
        self.use_chain(accept_chain=False)
        self.assertEqual(ts.srv.retrieve(QUESTION), [])
        docs, routing = ts.srv.retrieve_dated(QUESTION, dt.date(2026, 1, 1))
        self.assertEqual(docs, [])

    def test_restrict_with_an_accepted_chain_answers_and_cites_the_exact_provision(self):
        self.use_chain()
        r = self.ask()
        self.assertEqual(r["kind"], "answer", r)
        self.assertIn("**Sources**", r["response"])
        self.assertIn("Rule 5", r["response"])
        passage = r["sources"][0]["passages"][0]
        self.assertEqual((passage["provision_id"], passage["sha256"], passage["manifest_id"], passage["cited"]),
                         ("Rule 5", SHA, MID, True))
        self.assertEqual(r["sources"][0]["title"], "Synthetic Motor Rules")
        self.assertEqual(self.log_calls, [])

    def test_a_chunk_the_ledger_does_not_cover_is_never_served(self):
        self.use_chain()
        ts.FAKE_SEARCH["fn"] = lambda q, s, docs: [(chunk("Rule 6. Uncovered text."), 0.3)]
        r = self.ask()
        self.assertEqual(r["kind"], "no_support", r)
        self.assertEqual(r["sources"], [])
        self.assertNotIn("**Sources**", r["response"])

    def test_an_expired_or_unverified_provision_is_never_served(self):
        for name, led in {"lapsed freshness": ledger(end=("cv", 29000601)), "unverified end": ledger(end=("u", None)),
                          "start unapproved": ledger(start_ok=False)}.items():
            with self.subTest(name):
                c = tb.make_chain(self._tmp.name, led)
                rt = runtime_for(c)
                rt.load(c.metadatas, registry_sha256=registry_sha(c), approval_valid=True)
                self.assertTrue(rt.accepted, rt.problems)
                with mock.patch.object(ts.srv, "VALIDITY", rt):
                    self.assertEqual(ts.srv.retrieve(QUESTION), [])

    def test_the_ledger_cannot_serve_a_chunk_the_existing_checks_refuse(self):
        self.use_chain()
        for name, doc in {"not an approved document": chunk(sha256="c" * 64), "not answer eligible": chunk(answer_eligible=False),
                          "not a served state": chunk(state="Gujarat")}.items():
            with self.subTest(name):
                ts.FAKE_SEARCH["fn"] = lambda q, s, docs, d=doc: [(d, 0.3)]
                self.assertEqual(ts.srv.retrieve(QUESTION), [], name)

    def test_a_chain_that_stops_passing_stops_serving_on_the_next_request(self):
        c, rt = self.use_chain()
        self.assertEqual(self.ask(sid="a")["kind"], "answer")
        rt.invalidate()
        self.assertEqual(self.ask(sid="b")["kind"], "unavailable")

    def test_the_legacy_development_path_is_refused_too_until_the_chain_is_accepted(self):
        calls = []
        ts.FAKE_LLM["fn"] = lambda prompt: calls.append(prompt) or "stub"
        rt = runtime_for(tb.make_chain(self._tmp.name, ledger()))                    # restrict, never loaded
        self.patch(ANSWER_MODE="legacy_dev", VALIDITY=rt)
        ts.SEARCH_LOG.clear()
        r = self.ask("What is a learner's licence?")
        self.assertEqual(r["kind"], "unavailable", r)
        self.assertEqual((calls, ts.SEARCH_LOG), ([], []))

    def test_a_changed_input_marks_the_chain_stale_on_the_next_request(self):
        c, rt = self.use_chain()
        self.assertTrue(rt.accepted)
        self.patch(ensure_approval_current=ORIGINAL_ENSURE, _FINGERPRINT=("something else",))
        ORIGINAL_ENSURE()
        self.assertEqual(rt.state, "stale")
        self.assertEqual(self.ask()["kind"], "unavailable")

    def test_the_cache_epoch_moves_with_the_validity_state(self):
        c, rt = self.use_chain()
        before = ts.srv.cache_epoch()
        rt.invalidate()
        self.assertNotEqual(ts.srv.cache_epoch(), before)

    def test_a_cached_answer_cannot_use_a_chunk_the_ledger_would_now_remove(self):
        c, rt = self.use_chain()
        live = {ts.srv.chunk_identity(chunk()): chunk()}
        with mock.patch.object(ts.srv, "live_chunks", return_value=live):
            self.assertIsNotNone(ts.srv.cache_context([ts.srv.chunk_identity(chunk())]))
            rt.invalidate()
            self.assertIsNone(ts.srv.cache_context([ts.srv.chunk_identity(chunk())]))

    def test_status_reports_the_layer_without_paths(self):
        self.use_chain()
        body = self.client.get("/status").json()
        self.assertEqual(body["validity_layer"]["mode"], "restrict")
        self.assertTrue(body["validity_layer"]["accepted"])
        self.assertNotIn(self._tmp.name, json.dumps(body["validity_layer"]))

    def test_a_citation_that_does_not_map_withholds_the_answer(self):
        self.use_chain()
        with mock.patch.object(vr, "citation_errors", return_value=["[1] the citation is not for the cited passage"]):
            r = self.ask()
        self.assertEqual(r["kind"], "no_support", r)
        self.assertEqual(r["sources"], [])
        self.assertNotIn("**Sources**", r["response"])
        self.assertNotIn(self.CLAIM, r["response"])

    def test_a_cached_answer_whose_citation_does_not_map_is_not_replayed(self):
        c, rt = self.use_chain()
        docs = [ts.srv.with_text_status(chunk())]
        contract, kept = grounded_answer.build_contract(QUESTION, docs)
        entry = mock.Mock(raw=self.mock.raw if hasattr(self.mock, "raw") else json.dumps({
            "answer": self.CLAIM, "evidence_sufficiency": "sufficient",
            "claims": [{"text": self.CLAIM, "kind": "direct", "evidence_ids": ["E1"]}], "citations": ["E1"],
            "refusal_reason": None, "clarification_question": None}), cited_ids=(ts.srv.chunk_identity(docs[0]),))
        self.assertIsNotNone(ts.srv.cache_replay(QUESTION, entry, docs))
        with mock.patch.object(vr, "citation_errors", return_value=["bad"]):
            self.assertIsNone(ts.srv.cache_replay(QUESTION, entry, docs))

    def test_penalty_and_compounding_questions_stay_refused_with_an_accepted_chain(self):
        self.use_chain()
        for q in ("What is the fine for riding without a helmet?", "What is the penalty for no licence?",
                  "What is the compounding fee for over speeding?", "How much is the challan for signal jumping?",
                  "How much compounding amount applies under Section 200?"):
            with self.subTest(q):
                ts.SEARCH_LOG.clear()
                r = self.ask(q, sid=q[:12])
                self.assertIn(r["kind"], ("restricted", "unavailable", "clarification", "guard", "no_support", "missing_provision"), r)
                self.assertNotEqual(r["kind"], "answer")
                self.assertNotRegex(r["response"], r"₹|\bRs\.?\s*\d|\b\d{3,}\b")
                self.assertEqual(self.log_calls, [])
        self.assertTrue(ts.srv.penalty_lock_reason("What is the fine for riding without a helmet?"))
        self.assertFalse(ts.srv.PENALTY_ANSWERS_ENABLED)

    def test_penalty_approval_still_blocks_grounded_answers(self):
        self.use_chain()
        with mock.patch.object(ts.srv, "PENALTY_ANSWERS_ENABLED", True):
            self.assertIn("penalty answers are enabled", ts.srv.grounded_gate_errors())


class EndToEndTests(ServerBase):
    """The final end-to-end checks through POST /chat: evidence, citations, refusals, exclusions, penalty lock and both caches."""

    def cache_on(self, mode):
        from backend import answer_cache
        settings = answer_cache.Settings(mode=mode)
        self.patch(CACHE_SETTINGS=settings, ANSWER_CACHE=answer_cache.AnswerCache(settings),
                   live_chunks=lambda: {ts.srv.chunk_identity(chunk()): chunk()})
        if mode == "semantic":
            self.patch(cache_query_vector=lambda q: [1.0, 0.0, 0.0])      # every question embeds alike: a paraphrase is a near match
        return ts.srv.ANSWER_CACHE

    def swap_ledger(self, led, **kw):
        c = tb.make_chain(self._tmp.name, led, **kw)
        rt = runtime_for(c)
        rt.load(c.metadata if hasattr(c, "metadata") else c.metadatas, registry_sha256=registry_sha(c), approval_valid=True)
        self.assertTrue(rt.accepted, rt.problems)
        self.patch(VALIDITY=rt)
        return rt

    # 1-2: a supported question is answered with exact citations
    def test_a_supported_question_is_answered_and_every_citation_maps_exactly(self):
        self.use_chain()
        r = self.ask()
        self.assertEqual(r["kind"], "answer", r)
        self.assertIn("- [1] **Telangana** · Synthetic Motor Rules – Rule 5", r["response"])
        src = r["sources"][0]
        self.assertEqual((src["title"], src["verified"], src["sha256"], src["files"][0]["manifest_id"]),
                         ("Synthetic Motor Rules", True, SHA, MID))
        self.assertEqual([(p["provision_id"], p["sha256"], p["manifest_id"], p["cited"]) for p in src["passages"]],
                         [("Rule 5", SHA, MID, True)])
        self.assertEqual(self.log_calls, [])

    # 3: missing or insufficient evidence refuses
    def test_missing_or_insufficient_evidence_refuses(self):
        self.use_chain()
        ts.FAKE_SEARCH["fn"] = lambda q, s, docs: []
        r = self.ask(sid="none")
        self.assertEqual((r["kind"], r["sources"]), ("no_support", []))
        ts.FAKE_SEARCH["fn"] = lambda q, s, docs: [(chunk(), 0.3)]
        self.patch(ANSWER_GENERATOR=grounded_answer.MockGenerator(json.dumps({
            "answer": "", "evidence_sufficiency": "insufficient", "claims": [], "citations": [],
            "refusal_reason": "the passage does not answer this", "clarification_question": None})))
        r = self.ask(sid="insufficient")
        self.assertEqual((r["kind"], r["sources"]), ("no_support", []))
        self.assertNotIn("**Sources**", r["response"])

    # 4: pending / unapproved sources are excluded
    def test_pending_and_unapproved_sources_are_excluded(self):
        self.use_chain(register_mut=lambda reg: reg["decisions"][0].update(status="pending"))     # a pending decision behind a fact
        self.assertEqual(self.ask(sid="pending")["kind"], "unavailable")
        self.use_chain()
        ts.FAKE_SEARCH["fn"] = lambda q, s, docs: [(chunk(sha256="c" * 64), 0.3)]                 # a document the approval does not list
        self.assertEqual(self.ask(sid="unapproved")["kind"], "no_support")
        ts.FAKE_SEARCH["fn"] = lambda q, s, docs: [(chunk(verification_status="unverified", answer_eligible=False), 0.3)]
        self.assertEqual(self.ask(sid="ineligible")["kind"], "no_support")

    # 5: outdated or invalid provisions are excluded
    def test_outdated_and_invalid_provisions_are_excluded(self):
        self.use_chain()
        for name, doc in {"ended under the existing validity metadata": chunk(valid_from=20000101, valid_to=20200101),
                          "not yet begun": chunk(valid_from=29990101), "malformed validity range": chunk(valid_from=20300101, valid_to=20200101)}.items():
            with self.subTest(name):
                ts.FAKE_SEARCH["fn"] = lambda q, s, docs, d=doc: [(d, 0.3)]
                self.assertEqual(self.ask(sid=name[:8])["kind"], "no_support", name)
        ts.FAKE_SEARCH["fn"] = lambda q, s, docs: [(chunk(), 0.3)]
        for name, led in {"freshness lapsed": ledger(end=("cv", 29000601)), "end unverified": ledger(end=("u", None)),
                          "closed": ledger(end=("closed", 29050101)), "start unapproved": ledger(start_ok=False)}.items():
            with self.subTest(name):
                self.swap_ledger(led)
                self.assertEqual(self.ask(sid=name[:8])["kind"], "no_support", name)

    # 6: penalty and compounding stay refused
    def test_penalty_and_compounding_questions_stay_refused_even_when_the_chunk_is_covered(self):
        covered = "Rule 5. The compounding fee and the fine for this offence is stated in the schedule."
        self.use_chain()
        led = ledger(covered)
        self.swap_ledger(led)
        ts.FAKE_SEARCH["fn"] = lambda q, s, docs: [(chunk(covered), 0.3)]
        for q in ("What is the compounding fee for this offence?", "What fine applies under Rule 5?", "How much penalty for this?",
                  "compounding amount for a two wheeler"):
            with self.subTest(q):
                r = self.ask(q, sid=q[:10])
                self.assertNotEqual(r["kind"], "answer", r)
                self.assertNotIn("**Sources**", r["response"])
        self.assertEqual(self.log_calls, [])

    # 7: both cache paths keep every check
    def test_the_exact_cache_hits_only_while_the_chain_and_ledger_still_allow_the_chunk(self):
        cache = self.cache_on("exact")
        rt = self.use_chain()[1]
        first = self.ask(sid="e1")
        self.assertEqual(first["kind"], "answer", first)
        self.assertEqual(cache.snapshot()["entries"], 1)
        calls = len(self.mock.calls)
        self.assertEqual(self.ask(sid="e2")["kind"], "answer")
        self.assertEqual((cache.stats["hit_exact"], len(self.mock.calls)), (1, calls))        # served from cache, no new generation
        self.swap_ledger(ledger(end=("cv", 29000601)))                                         # the ledger no longer allows the chunk
        again = self.ask(sid="e3")
        self.assertNotEqual(again["kind"], "answer", again)
        self.assertEqual(cache.stats["hit_exact"], 1)                                          # never replayed
        rt.invalidate()
        self.patch(VALIDITY=rt)
        self.assertEqual(self.ask(sid="e4")["kind"], "unavailable")
        self.assertEqual(cache.snapshot()["entries"], 0)                                       # the epoch moved: nothing older survives

    def test_the_semantic_cache_hits_only_after_a_fresh_retrieval_the_ledger_allows(self):
        cache = self.cache_on("semantic")
        self.use_chain()
        self.assertEqual(self.ask(QUESTION, sid="s1")["kind"], "answer")
        calls = len(self.mock.calls)
        paraphrase = "Please explain how I apply for a learner's licence"
        hit = self.ask(paraphrase, sid="s2")
        self.assertEqual(hit["kind"], "answer", hit)
        self.assertEqual((cache.stats["hit_semantic"], len(self.mock.calls)), (1, calls))
        self.assertIn("- [1] **Telangana** · Synthetic Motor Rules – Rule 5", hit["response"])      # citations rebuilt from the live chunk
        self.swap_ledger(ledger(end=("u", None)))                                              # the chunk is removed before the cache is consulted
        gone = self.ask("Tell me how to apply for a learner's licence", sid="s3")
        self.assertNotEqual(gone["kind"], "answer", gone)
        self.assertEqual(cache.stats["hit_semantic"], 1)

    def test_a_cached_answer_is_not_replayed_when_the_chunk_text_or_citation_no_longer_maps(self):
        cache = self.cache_on("exact")
        self.use_chain()
        self.assertEqual(self.ask(sid="m1")["kind"], "answer")
        ts.FAKE_SEARCH["fn"] = lambda q, s, docs: [(chunk(TEXT + " (amended)"), 0.3)]
        self.patch(live_chunks=lambda: {ts.srv.chunk_identity(chunk(TEXT + " (amended)")): chunk(TEXT + " (amended)")})
        r = self.ask(sid="m2")
        self.assertNotEqual(r["kind"], "answer", r)             # the ledger covers the old text only: stale coverage removes the chunk
        self.assertEqual(cache.stats["hit_exact"], 0)


class ServerConfigTests(unittest.TestCase):
    def test_enforce_serves_nothing(self):
        server = ts._import_server_with_fakes({"TG_PROVISION_VALIDITY": "enforce"})
        self.assertEqual((server.VALIDITY.mode, server.VALIDITY.state), ("restrict", "misconfigured"))
        self.assertTrue(server.VALIDITY.serving_errors())
        self.assertEqual(server.VALIDITY.filter([chunk()]), [])

    def test_a_typo_serves_nothing(self):
        server = ts._import_server_with_fakes({"TG_PROVISION_VALIDITY": "restict"})
        self.assertEqual(server.VALIDITY.state, "misconfigured")

    def test_restrict_without_configured_files_serves_nothing(self):
        server = ts._import_server_with_fakes({"TG_PROVISION_VALIDITY": "restrict"})
        server._load_validity()
        self.assertEqual(server.VALIDITY.state, "misconfigured")
        self.assertTrue(server.grounded_gate_errors())
        self.assertTrue(any("provision validity" in e for e in server.grounded_gate_errors()))

    def test_unset_is_off(self):
        server = ts._import_server_with_fakes({"TG_PROVISION_VALIDITY": None})
        self.assertEqual(server.VALIDITY.mode, "off")
        self.assertIsNone(server.VALIDITY.fingerprint())


# ------------------------------------------------------------------------------------------------ isolation and limits

class IsolationAndLimitsTests(unittest.TestCase):
    def test_only_the_server_imports_the_runtime_wrapper(self):
        for p in sorted((ROOT / "backend").glob("*.py")):
            text = p.read_text(encoding="utf-8", errors="replace")
            uses = re.search(r"^\s*(?:from backend import[^\n]*\bprovision_validity_runtime\b|from backend\.provision_validity_runtime|"
                             r"import backend\.provision_validity_runtime|import provision_validity_runtime)", text, re.M)
            if p.name in ("server.py", "provision_validity_runtime.py"):
                continue
            with self.subTest(p.name):
                self.assertIsNone(uses)

    def test_the_server_does_not_call_the_gate_or_the_library_directly(self):
        text = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
        for forbidden in ("accept_ledger", "ledger_acceptance", "resolve_chunk", "load_ledger", "validity_decisions", "evidence_manifest"):
            self.assertNotIn(forbidden, text)

    def test_the_wrapper_never_writes_a_file_or_enables_enforce(self):
        text = (ROOT / "backend" / "provision_validity_runtime.py").read_text(encoding="utf-8")
        for forbidden in ("write_text", "write_bytes", "open(", ".unlink", "os.remove", "shutil", "ENFORCE_LOCKED = False", "\"enforce\"):"):
            self.assertNotIn(forbidden, text, forbidden)
        self.assertIn('"restrict"', text)

    def test_the_gate_has_no_date_parameter_and_the_wrapper_adds_none(self):
        self.assertNotIn("today", inspect.signature(ledger_acceptance.accept_ledger).parameters)
        self.assertNotIn("today", inspect.signature(vr.ValidityRuntime.load).parameters)

    def test_replay_protection_is_recorded_as_a_deferred_limitation(self):
        text = (ROOT / "docs" / "approval-trust-model.md").read_text(encoding="utf-8").lower()
        section = text[text.index("## provision-level validity in the application"):]
        self.assertIn("replay", section)
        self.assertIn("deferred", section)
        self.assertIn("not implemented", section)

    def test_the_real_registry_and_register_are_unchanged(self):
        self.assertEqual(hashlib.sha256((ROOT / "legal-status" / "source-status.json").read_bytes()).hexdigest(), REAL_REGISTRY_SHA256)
        self.assertEqual(hashlib.sha256(sup.REAL_REGISTER.read_bytes()).hexdigest(), REAL_REGISTER_SHA256)


if __name__ == "__main__":
    unittest.main()
