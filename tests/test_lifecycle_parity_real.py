"""Stage 6B: enrolling the index must not change what production retrieval returns, and quarantined or unmatched documents
must never be retrieved once the registry is in force. Real backend on a temporary COPY of a real index, exact and hnsw,
the 108-question retrieval benchmark. Approval evidence is a throwaway-key synthetic fixture (never a real approval)."""
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


def real_embeddings():
    from langchain_ollama import OllamaEmbeddings

    from backend import build_telangana_index as btx
    from backend import rag_profiles as rp
    return rp.ProfileEmbeddings(OllamaEmbeddings(model="nomic-embed-text"), btx.PROFILE)


@unittest.skipUnless(os.environ.get("KYR_REAL_INDEX_DIR") or REQUIRED, "real backend not configured")
class RealParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reason = missing()
        if reason and REQUIRED:
            raise AssertionError(f"real backend test required but cannot run: {reason}")
        if reason:
            raise unittest.SkipTest(reason)
        cls.tmp = Path(tempfile.mkdtemp(prefix="kyr-parity-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.runs, cls.shas, cls.plans = {}, [], {}
        for mode in ("exact", "hnsw"):
            base = cls.tmp / mode
            shutil.copytree(INDEX_DIR, base / "index")
            db = base / "index"
            before = dl.tree_digest(db)
            metas = chromadb.PersistentClient(path=str(shutil.copytree(db, base / "peek"))).get_collection(
                "telangana-traffic-rules", embedding_function=None).get(include=["metadatas"])["metadatas"]
            shas = sorted({m["sha256"] for m in metas})
            cls.shas = shas
            subset = set(shas[:10])
            scenarios = {"off": None}
            for name, only in (("all", None), ("subset", subset), ("none", "none")):
                state = base / f"state-{name}"
                lc = dl.Lifecycle(state, db, embeddings=real_embeddings())
                if only == "none":
                    res = lc.bootstrap("parity-test", None, allow_quarantine=True)
                else:
                    sf = status_file_for(base / f"status-{name}", metas, only)
                    res = lc.bootstrap("parity-test", BASIS, source_status_file=sf, allow_quarantine=True)
                cls.plans[(mode, name)] = res
                scenarios[name] = state
            assert dl.tree_digest(db) == before, "bootstrap modified the index"
            cls.runs[mode] = {}
            for name, state in scenarios.items():
                env = {k: v for k, v in os.environ.items() if not k.startswith(("TG_", "GROQ_", "GEMINI_", "PROVIDER_", "RAG_"))}
                env.update(TG_DB_DIR=str(db), RAG_VECTOR_SEARCH=mode, GROQ_API_KEY="offline-probe-not-real",
                           ANONYMIZED_TELEMETRY="False")
                if state is not None:
                    env["TG_LIFECYCLE_DIR"] = str(state)
                run = subprocess.run([sys.executable, str(ROOT / "tests" / "lifecycle_parity_probe.py")], cwd=ROOT, env=env,
                                     capture_output=True, text=True, timeout=900)
                if run.returncode != 0:
                    raise AssertionError(f"probe ({mode}, {name}) failed:\n" + run.stderr[-3000:])
                cls.runs[mode][name] = json.loads(run.stdout.strip().splitlines()[-1])
            cls.subset = subset

    def each(self):
        for mode, runs in self.runs.items():
            with self.subTest(mode=mode):
                yield runs

    def test_every_source_is_accounted_for(self):
        for mode in self.runs:
            self.assertEqual((self.plans[(mode, "all")]["verified"], self.plans[(mode, "all")]["quarantined"]), (20, 0))
            self.assertEqual((self.plans[(mode, "subset")]["verified"], self.plans[(mode, "subset")]["quarantined"]), (10, 10))
            self.assertEqual((self.plans[(mode, "none")]["verified"], self.plans[(mode, "none")]["quarantined"]), (0, 20))

    def test_lifecycle_flag_state(self):
        for runs in self.each():
            self.assertFalse(runs["off"]["lifecycle_enabled"])
            self.assertTrue(all(runs[n]["lifecycle_enabled"] for n in ("all", "subset", "none")))

    def test_enrolling_with_full_evidence_returns_exactly_the_same_results_as_before(self):
        for runs in self.each():
            self.assertEqual(len(runs["all"]["filtered"]), 108)
            self.assertEqual(runs["all"]["filtered"], runs["all"]["unfiltered"])      # same process, same open store
            self.assertTrue(any(runs["all"]["filtered"].values()))
            self.assertEqual(runs["off"]["filtered"], runs["off"]["unfiltered"])        # no registry configured: no effect

    def test_unmatched_documents_never_enter_retrieval(self):
        for runs in self.each():
            seen = {sha for r in runs["subset"]["filtered"].values() for _, sha in r}
            self.assertTrue(seen)
            self.assertTrue(seen <= self.subset, "a quarantined document was retrieved")
            self.assertTrue(seen < {sha for r in runs["subset"]["unfiltered"].values() for _, sha in r})

    def test_a_registry_with_nothing_verified_serves_nothing(self):
        for runs in self.each():
            self.assertTrue(any(runs["none"]["unfiltered"].values()))
            self.assertTrue(all(not r for r in runs["none"]["filtered"].values()))


if __name__ == "__main__":
    unittest.main()
