"""
Telangana source manifest: one entry per source file, describing what it is and where it came from.

Unknown metadata is recorded as null - never guessed. The manifest describes documents; it does NOT
approve them (approval comes only from a signed record, see backend/legal_approval.py).

Format (schema_version 1):
{
  "schema_version": 1,
  "jurisdiction": "Telangana",
  "documents": [{
    "id": "tmvr-1989-chap-1",               # unique, [a-z0-9._-]
    "title": "...",                          # as printed on the document
    "document_type": "Act" | "Rules" | "Regulations" | "G.O." | "Notification" | "Order",
    "issuing_authority": "..." | null,
    "document_number": "..." | null,         # e.g. "G.O.Ms.No. 53"
    "publication_date": "YYYY-MM-DD" | null,
    "effective_date": "YYYY-MM-DD" | null,
    "source_url": "https://..." | null,      # where the file was obtained
    "file": "relative/path/in/corpus",       # location inside the corpus directory
    "jurisdiction": "Telangana",
    "format": "pdf" | "html",
    "source_class": "official" | "unverified_snapshot" | "draft",
    "verification_status": "unverified" | "metadata_checked",
    "sha256": "<64 lowercase hex>",
    "notes": "..." | null,
    "valid_from": 20190901 | null,           # OPTIONAL KEYS (omit = unknown): integer YYYYMMDD, first day this text applies
    "valid_to": 20260814 | 99991231 | null,  #   last day it applies (inclusive); 99991231 = verified as continuing in force
    "validity_status": "unknown" | "verified_continuing" | "verified_closed",
    "validity_basis": "..." | null           #   the legal evidence the dates rest on (required whenever dates are set)
  }]
}

Validity (valid_from / valid_to) is separate from effective_date and publication_date, which stay as printed. It is set only
from verified legal evidence, never derived from another date and never guessed:
  unknown              no dates; the source is flagged as having unverified validity (the default when the keys are omitted)
  verified_continuing  valid_from set, valid_to = 99991231 (the ONLY use of 99991231)
  verified_closed      valid_from and valid_to set, valid_to before 99991231 (a superseded or expired text)

source_class:
  official             - a file obtained from the issuing authority's own publication (gazette, GOIR, department)
  unverified_snapshot  - a copy (e.g. a saved web page) whose currency and completeness are not established
  draft                - a draft or proposed instrument; never indexed
"""

import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path

from backend.legal_approval import SHA256_RE, sha256_file
from backend.offence_date import OPEN_ENDED, is_yyyymmdd

