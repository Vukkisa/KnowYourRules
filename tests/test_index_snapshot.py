"""Stage 7A: immutable index snapshots (backend/index_snapshot.py). Offline: tiny temporary Chroma directories from the Stage 6 test
fixtures, a hash-based fake embedder, a local directory as the object store, mocked HTTP for the R2 client. The real index, the real
lifecycle registry and the network are never touched."""
import gzip
import hashlib
import io
import json
import os
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path

import test_document_lifecycle as tdl

from backend import index_snapshot as snap

PRE = {"embed": None}


def tar_gz(entries):
    """entries: [(name, bytes, type)] -> tar.gz bytes (for forging hostile archives)."""
    raw = io.BytesIO()
    with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz, tarfile.open(fileobj=gz, mode="w") as tar:
        for name, data, kind in entries:
            info = tarfile.TarInfo(name)
            info.type = kind
            if kind == tarfile.SYMTYPE:
                info.linkname = "/etc/passwd"
            info.size = len(data) if kind == tarfile.REGTYPE else 0
            tar.addfile(info, io.BytesIO(data) if kind == tarfile.REGTYPE else None)
    return raw.getvalue()


class Fixture(tdl.Base):
    """self.db = tiny index (3 chunks, 8-dim vectors), self.state = its lifecycle registry, one approved version."""

    def setUp(self):
        super().setUp()
        self.approve_v1()
        self.store = snap.LocalObjectStore(self.tmp / "store")
        self.work = self.tmp / "work"

    def publish(self, **kw):
        args = dict(embed=self.emb.embed_documents, embedding_model="fake-embedder", family="fake-family", created_by="operator-a", doc_prefix="")
        args.update(kw)
        return snap.publish(kw.pop("store", None) or self.store, self.db, self.state, **{k: v for k, v in args.items() if k != "store"})

    def manager(self, **kw):
        return snap.SnapshotManager(kw.pop("store", self.store), kw.pop("work", self.work), **kw)

    def rewrite(self, mutate):
        """Replace the active manifest (and the pointer's checksum for it) after `mutate(manifest)`; used to forge states."""
        pointer = snap.parse_pointer(self.store.get_bytes("active.json"))
        manifest = json.loads(self.store.get_bytes(pointer["manifest_key"]))
        mutate(manifest)
        raw = snap.canonical_json(manifest)
        self.store.put_bytes(pointer["manifest_key"], raw)
        pointer["manifest_sha256"] = snap.sha256_bytes(raw)
        self.store.put_bytes("active.json", snap.canonical_json(pointer))
        return manifest

    def forge_archive(self, name, data):
        def mutate(m):
            self.store.put_bytes(m[name]["archive"], data)
            m[name].update(sha256=snap.sha256_bytes(data), size_bytes=len(data))
        self.rewrite(mutate)


