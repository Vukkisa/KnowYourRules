"""Immutable index snapshots in an object store (Cloudflare R2 or any S3-compatible store; a local directory for development).

Why: a free web host has an ephemeral disk. The ChromaDB index and the lifecycle registry (legal/lifecycle/) must reach it as ONE
verified unit. Nothing here changes retrieval, ranking, the lifecycle state machine or what is approved.

Layout under the configured prefix (every object except active.json is write-once):
    active.json                          pointer: {version, manifest_key, manifest_sha256, previous, updated_at, updated_by}
    manifests/<version>.json             manifest: checksums, embedding model / dimensions / probes, chunk count, creation metadata
    snapshots/<version>/index.tar.gz     the ChromaDB directory
    snapshots/<version>/lifecycle.tar.gz registry.json, audit.jsonl, versions/*.json (the lock file is never shipped)

Loading (SnapshotManager.activate), in order; the first failure stops it and the corpus is NOT ready:
    pointer -> manifest (checksum against the pointer, optional deploy-time pin) -> download each archive (size + sha256 while
    streaming) -> safe extraction (no absolute paths, '..', links or devices; size capped) -> tree digests -> index opens, collection
    exists, chunk count / dimensions / profile match -> lifecycle registry and audit chain verify and reconcile with the index.
It never creates an empty index, never substitutes another version, and never falls back to the previous snapshot on its own: an
older snapshot carries an older lifecycle registry, which could serve a document that was later withdrawn. Going back is an
explicit operator act (`rollback`). A failed update leaves the last verified archives untouched.

Secrets: R2 credentials come from the environment, are used only to sign requests and never appear in logs, errors or status.
Runtime should use a READ-ONLY R2 token; only the operator's machine needs write access (publish / rollback).
"""
from __future__ import annotations

import datetime as _dt
import gzip
import hashlib
import hmac
import io
import json
import logging
import os
import re
import shutil
import tarfile
import tempfile
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import quote, urlparse

log = logging.getLogger("kyr.snapshot")
# Extraction directories this interpreter created. A directory under <work>/run that is not in this set was left by an earlier
# process (a warm /tmp is reused with the same process id), is serving nothing, and is removed before the next restore.
_RUNS_THIS_PROCESS: set = set()

SCHEMA = 1
COLLECTION = "telangana-traffic-rules"
DEFAULT_PREFIX = "kyr/"
MAX_UNPACKED_BYTES = 2 * 1024 ** 3
CHUNK = 1 << 20
_KEY = re.compile(r"^[A-Za-z0-9._\-/]{1,300}$")
_VERSION = re.compile(r"^[A-Za-z0-9._\-]{1,80}$")
_HEX = re.compile(r"^[0-9a-f]{64}$")
LOCK_FILES = {".lifecycle.lock"}


class StoreError(RuntimeError):
    """The object store could not be read or written. The message is fixed text; it never carries credentials or response bodies.
    `transient` says whether trying again later can help (timeouts, connection errors, HTTP 429/5xx); a refusal such as 403 or a
    malformed answer is permanent and is never retried."""

    def __init__(self, *args, transient: bool = False):
        super().__init__(*args)
        self.transient = transient


def _http_error(status: int) -> "StoreError":
    return StoreError(f"object store returned HTTP {status}", transient=(status == 429 or status >= 500))


class ObjectMissing(StoreError):
    pass


class PreconditionFailed(StoreError):
    """A conditional write was refused because the object is not in the state the writer last saw (another writer got there first)."""


class SnapshotError(RuntimeError):
    def __init__(self, state: str, detail: str = "", transient: bool = False):
        super().__init__(f"{state}{f': {detail}' if detail else ''}")
        self.state, self.detail, self.transient = state, detail, transient


def _check_key(key: str) -> str:
    if not _KEY.match(key) or ".." in key.split("/") or key.startswith("/") or "//" in key:
        raise StoreError("invalid object key")
    return key


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def files_digest(root, skip=frozenset()) -> str:
    """Same construction as document_lifecycle.tree_digest (relative path, size, bytes), minus excluded names (lock files)."""
    h = hashlib.sha256()
    root = Path(root)
    for p in sorted(x for x in root.rglob("*") if x.is_file() and x.name not in skip):
        h.update(str(p.relative_to(root)).encode())
        h.update(str(p.stat().st_size).encode())
        with open(p, "rb") as f:
            for block in iter(lambda: f.read(CHUNK), b""):
                h.update(block)
    return h.hexdigest()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------------------------------------------
# Object stores
# ---------------------------------------------------------------------------------------------------
class ObjectStore:
    def get_stream(self, key: str) -> Iterator[bytes]:
        raise NotImplementedError

    def get_bytes(self, key: str, limit: int = 64 * 1024 * 1024) -> bytes:
        out, total = [], 0
        for block in self.get_stream(key):
            total += len(block)
            if total > limit:
                raise StoreError("object larger than the allowed size")
            out.append(block)
        return b"".join(out)

    def put_bytes(self, key: str, data: bytes) -> None:
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        raise NotImplementedError

    def get_with_etag(self, key: str) -> tuple[bytes, str]:
        """(content, entity tag). ObjectMissing if absent. The tag is opaque: it is only ever handed back to put_conditional."""
        raise StoreError("this store cannot report entity tags")

    def put_conditional(self, key: str, data: bytes, *, if_match: str | None = None, if_none_match: bool = False) -> None:
        """Write only if the object still has entity tag `if_match`, or (if_none_match) does not exist. PreconditionFailed otherwise.
        A store that cannot do this atomically must refuse (StoreError), never fall back to an unconditional write."""
        raise StoreError("this store cannot do conditional writes")

    def describe(self) -> dict:
        return {"kind": "unknown"}


class LocalObjectStore(ObjectStore):
    """A directory as an object store: development, tests, and dry-run publishing. Never leaves the machine."""

    def __init__(self, root):
        self.root = Path(root)

    def _path(self, key):
        return self.root / _check_key(key)

    def get_stream(self, key):
        p = self._path(key)
        if not p.is_file():
            raise ObjectMissing("object not found")
        try:
            with open(p, "rb") as f:
                yield from iter(lambda: f.read(CHUNK), b"")
        except OSError:
            raise StoreError("object could not be read") from None

    def put_bytes(self, key, data):
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + f".tmp-{uuid.uuid4().hex[:8]}")
        tmp.write_bytes(data)
        os.replace(tmp, p)

    def exists(self, key):
        return self._path(key).is_file()

    def get_with_etag(self, key):
        data = self.get_bytes(key)
        return data, sha256_bytes(data)

    def put_conditional(self, key, data, *, if_match=None, if_none_match=False):
        """Atomic compare-and-swap on a directory store: an exclusive file lock around check + replace (single machine only)."""
        if (if_match is None) == (not if_none_match):
            raise StoreError("exactly one of if_match / if_none_match is required")
        import fcntl
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(self.root / ".cas.lock", "ab") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                current = sha256_bytes(p.read_bytes()) if p.is_file() else None
                if if_none_match and current is not None:
                    raise PreconditionFailed("object already exists")
                if if_match is not None and current != if_match:
                    raise PreconditionFailed("object changed since it was read")
                self.put_bytes(key, data)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def describe(self):
        return {"kind": "local"}


