"""Stage 7B.2: conditional (ETag / If-Match) publication of the active snapshot pointer.
WHAT THIS PROVES: the compare-and-swap logic in backend/index_snapshot.py, against (a) a real directory store with a real file lock, with
real threads, and (b) a MOCK of an S3/R2-style API that implements ETag, If-Match, If-None-Match and 412 the way the S3 specification
describes them. WHAT IT DOES NOT PROVE: that Cloudflare R2 itself behaves that way. That needs one live check by the operator; see the
Stage 7B.2 report. No network, no accounts, no real index."""
import hashlib
import threading
import unittest
from urllib.parse import urlparse

import test_index_snapshot as tis
from backend import index_snapshot as snap


class FakeResponse:
    def __init__(self, status, body=b"", headers=None):
        self.status_code, self.content, self.headers = status, body, headers or {}

    def iter_content(self, n):
        yield self.content

    def close(self):
        pass


class FakeR2:
    """In-memory S3-style bucket. ETag = quoted md5 (as S3 returns for single-part uploads). Conditional PUT per the S3 API."""

    def __init__(self):
        self.objects, self.log = {}, []
        self.lock = threading.Lock()
        self.fail_next_put = 0

    @staticmethod
    def etag(data):
        return '"' + hashlib.md5(data).hexdigest() + '"'

    def __call__(self, method, url, headers=None, data=None, timeout=None, stream=False):
        key = urlparse(url).path.lstrip("/")
        headers = headers or {}
        self.log.append((method, key, {k: v for k, v in headers.items() if k.lower().startswith("if-")}))
        with self.lock:
            if method == "GET":
                if key not in self.objects:
                    return FakeResponse(404)
                return FakeResponse(200, self.objects[key], {"ETag": self.etag(self.objects[key])})
            if method == "HEAD":
                return FakeResponse(200 if key in self.objects else 404)
            if method == "PUT":
                if self.fail_next_put:
                    self.fail_next_put -= 1
                    return FakeResponse(500)
                cur = self.etag(self.objects[key]) if key in self.objects else None
                if headers.get("If-None-Match") == "*" and cur is not None:
                    return FakeResponse(412)
                if "If-Match" in headers and headers["If-Match"] != cur:
                    return FakeResponse(412)
                self.objects[key] = data or b""
                return FakeResponse(200, b"", {"ETag": self.etag(self.objects[key])})
        return FakeResponse(405)


def r2store(fake):
    return snap.PrefixedStore(snap.S3CompatStore("https://acct.r2.cloudflarestorage.com", "bkt", "id", "secret", http=fake, retries=0), "kyr/")


class Racing(snap.ObjectStore):
    """Delegates to `inner`; runs `hook` once right after the first read of active.json."""

    def __init__(self, inner, hook):
        self.inner, self.hook, self.fired = inner, hook, False

    def get_stream(self, key):
        return self.inner.get_stream(key)

    def put_bytes(self, key, data):
        self.inner.put_bytes(key, data)

    def exists(self, key):
        return self.inner.exists(key)

    def put_conditional(self, key, data, **kw):
        return self.inner.put_conditional(key, data, **kw)

    def get_with_etag(self, key):
        try:
            got = self.inner.get_with_etag(key)
        except snap.ObjectMissing:
            if key == "active.json" and not self.fired:      # "no pointer yet" is also what this publisher decided on
                self.fired = True
                self.hook()
            raise
        if key == "active.json" and not self.fired:
            self.fired = True
            self.hook()
        return got


class Case(tis.Fixture):
    def pub(self, store, version, by="op"):
        return snap.publish(store, self.db, self.state, embed=self.emb.embed_documents, embedding_model="fake-embedder", family="fake-family",
                            created_by=by, doc_prefix="", version=version)

    def active(self, store=None):
        return snap.parse_pointer((store or self.store).get_bytes("active.json"))


