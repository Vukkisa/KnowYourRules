"""Logical source documents: chapter files of one instrument share a source row, with no provenance lost. Offline."""

import json
import unittest
from pathlib import Path
from unittest import mock

from langchain_core.documents import Document

from test_server import srv

from backend import document_identity

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "docs" / "legal-sources" / "telangana-traffic" / "DRAFT-telangana-manifest.json"
INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
RULES = "Telangana Motor Vehicles Rules, 1989"
SHA = {name: char * 64 for name, char in (("chap3", "3"), ("chap5", "5"), ("go77", "7"), ("go24", "a"), ("go25", "b"))}


def chapter_chunk(n, provision, text="body", **meta):
    return Document(page_content=f"{RULES} - {provision}\n{text}", metadata={
        "manifest_id": f"tmvr-1989-chap-{n}", "source_file": f"middle-main-chap-{n}.htm", "sha256": SHA[f"chap{n}"],
        "title": RULES, "document_type": "Rules", "document_number": "", "jurisdiction": "Telangana",
        "source_class": "unverified_snapshot", "provision_id": provision, "provision_heading": "", "part": 1,
        "parts": 1, "chapter": f"CHAPTER {n}", "location": f"rule-{provision[5:]}", **meta})


def go_chunk(number, key, title, provision="Paragraph 1", text="body"):
    return Document(page_content=f"{title} - {provision}\n{text}", metadata={
        "manifest_id": f"go-ms-{number}-2025-trb", "source_file": f"2025TRB_Ms{number}.pdf", "sha256": SHA[key],
        "title": title, "document_type": "G.O.", "document_number": f"G.O.Ms.No. {number}",
        "jurisdiction": "Telangana", "source_class": "official", "provision_id": provision,
        "provision_heading": "", "part": 1, "parts": 1, "chapter": "", "location": "p1"})


AMENDMENT = "Amendment to Rule 81 of the Telangana Motor Vehicles Rules, 1989"


class LogicalDocumentIdTests(unittest.TestCase):
    def test_chapter_files_share_the_id_of_their_document(self):
        ids = {document_identity.logical_document_id({"manifest_id": f"tmvr-1989-chap-{n}"}) for n in range(1, 13)}
        self.assertEqual(ids, {"tmvr-1989"})

    def test_a_single_file_document_is_its_own_document(self):
        for manifest_id in ("go-ms-77-2025-trb", "tmvtr-1963", "tmvr-1989-chapters", "chap-3"):
            self.assertEqual(document_identity.logical_document_id({"manifest_id": manifest_id}), manifest_id)

    def test_a_chunk_without_manifest_identity_has_no_document_id(self):
        for metadata in ({}, None, {"manifest_id": ""}, {"manifest_id": 7}):
            self.assertIsNone(document_identity.logical_document_id(metadata))

    def test_id_is_left_out_when_its_files_are_described_differently(self):
        same = [chapter_chunk(3, "Rule 39").metadata, chapter_chunk(5, "Rule 81").metadata]
        self.assertEqual(document_identity.consistent_document_ids(same), {"tmvr-1989"})
        for field, value in (("title", AMENDMENT), ("document_type", "G.O."), ("document_number", "G.O.Ms.No. 77"),
                             ("source_class", "official"), ("jurisdiction", "Andhra Pradesh")):
            other = chapter_chunk(5, "Rule 81", **{field: value}).metadata
            self.assertEqual(document_identity.consistent_document_ids([same[0], other]), set(), field)

    def test_real_manifest_groups_only_the_chapter_files_of_the_rules(self):
        entries = json.loads(MANIFEST.read_text(encoding="utf-8"))["documents"]
        groups = {}
        for e in entries:
            groups.setdefault(document_identity.logical_document_id({"manifest_id": e["id"]}), []).append(e)
        multi = {doc_id: es for doc_id, es in groups.items() if len(es) > 1}
        self.assertEqual(list(multi), ["tmvr-1989"])
        self.assertEqual(len(multi["tmvr-1989"]), 12)
        self.assertEqual({(e["title"], e["document_type"]) for e in multi["tmvr-1989"]}, {(RULES, "Rules")})
        self.assertEqual(len({e["sha256"] for e in multi["tmvr-1989"]}), 12)  # twelve files, one document
        self.assertEqual(document_identity.consistent_document_ids(
            {**e, "manifest_id": e["id"]} for e in entries), set(groups))
        for e in entries:  # no order, amendment or other Rules shares an id with anything
            if e["document_type"] == "G.O." or e["id"] == "tmvtr-1963":
                self.assertEqual(groups[e["id"]], [e])


