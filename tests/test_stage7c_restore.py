"""Stage 7C: the R2 restore at start: bounded retries for transient failures, no retry for integrity failures, the pin, same-snapshot
consistency, and secret-free errors. Offline: a local-directory store and a mocked HTTP layer; sleeping and time are injected, so
nothing waits. Real R2 is not exercised (see the Stage 7C report)."""
import hashlib
import logging
import unittest

import requests

import test_index_snapshot as tis
from backend import index_snapshot as snap

SECRET = "SECRET-VALUE-0123456789-MUST-NOT-APPEAR"


class FlakyStore(snap.ObjectStore):
    """Delegates to a real store. `plan` maps a key (substring) to a list of outcomes consumed one per read: an exception to raise, or None."""

    def __init__(self, inner, plan=None):
        self.inner, self.plan, self.reads = inner, dict(plan or {}), []

    def _maybe(self, key):
        self.reads.append(key)
        for needle, outcomes in self.plan.items():
            if needle in key and outcomes:
                o = outcomes.pop(0)
                if o is not None:
                    raise o

    def get_stream(self, key):
        self._maybe(key)
        return self.inner.get_stream(key)

    def put_bytes(self, key, data):
        self.inner.put_bytes(key, data)

    def exists(self, key):
        return self.inner.exists(key)

    def get_with_etag(self, key):
        return self.inner.get_with_etag(key)

    def put_conditional(self, key, data, **kw):
        return self.inner.put_conditional(key, data, **kw)


class Clock:
    def __init__(self):
        self.now, self.sleeps = 0.0, []

    def sleep(self, d):
        self.sleeps.append(d)
        self.now += d

    def __call__(self):
        return self.now


def transient(msg="object store timed out"):
    return snap.StoreError(msg, transient=True)