def sigv4_headers(method, host, path, query, payload_hash, key_id, secret, region, service, amz_date, add_content_sha=True):
    """AWS Signature V4 for one request; returns the headers to send. `path` is already the final URI path (S3: encoded once)."""
    date = amz_date[:8]
    headers = {"host": host, "x-amz-date": amz_date}
    if add_content_sha:
        headers["x-amz-content-sha256"] = payload_hash
    signed = ";".join(sorted(headers))
    canonical_headers = "".join(f"{k}:{headers[k]}\n" for k in sorted(headers))
    canonical_query = "&".join(f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in sorted(query.items()))
    canonical = "\n".join([method, path, canonical_query, canonical_headers, signed, payload_hash])
    scope = f"{date}/{region}/{service}/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, sha256_bytes(canonical.encode())])

    def mac(k, m):
        return hmac.new(k, m.encode(), hashlib.sha256).digest()
    k = mac(mac(mac(mac(("AWS4" + secret).encode(), date), region), service), "aws4_request")
    signature = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
    out = {k: v for k, v in headers.items() if k != "host"}
    out["Authorization"] = f"AWS4-HMAC-SHA256 Credential={key_id}/{scope}, SignedHeaders={signed}, Signature={signature}"
    return out


class S3CompatStore(ObjectStore):
    """Cloudflare R2 (or any S3-compatible store), path-style, SigV4, over requests. Deliberately not boto3: one small dependency
    (requests is already required) instead of ~100 MB of memory on a 512 MB host."""

    def __init__(self, endpoint, bucket, key_id, secret, prefix=DEFAULT_PREFIX, region="auto", timeout=30.0, http=None, clock=None,
                 retries=2, backoff=0.5, sleep=None):
        # retries: extra attempts for timeouts, connection errors, HTTP 429 and 5xx. Every request this store makes is idempotent
        # (GET/HEAD, and PUT of a write-once or pointer object), so repeating one is safe. Never retried: 4xx other than 429.
        self.retries, self.backoff, self._sleep = max(0, int(retries)), float(backoff), sleep or time.sleep
        parsed = urlparse(endpoint)
        loopback = (parsed.hostname or "") in ("localhost", "127.0.0.1", "::1")
        if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
            raise StoreError("the object store endpoint must be https")
        if not (bucket and key_id and secret):
            raise StoreError("object store credentials are incomplete")
        self.endpoint, self.host, self.bucket = endpoint.rstrip("/"), parsed.netloc, bucket
        self._key_id, self._secret, self.region, self.timeout = key_id, secret, region, timeout
        self.prefix = prefix
        import requests
        self._requests, self.http = requests, http or requests.request
        self._clock = clock or (lambda: _dt.datetime.now(_dt.timezone.utc))

    def __repr__(self):
        return f"S3CompatStore(bucket={self.bucket!r}, host={self.host!r})"

    def describe(self):
        return {"kind": "s3-compatible", "host": self.host, "bucket": self.bucket}

    def _request(self, method, key, data=b"", stream=False, extra_headers=None):
        _check_key(key)
        path = "/" + quote(f"{self.bucket}/{key}", safe="/-_.~")
        payload_hash = sha256_bytes(data)
        for attempt in range(self.retries + 1):
            amz_date = self._clock().strftime("%Y%m%dT%H%M%SZ")   # signed afresh: a retry must not reuse a stale signature
            headers = sigv4_headers(method, self.host, path, {}, payload_hash, self._key_id, self._secret, self.region, "s3", amz_date)
            headers.update(extra_headers or {})        # If-Match / If-None-Match are not signed headers; they are sent as-is
            failure, resp = None, None
            try:
                resp = self.http(method, self.endpoint + path, headers=headers, data=data or None, timeout=self.timeout, stream=stream)
            except self._requests.Timeout:
                failure = StoreError("object store timed out", transient=True)
            except self._requests.RequestException as exc:
                failure = StoreError(f"object store unreachable ({type(exc).__name__})", transient=True)
            if failure is None and not (resp.status_code == 429 or resp.status_code >= 500):
                return resp
            if attempt == self.retries:
                if failure is not None:
                    raise failure from None
                return resp                  # the caller turns the final 429/5xx into a StoreError
            if resp is not None:
                resp.close()
            self._sleep(self.backoff * (2 ** attempt))

    def get_stream(self, key):
        resp = self._request("GET", key, stream=True)
        try:
            if resp.status_code == 404:
                raise ObjectMissing("object not found")
            if resp.status_code != 200:
                raise _http_error(resp.status_code)
            try:
                yield from resp.iter_content(CHUNK)
            except self._requests.RequestException as exc:
                raise StoreError(f"object store read failed ({type(exc).__name__})", transient=True) from None
        finally:
            resp.close()

    def put_bytes(self, key, data):
        resp = self._request("PUT", key, data=data)
        if resp.status_code not in (200, 201, 204):
            raise _http_error(resp.status_code)

    def exists(self, key):
        resp = self._request("HEAD", key)
        if resp.status_code == 404:
            return False
        if resp.status_code != 200:
            raise _http_error(resp.status_code)
        return True

    def get_with_etag(self, key):
        resp = self._request("GET", key)
        if resp.status_code == 404:
            raise ObjectMissing("object not found")
        if resp.status_code != 200:
            raise _http_error(resp.status_code)
        etag = resp.headers.get("ETag")
        if not etag:
            raise StoreError("object store returned no ETag")
        return resp.content, etag

    def put_conditional(self, key, data, *, if_match=None, if_none_match=False):
        if (if_match is None) == (not if_none_match):
            raise StoreError("exactly one of if_match / if_none_match is required")
        resp = self._request("PUT", key, data=data, extra_headers={"If-None-Match": "*"} if if_none_match else {"If-Match": if_match})
        if resp.status_code in (409, 412):          # 412 precondition failed; 409 a concurrent conditional write (S3 ConditionalRequestConflict)
            raise PreconditionFailed("object changed since it was read")
        if resp.status_code not in (200, 201, 204):
            raise _http_error(resp.status_code)


