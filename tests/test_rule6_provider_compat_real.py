"""Stage 4G: Rule 6 through the real provider abstraction (Groq, Gemini, Ollama request/response handling, retries,
classification, validation fallback) with MOCKED provider HTTP, the real backend /chat and a real index copy, in exact and
hnsw mode. tests/rule6_provider_probe.py does the work in its own process. No live provider is called.
Gate and skip rules are those of tests/test_licence_retrieval.py."""
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
PROVIDERS = ("groq", "gemini", "ollama")
ACCEPTED = ("verbatim", "whitespace", "interp_restated", "interp_contraction", "interp_nbsp")
REJECTED_BY_PENALTY = ("interp_bold", "interp_noun", "penalty_beside")
REJECTED_AS_NOT_JSON = ("fenced", "prose")


@unittest.skipUnless(os.environ.get("KYR_REAL_INDEX_DIR") or REQUIRED, "real backend not configured")
class RealProviderCompatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reason = missing()
        if reason and REQUIRED:
            raise AssertionError(f"real backend test required but cannot run: {reason}")
        if reason:
            raise unittest.SkipTest(reason)
        cls.tmp = tempfile.mkdtemp(prefix="kyr-rule6-providers-")
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.results = {}
        for mode in ("exact", "hnsw"):
            copy = Path(cls.tmp) / mode
            shutil.copytree(INDEX_DIR, copy)
            env = {k: v for k, v in os.environ.items() if not k.startswith(("TG_", "GROQ_", "GEMINI_", "PROVIDER_", "RAG_"))}
            env.update(TG_DB_DIR=str(copy), RAG_VECTOR_SEARCH=mode, GROQ_API_KEY="offline-probe-not-real")
            run = subprocess.run([sys.executable, str(ROOT / "tests" / "rule6_provider_probe.py")], cwd=ROOT, env=env,
                                 capture_output=True, text=True, timeout=900)
            if run.returncode != 0:
                raise AssertionError(f"probe ({mode}) failed:\n" + run.stderr[-3000:])
            cls.results[mode] = {r["label"]: r for r in json.loads(run.stdout.strip().splitlines()[-1])["rows"]}

    def rows(self):
        for mode, rows in self.results.items():
            with self.subTest(mode=mode):
                yield rows

    def test_every_provider_gets_rule6_and_accepted_wording_becomes_a_cited_answer(self):
        for rows in self.rows():
            for name in PROVIDERS:
                for style in ACCEPTED:
                    r = rows[f"{name}:{style}"]
                    with self.subTest(provider=name, style=style):
                        self.assertEqual((r["kind"], r["provider"], r["http_order"]), ("answer", name, [name]))
                        self.assertTrue(r["rule6_in_request"])
                        self.assertFalse(r["third_schedule_sent"])
                        self.assertEqual(r["n_sources"], 1)
                        self.assertGreaterEqual(r["source_warnings"], 1)
                        self.assertEqual(r["validation_errors"], [[]])

    def test_wording_that_is_not_the_sources_is_rejected_for_every_provider(self):
        for rows in self.rows():
            for name in PROVIDERS:
                for style in REJECTED_BY_PENALTY:
                    with self.subTest(provider=name, style=style):
                        r = rows[f"{name}:{style}"]
                        self.assertEqual(r["kind"], "no_support")
                        self.assertEqual(r["validation_errors"], [["penalty content withheld (penalty_term)"]])
                        self.assertEqual((r["n_sources"], r["http_order"]), (0, [name]))

    def test_output_that_is_not_bare_json_fails_closed_for_every_provider(self):
        # Pinned behaviour, not an endorsement: providers are asked for structured output, and no live run has produced
        # fenced or prose-wrapped JSON. Parsing leniency was deliberately not added.
        for rows in self.rows():
            for name in PROVIDERS:
                for style in REJECTED_AS_NOT_JSON:
                    with self.subTest(provider=name, style=style):
                        r = rows[f"{name}:{style}"]
                        self.assertEqual((r["kind"], r["validation_errors"]), ("no_support", [["malformed JSON"]]))

    def test_honest_refusal_is_not_retried_elsewhere(self):
        for rows in self.rows():
            for name in PROVIDERS:
                r = rows[f"{name}:refusal"]
                self.assertEqual((r["kind"], r["http_order"]), ("no_support", [name]))

    def test_gemini_thought_parts_are_not_part_of_the_answer(self):
        for rows in self.rows():
            self.assertEqual(rows["gemini:verbatim+thought_part"]["kind"], "answer")

    def test_fallback_order_and_classification(self):
        for rows in self.rows():
            self.assertEqual(rows["chain:groq_ok"]["http_order"], ["groq"])
            q = rows["chain:groq_quota->gemini"]
            self.assertEqual((q["kind"], q["provider"], q["http_order"], q["fallback_reasons"]),
                             ("answer", "gemini", ["groq", "gemini"], ["groq: quota_exhausted"]))
            u = rows["chain:groq_503->gemini"]
            self.assertEqual((u["provider"], u["http_order"]), ("gemini", ["groq", "groq", "gemini"]))
            o = rows["chain:groq_quota,gemini_quota->ollama"]
            self.assertEqual((o["provider"], o["http_order"], o["fallback_reasons"]),
                             ("ollama", ["groq", "gemini", "ollama"], ["groq: quota_exhausted", "gemini: quota_exhausted"]))
            d = rows["chain:all_down"]
            self.assertEqual((d["kind"], d["provider"], d["n_sources"]), ("unavailable", None, 0))

    def test_validation_failure_is_not_bypassed_by_fallback(self):
        for rows in self.rows():
            for label in ("chain:groq_penalty_beside->gemini_verbatim", "chain:groq_noun->gemini_verbatim"):
                r = rows[label]
                self.assertEqual((r["kind"], r["provider"], r["http_order"]), ("answer", "gemini", ["groq", "gemini"]))
                self.assertEqual(r["validation_errors"], [["penalty content withheld (penalty_term)"], []])  # both validated
                self.assertEqual(r["fallback_reasons"], ["groq: validation_rejected"])
            both = rows["chain:groq_penalty,gemini_penalty"]
            self.assertEqual(both["kind"], "no_support")
            self.assertEqual(both["http_order"], ["groq", "gemini"])  # bounded: Ollama is not asked
            self.assertEqual(both["n_sources"], 0)

    def test_no_request_ever_carries_the_withheld_schedule(self):
        for rows in self.rows():
            self.assertFalse(any(r["third_schedule_sent"] for r in rows.values()))


if __name__ == "__main__":
    unittest.main()
