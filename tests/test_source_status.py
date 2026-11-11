"""Stage 25: source-status registry, its approval binding, and warning propagation. Offline: fixtures, mocks,
throwaway in-memory keys only. No Ollama, Chroma, Groq or network."""

import copy
import datetime as dt
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from langchain_core.documents import Document

import test_legal_approval as tla
import test_server as ts
from backend import grounded_answer, hybrid_retrieval, legal_approval as la, source_status as ss

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_FILE = ROOT / "legal-status" / "source-status.json"
# The legal sources live outside this repository (untracked). Registry checks run against the pinned snapshot in
# tests/fixtures; TG_LEGAL_SOURCES_DIR (default: the sibling checkout) is used only to confirm that snapshot still
# matches the live files. KYR_REQUIRE_LEGAL_DATA=1 makes missing live files a failure instead of a skip.
SOURCES_DIR = Path(os.environ.get("TG_LEGAL_SOURCES_DIR")
                   or ROOT.parent / "KnowYourRules-repo" / "docs" / "legal-sources" / "telangana-traffic")
REQUIRE_LEGAL_DATA = os.environ.get("KYR_REQUIRE_LEGAL_DATA") == "1"
SNAPSHOT = json.loads((ROOT / "tests" / "fixtures" / "legal-data-snapshot.json").read_text(encoding="utf-8"))


def skip_or_fail(test, reason):
    if REQUIRE_LEGAL_DATA:
        test.fail(f"{reason} (KYR_REQUIRE_LEGAL_DATA=1)")
    test.skipTest(reason)
TODAY = dt.date(2026, 11, 11)
SHA_A, SHA_B = "a" * 64, "b" * 64
RULE81_FILE_SHA = "d901ad962697002883f18c9f4c97f530de64966931f13bbd91d49708b391a3ba"
GO77_SHA = "3de907353bdf37415df25f10d45b05e336bd29c077285fae2c9bda2655f7be71"
NO_REVIEW = {"reviewer": None, "review_date": None, "decision": None, "rationale": None}


def entry(sha=SHA_A, file="a.pdf", status="unverified_snapshot", overrides=(), **kw):
    e = {"manifest_id": file, "file": file, "sha256": sha, "status": status, "label": f"Doc {file}",
         "related_instruments": [], "decision_refs": [], "evidence": [{"file": file, "sha256": sha, "note": "n"}],
         "assigned_by": "fixture", "review": dict(NO_REVIEW), "provision_overrides": list(overrides)}
    if status == "verified_current":
        e.update(review=copy.deepcopy(ts.FIXTURE_REVIEW), decision_refs=["LD-999"])
    if status == "known_amendments_unresolved":
        e["related_instruments"] = ["Amending Order X"]
    e.update(kw)
    return e


def override(provision="Rule 81", status="known_amendments_unresolved", **kw):
    o = {"provision_id": provision, "status": status, "related_instruments": ["G.O.Ms.No. 77, TR&B, 15-11-2025"],
         "decision_refs": ["LD-001", "LD-002"], "evidence": [{"file": "g.pdf", "sha256": GO77_SHA, "note": "n"}],
         "assigned_by": "fixture", "review": dict(NO_REVIEW)}
    o.update(kw)
    return o


def registry(*entries):
    return {"schema_version": 1, "jurisdiction": "Telangana", "note": "fixture", "entries": list(entries)}


def valid(data):
    return ss.Registry("valid", [], "e" * 64, ss.parse(data, TODAY))


def doc(sha=SHA_A, file="a.pdf", provision="Rule 1", text="t"):
    return Document(page_content=text, metadata={"sha256": sha, "source_file": file, "provision_id": provision,
                                                 "state": "Telangana"})


