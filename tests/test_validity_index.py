"""Validity dates (valid_from / valid_to) from manifest to chunk metadata, lifecycle and retrieval.

Offline and synthetic: temporary Chroma directories, a hash-based fake embedder, throwaway fixtures. Nothing here is a real
legal date, a real approval or the production index. Run: python -m unittest discover -s tests -p "test_validity_index.py"
"""

import collections
import copy
import datetime as dt
import hashlib
import sys
import unittest
from pathlib import Path
from unittest import mock

import chromadb
from langchain_core.documents import Document

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_document_lifecycle as tdl  # noqa: E402
import test_server as ts  # noqa: E402
from backend import document_lifecycle as dl  # noqa: E402
from backend import index_validity as iv  # noqa: E402
from backend import offence_date as od  # noqa: E402
from backend import tg_ingest, tg_manifest as tm  # noqa: E402

OPEN = od.OPEN_ENDED
BASIS = "Synthetic test evidence (not a real instrument)"


def raw_doc(i=1, **extra):
    d = {"id": f"doc-{i}", "title": "T", "document_type": "Rules", "issuing_authority": None, "document_number": None,
         "publication_date": None, "effective_date": None, "source_url": None, "file": f"f{i}.htm", "jurisdiction": "Telangana",
         "format": "html", "source_class": "official", "verification_status": "unverified",
         "sha256": f"{i:064x}", "notes": None}
    d.update(extra)
    return d


def parse(*docs):
    return tm.parse_manifest({"schema_version": 1, "jurisdiction": "Telangana", "documents": list(docs)})


class ManifestValidityTests(unittest.TestCase):
    def rejects(self, fragment, **extra):
        with self.assertRaises(tm.ManifestError) as cm:
            parse(raw_doc(**extra))
        self.assertIn(fragment, str(cm.exception))

    def test_omitted_fields_mean_unknown_and_are_flagged(self):
        (e,) = parse(raw_doc())
        self.assertEqual((e.valid_from, e.valid_to, e.validity_status, e.validity_basis), (None, None, tm.UNKNOWN, None))
        self.assertEqual(tm.unverified_validity([e]), [e.id])
        self.assertEqual(tm.validity_metadata(e), {"validity_status": "unknown"})   # no date keys, never a placeholder

    def test_verified_continuing_and_closed_are_accepted(self):
        a, b = parse(raw_doc(1, valid_from=20190901, valid_to=OPEN, validity_status=tm.CONTINUING, validity_basis=BASIS),
                     raw_doc(2, valid_from=20100101, valid_to=20190831, validity_status=tm.CLOSED, validity_basis=BASIS))
        self.assertEqual(tm.validity_metadata(a), {"validity_status": tm.CONTINUING, "valid_from": 20190901, "valid_to": OPEN})
        self.assertEqual(tm.validity_metadata(b)["valid_to"], 20190831)
        self.assertEqual(tm.unverified_validity([a, b]), [])

    def test_dates_without_verified_status_are_refused(self):
        self.rejects("dates need verified evidence", valid_from=20190901, valid_to=OPEN)
        self.rejects("dates need verified evidence", valid_from=20190901, valid_to=OPEN, validity_status="unknown")

    def test_open_end_only_for_verified_continuing(self):
        self.rejects("only for verified_continuing", valid_from=20190901, valid_to=OPEN, validity_status=tm.CLOSED,
                     validity_basis=BASIS)
        self.rejects("needs valid_to = 99991231", valid_from=20190901, valid_to=20200101, validity_status=tm.CONTINUING,
                     validity_basis=BASIS)

    def test_basis_is_required_for_any_verified_range(self):
        self.rejects("validity_basis is required", valid_from=20190901, valid_to=OPEN, validity_status=tm.CONTINUING)
        self.rejects("validity_basis is required", valid_from=20190901, valid_to=OPEN, validity_status=tm.CONTINUING,
                     validity_basis="  ")

    def test_only_integer_calendar_dates_are_accepted(self):
        good = dict(validity_status=tm.CLOSED, validity_basis=BASIS)
        for name, bad in {"string": ("2019-09-01", 20200101), "iso digits string": ("20190901", 20200101),
                          "bool": (True, 20200101), "float": (20190901.0, 20200101), "bad month": (20191301, 20200101),
                          "bad day": (20190230, 20200101), "zero": (0, 20200101), "inverted": (20210101, 20200101),
                          "from is open end": (OPEN, OPEN), "one missing": (20190901, None)}.items():
            with self.subTest(name), self.assertRaises(tm.ManifestError):
                parse(raw_doc(valid_from=bad[0], valid_to=bad[1], **good))

    def test_unknown_keys_and_missing_base_keys_are_still_refused(self):
        with self.assertRaises(tm.ManifestError):
            parse(raw_doc(valid_until=20200101))
        d = raw_doc()
        del d["sha256"]
        with self.assertRaises(tm.ManifestError):
            parse(d)


