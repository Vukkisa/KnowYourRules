"""Step 5: coverage tooling. Synthetic fixtures only (invented text, temporary directories, a throwaway Chroma directory built
here); one read-only test also READS the real corpus and a real index copy to prove the tool leaves them byte-identical.

Nothing here writes a ledger, approval, register, manifest or registry, and nothing approves anything.
"""

import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chromadb  # noqa: E402
from chromadb.api.client import SharedSystemClient  # noqa: E402

import test_provision_validity as tpv  # noqa: E402
import test_tg_ingest as tgi  # noqa: E402
from backend import legal_approval as la, provision_validity as pv, tg_ingest as ti, tg_manifest as tm, validity_coverage as vc  # noqa: E402
from tg_fixtures import make_pdf  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REAL_REGISTRY_SHA256 = "cd463006b2df2928a624ce4f1aee8e60d7fd4d87f39f4c304fd10ca2f99431d6"
REAL_MANIFEST = ROOT / "docs" / "legal-sources" / "telangana-traffic" / "DRAFT-telangana-manifest.json"
REAL_CORPUS = ROOT / "docs" / "legal-sources" / "telangana-traffic" / "source-documents"
REAL_INDEX = ROOT / "chroma_telangana_staging_validity"
H = lambda s: hashlib.sha256(s.encode()).hexdigest()  # noqa: E731


def md(**over):
    m = {"manifest_id": "doc-a", "sha256": H("file-a"), "provision_id": "Rule 5", "part": 1, "parts": 1, "page_start": 1, "page_end": 1,
         "state": "Telangana", "answer_eligible": True}
    m.update(over)
    return m


def entry(mid="doc-a", sha=None, source_class="unverified_snapshot", verification="unverified"):
    return tm.ManifestEntry(id=mid, title="Synthetic", document_type="Rules", issuing_authority=None, document_number=None,
                            publication_date=None, effective_date=None, source_url=None, file=f"{mid}.htm", jurisdiction="Telangana",
                            format="html", source_class=source_class, verification_status=verification,
                            sha256=sha or H("file-" + mid[-1]), notes=None)


def chunk(cid, meta, text):
    return {"id": cid, "metadata": meta, "text": text}


class Registry:
    def __init__(self, status="unverified_snapshot"):
        self.status = status

    def lookup(self, sha, provision_id=None, label=None):
        return mock.Mock(status=self.status)


def source(entries_states, chunks):
    return {"documents": [{"entry": e, "file_state": s, "problem": None if s == "ok" else s} for e, s in entries_states], "chunks": chunks}


def index(chunks):
    return {"chunks": chunks, "collections": ["synthetic"], "sha256": "0" * 64}


def classes(rep):
    return rep["chunk_counts"]


# ------------------------------------------------------------------------------------------------ selectors

class SelectorTests(unittest.TestCase):
    def test_the_selector_keys_are_the_ledgers(self):
        self.assertEqual(vc.SELECTOR_KEYS, pv.SELECTOR_KEYS)

    def test_a_good_chunk_gets_an_exact_selector(self):
        sel = vc.selector_for(md(), "Rule 5. text")
        self.assertEqual(set(sel), set(pv.SELECTOR_KEYS))
        self.assertEqual(sel["text_sha256"], H("Rule 5. text"))
        self.assertEqual(sel, vc.selector_for(md(), "Rule 5. text"))
        self.assertEqual(sel["text_sha256"], pv.text_digest("Rule 5. text"))          # the ledger's own text digest

    def test_one_changed_character_or_field_breaks_the_match(self):
        sel = vc.selector_for(md(), "Rule 5. text")
        self.assertNotEqual(sel, vc.selector_for(md(), "Rule 5. text."))
        for k, v in {"manifest_id": "doc-b", "sha256": H("x"), "provision_id": "Rule 6", "part": 2, "parts": 2, "page_start": 2,
                     "page_end": 2}.items():
            self.assertNotEqual(sel, vc.selector_for(md(**{k: v}), "Rule 5. text"), k)

    def test_a_boolean_or_float_is_not_an_integer_field(self):
        for k in ("part", "parts", "page_start", "page_end"):
            for bad in (True, 1.0, "1", None):
                self.assertIsNone(vc.selector_for(md(**{k: bad}), "t"), (k, bad))

    def test_malformed_metadata_is_refused_not_repaired(self):
        cases = {"no provision": md(provision_id=""), "no manifest id": md(manifest_id=None), "short hash": md(sha256="abc"),
                 "upper-case hash": md(sha256=H("x").upper()), "part past parts": md(part=3, parts=2), "part zero": md(part=0)}
        for name, m in cases.items():
            with self.subTest(name):
                self.assertIsNone(vc.selector_for(m, "text"))
        self.assertIsNone(vc.selector_for(None, "text"))
        self.assertIsNone(vc.selector_for(md(), ""))
        self.assertIsNone(vc.selector_for(md(), None))

    def test_a_selector_the_tool_makes_is_found_by_the_ledgers_own_matcher(self):
        """The tool's selector, dropped into a ledger by a human, is exactly what the gate's resolver matches."""
        text = "Rule 5. A synthetic rule."
        m = md(manifest_id="m1", provision_id="SECTION 1")
        led = tpv.one()
        led["coverage"][0]["selector"] = vc.selector_for(m, text)
        ledger = tpv.build(led)
        v = pv.resolve_chunk(ledger, m, text, None, tpv.TODAY, "restrict", bound=True)
        self.assertTrue(v.covered)
        self.assertNotIn("stale_coverage", v.reasons)
        stale = pv.resolve_chunk(ledger, m, text + "!", None, tpv.TODAY, "restrict", bound=True)
        self.assertIn("stale_coverage", stale.reasons)


