"""Stage 4D: driving-licence retrieval.

Root cause: reciprocal-rank fusion let two keyword-only chunks (BM25 rank 2 and 3) displace Rule 6 (vector rank 3)
because a BM25-only hit at rank r gets the same vote as a vector-only hit at rank r and ties go to the BM25 list.
The guard (hybrid_retrieval.protect_vector_leaders, RAG_VECTOR_PROTECT, default 3) keeps the vector search's own
best chunks. See eval/latency/STAGE-4D-REPORT.md.

Unit tests run offline. The real-backend tests need KYR_REAL_INDEX_DIR and Ollama (same rules as
tests/test_view_source_real.py): they are skipped without them, and fail instead if KYR_REQUIRE_REAL_BACKEND=1.
Labels in eval/licence-retrieval-set.json were written by Claude and are not human-reviewed.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.documents import Document  # noqa: E402

from backend import hybrid_retrieval as hr  # noqa: E402
from test_view_source_real import INDEX_DIR, REQUIRED, missing  # noqa: E402 (shared real-backend gate)

ROOT = Path(__file__).resolve().parent.parent
LIC = {c["id"]: c for c in json.loads((ROOT / "eval" / "licence-retrieval-set.json").read_text())["cases"]}
RULE6 = "tmvr-1989-chap-2::Rule 6"


def doc(name):
    return Document(page_content=name, metadata={"manifest_id": "m", "provision_id": name, "part": 1})


def names(docs):
    return [d.metadata["provision_id"] for d in docs]


class ProtectVectorLeadersTests(unittest.TestCase):
    def setUp(self):
        self.d = {n: doc(n) for n in "ABCDEFGHI"}

    def run_guard(self, top, candidates, vector, protect=3, k=6):
        pick = lambda xs: [self.d[x] for x in xs]  # noqa: E731
        return names(hr.protect_vector_leaders(pick(top), pick(candidates), pick(vector), protect, k))

    def test_dropped_vector_leader_is_restored_at_the_expense_of_the_lowest_unprotected(self):
        # fused order A..G; vector ranks C 3rd, but C was 7th after fusion
        got = self.run_guard(top=list("ABDEFG"), candidates=list("ABDEFGC"), vector=list("HIC"), protect=3)
        self.assertIn("C", got)
        self.assertEqual(len(got), 6)
        self.assertEqual(got[:5], list("ABDEF"))  # only the last unprotected item made room

    def test_leader_already_present_changes_nothing(self):
        top = list("ABCDEF")
        self.assertEqual(self.run_guard(top, top + ["G"], list("CAB")), top)

    def test_protect_zero_is_the_unguarded_behaviour(self):
        top = list("ABDEFG")
        self.assertEqual(self.run_guard(top, top + ["C"], list("HIC"), protect=0), top)

    def test_a_vector_hit_that_fusion_or_a_filter_rejected_is_never_added(self):
        # H and I are vector leaders but are not in the candidate list (filtered out upstream: withheld, wrong
        # state or unapproved), so the guard may not bring them back.
        got = self.run_guard(top=list("ABCDEF"), candidates=list("ABCDEF"), vector=list("HIA"), protect=3)
        self.assertEqual(got, list("ABCDEF"))
        self.assertNotIn("H", got)

    def test_protected_chunks_are_never_evicted_and_the_result_never_exceeds_k(self):
        got = self.run_guard(top=list("ABCDEF"), candidates=list("ABCDEFGHI"), vector=list("GHI"), protect=3)
        self.assertEqual(sorted(got), sorted(["A", "B", "C", "G", "H", "I"]))  # F, E, D made room; G, H, I kept
        self.assertEqual(len(got), 6)

    def test_short_result_list_is_not_padded_or_trimmed(self):
        got = self.run_guard(top=list("AB"), candidates=list("ABC"), vector=list("C"), protect=3, k=6)
        self.assertEqual(got, ["A", "B", "C"])

    def test_duplicate_vector_hits_count_once(self):
        got = self.run_guard(top=list("ABDEFG"), candidates=list("ABDEFGC"), vector=list("CCC"), protect=3)
        self.assertEqual(got.count("C"), 1)

    def test_environment_parsing(self):
        self.assertEqual([hr.parse_vector_protect(v) for v in ("3", "0", "2", "6", "7", "-1", "x", None, "")],
                         [3, 0, 2, 6, 3, 3, 3, 3, 3])


class LicenceSetIntegrityTests(unittest.TestCase):
    def test_every_case_has_an_id_question_and_lists(self):
        for cid, c in LIC.items():
            self.assertTrue(c["question"].strip(), cid)
            for key in ("must_include", "related", "must_exclude"):
                self.assertIsInstance(c[key], list, cid)
            self.assertFalse(set(c["must_include"]) & set(c["must_exclude"]), cid)

    def test_rule6_answer_cases_and_exclusion_cases_exist(self):
        kinds = {c["kind"] for c in LIC.values()}
        self.assertEqual(kinds, {"rule6_answers", "corpus_gap", "unrelated_licence"})
        self.assertGreaterEqual(sum(1 for c in LIC.values() if RULE6 in c["must_include"]), 5)
        self.assertGreaterEqual(sum(1 for c in LIC.values() if RULE6 in c["must_exclude"]), 4)

    def test_corpus_gap_questions_do_not_require_any_provision(self):
        # The stored Telangana corpus has no provision listing the requirements for a licence; the set must not
        # pretend otherwise.
        for c in LIC.values():
            if c["kind"] == "corpus_gap":
                self.assertEqual(c["must_include"], [], c["id"])


@unittest.skipUnless(os.environ.get("KYR_REAL_INDEX_DIR") or REQUIRED, "real backend not configured")
class RealLicenceRetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reason = missing()
        if reason and REQUIRED:
            raise AssertionError(f"real backend test required but cannot run: {reason}")
        if reason:
            raise unittest.SkipTest(reason)
        cls.tmp = tempfile.mkdtemp(prefix="kyr-licence-index-")
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.results = {}
        for mode in ("exact", "hnsw"):  # both modes in every run, whatever RAG_VECTOR_SEARCH the suite uses
            copy = Path(cls.tmp) / mode
            shutil.copytree(INDEX_DIR, copy)
            env = {k: v for k, v in os.environ.items() if not k.startswith(("TG_", "GROQ_", "GEMINI_", "PROVIDER_", "RAG_"))}
            env.update(TG_DB_DIR=str(copy), RAG_VECTOR_SEARCH=mode)
            run = subprocess.run([sys.executable, str(ROOT / "tests" / "licence_retrieval_probe.py")], cwd=ROOT, env=env,
                                 capture_output=True, text=True, timeout=600)
            if run.returncode != 0:
                raise AssertionError(f"probe ({mode}) failed:\n" + run.stderr[-3000:])
            cls.results[mode] = json.loads(run.stdout.strip().splitlines()[-1])

    def each_mode(self):
        for mode, r in self.results.items():
            with self.subTest(mode=mode):
                yield mode, r

    def test_modes_ran_as_asked(self):
        self.assertEqual({m: r["vector_search"] for m, r in self.results.items()}, {"exact": "exact", "hnsw": "hnsw"})

    def test_rule6_is_retrieved_for_every_question_it_answers(self):
        for mode, r in self.each_mode():
            for cid, c in LIC.items():
                if RULE6 in c["must_include"]:
                    self.assertIn(RULE6, r["licence"][cid], f"{cid}: {c['question']}")

    def test_every_must_include_is_retrieved(self):
        for mode, r in self.each_mode():
            for cid, c in LIC.items():
                for want in c["must_include"]:
                    self.assertIn(want, r["licence"][cid], f"{cid}: {c['question']}")

    def test_unrelated_licence_questions_do_not_retrieve_rule6_or_other_excluded_provisions(self):
        for mode, r in self.each_mode():
            for cid, c in LIC.items():
                for bad in c["must_exclude"]:
                    self.assertNotIn(bad, r["licence"][cid], f"{cid}: {c['question']}")

    def test_the_guard_was_needed_the_unguarded_run_misses_rule6_for_the_original_case(self):
        # Documents the root cause on this index: without the guard LIC-001 loses Rule 6 to two keyword-only chunks.
        for mode, r in self.each_mode():
            self.assertNotIn(RULE6, r["licence_unguarded"]["LIC-001"])
            self.assertIn(RULE6, r["licence"]["LIC-001"])

    def test_every_retrievable_benchmark_question_still_gets_an_expected_provision(self):
        bench = {c["id"]: c for c in json.loads((ROOT / "eval" / "telangana-retrieval-benchmark.json").read_text())["cases"]}
        for mode, r in self.each_mode():
            for cid, got in r["benchmark"].items():
                case = bench[cid]
                if case["expected_retrieval_outcome"] == "retrieve" and case["expected_provisions"]:
                    self.assertTrue(set(got) & set(case["expected_provisions"]), f"{cid}: no expected provision in top 6")

    def test_withheld_and_excluded_evidence_is_never_retrieved(self):
        for mode, r in self.each_mode():
            self.assertEqual(r["leaks"], [])

    def test_exact_and_hnsw_agree_on_every_licence_question(self):
        # Only the licence set is compared. HNSW is approximate and varies between opens of identical copies (Stage 15):
        # on the benchmark, 0-3 of 108 questions differ from exact between runs, with or without the guard, so a
        # benchmark-wide equality assertion would be flaky and is deliberately not made.
        e, h = self.results["exact"], self.results["hnsw"]
        for section in ("licence", "licence_unguarded"):
            self.assertEqual(e[section], h[section], section)


if __name__ == "__main__":
    unittest.main()
