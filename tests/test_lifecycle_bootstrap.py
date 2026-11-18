"""Stage 6B: enrolling an existing index into the lifecycle registry. A source is approved only when an approval basis is given
AND it passes every other check (unambiguous id and file, known to the source-status registry, corpus hash). Everything else is
quarantined: in the index, never served. No signature or key is involved; the basis is a recorded, unauthenticated statement."""
import json
import shutil
import unittest
from pathlib import Path

import chromadb
import test_document_lifecycle as tdl
from test_document_lifecycle import V1, V2, fake_chunker

from backend import document_lifecycle as dl

BASIS = "synthetic approval basis for tests: a recorded statement, not a credential"
OTHER = "Rule 9. A second document rule.\nRule 10. Another rule."
THIRD = "Rule 20. A third document rule."


class BootBase(tdl.Base):
    def setUp(self):
        super().setUp()
        self.fixed = lambda: "2026-11-13T00:00:00Z"
        self.lc.clock = self.fixed
        # an "existing index": three sources indexed by an earlier process, with no registry
        scratch = dl.Lifecycle(self.tmp / "seed-state", self.db, embeddings=self.emb, chunker=fake_chunker)
        self.entries = {}
        for sid, name, text in (("src-a", "a.txt", V1), ("src-b", "b.txt", OTHER), ("src-c", "c.txt", THIRD)):
            e = self.entry(text, source=sid, name=name)
            scratch.ingest(e, self.corpus, by="seed")
            scratch.approve(sid, 1, by="seed")
            self.entries[sid] = e
        shutil.rmtree(self.tmp / "seed-state")
        self.emb.embedded.clear()
        self.metas = [m for _, _, m in self.live()]
        self.live_ids = sorted(i for i, _, _ in self.live())

    def tree(self):
        return dl.tree_digest(self.db)

    def servable(self):
        return dl.Lifecycle.servable_hashes(self.lc.load())

    def status_file(self, drop=None, wrong_id=None):
        entries = []
        for sid, e in self.entries.items():
            if sid == drop:
                continue
            entries.append({"manifest_id": "other" if sid == wrong_id else sid, "file": e.file, "sha256": e.sha256,
                            "status": "unverified_snapshot"})
        path = self.tmp / "source-status.json"
        path.write_text(json.dumps({"schema_version": 1, "entries": entries}))
        return path


class DryRunTests(BootBase):
    def test_dry_run_maps_every_source_and_changes_nothing(self):
        before = self.tree()
        plan = self.lc.plan_bootstrap(BASIS, self.corpus, self.status_file(drop="src-b"))
        self.assertEqual(self.tree(), before)
        self.assertFalse(self.state.exists())
        self.assertEqual((plan["index"]["rows"], plan["index"]["sources"], plan["index"]["hashes"]), (len(self.live_ids), 3, 3))
        t = plan["totals"]
        self.assertEqual((t["verified"], t["quarantined"], t["missing_approval"], t["hash_mismatch"], t["ambiguous"]),
                         (2, 1, 0, 0, 0))
        by = {e["source_id"]: e for e in plan["entries"]}
        self.assertEqual((by["src-a"]["status"], by["src-a"]["version"], by["src-a"]["target_state"]), ("verified", 1, "approved"))
        self.assertEqual(by["src-b"]["target_state"], "pending")
        self.assertIn("hash unknown to the source-status registry", " ".join(by["src-b"]["reasons"]))
        self.assertEqual((plan["approval"]["state"], plan["approval"]["basis"]), ("verified", BASIS))
        self.assertEqual(sum(e["chunks"] for e in plan["entries"]), len(self.live_ids))
        self.assertEqual(sorted(i for e in plan["entries"] for i in e["chunk_ids"]), self.live_ids)

    def test_no_basis_means_everything_is_quarantined(self):
        for basis in (None, "", "   "):
            plan = self.lc.plan_bootstrap(basis)
            self.assertEqual((plan["approval"]["state"], plan["totals"]["verified"], plan["totals"]["quarantined"]), ("absent", 0, 3))
            self.assertEqual(plan["totals"]["missing_approval"], 3)

    def test_effective_date_only_when_the_source_metadata_has_it(self):
        plan = self.lc.plan_bootstrap(None)
        self.assertTrue(all(e["effective_date"] is None for e in plan["entries"]))


