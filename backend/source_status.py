"""
Source-status registry: what is known about whether each source's text is the current law (Stage 25).

Independent of legal approval. Approval says a document may be used; text status says how far its text can be
trusted as current. An approved document keeps its warning. Nothing here infers currentness from approval.

Registry (legal-status/source-status.json, schema_version 1):
{
  "schema_version": 1, "jurisdiction": "Telangana", "note": "...",
  "entries": [{
     "manifest_id": "...", "file": "<path relative to source-documents>", "sha256": "<64 hex>",
     "status": one of STATUSES, "label": "...", "related_instruments": [...], "decision_refs": [...],
     "evidence": [{"file", "sha256", "note"}], "assigned_by": "...",
     "review": {"reviewer": null | {"name", "designation", "organisation"}, "review_date", "decision", "rationale"},
     "provision_overrides": [{"provision_id", "status", "related_instruments", "decision_refs", "evidence",
                              "assigned_by", "review"}]
  }]
}

Integrity: every entry is bound to a file hash; index and corpus files must match it. The registry file's own
SHA-256 must be named in the signed approval record (legal_approval.evaluate), so any edit to it invalidates the
approval. Warning text comes only from the fixed TEMPLATES below, never from a model.
"""

import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

SCHEMA_VERSION = 1
JURISDICTION = "Telangana"
STATUSES = ("verified_current", "official_text_commencement_unconfirmed", "unverified_snapshot",
            "known_amendments_unresolved")
UNRECORDED = "status_not_recorded"  # no valid entry covers the source: shown as a warning, never as current
# verified_current that is not covered by a valid approval binding this registry: never shown as current.
UNCONFIRMED_CURRENT = "verified_current_not_approved"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DECISION_REF_RE = re.compile(r"^LD-\d{3}$")
PLACEHOLDER_RE = re.compile(r"^_+$|\b(?:tbd|todo|placeholder|example|sample|test|dummy|n/?a|xxx+)\b", re.IGNORECASE)
ENTRY_KEYS = {"manifest_id", "file", "sha256", "status", "label", "related_instruments", "decision_refs", "evidence",
              "assigned_by", "review", "provision_overrides"}
OVERRIDE_KEYS = {"provision_id", "status", "related_instruments", "decision_refs", "evidence", "assigned_by", "review"}
REVIEW_KEYS = {"reviewer", "review_date", "decision", "rationale"}
REVIEWER_KEYS = {"name", "designation", "organisation"}
EVIDENCE_KEYS = {"file", "sha256", "note"}

# Fixed, backend-controlled warning templates. Fields come from the registry and index metadata only.
TEMPLATES = {
    "unverified_snapshot": (
        "{label}: this text comes from an unofficial web copy of unknown date. It may not include later "
        "amendments, so check the official text before relying on it."),
    "official_text_commencement_unconfirmed": (
        "{label}: the official text is held, but it has not been confirmed that this is the latest in-force version "
        "(Gazette publication, commencement or later amendments are not all confirmed)."),
    "known_amendments_unresolved": (
        "{label}, {provision}: the text shown is an older unofficial web copy. {instruments} contains amendments "
        "to this provision; their commencement and the current consolidated wording have not been established, "
        "so this answer cannot confirm the current law."),
    UNRECORDED: "{label}: the legal status of this source has not been recorded.",
    UNCONFIRMED_CURRENT: ("{label}: recorded as current, but that record is not covered by a valid legal approval, so "
                          "its currency is not confirmed."),
}


class SourceStatusError(ValueError):
    pass


@dataclass(frozen=True)
class Status:
    status: str
    sha256: str
    file: str
    label: str
    provision_id: str | None = None          # set when a provision override applies
    related_instruments: tuple = ()
    decision_refs: tuple = ()


