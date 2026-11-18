"""Document lifecycle (Stage 6): versions, explicit approval and withdrawal, incremental index updates, rollback.

Registry (one JSON file, written atomically, plus one snapshot per version):
  <state_dir>/registry.json            sources -> versions -> state, history, supersedes links; audit events; crash journal
  <state_dir>/versions/<sha256>.json   the version's chunks (text + metadata) and, once indexed, their embeddings

A "source" is a manifest entry id; a "version" is one file content (SHA-256). States and the only allowed transitions:

    pending  --approve-->  approved        approved --withdraw--> withdrawn   (terminal)
    pending  --reject-->   rejected        approved --replace---> superseded  (a newer version was approved)
    superseded --rollback-> approved       approved --rollback--> superseded  (another version was restored)

Rules this module enforces:
  * ingestion never approves and never touches the index: a new version is "pending" and absent from retrieval;
  * only an approved version that is the source's active version has chunks in the production collection, so a pending,
    rejected, superseded or withdrawn version can never be retrieved (the collection is the single place chunks live);
  * every index change is copy-on-write: a staging collection is built from the live one (unchanged rows copied with
    their stored embeddings), only new chunks are embedded, the result is verified, then renamed over the live one; the
    previous collection is deleted only after the new one passed a health check. Any failure leaves the live index as it was;
  * registry and index change together: the intended registry is written as a journal entry before the swap and committed
    after it; recover() finishes or undoes an interrupted operation on the next start;
  * nothing is inferred: effective dates are copied from the manifest or stay empty; legal meaning of an amendment is not
    interpreted; approval is an explicit call with a name and a note.
Approval by this module is the *document-lifecycle* approval, and it is the only gate on what is retrieved: a signed approval
record is no longer used. The operator name, note and bootstrap approval basis are recorded verbatim and are unauthenticated.

Chunk ids are deterministic (source version + provision + part + text), so ingesting or indexing the same content twice never
creates a second row.
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import hashlib
import json
import os
import sys
import shutil
import tempfile
import threading
import time
import types
from pathlib import Path

from backend import index_validity, tg_manifest

try:  # POSIX (Linux, macOS)
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None
try:  # Windows
    import msvcrt
except ImportError:
    msvcrt = None

PENDING, APPROVED, REJECTED, SUPERSEDED, WITHDRAWN = "pending", "approved", "rejected", "superseded", "withdrawn"
STATES = (PENDING, APPROVED, REJECTED, SUPERSEDED, WITHDRAWN)
TRANSITIONS = {  # (from, to): operation that may perform it
    (PENDING, APPROVED): "approve", (PENDING, REJECTED): "reject", (APPROVED, WITHDRAWN): "withdraw",
    (APPROVED, SUPERSEDED): "replace/rollback", (SUPERSEDED, APPROVED): "rollback",
}
SCHEMA = 1
BATCH = 100


class LifecycleError(Exception):
    pass


def _sha(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def chunk_id(chunk) -> str:
    """Deterministic row id: the same chunk of the same file always has the same id."""
    m = chunk.metadata
    return _sha(m.get("sha256"), m.get("provision_id"), m.get("part"), m.get("location"), chunk.page_content)[:40]


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atomic_write(path: Path, data: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def tree_digest(root) -> str:
    """Digest of every file under root (relative path, size, content hash): proves a directory was not modified."""
    h = hashlib.sha256()
    root = Path(root)
    for p in sorted(x for x in root.rglob("*") if x.is_file()):
        h.update(str(p.relative_to(root)).encode())
        h.update(str(p.stat().st_size).encode())
        with open(p, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
    return h.hexdigest()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


DEFAULT_LOCK_TIMEOUT = 30.0
GENESIS = "0" * 64
ASSURANCE = "operator-supplied-unauthenticated"   # what every recorded operator name is, until an authenticated provider exists
MAX_NAME = 120
MAX_BASIS = 2000


class LockTimeout(LifecycleError):
    """Another process holds the lifecycle lock and did not release it within the timeout."""


class ProcessLock:
    """Exclusive cross-process lock on <state_dir>/.lifecycle.lock using the OS file-lock (flock on POSIX, msvcrt on Windows).
    The OS releases it when the holder exits or is killed, so a crash cannot leave a stale lock; the file's text (holder pid,
    operation, operator, start time) is informational only and never decides ownership."""

    def __init__(self, path, timeout=DEFAULT_LOCK_TIMEOUT):
        self.path, self.timeout, self.fd = Path(path), timeout, None

    def acquire(self, holder: dict):
        if fcntl is None and msvcrt is None:
            raise LifecycleError("no OS file locking is available on this platform: lifecycle mutations are refused")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                if fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:  # pragma: no cover
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                break
            except OSError as e:
                if e.errno not in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK, errno.EDEADLK):
                    os.close(fd)
                    raise LifecycleError(f"cannot lock {self.path.name}: {e.__class__.__name__}") from e
                if time.monotonic() >= deadline:
                    info = self._holder(fd)
                    os.close(fd)
                    raise LockTimeout(f"the lifecycle lock is held by another process{info}; gave up after {self.timeout:g}s. "
                                      "Nothing was changed. Retry later; the lock is released automatically when that "
                                      "process ends.") from None
                time.sleep(0.05)
        self.fd = fd
        os.ftruncate(fd, 0)
        os.pwrite(fd, json.dumps(dict(holder, pid=os.getpid(), since=_now())).encode(), 0)

    @staticmethod
    def _holder(fd) -> str:
        try:
            h = json.loads(os.pread(fd, 4096, 0).decode() or "{}")
            return f" (pid {h.get('pid')}, operation {h.get('op')!r}, operator {h.get('by')!r}, since {h.get('since')})"
        except (OSError, ValueError):
            return ""

    def release(self):
        if self.fd is None:
            return
        fd, self.fd = self.fd, None
        try:
            os.ftruncate(fd, 0)
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
            else:  # pragma: no cover
                os.lseek(fd, 0, 0)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(fd)


def _event_hash(event: dict) -> str:
    body = {k: v for k, v in event.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def audit_problems(reg: dict, mirror_path=None) -> list[str]:
    """Integrity of the audit history: every event is hash-chained to the one before (so an edited, removed, inserted or
    reordered event is detected), and the append-only mirror file, if present, must agree with the registry's events and never
    be longer than them. A determined attacker who can rewrite BOTH files and recompute the chain is not detected: this is
    tamper-evidence against accidents and edits, not authentication."""
    events = reg.get("events", [])
    if not isinstance(events, list):
        return ["audit history is not a list"]
    problems = []
    if events and not any(isinstance(e, dict) and "hash" in e for e in events):
        return ["legacy audit history without a hash chain: run audit-adopt to make it tamper-evident"]
    prev = GENESIS
    for i, e in enumerate(events):
        if (not isinstance(e, dict) or e.get("seq") != i or e.get("prev") != prev or e.get("hash") != _event_hash(e)
                or not e.get("op") or "at" not in e):
            problems.append(f"audit event {i} is missing, altered, reordered or malformed")
            break
        prev = e["hash"]
    if mirror_path is not None and events and not Path(mirror_path).exists():
        return problems + ["the audit mirror file is missing: its history cannot be cross-checked (run audit-repair-mirror)"]
    if mirror_path is not None and Path(mirror_path).is_file():
        try:
            lines = [json.loads(x) for x in Path(mirror_path).read_text(encoding="utf-8").splitlines() if x.strip()]
        except (OSError, ValueError):
            return problems + ["the audit mirror file is unreadable or malformed"]
        if len(lines) > len(events):
            problems.append("the audit mirror records more events than the registry: the registry was rolled back or truncated")
        for i, line in enumerate(lines[:len(events)]):
            if not isinstance(line, dict) or line.get("hash") != events[i].get("hash"):
                problems.append(f"audit event {i} differs from the append-only mirror")
                break
    return problems


class Chunk:
    """Minimal Document stand-in (page_content + metadata) so the module needs no LangChain types."""

    def __init__(self, page_content, metadata):
        self.page_content, self.metadata = page_content, dict(metadata)


def validate_chunks(chunks, sha256: str, jurisdiction="Telangana") -> list[str]:
    """The checks verify_staging applies in the full builder, applied to one document's chunks."""
    problems, seen = [], set()
    if not chunks:
        return ["the document produced no chunks"]
    for c in chunks:
        m = c.metadata
        if m.get("sha256") != sha256:
            problems.append("a chunk carries a different sha256 than its document")
        if m.get("jurisdiction") != jurisdiction or m.get("state") != jurisdiction:
            problems.append(f"a chunk is not tagged {jurisdiction}")
        if not m.get("provision_id") or not m.get("location") or not m.get("title"):
            problems.append("a chunk is missing provision, location or title metadata")
        if not isinstance(m.get("answer_eligible"), bool):
            problems.append("a chunk has no answer_eligible flag")
        if not (c.page_content or "").strip():
            problems.append("a chunk is empty")
        cid = chunk_id(c)
        if cid in seen:
            problems.append("duplicate chunk inside the document")
        seen.add(cid)
        problems += index_validity.chunk_problems(m)
    return sorted(set(problems))


def rec_validity(rec) -> tuple:
    """(status, valid_from, valid_to) of a registry version. A record from before validity existed is 'unknown'."""
    return rec.get("validity_status") or tg_manifest.UNKNOWN, rec.get("valid_from"), rec.get("valid_to")


def verified_window(rec):
    """(valid_from, valid_to) when the version carries a verified, well-formed range, else None. Never inferred."""
    status, start, end = rec_validity(rec)
    if status == tg_manifest.UNKNOWN or tg_manifest.validity_problems(start, end, status, rec.get("validity_basis")):
        return None
    return start, end


