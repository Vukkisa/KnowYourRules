"""Evidence manifest for the provision validity decision records (Step 3 review M1).

NOT WIRED INTO ANYTHING. No runtime module imports this file; only ``ledger_acceptance`` (itself unwired) calls it.

The manifest is the list of evidence files an approved decision may cite: relative path, SHA-256 and size of each. Its own
SHA-256 is bound by the signed source-status registry (``validity_evidence_manifest_sha256``), which the approval record's
signature covers, so changing the manifest, or any file it lists, breaks the signed chain. Nothing here is a new signing
scheme: the only trust anchor is still the existing offline approval-authority key, and this module does NOT authenticate any
reviewer (it proves only that listed files have the bytes the authority attested).

Canonical form (the stored file must be byte-for-byte this, so one manifest has exactly one hash)::

    {"files":[{"path":"evidence/a.txt","sha256":"<64 lowercase hex>","size":123}],"jurisdiction":"Telangana","schema_version":1}

* UTF-8 JSON, keys sorted, separators ``,`` and ``:``, no whitespace, no trailing newline, ASCII only (non-ASCII is escaped),
  integers only (no floats, ``NaN`` or ``Infinity``), no duplicate keys.
* ``files`` is sorted by path, paths are unique (also case-insensitively), relative POSIX, ASCII, with no empty, ``.`` or
  ``..`` part, no backslash, colon, NUL or control character, no leading slash.
* ``size`` is a non-negative integer (not a boolean); ``sha256`` is 64 lowercase hex characters.

``verify_files`` opens every named file through a directory descriptor with ``O_NOFOLLOW`` on every component, so a symbolic
link anywhere below the evidence directory is refused (not followed), and there is no gap between a containment check and
the open. The file must be a regular file whose size and SHA-256 equal the manifest entry, hashed once from one read.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from typing import Optional

from backend import source_status as _ss

__all__ = ["ManifestError", "Manifest", "SCHEMA_VERSION", "MAX_MANIFEST_BYTES", "MAX_FILES", "MAX_FILE_BYTES", "canonical_bytes",
           "parse", "read_regular_file", "safe_relative", "verify_files"]

SCHEMA_VERSION = 1
MAX_MANIFEST_BYTES = 4 << 20
MAX_FILES = 4096
MAX_FILE_BYTES = 256 << 20
_MAX_PATH = 1024
_MAX_PART = 255
_TOP_KEYS = frozenset({"schema_version", "jurisdiction", "files"})
_FILE_KEYS = frozenset({"path", "sha256", "size"})
_PART_RE = re.compile(r"[A-Za-z0-9._ +()@=,~-]+")          # ASCII only: no normalisation or look-alike ambiguity


class ManifestError(ValueError):
    """The manifest is not acceptable. The message names the first problem."""


@dataclass(frozen=True)
class Manifest:
    jurisdiction: str
    files: tuple                       # ((path, sha256, size), ...) in canonical (sorted) order

    def entry(self, path) -> Optional[tuple]:
        for p, h, n in self.files:
            if p == path:
                return (p, h, n)
        return None


def canonical_bytes(obj) -> bytes:
    """The one serialisation a manifest may be stored in."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def safe_relative(name) -> bool:
    """A relative POSIX file name made only of plain ASCII parts: no traversal, absolute path, backslash, colon or control."""
    if not isinstance(name, str) or not name or len(name) > _MAX_PATH:
        return False
    parts = name.split("/")
    return all(0 < len(p) <= _MAX_PART and p not in (".", "..") and _PART_RE.fullmatch(p) is not None
               and not p.endswith((" ", ".")) and not p.startswith(" ") for p in parts)


