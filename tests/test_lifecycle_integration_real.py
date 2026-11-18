"""Stage 6D: the real FastAPI application with the document lifecycle enabled, on temporary COPIES of the real index and the
real lifecycle registry (both only ever copied; their digests are checked before and after). Exact and hnsw. Real Ollama query
embeddings; the answering model is a deterministic stand-in; no generation provider is called. Positive-path approval is a
throwaway-key synthetic fixture on a COPY; nothing is ever approved for the real 20 sources."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import chromadb
from lifecycle_fixtures import BASIS, status_file_for
from test_view_source_real import INDEX_DIR, REQUIRED, missing  # noqa: E402

from backend import document_lifecycle as dl

ROOT = Path(__file__).resolve().parent.parent
REAL_REGISTRY = ROOT / "legal" / "lifecycle"
APPROVED_IDS = ("tmvr-1989-chap-2", "tmvr-1989-chap-8")
EXPECTED_ROUTES = {"GET /", "GET /health", "GET /ready", "GET /status", "POST /approval/refresh", "POST /chat", "MOUNT /static",
                   "GET /release-gates"}


def embeddings():
    from langchain_ollama import OllamaEmbeddings

    from backend import build_telangana_index as btx
    from backend import rag_profiles as rp
    return rp.ProfileEmbeddings(OllamaEmbeddings(model="nomic-embed-text"), btx.PROFILE)


def probe(scenario, db, state, mode, env_extra=None, state_env=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TG_", "GROQ_", "GEMINI_", "PROVIDER_", "RAG_"))}
    env.update(TG_DB_DIR=str(db), RAG_VECTOR_SEARCH=mode, GROQ_API_KEY="offline-probe-not-real", TG_CACHE="semantic",
               ANONYMIZED_TELEMETRY="False", APPROVED_IDS=",".join(APPROVED_IDS))
    env["TG_LIFECYCLE_DIR"] = str(state) if state_env is None else state_env
    env.update(env_extra or {})
    run = subprocess.run([sys.executable, str(ROOT / "tests" / "lifecycle_integration_probe.py"), scenario], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=1200)
    if run.returncode != 0:
        raise AssertionError(f"probe {scenario} ({mode}) failed:\n" + run.stderr[-3000:])
    return json.loads(run.stdout.strip().splitlines()[-1])


@unittest.skipUnless(os.environ.get("KYR_REAL_INDEX_DIR") or REQUIRED, "real backend not configured")
class LifecycleIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reason = missing()
        if reason and REQUIRED:
            raise AssertionError(f"real backend test required but cannot run: {reason}")
        if reason:
            raise unittest.SkipTest(reason)
        if not (REAL_REGISTRY / "registry.json").is_file():
            raise unittest.SkipTest("no real lifecycle registry (legal/lifecycle) in this checkout")
        cls.before = (dl.tree_digest(INDEX_DIR), dl.tree_digest(REAL_REGISTRY))
        cls.tmp = Path(tempfile.mkdtemp(prefix="kyr-6d-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.addClassCleanup(cls.check_untouched)
        cls.r = {}
        cls.metas = None
        for mode in ("exact", "hnsw"):
            base = cls.tmp / mode
            shutil.copytree(INDEX_DIR, base / "q-index")
            shutil.copytree(REAL_REGISTRY, base / "q-state")
            cls.r[(mode, "quarantined")] = probe("startup", base / "q-index", base / "q-state", mode)
            cls.r[(mode, "partial")] = cls.partial(mode)
        for name in cls.FAILURES:
            cls.r[("exact", name)] = cls.failure(name)
        cls.recovery()
        dump = os.environ.get("KYR_6D_OUT")   # optional: keep the raw probe outputs for the Stage 6D evidence
        if dump:
            Path(dump).mkdir(parents=True, exist_ok=True)
            for (mode, name), value in cls.r.items():
                (Path(dump) / f"probe_{mode}_{name}.json").write_text(json.dumps(value, indent=1, default=str))

    @classmethod
    def check_untouched(cls):
        after = (dl.tree_digest(INDEX_DIR), dl.tree_digest(REAL_REGISTRY))
        assert after == cls.before, "the real index or the real registry was modified"

    # ---- fixtures ---------------------------------------------------------------------------------------------------
    @classmethod
    def copy_index(cls, dest):
        shutil.copytree(INDEX_DIR, dest)
        return dest

    @classmethod
    def read_metas(cls, index_copy):
        peek = cls.tmp / "peek"
        if not peek.exists():
            shutil.copytree(index_copy, peek)
        return chromadb.PersistentClient(path=str(peek)).get_collection("telangana-traffic-rules", embedding_function=None) \
            .get(include=["metadatas"])["metadatas"]

    @classmethod
    def synthetic_registry(cls, base, name):
        """Registry on an index COPY: only APPROVED_IDS verified, on a synthetic basis and a status registry naming only them; 18 quarantined."""
        index = cls.copy_index(base / f"{name}-index")
        metas = cls.read_metas(index)
        only = {m["sha256"] for m in metas if m["manifest_id"] in APPROVED_IDS}
        status = status_file_for(base / f"{name}-status", metas, only)
        state = base / f"{name}-state"
        res = dl.Lifecycle(state, index, embeddings=embeddings()).bootstrap("integration-test", BASIS, source_status_file=status,
                                                                            allow_quarantine=True)
        assert (res["verified"], res["quarantined"]) == (2, 18), res
        return index, state

    @classmethod
    def partial(cls, mode):
        index, state = cls.synthetic_registry(cls.tmp / mode, "p")
        return probe("partial", index, state, mode)

    FAILURES = ("healthy_control", "missing_directory", "empty_env_value", "missing_registry", "corrupt_registry", "wrong_schema",
                "audit_chain_edited", "audit_mirror_missing", "audit_mirror_garbage", "registry_history_truncated",
                "interrupted_operation", "index_registry_count_mismatch", "unknown_hash_in_index", "incomplete_update")

    @classmethod
    def failure(cls, name):
        base = cls.tmp / "fail" / name
        index, state = cls.synthetic_registry(base, "f")
        reg_path, mirror = state / "registry.json", state / "audit.jsonl"
        state_env = None
        if name == "missing_directory":
            state_env = str(base / "does-not-exist")
        elif name == "empty_env_value":
            state_env = ""
        elif name == "missing_registry":
            reg_path.unlink()
        elif name == "corrupt_registry":
            reg_path.write_text("{ not json")
        elif name == "wrong_schema":
            reg = json.loads(reg_path.read_text())
            reg["schema_version"] = 99
            reg_path.write_text(json.dumps(reg))
        elif name == "audit_chain_edited":
            reg = json.loads(reg_path.read_text())
            reg["events"][2]["note"] = "forged"
            reg_path.write_text(json.dumps(reg, indent=1, sort_keys=True))
        elif name == "audit_mirror_missing":
            mirror.unlink()
        elif name == "audit_mirror_garbage":
            mirror.write_text("garbage\n")
        elif name == "registry_history_truncated":
            reg = json.loads(reg_path.read_text())
            reg["events"].pop()
            reg_path.write_text(json.dumps(reg, indent=1, sort_keys=True))
        elif name == "interrupted_operation":
            lc = dl.Lifecycle(state, index)
            reg = lc.load()
            reg["intent"] = {"op": "approve", "expected": [], "source": "x"}
            reg_path.write_text(json.dumps(reg, indent=1, sort_keys=True))
        elif name == "index_registry_count_mismatch":
            col = chromadb.PersistentClient(path=str(index)).get_collection("telangana-traffic-rules", embedding_function=None)
            got = col.get(include=["metadatas"])
            victim = next(i for i, m in zip(got["ids"], got["metadatas"]) if m["manifest_id"] == APPROVED_IDS[1])
            col.delete(ids=[victim])
        elif name == "unknown_hash_in_index":
            col = chromadb.PersistentClient(path=str(index)).get_collection("telangana-traffic-rules", embedding_function=None)
            got = col.get(include=["documents", "metadatas", "embeddings"], limit=3)
            col.add(ids=[f"unknown-{i}" for i in range(3)], documents=got["documents"],
                    metadatas=[dict(m, sha256="e" * 64, manifest_id="unregistered-doc") for m in got["metadatas"]],
                    embeddings=[[float(x) for x in e] for e in got["embeddings"]])
        elif name == "incomplete_update":
            cls.interrupt_update(state, index)
        out = probe("startup", index, state, "exact", state_env=state_env)
        out["_state"], out["_index"] = str(state), str(index)
        return out

    @classmethod
    def interrupt_update(cls, state, index):
        """A real interrupted approval: the swap stops between the two renames (power cut), leaving journal + renamed collection."""
        lc = dl.Lifecycle(state, index, embeddings=embeddings())
        sid = APPROVED_IDS[1]
        snap = lc._read_snapshot(lc.load()["sources"][sid]["versions"]["1"]["sha256"])
        work = cls.tmp / "inc-corpus"
        work.mkdir(exist_ok=True)
        (work / "x.txt").write_text("\n".join(c["text"] for c in snap["chunks"]) + "\nchanged")
        import hashlib
        sha = hashlib.sha256((work / "x.txt").read_bytes()).hexdigest()
        from backend import tg_manifest
        m0 = snap["chunks"][0]["metadata"]
        lc.chunker = lambda e, c: [dl.Chunk(x["text"], dict(x["metadata"], sha256=sha)) for x in snap["chunks"]]
        entry = tg_manifest.ManifestEntry(id=sid, title=m0["title"], document_type=m0["document_type"], issuing_authority=None,
                                          document_number=None, publication_date=None, effective_date=None, source_url=None,
                                          file="x.txt", jurisdiction="Telangana", format="html", source_class=m0["source_class"],
                                          verification_status=m0["verification_status"], sha256=sha, notes=None)
        v = lc.ingest(entry, work, by="integration-test")["version"]

        def crash(client, expected):
            client.get_collection(lc.collection, embedding_function=None).modify(name=lc.btx.PREVIOUS)
            raise KeyboardInterrupt("power cut")
        lc._swap = crash
        try:
            lc.approve(sid, v, by="integration-test")
        except KeyboardInterrupt:
            pass

    @classmethod
    def recovery(cls):
        f = cls.r[("exact", "incomplete_update")]
        state, index = Path(f["_state"]), Path(f["_index"])
        cls.recovery_result = dl.Lifecycle(state, index).recover("integration-test")
        cls.r[("exact", "after_recovery")] = probe("startup", index, state, "exact")

    # ---- helpers ----------------------------------------------------------------------------------------------------
    def each_mode(self, scenario):
        for mode in ("exact", "hnsw"):
            with self.subTest(mode=mode):
                yield self.r[(mode, scenario)]

    # ---- 1. lifecycle-enabled startup on the real (quarantined) registry -------------------------------------------------
    def test_startup_recognises_lifecycle_mode_and_reports_zero_servable_documents(self):
        for r in self.each_mode("quarantined"):
            self.assertEqual(r["startup"], {"enabled": True, "state": "ok", "problems": [], "servable_documents": 0, "ready": False})
            self.assertEqual(r["status"]["lifecycle"], {"enabled": True, "state": "ok", "problems": [], "servable_documents": 0,
                                                       "ready": False, "corpus_ready": False})
            self.assertEqual(r["servable_hashes"], [])

    def test_health_is_process_health_and_status_is_corpus_readiness(self):
        for r in self.each_mode("quarantined"):
            self.assertEqual((r["health"]["status"], r["health"]["body"]), (200, {"status": "ok"}))
            self.assertEqual((r["status"]["code"], r["status"]["index"], r["status"]["chunks"]), (200, "ready", 590))
            self.assertFalse(r["status"]["lifecycle"]["corpus_ready"])
            self.assertFalse(r["status"]["kb_approved"])
            self.assertEqual(r["status"]["legal_review"], "pending")

    def test_all_twenty_real_sources_are_quarantined_in_the_registry_copy_and_the_real_files_are_untouched(self):
        reg = json.loads((REAL_REGISTRY / "registry.json").read_text())
        states = {v["state"] for s in reg["sources"].values() for v in s["versions"].values()}
        self.assertEqual((len(reg["sources"]), states, [s["active_version"] for s in reg["sources"].values()].count(None)),
                         (20, {"pending"}, 20))
        self.check_untouched()

    # ---- 2. retrieval -------------------------------------------------------------------------------------------------
    def test_zero_approved_sources_means_zero_retrieval_in_exact_and_hnsw_while_unfiltered_retrieval_finds_chunks(self):
        for r in self.each_mode("quarantined"):
            self.assertEqual((r["retrieval"]["questions"], r["retrieval"]["empty"], r["retrieval"]["shas"]), (108, 108, []))
            self.assertGreater(len(r["retrieval"]["unfiltered_shas"]), 5)
            self.assertEqual(r["provider_stage"], {"prompts": 0, "evidence_items": 0, "ineligible_evidence": 0, "forbidden_text_in_prompts": 0})

    def test_only_approved_documents_are_retrieved_with_a_partial_registry_in_exact_and_hnsw(self):
        for r in self.each_mode("partial"):
            self.assertEqual(r["verify"], [])
            self.assertTrue(r["retrieval"]["within_approved"])
            self.assertGreater(r["retrieval"]["non_empty"], 20)
            self.assertTrue(r["retrieval"]["unfiltered_includes_quarantined"])
            self.assertEqual(set(r["retrieval"]["shas"]), set(r["registry"]["servable_expected"]))

    def test_nothing_ineligible_ever_reaches_the_generation_stage_or_a_citation(self):
        for r in self.each_mode("partial"):
            self.assertEqual(r["violations"], [])
            self.assertEqual(r["provider_stage_before_ops"]["ineligible_evidence"], 0)
            self.assertEqual(r["provider_stage_before_ops"]["forbidden_text_in_prompts"], 0)
            self.assertEqual((r["provider_stage_final"]["ineligible_evidence"], r["provider_stage_final"]["forbidden_text_in_prompts"]), (0, 0))
            self.assertGreater(r["provider_stage_final"]["prompts"], 10)
            self.assertEqual(r["quarantined_only_questions"]["cited_ineligible"], 0)
            self.assertGreater(r["quarantined_only_questions"]["asked"], 0)

    # ---- 3. cache -----------------------------------------------------------------------------------------------------
    def test_cold_then_warm_cache_serves_only_eligible_content_with_warnings_intact(self):
        for r in self.each_mode("partial"):
            self.assertEqual(len(r["cold"]), 3)
            self.assertTrue(r["cold_all_cited_in_approved"])
            self.assertTrue(r["warnings_on_cold"])
            self.assertEqual(r["warm"]["hit_exact"], [True, True, True])
            self.assertEqual(r["warm"]["identical_to_cold"], [True, True, True])   # same citations, same source warnings
            self.assertEqual(r["warm"]["variant_kind"], "answer")

    def test_cache_off_and_a_failing_cache_store_still_give_validated_eligible_answers(self):
        for r in self.each_mode("partial"):
            self.assertEqual(r["cache_modes"]["broken_store"]["kind"], "answer")
            self.assertEqual(r["cache_modes"]["off"]["kind"], "answer")
            self.assertEqual(r["cache_modes"]["off_cache_delta"], {})
            self.assertTrue(set(r["cache_modes"]["off"]["cited"]) <= set(r["registry"]["servable_expected"]))

    def test_corrupt_registry_or_audit_state_cannot_be_bypassed_through_cached_answers(self):
        for r in self.each_mode("partial"):
            self.assertEqual(set(r["corruption"]), {"registry_garbage", "registry_deleted", "audit_chain_edited", "mirror_deleted", "mirror_garbage"})
            for name, c in r["corruption"].items():
                with self.subTest(corruption=name):
                    self.assertEqual((c["kind"], c["cited"], c["hit"], c["retrieved"]), ("unavailable", [], False, []))
            self.assertEqual({c["health"] for c in r["corruption"].values()}, {"unreadable", "missing", "audit_failed"})
            self.assertEqual(r["after_restore"]["health"], "ok")
            self.assertEqual(r["after_restore"]["kind"], "answer")

    def test_every_lifecycle_transition_forces_revalidation_instead_of_serving_old_answers(self):
        for r in self.each_mode("partial"):
            ops = r["ops"]
            for name in ("reject_quarantined", "supersede", "rollback", "withdraw"):
                after = ops[name]["after"] if name in ("reject_quarantined", "supersede", "rollback", "withdraw") else None
                self.assertTrue(all(not a["hit"] for a in after), (name, after))
            # Stale entries are swept on the FIRST request after the epoch moves, including a request that is then refused, so
            # the per-operation counter depends on what an earlier refused request already swept. What must hold is the total
            # and that a refused request empties the cache.
            sup = ops["supersede"]
            self.assertGreater(sup["cache_entries_before_blocked_requests"], 0)
            self.assertEqual(sup["cache_entries_after_blocked_requests"], 0)
            self.assertGreaterEqual(r["cache_final"]["invalidated_epoch"], 4)
            self.assertGreaterEqual(r["cache_final"]["epoch_changes"], 4)

    def test_pending_superseded_withdrawn_and_unloaded_versions_are_never_served_or_cited(self):
        for r in self.each_mode("partial"):
            ops = r["ops"]
            new = ops["supersede"]["new_sha"]
            self.assertTrue(all(new not in a["cited"] and a["kind"] in ("answer", "no_support") for a in ops["pending_amendment"]))
            self.assertTrue(any(a["kind"] == "answer" for a in ops["pending_amendment"]))   # the active version keeps serving meanwhile
            self.assertEqual(ops["supersede"]["approve"], {"replaced": 1, "embedded": 1})
            self.assertFalse(ops["supersede"]["old_servable"])
            self.assertFalse(ops["supersede"]["new_servable_in_running_app"])   # its chunks are not in the running index: closed until restart
            self.assertTrue(all(a["kind"] == "unavailable" and a["cited"] == [] for a in ops["supersede"]["after"]))
            self.assertTrue(ops["rollback"]["old_servable"])
            self.assertFalse(ops["rollback"]["new_servable"])
            self.assertTrue(all(ops["supersede"]["new_sha"] not in a["cited"] for a in ops["rollback"]["after"]))
            self.assertFalse(ops["withdraw"]["withdrawn_servable"])
            # the withdrawn document's rule is no longer in the eligible view: "not in the available source snapshot", never its text
            self.assertIn(ops["withdraw"]["after"][0]["kind"], ("no_support", "missing_provision"))
            self.assertEqual(ops["withdraw"]["after"][0]["cited"], [])
            self.assertEqual(r["verify_after"], [])
            self.assertEqual(r["audit_after"], [])

    # ---- 4. warnings and citations ------------------------------------------------------------------------------------
    def test_source_status_metadata_problems_are_surfaced_safely_not_dropped(self):
        for r in self.each_mode("partial"):
            w = r["warning_metadata_missing"]
            self.assertEqual((w["registry_state"], w["kind"]), ("invalid", "unavailable"))     # answers are withheld, not weakened
            self.assertEqual(w["gate_errors"], ["source-status registry is invalid"])
            self.assertGreater(w["retrieved_docs"], 0)
            self.assertEqual(w["warnings_generated_directly"], w["retrieved_docs"])             # one warning per source, none dropped
            self.assertEqual(w["warning_status_ids"], ["status_not_recorded"])
            self.assertEqual(r["after_status_restore"], {"state": "valid", "gate_errors": []})

    # ---- 5. API -------------------------------------------------------------------------------------------------------
    def test_no_approved_source_gives_the_established_unavailable_response(self):
        for r in self.each_mode("quarantined"):
            for c in r["chat_real_gate"] + r["chat_gate_satisfied"]:
                self.assertEqual((c["status"], c["kind"], c["sources"]), (200, "unavailable", 0))
                self.assertTrue(c["text"].startswith("Answers from the Telangana documents aren't available yet"))
            self.assertIn("document lifecycle registry is not ready: no approved, consistent document can be served",
                          r["gate_errors_satisfied"])
            self.assertEqual(len(r["gate_errors_satisfied"]), 1)     # the lifecycle clause is the only objection left

    def test_pre_answer_replies_do_not_describe_documents_that_are_not_served(self):
        for r in self.each_mode("quarantined"):
            for c in r["catalogue_replies"]:
                with self.subTest(q=c["q"]):
                    self.assertEqual(c["kind"], "unavailable")     # no "which instrument", no "no such rule", no G.O. talk
                    self.assertNotIn("appears in", c["text"])
        for r in self.each_mode("partial"):
            c = r["catalogue_replies"]
            self.assertTrue(c["rule_10_exists_in_quarantined_tmvtr"])      # the quarantined document does contain a Rule 10 ...
            self.assertFalse(c["rule_10_names_ineligible_instrument"])     # ... and the reply never mentions that instrument
            self.assertNotEqual(c["rule_10_reply_kind"], "clarification")
            self.assertEqual(c["ineligible_only_kind"], "missing_provision")   # a rule that exists only in a quarantined document: "not in the snapshot"
            self.assertNotIn("Telangana Motor Vehicles Taxation", c["ineligible_only_text"])
            self.assertEqual(c["lookup_ambiguous_for_go"], [])

    def test_api_contracts_routes_and_frontend_are_unchanged_and_no_admin_endpoint_was_added(self):
        for r in self.each_mode("quarantined"):
            c = r["contracts"]
            self.assertEqual(set(c["routes"]), EXPECTED_ROUTES)
            self.assertEqual(c["chat_keys"], ["kb_approved", "kind", "response", "source_warnings", "sources"])
            self.assertEqual((c["chat_status"], c["kb_approved_field"], c["root_status"], c["static_status"]), (200, False, 200, 200))
            self.assertFalse(c["cors_header_present"] or c["cors_middleware"])
            self.assertEqual((c["startup_handlers"], c["shutdown_handlers"]), (0, 0))

    # ---- 6. failure and recovery --------------------------------------------------------------------------------------
    def test_every_uncertain_lifecycle_state_fails_closed_and_serves_nothing(self):
        closed = ("missing_directory", "empty_env_value", "missing_registry", "corrupt_registry", "wrong_schema", "audit_chain_edited",
                  "audit_mirror_missing", "audit_mirror_garbage", "registry_history_truncated", "interrupted_operation", "incomplete_update")
        for name in closed:
            r = self.r[("exact", name)]
            with self.subTest(state=name):
                self.assertTrue(r["startup"]["enabled"], "the filter must stay on")
                self.assertFalse(r["startup"]["ready"])
                self.assertEqual(r["startup"]["servable_documents"], 0)
                self.assertEqual(r["retrieval"]["shas"], [], "retrieval returned content from an uncertain lifecycle state")
                self.assertEqual(r["retrieval"]["empty"], 108)
                self.assertEqual(r["servable_hashes"], [])
                self.assertTrue(all(c["kind"] == "unavailable" for c in r["chat_gate_satisfied"]))
                self.assertEqual(r["provider_stage"]["prompts"], 0)
                self.assertEqual(r["violations"], [])

    def test_the_failure_states_report_distinct_reasons(self):
        expect = {"missing_directory": "missing", "empty_env_value": "missing", "missing_registry": "missing",
                  "corrupt_registry": "unreadable", "wrong_schema": "unreadable", "audit_chain_edited": "audit_failed",
                  "audit_mirror_missing": "audit_failed", "audit_mirror_garbage": "audit_failed",
                  "registry_history_truncated": "audit_failed", "interrupted_operation": "interrupted"}
        for name, state in expect.items():
            with self.subTest(state=name):
                self.assertEqual(self.r[("exact", name)]["startup"]["state"], state)
                self.assertTrue(self.r[("exact", name)]["status"]["lifecycle"]["problems"])

    def test_control_the_healthy_synthetic_registry_does_serve_its_approved_documents(self):
        r = self.r[("exact", "healthy_control")]
        self.assertTrue(r["startup"]["ready"])
        self.assertEqual((r["startup"]["servable_documents"], len(r["servable_hashes"])), (2, 2))
        self.assertGreater(108 - r["retrieval"]["empty"], 20)
        self.assertTrue(set(r["retrieval"]["shas"]) <= set(r["servable_hashes"]))
        self.assertIn("answer", {c["kind"] for c in r["chat_gate_satisfied"]})

    def test_index_registry_mismatch_withholds_only_the_disagreeing_document(self):
        r = self.r[("exact", "index_registry_count_mismatch")]
        self.assertEqual(r["startup"]["state"], "index_mismatch")
        self.assertFalse(r["startup"]["ready"])
        self.assertEqual(r["startup"]["servable_documents"], 1)
        self.assertEqual(len(r["servable_hashes"]), 1)
        self.assertTrue(set(r["retrieval"]["shas"]) <= set(r["servable_hashes"]))
        self.assertTrue(all(c["kind"] == "unavailable" for c in r["chat_gate_satisfied"]))   # not ready: nothing is answered

    def test_a_document_in_the_index_that_the_registry_does_not_know_is_never_served(self):
        r = self.r[("exact", "unknown_hash_in_index")]
        self.assertTrue(r["startup"]["ready"])
        self.assertNotIn("e" * 64, r["retrieval"]["shas"])
        self.assertTrue(set(r["retrieval"]["shas"]) <= set(r["servable_hashes"]))
        self.assertEqual(r["violations"], [])

    def test_recovery_after_an_incomplete_update_restores_service_on_the_next_startup(self):
        self.assertEqual(self.recovery_result["action"], "aborted")
        broken, healed, control = self.r[("exact", "incomplete_update")], self.r[("exact", "after_recovery")], self.r[("exact", "healthy_control")]
        self.assertEqual((broken["startup"]["state"], broken["status"]["index"]), ("interrupted", "missing"))
        self.assertEqual(healed["startup"]["state"], "ok")
        self.assertTrue(healed["startup"]["ready"])
        self.assertEqual(healed["retrieval"]["shas"], control["retrieval"]["shas"])
        self.assertEqual(healed["status"]["lifecycle"]["problems"], [])
        self.assertEqual(healed["violations"], [])


if __name__ == "__main__":
    unittest.main()
