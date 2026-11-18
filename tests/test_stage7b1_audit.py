"""Stage 7B.1: embedding architecture audit and the evidence behind the compatibility / feasibility conclusions. Offline: reads source
files and the raw evidence under eval/deployment/stage7b1/. No network, no Ollama, no accounts. The real index is not opened.
What is proven: how the index's vectors were made and how a query must be made to match them; that the recorded numerical-agreement
evidence meets the compatibility gate the server enforces; that a quantised variant which fails that gate would be rejected; that the
Stage 7B measurement evidence was preserved and the controlled re-run stored beside it; that the measurement script refuses to run
alongside another measurement process."""
import hashlib
import importlib.util
import json
import re
import unittest
from pathlib import Path

from backend import embedding_provider as ep
from backend import rag_profiles as rp

ROOT = Path(__file__).resolve().parent.parent
E7B = ROOT / "eval" / "deployment" / "stage7b"
E71 = ROOT / "eval" / "deployment" / "stage7b1"


def jload(p):
    return json.loads(Path(p).read_text())


class Recorder:
    """Stands in for the base embedder; remembers exactly which strings reach the model."""

    def __init__(self):
        self.seen = []

    def embed_documents(self, texts):
        self.seen += list(texts)
        return [[0.0] for _ in texts]

    def embed_query(self, text):
        self.seen.append(text)
        return [0.0]


class EmbeddingConventionTests(unittest.TestCase):
    def test_the_index_is_built_by_the_structured_profile_with_nomic_task_prefixes(self):
        p = rp.PROFILES[rp.DEFAULT_BUILD_PROFILE]
        self.assertEqual((p.name, p.doc_prefix, p.query_prefix), ("structured", "search_document: ", "search_query: "))

    def test_documents_and_queries_reach_the_model_with_different_task_prefixes(self):
        rec = Recorder()
        pe = rp.ProfileEmbeddings(rec, rp.PROFILES["structured"])
        pe.embed_documents(["Rule 1"])
        pe.embed_query("Rule 1")
        self.assertEqual(rec.seen, ["search_document: Rule 1", "search_query: Rule 1"])

    def test_the_baseline_profile_adds_no_prefix_and_so_is_a_different_space(self):
        rec = Recorder()
        pe = rp.ProfileEmbeddings(rec, rp.PROFILES["baseline"])
        pe.embed_query("x")
        self.assertEqual(rec.seen, ["x"])

    def test_every_build_path_uses_the_one_local_model_name(self):
        for f, n in (("backend/build_telangana_index.py", 1), ("backend/document_lifecycle.py", 1)):  # build_index.py retired to archive/
            src = (ROOT / f).read_text()
            self.assertEqual(len(re.findall(r'OllamaEmbeddings\(model="nomic-embed-text"\)', src)), n, f)

    def test_the_known_families_name_one_model_and_nothing_else_is_assumed_compatible(self):
        self.assertEqual(set(ep.KNOWN_FAMILIES.values()), {ep.INDEX_FAMILY})
        self.assertEqual(ep.INDEX_FAMILY, "nomic-embed-text-v1.5")
        self.assertNotIn((ep.PROVIDER_ATLAS, "bge-base-en-v1.5"), ep.KNOWN_FAMILIES)   # same 768 dimensions, different space

    def test_the_server_embeds_queries_through_the_index_profile_and_the_guard_never_through_chroma(self):
        src = (ROOT / "backend/server.py").read_text()
        self.assertIn("embeddings_model = rag_profiles.ProfileEmbeddings(EMBEDDING)", src)
        self.assertIn("embeddings_model.profile = INDEX_PROFILE", src)