@dataclass
class Registry:
    state: str                                # "absent" | "invalid" | "valid"
    errors: list = field(default_factory=list)
    sha256: str | None = None                 # SHA-256 of the registry file bytes
    by_hash: dict = field(default_factory=dict)
    validity_ledger_sha256: str | None = None  # optional binding to a provision-validity ledger (roadmap Step 2); only ever set on a valid registry
    validity_decision_register_sha256: str | None = None  # optional: SHA-256 of the exact decision-register file bytes (Step 3 review M1)
    validity_evidence_manifest_sha256: str | None = None  # optional: SHA-256 of the canonical evidence manifest file bytes (Step 3 review M1)

    @property
    def valid(self) -> bool:
        return self.state == "valid"

    def lookup(self, sha256, provision_id=None, label=None) -> Status:
        """Text status of one chunk. Unknown or invalid registry -> UNRECORDED (a warning, never 'current')."""
        entry = self.by_hash.get(sha256) if self.valid else None
        if entry is None:
            return Status(UNRECORDED, sha256 or "", "", label or "Unrecorded source", provision_id)
        override = entry["overrides"].get(provision_id) if provision_id else None
        src = override or entry
        return Status(src["status"], sha256, entry["file"], entry["label"],
                      provision_id if override else None, tuple(src["related_instruments"]),
                      tuple(src["decision_refs"]))


REGISTRY_KEYS = frozenset({"schema_version", "jurisdiction", "note", "entries"})
LEDGER_KEY = "validity_ledger_sha256"          # optional; absent from the real registry
REGISTER_KEY = "validity_decision_register_sha256"   # optional; absent from the real registry
MANIFEST_KEY = "validity_evidence_manifest_sha256"   # optional; absent from the real registry
OPTIONAL_KEYS = frozenset({LEDGER_KEY, REGISTER_KEY, MANIFEST_KEY})


def _ledger_sha_ok(v) -> bool:
    return isinstance(v, str) and SHA256_RE.fullmatch(v) is not None


def _text(v) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _str_list(v) -> bool:
    return isinstance(v, list) and all(_text(x) for x in v)


def _check_review(review, where, status, errors, today):
    if not isinstance(review, dict) or set(review) != REVIEW_KEYS:
        errors.append(f"{where}.review must have exactly {sorted(REVIEW_KEYS)}")
        return
    complete = True
    rv = review["reviewer"]
    if rv is None:
        complete = False
    elif not isinstance(rv, dict) or set(rv) != REVIEWER_KEYS:
        errors.append(f"{where}.review.reviewer must be null or have exactly {sorted(REVIEWER_KEYS)}")
        complete = False
    else:
        for k in sorted(REVIEWER_KEYS):
            if not _text(rv[k]):
                errors.append(f"{where}.review.reviewer.{k} is empty")
                complete = False
            elif PLACEHOLDER_RE.search(rv[k]):
                errors.append(f"{where}.review.reviewer.{k} looks like a placeholder")
                complete = False
    date = review["review_date"]
    if date is None:
        complete = False
    else:
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) or dt.date.fromisoformat(date) > today:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"{where}.review.review_date must be a real, non-future YYYY-MM-DD date or null")
            complete = False
    for k in ("decision", "rationale"):
        if review[k] is None:
            complete = False
        elif not _text(review[k]):
            errors.append(f"{where}.review.{k} must be non-empty text or null")
            complete = False
    filled = [rv, date, review["decision"], review["rationale"]]
    if any(x is not None for x in filled) and not all(x is not None for x in filled):
        errors.append(f"{where}.review is partly filled: reviewer, date, decision and rationale go together")
    if status == "verified_current" and not complete:
        errors.append(f"{where}: verified_current requires a complete human review "
                      "(reviewer name/designation/organisation, review_date, decision, rationale)")


def _check_common(obj, where, errors, today):
    if obj.get("status") not in STATUSES:
        errors.append(f"{where}.status must be one of {list(STATUSES)}")
    for k in ("related_instruments", "decision_refs"):
        if not _str_list(obj.get(k)):
            errors.append(f"{where}.{k} must be a list of non-empty strings")
    if _str_list(obj.get("decision_refs")):
        for ref in obj["decision_refs"]:
            if not DECISION_REF_RE.match(ref):
                errors.append(f"{where}.decision_refs has an invalid id {ref!r}")
    if obj.get("status") == "known_amendments_unresolved" and not obj.get("related_instruments"):
        errors.append(f"{where}: known_amendments_unresolved must name the amending instrument(s)")
    if obj.get("status") == "verified_current" and not obj.get("decision_refs"):
        errors.append(f"{where}: verified_current must reference the legal decision that established it")
    ev = obj.get("evidence")
    if not isinstance(ev, list) or not ev:
        errors.append(f"{where}.evidence must be a non-empty list")
    else:
        for i, e in enumerate(ev):
            if not isinstance(e, dict) or set(e) != EVIDENCE_KEYS or not _text(e.get("file")) \
                    or not isinstance(e.get("sha256"), str) or not SHA256_RE.match(e["sha256"]) \
                    or not _text(e.get("note")):
                errors.append(f"{where}.evidence[{i}] must be {{file, sha256 (64 hex), note}}")
    if not _text(obj.get("assigned_by")):
        errors.append(f"{where}.assigned_by is missing")
    _check_review(obj.get("review"), where, obj.get("status"), errors, today)


