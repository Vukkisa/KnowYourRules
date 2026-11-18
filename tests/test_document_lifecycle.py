"""Stage 6: document lifecycle, incremental indexing, rollback, serving filter and cache invalidation.
Deterministic and offline: temporary Chroma directories, a hash-based fake embedder (no Ollama, no model download), a fake
chunker, the real AnswerCache and the real exact-search class. The real production index is never opened."""
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import chromadb
import numpy as np

from backend import answer_cache as ac
from backend import document_lifecycle as dl
from backend import tg_manifest
from backend.exact_vector import ExactVectorIndex


class FakeEmbedder:
    embedder_id = "fake-embedder-1"

    def __init__(self):
        self.embedded = []
        self.fail = False

    @staticmethod
    def vec(text):
        h = hashlib.sha256(text.encode()).digest()
        v = np.array([b / 255.0 for b in h[:8]], dtype=np.float64) + 0.01
        return [float(x) for x in v / np.linalg.norm(v)]

    def embed_documents(self, texts):
        if self.fail:
            raise RuntimeError("embedding service down")
        self.embedded += list(texts)
        return [self.vec(t) for t in texts]

    def embed_query(self, text):
        return self.vec(text)


def fake_chunker(entry, corpus_dir):
    """One chunk per non-empty line 'Rule N. text' of the file, with the metadata chunk_document produces."""
    out = []
    for line in (Path(corpus_dir) / entry.file).read_text().splitlines():
        if not line.strip():
            continue
        pid = line.split(".")[0]
        out.append(dl.Chunk(f"{entry.title} - {pid}\n{line}", {
            "sha256": entry.sha256, "source_file": Path(entry.file).name, "manifest_id": entry.id, "title": entry.title,
            "document_type": entry.document_type, "issuing_authority": entry.issuing_authority or "",
            "document_number": entry.document_number or "", "publication_date": entry.publication_date or "",
            "effective_date": entry.effective_date or "", "jurisdiction": "Telangana", "state": "Telangana",
            "source_class": entry.source_class, "verification_status": entry.verification_status,
            "source_url": "", "provision_kind": "rule", "provision_id": pid, "provision_heading": "", "chapter": "",
            "location": f"{entry.file}#{pid}", "page_start": -1, "page_end": -1, "part": 1, "parts": 1,
            "split_method": "x", "has_table": False, "manifest_notes": "", "extraction_warning": "",
            "answer_eligible": True}))
    return out


V1 = "Rule 1. Riders shall wear a helmet.\nRule 2. A licence is needed to drive.\nRule 3. Keep left."
V2 = "Rule 1. Riders shall wear a protective helmet.\nRule 2. A licence is needed to drive.\nRule 3. Keep left."


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kyr-lifecycle-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.corpus, self.state, self.db = self.tmp / "corpus", self.tmp / "state", self.tmp / "db"
        self.corpus.mkdir()
        self.emb = FakeEmbedder()
        self.invalidated = []
        self.lc = self.make()

    def make(self):
        return dl.Lifecycle(self.state, self.db, embeddings=self.emb, chunker=fake_chunker,
                            invalidate=lambda shas, sid: self.invalidated.append((tuple(shas), sid)))

    def entry(self, text, source="tmvr-fixture", name="rules.txt", effective=None):
        (self.corpus / name).write_text(text)
        sha = hashlib.sha256((self.corpus / name).read_bytes()).hexdigest()
        return tg_manifest.ManifestEntry(
            id=source, title="Fixture Rules", document_type="Rules", issuing_authority=None, document_number=None,
            publication_date=None, effective_date=effective, source_url=None, file=name, jurisdiction="Telangana",
            format="html", source_class="unverified_snapshot", verification_status="unverified", sha256=sha, notes=None)

    def ingest(self, text, **kw):
        e = self.entry(text, **kw)
        return e, self.lc.ingest(e, self.corpus, by="ingest-bot")

    def live(self):
        c = chromadb.PersistentClient(path=str(self.db))
        if dl.Lifecycle(self.state, self.db).btx.COLLECTION not in {x.name for x in c.list_collections()}:
            return []
        col = c.get_collection("telangana-traffic-rules", embedding_function=None)
        g = col.get(include=["documents", "metadatas"])
        return [(i, d, m) for i, d, m in zip(g["ids"], g["documents"], g["metadatas"])]

    def hashes(self):
        return {m["sha256"] for _, _, m in self.live()}

    def approve_v1(self):
        e, r = self.ingest(V1)
        self.lc.approve(e.id, r["version"], by="reviewer", note="ok")
        return e