def store_from_env(env=None, http=None, sleep=None) -> ObjectStore | None:
    """TG_SNAPSHOT_STORE = local | r2. Unset = snapshot mode off (None)."""
    env = os.environ if env is None else env
    kind = (env.get("TG_SNAPSHOT_STORE") or "").strip().lower()
    prefix = env.get("TG_SNAPSHOT_PREFIX")
    prefix = DEFAULT_PREFIX if prefix is None else prefix.strip()   # explicitly empty = the bucket root
    prefix = prefix if prefix.endswith("/") or not prefix else prefix + "/"
    if not kind:
        return None
    if kind == "local":
        d = (env.get("TG_SNAPSHOT_LOCAL_DIR") or "").strip()
        if not d:
            raise SnapshotError("misconfigured", "TG_SNAPSHOT_LOCAL_DIR is required for TG_SNAPSHOT_STORE=local")
        return PrefixedStore(LocalObjectStore(d), prefix)
    if kind == "r2":
        account = (env.get("R2_ACCOUNT_ID") or "").strip()
        endpoint = (env.get("R2_ENDPOINT") or "").strip() or (f"https://{account}.r2.cloudflarestorage.com" if account else "")
        if not endpoint:
            raise SnapshotError("misconfigured", "R2_ACCOUNT_ID (or R2_ENDPOINT) is not set")
        try:
            return PrefixedStore(S3CompatStore(endpoint, (env.get("R2_BUCKET") or "").strip(), (env.get("R2_ACCESS_KEY_ID") or "").strip(),
                                               (env.get("R2_SECRET_ACCESS_KEY") or "").strip(), http=http, sleep=sleep), prefix)
        except StoreError as e:
            raise SnapshotError("misconfigured", str(e)) from None
    raise SnapshotError("misconfigured", "TG_SNAPSHOT_STORE must be local or r2")


class PrefixedStore(ObjectStore):
    def __init__(self, inner: ObjectStore, prefix: str):
        self.inner, self.prefix = inner, prefix

    def _k(self, key):
        return _check_key(self.prefix + key)

    def get_stream(self, key):
        return self.inner.get_stream(self._k(key))

    def put_bytes(self, key, data):
        return self.inner.put_bytes(self._k(key), data)

    def exists(self, key):
        return self.inner.exists(self._k(key))

    def get_with_etag(self, key):
        return self.inner.get_with_etag(self._k(key))

    def put_conditional(self, key, data, *, if_match=None, if_none_match=False):
        return self.inner.put_conditional(self._k(key), data, if_match=if_match, if_none_match=if_none_match)

    def describe(self):
        return dict(self.inner.describe(), prefix=self.prefix)