# ------------------------------------------------------------------------------------------------ analysis (no files)

class AnalysisTests(unittest.TestCase):
    A = entry("doc-a")

    def run_(self, src_chunks, idx_chunks=None, states=None, registry=None, index_error=None, entries=None):
        entries = entries or [(self.A, "ok")]
        return vc.analyze(source(states or entries, src_chunks), None if idx_chunks is None else index(idx_chunks),
                          registry=registry, index_error=index_error)

    def pair(self, n=1, **over):
        out_s, out_i = [], []
        for i in range(n):
            m = md(provision_id=f"Rule {i + 1}", **over)
            t = f"Rule {i + 1} text"
            out_s.append(chunk(f"s{i}", dict(m), t))
            out_i.append(chunk(f"i{i}", dict(m), t))
        return out_s, out_i

    def test_correct_mapping_is_verified(self):
        s, i = self.pair(3)
        rep = self.run_(s, i)
        self.assertEqual(classes(rep), {"verified": 3, "candidate": 0, "ambiguous": 0, "unmapped": 0})
        self.assertEqual(rep["provisions"]["without_indexed_chunks"], 0)

    def test_without_an_index_nothing_is_verified(self):
        s, _ = self.pair(2)
        rep = self.run_(s, None)
        self.assertEqual(classes(rep), {"verified": 0, "candidate": 2, "ambiguous": 0, "unmapped": 0})
        self.assertEqual(rep["inputs"]["index_state"], "not_supplied")
        self.assertIsNone(rep["provisions"]["without_indexed_chunks"])

    def test_an_unreadable_index_verifies_nothing(self):
        s, _ = self.pair(2)
        rep = self.run_(s, None, index_error="the index could not be read")
        self.assertEqual(classes(rep)["verified"], 0)
        self.assertEqual(rep["inputs"]["index_state"], "unreadable")

    def test_a_provision_missing_from_the_index_is_reported(self):
        s, i = self.pair(3)
        rep = self.run_(s, i[:2])
        self.assertEqual(rep["provisions"]["without_indexed_chunks"], 1)
        self.assertEqual(rep["provisions_without_indexed_chunks"][0]["provision_id"], "Rule 3")
        self.assertEqual(classes(rep), {"verified": 2, "candidate": 1, "ambiguous": 0, "unmapped": 0})
        self.assertIn("not_indexed", rep["candidates"]["items"][0]["reasons"])

    def test_a_part_missing_from_the_index_is_reported(self):
        s = [chunk("s1", md(part=1, parts=2), "p1"), chunk("s2", md(part=2, parts=2), "p2")]
        rep = self.run_(s, [s[0]])
        self.assertEqual(rep["provisions"]["with_missing_parts"], 1)
        self.assertEqual(rep["provisions_with_missing_parts"][0]["missing_parts"], [2])

    def test_text_that_differs_from_the_index_is_a_candidate_not_verified(self):
        s, i = self.pair(1)
        i[0]["text"] += " (edited)"
        rep = self.run_(s, i)
        self.assertEqual(classes(rep)["verified"], 0)
        self.assertEqual(classes(rep)["candidate"], 1)
        self.assertIn("index_text_or_pages_differ_from_source", rep["candidates"]["items"][0]["reasons"])

    def test_a_candidate_proposal_uses_the_deployed_chunks_own_selector(self):
        s, i = self.pair(1)
        i[0]["text"] += " (edited)"
        p = self.run_(s, i)["proposed_coverage"][0]
        self.assertEqual(p["selector"]["text_sha256"], hashlib.sha256(i[0]["text"].encode("utf-8")).hexdigest())
        self.assertEqual(p["source_selector"]["text_sha256"], hashlib.sha256(s[0]["text"].encode("utf-8")).hexdigest())
        self.assertFalse(p["loadable_as_ledger_coverage"])

    def test_pages_that_differ_are_not_verified(self):
        s, i = self.pair(1)
        i[0]["metadata"]["page_end"] = 9
        self.assertEqual(classes(self.run_(s, i))["verified"], 0)

    def test_a_duplicate_selector_is_ambiguous_on_either_side(self):
        s, i = self.pair(1)
        twin_s = [s[0], chunk("s9", dict(s[0]["metadata"]), s[0]["text"])]
        rep = self.run_(twin_s, i)
        self.assertEqual(classes(rep)["ambiguous"], 2)
        self.assertEqual(classes(rep)["verified"], 0)
        twin_i = [i[0], chunk("i9", dict(i[0]["metadata"]), i[0]["text"])]
        rep = self.run_(s, twin_i)
        self.assertEqual(classes(rep), {"verified": 0, "candidate": 0, "ambiguous": 1, "unmapped": 0})
        self.assertIn("duplicate_selector_in_index", rep["ambiguous"]["items"][0]["reasons"])

    def test_siblings_with_one_label_but_different_pages_or_text_are_both_verified(self):
        """G.O. 53's two 'SCHEDULE' chunks: same label and part, different pages and text. Existing metadata tells them apart."""
        a = chunk("s1", md(provision_id="SCHEDULE", page_start=4, page_end=4), "Schedule one text")
        b = chunk("s2", md(provision_id="SCHEDULE", page_start=4, page_end=5), "Schedule two text, longer")
        rep = self.run_([a, b], [dict(a, id="i1"), dict(b, id="i2")])
        self.assertEqual(classes(rep), {"verified": 2, "candidate": 0, "ambiguous": 0, "unmapped": 0})
        self.assertNotEqual(rep["proposed_coverage"][0]["selector"], rep["proposed_coverage"][1]["selector"])

    def test_siblings_are_not_swapped_when_one_changes(self):
        a = chunk("s1", md(provision_id="SCHEDULE", page_start=4, page_end=4), "Schedule one text")
        b = chunk("s2", md(provision_id="SCHEDULE", page_start=4, page_end=5), "Schedule two text, longer")
        rep = self.run_([a, b], [dict(a, id="i1"), dict(b, id="i2", text="Schedule two text, EDITED")])
        self.assertEqual(classes(rep)["verified"], 1)
        self.assertEqual(classes(rep)["candidate"], 1)
        self.assertEqual(classes(rep)["ambiguous"], 0)

    def test_siblings_identical_in_every_field_are_still_ambiguous(self):
        a = chunk("s1", md(provision_id="SCHEDULE"), "same text")
        rep = self.run_([a, dict(a, id="s2")], [dict(a, id="i1")])
        self.assertEqual(classes(rep)["ambiguous"], 2)

    def test_an_index_only_duplicate_is_reported_once(self):
        _, i = self.pair(1)
        rep = self.run_([], [i[0], dict(i[0], id="i9")])
        self.assertEqual(classes(rep)["ambiguous"], 2)          # no source chunk: each index duplicate is listed

    def test_an_index_chunk_the_sources_cannot_reproduce_is_unmapped(self):
        s, i = self.pair(1)
        orphan = chunk("o1", md(provision_id="Rule 99"), "Rule 99 text")
        rep = self.run_(s, i + [orphan])
        self.assertEqual(classes(rep)["unmapped"], 1)
        self.assertIn("no_source_chunk_for_this_provision", rep["unmapped"]["items"][0]["reasons"])

    def test_a_stale_source_hash_leaves_its_index_chunks_unmapped(self):
        stale = entry("doc-a")
        s, i = self.pair(2)
        rep = self.run_([], i, states=[(stale, "stale_hash")])
        self.assertEqual(classes(rep), {"verified": 0, "candidate": 0, "ambiguous": 0, "unmapped": 2})
        self.assertIn("source_file_not_held_or_stale", rep["unmapped"]["items"][0]["reasons"])
        self.assertEqual(rep["documents"][0]["file_state"], "stale_hash")

    def test_an_index_chunk_with_an_unknown_hash_is_unmapped(self):
        s, i = self.pair(1)
        rep = self.run_(s, [chunk("x", md(sha256=H("not in the manifest")), "t")] + i)
        self.assertIn("stale_or_unknown_source_hash", rep["unmapped"]["items"][0]["reasons"])

    def test_a_manifest_id_that_does_not_belong_to_the_hash_is_unmapped(self):
        s, i = self.pair(1)
        other = entry("doc-b")
        rep = self.run_(s, [chunk("x", md(manifest_id="doc-b", sha256=self.A.sha256), "t")] + i, entries=[(self.A, "ok"), (other, "ok")])
        self.assertIn("manifest_id_does_not_match_hash", rep["unmapped"]["items"][0]["reasons"])

    def test_malformed_metadata_is_unmapped_on_both_sides(self):
        bad = chunk("b1", md(provision_id=""), "text")
        rep = self.run_([bad], [chunk("b2", md(page_start="x"), "text")])
        self.assertEqual(classes(rep), {"verified": 0, "candidate": 0, "ambiguous": 0, "unmapped": 2})
        self.assertTrue(all("malformed_metadata" in x["reasons"] for x in rep["unmapped"]["items"]))

    def test_a_pending_or_unapproved_source_is_flagged_and_never_approvable(self):
        s, i = self.pair(2)
        for status in ("unverified_snapshot", "official_text_commencement_unconfirmed", "status_not_recorded"):
            with self.subTest(status):
                rep = self.run_(s, i, registry=Registry(status))
                self.assertTrue(rep["documents"][0]["source_pending_or_unapproved"])
                self.assertEqual(rep["documents"][0]["approval"], "not evaluated by this tool")
                for p in rep["proposed_coverage"]:
                    self.assertTrue(any("pending or unapproved" in b for b in p["blocked_by"]))
                    self.assertEqual((p["status"], p["decision_ref"], p["provisions"]), ("proposed", None, []))
                    self.assertFalse(p["loadable_as_ledger_coverage"])

    def test_even_a_verified_current_registry_status_does_not_approve_a_mapping(self):
        s, i = self.pair(1)
        rep = self.run_(s, i, registry=Registry("verified_current"))
        self.assertEqual(rep["proposed_coverage"][0]["status"], "proposed")
        self.assertIsNone(rep["proposed_coverage"][0]["decision_ref"])
        self.assertTrue(any("counsel" in b for b in rep["proposed_coverage"][0]["blocked_by"]))

    def test_a_draft_document_contributes_no_chunks(self):
        d = entry("doc-a", source_class="draft")
        rep = self.run_([], [], states=[(d, "draft")])
        self.assertEqual(sum(classes(rep).values()), 0)
        self.assertEqual(rep["documents"][0]["file_state"], "draft")

    def test_a_missing_registry_is_reported_not_guessed(self):
        s, i = self.pair(1)
        self.assertEqual(self.run_(s, i)["documents"][0]["registry_status"], "registry_not_supplied")

    def test_a_label_shared_by_two_documents_is_noted_and_does_not_merge_them(self):
        a, b = entry("doc-a"), entry("doc-b", sha=H("file-b"))
        sa = chunk("s1", md(manifest_id="doc-a"), "Rule 5 a")
        sb = chunk("s2", md(manifest_id="doc-b", sha256=b.sha256), "Rule 5 b")
        rep = self.run_([sa, sb], [dict(sa, id="i1"), dict(sb, id="i2")], entries=[(a, "ok"), (b, "ok")])
        self.assertEqual(classes(rep)["verified"], 2)
        self.assertEqual(rep["provision_labels_shared_by_several_documents"], ["Rule 5"])

    def test_proposals_carry_no_invented_provision_key_date_or_decision(self):
        s, i = self.pair(2)
        for p in self.run_(s, i)["proposed_coverage"]:
            self.assertEqual(set(p), {"selector", "source_selector", "provisions", "decision_ref", "status", "mapping_class",
                                      "source_provision_label", "loadable_as_ledger_coverage", "blocked_by"})
            self.assertEqual(p["provisions"], [])
            self.assertNotIn("valid_from", json.dumps(p))

    def test_a_proposal_cannot_be_loaded_as_ledger_coverage(self):
        s, i = self.pair(1)
        proposal = self.run_(s, i)["proposed_coverage"][0]
        led = tpv.one()
        led["coverage"] = [proposal]
        with self.assertRaises(pv.LedgerError):
            tpv.build(led)
        led["coverage"] = [{"selector": proposal["selector"], "provisions": proposal["provisions"], "decision_ref": None}]
        with self.assertRaises(pv.LedgerError):                       # no provision key: the loader needs a human to assign one
            tpv.build(led)

    def test_the_report_is_deterministic_and_labelled(self):
        s, i = self.pair(3)
        a, b = self.run_(s, i), self.run_(s, i)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        self.assertEqual((a["kind"], a["development_only"], a["not_a_ledger"]), ("validity-coverage-report", True, True))
        self.assertIn("approves any source", a["statement"])

    def test_long_lists_are_bounded_but_counted(self):
        s = [chunk(f"s{n}", md(provision_id=f"Rule {n}"), f"t{n}") for n in range(vc.MAX_LISTED + 25)]
        rep = self.run_(s, None)
        self.assertEqual(len(rep["candidates"]["items"]), vc.MAX_LISTED)
        self.assertEqual(rep["candidates"]["omitted"], 25)
        self.assertEqual(classes(rep)["candidate"], vc.MAX_LISTED + 25)

    def test_markdown_distinguishes_verified_from_candidate(self):
        s, i = self.pair(2)
        text = vc.render_markdown(self.run_(s, i[:1]))
        for needle in ("DEVELOPMENT OUTPUT", "| verified |", "| candidate |", "| ambiguous |", "| unmapped |", "Provisions with no indexed chunk",
                       "approves any source"):
            self.assertIn(needle, text)