class IndexFactsTests(unittest.TestCase):
    info = jload(E71 / "reference_set_info.json")

    def test_the_stored_vectors_are_768_dimensional_unit_length_and_l2(self):
        i = self.info
        self.assertEqual((i["chunks"], i["dims"]), (590, 768))
        self.assertAlmostEqual(i["norm_min"], 1.0, places=5)
        self.assertAlmostEqual(i["norm_max"], 1.0, places=5)
        self.assertIn("'space': 'l2'", i["collection_configuration"])

    def test_reading_the_reference_set_did_not_change_the_real_index(self):
        i = self.info
        self.assertTrue(i["index_unchanged"])
        self.assertEqual(i["index_digest_before"], i["index_digest_after"])
        self.assertEqual(i["index_digest_after"], "140cd2008980f7e64858a8089d81f0346f758db1eda4d8c5c390418eac0ebe29")

    def test_the_longest_chunk_fits_the_models_context(self):
        self.assertLess(self.info["chunk_chars_max"], 8000)


class NumericalCompatibilityEvidenceTests(unittest.TestCase):
    r = jload(E71 / "compare_ollama_result.json")
    gate = ep.EmbeddingSettings().min_cosine

    def test_todays_ollama_reproduces_every_stored_vector(self):
        self.assertGreaterEqual(self.r["ollama_vs_stored_docs_cosine"]["min"], 0.99999)

    def test_the_reimplementation_from_the_same_weights_matches_ollama_far_inside_the_gate(self):
        v = self.r["variants"]["mean_pool_l2 (llama.cpp/Ollama behaviour)"]
        for k in ("docs_vs_ollama_cosine", "queries_vs_ollama_cosine", "docs_vs_stored_cosine"):
            self.assertGreaterEqual(v[k]["min"], 0.999999, k)
            self.assertGreater(v[k]["min"], self.gate)
        self.assertEqual((self.r["n_docs"], self.r["n_questions"]), (590, 108))

    def test_the_published_layernorm_recipe_also_passes_the_gate_and_does_not_move_retrieval(self):
        v = self.r["variants"]["layernorm_then_l2 (published ST recipe)"]
        self.assertGreater(v["queries_vs_ollama_cosine"]["min"], 0.9999)
        self.assertEqual(self.r["retrieval"]["layernorm_then_l2"]["top1_same"], 1.0)

    def test_retrieval_is_identical_at_rank_one_and_in_the_top_ten(self):
        for name, x in self.r["retrieval"].items():
            self.assertEqual(x["top1_same"], 1.0, name)
            self.assertEqual(x["top10_set_same"], 1.0, name)
            self.assertGreaterEqual(x["top5_set_same"], 0.98, name)

    def test_the_tokenizer_agrees_with_ollama_on_every_sampled_text(self):
        t = self.r["token_count_check"]
        self.assertEqual((t["texts"], t["mismatches"]), (226, 0))

    def test_the_first_run_that_exposed_a_tokenizer_bug_is_kept_and_not_used_as_evidence(self):
        first = jload(E71 / "compare_ollama_result_FIRST_RUN_tokenizer_bug.json")
        self.assertLess(first["variants"]["mean_pool_l2 (llama.cpp/Ollama behaviour)"]["docs_vs_ollama_cosine"]["mean"], 0.5)
        self.assertGreater(first["token_count_check"]["mismatches"], 100)


class RuntimeCandidateEvidenceTests(unittest.TestCase):
    runs = {n: jload(E71 / "onnx_runs" / f"{n}.json") for n in ("fp32", "int8", "numpy_f16_gguf")}
    gate = ep.EmbeddingSettings().min_cosine

    def test_exact_precision_runtimes_pass_the_gate_and_the_int8_quantisation_fails_it(self):
        self.assertGreater(self.runs["fp32"]["queries_vs_ollama_cosine"]["min"], self.gate)
        self.assertGreater(self.runs["numpy_f16_gguf"]["queries_vs_ollama_cosine"]["min"], self.gate)
        self.assertLess(self.runs["int8"]["queries_vs_ollama_cosine"]["min"], self.gate)
        self.assertLess(self.runs["int8"]["retrieval_vs_ollama"]["top5_set_same"], 0.9)

    def test_the_int8_cosine_would_be_refused_by_the_servers_own_probe_check(self):
        cos = self.runs["int8"]["queries_vs_ollama_cosine"]["min"]
        self.assertLess(cos, self.gate)          # GuardedEmbeddings.verify() requires every probe cosine >= min_cosine

    def test_no_runtime_fits_in_512_mb_alone_with_the_backend_except_by_estimate(self):
        # fp32 and int8 ONNX need more than the 512 MB plan on their own once loaded; the numpy variant is the only one under it alone.
        self.assertGreater(self.runs["fp32"]["ru_maxrss_mb"], 512)
        self.assertGreater(self.runs["int8"]["rss_mb"]["after longest input"], 400)
        self.assertLess(self.runs["numpy_f16_gguf"]["rss_mb"]["after 108 single queries"], 512)


