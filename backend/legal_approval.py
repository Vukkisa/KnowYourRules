"""
Legal approval record for the Telangana knowledge base, and its integrity checks.

The record is a JSON file written by hand from the signed approval block in
docs/legal-sources/telangana-traffic/LEGAL-REVIEW-HANDOFF.md section 5. This module never creates one.
Anything malformed, incomplete or inconsistent with the corpus / index is rejected, and the server then
treats the knowledge base as NOT approved (fail closed).

Record format (schema_version 1):
{
  "schema_version": 1,
  "jurisdiction": "Telangana",
  "reviewer": {"name": "...", "designation": "..."},
  "approval_date": "YYYY-MM-DD",
  "decision": "approved" | "approved_with_conditions",
  "conditions": ["..." | {"text": "...", "resolved": bool, "resolution": "..."}],
                                              # required for approved_with_conditions; any unresolved one
                                              # keeps the approval INACTIVE
  "corpus_version": "...",
  "general_answers_approved": true,
  "penalty_answers_approved": false,          # separate, explicit; needs general_answers_approved
  "documents": [{"file": "...", "sha256": "<64 hex>", "title": "...", "instrument": "..."}]
}

The record must carry a detached Ed25519 signature (<record>.sig) from a key in the trusted-keys file;
see docs/approval-trust-model.md. This module only VERIFIES - signing lives in scripts/sign_approval_record.py.
"""

import base64
import binascii
import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

