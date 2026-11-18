#!/usr/bin/env python3
"""Stage 7B: validate the cloud deployment's environment BEFORE the server starts. Offline: nothing is contacted, no object store
is read, no provider is called. It prints variable NAMES and reasons, never values, and exits 1 on any error.

    python scripts/check_cloud_env.py            # reads os.environ (Render runs this in front of uvicorn)
    python scripts/check_cloud_env.py --json     # machine-readable

Corpus source: TG_SNAPSHOT_STORE=r2 (Cloudflare R2) or TG_SNAPSHOT_STORE=local (a directory on a persistent mounted volume, the OCI
deployment). The local store is never created, mounted or written to here beyond one tiny probe file that is removed at once: the
volume must already be mounted, the directory must already exist, and nothing falls back to a temporary or container-local path.
The snapshot's integrity (manifest checksums, the reviewed pin, lifecycle registry, audit chain) is still verified by the server at
start; this script only checks the configuration around it.

Errors stop the start (a mis-set service must not look healthy). Warnings are legitimate-but-notable states: the service starts
and says "unavailable" where it must, e.g. no signed approval record yet, or no generation key (Groq -> Gemini -> unavailable)."""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import embedding_provider as ep  # noqa: E402
from backend import index_snapshot as snap  # noqa: E402
from backend import runtime_config  # noqa: E402

TRUE = ("1", "true", "yes", "on")


def _flag(env, name):
    return (env.get(name) or "").strip().lower() in TRUE


DEFAULT_MIN_FREE_MB = 1024          # headroom for several published snapshot versions plus one extraction (a snapshot is about 10 MB)
MIN_FREE_MB_RANGE = (64, 1_048_576)
TEMPORARY_ROOTS = ("/tmp", "/var/tmp", "/dev/shm", "/run", "/private/tmp", "/private/var/tmp")


class FileSystem:
    """The few filesystem questions this validator asks, in one place so tests can answer them without a real mount."""

    @staticmethod
    def ismount(path) -> bool:
        return os.path.ismount(path)

    @staticmethod
    def free_bytes(path) -> int:
        return shutil.disk_usage(path).free

    @staticmethod
    def writable(directory) -> bool:
        """Create and remove one tiny file. os.access alone can say yes on a volume that was remounted read-only."""
        try:
            fd, name = tempfile.mkstemp(prefix=".kyr-write-probe-", dir=str(directory))
        except OSError:
            return False
        try:
            os.write(fd, b"x")
            return True
        except OSError:
            return False
        finally:
            os.close(fd)
            try:
                os.unlink(name)
            except OSError:
                pass

    @staticmethod
    def temporary_roots() -> tuple:
        return tuple({*TEMPORARY_ROOTS, tempfile.gettempdir(), os.path.realpath(tempfile.gettempdir())})


def _inside(child, parent) -> bool:
    try:
        return Path(child).is_relative_to(parent)
    except ValueError:
        return False


def _absolute_dir(raw, name, err):
    """An explicitly configured, absolute, existing directory, resolved. Nothing is created. Returns the real path or None."""
    raw = (raw or "").strip()
    if not raw:
        err(name, "is required")
        return None
    if not os.path.isabs(raw) or ".." in Path(raw).parts:
        err(name, "must be an absolute path without '..'")
        return None
    if not os.path.isdir(raw):
        err(name, "does not exist or is not a directory (it is never created here)")
        return None
    return os.path.realpath(raw)