class IngestionTests(Base):
    def test_first_ingestion_registers_a_pending_version_and_touches_no_index(self):
        e, r = self.ingest(V1, effective="2019-01-01")
        self.assertEqual((r["outcome"], r["version"], r["state"], r["chunks"]), ("new_source", 1, "pending", 3))
        rec = self.lc.load()["sources"][e.id]["versions"]["1"]
        self.assertEqual((rec["sha256"], rec["file"], rec["effective_date"], rec["supersedes"]), (e.sha256, "rules.txt", "2019-01-01", None))
        self.assertTrue(rec["ingested_at"] and rec["history"][0]["state"] == "pending")
        self.assertEqual(self.live(), [])
        self.assertEqual(self.emb.embedded, [])
        self.assertTrue(self.lc._snapshot_path(e.sha256).is_file())

    def test_effective_date_is_never_inferred(self):
        _, r = self.ingest(V1, name="rules-effective-2021-05-05.txt")
        rec = self.lc.load()["sources"]["tmvr-fixture"]["versions"]["1"]
        self.assertIsNone(rec["effective_date"])

    def test_repeated_ingestion_of_unchanged_content_creates_nothing(self):
        e, r1 = self.ingest(V1)
        _, r2 = self.ingest(V1)
        self.assertEqual((r2["outcome"], r2["version"]), ("unchanged", 1))
        self.assertEqual(len(self.lc.load()["sources"][e.id]["versions"]), 1)
        self.lc.approve(e.id, 1, by="r")
        _, r3 = self.ingest(V1)
        self.assertEqual((r3["outcome"], r3["state"]), ("unchanged", "approved"))
        self.assertEqual(len(self.live()), 3)
        self.assertEqual(self.lc.verify(), [])

    def test_changed_content_is_a_new_version_linked_to_the_active_one(self):
        e = self.approve_v1()
        e2, r = self.ingest(V2)
        self.assertNotEqual(e.sha256, e2.sha256)
        self.assertEqual((r["outcome"], r["version"], r["state"], r["supersedes"]), ("new_version", 2, "pending", 1))
        reg = self.lc.load()["sources"][e.id]
        self.assertEqual(reg["active_version"], 1)
        self.assertEqual(reg["versions"]["1"]["state"], "approved")  # history untouched
        self.assertEqual(self.hashes(), {e.sha256})

    def test_bad_input_is_refused_before_anything_is_recorded(self):
        e = self.entry(V1)
        bad = tg_manifest.ManifestEntry(**dict(e.__dict__, sha256="0" * 64))
        with self.assertRaises(dl.LifecycleError):
            self.lc.ingest(bad, self.corpus, by="x")
        draft = tg_manifest.ManifestEntry(**dict(e.__dict__, source_class="draft"))
        with self.assertRaises(dl.LifecycleError):
            self.lc.ingest(draft, self.corpus, by="x")
        dup = self.entry("Rule 1. same.\nRule 1. same.")
        lc = dl.Lifecycle(self.state, self.db, embeddings=self.emb, chunker=lambda en, c: fake_chunker(en, c) * 2)
        with self.assertRaises(dl.LifecycleError):  # duplicate chunks inside one document
            lc.ingest(dup, self.corpus, by="x")
        self.assertEqual(self.lc.load()["sources"], {})