def parse(data, today: dt.date | None = None) -> dict:
    """Validate a decoded registry strictly. Returns {sha256: entry}; raises SourceStatusError listing problems."""
    today = today or dt.date.today()
    errors = []
    if not isinstance(data, dict) or not REGISTRY_KEYS <= set(data) <= REGISTRY_KEYS | OPTIONAL_KEYS:
        raise SourceStatusError("registry must be an object with exactly schema_version, jurisdiction, note, entries")
    for key in sorted(OPTIONAL_KEYS & set(data)):
        if not _ledger_sha_ok(data[key]):
            errors.append(f"{key} must be 64 lowercase hex characters")
    if data["schema_version"] != SCHEMA_VERSION or isinstance(data["schema_version"], bool):
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if data["jurisdiction"] != JURISDICTION:
        errors.append(f"jurisdiction must be {JURISDICTION!r}")
    entries = data["entries"]
    if not isinstance(entries, list) or not entries:
        raise SourceStatusError("; ".join(errors + ["entries must be a non-empty list"]))
    by_hash, names = {}, {}
    for i, e in enumerate(entries):
        where = f"entries[{i}]"
        if not isinstance(e, dict) or set(e) != ENTRY_KEYS:
            errors.append(f"{where} must have exactly {sorted(ENTRY_KEYS)}")
            continue
        h, f = e["sha256"], e["file"]
        if not isinstance(h, str) or not SHA256_RE.match(h):
            errors.append(f"{where}.sha256 must be 64 lowercase hex characters")
            continue
        if not _text(f) or not _text(e["label"]) or not _text(e["manifest_id"]):
            errors.append(f"{where} has an empty file, label or manifest_id")
            continue
        name = PurePosixPath(f).name
        if h in by_hash:
            errors.append(f"{where} duplicates the entry for sha256 {h[:12]}...")
            continue
        if name in names:
            errors.append(f"{where} duplicates file name {name!r}")
            continue
        _check_common(e, where, errors, today)
        overrides = {}
        if not isinstance(e["provision_overrides"], list):
            errors.append(f"{where}.provision_overrides must be a list")
        else:
            for j, o in enumerate(e["provision_overrides"]):
                ow = f"{where}.provision_overrides[{j}]"
                if not isinstance(o, dict) or set(o) != OVERRIDE_KEYS or not _text(o.get("provision_id")):
                    errors.append(f"{ow} must have exactly {sorted(OVERRIDE_KEYS)} with a provision_id")
                    continue
                if o["provision_id"] in overrides:
                    errors.append(f"{ow} duplicates provision {o['provision_id']!r}")
                    continue
                _check_common(o, ow, errors, today)
                overrides[o["provision_id"]] = o
        names[name] = h
        by_hash[h] = {"file": f, "name": name, "manifest_id": e["manifest_id"].strip(), "label": e["label"].strip(), "status": e["status"],
                      "related_instruments": e["related_instruments"], "decision_refs": e["decision_refs"],
                      "overrides": overrides}
    if errors:
        raise SourceStatusError("; ".join(errors))
    return by_hash