class RegistryParsingTests(unittest.TestCase):
    def assert_rejected(self, data, fragment):
        with self.assertRaises(ss.SourceStatusError) as cm:
            ss.parse(data, TODAY)
        self.assertIn(fragment, str(cm.exception))

    def test_each_status_is_accepted(self):
        for status in ss.STATUSES:
            with self.subTest(status):
                by_hash = ss.parse(registry(entry(status=status)), TODAY)
                self.assertEqual(by_hash[SHA_A]["status"], status)

    def test_unknown_status_rejected(self):
        self.assert_rejected(registry(entry(status="current")), "status must be one of")

    def test_hash_format_rejected(self):
        for bad in ("A" * 64, "a" * 63, "", None, "g" * 64):
            with self.subTest(bad):
                self.assert_rejected(registry(entry(sha=bad)), "sha256 must be 64 lowercase hex")

    def test_duplicate_hash_and_duplicate_file_rejected(self):
        self.assert_rejected(registry(entry(), entry(file="b.pdf")), "duplicates the entry for sha256")
        self.assert_rejected(registry(entry(), entry(sha=SHA_B, file="dir/a.pdf")), "duplicates file name")

    def test_duplicate_provision_override_rejected(self):
        self.assert_rejected(registry(entry(overrides=[override(), override()])), "duplicates provision")

    def test_unknown_or_missing_keys_rejected(self):
        e = entry()
        e["current"] = True
        self.assert_rejected(registry(e), "must have exactly")
        e = entry()
        del e["review"]
        self.assert_rejected(registry(e), "must have exactly")
        self.assert_rejected({"schema_version": 1, "jurisdiction": "Telangana", "entries": []}, "exactly")
        self.assert_rejected(registry(), "non-empty list")

    def test_verified_current_needs_complete_human_review(self):
        self.assert_rejected(registry(entry(status="verified_current", review=dict(NO_REVIEW))),
                             "verified_current requires a complete human review")
        partial = copy.deepcopy(ts.FIXTURE_REVIEW)
        partial["rationale"] = None
        self.assert_rejected(registry(entry(status="verified_current", review=partial)), "partly filled")
        placeholder = copy.deepcopy(ts.FIXTURE_REVIEW)
        placeholder["reviewer"]["name"] = "TBD"
        self.assert_rejected(registry(entry(status="verified_current", review=placeholder)), "placeholder")
        future = copy.deepcopy(ts.FIXTURE_REVIEW)
        future["review_date"] = "2027-01-01"
        self.assert_rejected(registry(entry(status="verified_current", review=future)), "non-future")
        self.assert_rejected(registry(entry(status="verified_current", decision_refs=[])), "must reference")

    def test_known_amendments_must_name_instrument_and_decision_ids_are_checked(self):
        self.assert_rejected(registry(entry(overrides=[override(related_instruments=[])])), "must name the amending")
        self.assert_rejected(registry(entry(overrides=[override(decision_refs=["LD-1"])])), "invalid id")

    def test_evidence_provenance_required(self):
        self.assert_rejected(registry(entry(evidence=[])), "evidence must be a non-empty list")
        self.assert_rejected(registry(entry(evidence=[{"file": "x", "sha256": "bad", "note": "n"}])), "evidence[0]")
        self.assert_rejected(registry(entry(assigned_by="")), "assigned_by")


