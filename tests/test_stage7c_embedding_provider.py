"""Stage 7C (D2), part 2: the `inprocess_nomic` provider: configuration, fail-closed identity checks, the unchanged compatibility gate,
single model load, prefixes, and the other providers. Offline: a tiny synthetic engine (tests/gguf_fixture.py); no real model, no
Ollama, no network. Agreement with the REAL model is in test_stage7c_nomic_real.py."""
import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import gguf_fixture as gf
from backend import embedding_provider as ep
from backend import nomic_local as nl
from backend import rag_profiles as rp

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_cloud_env_7c2", ROOT / "scripts" / "check_cloud_env.py")
cce = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cce)


def tiny_factory(calls=None):
    def factory(path, sha):
        if calls is not None:
            calls.append(path)
        return nl.NomicEngine(path, sha, spec=gf.TINY)
    return factory


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        cls.model = gf.write(d / "tiny.gguf", seed=1)
        cls.other = gf.write(d / "other.gguf", seed=2)         # same identity, different weights: a different vector space
        cls.sha = hashlib.sha256(cls.model.read_bytes()).hexdigest()
        cls.other_sha = hashlib.sha256(cls.other.read_bytes()).hexdigest()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def env(self, **kw):
        e = {"EMBEDDING_PROVIDER": "inprocess_nomic", "EMBEDDING_MODEL_FILE": str(self.model), "EMBEDDING_MODEL_SHA256": self.sha}
        e.update(kw)
        return {k: v for k, v in e.items() if v is not None}

    def guard(self, env=None, factory=None):
        return ep.build_embeddings(ep.EmbeddingSettings.from_env(env or self.env()), engine_factory=factory or tiny_factory())

    def probes(self, model_path=None, sha=None):
        eng = nl.NomicEngine(model_path or self.model, sha or self.sha, spec=gf.TINY)
        texts = ["search_document: " + t for t in ep.PROBE_TEXTS]
        return [{"input": t, "vector": [float(x) for x in v]} for t, v in zip(texts, eng.embed(texts))]