class IngestMetadataTests(unittest.TestCase):
    BLOCKS = [tg_ingest.Block("text", "Rule 1. Keep left.", "f.htm#a1"), tg_ingest.Block("text", "Rule 2. Wear a helmet.", "f.htm#a2")]

    def chunks(self, **extra):
        (e,) = parse(raw_doc(**extra))
        return tg_ingest.chunk_document(self.BLOCKS, e)

    def test_unknown_validity_is_flagged_and_has_no_date_keys(self):
        for c in self.chunks():
            self.assertEqual(c.metadata["validity_status"], "unknown")
            self.assertNotIn("valid_from", c.metadata)
            self.assertNotIn("valid_to", c.metadata)

    def test_verified_dates_become_integer_metadata(self):
        cs = self.chunks(valid_from=20190901, valid_to=OPEN, validity_status=tm.CONTINUING, validity_basis=BASIS)
        self.assertTrue(cs)
        for c in cs:
            self.assertIs(type(c.metadata["valid_from"]), int)
            self.assertEqual((c.metadata["valid_from"], c.metadata["valid_to"]), (20190901, OPEN))
            self.assertEqual(iv.chunk_problems(c.metadata), [])

    def test_effective_date_is_never_used_as_a_validity_date(self):
        cs = self.chunks(effective_date="2019-09-01")
        for c in cs:
            self.assertEqual(c.metadata["effective_date"], "2019-09-01")
            self.assertNotIn("valid_from", c.metadata)


class IndexReportTests(unittest.TestCase):
    def setUp(self):
        self.entries = parse(raw_doc(1, valid_from=20190901, valid_to=OPEN, validity_status=tm.CONTINUING, validity_basis=BASIS),
                             raw_doc(2))
        blocks = IngestMetadataTests.BLOCKS
        self.metas = [dict(c.metadata) for e in self.entries for c in tg_ingest.chunk_document(blocks, e)]

    def test_consistent_index_reports_counts_and_flags_unknown_sources(self):
        r = iv.report(self.metas, self.entries)
        self.assertEqual(r["problems"], [])
        self.assertEqual((r["versioned"], r["unversioned"], r["unflagged"]), (2, 2, 0))
        self.assertEqual(r["unknown"], ["doc-2"])

    def test_chunk_that_disagrees_with_the_manifest_is_reported(self):
        self.metas[0]["valid_to"] = 20250101
        self.assertTrue(iv.report(self.metas, self.entries)["problems"])     # continuing but no longer open-ended
        self.metas[0].update(valid_to=OPEN, valid_from=20200101)             # well-formed, yet not what the manifest says
        self.assertTrue(any("differs from the manifest" in p for p in iv.report(self.metas, self.entries)["problems"]))

    def test_dates_present_for_a_source_the_manifest_calls_unknown_are_reported(self):
        m = dict(self.metas[-1], valid_from=20100101, valid_to=OPEN, validity_status=tm.CONTINUING)
        self.assertTrue(iv.report(self.metas[:-1] + [m], self.entries)["problems"])

    def test_malformed_ranges_are_reported(self):
        for name, patch in {"half": {"valid_to": None}, "string": {"valid_from": "20190901"}, "bool": {"valid_from": True},
                            "inverted": {"valid_from": 20300101, "valid_to": 20200101}, "no status": {"validity_status": None}}.items():
            with self.subTest(name):
                m = {k: v for k, v in dict(self.metas[0], **patch).items() if v is not None}
                self.assertTrue(iv.chunk_problems(m), name)

    def test_missing_documents_and_foreign_chunks_are_reported(self):
        only_first = [m for m in self.metas if m["manifest_id"] == "doc-1"]
        self.assertIn("doc-2: no chunks in the index", iv.report(only_first, self.entries)["problems"])
        foreign = dict(self.metas[0], sha256="f" * 64, manifest_id="other")
        self.assertTrue(any("outside the manifest" in p for p in iv.report(self.metas + [foreign], self.entries)["problems"]))

    def test_legacy_chunks_without_any_validity_keys_are_unflagged_not_errors(self):
        legacy = [{k: v for k, v in m.items() if not k.startswith("valid")} for m in self.metas]
        r = iv.report(legacy)
        self.assertEqual((r["problems"], r["unflagged"], r["versioned"]), ([], 4, 0))


