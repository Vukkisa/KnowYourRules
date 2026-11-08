"""Offline tests for the Telangana manifest, HTML/PDF ingestion, legal-aware chunking and the dedicated builder.

Synthetic fixtures only: invented placeholder text, throwaway in-memory keys, temporary directories.
No real document, approval, key, Groq, Ollama or production index is used.
"""

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import chromadb  # noqa: E402
from chromadb.api.client import SharedSystemClient  # noqa: E402
from langchain_core.embeddings import DeterministicFakeEmbedding  # noqa: E402

from backend import build_telangana_index as bt, legal_approval as la, tg_ingest as ti, tg_manifest as tm  # noqa: E402
import test_legal_approval as tla  # noqa: E402
from tg_fixtures import make_pdf  # noqa: E402

FILLER = "Synthetic placeholder text for testing only. " * 3

RULES_HTML = f"""<html><head><title>x</title><script>var ignored = 1;</script></head><body>
<h2>SYNTHETIC FIXTURE RULES</h2>
<p>Preliminary synthetic text before any rule. {FILLER}</p>
<h3 id="ch1">CHAPTER I</h3><p>PRELIMINARY</p>
<div><span>1.</span></div><div><a name="r1">Short title.- {FILLER}</a></div>
<p>(1) Synthetic sub-rule one. {FILLER}</p>
<p>(2) Synthetic sub-rule two.</p>
<p>(a) synthetic clause a.</p>
<p id="r2">2. Definitions.- {FILLER}</p>
<ol><li>1. A numbered list item inside rule 2 that must not start a new rule.</li></ol>
<h3>CHAPTER II - SYNTHETIC MATTERS</h3>
<p id="r2a">2A. Inserted synthetic rule.- {FILLER}</p>
<p>Rule 3 Synthetic heading - {FILLER}</p>
<p id="sch1">FIRST SCHEDULE</p>
<table id="t1"><tr><th>Synthetic class</th><th>Synthetic value</th></tr>
<tr><td>Class A</td><td>10</td></tr><tr><td>Class B</td><td>20</td></tr></table>
<p>4. A numbered line inside the schedule stays inside the schedule.</p>
</body></html>"""

PDF_PAGES = [
    ["SYNTHETIC FIXTURE ACT", "CHAPTER I", "PRELIMINARY",
     "1. Short title.- Synthetic placeholder text for section one of the fixture act.",
     "(1) Synthetic sub-section one text that is long enough to read.",
     "(2) Synthetic sub-section two text that is long enough to read."],
    ["2. Synthetic heading.- Placeholder text for section two of the fixture.",
     "Synthetic class      Synthetic value", "Class A      10", "Class B      20",
     "3. Another synthetic section with filler text filler text filler text."],
]


def entry_dict(file, sha, **over):
    d = {"id": Path(file).stem.lower().replace("_", "-"), "title": f"Synthetic Fixture {Path(file).stem}",
         "document_type": "Rules", "issuing_authority": None, "document_number": None, "publication_date": None,
         "effective_date": None, "source_url": None, "file": file, "jurisdiction": "Telangana",
         "format": "pdf" if file.endswith(".pdf") else "html", "source_class": "unverified_snapshot",
         "verification_status": "unverified", "sha256": sha, "notes": None}
    d.update(over)
    return d


def manifest(*entries):
    return {"schema_version": 1, "jurisdiction": "Telangana", "documents": list(entries)}