def index_errors(by_hash: dict, metadatas) -> list:
    """Every indexed document needs an entry with the same hash; a file name indexed with another hash is rejected."""
    errors, seen = [], set()
    name_to_hash = {v["name"]: h for h, v in by_hash.items()}
    for m in metadatas or []:
        m = m or {}
        h, name = m.get("sha256"), m.get("source_file")
        if (h, name) in seen:
            continue
        seen.add((h, name))
        if name in name_to_hash and name_to_hash[name] != h:
            errors.append(f"hash mismatch for {name!r}: index {str(h)[:12]}..., registry {name_to_hash[name][:12]}...")
        elif h not in by_hash:
            errors.append(f"missing registry entry for indexed document {name!r}")
        elif m.get("manifest_id") and by_hash[h].get("manifest_id") and m["manifest_id"] != by_hash[h]["manifest_id"]:
            errors.append(f"manifest id mismatch for {name!r}: index {m['manifest_id']!r}, registry {by_hash[h]['manifest_id']!r}")
    return errors


def corpus_errors(by_hash: dict, corpus_dir) -> list:
    """Each registry entry's file, if present under corpus_dir, must hash to the registered SHA-256."""
    errors = []
    root = Path(corpus_dir)
    for h, v in by_hash.items():
        path = root / v["file"]
        if not path.is_file():
            errors.append(f"registered file missing from corpus: {v['file']!r}")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != h:
            errors.append(f"hash mismatch for {v['file']!r}: file on disk differs from the registry")
    return errors


def load(path, metadatas=None, corpus_dir=None, today: dt.date | None = None) -> Registry:
    """Load and validate. Never raises; any problem gives an invalid registry (all sources then warn)."""
    if path is None or not Path(path).is_file():
        return Registry("absent", ["source-status registry not found"])
    try:
        raw = Path(path).read_bytes()
    except OSError as e:
        return Registry("invalid", [f"cannot read source-status registry: {e.__class__.__name__}"])
    return load_bytes(raw, metadatas, corpus_dir, today)


def load_bytes(raw, metadatas=None, corpus_dir=None, today: dt.date | None = None) -> Registry:
    """``load`` for bytes the caller has already read: the digest and the parse use exactly these bytes, so a caller that
    hashes or verifies the same bytes cannot be affected by the file changing afterwards. Never raises."""
    if not isinstance(raw, (bytes, bytearray)):
        return Registry("invalid", ["cannot read source-status registry: not bytes"])
    raw = bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    try:
        data = json.loads(raw.decode("utf-8"))
        by_hash = parse(data, today)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        return Registry("invalid", [f"cannot read source-status registry: {e.__class__.__name__}"])
    except SourceStatusError as e:
        return Registry("invalid", [str(e)])
    problems = index_errors(by_hash, metadatas) if metadatas is not None else []
    if corpus_dir is not None:
        problems += corpus_errors(by_hash, corpus_dir)
    if problems:
        return Registry("invalid", problems, digest)
    return Registry("valid", [], digest, by_hash, data.get(LEDGER_KEY), data.get(REGISTER_KEY), data.get(MANIFEST_KEY))


def verify_ledger_binding(registry, ledger_sha256) -> list:
    """Hash check only: does this valid registry name exactly this ledger hash? Returns problems; [] means it does.

    NECESSARY BUT NOT SUFFICIENT. It says nothing about the ledger's content. A ledger may be used only after
    the ledger acceptance gate (``backend/ledger_acceptance.py``) has also validated it completely (any validation error rejects it)."""
    if not isinstance(registry, Registry) or not registry.valid:
        return ["source-status registry is not valid"]
    bound = registry.validity_ledger_sha256
    if bound is None:
        return ["source-status registry does not bind a validity ledger"]
    if not _ledger_sha_ok(bound):
        return [f"{LEDGER_KEY} is malformed"]
    if not _ledger_sha_ok(ledger_sha256):
        return ["ledger sha256 must be 64 lowercase hex characters"]
    if bound != ledger_sha256:
        return ["validity ledger has changed since the registry bound it"]
    return []


def _verify_bound(registry, attr, key, noun, sha256) -> list:
    if not isinstance(registry, Registry) or not registry.valid:
        return ["source-status registry is not valid"]
    bound = getattr(registry, attr)
    if bound is None:
        return [f"source-status registry does not bind a {noun}"]
    if not _ledger_sha_ok(bound):
        return [f"{key} is malformed"]
    if not _ledger_sha_ok(sha256):
        return [f"{noun} sha256 must be 64 lowercase hex characters"]
    if bound != sha256:
        return [f"{noun} has changed since the registry bound it"]
    return []