def doc(text, provision="Rule 5", sha="a" * 64, **meta):
    base = {"state": "Telangana", "source_file": ts.TG_RULES_FILE, "sha256": sha, "provision_id": provision,
            "manifest_id": "tmvr-1989-chap-2", "part": 1, "parts": 1, "title": "Synthetic Motor Rules"}
    base.update(meta)
    return Document(page_content=text, metadata=base)


class RoutingTests(unittest.TestCase):
    D = dt.date

    def test_expired_rule_is_not_evidence_after_its_last_day_but_is_on_it(self):
        old = doc("old", valid_from=20100101, valid_to=20190831)
        self.assertEqual(od.route_documents([old], self.D(2019, 8, 31)).authoritative, (old,))
        r = od.route_documents([old], self.D(2019, 9, 1))
        self.assertEqual((r.authoritative, r.dropped), ((), 1))

    def test_future_rule_is_not_evidence_before_its_first_day(self):
        new = doc("new", valid_from=20260815, valid_to=OPEN)
        self.assertEqual(od.route_documents([new], self.D(2026, 8, 14)).dropped, 1)
        self.assertEqual(od.route_documents([new], self.D(2026, 8, 15)).authoritative, (new,))

    def test_unknown_dates_are_unverified_never_evidence(self):
        u = doc("u", validity_status="unknown")
        r = od.route_documents([u], self.D(2022, 1, 1))
        self.assertEqual((r.authoritative, r.unverified), ((), (u,)))
        self.assertFalse(r.temporally_established)

    def test_overlapping_versions_cancel_each_other(self):
        a = doc("a", sha="a" * 64, valid_from=20100101, valid_to=20200101)
        b = doc("b", sha="b" * 64, valid_from=20190101, valid_to=OPEN)
        r = od.route_documents([a, b], self.D(2019, 6, 1))
        self.assertEqual((r.authoritative, len(r.unverified), r.conflicts), ((), 2, 1))
        self.assertIn(od.CONFLICT_NOTE, r.notes)
        # outside the overlap each version stands alone
        self.assertEqual(od.route_documents([a, b], self.D(2015, 1, 1)).authoritative, (a,))
        self.assertEqual(od.route_documents([a, b], self.D(2024, 1, 1)).authoritative, (b,))

    def test_different_provisions_or_sources_are_not_a_conflict(self):
        a = doc("a", provision="Rule 5", sha="a" * 64, valid_from=20100101, valid_to=OPEN)
        b = doc("b", provision="Rule 6", sha="b" * 64, valid_from=20100101, valid_to=OPEN)
        c = doc("c", provision="Rule 5", sha="c" * 64, manifest_id="other", valid_from=20100101, valid_to=OPEN)
        self.assertEqual(len(od.route_documents([a, b, c], self.D(2020, 1, 1)).authoritative), 3)

    def test_current_law_uses_todays_range_and_refuses_malformed(self):
        today = self.D(2026, 11, 16)
        ok = lambda **m: od.in_force_today(m, today)  # noqa: E731
        self.assertTrue(ok())                                                        # unversioned: unchanged behaviour
        self.assertTrue(ok(valid_from=20190901, valid_to=OPEN))
        self.assertFalse(ok(valid_from=20100101, valid_to=20190831))                 # expired
        self.assertFalse(ok(valid_from=20270101, valid_to=OPEN))                     # not yet in force
        self.assertFalse(ok(valid_from=20300101, valid_to=20200101))                 # malformed