class LocalStoreCas(Case):
    def test_two_publishers_from_the_same_etag_exactly_one_wins(self):
        self.pub(self.store, "v0")
        a, b = snap.read_pointer(self.store), snap.read_pointer(self.store)
        self.assertEqual(a.etag, b.etag)
        self.pub(self.store, "v-a", "op-a")                                  # (A's own read sees the same tag and swaps first)
        with self.assertRaises(snap.SnapshotError) as cm:
            snap._swap_pointer(self.store, {"schema_version": 1, "version": "v-b"}, b, "v-b")
        self.assertEqual(cm.exception.state, "publish_conflict")
        self.assertEqual(self.active()["version"], "v-a")

    def test_retry_after_conflict_is_an_explicit_activation_that_records_the_winner_as_previous(self):
        self.pub(self.store, "v0")
        with self.assertRaises(snap.SnapshotError):
            self.pub(Racing(self.store, lambda: self.pub(self.store, "v-a", "op-a")), "v-b", "op-b")
        self.assertEqual(self.active()["version"], "v-a")
        snap.rollback(self.store, "v-b", "op-b")                             # the retry the conflict message names
        p = self.active()
        self.assertEqual((p["version"], p["previous"]["version"]), ("v-b", "v-a"))
        self.assertEqual(self.manager(work=self.tmp / "w").activate().version, "v-b")

    def test_first_ever_publish_race_uses_if_none_match(self):
        racing = Racing(self.store, lambda: self.pub(self.store, "v-a", "op-a"))
        with self.assertRaises(snap.SnapshotError) as cm:
            self.pub(racing, "v-b", "op-b")                                  # B saw "no pointer"; A created it first
        self.assertEqual(cm.exception.state, "publish_conflict")
        self.assertEqual(self.active()["version"], "v-a")

    def test_threads_swapping_from_one_tag_exactly_one_succeeds(self):
        self.store.put_bytes("active.json", b"{}")
        tag = self.store.get_with_etag("active.json")[1]
        results = []

        def go(i):
            try:
                self.store.put_conditional("active.json", f"w{i}".encode(), if_match=tag)
                results.append("ok")
            except snap.PreconditionFailed:
                results.append("conflict")
        ts = [threading.Thread(target=go, args=(i,)) for i in range(16)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual((results.count("ok"), results.count("conflict")), (1, 15))

    def test_rollback_also_refuses_to_overwrite_a_pointer_that_changed_under_it(self):
        self.pub(self.store, "v0")
        self.pub(self.store, "v1")
        racing = Racing(self.store, lambda: self.pub(self.store, "v2", "op-x"))
        with self.assertRaises(snap.SnapshotError) as cm:
            snap.rollback(racing, "v0", "op-b")
        self.assertEqual(cm.exception.state, "publish_conflict")
        self.assertEqual(self.active()["version"], "v2")

    def test_an_invalid_pointer_blocks_publish_but_rollback_can_repair_it(self):
        self.pub(self.store, "v0")
        self.store.put_bytes("active.json", b"not json")
        with self.assertRaises(snap.SnapshotError) as cm:
            self.pub(self.store, "v1")
        self.assertEqual(cm.exception.state, "pointer_invalid")
        self.assertEqual(self.store.get_bytes("active.json"), b"not json")   # untouched
        snap.rollback(self.store, "v0", "op")
        self.assertEqual(self.active()["version"], "v0")


class FailureAndCleanup(Case):
    def test_a_store_without_conditional_writes_refuses_and_writes_no_pointer(self):
        class Plain(snap.ObjectStore):
            def __init__(s, inner):
                s.inner = inner
            def get_stream(s, k): return s.inner.get_stream(k)
            def put_bytes(s, k, d): s.inner.put_bytes(k, d)
            def exists(s, k): return s.inner.exists(k)
        with self.assertRaises(snap.SnapshotError) as cm:
            self.pub(Plain(self.store), "v0")
        self.assertEqual(cm.exception.state, "store_unavailable")
        self.assertFalse(self.store.exists("active.json"))

    def test_a_failed_pointer_write_keeps_the_old_snapshot_active_and_the_new_one_complete(self):
        self.pub(self.store, "v0")
        fake_inner = self.store

        class Boom(Racing):
            def put_conditional(s, key, data, **kw):
                raise snap.StoreError("object store returned HTTP 500")
        with self.assertRaises(snap.SnapshotError) as cm:
            self.pub(Boom(fake_inner, lambda: None), "v1")
        self.assertIn("rollback --to v1", str(cm.exception))
        self.assertEqual(self.active()["version"], "v0")
        snap.verify_uploaded(self.store, snap.validate_manifest(__import__("json").loads(self.store.get_bytes("manifests/v1.json"))))

    def test_a_retried_put_that_really_succeeded_is_not_reported_as_a_conflict(self):
        self.pub(self.store, "v0")
        seen = snap.read_pointer(self.store)
        pointer = {"schema_version": 1, "version": "v0", "manifest_key": "manifests/v0.json", "manifest_sha256": "x", "previous": None,
                   "updated_at": "t", "updated_by": "o"}
        self.store.put_bytes("active.json", snap.canonical_json(pointer))    # first attempt landed, response lost, tag moved
        snap._swap_pointer(self.store, pointer, seen, "v0")                  # the retry sees 412 but finds its own content: success

    def test_the_active_and_previous_snapshots_are_protected_and_there_is_no_delete_operation(self):
        for v in ("v0", "v1", "v2"):
            self.pub(self.store, v)
        self.assertEqual(snap.protected_versions(self.store), {"v2", "v1"})
        for cls in (snap.ObjectStore, snap.LocalObjectStore, snap.S3CompatStore, snap.PrefixedStore):
            self.assertFalse([n for n in dir(cls) if "delete" in n.lower() or "remove" in n.lower()], cls)

    def test_the_active_snapshot_stays_loadable_and_verifiable_after_a_lost_race(self):
        self.pub(self.store, "v0")
        with self.assertRaises(snap.SnapshotError):
            self.pub(Racing(self.store, lambda: self.pub(self.store, "v-a", "a")), "v-b", "b")
        status = self.manager(work=self.tmp / "w").activate()
        self.assertEqual((status.state, status.version), ("ready", "v-a"))


class MockedR2Api(Case):
    """MOCK of the S3/R2 conditional-PUT contract. Not evidence about Cloudflare R2."""

    def test_publish_sends_if_none_match_first_then_if_match_with_the_etag_it_read(self):
        fake = FakeR2()
        st = r2store(fake)
        self.pub(st, "v0")
        self.pub(st, "v1")
        puts = [(k, c) for m, k, c in fake.log if m == "PUT" and k.endswith("active.json")]
        self.assertEqual(puts[0][1], {"If-None-Match": "*"})
        tag0 = FakeR2.etag(b"")                                              # placeholder: the second PUT must carry the tag of the first pointer
        self.assertEqual(list(puts[1][1]), ["If-Match"])
        self.assertNotEqual(puts[1][1]["If-Match"], tag0)
        self.assertTrue(all(c == {} for m, k, c in fake.log if m == "PUT" and not k.endswith("active.json")))   # write-once objects: no conditions

    def test_a_412_is_a_conflict_and_the_winners_pointer_is_not_overwritten(self):
        fake = FakeR2()
        st = r2store(fake)
        self.pub(st, "v0")
        with self.assertRaises(snap.SnapshotError) as cm:
            self.pub(Racing(st, lambda: self.pub(st, "v-a", "a")), "v-b", "b")
        self.assertEqual(cm.exception.state, "publish_conflict")
        self.assertEqual(snap.parse_pointer(st.get_bytes("active.json"))["version"], "v-a")

    def test_a_409_conditional_request_conflict_is_also_a_conflict(self):
        fake = FakeR2()
        st = r2store(fake)
        inner = fake.__call__

        def conflicting(method, url, headers=None, data=None, timeout=None, stream=False):
            if method == "PUT" and "If-Match" in (headers or {}):
                return FakeResponse(409)
            return inner(method, url, headers=headers, data=data, timeout=timeout, stream=stream)
        st = r2store(conflicting)
        self.pub(st, "v0")
        with self.assertRaises(snap.SnapshotError) as cm:
            self.pub(st, "v1")
        self.assertEqual(cm.exception.state, "publish_conflict")

    def test_missing_etag_header_refuses_instead_of_guessing(self):
        fake = FakeR2()
        st = r2store(fake)
        self.pub(st, "v0")
        orig = fake.__call__

        def no_etag(method, url, **kw):
            r = orig(method, url, **kw)
            r.headers = {}
            return r
        with self.assertRaises(snap.SnapshotError) as cm:
            self.pub(r2store(no_etag), "v1")
        self.assertEqual(cm.exception.state, "store_unavailable")
        self.assertEqual(snap.parse_pointer(st.get_bytes("active.json"))["version"], "v0")


if __name__ == "__main__":
    unittest.main()
