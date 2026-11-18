"""Offline tests for backend/rag_profiles.py.

No Ollama, no network. The profile handling of the index build is tested in test_tg_ingest.py
(backend/build_telangana_index.py); the retired multi-state builder's tests are in archive/legacy-multistate-builder/.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

from langchain_core.documents import Document  # noqa: E402
from langchain_text_splitters import RecursiveCharacterTextSplitter  # noqa: E402

from backend import rag_profiles as rp  # noqa: E402
import rag_bench as rb  # noqa: E402

SECTIONED = (
    "THE EXAMPLE ACT\n\n"
    "Section 1. Short title\nThis Act may be called the Example Act and applies to every road in the land. " * 1
    + "\n\nSection 2. Licences\n" + "No person shall drive without a licence issued under this Act. " * 6
    + "\n\nSection 3. Helmets\n" + "Every rider and pillion rider shall wear protective headgear. " * 30
    + "\n\nSection 4. Penalties\n" + "Whoever contravenes section 2 shall be punished with a fine. " * 5
)


class ProfileSelectionTests(unittest.TestCase):
    def test_default_and_named_profiles(self):
        self.assertEqual(rp.get_profile(None).name, "structured")
        self.assertEqual(rp.get_profile("").name, "structured")
        self.assertEqual(rp.get_profile(" Baseline ").name, "baseline")
        with self.assertRaisesRegex(ValueError, "unknown RAG_PROFILE"):
            rp.get_profile("bogus")

    def test_baseline_profile_is_the_original_pipeline(self):
        b = rp.PROFILES["baseline"]
        self.assertEqual((b.chunking, b.doc_prefix, b.query_prefix, b.default_max_distance), ("fixed", "", "", 0.88))

    def test_profile_of_index_reads_collection_metadata(self):
        class Coll:
            def __init__(self, metadata):
                self.metadata = metadata

        class Store:
            def __init__(self, metadata):
                self._collection = Coll(metadata)

        self.assertEqual(rp.profile_of_index(Store({"rag_profile": "structured"})).name, "structured")
        self.assertEqual(rp.profile_of_index(Store(None)).name, "baseline")
        self.assertEqual(rp.profile_of_index(Store({"rag_profile": "unknown"})).name, "baseline")
        self.assertEqual(rp.profile_of_index(object()).name, "baseline")

    def test_embeddings_prefixes(self):
        class Rec:
            def embed_documents(self, texts):
                self.docs = texts
                return [[1.0]] * len(texts)

            def embed_query(self, text):
                self.q = text
                return [1.0]

        base = Rec()
        emb = rp.ProfileEmbeddings(base, rp.PROFILES["structured"])
        emb.embed_documents(["a"])
        emb.embed_query("b")
        self.assertEqual((base.docs, base.q), (["search_document: a"], "search_query: b"))
        emb.profile = rp.PROFILES["baseline"]
        emb.embed_documents(["a"])
        emb.embed_query("b")
        self.assertEqual((base.docs, base.q), (["a"], "b"))


class ChunkingTests(unittest.TestCase):
    def doc(self, text, **meta):
        return Document(page_content=text, metadata=dict({"state": "Central", "source_file": "x.pdf"}, **meta))

    def test_baseline_matches_the_original_splitter(self):
        docs = [self.doc(SECTIONED)]
        original = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200, add_start_index=True).split_documents(docs)
        got = rp.split_documents(docs, rp.PROFILES["baseline"], RecursiveCharacterTextSplitter)
        self.assertEqual([(c.page_content, c.metadata) for c in got], [(c.page_content, c.metadata) for c in original])

    def test_structured_chunks_stay_inside_one_section_with_correct_offsets(self):
        chunks = rp.split_documents([self.doc(SECTIONED)], rp.PROFILES["structured"], RecursiveCharacterTextSplitter)
        spans = rp.section_spans(SECTIONED)
        for c in chunks:
            start = c.metadata["start_index"]
            self.assertEqual(SECTIONED[start:start + len(c.page_content)], c.page_content)
            self.assertTrue(any(s <= start and start + len(c.page_content) <= e for s, e in spans))
            self.assertEqual(c.metadata["chunking"], "structure")
            self.assertEqual(c.metadata["state"], "Central")
            self.assertLessEqual(len(c.page_content), rp.CHUNK_SIZE)
        helmets = [c for c in chunks if c.metadata["section"].startswith("Section 3.")]
        self.assertGreater(len(helmets), 1)  # the long section is split, but stays labelled

    def test_short_sections_and_preamble_are_merged_forward(self):
        spans = rp.section_spans(SECTIONED)
        self.assertEqual(spans[0][0], 0)  # the short title and section 1 are merged into section 2
        self.assertTrue(all(e - s >= rp.MIN_SECTION_CHARS for s, e in spans[:-1]))

    def test_unsectioned_text_falls_back_to_fixed_chunks(self):
        text = "Standard operating procedure for permit renewals. " * 60
        chunks = rp.split_documents([self.doc(text)], rp.PROFILES["structured"], RecursiveCharacterTextSplitter)
        self.assertTrue(chunks)
        self.assertTrue(all(c.metadata["chunking"] == "fixed-fallback" for c in chunks))
        self.assertIsNone(rp.section_spans(text))

    def test_structured_matches_benchmark_on_synthetic_corpus(self):
        """Every structured chunk of the benchmark corpus covers exactly one provision, as the
        benchmark's winning 'structure' chunker does."""
        docs = rb.load_corpus(rb.DATA / "corpus_v1.json")
        by_id = {d["doc_id"]: d for d in docs}
        lc_docs = [self.doc(d["text"], doc_id=d["doc_id"]) for d in docs]
        chunks = rp.split_documents(lc_docs, rp.PROFILES["structured"], RecursiveCharacterTextSplitter)
        covered = set()
        for c in chunks:
            s = c.metadata["start_index"]
            hits = rb.provisions_hit({"doc_id": c.metadata["doc_id"], "start": s, "end": s + len(c.page_content)}, by_id)
            self.assertEqual(len(hits), 1, c.page_content[:60])
            covered |= hits
        self.assertEqual(len(covered), sum(len(d["spans"]) for d in docs))


if __name__ == "__main__":
    unittest.main()