def check_local_store(env, err, warn, fs):
    """TG_SNAPSHOT_STORE=local: the snapshot directory must live on a persistent volume that is really mounted, be writable and have
    room. Every failure is an error: the service must not start on a missing volume or quietly use temporary storage."""
    if not _flag(env, "TG_CLOUD"):
        err("TG_CLOUD", "must be 1 with a local snapshot store: it makes the server treat this as a cloud deployment (no Ollama fallback, "
                        "mandatory embedding-model SHA-256); without it the server would run with the local-development defaults")
    min_free_mb = DEFAULT_MIN_FREE_MB
    raw_free = (env.get("TG_SNAPSHOT_MIN_FREE_MB") or "").strip()
    if raw_free:
        try:
            value = float(raw_free)
        except ValueError:
            value = float("nan")
        if MIN_FREE_MB_RANGE[0] <= value <= MIN_FREE_MB_RANGE[1]:
            min_free_mb = value
        else:
            err("TG_SNAPSHOT_MIN_FREE_MB", f"must be a number of megabytes between {MIN_FREE_MB_RANGE[0]} and {MIN_FREE_MB_RANGE[1]}")
    store = _absolute_dir(env.get("TG_SNAPSHOT_LOCAL_DIR"), "TG_SNAPSHOT_LOCAL_DIR", err)
    mount = _absolute_dir(env.get("TG_SNAPSHOT_MOUNT_POINT"), "TG_SNAPSHOT_MOUNT_POINT", err)
    temporary = [os.path.realpath(t) for t in fs.temporary_roots()]
    if mount is not None and not fs.ismount(mount):
        err("TG_SNAPSHOT_MOUNT_POINT", "is not a mount point: the persistent volume is missing or not mounted")
    if store is not None:
        if mount is not None and not _inside(store, mount):
            err("TG_SNAPSHOT_LOCAL_DIR", "must be inside the persistent volume named by TG_SNAPSHOT_MOUNT_POINT")
        if any(_inside(store, t) for t in temporary):
            err("TG_SNAPSHOT_LOCAL_DIR", "must not be in a temporary location")
        if not fs.writable(store):
            err("TG_SNAPSHOT_LOCAL_DIR", "is not writable")
        elif fs.free_bytes(store) < min_free_mb * 1024 * 1024:
            err("TG_SNAPSHOT_LOCAL_DIR", f"has less than {min_free_mb:g} MB free")
    # The restore extracts the verified snapshot here at every start. It is regenerable, so it need not be on the volume, but it
    # must be chosen explicitly: the default is a temporary directory.
    work = _absolute_dir(env.get("TG_SNAPSHOT_WORK_DIR"), "TG_SNAPSHOT_WORK_DIR", err)
    if work is not None:
        if any(_inside(work, t) for t in temporary):
            err("TG_SNAPSHOT_WORK_DIR", "must not be in a temporary location")
        if not fs.writable(work):
            err("TG_SNAPSHOT_WORK_DIR", "is not writable")
        elif fs.free_bytes(work) < min_free_mb * 1024 * 1024:
            err("TG_SNAPSHOT_WORK_DIR", f"has less than {min_free_mb:g} MB free")
    if any((env.get(name) or "").strip() for name in ("R2_ACCOUNT_ID", "R2_ENDPOINT", "R2_BUCKET", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")):
        warn("R2_*", "set but ignored: TG_SNAPSHOT_STORE=local")


def check(env=None, fs=None) -> dict:
    env = os.environ if env is None else env
    fs = fs or FileSystem()
    errors, warnings = [], []
    err = lambda name, why: errors.append({"name": name, "problem": why})        # noqa: E731
    warn = lambda name, why: warnings.append({"name": name, "problem": why})     # noqa: E731

    # --- deployment mode and the lifecycle/answer switches
    mode = runtime_config.deployment_environment(env)
    if mode not in ("production", "staging"):
        err("TG_ENVIRONMENT", "must be production (or staging) for a cloud deployment")
    if not _flag(env, "TG_GROUNDED_ANSWERS"):
        err("TG_GROUNDED_ANSWERS", "must be 1: the cloud service answers only through the grounded path")
    for name in ("TG_LEGACY_DEV_ANSWERS", "TG_KB_APPROVED", "TG_PENALTY_ANSWERS", "TG_SNAPSHOT_ALLOW_STALE", "EMBEDDING_VERIFY",
                 "EMBEDDING_NORMALIZE"):
        if (env.get(name) or "").strip():
            err(name, "must not be set in a cloud deployment (it weakens a safeguard)")
    raw_cos = (env.get("EMBEDDING_MIN_COSINE") or "").strip()
    if raw_cos:
        try:
            lowered = float(raw_cos) < 0.995
        except ValueError:
            lowered = True
        if lowered:
            err("EMBEDDING_MIN_COSINE", "must not be set below 0.995 (the compatibility gate is never weakened in a cloud deployment)")
    if _flag(env, "TG_ENABLE_APPROVAL_REFRESH"):
        err("TG_ENABLE_APPROVAL_REFRESH", "must not be set: /approval/refresh is an unauthenticated administrative scan")
    if (env.get("OLLAMA_ENABLED") or "").strip().lower() not in ("0", "false", "no", "off"):
        err("OLLAMA_ENABLED", "must be set to false: generation in the cloud is Groq -> Gemini -> unavailable; Ollama is local development")

    # --- the corpus: one verified snapshot, from R2 or from a local directory on a persistent mounted volume
    store_kind = (env.get("TG_SNAPSHOT_STORE") or "").strip().lower()
    if store_kind not in ("r2", "local"):
        err("TG_SNAPSHOT_STORE", "must be r2 or local: the corpus must come from a verified snapshot, never from a directory of the app")
    for name in ("TG_DB_DIR", "TG_LIFECYCLE_DIR"):
        if name in env:
            err(name, "must be unset: the snapshot supplies this directory")
    if store_kind == "local":
        check_local_store(env, err, warn, fs)
    elif store_kind == "r2":
        try:
            snap.store_from_env({**env, "TG_SNAPSHOT_STORE": "r2"})
        except snap.SnapshotError as exc:
            err("R2_*", str(exc.detail or exc))
    pin = (env.get("TG_SNAPSHOT_PIN_SHA256") or "").strip()
    if pin and not (len(pin) == 64 and all(c in "0123456789abcdefABCDEF" for c in pin)):
        err("TG_SNAPSHOT_PIN_SHA256", "must be 64 hex characters")
    if not pin:
        err("TG_SNAPSHOT_PIN_SHA256", "is required in production: the manifest digest you reviewed (python -m backend.index_snapshot pin); "
                                      "without it the bucket vouches for itself")
    for problem in snap.RestoreSettings.from_env(env).problems:
        err("TG_SNAPSHOT_*", problem)

    # --- query embeddings: explicit, hosted, never Ollama (settings are computed in cloud mode whatever the platform says)
    cloud_env = {**env, "TG_SNAPSHOT_STORE": "r2"}
    settings = ep.EmbeddingSettings.from_env(cloud_env)
    for problem in settings.problems:
        err("EMBEDDING_*", problem)
    if not (settings.hosted or settings.in_process) and not settings.problems:
        err("EMBEDDING_PROVIDER", "must name a hosted provider or inprocess_nomic")

    # --- browser access from GitHub Pages
    for problem in runtime_config.cors_problems({**env, "TG_ENVIRONMENT": mode if mode in ("production", "staging") else "production"}):
        err("TG_CORS_ORIGINS", problem)

    # --- notable but valid states
    if not ((env.get("GROQ_API_KEY") or "").strip() or (env.get("GEMINI_API_KEY") or "").strip()):
        warn("GROQ_API_KEY/GEMINI_API_KEY", "neither is set: generation will answer 'unavailable'")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "environment": mode or None,
            "snapshot_store": store_kind if store_kind in ("r2", "local") else None,
            "embedding": settings.describe() | {"api_key_set": bool(settings.api_key)}}


def main(argv=None, out=print, env=None, fs=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    result = check(env, fs)
    if "--json" in argv:
        out(json.dumps(result, indent=1))
    else:
        for item in result["errors"]:
            out(f"ERROR {item['name']}: {item['problem']}")
        for item in result["warnings"]:
            out(f"WARN  {item['name']}: {item['problem']}")
        out("cloud environment: OK" if result["ok"] else f"cloud environment: {len(result['errors'])} error(s); not starting")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