class ConfigurationTests(Base):
    def test_the_valid_configuration_is_accepted(self):
        s = ep.EmbeddingSettings.from_env(self.env())
        self.assertEqual((s.provider, s.problems, s.model, s.family, s.in_process, s.hosted), ("inprocess_nomic", (), "nomic-embed-text-v1.5", ep.INDEX_FAMILY, True, False))
        self.assertTrue(s.verification_required)                                   # verified against the snapshot's probes, like a hosted provider
        self.assertEqual(s.timeout_seconds, 60.0)

    def test_it_is_a_known_provider_and_the_other_providers_are_unchanged(self):
        self.assertEqual(ep.PROVIDERS, ("ollama", "openai_compatible", "nomic_atlas", "inprocess_nomic"))
        self.assertEqual(ep.HOSTED_PROVIDERS, ("openai_compatible", "nomic_atlas"))
        self.assertEqual(ep.EmbeddingSettings.from_env({}).provider, "ollama")
        self.assertEqual(ep.EmbeddingSettings.from_env({}).problems, ())
        hosted = ep.EmbeddingSettings.from_env({"EMBEDDING_PROVIDER": "nomic_atlas", "EMBEDDING_MODEL": "nomic-embed-text-v1.5", "EMBEDDING_API_KEY": "k"})
        self.assertEqual((hosted.problems, hosted.hosted, hosted.in_process), ((), True, False))

    def test_invalid_provider_names_fail(self):
        for bad in ("inprocess", "local", "nomic", "in_process_nomic", "inprocess_nomic ; ollama", "INPROCESS-NOMIC", "gguf"):
            s = ep.EmbeddingSettings.from_env({"EMBEDDING_PROVIDER": bad})
            self.assertTrue(s.problems, bad)
            self.assertEqual(s.provider, "invalid", bad)
            self.assertEqual(ep.build_embeddings(s).state, "misconfigured", bad)

    def test_a_missing_or_unset_model_file_is_a_clear_startup_error(self):
        s = ep.EmbeddingSettings.from_env(self.env(EMBEDDING_MODEL_FILE=None))
        self.assertTrue(any("EMBEDDING_MODEL_FILE is required" in p for p in s.problems))
        s = ep.EmbeddingSettings.from_env(self.env(EMBEDDING_MODEL_FILE="/no/such/model.gguf"))
        self.assertTrue(any("does not name an existing file" in p for p in s.problems))
        self.assertNotIn("/no/such", " ".join(s.problems))                          # the path is never echoed
        self.assertEqual(ep.build_embeddings(s).state, "misconfigured")

    def test_the_pin_is_mandatory_in_the_cloud_and_must_be_hex(self):
        cloud = {"TG_SNAPSHOT_STORE": "r2"}
        s = ep.EmbeddingSettings.from_env(self.env(EMBEDDING_MODEL_SHA256=None, **cloud))
        self.assertTrue(any("EMBEDDING_MODEL_SHA256 is required" in p for p in s.problems))
        for bad in ("xyz", "ab" * 31, "g" * 64):
            self.assertTrue(any("64 hex" in p for p in ep.EmbeddingSettings.from_env(self.env(EMBEDDING_MODEL_SHA256=bad)).problems), bad)
        self.assertEqual(ep.EmbeddingSettings.from_env(self.env(EMBEDDING_MODEL_SHA256=None)).problems, ())    # development: the metadata identity still applies

    def test_a_wrong_model_identity_is_refused(self):
        for bad in ("bge-small-en-v1.5", "nomic-embed-text", "nomic-embed-text:latest", "nomic-embed-text-v2"):
            s = ep.EmbeddingSettings.from_env(self.env(EMBEDDING_MODEL=bad))
            self.assertTrue(any("EMBEDDING_MODEL must be" in p for p in s.problems), bad)
        self.assertEqual(ep.EmbeddingSettings.from_env(self.env(EMBEDDING_MODEL="nomic-embed-text-v1.5")).problems, ())

    def test_the_cloud_never_defaults_to_ollama_and_inprocess_is_allowed_there(self):
        self.assertTrue(ep.EmbeddingSettings.from_env({"TG_SNAPSHOT_STORE": "r2"}).problems)
        self.assertTrue(ep.EmbeddingSettings.from_env({"TG_SNAPSHOT_STORE": "r2", "EMBEDDING_PROVIDER": "ollama"}).problems)
        self.assertEqual(ep.EmbeddingSettings.from_env(self.env(TG_SNAPSHOT_STORE="r2")).problems, ())

    def test_the_describe_output_has_no_path_and_no_digest(self):
        d = ep.EmbeddingSettings.from_env(self.env()).describe()
        self.assertTrue(d["in_process"] and d["model_file_set"] and d["model_sha256_pinned"])
        self.assertNotIn(str(self.model), repr(d))
        self.assertNotIn(self.sha, repr(d))

    def test_the_cosine_floor_is_clamped_and_the_default_gate_is_unchanged(self):
        self.assertEqual(ep.EmbeddingSettings.from_env(self.env()).min_cosine, 0.995)
        for low in ("0.5", "0.97", "0.0"):
            self.assertEqual(ep.EmbeddingSettings.from_env(self.env(EMBEDDING_MIN_COSINE=low)).min_cosine, 0.98, low)     # the pre-existing hard floor
        self.assertEqual(ep.EmbeddingSettings.from_env(self.env(EMBEDDING_MIN_COSINE="0.999")).min_cosine, 0.999)         # raising it is allowed


