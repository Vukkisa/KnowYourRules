"""Test support for Step 3: builds a SYNTHETIC decision register and held evidence files that match a synthetic ledger.

Everything here is invented test data. Reviewer names are obvious placeholders for a person, the records are written only
into temp directories or the tests/fixtures/validity_decisions fixtures (which declare "fixture": true), and nothing here
touches the real Stage 22 register. Synthetic decision ids start at LD-012 and never reuse LD-001 to LD-011: `renumber`
moves every id below 100 up by 11 (LD-001 -> LD-012), and ids from LD-900 up are left alone."""

import copy
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REAL_REGISTER = ROOT / "eval" / "legal-validation" / "stage-22-legal-decision-register.json"
FIX = Path(__file__).resolve().parent / "fixtures" / "validity_decisions"

SHIFT = 11
EV_FILE = "evidence/instrument-clause.txt"
EV_BYTES = b"SYNTHETIC instrument clause text for tests. Not a legal source.\n"
EV_SHA = hashlib.sha256(EV_BYTES).hexdigest()
GAZ_FILE = "evidence/gazette-print.txt"
GAZ_BYTES = b"SYNTHETIC gazette print stand-in for tests. Not a legal source.\n"
GAZ_SHA = hashlib.sha256(GAZ_BYTES).hexdigest()
REVIEW_DATE = "2026-01-02"
# Invented placeholders for a person and a firm. They carry no "synthetic"/"fixture"/"test" wording on purpose, so an unflagged
# register built from them exercises the production path; they are not real people and no real decision is implied.
REVIEWER = "Reviewer Alpha"
PREPARER = "Preparer Beta"
_ID = re.compile(r"LD-(\d{3})")