class EvidenceFailsClosedTests(BootBase):
    def quarantined_all(self, basis, **kw):
        plan = self.lc.plan_bootstrap(basis, **kw)
        self.assertEqual((plan["totals"]["verified"], plan["totals"]["quarantined"]), (0, 3), plan["approval"])
        return plan

    def test_a_missing_or_malformed_basis_approves_nothing(self):
        for basis in (None, "", "  \n ", 12, ["basis"]):
            self.assertEqual(self.quarantined_all(basis)["approval"]["state"], "absent", basis)
        for basis in ("x" * (dl.MAX_BASIS + 1), "bad\x00basis"):
            self.assertEqual(self.quarantined_all(basis)["approval"]["state"], "invalid", basis[:12])

    def test_hash_mismatch_missing_source_file_and_wrong_file_name(self):
        sf = self.status_file()
        (self.corpus / "b.txt").write_text("changed on disk")
        (self.corpus / "c.txt").unlink()
        plan = self.lc.plan_bootstrap(BASIS, self.corpus, sf)
        by = {e["source_id"]: e for e in plan["entries"]}
        self.assertEqual(by["src-a"]["status"], "verified")
        self.assertIn("hash mismatch", " ".join(by["src-b"]["reasons"]))
        self.assertIn("source file not found", " ".join(by["src-c"]["reasons"]))
        self.assertEqual(plan["totals"]["hash_mismatch"], 1)

    def test_source_status_registry_mismatches_quarantine(self):
        plan = self.lc.plan_bootstrap(BASIS, source_status_file=self.status_file(drop="src-b", wrong_id="src-c"))
        by = {e["source_id"]: e["reasons"] for e in plan["entries"]}
        self.assertIn("hash unknown to the source-status registry", " ".join(by["src-b"]))
        self.assertIn("different manifest id", " ".join(by["src-c"]))
        self.assertEqual(by["src-a"], [])


class AmbiguityTests(tdl.Base):
    def raw_index(self, rows):
        c = chromadb.PersistentClient(path=str(self.db))
        col = c.create_collection("telangana-traffic-rules", metadata={"rag_profile": "structured"}, embedding_function=None)
        base = dict(state="Telangana", jurisdiction="Telangana", title="T", provision_id="Rule 1", location="x#1",
                    answer_eligible=True, document_type="Rules")
        col.add(ids=[f"id{i}" for i in range(len(rows))], documents=[f"doc {i}" for i in range(len(rows))],
                metadatas=[dict(base, **r) for r in rows], embeddings=[[0.1 * (i + 1), 0.2] for i in range(len(rows))])

    def test_ambiguous_and_unmapped_sources_are_quarantined_never_approved(self):
        a, b = "a" * 64, "b" * 64
        self.raw_index([
            dict(sha256=a, manifest_id="same-id", source_file="x.txt"),
            dict(sha256=b, manifest_id="same-id", source_file="x.txt"),            # one id, two contents
            dict(sha256="c" * 64, manifest_id="m1", source_file="y.txt"),
            dict(sha256="c" * 64, manifest_id="m2", source_file="y.txt"),          # one content, two ids
            dict(sha256="d" * 64, manifest_id="m3", source_file="p.txt"),
            dict(sha256="d" * 64, manifest_id="m3", source_file="q.txt"),          # one content, two file names
            dict(sha256="not-a-hash", manifest_id="m4", source_file="z.txt"),      # no valid hash
        ])
        plan = self.lc.plan_bootstrap(BASIS)
        self.assertEqual(plan["totals"]["verified"], 0)
        reasons = " | ".join(r for e in plan["entries"] for r in e["reasons"])
        for text in ("different contents", "ambiguous source id", "ambiguous source file name", "no valid sha256"):
            self.assertIn(text, reasons)
        self.assertIn("unmapped-no-hash", {e["source_id"] for e in plan["entries"]})
        res = self.lc.bootstrap("op", BASIS, allow_quarantine=True)
        self.assertEqual(res["verified"], 0)
        self.assertEqual(res["result"]["not_registrable"], 1)
        self.assertNotIn("unmapped-no-hash", self.lc.load()["sources"])
        self.assertEqual(dl.Lifecycle.servable_hashes(self.lc.load()), set())
        self.assertEqual(dl.ServeFilter(self.state).servable("a" * 64), False)


