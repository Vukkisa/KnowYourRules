"""Offline tests for backend/legal_approval.py, hash metadata in backend/build_index.py, and the server's
use of the approval record.

All records, reviewers, dates and hashes here are SYNTHETIC fixtures. Nothing here is, or may be used as,
a real legal approval. Run from the project root:
    python -m unittest discover -s tests -v
"""

import base64
import copy
import datetime as dt
import hashlib
import json
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402
from langchain_core.documents import Document  # noqa: E402
from langchain_core.embeddings import DeterministicFakeEmbedding  # noqa: E402

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from backend import legal_approval as la  # noqa: E402
import backend.build_index as bi  # noqa: E402
import test_build_index as tbi  # noqa: E402
import test_server as ts  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import sign_approval_record as signer  # noqa: E402

TODAY = dt.date(2026, 11, 8)
SHA_A, SHA_B, SHA_C = "a" * 64, "b" * 64, "c" * 64


def synthetic_record(**overrides):
    record = {
        "schema_version": 1,
        "jurisdiction": "Telangana",
        "reviewer": {"name": "Synthetic Reviewer Fixture", "designation": "Synthetic Counsel Fixture"},
        "approval_date": "2026-01-01",
        "decision": "approved",
        "conditions": [],
        "corpus_version": "synthetic-corpus-1",
        "general_answers_approved": True,
        "penalty_answers_approved": False,
        "documents": [
            {"file": ts.TG_RULES_FILE, "sha256": SHA_A, "title": "Synthetic Rules Fixture", "instrument": "Rules"},
            {"file": ts.TG_TAX_FILE, "sha256": SHA_B, "title": "Synthetic G.O. Fixture", "instrument": "G.O."},
        ],
    }
    record.update(overrides)
    return record


def new_key():
    """A throwaway Ed25519 key generated in memory for one test. Never written outside a temp dir."""
    return Ed25519PrivateKey.generate()


def key_entry(key, key_id, status="active", not_after=None):
    return {"key_id": key_id, "algorithm": "ed25519", "public_key": signer.public_key_b64(key),
            "status": status, "not_after": not_after}


def write_signed(dir_, record, key, key_id, raw=None):
    """Write record JSON (or raw text) and its detached signature into dir_; return the record path."""
    path = Path(dir_) / "approval.json"
    path.write_text(raw if raw is not None else json.dumps(record, indent=2))
    sig = signer.signature_document(path.read_bytes(), key, key_id)
    signature_path = la.signature_path(path)
    signature_path.write_text(json.dumps(sig))
    return path


def write_keys(dir_, *entries):
    path = Path(dir_) / "trusted-keys.json"
    path.write_text(json.dumps({"schema_version": 1, "keys": list(entries)}))
    return path


def meta(file, sha, state="Telangana"):
    return {"source_file": file, "sha256": sha, "state": state}


INDEX_OK = [meta(ts.TG_RULES_FILE, SHA_A), meta(ts.TG_RULES_FILE, SHA_A), meta(ts.TG_TAX_FILE, SHA_B)]


