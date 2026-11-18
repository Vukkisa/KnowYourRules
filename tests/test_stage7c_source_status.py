"""Stage 7C (D12): the status file (git) and the lifecycle registry (R2 snapshot) must agree about every indexed document, and a
disagreement must be reported by category and must never make an unapproved document servable. Offline fixtures only. Neither file is
reconciled, approved or rewritten by anything here (the tests read copies in a temp directory)."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

import test_index_snapshot as tis
import test_source_status as tss
from backend import document_lifecycle as dl
from backend import source_status as ss

ROOT = Path(__file__).resolve().parent.parent
A, B, C = "a" * 64, "b" * 64, "c" * 64


def meta(sha, manifest_id, file, n=2):
    return [{"sha256": sha, "manifest_id": manifest_id, "source_file": file, "provision_id": f"Rule {i}"} for i in range(n)]


def lifecycle(path, versions):
    """versions: {source_id: (sha, state, chunk_count, file)}"""
    reg = {"schema_version": dl.SCHEMA, "sources": {sid: {"active_version": None, "versions": {"1": {"sha256": sha, "state": state, "chunk_count": n, "file": f}}}
                                                    for sid, (sha, state, n, f) in versions.items()}, "events": []}
    Path(path).write_text(json.dumps(reg))
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.status_path = self.dir / "source-status.json"
        self.lc_path = self.dir / "registry.json"

    def tearDown(self):
        self.tmp.cleanup()

    def status(self, *entries):
        self.status_path.write_text(json.dumps(tss.registry(*entries)))

    def good(self):
        self.status(tss.entry(A, "a.pdf"), tss.entry(B, "b.pdf"))
        lifecycle(self.lc_path, {"a.pdf": (A, "pending", 2, "a.pdf"), "b.pdf": (B, "pending", 2, "b.pdf")})
        return meta(A, "a.pdf", "a.pdf") + meta(B, "b.pdf", "b.pdf")

    def diag(self, metas, lc=True):
        return ss.diagnose(self.status_path, metas, self.lc_path if lc else None)

    def cats(self, metas, **kw):
        return sorted({d["category"] for d in self.diag(metas, **kw)})


class ConsistentStateTests(Base):
    def test_agreeing_files_produce_no_diagnostics(self):
        m = self.good()
        self.assertEqual(self.diag(m), [])
        s = ss.summarize(self.diag(m))
        self.assertEqual((s["consistent"], s["blocking"], s["categories"]), (True, [], {}))

    def test_the_shipped_status_file_agrees_with_the_shipped_index_metadata_and_registry(self):
        ev = ROOT / "eval/deployment/stage7b2/candidate/chunk_metadata.json"
        if not ev.is_file():
            self.skipTest("evidence file not present")
        metas = json.loads(ev.read_text())["metadatas"]
        # The evidence file is the frozen Telangana candidate index. The three Central sources are indexed later, beside it: their
        # chunk metadata is rebuilt from the Central manifest with the same chunker and flags (one row per indexed chunk).
        central = ROOT / "docs/legal-sources/telangana-traffic/CENTRAL-manifest.json"
        if central.is_file():
            from backend import build_telangana_index as bt, tg_ingest as ti, tg_manifest as tm
            corpus = central.parent / "source-documents"
            flags = bt.load_chunk_flags(central.parent / "CENTRAL-chunk-flags.json")
            for entry in tm.load_manifest(central):
                chunks = ti.chunk_document(ti.load_blocks(corpus / entry.file, entry.format, entry.file), entry)
                bt.apply_chunk_flags(chunks, [f for f in flags if f["match"]["manifest_id"] == entry.id])
                metas = metas + [c.metadata for c in chunks]
        d = ss.diagnose(ROOT / "legal-status/source-status.json", metas, ROOT / "legal/lifecycle/registry.json")
        self.assertEqual(d, [])


class MismatchCategoryTests(Base):
    def test_a_missing_status_entry_is_blocking(self):
        m = self.good()
        self.status(tss.entry(A, "a.pdf"))
        self.assertIn(ss.MISSING_ENTRY, self.cats(m))
        self.assertIn(ss.MISSING_ENTRY, ss.summarize(self.diag(m))["blocking"])

    def test_an_extra_status_entry_is_reported_but_does_not_block(self):
        m = self.good()
        self.status(tss.entry(A, "a.pdf"), tss.entry(B, "b.pdf"), tss.entry(C, "c.pdf"))
        d = self.diag(m)
        self.assertEqual([x["category"] for x in d], [ss.EXTRA_ENTRY])
        self.assertEqual(ss.summarize(d)["blocking"], [])

    def test_a_changed_hash_is_blocking_and_names_both_prefixes(self):
        m = self.good()
        self.status(tss.entry(C, "a.pdf"), tss.entry(B, "b.pdf"))                 # a.pdf now recorded with another hash
        d = [x for x in self.diag(m) if x["category"] == ss.HASH_MISMATCH]
        self.assertEqual(len(d), 1)
        self.assertIn("aaaaaaaaaaaa", d[0]["detail"])
        self.assertIn("cccccccccccc", d[0]["detail"])
        self.assertNotIn(A, d[0]["detail"])                                         # prefixes only, never full hashes
        self.assertIn(ss.HASH_MISMATCH, ss.summarize(self.diag(m))["blocking"])

    def test_a_changed_manifest_id_is_detected_and_blocking(self):
        m = self.good()
        e = tss.entry(A, "a.pdf")
        e["manifest_id"] = "some-other-document"
        self.status(e, tss.entry(B, "b.pdf"))
        self.assertIn(ss.MANIFEST_ID_MISMATCH, self.cats(m))
        self.assertIn(ss.MANIFEST_ID_MISMATCH, ss.summarize(self.diag(m))["blocking"])

    def test_the_load_path_also_rejects_a_changed_manifest_id(self):
        m = self.good()
        e = tss.entry(A, "a.pdf")
        e["manifest_id"] = "some-other-document"
        self.status(e, tss.entry(B, "b.pdf"))
        reg = ss.load(self.status_path, m)
        self.assertFalse(reg.valid)                                                 # an invalid registry means: nothing is answered
        self.assertTrue(any("manifest id mismatch" in x for x in reg.errors))

    def test_a_renamed_source_file_is_reported(self):
        m = self.good()
        self.status(tss.entry(A, "renamed.pdf"), tss.entry(B, "b.pdf"))
        self.assertIn(ss.FILE_NAME_MISMATCH, self.cats(m))

    def test_conflicting_status_a_current_label_on_a_pending_source_is_reported(self):
        m = self.good()
        self.status(tss.entry(A, "a.pdf", status="verified_current"), tss.entry(B, "b.pdf"))
        d = [x for x in self.diag(m) if x["category"] == ss.STATUS_CONFLICT]
        self.assertEqual(len(d), 1)
        self.assertIn("pending", d[0]["detail"])
        # the label alone can never present the text as current: without a signed approval binding it is shown as unconfirmed
        reg = ss.load(self.status_path, m)
        w = ss.warning_text(reg.lookup(A))
        self.assertEqual(reg.lookup(A).status, "verified_current")
        self.assertFalse(ss.warning_text(reg.lookup(A), trust_verified=False) is None)   # unconfirmed: it still warns

    def test_stale_registry_state_is_reported_by_hash_and_by_count(self):
        m = self.good()
        lifecycle(self.lc_path, {"a.pdf": (A, "pending", 2, "a.pdf"), "b.pdf": (C, "pending", 2, "b.pdf")})        # b.pdf's hash is stale
        self.assertIn(ss.LIFECYCLE_UNKNOWN, self.cats(m))
        lifecycle(self.lc_path, {"a.pdf": (A, "pending", 5, "a.pdf"), "b.pdf": (B, "pending", 2, "b.pdf")})        # a.pdf's chunk count is stale
        self.assertIn(ss.LIFECYCLE_COUNT_MISMATCH, self.cats(m))


class UnreadableInputTests(Base):
    def test_malformed_json_is_reported_not_raised(self):
        self.status_path.write_text("{ this is not json")
        d = self.diag([])
        self.assertEqual([x["category"] for x in d], [ss.MALFORMED_REGISTRY])
        self.status_path.write_bytes(b"\xff\xfe\x00")
        self.assertEqual([x["category"] for x in self.diag([])], [ss.MALFORMED_REGISTRY])

    def test_a_missing_or_schema_invalid_status_file_is_reported(self):
        self.assertEqual([x["category"] for x in ss.diagnose(self.dir / "absent.json", [])], [ss.ABSENT_REGISTRY])
        self.status_path.write_text(json.dumps({"schema_version": 1}))
        self.assertEqual([x["category"] for x in self.diag([])], [ss.INVALID_REGISTRY])
        doc = tss.registry(tss.entry(A, "a.pdf"))
        doc["entries"][0]["status"] = "approved"                                    # not a status this registry knows
        self.status_path.write_text(json.dumps(doc))
        self.assertEqual([x["category"] for x in self.diag([])], [ss.INVALID_REGISTRY])

    def test_an_unreadable_lifecycle_registry_is_reported(self):
        m = self.good()
        self.lc_path.write_text("garbage")
        self.assertIn(ss.LIFECYCLE_UNREADABLE, self.cats(m))
        self.assertIn(ss.LIFECYCLE_UNREADABLE, self.cats(m) )

    def test_every_blocking_category_makes_the_registry_invalid_or_is_reported_as_blocking(self):
        self.assertEqual(ss.BLOCKING, {ss.ABSENT_REGISTRY, ss.MALFORMED_REGISTRY, ss.INVALID_REGISTRY, ss.MISSING_ENTRY, ss.HASH_MISMATCH, ss.MANIFEST_ID_MISMATCH})
        for cat in (ss.EXTRA_ENTRY, ss.STATUS_CONFLICT, ss.LIFECYCLE_UNKNOWN, ss.LIFECYCLE_COUNT_MISMATCH, ss.FILE_NAME_MISMATCH, ss.LIFECYCLE_UNREADABLE):
            self.assertNotIn(cat, ss.BLOCKING)


class NothingBecomesServableTests(Base):
    """The status file has no vote on eligibility; the lifecycle registry does, and it is fail-closed."""

    def real_registry_copy(self):
        src = ROOT / "legal" / "lifecycle"
        if not (src / "registry.json").is_file():
            self.skipTest("the real lifecycle registry is not present")
        import shutil
        dst = self.dir / "real-registry"
        shutil.copytree(src, dst)
        reg = json.loads((dst / "registry.json").read_text())
        counts = {r["sha256"]: r["chunk_count"] for s in reg["sources"].values() for r in s["versions"].values()}
        return dst, reg, counts

    def test_no_status_file_content_can_change_which_sources_are_servable(self):
        """Servability comes from the lifecycle registry alone (approved + active version). Whatever a status file says,
        including "verified_current", the served set is exactly the registry's approved, active versions. (The pending and
        quarantined cases are covered with temporary registries in test_lifecycle_*.)"""
        dst, reg, counts = self.real_registry_copy()
        approved = {r["sha256"] for s in reg["sources"].values() for v, r in s["versions"].items()
                    if r["state"] == "approved" and str(v) == str(s.get("active_version"))}
        self.assertTrue(approved <= set(counts))
        metas = [m for h, n in counts.items() for m in meta(h, "doc-" + h[:6], "f-" + h[:6] + ".pdf", n)]
        for variant in ("verified_current", "unverified_snapshot", "official_text_commencement_unconfirmed"):
            self.status(*[tss.entry(h, "f-" + h[:6] + ".pdf", status=variant) for h in counts])
            f = dl.ServeFilter(dst)
            f.reconcile(dict(counts))
            h = f.health()
            self.assertEqual((h["state"], h["servable_documents"]), ("ok", len(approved)), variant)
            self.assertEqual({x for x in counts if f.servable(x)}, approved, variant)
            ss.diagnose(self.status_path, metas, dst / "registry.json")                                      # diagnosing changes nothing about eligibility
            self.assertEqual({x for x in counts if f.servable(x)}, approved, variant)

    def test_a_hash_the_registry_does_not_know_is_not_servable(self):
        dst, reg, counts = self.real_registry_copy()
        f = dl.ServeFilter(dst)
        f.reconcile({**counts, C: 2})
        self.assertFalse(f.servable(C))
        self.assertFalse(f.servable(None))
        self.assertFalse(f.servable("not-a-hash"))

    def test_an_index_that_disagrees_with_a_pending_source_still_serves_nothing(self):
        dst, reg, counts = self.real_registry_copy()
        h = next(iter(counts))
        f = dl.ServeFilter(dst)
        f.reconcile({**counts, h: counts[h] + 1})
        self.assertFalse(f.servable(h))
        self.assertFalse(f.health()["ready"])

    def test_an_unreadable_or_missing_registry_serves_nothing(self):
        self.lc_path.write_text("garbage")
        f = dl.ServeFilter(self.dir)
        self.assertFalse(f.servable(A))
        self.assertFalse(f.health()["ready"])
        f2 = dl.ServeFilter(self.dir / "nowhere")
        self.assertFalse(f2.servable(A))

    def test_diagnosis_modifies_neither_file(self):
        m = self.good()
        before = (self.status_path.read_bytes(), self.lc_path.read_bytes())
        self.diag(m)
        ss.load(self.status_path, m)
        self.assertEqual(before, (self.status_path.read_bytes(), self.lc_path.read_bytes()))


class ApprovedSourceMismatchTests(tis.Fixture):
    """An APPROVED source whose restored chunks disagree with the registry stops being served (the one case where a mismatch could matter)."""

    def test_count_mismatch_on_an_approved_source_is_reported_and_unserved(self):
        from collections import Counter
        from backend import index_snapshot as snap
        counts = dict(snap._chroma_facts(self.db)["counts"])
        f = dl.ServeFilter(self.state)
        f.reconcile(Counter(counts))
        sha = next(iter(counts))
        self.assertTrue(f.servable(sha))                                            # approved and consistent
        f.reconcile(Counter({**counts, sha: counts[sha] + 1}))
        self.assertEqual(f.health()["state"], "index_mismatch")
        self.assertFalse(f.servable(sha))
        f.reconcile(Counter({k: v for k, v in counts.items() if k != sha}))         # the index lost the document
        self.assertFalse(f.servable(sha))


if __name__ == "__main__":
    unittest.main()