JURISDICTION = "Telangana"
# The assistant's own jurisdiction is Telangana. A separate, Central-only manifest may be served beside it: every manifest is
# single-jurisdiction (mixed manifests are rejected), and each chunk keeps the jurisdiction of its own document.
CENTRAL = "Central"
JURISDICTIONS = (JURISDICTION, CENTRAL)
DOCUMENT_TYPES = {"Act", "Rules", "Regulations", "G.O.", "Notification", "Order"}
FORMATS = {"pdf", "html"}
SOURCE_CLASSES = {"official", "unverified_snapshot", "draft"}
VERIFICATION_STATUSES = {"unverified", "metadata_checked"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
REQUIRED = ("id", "title", "document_type", "file", "jurisdiction", "format", "source_class",
            "verification_status", "sha256")
OPTIONAL = ("issuing_authority", "document_number", "publication_date", "effective_date", "source_url", "notes")
BASE_KEYS = set(REQUIRED) | set(OPTIONAL)
VALIDITY_KEYS = ("valid_from", "valid_to", "validity_status", "validity_basis")  # may be omitted: omitted = unknown
ENTRY_KEYS = BASE_KEYS | set(VALIDITY_KEYS)
UNKNOWN, CONTINUING, CLOSED = "unknown", "verified_continuing", "verified_closed"
VALIDITY_STATUSES = {UNKNOWN, CONTINUING, CLOSED}


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class ManifestEntry:
    id: str
    title: str
    document_type: str
    issuing_authority: str | None
    document_number: str | None
    publication_date: str | None
    effective_date: str | None
    source_url: str | None
    file: str
    jurisdiction: str
    format: str
    source_class: str
    verification_status: str
    sha256: str
    notes: str | None
    valid_from: int | None = None
    valid_to: int | None = None
    validity_status: str = UNKNOWN
    validity_basis: str | None = None


def validity_metadata(entry) -> dict:
    """Chunk metadata for an entry's validity. Always states the status; dates only when verified. Chroma cannot store None,
    so 'unknown' is encoded as the two date keys being absent, which the router reads as unversioned."""
    status = getattr(entry, "validity_status", UNKNOWN)
    start, end = getattr(entry, "valid_from", None), getattr(entry, "valid_to", None)
    if status == UNKNOWN or start is None or end is None:
        return {"validity_status": UNKNOWN}
    return {"validity_status": status, "valid_from": start, "valid_to": end}


def validity_problems(start, end, status, basis, where="entry") -> list[str]:
    """Why a validity triple is unusable. Pure; shared by the manifest parser, the lifecycle and the index checks."""
    if not isinstance(status, str) or status not in VALIDITY_STATUSES:
        return [f"{where}.validity_status must be one of {sorted(VALIDITY_STATUSES)}"]
    if status == UNKNOWN:
        return ([f"{where}: validity dates are set but validity_status is 'unknown' (dates need verified evidence)"]
                if start is not None or end is not None else [])
    errors = []
    for name, v in (("valid_from", start), ("valid_to", end)):
        if not is_yyyymmdd(v):
            errors.append(f"{where}.{name} must be an integer YYYYMMDD calendar date")
    if errors:
        return errors
    if start == OPEN_ENDED:
        errors.append(f"{where}.valid_from cannot be {OPEN_ENDED}")
    if start > end:
        errors.append(f"{where}.valid_from is after valid_to")
    if status == CONTINUING and end != OPEN_ENDED:
        errors.append(f"{where}: verified_continuing needs valid_to = {OPEN_ENDED}")
    if status == CLOSED and end == OPEN_ENDED:
        errors.append(f"{where}: {OPEN_ENDED} is only for verified_continuing; a closed text needs a real end date")
    if not isinstance(basis, str) or not basis.strip():
        errors.append(f"{where}.validity_basis is required: name the legal evidence the dates rest on")
    return errors


def unverified_validity(entries) -> list[str]:
    """Ids of the sources whose validity is not verified (flagged, never defaulted to 'in force')."""
    return [e.id for e in entries if e.validity_status == UNKNOWN]


def _date_or_none(value, where, errors):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        errors.append(f"{where} must be YYYY-MM-DD or null")
        return None
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        errors.append(f"{where} is not a real date")
    return value


def parse_manifest(data) -> list[ManifestEntry]:
    """Strictly validate a decoded manifest. Raises ManifestError listing every problem."""
    if not isinstance(data, dict) or set(data) != {"schema_version", "jurisdiction", "documents"}:
        raise ManifestError("manifest must be {schema_version, jurisdiction, documents}")
    errors = []
    if data["schema_version"] != 1 or isinstance(data["schema_version"], bool):
        errors.append("schema_version must be 1")
    if data["jurisdiction"] not in JURISDICTIONS:
        errors.append(f"manifest jurisdiction must be one of {list(JURISDICTIONS)}")
    docs = data["documents"]
    if not isinstance(docs, list) or not docs:
        raise ManifestError("; ".join(errors + ["documents must be a non-empty list"]))
    entries, ids, files, hashes = [], set(), set(), set()
    for i, d in enumerate(docs):
        where = f"documents[{i}]"
        if not isinstance(d, dict) or not BASE_KEYS <= set(d) <= ENTRY_KEYS:
            errors.append(f"{where} must have exactly the fields {sorted(BASE_KEYS)} (the validity fields "
                          f"{list(VALIDITY_KEYS)} may be added, nothing else)")
            continue
        bad = [k for k in REQUIRED if not isinstance(d[k], str) or not d[k].strip()]
        bad += [k for k in OPTIONAL if d[k] is not None and (not isinstance(d[k], str) or not d[k].strip())]
        if bad:
            errors.append(f"{where} has empty or non-text fields {bad} (use null for unknown optional fields)")
            continue
        if not ID_RE.match(d["id"]):
            errors.append(f"{where}.id is invalid")
        if d["document_type"] not in DOCUMENT_TYPES:
            errors.append(f"{where}.document_type must be one of {sorted(DOCUMENT_TYPES)}")
        if d["jurisdiction"] != data["jurisdiction"]:
            errors.append(f"{where} has jurisdiction {d['jurisdiction']!r} (mixed jurisdictions are not allowed)")
        if d["format"] not in FORMATS:
            errors.append(f"{where}.format must be one of {sorted(FORMATS)}")
        elif Path(d["file"]).suffix.lower() not in ({".pdf"} if d["format"] == "pdf" else {".html", ".htm"}):
            errors.append(f"{where}.file extension does not match format {d['format']!r}")
        if d["source_class"] not in SOURCE_CLASSES:
            errors.append(f"{where}.source_class must be one of {sorted(SOURCE_CLASSES)}")
        if d["verification_status"] not in VERIFICATION_STATUSES:
            errors.append(f"{where}.verification_status must be one of {sorted(VERIFICATION_STATUSES)}")
        if not SHA256_RE.match(d["sha256"]):
            errors.append(f"{where}.sha256 must be 64 lowercase hex characters")
        if d["source_url"] is not None and not re.match(r"^https?://", d["source_url"]):
            errors.append(f"{where}.source_url must be an http(s) URL or null")
        if Path(d["file"]).is_absolute() or ".." in Path(d["file"]).parts:
            errors.append(f"{where}.file must be a relative path inside the corpus")
        _date_or_none(d["publication_date"], f"{where}.publication_date", errors)
        _date_or_none(d["effective_date"], f"{where}.effective_date", errors)
        errors += validity_problems(d.get("valid_from"), d.get("valid_to"), d.get("validity_status", UNKNOWN),
                                    d.get("validity_basis"), where)
        for value, seen, what in ((d["id"], ids, "id"), (d["file"], files, "file"), (d["sha256"], hashes, "sha256")):
            if value in seen:
                errors.append(f"{where} repeats {what} {value!r}" if what != "sha256"
                              else f"{where} is a duplicate of another document (same sha256)")
            seen.add(value)
        entries.append(ManifestEntry(**{k: d[k] for k in BASE_KEYS},
                                     **{k: d[k] for k in VALIDITY_KEYS if k in d}))
    names = {}
    for e in entries:
        names.setdefault(Path(e.file).name, set()).add(e.sha256)
    for name, hs in sorted(names.items()):
        if len(hs) > 1:
            errors.append(f"file name {name!r} appears with {len(hs)} different contents")
    if errors:
        raise ManifestError("; ".join(errors))
    return entries


def load_manifest(path) -> list[ManifestEntry]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as e:
        raise ManifestError(f"cannot read manifest: {e.__class__.__name__}") from e
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ManifestError("manifest is not valid JSON") from e
    return parse_manifest(data)


def file_errors(entries, corpus_dir) -> list[str]:
    """Each manifest file must exist inside corpus_dir and hash to its recorded sha256."""
    errors = []
    root = Path(corpus_dir).resolve()
    for e in entries:
        path = (root / e.file).resolve()
        if root not in path.parents:
            errors.append(f"{e.id}: file is outside the corpus directory")
        elif not path.is_file():
            errors.append(f"{e.id}: file not found ({e.file})")
        elif sha256_file(path) != e.sha256:
            errors.append(f"{e.id}: sha256 does not match the file ({e.file})")
    return errors