class RegistryBindingToSourcesTests(unittest.TestCase):
    def test_missing_entry_for_indexed_document(self):
        by_hash = ss.parse(registry(entry()), TODAY)
        errors = ss.index_errors(by_hash, [{"sha256": SHA_A, "source_file": "a.pdf"},
                                           {"sha256": SHA_B, "source_file": "b.pdf"}])
        self.assertEqual(errors, ["missing registry entry for indexed document 'b.pdf'"])

    def test_hash_mismatch_with_index(self):
        by_hash = ss.parse(registry(entry()), TODAY)
        errors = ss.index_errors(by_hash, [{"sha256": SHA_B, "source_file": "a.pdf"}])
        self.assertIn("hash mismatch for 'a.pdf'", errors[0])

    def test_hash_mismatch_with_corpus_file_and_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a.pdf").write_bytes(b"real bytes")
            real = hashlib.sha256(b"real bytes").hexdigest()
            self.assertEqual(ss.corpus_errors(ss.parse(registry(entry(sha=real)), TODAY), d), [])
            self.assertIn("file on disk differs", ss.corpus_errors(ss.parse(registry(entry()), TODAY), d)[0])
            self.assertIn("missing from corpus",
                          ss.corpus_errors(ss.parse(registry(entry(sha=real, file="gone.pdf")), TODAY), d)[0])

    def test_load_fails_closed(self):
        self.assertEqual(ss.load(None).state, "absent")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.json"
            p.write_text("{")
            self.assertEqual(ss.load(p).state, "invalid")
            p.write_text(json.dumps(registry(entry())))
            reg = ss.load(p, [{"sha256": SHA_B, "source_file": "b.pdf"}])
            self.assertEqual(reg.state, "invalid")
            # an invalid registry never yields a status other than "not recorded"
            self.assertEqual(reg.lookup(SHA_A).status, ss.UNRECORDED)
            ok = ss.load(p, [{"sha256": SHA_A, "source_file": "a.pdf"}])
            self.assertEqual((ok.state, ok.sha256), ("valid", hashlib.sha256(p.read_bytes()).hexdigest()))


class LookupAndWarningTests(unittest.TestCase):
    def test_provision_override_applies_only_to_that_provision(self):
        reg = valid(registry(entry(overrides=[override()])))
        self.assertEqual(reg.lookup(SHA_A, "Rule 81").status, "known_amendments_unresolved")
        self.assertEqual(reg.lookup(SHA_A, "Rule 80").status, "unverified_snapshot")
        self.assertEqual(reg.lookup(SHA_A).status, "unverified_snapshot")
        self.assertEqual(reg.lookup(SHA_B).status, ss.UNRECORDED)

    def test_each_status_has_fixed_template_text(self):
        for status in ss.STATUSES:
            reg = valid(registry(entry(status=status)))
            w = ss.collect_warnings(reg, [doc()], trust_verified=True)
            if status == "verified_current":
                self.assertEqual(w, [])
            else:
                self.assertEqual(w[0]["status"], status)
                self.assertTrue(w[0]["text"].startswith("Doc a.pdf"))
        w = ss.collect_warnings(valid(registry(entry())), [doc(sha=SHA_B, file="b.pdf")])
        self.assertEqual(w[0]["text"], ss.TEMPLATES[ss.UNRECORDED].format(label="b.pdf"))

    def test_rule81_warning_names_go77_and_decisions(self):
        reg = valid(registry(entry(overrides=[override()])))
        [w] = ss.collect_warnings(reg, [doc(provision="Rule 81")])
        self.assertEqual(w["status"], "known_amendments_unresolved")
        self.assertIn("G.O.Ms.No. 77, TR&B, 15-11-2025 contains amendments", w["text"])
        self.assertIn("cannot confirm the current law", w["text"])
        self.assertEqual((w["provision_id"], w["decision_refs"]), ("Rule 81", ["LD-001", "LD-002"]))
        # the template never claims the snapshot IS outdated or that G.O. 77 IS in force
        self.assertNotIn("in force", w["text"])
        self.assertNotIn("is outdated", w["text"])

    def test_warnings_are_deduplicated_per_source_and_override(self):
        reg = valid(registry(entry(overrides=[override()])))
        docs = [doc(provision="Rule 81", text="1"), doc(provision="Rule 81", text="2"), doc(provision="Rule 80"),
                doc(provision="Rule 79")]
        w = ss.collect_warnings(reg, docs, [1, 2, 3, 4])
        self.assertEqual([(x["status"], x["citations"]) for x in w],
                         [("known_amendments_unresolved", [1, 2]), ("unverified_snapshot", [3, 4])])

    def test_verified_current_warns_unless_bound_by_a_valid_approval(self):
        reg = valid(registry(entry(status="verified_current")))
        [w] = ss.collect_warnings(reg, [doc()], trust_verified=False)
        self.assertEqual(w["status"], ss.UNCONFIRMED_CURRENT)
        self.assertEqual(ss.collect_warnings(reg, [doc()], trust_verified=True), [])

    def test_approval_never_removes_a_non_current_warning(self):
        reg = valid(registry(entry(overrides=[override()])))
        for trust in (False, True):
            self.assertEqual(len(ss.collect_warnings(reg, [doc(provision="Rule 81")], trust_verified=trust)), 1)