class ApprovalAndRetrievalTests(Base):
    def test_pending_is_excluded_and_explicit_approval_makes_it_eligible(self):
        e, r = self.ingest(V1)
        flt = dl.ServeFilter(self.state)
        self.assertFalse(flt.servable(e.sha256))
        self.assertEqual(self.hashes(), set())
        out = self.lc.approve(e.id, 1, by="Dr Reviewer", note="checked against gazette")
        self.assertEqual((out["state"], out["embedded"]), ("approved", 3))
        self.assertTrue(flt.servable(e.sha256))
        self.assertEqual(self.hashes(), {e.sha256})
        rec = self.lc.load()["sources"][e.id]["versions"]["1"]
        self.assertEqual([h["state"] for h in rec["history"]], ["pending", "approved"])
        self.assertEqual(rec["history"][1]["by"], "Dr Reviewer")
        self.assertEqual(self.lc.verify(), [])

    def test_approval_needs_a_named_operator_and_a_pending_version(self):
        e, _ = self.ingest(V1)
        with self.assertRaises(dl.LifecycleError):
            self.lc.approve(e.id, 1, by="  ")
        self.assertEqual(self.lc.status()[e.id]["versions"]["1"], "pending")
        self.lc.approve(e.id, 1, by="r")
        with self.assertRaises(dl.LifecycleError):
            self.lc.approve(e.id, 1, by="r")
        with self.assertRaises(dl.LifecycleError):
            self.lc.approve("unknown", 1, by="r")

    def test_rejected_never_enters_the_index_and_cannot_be_approved(self):
        e, _ = self.ingest(V1)
        self.lc.reject(e.id, 1, by="r", note="wrong file")
        self.assertEqual(self.live(), [])
        with self.assertRaises(dl.LifecycleError):
            self.lc.approve(e.id, 1, by="r")

    def test_withdrawal_removes_chunks_and_nothing_is_restored_automatically(self):
        e = self.approve_v1()
        e2, r = self.ingest(V2)
        self.lc.approve(e.id, r["version"], by="r")                    # v2 active, v1 superseded
        out = self.lc.withdraw(e.id, 2, by="r", note="repealed")
        self.assertEqual(out["state"], "withdrawn")
        self.assertEqual(self.live(), [])
        self.assertFalse(dl.ServeFilter(self.state).servable(e2.sha256))
        self.assertFalse(dl.ServeFilter(self.state).servable(e.sha256))
        self.assertIsNone(self.lc.load()["sources"][e.id]["active_version"])
        self.assertEqual(self.lc.verify(), [])
        with self.assertRaises(dl.LifecycleError):
            self.lc.withdraw(e.id, 2, by="r")

    def test_replacement_removes_stale_chunks_and_embeds_only_what_changed(self):
        e = self.approve_v1()
        self.emb.embedded.clear()
        e2, r = self.ingest(V2)
        out = self.lc.approve(e.id, r["version"], by="r", note="amendment")
        self.assertEqual((out["replaced"], out["embedded"], out["reused"]), (1, 1, 2))
        self.assertEqual(len(self.emb.embedded), 1)
        self.assertIn("protective helmet", self.emb.embedded[0])
        rows = self.live()
        self.assertEqual({m["sha256"] for _, _, m in rows}, {e2.sha256})
        self.assertFalse(any("Riders shall wear a helmet" in d for _, d, _ in rows))
        self.assertEqual(len(rows), 3)
        reg = self.lc.load()["sources"][e.id]
        self.assertEqual((reg["active_version"], reg["versions"]["1"]["state"], reg["versions"]["1"]["superseded_by"]),
                         (2, "superseded", 2))
        self.assertEqual(self.lc.verify(), [])

    def test_repeated_activation_work_never_duplicates_rows(self):
        e = self.approve_v1()
        e2, r = self.ingest(V2)
        self.lc.approve(e.id, 2, by="r")
        self.lc.rollback(e.id, 1, by="r")
        self.lc.rollback(e.id, 2, by="r")
        rows = self.live()
        self.assertEqual(len(rows), 3)
        self.assertEqual(len({i for i, _, _ in rows}), 3)
        ids = [dl.chunk_id(c) for c in fake_chunker(e2, self.corpus)]
        self.assertEqual(sorted(i for i, _, m in rows if m["sha256"] == e2.sha256), sorted(ids))  # stable ids


class RollbackTests(Base):
    def test_rollback_restores_the_previous_approved_version_without_re_embedding(self):
        e = self.approve_v1()
        e2, r = self.ingest(V2)
        self.lc.approve(e.id, 2, by="r")
        self.emb.embedded.clear()
        out = self.lc.rollback(e.id, 1, by="ops", note="amendment was issued in error")
        self.assertEqual((out["state"], out["embedded"]), ("approved", 0))
        self.assertEqual(self.hashes(), {e.sha256})
        reg = self.lc.load()
        s = reg["sources"][e.id]
        self.assertEqual((s["active_version"], s["versions"]["1"]["state"], s["versions"]["2"]["state"]),
                         (1, "approved", "superseded"))
        audit = [ev for ev in reg["events"] if ev["op"] == "rollback"]
        self.assertEqual((len(audit), audit[0]["by"], audit[0]["version"], audit[0]["replaced"]), (1, "ops", 1, 2))
        self.assertIn("helmet.", " ".join(d for _, d, _ in self.live()))
        self.assertFalse(dl.ServeFilter(self.state).servable(e2.sha256))
        self.assertEqual(self.lc.verify(), [])

    def test_rollback_refuses_versions_that_were_never_approved_or_are_withdrawn(self):
        e = self.approve_v1()
        e2, r = self.ingest(V2)                                   # v2 pending
        e3, r3 = self.ingest("Rule 1. Third text.")               # v3 pending
        self.lc.reject(e.id, 3, by="r")
        for target in (2, 3):
            with self.assertRaises(dl.LifecycleError):
                self.lc.rollback(e.id, target, by="r")
        self.lc.approve(e.id, 2, by="r")
        self.lc.withdraw(e.id, 2, by="r")
        with self.assertRaises(dl.LifecycleError):
            self.lc.rollback(e.id, 2, by="r")                     # withdrawn
        with self.assertRaises(dl.LifecycleError):
            self.lc.rollback(e.id, 9, by="r")                     # does not exist
        with self.assertRaises(dl.LifecycleError):
            self.lc.rollback(e.id, 1, by="")                      # no named operator
        self.assertEqual(self.hashes(), set())                    # nothing was restored by the refused calls
        self.lc.rollback(e.id, 1, by="r")                         # the genuinely approved-then-superseded one is allowed
        self.assertEqual(self.hashes(), {e.sha256})