class RestoreRetryTests(tis.Fixture):
    def setUp(self):
        super().setUp()
        self.m = self.publish()
        self.clock = Clock()
        self.settings = snap.RestoreSettings(startup_timeout=60, retry_base=1, retry_max_delay=15)

    def restore(self, store=None, pin=None, **kw):
        mgr = snap.SnapshotManager(store or self.store, self.tmp / "work", pin_sha256=pin)
        return snap.activate_with_retry(mgr, kw.get("settings", self.settings), sleep=self.clock.sleep, clock=self.clock)

    def test_a_clean_restore_is_one_attempt_and_ready(self):
        st = self.restore()
        self.assertEqual((st.state, st.attempts, st.ready, st.timed_out), ("ready", 1, True, False))
        self.assertEqual(self.clock.sleeps, [])

    def test_transient_failures_are_retried_with_exponential_backoff_then_succeed(self):
        store = FlakyStore(self.store, {"active.json": [transient(), transient(), transient(), None]})
        st = self.restore(store)
        self.assertTrue(st.ready)
        self.assertEqual((st.attempts, self.clock.sleeps), (4, [1, 2, 4]))

    def test_backoff_is_capped_at_the_maximum_delay(self):
        store = FlakyStore(self.store, {"active.json": [transient()] * 7 + [None]})
        st = self.restore(store, settings=snap.RestoreSettings(startup_timeout=600, retry_base=1, retry_max_delay=10))
        self.assertTrue(st.ready)
        self.assertEqual(self.clock.sleeps, [1, 2, 4, 8, 10, 10, 10])

    def test_a_store_that_never_recovers_gives_up_within_the_startup_budget(self):
        store = FlakyStore(self.store, {"active.json": [transient()] * 100})
        st = self.restore(store)
        self.assertFalse(st.ready)
        self.assertTrue(st.timed_out)
        self.assertEqual(st.state, "store_unavailable")
        self.assertLessEqual(self.clock.now, 60)                               # never sleeps past the budget
        self.assertGreater(st.attempts, 3)
        self.assertTrue(any("budget" in p for p in st.problems))
        self.assertIsNone(st.db_dir)                                           # nothing half-restored is handed out
        self.assertIsNone(st.lifecycle_dir)

    def test_a_permanent_store_refusal_is_not_retried(self):
        store = FlakyStore(self.store, {"active.json": [snap.StoreError("object store returned HTTP 403")] * 5})
        st = self.restore(store)
        self.assertEqual((st.ready, st.state, st.attempts, self.clock.sleeps), (False, "store_unavailable", 1, []))
        self.assertFalse(st.transient)

    def test_integrity_failures_are_final_on_the_first_attempt(self):
        (self.tmp / "store" / self.m["index"]["archive"]).write_bytes(b"corrupt")
        st = self.restore()
        self.assertEqual((st.state, st.attempts, st.ready, self.clock.sleeps), ("checksum_mismatch", 1, False, []))
        self.assertFalse(st.transient)
        self.assertIsNone(st.db_dir)

    def test_a_missing_object_and_a_missing_manifest_are_final(self):
        (self.tmp / "store" / self.m["lifecycle"]["archive"]).unlink()
        st = self.restore()
        self.assertEqual((st.state, st.attempts), ("snapshot_missing", 1))
        (self.tmp / "store" / "active.json").unlink()
        st = self.restore()
        self.assertEqual((st.state, st.attempts), ("manifest_missing", 1))

    def test_a_download_that_breaks_midway_is_retried_and_restored_whole(self):
        calls = []

        class Breaking(FlakyStore):
            def get_stream(s, key):
                if "index.tar.gz" in key and not calls:
                    calls.append(1)
                    def gen():
                        yield b"partial"
                        raise transient("object store read failed (ConnectionError)")
                    return gen()
                return super().get_stream(key)
        st = self.restore(Breaking(self.store))
        self.assertTrue(st.ready)
        work = self.tmp / "work" / "archives" / self.m["version"]
        self.assertFalse(list(work.glob("*.part")))                            # no partial file is left behind
        self.assertEqual(snap.sha256_file(work / "index.tar.gz"), self.m["index"]["sha256"])

    def test_a_stale_partial_file_from_an_earlier_crash_never_becomes_the_archive(self):
        d = self.tmp / "work" / "archives" / self.m["version"]
        d.mkdir(parents=True)
        (d / "index.tar.gz.part").write_bytes(b"half a download")
        (d / "index.tar.gz").write_bytes(b"truncated archive")
        st = self.restore()
        self.assertTrue(st.ready)

    def test_index_and_registry_come_from_the_same_manifest(self):
        st = self.restore()
        v = st.manifest["version"]
        self.assertEqual((st.manifest["index"]["archive"], st.manifest["lifecycle"]["archive"]), (f"snapshots/{v}/index.tar.gz", f"snapshots/{v}/lifecycle.tar.gz"))
        self.assertEqual(snap.sha256_file(st.lifecycle_dir / "registry.json"), st.manifest["lifecycle"]["registry_sha256"])

    def test_a_manifest_that_mixes_in_another_versions_archive_is_refused(self):
        self.publish(version="v-other")
        self.rewrite(lambda m: m["lifecycle"].update(archive=f"snapshots/{self.m['version']}/lifecycle.tar.gz"))   # the OLDER snapshot's archive
        st = self.restore()
        self.assertEqual(st.state, "manifest_invalid")
        self.assertFalse(st.ready)

    def test_a_failed_restore_hands_out_no_directories_and_a_later_success_recovers(self):
        store = FlakyStore(self.store, {"active.json": [transient()] * 100})
        bad = self.restore(store, settings=snap.RestoreSettings(startup_timeout=5, retry_base=1, retry_max_delay=2))
        self.assertFalse(bad.ready)
        self.assertEqual((bad.db_dir, bad.lifecycle_dir), (None, None))
        good = self.restore()                                                  # the store is back: a fresh start restores fully
        self.assertTrue(good.ready)
        self.assertTrue((good.db_dir / "chroma.sqlite3").is_file())