class Workspace(unittest.TestCase):
    """Temp corpus with one synthetic HTML and one synthetic PDF document plus a manifest."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(SharedSystemClient.clear_system_cache)
        self.root = Path(tmp.name)
        self.corpus = self.root / "corpus"
        (self.corpus / "html").mkdir(parents=True)
        self.html = self.corpus / "html" / "rules.htm"
        self.html.write_text(RULES_HTML)
        self.pdf = self.corpus / "act.pdf"
        self.pdf.write_bytes(make_pdf(PDF_PAGES))
        self.entries_raw = [entry_dict("html/rules.htm", la.sha256_file(self.html)),
                            entry_dict("act.pdf", la.sha256_file(self.pdf), document_type="Act")]
        self.manifest_path = self.write_manifest(self.entries_raw)

    def write_manifest(self, entries):
        path = self.root / "manifest.json"
        path.write_text(json.dumps(manifest(*entries)))
        return path

    def entries(self):
        return tm.load_manifest(self.manifest_path)


class ManifestTests(Workspace):
    def test_valid_manifest_with_unknown_metadata_as_null(self):
        entries = self.entries()
        self.assertEqual([e.issuing_authority for e in entries], [None, None])
        self.assertEqual(tm.file_errors(entries, self.corpus), [])

    def test_hash_generation_matches_file_bytes(self):
        import hashlib
        self.assertEqual(self.entries()[0].sha256, hashlib.sha256(self.html.read_bytes()).hexdigest())

    def reject(self, entries, fragment, top=None):
        data = top or manifest(*entries)
        with self.assertRaises(tm.ManifestError) as cm:
            tm.parse_manifest(data)
        self.assertIn(fragment, str(cm.exception))

    def test_missing_and_empty_fields_are_rejected_not_guessed(self):
        e = dict(self.entries_raw[0])
        del e["effective_date"]
        self.reject([e], "exactly the fields")
        self.reject([dict(self.entries_raw[0], issuing_authority="")], "use null for unknown")
        self.reject([dict(self.entries_raw[0], title="  ")], "empty or non-text")

    def test_mixed_jurisdiction_is_rejected(self):
        self.reject([self.entries_raw[0], dict(self.entries_raw[1], jurisdiction="Andhra Pradesh")],
                    "mixed jurisdictions")
        self.reject([], "manifest jurisdiction", top=dict(manifest(*self.entries_raw), jurisdiction="Central"))

    def test_duplicate_files_are_rejected(self):
        twin = dict(self.entries_raw[0], id="twin", file="html/copy.htm")
        self.reject([self.entries_raw[0], twin], "duplicate of another document")
        same_name = dict(self.entries_raw[1], id="other", file="other/rules.htm", format="html")
        self.reject([self.entries_raw[0], same_name], "appears with 2 different contents")
        self.reject([self.entries_raw[0], dict(self.entries_raw[1], id=self.entries_raw[0]["id"])], "repeats id")

    def test_field_values_are_strict(self):
        base = self.entries_raw[0]
        for over, fragment in (({"sha256": "ABC"}, "sha256"), ({"document_type": "Circular"}, "document_type"),
                               ({"source_class": "official-ish"}, "source_class"),
                               ({"verification_status": "approved"}, "verification_status"),
                               ({"publication_date": "2026-02-30"}, "not a real date"),
                               ({"publication_date": "13-08-2025"}, "YYYY-MM-DD"),
                               ({"source_url": "ftp://x"}, "source_url"), ({"format": "pdf"}, "extension"),
                               ({"file": "../outside.htm"}, "inside the corpus"), ({"id": "Bad ID"}, ".id")):
            with self.subTest(over=over):
                self.reject([dict(base, **over)], fragment)

    def test_file_errors_for_missing_and_changed_files(self):
        entries = self.entries()
        self.pdf.write_bytes(make_pdf(PDF_PAGES + [["Extra synthetic page."]]))
        self.html.unlink()
        errors = tm.file_errors(entries, self.corpus)
        self.assertIn("rules: file not found (html/rules.htm)", errors)
        self.assertIn("act: sha256 does not match the file (act.pdf)", errors)


class HtmlTests(Workspace):
    def provisions(self):
        return ti.segment(ti.load_html(self.html, "html/rules.htm"), "Rules")

    def test_rules_chapters_and_split_numbers(self):
        ids = [(p.identifier, p.chapter) for p in self.provisions()]
        self.assertEqual(ids, [
            ("Preamble", ""), ("Rule 1", "CHAPTER I PRELIMINARY"), ("Rule 2", "CHAPTER I PRELIMINARY"),
            ("Rule 2A", "CHAPTER II SYNTHETIC MATTERS"), ("Rule 3", "CHAPTER II SYNTHETIC MATTERS"),
            ("FIRST SCHEDULE", "CHAPTER II SYNTHETIC MATTERS")])
        rule1 = self.provisions()[1]
        # Changed after real-document validation: headings now stop at the ".-" / ":-" separator.
        self.assertEqual(rule1.heading, "Short title")

    def test_sub_rules_clauses_and_list_items_stay_in_their_rule(self):
        p = {x.identifier: x for x in self.provisions()}
        text1 = "\n".join(b.text for b in p["Rule 1"].blocks)
        self.assertIn("(1) Synthetic sub-rule one.", text1)
        self.assertIn("(2) Synthetic sub-rule two.", text1)
        self.assertIn("(a) synthetic clause a.", text1)
        self.assertIn("1. A numbered list item inside rule 2", "\n".join(b.text for b in p["Rule 2"].blocks))

    def test_tables_and_schedules_are_preserved(self):
        sched = self.provisions()[-1]
        tables = [b for b in sched.blocks if b.kind == "table"]
        self.assertEqual(tables[0].text, "Synthetic class | Synthetic value\nClass A | 10\nClass B | 20")
        self.assertEqual(tables[0].location, "html/rules.htm#t1")
        self.assertIn("4. A numbered line inside the schedule", "\n".join(b.text for b in sched.blocks))

    def test_source_locations_and_scripts(self):
        blocks = ti.load_html(self.html, "html/rules.htm")
        self.assertTrue(all(b.location.startswith("html/rules.htm#") for b in blocks))
        self.assertIn("html/rules.htm#r2", [b.location for b in blocks])
        self.assertNotIn("var ignored", " ".join(b.text for b in blocks))

    def test_sections_for_acts(self):
        self.assertEqual(ti.segment(ti.load_html(self.html), "Act")[1].identifier, "Section 1")

    def test_empty_html_is_rejected(self):
        empty = self.corpus / "empty.htm"
        empty.write_text("<html><body><p> </p><script>x()</script></body></html>")
        with self.assertRaisesRegex(ti.IngestError, "empty document"):
            ti.load_blocks(empty, "html", "empty.htm")


class PdfTests(Workspace):
    def test_page_numbers_tables_and_sections(self):
        blocks = ti.load_pdf(self.pdf, "act.pdf")
        self.assertEqual({b.page for b in blocks}, {1, 2})
        table = [b for b in blocks if b.kind == "table"][0]
        self.assertEqual((table.page, table.text), (2, "Synthetic class | Synthetic value\nClass A | 10\nClass B | 20"))
        provisions = ti.segment(blocks, "Act")
        self.assertEqual([p.identifier for p in provisions], ["Preamble", "Section 1", "Section 2", "Section 3"])
        self.assertEqual(provisions[1].chapter, "CHAPTER I PRELIMINARY")

    def test_chunk_page_metadata(self):
        chunks = ti.chunk_document(ti.load_pdf(self.pdf, "act.pdf"), self.entries()[1])
        by_id = {c.metadata["provision_id"]: c.metadata for c in chunks}
        self.assertEqual((by_id["Section 1"]["page_start"], by_id["Section 1"]["page_end"]), (1, 1))
        self.assertEqual(by_id["Section 2"]["location"], "act.pdf#page=2")
        self.assertTrue(by_id["Section 2"]["has_table"])

    def test_scanned_pdf_requires_ocr(self):
        scanned = self.corpus / "scanned.pdf"
        scanned.write_bytes(make_pdf([[], []], image_pages={0, 1}))
        with self.assertRaisesRegex(ti.IngestError, r"OCR required - page\(s\) \[1, 2\]"):
            ti.load_pdf(scanned)

    def test_partly_scanned_pdf_requires_ocr(self):
        mixed = self.corpus / "mixed.pdf"
        mixed.write_bytes(make_pdf(PDF_PAGES + [[]], image_pages={2}))
        with self.assertRaisesRegex(ti.IngestError, r"OCR required - page\(s\) \[3\]"):
            ti.load_pdf(mixed)

    def test_listed_but_undrawn_image_is_not_treated_as_scanned(self):
        p = self.corpus / "listed.pdf"
        p.write_bytes(make_pdf(PDF_PAGES, listed_image_pages={0, 1}))
        self.assertEqual({b.page for b in ti.load_pdf(p)}, {1, 2})

    def test_empty_and_unreadable_pdfs(self):
        blank = self.corpus / "blank.pdf"
        blank.write_bytes(make_pdf([[], ["x"]]))
        with self.assertRaisesRegex(ti.IngestError, "empty document"):
            ti.load_pdf(blank)
        junk = self.corpus / "junk.pdf"
        junk.write_bytes(b"not a pdf at all")
        with self.assertRaisesRegex(ti.IngestError, "unreadable PDF"):
            ti.load_pdf(junk)


class ChunkingTests(Workspace):
    REQUIRED_METADATA = {"sha256", "title", "issuing_authority", "jurisdiction", "state", "provision_id",
                         "location", "page_start", "page_end", "source_class", "verification_status", "source_file"}

    def chunks(self):
        return ti.chunk_document(ti.load_html(self.html, "html/rules.htm"), self.entries()[0])

    def test_one_provision_per_chunk_with_full_metadata(self):
        chunks = self.chunks()
        self.assertEqual([c.metadata["provision_id"] for c in chunks],
                         ["Preamble", "Rule 1", "Rule 2", "Rule 2A", "Rule 3", "FIRST SCHEDULE"])
        for c in chunks:
            self.assertTrue(self.REQUIRED_METADATA <= set(c.metadata), c.metadata)
            self.assertEqual(c.metadata["sha256"], la.sha256_file(self.html))
            self.assertTrue(all(isinstance(v, (str, int, float, bool)) for v in c.metadata.values()))
        rule3 = [c for c in chunks if c.metadata["provision_id"] == "Rule 3"][0]
        self.assertNotIn("FIRST SCHEDULE", rule3.page_content)
        self.assertNotIn("Inserted synthetic rule", rule3.page_content)

    def test_long_rule_splits_only_at_its_sub_rules(self):
        long_rule = "".join(f"<p>({i}) Synthetic sub-rule {i}. {FILLER * 8}</p>" for i in range(1, 7))
        page = self.corpus / "long.htm"
        page.write_text(f"<body><p>7. Long synthetic rule.- intro</p>{long_rule}<p>8. Next rule.- {FILLER}</p></body>")
        e = tm.parse_manifest(manifest(entry_dict("long.htm", la.sha256_file(page))))[0]
        chunks = ti.chunk_document(ti.load_html(page, "long.htm"), e)
        rule7 = [c for c in chunks if c.metadata["provision_id"] == "Rule 7"]
        self.assertGreater(len(rule7), 1)
        self.assertTrue(all(c.metadata["split_method"] == "sub-rule" for c in rule7))
        self.assertEqual({c.metadata["parts"] for c in rule7}, {len(rule7)})
        for c in rule7:
            self.assertLessEqual(len(c.page_content), ti.MAX_CHUNK_CHARS + 200)
            self.assertNotIn("Next rule", c.page_content)
            body = c.page_content.split("\n", 1)[1]
            self.assertRegex(body.splitlines()[0], r"^(7\.|\(\d\))")  # starts at a sub-rule boundary

    def test_large_table_split_repeats_header(self):
        rows = "".join(f"<tr><td>Synthetic class {i}</td><td>{i}</td></tr>" for i in range(400))
        page = self.corpus / "table.htm"
        page.write_text(f"<body><p>SECOND SCHEDULE</p><table><tr><th>Class</th><th>Value</th></tr>{rows}</table></body>")
        e = tm.parse_manifest(manifest(entry_dict("table.htm", la.sha256_file(page))))[0]
        chunks = ti.chunk_document(ti.load_html(page, "table.htm"), e)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(c.metadata["provision_id"] == "SECOND SCHEDULE" for c in chunks))
        self.assertTrue(all("Class | Value" in c.page_content for c in chunks))
        self.assertEqual(chunks[-1].metadata["split_method"], "table-rows")


class LegacyLayoutTests(Workspace):
    """Regression tests for structures found in the real Telangana snapshots (synthetic text only)."""

    LEGACY = ("<html><head><meta http-equiv='Content-Type' content='text/html; charset=iso-8859-1'></head><body>"
              "<table><tr><td>Synthetic Header Fixture</td></tr><tr><td><table><tr><td>"
              "<div align='justify'><strong><a name='1'></a>7. Synthetic duty \u2013 scope :- </strong>(1) Synthetic "
              "sub-rule text one for the fixture.<br><br><strong>(i)</strong> synthetic item.<br><br>"
              "<strong><a name='2'></a>8.Synthetic no space heading :- </strong>Synthetic text two.<br><br>"
              "<strong><a name='3'></a>8-A. Synthetic inserted rule :- </strong>Synthetic text three.<br><br>"
              "<strong><a name='4'></a>8-B Synthetic inserted rule without period :- </strong>Synthetic four."
              "<table><tr><td>Synthetic col</td><td>Synthetic val</td></tr><tr><td>A</td><td>1</td></tr></table>"
              "Synthetic trailing text after the nested table belongs to rule 8-B.<br><br>"
              "<strong><a name='5'></a>9. Synthetic last rule :- </strong>Synthetic text five.</div>"
              "</td></tr></table></td></tr>"
              "<tr><td><table><tr><td>\xab Previous</td><td>\xab Back to Chapters</td><td>Next \xbb</td></tr>"
              "</table></td></tr></table></body></html>").encode("cp1252")

    def blocks(self):
        page = self.corpus / "legacy.htm"
        page.write_bytes(self.LEGACY)
        return ti.load_html(page, "legacy.htm")

    def test_layout_tables_are_walked_and_rules_found(self):
        provisions = ti.segment(self.blocks(), "Rules")
        self.assertEqual([p.identifier for p in provisions], ["Preamble", "Rule 7", "Rule 8", "Rule 8A", "Rule 8B", "Rule 9"])
        self.assertEqual([p.heading for p in provisions[1:]],
                         ["Synthetic duty – scope", "Synthetic no space heading", "Synthetic inserted rule",
                          "Synthetic inserted rule without period", "Synthetic last rule"])

    def test_br_paragraphs_keep_their_own_anchor(self):
        locs = {b.text.split(" ")[0]: b.location for b in self.blocks() if b.kind == "text"}
        self.assertEqual(locs["7."], "legacy.htm#1")
        self.assertEqual(locs["8.Synthetic"], "legacy.htm#2")
        self.assertEqual(locs["9."], "legacy.htm#5")

    def test_inline_text_mixed_with_tables_is_kept_in_order(self):
        provisions = {p.identifier: p for p in ti.segment(self.blocks(), "Rules")}
        kinds = [(b.kind, b.text[:20]) for b in provisions["Rule 8B"].blocks]
        self.assertEqual(kinds[1][0], "table")
        self.assertIn("Synthetic trailing text", provisions["Rule 8B"].blocks[2].text)

    def test_windows_1252_and_navigation(self):
        text = " ".join(b.text for b in self.blocks())
        self.assertIn("–", text)
        self.assertNotIn("\x96", text)
        self.assertNotIn("Back to Chapters", text)

    def test_justified_pdf_line_is_text_not_table(self):
        pdf = self.corpus / "justified.pdf"
        pdf.write_bytes(make_pdf([["1. Synthetic first regulation heading.-Synthetic body text for the fixture.",
                                   "2. Synthetic keep left.-The driver of a synthetic veh      icle shall drive",
                                   "the synthetic vehicle as close to the left side as      possible always.",
                                   "3. Synthetic third regulation.-More synthetic body text for the fixture."]]))
        provisions = ti.segment(ti.load_pdf(pdf), "Regulations")
        self.assertEqual([p.identifier for p in provisions], ["Regulation 1", "Regulation 2", "Regulation 3"])

    def test_no_chunk_exceeds_limit_even_with_a_huge_table_row(self):
        page = self.corpus / "huge.htm"
        page.write_text("<body><p>SECOND SCHEDULE</p><table><tr><td>Head</td><td>Value</td></tr><tr><td>"
                        + "synthetic " * 2000 + "</td><td>1</td></tr></table></body>")
        e = tm.parse_manifest(manifest(entry_dict("huge.htm", la.sha256_file(page))))[0]
        chunks = ti.chunk_document(ti.load_html(page, "huge.htm"), e)
        self.assertGreater(len(chunks), 1)
        label = len(chunks[0].page_content.split("\n", 1)[0]) + 1
        self.assertTrue(all(len(c.page_content) - label <= ti.MAX_CHUNK_CHARS + 50 for c in chunks))


class BuilderTests(Workspace):
    def setUp(self):
        super().setUp()
        self.db = self.root / "tg_db"
        self.key = tla.new_key()
        self.keys = tla.write_keys(self.root, tla.key_entry(self.key, "fixture-key"))

    def approval(self, entries_raw=None, **over):
        docs = [{"file": Path(e["file"]).name, "sha256": e["sha256"], "title": e["title"],
                 "instrument": e["document_type"]} for e in (entries_raw or self.entries_raw)]
        return tla.write_signed(self.root, tla.synthetic_record(documents=docs, **over), self.key, "fixture-key")

    def build(self, approval=True, embeddings=None, db=None, **kw):
        lines = []
        rc = bt.main(self.manifest_path, self.corpus, db or self.db,
                     approval_path=self.approval() if approval is True else approval, trusted_keys=self.keys,
                     embeddings=embeddings or DeterministicFakeEmbedding(size=16), out=lines.append, **kw)
        return rc, "\n".join(lines)

    def live(self, db=None):
        client = chromadb.PersistentClient(path=str(db or self.db))
        return client, client.get_collection(bt.COLLECTION)

    def write_flags(self, flags):
        path = self.root / "flags.json"
        path.write_text(json.dumps({"schema_version": 1, "flags": flags}))
        return path

    def test_chunk_flags_mark_chunks_ineligible_without_changing_text(self):
        plain, _ = bt.prepare(self.manifest_path, self.corpus, self.db, self.approval(), self.keys)
        flags = self.write_flags([{"match": {"manifest_id": "act", "has_table": True},
                                   "warning": "Synthetic table warning", "answer_eligible": False},
                                  {"match": {"manifest_id": "rules", "provision_id": "Rule 3"},
                                   "warning": "Synthetic discrepancy", "answer_eligible": True}])
        flagged, errors = bt.prepare(self.manifest_path, self.corpus, self.db, self.approval(), self.keys, chunk_flags=flags)
        self.assertEqual(errors, [])
        self.assertEqual([c.page_content for c in plain], [c.page_content for c in flagged])
        by = {(c.metadata["manifest_id"], c.metadata["provision_id"]): c.metadata for c in flagged}
        self.assertEqual((by[("act", "Section 2")]["answer_eligible"], by[("act", "Section 2")]["extraction_warning"]),
                         (False, "Synthetic table warning"))
        self.assertEqual((by[("rules", "Rule 3")]["answer_eligible"], by[("rules", "Rule 3")]["extraction_warning"]),
                         (True, "Synthetic discrepancy"))
        self.assertTrue(all(m["answer_eligible"] for k, m in by.items() if k != ("act", "Section 2")))

    def test_flag_matching_nothing_or_malformed_fails_the_build(self):
        for flags in ([{"match": {"manifest_id": "act", "provision_id": "Section 99"}, "warning": "x",
                        "answer_eligible": False}],
                      [{"match": {"provision_id": "Rule 1"}, "warning": "x", "answer_eligible": False}],
                      [{"match": {"manifest_id": "act"}, "warning": "", "answer_eligible": False}]):
            rc, out = self.build(chunk_flags=self.write_flags(flags))
            self.assertEqual(rc, 1, flags)
        self.assertFalse(self.db.exists())

    def test_flags_and_notes_are_stored_in_the_index(self):
        rc, out = self.build(chunk_flags=self.write_flags([{"match": {"manifest_id": "act", "has_table": True},
                                                            "warning": "Synthetic", "answer_eligible": False}]))
        self.assertEqual(rc, 0, out)
        metas = self.live()[1].get(include=["metadatas"])["metadatas"]
        self.assertEqual(sum(1 for m in metas if m["answer_eligible"] is False), 1)
        self.assertTrue(all("manifest_notes" in m for m in metas))

    def test_collection_name_matches_server(self):
        server_src = (Path(bt.__file__).parent / "server.py").read_text()
        self.assertIn(f'TG_COLLECTION = "{bt.COLLECTION}"', server_src)
        self.assertNotEqual(bt.DEFAULT_DB_DIR, bt.SHARED_DB_DIR)

    def test_approved_build_succeeds_and_index_validates_against_record(self):
        rc, out = self.build()
        self.assertEqual(rc, 0, out)
        client, live = self.live()
        self.assertEqual({c.name for c in client.list_collections()}, {bt.COLLECTION})
        metas = live.get(include=["metadatas"])["metadatas"]
        self.assertEqual({m["jurisdiction"] for m in metas}, {"Telangana"})
        record = la.load_record(self.approval())
        self.assertEqual(la.index_errors(record, metas), [])
        self.assertEqual(live.metadata["rag_profile"], "structured")

    def test_shared_collection_in_same_directory_is_never_touched(self):
        client = chromadb.PersistentClient(path=str(self.db))
        client.create_collection(bt.SHARED_COLLECTION).add(ids=["shared-1"], embeddings=[[0.1] * 16],
                                                            documents=["shared"], metadatas=[{"state": "Delhi"}])
        rc, out = self.build()
        self.assertEqual(rc, 0, out)
        shared = chromadb.PersistentClient(path=str(self.db)).get_collection(bt.SHARED_COLLECTION)
        self.assertEqual(shared.get()["ids"], ["shared-1"])

    def test_refuses_shared_directory(self):
        rc, out = self.build(db=bt.SHARED_DB_DIR)
        self.assertEqual(rc, 1)
        self.assertIn("shared index directory", out)

    def test_no_approval_is_refused_and_preview_needs_separate_directory(self):
        rc, out = self.build(approval=None)
        self.assertEqual(rc, 1)
        self.assertIn("no approval record", out)
        with unittest.mock.patch.object(bt, "DEFAULT_DB_DIR", self.db):
            rc, out = self.build(approval=None, allow_unapproved=True)
        self.assertEqual(rc, 1)
        self.assertIn("separate preview directory", out)
        rc, out = self.build(approval=None, allow_unapproved=True, db=self.root / "preview_db")
        self.assertEqual(rc, 0, out)

    def test_unapproved_or_extra_documents_are_rejected(self):
        rc, out = self.build(approval=self.approval(self.entries_raw[:1]))
        self.assertEqual(rc, 1)
        self.assertIn("act: not approved", out)
        self.assertFalse(self.db.exists())

    def test_unresolved_conditions_and_bad_signature_block_the_build(self):
        rc, out = self.build(approval=self.approval(decision="approved_with_conditions",
                                                    conditions=["Synthetic condition"]))
        self.assertIn("1 approval condition(s) unresolved", out)
        path = self.approval()
        path.write_text(path.read_text() + " ")
        rc, out = self.build(approval=path)
        self.assertEqual(rc, 1)
        self.assertIn("signature is invalid", out)

    def test_mixed_jurisdiction_and_drafts_and_changed_files_are_rejected(self):
        for change, fragment in (({"jurisdiction": "Central"}, "mixed jurisdictions"),
                                 ({"source_class": "draft"}, "draft documents are never indexed"),
                                 ({"sha256": "0" * 64}, "sha256 does not match")):
            entries = copy.deepcopy(self.entries_raw)
            entries[1].update(change)
            self.manifest_path = self.write_manifest(entries)
            rc, out = self.build(approval=self.approval(entries))
            self.assertEqual(rc, 1, change)
            self.assertIn(fragment, out)

    def test_scanned_document_fails_the_build_before_any_write(self):
        self.pdf.write_bytes(make_pdf([[], []], image_pages={0, 1}))
        self.entries_raw[1]["sha256"] = la.sha256_file(self.pdf)
        self.manifest_path = self.write_manifest(self.entries_raw)
        rc, out = self.build()
        self.assertEqual(rc, 1)
        self.assertIn("OCR required", out)
        self.assertFalse(self.db.exists())

    def test_failed_staging_build_keeps_previous_index(self):
        rc, out = self.build()
        self.assertEqual(rc, 0, out)
        before = sorted(self.live()[1].get()["ids"])

        class Failing(DeterministicFakeEmbedding):
            def embed_documents(self, texts):
                raise ConnectionError("synthetic embedding outage")

        rc, out = self.build(embeddings=Failing(size=16))
        self.assertEqual(rc, 1)
        self.assertIn("previous index was kept", out)
        client, live = self.live()
        self.assertEqual(sorted(live.get()["ids"]), before)
        self.assertEqual({c.name for c in client.list_collections()}, {bt.COLLECTION})

    def test_validation_failure_before_activation_keeps_previous_index(self):
        rc, _ = self.build()
        before = sorted(self.live()[1].get()["ids"])
        real = ti.chunk_document

        def mislabelled(blocks, entry):
            docs = real(blocks, entry)
            docs[0].metadata["state"] = "Central"
            return docs

        with unittest.mock.patch.object(ti, "chunk_document", mislabelled):
            rc, out = self.build()
        self.assertEqual(rc, 1)
        self.assertIn("mixed jurisdictions", out)
        self.assertEqual(sorted(self.live()[1].get()["ids"]), before)

    def test_verify_staging_rejects_missing_hash_and_missing_documents(self):
        client = chromadb.PersistentClient(path=str(self.db))
        chunks = [ti.chunk_document(ti.load_html(self.html, "html/rules.htm"), self.entries()[0])[0]]
        staging = client.create_collection(bt.STAGING, metadata={"rag_profile": "structured"})
        meta = dict(chunks[0].metadata)
        del meta["sha256"]
        staging.add(ids=["x"], embeddings=[[0.1] * 16], documents=["x"], metadatas=[meta])
        with self.assertRaisesRegex(bt.BuildError, "no valid sha256"):
            bt.verify_staging(client, chunks, {chunks[0].metadata["sha256"]})
        client.delete_collection(bt.STAGING)
        staging = client.create_collection(bt.STAGING, metadata={"rag_profile": "structured"})
        staging.add(ids=["x"], embeddings=[[0.1] * 16], documents=["x"], metadatas=[chunks[0].metadata])
        with self.assertRaisesRegex(bt.BuildError, "produced no chunks"):
            bt.verify_staging(client, chunks, {chunks[0].metadata["sha256"], "f" * 64})

    def test_recover_restores_previous_after_interrupted_swap(self):
        rc, _ = self.build()
        client, live = self.live()
        before = sorted(live.get()["ids"])
        live.modify(name=bt.PREVIOUS)  # interrupted between the two renames
        bt.recover(client)
        self.assertEqual(sorted(client.get_collection(bt.COLLECTION).get()["ids"]), before)


import unittest.mock  # noqa: E402

if __name__ == "__main__":
    unittest.main()