def _reject_duplicates(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ManifestError(f"duplicate JSON key {k!r}")
        out[k] = v
    return out


def _no_constant(name):
    raise ManifestError(f"{name} is not allowed")


def _no_float(text):
    raise ManifestError("floating-point numbers are not allowed")


def parse(raw) -> Manifest:
    """Parse and strictly validate manifest bytes. Raises ``ManifestError``; never returns a partly valid manifest."""
    if not isinstance(raw, (bytes, bytearray)):
        raise ManifestError("the manifest must be bytes")
    raw = bytes(raw)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ManifestError("the manifest is too large")
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicates, parse_float=_no_float,
                          parse_constant=_no_constant)
    except (UnicodeDecodeError, RecursionError) as exc:
        raise ManifestError(f"the manifest is not valid UTF-8 JSON ({exc.__class__.__name__})") from None
    except ManifestError:
        raise
    except ValueError as exc:
        raise ManifestError(f"the manifest is not valid JSON ({exc.__class__.__name__})") from None
    if not isinstance(data, dict) or set(data) != _TOP_KEYS:
        raise ManifestError(f"the manifest must be an object with exactly {sorted(_TOP_KEYS)}")
    sv = data["schema_version"]
    if isinstance(sv, bool) or not isinstance(sv, int) or sv != SCHEMA_VERSION:
        raise ManifestError(f"schema_version must be {SCHEMA_VERSION}")
    jur = data["jurisdiction"]
    if not isinstance(jur, str) or not jur.strip():
        raise ManifestError("jurisdiction must be a non-empty string")
    files = data["files"]
    if not isinstance(files, list) or len(files) > MAX_FILES:
        raise ManifestError(f"files must be a list of at most {MAX_FILES} entries")
    entries, seen, folded, last = [], set(), set(), None
    for i, e in enumerate(files):
        where = f"files[{i}]"
        if not isinstance(e, dict) or set(e) != _FILE_KEYS:
            raise ManifestError(f"{where} must have exactly {sorted(_FILE_KEYS)}")
        path, sha, size = e["path"], e["sha256"], e["size"]
        if not safe_relative(path):
            raise ManifestError(f"{where}.path is not a safe relative file name")
        if not isinstance(sha, str) or _ss.SHA256_RE.fullmatch(sha) is None:
            raise ManifestError(f"{where}.sha256 must be 64 lowercase hex characters")
        if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= MAX_FILE_BYTES:
            raise ManifestError(f"{where}.size must be an integer from 0 to {MAX_FILE_BYTES}")
        if path in seen or path.casefold() in folded:
            raise ManifestError(f"{where}.path repeats an earlier path (case-insensitively)")
        if last is not None and path < last:
            raise ManifestError(f"{where}.path is out of order: files must be sorted by path")
        seen.add(path)
        folded.add(path.casefold())
        last = path
        entries.append((path, sha, size))
    if raw != canonical_bytes(data):
        raise ManifestError("the manifest is not in canonical form (sorted keys, no whitespace, no trailing newline, ASCII)")
    return Manifest(jur, tuple(entries))


def read_regular_file(path, limit: int) -> bytes:
    """Read one regular file, at most ``limit`` bytes, without blocking on a FIFO or device. Raises ``OSError`` for anything
    that is not a regular file and ``ValueError`` for one that is too large."""
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0))
    with os.fdopen(fd, "rb") as fh:
        if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
            raise OSError("not a regular file")
        data = fh.read(limit + 1)
    if len(data) > limit:
        raise ValueError("file is too large")
    return data


def _open_no_follow(root_fd: int, name: str) -> int:
    """Open `name` below the directory `root_fd`, refusing a symbolic link in any component. Returns a descriptor."""
    parts = name.split("/")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
    cur = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            nxt = os.open(part, flags | os.O_DIRECTORY, dir_fd=cur)
            os.close(cur)
            cur = nxt
        return os.open(parts[-1], flags | getattr(os, "O_NONBLOCK", 0), dir_fd=cur)
    finally:
        os.close(cur)


def verify_files(manifest: Manifest, root: str, names) -> tuple:
    """Check every cited file against the manifest. Returns ``(problems, held)``.

    ``held`` maps a name to its SHA-256 only for a file that is listed in the manifest, is a regular file reached without
    following any link, has exactly the listed size and hashes to exactly the listed SHA-256 (read once, streamed, never more
    than size + 1 bytes). Every other cited name gets a problem string and is absent from ``held``."""
    problems: list = []
    held: dict = {}
    if os.open not in os.supports_dir_fd or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        return ["evidence files cannot be verified safely on this platform"], held
    try:
        root_fd = os.open(root, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | os.O_DIRECTORY)
    except (OSError, ValueError, TypeError):
        return ["the evidence directory cannot be opened"], held
    try:
        for name in sorted({n for n in names if isinstance(n, str)}):
            entry = manifest.entry(name) if safe_relative(name) else None
            if entry is None:
                problems.append(f"{name!r} is not in the signed evidence manifest")
                continue
            _, want_sha, want_size = entry
            try:
                fd = _open_no_follow(root_fd, name)
                with os.fdopen(fd, "rb") as fh:
                    st = os.fstat(fh.fileno())
                    if not stat.S_ISREG(st.st_mode):
                        problems.append(f"{name!r} is not a regular file")
                        continue
                    if st.st_size != want_size:
                        problems.append(f"{name!r} has a different size from the manifest")
                        continue
                    h, total = hashlib.sha256(), 0
                    while True:
                        block = fh.read(min(1 << 20, want_size + 1 - total))
                        if not block:
                            break
                        total += len(block)
                        h.update(block)
                        if total > want_size:
                            break
            except (OSError, ValueError):
                problems.append(f"{name!r} cannot be opened below the evidence directory (missing, a link, or unreadable)")
                continue
            if total != want_size:
                problems.append(f"{name!r} changed size while it was read")
            elif h.hexdigest() != want_sha:
                problems.append(f"{name!r} does not match the manifest SHA-256")
            else:
                held[name] = want_sha
    finally:
        os.close(root_fd)
    return problems, held
