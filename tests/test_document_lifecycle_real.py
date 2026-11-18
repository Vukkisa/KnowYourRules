"""Stage 6: the lifecycle inside the real backend, across a restart (phase a, then phase b in a new process), in exact and
hnsw mode, on a temporary COPY of a real index. Gate and skip rules are those of test_licence_retrieval. The real index
directory is only copied, never opened; the answering model is a deterministic stand-in; no live provider is called."""
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
class RealLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reason = missing()
        if reason and REQUIRED:
            raise AssertionError(f"real backend test required but cannot run: {reason}")
        if reason:
            raise unittest.SkipTest(reason)
        cls.tmp = tempfile.mkdtemp(prefix="kyr-lifecycle-real-")
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.results = {}
        for mode in ("exact", "hnsw"):
            base = Path(cls.tmp) / mode
            shutil.copytree(INDEX_DIR, base / "index")
            env = {k: v for k, v in os.environ.items() if not k.startswith(("TG_", "GROQ_", "GEMINI_", "PROVIDER_", "RAG_"))}
            env.update(TG_DB_DIR=str(base / "index"), RAG_VECTOR_SEARCH=mode, GROQ_API_KEY="offline-probe-not-real",
                       TG_CACHE="semantic", TG_LIFECYCLE_DIR=str(base / "state"), ANONYMIZED_TELEMETRY="False")
            cls.results[mode] = {}
            for phase in ("a", "b"):
                run = subprocess.run([sys.executable, str(ROOT / "tests" / "lifecycle_probe.py"), phase], cwd=ROOT, env=env,
                                     capture_output=True, text=True, timeout=900)
                if run.returncode != 0:
                    raise AssertionError(f"probe ({mode}, phase {phase}) failed:\n" + run.stderr[-3000:])
                cls.results[mode][phase] = json.loads(run.stdout.strip().splitlines()[-1])

    def each(self):
        for mode, phases in self.results.items():
            with self.subTest(mode=mode):
                yield phases["a"], phases["b"]

    def test_a_bootstrapped_registry_is_consistent_and_serves_the_existing_answer(self):
        for a, b in self.each():
            self.assertTrue(a["lifecycle_enabled"])
            self.assertEqual(a["verify_at_start"], [])
            self.assertEqual(a["warm"]["kinds"], ["answer", "answer"])
            self.assertEqual(len(a["warm"]["cited"]), 1)

    def test_a_pending_amendment_is_not_retrievable_and_the_old_version_keeps_serving(self):
        for a, _ in self.each():
            self.assertEqual((a["pending"]["ingest"]["outcome"], a["pending"]["ingest"]["supersedes"]), ("new_version", 1))
            self.assertFalse(a["pending"]["index_has_new"])
            self.assertFalse(a["pending"]["new_sha_in_response"])
            self.assertTrue(a["pending"]["old_sha_in_response"])

    def test_approval_embeds_only_the_changed_chunk(self):
        for a, _ in self.each():
            self.assertEqual((a["approve"]["embedded"], a["approve"]["replaced"]), (1, 1))
            self.assertGreater(a["approve"]["reused"], 0)
            self.assertEqual(a["verify_after"], [])

    def test_after_approval_the_cached_answer_and_the_old_text_are_gone(self):
        for a, _ in self.each():
            r = a["after_approve_in_process"]
            self.assertFalse(r["hit"])
            self.assertFalse(r["old_sha_in_response"])
            self.assertGreaterEqual(r["cache_delta"].get("invalidated_epoch", 0), 1)

    def test_after_a_restart_the_amended_version_serves_and_the_old_one_does_not(self):
        for a, b in self.each():
            self.assertEqual(b["verify_at_start"], [])
            self.assertEqual(b["restart"]["status_after_restart"]["active"], 2)
            self.assertTrue(b["restart"]["new_sha_served"])
            self.assertFalse(b["restart"]["old_sha_served"])

    def test_rollback_invalidates_answers_built_on_the_replaced_version(self):
        for a, b in self.each():
            r = b["after_rollback_in_process"]
            self.assertFalse(r["hit"])
            self.assertFalse(r["new_sha_in_response"])
            self.assertGreaterEqual(r["cache_delta"].get("invalidated_epoch", 0), 1)
            self.assertEqual(b["verify_after"], [])


if __name__ == "__main__":
    unittest.main()