class PinTests(tis.Fixture):
    def setUp(self):
        super().setUp()
        self.m = self.publish()
        self.digest = snap.sha256_bytes(self.store.get_bytes(f"manifests/{self.m['version']}.json"))
        self.base = {"TG_SNAPSHOT_STORE": "local", "TG_SNAPSHOT_LOCAL_DIR": str(self.tmp / "store"), "TG_SNAPSHOT_PREFIX": "",
                     "TG_SNAPSHOT_WORK_DIR": str(self.tmp / "w")}

    def activate(self, **env):
        return snap.activate_from_env({**self.base, **env}, sleep=lambda d: None)

    def test_production_without_a_pin_does_not_restore_at_all(self):
        st = self.activate(TG_ENVIRONMENT="production")
        self.assertEqual((st.state, st.ready), ("pin_required", False))
        self.assertIn("TG_SNAPSHOT_PIN_SHA256", st.problems[0])
        st = self.activate(TG_ENVIRONMENT="staging")
        self.assertEqual(st.state, "pin_required")

    def test_a_malformed_pin_is_refused(self):
        for bad in ("xyz", "ab" * 31, "g" * 64, "ab" * 33):
            self.assertEqual(self.activate(TG_ENVIRONMENT="production", TG_SNAPSHOT_PIN_SHA256=bad).state, "misconfigured", bad)

    def test_the_right_pin_restores_and_marks_the_snapshot_pinned(self):
        st = self.activate(TG_ENVIRONMENT="production", TG_SNAPSHOT_PIN_SHA256=self.digest)
        self.assertEqual((st.state, st.pinned), ("ready", True))
        self.assertTrue(st.public()["pinned"])
        self.assertTrue(self.activate(TG_ENVIRONMENT="production", TG_SNAPSHOT_PIN_SHA256=self.digest.upper()).pinned)

    def test_a_mismatching_pin_fails_closed_and_is_final(self):
        st = self.activate(TG_ENVIRONMENT="production", TG_SNAPSHOT_PIN_SHA256="0" * 64)
        self.assertEqual((st.state, st.ready, st.attempts), ("pin_mismatch", False, 1))
        self.assertIsNone(st.db_dir)

    def test_a_pin_for_an_older_snapshot_does_not_accept_a_newer_one(self):
        self.publish(version="v-newer")
        st = self.activate(TG_ENVIRONMENT="production", TG_SNAPSHOT_PIN_SHA256=self.digest)
        self.assertEqual(st.state, "pin_mismatch")                             # the pointer moved; the reviewed manifest is no longer the active one

    def test_development_keeps_the_pin_optional(self):
        st = self.activate()
        self.assertEqual((st.state, st.pinned), ("ready", False))

    def test_the_pin_cli_prints_the_digest_of_the_reviewed_active_manifest(self):
        out = []
        import os
        old = {k: os.environ.get(k) for k in self.base}
        os.environ.update(self.base)
        try:
            self.assertEqual(snap.main(["pin"], out=out.append), 0)
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        import json
        info = json.loads(out[0])
        self.assertEqual((info["manifest_sha256"], info["TG_SNAPSHOT_PIN_SHA256"], info["version"]), (self.digest, self.digest, self.m["version"]))

    def test_the_pin_cli_refuses_a_manifest_that_does_not_match_the_pointer(self):
        import os
        raw = self.store.get_bytes(f"manifests/{self.m['version']}.json")
        (self.tmp / "store" / f"manifests/{self.m['version']}.json").write_bytes(raw + b" ")
        out = []
        os.environ.update(self.base)
        try:
            self.assertEqual(snap.main(["pin"], out=out.append), 1)
        finally:
            for k in self.base:
                os.environ.pop(k, None)
        self.assertIn("do not pin", out[0])