class FailureTests(Base):
    def test_embedding_failure_leaves_the_previous_index_and_registry_untouched(self):
        e = self.approve_v1()
        before_rows = sorted(self.live())
        before_reg = self.lc.load()
        e2, r = self.ingest(V2)
        self.emb.fail = True
        with self.assertRaises(RuntimeError):
            self.lc.approve(e.id, 2, by="r")
        self.emb.fail = False
        self.assertEqual(sorted(self.live()), before_rows)
        reg = self.lc.load()
        self.assertEqual(reg["sources"][e.id]["versions"]["2"]["state"], "pending")
        self.assertEqual(reg["sources"][e.id]["active_version"], 1)
        self.assertIsNone(reg["intent"])
        self.assertTrue(dl.ServeFilter(self.state).servable(e.sha256))
        self.lc.approve(e.id, 2, by="r")                           # and a retry works
        self.assertEqual(self.hashes(), {e2.sha256})

    def test_failure_during_the_swap_keeps_the_live_index_and_clears_the_journal(self):
        e = self.approve_v1()
        before_rows = sorted(self.live())
        self.ingest(V2)

        def boom(*a, **k):
            raise RuntimeError("disk full")
        orig, self.lc._swap = self.lc._swap, boom
        with self.assertRaises(dl.LifecycleError):
            self.lc.approve(e.id, 2, by="r")
        self.lc._swap = orig
        self.assertEqual(sorted(self.live()), before_rows)
        reg = self.lc.load()
        self.assertIsNone(reg["intent"])
        self.assertEqual(reg["sources"][e.id]["versions"]["2"]["state"], "pending")
        names = {c.name for c in chromadb.PersistentClient(path=str(self.db)).list_collections()}
        self.assertEqual(names, {"telangana-traffic-rules"})        # no staging or previous left behind
        self.assertEqual(self.lc.verify(), [])

    def test_unhealthy_replacement_is_not_swapped_in(self):
        e = self.approve_v1()
        self.ingest(V2)
        before_rows = sorted(self.live())
        orig = self.lc._verify
        calls = []

        def verify(col, expected, count):
            calls.append(1)
            if len(calls) == 2:       # the post-swap health check
                raise dl.LifecycleError("health check failed")
            return orig(col, expected, count)
        self.lc._verify = verify
        with self.assertRaises(dl.LifecycleError):
            self.lc.approve(e.id, 2, by="r")
        self.lc._verify = orig
        self.assertEqual(sorted(self.live()), before_rows)
        self.assertEqual(self.lc.verify(), [])