class ModelLoadTests(Base):
    def test_the_model_is_loaded_once_per_process_not_per_request(self):
        calls = []
        g = self.guard(factory=tiny_factory(calls))
        g.configure_index(dims=16, family=ep.INDEX_FAMILY, probes=self.probes(), min_cosine=0.995)
        for i in range(6):
            g.embed_query(f"search_query: question {i}")
        g.verify()
        g.embed_documents(["search_document: a", "search_document: b"])
        self.assertEqual(len(calls), 1)

    def test_a_missing_wrong_or_corrupt_file_leaves_the_provider_misconfigured_and_nothing_is_substituted(self):
        d = Path(self.tmp.name)
        junk = d / "junk.gguf"
        junk.write_bytes(b"x" * 100)
        cases = {"missing": self.env(EMBEDDING_MODEL_FILE=str(d / "gone.gguf")), "junk": self.env(EMBEDDING_MODEL_FILE=str(junk), EMBEDDING_MODEL_SHA256=None),
                 "wrong pin": self.env(EMBEDDING_MODEL_SHA256="0" * 64)}
        for name, env in cases.items():
            with mock.patch.object(ep, "OllamaBackend", side_effect=AssertionError("must never fall back to ollama")):
                g = ep.build_embeddings(ep.EmbeddingSettings.from_env(env), engine_factory=tiny_factory())
            self.assertEqual(g.state, "misconfigured", name)
            self.assertFalse(g.ready(), name)
            with self.assertRaises(ep.EmbeddingUnavailable) as cm:
                g.embed_query("search_query: x")
            self.assertEqual(cm.exception.reason, ep.NOT_CONFIGURED, name)
            self.assertNotIn(str(d), repr(g.health()), name)

    def test_the_production_engine_refuses_the_tiny_fixture_as_not_being_the_model(self):
        g = ep.build_embeddings(ep.EmbeddingSettings.from_env(self.env()))        # default factory = the real production spec
        self.assertEqual(g.state, "misconfigured")
        self.assertTrue(any("not nomic-embed-text-v1.5" in p for p in g.health()["problems"]))

    def test_a_load_failure_is_visible_in_health_without_a_path(self):
        g = ep.build_embeddings(ep.EmbeddingSettings.from_env(self.env(EMBEDDING_MODEL_SHA256="0" * 64)), engine_factory=tiny_factory())
        h = g.health()
        self.assertFalse(h["ready"])
        self.assertTrue(any("pinned SHA-256" in p for p in h["problems"]))