class ShippedRegistryTests(unittest.TestCase):
    """The real legal-status/source-status.json: valid, conservative, hash-bound."""

    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        cls.by_hash = ss.parse(cls.data)

    def test_nothing_is_verified_current_and_no_reviewer_is_filled(self):
        statuses = [e["status"] for e in self.data["entries"]] + \
                   [o["status"] for e in self.data["entries"] for o in e["provision_overrides"]]
        self.assertNotIn("verified_current", statuses)
        for e in self.data["entries"]:
            self.assertEqual(e["review"], NO_REVIEW)
            for o in e["provision_overrides"]:
                self.assertEqual(o["review"], NO_REVIEW)

    def test_rule81_is_known_amendments_unresolved_with_go77_and_pending_decisions(self):
        s = ss.Registry("valid", [], None, self.by_hash).lookup(RULE81_FILE_SHA, "Rule 81")
        self.assertEqual(s.status, "known_amendments_unresolved")
        self.assertEqual(s.decision_refs, ("LD-001", "LD-002"))
        self.assertTrue(any("G.O.Ms.No. 77" in i for i in s.related_instruments))
        [chap4] = [e for e in self.data["entries"] if e["sha256"] == RULE81_FILE_SHA]
        [o] = chap4["provision_overrides"]
        self.assertEqual([e["sha256"] for e in o["evidence"]], [RULE81_FILE_SHA, GO77_SHA])

    # Stage 27: these run in a fresh clone against the pinned snapshot (tests/fixtures/legal-data-snapshot.json).
    # The test_pinned_snapshot_matches_live_* tests below keep that snapshot honest wherever the live files exist.

    def test_ld001_ld002_still_unresolved_in_the_register(self):
        decisions = SNAPSHOT["decisions"]
        for ld in ("LD-001", "LD-002"):
            self.assertEqual(decisions[ld]["status"], "evidence_incomplete")
            self.assertIsNone(decisions[ld]["decision"])
            self.assertIsNone(decisions[ld]["review_date"])
            self.assertEqual(decisions[ld]["reviewer"], {"name": None, "designation": None, "organisation": None})
        refs = {r for e in self.data["entries"] for o in [e, *e["provision_overrides"]] for r in o["decision_refs"]}
        self.assertLessEqual(refs, set(decisions))  # the registry cites only decisions pinned as unresolved

    def test_every_hash_matches_sha256sums_and_draft_manifest(self):
        listed = SNAPSHOT["sha256sums"]
        for e in self.data["entries"]:
            self.assertEqual(listed.get(e["file"]), e["sha256"], e["file"])
        man = {f: d["sha256"] for f, d in SNAPSHOT["manifest"].items()}
        self.assertEqual({e["file"]: e["sha256"] for e in self.data["entries"]}, man)
        # Statuses follow the manifest class: snapshots never appear as official, official never as current.
        for e in self.data["entries"]:
            expected = {"unverified_snapshot": "unverified_snapshot",
                        "official": "official_text_commencement_unconfirmed"}[SNAPSHOT["manifest"][e["file"]]["source_class"]]
            self.assertEqual(e["status"], expected, e["file"])

    def test_pinned_snapshot_matches_live_legal_sources(self):
        sums = SOURCES_DIR / "source-documents" / "SHA256SUMS"
        manifest = SOURCES_DIR / "DRAFT-telangana-manifest.json"
        if not sums.is_file() or not manifest.is_file():
            skip_or_fail(self, f"live legal sources not found at {SOURCES_DIR} (set TG_LEGAL_SOURCES_DIR)")
        pinned = SNAPSHOT["pinned_from"]
        self.assertEqual(hashlib.sha256(sums.read_bytes()).hexdigest(), pinned["SHA256SUMS"]["sha256"],
                         "SHA256SUMS changed: regenerate tests/fixtures/legal-data-snapshot.json and re-review")
        self.assertEqual(hashlib.sha256(manifest.read_bytes()).hexdigest(), pinned["manifest"]["sha256"],
                         "manifest changed: regenerate tests/fixtures/legal-data-snapshot.json and re-review")

    def test_pinned_snapshot_matches_live_decision_register(self):
        reg = ROOT / "eval" / "legal-validation" / "stage-22-legal-decision-register.json"
        if not reg.is_file():
            skip_or_fail(self, "live decision register not present")
        live = {d["decision_id"]: d for d in json.loads(reg.read_text())["decisions"]}
        for ld, pinned in SNAPSHOT["decisions"].items():
            self.assertEqual({k: live[ld][k] for k in pinned}, pinned, ld)