class RestartTests(Base):
    def test_state_survives_a_restart(self):
        e = self.approve_v1()
        self.ingest(V2)
        fresh = self.make()
        self.assertEqual(fresh.status(), {e.id: {"active": 1, "versions": {"1": "approved", "2": "pending"}}})
        fresh.approve(e.id, 2, by="r")
        self.assertEqual(self.make().verify(), [])

    def test_crash_between_the_two_renames_is_undone(self):
        e = self.approve_v1()
        e2, _ = self.ingest(V2)
        before = sorted(self.live())

        def crash(client, expected):
            btx = self.lc.btx
            client.get_collection(self.lc.collection, embedding_function=None).modify(name=btx.PREVIOUS)
            raise KeyboardInterrupt("power cut")
        self.lc._swap = crash
        with self.assertRaises(KeyboardInterrupt):
            self.lc.approve(e.id, 2, by="r")
        restarted = self.make()
        with self.assertRaises(dl.LifecycleError):                   # nothing else may run until recovered
            restarted.withdraw(e.id, 1, by="r")
        self.assertFalse(dl.ServeFilter(self.state).enabled and dl.ServeFilter(self.state).servable(e.sha256))  # fail closed
        self.assertEqual(restarted.recover()["action"], "aborted")
        self.assertEqual(sorted(self.live()), before)
        self.assertEqual(restarted.verify(), [])
        self.assertEqual(restarted.status()[e.id]["versions"]["2"], "pending")

    def test_crash_after_the_swap_is_committed_on_recovery(self):
        e = self.approve_v1()
        e2, _ = self.ingest(V2)

        def crash(*a, **k):
            raise KeyboardInterrupt("power cut")
        self.lc._write_snapshot = crash          # first thing that happens after the swap succeeded
        with self.assertRaises(KeyboardInterrupt):
            self.lc.approve(e.id, 2, by="r")
        restarted = self.make()
        self.assertEqual(restarted.recover()["action"], "committed")
        self.assertEqual(self.hashes(), {e2.sha256})
        self.assertEqual(restarted.status()[e.id], {"active": 2, "versions": {"1": "superseded", "2": "approved"}})
        self.assertEqual(restarted.verify(), [])
        self.assertEqual(restarted.recover()["action"], "none")

    def test_embedding_model_change_refuses_to_mix_vectors(self):
        e = self.approve_v1()
        self.ingest(V2)
        self.emb.embedder_id = "another-model"
        with self.assertRaises(dl.LifecycleError):
            self.lc.approve(e.id, 2, by="r")
        self.assertEqual(self.hashes(), {e.sha256})


class IndexModesTests(Base):
    def test_exact_and_hnsw_search_agree_and_see_only_active_chunks(self):
        e = self.approve_v1()
        self.ingest(V2)
        self.lc.approve(e.id, 2, by="r")
        col = chromadb.PersistentClient(path=str(self.db)).get_collection("telangana-traffic-rules", embedding_function=None)
        got = col.get(include=["embeddings", "documents", "metadatas"])
        exact = ExactVectorIndex(got["ids"], got["embeddings"], got["documents"], got["metadatas"], self.emb)
        q = self.emb.embed_query("Rule 1. Riders shall wear a protective helmet.")
        ex = exact.similarity_search_with_score  # signature takes text; use the embedding directly
        d = exact.distances(q)
        exact_top = got["ids"][int(np.argmin(d))]
        hnsw = col.query(query_embeddings=[q], n_results=3, include=["metadatas"])
        self.assertEqual(hnsw["ids"][0][0], exact_top)
        self.assertEqual({m["sha256"] for m in hnsw["metadatas"][0]}, {self.entry(V2).sha256})
        self.assertEqual(col.metadata.get("rag_profile"), "structured")

    def test_server_style_search_never_returns_a_superseded_or_withdrawn_text(self):
        e = self.approve_v1()
        self.ingest(V2)
        self.lc.approve(e.id, 2, by="r")
        col = chromadb.PersistentClient(path=str(self.db)).get_collection("telangana-traffic-rules", embedding_function=None)
        res = col.query(query_embeddings=[self.emb.embed_query("Riders shall wear a helmet")], n_results=10)
        self.assertFalse(any("Riders shall wear a helmet." in d for d in res["documents"][0]))


class ServeFilterTests(Base):
    def test_disabled_without_a_registry_directory(self):
        f = dl.ServeFilter(None)
        self.assertEqual((f.enabled, f.servable("x" * 64), f.digest()), (False, True, None))

    def test_fail_closed(self):
        f = dl.ServeFilter(self.state)
        self.assertFalse(f.servable("a" * 64))                        # no registry yet
        e = self.approve_v1()
        self.assertTrue(f.servable(e.sha256))
        self.assertFalse(f.servable("b" * 64))                        # unknown hash
        (self.state / "registry.json").write_text("{not json")
        self.assertFalse(f.servable(e.sha256))                        # unreadable registry
        self.assertEqual(f.digest(), "unreadable")

    def test_interrupted_operation_serves_nothing(self):
        e = self.approve_v1()
        reg = self.lc.load()
        reg["intent"] = {"op": "approve", "expected": []}
        self.lc._save(reg)
        self.assertFalse(dl.ServeFilter(self.state).servable(e.sha256))

    def test_picks_up_changes_made_by_another_process(self):
        f = dl.ServeFilter(self.state)
        e = self.approve_v1()
        self.assertTrue(f.servable(e.sha256))
        d1 = f.digest()
        self.lc.withdraw(e.id, 1, by="r")
        self.assertFalse(f.servable(e.sha256))
        self.assertNotEqual(f.digest(), d1)