# ------------------------------------------------------------------------------------------------ real files, synthetic content

def build_index(path, chunks):
    """A genuine Chroma directory (real schema) holding the given Documents. Created in a temp directory."""
    client = chromadb.PersistentClient(path=str(path))
    coll = client.get_or_create_collection("telangana-traffic-rules")
    if chunks:
        coll.add(ids=[f"c{n}" for n in range(len(chunks))], documents=[c.page_content for c in chunks],
                 metadatas=[c.metadata for c in chunks], embeddings=[[0.1, 0.2, 0.3, 0.4]] * len(chunks))
    del coll, client
    SharedSystemClient.clear_system_cache()


class Workspace(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(SharedSystemClient.clear_system_cache)
        self.root = Path(tmp.name)
        self.corpus = self.root / "corpus"
        (self.corpus / "html").mkdir(parents=True)
        self.html = self.corpus / "html" / "rules.htm"
        self.html.write_text(tgi.RULES_HTML)
        self.pdf = self.corpus / "act.pdf"
        self.pdf.write_bytes(make_pdf(tgi.PDF_PAGES))
        self.raw = [tgi.entry_dict("html/rules.htm", la.sha256_file(self.html)),
                    tgi.entry_dict("act.pdf", la.sha256_file(self.pdf), document_type="Act")]
        self.manifest = self.write_manifest()

    def write_manifest(self):
        path = self.root / "manifest.json"
        path.write_text(json.dumps(tgi.manifest(*self.raw)))
        return path

    def chunks(self):
        out = []
        for e in tm.load_manifest(self.manifest):
            if (self.corpus / e.file).is_file() and la.sha256_file(self.corpus / e.file) == e.sha256:
                out += ti.chunk_document(ti.load_blocks(self.corpus / e.file, e.format, e.file), e, ti.snapshot_chapter(self.corpus, e.file))
        return out

    def index_dir(self, name, chunks):
        d = self.root / name
        d.mkdir()
        build_index(d, chunks)
        return d

    def report(self, index_dir=None, registry=None):
        src = vc.read_source_chunks(self.manifest, self.corpus)
        idx, err = None, None
        if index_dir is not None:
            try:
                idx = vc.read_index_chunks(index_dir)
            except vc.ReadError as e:
                err = str(e)
        return vc.analyze(src, idx, registry=registry, index_error=err), src, idx


class EndToEndTests(Workspace):
    def test_the_source_files_are_chunked_like_the_builder_does(self):
        src = vc.read_source_chunks(self.manifest, self.corpus)
        self.assertEqual([(c["metadata"]["manifest_id"], c["metadata"]["provision_id"], c["text"]) for c in src["chunks"]],
                         [(d.metadata["manifest_id"], d.metadata["provision_id"], d.page_content) for d in self.chunks()])
        self.assertTrue(src["chunks"])

    def test_a_complete_index_maps_every_chunk_exactly(self):
        d = self.index_dir("idx", self.chunks())
        rep, src, idx = self.report(d)
        n = len(src["chunks"])
        self.assertEqual(idx["collections"], ["telangana-traffic-rules"])
        self.assertEqual(classes(rep), {"verified": n, "candidate": 0, "ambiguous": 0, "unmapped": 0})
        self.assertEqual(rep["provisions"]["without_indexed_chunks"], 0)
        self.assertEqual(rep["inputs"]["index_chunks"], n)

    def test_the_index_is_read_with_its_metadata_types_intact(self):
        d = self.index_dir("idx", self.chunks())
        idx = vc.read_index_chunks(d)
        c = idx["chunks"][0]
        self.assertIsInstance(c["metadata"]["part"], int)
        self.assertIsInstance(c["metadata"]["answer_eligible"], bool)
        self.assertIsInstance(c["metadata"]["has_table"], bool)
        self.assertTrue(c["text"].strip())
        self.assertNotIn("chroma:document", c["metadata"])

    def test_missing_indexed_provisions_are_found(self):
        chunks = self.chunks()
        gone = chunks[0].metadata["provision_id"], chunks[0].metadata["manifest_id"]
        keep = [c for c in chunks if (c.metadata["provision_id"], c.metadata["manifest_id"]) != gone]
        rep, _, _ = self.report(self.index_dir("idx", keep))
        self.assertGreaterEqual(rep["provisions"]["without_indexed_chunks"], 1)
        self.assertTrue(any((x["provision_id"], x["manifest_id"]) == gone for x in rep["provisions_without_indexed_chunks"]))
        self.assertGreaterEqual(classes(rep)["candidate"], 1)

    def test_an_edited_indexed_chunk_is_not_verified(self):
        chunks = self.chunks()
        edited = list(chunks)
        edited[1] = type(chunks[1])(page_content=chunks[1].page_content + " EDITED", metadata=dict(chunks[1].metadata))
        rep, _, _ = self.report(self.index_dir("idx", edited))
        self.assertEqual(classes(rep)["verified"], len(chunks) - 1)
        self.assertEqual(classes(rep)["candidate"], 1)

    def test_a_chunk_in_the_index_that_no_source_produces_is_unmapped(self):
        chunks = self.chunks()
        extra = type(chunks[0])(page_content="Rule 77. Not in any source.", metadata=dict(chunks[0].metadata, provision_id="Rule 77"))
        rep, _, _ = self.report(self.index_dir("idx", chunks + [extra]))
        self.assertEqual(classes(rep)["unmapped"], 1)
        self.assertEqual(classes(rep)["verified"], len(chunks))

    def test_a_duplicate_indexed_chunk_is_ambiguous(self):
        chunks = self.chunks()
        rep, _, _ = self.report(self.index_dir("idx", chunks + [chunks[2]]))
        self.assertEqual(classes(rep)["ambiguous"], 1)
        self.assertEqual(classes(rep)["verified"], len(chunks) - 1)

    def test_a_source_file_changed_after_the_manifest_is_stale(self):
        d = self.index_dir("idx", self.chunks())
        self.html.write_text(tgi.RULES_HTML + "<p>edited after the manifest</p>")
        rep, src, _ = self.report(d)
        doc = next(x for x in rep["documents"] if x["file"] == "html/rules.htm")
        self.assertEqual(doc["file_state"], "stale_hash")
        self.assertTrue(all(c["metadata"]["manifest_id"] != doc["manifest_id"] for c in src["chunks"]))
        self.assertGreaterEqual(classes(rep)["unmapped"], 1)
        self.assertTrue(any("source_file_not_held_or_stale" in x["reasons"] for x in rep["unmapped"]["items"]))

    def test_a_missing_source_file_is_reported_and_yields_no_chunks(self):
        self.pdf.unlink()
        rep, src, _ = self.report(None)
        self.assertEqual(next(d for d in rep["documents"] if d["file"] == "act.pdf")["file_state"], "missing")
        self.assertTrue(all(c["metadata"]["manifest_id"] != "act" for c in src["chunks"]))

    def test_a_draft_entry_is_never_chunked(self):
        self.raw[1]["source_class"] = "draft"
        self.write_manifest()
        rep, src, _ = self.report(None)
        self.assertEqual(next(d for d in rep["documents"] if d["file"] == "act.pdf")["file_state"], "draft")
        self.assertTrue(all(c["metadata"]["manifest_id"] != "act" for c in src["chunks"]))

    def test_malformed_indexed_metadata_is_unmapped(self):
        chunks = self.chunks()
        bad = type(chunks[0])(page_content=chunks[0].page_content, metadata={**chunks[0].metadata, "page_start": "one"})
        rep, _, _ = self.report(self.index_dir("idx", [bad] + chunks[1:]))
        self.assertTrue(any("malformed_metadata" in x["reasons"] for x in rep["unmapped"]["items"]))

    def test_pending_sources_stay_pending_whatever_the_index_says(self):
        rep, _, _ = self.report(self.index_dir("idx", self.chunks()), registry=Registry("unverified_snapshot"))
        self.assertTrue(all(d["source_pending_or_unapproved"] for d in rep["documents"]))
        self.assertTrue(rep["proposed_coverage"])
        self.assertTrue(all(any("pending or unapproved" in b for b in p["blocked_by"]) for p in rep["proposed_coverage"]))

    def test_a_directory_with_no_index_is_reported_unreadable(self):
        (self.root / "empty").mkdir()
        rep, _, _ = self.report(self.root / "empty")
        self.assertEqual(rep["inputs"]["index_state"], "unreadable")
        self.assertEqual(classes(rep)["verified"], 0)

    def test_a_corrupt_index_file_is_reported_unreadable(self):
        d = self.root / "corrupt"
        d.mkdir()
        (d / "chroma.sqlite3").write_bytes(b"not a database" * 100)
        rep, _, _ = self.report(d)
        self.assertEqual(rep["inputs"]["index_state"], "unreadable")
        self.assertEqual(classes(rep)["verified"], 0)


class ReadOnlyTests(Workspace):
    def snapshot(self, d):
        return sorted((str(p.relative_to(d)), hashlib.sha256(p.read_bytes()).hexdigest()) for p in Path(d).rglob("*") if p.is_file())

    def test_reading_the_index_changes_nothing_and_adds_no_files(self):
        d = self.index_dir("idx", self.chunks())
        before = self.snapshot(d)
        names = sorted(p.name for p in d.rglob("*"))
        vc.read_index_chunks(d)
        self.assertEqual(self.snapshot(d), before)
        self.assertEqual(sorted(p.name for p in d.rglob("*")), names)

    def test_a_write_protected_index_is_still_readable(self):
        d = self.index_dir("idx", self.chunks())
        db = d / "chroma.sqlite3"
        db.chmod(0o444)
        d.chmod(0o555)
        self.addCleanup(d.chmod, 0o755)
        self.addCleanup(db.chmod, 0o644)
        self.assertTrue(vc.read_index_chunks(d)["chunks"])

    def test_the_index_file_hash_is_reported(self):
        d = self.index_dir("idx", self.chunks())
        self.assertEqual(vc.read_index_chunks(d)["sha256"], hashlib.sha256((d / "chroma.sqlite3").read_bytes()).hexdigest())

    def test_the_index_connection_is_read_only_and_immutable(self):
        d = self.index_dir("idx", self.chunks())
        seen = []
        real = vc.sqlite3.connect

        def spy(target, *a, **k):
            seen.append(target)
            return real(target, *a, **k)
        with mock.patch.object(vc.sqlite3, "connect", spy):
            vc.read_index_chunks(d)
        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0].endswith("?mode=ro&immutable=1"), seen[0])

    def test_a_file_that_changes_during_the_read_is_refused(self):
        d = self.index_dir("idx", self.chunks())
        real = vc.sha256_file
        calls = []

        def shifting(path):
            calls.append(1)
            return real(path) if len(calls) == 1 else "0" * 64
        with mock.patch.object(vc, "sha256_file", shifting):
            with self.assertRaises(vc.ReadError):
                vc.read_index_chunks(d)

    def test_the_corpus_and_manifest_are_not_modified_by_analysis(self):
        d = self.index_dir("idx", self.chunks())
        before = self.snapshot(self.root)
        self.report(d)
        self.assertEqual(self.snapshot(self.root), before)

    def test_no_chroma_client_is_ever_created_by_the_tool(self):
        d = self.index_dir("idx", self.chunks())
        with mock.patch.object(chromadb, "PersistentClient", side_effect=AssertionError("no client")), \
                mock.patch.object(chromadb, "Client", side_effect=AssertionError("no client")), \
                mock.patch.object(chromadb, "HttpClient", side_effect=AssertionError("no client")):
            self.report(d)