class MeasurementEvidenceTests(unittest.TestCase):
    def test_the_original_stage_7b_measurements_were_not_overwritten(self):
        recorded = dict(line.split("  ", 1)[::-1] for line in (E71 / "original_7b_evidence.sha256").read_text().splitlines())
        for rel in ("eval/deployment/stage7b/measurements.json", "eval/deployment/stage7b/measure.out"):
            digest = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
            self.assertEqual(digest, recorded[rel], rel)

    def test_the_controlled_rerun_is_stored_separately(self):
        c = E71 / "controlled" / "measurements_controlled.json"
        self.assertTrue(c.exists())
        self.assertNotEqual(c.resolve(), (E7B / "measurements.json").resolve())
        d = jload(c)
        self.assertTrue(d["real_index_and_registry_unchanged"])
        self.assertEqual(d["real_index_tree_digest"], "140cd2008980f7e64858a8089d81f0346f758db1eda4d8c5c390418eac0ebe29")
        for cfg in ("full_environment", "cloud_requirements"):
            self.assertEqual(len(d["server_runs"][cfg]), 3, cfg)
            self.assertTrue(d["server_runs"][cfg][0]["cold_start"])

    def test_the_controlled_run_recorded_that_nothing_else_was_measuring(self):
        d = jload(E71 / "controlled" / "measurements_controlled.json")
        self.assertIn("no other measure/test/uvicorn process", d["machine"]["single_session_precheck"])

    def test_the_stage_7b_report_discloses_the_overlap_and_names_the_shared_files(self):
        t = (ROOT / "eval/deployment/STAGE-7B-REPORT.md").read_text()
        self.assertIn("Measurement caveat", t)
        for needle in ("measurements.json", "measure.out", "STAGE-7B-REPORT.md", "provisional"):
            self.assertIn(needle, t)


class MeasurementGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("measure_controlled", E71 / "measure_controlled.py")
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def test_it_writes_only_beside_the_controlled_directory(self):
        src = (E71 / "measure_controlled.py").read_text()
        self.assertIn('OUTDIR / "measurements_controlled.json"', src)
        self.assertNotIn('HERE / "measurements.json"', src)
        self.assertEqual(self.mod.OUTDIR, E71 / "controlled")

    def test_it_refuses_to_start_while_another_measurement_or_test_process_runs(self):
        class P:
            def __init__(self, pid, name, cmd):
                self.info = {"pid": pid, "name": name, "cmdline": cmd}
        fake = [P(1, "Python", ["python3", "eval/deployment/stage7b/measure.py"]), P(2, "zsh", ["zsh", "-c", "measure_controlled"]),
                P(3, "python3", ["python3", "-m", "unittest", "discover"])]
        orig = self.mod.psutil.process_iter
        self.mod.psutil.process_iter = lambda attrs=None: iter(fake)
        try:
            busy = self.mod.other_workers()
        finally:
            self.mod.psutil.process_iter = orig
        self.assertEqual(len(busy), 2)           # the two python processes; a shell that merely mentions the script does not count

    def test_the_real_index_and_registry_are_digested_before_and_after_and_only_copies_are_used(self):
        src = (E71 / "measure_controlled.py").read_text()
        self.assertIn("before = (dl.tree_digest(INDEX), dl.tree_digest(REGISTRY))", src)
        self.assertIn("shutil.copytree(INDEX, idx)", src)
        self.assertIn("shutil.copytree(REGISTRY, st)", src)


if __name__ == "__main__":
    unittest.main()
