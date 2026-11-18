"""Stage 7B: the persistence layer under failure. Offline: tiny Chroma indexes, a hash-based fake embedder, a local directory (or a
fake in-memory S3 server) as the object store. The real index, the real registry and every network are never touched.
What is proven: an interrupted, corrupted or failed publish can never change what a server loads; a failed or broken download never
yields a corpus; nothing in this code deletes an object; a cold start is reproducible."""
import datetime
import hashlib
import json
import shutil
import unittest
from pathlib import Path

import requests

import test_cloud_readiness as tcr
import test_index_snapshot as tis
from backend import index_snapshot as snap


class ScriptedStore(snap.ObjectStore):
    """Wraps a real store and misbehaves on demand. `calls` records every operation."""

    def __init__(self, inner):
        self.inner, self.calls = inner, []
        self.fail_put, self.corrupt_put, self.drop_put, self.break_stream = set(), set(), set(), {}

    def _match(self, key, names):
        return any(n in key for n in names)

    def get_stream(self, key):
        self.calls.append(("GET", key))
        broken = next((n for n in list(self.break_stream) if n in key and self.break_stream[n] > 0), None)
        for i, block in enumerate(self.inner.get_stream(key)):
            if broken and i >= 0:
                self.break_stream[broken] -= 1
                yield block[: max(1, len(block) // 3)]
                raise snap.StoreError("object store read failed (ConnectionError)", transient=True)
            yield block

    def put_bytes(self, key, data):
        self.calls.append(("PUT", key))
        if self._match(key, self.fail_put):
            raise snap.StoreError("object store returned HTTP 500")
        if self._match(key, self.drop_put):
            return                                   # claims success, stores nothing
        if self._match(key, self.corrupt_put):
            data = bytes([data[0] ^ 0xFF]) + data[1:]
        self.inner.put_bytes(key, data)

    def exists(self, key):
        self.calls.append(("HEAD", key))
        return self.inner.exists(key)

    def get_with_etag(self, key):                       # Stage 7B.2: the pointer is now read with its entity tag and swapped conditionally
        self.calls.append(("GET", key))
        return self.inner.get_with_etag(key)

    def put_conditional(self, key, data, **kw):
        self.calls.append(("PUT", key))
        if self._match(key, self.fail_put):
            raise snap.StoreError("object store returned HTTP 500")
        if self._match(key, self.drop_put):
            return
        self.inner.put_conditional(key, data, **kw)

    def puts(self, needle):
        return sum(1 for op, k in self.calls if op == "PUT" and needle in k)


class Case(tis.Fixture):
    def setUp(self):
        super().setUp()
        self.flaky = ScriptedStore(self.store)

    def active_version(self, store=None):
        return snap.parse_pointer((store or self.store).get_bytes("active.json"))["version"]

    def loads(self, work="w"):
        return self.manager(work=self.tmp / work).activate()

    def store_digest(self):
        return {p.relative_to(self.tmp / "store").as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted((self.tmp / "store").rglob("*")) if p.is_file()}


class InterruptedPublishTests(Case):
    def test_an_interruption_at_any_step_leaves_the_previous_snapshot_active_and_loadable(self):
        self.publish(version="v1")
        before = self.store_digest()
        for step in ("index.tar.gz", "lifecycle.tar.gz", "manifests/v2.json", "active.json"):
            flaky = ScriptedStore(self.store)
            flaky.fail_put = {step}
            with self.assertRaises((snap.SnapshotError, snap.StoreError), msg=step):
                self.publish(version="v2", store=flaky)
            self.assertEqual(self.active_version(), "v1", step)
            st = self.loads(f"w-{step.replace('/', '_')}")
            self.assertEqual((st.state, st.version, st.ready), ("ready", "v1", True), step)
            # what v1 consisted of is untouched (anything written for v2 is additional, never a replacement)
            now = self.store_digest()
            for k in [k for k in before if "v1" in k]:
                self.assertEqual(now[k], before[k], f"{step}: {k}")
            # clear this attempt's leftovers so the next step starts from the same store
            for leftover in (self.tmp / "store").glob("**/v2*"):
                shutil.rmtree(leftover, ignore_errors=True) if leftover.is_dir() else leftover.unlink()

    def test_a_first_publish_that_is_interrupted_leaves_no_pointer_so_nothing_is_ready(self):
        flaky = ScriptedStore(self.store)
        flaky.fail_put = {"lifecycle.tar.gz"}
        with self.assertRaises(snap.StoreError):
            self.publish(version="v1", store=flaky)
        self.assertFalse(self.store.exists("active.json"))
        st = self.loads()
        self.assertEqual((st.state, st.ready, st.db_dir), ("manifest_missing", False, None))

    def test_an_interrupted_upload_can_be_resumed_without_rewriting_what_already_arrived(self):
        self.publish(version="v1")
        flaky = ScriptedStore(self.store)
        flaky.fail_put = {"lifecycle.tar.gz"}
        with self.assertRaises(snap.StoreError):
            self.publish(version="v2", store=flaky)
        self.assertTrue(self.store.exists("snapshots/v2/index.tar.gz"))
        self.assertFalse(self.store.exists("manifests/v2.json"))       # no manifest: v2 does not exist yet as far as any reader knows
        resume = ScriptedStore(self.store)
        m = self.publish(version="v2", store=resume)
        self.assertEqual(resume.puts("snapshots/v2/index.tar.gz"), 0)  # identical content already there: reused, not rewritten
        self.assertEqual(resume.puts("snapshots/v2/lifecycle.tar.gz"), 1)
        self.assertEqual((self.active_version(), m["version"]), ("v2", "v2"))
        self.assertEqual(self.loads().state, "ready")

    def test_a_failed_pointer_update_keeps_the_old_snapshot_active_and_says_how_to_activate_the_new_one(self):
        self.publish(version="v1")
        flaky = ScriptedStore(self.store)
        flaky.fail_put = {"active.json"}
        with self.assertRaises(snap.SnapshotError) as cm:
            self.publish(version="v2", store=flaky)
        self.assertEqual(cm.exception.state, "store_unavailable")
        self.assertIn("rollback --to v2", cm.exception.detail)
        self.assertEqual(self.active_version(), "v1")
        self.assertTrue(self.store.exists("manifests/v2.json"))
        with self.assertRaises(snap.SnapshotError):                     # a finished version is immutable: it is activated, not re-published
            self.publish(version="v2")
        snap.rollback(self.store, "v2", "operator-b")
        st = self.loads()
        self.assertEqual((st.state, st.version), ("ready", "v2"))
        self.assertEqual(snap.parse_pointer(self.store.get_bytes("active.json"))["previous"]["version"], "v1")

    def test_different_content_under_an_existing_archive_key_is_refused_and_left_alone(self):
        self.store.put_bytes("snapshots/v9/index.tar.gz", b"someone else's bytes")
        with self.assertRaises(snap.SnapshotError) as cm:
            self.publish(version="v9")
        self.assertEqual(cm.exception.state, "manifest_invalid")
        self.assertEqual(self.store.get_bytes("snapshots/v9/index.tar.gz"), b"someone else's bytes")
        self.assertFalse(self.store.exists("active.json") or self.store.exists("manifests/v9.json"))


class ReadBackVerificationTests(Case):
    """The pointer is written only after the uploaded snapshot has been read back out of the store and matched its manifest."""

    def test_an_archive_that_is_stored_corrupted_never_gets_a_pointer(self):
        self.publish(version="v1")
        for name in ("index.tar.gz", "lifecycle.tar.gz"):
            flaky = ScriptedStore(self.store)
            flaky.corrupt_put = {name}
            with self.assertRaises(snap.SnapshotError) as cm:
                self.publish(version="v2", store=flaky)
            self.assertEqual(cm.exception.state, "checksum_mismatch", name)
            self.assertEqual(self.active_version(), "v1", name)
            (self.tmp / "store" / "manifests" / "v2.json").unlink()
            shutil.rmtree(self.tmp / "store" / "snapshots" / "v2")

    def test_an_object_the_store_silently_lost_never_gets_a_pointer(self):
        self.publish(version="v1")
        flaky = ScriptedStore(self.store)
        flaky.drop_put = {"lifecycle.tar.gz"}
        with self.assertRaises(snap.SnapshotError) as cm:
            self.publish(version="v2", store=flaky)
        self.assertEqual(cm.exception.state, "snapshot_missing")
        self.assertEqual(self.active_version(), "v1")

    def test_a_manifest_that_does_not_read_back_identically_never_gets_a_pointer(self):
        self.publish(version="v1")
        flaky = ScriptedStore(self.store)
        flaky.corrupt_put = {"manifests/v2.json"}
        with self.assertRaises(snap.SnapshotError) as cm:
            self.publish(version="v2", store=flaky)
        self.assertEqual(cm.exception.state, "checksum_mismatch")
        self.assertEqual(self.active_version(), "v1")

    def test_activating_an_older_snapshot_also_reads_it_back_first(self):
        self.publish(version="v1")
        self.publish(version="v2")
        (self.tmp / "store" / "snapshots" / "v1" / "index.tar.gz").write_bytes(b"rotted")
        with self.assertRaises(snap.SnapshotError) as cm:
            snap.rollback(self.store, "v1", "operator-b")
        self.assertEqual(cm.exception.state, "checksum_mismatch")
        self.assertEqual(self.active_version(), "v2")
        (self.tmp / "store" / "snapshots" / "v1" / "index.tar.gz").unlink()
        with self.assertRaises(snap.SnapshotError) as cm:
            snap.rollback(self.store, "v1", "operator-b")
        self.assertEqual(cm.exception.state, "snapshot_missing")
        self.assertEqual(self.active_version(), "v2")


class PreservationTests(Case):
    def test_earlier_snapshots_stay_byte_for_byte_and_loadable_after_later_publishes(self):
        self.publish(version="v1")
        first = {k: v for k, v in self.store_digest().items() if "v1" in k}
        self.publish(version="v2")
        self.publish(version="v3")
        now = self.store_digest()
        for k, digest in first.items():
            self.assertEqual(now[k], digest, k)
        snap.rollback(self.store, "v1", "operator-b")
        self.assertEqual(self.loads().version, "v1")

    def test_the_failed_publish_of_a_newer_snapshot_never_costs_the_working_one(self):
        self.publish(version="v1")
        before = self.store_digest()
        flaky = ScriptedStore(self.store)
        flaky.corrupt_put = {"index.tar.gz"}
        with self.assertRaises(snap.SnapshotError):
            self.publish(version="v2", store=flaky)
        after = self.store_digest()
        for k, digest in before.items():
            self.assertEqual(after[k], digest, k)       # including active.json
        self.assertEqual(self.loads().state, "ready")

    def test_no_store_has_a_delete_operation_and_nothing_in_the_module_issues_one(self):
        for cls in (snap.ObjectStore, snap.LocalObjectStore, snap.S3CompatStore, snap.PrefixedStore):
            for name in ("delete", "delete_object", "remove", "purge", "prune_remote"):
                self.assertFalse(hasattr(cls, name), f"{cls.__name__}.{name}")
        source = Path(snap.__file__).read_text("utf-8")
        for needle in ('"DELETE"', "'DELETE'", ".delete_object", ".remove(", "unlink"):
            # local work-directory housekeeping (_prune, .part cleanup) is allowed to unlink; the object stores are not
            if needle == "unlink":
                continue
            self.assertNotIn(needle, source.split("class SnapshotManager")[0], needle)


class ManifestMetadataTests(Case):
    def test_the_manifest_carries_everything_an_operator_and_the_server_need(self):
        m = self.publish(version="v1")
        self.assertEqual(m["version"], "v1")                                                   # snapshot identifier
        self.assertEqual(m["index"]["archive"], "snapshots/v1/index.tar.gz")                    # snapshot object key
        self.assertRegex(m["index"]["sha256"], r"^[0-9a-f]{64}$")                               # SHA-256 checksum
        self.assertTrue(m["index"]["index_version"].startswith("telangana") or "@" in m["index"]["index_version"])  # index version
        self.assertEqual((m["embedding"]["model"], m["embedding"]["dimensions"]), ("fake-embedder", 8))
        self.assertEqual(m["index"]["chunk_count"], 3)                                          # chunk count
        datetime.datetime.fromisoformat(m["created_at"].replace("Z", "+00:00"))                 # creation timestamp (ISO-8601)
        self.assertRegex(m["lifecycle"]["registry_sha256"], r"^[0-9a-f]{64}$")                  # lifecycle registry digest
        self.assertRegex(m["lifecycle"]["tree_digest"], r"^[0-9a-f]{64}$")
        self.assertEqual(snap.validate_manifest(json.loads(self.store.get_bytes("manifests/v1.json")))["version"], "v1")

    def test_a_manifest_missing_any_of_them_is_rejected(self):
        m = json.loads(json.dumps(self.publish(version="v1")))
        for label, drop in (("version", lambda x: x.pop("version")), ("key", lambda x: x["index"].pop("archive")),
                            ("sha", lambda x: x["index"].pop("sha256")), ("index version", lambda x: x["index"].pop("index_version")),
                            ("model", lambda x: x["embedding"].pop("model")), ("dims", lambda x: x["embedding"].pop("dimensions")),
                            ("chunks", lambda x: x["index"].pop("chunk_count")), ("created", lambda x: x.pop("created_at")),
                            ("registry digest", lambda x: x["lifecycle"].pop("registry_sha256"))):
            broken = json.loads(json.dumps(m))
            drop(broken)
            with self.assertRaises(snap.SnapshotError, msg=label):
                snap.validate_manifest(broken)


class StoreRetryTests(unittest.TestCase):
    SECRET = "r2-secret-THIS-MUST-NEVER-APPEAR"

    def client(self, *script, **kw):
        calls, sleeps, ticks = [], [], iter(range(10 ** 6))
        start = datetime.datetime(2026, 11, 14, 10, 0, 0, tzinfo=datetime.timezone.utc)

        def http(method, url, headers=None, data=None, timeout=None, stream=False):
            calls.append({"method": method, "headers": dict(headers)})
            item = script[min(len(calls), len(script)) - 1]
            if isinstance(item, Exception):
                raise item
            return item
        c = snap.S3CompatStore("https://acc.r2.cloudflarestorage.com", "bucket", "AKID", self.SECRET, http=http, sleep=sleeps.append,
                               clock=lambda: start + datetime.timedelta(seconds=next(ticks)), **kw)
        return c, calls, sleeps

    R = tis.R2ClientTests.Resp

    def test_transient_failures_are_retried_with_backoff_and_every_attempt_is_signed_afresh(self):
        c, calls, sleeps = self.client(self.R(503), self.R(429), self.R(200, b"ok"))
        self.assertEqual(c.get_bytes("kyr/active.json"), b"ok")
        self.assertEqual((len(calls), sleeps), (3, [0.5, 1.0]))
        self.assertEqual(len({x["headers"]["x-amz-date"] for x in calls}), 3)
        self.assertEqual(len({x["headers"]["Authorization"] for x in calls}), 3)

    def test_network_errors_and_timeouts_are_retried_then_reported_without_the_secret(self):
        for failure in (requests.ConnectionError(self.SECRET), requests.Timeout(self.SECRET)):
            c, calls, sleeps = self.client(failure)
            with self.assertRaises(snap.StoreError) as cm:
                c.exists("kyr/x")
            self.assertEqual((len(calls), len(sleeps)), (3, 2))
            self.assertNotIn(self.SECRET, str(cm.exception))

    def test_exhausted_retries_end_in_a_store_error_not_a_loop(self):
        c, calls, _ = self.client(self.R(500, self.SECRET.encode()))
        with self.assertRaises(snap.StoreError) as cm:
            c.get_bytes("kyr/x")
        self.assertEqual(len(calls), 3)
        self.assertNotIn(self.SECRET, str(cm.exception))

    def test_answers_that_will_not_change_are_not_retried(self):
        for status, error in ((404, snap.ObjectMissing), (403, snap.StoreError), (400, snap.StoreError), (412, snap.StoreError)):
            c, calls, sleeps = self.client(self.R(status))
            with self.assertRaises(error):
                c.get_bytes("kyr/x")
            self.assertEqual((len(calls), sleeps), (1, []), status)

    def test_a_write_is_retried_too_because_every_object_here_is_write_once_or_a_pointer(self):
        c, calls, _ = self.client(self.R(500), self.R(200))
        c.put_bytes("kyr/c", b"data")
        self.assertEqual([x["method"] for x in calls], ["PUT", "PUT"])

    def test_retries_can_be_switched_off(self):
        c, calls, _ = self.client(self.R(503), retries=0)
        with self.assertRaises(snap.StoreError):
            c.get_bytes("kyr/x")
        self.assertEqual(len(calls), 1)


class FakeR2:
    """An in-memory path-style S3 endpoint behind S3CompatStore: records the methods and the keys it is asked for."""

    class Resp(tis.R2ClientTests.Resp):
        def iter_content(self, n):
            for i in range(0, max(len(self.body), 1), n):
                yield self.body[i:i + n]

    def __init__(self):
        self.objects, self.methods, self.fail = {}, [], {}

    def http(self, method, url, headers=None, data=None, timeout=None, stream=False):
        key = url.split("/bucket/", 1)[1]
        self.methods.append(method)
        if method == "PUT":
            self.objects[key] = data or b""
            return self.Resp(200)
        if self.fail.get(key, 0) > 0 and method == "GET":
            self.fail[key] -= 1
            return self.Resp(503)
        return self.Resp(200, self.objects[key]) if key in self.objects else self.Resp(404)

    def store(self, **kw):
        return snap.PrefixedStore(snap.S3CompatStore("https://acc.r2.cloudflarestorage.com", "bucket", "AKID", "secret", http=self.http,
                                                     clock=lambda: datetime.datetime.now(datetime.timezone.utc), sleep=lambda s: None, **kw), "kyr/")


class DownloadAndColdStartTests(Case):
    def test_a_download_that_breaks_once_is_retried_and_the_corpus_still_verifies(self):
        self.publish(version="v1")
        flaky = ScriptedStore(self.store)
        flaky.break_stream = {"index.tar.gz": 1}
        st = self.manager(store=flaky, work=self.tmp / "w").activate()
        self.assertEqual((st.state, st.ready), ("ready", True), st.problems)
        self.assertEqual(sorted((self.tmp / "w").rglob("*.part")), [])

    def test_a_download_that_keeps_breaking_is_not_ready_and_leaves_nothing_behind(self):
        self.publish(version="v1")
        flaky = ScriptedStore(self.store)
        flaky.break_stream = {"index.tar.gz": 99}
        st = self.manager(store=flaky, work=self.tmp / "w").activate()
        self.assertEqual((st.state, st.ready, st.db_dir, st.lifecycle_dir), ("store_unavailable", False, None, None))
        self.assertEqual(sorted((self.tmp / "w").rglob("*.part")), [])
        self.assertFalse((self.tmp / "w" / "run").exists())

    def test_a_cold_start_is_reproducible_and_a_warm_restart_downloads_nothing(self):
        m = self.publish(version="v1")
        a = self.loads("cold-a")
        b = self.loads("cold-b")
        self.assertEqual((a.state, b.state), ("ready", "ready"))
        self.assertEqual(snap.files_digest(a.db_dir), snap.files_digest(b.db_dir))
        self.assertEqual(snap.files_digest(a.db_dir), m["index"]["tree_digest"])
        self.assertEqual(snap.files_digest(a.lifecycle_dir, snap.LOCK_FILES), m["lifecycle"]["tree_digest"])
        spy = ScriptedStore(self.store)
        warm = self.manager(store=spy, work=self.tmp / "cold-a").activate()
        self.assertEqual(warm.state, "ready")
        self.assertEqual([k for op, k in spy.calls if op == "GET" and k.startswith("snapshots/")], [])   # archives were re-hashed, not re-fetched

    def test_over_an_r2_shaped_store_publish_and_load_use_only_get_head_and_put(self):
        r2 = FakeR2()
        write = r2.store()
        m = snap.publish(write, self.db, self.state, embed=self.emb.embed_documents, embedding_model="fake-embedder", family="fake-family",
                         created_by="operator-a", doc_prefix="", version="v1")
        self.assertEqual(set(r2.methods), {"GET", "HEAD", "PUT"})
        r2.methods.clear()
        st = snap.SnapshotManager(r2.store(), self.tmp / "srv").activate()
        self.assertEqual((st.state, st.version), ("ready", m["version"]))
        self.assertEqual(set(r2.methods), {"GET"})                    # the runtime token never needs to write (or even HEAD)

    def test_over_an_r2_shaped_store_a_flaky_archive_is_survived_and_a_dead_one_is_not_ready(self):
        r2 = FakeR2()
        snap.publish(r2.store(), self.db, self.state, embed=self.emb.embed_documents, embedding_model="fake-embedder", family="fake-family",
                     created_by="operator-a", doc_prefix="", version="v1")
        r2.fail["kyr/snapshots/v1/index.tar.gz"] = 2                  # two 503s, then the object is served (store-level retries)
        self.assertEqual(snap.SnapshotManager(r2.store(), self.tmp / "s1").activate().state, "ready")
        r2.fail["kyr/snapshots/v1/index.tar.gz"] = 99
        st = snap.SnapshotManager(r2.store(), self.tmp / "s2").activate()
        self.assertEqual((st.state, st.ready, st.db_dir), ("store_unavailable", False, None))


class ServerStartupTests(tcr.ServerCase, tis.Fixture):
    """The server with R2 configuration in every state: it starts, says why it is not ready, serves nothing and creates nothing."""

    def env(self, **extra):
        return {"TG_DB_DIR": None, "TG_LIFECYCLE_DIR": None, "TG_SNAPSHOT_WORK_DIR": str(self.tmp / "srvwork"), **extra}

    def assert_serves_nothing(self, srv, client, state):
        self.assertEqual((srv.SNAPSHOT.state, srv.SNAPSHOT.ready), (state, False))
        self.assertIsNone(srv.vector_store)
        s = client.get("/status").json()
        self.assertEqual((s["corpus_ready"], s["snapshot"]["state"]), (False, state))
        self.assertEqual(client.get("/health").json(), {"status": "ok"})          # alive, and not claiming to be ready
        self.assertEqual(client.post("/chat", json={"message": tcr.Q, "session_id": "s"}).json()["kind"], "unavailable")
        self.assertFalse(srv._UNAVAILABLE_DIR.exists())                              # no empty index was created to "serve"

    def test_missing_r2_configuration_is_not_ready(self):
        srv, client = self.server(**self.env(TG_SNAPSHOT_STORE="r2", R2_ACCOUNT_ID=None, R2_BUCKET=None, R2_ACCESS_KEY_ID=None,
                                             R2_SECRET_ACCESS_KEY=None))
        self.assert_serves_nothing(srv, client, "misconfigured")

    def test_incomplete_or_insecure_r2_configuration_is_not_ready(self):
        for extra in ({"R2_SECRET_ACCESS_KEY": None}, {"R2_BUCKET": None}, {"R2_ENDPOINT": "http://r2.example"}):
            base = {"TG_SNAPSHOT_STORE": "r2", "R2_ACCOUNT_ID": "acc", "R2_BUCKET": "b", "R2_ACCESS_KEY_ID": "k", "R2_SECRET_ACCESS_KEY": "s"}
            srv, client = self.server(**self.env(**{**base, **extra}))
            self.assert_serves_nothing(srv, client, "misconfigured")

    def test_a_corrupt_lifecycle_registry_or_audit_chain_fails_closed_at_the_server(self):
        m = self.publish()
        lc_tar = self.tmp / "lc.tar.gz"
        lc_tar.write_bytes(self.store.get_bytes(m["lifecycle"]["archive"]))
        work = self.tmp / "lc-unpacked"
        snap.safe_extract(lc_tar, work, 10 ** 8)
        (work / "audit.jsonl").write_text((work / "audit.jsonl").read_text()[:-5])
        new_tar = self.tmp / "lc2.tar.gz"
        snap.make_archive(work, new_tar)
        data = new_tar.read_bytes()

        def mutate(manifest):
            self.store.put_bytes(manifest["lifecycle"]["archive"], data)
            manifest["lifecycle"].update(sha256=snap.sha256_bytes(data), size_bytes=len(data), tree_digest=snap.files_digest(work),
                                         unpacked_bytes=sum(p.stat().st_size for p in work.rglob("*") if p.is_file()))
        self.rewrite(mutate)
        srv, client = self.server(**self.env(TG_SNAPSHOT_STORE="local", TG_SNAPSHOT_LOCAL_DIR=str(self.tmp / "store"), TG_SNAPSHOT_PREFIX=""))
        self.assert_serves_nothing(srv, client, "lifecycle_invalid")
        self.assertFalse(srv.LIFECYCLE.ready())

    def test_an_index_that_disagrees_with_the_registry_fails_closed_at_the_server(self):
        self.publish()
        self.rewrite(lambda m: m["index"].update(chunk_count=99))
        srv, client = self.server(**self.env(TG_SNAPSHOT_STORE="local", TG_SNAPSHOT_LOCAL_DIR=str(self.tmp / "store"), TG_SNAPSHOT_PREFIX=""))
        self.assert_serves_nothing(srv, client, "index_invalid")

    def test_a_failed_download_on_a_cold_start_is_not_ready(self):
        self.publish(version="v1")
        (self.tmp / "store" / "snapshots" / "v1" / "index.tar.gz").unlink()
        srv, client = self.server(**self.env(TG_SNAPSHOT_STORE="local", TG_SNAPSHOT_LOCAL_DIR=str(self.tmp / "store"), TG_SNAPSHOT_PREFIX=""))
        self.assert_serves_nothing(srv, client, "snapshot_missing")


if __name__ == "__main__":
    unittest.main()