class ExecuteTests(BootBase):
    def test_refuses_to_register_unresolved_sources_without_an_explicit_allowance(self):
        with self.assertRaises(dl.LifecycleError):
            self.lc.bootstrap("op", None)
        # Stage 6C: taking the lifecycle lock creates the state directory and its lock file, so the property pinned here is
        # that the refused run registered nothing (no registry, no snapshots), not that the directory is absent.
        self.assertFalse((self.state / "registry.json").exists())
        self.assertFalse((self.state / "versions").exists())

    def test_requires_a_named_operator(self):
        with self.assertRaises(dl.LifecycleError):
            self.lc.bootstrap(" ", BASIS)

    def test_verified_sources_are_approved_with_evidence_and_the_rest_are_quarantined(self):
        sha_a = self.entries["src-a"].sha256
        before = self.tree()
        res = self.lc.bootstrap("operator-1", BASIS, self.corpus, self.status_file(drop="src-b", wrong_id="src-c"),
                                note="first enrolment", allow_quarantine=True)
        self.assertEqual((res["verified"], res["quarantined"], res["result"]["registered"]), (1, 2, 3))
        self.assertEqual(self.tree(), before)                         # the index was not touched
        self.assertEqual(self.emb.embedded, [])                       # no embeddings were generated
        reg = self.lc.load()
        rec = reg["sources"]["src-a"]["versions"]["1"]
        self.assertEqual((rec["state"], rec["sha256"], reg["sources"]["src-a"]["active_version"]), ("approved", sha_a, 1))
        ev = rec["history"][-1]["evidence"]
        self.assertEqual((rec["history"][-1]["by"], ev), ("operator-1", {"approval_basis": BASIS}))
        q = reg["sources"]["src-b"]["versions"]["1"]
        self.assertEqual((q["state"], reg["sources"]["src-b"]["active_version"], q["quarantine"]["in_index"]), ("pending", None, True))
        self.assertIn("hash unknown to the source-status registry", q["quarantine"]["reasons"][0])
        self.assertEqual(self.servable(), {sha_a})
        flt = dl.ServeFilter(self.state)
        self.assertTrue(flt.servable(sha_a))
        self.assertFalse(flt.servable(self.entries["src-b"].sha256))
        self.assertFalse(flt.servable(self.entries["src-c"].sha256))
        self.assertEqual(reg["bootstrap"]["by"], "operator-1")
        self.assertEqual(self.lc.verify(), [])

    def test_chunk_ids_and_embeddings_are_preserved_for_rollback(self):
        a = BASIS
        self.lc.bootstrap("op", a)
        snap = self.lc._read_snapshot(self.entries["src-a"].sha256)
        live = {i: d for i, d, m in self.live() if m["sha256"] == self.entries["src-a"].sha256}
        self.assertEqual(sorted(c["id"] for c in snap["chunks"]), sorted(live))     # the index's own ids
        self.assertTrue(all(c["embedding"] for c in snap["chunks"]))

    def test_rerun_is_idempotent(self):
        a = BASIS
        self.lc.bootstrap("op", a)
        first = (self.state / "registry.json").read_bytes()
        res = self.lc.bootstrap("op", a)
        self.assertEqual(res["result"], {"registered": 0, "upgraded": 0, "unchanged": 3})
        self.assertEqual((self.state / "registry.json").read_bytes(), first)
        reg = self.lc.load()
        self.assertEqual(sum(len(s["versions"]) for s in reg["sources"].values()), 3)
        self.assertEqual(len(reg["events"]), 3)

    def test_later_evidence_upgrades_a_quarantined_source_without_duplicating_it(self):
        self.lc.bootstrap("op", None, allow_quarantine=True)
        self.assertEqual(self.servable(), set())
        res = self.lc.bootstrap("op", BASIS, source_status_file=self.status_file(drop="src-a", wrong_id="src-c"),
                                allow_quarantine=True)
        self.assertEqual((res["result"]["upgraded"], res["result"]["registered"]), (1, 0))
        reg = self.lc.load()
        self.assertEqual(self.servable(), {self.entries["src-b"].sha256})
        self.assertEqual(len(reg["sources"]["src-b"]["versions"]), 1)
        self.assertEqual([h["state"] for h in reg["sources"]["src-b"]["versions"]["1"]["history"]], ["pending", "approved"])
        self.assertNotIn("quarantine", reg["sources"]["src-b"]["versions"]["1"])
        self.assertEqual(self.lc.verify(), [])

    def test_interrupted_bootstrap_leaves_nothing_servable_and_resumes(self):
        a = BASIS
        calls = []
        orig = self.lc._snapshot_rows

        def flaky(*args, **kw):
            calls.append(1)
            if len(calls) == 2:
                raise KeyboardInterrupt("power cut")
            return orig(*args, **kw)
        self.lc._snapshot_rows = flaky
        with self.assertRaises(KeyboardInterrupt):
            self.lc.bootstrap("op", a)
        self.assertFalse((self.state / "registry.json").exists())          # no half registry
        self.assertFalse(dl.ServeFilter(self.state).servable(self.entries["src-a"].sha256))   # fail closed meanwhile
        self.lc._snapshot_rows = orig
        res = self.lc.bootstrap("op", a)
        self.assertEqual(res["result"]["registered"], 3)
        self.assertEqual(len(self.lc.load()["sources"]), 3)
        self.assertEqual(self.lc.verify(), [])

    def test_a_corrupt_registry_exposes_nothing_and_is_never_overwritten(self):
        a = BASIS
        self.lc.bootstrap("op", a)
        flt = dl.ServeFilter(self.state)
        self.assertTrue(flt.servable(self.entries["src-a"].sha256))
        (self.state / "registry.json").write_text('{"schema_version": 1, "sources": ')
        self.assertFalse(flt.servable(self.entries["src-a"].sha256))
        with self.assertRaises(dl.LifecycleError):
            self.lc.bootstrap("op", a)
        self.assertTrue((self.state / "registry.json").read_text().startswith('{"schema_version": 1, "sources": '))

    def test_read_only_commands_leave_the_index_byte_identical(self):
        # Opening a Chroma directory rewrites its files even to read it; verify, status, recover and the dry run must not.
        a = BASIS
        self.lc.bootstrap("op", a)
        before = self.tree()
        for _ in range(2):
            self.assertEqual(self.lc.verify(), [])
            self.lc.status()
            self.assertEqual(self.lc.recover(), {"action": "none"})
            self.lc.plan_bootstrap(a)
            self.assertEqual(self.tree(), before)

    def test_the_enrolled_index_stays_recoverable_and_manageable(self):
        a = BASIS
        self.lc.bootstrap("op", a)
        orig_ids = self.live_ids
        e2 = self.entry(V2, source="src-a", name="a.txt")
        self.lc.ingest(e2, self.corpus, by="r")
        self.lc.approve("src-a", 2, by="r")
        self.assertNotIn(self.entries["src-a"].sha256, self.hashes())
        self.lc.rollback("src-a", 1, by="r")
        self.assertEqual(sorted(i for i, _, _ in self.live()), orig_ids)       # same rows, same ids as before enrolment
        self.assertEqual(self.lc.verify(), [])

    def test_quarantined_legacy_documents_cannot_be_approved_only_rejected(self):
        self.lc.bootstrap("op", None, allow_quarantine=True)
        with self.assertRaises(dl.LifecycleError):
            self.lc.approve("src-b", 1, by="op")
        out = self.lc.reject("src-b", 1, by="op", note="not part of the corpus")
        self.assertTrue(out["chunks_removed"])
        self.assertNotIn(self.entries["src-b"].sha256, self.hashes())
        self.assertEqual(self.lc.verify(), [])

    def test_a_quarantined_document_is_present_in_the_index_but_never_served(self):
        self.lc.bootstrap("op", None, allow_quarantine=True)
        self.assertEqual(self.hashes(), {e.sha256 for e in self.entries.values()})
        flt = dl.ServeFilter(self.state)
        self.assertFalse(any(flt.servable(h) for h in self.hashes()))


