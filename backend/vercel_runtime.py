"""Start-up preparation for running backend.server on Vercel Hobby (Python function, read-only filesystem, writable /tmp, no persistent disk).

Used only by backend/vercel_app.py, BEFORE backend.server is imported. It changes no retrieval, legal or provider behaviour. It does three things:

  1. apply_defaults: fills in the paths and fixed values that are the same on every Vercel deployment (never a secret, never a value that
     decides legal behaviour: TG_ENVIRONMENT, the snapshot pin and the client-IP source must be set by the operator).
  2. validate: refuses (by raising) a configuration that would weaken a safeguard: Ollama, EMBEDDING_VERIFY=off, a missing pin, a
     different embedding model, a store other than the bundled snapshot, an unset client-IP source. A misconfigured deployment answers
     nothing (HTTP 500 at start-up); it never runs half-configured.
  3. fetch_model_to_memory: puts the exact pinned Nomic GGUF (SHA-256 970aa74c..., 274,290,656 bytes) into an anonymous memory buffer, NOT
     into /tmp. The 262 MiB file does not fit in the writable space that is left once the dependencies are in the bundle (the bundle and /tmp
     share about 500 MB), so it is downloaded from the URL the operator names (KYR_MODEL_URL), size- and SHA-256-checked WHILE streaming, and
     only a fully verified buffer is handed to the engine. No model file and no lock file is ever written. The engine (backend/nomic_local.py)
     hashes the buffer again before it parses it, and the probe-vector check against the snapshot manifest still runs; nothing here relaxes
     either. ensure_model (the earlier /tmp file download) is kept unused, so reverting is a one-function change.

The index and the lifecycle registry are NOT handled here: they come from the verified snapshot in snapshot-store/ (TG_SNAPSHOT_STORE=local,
read-only inside the bundle), restored into a per-process directory under /tmp by backend/index_snapshot.py exactly as on every other host.

Nothing is logged that could carry a secret: the download URL (which may be a pre-signed link) is never written to a log or an error."""
from __future__ import annotations

import errno
import fcntl
import hashlib
import logging
import mmap
import os
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from backend import nomic_local

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_SHA256 = nomic_local.KNOWN_MODEL_SHA256
MODEL_BYTES = 274290656             # the exact pinned file (measured); an early abort for a wrong download, the SHA-256 is the proof
MODEL_FILENAME = "nomic-embed-text-v1.5.f16.gguf"
EXPECT_FAMILY = "nomic-embed-text-v1.5"
FREE_SPACE_MARGIN = 64 * 1024 * 1024
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class VercelConfigError(RuntimeError):
    """The environment is unsafe or incomplete. The message lists problems by variable name only (never values)."""


class ModelFetchError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code


def _truthy(value) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes")


def _blank(env, name) -> bool:
    return not (env.get(name) or "").strip()


def work_root() -> Path:
    return Path(tempfile.gettempdir()) / "kyr"


def apply_defaults(env, *, pid: int | None = None, tmp_root: Path | None = None, project_root: Path = PROJECT_ROOT) -> None:
    """Fill in only what is identical on every Vercel deployment. An operator value is never overwritten."""
    root = Path(tmp_root) if tmp_root is not None else work_root()
    # A snapshot work directory per process: the restore stages archives under fixed names, so two processes sharing one /tmp
    # directory could overwrite each other's partial file. Per-process directories make that impossible (the index is ~10 MB).
    defaults = {
        "TG_CLOUD": "1",                       # forces the cloud embedding rules even for a local store: never an Ollama fallback
        "OLLAMA_ENABLED": "false",
        "TG_GROUNDED_ANSWERS": "1",
        "EMBEDDING_PROVIDER": "inprocess_nomic",
        "EMBEDDING_MODEL_SHA256": MODEL_SHA256,
        "EMBEDDING_MODEL_SOURCE": "memory",    # the model is downloaded into RAM: /tmp has no room for it next to the bundle
        "TG_SNAPSHOT_STORE": "local",
        "TG_SNAPSHOT_LOCAL_DIR": str(Path(project_root) / "snapshot-store"),
        "TG_SNAPSHOT_WORK_DIR": str(root / f"snapshots-{os.getpid() if pid is None else pid}"),
        "TG_SNAPSHOT_EXPECT_FAMILY": EXPECT_FAMILY,
    }
    corpus = Path(project_root) / "legal" / "source-documents"
    if corpus.is_dir():
        # The deployment folder carries a copy of the source files, so every chunk's file hash is still checked against them.
        defaults["TG_CORPUS_DIR"] = str(corpus)
    for name, value in defaults.items():
        if _blank(env, name):
            env[name] = value