# ---------------------------------------------------------------------------------------------------
# Archives
# ---------------------------------------------------------------------------------------------------
def make_archive(src_dir, dest_file, skip=frozenset()) -> dict:
    """Deterministic tar.gz of the files under src_dir (sorted, zero mtime/owner): the same content gives the same bytes."""
    src_dir, count, unpacked = Path(src_dir), 0, 0
    with open(dest_file, "wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, compresslevel=6) as gz:
            with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
                for p in sorted(x for x in src_dir.rglob("*") if x.is_file() and x.name not in skip):
                    info = tarfile.TarInfo(str(p.relative_to(src_dir)).replace(os.sep, "/"))
                    info.size, info.mtime, info.mode, info.uid, info.gid, info.uname, info.gname = p.stat().st_size, 0, 0o644, 0, 0, "", ""
                    with open(p, "rb") as f:
                        tar.addfile(info, f)
                    count += 1
                    unpacked += info.size
    return {"files": count, "unpacked_bytes": unpacked}


def safe_extract(archive, dest_dir, max_unpacked: int) -> int:
    """Extract regular files only. Rejects absolute paths, '..', links, devices and anything beyond max_unpacked bytes."""
    dest = Path(dest_dir).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        with tarfile.open(archive, mode="r:gz") as tar:
            for m in tar:
                name = m.name
                if m.isdir():
                    continue
                parts = name.split("/")
                if (not m.isreg() or name.startswith("/") or "\\" in name or any(p in ("", ".", "..") for p in parts)
                        or ":" in parts[0]):
                    raise SnapshotError("archive_invalid", "archive contains an unsafe entry")
                total += m.size
                if total > min(max_unpacked, MAX_UNPACKED_BYTES):
                    raise SnapshotError("archive_invalid", "archive unpacks larger than declared")
                target = (dest / name).resolve()
                if dest not in target.parents:
                    raise SnapshotError("archive_invalid", "archive entry escapes the target directory")
                target.parent.mkdir(parents=True, exist_ok=True)
                src = tar.extractfile(m)
                with open(target, "wb") as out:
                    shutil.copyfileobj(src, out, CHUNK)
                os.chmod(target, 0o644)
    except (tarfile.TarError, EOFError, OSError, gzip.BadGzipFile) as exc:
        raise SnapshotError("archive_invalid", f"archive could not be read ({type(exc).__name__})") from None
    return total


# ---------------------------------------------------------------------------------------------------
# Manifest and pointer
# ---------------------------------------------------------------------------------------------------
def validate_manifest(m) -> dict:
    """Strict structural check. Raises SnapshotError('manifest_invalid')."""
    def bad(why):
        raise SnapshotError("manifest_invalid", why)
    if not isinstance(m, dict) or m.get("schema_version") != SCHEMA:
        bad("unknown manifest schema")
    if not isinstance(m.get("version"), str) or not _VERSION.match(m["version"]):
        bad("invalid version identifier")
    for part in ("index", "lifecycle"):
        c = m.get(part)
        if not isinstance(c, dict):
            bad(f"{part} component missing")
        if not (isinstance(c.get("archive"), str) and _KEY.match(c["archive"]) and ".." not in c["archive"]):
            bad(f"{part} archive key invalid")
        if c["archive"] != f"snapshots/{m['version']}/{part}.tar.gz":
            bad(f"{part} archive is not this version's own object (index and lifecycle must come from one snapshot)")
        if not (isinstance(c.get("sha256"), str) and _HEX.match(c["sha256"])):
            bad(f"{part} sha256 invalid")
        if not (isinstance(c.get("tree_digest"), str) and _HEX.match(c["tree_digest"])):
            bad(f"{part} tree digest invalid")
        for n in ("size_bytes", "unpacked_bytes"):
            if not (isinstance(c.get(n), int) and not isinstance(c.get(n), bool) and 0 < c[n] <= MAX_UNPACKED_BYTES):
                bad(f"{part} {n} invalid")
    ix, emb = m["index"], m.get("embedding")
    if not (isinstance(ix.get("chunk_count"), int) and ix["chunk_count"] > 0):
        bad("chunk count invalid")
    if not (isinstance(ix.get("collection"), str) and ix["collection"]):
        bad("collection name invalid")
    if not (isinstance(ix.get("index_version"), str) and ix["index_version"]):
        bad("index version missing")
    if not (isinstance(m["lifecycle"].get("registry_sha256"), str) and _HEX.match(m["lifecycle"]["registry_sha256"])):
        bad("lifecycle registry digest invalid")
    if not isinstance(emb, dict):
        bad("embedding block missing")
    if not (isinstance(emb.get("model"), str) and emb["model"] and isinstance(emb.get("family"), str) and emb["family"]):
        bad("embedding model / family missing")
    if not (isinstance(emb.get("dimensions"), int) and 0 < emb["dimensions"] <= 8192):
        bad("embedding dimensions invalid")
    probes = emb.get("probes")
    if not (isinstance(probes, list) and probes):
        bad("embedding probes missing")
    for p in probes:
        if not (isinstance(p, dict) and isinstance(p.get("input"), str) and isinstance(p.get("vector"), list)
                and len(p["vector"]) == emb["dimensions"] and all(isinstance(x, (int, float)) for x in p["vector"])):
            bad("embedding probe invalid")
    if not (isinstance(m.get("created_at"), str) and isinstance(m.get("created_by"), str)):
        bad("creation metadata missing")
    return m


def canonical_json(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, indent=1, ensure_ascii=False).encode("utf-8")


def parse_pointer(raw: bytes) -> dict:
    try:
        p = json.loads(raw.decode("utf-8"))
        if (p.get("schema_version") != SCHEMA or not _VERSION.match(p["version"]) or p["manifest_key"] != f"manifests/{p['version']}.json"
                or not _HEX.match(p["manifest_sha256"])):
            raise ValueError
        return p
    except (ValueError, KeyError, TypeError, AttributeError):
        raise SnapshotError("manifest_invalid", "active pointer is invalid") from None


# ---------------------------------------------------------------------------------------------------
# Publishing (operator machine; reads the live directories without opening them)
# ---------------------------------------------------------------------------------------------------
def _space_report(work) -> str:
    """Free space on the temp filesystem and the size of what this loader and the temp dir already hold (diagnostics only;
    never raises, never changes behaviour)."""
    try:
        tmp = Path(tempfile.gettempdir())
        du = shutil.disk_usage(tmp)
        def size(p):
            total = 0
            for root, _d, files in os.walk(p):
                for f in files:
                    try:
                        total += os.lstat(os.path.join(root, f)).st_size
                    except OSError:
                        pass
            return total
        mb = lambda n: round(n / 1048576, 1)
        top = {}
        for e in tmp.iterdir():
            top[e.name] = mb(size(e)) if e.is_dir() else mb(e.lstat().st_size)
        biggest = dict(sorted(top.items(), key=lambda kv: kv[1], reverse=True)[:6])
        return f"tmp total={mb(du.total)}MB free={mb(du.free)}MB used={mb(du.used)}MB work={mb(size(work))}MB biggest={biggest}"
    except Exception as exc:  # noqa: BLE001
        return f"unavailable ({type(exc).__name__})"


def _chroma_facts(index_dir, collection=COLLECTION):
    """chunk count, dimensions, per-hash chunk counts and collection metadata, read from a PRIVATE COPY (Chroma rewrites files
    when it opens a directory, so the caller's directory is never opened)."""
    import chromadb
    tmp = Path(tempfile.mkdtemp(prefix="kyr-snap-peek-"))
    try:
        peek = tmp / "idx"
        shutil.copytree(index_dir, peek)
        client = chromadb.PersistentClient(path=str(peek))
        try:
            col = client.get_collection(collection, embedding_function=None)
        except Exception:
            raise SnapshotError("index_invalid", "the collection is missing from the index") from None
        got = col.get(include=["metadatas", "embeddings", "documents"])
        n = len(got["ids"])
        embs = got["embeddings"]
        dims = len(embs[0]) if n else 0
        counts = Counter((m or {}).get("sha256") for m in got["metadatas"])
        meta = dict(col.metadata or {})
        return {"count": n, "dims": dims, "counts": counts, "metadata": meta, "documents": got["documents"], "embeddings": embs}
    finally:
        try:
            from chromadb.api.shared_system_client import SharedSystemClient
            SharedSystemClient.clear_system_cache()
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(tmp, ignore_errors=True)


@dataclass
class PointerRead:
    """active.json as one publisher saw it: its entity tag (None = there was no pointer) and the `previous` link a new pointer records."""
    etag: str | None
    pointer: dict | None
    previous: dict | None


def read_pointer(store: ObjectStore, strict: bool = True) -> PointerRead:
    try:
        raw, etag = store.get_with_etag("active.json")
    except ObjectMissing:
        return PointerRead(None, None, None)
    except StoreError as exc:
        raise SnapshotError("store_unavailable", f"cannot read the active pointer with an entity tag, so nothing was published ({exc})") from None
    try:
        cur = parse_pointer(raw)
    except SnapshotError:
        if not strict:                    # rollback is the repair tool: it may replace a corrupt pointer, still compare-and-swap on its tag
            return PointerRead(etag, None, None)
        raise SnapshotError("pointer_invalid", "the current active.json is not a valid pointer; repair or replace it deliberately, "
                                               "this tool will not overwrite it") from None
    return PointerRead(etag, cur, {k: cur[k] for k in ("version", "manifest_key", "manifest_sha256")})


def _swap_pointer(store: ObjectStore, pointer: dict, seen: PointerRead, version: str):
    """Compare-and-swap of active.json against the tag that was read first. Never an unconditional write."""
    body = canonical_json(pointer)
    try:
        if seen.etag is None:
            store.put_conditional("active.json", body, if_none_match=True)
        else:
            store.put_conditional("active.json", body, if_match=seen.etag)
    except PreconditionFailed:
        # A retried PUT whose first attempt succeeded looks like a conflict; the pointer then already says exactly what we wrote.
        try:
            if store.get_bytes("active.json") == body:
                return
            now = parse_pointer(store.get_bytes("active.json")).get("version")
        except (StoreError, SnapshotError):
            now = "unknown"
        raise SnapshotError("publish_conflict",
                            f"another publisher changed the active pointer (now {now!r}) after this publish read it; its pointer was NOT overwritten. "
                            f"Snapshot {version} is uploaded and verified but not active. To retry: look at what is active, then activate yours "
                            f"deliberately with: rollback --to {version}") from None
    except StoreError as exc:
        raise SnapshotError("store_unavailable",
                            f"snapshot {version} is uploaded and verified but the active pointer was NOT updated ({exc}); "
                            f"the previous snapshot is still active. Activate it later with: rollback --to {version}") from None


def protected_versions(store: ObjectStore) -> set:
    """Versions that must never be deleted: the active one and the one it replaced. (This module has no delete operation at all;
    this is the rule for any manual cleanup. A snapshot that is neither, whose publish was interrupted or lost a race, is an orphan.)"""
    cur = read_pointer(store)
    out = set()
    if cur.pointer:
        out.add(cur.pointer["version"])
        if cur.pointer.get("previous"):
            out.add(cur.pointer["previous"]["version"])
    return out


def publish(store: ObjectStore, db_dir, lifecycle_dir, *, embed: Callable[[list[str]], list[list[float]]], embedding_model: str,
            family: str, created_by: str, notes: str = "", doc_prefix="search_document: ", query_prefix="search_query: ",
            probe_texts=None, consistency_samples=6, min_consistency_cosine=0.9999, version=None) -> dict:
    """Package the index and lifecycle directories, verify the index's vectors against `embed` (the model that built it), and
    write archives, manifest and pointer. Write-once objects are never overwritten. Returns the manifest."""
    from backend import embedding_provider as ep
    if not (created_by or "").strip():
        raise SnapshotError("manifest_invalid", "an operator name is required")
    facts = _chroma_facts(db_dir)
    if not facts["count"]:
        raise SnapshotError("index_invalid", "refusing to publish an empty index")
    # the index's own vectors must be reproducible by the model that is declared: otherwise the probes would certify nothing
    step = max(1, facts["count"] // consistency_samples)
    pick = list(range(0, facts["count"], step))[:consistency_samples]
    again = embed([doc_prefix + facts["documents"][i] for i in pick])
    worst = min(ep.cosine(a, facts["embeddings"][i]) for a, i in zip(again, pick))
    if worst < min_consistency_cosine:
        raise SnapshotError("embedding_incompatible",
                            f"re-embedding stored chunks with the declared model gives cosine {worst:.6f} < {min_consistency_cosine}")
    probes = ep.make_probes(embed, list(probe_texts or ep.PROBE_TEXTS), doc_prefix)
    if any(len(p["vector"]) != facts["dims"] for p in probes):
        raise SnapshotError("embedding_incompatible", "probe vectors differ in size from the stored vectors")
    if not (Path(lifecycle_dir) / "registry.json").is_file():
        raise SnapshotError("lifecycle_invalid", "registry.json is missing")
    check_lifecycle_dir(lifecycle_dir, facts["counts"])   # never publish a registry that the server would refuse
    tree = files_digest(db_dir)
    version = version or (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + tree[:10])
    if not _VERSION.match(version):
        raise SnapshotError("manifest_invalid", "invalid version identifier")
    if store.exists(f"manifests/{version}.json"):
        raise SnapshotError("manifest_invalid", "that version already exists; snapshots are immutable")
    seen = read_pointer(store)            # step 1: what is active now, and its entity tag; the pointer is only swapped if that is still true
    work = Path(tempfile.mkdtemp(prefix="kyr-snap-pub-"))
    try:
        comp = {}
        for name, src, skip in (("index", Path(db_dir), frozenset()), ("lifecycle", Path(lifecycle_dir), LOCK_FILES)):
            f = work / f"{name}.tar.gz"
            info = make_archive(src, f, skip)
            key = f"snapshots/{version}/{name}.tar.gz"
            comp[name] = dict(archive=key, sha256=sha256_file(f), size_bytes=f.stat().st_size, unpacked_bytes=info["unpacked_bytes"],
                              files=info["files"], tree_digest=files_digest(src, skip), _file=f)
        reg = json.loads((Path(lifecycle_dir) / "registry.json").read_text("utf-8"))
        manifest = {
            "schema_version": SCHEMA, "version": version, "created_at": _now(), "created_by": created_by.strip()[:120], "notes": notes[:500],
            "index": {k: v for k, v in comp["index"].items() if k != "_file"} | {
                "collection": COLLECTION, "chunk_count": facts["count"], "document_count": len([h for h in facts["counts"] if h]),
                "rag_profile": facts["metadata"].get("rag_profile"), "index_version": f"{COLLECTION}@{comp['index']['tree_digest'][:16]}"},
            "lifecycle": {k: v for k, v in comp["lifecycle"].items() if k != "_file"} | {
                "registry_sha256": sha256_file(Path(lifecycle_dir) / "registry.json"),
                "audit_sha256": sha256_file(Path(lifecycle_dir) / "audit.jsonl") if (Path(lifecycle_dir) / "audit.jsonl").is_file() else None,
                "sources": len(reg.get("sources", {})), "events": len(reg.get("events", []))},
            "embedding": {"model": embedding_model, "family": family, "dimensions": facts["dims"], "normalized": True, "distance": "l2",
                          "doc_prefix": doc_prefix, "query_prefix": query_prefix, "min_cosine": 0.995, "probes": probes,
                          "consistency_cosine_min": round(worst, 8)},
        }
        validate_manifest(manifest)
        raw = canonical_json(manifest)
        # Order matters for interruption safety: archives, then the manifest (a version exists only once its manifest does), then a
        # read-back of everything that was written, and only then the pointer. Nothing here deletes or overwrites an existing object.
        for name in ("index", "lifecycle"):
            _put_archive(store, comp[name])
        store.put_bytes(f"manifests/{version}.json", raw)
        verify_uploaded(store, manifest, raw)
        previous = seen.previous
        pointer = {"schema_version": SCHEMA, "version": version, "manifest_key": f"manifests/{version}.json",
                   "manifest_sha256": sha256_bytes(raw), "previous": previous, "updated_at": _now(), "updated_by": created_by.strip()[:120]}
        _swap_pointer(store, pointer, seen, version)
        return manifest
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _remote_sha256(store: ObjectStore, key: str):
    """(sha256, size) of a stored object, or None if it does not exist."""
    h, n = hashlib.sha256(), 0
    try:
        for block in store.get_stream(key):
            h.update(block)
            n += len(block)
    except ObjectMissing:
        return None
    return h.hexdigest(), n


def _put_archive(store: ObjectStore, comp: dict):
    """Write-once upload. An archive left behind by an interrupted publish of the SAME content is reused; different content under the
    same key is refused (snapshots are immutable and nothing is overwritten)."""
    existing = _remote_sha256(store, comp["archive"])
    if existing is None:
        store.put_bytes(comp["archive"], comp["_file"].read_bytes())
    elif existing != (comp["sha256"], comp["size_bytes"]):
        raise SnapshotError("manifest_invalid", "archive already exists with different content; snapshots are immutable")


def verify_uploaded(store: ObjectStore, manifest: dict, raw: bytes | None = None):
    """Read a snapshot back out of the store and check it against its manifest, before anything points at it."""
    key = f"manifests/{manifest['version']}.json"
    try:
        stored = store.get_bytes(key, limit=16 * 1024 * 1024)
        if raw is not None and stored != raw:
            raise SnapshotError("checksum_mismatch", "the stored manifest does not read back identically")
        for name in ("index", "lifecycle"):
            got = _remote_sha256(store, manifest[name]["archive"])
            if got is None:
                raise SnapshotError("snapshot_missing", f"the {name} archive is not readable from the store")
            if got != (manifest[name]["sha256"], manifest[name]["size_bytes"]):
                raise SnapshotError("checksum_mismatch", f"the stored {name} archive does not read back identically")
    except ObjectMissing:
        raise SnapshotError("snapshot_missing", "an object of this snapshot is not readable from the store") from None


def rollback(store: ObjectStore, to_version: str, by: str) -> dict:
    """Operator act: repoint active.json at an existing, verifiable snapshot (its archives are read back first). Review that
    snapshot's lifecycle registry before running this: an older registry can list a document that was later withdrawn."""
    key = f"manifests/{to_version}.json"
    raw = store.get_bytes(key)          # ObjectMissing for an unknown version
    manifest = validate_manifest(json.loads(raw))
    if manifest["version"] != to_version:
        raise SnapshotError("manifest_invalid", "manifest version differs from the requested version")
    verify_uploaded(store, manifest, raw)
    seen = read_pointer(store, strict=False)
    pointer = {"schema_version": SCHEMA, "version": to_version, "manifest_key": key, "manifest_sha256": sha256_bytes(raw),
               "previous": seen.previous, "updated_at": _now(), "updated_by": (by or "").strip()[:120]}
    _swap_pointer(store, pointer, seen, to_version)
    return pointer


# ---------------------------------------------------------------------------------------------------
# Loading (the server)
# ---------------------------------------------------------------------------------------------------
@dataclass
class SnapshotStatus:
    state: str = "disabled"          # disabled | ready | <failure state>
    version: str | None = None
    problems: list = field(default_factory=list)
    db_dir: Path | None = None
    lifecycle_dir: Path | None = None
    manifest: dict | None = None
    seconds: dict = field(default_factory=dict)
    stale: bool = False
    transient: bool = False          # the failure may clear by itself (store unreachable); integrity failures never are
    attempts: int = 1
    timed_out: bool = False          # the bounded startup retry gave up because its time budget ran out
    pinned: bool = False             # the manifest digest was compared with TG_SNAPSHOT_PIN_SHA256 and matched

    @property
    def enabled(self) -> bool:
        return self.state != "disabled"

    @property
    def ready(self) -> bool:
        return self.state == "ready"

    def public(self) -> dict:
        m = self.manifest or {}
        return {"enabled": self.enabled, "state": self.state, "ready": self.ready, "version": self.version, "stale": self.stale,
                "problems": self.problems[:5], "chunks": (m.get("index") or {}).get("chunk_count"),
                "created_at": m.get("created_at"), "seconds": self.seconds, "attempts": self.attempts,
                "retryable_failure": (not self.ready) and self.transient, "pinned": self.pinned}


class SnapshotManager:
    def __init__(self, store: ObjectStore, work_dir, *, pin_sha256: str | None = None, allow_stale: bool = False,
                 expected_family: str | None = None):
        self.store, self.work, self.pin, self.allow_stale = store, Path(work_dir), (pin_sha256 or "").lower() or None, allow_stale
        self.expected_family = expected_family

    # -- remote ---------------------------------------------------------------------------------------------------------------
    def fetch_manifest(self):
        try:
            pointer = parse_pointer(self.store.get_bytes("active.json", limit=1 << 20))
        except ObjectMissing:
            raise SnapshotError("manifest_missing", "no active snapshot pointer in the store") from None
        try:
            raw = self.store.get_bytes(pointer["manifest_key"], limit=16 * 1024 * 1024)
        except ObjectMissing:
            raise SnapshotError("manifest_missing", "the active manifest object is missing") from None
        digest = sha256_bytes(raw)
        if digest != pointer["manifest_sha256"]:
            raise SnapshotError("checksum_mismatch", "manifest does not match the checksum in the active pointer")
        if self.pin and digest != self.pin:
            raise SnapshotError("pin_mismatch", "manifest does not match TG_SNAPSHOT_PIN_SHA256")
        try:
            manifest = json.loads(raw.decode("utf-8"))
        except ValueError:
            raise SnapshotError("manifest_invalid", "manifest is not valid JSON") from None
        validate_manifest(manifest)
        if manifest["version"] != pointer["version"]:
            raise SnapshotError("manifest_invalid", "manifest version differs from the pointer")
        return manifest, digest

    def _download(self, comp: dict, dest: Path):
        """One retry when the transfer itself breaks (connection reset, timeout mid-stream). A checksum mismatch is never retried:
        it means the object is wrong, not that the network was."""
        try:
            return self._download_once(comp, dest)
        except StoreError as first:
            if not first.transient:
                raise                      # a refusal (403, 404, malformed answer) will not change by asking again
            log.warning("snapshot archive download interrupted (%s); retrying once", first)
            return self._download_once(comp, dest)

    def _download_once(self, comp: dict, dest: Path):
        h, size = hashlib.sha256(), 0
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        try:
            with open(part, "wb") as f:
                for block in self.store.get_stream(comp["archive"]):
                    size += len(block)
                    if size > comp["size_bytes"]:
                        raise SnapshotError("checksum_mismatch", "archive larger than the manifest declares")
                    h.update(block)
                    f.write(block)
        except ObjectMissing:
            part.unlink(missing_ok=True)
            raise SnapshotError("snapshot_missing", "a snapshot archive named in the manifest is missing") from None
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        if size != comp["size_bytes"] or h.hexdigest() != comp["sha256"]:
            part.unlink(missing_ok=True)
            raise SnapshotError("checksum_mismatch", "archive checksum does not match the manifest")
        os.replace(part, dest)

    # -- the whole procedure ---------------------------------------------------------------------------------------------------
    def activate(self) -> SnapshotStatus:
        t0 = time.perf_counter()
        log.info("snapshot restore starting; space: %s", _space_report(self.work))
        seconds = {}
        manifest = None
        try:
            try:
                manifest, mdigest = self.fetch_manifest()
                archives = self._stage_archives(manifest, seconds)
            except StoreError as exc:
                cached = self._cached() if self.allow_stale else None
                if cached is None:
                    raise SnapshotError("store_unavailable", str(exc), transient=exc.transient) from None
                manifest, archives = cached
                log.warning("snapshot store unreachable; serving the cached verified snapshot %s (TG_SNAPSHOT_ALLOW_STALE)", manifest["version"])
                status = self._load(manifest, archives, seconds)
                status.stale = True
                return status
            return self._load(manifest, archives, seconds)
        except SnapshotError as err:
            log.error("snapshot not loaded: %s", err.state)
            return SnapshotStatus(state=err.state, problems=[err.detail or err.state], manifest=manifest, seconds=seconds,
                                  transient=err.transient)
        except Exception as exc:  # noqa: BLE001 - nothing unexpected may leave a half-loaded corpus looking ready
            # the traceback goes to the server log only; the status shown to callers still names just the exception type
            log.error("snapshot not loaded: unexpected %s", type(exc).__name__, exc_info=True)
            log.error("snapshot work dir space at failure: %s", _space_report(self.work))
            return SnapshotStatus(state="index_invalid", problems=[f"unexpected error while loading: {type(exc).__name__}"], seconds=seconds)
        finally:
            seconds["total"] = round(time.perf_counter() - t0, 3)

    def _archive_dir(self, version):
        return self.work / "archives" / version

    def _stage_archives(self, manifest, seconds):
        d = self._archive_dir(manifest["version"])
        t = time.perf_counter()
        out = {}
        for name in ("index", "lifecycle"):
            dest = d / f"{name}.tar.gz"
            if dest.is_file() and dest.stat().st_size == manifest[name]["size_bytes"] and sha256_file(dest) == manifest[name]["sha256"]:
                out[name] = dest           # a previously verified archive; never trusted without re-hashing
                continue
            self._download(manifest[name], dest)
            out[name] = dest
        seconds["download_and_verify"] = round(time.perf_counter() - t, 3)
        self._prune(keep={manifest["version"]})
        (self.work).mkdir(parents=True, exist_ok=True)
        tmp = self.work / "current.json.tmp"
        tmp.write_text(json.dumps({"version": manifest["version"], "manifest": manifest}), "utf-8")
        os.replace(tmp, self.work / "current.json")
        return out

    def _cached(self):
        try:
            cur = json.loads((self.work / "current.json").read_text("utf-8"))
            manifest = validate_manifest(cur["manifest"])
            d = self._archive_dir(manifest["version"])
            out = {}
            for name in ("index", "lifecycle"):
                f = d / f"{name}.tar.gz"
                if not (f.is_file() and sha256_file(f) == manifest[name]["sha256"]):
                    return None
                out[name] = f
            return manifest, out
        except (OSError, ValueError, KeyError, SnapshotError):
            return None

    def _prune(self, keep):
        """Keep the active version and the most recent other one (the last known-good); older archives go."""
        root = self.work / "archives"
        if not root.is_dir():
            return
        others = sorted((p for p in root.iterdir() if p.is_dir() and p.name not in keep), key=lambda p: p.stat().st_mtime, reverse=True)
        for p in others[1:]:
            shutil.rmtree(p, ignore_errors=True)

    def _remove_stale_runs(self):
        """Free the space held by extraction directories of earlier processes. /tmp on Vercel is small (about 525 MB, 405 MB of it
        dependencies), and each leftover run holds ~27 MB, so a few of them make the next restore fail with ENOSPC."""
        root = self.work / "run"
        if not root.is_dir():
            return
        for p in root.iterdir():
            if str(p) not in _RUNS_THIS_PROCESS:
                shutil.rmtree(p, ignore_errors=True)
                log.info("removed a stale snapshot extraction left by an earlier process: %s", p.name)

    def _load(self, manifest, archives, seconds) -> SnapshotStatus:
        t = time.perf_counter()
        self._remove_stale_runs()
        run = self.work / "run" / f"{manifest['version']}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        _RUNS_THIS_PROCESS.add(str(run))
        try:
            dirs = {}
            for name in ("index", "lifecycle"):
                dirs[name] = run / name
                safe_extract(archives[name], dirs[name], manifest[name]["unpacked_bytes"])
                skip = LOCK_FILES if name == "lifecycle" else frozenset()
                if files_digest(dirs[name], skip) != manifest[name]["tree_digest"]:
                    raise SnapshotError("checksum_mismatch", f"extracted {name} does not match the manifest tree digest")
            seconds["extract_and_verify"] = round(time.perf_counter() - t, 3)
            t = time.perf_counter()
            counts = self._check_index(dirs["index"], manifest)
            self._check_lifecycle(dirs["lifecycle"], manifest, counts)
            seconds["validate"] = round(time.perf_counter() - t, 3)
        except BaseException:
            shutil.rmtree(run, ignore_errors=True)
            raise
        return SnapshotStatus(state="ready", version=manifest["version"], db_dir=dirs["index"], lifecycle_dir=dirs["lifecycle"],
                              manifest=manifest, seconds=seconds, pinned=bool(self.pin))

    def _check_index(self, index_dir, manifest):
        facts = _chroma_facts(index_dir, manifest["index"].get("collection", COLLECTION))
        ix, emb = manifest["index"], manifest["embedding"]
        if facts["count"] != ix["chunk_count"]:
            raise SnapshotError("index_invalid", f"index holds {facts['count']} chunks, the manifest says {ix['chunk_count']}")
        if facts["dims"] != emb["dimensions"]:
            raise SnapshotError("embedding_incompatible", f"index vectors have {facts['dims']} dimensions, the manifest says {emb['dimensions']}")
        if ix.get("rag_profile") and facts["metadata"].get("rag_profile") != ix["rag_profile"]:
            raise SnapshotError("index_invalid", "the index's retrieval profile differs from the manifest")
        if self.expected_family and emb["family"] != self.expected_family:
            raise SnapshotError("embedding_incompatible", f"snapshot embeddings are {emb['family']}, this build expects {self.expected_family}")
        return facts["counts"]

    def _check_lifecycle(self, lifecycle_dir, manifest, counts):
        if sha256_file(Path(lifecycle_dir) / "registry.json") != manifest["lifecycle"]["registry_sha256"]:
            raise SnapshotError("lifecycle_invalid", "registry.json does not match the manifest")
        check_lifecycle_dir(lifecycle_dir, counts)


def check_lifecycle_dir(lifecycle_dir, counts) -> dict:
    """The registry and its audit chain verify and agree with the index's per-hash chunk counts (the same checks the server makes at
    startup). A registry with zero approved documents is consistent: it simply serves nothing."""
    from backend import document_lifecycle
    f = document_lifecycle.ServeFilter(lifecycle_dir)
    f.reconcile(Counter(counts))
    h = f.health()
    if h["state"] != "ok":
        raise SnapshotError("lifecycle_invalid", f"lifecycle registry is not consistent ({h['state']})")
    return h


@dataclass(frozen=True)
class RestoreSettings:
    """How the server restores the snapshot at start. Bounded on purpose: a free host has to open its port in reasonable time, and an
    integrity failure must stop at once instead of being retried."""
    startup_timeout: float = 60.0        # total seconds the restore may take, retries and waits included (checked between attempts)
    retry_base: float = 1.0              # first wait; doubles each attempt
    retry_max_delay: float = 15.0        # no single wait is longer than this
    require_pin: bool = False            # production/staging: TG_SNAPSHOT_PIN_SHA256 is mandatory
    problems: tuple = ()

    @classmethod
    def from_env(cls, env=None) -> "RestoreSettings":
        from backend import runtime_config
        env = os.environ if env is None else env
        problems = []

        def num(name, default, lo, hi):
            raw = (env.get(name) or "").strip()
            if not raw:
                return default
            try:
                v = float(raw)
            except ValueError:
                v = float("nan")
            if not (lo <= v <= hi):
                problems.append(f"{name} must be a number between {lo:g} and {hi:g}")
                return default
            return v
        return cls(startup_timeout=num("TG_SNAPSHOT_STARTUP_TIMEOUT_SECONDS", 60.0, 5.0, 600.0),
                   retry_base=num("TG_SNAPSHOT_RETRY_BASE_SECONDS", 1.0, 0.1, 30.0),
                   retry_max_delay=num("TG_SNAPSHOT_RETRY_MAX_DELAY_SECONDS", 15.0, 1.0, 120.0),
                   require_pin=runtime_config.is_production_like(env), problems=tuple(problems))


def activate_with_retry(manager, settings: RestoreSettings, sleep=time.sleep, clock=time.monotonic) -> SnapshotStatus:
    """Restore, retrying ONLY failures that can clear by themselves (store unreachable, timeouts, HTTP 429/5xx), with exponential
    back-off capped at settings.retry_max_delay and a total budget of settings.startup_timeout. An integrity failure (checksum, pin,
    manifest, index, lifecycle, embedding family) is final on the first attempt. Whatever happens, the result is either a fully
    verified snapshot or a not-ready status; there is no partial state."""
    start, attempt = clock(), 0
    while True:
        attempt += 1
        status = manager.activate()
        status.attempts = attempt
        if status.ready or not status.transient:
            return status
        delay = min(settings.retry_max_delay, settings.retry_base * (2 ** (attempt - 1)))
        if clock() - start + delay > settings.startup_timeout:
            status.timed_out = True
            status.problems = list(status.problems) + [f"restore gave up after {attempt} attempt(s): the {settings.startup_timeout:g} s startup budget is used up"]
            log.error("snapshot restore gave up: category=%s attempts=%d budget=%gs", status.state, attempt, settings.startup_timeout)
            return status
        log.warning("snapshot restore attempt %d failed (category=%s, transient); retrying in %.1f s", attempt, status.state, delay)
        sleep(delay)


def activate_from_env(env=None, http=None, manager_factory=None, sleep=time.sleep, clock=time.monotonic) -> SnapshotStatus:
    """Used by the server before it reads TG_DB_DIR / TG_LIFECYCLE_DIR. Disabled (and silent) unless TG_SNAPSHOT_STORE is set."""
    env = os.environ if env is None else env
    if not (env.get("TG_SNAPSHOT_STORE") or "").strip():
        return SnapshotStatus(state="disabled")
    try:
        for name in ("TG_DB_DIR", "TG_LIFECYCLE_DIR"):
            if name in env:
                raise SnapshotError("misconfigured", f"{name} must not be set when TG_SNAPSHOT_STORE is used (the snapshot supplies it)")
        settings = RestoreSettings.from_env(env)
        if settings.problems:
            raise SnapshotError("misconfigured", "; ".join(settings.problems))
        pin = (env.get("TG_SNAPSHOT_PIN_SHA256") or "").strip().lower()
        if pin and not _HEX.match(pin):
            raise SnapshotError("misconfigured", "TG_SNAPSHOT_PIN_SHA256 must be 64 hex characters")
        if settings.require_pin and not pin:
            # The pointer and the manifest live in the same bucket as the snapshot, so they cannot vouch for themselves: whoever can
            # write the bucket can publish a consistent, different snapshot. The pin is the reviewed manifest digest held outside it.
            raise SnapshotError("pin_required", "TG_SNAPSHOT_PIN_SHA256 is required in production: set it to the sha256 of the reviewed "
                                                "manifest (python -m backend.index_snapshot pin)")
        store = store_from_env(env, http=http, sleep=sleep)
        work = Path((env.get("TG_SNAPSHOT_WORK_DIR") or "").strip() or Path(tempfile.gettempdir()) / "kyr-snapshots")
        mgr = (manager_factory or SnapshotManager)(
            store, work, pin_sha256=pin or None, expected_family=(env.get("TG_SNAPSHOT_EXPECT_FAMILY") or "").strip() or None,
            allow_stale=(env.get("TG_SNAPSHOT_ALLOW_STALE") or "").strip().lower() in ("1", "true", "yes"))
        return activate_with_retry(mgr, settings, sleep=sleep, clock=clock)
    except SnapshotError as err:
        return SnapshotStatus(state=err.state, problems=[err.detail or err.state])


# ---------------------------------------------------------------------------------------------------
# Operator CLI
# ---------------------------------------------------------------------------------------------------
def main(argv=None, out=print) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Index snapshots (operator tool). Reads the live directories without opening them.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("publish", help="package index + lifecycle and write them to the store (local dry run, or R2 with write credentials)")
    p.add_argument("--db-dir", required=True)
    p.add_argument("--lifecycle-dir", required=True)
    p.add_argument("--by", required=True, help="operator name recorded in the manifest")
    p.add_argument("--notes", default="")
    p.add_argument("--version")
    r = sub.add_parser("rollback", help="repoint the active pointer at an earlier version (review its lifecycle registry first)")
    r.add_argument("--to", required=True)
    r.add_argument("--by", required=True)
    sub.add_parser("verify", help="download and fully verify the active snapshot into a temporary directory")
    sub.add_parser("show", help="print the active pointer")
    sub.add_parser("pin", help="print the sha256 of the active manifest: the value for TG_SNAPSHOT_PIN_SHA256 (after you have reviewed it)")
    args = ap.parse_args(argv)
    try:
        store = store_from_env()
        if store is None:
            out("TG_SNAPSHOT_STORE is not set")
            return 2
        if args.cmd == "show":
            out(store.get_bytes("active.json").decode())
            return 0
        if args.cmd == "pin":
            pointer = parse_pointer(store.get_bytes("active.json", limit=1 << 20))
            raw = store.get_bytes(pointer["manifest_key"], limit=16 * 1024 * 1024)
            if sha256_bytes(raw) != pointer["manifest_sha256"]:
                out("failed: the manifest does not match the checksum in the active pointer; do not pin it")
                return 1
            m = json.loads(raw.decode("utf-8"))
            out(json.dumps({"version": pointer["version"], "manifest_sha256": pointer["manifest_sha256"], "created_at": m.get("created_at"),
                            "created_by": m.get("created_by"), "chunks": (m.get("index") or {}).get("chunk_count"),
                            "sources": (m.get("lifecycle") or {}).get("sources"), "TG_SNAPSHOT_PIN_SHA256": pointer["manifest_sha256"]}, indent=1))
            return 0
        if args.cmd == "rollback":
            out(json.dumps(rollback(store, args.to, args.by), indent=1))
            return 0
        if args.cmd == "verify":
            work = tempfile.mkdtemp(prefix="kyr-snap-verify-")
            try:
                st = SnapshotManager(store, work).activate()
                out(json.dumps(st.public(), indent=1))
                return 0 if st.ready else 1
            finally:
                shutil.rmtree(work, ignore_errors=True)
        from backend import embedding_provider as ep
        guard = ep.build_embeddings(ep.EmbeddingSettings.from_env(os.environ))
        if guard.settings.hosted:
            out("publish must embed with the model that built the index: use EMBEDDING_PROVIDER=ollama (local)")
            return 2
        m = publish(store, args.db_dir, args.lifecycle_dir, embed=guard.embed_documents, embedding_model=guard.model,
                    family=ep.INDEX_FAMILY, created_by=args.by, notes=args.notes, version=args.version)
        out(json.dumps({k: m[k] for k in ("version", "created_at")} | {"index": m["index"]["sha256"], "lifecycle": m["lifecycle"]["sha256"]}, indent=1))
        return 0
    except (SnapshotError, StoreError) as err:
        out(f"failed: {err}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
