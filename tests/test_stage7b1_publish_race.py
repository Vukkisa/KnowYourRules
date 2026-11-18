"""Stage 7B.1 documented a publish race (two operators; `publish` overwrote active.json unconditionally, so one update was lost silently).
Stage 7B.2 fixed it with a compare-and-swap on the pointer's entity tag. This module keeps the original interleaving and now asserts the
FIXED behaviour: the loser gets a conflict, the winner's pointer survives, nothing is corrupted. More cases: test_stage7b2_publish_cas.py.
Offline: tiny index, local directory store. Real R2 is NOT exercised here (see the Stage 7B.2 report)."""
import unittest

import test_index_snapshot as tis
from backend import index_snapshot as snap


class InterleavingStore(snap.ObjectStore):
    """Runs `hook` once, right after the FIRST read of active.json (the moment the publisher decides what `previous` is)."""

    def __init__(self, inner):
        self.inner, self.hook, self.fired = inner, None, False

    def get_stream(self, key):
        return self.inner.get_stream(key)

    def get_bytes(self, key, limit=64 * 1024 * 1024):
        return self.inner.get_bytes(key, limit)

    def get_with_etag(self, key):
        got = self.inner.get_with_etag(key)
        if key == "active.json" and self.hook and not self.fired:
            self.fired = True
            self.hook()
        return got

    def put_bytes(self, key, data):
        self.inner.put_bytes(key, data)

    def put_conditional(self, key, data, **kw):
        self.inner.put_conditional(key, data, **kw)

    def exists(self, key):
        return self.inner.exists(key)


class PublishRaceTests(tis.Fixture):
    def active(self):
        return snap.parse_pointer(self.store.get_bytes("active.json"))

    def publish_b(self, racing):
        return snap.publish(racing, self.db, self.state, embed=self.emb.embed_documents, embedding_model="fake-embedder", family="fake-family",
                            created_by="operator-b", doc_prefix="", version="v-b")

    def test_interleaved_publishers_the_loser_gets_a_conflict_and_the_winner_is_kept(self):
        self.publish(version="v0")
        racing = InterleavingStore(self.store)
        racing.hook = lambda: self.publish(version="v-a", created_by="operator-a")      # A completes between B's read and B's write
        with self.assertRaises(snap.SnapshotError) as cm:
            self.publish_b(racing)
        self.assertEqual(cm.exception.state, "publish_conflict")
        self.assertEqual(self.active()["version"], "v-a")                                # the winner's pointer was not overwritten
        self.assertEqual(self.active()["previous"]["version"], "v0")
        self.assertTrue(self.store.exists("manifests/v-b.json"))                         # the loser's snapshot is intact, just not active

    def test_the_server_still_loads_the_winner_after_a_race(self):
        self.publish(version="v0")
        racing = InterleavingStore(self.store)
        racing.hook = lambda: self.publish(version="v-a", created_by="operator-a")
        with self.assertRaises(snap.SnapshotError):
            self.publish_b(racing)
        status = self.manager(work=self.tmp / "w").activate()
        self.assertEqual((status.state, status.version), ("ready", "v-a"))

    def test_the_pointer_write_is_conditional(self):
        import inspect
        src = inspect.getsource(snap._swap_pointer)
        self.assertIn("if_match=seen.etag", src)
        self.assertIn("if_none_match=True", src)
        self.assertNotIn('put_bytes("active.json"', inspect.getsource(snap.publish) + inspect.getsource(snap.rollback))


if __name__ == "__main__":
    unittest.main()