class CliTests(BootBase):
    def test_dry_run_command_prints_a_summary_and_writes_the_plan(self):
        out = []
        report = self.tmp / "plan.json"
        before = self.tree()
        code = dl.main(["--state-dir", str(self.state), "--db-dir", str(self.db), "bootstrap-dry-run", "--report", str(report)],
                       out=out.append, embeddings=self.emb)
        self.assertEqual(code, 0)
        summary = json.loads(out[0])
        self.assertEqual(summary["totals"]["quarantined"], 3)
        self.assertEqual(len(json.loads(report.read_text())["entries"]), 3)
        self.assertNotIn("_rows", json.loads(report.read_text()))
        self.assertEqual((self.tree(), self.state.exists()), (before, False))

    def test_bootstrap_command_requires_the_allowance_and_a_name(self):
        out = []
        argv = ["--state-dir", str(self.state), "--db-dir", str(self.db), "bootstrap", "--by", "op"]
        self.assertEqual(dl.main(argv, out=out.append, embeddings=self.emb), 1)
        self.assertIn("FAILED", out[-1])
        self.assertEqual(dl.main(argv + ["--allow-quarantine"], out=out.append, embeddings=self.emb), 0)
        self.assertTrue((self.state / "registry.json").is_file())


if __name__ == "__main__":
    unittest.main()
