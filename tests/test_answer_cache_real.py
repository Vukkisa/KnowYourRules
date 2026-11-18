"""Stage 5: the answer cache inside the real backend (real index copy, real Ollama embeddings, real retrieval and validator),
exact and hnsw. tests/answer_cache_probe.py does the work in its own process; only the answering model is a deterministic
stand-in (tests/answer_cache_gen.py). No live provider is called. Gate and skip rules are those of test_licence_retrieval."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_view_source_real import INDEX_DIR, REQUIRED, missing  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(os.environ.get("KYR_REAL_INDEX_DIR") or REQUIRED, "real backend not configured")
class RealAnswerCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reason = missing()
        if reason and REQUIRED:
            raise AssertionError(f"real backend test required but cannot run: {reason}")
        if reason:
            raise unittest.SkipTest(reason)
        cls.tmp = tempfile.mkdtemp(prefix="kyr-answer-cache-")
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.results = {}
        for mode in ("exact", "hnsw"):
            copy = Path(cls.tmp) / mode
            shutil.copytree(INDEX_DIR, copy)
            env = {k: v for k, v in os.environ.items() if not k.startswith(("TG_", "GROQ_", "GEMINI_", "PROVIDER_", "RAG_"))}
            env.update(TG_DB_DIR=str(copy), RAG_VECTOR_SEARCH=mode, GROQ_API_KEY="offline-probe-not-real", TG_CACHE="semantic",
                       ANONYMIZED_TELEMETRY="False")
            run = subprocess.run([sys.executable, str(ROOT / "tests" / "answer_cache_probe.py")], cwd=ROOT, env=env,
                                 capture_output=True, text=True, timeout=900)
            if run.returncode != 0:
                raise AssertionError(f"probe ({mode}) failed:\n" + run.stderr[-3000:])
            cls.results[mode] = json.loads(run.stdout.strip().splitlines()[-1])["scenarios"]

    def each(self, name):
        for mode, scenarios in self.results.items():
            with self.subTest(mode=mode, scenario=name):
                self.assertNotIn("exception", scenarios[name], scenarios[name])
                yield scenarios[name]

    # ---- hits ------------------------------------------------------------------------------------------------------
    def test_exact_hit_returns_the_same_validated_answer_without_generating(self):
        for r in self.each("exact_hit"):
            self.assertEqual(r["kinds"], ["answer"] * 3)
            self.assertEqual(r["generations"], [1, 1])
            self.assertEqual(r["identical_to_first"], [True, True])
            self.assertEqual(r["counters"]["hit_exact"], 2)
            self.assertGreaterEqual(r["sources"], 1)

    def test_semantic_hit_is_identical_to_a_fresh_answer_and_skips_generation(self):
        # Exact search is deterministic, so the hit is required. HNSW can return a slightly different context for the
        # reworded question; then the fresh-context rule must refuse the hit (a miss is the safe outcome). Either way the
        # response must equal a fresh answer and a hit must not have generated.
        for mode, scenarios in self.results.items():
            r = scenarios["semantic_hit_equals_fresh_answer"]
            with self.subTest(mode=mode):
                self.assertTrue(r["hit_equals_fresh"], r)
                if "hit_semantic" in r["delta"]:
                    self.assertEqual((r["delta"]["hit_semantic"], r["generations_after_hit"]), (1, 1))
                else:
                    self.assertEqual(mode, "hnsw", r)
                    self.assertEqual((r["delta"].get("semantic_replay_rejected", 0) + r["delta"].get("miss_semantic", 0) > 0,
                                      r["generations_after_hit"]), (True, 2))

    # ---- legal correctness -------------------------------------------------------------------------------------------
    def test_a_different_legal_situation_is_never_answered_from_the_cache(self):
        for r in self.each("different_legal_situation_is_a_miss"):
            for label, case in r.items():
                with self.subTest(case=label):
                    self.assertEqual(case["generated"], 1, case)
                    self.assertNotIn("hit_exact", case["delta"])
                    self.assertNotIn("hit_semantic", case["delta"])

    def test_fee_questions_use_the_exact_layer_only(self):
        for r in self.each("fee_and_date_questions_are_exact_only"):
            self.assertNotIn("hit_semantic", r["delta"])
            self.assertNotIn("miss_semantic", r["delta"])  # the semantic layer was not even consulted
            self.assertEqual(r["entries"], 2)

    def test_unvalidated_and_refused_outputs_are_never_cached(self):
        for r in self.each("unsupported_and_unvalidated_are_not_cached"):
            for mode in ("refuse", "malformed", "fabricate", "penalty_wording"):
                self.assertEqual(r[mode], {"kind": "no_support", "entries": 0}, mode)
            self.assertEqual(r["refusal_is_regenerated_not_replayed"], {"generations": 2, "entries": 0})
            self.assertEqual(r["recovers_after_failures"], {"kind": "answer", "generated": 1})

    def test_penalty_questions_and_follow_ups_never_reach_the_cache(self):
        for r in self.each("penalty_question_stays_locked"):
            self.assertEqual(r["kinds"], ["restricted", "restricted"])
        for r in self.each("vague_follow_up_never_uses_the_cache"):
            self.assertEqual(r["kind"], "clarification")

    # ---- security --------------------------------------------------------------------------------------------------
    def test_a_tampered_entry_is_revalidated_and_refused(self):
        for r in self.each("poisoned_entry_is_not_served"):
            self.assertFalse(r["mentions_fabrication"])
            self.assertEqual(r["regenerated"], 1)
            self.assertEqual(r["delta"].get("invalidated_revalidation"), 1)

    def test_personal_identifiers_are_not_cached(self):
        for r in self.each("personal_identifiers_are_not_cached"):
            self.assertEqual((r["entries"], r["bypassed"]), (0, 1))

    def test_no_cross_user_leak_and_no_withheld_source(self):
        for r in self.each("cross_user_isolation"):
            self.assertTrue(r["bob_body_is_fresh_body"])
            self.assertFalse(r["response_mentions_session"])
        for r in self.each("no_withheld_source_in_cached_answers"):
            self.assertTrue(r["all_cited_sources_approved"])
            self.assertFalse(r["hit_mentions_third_schedule"])

    def test_cache_off_stores_and_hits_nothing(self):
        for r in self.each("cache_off_never_stores_or_hits"):
            self.assertEqual((r["generations"], r["entries"], r["counters"]), (2, 0, {}))

    # ---- invalidation ----------------------------------------------------------------------------------------------
    def test_any_change_to_the_inputs_of_an_answer_invalidates_it(self):
        for name in ("invalidation_source_withdrawn_from_approval", "invalidation_new_amendment_ingested",
                     "invalidation_index_rebuilt_or_changed", "invalidation_embedding_model_changed",
                     "invalidation_chunking_configuration_changed", "invalidation_retrieval_setting_changed",
                     "invalidation_validator_code_changed", "invalidation_answer_generator_replaced"):
            for r in self.each(name):
                with self.subTest(change=name):
                    self.assertEqual(r["entries_before"], 1)
                    self.assertEqual(r["delta"].get("invalidated_epoch"), 1, r)
                    self.assertNotIn("hit_exact", r["delta"])
                    self.assertNotIn("hit_semantic", r["delta"])

    def test_a_withdrawn_source_gives_no_answer_from_the_cache(self):
        for r in self.each("invalidation_source_withdrawn_from_approval"):
            self.assertEqual((r["after"], r["regenerated"]), ("no_support", 0))
            self.assertFalse(r["same_answer"])

    def test_expiry(self):
        for r in self.each("invalidation_ttl_expired"):
            self.assertEqual(r["delta"].get("invalidated_expired"), 1)
            self.assertEqual(r["regenerated"], 1)

    def test_a_cited_chunk_that_changes_without_any_other_signal_is_caught_by_the_dependency_check(self):
        for r in self.each("invalidation_cited_chunk_edited_in_place"):
            self.assertNotIn("invalidated_epoch", r["delta"])      # nothing else changed: the epoch is the same
            self.assertEqual(r["delta"].get("invalidated_source"), 1)
            self.assertEqual(r["regenerated"], 1)
            self.assertNotIn("hit_exact", r["delta"])

    def test_a_deleted_source_chunk_is_not_served(self):
        for r in self.each("invalidation_cited_chunk_deleted"):
            self.assertFalse(r["stale_answer_served"])
            self.assertEqual(r["regenerated"], 1)

    def test_one_document_can_be_invalidated_without_clearing_the_cache(self):
        for r in self.each("invalidation_one_document_only"):
            self.assertEqual((r["dropped"], r["entries_after"]), (1, 1))

    # ---- robustness ------------------------------------------------------------------------------------------------
    def test_concurrent_requests_are_consistent(self):
        for r in self.each("concurrent_identical_requests"):
            self.assertEqual(r["errors"], [])
            self.assertEqual((r["answers"], r["distinct_bodies"], r["kinds"]), (12, 1, ["answer"]))
            self.assertGreaterEqual(r["generations"], 1)
            self.assertEqual(r["entries"], 1)

    def test_storage_failure_does_not_break_answers(self):
        for r in self.each("storage_failure_is_harmless"):
            self.assertEqual(r["statuses"], [200, 200])
            self.assertEqual(r["kinds"], ["answer", "answer"])
            self.assertEqual(r["generations"], 2)
            self.assertGreater(r["storage_errors"], 0)


if __name__ == "__main__":
    unittest.main()