SCHEMA_VERSION = 1
JURISDICTION = "Telangana"
DECISIONS = {"approved", "approved_with_conditions"}
INSTRUMENTS = {"Act", "Rules", "Regulations", "G.O.", "Notification", "Order"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
# Values that are obviously not a real reviewer entry (template blanks, examples).
PLACEHOLDER_RE = re.compile(r"^_+$|\b(?:tbd|todo|placeholder|example|sample|test|dummy|n/?a|xxx+)\b", re.IGNORECASE)
TOP_LEVEL_KEYS = {
    "schema_version", "jurisdiction", "reviewer", "approval_date", "decision", "conditions", "corpus_version",
    "general_answers_approved", "penalty_answers_approved", "documents",
}


KEY_STATUSES = {"active", "retired", "revoked"}
KEY_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
# Passed as trusted_keys ONLY by isolated unit tests of the record parser/validators. The server never does.
UNSIGNED_TEST_ONLY = object()


class ApprovalError(ValueError):
    """The approval record is malformed; message lists every problem found."""


@dataclass(frozen=True)
class ApprovedDocument:
    file: str
    sha256: str
    title: str
    instrument: str


@dataclass(frozen=True)
class ApprovalRecord:
    jurisdiction: str
    reviewer_name: str
    reviewer_designation: str
    approval_date: dt.date
    decision: str
    conditions: tuple               # condition texts, in order
    unresolved_conditions: int      # > 0 means the approval is not active
    corpus_version: str
    general_answers_approved: bool
    penalty_answers_approved: bool
    documents: tuple

    @property
    def hashes(self) -> set:
        return {d.sha256 for d in self.documents}

    def document(self, sha256: str):
        return next((d for d in self.documents if d.sha256 == sha256), None)


@dataclass
class ApprovalStatus:
    """Outcome of loading and validating the record. Only state == "valid" approves anything."""
    state: str                      # "absent" | "invalid" | "valid"
    errors: list = field(default_factory=list)
    record: ApprovalRecord | None = None

    @property
    def general_answers(self) -> bool:
        return self.state == "valid" and self.record.general_answers_approved

    @property
    def penalty_answers(self) -> bool:
        return self.general_answers and self.record.penalty_answers_approved


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _text(value) -> bool:
    return isinstance(value, str) and value.strip() != ""


def parse_record(data, today: dt.date | None = None) -> ApprovalRecord:
    """Validate a decoded JSON object strictly; raise ApprovalError listing every problem."""
    today = today or dt.date.today()
    errors = []
    if not isinstance(data, dict):
        raise ApprovalError("approval record must be a JSON object")
    missing = TOP_LEVEL_KEYS - data.keys()
    unknown = data.keys() - TOP_LEVEL_KEYS
    if missing:
        errors.append(f"missing fields: {sorted(missing)}")
    if unknown:
        errors.append(f"unknown fields: {sorted(unknown)}")
    if errors:
        raise ApprovalError("; ".join(errors))

    if data["schema_version"] != SCHEMA_VERSION or isinstance(data["schema_version"], bool):
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if data["jurisdiction"] != JURISDICTION:
        errors.append(f"jurisdiction must be {JURISDICTION!r}")

    reviewer = data["reviewer"]
    if not isinstance(reviewer, dict) or set(reviewer) != {"name", "designation"}:
        errors.append("reviewer must be an object with exactly 'name' and 'designation'")
        reviewer = {}
    for key in ("name", "designation"):
        value = reviewer.get(key)
        if not _text(value):
            errors.append(f"reviewer.{key} is missing or empty")
        elif PLACEHOLDER_RE.search(value):
            errors.append(f"reviewer.{key} looks like a placeholder")

    approval_date = None
    if not isinstance(data["approval_date"], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["approval_date"]):
        errors.append("approval_date must be YYYY-MM-DD")
    else:
        try:
            approval_date = dt.date.fromisoformat(data["approval_date"])
        except ValueError:
            errors.append("approval_date is not a real date")
        else:
            if approval_date > today:
                errors.append("approval_date is in the future")

    if data["decision"] not in DECISIONS:
        errors.append(f"decision must be one of {sorted(DECISIONS)}")
    conditions, unresolved = [], 0
    raw_conditions = data["conditions"]
    if not isinstance(raw_conditions, list):
        errors.append("conditions must be a list")
        raw_conditions = []
    for i, c in enumerate(raw_conditions):
        if _text(c):
            conditions.append(c.strip())
            unresolved += 1  # a bare string has no recorded resolution
        elif isinstance(c, dict) and set(c) == {"text", "resolved", "resolution"} and _text(c["text"]) \
                and isinstance(c["resolved"], bool) and isinstance(c["resolution"], str):
            if c["resolved"] and not _text(c["resolution"]):
                errors.append(f"conditions[{i}] is marked resolved without a resolution")
                continue
            conditions.append(c["text"].strip())
            unresolved += 0 if c["resolved"] else 1
        else:
            errors.append(f"conditions[{i}] must be a non-empty string or {{text, resolved, resolution}}")
    if data["decision"] == "approved_with_conditions" and not raw_conditions:
        errors.append("approved_with_conditions requires at least one condition")

    if not _text(data["corpus_version"]):
        errors.append("corpus_version is missing or empty")
    for key in ("general_answers_approved", "penalty_answers_approved"):
        if not isinstance(data[key], bool):
            errors.append(f"{key} must be true or false")
    if data["penalty_answers_approved"] is True and data["general_answers_approved"] is not True:
        errors.append("penalty_answers_approved requires general_answers_approved")

    documents = []
    raw_docs = data["documents"]
    if not isinstance(raw_docs, list) or not raw_docs:
        errors.append("documents must be a non-empty list")
        raw_docs = []
    seen_hashes, seen_files = set(), set()
    for i, d in enumerate(raw_docs):
        if not isinstance(d, dict) or set(d) != {"file", "sha256", "title", "instrument"}:
            errors.append(f"documents[{i}] must have exactly file, sha256, title, instrument")
            continue
        if not all(_text(d[k]) for k in ("file", "title", "instrument")):
            errors.append(f"documents[{i}] has an empty file, title or instrument")
            continue
        if not isinstance(d["sha256"], str) or not SHA256_RE.match(d["sha256"]):
            errors.append(f"documents[{i}].sha256 must be 64 lowercase hex characters")
            continue
        if d["instrument"] not in INSTRUMENTS:
            errors.append(f"documents[{i}].instrument must be one of {sorted(INSTRUMENTS)}")
            continue
        if d["sha256"] in seen_hashes:
            errors.append(f"documents[{i}] repeats an approved sha256")
            continue
        if d["file"] in seen_files:
            errors.append(f"documents[{i}] repeats file name {d['file']!r} with different contents")
            continue
        seen_hashes.add(d["sha256"])
        seen_files.add(d["file"])
        documents.append(ApprovedDocument(d["file"], d["sha256"], d["title"].strip(), d["instrument"]))

    if errors:
        raise ApprovalError("; ".join(errors))
    return ApprovalRecord(
        jurisdiction=data["jurisdiction"], reviewer_name=reviewer["name"].strip(),
        reviewer_designation=reviewer["designation"].strip(), approval_date=approval_date,
        decision=data["decision"], conditions=tuple(conditions), unresolved_conditions=unresolved,
        corpus_version=data["corpus_version"].strip(),
        general_answers_approved=data["general_answers_approved"],
        penalty_answers_approved=data["penalty_answers_approved"], documents=tuple(documents),
    )


def parse_record_bytes(raw: bytes, today: dt.date | None = None) -> ApprovalRecord:
    try:
        data = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as e:
        raise ApprovalError("approval record is not UTF-8") from e
    except json.JSONDecodeError as e:
        raise ApprovalError(f"approval record is not valid JSON (line {e.lineno})") from e
    return parse_record(data, today)


def load_record(path, today: dt.date | None = None) -> ApprovalRecord:
    try:
        raw = Path(path).read_bytes()
    except OSError as e:
        raise ApprovalError(f"cannot read approval record: {e.__class__.__name__}") from e
    return parse_record_bytes(raw, today)


# ------------------------------------------------------------------------------------------------
# Signatures (verification only)
# ------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class TrustedKey:
    key_id: str
    public_key: Ed25519PublicKey
    status: str
    not_after: dt.date | None


def signature_path(record_path) -> Path:
    return Path(str(record_path) + ".sig")


def _b64(value, length, what):
    if not isinstance(value, str):
        raise ApprovalError(f"{what} must be base64 text")
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ApprovalError(f"{what} is not valid base64") from e
    if len(raw) != length:
        raise ApprovalError(f"{what} must decode to {length} bytes")
    return raw


def load_trusted_keys(path) -> dict:
    """key_id -> TrustedKey from the trusted-keys file (public keys only). Raises ApprovalError."""
    if path is None:
        raise ApprovalError("no trusted signing keys are configured")
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as e:
        raise ApprovalError(f"cannot read trusted-keys file: {e.__class__.__name__}") from e
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ApprovalError("trusted-keys file is not valid JSON") from e
    if not isinstance(data, dict) or set(data) != {"schema_version", "keys"} or data["schema_version"] != 1 \
            or not isinstance(data["keys"], list) or not data["keys"]:
        raise ApprovalError("trusted-keys file must be {schema_version: 1, keys: [...]} with at least one key")
    keys = {}
    for i, k in enumerate(data["keys"]):
        if not isinstance(k, dict) or set(k) != {"key_id", "algorithm", "public_key", "status", "not_after"}:
            raise ApprovalError(f"keys[{i}] must have exactly key_id, algorithm, public_key, status, not_after")
        if not isinstance(k["key_id"], str) or not KEY_ID_RE.match(k["key_id"]):
            raise ApprovalError(f"keys[{i}].key_id is invalid")
        if k["key_id"] in keys:
            raise ApprovalError(f"keys[{i}] repeats key_id {k['key_id']!r}")
        if k["algorithm"] != "ed25519":
            raise ApprovalError(f"keys[{i}].algorithm must be ed25519")
        if k["status"] not in KEY_STATUSES:
            raise ApprovalError(f"keys[{i}].status must be one of {sorted(KEY_STATUSES)}")
        not_after = None
        if k["not_after"] is not None:
            try:
                not_after = dt.date.fromisoformat(k["not_after"])
            except (TypeError, ValueError) as e:
                raise ApprovalError(f"keys[{i}].not_after must be YYYY-MM-DD or null") from e
        if k["status"] == "retired" and not_after is None:
            raise ApprovalError(f"keys[{i}] is retired but has no not_after date")
        public = Ed25519PublicKey.from_public_bytes(_b64(k["public_key"], 32, f"keys[{i}].public_key"))
        keys[k["key_id"]] = TrustedKey(k["key_id"], public, k["status"], not_after)
    return keys


def verify_signature(record_bytes: bytes, record: ApprovalRecord, sig_path, trusted: dict) -> str:
    """Verify the detached signature over the record's exact bytes. Returns the key_id. Raises ApprovalError."""
    try:
        sig = json.loads(Path(sig_path).read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ApprovalError("approval record is not signed") from e
    except OSError as e:
        raise ApprovalError(f"cannot read signature: {e.__class__.__name__}") from e
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ApprovalError("signature file is not valid JSON") from e
    if not isinstance(sig, dict) or set(sig) != {"schema_version", "algorithm", "key_id", "signature"} \
            or sig["schema_version"] != 1 or sig["algorithm"] != "ed25519":
        raise ApprovalError("signature file must be {schema_version: 1, algorithm: ed25519, key_id, signature}")
    key = trusted.get(sig["key_id"]) if isinstance(sig["key_id"], str) else None
    if key is None:
        raise ApprovalError("approval record is signed with an unknown key")
    if key.status == "revoked":
        raise ApprovalError("approval record is signed with a revoked key")
    if key.status == "retired" and record.approval_date > key.not_after:
        raise ApprovalError("approval record is dated after its signing key was retired")
    if key.status == "active" and key.not_after is not None and record.approval_date > key.not_after:
        raise ApprovalError("approval record is dated after its signing key's validity")
    try:
        key.public_key.verify(_b64(sig["signature"], 64, "signature"), record_bytes)
    except InvalidSignature as e:
        raise ApprovalError("approval record signature is invalid") from e
    return key.key_id


def corpus_errors(record: ApprovalRecord, files) -> list:
    """Compare the actual source files (paths) with the record: missing, changed, extra, duplicate names."""
    errors = []
    by_name = {}
    for path in files:
        path = Path(path)
        by_name.setdefault(path.name, set()).add(sha256_file(path))
    for name, hashes in by_name.items():
        if len(hashes) > 1:
            errors.append(f"file name {name!r} appears with {len(hashes)} different contents")
    actual = {h for hashes in by_name.values() for h in hashes}
    approved_names = {d.file: d.sha256 for d in record.documents}
    for name, hashes in by_name.items():
        if name in approved_names and approved_names[name] not in hashes:
            errors.append(f"{name!r} has changed since approval")
    for h in sorted(actual - record.hashes):
        names = sorted(n for n, hs in by_name.items() if h in hs)
        if not any(n in approved_names for n in names):
            errors.append(f"unapproved document: {', '.join(names)}")
    for d in record.documents:
        if d.sha256 not in actual and d.file not in by_name:
            errors.append(f"approved document missing from corpus: {d.file!r}")
    return errors


def index_errors(record: ApprovalRecord, metadatas) -> list:
    """Compare indexed chunk metadata with the record. Every chunk must carry an approved sha256."""
    errors = []
    if not metadatas:
        return ["index has no chunks"]
    names_by_hash, hashes_by_name = {}, {}
    missing_hash = 0
    for m in metadatas:
        m = m or {}
        h, name = m.get("sha256"), m.get("source_file")
        if not isinstance(h, str) or not SHA256_RE.match(h) or not name:
            missing_hash += 1
            continue
        names_by_hash.setdefault(h, set()).add(name)
        hashes_by_name.setdefault(name, set()).add(h)
        if m.get("state") != record.jurisdiction:
            errors.append(f"chunk from {name!r} is not tagged {record.jurisdiction}")
    if missing_hash:
        errors.append(f"{missing_hash} chunk(s) have no valid sha256/source_file metadata")
    for name, hashes in sorted(hashes_by_name.items()):
        if len(hashes) > 1:
            errors.append(f"file name {name!r} is indexed with {len(hashes)} different contents")
    indexed = set(names_by_hash)
    for h in sorted(indexed - record.hashes):
        errors.append(f"unapproved document in index: {', '.join(sorted(names_by_hash[h]))}")
    for d in record.documents:
        if d.sha256 not in indexed:
            errors.append(f"approved document missing from index: {d.file!r}")
    return sorted(set(errors), key=errors.index)


def evaluate(path, metadatas, today: dt.date | None = None, trusted_keys=None, corpus_dir=None) -> ApprovalStatus:
    """Load, verify and check the record at path. Never raises.

    trusted_keys: path of the trusted-keys file (required for any approval), or UNSIGNED_TEST_ONLY in
    isolated parser tests. corpus_dir: if given, every file under it is compared with the record too.
    """
    path = Path(path) if path else None
    if path is None or not path.exists():
        return ApprovalStatus("absent")
    try:
        raw = path.read_bytes()
        record = parse_record_bytes(raw, today)
        if trusted_keys is not UNSIGNED_TEST_ONLY:
            verify_signature(raw, record, signature_path(path), load_trusted_keys(trusted_keys))
    except OSError as e:
        return ApprovalStatus("invalid", [f"cannot read approval record: {e.__class__.__name__}"])
    except ApprovalError as e:
        return ApprovalStatus("invalid", [str(e)])
    problems = []
    if record.unresolved_conditions:
        # Never ignored: conditions the software cannot check keep the approval inactive.
        problems.append(f"{record.unresolved_conditions} approval condition(s) unresolved")
    problems += index_errors(record, metadatas)
    if corpus_dir is not None:
        problems += corpus_errors(record, sorted(p for p in Path(corpus_dir).rglob("*") if p.is_file()))
    if problems:
        return ApprovalStatus("invalid", problems, record)
    return ApprovalStatus("valid", [], record)