class PublishTests(Fixture):
    def test_publish_writes_immutable_objects_manifest_and_pointer(self):
        m = self.publish()
        v = m["version"]
        for key in (f"manifests/{v}.json", f"snapshots/{v}/index.tar.gz", f"snapshots/{v}/lifecycle.tar.gz", "active.json"):
            self.assertTrue(self.store.exists(key), key)
        self.assertEqual((m["index"]["chunk_count"], m["embedding"]["dimensions"], m["embedding"]["model"], m["created_by"]), (3, 8, "fake-embedder", "operator-a"))
        self.assertEqual(len(m["embedding"]["probes"]), 3)
        self.assertEqual(snap.sha256_bytes(self.store.get_bytes(m["index"]["archive"])), m["index"]["sha256"])
        pointer = snap.parse_pointer(self.store.get_bytes("active.json"))
        self.assertEqual((pointer["version"], pointer["previous"]), (v, None))

    def test_a_second_publish_keeps_the_first_and_links_it_as_previous(self):
        first = self.publish(version="v1")
        second = self.publish(version="v2")
        pointer = snap.parse_pointer(self.store.get_bytes("active.json"))
        self.assertEqual((pointer["version"], pointer["previous"]["version"]), ("v2", "v1"))
        self.assertTrue(self.store.exists("snapshots/v1/index.tar.gz") and self.store.exists("manifests/v1.json"))
        self.assertEqual(first["index"]["sha256"], second["index"]["sha256"])   # deterministic archives: same content, same bytes

    def test_an_existing_version_is_never_overwritten(self):
        self.publish(version="v1")
        before = self.store.get_bytes("manifests/v1.json")
        with self.assertRaises(snap.SnapshotError):
            self.publish(version="v1")
        self.assertEqual(self.store.get_bytes("manifests/v1.json"), before)

    def test_refuses_an_empty_index_a_nameless_operator_and_a_model_that_cannot_reproduce_the_vectors(self):
        class Other(tdl.FakeEmbedder):
            @staticmethod
            def vec(text):
                return tdl.FakeEmbedder.vec("different " + text)
        with self.assertRaises(snap.SnapshotError) as cm:
            self.publish(embed=Other().embed_documents)
        self.assertEqual(cm.exception.state, "embedding_incompatible")
        with self.assertRaises(snap.SnapshotError):
            self.publish(created_by=" ")
        empty = self.tmp / "empty-db"
        import chromadb
        chromadb.PersistentClient(path=str(empty)).create_collection("telangana-traffic-rules")
        with self.assertRaises(snap.SnapshotError) as cm:
            snap.publish(self.store, empty, self.state, embed=self.emb.embed_documents, embedding_model="m", family="f", created_by="op")
        self.assertEqual(cm.exception.state, "index_invalid")
        self.assertFalse(self.store.exists("active.json"))   # nothing half-published

    def test_refuses_a_lifecycle_registry_the_server_would_reject(self):
        audit = self.state / "audit.jsonl"
        audit.write_text(audit.read_text()[:-5])
        with self.assertRaises(snap.SnapshotError) as cm:
            self.publish()
        self.assertEqual(cm.exception.state, "lifecycle_invalid")
        self.assertFalse(self.store.exists("active.json"))

    def test_live_directories_are_not_modified_and_the_lock_file_is_not_shipped(self):
        before = (snap.files_digest(self.db), snap.files_digest(self.state))
        m = self.publish()
        self.assertEqual((snap.files_digest(self.db), snap.files_digest(self.state)), before)
        path = self.tmp / "lc.tar.gz"
        path.write_bytes(self.store.get_bytes(m["lifecycle"]["archive"]))
        with tarfile.open(path) as t:
            names = t.getnames()
        self.assertIn("registry.json", names)
        self.assertFalse([n for n in names if n.endswith(".lock")])

    def test_rollback_repoints_the_pointer_and_records_the_displaced_version(self):
        self.publish(version="v1")
        self.publish(version="v2")
        snap.rollback(self.store, "v1", "operator-b")
        p = snap.parse_pointer(self.store.get_bytes("active.json"))
        self.assertEqual((p["version"], p["previous"]["version"], p["updated_by"]), ("v1", "v2", "operator-b"))
        with self.assertRaises(snap.ObjectMissing):
            snap.rollback(self.store, "v0", "operator-b")