def verify_register_binding(registry, register_sha256) -> list:
    """Hash check only: does this valid registry name exactly the SHA-256 of these decision-register bytes? [] means yes.
    The registry is itself bound to the signed approval record, so a changed register no longer matches the signed chain."""
    return _verify_bound(registry, "validity_decision_register_sha256", REGISTER_KEY, "validity decision register", register_sha256)


def verify_manifest_binding(registry, manifest_sha256) -> list:
    """Hash check only: does this valid registry name exactly the SHA-256 of these evidence-manifest bytes? [] means yes."""
    return _verify_bound(registry, "validity_evidence_manifest_sha256", MANIFEST_KEY, "validity evidence manifest", manifest_sha256)


def sha256_file(path) -> str | None:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except (OSError, TypeError):
        return None


def warning_text(s: Status, trust_verified: bool = False) -> str | None:
    if s.status == "verified_current":
        return None if trust_verified else TEMPLATES[UNCONFIRMED_CURRENT].format(label=s.label)
    instruments = " and ".join(s.related_instruments) or "A later instrument"
    return TEMPLATES[s.status].format(label=s.label, provision=s.provision_id or "", instruments=instruments)


def collect_warnings(registry: Registry, docs, citation_numbers=None, trust_verified: bool = False) -> list[dict]:
    """One warning per (source, override, status), in first-citation order, listing the citations it covers.

    citation_numbers: the [n] number of each doc (grounded answers); defaults to 1..len(docs).
    trust_verified: True only when a valid signed approval binds this exact registry; otherwise verified_current
    still warns. Approval never removes any other warning."""
    out, index = [], {}
    for pos, d in enumerate(docs):
        m = getattr(d, "metadata", None) or {}
        s = registry.lookup(m.get("sha256"), m.get("provision_id"),
                            label=m.get("title") or m.get("source_file"))
        text = warning_text(s, trust_verified)
        if text is None:
            continue
        status = s.status if s.status != "verified_current" else UNCONFIRMED_CURRENT
        key = (s.sha256, s.provision_id, status)
        n = citation_numbers[pos] if citation_numbers else pos + 1
        if key in index:
            if n not in out[index[key]]["citations"]:
                out[index[key]]["citations"].append(n)
            continue
        index[key] = len(out)
        out.append({"warning_id": f"{status}:{s.sha256[:12]}" + (f":{s.provision_id}" if s.provision_id else ""),
                    "status": status, "text": text, "source_file": s.file or m.get("source_file"),
                    "sha256": s.sha256 or None, "provision_id": s.provision_id,
                    "related_instruments": list(s.related_instruments), "decision_refs": list(s.decision_refs),
                    "citations": [n]})
    return out


# ---------------------------------------------------------------------------------------------------
# Stage 7C (D12): which source of truth says what, and where the two disagree.
#   * ELIGIBILITY (may a chunk be served at all) belongs to the lifecycle registry that travels in the R2 snapshot (state per file
#     hash) and, for answering, to the signed approval record. This module can never make a source eligible.
#   * TEXT STATUS (how far the text can be trusted as current law: a warning label) belongs to legal-status/source-status.json, which
#     travels with the code in git, is validated against the restored index, and is bound by hash into the signed approval record.
# Any disagreement is reported with a category. The BLOCKING categories already make the server refuse to answer (an invalid
# registry means no answers: backend/server.py serving errors); the others are diagnostics. Nothing here reconciles or rewrites either file.
# ---------------------------------------------------------------------------------------------------
ABSENT_REGISTRY = "absent_status_registry"
MALFORMED_REGISTRY = "malformed_status_registry"
INVALID_REGISTRY = "invalid_status_registry"
MISSING_ENTRY = "missing_status_entry"
HASH_MISMATCH = "hash_mismatch"
MANIFEST_ID_MISMATCH = "manifest_id_mismatch"
EXTRA_ENTRY = "extra_status_entry"
FILE_NAME_MISMATCH = "file_name_mismatch"
LIFECYCLE_UNREADABLE = "lifecycle_registry_unreadable"
LIFECYCLE_UNKNOWN = "lifecycle_hash_unknown"
LIFECYCLE_COUNT_MISMATCH = "lifecycle_chunk_count_mismatch"
STATUS_CONFLICT = "status_conflict"
BLOCKING = frozenset({ABSENT_REGISTRY, MALFORMED_REGISTRY, INVALID_REGISTRY, MISSING_ENTRY, HASH_MISMATCH, MANIFEST_ID_MISMATCH})


