"""Offline tests for backend/build_index.py.

Every test uses a fresh temporary Chroma directory, a fake PDF loader and deterministic fake
embeddings - no Ollama, no PDFs, no network, and the real index is never opened. Run from the
project root:
    python -m unittest discover -s tests -v
"""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chromadb  # noqa: E402
from chromadb.api.client import SharedSystemClient  # noqa: E402
from langchain_chroma import Chroma  # noqa: E402
from langchain_core.documents import Document  # noqa: E402
from langchain_core.embeddings import DeterministicFakeEmbedding  # noqa: E402

import backend.build_index as bi  # noqa: E402

LONG_TEXT = "Section 1. Every driver shall carry a licence. " * 80  # ~3,800 chars -> several chunks


class FakeLoader:
    def __init__(self, path, **kwargs):
        self.path = path

    def load(self):
        text = Path(self.path).read_text()
        if text == "RAISE":
            raise ValueError("corrupt pdf")
        return [Document(page_content=text, metadata={"source": self.path})]


class FailingEmbeddings(DeterministicFakeEmbedding):
    def embed_documents(self, texts):
        raise ConnectionError("embedding server unreachable")


class BuildIndexTests(unittest.TestCase):
    def setUp(self):
        # Every patch and temp dir is undone by addCleanup, even if setUp fails part-way.
        for patcher in (mock.patch.dict(os.environ, {"ANONYMIZED_TELEMETRY": "False"}),
                        mock.patch.object(bi, "RETRY_DELAY", 0)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(SharedSystemClient.clear_system_cache)
        root = Path(self.tmp.name)
        self.corpus, self.db = root / "corpus", root / "db"
        (self.corpus / "state").mkdir(parents=True)
        self.write("state/central.pdf", LONG_TEXT)
        self.write("state/delhi.pdf", LONG_TEXT.replace("Section", "Rule"))
        self.files = [("state/central.pdf", "Central"), ("state/delhi.pdf", "Delhi")]
        self.client = chromadb.PersistentClient(path=str(self.db))
        # A live index that failed builds must leave exactly as it is.
        self.client.create_collection(bi.COLLECTION).add(
            ids=["old-1", "old-2"], embeddings=[[0.1] * 16, [0.2] * 16], documents=["old a", "old b"],
            metadatas=[{"state": "Central", "source_file": "old.pdf"}] * 2)

    def write(self, rel, text):
        (self.corpus / rel).write_text(text)

    def run_build(self, files=None, embeddings=None):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = bi.main(self.corpus, self.db, self.files if files is None else files, loader_cls=FakeLoader,
                         embeddings=embeddings or DeterministicFakeEmbedding(size=16))
        return rc, out.getvalue()

    def names(self):
        return {c.name for c in self.client.list_collections()}

    def live_ids(self):
        return sorted(self.client.get_collection(bi.COLLECTION).get()["ids"])

    def assert_live_untouched(self):
        self.assertEqual(self.names(), {bi.COLLECTION})
        self.assertEqual(self.live_ids(), ["old-1", "old-2"])

    # --- validation failures: nothing is touched ---
    def test_missing_file_fails_and_keeps_live(self):
        rc, out = self.run_build(self.files + [("state/missing.pdf", "Gujarat")])
        self.assertEqual(rc, 1)
        self.assertIn("state/missing.pdf: file not found", out)
        self.assert_live_untouched()

    def test_near_empty_extraction_fails_and_names_file(self):
        self.write("state/scanned.pdf", "tiny")
        rc, out = self.run_build(self.files + [("state/scanned.pdf", "Mizoram")])
        self.assertEqual(rc, 1)
        self.assertIn("scanned.pdf: only 4 characters extracted", out)
        self.assert_live_untouched()

    def test_loader_error_fails_and_names_file(self):
        self.write("state/broken.pdf", "RAISE")
        rc, out = self.run_build(self.files + [("state/broken.pdf", "Mizoram")])
        self.assertEqual(rc, 1)
        self.assertIn("broken.pdf: failed to load (corrupt pdf)", out)
        self.assert_live_untouched()

    def run_default_list(self, scope_files):
        """Run main() on its default file list, with that list fixed by the test (not by the
        PDFs that happen to exist on this machine)."""
        out = io.StringIO()
        with mock.patch.object(bi, "SCOPE_FILES_WITH_STATE", scope_files), redirect_stdout(out):
            rc = bi.main(self.corpus, self.db, loader_cls=FakeLoader, embeddings=DeterministicFakeEmbedding(size=16))
        return rc, out.getvalue()

    def test_default_file_list_requires_haryana_files(self):
        rc, out = self.run_default_list(list(self.files))
        self.assertEqual(rc, 1)
        self.assertIn("[Haryana] no files matched", out)
        self.assert_live_untouched()

    def test_default_file_list_with_haryana_files_passes_the_check(self):
        self.write("state/haryana-hartrans-gov-in-acts-rules__motor-vehicles.pdf", LONG_TEXT)
        rc, out = self.run_default_list(self.files + [("state/haryana-hartrans-gov-in-acts-rules__motor-vehicles.pdf", "Haryana")])
        self.assertEqual(rc, 0, out)
        self.assertNotIn("no files matched", out)

    def test_empty_file_list_cannot_replace_live(self):
        rc, out = self.run_build(files=[])
        self.assertEqual(rc, 1)
        self.assertIn("the file list is empty", out)
        self.assert_live_untouched()

    def test_zero_chunk_output_cannot_replace_live(self):
        class NoChunks:
            def __init__(self, *args, **kwargs):
                pass

            def split_documents(self, docs):
                return []

        with mock.patch.object(bi, "RecursiveCharacterTextSplitter", NoChunks):
            rc, out = self.run_build()
        self.assertEqual(rc, 1)
        self.assertIn("splitting produced 0 chunks", out)
        self.assert_live_untouched()  # also proves no staging collection was left behind

    def test_verify_rejects_zero_chunks(self):
        self.client.create_collection(bi.STAGING)
        with self.assertRaisesRegex(bi.BuildError, "no chunks to index"):
            bi.verify_staging(self.client, [])

    # --- failures after validation: staging is discarded, live is kept ---
    def test_embedding_failure_keeps_live_and_removes_staging(self):
        rc, out = self.run_build(embeddings=FailingEmbeddings(size=16))
        self.assertEqual(rc, 1)
        self.assertIn("failed after 3 attempts", out)
        self.assert_live_untouched()

    def test_verify_rejects_wrong_count_and_missing_metadata(self):
        staging = self.client.create_collection(bi.STAGING)
        staging.add(ids=["s1"], embeddings=[[0.1] * 16], documents=["x"], metadatas=[{"state": "Delhi"}])
        splits = [Document(page_content="x", metadata={"state": "Delhi", "source_file": "d.pdf"})] * 2
        with self.assertRaisesRegex(bi.BuildError, "staging has 1 chunks, expected 2"):
            bi.verify_staging(self.client, splits)
        with self.assertRaisesRegex(bi.BuildError, "missing state/source_file"):
            bi.verify_staging(self.client, splits[:1])

    # --- success ---
    def test_success_replaces_live_with_usable_verified_index(self):
        rc, out = self.run_build()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.names(), {bi.COLLECTION})  # no staging/previous left behind
        expected = int(out.split("documents into ")[1].split(" chunks")[0])
        data = self.client.get_collection(bi.COLLECTION).get(include=["metadatas"])
        self.assertNotIn("old-1", data["ids"])
        self.assertEqual(len(data["ids"]), expected)
        self.assertEqual({m["state"] for m in data["metadatas"]}, {"Central", "Delhi"})
        store = Chroma(client=self.client, collection_name=bi.COLLECTION,
                       embedding_function=DeterministicFakeEmbedding(size=16))
        hits = store.as_retriever(search_kwargs={"k": 2, "filter": {"state": "Delhi"}}).invoke("licence")
        self.assertEqual({d.metadata["state"] for d in hits}, {"Delhi"})

    # --- recovery from an interrupted swap ---
    def test_recover_restores_previous_after_interrupted_swap(self):
        self.client.get_collection(bi.COLLECTION).modify(name=bi.PREVIOUS)  # died between the renames...
        self.client.create_collection(bi.COLLECTION)                         # ...and the server created an empty one
        with redirect_stdout(io.StringIO()):
            bi.recover(self.client)
        self.assert_live_untouched()

    def test_recover_drops_previous_when_swap_had_completed(self):
        self.client.create_collection(bi.PREVIOUS).add(ids=["p"], embeddings=[[0.3] * 16], documents=["p"])
        bi.recover(self.client)
        self.assert_live_untouched()

    def test_rebuild_after_interrupted_swap_succeeds(self):
        self.client.get_collection(bi.COLLECTION).modify(name=bi.PREVIOUS)
        rc, out = self.run_build()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.names(), {bi.COLLECTION})
        self.assertNotIn("old-1", self.live_ids())


if __name__ == "__main__":
    unittest.main()