class LoadTests(Fixture):
    def test_roundtrip_verifies_extracts_and_the_lifecycle_filter_agrees(self):
        m = self.publish()
        st = self.manager().activate()
        self.assertEqual((st.state, st.ready, st.version), ("ready", True, m["version"]), st.problems)
        self.assertTrue((st.db_dir / "chroma.sqlite3").is_file() and (st.lifecycle_dir / "registry.json").is_file())
        from backend import document_lifecycle as dl
        f = dl.ServeFilter(st.lifecycle_dir)
        h = f.health()
        self.assertEqual((h["state"], h["servable_documents"], h["ready"]), ("ok", 1, True))
        self.assertTrue(set(self.hashes()) and all(f.servable(x) for x in self.hashes()))
        self.assertFalse(f.servable("0" * 64))
        for k in ("download_and_verify", "extract_and_verify", "validate", "total"):
            self.assertIn(k, st.seconds)

    def test_extractions_left_by_an_earlier_process_are_removed_before_a_restore(self):
        """On a small /tmp (Vercel) leftover run directories filled the disk and the next restore failed with ENOSPC."""
        self.publish()
        stale = self.work / "run" / "old-version-8-aaaaaa"
        (stale / "index").mkdir(parents=True)
        (stale / "index" / "junk.bin").write_bytes(b"x" * 1024)
        st = self.manager().activate()
        self.assertEqual((st.state, st.ready), ("ready", True), st.problems)
        self.assertFalse(stale.exists())
        self.assertTrue((st.db_dir / "chroma.sqlite3").is_file())

    def test_an_old_private_index_copy_is_removed_and_a_fresh_one_is_kept(self):
        import tempfile, time
        self.publish()
        old = Path(tempfile.mkdtemp(prefix="kyr-snap-peek-"))
        fresh = Path(tempfile.mkdtemp(prefix="kyr-snap-peek-"))
        try:
            (old / "x.bin").write_bytes(b"x" * 1024)
            os.utime(old, (time.time() - 600, time.time() - 600))
            st = self.manager().activate()
            self.assertTrue(st.ready, st.problems)
            self.assertFalse(old.exists())
            self.assertTrue(fresh.exists())
        finally:
            shutil.rmtree(old, ignore_errors=True)
            shutil.rmtree(fresh, ignore_errors=True)

    def test_a_restore_never_removes_the_extraction_this_process_is_serving(self):
        self.publish()
        first = self.manager().activate()
        self.assertTrue(first.ready, first.problems)
        second = self.manager().activate()          # e.g. a reload while the first corpus is still in use
        self.assertTrue(second.ready, second.problems)
        self.assertTrue((first.db_dir / "chroma.sqlite3").is_file() and (first.lifecycle_dir / "registry.json").is_file())

    def test_a_failed_restore_still_leaves_no_extraction_behind(self):
        m = self.publish()
        self.forge_archive("index", b"not a tar archive")
        st = self.manager().activate()
        self.assertFalse(st.ready)
        run = self.work / "run"
        self.assertEqual(list(run.iterdir()) if run.is_dir() else [], [])

    def test_missing_pointer_manifest_and_archives_fail_closed_without_creating_anything(self):
        st = self.manager().activate()
        self.assertEqual((st.state, st.ready, st.db_dir), ("manifest_missing", False, None))
        m = self.publish()
        os.remove(self.tmp / "store" / m["index"]["archive"])
        st = self.manager().activate()
        self.assertEqual((st.state, st.db_dir), ("snapshot_missing", None))
        os.remove(self.tmp / "store" / "manifests" / f"{m['version']}.json")
        self.assertEqual(self.manager().activate().state, "manifest_missing")
        self.assertFalse((self.work / "run").exists())     # no runtime directory, empty or otherwise

    def test_every_kind_of_corruption_is_caught_before_anything_is_loaded(self):
        m = self.publish()
        archive = self.tmp / "store" / m["index"]["archive"]
        good = archive.read_bytes()
        bad = bytearray(good)
        bad[len(bad) // 2] ^= 0xFF
        for label, data in (("flipped byte", bytes(bad)), ("truncated", good[:-40]), ("padded", good + b"x"), ("empty", b"")):
            archive.write_bytes(data)
            st = self.manager(work=self.tmp / f"work-{label}").activate()
            self.assertEqual((st.state, st.ready, st.db_dir), ("checksum_mismatch", False, None), label)
        archive.write_bytes(good)
        self.assertEqual(self.manager(work=self.tmp / "work-ok").activate().state, "ready")

    def test_manifest_checksum_pointer_pin_and_schema(self):
        m = self.publish()
        mpath = self.tmp / "store" / "manifests" / f"{m['version']}.json"
        original = mpath.read_bytes()
        pin = snap.sha256_bytes(original)
        self.assertEqual(self.manager(pin_sha256=pin).activate().state, "ready")
        self.assertEqual(self.manager(pin_sha256="1" * 64, work=self.tmp / "w2").activate().state, "pin_mismatch")
        mpath.write_bytes(original.replace(b'"created_by": "operator-a"', b'"created_by": "someone-else"'))
        self.assertEqual(self.manager(work=self.tmp / "w3").activate().state, "checksum_mismatch")   # pointer checksum catches an edit
        mpath.write_bytes(b"not json")
        self.assertEqual(self.manager(work=self.tmp / "w4").activate().state, "checksum_mismatch")
        (self.tmp / "store" / "active.json").write_bytes(b'{"version": "../../x"}')
        self.assertEqual(self.manager(work=self.tmp / "w5").activate().state, "manifest_invalid")

    def test_manifest_claims_that_do_not_match_the_extracted_index_are_refused(self):
        self.publish()
        cases = [("chunk count", lambda m: m["index"].update(chunk_count=99), "index_invalid"),
                 ("dimensions", lambda m: m["embedding"].update(dimensions=7), "manifest_invalid"),
                 ("profile", lambda m: m["index"].update(rag_profile="baseline"), "index_invalid"),
                 ("tree digest", lambda m: m["index"].update(tree_digest="a" * 64), "checksum_mismatch"),
                 ("registry", lambda m: m["lifecycle"].update(registry_sha256="b" * 64), "lifecycle_invalid"),
                 ("lifecycle tree", lambda m: m["lifecycle"].update(tree_digest="c" * 64), "checksum_mismatch")]
        for label, mutate, state in cases:
            self.publish_fresh = self.rewrite(mutate)
            st = self.manager(work=self.tmp / f"w-{label}").activate()
            self.assertEqual((st.state, st.ready, st.db_dir), (state, False, None), label)
            self.setUp_store_again()

    def setUp_store_again(self):
        shutil.rmtree(self.tmp / "store")
        self.publish()

    def test_embedding_family_the_build_does_not_expect_is_refused(self):
        self.publish()
        st = self.manager(expected_family="nomic-embed-text-v1.5").activate()
        self.assertEqual(st.state, "embedding_incompatible")

    def test_hostile_archives_are_rejected_with_correct_checksums(self):
        self.publish()
        hostile = {"parent traversal": [("../evil", b"x", tarfile.REGTYPE)], "absolute": [("/tmp/evil", b"x", tarfile.REGTYPE)],
                   "symlink": [("link", b"", tarfile.SYMTYPE)], "dot segment": [("a/./b", b"x", tarfile.REGTYPE)],
                   "backslash": [("a\\b", b"x", tarfile.REGTYPE)]}
        for label, entries in hostile.items():
            self.forge_archive("lifecycle", tar_gz(entries))
            st = self.manager(work=self.tmp / f"hw-{label}").activate()
            self.assertEqual((st.state, st.db_dir), ("archive_invalid", None), label)
            self.assertFalse((self.tmp / "evil").exists() or Path("/tmp/evil").exists())
            self.setUp_store_again()

    def test_archive_that_unpacks_larger_than_declared_is_refused(self):
        self.publish()
        self.forge_archive("lifecycle", tar_gz([("registry.json", b"x" * 5000, tarfile.REGTYPE)]))
        self.rewrite(lambda m: m["lifecycle"].update(unpacked_bytes=100))
        self.assertEqual(self.manager().activate().state, "archive_invalid")

    def test_tampered_audit_history_is_caught_by_the_lifecycle_check_not_just_checksums(self):
        # an attacker who can rewrite the bucket can also fix the checksums; the lifecycle's own hash chain still fails
        m = self.publish()
        lc_tar = self.tmp / "lc.tar.gz"
        lc_tar.write_bytes(self.store.get_bytes(m["lifecycle"]["archive"]))
        work = self.tmp / "unpacked-lc"
        snap.safe_extract(lc_tar, work, 10 ** 8)
        audit = work / "audit.jsonl"
        audit.write_text(audit.read_text()[:-5])
        new_tar = self.tmp / "lc2.tar.gz"
        snap.make_archive(work, new_tar)
        data = new_tar.read_bytes()

        def mutate(manifest):
            self.store.put_bytes(manifest["lifecycle"]["archive"], data)
            manifest["lifecycle"].update(sha256=snap.sha256_bytes(data), size_bytes=len(data), tree_digest=snap.files_digest(work),
                                         unpacked_bytes=sum(p.stat().st_size for p in work.rglob("*") if p.is_file()))
        self.rewrite(mutate)
        st = self.manager().activate()
        self.assertEqual((st.state, st.db_dir), ("lifecycle_invalid", None))

    def test_unexpected_errors_never_look_ready(self):
        self.publish()

        class Exploding(snap.SnapshotManager):
            def _check_index(self, *a, **k):
                raise RuntimeError("boom")
        st = Exploding(self.store, self.work).activate()
        self.assertEqual((st.state, st.ready, st.db_dir), ("index_invalid", False, None))


class PendingOnlyTests(tdl.Base):
    def test_a_registry_with_no_approved_document_is_consistent_and_serves_nothing(self):
        e, r = self.ingest(tdl.V1)          # registered pending: in no index, approved nowhere
        h = snap.check_lifecycle_dir(self.state, {})
        self.assertEqual((h["state"], h["servable_documents"], h["ready"]), ("ok", 0, False))
        self.assertEqual(self.lc.load()["sources"][e.id]["versions"]["1"]["state"], "pending")


class UpdateAndRecoveryTests(Fixture):
    def test_a_failed_update_keeps_the_last_verified_snapshot_and_never_swaps_silently(self):
        self.publish(version="v1")
        self.assertEqual(self.manager().activate().version, "v1")
        self.publish(version="v2")
        (self.tmp / "store" / "snapshots" / "v2" / "index.tar.gz").write_bytes(b"corrupt")
        st = self.manager().activate()
        self.assertEqual((st.state, st.ready), ("checksum_mismatch", False))   # does NOT quietly serve v1
        self.assertTrue((self.work / "archives" / "v1" / "index.tar.gz").is_file())
        cur = json.loads((self.work / "current.json").read_text())
        self.assertEqual(cur["version"], "v1")                                  # the verified record is untouched

    def test_cached_snapshot_is_used_only_when_the_operator_allows_it_and_is_flagged_stale(self):
        self.publish(version="v1")
        self.assertTrue(self.manager().activate().ready)

        class Down(snap.ObjectStore):
            def get_stream(self, key):
                raise snap.StoreError("object store unreachable (ConnectionError)")
        st = snap.SnapshotManager(Down(), self.work).activate()
        self.assertEqual((st.state, st.ready), ("store_unavailable", False))
        st = snap.SnapshotManager(Down(), self.work, allow_stale=True).activate()
        self.assertEqual((st.state, st.stale, st.version), ("ready", True, "v1"))
        shutil.rmtree(self.work)
        self.assertEqual(snap.SnapshotManager(Down(), self.work, allow_stale=True).activate().state, "store_unavailable")   # no cache: nothing

    def test_only_the_active_and_one_previous_archive_set_are_kept(self):
        for v in ("v1", "v2", "v3"):
            self.publish(version=v)
            self.assertTrue(self.manager().activate().ready)
        kept = sorted(p.name for p in (self.work / "archives").iterdir())
        self.assertEqual(len(kept), 2)
        self.assertIn("v3", kept)

    def test_restart_after_recovery_loads_the_same_corpus(self):
        m = self.publish()
        a = self.manager(work=self.tmp / "boot-1").activate()
        b = self.manager(work=self.tmp / "boot-2").activate()
        self.assertEqual((a.version, b.version), (m["version"], m["version"]))
        self.assertEqual(snap.files_digest(a.lifecycle_dir), snap.files_digest(b.lifecycle_dir))


class EnvironmentTests(Fixture):
    def test_disabled_without_a_store_and_silent(self):
        st = snap.activate_from_env({})
        self.assertEqual((st.state, st.enabled, st.ready), ("disabled", False, False))

    def test_snapshot_mode_owns_the_directories_and_refuses_ambiguity(self):
        for name in ("TG_DB_DIR", "TG_LIFECYCLE_DIR"):
            st = snap.activate_from_env({"TG_SNAPSHOT_STORE": "local", "TG_SNAPSHOT_LOCAL_DIR": str(self.tmp / "store"), name: "/x"})
            self.assertEqual(st.state, "misconfigured", name)
            self.assertTrue(st.enabled and not st.ready)

    def test_misconfigurations_fail_closed(self):
        cases = [{"TG_SNAPSHOT_STORE": "ftp"}, {"TG_SNAPSHOT_STORE": "local"}, {"TG_SNAPSHOT_STORE": "r2"},
                 {"TG_SNAPSHOT_STORE": "r2", "R2_ACCOUNT_ID": "acc", "R2_BUCKET": "b", "R2_ACCESS_KEY_ID": "k"},
                 {"TG_SNAPSHOT_STORE": "local", "TG_SNAPSHOT_LOCAL_DIR": "/x", "TG_SNAPSHOT_PIN_SHA256": "nothex"}]
        for env in cases:
            st = snap.activate_from_env(env)
            self.assertEqual((st.state, st.ready), ("misconfigured", False), env)

    def test_end_to_end_from_the_environment_with_a_local_store(self):
        m = self.publish()
        env = {"TG_SNAPSHOT_STORE": "local", "TG_SNAPSHOT_LOCAL_DIR": str(self.tmp / "store"), "TG_SNAPSHOT_PREFIX": "",
               "TG_SNAPSHOT_WORK_DIR": str(self.tmp / "envwork"), "TG_SNAPSHOT_PIN_SHA256": snap.sha256_bytes(self.store.get_bytes(f"manifests/{m['version']}.json"))}
        st = snap.activate_from_env(env)
        self.assertEqual((st.state, st.version), ("ready", m["version"]), st.problems)
        public = json.dumps(st.public())
        self.assertNotIn(str(self.tmp), public)        # no filesystem paths in what /status shows
        self.assertEqual(st.public()["chunks"], 3)


class R2ClientTests(unittest.TestCase):
    SECRET = "r2-secret-THIS-MUST-NEVER-APPEAR"

    class Resp:
        def __init__(self, status=200, body=b""):
            self.status_code, self.body = status, body

        def iter_content(self, n):
            yield self.body

        def close(self):
            pass

    def client(self, *script, **kw):
        calls = []

        def http(method, url, headers=None, data=None, timeout=None, stream=False):
            calls.append({"method": method, "url": url, "headers": headers, "data": data})
            item = script[min(len(calls), len(script)) - 1]
            if isinstance(item, Exception):
                raise item
            return item
        import datetime
        c = snap.S3CompatStore("https://acc.r2.cloudflarestorage.com", "bucket", "AKIDTEST", self.SECRET, http=http,
                               clock=lambda: datetime.datetime(2026, 11, 14, 10, 0, 0, tzinfo=datetime.timezone.utc), **kw)
        return c, calls

    def test_sigv4_matches_the_published_aws_test_vector(self):
        h = snap.sigv4_headers("GET", "example.amazonaws.com", "/", {}, snap.sha256_bytes(b""), "AKIDEXAMPLE",
                               "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY", "us-east-1", "service", "20150830T123600Z", add_content_sha=False)
        self.assertTrue(h["Authorization"].endswith("Signature=5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31"))

    def test_requests_are_signed_path_style_and_never_carry_the_secret(self):
        c, calls = self.client(self.Resp(200, b"hello"))
        self.assertEqual(c.get_bytes("kyr/active.json"), b"hello")
        call = calls[0]
        self.assertEqual((call["method"], call["url"]), ("GET", "https://acc.r2.cloudflarestorage.com/bucket/kyr/active.json"))
        auth = call["headers"]["Authorization"]
        self.assertIn("Credential=AKIDTEST/20261114/auto/s3/aws4_request", auth)
        self.assertNotIn(self.SECRET, json.dumps(call["headers"]) + call["url"] + repr(c))

    def test_not_found_server_error_and_network_failure_are_distinct_and_safe(self):
        import requests
        c, _ = self.client(self.Resp(404))
        with self.assertRaises(snap.ObjectMissing):
            c.get_bytes("kyr/x")
        c, _ = self.client(self.Resp(500, self.SECRET.encode()))
        with self.assertRaises(snap.StoreError) as cm:
            c.get_bytes("kyr/x")
        self.assertNotIn(self.SECRET, str(cm.exception))
        c, _ = self.client(requests.ConnectionError(self.SECRET))
        with self.assertRaises(snap.StoreError) as cm:
            c.get_bytes("kyr/x")
        self.assertNotIn(self.SECRET, str(cm.exception))
        c, _ = self.client(requests.Timeout(self.SECRET))
        with self.assertRaises(snap.StoreError) as cm:
            c.exists("kyr/x")

    def test_head_put_and_key_validation(self):
        c, calls = self.client(self.Resp(200), self.Resp(404), self.Resp(200))
        self.assertTrue(c.exists("kyr/a"))
        self.assertFalse(c.exists("kyr/b"))
        c.put_bytes("kyr/c", b"data")
        self.assertEqual([x["method"] for x in calls], ["HEAD", "HEAD", "PUT"])
        self.assertEqual(calls[2]["data"], b"data")
        for key in ("../x", "/abs", "a//b", "a b", "a?b=1", "x" * 400):
            with self.assertRaises(snap.StoreError):
                c.get_bytes(key)

    def test_plain_http_endpoints_and_incomplete_credentials_are_refused(self):
        for args in (("http://acc.example", "b", "k", "s"), ("https://acc.example", "", "k", "s"), ("https://acc.example", "b", "", "s")):
            with self.assertRaises(snap.StoreError):
                snap.S3CompatStore(*args)
        snap.S3CompatStore("http://127.0.0.1:9000", "b", "k", "s")   # loopback (a local S3 emulator) is allowed

    def test_the_whole_load_path_works_against_a_signed_store(self):
        # served from memory, through the same SnapshotManager code as production
        objects = {}

        def http(method, url, headers=None, data=None, timeout=None, stream=False):
            key = url.split("/bucket/", 1)[1]
            if method == "PUT":
                objects[key] = data
                return self.Resp(200)
            return self.Resp(200, objects[key]) if key in objects else self.Resp(404)
        import datetime
        store = snap.PrefixedStore(snap.S3CompatStore("https://acc.r2.cloudflarestorage.com", "bucket", "AKID", self.SECRET, http=http,
                                                      clock=lambda: datetime.datetime.now(datetime.timezone.utc)), "kyr/")
        fixture = Fixture("run")   # reuse the tiny-index builder
        fixture.setUp()
        try:
            fixture.publish(store=store)
            st = snap.SnapshotManager(store, fixture.tmp / "r2work").activate()
            self.assertEqual((st.state, st.ready), ("ready", True), st.problems)
            self.assertTrue(all(k.startswith("kyr/") for k in objects))
        finally:
            shutil.rmtree(fixture.tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