def diagnose(path, index_metadatas, lifecycle_registry_path=None) -> list:
    """Categorised disagreements between the status file, the (restored) index and the lifecycle registry. Never raises, never
    modifies anything. Each item: {"category", "document", "detail"}; `document` is a manifest id or file name, `detail` carries at most
    12-character hash prefixes."""
    out = []

    def add(cat, doc, detail):
        out.append({"category": cat, "document": doc, "detail": detail})
    if path is None or not Path(path).is_file():
        return [{"category": ABSENT_REGISTRY, "document": None, "detail": "source-status registry not found"}]
    try:
        raw = Path(path).read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        return [{"category": MALFORMED_REGISTRY, "document": None, "detail": f"cannot read source-status registry: {e.__class__.__name__}"}]
    try:
        by_hash = parse(data)
    except SourceStatusError as e:
        return [{"category": INVALID_REGISTRY, "document": None, "detail": str(e)[:300]}]
    meta = [m or {} for m in (index_metadatas or [])]
    idx = {}
    for m in meta:
        if m.get("sha256"):
            idx.setdefault(m["sha256"], {"manifest_id": m.get("manifest_id"), "file": m.get("source_file"), "chunks": 0})["chunks"] += 1
    name_to_hash = {v["name"]: h for h, v in by_hash.items()}
    for h, info in sorted(idx.items(), key=lambda kv: str(kv[1]["file"])):
        doc = info["manifest_id"] or info["file"]
        if info["file"] in name_to_hash and name_to_hash[info["file"]] != h:
            add(HASH_MISMATCH, doc, f"index {h[:12]}, registry {name_to_hash[info['file']][:12]}")
        elif h not in by_hash:
            add(MISSING_ENTRY, doc, f"no status entry for indexed hash {h[:12]}")
        else:
            e = by_hash[h]
            if info["manifest_id"] and e["manifest_id"] != info["manifest_id"]:
                add(MANIFEST_ID_MISMATCH, doc, f"index {info['manifest_id']!r}, registry {e['manifest_id']!r}")
            if info["file"] and e["name"] != info["file"]:
                add(FILE_NAME_MISMATCH, doc, f"index {info['file']!r}, registry {e['name']!r}")
    for h, e in sorted(by_hash.items(), key=lambda kv: kv[1]["manifest_id"]):
        if h not in idx:
            add(EXTRA_ENTRY, e["manifest_id"], f"status entry {h[:12]} matches nothing in the index")
    if lifecycle_registry_path is not None:
        try:
            lc = json.loads(Path(lifecycle_registry_path).read_text("utf-8"))
            versions = {rec["sha256"]: rec for src in lc["sources"].values() for rec in src["versions"].values()}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            add(LIFECYCLE_UNREADABLE, None, "the lifecycle registry could not be read; nothing is servable")
            return out
        for h, info in sorted(idx.items(), key=lambda kv: str(kv[1]["file"])):
            doc = info["manifest_id"] or info["file"]
            rec = versions.get(h)
            if rec is None:
                add(LIFECYCLE_UNKNOWN, doc, f"hash {h[:12]} is in the index but in no lifecycle version: not servable")
                continue
            if rec.get("chunk_count") != info["chunks"]:
                add(LIFECYCLE_COUNT_MISMATCH, doc, f"index holds {info['chunks']} chunks, lifecycle says {rec.get('chunk_count')}: not servable")
            e = by_hash.get(h)
            if e and e["status"] == "verified_current" and rec.get("state") != "approved":
                add(STATUS_CONFLICT, doc, f"status file says verified_current, lifecycle state is {rec.get('state')!r}: shown as unconfirmed, not served")
    return out


def summarize(diagnostics: list) -> dict:
    """Counts per category and whether anything blocks answering; safe for /status."""
    counts = {}
    for d in diagnostics:
        counts[d["category"]] = counts.get(d["category"], 0) + 1
    return {"consistent": not diagnostics, "blocking": sorted(c for c in counts if c in BLOCKING), "categories": counts}
