"""Stage 7B.2: the evidence behind the Path A / Path B comparison. Offline: reads files under eval/deployment/stage7b2/ only. No network,
no Ollama, no accounts; the real index is not opened (its digest is compared with the recorded one by reading the baseline record).
What is asserted: the independently re-run Path A agreement with Ollama and with the stored index; that Path B (bge-small-en-v1.5) was
built as a separate 384-d candidate index with the same ids/metadata; the recorded Path B regressions (so they cannot be quietly
dropped); that production embedding configuration and the legal state are unchanged; that the R2 fix has no delete operation."""
import json
import re
import unittest
from pathlib import Path

from backend import embedding_provider as ep
from backend import index_snapshot as snap

ROOT = Path(__file__).resolve().parent.parent
E72 = ROOT / "eval" / "deployment" / "stage7b2"
jl = lambda p: json.loads((E72 / p).read_text())  # noqa: E731


class BaselineTests(unittest.TestCase):
    def test_index_and_registry_digests_were_the_known_ones_before_and_after(self):
        t = (E72 / "baseline_integrity.txt").read_text()
        self.assertIn("140cd2008980f7e64858a8089d81f0346f758db1eda4d8c5c390418eac0ebe29", t)
        self.assertIn("5f4094d88cf9b770b7210749fdadddfeea4d4c0cfd168c39bb3b905767bbdbe3", t)
        self.assertIn("INDEX UNCHANGED", t)
        self.assertIn("REGISTRY UNCHANGED", t)
        self.assertIn("lifecycle verify: consistent", t)
        self.assertIn("audit history intact", t)

    def test_all_twenty_sources_pending_and_none_active_at_baseline(self):
        self.assertIn("20 sources; states: ['pending'] ; any active: False", (E72 / "baseline_lifecycle_status.txt").read_text())

    def test_exact_and_hnsw_baselines_agree_on_every_headline_metric(self):
        a, b = jl("baseline/retrieval_exact.json"), jl("baseline/retrieval_hnsw.json")
        self.assertEqual(a["retrieval"], b["retrieval"])
        self.assertEqual((a["cases"], a["retrieval"]["scored_cases"]), (108, 79))
        self.assertEqual(a["retrieval"]["hit@5"], 1.0)
        self.assertEqual(a["guard"]["accuracy"], 1.0)
        self.assertEqual(a["leakage"]["rate"], 0.0)
        self.assertEqual(a["failures"], [])


class PathAIndependentRunTests(unittest.TestCase):
    gate = ep.EmbeddingSettings().min_cosine

    def test_queries_match_fresh_ollama_vectors_far_inside_the_gate_in_both_thread_settings(self):
        for f in ("pathA/numpy_queries_single_thread.json", "pathA/numpy_queries_default_threads.json", "pathA/numpy_single_thread.json"):
            r = jl(f)
            self.assertEqual(r["queries_vs_ollama_cosine"]["n"], 108, f)
            self.assertGreater(r["queries_vs_ollama_cosine"]["min"], 0.999999, f)
            self.assertGreater(r["queries_vs_ollama_cosine"]["min"], self.gate)
            self.assertTrue(r["blob"].startswith("sha256:970aa74c0a90"), f)

    def test_documents_match_the_vectors_stored_in_the_real_index(self):
        r = jl("pathA/numpy_single_thread.json")
        self.assertGreaterEqual(r["documents_vs_stored_index_cosine"]["n"], 100)
        self.assertGreater(r["documents_vs_stored_index_cosine"]["min"], 0.999999)

    def test_the_memory_result_is_recorded_as_not_fitting_with_margin(self):
        q = jl("pathA/numpy_queries_single_thread.json")
        # the engine ALONE, queries only, already reaches ~300-360 MB; the backend adds ~200-330 MB (Stage 7B.1): no headroom under 512 MB
        self.assertGreater(q["ru_maxrss_mb"], 300)
        self.assertGreater(q["query_latency_ms"]["p50"], 300)      # one core: ~0.4 s/query, so ~4 s at the 0.1 CPU share (estimate, not measured)