# ------------------------------------------------------------------------------------------------ output and the command

SPEC = importlib.util.spec_from_file_location("propose_validity_coverage", ROOT / "scripts" / "propose_validity_coverage.py")
script = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(script)


class OutputTests(Workspace):
    def setUp(self):
        super().setUp()
        self.repo = self.root / "repo"
        (self.repo / "dev-output").mkdir(parents=True)
        for d in ("legal", "legal-status", "backend", "docs/legal-sources", "chroma_x"):
            (self.repo / d).mkdir(parents=True)

    def rep(self):
        return self.report(None)[0]

    def test_output_is_allowed_only_under_dev_output(self):
        ok = vc.check_output_dir(self.repo / "dev-output" / "validity-coverage" / "run1", self.repo)
        self.assertEqual(ok, (self.repo / "dev-output" / "validity-coverage" / "run1").resolve())
        for bad in ("", "reports", "docs", "tests", "dev-outputs", "..", "../elsewhere", "legal", "legal-status", "backend",
                    "docs/legal-sources", "chroma_x", "dev-output", "dev-output/../legal", "dev-output/../backend"):
            with self.subTest(bad), self.assertRaises(vc.OutputRefused):
                vc.check_output_dir(self.repo / bad, self.repo)

    def test_an_absolute_path_outside_the_repo_is_refused(self):
        with self.assertRaises(vc.OutputRefused):
            vc.check_output_dir(self.root / "outside", self.repo)

    def test_a_symlinked_output_directory_is_refused(self):
        target = self.repo / "legal"
        link = self.repo / "dev-output" / "link"
        link.symlink_to(target)
        with self.assertRaises(vc.OutputRefused):
            vc.check_output_dir(link, self.repo)

    def test_output_may_not_overlap_an_input(self):
        out = self.repo / "dev-output" / "validity-coverage"
        for protected in (out, out / "inner", self.repo / "dev-output"):
            with self.subTest(str(protected)), self.assertRaises(vc.OutputRefused):
                vc.check_output_dir(out, self.repo, protected=[protected])

    def test_exactly_three_labelled_files_are_written(self):
        out = self.repo / "dev-output" / "run"
        written = vc.write_report(self.rep(), out, self.repo)
        self.assertEqual(sorted(Path(w).name for w in written), ["coverage-report.json", "coverage-report.md"])
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["coverage-report.json", "coverage-report.md"])
        data = json.loads((out / "coverage-report.json").read_text())
        self.assertEqual((data["kind"], data["not_a_ledger"]), ("validity-coverage-report", True))
        self.assertIn("NOT A LEDGER", (out / "coverage-report.md").read_text())
        self.assertIn("approves any source", data["statement"])

    def test_nothing_is_overwritten_unless_asked(self):
        out = self.repo / "dev-output" / "run"
        vc.write_report(self.rep(), out, self.repo)
        (out / "coverage-report.json").write_text("keep me")
        with self.assertRaises(vc.OutputRefused):
            vc.write_report(self.rep(), out, self.repo)
        self.assertEqual((out / "coverage-report.json").read_text(), "keep me")
        vc.write_report(self.rep(), out, self.repo, overwrite=True)
        self.assertNotEqual((out / "coverage-report.json").read_text(), "keep me")

    def test_a_pre_existing_ledger_or_register_in_the_output_directory_is_never_touched(self):
        out = self.repo / "dev-output" / "run"
        out.mkdir()
        for name in ("ledger.json", "decision-register.json", "evidence-manifest.json", "telangana-approval.json"):
            (out / name).write_text("precious")
        vc.write_report(self.rep(), out, self.repo)
        for name in ("ledger.json", "decision-register.json", "evidence-manifest.json", "telangana-approval.json"):
            self.assertEqual((out / name).read_text(), "precious")

    def cli(self, *extra, index=None):
        args = ["--manifest", str(self.manifest), "--corpus", str(self.corpus), *extra]
        if index:
            args += ["--index-dir", str(index)]
        with mock.patch.object(script, "ROOT", self.repo):
            return script.main(args)

    def test_the_command_writes_a_report_under_dev_output(self):
        d = self.index_dir("idx", self.chunks())
        code = self.cli("--out", str(self.repo / "dev-output" / "validity-coverage" / "r"), index=d)
        self.assertEqual(code, 0)
        data = json.loads((self.repo / "dev-output" / "validity-coverage" / "r" / "coverage-report.json").read_text())
        self.assertEqual(data["chunk_counts"]["unmapped"], 0)
        self.assertGreater(data["chunk_counts"]["verified"], 0)

    def test_the_command_refuses_before_reading_when_the_output_is_not_allowed(self):
        for bad in (self.repo / "legal", self.repo / "docs", self.root / "elsewhere", self.repo / "chroma_x"):
            with self.subTest(str(bad)), mock.patch.object(vc, "read_source_chunks", side_effect=AssertionError("must not read")):
                self.assertEqual(self.cli("--out", str(bad)), 2)

    def test_the_command_refuses_to_write_inside_its_own_inputs(self):
        inside = self.repo / "dev-output" / "in"
        inside.mkdir()
        args = ["--manifest", str(self.manifest), "--corpus", str(self.corpus), "--out", str(inside), "--index-dir", str(inside)]
        with mock.patch.object(script, "ROOT", self.repo):
            self.assertEqual(script.main(args), 2)

    def test_a_bad_manifest_is_exit_two(self):
        self.manifest.write_text("{}")
        self.assertEqual(self.cli("--out", str(self.repo / "dev-output" / "r")), 2)


