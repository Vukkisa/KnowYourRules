"""Cold start on a small, shared /tmp (Vercel). Several processes of one container restore the snapshot into the same disk:
each needed archives + an unpacked copy + a private copy for the index check, so two overlapping restores did not fit and the
second failed with a misleading "archive_invalid" (ENOSPC) and stayed unavailable. Restores are now serialised across processes,
archives are dropped once verified, dead processes' directories are reclaimed, and a full disk is reported as such and retried.
The snapshot, its hashes and every verification step are unchanged: these tests only touch space and ordering."""

import errno
import os
import shutil
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import test_index_snapshot as tis

from backend import index_snapshot as snap
from backend import vercel_runtime


class ColdStart(tis.Fixture):
    def setUp(self):
        super().setUp()
        self.publish()

    def test_archives_are_dropped_once_verified_when_the_host_is_small(self):
        st = self.manager(discard_archives=True).activate()
        self.assertEqual((st.state, st.ready), ("ready", True), st.problems)
        self.assertFalse((self.work / "archives").exists() and any((self.work / "archives").rglob("*.tar.gz")))
        self.assertTrue((st.db_dir / "chroma.sqlite3").is_file() and (st.lifecycle_dir / "registry.json").is_file())

    def test_archives_are_kept_by_default(self):
        st = self.manager().activate()
        self.assertTrue(st.ready, st.problems)
        self.assertTrue(any((self.work / "archives").rglob("*.tar.gz")))

    def test_verification_still_runs_when_archives_are_discarded(self):
        self.forge_archive("index", b"not a tar archive")
        st = self.manager(discard_archives=True).activate()
        self.assertFalse(st.ready)
        self.assertIn(st.state, ("checksum_mismatch", "archive_invalid"))

    def test_the_vercel_defaults_turn_the_small_disk_mode_on(self):
        env = {}
        vercel_runtime.apply_defaults(env, pid=1234, tmp_root=self.tmp / "tmp")
        self.assertEqual(env["TG_SNAPSHOT_DISCARD_ARCHIVES"], "1")
        self.assertTrue(env["TG_SNAPSHOT_WORK_DIR"].endswith("snapshots-1234"))

    def test_an_operator_value_is_never_overwritten(self):
        env = {"TG_SNAPSHOT_DISCARD_ARCHIVES": "0"}
        vercel_runtime.apply_defaults(env, pid=1, tmp_root=self.tmp / "tmp")
        self.assertEqual(env["TG_SNAPSHOT_DISCARD_ARCHIVES"], "0")

    # --- leftovers are reclaimed; a live process's extraction never is (several processes can share one pid) ---
    def test_abandoned_extractions_in_sibling_work_directories_are_reclaimed(self):
        root = self.tmp / "kyr"
        mine = root / "snapshots-8"
        gone = root / "snapshots-9"
        (gone / "run" / "old-version-8-aaaaaa" / "index").mkdir(parents=True)
        (gone / "run" / "old-version-8-aaaaaa" / "index" / "junk.bin").write_bytes(b"x" * 2048)
        (gone / "archives" / "old-version").mkdir(parents=True)
        (gone / "archives" / "old-version" / "index.tar.gz").write_bytes(b"x" * 2048)
        st = snap.SnapshotManager(self.store, mine).activate()
        self.assertTrue(st.ready, st.problems)
        self.assertFalse(gone.exists())

    def test_an_extraction_a_live_process_holds_is_never_removed(self):
        import subprocess
        import sys
        root = self.tmp / "kyr"
        busy = root / "snapshots-9" / "run" / "other-version-8-bbbbbb"
        (busy / "index").mkdir(parents=True)
        (busy / "index" / "keep.bin").write_bytes(b"x" * 2048)
        code = ("import fcntl,os,sys,time;"
                f"fd=os.open({str(busy) + '.alive'!r},os.O_RDWR|os.O_CREAT,0o600);"
                "fcntl.flock(fd,fcntl.LOCK_EX);print('held',flush=True);time.sleep(30)")
        p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(p.stdout.readline().strip(), "held")
            st = snap.SnapshotManager(self.store, root / "snapshots-8").activate()
            self.assertTrue(st.ready, st.problems)
            self.assertTrue((busy / "index" / "keep.bin").is_file())
        finally:
            p.kill()
            p.wait(10)

    def test_a_second_process_with_the_same_pid_and_work_directory_does_not_remove_the_first_ones_index(self):
        import subprocess
        import sys
        work = self.tmp / "kyr" / "snapshots-8"
        code = ("import sys,time;sys.path.insert(0,%r);from backend import index_snapshot as s;"
                "st=s.SnapshotManager(s.LocalObjectStore(%r),%r,discard_archives=True).activate();"
                "print(st.state,st.db_dir,flush=True);time.sleep(30)") % (str(Path(snap.__file__).resolve().parent.parent),
                                                                         str(self.tmp / "store"), str(work))
        p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        try:
            state, db_dir = p.stdout.readline().split(" ", 1)
            self.assertEqual(state, "ready")
            st = snap.SnapshotManager(self.store, work, discard_archives=True).activate()
            self.assertTrue(st.ready, st.problems)
            self.assertTrue((Path(db_dir.strip()) / "chroma.sqlite3").is_file())     # the first process still has its files
            self.assertNotEqual(str(st.db_dir), db_dir.strip())
        finally:
            p.kill()
            p.wait(10)

    def test_where_locks_are_not_shared_between_processes_recent_extractions_are_assumed_live(self):
        root = self.tmp / "kyr"
        old, recent = (root / "snapshots-9" / "run" / n for n in ("v-8-aaaaaa", "v-8-bbbbbb"))
        for d in (old, recent):
            (d / "index").mkdir(parents=True)
            (d / "index" / "x.bin").write_bytes(b"x" * 2048)
        past = time.time() - snap.RECENT_RUN_SECONDS - 60
        os.utime(old, (past, past))
        with mock.patch.object(snap, "_FLOCK_SHARED", False):
            st = snap.SnapshotManager(self.store, root / "snapshots-8").activate()
        self.assertTrue(st.ready, st.problems)
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())

    def test_the_lock_self_test_reports_shared_locks_on_this_host(self):
        with mock.patch.object(snap, "_FLOCK_SHARED", None):
            self.assertTrue(snap._flock_is_shared())

    def test_a_failed_restore_releases_its_ownership_marker(self):
        self.forge_archive("index", b"not a tar archive")
        self.manager().activate()
        run = self.work / "run"
        self.assertEqual(list(run.iterdir()) if run.is_dir() else [], [])

    # --- a full disk is a disk problem, not a bad archive ---
    def test_a_full_disk_while_unpacking_is_reported_as_storage_full_and_is_transient(self):
        with mock.patch.object(snap.shutil, "copyfileobj", side_effect=OSError(errno.ENOSPC, "No space left on device")):
            st = self.manager().activate()
        self.assertEqual((st.state, st.transient, st.ready), ("storage_full", True, False))
        run = self.work / "run"
        self.assertEqual(list(run.iterdir()) if run.is_dir() else [], [])

    def test_too_little_free_space_is_refused_before_anything_is_unpacked(self):
        class Usage:
            free, total, used = 0, 1 << 30, 1 << 30
        with mock.patch.object(snap.shutil, "disk_usage", return_value=Usage):
            st = self.manager().activate()
        self.assertEqual((st.state, st.transient), ("storage_full", True))
        run = self.work / "run"
        self.assertEqual(list(run.iterdir()) if run.is_dir() else [], [])

    def test_the_startup_retry_succeeds_once_space_is_available(self):
        class Usage:
            free, total, used = 0, 1 << 30, 1 << 30
        real, calls = shutil.disk_usage, []

        def usage(path):
            if Path(path) != self.work:               # the diagnostic report reads the temp directory, not the work directory
                return real(path)
            calls.append(1)
            return Usage if len(calls) == 1 else real(path)
        settings = snap.RestoreSettings()
        with mock.patch.object(snap.shutil, "disk_usage", side_effect=usage):
            st = snap.activate_with_retry(self.manager(), settings, sleep=lambda s: None)
        self.assertTrue(st.ready, st.problems)
        self.assertEqual(st.attempts, 2)

    # --- concurrent requests / processes ---
    def test_concurrent_restores_never_overlap_and_all_succeed(self):
        active, peak, lock = [0], [0], threading.Lock()
        real = snap.SnapshotManager._check_index

        def watched(mgr, *a, **k):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            try:
                time.sleep(0.15)
                return real(mgr, *a, **k)
            finally:
                with lock:
                    active[0] -= 1
        results, errors = [], []

        def go(i):
            try:
                results.append(snap.SnapshotManager(self.store, self.tmp / "kyr" / f"snapshots-{10000 + i}", discard_archives=True).activate())
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
        with mock.patch.object(snap.SnapshotManager, "_check_index", watched):
            threads = [threading.Thread(target=go, args=(i,)) for i in range(4)]
            [t.start() for t in threads]
            [t.join(60) for t in threads]
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 4)
        self.assertTrue(all(r.ready for r in results), [r.problems for r in results])
        self.assertEqual(peak[0], 1)

    def test_a_restore_that_cannot_get_the_lock_in_time_fails_as_transient(self):
        import fcntl
        path = Path(snap.tempfile.gettempdir()) / "kyr-snapshot-restore.lock"
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            with mock.patch.object(snap, "RESTORE_LOCK_WAIT", 0.3):
                st = self.manager().activate()
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        self.assertEqual((st.state, st.transient, st.ready), ("restore_busy", True, False))

    def test_a_lock_held_by_another_process_is_released_when_it_ends(self):
        import subprocess
        import sys
        code = ("import fcntl,os,sys,tempfile,time;"
                "fd=os.open(os.path.join(tempfile.gettempdir(),'kyr-snapshot-restore.lock'),os.O_RDWR|os.O_CREAT,0o600);"
                "fcntl.flock(fd,fcntl.LOCK_EX);print('held',flush=True);time.sleep(0.8)")
        p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(p.stdout.readline().strip(), "held")
            t0 = time.monotonic()
            st = self.manager().activate()
            self.assertTrue(st.ready, st.problems)
            self.assertGreater(time.monotonic() - t0, 0.3)       # it waited for the other process, then restored
        finally:
            p.wait(10)


if __name__ == "__main__":
    unittest.main()
