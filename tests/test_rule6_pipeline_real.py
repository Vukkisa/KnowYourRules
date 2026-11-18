"""Stage 4F: the Rule 6 false rejection through the REAL pipeline (real backend.server /chat, real Chroma index copy, real
Ollama embeddings, real retrieval, context assembly and validator) in exact AND hnsw mode. The model is a scripted
generator (tests/rule6_pipeline_probe.py), so the run is deterministic and no provider is called. Gate and skip rules
are the same as tests/test_licence_retrieval.py: skipped without KYR_REAL_INDEX_DIR, failing under
KYR_REQUIRE_REAL_BACKEND=1 if the backend cannot run."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_view_source_real import INDEX_DIR, REQUIRED, missing  # noqa: E402 (shared real-backend gate)

ROOT = Path(__file__).resolve().parent.parent
LEGIT = ("quote",)
MUST_STAY_REFUSED = ("penalty", "grounded_penalty", "mixed_two_claims", "fabricate")


@unittest.skipUnless(os.environ.get("KYR_REAL_INDEX_DIR") or REQUIRED, "real backend not configured")
class RealRule6PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reason = missing()
        if reason and REQUIRED:
            raise AssertionError(f"real backend test required but cannot run: {reason}")
        if reason:
            raise unittest.SkipTest(reason)
        cls.tmp = tempfile.mkdtemp(prefix="kyr-rule6-index-")
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.results = {}
        for mode in ("exact", "hnsw"):
            copy = Path(cls.tmp) / mode
            shutil.copytree(INDEX_DIR, copy)
            env = {k: v for k, v in os.environ.items() if not k.startswith(("TG_", "GROQ_", "GEMINI_", "PROVIDER_", "RAG_"))}
            env.update(TG_DB_DIR=str(copy), RAG_VECTOR_SEARCH=mode, GROQ_API_KEY="offline-probe-not-real")
            run = subprocess.run([sys.executable, str(ROOT / "tests" / "rule6_pipeline_probe.py")], cwd=ROOT, env=env,
                                 capture_output=True, text=True, timeout=600)
            if run.returncode != 0:
                raise AssertionError(f"probe ({mode}) failed:\n" + run.stderr[-3000:])
            cls.results[mode] = json.loads(run.stdout.strip().splitlines()[-1])

    def each_mode(self):
        for mode, r in self.results.items():
            with self.subTest(mode=mode):
                yield mode, r

    @staticmethod
    def rows(r, tag, scripts, question_part=None):
        return [x for x in r[tag] if x["script"] in scripts and (question_part is None or question_part in x["question"])]

    def test_modes_ran_as_asked(self):
        self.assertEqual({r["vector_search"] for r in self.results.values()}, {"exact", "hnsw"})

    def test_rule6_text_reaches_the_provider_context_for_both_licence_questions(self):
        for _m, r in self.each_mode():
            for x in self.rows(r, "after", LEGIT):
                self.assertTrue(x["context"]["has_rule6_text"], x["question"])
                self.assertIn("Rule 6", x["context"]["provisions"], x["question"])

    def test_legitimate_rule6_answer_is_accepted_after_and_was_rejected_before(self):
        for _m, r in self.each_mode():
            for x in self.rows(r, "after", LEGIT):
                self.assertEqual((x["kind"], x["validation_errors"]), ("answer", []), x["question"])
                self.assertEqual(x["n_sources"], 1)
                self.assertGreaterEqual(x["source_warnings"], 1)  # source-status warning still rendered
                self.assertIn("not disqualified", x["answer"])
            for x in self.rows(r, "before", LEGIT):
                self.assertEqual(x["kind"], "no_support", x["question"])
                self.assertEqual(x["validation_errors"], ["penalty content withheld (penalty_term)"])

    def test_genuine_penalty_and_fabricated_claims_stay_refused(self):
        for _m, r in self.each_mode():
            for tag in ("before", "after"):
                for x in self.rows(r, tag, MUST_STAY_REFUSED):
                    self.assertNotEqual(x["kind"], "answer", (tag, x["script"], x["question"]))

    def test_a_grounded_penalty_claim_is_still_stopped_by_the_penalty_gate(self):
        for _m, r in self.each_mode():
            for x in self.rows(r, "after", ("grounded_penalty", "mixed_two_claims")):
                self.assertTrue(any(e.startswith("penalty content withheld") for e in x["validation_errors"]),
                                (x["script"], x["validation_errors"]))

    def test_unsupported_licence_requirements_remain_refusals(self):
        for _m, r in self.each_mode():
            for x in r["after"]:
                if x["question"].startswith(("What are the requirements", "What documents are required")):
                    self.assertEqual(x["kind"], "no_support", (x["script"], x["question"]))

    def test_the_exception_changes_only_rule_6_and_rule_52_in_the_whole_corpus(self):
        for _m, r in self.each_mode():
            self.assertEqual(sorted(c["provision"] for c in r["corpus_changed_sentences"]), ["Rule 52", "Rule 6"])
            for c in r["corpus_changed_sentences"]:
                self.assertEqual((c["before"], c["after"]), ("penalty_term", None))
            self.assertEqual(r["corpus_sentences_with_negated_status"], ["Rule 52", "Rule 6"])

    def test_no_withheld_schedule_reaches_any_context(self):
        for _m, r in self.each_mode():
            for tag in ("before", "after"):
                for x in r[tag]:
                    if x["context"]:
                        self.assertFalse(x["context"]["third_schedule"] or x["context"]["withheld"], x["question"])


if __name__ == "__main__":
    unittest.main()