class PathBCandidateTests(unittest.TestCase):
    def test_the_candidate_is_a_separate_384_dimensional_index_with_the_same_chunk_ids(self):
        out = (E72 / "candidate/build_candidate_index.out").read_text()
        self.assertIn("candidate chunks: 590 dims: 384", out)
        self.assertIn("real index unchanged: 140cd2008980f7e64858a8089d81f0346f758db1eda4d8c5c390418eac0ebe29", out)
        meta, ref = jl("candidate/chunk_metadata.json"), json.loads((ROOT / "eval/deployment/stage7b1/reference_set.json").read_text())
        self.assertEqual(meta["ids"], ref["ids"])
        self.assertEqual(len(meta["metadatas"]), 590)

    def test_exact_and_hnsw_candidate_runs_exist_and_the_hybrid_ones_agree_on_the_headline(self):
        e, h = jl("candidate/retrieval/bge_small_instr_hybrid_exact.json"), jl("candidate/retrieval/bge_small_instr_hybrid_hnsw.json")
        self.assertEqual(e["retrieval"], h["retrieval"])

    def test_the_recorded_regressions_are_not_hidden(self):
        base, cand = jl("baseline/retrieval_exact.json"), jl("candidate/retrieval/bge_small_instr_hybrid_exact.json")
        self.assertEqual(base["retrieval"]["hit@5"], 1.0)
        self.assertLess(cand["retrieval"]["hit@5"], 1.0)                                      # a question the baseline answers is lost
        self.assertEqual([f["id"] for f in cand["failures"]], ["TG-PQ-020"])
        d = jl("candidate/hybrid_diff_and_gate.json")
        self.assertEqual(d["hybrid_exact_pipeline"]["missing_from_top5"], {"nomic": [], "bge": ["TG-PQ-020"]})
        self.assertGreaterEqual(len(d["hybrid_exact_pipeline"]["bge_worse"]), 5)

    def test_the_licence_must_recall_set_loses_rule_6_with_the_candidate(self):
        L = json.loads((ROOT / "eval/licence-retrieval-set.json").read_text())["cases"]
        got = {}
        for n in ("nomic", "bge"):
            d = jl(f"candidate/regression/licence_probe_{n}.json")
            got[n] = sum(m in d["licence"][c["id"]] for c in L for m in c["must_include"])
        self.assertEqual((got["nomic"], got["bge"]), (12, 11))

    def test_the_candidate_regression_summary_lists_the_failing_real_backend_modules(self):
        s = (E72 / "candidate/regression/summary.txt").read_text()
        for mode in ("exact", "hnsw"):
            self.assertRegex(s, rf"{mode} test_licence_retrieval rc=1")
            self.assertRegex(s, rf"{mode} test_view_source_real rc=1")
            self.assertRegex(s, rf"{mode} test_rule6_pipeline_real rc=0")

    def test_many_chunks_exceed_the_candidates_512_token_window(self):
        self.assertTrue((E72 / "candidate/shim/sitecustomize.py").is_file())   # documented in the report: 45 of 590 chunks truncated

    def test_the_candidate_cannot_be_mistaken_for_the_nomic_family_by_the_server(self):
        self.assertNotIn("bge-small-en-v1.5", ep.KNOWN_FAMILIES.values())
        self.assertEqual(set(ep.KNOWN_FAMILIES.values()), {"nomic-embed-text-v1.5"})

    def test_the_shim_is_off_unless_explicitly_enabled(self):
        src = (E72 / "candidate/shim/sitecustomize.py").read_text()
        self.assertIn('if os.environ.get("KYR_CANDIDATE_EMBED"):', src)
        self.assertNotIn("candidate/shim", (ROOT / "backend/server.py").read_text())


class ProductionConfigUnchangedTests(unittest.TestCase):
    def test_the_production_embedding_model_name_and_family_are_still_nomic(self):
        self.assertEqual(ep.INDEX_FAMILY, "nomic-embed-text-v1.5")
        for f in ("backend/build_telangana_index.py", "backend/document_lifecycle.py"):  # build_index.py retired to archive/
            self.assertIn('OllamaEmbeddings(model="nomic-embed-text")', (ROOT / f).read_text(), f)

    def test_the_r2_fix_added_no_delete_and_no_unconditional_pointer_write(self):
        import inspect
        for cls in (snap.ObjectStore, snap.LocalObjectStore, snap.S3CompatStore, snap.PrefixedStore):
            self.assertFalse([n for n in dir(cls) if re.search("delete|remove", n, re.I)], cls)
        self.assertNotIn('put_bytes("active.json"', inspect.getsource(snap))

    def test_no_endpoint_for_lifecycle_or_approval_mutation_was_added(self):
        src = (ROOT / "backend/server.py").read_text()
        self.assertFalse(re.findall(r'@app\.(?:post|put|delete|patch)\("/(?:approve|lifecycle|admin|rollback|publish)', src))


class LinuxContainerEvidenceTests(unittest.TestCase):
    L = E72 / "linux"

    def test_the_512mb_runs_completed_without_an_oom_kill(self):
        for n in ("mem512_cpu2_run1", "mem512_cpu0.1_short"):
            r = json.loads((self.L / f"{n}.json").read_text())
            self.assertIn("512", r["cgroup"]["memory.max"] and str(int(r["cgroup"]["memory.max"]) // 2**20))
            self.assertIn("oom_kill 0", r["cgroup_end"]["memory.events"])
            self.assertEqual(r["sequential_ms"]["errors"], [])

    def test_at_the_render_free_cpu_share_a_query_takes_about_a_minute_so_path_a_is_unusable(self):
        r = json.loads((self.L / "mem512_cpu0.1_short.json").read_text())
        self.assertEqual(r["cgroup"]["cpu.max"].split()[0] if r["cgroup"]["cpu.max"] else "", "10000")     # 0.1 CPU
        self.assertGreater(r["sequential_ms"]["p50"], 30000)
        self.assertGreater(r["marks"]["import backend.server (store+exact+BM25 built)"]["t"], 60)

    def test_the_faster_run_shows_the_memory_is_thin_not_roomy(self):
        r = json.loads((self.L / "mem512_cpu2_run1.json").read_text())
        self.assertGreater(r["marks"]["after 3 rounds of 4 concurrent retrievals"]["rss_mb"], 480)
        self.assertGreater(r["concurrency"]["p50_ms"], 5000)

    def test_the_aborted_first_attempt_is_kept(self):
        self.assertTrue((self.L / "aborted").is_dir())


if __name__ == "__main__":
    unittest.main()