class GroupedSourceEntriesTests(unittest.TestCase):
    def test_chapter_files_of_one_document_are_one_row(self):
        docs = [chapter_chunk(3, "Rule 39"), chapter_chunk(5, "Rule 81"), chapter_chunk(3, "Rule 37")]
        [row] = srv.source_entries(docs)
        self.assertEqual(row["document_id"], "tmvr-1989")
        self.assertEqual([p["provision_id"] for p in row["passages"]], ["Rule 39", "Rule 81", "Rule 37"])
        self.assertEqual(row["files"], [
            {"file": "middle-main-chap-3.htm", "sha256": SHA["chap3"], "manifest_id": "tmvr-1989-chap-3"},
            {"file": "middle-main-chap-5.htm", "sha256": SHA["chap5"], "manifest_id": "tmvr-1989-chap-5"}])
        self.assertEqual((row["file"], row["sha256"]), ("middle-main-chap-3.htm", SHA["chap3"]))

    def test_every_passage_keeps_its_own_label_chunk_id_and_source_reference(self):
        docs = [chapter_chunk(3, "Rule 39", "thirty-nine", provision_heading="Badges", part=2, parts=3),
                chapter_chunk(5, "Rule 81", "eighty-one")]
        first, second = srv.source_entries(docs)[0]["passages"]
        self.assertEqual(first, {
            "provision_id": "Rule 39", "label": "Rule 39 - Badges (part 2 of 3)", "text": "thirty-nine",
            "cited": False, "chunk_id": "tmvr-1989-chap-3::Rule 39::part2of3", "manifest_id": "tmvr-1989-chap-3",
            "file": "middle-main-chap-3.htm", "sha256": SHA["chap3"], "chapter": "CHAPTER 3", "location": "rule-39"})
        self.assertEqual((second["chunk_id"], second["file"], second["sha256"], second["location"]),
                         ("tmvr-1989-chap-5::Rule 81::part1of1", "middle-main-chap-5.htm", SHA["chap5"], "rule-81"))

    def test_grouping_does_not_change_the_stored_chunks(self):
        docs = [chapter_chunk(3, "Rule 39"), chapter_chunk(5, "Rule 81")]
        before = [(d.page_content, dict(d.metadata)) for d in docs]
        srv.source_entries(docs)
        self.assertEqual([(d.page_content, d.metadata) for d in docs], before)

    def test_an_amending_order_is_not_merged_into_the_rules_it_amends(self):
        docs = [chapter_chunk(5, "Rule 81"), go_chunk(77, "go77", AMENDMENT), chapter_chunk(3, "Rule 39")]
        rules, order = srv.source_entries(docs)
        self.assertEqual((rules["document_id"], len(rules["files"]), len(rules["passages"])), ("tmvr-1989", 2, 2))
        self.assertEqual((order["document_id"], [f["file"] for f in order["files"]]),
                         ("go-ms-77-2025-trb", ["2025TRB_Ms77.pdf"]))
        self.assertEqual([p["manifest_id"] for p in order["passages"]], ["go-ms-77-2025-trb"])

    def test_orders_with_the_same_title_stay_separate(self):
        title = "Challans under Rule 167 of the Central Motor Vehicles Rules, 1989"
        rows = srv.source_entries([go_chunk(24, "go24", title), go_chunk(25, "go25", title)])
        self.assertEqual([r["document_id"] for r in rows], ["go-ms-24-2025-trb", "go-ms-25-2025-trb"])

    def test_a_file_named_like_a_chapter_but_described_differently_is_not_merged(self):
        order = go_chunk(77, "go77", AMENDMENT)
        order.metadata["manifest_id"] = "tmvr-1989-chap-99"  # a wrong id must not pull an order into the Rules
        rows = srv.source_entries([chapter_chunk(3, "Rule 39"), order, chapter_chunk(5, "Rule 81")])
        self.assertEqual([[f["sha256"] for f in r["files"]] for r in rows],
                         [[SHA["chap3"]], [SHA["go77"]], [SHA["chap5"]]])
        self.assertEqual([r["document_id"] for r in rows],
                         ["tmvr-1989-chap-3", "tmvr-1989-chap-99", "tmvr-1989-chap-5"])

    def test_approved_and_unapproved_files_are_never_one_row(self):
        with mock.patch.dict(srv.SOURCES, {SHA["chap3"]: (RULES, "Rules")}):
            approved, unapproved = srv.source_entries([chapter_chunk(3, "Rule 39"), chapter_chunk(5, "Rule 81")])
        self.assertEqual((approved["verified"], approved["title"], [f["sha256"] for f in approved["files"]]),
                         (True, RULES, [SHA["chap3"]]))
        self.assertEqual((unapproved["verified"], unapproved["title"], [f["sha256"] for f in unapproved["files"]]),
                         (False, "Unverified source", [SHA["chap5"]]))

    def test_approved_chapter_files_are_one_verified_row(self):
        approved = {SHA["chap3"]: (RULES, "Rules"), SHA["chap5"]: (RULES, "Rules")}
        with mock.patch.dict(srv.SOURCES, approved):
            [row] = srv.source_entries([chapter_chunk(3, "Rule 39"), chapter_chunk(5, "Rule 81")], cited=True)
        self.assertEqual((row["title"], row["instrument"], row["verified"], len(row["files"])), (RULES, "Rules", True, 2))
        self.assertTrue(all(p["cited"] for p in row["passages"]))

    def test_repeated_chunks_and_files_are_listed_once(self):
        a, b = chapter_chunk(3, "Rule 39"), chapter_chunk(5, "Rule 81")
        [row] = srv.source_entries([a, b, a, chapter_chunk(3, "Rule 39"), b])
        self.assertEqual([p["chunk_id"] for p in row["passages"]],
                         ["tmvr-1989-chap-3::Rule 39::part1of1", "tmvr-1989-chap-5::Rule 81::part1of1"])
        self.assertEqual(len(row["files"]), 2)

    def test_chunks_without_manifest_identity_keep_one_row_per_file(self):
        a = Document(page_content="H\none", metadata={"source_file": "a.html", "sha256": "c" * 64, "title": RULES})
        b = Document(page_content="H\ntwo", metadata={"source_file": "b.html", "sha256": "d" * 64, "title": RULES})
        rows = srv.source_entries([a, b])
        self.assertEqual([(r["file"], r["document_id"], len(r["files"])) for r in rows],
                         [("a.html", None, 1), ("b.html", None, 1)])

    def test_a_chunk_without_a_valid_hash_is_not_grouped(self):
        bad = chapter_chunk(5, "Rule 81")
        bad.metadata["sha256"] = "not-a-hash"
        rows = srv.source_entries([chapter_chunk(3, "Rule 39"), bad])
        self.assertEqual([(r["sha256"], len(r["passages"])) for r in rows], [(SHA["chap3"], 1), (None, 1)])

    def test_row_shows_the_most_cautious_text_status_of_its_files(self):
        by_file = {SHA["chap3"]: "verified_current", SHA["chap5"]: "known_amendments_unresolved"}
        with mock.patch.object(srv, "source_text_status", side_effect=lambda sha, docs: by_file[sha]):
            [row] = srv.source_entries([chapter_chunk(3, "Rule 39"), chapter_chunk(5, "Rule 81")])
        self.assertEqual(row["text_status"], "known_amendments_unresolved")

    def test_rows_fit_the_api_response_model(self):
        rows = srv.source_entries([chapter_chunk(3, "Rule 39"), chapter_chunk(5, "Rule 81"),
                                   go_chunk(77, "go77", AMENDMENT)])
        dumped = [srv.Source(**r).model_dump() for r in rows]
        self.assertEqual(dumped, rows)


class FrontendGroupedSourceTests(unittest.TestCase):
    def test_row_counts_its_files_and_dialog_names_the_file_of_each_passage(self):
        self.assertIn("function sourceMeta(s)", INDEX)
        self.assertIn("n + ' files'", INDEX)
        self.assertIn("const from = [p.chapter, p.file].filter(Boolean).join(' · ');", INDEX)
        self.assertIn("if(manyFiles && from) section.append(el('p', 'prov', from));", INDEX)
        self.assertIn("section.dataset.chunkId = p.chunk_id", INDEX)

    def test_page_still_assigns_html_in_two_places_only(self):
        self.assertEqual(INDEX.count(".innerHTML"), 2)


if __name__ == "__main__":
    unittest.main()