class ApprovalBindingTests(unittest.TestCase):
    """The signed record must name the registry's SHA-256; any registry edit invalidates the approval."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.registry = self.dir / "source-status.json"
        self.registry.write_text(json.dumps(ts.fixture_registry_data([(SHA_A, ts.TG_RULES_FILE),
                                                                      (SHA_B, ts.TG_TAX_FILE)])))
        self.key = tla.new_key()
        self.keys = tla.write_keys(self.dir, tla.key_entry(self.key, "k1"))

    def evaluate(self, record, **kw):
        path = tla.write_signed(self.dir, record, self.key, "k1")
        return la.evaluate(path, tla.INDEX_OK, today=tla.TODAY, trusted_keys=self.keys, **kw)

    def bound(self, **kw):
        return tla.synthetic_record(source_status_sha256=la.sha256_file(self.registry), **kw)

    def test_bound_record_is_valid(self):
        status = self.evaluate(self.bound(), source_status_file=self.registry)
        self.assertEqual((status.state, status.errors), ("valid", []))

    def test_changed_registry_invalidates_a_correctly_signed_record(self):
        record = self.bound()
        data = json.loads(self.registry.read_text())
        data["entries"][0]["status"] = "unverified_snapshot"
        data["entries"][0]["review"] = dict(NO_REVIEW)
        data["entries"][0]["decision_refs"] = []
        self.registry.write_text(json.dumps(data))
        status = self.evaluate(record, source_status_file=self.registry)
        self.assertEqual(status.state, "invalid")
        self.assertIn("source-status registry has changed since approval", status.errors)

    def test_pre_stage25_record_fails_closed(self):
        status = self.evaluate(tla.synthetic_record(), source_status_file=self.registry)
        self.assertEqual(status.state, "invalid")
        self.assertIn("re-approval required", status.errors[0])

    def test_missing_registry_fails_closed(self):
        status = self.evaluate(self.bound(), source_status_file=self.dir / "gone.json")
        self.assertIn("source-status registry is missing or unreadable", status.errors)

    def test_binding_cannot_be_edited_without_breaking_the_signature(self):
        path = tla.write_signed(self.dir, self.bound(), self.key, "k1")
        data = json.loads(path.read_text())
        data["source_status_sha256"] = "0" * 64
        path.write_text(json.dumps(data, indent=2))
        status = la.evaluate(path, tla.INDEX_OK, today=tla.TODAY, trusted_keys=self.keys,
                             source_status_file=self.registry)
        self.assertEqual(status.state, "invalid")

    def test_malformed_binding_rejected_by_parser(self):
        with self.assertRaises(la.ApprovalError):
            la.parse_record(tla.synthetic_record(source_status_sha256="xyz"), tla.TODAY)

    def test_parser_stays_compatible_without_registry_check(self):
        # The format accepts records without the field; only evaluate(source_status_file=...) enforces it.
        record = la.parse_record(tla.synthetic_record(), tla.TODAY)
        self.assertIsNone(record.source_status_sha256)


class ServerRegistryLifecycleTests(unittest.TestCase):
    start = tla.ServerApprovalTests.start  # borrowed helper only; the parent's tests are not re-run

    def test_server_binds_registry_and_goes_stale_when_it_changes(self):
        srv, client = self.start(tla.synthetic_record())
        self.assertEqual(client.get("/status").json()["approval"], "valid")
        self.registry_path.write_text(self.registry_path.read_text() + "\n")
        self.assertEqual(client.get("/status").json()["approval"], "stale")
        client.post("/approval/refresh")
        s = client.get("/status").json()
        self.assertEqual((s["approval"], s["kb_approved"]), ("invalid", False))

    def test_server_rejects_record_without_binding(self):
        srv, client = self.start(tla.synthetic_record(source_status_sha256=None))
        self.assertEqual(client.get("/status").json()["approval"], "invalid")


class WarningPropagationTests(ts.Base):
    """Through retrieval, grounded context, citations, the API response and (statically) the frontend."""

    CLAIM = "A learner's licence application is made in Form 2."

    def setUp(self):
        super().setUp()
        self.eligible = Document(page_content="Rule 5. A learner's licence application is made in Form 2.", metadata={
            "state": "Telangana", "manifest_id": "tmvr-fixture", "provision_id": "Rule 5", "location": "chap-2.htm#5",
            "title": "Synthetic Motor Rules", "answer_eligible": True, "verification_status": "unverified",
            "source_file": ts.TG_RULES_FILE, "sha256": ts.TG_RULES_SHA})
        ts.FAKE_SEARCH["fn"] = lambda q, s, docs: [(self.eligible, 0.3)]
        self.mock = grounded_answer.MockGenerator(json.dumps({
            "answer": self.CLAIM, "evidence_sufficiency": "sufficient",
            "claims": [{"text": self.CLAIM, "kind": "direct", "evidence_ids": ["E1"]}],
            "citations": ["E1"], "refusal_reason": None, "clarification_question": None}))

    def patch(self, **values):
        for name, value in values.items():
            p = mock.patch.object(ts.srv, name, value)
            p.start()
            self.addCleanup(p.stop)

    def approve(self, reg_data, bind=True):
        reg = ss.Registry("valid", [], "e" * 64, ss.parse(reg_data, TODAY))
        record = la.ApprovalRecord(
            jurisdiction="Telangana", reviewer_name="Synthetic Reviewer Fixture", reviewer_designation="Fixture",
            approval_date=dt.date(2026, 1, 1), decision="approved", conditions=(), unresolved_conditions=0,
            corpus_version="test-v1", general_answers_approved=True, penalty_answers_approved=False,
            documents=(la.ApprovedDocument(ts.TG_RULES_FILE, ts.TG_RULES_SHA, "Synthetic Motor Rules", "Rules"),),
            source_status_sha256=reg.sha256 if bind else None)
        status = la.ApprovalStatus("valid", [], record)
        self.patch(GROUNDED_ANSWERS_ENABLED=True, ANSWER_MODE="grounded", APPROVAL=status, KB_APPROVED=True,
                   PENALTY_ANSWERS_ENABLED=False, TRUSTED_KEYS_FILE=Path("k"), CORPUS_DIR=Path("c"),
                   EXPECTED_CORPUS_VERSION="test-v1", ANSWER_GENERATOR=self.mock,
                   ensure_approval_current=lambda: None, SOURCE_STATUS=reg)
        p = mock.patch.dict(ts.srv.SOURCES, {ts.TG_RULES_SHA: ("Synthetic Motor Rules", "Rules")}, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def snapshot_with_override(self):
        return registry(entry(sha=ts.TG_RULES_SHA, file=ts.TG_RULES_FILE, overrides=[override("Rule 5")]))

    def test_rule81_style_warning_persists_after_simulated_approval(self):
        self.approve(self.snapshot_with_override())
        r = self.post("How do I apply for a learner's licence?").json()
        self.assertEqual((r["kind"], r["kb_approved"]), ("answer", True))
        [w] = r["source_warnings"]
        self.assertEqual((w["status"], w["provision_id"], w["citations"]), ("known_amendments_unresolved", "Rule 5", [1]))
        self.assertEqual(w["decision_refs"], ["LD-001", "LD-002"])
        self.assertIn("Source status:\n- " + w["text"] + " [1]", r["response"])
        [src] = r["sources"]
        self.assertEqual((src["verified"], src["text_status"]), (True, "known_amendments_unresolved"))

    def test_warning_text_is_backend_template_not_model_text(self):
        self.approve(self.snapshot_with_override())
        r = self.post("How do I apply for a learner's licence?").json()
        expected = ss.TEMPLATES["known_amendments_unresolved"].format(
            label=f"Doc {ts.TG_RULES_FILE}", provision="Rule 5", instruments="G.O.Ms.No. 77, TR&B, 15-11-2025")
        self.assertEqual(r["source_warnings"][0]["text"], expected)

    def test_text_status_reaches_grounded_context(self):
        self.approve(self.snapshot_with_override())
        self.post("How do I apply for a learner's licence?")
        self.assertIn('"text_status": "known_amendments_unresolved"', self.mock.calls[0])

    def test_unbound_registry_blocks_grounded_answers(self):
        self.approve(self.snapshot_with_override(), bind=False)
        r = self.post("How do I apply for a learner's licence?").json()
        self.assertEqual(r["kind"], "unavailable")
        self.assertIn("approval does not bind the source-status registry in use", ts.srv.grounded_gate_errors())
        self.assertEqual(self.mock.calls, [])

    def test_invalid_registry_blocks_grounded_answers(self):
        self.approve(self.snapshot_with_override())
        self.patch(SOURCE_STATUS=ss.Registry("invalid", ["x"]))
        self.assertEqual(self.post("How do I apply for a learner's licence?").json()["kind"], "unavailable")

    def test_bound_verified_current_has_no_warning(self):
        self.approve(registry(entry(sha=ts.TG_RULES_SHA, file=ts.TG_RULES_FILE, status="verified_current")))
        r = self.post("How do I apply for a learner's licence?").json()
        self.assertEqual((r["kind"], r["source_warnings"]), ("answer", []))
        self.assertNotIn("Source status:", r["response"])
        self.assertEqual(r["sources"][0]["text_status"], "verified_current")

    def test_legacy_dev_answers_carry_warnings_and_old_fields(self):
        r = self.post("How do I apply for a learner's licence?").json()
        self.assertEqual(r["kind"], "development")
        for key in ("response", "kind", "sources", "kb_approved"):
            self.assertIn(key, r)
        self.assertEqual([w["status"] for w in r["source_warnings"]], [ss.UNRECORDED])
        self.assertIn("Source status:", r["response"])

    def test_non_answers_have_empty_warnings(self):
        r = self.post("What is the fine for no helmet?").json()
        self.assertEqual((r["kind"], r["source_warnings"]), ("restricted", []))

    def test_retrieval_annotation_keeps_chunk_identity_in_both_vector_modes(self):
        for mode in ("exact", "hnsw"):
            with self.subTest(mode), mock.patch.object(ts.srv, "VECTOR_SEARCH", mode):
                got = ts.srv.retrieve("learner licence")
                self.assertEqual([hybrid_retrieval.chunk_key(d) for d in got],
                                 [hybrid_retrieval.chunk_key(self.eligible)])
                self.assertEqual(got[0].metadata["text_status"], ss.UNRECORDED)
                self.assertNotIn("text_status", self.eligible.metadata)  # stored chunk untouched

    # Stage 26 adversarial additions: paths Stage 25 covered only at unit level or not at all.

    SECOND = "A learner's licence application is made in Form 3."

    def two_chunks_same_source(self, sufficiency):
        other = Document(page_content="Rule 5A. " + self.SECOND, metadata={
            **self.eligible.metadata, "provision_id": "Rule 5A", "location": "chap-2.htm#5A"})
        ts.FAKE_SEARCH["fn"] = lambda q, s, docs: [(self.eligible, 0.3), (other, 0.31)]
        claims = [{"text": self.CLAIM, "kind": "direct", "evidence_ids": ["E1"]},
                  {"text": self.SECOND, "kind": "direct", "evidence_ids": ["E2"]}]
        self.mock.response = json.dumps({
            "answer": " ".join(c["text"] for c in claims), "evidence_sufficiency": sufficiency, "claims": claims,
            "citations": ["E1", "E2"], "refusal_reason": None, "clarification_question": None})

    def test_conflict_response_carries_warnings_after_approval(self):
        self.approve(self.snapshot_with_override())
        self.two_chunks_same_source("conflicting")
        r = self.post("How do I apply for a learner's licence?").json()
        self.assertEqual((r["kind"], r["kb_approved"]), ("conflict", True))
        self.assertEqual([(w["status"], w["provision_id"], w["citations"]) for w in r["source_warnings"]],
                         [("known_amendments_unresolved", "Rule 5", [1]), ("unverified_snapshot", None, [2])])
        for w in r["source_warnings"]:
            self.assertIn(w["text"], r["response"])
        [src] = r["sources"]  # one source, shown with its most cautious status in this answer
        self.assertEqual((src["verified"], src["text_status"]), (True, "known_amendments_unresolved"))

    def test_multiple_chunks_of_one_approved_snapshot_give_one_warning(self):
        self.approve(registry(entry(sha=ts.TG_RULES_SHA, file=ts.TG_RULES_FILE)))
        self.two_chunks_same_source("sufficient")
        r = self.post("How do I apply for a learner's licence?").json()
        self.assertEqual(r["kind"], "answer")
        [w] = r["source_warnings"]
        self.assertEqual((w["status"], w["citations"]), ("unverified_snapshot", [1, 2]))
        self.assertEqual(r["response"].count(w["text"]), 1)
        self.assertIn(w["text"] + " [1] [2]", r["response"])

    def test_generator_failure_returns_no_legal_text(self):
        self.approve(self.snapshot_with_override())
        self.mock.fn = lambda p, c: (_ for _ in ()).throw(TimeoutError())
        r = self.post("How do I apply for a learner's licence?").json()
        self.assertEqual((r["kind"], r["response"], r["sources"], r["source_warnings"]),
                         ("no_support", ts.srv.NO_SUPPORT_MESSAGE, [], []))
        self.assertNotIn("Form 2", r["response"])

    def test_warning_failure_withholds_the_answer(self):
        # If warnings cannot be built, the answer must not go out without them.
        self.approve(self.snapshot_with_override())
        self.patch(source_warnings=mock.Mock(side_effect=RuntimeError("registry failure")))
        r = self.post("How do I apply for a learner's licence?")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json(), {"detail": ts.srv.PROVIDER_ERROR})

    def test_snapshot_chunk_missing_from_registry_warns_after_approval(self):
        # Approved document with no registry entry for its hash. (A real load would reject such a registry against
        # the index and block answers; this checks the last line of defence: the chunk still warns "not recorded".)
        reg = registry(entry(sha=SHA_B, file="other.pdf"))
        self.approve(reg)
        r = self.post("How do I apply for a learner's licence?").json()
        self.assertEqual(r["kind"], "answer")
        [w] = r["source_warnings"]
        self.assertEqual((w["status"], w["citations"]), (ss.UNRECORDED, [1]))


class FrontendStatusDisplayTests(unittest.TestCase):
    INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    def test_status_badge_is_separate_from_approval_badge_and_text_only(self):
        self.assertIn("TEXT_STATUS_LABELS", self.INDEX)
        self.assertIn("status.textContent = TEXT_STATUS_LABELS[s.text_status] || 'Status not recorded';", self.INDEX)
        self.assertIn("s.text_status !== 'verified_current'", self.INDEX)
        for status in ("unverified_snapshot", "official_text_commencement_unconfirmed", "known_amendments_unresolved",
                       "status_not_recorded", "verified_current_not_approved"):
            self.assertIn(status + ":", self.INDEX)


if __name__ == "__main__":
    unittest.main()