def _inside(child, parent) -> bool:
    try:
        Path(os.path.realpath(child)).relative_to(Path(os.path.realpath(parent)))
        return True
    except ValueError:
        return False


def validate_model_url(url: str) -> str | None:
    """None when acceptable, else a reason that contains no part of the URL."""
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
    except ValueError:
        return "is not a valid URL"
    if parts.scheme != "https":
        return "must be an https URL"
    if not host:
        return "has no host"
    if parts.username or parts.password:
        return "must not contain credentials"
    return None


def validate(env, *, tmp_root: Path | None = None, project_root: Path = PROJECT_ROOT) -> list[str]:
    """Problems that must stop the deployment, by variable name. Empty means the configuration is acceptable (not that it works)."""
    tmp = Path(tmp_root) if tmp_root is not None else Path(tempfile.gettempdir())
    errors: list[str] = []

    def need(cond, text):
        if not cond:
            errors.append(text)

    need((env.get("TG_ENVIRONMENT") or "").strip().lower() == "production", "TG_ENVIRONMENT must be production")
    need(_truthy(env.get("TG_GROUNDED_ANSWERS")), "TG_GROUNDED_ANSWERS must be 1 (validated, grounded answers)")
    need(not _truthy(env.get("TG_LEGACY_DEV_ANSWERS")), "TG_LEGACY_DEV_ANSWERS must not be set")
    need(not _truthy(env.get("OLLAMA_ENABLED")), "OLLAMA_ENABLED must be false (no Ollama on Vercel)")
    need(_truthy(env.get("TG_CLOUD")), "TG_CLOUD must be 1")
    need((env.get("EMBEDDING_PROVIDER") or "").strip().lower() == "inprocess_nomic", "EMBEDDING_PROVIDER must be inprocess_nomic")
    need((env.get("EMBEDDING_MODEL_SHA256") or "").strip().lower() == MODEL_SHA256,
         "EMBEDDING_MODEL_SHA256 must be the pinned nomic-embed-text-v1.5 F16 hash")
    need((env.get("EMBEDDING_VERIFY") or "auto").strip().lower() in ("auto", "required"), "EMBEDDING_VERIFY must be auto or required")
    need((env.get("TG_SNAPSHOT_STORE") or "").strip().lower() == "local", "TG_SNAPSHOT_STORE must be local (the bundled snapshot)")
    need((env.get("TG_SNAPSHOT_EXPECT_FAMILY") or "").strip() == EXPECT_FAMILY, "TG_SNAPSHOT_EXPECT_FAMILY must be nomic-embed-text-v1.5")
    need(bool(_HEX64.match((env.get("TG_SNAPSHOT_PIN_SHA256") or "").strip().lower())),
         "TG_SNAPSHOT_PIN_SHA256 must be the 64-hex SHA-256 of the reviewed snapshot manifest")
    need(_blank(env, "TG_DB_DIR") and _blank(env, "TG_LIFECYCLE_DIR"), "TG_DB_DIR and TG_LIFECYCLE_DIR must not be set (snapshot mode)")
    need((env.get("TG_CLIENT_IP_SOURCE") or "").strip().lower() == "vercel",
         "TG_CLIENT_IP_SOURCE must be vercel (otherwise every visitor shares the platform's address as one rate-limit bucket)")
    need(bool((env.get("VERCEL") or "").strip()), "VERCEL is not set: this entry point is for Vercel only")

    local_dir = (env.get("TG_SNAPSHOT_LOCAL_DIR") or "").strip()
    need(bool(local_dir) and _inside(local_dir, project_root) and not _inside(local_dir, tmp),
         "TG_SNAPSHOT_LOCAL_DIR must be inside the deployment bundle (read-only), not in /tmp")
    value = (env.get("TG_SNAPSHOT_WORK_DIR") or "").strip()
    need(bool(value) and _inside(value, tmp), f"TG_SNAPSHOT_WORK_DIR must be under {tmp} (the only writable location)")
    need((env.get("EMBEDDING_MODEL_SOURCE") or "").strip().lower() == "memory", "EMBEDDING_MODEL_SOURCE must be memory (no model file is written to /tmp)")
    need(_blank(env, "EMBEDDING_MODEL_FILE"), "EMBEDDING_MODEL_FILE must not be set (the model is held in memory)")

    url = (env.get("KYR_MODEL_URL") or "").strip()
    if url:
        why = validate_model_url(url)
        need(why is None, f"KYR_MODEL_URL {why}")
    return errors


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise urllib.error.URLError("redirect to a non-https address refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _default_opener():
    return urllib.request.build_opener(_HttpsOnlyRedirects).open


class _Lock:
    """flock on a sidecar file, polled so a stuck holder cannot block start-up beyond `timeout` seconds."""

    def __init__(self, path: Path, timeout: float, clock=time.monotonic, sleep=time.sleep):
        self.path, self.timeout, self.clock, self.sleep, self.fd = path, timeout, clock, sleep, None

    def __enter__(self):
        self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        end = self.clock() + self.timeout
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError as exc:
                if exc.errno not in (errno.EAGAIN, errno.EACCES):
                    os.close(self.fd)
                    raise
                if self.clock() >= end:
                    os.close(self.fd)
                    raise ModelFetchError("lock_timeout", "another process is still preparing the model file") from None
                self.sleep(0.25)

    def __exit__(self, *exc):
        try:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            os.close(self.fd)


def ensure_model(path, url: str | None, *, sha256: str = MODEL_SHA256, size: int = MODEL_BYTES, opener=None, timeout: float = 30.0,
                 deadline_seconds: float = 150.0, lock_timeout: float = 170.0, clock=time.monotonic, sleep=time.sleep) -> dict:
    """Make `path` hold the pinned model. Returns {"downloaded": bool, "seconds": float}. Raises ModelFetchError (code, safe detail)."""
    t0 = clock()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _Lock(path.with_name(path.name + ".lock"), lock_timeout, clock, sleep):
        if path.is_file():
            if path.stat().st_size == size and _sha256_file(path) == sha256:
                return {"downloaded": False, "seconds": round(clock() - t0, 3)}
            log.warning("model file present but failed verification: replacing it")
            path.unlink()
        if not url:
            raise ModelFetchError("model_missing", "the model file is absent and KYR_MODEL_URL is not set")
        why = validate_model_url(url)
        if why:
            raise ModelFetchError("bad_url", f"KYR_MODEL_URL {why}")
        free = shutil.disk_usage(path.parent).free
        if free < size + FREE_SPACE_MARGIN:
            raise ModelFetchError("no_space", f"{free // (1 << 20)} MiB free, {size // (1 << 20)} MiB needed")
        opener = opener or _default_opener()
        deadline = t0 + deadline_seconds
        for attempt in (1, 2):
            try:
                _download(path, url, sha256, size, opener, timeout, deadline, clock)
                break
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                transient = not isinstance(exc, urllib.error.HTTPError) or exc.code >= 500
                if attempt == 2 or not transient or clock() >= deadline:
                    raise ModelFetchError("download_failed", f"{type(exc).__name__} while downloading the model") from None
                log.warning("model download interrupted (%s); retrying once", type(exc).__name__)
        log.info("model file downloaded and verified (%d bytes)", size)
        return {"downloaded": True, "seconds": round(clock() - t0, 3)}


def _download(dest: Path, url: str, sha256: str, size: int, opener, timeout: float, deadline: float, clock) -> None:
    part = dest.with_name(f"{dest.name}.part-{os.getpid()}")
    h, got = hashlib.sha256(), 0
    try:
        resp = opener(urllib.request.Request(url, headers={"User-Agent": "kyr-vercel-runtime"}), timeout=timeout)
        try:
            declared = resp.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) != size:
                raise ModelFetchError("size_mismatch", "the server announces a different file size than the pinned model")
            with open(part, "wb") as f:
                while True:
                    block = resp.read(1 << 20)
                    if not block:
                        break
                    got += len(block)
                    if got > size:
                        raise ModelFetchError("size_mismatch", "the download is larger than the pinned model")
                    if clock() > deadline:
                        raise ModelFetchError("deadline", "the model download exceeded its time budget")
                    h.update(block)
                    f.write(block)
                f.flush()
                os.fsync(f.fileno())
        finally:
            close = getattr(resp, "close", None)
            if close:
                close()
        if got != size or h.hexdigest() != sha256:
            raise ModelFetchError("checksum_mismatch", "the downloaded file is not the pinned model")
        os.replace(part, dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def _new_buffer(size: int):
    """An anonymous, private, bounded memory region: nothing is written to disk, and the pages exist only as they are filled."""
    try:
        return mmap.mmap(-1, size, flags=mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS, prot=mmap.PROT_READ | mmap.PROT_WRITE)
    except (AttributeError, TypeError):            # a platform without these flags: the default anonymous mapping is equivalent
        return mmap.mmap(-1, size)


def _download_to_buffer(url: str, sha256: str, size: int, opener, timeout: float, deadline: float, clock):
    """One attempt. Returns (buffer, seconds_streaming). The buffer is released again if anything is wrong with the bytes."""
    buf = _new_buffer(size)
    h, got = hashlib.sha256(), 0
    try:
        resp = opener(urllib.request.Request(url, headers={"User-Agent": "kyr-vercel-runtime"}), timeout=timeout)
        try:
            declared = resp.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) != size:
                raise ModelFetchError("size_mismatch", "the server announces a different file size than the pinned model")
            while True:
                block = resp.read(1 << 20)
                if not block:
                    break
                if got + len(block) > size:
                    raise ModelFetchError("size_mismatch", "the download is larger than the pinned model")
                if clock() > deadline:
                    raise ModelFetchError("deadline", "the model download exceeded its time budget")
                h.update(block)
                buf.write(block)
                got += len(block)
        finally:
            close = getattr(resp, "close", None)
            if close:
                close()
        if got != size:
            raise ModelFetchError("size_mismatch", "the download is shorter than the pinned model (truncated)")
        if h.hexdigest() != sha256:
            raise ModelFetchError("checksum_mismatch", "the downloaded bytes are not the pinned model")
        buf.seek(0)
        return buf
    except BaseException:
        try:
            buf.close()
        except Exception:  # noqa: BLE001
            pass
        raise


