"""Stage 28: chapter context for HTML snapshot chapters, and BM25 text without the chapter label.

Unit tests use synthetic fixtures in temporary directories (no Ollama, Chroma, Groq or network). The recorded
regression tests read the Stage 28 evaluation record, which was produced on scratchpad index copies with local
embeddings only; they skip when the record is absent (KYR_REQUIRE_LEGAL_DATA=1 makes that a failure)."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from langchain_core.documents import Document  # noqa: E402

from backend import build_telangana_index as bt, hybrid_retrieval as hr, tg_ingest as ti, tg_manifest as tm  # noqa: E402
from test_tg_ingest import entry_dict, manifest  # noqa: E402
from backend import legal_approval as la  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RECORD = ROOT / "eval" / "legal-validation" / "stage-28-evaluation.json"
REQUIRE = os.environ.get("KYR_REQUIRE_LEGAL_DATA") == "1"

TOC = """<html><body><a href="acts-rules/main-chap-1.htm">Chapter-I ( Preliminary )</a>
<a href="acts-rules/main-chap-2.htm">Chapter-II ( Synthetic Licences of Drivers )</a>
<a href="acts-rules/main-chap-4.htm">Chapter-IV ( Synthetic Tribunals - Establishment of )</a></body></html>"""
FILLER = "Synthetic placeholder text for testing only. " * 3
CHAPTER_PAGE = f"""<html><body><p id="1">10. Applications:- Every synthetic application is made in Form Z. {FILLER}</p>
<p id="2">11. Fees:- A synthetic fee is payable. {FILLER}</p></body></html>"""
HEADED_PAGE = f"""<html><body><h3>CHAPTER IX - HEADED IN TEXT</h3>
<p id="1">20. Headed rule:- Synthetic text. {FILLER}</p></body></html>"""


class SnapshotChapterTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.corpus = Path(tmp.name)
        self.snap = self.corpus / "html-snapshots" / "rules"
        self.snap.mkdir(parents=True)
        (self.snap / "index.html").write_text(TOC)

    def test_chapter_label_comes_from_the_snapshot_table_of_contents(self):
        self.assertEqual(ti.snapshot_chapter(self.corpus, "html-snapshots/rules/middle-main-chap-4.htm"),
                         "CHAPTER IV SYNTHETIC TRIBUNALS - ESTABLISHMENT OF")
        self.assertEqual(ti.snapshot_chapter(self.corpus, "html-snapshots/rules/middle-main-chap-1.htm"),
                         "CHAPTER I PRELIMINARY")

    def test_never_guessed(self):
        self.assertEqual(ti.snapshot_chapter(self.corpus, "html-snapshots/rules/middle-main-chap-3.htm"), "")  # no entry
        self.assertEqual(ti.snapshot_chapter(self.corpus, "html-snapshots/other/middle-main-chap-4.htm"), "")  # no TOC
        self.assertEqual(ti.snapshot_chapter(self.corpus, "html-snapshots/rules/left-main-chap-4.htm"), "")
        self.assertEqual(ti.snapshot_chapter(self.corpus, "goir/order.pdf"), "")
        self.assertEqual(ti.snapshot_chapter(None, "html-snapshots/rules/middle-main-chap-4.htm"), "")

    def test_roman_numerals(self):
        self.assertEqual([ti._roman_value(n) for n in ("I", "IV", "IX", "XI", "XII", "XIV", "XL")],
                         [1, 4, 9, 11, 12, 14, 40])


class ChunkContextTests(unittest.TestCase):
    def chunks(self, page, default_chapter, tmpname="page.htm"):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / tmpname
            p.write_text(page)
            entry = tm.parse_manifest(manifest(entry_dict(tmpname, la.sha256_file(p))))[0]
            return ti.chunk_document(ti.load_blocks(p, "html", tmpname), entry, default_chapter)

    def test_default_chapter_goes_into_header_and_metadata(self):
        docs = self.chunks(CHAPTER_PAGE, "CHAPTER IV SYNTHETIC TRIBUNALS - ESTABLISHMENT OF")
        rule10 = next(d for d in docs if d.metadata["provision_id"] == "Rule 10")
        self.assertEqual(rule10.metadata["chapter"], "CHAPTER IV SYNTHETIC TRIBUNALS - ESTABLISHMENT OF")
        self.assertTrue(rule10.page_content.startswith(
            "Synthetic Fixture page - CHAPTER IV SYNTHETIC TRIBUNALS - ESTABLISHMENT OF - Rule 10 - Applications\n"))

    def test_without_default_the_chunks_are_unchanged(self):
        plain = self.chunks(CHAPTER_PAGE, "")
        self.assertEqual([d.metadata["chapter"] for d in plain], ["", ""])
        with_ctx = self.chunks(CHAPTER_PAGE, "CHAPTER IV X")
        self.assertEqual([d.page_content.partition("\n")[2] for d in plain],
                         [d.page_content.partition("\n")[2] for d in with_ctx])  # body text identical
        self.assertEqual([(d.metadata["provision_id"], d.metadata["part"]) for d in plain],
                         [(d.metadata["provision_id"], d.metadata["part"]) for d in with_ctx])  # same chunk identities

    def test_a_chapter_heading_in_the_text_wins(self):
        docs = self.chunks(HEADED_PAGE, "CHAPTER IV SYNTHETIC TRIBUNALS - ESTABLISHMENT OF")
        rule20 = next(d for d in docs if d.metadata["provision_id"] == "Rule 20")
        self.assertEqual(rule20.metadata["chapter"], "CHAPTER IX HEADED IN TEXT")


class BuilderChapterTests(unittest.TestCase):
    def test_prepare_labels_snapshot_chapter_pages(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            snap = root / "corpus" / "html-snapshots" / "rules"
            snap.mkdir(parents=True)
            (snap / "index.html").write_text(TOC)
            page = snap / "middle-main-chap-4.htm"
            page.write_text(CHAPTER_PAGE)
            rel = "html-snapshots/rules/middle-main-chap-4.htm"
            (root / "m.json").write_text(json.dumps(manifest(entry_dict(rel, la.sha256_file(page)))))
            chunks, errors = bt.prepare(root / "m.json", root / "corpus", root / "preview-db", allow_unapproved=True)
            self.assertEqual(errors, [])
            self.assertEqual({c.metadata["chapter"] for c in chunks},
                             {"CHAPTER IV SYNTHETIC TRIBUNALS - ESTABLISHMENT OF"})
            self.assertFalse((root / "preview-db").exists())  # prepare never writes an index


class LexicalTextTests(unittest.TestCase):
    CH = "CHAPTER II LICENSING OF DRIVERS OF MOTOR VEHICLES"

    def doc(self, body, chapter=CH, provision="Rule 5"):
        header = " - ".join(x for x in ("Synthetic Rules", chapter, provision, "Heading") if x)
        return Document(page_content=f"{header}\n{body}", metadata={"chapter": chapter, "provision_id": provision,
                                                                     "manifest_id": "m", "title": "Synthetic Rules"})

    def test_chapter_label_removed_from_header_only(self):
        d = self.doc(f"Body that quotes {self.CH} verbatim.")
        self.assertEqual(hr.lexical_text(d),
                         f"Synthetic Rules - Rule 5 - Heading\nBody that quotes {self.CH} verbatim.")
        self.assertIn(self.CH, d.page_content)  # stored text untouched

    def test_no_chapter_means_unchanged(self):
        d = self.doc("Body.", chapter="")
        self.assertEqual(hr.lexical_text(d), d.page_content)

    def test_chapter_words_do_not_score_in_bm25(self):
        a = self.doc("A conductor badge is renewed annually.", provision="Rule 5")  # "drivers" only in its chapter
        b = self.doc("A driver badge is renewed annually.", provision="Rule 6", chapter="CHAPTER III OTHER")
        index = hr.LexicalIndex([a.page_content, b.page_content], [a.metadata, b.metadata])
        self.assertEqual([d.metadata["provision_id"] for d in index.search("drivers", 2)], ["Rule 6"])
        self.assertEqual(index.search("motor vehicles", 2), [])  # chapter-title words alone match nothing


class RecordedRegressionTests(unittest.TestCase):
    """The Stage 28 record: TG-PQ-017 improves, nothing falls out of hit@5, exact and HNSW agree on metrics."""

    @classmethod
    def setUpClass(cls):
        cls.rec = json.loads(RECORD.read_text()) if RECORD.is_file() else None

    def setUp(self):
        if self.rec is None:
            if REQUIRE:
                self.fail("Stage 28 record not present (KYR_REQUIRE_LEGAL_DATA=1)")
            self.skipTest("Stage 28 record not present")

    def test_tg_pq_017_finds_rule_455_in_top_5(self):
        for mode in ("exact", "hnsw"):
            ranked = self.rec["stage28"][mode]["ranked"]["TG-PQ-017"]
            self.assertIn("tmvr-1989-chap-11::Rule 455", ranked[:5], mode)
            self.assertNotIn("tmvr-1989-chap-11::Rule 455", self.rec["baseline"][mode]["ranked"]["TG-PQ-017"][:5])

    def test_no_regression_in_hit5_recall5_guard_or_leakage(self):
        for mode in ("exact", "hnsw"):
            base, new = self.rec["baseline"][mode], self.rec["stage28"][mode]
            self.assertEqual(new["hit@5"], 1.0)
            self.assertGreaterEqual(new["recall@5"], base["recall@5"])
            self.assertEqual((new["guard"], new["excluded_chunks_retrieved"], new["model_calls"]), ("12/12", 0, {}))
            self.assertEqual(new["scored_cases"], 79)

    def test_unrelated_questions_keep_every_expected_provision_in_top_6(self):
        cases = {c["id"]: c for c in json.loads((ROOT / "eval" / "telangana-retrieval-benchmark.json").read_text())["cases"]}
        lost = []
        for mode in ("exact", "hnsw"):
            for qid, ranked in self.rec["stage28"][mode]["ranked"].items():
                case = cases[qid]
                if case["expected_retrieval_outcome"] != "retrieve":
                    continue
                before = self.rec["baseline"][mode]["ranked"][qid]
                lost += [(mode, qid, p) for p in case["expected_provisions"] if p in before and p not in ranked]
        self.assertEqual(lost, [])

    def test_exact_and_hnsw_metrics_agree(self):
        keys = ("recall@1", "recall@3", "recall@5", "hit@5", "mrr")
        self.assertEqual({k: self.rec["stage28"]["exact"][k] for k in keys},
                         {k: self.rec["stage28"]["hnsw"][k] for k in keys})


if __name__ == "__main__":
    unittest.main()