def sha_of(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def renumber(obj):
    """Return a deep copy with every LD-nnn string below LD-100 moved up by 11, so no synthetic id equals a real one."""
    def walk(x):
        if isinstance(x, dict):
            return {walk(k) if isinstance(k, str) else k: walk(v) for k, v in x.items()}
        if isinstance(x, list):
            return [walk(v) for v in x]
        if isinstance(x, str):
            m = _ID.fullmatch(x)
            if m and int(m.group(1)) < 100:
                return f"LD-{int(m.group(1)) + SHIFT:03d}"
        return x
    return walk(obj)


def _facts(ledger):
    for op in ledger.get("operations", []):
        f = op.get("effective_from")
        if isinstance(f, dict):
            yield f
    for v in ledger.get("versions", []):
        for k in ("start",):
            if isinstance(v.get(k), dict):
                yield v[k]


def synthetic_record(did, status, subject, *, prepared_by=PREPARER, reviewer=REVIEWER,
                     sources=None, extra=None):
    """One register record in the existing Stage 22 shape, plus the Step 3 keys. Approved records are complete."""
    r = {"decision_id": did, "subject": subject, "status": status, "prepared_by": prepared_by,
         "reviewer": {"name": None, "designation": None, "organisation": None}, "review_date": None, "decision": None,
         "rationale": None, "conditions": [], "supporting_sources": [], "replaces": None,
         "history": [{"date": "2026-01-01", "status": "pending", "by": "tooling"}]}
    if status == "approved":
        r.update(reviewer={"name": reviewer, "designation": "Reviewing Counsel", "organisation": "Alpha Chambers"},
                 review_date=REVIEW_DATE, decision="approved as recorded", rationale="rationale recorded for this decision",
                 supporting_sources=sources if sources is not None else [
                     {"file": EV_FILE, "sha256": EV_SHA, "location": "cl. 1", "kind": "instrument_text"}])
        r["history"].append({"date": REVIEW_DATE, "status": "approved", "by": reviewer})
    r.update(extra or {})
    return r


def decorate(ledger_obj, *, fixture_register=False):
    """(ledger, register, evidence_files) for a synthetic ledger: ids renumbered to LD-012 onward, every approved fact given
    evidence the register lists, and one register record per ledger decision with the same status, subject, preparer and
    reviewer. Continuing-verified and coverage decisions also get their search record and coverage confirmation."""
    ledger = renumber(ledger_obj)
    for d in ledger.get("decisions", []):                      # an approved decision is pinned in the ledger by reviewer and preparer
        if d.get("status") == "approved":
            d["prepared_by"] = PREPARER
            if isinstance(d.get("reviewer"), dict):
                d["reviewer"]["name"] = REVIEWER
            else:
                d["reviewer"] = REVIEWER
    for f in _facts(ledger):
        if f.get("state") == "approved" and not f.get("evidence"):
            f["evidence"] = [{"file": EV_FILE, "sha256": EV_SHA, "locator": "cl. 1"}]
    searched, covered = {}, {}
    for v in ledger.get("versions", []):
        e = v.get("end") or {}
        if e.get("state") == "continuing_verified":
            searched[e["decision_ref"]] = e["checked_through"]
    for c in ledger.get("coverage", []):
        if c.get("decision_ref"):
            covered.setdefault(c["decision_ref"], []).append(
                {"text_sha256": c["selector"]["text_sha256"], "provisions": list(c["provisions"])})
    records = []
    for d in ledger.get("decisions", []):
        extra = {}
        if d["decision_id"] in searched:
            extra["search_record"] = {"scope": "synthetic scope", "sources": ["synthetic source list"], "searched_on": searched[d["decision_id"]],
                                      "searcher": "synthetic searcher", "result": "no later amendment found (synthetic)"}
        if d["decision_id"] in covered:
            extra["coverage_confirmation"] = covered[d["decision_id"]]
        rv = (d.get("reviewer") or {}).get("name") if isinstance(d.get("reviewer"), dict) else d.get("reviewer")
        rec = synthetic_record(d["decision_id"], d["status"], d.get("subject", "synthetic subject"),
                               prepared_by=d.get("prepared_by") or PREPARER,
                               reviewer=rv or REVIEWER, extra=extra)
        if d["status"] != "approved":
            rec["reviewer"]["name"] = rv                       # the register carries whatever the ledger copy declares
            rec["prepared_by"] = d.get("prepared_by")
        records.append(rec)
    register = {"schema_version": 1, "stage": 22, "jurisdiction": "Telangana", "decisions": records}
    if fixture_register:
        register["fixture"] = True
    return ledger, register, {EV_FILE: EV_BYTES, GAZ_FILE: GAZ_BYTES}


def manifest_obj(files, jurisdiction="Telangana"):
    return {"schema_version": 1, "jurisdiction": jurisdiction,
            "files": [{"path": p, "sha256": sha_of(files[p]), "size": len(files[p])} for p in sorted(files)]}


def manifest_json(obj) -> bytes:
    """Canonical manifest bytes for a manifest object (the same rule as backend.evidence_manifest.canonical_bytes)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def manifest_bytes(files, jurisdiction="Telangana") -> bytes:
    """The canonical evidence manifest for `files` ({relative path: bytes})."""
    return manifest_json(manifest_obj(files, jurisdiction))


def write_evidence(root, files):
    root = Path(root)
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return root


def held_table(files):
    return {rel: sha_of(data) for rel, data in files.items()}


def register_record(register, did):
    return next(r for r in register["decisions"] if r["decision_id"] == did)


def real_register():
    return json.loads(REAL_REGISTER.read_text(encoding="utf-8"))


def build_fixture_set(base_ledger):
    """The static fixture set in tests/fixtures/validity_decisions, rebuilt from a base synthetic ledger. A test compares the
    files on disk with this output, so the fixtures cannot drift from the code that documents them."""
    obj = copy.deepcopy(base_ledger)
    obj["fixture"] = True
    obj["note"] = "SYNTHETIC ledger for the Step 3 decision-record tests. Not legal data."
    ledger, register, files = decorate(obj, fixture_register=True)
    register["note"] = "SYNTHETIC decision register for tests. LD-012 onward; the real Stage 22 records are untouched."
    first = register["decisions"][0]                       # the start decision also cites a (synthetic) Gazette print
    first["supporting_sources"].append({"file": GAZ_FILE, "sha256": GAZ_SHA, "location": "p. 1", "kind": "gazette_print"})
    return ledger, register, files


def dump(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True) + "\n"