class LifecycleBase(tdl.Base):
    """Real Lifecycle + Chroma in a temp dir, with a chunker that carries the manifest entry's validity into chunk metadata."""

    def make(self):
        def chunker(entry, corpus_dir):
            out = tdl.fake_chunker(entry, corpus_dir)
            for c in out:
                c.metadata.update(tm.validity_metadata(entry))
            return out
        return dl.Lifecycle(self.state, self.db, embeddings=self.emb, chunker=chunker)

    def ventry(self, text, status=tm.UNKNOWN, start=None, end=None, source="tmvr-fixture", name="rules.txt"):
        e = self.entry(text, source=source, name=name)
        return copy.copy(e).__class__(**{**e.__dict__, "valid_from": start, "valid_to": end, "validity_status": status,
                                         "validity_basis": BASIS if status != tm.UNKNOWN else None})

    def version(self, text, status=tm.UNKNOWN, start=None, end=None, approve=True):
        e = self.ventry(text, status, start, end)
        r = self.lc.ingest(e, self.corpus, by="op")
        if approve:
            self.lc.approve(e.id, r["version"], by="op")
        return e, r["version"]

    def index_rows(self):
        col = chromadb.PersistentClient(path=str(self.db)).get_collection(self.lc.btx.COLLECTION, embedding_function=None)
        return col.get(include=["metadatas"])["metadatas"]

    def index_shas(self):
        return {m["sha256"] for m in self.index_rows()}

    def serve_filter(self):
        f = dl.ServeFilter(self.state)
        f.reconcile(collections.Counter(m["sha256"] for m in self.index_rows()))
        return f