# ------------------------------------------------------------------------------------------------ safety and isolation

class SafetyTests(unittest.TestCase):
    SRC = (ROOT / "backend" / "validity_coverage.py").read_text(encoding="utf-8")

    def test_the_library_writes_only_in_write_report(self):
        body = self.SRC.split("def write_report", 1)
        self.assertEqual(len(re.findall(r"write_text|write_bytes|\.mkdir\(|open\([^)]*[\"']w", body[0])), 0)
        self.assertEqual(len(re.findall(r"write_text", body[1])), 1)
        for forbidden in ("unlink", "rmtree", "shutil", "os.remove", "os.rename", "replace(", "chmod"):
            self.assertNotIn(forbidden, self.SRC, forbidden)

    def test_the_library_never_imports_the_server_chroma_or_the_gate(self):
        for forbidden in ("chromadb", "langchain_chroma", "backend.server", "import server", "ledger_acceptance", "legal_approval",
                          "validity_decisions", "evidence_manifest", "provision_validity_runtime", "sign_approval"):
            self.assertNotIn(forbidden, self.SRC, forbidden)

    def test_the_index_is_opened_read_only_and_immutable(self):
        self.assertIn('?mode=ro&immutable=1", uri=True', self.SRC)
        self.assertIn("PRAGMA query_only = ON", self.SRC)
        self.assertNotIn("sqlite3.connect(str", self.SRC)

    def test_nothing_in_the_tool_can_produce_an_approval(self):
        self.assertNotIn('"approved"', self.SRC)
        self.assertNotIn("'approved'", self.SRC)
        self.assertNotIn("enforce", self.SRC.lower().replace("immutable", ""))
        self.assertNotIn("TG_PROVISION_VALIDITY", self.SRC)

    def test_no_runtime_module_imports_the_tool(self):
        for p in sorted((ROOT / "backend").glob("*.py")) + sorted((ROOT / "scripts").glob("*.py")):
            if p.name in ("validity_coverage.py", "propose_validity_coverage.py"):
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            with self.subTest(p.name):
                self.assertIsNone(re.search(r"^\s*(?:from backend import[^\n]*\bvalidity_coverage\b|from backend\.validity_coverage|"
                                            r"import backend\.validity_coverage|import validity_coverage)", text, re.M))

    def test_the_command_has_no_flag_that_could_write_a_ledger_or_approval(self):
        text = (ROOT / "scripts" / "propose_validity_coverage.py").read_text(encoding="utf-8")
        for forbidden in ("--ledger", "--approve", "--sign", "--register", "--registry-out", "write_text", "write_bytes"):
            self.assertNotIn(forbidden, text, forbidden)

    def test_the_real_registry_is_unchanged(self):
        self.assertEqual(hashlib.sha256((ROOT / "legal-status" / "source-status.json").read_bytes()).hexdigest(), REAL_REGISTRY_SHA256)

    def test_the_penalty_lock_is_not_touched_by_this_step(self):
        server = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
        self.assertNotIn("validity_coverage", server)
        self.assertIn("def penalty_lock_reason", server)