class CacheIntegrationTests(Base):
    """The Stage 5 mechanisms follow lifecycle changes. The epoch below is built the way server.cache_epoch builds its
    own: the registry digest and the index fingerprint are inputs, so any lifecycle operation changes it."""

    def setUp(self):
        super().setUp()
        self.flt = dl.ServeFilter(self.state)
        self.cache = ac.AnswerCache(ac.Settings(mode="exact"))

    def epoch(self):
        c = chromadb.PersistentClient(path=str(self.db))
        names = {x.name for x in c.list_collections()}
        fp = None
        if "telangana-traffic-rules" in names:
            col = c.get_collection("telangana-traffic-rules", embedding_function=None)
            fp = (str(col.id), col.count())
        return ac.digest(self.flt.digest(), fp)

    def warm(self, question="what is the helmet rule", sha=None):
        ep = self.epoch()
        self.cache.note_epoch(ep)
        ok = self.cache.put(ac.normalize_query(question), ac.signature(question), None, ep, '{"answer":"x"}',
                            ("c1",), ("c1",), ((sha or "s", "tmvr-fixture"),))
        self.assertTrue(ok)
        return question

    def hit(self, question):
        ep = self.epoch()
        self.cache.note_epoch(ep)
        return self.cache.lookup_exact(ac.normalize_query(question), ep) is not None

    def test_approval_of_a_new_document_invalidates(self):
        e, _ = self.ingest(V1)
        q = self.warm()
        self.assertTrue(self.hit(q))
        self.lc.approve(e.id, 1, by="r")
        self.assertFalse(self.hit(q))
        self.assertGreaterEqual(self.cache.stats["invalidated_epoch"], 1)

    def test_amendment_invalidates(self):
        e = self.approve_v1()
        self.ingest(V2)
        q = self.warm()
        self.assertTrue(self.hit(q))
        self.assertTrue(self.hit(q))
        self.lc.approve(e.id, 2, by="r")
        self.assertFalse(self.hit(q))

    def test_withdrawal_invalidates(self):
        e = self.approve_v1()
        q = self.warm()
        self.lc.withdraw(e.id, 1, by="r")
        self.assertFalse(self.hit(q))

    def test_rollback_invalidates_answers_built_on_the_replaced_version(self):
        e = self.approve_v1()
        self.ingest(V2)
        self.lc.approve(e.id, 2, by="r")
        q = self.warm()
        self.assertTrue(self.hit(q))
        self.lc.rollback(e.id, 1, by="r")
        self.assertFalse(self.hit(q))

    def test_a_pending_ingestion_alone_changes_the_registry_digest_but_not_the_index(self):
        e = self.approve_v1()
        q = self.warm()
        d = self.flt.digest()
        self.ingest(V2)
        self.assertNotEqual(self.flt.digest(), d)        # conservative: the epoch moves, entries are rebuilt
        self.assertFalse(self.hit(q))

    def test_the_invalidate_callback_names_the_changed_documents(self):
        e = self.approve_v1()
        e2, _ = self.ingest(V2)
        self.invalidated.clear()
        self.lc.approve(e.id, 2, by="r")
        (shas, sid), = self.invalidated
        self.assertEqual((set(shas), sid), ({e.sha256, e2.sha256}, e.id))
        # and wired to the cache's own per-document invalidation
        self.cache.put("k", frozenset(), None, "E", "{}", ("c",), ("c",), ((e.sha256, e.id),))
        self.assertEqual(self.cache.invalidate_source(e.sha256), 1)


class StateMachineTests(unittest.TestCase):
    def test_transition_table_is_exactly_the_documented_one(self):
        self.assertEqual(set(dl.TRANSITIONS), {("pending", "approved"), ("pending", "rejected"), ("approved", "withdrawn"),
                                               ("approved", "superseded"), ("superseded", "approved")})
        for terminal in ("rejected", "withdrawn"):
            self.assertFalse(any(frm == terminal for frm, _ in dl.TRANSITIONS))


if __name__ == "__main__":
    unittest.main()