class CompatibilityGateTests(Base):
    def test_the_probe_check_passes_for_the_model_that_made_the_probes(self):
        g = self.guard()
        g.configure_index(dims=16, family=ep.INDEX_FAMILY, probes=self.probes(), min_cosine=0.995)
        self.assertEqual(g.state, "unverified")
        g.verify()
        self.assertEqual(g.state, "ok")
        self.assertGreater(g._verify_report["min_cosine_observed"], 0.99999)

    def test_a_model_of_the_right_name_but_different_weights_is_incompatible_and_refused(self):
        g = self.guard(self.env(EMBEDDING_MODEL_FILE=str(self.other), EMBEDDING_MODEL_SHA256=self.other_sha))
        g.configure_index(dims=16, family=ep.INDEX_FAMILY, probes=self.probes(), min_cosine=0.995)
        with self.assertRaises(ep.EmbeddingIncompatible):
            g.verify()
        self.assertEqual(g.state, "incompatible")
        with self.assertRaises(ep.EmbeddingIncompatible):
            g.embed_query("search_query: x")                                        # permanently refused for this process

    def test_the_first_real_query_triggers_verification_and_an_unverified_provider_does_not_answer_around_it(self):
        g = self.guard()
        g.configure_index(dims=16, family=ep.INDEX_FAMILY, probes=self.probes(self.other, self.other_sha), min_cosine=0.995)
        with self.assertRaises(ep.EmbeddingIncompatible):
            g.embed_query("search_query: x")
        self.assertFalse(g.ready())

    def test_without_probes_it_cannot_be_verified_and_is_not_ready(self):
        g = self.guard()
        g.configure_index(dims=16, family=ep.INDEX_FAMILY, probes=[], min_cosine=0.995)
        with self.assertRaises(ep.EmbeddingUnavailable):
            g.embed_query("search_query: x")
        self.assertFalse(g.ready())
        self.assertTrue(any("no embedding probes" in p for p in g.health()["problems"]))

    def test_the_manifest_cannot_lower_the_floor(self):
        g = self.guard()
        g.configure_index(dims=16, family=ep.INDEX_FAMILY, probes=self.probes(), min_cosine=0.5)
        self.assertEqual(g.min_cosine, 0.995)

    def test_wrong_dimensions_fail_closed(self):
        g = self.guard()
        g.configure_index(dims=768, family=ep.INDEX_FAMILY, probes=self.probes(), min_cosine=0.995)   # the index holds 768; this engine returns 16
        with self.assertRaises(ep.EmbeddingIncompatible) as cm:
            g.embed_query("search_query: x")
        self.assertEqual(cm.exception.reason, ep.DIMENSION_MISMATCH)
        self.assertEqual(g.state, "incompatible")
        s = ep.EmbeddingSettings.from_env(self.env(EMBEDDING_DIMENSIONS="384"))
        g2 = ep.build_embeddings(s, engine_factory=tiny_factory())
        g2.configure_index(dims=768, family=ep.INDEX_FAMILY)
        self.assertEqual(g2.state, "incompatible")                                  # configured size contradicts the index

    def test_an_index_of_another_family_is_refused(self):
        g = self.guard()
        g.configure_index(dims=16, family="bge-small-en-v1.5", probes=self.probes(), min_cosine=0.995)
        self.assertEqual(g.state, "incompatible")

    def test_vectors_that_are_not_unit_length_are_refused(self):
        class Bad:
            dimensions = 16

            def embed(self, texts):
                import numpy as np
                return np.ones((len(texts), 16), dtype=np.float32)
        g = ep.build_embeddings(ep.EmbeddingSettings.from_env(self.env(EMBEDDING_VERIFY="off")), engine_factory=lambda p, s: Bad())
        g.configure_index(dims=16, family=ep.INDEX_FAMILY)
        with self.assertRaises(ep.EmbeddingIncompatible) as cm:
            g.embed_query("search_query: x")
        self.assertEqual(cm.exception.reason, ep.NOT_NORMALIZED)


class PrefixTests(Base):
    def test_the_profile_adds_the_nomic_task_prefixes_before_the_engine_sees_the_text(self):
        seen = []

        class Spy:
            def embed(self, texts):
                import numpy as np
                seen.extend(texts)
                return np.tile(np.eye(1, 16, dtype=np.float32), (len(texts), 1))
        g = ep.build_embeddings(ep.EmbeddingSettings.from_env(self.env(EMBEDDING_VERIFY="off")), engine_factory=lambda p, s: Spy())
        g.configure_index(dims=16, family=ep.INDEX_FAMILY)
        pe = rp.ProfileEmbeddings(g, rp.PROFILES["structured"])
        pe.embed_query("Rule 6")
        pe.embed_documents(["Rule 6 text"])
        self.assertEqual(seen, ["search_query: Rule 6", "search_document: Rule 6 text"])

    def test_text_without_a_task_prefix_is_refused_not_embedded_into_a_third_space(self):
        g = self.guard()
        g.configure_index(dims=16, family=ep.INDEX_FAMILY, probes=self.probes(), min_cosine=0.995)
        with self.assertRaises(ep.EmbeddingUnavailable):
            g.embed_query("Rule 6 without a prefix")

    def test_query_and_document_vectors_differ(self):
        g = self.guard()
        g.configure_index(dims=16, family=ep.INDEX_FAMILY, probes=self.probes(), min_cosine=0.995)
        q, d = g.embed_query("search_query: hello"), g.embed_documents(["search_document: hello"])[0]
        self.assertLess(ep.cosine(q, d), 0.9999)