class HistoricalVersionTests(LifecycleBase):
    def test_a_closed_version_stays_in_the_index_as_history_but_never_as_current_law(self):
        e1, v1 = self.version(tdl.V1, tm.CONTINUING, 20190901, OPEN)
        self.lc.close_validity(e1.id, v1, 20260814, "Synthetic: replaced by the 2026 text", by="op")
        e2, v2 = self.version(tdl.V2, tm.CONTINUING, 20260815, OPEN)
        reg = self.lc.load()
        self.assertEqual(dl.Lifecycle.servable_hashes(reg), {e2.sha256})
        self.assertEqual(dl.Lifecycle.historical_hashes(reg), {e1.sha256})
        self.assertEqual(self.index_shas(), {e1.sha256, e2.sha256})
        f = self.serve_filter()
        self.assertFalse(f.servable(e1.sha256))                    # undated: only the active version
        self.assertTrue(f.servable_on(e1.sha256, dated=True))      # dated: history may be used, its range decides
        self.assertTrue(f.servable_on(e2.sha256, dated=True))
        self.assertFalse(f.servable_on(e1.sha256, dated=False))
        self.assertEqual(f.health()["historical_documents"], 1)

    def test_index_rows_carry_the_closed_range(self):
        e1, v1 = self.version(tdl.V1, tm.CONTINUING, 20190901, OPEN)
        self.lc.close_validity(e1.id, v1, 20260814, BASIS, by="op")   # in place, while still the active version
        self.assertEqual({(m["valid_from"], m["valid_to"], m["validity_status"]) for m in self.index_rows()},
                         {(20190901, 20260814, tm.CLOSED)})
        self.assertEqual(iv.report(self.index_rows())["problems"], [])

    def test_unknown_or_open_ended_superseded_versions_leave_the_index(self):
        e1, _ = self.version(tdl.V1)                                  # unknown validity
        e2, _ = self.version(tdl.V2, tm.CONTINUING, 20260815, OPEN)
        self.assertEqual(self.index_shas(), {e2.sha256})
        self.assertEqual(dl.Lifecycle.historical_hashes(self.lc.load()), set())
        self.assertFalse(self.serve_filter().servable_on(e1.sha256, dated=True))
        e3, _ = self.version(tdl.V1.replace("helmet", "hat"), tm.CONTINUING, 20270101, OPEN)   # e2 was open-ended
        self.assertEqual(self.index_shas(), {e3.sha256})

    def test_overlapping_versions_are_refused_and_nothing_changes(self):
        e1, v1 = self.version(tdl.V1, tm.CLOSED, 20190901, 20260814)
        e2 = self.ventry(tdl.V2, tm.CONTINUING, 20260101, OPEN)
        r = self.lc.ingest(e2, self.corpus, by="op")
        with self.assertRaises(dl.LifecycleError) as cm:
            self.lc.approve(e2.id, r["version"], by="op")
        self.assertIn("overlaps", str(cm.exception))
        reg = self.lc.load()
        self.assertEqual(dl.Lifecycle.servable_hashes(reg), {e1.sha256})
        self.assertEqual(self.index_shas(), {e1.sha256})
        self.assertEqual(reg["sources"][e1.id]["versions"][str(r["version"])]["state"], dl.PENDING)

    def test_rollback_restores_a_historical_version_without_duplicating_rows(self):
        e1, v1 = self.version(tdl.V1, tm.CONTINUING, 20190901, OPEN)
        self.lc.close_validity(e1.id, v1, 20260814, BASIS, by="op")
        e2, _ = self.version(tdl.V2, tm.CONTINUING, 20260815, OPEN)
        self.lc.rollback(e1.id, v1, by="op")
        self.assertEqual(self.index_shas(), {e1.sha256})          # v2 is open-ended: not kept as history
        self.assertEqual(len(self.index_rows()), 3)
        self.assertEqual(dl.Lifecycle.servable_hashes(self.lc.load()), {e1.sha256})

    def test_pending_rejected_and_withdrawn_versions_are_never_history(self):
        e1, v1 = self.version(tdl.V1, tm.CONTINUING, 20190901, OPEN)
        self.lc.close_validity(e1.id, v1, 20260814, BASIS, by="op")
        e2, v2 = self.version(tdl.V2, tm.CONTINUING, 20260815, OPEN)
        pend = self.ventry(tdl.V1.replace("helmet", "cap"), tm.CLOSED, 20000101, 20010101)
        rp = self.lc.ingest(pend, self.corpus, by="op")
        self.assertNotIn(pend.sha256, dl.Lifecycle.index_hashes(self.lc.load()))
        self.lc.reject(pend.id, rp["version"], by="op")
        self.assertNotIn(pend.sha256, dl.Lifecycle.index_hashes(self.lc.load()))
        self.lc.withdraw(e2.id, v2, by="op")
        self.assertEqual(self.index_shas(), {e1.sha256})           # v1 stays history; the withdrawn v2 is gone
        self.assertFalse(self.serve_filter().servable_on(e2.sha256, dated=True))

    def test_close_validity_refusals(self):
        e0, v0 = self.version(tdl.V1)                                   # unknown
        with self.assertRaises(dl.LifecycleError):
            self.lc.close_validity(e0.id, v0, 20260814, BASIS, by="op")
        e1, v1 = self.version(tdl.V2, tm.CONTINUING, 20190901, OPEN)
        for bad in ((20180101, BASIS), (OPEN, BASIS), (20261340, BASIS), ("20260814", BASIS), (20260814, ""), (20260814, "  ")):
            with self.subTest(bad), self.assertRaises(dl.LifecycleError):
                self.lc.close_validity(e1.id, v1, bad[0], bad[1], by="op")
        self.assertEqual(self.lc.load()["sources"][e1.id]["versions"][str(v1)]["validity_status"], tm.CONTINUING)
        self.lc.close_validity(e1.id, v1, 20260814, BASIS, by="op")
        with self.assertRaises(dl.LifecycleError):                       # a closed range is never edited
            self.lc.close_validity(e1.id, v1, 20250101, BASIS, by="op")
        ev = [x for x in self.lc.load()["events"] if x["op"] == "close_validity"]
        self.assertEqual((len(ev), ev[0]["valid_to"], ev[0]["basis"]), (1, 20260814, BASIS))
        self.assertEqual(self.lc.verify(), [])

    def test_ingest_refuses_chunks_whose_dates_differ_from_the_manifest(self):
        lc = dl.Lifecycle(self.state, self.db, embeddings=self.emb, chunker=tdl.fake_chunker)   # chunker adds no dates
        e = self.ventry(tdl.V1, tm.CONTINUING, 20190901, OPEN)
        with self.assertRaises(dl.LifecycleError) as cm:
            lc.ingest(e, self.corpus, by="op")
        self.assertIn("validity dates differ", str(cm.exception))

    def test_legacy_registry_records_without_validity_behave_as_before(self):
        e, v = self.version(tdl.V1)
        reg = self.lc.load()
        rec = reg["sources"][e.id]["versions"][str(v)]
        for k in ("validity_status", "valid_from", "valid_to", "validity_basis"):
            rec.pop(k)
        self.assertEqual(dl.rec_validity(rec), (tm.UNKNOWN, None, None))
        self.assertIsNone(dl.verified_window(rec))
        self.assertEqual(dl.Lifecycle.historical_hashes(reg), set())