# ------------------------------------------------------------------------------------------------ the real corpus (read-only)

@unittest.skipUnless(REAL_MANIFEST.is_file() and REAL_CORPUS.is_dir() and (REAL_INDEX / "chroma.sqlite3").is_file(),
                     "real corpus or index copy not present")
class RealCorpusReadOnlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        def tree(p):
            return sorted((str(f.relative_to(p)), hashlib.sha256(f.read_bytes()).hexdigest()) for f in Path(p).rglob("*") if f.is_file())
        cls.tree, cls.before = staticmethod(tree), (tree(REAL_INDEX), tree(REAL_CORPUS), tree(ROOT / "legal-status"), tree(ROOT / "legal"),
                                      hashlib.sha256(REAL_MANIFEST.read_bytes()).hexdigest())
        src = vc.read_source_chunks(REAL_MANIFEST, REAL_CORPUS)
        cls.src, cls.idx = src, vc.read_index_chunks(REAL_INDEX)
        from backend import source_status
        reg = source_status.load(ROOT / "legal-status" / "source-status.json")
        cls.rep = vc.analyze(src, cls.idx, registry=reg if reg.valid else None)

    def test_the_real_inputs_are_byte_identical_after_analysis(self):
        after = (self.tree(REAL_INDEX), self.tree(REAL_CORPUS), self.tree(ROOT / "legal-status"), self.tree(ROOT / "legal"),
                 hashlib.sha256(REAL_MANIFEST.read_bytes()).hexdigest())
        self.assertEqual(after, self.before)

    def test_counts_are_consistent(self):
        r = self.rep
        self.assertEqual(r["inputs"]["documents"], 20)
        self.assertEqual(r["inputs"]["source_chunks"], len(self.src["chunks"]))
        self.assertEqual(r["inputs"]["index_chunks"], len(self.idx["chunks"]))
        self.assertGreaterEqual(sum(r["chunk_counts"].values()), r["inputs"]["source_chunks"])

    def test_every_real_document_is_pending_and_nothing_is_approved(self):
        self.assertTrue(all(d["source_pending_or_unapproved"] for d in self.rep["documents"]))
        self.assertTrue(all(p["status"] == "proposed" and p["decision_ref"] is None and p["provisions"] == []
                            for p in self.rep["proposed_coverage"]))
        self.assertTrue(all(any("pending or unapproved" in b for b in p["blocked_by"]) for p in self.rep["proposed_coverage"]))

    def test_no_verified_mapping_comes_from_a_document_that_is_not_held(self):
        held = {d["manifest_id"] for d in self.rep["documents"] if d["file_state"] == "ok"}
        self.assertTrue(all(p["selector"]["manifest_id"] in held for p in self.rep["proposed_coverage"]))

    def test_every_selector_is_unique_and_the_go53_schedule_chunks_are_distinct_and_verified(self):
        sels = [tuple(sorted(p["selector"].items())) for p in self.rep["proposed_coverage"]]
        self.assertEqual(len(sels), len(set(sels)))
        self.assertEqual(self.rep["chunk_counts"]["ambiguous"], 0)
        schedule = [p for p in self.rep["proposed_coverage"]
                    if p["selector"]["manifest_id"] == "go-ms-53-2025-trb" and p["selector"]["provision_id"] == "SCHEDULE"]
        self.assertEqual(len(schedule), 2)
        self.assertEqual({p["mapping_class"] for p in schedule}, {"verified"})
        self.assertNotEqual(schedule[0]["selector"]["text_sha256"], schedule[1]["selector"]["text_sha256"])
        self.assertNotEqual((schedule[0]["selector"]["page_start"], schedule[0]["selector"]["page_end"]),
                            (schedule[1]["selector"]["page_start"], schedule[1]["selector"]["page_end"]))

    def test_a_ledger_built_from_the_two_real_schedule_selectors_loads_and_each_chunk_finds_its_own_entry(self):
        sch = {(p["selector"]["page_start"], p["selector"]["page_end"]): p["selector"] for p in self.rep["proposed_coverage"]
               if p["selector"]["manifest_id"] == "go-ms-53-2025-trb" and p["selector"]["provision_id"] == "SCHEDULE"}
        chunks = [c for c in self.src["chunks"] if c["metadata"]["manifest_id"] == "go-ms-53-2025-trb" and c["metadata"]["provision_id"] == "SCHEDULE"]
        led = tpv.one()
        led["coverage"] = [{"selector": s, "provisions": [tpv.P], "decision_ref": "LD-003"} for s in sch.values()]
        ledger = tpv.build(led)
        for c in chunks:
            v = pv.resolve_chunk(ledger, c["metadata"], c["text"], None, tpv.TODAY, "restrict", bound=True)
            self.assertTrue(v.covered, c["id"])
            self.assertNotIn("stale_coverage", v.reasons)
        swapped = pv.resolve_chunk(ledger, chunks[0]["metadata"], chunks[1]["text"], None, tpv.TODAY, "restrict", bound=True)
        self.assertIn("stale_coverage", swapped.reasons)

    def test_the_report_is_reproducible(self):
        again = vc.analyze(vc.read_source_chunks(REAL_MANIFEST, REAL_CORPUS), vc.read_index_chunks(REAL_INDEX))
        self.assertEqual(again["chunk_counts"], self.rep["chunk_counts"])


if __name__ == "__main__":
    unittest.main()