class CloudCheckerTests(Base):
    CLOUD = {"TG_ENVIRONMENT": "production", "TG_GROUNDED_ANSWERS": "1", "OLLAMA_ENABLED": "false", "TG_SNAPSHOT_STORE": "r2", "R2_ACCOUNT_ID": "a", "R2_BUCKET": "b",
             "R2_ACCESS_KEY_ID": "k", "R2_SECRET_ACCESS_KEY": "s", "TG_CORS_ORIGINS": "https://someone.github.io", "TG_SNAPSHOT_PIN_SHA256": "ab" * 32,
             "GROQ_API_KEY": "fakefakefake"}

    def check(self, **kw):
        r = cce.check({**self.CLOUD, **self.env(**kw)})
        return {e["name"] for e in r["errors"]}, r

    def test_the_checker_accepts_a_valid_inprocess_configuration(self):
        names, r = self.check()
        self.assertEqual(names, set())
        self.assertTrue(r["ok"])
        self.assertTrue(r["embedding"]["in_process"])
        self.assertNotIn(str(self.model), repr(r))

    def test_the_checker_rejects_each_broken_inprocess_setting(self):
        for change in ({"EMBEDDING_MODEL_FILE": None}, {"EMBEDDING_MODEL_FILE": "/no/such"}, {"EMBEDDING_MODEL_SHA256": None}, {"EMBEDDING_MODEL_SHA256": "zz"},
                       {"EMBEDDING_MODEL": "bge-small-en-v1.5"}):
            self.assertIn("EMBEDDING_*", self.check(**change)[0], change)

    def test_the_checker_still_rejects_ollama_and_an_unset_provider(self):
        self.assertIn("EMBEDDING_*", self.check(EMBEDDING_PROVIDER="ollama")[0])
        self.assertIn("EMBEDDING_*", self.check(EMBEDDING_PROVIDER=None)[0])
        self.assertIn("EMBEDDING_*", self.check(EMBEDDING_PROVIDER="inprocess")[0])

    def test_the_gate_cannot_be_lowered_in_a_cloud_deployment(self):
        for low in ("0.98", "0.9", "0", "abc", "0.9949"):
            self.assertIn("EMBEDDING_MIN_COSINE", self.check(EMBEDDING_MIN_COSINE=low)[0], low)
        for ok in ("0.995", "0.999", "1"):
            self.assertNotIn("EMBEDDING_MIN_COSINE", self.check(EMBEDDING_MIN_COSINE=ok)[0], ok)

    def test_verification_cannot_be_switched_off_in_the_cloud(self):
        self.assertIn("EMBEDDING_VERIFY", self.check(EMBEDDING_VERIFY="off")[0])


class DeploymentShapeTests(unittest.TestCase):
    def test_the_blueprint_runs_exactly_one_worker_so_the_model_is_never_duplicated(self):
        import yaml
        svc = yaml.safe_load((ROOT / "deploy" / "render.yaml").read_text())["services"][0]
        self.assertRegex(svc["startCommand"], r"--workers 1\b")
        self.assertNotRegex(svc["startCommand"], r"--workers [2-9]|WEB_CONCURRENCY|gunicorn")
        keys = {e["key"] for e in svc["envVars"]}
        self.assertTrue({"EMBEDDING_MODEL_FILE", "EMBEDDING_MODEL_SHA256"} <= keys)
        self.assertTrue(all(e.get("sync") is False for e in svc["envVars"] if e["key"] in ("EMBEDDING_MODEL_FILE", "EMBEDDING_MODEL_SHA256")))

    def test_the_engine_is_constructed_in_one_place_at_import(self):
        src = (ROOT / "backend" / "server.py").read_text()
        self.assertEqual(src.count("build_embeddings("), 1)
        import re
        self.assertEqual(len(re.findall(r"InProcessBackend\(", (ROOT / "backend" / "embedding_provider.py").read_text())), 1)   # one construction site

    def test_tokenizers_is_pinned_for_the_engine(self):
        self.assertRegex((ROOT / "requirements-cloud.txt").read_text(), r"(?m)^tokenizers==0\.23\.2$")


if __name__ == "__main__":
    unittest.main()