class RecordParsingTests(unittest.TestCase):
    def parse(self, data):
        return la.parse_record(data, today=TODAY)

    def assert_rejected(self, data, fragment):
        with self.assertRaises(la.ApprovalError) as cm:
            self.parse(data)
        self.assertIn(fragment, str(cm.exception))

    def test_synthetic_valid_record_parses(self):
        r = self.parse(synthetic_record())
        self.assertEqual(r.hashes, {SHA_A, SHA_B})
        self.assertTrue(r.general_answers_approved)
        self.assertFalse(r.penalty_answers_approved)

    def test_non_object_and_missing_or_unknown_fields(self):
        self.assert_rejected([], "JSON object")
        data = synthetic_record()
        del data["corpus_version"]
        self.assert_rejected(data, "missing fields")
        self.assert_rejected(synthetic_record(approved_by_env=True), "unknown fields")

    def test_wrong_schema_or_jurisdiction(self):
        self.assert_rejected(synthetic_record(schema_version=2), "schema_version")
        self.assert_rejected(synthetic_record(schema_version=True), "schema_version")
        self.assert_rejected(synthetic_record(jurisdiction="Gujarat"), "jurisdiction")

    def test_reviewer_must_be_filled_and_not_a_placeholder(self):
        for reviewer in ({"name": "", "designation": "Counsel"}, {"name": "____", "designation": "Counsel"},
                         {"name": "TBD", "designation": "Counsel"}, {"name": "Someone", "designation": "placeholder"},
                         {"name": "Someone"}, "Someone"):
            with self.subTest(reviewer=reviewer):
                self.assertRaises(la.ApprovalError, self.parse, synthetic_record(reviewer=reviewer))

    def test_dates_must_be_real_iso_and_not_future(self):
        self.assert_rejected(synthetic_record(approval_date="08/11/2026"), "YYYY-MM-DD")
        self.assert_rejected(synthetic_record(approval_date="2026-02-30"), "not a real date")
        self.assert_rejected(synthetic_record(approval_date="2026-11-09"), "future")

    def test_decision_and_conditions(self):
        self.assert_rejected(synthetic_record(decision="ready_for_review"), "decision")
        self.assert_rejected(synthetic_record(decision="approved_with_conditions"), "at least one condition")
        self.assert_rejected(synthetic_record(conditions=[""]), "conditions")
        r = self.parse(synthetic_record(decision="approved_with_conditions", conditions=["Synthetic condition"]))
        self.assertEqual(r.conditions, ("Synthetic condition",))

    def test_answer_flags_must_be_booleans_and_penalty_needs_general(self):
        self.assert_rejected(synthetic_record(general_answers_approved="yes"), "general_answers_approved")
        self.assert_rejected(synthetic_record(penalty_answers_approved=1), "penalty_answers_approved")
        self.assert_rejected(synthetic_record(general_answers_approved=False, penalty_answers_approved=True),
                             "requires general_answers_approved")

    def test_document_entries_are_strict(self):
        docs = synthetic_record()["documents"]
        bad = copy.deepcopy(docs)
        bad[0]["sha256"] = "A" * 64
        self.assert_rejected(synthetic_record(documents=bad), "lowercase hex")
        bad = copy.deepcopy(docs)
        bad[0]["sha256"] = "abc"
        self.assert_rejected(synthetic_record(documents=bad), "lowercase hex")
        bad = copy.deepcopy(docs)
        bad[1]["sha256"] = SHA_A
        self.assert_rejected(synthetic_record(documents=bad), "repeats an approved sha256")
        bad = copy.deepcopy(docs)
        bad[1]["file"] = bad[0]["file"]
        self.assert_rejected(synthetic_record(documents=bad), "repeats file name")
        bad = copy.deepcopy(docs)
        bad[0]["instrument"] = "Circular"
        self.assert_rejected(synthetic_record(documents=bad), "instrument")
        bad = copy.deepcopy(docs)
        bad[0]["verified"] = True
        self.assert_rejected(synthetic_record(documents=bad), "exactly file, sha256, title, instrument")
        self.assert_rejected(synthetic_record(documents=[]), "non-empty list")

    def test_unreadable_and_invalid_json_files(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "record.json"
            path.write_text("{not json")
            with self.assertRaisesRegex(la.ApprovalError, "not valid JSON"):
                la.load_record(path, TODAY)
            with self.assertRaisesRegex(la.ApprovalError, "cannot read"):
                la.load_record(Path(d) / "missing.json", TODAY)


class CorpusValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def record_for(self, *paths):
        docs = [{"file": p.name, "sha256": la.sha256_file(p), "title": f"Synthetic {p.stem}", "instrument": "Rules"}
                for p in paths]
        return la.parse_record(synthetic_record(documents=docs), TODAY)

    def test_sha256_matches_hashlib(self):
        p = self.write("x.txt", "synthetic")
        self.assertEqual(la.sha256_file(p), hashlib.sha256(b"synthetic").hexdigest())

    def test_matching_corpus_passes(self):
        a, b = self.write("a.pdf", "one"), self.write("b.pdf", "two")
        self.assertEqual(la.corpus_errors(self.record_for(a, b), [a, b]), [])

    def test_changed_document_is_rejected(self):
        a, b = self.write("a.pdf", "one"), self.write("b.pdf", "two")
        record = self.record_for(a, b)
        a.write_text("one, amended")
        self.assertIn("'a.pdf' has changed since approval", la.corpus_errors(record, [a, b]))

    def test_additional_unapproved_document_is_rejected(self):
        a, b = self.write("a.pdf", "one"), self.write("b.pdf", "two")
        extra = self.write("extra.pdf", "three")
        self.assertIn("unapproved document: extra.pdf", la.corpus_errors(self.record_for(a, b), [a, b, extra]))

    def test_missing_approved_document_is_rejected(self):
        a, b = self.write("a.pdf", "one"), self.write("b.pdf", "two")
        self.assertIn("approved document missing from corpus: 'b.pdf'", la.corpus_errors(self.record_for(a, b), [a]))

    def test_duplicate_file_names_with_different_contents_are_rejected(self):
        a, b = self.write("x/a.pdf", "one"), self.write("b.pdf", "two")
        twin = self.write("y/a.pdf", "one, but different")
        errors = la.corpus_errors(self.record_for(a, b), [a, b, twin])
        self.assertIn("file name 'a.pdf' appears with 2 different contents", errors)


class IndexValidationTests(unittest.TestCase):
    def setUp(self):
        self.record = la.parse_record(synthetic_record(), TODAY)

    def test_matching_index_passes(self):
        self.assertEqual(la.index_errors(self.record, INDEX_OK), [])

    def test_empty_index(self):
        self.assertEqual(la.index_errors(self.record, []), ["index has no chunks"])

    def test_missing_or_invalid_hash_metadata(self):
        for bad in ({"source_file": ts.TG_TAX_FILE, "state": "Telangana"}, meta(ts.TG_TAX_FILE, "xyz"), None):
            errors = la.index_errors(self.record, INDEX_OK + [bad])
            self.assertIn("1 chunk(s) have no valid sha256/source_file metadata", errors, bad)

    def test_hash_mismatch_unapproved_and_missing_documents(self):
        changed = [meta(ts.TG_RULES_FILE, SHA_A), meta(ts.TG_TAX_FILE, SHA_C)]
        errors = la.index_errors(self.record, changed)
        self.assertIn(f"unapproved document in index: {ts.TG_TAX_FILE}", errors)
        self.assertIn(f"approved document missing from index: {ts.TG_TAX_FILE!r}", errors)

    def test_additional_document_in_index(self):
        errors = la.index_errors(self.record, INDEX_OK + [meta("extra.pdf", SHA_C)])
        self.assertEqual(errors, ["unapproved document in index: extra.pdf"])

    def test_same_file_name_with_two_contents_in_index(self):
        errors = la.index_errors(self.record, INDEX_OK + [meta(ts.TG_RULES_FILE, SHA_C)])
        self.assertIn(f"file name {ts.TG_RULES_FILE!r} is indexed with 2 different contents", errors)

    def test_non_telangana_chunk(self):
        errors = la.index_errors(self.record, [meta(ts.TG_RULES_FILE, SHA_A), meta(ts.TG_TAX_FILE, SHA_B, "Central")])
        self.assertIn(f"chunk from {ts.TG_TAX_FILE!r} is not tagged Telangana", errors)

    def test_evaluate_states(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "record.json"
            # Changed for signing: unsigned records are evaluated only with the explicit test-only sentinel.
            U = la.UNSIGNED_TEST_ONLY
            self.assertEqual(la.evaluate(path, INDEX_OK, TODAY, U).state, "absent")
            self.assertEqual(la.evaluate(None, INDEX_OK, TODAY, U).state, "absent")
            path.write_text(json.dumps(synthetic_record()))
            ok = la.evaluate(path, INDEX_OK, TODAY, U)
            self.assertEqual((ok.state, ok.general_answers, ok.penalty_answers), ("valid", True, False))
            bad = la.evaluate(path, INDEX_OK + [meta("extra.pdf", SHA_C)], TODAY, U)
            self.assertEqual((bad.state, bad.general_answers, bad.penalty_answers), ("invalid", False, False))
            path.write_text(json.dumps(synthetic_record(penalty_answers_approved=True)))
            self.assertTrue(la.evaluate(path, INDEX_OK, TODAY, U).penalty_answers)
            self.assertFalse(la.evaluate(path, INDEX_OK[:1], TODAY, U).penalty_answers)  # mismatch blocks it


class BuildIndexHashTests(tbi.BuildIndexTests):
    """Hash metadata and approval checks in the builder (reuses the builder test fixtures)."""

    def test_loaded_documents_carry_file_sha256(self):
        docs, errors = bi.load_documents(self.files, self.corpus, tbi.FakeLoader)
        self.assertEqual(errors, [])
        for d in docs:
            self.assertEqual(d.metadata["sha256"], la.sha256_file(self.corpus / "state" / d.metadata["source_file"]))

    def test_indexed_chunks_carry_sha256(self):
        rc, out = self.run_build()
        self.assertEqual(rc, 0, out)
        metas = self.client.get_collection(bi.COLLECTION).get(include=["metadatas"])["metadatas"]
        self.assertTrue(all(la.SHA256_RE.match(m["sha256"]) for m in metas))

    def test_verify_rejects_chunks_without_sha256(self):
        staging = self.client.create_collection(bi.STAGING)
        staging.add(ids=["s1"], embeddings=[[0.1] * 16], documents=["x"],
                    metadatas=[{"state": "Delhi", "source_file": "d.pdf"}])
        splits = [Document(page_content="x", metadata={"state": "Delhi", "source_file": "d.pdf"})]
        with self.assertRaisesRegex(bi.BuildError, "valid sha256"):
            bi.verify_staging(self.client, splits)

    def approval_for(self, rels):
        docs = [{"file": Path(r).name, "sha256": la.sha256_file(self.corpus / r), "title": f"Synthetic {r}",
                 "instrument": "Rules"} for r in rels]
        return la.parse_record(synthetic_record(documents=docs), TODAY)

    def run_with_approval(self, record):
        import io
        from contextlib import redirect_stdout
        out = io.StringIO()
        with redirect_stdout(out):
            rc = bi.main(self.corpus, self.db, self.files, loader_cls=tbi.FakeLoader,
                         embeddings=DeterministicFakeEmbedding(size=16), approval_record=record)
        return rc, out.getvalue()

    def test_build_with_matching_approval_succeeds(self):
        rc, out = self.run_with_approval(self.approval_for([f for f, _ in self.files]))
        self.assertEqual(rc, 0, out)

    def test_build_with_changed_document_fails_and_keeps_live(self):
        record = self.approval_for([f for f, _ in self.files])
        self.write("state/delhi.pdf", tbi.LONG_TEXT + " amended")
        rc, out = self.run_with_approval(record)
        self.assertEqual(rc, 1)
        self.assertIn("'delhi.pdf' has changed since approval", out)
        self.assert_live_untouched()

    def test_build_with_unapproved_document_fails_and_keeps_live(self):
        rc, out = self.run_with_approval(self.approval_for(["state/central.pdf"]))
        self.assertEqual(rc, 1)
        self.assertIn("unapproved document: delhi.pdf", out)
        self.assert_live_untouched()


# Inherited builder tests already run in test_build_index; skip the copies here.
for _name in [n for n in dir(tbi.BuildIndexTests) if n.startswith("test_")]:
    if _name not in BuildIndexHashTests.__dict__:
        setattr(BuildIndexHashTests, _name, None)


class ServerApprovalTests(unittest.TestCase):
    """The real server module (with offline fakes) started against a synthetic approval record."""

    def start(self, record=None, raw=None, extra_env=None):
        # Changed for signing: synthetic records are signed with a throwaway in-memory key and a temp keyring.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmpdir = Path(tmp.name)
        self.key = new_key()
        self.keys_path = write_keys(self.tmpdir, key_entry(self.key, "test-key-1"))
        path = self.tmpdir / "approval.json"
        if record is not None or raw is not None:
            path = write_signed(self.tmpdir, record, self.key, "test-key-1", raw=raw)
        self.record_path = path
        srv = ts._import_server_with_fakes({"TG_APPROVAL_FILE": str(path), "TG_TRUSTED_KEYS_FILE": str(self.keys_path),
                                            **(extra_env or {})})
        self.addCleanup(ts.FAKE_SEARCH.update, {"fn": None})
        ts.FAKE_LLM["fn"] = ts.fake_llm(answer="grounded answer")
        return srv, TestClient(srv.app)

    def test_no_record_means_not_approved(self):
        srv, client = self.start()
        s = client.get("/status").json()
        self.assertEqual((s["approval"], s["kb_approved"], s["penalty_answers"]), ("absent", False, False))
        self.assertEqual(srv.SOURCES, {})

    def test_valid_record_approves_general_answers_with_hash_verified_sources(self):
        srv, client = self.start(synthetic_record())
        s = client.get("/status").json()
        self.assertEqual((s["approval"], s["kb_approved"], s["penalty_answers"]), ("valid", True, False))
        self.assertEqual(s["corpus_version"], "synthetic-corpus-1")
        r = client.post("/chat", json={"message": "How do I apply for a learner's licence?", "session_id": "x"}).json()
        self.assertTrue(r["kb_approved"])
        self.assertEqual({(x["title"], x["verified"]) for x in r["sources"]},
                         {("Synthetic Rules Fixture", True), ("Synthetic G.O. Fixture", True)})

    def test_general_approval_does_not_enable_penalty_answers(self):
        srv, client = self.start(synthetic_record())
        r = client.post("/chat", json={"message": "What is the fine for no helmet?", "session_id": "x"}).json()
        self.assertEqual(r["kind"], "restricted")

    def test_separate_penalty_approval_is_required_and_sufficient(self):
        srv, _ = self.start(synthetic_record(penalty_answers_approved=True))
        self.assertTrue(srv.PENALTY_ANSWERS_ENABLED)

    def test_env_flags_cannot_approve_anything(self):
        srv = ts._import_server_with_fakes({"TG_KB_APPROVED": "1", "TG_PENALTY_ANSWERS": "1"})
        self.assertFalse(srv.KB_APPROVED)
        self.assertFalse(srv.PENALTY_ANSWERS_ENABLED)

    def test_malformed_record_fails_closed(self):
        for raw in ("{", json.dumps(synthetic_record(reviewer={"name": "____", "designation": "____"})),
                    json.dumps(synthetic_record(penalty_answers_approved="true"))):
            srv, client = self.start(raw=raw)
            s = client.get("/status").json()
            self.assertEqual((s["approval"], s["kb_approved"], s["penalty_answers"]), ("invalid", False, False), raw)
            self.assertTrue(s["approval_errors"])

    def test_hash_mismatch_with_index_fails_closed(self):
        docs = synthetic_record()["documents"]
        docs[1]["sha256"] = SHA_C  # the record approves different bytes than the index holds
        srv, client = self.start(synthetic_record(documents=docs, penalty_answers_approved=True))
        s = client.get("/status").json()
        self.assertEqual((s["approval"], s["kb_approved"], s["penalty_answers"]), ("invalid", False, False))
        self.assertEqual(srv.SOURCES, {})

    def test_status_does_not_expose_reviewer_details(self):
        srv, client = self.start(synthetic_record())
        self.assertNotIn("Synthetic Reviewer Fixture", client.get("/status").text)

    def test_model_citations_cannot_create_verified_status(self):
        srv, client = self.start()
        ts.FAKE_LLM["fn"] = ts.fake_llm(answer="Source: Synthetic Rules Fixture (Rules) - VERIFIED. sha256 " + SHA_A)
        r = client.post("/chat", json={"message": "How do I apply for a learner's licence?", "session_id": "x"}).json()
        self.assertEqual(r["kind"], "development")
        self.assertTrue(r["sources"])
        self.assertTrue(all(not x["verified"] and x["title"] == "Unverified source" for x in r["sources"]))

    def test_same_file_name_with_unapproved_hash_is_not_verified(self):
        srv, client = self.start()
        with unittest.mock.patch.dict(srv.SOURCES, {SHA_A: ("Synthetic Rules Fixture", "Rules")}):
            impostor = Document(page_content="x", metadata=meta(ts.TG_RULES_FILE, SHA_C))
            genuine = Document(page_content="y", metadata=meta(ts.TG_RULES_FILE, SHA_A))
            entries = srv.source_entries([impostor, genuine])
        self.assertEqual([(e["sha256"], e["verified"]) for e in entries], [(SHA_C, False), (SHA_A, True)])

    def test_approved_mode_drops_chunks_from_unapproved_documents(self):
        srv, client = self.start(synthetic_record())
        rogue = Document(page_content="Rogue fixture text.", metadata=meta("rogue.pdf", SHA_C))
        ts.FAKE_SEARCH["fn"] = lambda q, state, docs: [(rogue, 0.1)] + [(d, 0.3) for d in docs]
        log = {}
        ts.FAKE_LLM["fn"] = ts.fake_llm(log=log)
        r = client.post("/chat", json={"message": "How do I apply for a learner's licence?", "session_id": "x"}).json()
        self.assertNotIn("Rogue fixture text.", log["answer"][-1])
        self.assertNotIn("rogue.pdf", [x["file"] for x in r["sources"]])


class SignatureTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.key = new_key()
        self.keys = write_keys(self.dir, key_entry(self.key, "k1"))

    def evaluate(self, path, keys=None):
        return la.evaluate(path, INDEX_OK, TODAY, trusted_keys=self.keys if keys is None else keys)

    def test_correctly_signed_record_is_valid(self):
        self.assertEqual(self.evaluate(write_signed(self.dir, synthetic_record(), self.key, "k1")).state, "valid")

    def test_missing_signature(self):
        path = self.dir / "approval.json"
        path.write_text(json.dumps(synthetic_record()))
        st = self.evaluate(path)
        self.assertEqual((st.state, st.errors), ("invalid", ["approval record is not signed"]))

    def test_invalid_signature(self):
        path = write_signed(self.dir, synthetic_record(), self.key, "k1")
        sig = json.loads(la.signature_path(path).read_text())
        sig["signature"] = base64.b64encode(b"\x00" * 64).decode()
        la.signature_path(path).write_text(json.dumps(sig))
        self.assertEqual(self.evaluate(path).errors, ["approval record signature is invalid"])

    def test_signature_by_untrusted_key_with_trusted_id(self):
        path = write_signed(self.dir, synthetic_record(), new_key(), "k1")
        self.assertEqual(self.evaluate(path).errors, ["approval record signature is invalid"])

    def test_unknown_signing_key(self):
        path = write_signed(self.dir, synthetic_record(), self.key, "someone-else")
        self.assertEqual(self.evaluate(path).errors, ["approval record is signed with an unknown key"])

    def test_record_changed_after_signing(self):
        path = write_signed(self.dir, synthetic_record(), self.key, "k1")
        path.write_text(path.read_text() + " ")
        self.assertEqual(self.evaluate(path).errors, ["approval record signature is invalid"])
        path.write_text(json.dumps(synthetic_record(penalty_answers_approved=True), indent=2))
        st = self.evaluate(path)
        self.assertEqual((st.state, st.penalty_answers), ("invalid", False))

    def test_malformed_signature_files(self):
        path = write_signed(self.dir, synthetic_record(), self.key, "k1")
        for bad in ("{", json.dumps({"key_id": "k1"}), json.dumps({"schema_version": 1, "algorithm": "rsa",
                                                                  "key_id": "k1", "signature": "x"}),
                    json.dumps({"schema_version": 1, "algorithm": "ed25519", "key_id": "k1", "signature": "!!"})):
            la.signature_path(path).write_text(bad)
            self.assertEqual(self.evaluate(path).state, "invalid", bad)

    def test_no_trusted_keys_configured_rejects_everything(self):
        path = write_signed(self.dir, synthetic_record(), self.key, "k1")
        st = la.evaluate(path, INDEX_OK, TODAY, trusted_keys=None)
        self.assertEqual(st.errors, ["no trusted signing keys are configured"])

    def test_malformed_keyrings(self):
        path = write_signed(self.dir, synthetic_record(), self.key, "k1")
        good = key_entry(self.key, "k1")
        for keys in ([good, good], [dict(good, public_key="abc")], [dict(good, status="retired")],
                     [dict(good, algorithm="rsa")], [dict(good, status="trusted")], [dict(good, extra=1)], []):
            bad = write_keys(self.dir, *keys)
            self.assertEqual(self.evaluate(path, bad).state, "invalid", keys)

    def test_key_rotation(self):
        old, new = self.key, new_key()
        record = synthetic_record(approval_date="2026-01-01")
        # Planned rotation: the old key is retired from 2026-06-30, the new key is active.
        keys = write_keys(self.dir, key_entry(old, "k1", "retired", "2026-06-30"), key_entry(new, "k2"))
        self.assertEqual(self.evaluate(write_signed(self.dir, record, old, "k1"), keys).state, "valid")
        late = synthetic_record(approval_date="2026-07-01")
        st = self.evaluate(write_signed(self.dir, late, old, "k1"), keys)
        self.assertEqual(st.errors, ["approval record is dated after its signing key was retired"])
        self.assertEqual(self.evaluate(write_signed(self.dir, late, new, "k2"), keys).state, "valid")
        # Compromise: the old key is revoked and its records stop being trusted.
        revoked = write_keys(self.dir, key_entry(old, "k1", "revoked"), key_entry(new, "k2"))
        st = self.evaluate(write_signed(self.dir, record, old, "k1"), revoked)
        self.assertEqual(st.errors, ["approval record is signed with a revoked key"])

    def test_signing_tool_refuses_key_inside_repository(self):
        with self.assertRaisesRegex(signer.SigningError, "inside the repository"):
            signer.load_private_key(Path(signer.REPO_ROOT) / "backend" / "authority.pem")

    def test_signing_tool_signatures_verify(self):
        from cryptography.hazmat.primitives import serialization
        pem = self.dir / "authority.pem"
        pem.write_bytes(self.key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
        record = self.dir / "approval.json"
        record.write_text(json.dumps(synthetic_record()))
        with unittest.mock.patch("sys.stdout"):
            self.assertEqual(signer.main([str(record), "--key", str(pem), "--key-id", "k1"]), 0)
        self.assertEqual(self.evaluate(record).state, "valid")


class ConditionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.key = new_key()
        self.keys = write_keys(self.dir, key_entry(self.key, "k1"))

    def evaluate(self, record):
        return la.evaluate(write_signed(self.dir, record, self.key, "k1"), INDEX_OK, TODAY, trusted_keys=self.keys)

    def test_unresolved_conditions_keep_approval_inactive(self):
        st = self.evaluate(synthetic_record(decision="approved_with_conditions",
                                            conditions=["Synthetic condition text", "Another synthetic condition"],
                                            penalty_answers_approved=True))
        self.assertEqual((st.state, st.general_answers, st.penalty_answers), ("invalid", False, False))
        self.assertEqual(st.errors, ["2 approval condition(s) unresolved"])
        self.assertNotIn("Synthetic condition text", " ".join(st.errors))
        self.assertNotIn("Synthetic Reviewer", " ".join(st.errors))

    def test_conditions_on_plain_approved_decision_are_not_ignored(self):
        st = self.evaluate(synthetic_record(conditions=["Synthetic condition"]))
        self.assertEqual(st.errors, ["1 approval condition(s) unresolved"])

    def test_partly_resolved_conditions_still_block(self):
        st = self.evaluate(synthetic_record(decision="approved_with_conditions", conditions=[
            {"text": "Synthetic A", "resolved": True, "resolution": "Synthetic resolution"},
            {"text": "Synthetic B", "resolved": False, "resolution": ""}]))
        self.assertEqual(st.errors, ["1 approval condition(s) unresolved"])

    def test_all_conditions_resolved_in_signed_record_is_active(self):
        st = self.evaluate(synthetic_record(decision="approved_with_conditions", conditions=[
            {"text": "Synthetic A", "resolved": True, "resolution": "Synthetic resolution"}]))
        self.assertEqual(st.state, "valid")

    def test_resolved_without_resolution_or_malformed_condition_is_rejected(self):
        for cond in ({"text": "Synthetic", "resolved": True, "resolution": ""},
                     {"text": "Synthetic", "resolved": "yes", "resolution": "x"}, {"text": "Synthetic"}, 3):
            self.assertRaises(la.ApprovalError, la.parse_record,
                              synthetic_record(decision="approved_with_conditions", conditions=[cond]), TODAY)


class LifecycleTests(ServerApprovalTests):
    """Approval invalidation after startup. Inherits start() from ServerApprovalTests."""

    def setUp(self):
        self._corpus = list(ts.CORPUS)
        self._metas = [dict(d.metadata) for d in ts.CORPUS]
        self.addCleanup(self._restore)

    def _restore(self):
        ts.CORPUS[:] = self._corpus
        for d, m in zip(ts.CORPUS, self._metas):
            d.metadata.clear()
            d.metadata.update(m)

    def status(self, client):
        return client.get("/status").json()

    def assert_unapproved(self, srv, client, state):
        s = self.status(client)
        self.assertEqual((s["approval"], s["kb_approved"], s["penalty_answers"]), (state, False, False))
        self.assertEqual(srv.SOURCES, {})
        r = client.post("/chat", json={"message": "How do I apply for a learner's licence?", "session_id": "z"}).json()
        self.assertFalse(r["kb_approved"])
        self.assertTrue(all(not x["verified"] for x in r["sources"]))
        p = client.post("/chat", json={"message": "What is the fine for no helmet?", "session_id": "z2"}).json()
        self.assertEqual(p["kind"], "restricted")

    def test_changed_approval_record_invalidates_until_refresh(self):
        srv, client = self.start(synthetic_record(penalty_answers_approved=True))
        self.assertTrue(self.status(client)["penalty_answers"])
        self.record_path.write_text(self.record_path.read_text().replace("synthetic-corpus-1", "synthetic-corpus-2"))
        self.assert_unapproved(srv, client, "stale")
        refreshed = client.post("/approval/refresh").json()
        self.assertEqual((refreshed["approval"], refreshed["penalty_answers"]), ("invalid", False))
        self.assertIn("approval record signature is invalid", refreshed["approval_errors"])

    def test_corpus_version_change_resigned_needs_explicit_revalidation(self):
        srv, client = self.start(synthetic_record())
        write_signed(self.tmpdir, synthetic_record(corpus_version="synthetic-corpus-2"), self.key, "test-key-1")
        self.assertEqual(self.status(client)["approval"], "stale")
        self.assertEqual(self.status(client)["approval"], "stale")  # stays stale: no silent re-approval
        client.post("/approval/refresh")
        s = self.status(client)
        self.assertEqual((s["approval"], s["corpus_version"]), ("valid", "synthetic-corpus-2"))

    def test_changed_index_after_startup_invalidates(self):
        srv, client = self.start(synthetic_record(penalty_answers_approved=True))
        ts.CORPUS.append(Document(page_content="Added later.", metadata=meta("added.pdf", SHA_C)))
        self.assert_unapproved(srv, client, "stale")
        refreshed = client.post("/approval/refresh").json()
        self.assertEqual(refreshed["approval"], "invalid")
        self.assertIn("unapproved document in index: added.pdf", refreshed["approval_errors"])

    def test_hash_changed_in_place_is_caught_by_refresh_and_periodic_check(self):
        srv, client = self.start(synthetic_record(penalty_answers_approved=True))
        ts.CORPUS[1].metadata["sha256"] = SHA_C  # same chunk count: the cheap fingerprint cannot see it
        self.assertEqual(self.status(client)["approval"], "valid")
        srv._LAST_FULL_CHECK = -1e9  # the periodic full check is due
        self.assert_unapproved(srv, client, "invalid")
        self.assertFalse(client.post("/approval/refresh").json()["penalty_answers"])

    def test_changed_corpus_after_startup_invalidates(self):
        corpus = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: [p.unlink() for p in corpus.iterdir()] and None or corpus.rmdir())
        a, b = corpus / ts.TG_RULES_FILE, corpus / ts.TG_TAX_FILE
        a.write_text("synthetic rules bytes")
        b.write_text("synthetic tax bytes")
        ha, hb = la.sha256_file(a), la.sha256_file(b)
        ts.CORPUS[0].metadata["sha256"], ts.CORPUS[1].metadata["sha256"] = ha, hb
        docs = synthetic_record()["documents"]
        docs[0]["sha256"], docs[1]["sha256"] = ha, hb
        srv, client = self.start(synthetic_record(documents=docs, penalty_answers_approved=True),
                                 extra_env={"TG_CORPUS_DIR": str(corpus)})
        self.assertEqual(self.status(client)["approval"], "valid")
        b.write_text("synthetic tax bytes, amended")
        self.assert_unapproved(srv, client, "stale")
        refreshed = client.post("/approval/refresh").json()
        self.assertIn(f"{ts.TG_TAX_FILE!r} has changed since approval", refreshed["approval_errors"])
        b.write_text("synthetic tax bytes")
        (corpus / "extra.pdf").write_text("unapproved")
        refreshed = client.post("/approval/refresh").json()
        self.assertIn("unapproved document: extra.pdf", refreshed["approval_errors"])
        self.assertFalse(refreshed["penalty_answers"])

    def test_changed_trusted_keys_invalidates(self):
        srv, client = self.start(synthetic_record())
        write_keys(self.tmpdir, key_entry(self.key, "test-key-1", "revoked"))
        self.assertEqual(self.status(client)["approval"], "stale")
        self.assertIn("revoked", " ".join(client.post("/approval/refresh").json()["approval_errors"]))

    def test_unchanged_inputs_stay_valid_without_full_rescan(self):
        srv, client = self.start(synthetic_record())
        with unittest.mock.patch.object(srv, "_full_validation", side_effect=AssertionError("full scan")):
            for _ in range(3):
                self.assertEqual(self.status(client)["approval"], "valid")


# LifecycleTests reuses start() only; do not rerun the ServerApprovalTests cases under its name.
for _name in [n for n in dir(ServerApprovalTests) if n.startswith("test_")]:
    if _name not in LifecycleTests.__dict__:
        setattr(LifecycleTests, _name, None)


if __name__ == "__main__":
    unittest.main()