def overlay_validity(metadata: dict, rec) -> dict:
    """Chunk metadata with the registry's validity applied (the registry is the authority once a version records one)."""
    if "validity_status" not in rec:
        return dict(metadata)
    out = {k: v for k, v in metadata.items() if k not in ("valid_from", "valid_to", "validity_status")}
    out.update(tg_manifest.validity_metadata(types.SimpleNamespace(
        validity_status=rec["validity_status"], valid_from=rec.get("valid_from"), valid_to=rec.get("valid_to"))))
    return out


class Lifecycle:
    def __init__(self, state_dir, db_dir=None, embeddings=None, chunker=None, clock=_now, collection=None,
                 invalidate=None, lock_timeout=None, source_status_file=None):
        """embeddings: object with embed_documents(list[str]) and optional embedder_id. chunker(entry, corpus_dir) ->
        chunks (default: the Telangana ingestion pipeline). invalidate(sha256s, source_id): called after every committed
        change; in a running server the cache also follows the registry digest through its epoch."""
        from backend import build_telangana_index as btx
        self.btx = btx
        self.dir, self.registry_path = Path(state_dir), Path(state_dir) / "registry.json"
        self.versions_dir = self.dir / "versions"
        self.db_dir = Path(db_dir) if db_dir is not None else None
        self.embeddings, self.chunker, self.clock, self.invalidate = embeddings, chunker, clock, invalidate
        self.collection = collection or btx.COLLECTION
        self.lock = threading.RLock()
        self.audit_path = self.dir / "audit.jsonl"
        self.source_status_file = source_status_file
        timeout = lock_timeout if lock_timeout is not None else float(os.environ.get("TG_LIFECYCLE_LOCK_TIMEOUT", DEFAULT_LOCK_TIMEOUT))
        self._plock, self._depth = ProcessLock(self.dir / ".lifecycle.lock", timeout), 0

    # ------------------------------------------------------------------------------------------------ registry I/O
    def load(self) -> dict:
        if not self.registry_path.is_file():
            return {"schema_version": SCHEMA, "sources": {}, "events": [], "intent": None}
        try:
            reg = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise LifecycleError(f"registry unreadable: {e.__class__.__name__}") from e
        if not isinstance(reg, dict) or reg.get("schema_version") != SCHEMA or not isinstance(reg.get("sources"), dict):
            raise LifecycleError("registry has an unknown format")
        return reg

    def _save(self, reg: dict):
        _atomic_write(self.registry_path, json.dumps(reg, indent=1, sort_keys=True, ensure_ascii=False))
        if not reg.get("intent"):   # a journal entry is not history yet; committed registries are mirrored
            self._sync_audit(reg)

    def _sync_audit(self, reg: dict):
        """Append the events the mirror has not seen yet (one JSON line each, fsynced). The mirror only ever grows."""
        events = reg.get("events", [])
        try:
            have = len([x for x in self.audit_path.read_text(encoding="utf-8").splitlines() if x.strip()]) \
                if self.audit_path.is_file() else 0
            if have < len(events) and all("hash" in e for e in events):
                with open(self.audit_path, "a", encoding="utf-8") as f:
                    for e in events[have:]:
                        f.write(json.dumps(e, sort_keys=True, ensure_ascii=False) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
        except OSError as e:
            raise LifecycleError(f"the registry was saved but the audit mirror could not be written: {e.__class__.__name__}") from e

    def audit_check(self) -> list[str]:
        """Audit problems of the registry on disk ([] if none or no registry yet). Read-only."""
        if not self.registry_path.is_file():
            return []
        return audit_problems(self.load(), self.audit_path)

    @contextlib.contextmanager
    def _mutation(self, op, by=None, audit_guard=True, require_operator=True):
        """Every registry/index mutation runs inside this: the operator name is validated first, then the cross-process lock
        is taken (re-entrant within the process), then the audit history must be intact. Reads never come through here."""
        if require_operator or by is not None:
            self._who(by)
        with self.lock:
            if self._depth == 0:
                self._plock.acquire({"op": op, "by": str(by)[:MAX_NAME] if by else None})
            self._depth += 1
            try:
                if audit_guard:
                    problems = self.audit_check()
                    if problems:
                        raise LifecycleError("audit integrity failure, no mutation allowed: " + "; ".join(problems))
                yield
            finally:
                self._depth -= 1
                if self._depth == 0:
                    self._plock.release()

    @staticmethod
    def _event(reg, op, source_id, version, by, note, prev_state=None, new_state=None, **extra):
        events = reg["events"]
        ev = dict({"seq": len(events), "at": _now(), "op": op, "source": source_id, "version": version, "by": by,
                   "note": note, "previous_state": prev_state, "new_state": new_state, "identity_assurance": ASSURANCE,
                   "prev": events[-1]["hash"] if events else GENESIS}, **extra)
        ev["hash"] = _event_hash(ev)
        events.append(ev)

    def _snapshot_path(self, sha256: str) -> Path:
        return self.versions_dir / f"{sha256}.json"

    def _read_snapshot(self, sha256: str) -> dict:
        try:
            return json.loads(self._snapshot_path(sha256).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise LifecycleError(f"version snapshot {sha256[:12]} is missing or unreadable") from e

    def _write_snapshot(self, sha256, chunks, embeddings=None, embedder=None):
        _atomic_write(self._snapshot_path(sha256), json.dumps({
            "sha256": sha256, "embedder": embedder,
            "chunks": [{"id": chunk_id(c), "text": c.page_content, "metadata": c.metadata,
                        "embedding": (embeddings or {}).get(chunk_id(c))} for c in chunks]}, ensure_ascii=False))

    # ------------------------------------------------------------------------------------------------ ingestion
    def ingest(self, entry, corpus_dir, by="", note="") -> dict:
        """Register a document file as a new PENDING version. Never approves, never touches the index."""
        from backend import tg_manifest
        with self._mutation("ingest", by):
            self._refuse_if_interrupted()
            if entry.source_class == "draft":
                raise LifecycleError(f"{entry.id}: draft documents are never indexed")
            problems = tg_manifest.file_errors([entry], corpus_dir)
            if problems:
                raise LifecycleError("; ".join(problems))
            reg = self.load()
            src = reg["sources"].get(entry.id)
            if src:
                for v, rec in src["versions"].items():
                    if rec["sha256"] == entry.sha256:
                        self._event(reg, "ingest_unchanged", entry.id, int(v), by, note, prev_state=rec["state"], new_state=rec["state"], sha256=entry.sha256)
                        self._save(reg)
                        return {"outcome": "unchanged", "source": entry.id, "version": int(v), "state": rec["state"]}
            chunker = self.chunker or self._default_chunker
            chunks = chunker(entry, corpus_dir)
            problems = validate_chunks(chunks, entry.sha256, entry.jurisdiction)
            want = tg_manifest.validity_metadata(entry)
            if any((c.metadata.get("valid_from"), c.metadata.get("valid_to")) != (want.get("valid_from"), want.get("valid_to"))
                   for c in chunks):
                problems.append("a chunk's validity dates differ from the manifest entry's")
            if tg_manifest.validity_problems(entry.valid_from, entry.valid_to, entry.validity_status, entry.validity_basis, entry.id):
                problems.append("the manifest entry's validity is malformed")
            if problems:
                raise LifecycleError(f"{entry.id}: " + "; ".join(sorted(set(problems))))
            self._write_snapshot(entry.sha256, chunks)
            new_source = src is None
            src = reg["sources"].setdefault(entry.id, {"active_version": None, "versions": {}})
            number = max((int(v) for v in src["versions"]), default=0) + 1
            at = self.clock()
            src["versions"][str(number)] = {
                "version": number, "sha256": entry.sha256, "file": entry.file, "ingested_at": at, "state": PENDING,
                "effective_date": entry.effective_date or None, "chunk_count": len(chunks),
                "supersedes": src["active_version"], "superseded_by": None, "embedder": None,
                "validity_status": entry.validity_status, "valid_from": entry.valid_from, "valid_to": entry.valid_to,
                "validity_basis": entry.validity_basis,
                "metadata": {k: getattr(entry, k) for k in (
                    "title", "document_type", "issuing_authority", "document_number", "publication_date",
                    "effective_date", "source_url", "source_class", "verification_status", "notes", "format")},
                "history": [{"state": PENDING, "at": at, "by": by, "note": note}]}
            self._event(reg, "ingest", entry.id, number, by, note, prev_state=None, new_state=PENDING, sha256=entry.sha256)
            self._save(reg)
            return {"outcome": "new_source" if new_source else "new_version", "source": entry.id, "version": number,
                    "state": PENDING, "chunks": len(chunks), "supersedes": src["versions"][str(number)]["supersedes"]}

    @staticmethod
    def _default_chunker(entry, corpus_dir):
        from backend import tg_ingest
        blocks = tg_ingest.load_blocks(Path(corpus_dir) / entry.file, entry.format, entry.file)
        return tg_ingest.chunk_document(blocks, entry, tg_ingest.snapshot_chapter(corpus_dir, entry.file))

    # ------------------------------------------------------------------------------------------------ transitions
    def _version(self, reg, source_id, version):
        src = reg["sources"].get(source_id)
        rec = src and src["versions"].get(str(version))
        if not rec:
            raise LifecycleError(f"{source_id} version {version} does not exist")
        return src, rec

    @staticmethod
    def _move(rec, state, by, note, at):
        if (rec["state"], state) not in TRANSITIONS:
            raise LifecycleError(f"cannot move {rec['state']} to {state}")
        rec["state"] = state
        rec["history"].append({"state": state, "at": at, "by": by, "note": note})

    def reject(self, source_id, version, by, note="") -> dict:
        with self._mutation("reject", by):
            self._refuse_if_interrupted()
            reg = self.load()
            _, rec = self._version(reg, source_id, version)
            self._move(rec, REJECTED, self._who(by), note, self.clock())
            self._event(reg, "reject", source_id, version, by, note, prev_state=PENDING, new_state=REJECTED, sha256=rec["sha256"])
            if (rec.get("quarantine") or {}).get("in_index"):   # a quarantined legacy document: remove its chunks too
                rec["quarantine"]["in_index"] = False
                self._apply_index(reg, remove={rec["sha256"]}, add=[], op="reject", source_id=source_id,
                                  changed={rec["sha256"]})
                return {"source": source_id, "version": version, "state": REJECTED, "chunks_removed": True}
            self._save(reg)
            return {"source": source_id, "version": version, "state": REJECTED}

    def approve(self, source_id, version, by, note="", accept_missing_status=False) -> dict:
        """Approve a PENDING version, make it the source's active version and index it. A previously active version is
        superseded and its chunks leave the index in the same atomic swap. This is a document-lifecycle decision by a named but
        unauthenticated operator; the name and note are labels, not proof of who approved or why.
        With a source-status registry configured, a version without a usable status entry is refused unless
        accept_missing_status is passed (and then recorded)."""
        with self._mutation("approve", by):
            self._refuse_if_interrupted()
            reg = self.load()
            src, rec = self._version(reg, source_id, version)
            if rec["state"] != PENDING:
                raise LifecycleError(f"only a pending version can be approved (this one is {rec['state']})")
            if (rec.get("quarantine") or {}).get("in_index"):
                raise LifecycleError("this legacy document is quarantined: it can only be approved by re-running bootstrap "
                                     "with an approval basis (or rejected, which removes its chunks)")
            cov = self._coverage_gate(source_id, rec, accept_missing_status)
            return self._activate(reg, src, rec, "approve", by, note, cov)

    def rollback(self, source_id, to_version, by, note="", accept_missing_status=False) -> dict:
        """Restore a previously approved (now superseded) version. Pending, rejected and withdrawn versions are refused."""
        with self._mutation("rollback", by):
            self._refuse_if_interrupted()
            reg = self.load()
            src, rec = self._version(reg, source_id, to_version)
            if rec["state"] != SUPERSEDED or not any(h["state"] == APPROVED for h in rec["history"]):
                raise LifecycleError(f"cannot roll back to a version that is {rec['state']}: only a previously approved, "
                                     "superseded version can be restored")
            if not self._snapshot_path(rec["sha256"]).is_file():
                raise LifecycleError("the version's snapshot is missing; it cannot be restored")
            cov = self._coverage_gate(source_id, rec, accept_missing_status)
            return self._activate(reg, src, rec, "rollback", by, note, cov)

    def withdraw(self, source_id, version, by, note="") -> dict:
        """Withdraw the approved version: its chunks leave the index. No earlier version is restored automatically."""
        with self._mutation("withdraw", by):
            self._refuse_if_interrupted()
            reg = self.load()
            src, rec = self._version(reg, source_id, version)
            if rec["state"] != APPROVED:
                raise LifecycleError(f"only an approved version can be withdrawn (this one is {rec['state']})")
            at = self.clock()
            self._move(rec, WITHDRAWN, self._who(by), note, at)
            src["active_version"] = None
            self._event(reg, "withdraw", source_id, version, by, note, prev_state=APPROVED, new_state=WITHDRAWN, sha256=rec["sha256"])
            self._apply_index(reg, remove={rec["sha256"]}, add=[], op="withdraw", source_id=source_id,
                              changed={rec["sha256"]})
            return {"source": source_id, "version": version, "state": WITHDRAWN}

    def close_validity(self, source_id, version, valid_to: int, basis: str, by, note="") -> dict:
        """Record, from stated legal evidence, the last day a version's text applied (it was verified_continuing). Needed
        before a newer version with an overlapping range can be approved, and what lets a superseded version stay in the
        index as history. Nothing is inferred: the date and the evidence are the operator's, recorded in the audit chain.
        Only a once-approved version with a verified continuing range can be closed; a closed range is never edited."""
        with self._mutation("close_validity", by):
            self._refuse_if_interrupted()
            reg = self.load()
            src, rec = self._version(reg, source_id, version)
            status, start, end = rec_validity(rec)
            if status != tg_manifest.CONTINUING or verified_window(rec) is None:
                raise LifecycleError(f"only a version with a verified continuing validity range can be closed (this one is {status})")
            if rec["state"] not in (APPROVED, SUPERSEDED) or not any(h["state"] == APPROVED for h in rec["history"]):
                raise LifecycleError(f"a {rec['state']} version cannot be closed: only a once-approved version")
            if not isinstance(basis, str) or not basis.strip():
                raise LifecycleError("the legal evidence for the closing date is required")
            if tg_manifest.validity_problems(start, valid_to, tg_manifest.CLOSED, basis, "close_validity") or valid_to == tg_manifest.OPEN_ENDED:
                raise LifecycleError("valid_to must be a real YYYYMMDD date on or after valid_from, and not 99991231")
            rec["valid_to"], rec["validity_status"], rec["validity_closed_basis"] = valid_to, tg_manifest.CLOSED, basis.strip()
            self._refuse_overlap(src, rec)
            self._event(reg, "close_validity", source_id, version, by, note, prev_state=rec["state"], new_state=rec["state"],
                        sha256=rec["sha256"], valid_from=start, valid_to=valid_to, basis=basis.strip())
            update = {rec["sha256"]: {"valid_to": valid_to, "validity_status": tg_manifest.CLOSED}}
            if rec["state"] == APPROVED:   # its rows are in the index: update their dates in place
                self._apply_index(reg, remove=set(), add=[], op="close_validity", source_id=source_id,
                                  changed={rec["sha256"]}, meta_updates=update)
            elif self.retainable(rec):     # superseded and until now removed: it now qualifies as history, so bring it back
                self._apply_index(reg, remove=set(), add=[self._prepare_chunks(rec, src)], op="close_validity",
                                  source_id=source_id, changed={rec["sha256"]})
            else:
                self._save(reg)
            return {"source": source_id, "version": version, "state": rec["state"], "valid_from": start, "valid_to": valid_to}

    @staticmethod
    def _who(by):
        """The operator name supplied for a mutation. It is a LABEL, recorded as supplied and marked unauthenticated in every
        audit event: nothing here proves who typed it. Empty, non-text, over-long or control-character names are refused."""
        if not isinstance(by, str) or not by.strip():
            raise LifecycleError("an explicit approver/operator name is required")
        if len(by) > MAX_NAME or any(ord(c) < 32 or ord(c) == 127 for c in by):
            raise LifecycleError("the operator name is too long or contains control characters")
        return by

    def _activate(self, reg, src, rec, op, by, note, coverage=None):
        at, by = self.clock(), self._who(by)
        old = src["versions"].get(str(src["active_version"])) if src["active_version"] is not None else None
        remove, retired = set(), set()
        if old is not None and old is not rec:
            self._move(old, SUPERSEDED, by, f"{op}: replaced by version {rec['version']}", at)
            old["superseded_by"] = rec["version"]
            retired.add(old["sha256"])
            if not self.retainable(old):   # no verified closed range: it cannot answer a dated question, so it leaves the index
                remove.add(old["sha256"])
        self._move(rec, APPROVED, by, note, at)
        rec["superseded_by"] = None
        src["active_version"] = rec["version"]
        self._refuse_overlap(src, rec)
        remove.add(rec["sha256"])   # a version restored by rollback may still be in the index as history: replace its rows
        add = self._prepare_chunks(rec, src)
        reg["embedder"] = add["embedder"]
        source_id = next(k for k, v in reg["sources"].items() if v is src)
        if old is not None and old is not rec:
            self._event(reg, "supersede", source_id, old["version"], by, f"{op}: replaced by version {rec['version']}",
                        prev_state=APPROVED, new_state=SUPERSEDED, sha256=old["sha256"], superseded_by=rec["version"])
        self._event(reg, op, source_id, rec["version"], by, note, prev_state=PENDING if op == "approve" else SUPERSEDED,
                    new_state=APPROVED, sha256=rec["sha256"], replaced=old["version"] if old else None,
                    legal_approval="not established by this operation: the name and note are unauthenticated labels",
                    warning_coverage=(coverage or {}).get("coverage"), warning_findings=(coverage or {}).get("findings"),
                    status_override_accepted=bool((coverage or {}).get("override")))
        out = self._apply_index(reg, remove=remove, add=[add], op=op, source_id=source_id,
                                changed=retired | {rec["sha256"]})
        out.update(source=source_id, version=rec["version"], state=APPROVED,
                   replaced=old["version"] if old else None, warning_coverage=coverage)
        return out

    # ------------------------------------------------------------------------------------------------ embeddings
    def _embedder_id(self) -> str:
        e = self.embeddings
        if e is None:
            raise LifecycleError("no embedding function configured")
        return getattr(e, "embedder_id", None) or (
            f"{type(getattr(e, 'base', e)).__name__}:{getattr(getattr(e, 'base', e), 'model', '')}:"
            f"{getattr(getattr(e, 'profile', None), 'name', '')}")

    def _prepare_chunks(self, rec, src) -> dict:
        """(sha256, chunks, vectors) for a version. Reuses stored vectors for chunks whose text is unchanged (same embedder,
        this version's snapshot, other versions of the source, live rows); embeds only the rest."""
        snap = self._read_snapshot(rec["sha256"])
        embedder = self._embedder_id()
        recorded = self.load().get("embedder")
        if recorded and recorded != embedder:
            raise LifecycleError(f"the index was embedded with {recorded!r} but the configured embedder is {embedder!r}: "
                                 "stored vectors cannot be mixed, rebuild the index instead")
        chunks = [Chunk(c["text"], overlay_validity(c["metadata"], rec)) for c in snap["chunks"]]
        known: dict[str, list] = {}
        if snap.get("embedder") == embedder:
            known.update({c["id"]: c["embedding"] for c in snap["chunks"] if c.get("embedding")})
        by_text: dict[str, list] = {}
        for other in src["versions"].values():
            if other["sha256"] == rec["sha256"] or not self._snapshot_path(other["sha256"]).is_file():
                continue
            o = self._read_snapshot(other["sha256"])
            if o.get("embedder") == embedder:
                by_text.update({text_digest(c["text"]): c["embedding"] for c in o["chunks"] if c.get("embedding")})
        for row in self._live_rows():
            by_text.setdefault(text_digest(row["document"]), row["embedding"])
        vectors, todo = {}, []
        for c, raw in zip(chunks, snap["chunks"]):
            cid = raw["id"]
            vec = known.get(cid) or by_text.get(text_digest(c.page_content))
            if vec:
                vectors[cid] = [float(x) for x in vec]
            else:
                todo.append((cid, c))
        for i in range(0, len(todo), BATCH):
            batch = todo[i:i + BATCH]
            out = self.embeddings.embed_documents([c.page_content for _, c in batch])
            if len(out) != len(batch):
                raise LifecycleError("the embedding function returned the wrong number of vectors")
            for (cid, _), v in zip(batch, out):
                vectors[cid] = [float(x) for x in v]
        return {"sha256": rec["sha256"], "chunks": chunks, "ids": [c["id"] for c in snap["chunks"]], "vectors": vectors,
                "embedded": len(todo), "reused": len(chunks) - len(todo), "embedder": embedder}

    def _live_rows(self):
        if self.db_dir is None:
            return []
        import chromadb
        try:
            col = chromadb.PersistentClient(path=str(self.db_dir)).get_collection(self.collection, embedding_function=None)
            got = col.get(include=["documents", "embeddings"])
        except Exception:  # noqa: BLE001 - no live collection yet
            return []
        return [{"document": d, "embedding": e} for d, e in zip(got["documents"], got["embeddings"])]

    # ------------------------------------------------------------------------------------------------ index update
    def _apply_index(self, reg, remove: set, add: list, op: str, source_id: str, changed: set, meta_updates=None) -> dict:
        """Journal, copy-on-write swap, health check, commit. reg already holds the intended registry state."""
        import chromadb
        btx = self.btx
        if self.db_dir is None:
            raise LifecycleError("no index directory configured")
        client = chromadb.PersistentClient(path=str(self.db_dir))
        self._recover_collections(client, reg)
        expected = self.expected_hashes(reg)
        previous_registry = self.load()
        # the journal carries the full intended registry; the file on disk keeps the OLD state until commit
        pending = dict(previous_registry, intent={"op": op, "source": source_id, "expected": sorted(expected),
                                                  "at": _now(), "next": reg,
                                                  "before": sorted(self._live_hashes(client))})
        self._save(pending)
        embedded = sum(a["embedded"] for a in add)
        try:
            self._stage(client, remove, add, expected, meta_updates)
            self._swap(client, expected)
        except Exception as e:  # noqa: BLE001 - any failure: live index untouched or restored, registry unchanged
            self._cleanup_staging(client)
            self._save(dict(previous_registry, intent=None))
            raise LifecycleError(f"index update failed, the previous index was kept: {e}") from e
        for a in add:  # persist vectors so a rollback or later version can reuse them
            self._write_snapshot(a["sha256"], a["chunks"], a["vectors"] and {i: a["vectors"][i] for i in a["ids"]},
                                 a["embedder"])
            for rec in (r for s in reg["sources"].values() for r in s["versions"].values() if r["sha256"] == a["sha256"]):
                rec["embedder"] = a["embedder"]
        reg["intent"] = None
        self._save(reg)
        if self.invalidate:
            try:
                self.invalidate(sorted(changed), source_id)
            except Exception:  # noqa: BLE001 - invalidation callbacks must not undo a committed change
                pass
        return {"op": op, "indexed_hashes": sorted(expected), "embedded": embedded,
                "reused": sum(a["reused"] for a in add)}

    @staticmethod
    def servable_hashes(reg) -> set:
        """File hashes production retrieval may serve: the approved, active version of each source. Nothing else."""
        out = set()
        for src in reg["sources"].values():
            if src["active_version"] is not None:
                rec = src["versions"][str(src["active_version"])]
                if rec["state"] == APPROVED:
                    out.add(rec["sha256"])
        return out

    @staticmethod
    def retainable(rec) -> bool:
        """May this superseded version stay in the index as HISTORY? Only a version that was once approved and carries a
        verified, closed validity range (valid_to before 99991231). History is never current law: servable_hashes() does not
        include it, so undated questions never see it; only a dated question whose offence date falls in its range can."""
        window = verified_window(rec)
        return (rec["state"] == SUPERSEDED and window is not None and window[1] != tg_manifest.OPEN_ENDED
                and any(h["state"] == APPROVED for h in rec["history"]))

    @staticmethod
    def historical_hashes(reg) -> set:
        """File hashes kept for historical offence-date questions: retainable superseded versions, nothing else."""
        return {rec["sha256"] for src in reg["sources"].values() for rec in src["versions"].values()
                if Lifecycle.retainable(rec)}

    @staticmethod
    def _refuse_overlap(src, rec):
        """A version that stays in the index (current or history) may not share a day with another one of the same source:
        a dated question could not tell which text applied. Only verified ranges can be compared."""
        mine = verified_window(rec)
        if mine is None:
            return
        for other in src["versions"].values():
            if other is rec or not (other["state"] == APPROVED or Lifecycle.retainable(other)):
                continue
            theirs = verified_window(other)
            if theirs is not None and mine[0] <= theirs[1] and theirs[0] <= mine[1]:
                raise LifecycleError(
                    f"version {rec['version']} (valid {mine[0]}-{mine[1]}) overlaps version {other['version']} "
                    f"(valid {theirs[0]}-{theirs[1]}): close the earlier version's validity first")

    @staticmethod
    def index_hashes(reg) -> set:
        """What the production collection must contain: the servable hashes, the retained historical versions, plus legacy
        documents that were found in the index at bootstrap without verified approval (quarantined: present, never served,
        until resolved)."""
        out = Lifecycle.servable_hashes(reg) | Lifecycle.historical_hashes(reg)
        for src in reg["sources"].values():
            for rec in src["versions"].values():
                if rec["state"] == PENDING and (rec.get("quarantine") or {}).get("in_index"):
                    out.add(rec["sha256"])
        return out

    expected_hashes = index_hashes

    def _live_hashes(self, client) -> set:
        names = {c.name for c in client.list_collections()}
        if self.collection not in names:
            return set()
        return {(m or {}).get("sha256") for m in client.get_collection(self.collection, embedding_function=None)
                .get(include=["metadatas"])["metadatas"]}

    def _stage(self, client, remove, add, expected, meta_updates=None):
        btx = self.btx
        meta_updates = meta_updates or {}   # {sha256: {key: value}} applied to kept rows (validity closed in the registry)
        names = {c.name for c in client.list_collections()}
        if btx.STAGING in names:
            client.delete_collection(btx.STAGING)
        live = client.get_collection(self.collection, embedding_function=None) if self.collection in names else None
        meta = dict(live.metadata or {}) if live is not None else {}
        meta.setdefault("rag_profile", btx.PROFILE.name)
        staging = client.create_collection(btx.STAGING, metadata=meta, embedding_function=None)
        kept = 0
        if live is not None:
            got = live.get(include=["documents", "metadatas", "embeddings"])
            rows = [(i, d, {**(m or {}), **meta_updates.get((m or {}).get("sha256"), {})}, [float(x) for x in e])
                    for i, d, m, e in zip(got["ids"], got["documents"], got["metadatas"], got["embeddings"])
                    if (m or {}).get("sha256") not in remove]
            for i in range(0, len(rows), BATCH):
                b = rows[i:i + BATCH]
                staging.add(ids=[r[0] for r in b], documents=[r[1] for r in b], metadatas=[r[2] for r in b],
                            embeddings=[r[3] for r in b])
            kept = len(rows)
        added = 0
        for a in add:
            for i in range(0, len(a["chunks"]), BATCH):
                b = list(zip(a["ids"][i:i + BATCH], a["chunks"][i:i + BATCH]))
                staging.upsert(ids=[x for x, _ in b], documents=[c.page_content for _, c in b],
                               metadatas=[c.metadata for _, c in b], embeddings=[a["vectors"][x] for x, _ in b])
            added += len(a["chunks"])
        self._verify(staging, expected, kept + added)

    def _verify(self, col, expected, count):
        got = col.get(include=["metadatas"])
        metas = got["metadatas"]
        if len(metas) != count or len(set(got["ids"])) != len(got["ids"]):
            raise LifecycleError(f"index holds {len(metas)} rows, expected {count}")
        if {(m or {}).get("sha256") for m in metas} != set(expected):
            raise LifecycleError("index would contain documents other than the approved active versions")
        for m in metas:
            if not self.btx.legal_approval.SHA256_RE.match(str((m or {}).get("sha256", ""))):
                raise LifecycleError("a row has no valid sha256")
            if (m.get("state") not in self.btx.tg_manifest.JURISDICTIONS or m.get("state") != m.get("jurisdiction")
                    or not isinstance(m.get("answer_eligible"), bool)):
                raise LifecycleError("a row is not a flagged Telangana or Central chunk")
            if index_validity.chunk_problems(m):
                raise LifecycleError("a row has malformed validity metadata")
        if (col.metadata or {}).get(self.btx.rp.PROFILE_METADATA_KEY) is None:
            raise LifecycleError("index does not record its rag_profile")

    def _swap(self, client, expected):
        btx = self.btx
        names = {c.name for c in client.list_collections()}
        had_live = self.collection in names
        if had_live:
            client.get_collection(self.collection, embedding_function=None).modify(name=btx.PREVIOUS)
        try:
            client.get_collection(btx.STAGING, embedding_function=None).modify(name=self.collection)
            self._verify(client.get_collection(self.collection, embedding_function=None), expected,
                         client.get_collection(self.collection, embedding_function=None).count())
        except Exception:
            if self.collection in {c.name for c in client.list_collections()}:
                client.delete_collection(self.collection)
            if had_live:
                client.get_collection(btx.PREVIOUS, embedding_function=None).modify(name=self.collection)
            raise
        if had_live:
            client.delete_collection(btx.PREVIOUS)  # only after the new collection passed its health check

    def _cleanup_staging(self, client):
        try:
            if self.btx.STAGING in {c.name for c in client.list_collections()}:
                client.delete_collection(self.btx.STAGING)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------------------------------------ recovery
    def _refuse_if_interrupted(self):
        if self.load().get("intent"):
            raise LifecycleError("an earlier operation was interrupted: run recover() first")

    def _recover_collections(self, client, reg):
        """Undo a crash between the two renames of a swap (the live collection is missing)."""
        btx = self.btx
        names = {c.name for c in client.list_collections()}
        if self.collection not in names and btx.PREVIOUS in names:
            client.get_collection(btx.PREVIOUS, embedding_function=None).modify(name=self.collection)
        self._cleanup_staging(client)

    def recover(self, by=None) -> dict:
        """Finish or undo an interrupted operation. Safe to call at any time; a clean registry is left untouched."""
        import chromadb
        with self._mutation("recover", by, audit_guard=False, require_operator=False):
            reg = self.load()
            intent = reg.get("intent")
            if not intent:   # a journal is written before any change to the index, so nothing to recover: do not open it
                return {"action": "none"}
            client = chromadb.PersistentClient(path=str(self.db_dir)) if self.db_dir is not None else None
            if client is not None:
                names = {c.name for c in client.list_collections()}
                if self.collection not in names and self.btx.PREVIOUS in names:
                    client.get_collection(self.btx.PREVIOUS, embedding_function=None).modify(name=self.collection)
                    names = {c.name for c in client.list_collections()}
                self._cleanup_staging(client)
                if self.btx.PREVIOUS in names and self.collection in names and intent:
                    live = self._live_hashes(client)
                    if live == set(intent["expected"]):
                        client.delete_collection(self.btx.PREVIOUS)
                    else:  # the new collection is not what the journal intended: go back to the previous one
                        client.delete_collection(self.collection)
                        client.get_collection(self.btx.PREVIOUS, embedding_function=None).modify(name=self.collection)
            if not intent:
                return {"action": "none"}
            live = self._live_hashes(client) if client is not None else set()
            if live == set(intent["expected"]) and intent.get("next"):
                nxt = intent["next"]
                nxt["intent"] = None
                self._save(nxt)
                return {"action": "committed", "op": intent["op"]}
            reg["intent"] = None
            self._save(reg)
            return {"action": "aborted", "op": intent["op"]}

    # ------------------------------------------------------------------------------------------------ legacy import
    def _read_index(self, embeddings=True) -> dict:
        """Read every row of the production collection WITHOUT opening the production directory: a temporary copy is read, and
        a digest of the production directory's files before and after proves nothing changed."""
        import chromadb
        if self.db_dir is None or not Path(self.db_dir).is_dir():
            raise LifecycleError("index directory not found")
        before = tree_digest(self.db_dir)
        tmp = Path(tempfile.mkdtemp(prefix="kyr-bootstrap-read-"))
        try:
            copy = tmp / "index"
            shutil.copytree(self.db_dir, copy)
            client = chromadb.PersistentClient(path=str(copy))
            if self.collection not in {c.name for c in client.list_collections()}:
                raise LifecycleError(f"collection {self.collection!r} not found in the index")
            col = client.get_collection(self.collection, embedding_function=None)
            got = col.get(include=["documents", "metadatas"] + (["embeddings"] if embeddings else []))
            vecs = got["embeddings"] if embeddings else [[] for _ in got["ids"]]
            rows = [{"id": i, "document": d, "metadata": m or {}, "embedding": [float(x) for x in e]}
                    for i, d, m, e in zip(got["ids"], got["documents"], got["metadatas"], vecs)]
            meta = dict(col.metadata or {})
            del client, col
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        after = tree_digest(self.db_dir)
        if before != after:
            raise LifecycleError("the index directory changed while it was being read")
        return {"rows": rows, "collection_metadata": meta, "tree_sha256": before}

    @staticmethod
    def _approval_evidence(approval_basis) -> dict:
        """The recorded basis on which documents are approved. It is a statement, not a credential: no signature or key is
        involved, and nothing here proves who made it. Without a basis nothing is approved."""
        if not isinstance(approval_basis, str) or not approval_basis.strip():
            return {"state": "absent", "errors": ["no approval basis given"], "basis": None}
        if len(approval_basis) > MAX_BASIS or any(ord(c) < 32 and c not in "\n\t" or ord(c) == 127 for c in approval_basis):
            return {"state": "invalid", "errors": ["the approval basis is too long or contains control characters"], "basis": None}
        return {"state": "verified", "errors": [], "basis": approval_basis.strip()}

    def plan_bootstrap(self, approval_basis=None, corpus_dir=None, source_status_file=None) -> dict:
        """DRY RUN. Maps every indexed document to its approval evidence and says what bootstrap would register. Changes
        nothing: not the registry, not the index (the production directory is read through a copy and digest-checked)."""
        from backend import legal_approval as la
        idx = self._read_index()
        rows = idx["rows"]
        approval = self._approval_evidence(approval_basis)
        registry = {}
        if source_status_file and Path(source_status_file).is_file():
            try:
                for e in json.loads(Path(source_status_file).read_text(encoding="utf-8"))["entries"]:
                    registry[e["sha256"]] = e
            except (OSError, ValueError, KeyError, TypeError):
                registry = None
        groups: dict[str, list] = {}
        for r in rows:
            sha = r["metadata"].get("sha256")
            groups.setdefault(sha if isinstance(sha, str) and la.SHA256_RE.match(sha) else "(none)", []).append(r)
        ids_by_sha = {sha: sorted({r["metadata"].get("manifest_id") or "" for r in rs} - {""}) for sha, rs in groups.items()}
        shas_by_id: dict[str, set] = {}
        for sha, ids in ids_by_sha.items():
            for i in ids:
                shas_by_id.setdefault(i, set()).add(sha)
        entries, ver_counter = [], {}
        for sha in sorted(groups, key=lambda k: (ids_by_sha.get(k, [""])[:1] or [""], k)):
            rs = groups[sha]
            m0 = rs[0]["metadata"]
            ids = ids_by_sha[sha]
            names = sorted({r["metadata"].get("source_file") or "" for r in rs} - {""})
            reasons = []
            if sha == "(none)":
                reasons.append("chunks have no valid sha256")
            if len(ids) != 1:
                reasons.append("ambiguous source id: " + (", ".join(ids) if ids else "no manifest_id"))
            elif len(shas_by_id[ids[0]]) > 1:
                reasons.append(f"ambiguous: {ids[0]!r} is indexed with {len(shas_by_id[ids[0]])} different contents")
            if len(names) != 1:
                reasons.append("ambiguous source file name: " + (", ".join(names) or "none"))
            if approval["state"] != "verified":
                reasons.append(f"no approval basis ({approval['state']}: {'; '.join(approval['errors'])[:160]})")
            reg_entry = (registry or {}).get(sha) if registry is not None else None
            if registry is None:
                reasons.append("source-status registry unreadable")
            elif source_status_file and sha != "(none)":
                if reg_entry is None:
                    reasons.append("hash unknown to the source-status registry")
                elif len(ids) == 1 and reg_entry.get("manifest_id") != ids[0]:
                    reasons.append("source-status registry maps this hash to a different manifest id")
            if corpus_dir and reg_entry and sha != "(none)":
                path = Path(corpus_dir) / reg_entry["file"]
                if not path.is_file():
                    reasons.append(f"source file not found in the corpus directory ({reg_entry['file']})")
                elif la.sha256_file(path) != sha:
                    reasons.append("hash mismatch: the corpus file does not hash to the indexed sha256")
            dates = {r["metadata"].get("effective_date") or "" for r in rs}
            sid = "unmapped-no-hash" if sha == "(none)" else ids[0] if len(ids) == 1 else f"unmapped-{sha[:12]}"
            ver_counter[sid] = ver_counter.get(sid, 0) + 1
            det = [chunk_id(Chunk(r["document"], r["metadata"])) for r in rs]
            entries.append({
                "source_id": sid, "version": ver_counter[sid], "sha256": sha, "file": names[0] if len(names) == 1 else None,
                "title": m0.get("title", ""), "chunks": len(rs), "chunk_ids": sorted(r["id"] for r in rs),
                "duplicate_chunks": len(det) - len(set(det)),
                "effective_date": dates.pop() or None if len(dates) == 1 else None,
                "status": "verified" if not reasons else "quarantined", "reasons": reasons,
                "target_state": APPROVED if not reasons else PENDING})
        plan = {
            "index": {"collection": self.collection, "rows": len(rows), "sources": len({e["source_id"] for e in entries}),
                      "hashes": len(groups), "tree_sha256": idx["tree_sha256"],
                      "unique_row_ids": len({r["id"] for r in rows}) == len(rows)},
            "approval": {"state": approval["state"], "errors": approval["errors"], "basis": approval["basis"]},
            "totals": {"verified": sum(e["status"] == "verified" for e in entries),
                       "quarantined": sum(e["status"] == "quarantined" for e in entries),
                       "chunks_verified": sum(e["chunks"] for e in entries if e["status"] == "verified"),
                       "chunks_quarantined": sum(e["chunks"] for e in entries if e["status"] == "quarantined"),
                       "missing_approval": sum(any("no approval basis" in r for r in e["reasons"]) for e in entries),
                       "hash_mismatch": sum(any("hash mismatch" in r for r in e["reasons"]) for e in entries),
                       "ambiguous": sum(any("ambiguous" in r for r in e["reasons"]) for e in entries)},
            "entries": entries,
        }
        plan["plan_sha256"] = _sha(plan["entries"], plan["approval"]["basis"])
        plan["_rows"] = rows  # stripped by plan_bootstrap callers that serialise
        return plan

    def bootstrap(self, by, approval_basis=None, corpus_dir=None, source_status_file=None,
                  note="", allow_quarantine=False, plan=None) -> dict:
        """Enrol the existing index. A document is approved when an approval basis is given and it passes every other check
        (unambiguous source id and file, known to the source-status registry, hash matching the corpus file when a corpus
        directory is given); everything else is registered pending+quarantined (in the index, never served). Idempotent: re-running with the same inputs
        changes nothing; re-running with newly available evidence upgrades quarantined documents. The index is not
        modified. The registry is written in one atomic step after the snapshots, so an interrupted run leaves no
        half-registry and can simply be run again."""
        with self._mutation("bootstrap", by):
            by = self._who(by)
            plan = plan or self.plan_bootstrap(approval_basis, corpus_dir, source_status_file)
            rows = plan["_rows"]
            by_sha: dict[str, list] = {}
            for r in rows:
                by_sha.setdefault(r["metadata"].get("sha256"), []).append(r)
            if plan["totals"]["quarantined"] and not allow_quarantine:
                raise LifecycleError(f"{plan['totals']['quarantined']} source(s) lack verified approval or are ambiguous: review "
                                     "the dry-run and re-run with allow_quarantine to register them as quarantined")
            reg = self.load() if self.registry_path.is_file() else {"schema_version": SCHEMA, "sources": {}, "events": [],
                                                                    "intent": None}
            if reg.get("intent"):
                raise LifecycleError("an interrupted lifecycle operation exists: run recover() first")
            embedder = self._embedder_id() if self.embeddings is not None else reg.get("embedder")
            if embedder:
                reg["embedder"] = embedder
            at, changed = self.clock(), {"registered": 0, "upgraded": 0, "unchanged": 0}
            evidence = {"approval_basis": plan["approval"]["basis"]}
            for e in plan["entries"]:
                if e["sha256"] == "(none)":   # rows without a valid file hash cannot be enrolled; they are never servable
                    changed["not_registrable"] = changed.get("not_registrable", 0) + e["chunks"]
                    continue
                src = reg["sources"].setdefault(e["source_id"], {"active_version": None, "versions": {}})
                existing = next((r for r in src["versions"].values() if r["sha256"] == e["sha256"]), None)
                verified = e["status"] == "verified"
                if existing is not None:
                    q = existing.get("quarantine") or {}
                    if verified and existing["state"] == PENDING and q.get("in_index"):
                        self._upgrade(src, existing, by, at, evidence, note)
                        self._event(reg, "bootstrap_upgrade", e["source_id"], existing["version"], by, note, prev_state=PENDING, new_state=APPROVED, sha256=e["sha256"], legal_evidence=evidence)
                        changed["upgraded"] += 1
                        self._snapshot_rows(e["sha256"], by_sha[e["sha256"]], embedder, with_embeddings=True)
                    else:
                        changed["unchanged"] += 1
                    continue
                number = max((int(v) for v in src["versions"]), default=0) + 1
                self._snapshot_rows(e["sha256"], by_sha[e["sha256"]], embedder, with_embeddings=verified)
                m0 = by_sha[e["sha256"]][0]["metadata"]
                rec = {"version": number, "sha256": e["sha256"], "file": e["file"] or "", "ingested_at": at,
                       "state": PENDING, "effective_date": e["effective_date"], "chunk_count": e["chunks"],
                       "supersedes": None, "superseded_by": None, "embedder": embedder if verified else None,
                       "metadata": {k: m0.get(k, "") for k in ("title", "document_type", "issuing_authority", "document_number",
                                                              "publication_date", "effective_date", "source_url",
                                                              "source_class", "verification_status")},
                       "history": [{"state": PENDING, "at": at, "by": by,
                                    "note": "bootstrap: found in the production index" + (f" - {note}" if note else "")}],
                       "provenance": {"origin": "bootstrap", "plan_sha256": plan["plan_sha256"], "index_tree_sha256":
                                      plan["index"]["tree_sha256"]}}
                src["versions"][str(number)] = rec
                if verified:
                    self._upgrade(src, rec, by, at, evidence, note)
                else:
                    rec["quarantine"] = {"in_index": True, "reasons": e["reasons"]}
                self._event(reg, "bootstrap", e["source_id"], number, by, note, prev_state=None, new_state=rec["state"], sha256=e["sha256"], status=e["status"],
                            reasons=e["reasons"])
                changed["registered"] += 1
            if changed["registered"] or changed["upgraded"]:   # a re-run that finds nothing new writes nothing
                reg["bootstrap"] = {"at": at, "by": by, "plan_sha256": plan["plan_sha256"], "evidence": evidence,
                                    "index_tree_sha256": plan["index"]["tree_sha256"], "result": changed}
                self._save(reg)
            return {"result": changed, "verified": plan["totals"]["verified"], "quarantined": plan["totals"]["quarantined"],
                    "plan_sha256": plan["plan_sha256"]}

    @staticmethod
    def _upgrade(src, rec, by, at, evidence, note):
        """Quarantined/new -> approved on the recorded approval basis."""
        rec["state"] = APPROVED
        rec.pop("quarantine", None)
        rec["history"].append({"state": APPROVED, "at": at, "by": by, "evidence": evidence,
                               "note": "bootstrap: approved on the recorded approval basis" + (f" - {note}" if note else "")})
        src["active_version"] = rec["version"]

    def _snapshot_rows(self, sha, rows, embedder, with_embeddings):
        path = self._snapshot_path(sha)
        if path.is_file():
            try:
                old = json.loads(path.read_text(encoding="utf-8"))
                if (not with_embeddings or all(c.get("embedding") for c in old.get("chunks", []))) and \
                        len(old.get("chunks", [])) == len(rows):
                    return  # idempotent: already complete
            except (OSError, ValueError):
                pass
        _atomic_write(path, json.dumps({
            "sha256": sha, "embedder": embedder if with_embeddings else None,
            "chunks": [{"id": r["id"], "text": r["document"], "metadata": r["metadata"],
                        "embedding": r["embedding"] if with_embeddings else None} for r in rows]}, ensure_ascii=False))

    # ------------------------------------------------------------------------------------------------ warnings
    def _load_status_registry(self, path=None):
        """(by_hash entries, error list) of the source-status registry, parsed with the registry's own strict parser."""
        from backend import source_status
        path = path or self.source_status_file
        if not path or not Path(path).is_file():
            return None, ["no source-status registry file"]
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            parsed = source_status.parse(data)     # strict validation by the registry's own parser (raises if invalid)
            raw = {e["sha256"]: e for e in data["entries"]}
            # the parser drops manifest_id and review; keep them for the identity and copied-entry checks
            return {h: dict(v, manifest_id=raw[h].get("manifest_id"), review=raw[h].get("review")) for h, v in parsed.items()}, []
        except (OSError, ValueError, source_status.SourceStatusError) as e:
            return None, [f"source-status registry invalid: {str(e)[:200]}"]

    def warning_coverage(self, source_status_file=None, reg=None) -> dict:
        """For every registered version: does the legal source-status registry hold an entry for its exact file hash, is that
        entry unambiguous, and could it have been inherited from an earlier version? Read-only. Never edits the registry
        and never copies an entry from one version to another: an amended version needs its own reviewed entry.
        Meaning of the server's behaviour: an indexed hash with no entry makes the registry invalid for the server gate (answers
        are blocked) and its warning reads 'status not recorded'; it is never silently omitted."""
        reg = reg or self.load()
        by_hash, errors = self._load_status_registry(source_status_file)
        out = {"registry_errors": errors, "versions": [], "orphan_registry_entries": []}
        known = set()
        for sid, src in sorted(reg["sources"].items()):
            for v, rec in sorted(src["versions"].items(), key=lambda kv: int(kv[0])):
                known.add(rec["sha256"])
                findings, entry = [], (by_hash or {}).get(rec["sha256"])
                pred = src["versions"].get(str(rec.get("supersedes"))) if rec.get("supersedes") is not None else None
                pred_entry = (by_hash or {}).get(pred["sha256"]) if pred else None
                if by_hash is None:
                    cov = "registry_unavailable"
                    findings.append("source-status registry unavailable: every source warns 'status not recorded'")
                elif entry is None:
                    cov = "missing"
                    findings.append("no registry entry for this exact file hash: the warning would read 'status not recorded' "
                                    "and the server's registry check fails until an entry is reviewed and added")
                else:
                    cov = "covered"
                    if entry.get("manifest_id") not in (None, sid):
                        cov = "ambiguous"
                        findings.append(f"registry maps this hash to manifest id {entry.get('manifest_id')!r}, not {sid!r}")
                    if rec.get("file") and entry.get("file") and Path(entry["file"]).name != Path(rec["file"]).name:
                        cov = "ambiguous"
                        findings.append("registry entry names a different file than this version")
                    if entry.get("status") == "verified_current":
                        findings.append("status verified_current only removes the warning when a signed approval binds the "
                                        "registry; lifecycle approval does not")
                if pred is not None and entry is None and pred_entry is not None:
                    findings.append(f"amendment: version {pred['version']} has status {pred_entry.get('status')!r} but its "
                                    "applicability to this version is unreviewed and is NOT inherited")
                if pred_entry is not None and entry is not None and all(
                        pred_entry.get(k) == entry.get(k) for k in ("status", "decision_refs", "related_instruments", "review")):
                    findings.append("entry is identical to the predecessor's: confirm it applies to the amended text")
                active = src.get("active_version") == rec["version"] and rec["state"] == APPROVED
                if rec["state"] in (SUPERSEDED, WITHDRAWN, REJECTED):
                    findings.append(f"{rec['state']}: not served, so no warning attaches to answers; the entry is kept for traceability")
                elif not active:
                    findings.append("not active/approved: not served")
                out["versions"].append({"source": sid, "version": rec["version"], "sha256": rec["sha256"], "state": rec["state"],
                                        "served": active, "coverage": cov, "findings": findings,
                                        "status": (entry or {}).get("status")})
        for sha, e in (by_hash or {}).items():
            if sha not in known:
                out["orphan_registry_entries"].append({"sha256": sha, "manifest_id": e.get("manifest_id"), "status": e.get("status")})
        return out

    def _coverage_gate(self, source_id, rec, accept_missing_status):
        """Before a version becomes servable: its warning metadata must be present and unambiguous (when a registry is
        configured). An explicit override is allowed and is recorded in the audit event."""
        if not self.source_status_file:
            return None
        cov = next(v for v in self.warning_coverage()["versions"] if v["source"] == source_id and v["version"] == rec["version"])
        result = {"coverage": cov["coverage"], "findings": cov["findings"], "override": False}
        if cov["coverage"] != "covered":
            if not accept_missing_status:
                raise LifecycleError(f"{source_id} v{rec['version']}: warning metadata is {cov['coverage']}: "
                                     + " ".join(cov["findings"]) + " Add a reviewed source-status entry for this exact hash, or "
                                     "pass accept_missing_status to proceed knowingly.")
            result["override"] = True
        return result

    def repair_audit_mirror(self, by, note="") -> dict:
        """Recreate a MISSING audit mirror from a registry whose hash chain verifies, and record that this was done. Refuses if the
        chain itself is broken or a mirror exists (a mirror that disagrees is evidence, not something to overwrite)."""
        with self._mutation("audit-repair-mirror", by, audit_guard=False):
            reg = self.load()
            if self.audit_path.exists():
                raise LifecycleError("an audit mirror exists: it is evidence and is never overwritten")
            problems = [p for p in audit_problems(reg, None)]
            if problems:
                raise LifecycleError("the registry's own audit chain is broken: " + "; ".join(problems))
            self._event(reg, "audit_mirror_rebuilt", None, None, by, note or "audit mirror recreated from the registry",
                        caveat="the mirror was missing, so the history before this event could not be cross-checked")
            self._save(reg)
            return {"events": len(reg["events"])}

    def adopt_audit_chain(self, by, note="") -> dict:
        """One-time, explicit: give a registry written before Stage 6C a hash chain. Only when NO event has chain fields (a
        mixture is treated as tampering). Existing events are kept verbatim and marked legacy; the history before this point was
        not tamper-evident and is recorded as such."""
        with self._mutation("audit-adopt", by, audit_guard=False):
            reg = self.load()
            if any(isinstance(e, dict) and "hash" in e for e in reg["events"]):
                raise LifecycleError("the audit history already has a hash chain (or a mixture): nothing to adopt")
            if self.audit_path.is_file() and self.audit_path.read_text(encoding="utf-8").strip():
                raise LifecycleError("an audit mirror exists for an unchained history: refusing to adopt")
            if reg.get("intent"):
                raise LifecycleError("an interrupted operation exists: run recover first")
            legacy, reg["events"] = reg["events"], []
            for e in legacy:
                ev = dict(e, seq=len(reg["events"]), previous_state=None, new_state=None, legacy=True,
                          identity_assurance=ASSURANCE, prev=reg["events"][-1]["hash"] if reg["events"] else GENESIS)
                ev["hash"] = _event_hash(ev)
                reg["events"].append(ev)
            self._event(reg, "audit_adopt", None, None, by, note or "hash chain adopted over the existing history",
                        legacy_events=len(legacy),
                        caveat="history before this event was not tamper-evident and its authenticity is not established")
            self._save(reg)
            return {"adopted_events": len(legacy), "total_events": len(reg["events"])}

    # ------------------------------------------------------------------------------------------------ inspection
    def verify(self) -> list[str]:
        """Consistency between registry and live collection. Empty list = consistent."""
        import chromadb
        reg = self.load()
        problems = [f"audit: {x}" for x in audit_problems(reg, self.audit_path)]
        if reg.get("intent"):
            problems.append("an interrupted operation is recorded (run recover)")
        for sid, src in reg["sources"].items():
            approved = [v for v, r in src["versions"].items() if r["state"] == APPROVED]
            if len(approved) > 1:
                problems.append(f"{sid}: more than one approved version")
            if (src["active_version"] is None) != (not approved) or (approved and str(src["active_version"]) != approved[0]):
                problems.append(f"{sid}: active_version does not match the approved version")
        if self.db_dir is not None:
            # Read-only by construction: the production directory is never opened (a copy is), and its files are
            # digest-checked before and after. Opening a Chroma directory rewrites its files, even to read it.
            try:
                rows = self._read_index(embeddings=False)["rows"]
            except LifecycleError as e:
                rows = None
                if self.expected_hashes(reg):
                    problems.append(f"index unreadable: {e}")
            if rows is not None:
                live = {}
                for r in rows:
                    live[r["metadata"].get("sha256")] = live.get(r["metadata"].get("sha256"), 0) + 1
                if set(live) != self.expected_hashes(reg):
                    problems.append("index documents differ from the approved active versions")
                if len({r["id"] for r in rows}) != len(rows):
                    problems.append("duplicate row ids in the index")
                for sid, src in reg["sources"].items():
                    for r in src["versions"].values():
                        if (r["state"] == APPROVED or (r.get("quarantine") or {}).get("in_index")) \
                                and live.get(r["sha256"]) != r["chunk_count"]:
                            problems.append(f"{sid} v{r['version']}: index has {live.get(r['sha256'], 0)} chunks, "
                                            f"expected {r['chunk_count']}")
        return problems

    def status(self) -> dict:
        reg = self.load()
        return {sid: {"active": s["active_version"], "versions": {v: r["state"] for v, r in s["versions"].items()}}
                for sid, s in reg["sources"].items()}


# ---------------------------------------------------------------------------------------------------- serving side
class ServeFilter:
    """What the running server asks: may a chunk with this file hash be served? With TG_LIFECYCLE_DIR unset it is disabled
    (today's behaviour). With it set it is FAIL-CLOSED in every uncertain state: a missing directory or registry, an
    unreadable or wrong-format registry, an interrupted operation, a broken or missing audit history, an unknown hash, a
    non-active version, a version whose chunk count in the index differs from the registry, and any unexpected error while
    checking all mean "not servable". A set-but-empty TG_LIFECYCLE_DIR is a misconfiguration and also fails closed; it never
    disables the filter. Re-reads the files only when they change."""

    EMPTY_ENV_PATH = Path("(TG_LIFECYCLE_DIR is set but empty)")

    def __init__(self, state_dir=None, misconfigured=False):
        self.path = (Path(state_dir) / "registry.json" if state_dir else
                     self.EMPTY_ENV_PATH / "registry.json" if misconfigured else None)
        self._stamp = None
        self._hashes, self._counts, self._digest = frozenset(), {}, None
        self._hist = frozenset()   # retained superseded versions: servable for a dated question only, never as current law
        self._state, self._problems, self._index_counts = "unchecked", [], None

    @classmethod
    def from_env(cls, environ=None):
        env = os.environ if environ is None else environ
        if "TG_LIFECYCLE_DIR" in env:
            value = env["TG_LIFECYCLE_DIR"]
            return cls(value) if value.strip() else cls(misconfigured=True)
        return cls(None)

    @property
    def enabled(self) -> bool:
        return self.path is not None

    @staticmethod
    def _stat(p):
        try:
            st = p.stat()
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def _fail(self, state, problems):
        self._hashes, self._counts, self._digest = frozenset(), {}, "unreadable"
        self._hist = frozenset()
        self._state, self._problems = state, list(problems)

    def _refresh(self):
        mirror = self.path.parent / "audit.jsonl"
        stamp = (self._stat(self.path), self._stat(mirror))
        if stamp == self._stamp and self._digest is not None:
            return
        self._stamp = stamp
        try:
            if stamp[0] is None:
                return self._fail("missing", ["lifecycle registry not found"])
            raw = self.path.read_bytes()
            reg = json.loads(raw.decode("utf-8"))
            if not isinstance(reg, dict) or reg.get("schema_version") != SCHEMA or not isinstance(reg.get("sources"), dict):
                return self._fail("unreadable", ["lifecycle registry has an unknown format"])
            if reg.get("intent"):
                return self._fail("interrupted", ["an interrupted lifecycle operation is recorded: run recover"])
            problems = audit_problems(reg, mirror)
            if problems:
                return self._fail("audit_failed", problems)
            hashes = frozenset(Lifecycle.servable_hashes(reg))
            hist = frozenset(Lifecycle.historical_hashes(reg)) - hashes
            counts = {}
            for src in reg["sources"].values():
                for rec in src["versions"].values():
                    if (rec["sha256"] in hashes and rec["state"] == APPROVED) or rec["sha256"] in hist:
                        counts[rec["sha256"]] = rec["chunk_count"]
            self._hashes, self._counts, self._hist = hashes, counts, hist
            self._digest = hashlib.sha256(raw + (mirror.read_bytes() if stamp[1] else b"")).hexdigest()[:32]
            self._state, self._problems = "ok", []
        except Exception as e:  # noqa: BLE001 - any surprise while checking means closed, never open
            self._fail("unreadable", [f"lifecycle registry could not be checked: {e.__class__.__name__}"])

    def reconcile(self, index_counts: dict):
        """Tell the filter how many chunks per file hash the running index actually holds (taken at startup). A version
        whose count differs from the registry's chunk_count is not servable: registry and index disagree."""
        self._index_counts = dict(index_counts)

    def _mismatched(self):
        if self._index_counts is None:
            return set()
        return {h for h, n in self._counts.items() if self._index_counts.get(h) != n}

    def servable(self, sha256) -> bool:
        if not self.enabled:
            return True
        try:
            self._refresh()
            return (isinstance(sha256, str) and sha256 in self._hashes and sha256 not in self._mismatched())
        except Exception:  # noqa: BLE001
            return False

    def servable_on(self, sha256, dated: bool) -> bool:
        """May a chunk with this file hash be used for a question? Undated: exactly servable() (the approved active version).
        Dated: also a retained historical version, whose own validity range then decides whether it covers the date. Disabled
        lifecycle behaves as servable() does (everything), and every uncertain state is closed, as for servable()."""
        if not dated or not self.enabled:
            return self.servable(sha256)
        try:
            self._refresh()
            return (isinstance(sha256, str) and (sha256 in self._hashes or sha256 in self._hist)
                    and sha256 not in self._mismatched())
        except Exception:  # noqa: BLE001
            return False

    def digest(self):
        if not self.enabled:
            return None
        try:
            self._refresh()
            return self._digest
        except Exception:  # noqa: BLE001
            return "unreadable"

    def health(self) -> dict:
        """State for readiness reporting: no document text, no hashes beyond short prefixes."""
        if not self.enabled:
            return {"enabled": False}
        try:
            self._refresh()
            bad = sorted(self._mismatched())
            servable = len(self._hashes) - len([h for h in bad if h in self._hashes])
            problems = list(self._problems) + [f"index and registry disagree on the chunk count of {h[:12]}" for h in bad]
            state = self._state if self._state != "ok" or not bad else "index_mismatch"
        except Exception:  # noqa: BLE001
            return {"enabled": True, "state": "unreadable", "problems": ["lifecycle state could not be checked"],
                    "servable_documents": 0, "ready": False}
        return {"enabled": True, "state": state, "problems": problems, "servable_documents": servable,
                "historical_documents": len(self._hist), "ready": state == "ok" and servable > 0}

    def ready(self) -> bool:
        return (not self.enabled) or self.health()["ready"]


# ---------------------------------------------------------------------------------------------------- command line
def main(argv=None, out=print, embeddings=None) -> int:
    ap = argparse.ArgumentParser(description="Document lifecycle for the Telangana index (operator tool, no HTTP).")
    ap.add_argument("--state-dir", default=os.environ.get("TG_LIFECYCLE_DIR"), required=not os.environ.get("TG_LIFECYCLE_DIR"))
    ap.add_argument("--db-dir", default=os.environ.get("TG_DB_DIR"))
    default_registry = os.environ.get("TG_SOURCE_STATUS_FILE") or (
        str(Path(__file__).resolve().parent.parent / "legal-status" / "source-status.json")
        if (Path(__file__).resolve().parent.parent / "legal-status" / "source-status.json").is_file() else None)
    ap.add_argument("--status-registry", default=default_registry,
                    help="legal source-status registry used to check warning metadata before approve/rollback")
    ap.add_argument("--lock-timeout", type=float, default=None, help="seconds to wait for the lifecycle lock (default 30)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ingest")
    p.add_argument("--manifest", required=True)
    p.add_argument("--corpus", required=True)
    p.add_argument("--id", help="ingest only this manifest id")
    p.add_argument("--chunk-flags", help="reviewed extraction flags (JSON, as for build_telangana_index); only flags for the "
                                         "ingested manifest id are applied, and a flag that matches no chunk is an error")
    for name in ("approve", "reject", "withdraw", "rollback"):
        p = sub.add_parser(name)
        p.add_argument("source")
        p.add_argument("version", type=int)
    for name in ("bootstrap", "bootstrap-dry-run"):
        p = sub.add_parser(name, help="enrol the existing index; bootstrap-dry-run changes nothing")
        p.add_argument("--approval-basis", help="the stated basis on which the documents are approved (recorded verbatim, "
                                                "unauthenticated); without it nothing is approved")
        p.add_argument("--corpus", help="source files directory: if given, every hash is checked against the file")
        p.add_argument("--source-status", help="source-status registry (legal-status/source-status.json)")
        p.add_argument("--report", help="write the full plan as JSON here")
    sub.choices["bootstrap"].add_argument("--allow-quarantine", action="store_true",
                                          help="register documents without verified approval as quarantined")
    for name in ("approve", "rollback"):
        sub.choices[name].add_argument("--accept-missing-status", action="store_true",
                                       help="proceed although the source-status entry is missing/ambiguous (recorded in the audit)")
    sub.add_parser("audit-adopt", help="one-time: add a tamper-evident hash chain to a pre-6C registry")
    sub.add_parser("audit-repair-mirror", help="recreate a missing audit mirror from a verified registry chain")
    for name in ("approve", "reject", "withdraw", "rollback", "ingest", "bootstrap", "audit-adopt", "audit-repair-mirror"):
        sub.choices[name].add_argument("--by", required=True,
                                       help="operator label for the audit trail (recorded as supplied; NOT authenticated)")
        sub.choices[name].add_argument("--note", default="", help="reason, recorded in the audit trail")
    p = sub.add_parser("recover")
    p.add_argument("--by", default=None)
    for name in ("status", "verify", "audit-verify", "warnings"):
        sub.add_parser(name)
    a = ap.parse_args(argv)
    from backend import tg_manifest
    lc = Lifecycle(a.state_dir, a.db_dir, embeddings=embeddings, lock_timeout=a.lock_timeout,
                   source_status_file=a.status_registry)
    if embeddings is None and a.cmd in ("approve", "rollback", "bootstrap"):
        from langchain_ollama import OllamaEmbeddings  # constructing the client makes no network call
        from backend import rag_profiles as rp
        lc.embeddings = rp.ProfileEmbeddings(OllamaEmbeddings(model="nomic-embed-text"), lc.btx.PROFILE)
    try:
        if a.cmd == "ingest":
            if a.chunk_flags:
                flags = lc.btx.load_chunk_flags(a.chunk_flags)

                def flagged_chunker(entry, corpus_dir, _flags=flags):
                    chunks = Lifecycle._default_chunker(entry, corpus_dir)
                    problems = lc.btx.apply_chunk_flags(chunks, [f for f in _flags if f["match"]["manifest_id"] == entry.id])
                    if problems:
                        raise LifecycleError("; ".join(problems))
                    return chunks
                lc.chunker = flagged_chunker
            for e in tg_manifest.load_manifest(a.manifest):
                if not a.id or e.id == a.id:
                    out(json.dumps(lc.ingest(e, a.corpus, a.by, a.note)))
        elif a.cmd in ("approve", "rollback"):
            out(json.dumps(getattr(lc, a.cmd)(a.source, a.version, a.by, a.note,
                                              accept_missing_status=a.accept_missing_status)))
        elif a.cmd in ("reject", "withdraw"):
            out(json.dumps(getattr(lc, a.cmd)(a.source, a.version, a.by, a.note)))
        elif a.cmd == "audit-adopt":
            out(json.dumps(lc.adopt_audit_chain(a.by, a.note)))
        elif a.cmd == "audit-repair-mirror":
            out(json.dumps(lc.repair_audit_mirror(a.by, a.note)))
        elif a.cmd == "audit-verify":
            problems = lc.audit_check()
            out("audit history intact" if not problems else "\n".join(problems))
            return 1 if problems else 0
        elif a.cmd == "warnings":
            out(json.dumps(lc.warning_coverage(a.status_registry), indent=1))
        elif a.cmd in ("bootstrap", "bootstrap-dry-run"):
            args = (a.approval_basis, a.corpus, a.source_status)
            plan = lc.plan_bootstrap(*args)
            serial = {k: v for k, v in plan.items() if k != "_rows"}
            if a.report:
                _atomic_write(Path(a.report), json.dumps(serial, indent=1, ensure_ascii=False))
            summary = {k: serial[k] for k in ("index", "approval", "totals", "plan_sha256")}
            if a.cmd == "bootstrap-dry-run":
                out(json.dumps(summary, indent=1))
            else:
                out(json.dumps(lc.bootstrap(a.by, *args, note=a.note, allow_quarantine=a.allow_quarantine, plan=plan)))
        elif a.cmd == "status":
            out(json.dumps(lc.status(), indent=1))
        elif a.cmd == "recover":
            out(json.dumps(lc.recover(a.by)))
        elif a.cmd == "verify":
            problems = lc.verify()
            out("consistent" if not problems else "\n".join(problems))
            return 1 if problems else 0
    except (LifecycleError, tg_manifest.ManifestError) as e:
        out(f"FAILED: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