class RetrievalTests(ts.Base):
    """Server retrieval: validity dates, lifecycle history and approval status together (fake store, no model)."""

    SHA_OLD, SHA_NEW = "1" * 64, "2" * 64

    def serve(self, *docs):
        ts.FAKE_SEARCH["fn"] = lambda q, state, _docs: [(d, 0.3) for d in docs]

    def texts(self, docs):
        return sorted(d.page_content for d in docs)

    def test_current_law_drops_expired_future_and_malformed_but_keeps_unversioned(self):
        self.serve(doc("EXPIRED", "R1", valid_from=20100101, valid_to=20190831), doc("FUTURE", "R2", valid_from=20990101, valid_to=OPEN),
                   doc("MALFORMED", "R3", valid_from=20300101, valid_to=20200101), doc("LEGACY", "R4"),
                   doc("CURRENT", "R5", valid_from=20190901, valid_to=OPEN))
        self.assertEqual(self.texts(ts.srv.retrieve("learner licence")), ["CURRENT", "LEGACY"])

    def test_dated_query_uses_the_version_in_force_on_that_date(self):
        old = doc("OLD-TEXT", sha=self.SHA_OLD, valid_from=20100101, valid_to=20260814)
        new = doc("NEW-TEXT", sha=self.SHA_NEW, valid_from=20260815, valid_to=OPEN)
        self.serve(old, new)
        for date, want in ((dt.date(2022, 5, 1), ["OLD-TEXT"]), (dt.date(2026, 8, 14), ["OLD-TEXT"]),
                           (dt.date(2026, 8, 15), ["NEW-TEXT"]), (dt.date(2005, 1, 1), [])):
            with self.subTest(date):
                docs, routing = ts.srv.retrieve_dated("learner licence", date)
                self.assertEqual(self.texts(docs), want)
                self.assertEqual(routing.temporally_established, bool(want))

    def test_dated_query_never_uses_unknown_or_overlapping_text(self):
        self.serve(doc("UNKNOWN", "R1", validity_status="unknown"), doc("NODATES", "R2"),
                   doc("A", "R3", sha=self.SHA_OLD, valid_from=20100101, valid_to=20200101),
                   doc("B", "R3", sha=self.SHA_NEW, valid_from=20190101, valid_to=OPEN))
        docs, routing = ts.srv.retrieve_dated("learner licence", dt.date(2019, 6, 1))
        self.assertEqual(docs, [])
        self.assertEqual(routing.conflicts, 1)

    def _lifecycle(self):
        """A real registry and index: version 1 closed (history), version 2 active."""
        t = LifecycleBase("run")
        t.setUp()
        self.addCleanup(t.tearDown)
        e1, v1 = t.version(tdl.V1, tm.CONTINUING, 20190901, OPEN)
        t.lc.close_validity(e1.id, v1, 20260814, BASIS, by="op")
        e2, _ = t.version(tdl.V2, tm.CONTINUING, 20260815, OPEN)
        return t, e1, e2

    def test_history_serves_only_dated_questions_inside_its_range(self):
        t, e1, e2 = self._lifecycle()
        old = doc("OLD-TEXT", sha=e1.sha256, valid_from=20190901, valid_to=20260814)
        new = doc("NEW-TEXT", sha=e2.sha256, valid_from=20260815, valid_to=OPEN)
        self.serve(old, new)
        with mock.patch.object(ts.srv, "LIFECYCLE", t.serve_filter()):
            self.assertEqual(self.texts(ts.srv.retrieve("q")), ["NEW-TEXT"])              # current law: the active version only
            self.assertEqual(self.texts(ts.srv.retrieve_dated("q", dt.date(2022, 5, 1))[0]), ["OLD-TEXT"])
            self.assertEqual(self.texts(ts.srv.retrieve_dated("q", dt.date(2026, 9, 1))[0]), ["NEW-TEXT"])
            self.assertEqual(ts.srv.retrieve_dated("q", dt.date(2015, 1, 1))[0], [])      # before either version

    def test_history_with_no_verified_closed_range_is_not_served_for_any_date(self):
        t = LifecycleBase("run")
        t.setUp()
        self.addCleanup(t.tearDown)
        e1, _ = t.version(tdl.V1, tm.CONTINUING, 20190901, OPEN)    # superseded while open-ended: not retained
        t.version(tdl.V2, tm.CONTINUING, 20260815, OPEN)
        self.serve(doc("OLD-TEXT", sha=e1.sha256, valid_from=20190901, valid_to=OPEN))
        with mock.patch.object(ts.srv, "LIFECYCLE", t.serve_filter()):
            self.assertEqual(ts.srv.retrieve_dated("q", dt.date(2022, 5, 1))[0], [])

    def test_dated_retrieval_serves_a_retained_version_only_through_the_lifecycle_and_its_own_validity_range(self):
        t, e1, e2 = self._lifecycle()
        old = doc("OLD-TEXT", sha=e1.sha256, valid_from=20190901, valid_to=20260814)
        new = doc("NEW-TEXT", sha=e2.sha256, valid_from=20260815, valid_to=OPEN)
        self.serve(old, new)
        # No signed approval narrows this any more: the lifecycle (approved/retained versions) and each chunk's own range decide.
        with mock.patch.object(ts.srv, "LIFECYCLE", t.serve_filter()):
            self.assertEqual(self.texts(ts.srv.retrieve_dated("q", dt.date(2022, 5, 1))[0]), ["OLD-TEXT"])
            self.assertEqual(self.texts(ts.srv.retrieve_dated("q", dt.date(2026, 9, 1))[0]), ["NEW-TEXT"])
        # a source the lifecycle does not serve stays out, whatever the date
        flt = t.serve_filter()
        with mock.patch.object(ts.srv, "LIFECYCLE", flt), mock.patch.object(flt, "servable_on", lambda sha, dated: sha == e2.sha256):
            self.assertEqual(ts.srv.retrieve_dated("q", dt.date(2022, 5, 1))[0], [])

    def test_registry_mismatch_makes_history_unservable(self):
        t, e1, e2 = self._lifecycle()
        f = t.serve_filter()
        f.reconcile({e1.sha256: 99, e2.sha256: 3})     # the index holds a different number of rows than the registry says
        self.assertFalse(f.servable_on(e1.sha256, dated=True))

    def test_staging_comparison_with_the_manifest_is_clean_for_a_consistent_build(self):
        e1 = self.ventry_for_report()
        self.assertEqual(iv.report([c.metadata for c in tg_ingest.chunk_document(IngestMetadataTests.BLOCKS, e1)], [e1])["problems"], [])

    @staticmethod
    def ventry_for_report():
        return parse(raw_doc(valid_from=20190901, valid_to=OPEN, validity_status=tm.CONTINUING, validity_basis=BASIS))[0]


if __name__ == "__main__":
    unittest.main()