class HttpFailureTests(unittest.TestCase):
    """S3CompatStore failure classification and secret hygiene, with a mocked HTTP layer."""

    def env(self):
        return {"TG_SNAPSHOT_STORE": "r2", "R2_ENDPOINT": "https://acct.r2.example", "R2_BUCKET": "b", "R2_ACCESS_KEY_ID": "AKID" + SECRET,
                "R2_SECRET_ACCESS_KEY": SECRET, "TG_SNAPSHOT_WORK_DIR": "/nonexistent-never-used", "TG_SNAPSHOT_STARTUP_TIMEOUT_SECONDS": "5",
                "TG_SNAPSHOT_RETRY_BASE_SECONDS": "0.1", "TG_SNAPSHOT_RETRY_MAX_DELAY_SECONDS": "1"}

    class Resp:
        def __init__(self, code):
            self.status_code, self.headers, self.content = code, {}, b""

        def close(self):
            pass

        def iter_content(self, n):
            return iter(())

    def run_with(self, http):
        sleeps = []
        clock = Clock()
        st = snap.activate_from_env(self.env(), http=http, sleep=clock.sleep, clock=clock)
        return st, clock

    def test_server_errors_and_timeouts_are_transient_and_retried_to_the_budget(self):
        for http in (lambda *a, **k: self.Resp(503), lambda *a, **k: self.Resp(429), self.raiser(requests.Timeout()), self.raiser(requests.ConnectionError())):
            st, clock = self.run_with(http)
            self.assertEqual(st.state, "store_unavailable")
            self.assertTrue(st.transient and st.timed_out)
            self.assertGreater(st.attempts, 2)

    def raiser(self, exc):
        def http(*a, **k):
            raise exc
        return http

    def test_authentication_and_other_client_errors_are_permanent_and_not_retried(self):
        for code in (400, 401, 403):
            st, clock = self.run_with(lambda *a, code=code, **k: self.Resp(code))
            self.assertEqual((st.state, st.attempts, st.transient, st.timed_out), ("store_unavailable", 1, False, False), code)

    def test_a_missing_pointer_is_not_a_transient_error(self):
        st, _ = self.run_with(lambda *a, **k: self.Resp(404))
        self.assertEqual((st.state, st.attempts), ("manifest_missing", 1))

    def test_no_credential_reaches_the_status_or_the_logs(self):
        records = []

        class H(logging.Handler):
            def emit(s, r):
                records.append(r.getMessage())
        h = H()
        logging.getLogger().addHandler(h)
        try:
            st, _ = self.run_with(lambda *a, **k: self.Resp(503))
            st2, _ = self.run_with(self.raiser(requests.ConnectionError(SECRET)))
        finally:
            logging.getLogger().removeHandler(h)
        blob = repr((st.public(), st.problems, st2.public(), st2.problems, records))
        self.assertNotIn(SECRET, blob)
        self.assertNotIn("AKID", blob)

    def test_the_retry_settings_are_validated(self):
        for name, bad in (("TG_SNAPSHOT_STARTUP_TIMEOUT_SECONDS", "0"), ("TG_SNAPSHOT_STARTUP_TIMEOUT_SECONDS", "forever"),
                          ("TG_SNAPSHOT_RETRY_BASE_SECONDS", "-1"), ("TG_SNAPSHOT_RETRY_MAX_DELAY_SECONDS", "1000")):
            s = snap.RestoreSettings.from_env({name: bad})
            self.assertTrue(s.problems, (name, bad))
        self.assertEqual(snap.RestoreSettings.from_env({}).problems, ())
        env = {**self.env(), "TG_SNAPSHOT_STARTUP_TIMEOUT_SECONDS": "forever"}
        self.assertEqual(snap.activate_from_env(env).state, "misconfigured")

    def test_the_transient_flag_is_assigned_by_cause(self):
        self.assertTrue(snap._http_error(500).transient)
        self.assertTrue(snap._http_error(429).transient)
        self.assertFalse(snap._http_error(403).transient)
        self.assertFalse(snap._http_error(412).transient)
        self.assertFalse(snap.StoreError("x").transient)


if __name__ == "__main__":
    unittest.main()
