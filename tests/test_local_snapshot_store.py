"""scripts/check_cloud_env.py with TG_SNAPSHOT_STORE=local (the OCI deployment: a directory on a persistent mounted volume).

Offline and deterministic. A real mount cannot be created in a test, so the filesystem questions (is it a mount point, how much is
free, may I write) go through the validator's FileSystem object and are answered by a fake; the real FileSystem is exercised for
what a temporary directory can show (not a mount point, not writable when read-only, no probe file left behind)."""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("check_cloud_env_local_store", ROOT / "scripts" / "check_cloud_env.py")
cce = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cce)

MODEL_SHA = "970aa74c0a90ef7482477cf803618e776e173c007bf957f635f1015bfcfef0e6"
SENTINELS = {"GROQ_API_KEY": "gsk_SENTINEL0123456789abcdefghij", "GEMINI_API_KEY": "AIzaSENTINEL0123456789abcdefghijklmnop",
             "R2_SECRET_ACCESS_KEY": "SENTINEL-r2-secret-0123456789"}
GB = 1024 ** 3


class FakeFs:
    """Answers the three filesystem questions; `real_writable` lets a test use the real write probe."""

    def __init__(self, mounts=(), free=50 * GB, writable=True, temporary=(), real_writable=False):
        self.mounts, self.free, self._writable, self.temp = {os.path.realpath(m) for m in mounts}, free, writable, tuple(temporary)
        self.real = cce.FileSystem() if real_writable else None

    def ismount(self, path):
        return os.path.realpath(path) in self.mounts

    def free_bytes(self, path):
        return self.free

    def writable(self, directory):
        return self.real.writable(directory) if self.real else self._writable

    def temporary_roots(self):
        return self.temp


class LocalStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kyr-local-store-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.mount = self.tmp / "volume"
        self.store = self.mount / "snapshots"
        self.work = self.tmp / "work"
        for d in (self.store, self.work):
            d.mkdir(parents=True)
        self.model = self.tmp / "nomic.gguf"
        self.model.write_bytes(b"x")
        self.fs = FakeFs(mounts=[self.mount])
        self.base = {"TG_ENVIRONMENT": "production", "TG_GROUNDED_ANSWERS": "1", "OLLAMA_ENABLED": "false", "TG_CLOUD": "1",
                     "TG_SNAPSHOT_STORE": "local", "TG_SNAPSHOT_LOCAL_DIR": str(self.store), "TG_SNAPSHOT_MOUNT_POINT": str(self.mount),
                     "TG_SNAPSHOT_WORK_DIR": str(self.work), "TG_SNAPSHOT_PIN_SHA256": "ab" * 32,
                     "EMBEDDING_PROVIDER": "inprocess_nomic", "EMBEDDING_MODEL_FILE": str(self.model), "EMBEDDING_MODEL_SHA256": MODEL_SHA,
                     "TG_CORS_ORIGINS": "https://someone.github.io", **SENTINELS}

    def run_check(self, fs=None, **change):
        env = {**self.base, **change}
        return cce.check({k: v for k, v in env.items() if v is not None}, fs or self.fs)

    def names(self, result):
        return {e["name"] for e in result["errors"]}

    def problems(self, result, name):
        return " ".join(e["problem"] for e in result["errors"] if e["name"] == name)

    # ---------------------------------------------------------------------------------------------- valid
    def test_a_complete_local_environment_on_a_mounted_volume_passes(self):
        r = self.run_check()
        self.assertEqual((r["ok"], r["errors"], r["snapshot_store"]), (True, [], "local"))
        self.assertFalse({"TG_APPROVAL_FILE", "TG_TRUSTED_KEYS_FILE"} & {w["name"] for w in r["warnings"]})   # no approval material is needed

    def test_the_store_directory_may_be_the_mount_point_itself(self):
        self.assertTrue(self.run_check(TG_SNAPSHOT_LOCAL_DIR=str(self.mount))["ok"])

    def test_the_validator_creates_nothing_and_leaves_no_probe_file(self):
        before = sorted(p.name for p in self.tmp.rglob("*"))
        self.run_check(fs=FakeFs(mounts=[self.mount], real_writable=True))
        self.assertEqual(sorted(p.name for p in self.tmp.rglob("*")), before)
        self.assertEqual(list(self.store.iterdir()), [])

    # ---------------------------------------------------------------------------------------------- missing mount
    def test_a_volume_that_is_not_mounted_stops_the_start(self):
        r = self.run_check(fs=FakeFs(mounts=[]))
        self.assertFalse(r["ok"])
        self.assertIn("not a mount point", self.problems(r, "TG_SNAPSHOT_MOUNT_POINT"))

    def test_the_real_filesystem_check_refuses_a_plain_directory_as_a_mount_point(self):
        class Real(cce.FileSystem):
            def temporary_roots(self):
                return ()
        r = cce.check({k: v for k, v in self.base.items()}, Real())
        self.assertFalse(r["ok"])
        self.assertIn("TG_SNAPSHOT_MOUNT_POINT", self.names(r))

    def test_a_missing_mount_point_or_store_directory_is_an_error_and_is_never_created(self):
        gone = self.tmp / "not-mounted"
        r = self.run_check(TG_SNAPSHOT_MOUNT_POINT=str(gone))
        self.assertIn("TG_SNAPSHOT_MOUNT_POINT", self.names(r))
        self.assertFalse(gone.exists())
        missing = self.mount / "no-such-dir"
        r = self.run_check(TG_SNAPSHOT_LOCAL_DIR=str(missing))
        self.assertIn("TG_SNAPSHOT_LOCAL_DIR", self.names(r))
        self.assertFalse(missing.exists())

    def test_a_store_directory_outside_the_volume_is_refused(self):
        elsewhere = self.tmp / "boot-disk-dir"
        elsewhere.mkdir()
        r = self.run_check(TG_SNAPSHOT_LOCAL_DIR=str(elsewhere))
        self.assertIn("inside the persistent volume", self.problems(r, "TG_SNAPSHOT_LOCAL_DIR"))

    def test_a_symlink_out_of_the_volume_does_not_count_as_inside_it(self):
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        link = self.mount / "link"
        link.symlink_to(elsewhere)
        self.assertIn("TG_SNAPSHOT_LOCAL_DIR", self.names(self.run_check(TG_SNAPSHOT_LOCAL_DIR=str(link))))

    def test_temporary_locations_are_never_accepted_even_on_a_mount(self):
        r = self.run_check(fs=FakeFs(mounts=[self.mount], temporary=[str(self.mount)]))
        self.assertIn("temporary", self.problems(r, "TG_SNAPSHOT_LOCAL_DIR"))
        r = self.run_check(fs=FakeFs(mounts=[self.mount], temporary=[str(self.work)]))
        self.assertIn("temporary", self.problems(r, "TG_SNAPSHOT_WORK_DIR"))

    def test_the_default_temporary_roots_are_refused_by_the_real_filesystem_object(self):
        roots = {os.path.realpath(t) for t in cce.FileSystem().temporary_roots()}
        self.assertTrue({os.path.realpath("/tmp"), os.path.realpath(tempfile.gettempdir())} <= roots)

    # ---------------------------------------------------------------------------------------------- unwritable
    def test_an_unwritable_store_directory_is_an_error(self):
        r = self.run_check(fs=FakeFs(mounts=[self.mount], writable=False))
        self.assertIn("not writable", self.problems(r, "TG_SNAPSHOT_LOCAL_DIR"))
        self.assertIn("not writable", self.problems(r, "TG_SNAPSHOT_WORK_DIR"))

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can write anywhere")
    def test_a_read_only_directory_fails_the_real_write_probe(self):
        os.chmod(self.store, 0o500)
        self.addCleanup(os.chmod, self.store, 0o700)
        r = self.run_check(fs=FakeFs(mounts=[self.mount], real_writable=True))
        self.assertIn("not writable", self.problems(r, "TG_SNAPSHOT_LOCAL_DIR"))
        self.assertEqual(list(self.store.iterdir()), [])

    # ---------------------------------------------------------------------------------------------- free space
    def test_too_little_free_space_is_an_error_and_the_threshold_is_configurable(self):
        r = self.run_check(fs=FakeFs(mounts=[self.mount], free=100 * 1024 * 1024))
        self.assertIn("MB free", self.problems(r, "TG_SNAPSHOT_LOCAL_DIR"))
        self.assertTrue(self.run_check(fs=FakeFs(mounts=[self.mount], free=100 * 1024 * 1024), TG_SNAPSHOT_MIN_FREE_MB="64")["ok"])
        self.assertFalse(self.run_check(fs=FakeFs(mounts=[self.mount], free=2 * GB), TG_SNAPSHOT_MIN_FREE_MB="4096")["ok"])

    def test_the_default_threshold_is_one_gibibyte(self):
        self.assertEqual(cce.DEFAULT_MIN_FREE_MB, 1024)
        self.assertTrue(self.run_check(fs=FakeFs(mounts=[self.mount], free=GB))["ok"])
        self.assertFalse(self.run_check(fs=FakeFs(mounts=[self.mount], free=GB - 1))["ok"])

    # ---------------------------------------------------------------------------------------------- invalid configuration
    def test_each_missing_or_invalid_local_setting_is_an_error(self):
        cases = {
            "TG_SNAPSHOT_LOCAL_DIR": [{"TG_SNAPSHOT_LOCAL_DIR": None}, {"TG_SNAPSHOT_LOCAL_DIR": ""}, {"TG_SNAPSHOT_LOCAL_DIR": "relative/dir"},
                                      {"TG_SNAPSHOT_LOCAL_DIR": str(self.store) + "/../snapshots"}],
            "TG_SNAPSHOT_MOUNT_POINT": [{"TG_SNAPSHOT_MOUNT_POINT": None}, {"TG_SNAPSHOT_MOUNT_POINT": "volume"}],
            "TG_SNAPSHOT_WORK_DIR": [{"TG_SNAPSHOT_WORK_DIR": None}, {"TG_SNAPSHOT_WORK_DIR": "work"}],
            "TG_SNAPSHOT_MIN_FREE_MB": [{"TG_SNAPSHOT_MIN_FREE_MB": "lots"}, {"TG_SNAPSHOT_MIN_FREE_MB": "1"}, {"TG_SNAPSHOT_MIN_FREE_MB": "nan"}],
            "TG_SNAPSHOT_STORE": [{"TG_SNAPSHOT_STORE": "s3"}, {"TG_SNAPSHOT_STORE": None}, {"TG_SNAPSHOT_STORE": "file"}],
            "TG_SNAPSHOT_PIN_SHA256": [{"TG_SNAPSHOT_PIN_SHA256": None}, {"TG_SNAPSHOT_PIN_SHA256": "xyz"}],
        }
        for name, changes in cases.items():
            for change in changes:
                r = self.run_check(**change)
                self.assertFalse(r["ok"], change)
                self.assertIn(name, self.names(r), change)

    def test_a_local_store_requires_tg_cloud_so_the_server_keeps_its_cloud_safeguards(self):
        for change in ({"TG_CLOUD": None}, {"TG_CLOUD": "0"}, {"TG_CLOUD": "no"}):
            self.assertIn("TG_CLOUD", self.names(self.run_check(**change)), change)

    def test_the_directory_overrides_stay_forbidden(self):
        for name in ("TG_DB_DIR", "TG_LIFECYCLE_DIR"):
            self.assertIn(name, self.names(self.run_check(**{name: "/srv/x"})))

    def test_a_missing_work_directory_never_falls_back_to_the_temporary_default(self):
        r = self.run_check(TG_SNAPSHOT_WORK_DIR=None)
        self.assertIn("is required", self.problems(r, "TG_SNAPSHOT_WORK_DIR"))

    def test_r2_settings_alongside_a_local_store_are_ignored_with_a_warning(self):
        r = self.run_check(R2_ACCOUNT_ID="acct", R2_BUCKET="b")
        self.assertTrue(r["ok"])
        self.assertIn("R2_*", {w["name"] for w in r["warnings"]})

    # ---------------------------------------------------------------------------------------------- other safeguards unchanged
    def test_every_other_cloud_safeguard_is_still_enforced_with_a_local_store(self):
        cases = {"TG_ENVIRONMENT": {"TG_ENVIRONMENT": "development"}, "TG_GROUNDED_ANSWERS": {"TG_GROUNDED_ANSWERS": "0"},
                 "OLLAMA_ENABLED": {"OLLAMA_ENABLED": None}, "TG_KB_APPROVED": {"TG_KB_APPROVED": "1"},
                 "TG_PENALTY_ANSWERS": {"TG_PENALTY_ANSWERS": "1"}, "TG_LEGACY_DEV_ANSWERS": {"TG_LEGACY_DEV_ANSWERS": "1"},
                 "TG_SNAPSHOT_ALLOW_STALE": {"TG_SNAPSHOT_ALLOW_STALE": "1"}, "EMBEDDING_VERIFY": {"EMBEDDING_VERIFY": "off"},
                 "EMBEDDING_MIN_COSINE": {"EMBEDDING_MIN_COSINE": "0.5"},
                 "TG_ENABLE_APPROVAL_REFRESH": {"TG_ENABLE_APPROVAL_REFRESH": "1"}, "TG_CORS_ORIGINS": {"TG_CORS_ORIGINS": "*"},
                 "EMBEDDING_*": {"EMBEDDING_PROVIDER": "ollama"}}
        for name, change in cases.items():
            r = self.run_check(**change)
            self.assertFalse(r["ok"], name)
            self.assertIn(name, self.names(r), name)

    def test_the_in_process_model_pin_is_still_mandatory(self):
        r = self.run_check(EMBEDDING_MODEL_SHA256=None)
        self.assertFalse(r["ok"])
        self.assertIn("EMBEDDING_*", self.names(r))

    def test_without_an_approval_the_service_starts_and_does_not_warn_about_one(self):
        r = self.run_check()
        self.assertTrue(r["ok"])
        self.assertEqual({w["name"] for w in r["warnings"]} & {"TG_APPROVAL_FILE", "TG_TRUSTED_KEYS_FILE"}, set())

    # ---------------------------------------------------------------------------------------------- R2 is intact
    def test_r2_still_passes_without_any_local_setting_and_ignores_them(self):
        r2 = {"TG_ENVIRONMENT": "production", "TG_GROUNDED_ANSWERS": "1", "OLLAMA_ENABLED": "false", "TG_SNAPSHOT_STORE": "r2",
              "R2_ACCOUNT_ID": "acct", "R2_BUCKET": "kyr", "R2_ACCESS_KEY_ID": "keyid0123", "R2_SECRET_ACCESS_KEY": "secret0123",
              "TG_SNAPSHOT_PIN_SHA256": "ab" * 32, "EMBEDDING_PROVIDER": "inprocess_nomic",
              "EMBEDDING_MODEL_FILE": str(self.model), "EMBEDDING_MODEL_SHA256": MODEL_SHA, "TG_CORS_ORIGINS": "https://someone.github.io"}
        r = cce.check(r2, FakeFs(mounts=[]))
        self.assertEqual((r["ok"], r["errors"], r["snapshot_store"]), (True, [], "r2"))
        self.assertTrue(cce.check({**r2, "TG_SNAPSHOT_MOUNT_POINT": "/nowhere", "TG_SNAPSHOT_LOCAL_DIR": "relative"}, FakeFs(mounts=[]))["ok"])
        self.assertFalse(cce.check({k: v for k, v in r2.items() if k != "R2_BUCKET"}, FakeFs(mounts=[]))["ok"])

    # ---------------------------------------------------------------------------------------------- reporting
    def test_the_report_never_contains_a_path_or_a_secret_value(self):
        gone = self.tmp / "private-volume-name"
        for fs, change in ((self.fs, {}), (FakeFs(mounts=[]), {"TG_SNAPSHOT_MOUNT_POINT": str(gone)})):
            lines = []
            env = {**self.base, **change}
            cce.main([], out=lines.append, env=env, fs=fs)
            cce.main(["--json"], out=lines.append, env=env, fs=fs)
            text = "\n".join(lines)
            for value in (*SENTINELS.values(), str(self.tmp), "private-volume-name", MODEL_SHA):
                self.assertNotIn(value, text)

    def test_main_exits_non_zero_on_a_missing_mount_and_zero_on_a_good_one(self):
        lines = []
        self.assertEqual(cce.main([], out=lines.append, env=dict(self.base), fs=self.fs), 0)
        self.assertEqual(cce.main([], out=lines.append, env=dict(self.base), fs=FakeFs(mounts=[])), 1)
        self.assertTrue(any("not a mount point" in l for l in lines))

    def test_the_script_run_as_a_process_fails_closed_with_a_plain_directory(self):
        import subprocess
        env = {k: v for k, v in self.base.items() if v is not None}
        env["PATH"] = os.environ.get("PATH", "")
        p = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_cloud_env.py"), "--json"], env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)
        names = {e["name"] for e in json.loads(p.stdout)["errors"]}
        self.assertIn("TG_SNAPSHOT_MOUNT_POINT", names)


if __name__ == "__main__":
    unittest.main()