def fetch_model_to_memory(url: str | None, *, sha256: str = MODEL_SHA256, size: int = MODEL_BYTES, opener=None, timeout: float = 30.0,
                          deadline_seconds: float = 150.0, clock=time.monotonic):
    """Download the pinned model straight into memory: no file, no lock file, no /tmp. The size and SHA-256 are checked before anything is
    parsed. Returns (buffer, {"seconds": ...}). Raises ModelFetchError (code, safe detail); a failed or wrong download is never used."""
    t0 = clock()
    if not url:
        raise ModelFetchError("model_missing", "KYR_MODEL_URL is not set and the model is not bundled")
    why = validate_model_url(url)
    if why:
        raise ModelFetchError("bad_url", f"KYR_MODEL_URL {why}")
    opener = opener or _default_opener()
    deadline = t0 + deadline_seconds
    for attempt in (1, 2):
        try:
            buf = _download_to_buffer(url, sha256, size, opener, timeout, deadline, clock)
            break
        except ModelFetchError:
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            transient = not isinstance(exc, urllib.error.HTTPError) or exc.code >= 500
            if attempt == 2 or not transient or clock() >= deadline:
                raise ModelFetchError("download_failed", f"{type(exc).__name__} while downloading the model") from None
            log.warning("model download interrupted (%s); retrying once", type(exc).__name__)
    log.info("model downloaded into memory and verified (%d bytes)", size)
    return buf, {"downloaded": True, "in_memory": True, "seconds": round(clock() - t0, 3)}


def prepare(env=None, *, opener=None, tmp_root: Path | None = None, project_root: Path = PROJECT_ROOT, **fetch_kwargs) -> dict:
    """The whole start-up step. Raises VercelConfigError (unsafe configuration) or ModelFetchError (the model could not be made ready):
    in both cases the function does not start, so nothing runs half-configured. Returns a summary with no secrets."""
    env = os.environ if env is None else env
    apply_defaults(env, tmp_root=tmp_root, project_root=project_root)
    errors = validate(env, tmp_root=tmp_root, project_root=project_root)
    if errors:
        raise VercelConfigError("Vercel configuration refused: " + "; ".join(errors))
    buf, result = fetch_model_to_memory((env.get("KYR_MODEL_URL") or "").strip() or None, opener=opener, **fetch_kwargs)
    nomic_local.set_memory_model(buf)       # the embedding provider builds its engine from this verified buffer; the engine then keeps it alive
    return {"model": result, "snapshot_store": "local", "client_ip_source": "vercel"}
