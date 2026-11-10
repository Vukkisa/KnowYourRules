"""
Human review import and reconciliation for the Telangana retrieval benchmark.

    # once, from the preview index (read-only): stable references for every indexed chunk
    python -m backend.review_import build-refs
    # check one or more completed reviewer CSVs (exit code 1 on any error)
    python -m backend.review_import validate submissions/reviewer-a.csv
    # validate, then write a SEPARATE reviewed-benchmark candidate file
    python -m backend.review_import reconcile submissions/*.csv --out eval/telangana-benchmark-review-candidate.json

Machine data is never changed: the benchmark JSON and the reviewer template CSV are read-only inputs, any change
to a machine column in a submission rejects the whole file, and reviewer corrections are recorded beside the
machine labels, never applied to them. Nothing here creates, implies or records legal approval.
"""

import argparse
import collections
import csv
import datetime as dt
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
BENCHMARK = BASE_DIR / "eval" / "telangana-retrieval-benchmark.json"
TEMPLATE = BASE_DIR / "eval" / "telangana-retrieval-review.csv"
REFERENCES = BASE_DIR / "eval" / "telangana-chunk-references.json"
PREVIEW_DB = BASE_DIR / "chroma_telangana_preview"
COLLECTION = "telangana-traffic-rules"

LEGAL_STATUS = ("NOT LEGAL APPROVAL. Human benchmark review records whether retrieval labels are right. It does "
                "not verify the corpus, approve answers or approve penalties; that requires the separate signed "
                "legal approval record.")

# --- reviewer fields (documented in eval/HUMAN-REVIEW-GUIDE.md) ---
DECISIONS = ("correct", "partially_correct", "incorrect", "ambiguous", "missing_source", "refuse_expected")
ENUM_FIELDS = {
    "human_decision": DECISIONS,
    "human_retrieved_passages_sufficient": ("yes", "partly", "no", "n/a"),
    "human_jurisdiction_correct": ("yes", "no", "n/a"),
    "human_instrument_correct": ("yes", "no", "n/a"),
    "human_source_current_and_applicable": ("yes", "no", "unknown"),
    "human_supersession_checked": ("yes", "no"),
    "human_should_be_refused": ("yes", "no"),
}
TEXT_FIELDS = ("human_correct_expected_provisions", "human_exceptions_or_conditions_missing",
               "human_missing_evidence", "human_comments")
IDENTITY_FIELDS = ("reviewed_on", "reviewer_name", "reviewer_designation")
HUMAN_FIELDS = tuple(ENUM_FIELDS) + TEXT_FIELDS + IDENTITY_FIELDS
NEEDS_COMMENT = ("partially_correct", "incorrect", "ambiguous", "missing_source")
DATE_RE = re.compile(r"^(\d{2})-(\d{2})-(\d{4})$")
PROVISION_ITEM_RE = re.compile(r"^\s*([a-z0-9-]+)\s*::\s*(.+?)\s*$")
EARLIEST_REVIEW_DATE = dt.date(2026, 11, 9)  # the benchmark's creation date (see its "corpus" field)


# ---------------------------------------------------------------------------------------------------
# Stable chunk references
# ---------------------------------------------------------------------------------------------------
def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_id(meta) -> str:
    return f"{meta['manifest_id']}::{meta['provision_id']}::part{meta['part']}of{meta['parts']}"


def review_ref(meta, text_hash: str) -> str:
    """Unambiguous, rebuild-stable reference: benchmark chunk ID + source location + chunk-text hash. Two chunks
    that share a chunk ID (G.O. 53's two SCHEDULE sections) still differ in location and text."""
    return f"{chunk_id(meta)}@{meta['location']}|text:{text_hash[:12]}"


def build_references(db_dir=PREVIEW_DB) -> dict:
    """Metadata-only snapshot of the preview index (no legal text). Reads Chroma; writes nothing to it."""
    import chromadb
    got = chromadb.PersistentClient(str(db_dir)).get_collection(COLLECTION).get(include=["documents", "metadatas"])
    chunks = []
    for text, meta in sorted(zip(got["documents"], got["metadatas"]),
                             key=lambda tm: (tm[1]["manifest_id"], tm[1]["location"], tm[1]["provision_id"])):
        h = text_sha(text)
        chunks.append({"ref": review_ref(meta, h), "chunk_id": chunk_id(meta), "document": meta["manifest_id"],
                       "provision": meta["provision_id"], "part": meta["part"], "parts": meta["parts"],
                       "location": meta["location"], "document_sha256": meta["sha256"], "text_sha256": h,
                       "answer_eligible": meta.get("answer_eligible") is not False})
    counts = collections.Counter(c["chunk_id"] for c in chunks)
    refs = collections.Counter(c["ref"] for c in chunks)
    if any(n > 1 for n in refs.values()):
        raise ValueError("review references are not unique; refusing to write an ambiguous snapshot")
    return {"schema_version": 1, "source": "preview index (read-only snapshot of chunk metadata and text hashes)",
            "chunks": chunks, "duplicate_chunk_ids": {k: [c["ref"] for c in chunks if c["chunk_id"] == k]
                                                      for k, n in sorted(counts.items()) if n > 1}}


def load_references(path=REFERENCES) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def resolve_benchmark_chunk(entry, references) -> list[str]:
    """Review refs for one benchmark expected/excluded chunk (chunk ID + location); normally exactly one."""
    return [c["ref"] for c in references["chunks"]
            if c["chunk_id"] == entry["chunk_id"] and c["location"] == entry["location"]]


# ---------------------------------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------------------------------
@dataclass
class Submission:
    path: str
    sha256: str
    rows: dict = field(default_factory=dict)        # id -> row (reviewed rows only)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    unreviewed: list = field(default_factory=list)  # ids with every human field empty

    @property
    def ok(self) -> bool:
        return not self.errors


def _read_csv(path) -> tuple[list, list]:
    raw = Path(path).read_bytes()
    text = raw.decode("utf-8-sig")  # tolerate the BOM spreadsheet programs add
    reader = csv.DictReader(text.splitlines(keepends=True))
    rows = list(reader)
    return reader.fieldnames or [], rows


def _norm_machine(value) -> str:
    return (value or "").replace("\r\n", "\n").replace("\r", "\n")


def _parse_date(value: str):
    m = DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _machine_from_benchmark(case) -> dict:
    """Template columns that are derivable from the benchmark JSON itself."""
    return {"question": case["question"], "category": case["category"],
            "machine_expected_outcome": case["expected_retrieval_outcome"],
            "machine_expected_provisions": "; ".join(case["expected_provisions"]),
            "machine_label_source": case["label_source"], "reviewer_status": case["reviewer_status"]}


def check_template(template_rows, cases) -> list:
    """The template itself must still agree with the benchmark (detects drift between the two machine files)."""
    errors = []
    by_id = {r["id"]: r for r in template_rows}
    if sorted(by_id) != sorted(c["id"] for c in cases) or len(by_id) != len(template_rows):
        errors.append("template CSV ids do not match the benchmark")
    for c in cases:
        row = by_id.get(c["id"])
        if row is None:
            continue
        for col, expected in _machine_from_benchmark(c).items():
            if _norm_machine(row.get(col)) != expected:
                errors.append(f"template {c['id']}: {col} differs from the benchmark")
    return errors


def validate(path, *, benchmark=BENCHMARK, template=TEMPLATE, references=REFERENCES,
             today: dt.date | None = None) -> Submission:
    today = today or dt.date.today()
    sub = Submission(str(path), hashlib.sha256(Path(path).read_bytes()).hexdigest())
    cases = json.loads(Path(benchmark).read_text(encoding="utf-8"))["cases"]
    t_fields, t_rows = _read_csv(template)
    refs = load_references(references)
    sub.errors += check_template(t_rows, cases)
    template_by_id = {r["id"]: r for r in t_rows}
    machine_cols = [c for c in t_fields if c not in HUMAN_FIELDS]
    eligible = collections.defaultdict(list)
    for c in refs["chunks"]:
        eligible[(c["document"], c["provision"])].append(c["answer_eligible"])

    try:
        fields, rows = _read_csv(path)
    except (UnicodeDecodeError, csv.Error) as e:
        sub.errors.append(f"cannot read CSV: {type(e).__name__}")
        return sub
    if set(fields) != set(t_fields) or len(fields) != len(t_fields):
        missing, extra = sorted(set(t_fields) - set(fields)), sorted(set(fields) - set(t_fields))
        sub.errors.append(f"columns differ from the template (missing {missing}, unexpected {extra})")
        return sub

    ids = [r.get("id", "") for r in rows]
    counts = collections.Counter(ids)
    for i in sorted(k for k, n in counts.items() if n > 1):
        sub.errors.append(f"duplicate question id {i}")
    for i in sorted(set(ids) - set(template_by_id)):
        sub.errors.append(f"unknown question id {i!r}")
    for i in sorted(set(template_by_id) - set(ids)):
        sub.errors.append(f"missing question id {i}")

    for row in rows:
        qid = row.get("id", "")
        base = template_by_id.get(qid)
        if base is None or counts[qid] > 1:
            continue
        for col in machine_cols:
            if _norm_machine(row[col]) != _norm_machine(base[col]):
                sub.errors.append(f"{qid}: machine column {col} was modified")
        human = {f: (row[f] or "").strip() for f in HUMAN_FIELDS}
        if not any(human.values()):
            sub.unreviewed.append(qid)
            continue
        problems = []
        for f in IDENTITY_FIELDS + tuple(ENUM_FIELDS):
            if not human[f]:
                problems.append(f"{f} is empty")
        for f, allowed in ENUM_FIELDS.items():
            if human[f] and human[f] not in allowed:
                problems.append(f"{f}={human[f]!r} is not one of {list(allowed)}")
        if human["reviewed_on"]:
            d = _parse_date(human["reviewed_on"])
            if d is None:
                problems.append(f"reviewed_on={human['reviewed_on']!r} is not a valid DD-MM-YYYY date")
            elif d > today:
                problems.append(f"reviewed_on {human['reviewed_on']} is in the future")
            elif d < EARLIEST_REVIEW_DATE:
                problems.append(f"reviewed_on {human['reviewed_on']} is before the benchmark existed")
        decision = human["human_decision"]
        if decision in NEEDS_COMMENT and not human["human_comments"]:
            problems.append(f"human_decision={decision} needs human_comments explaining why")
        if decision == "missing_source" and not human["human_missing_evidence"]:
            problems.append("human_decision=missing_source needs human_missing_evidence")
        if human["human_retrieved_passages_sufficient"] == "n/a" and \
                base["machine_expected_outcome"] == "retrieve":
            problems.append("human_retrieved_passages_sufficient=n/a is only for non-retrieval outcomes")
        for item in filter(None, (p.strip() for p in human["human_correct_expected_provisions"].split(";"))):
            m = PROVISION_ITEM_RE.match(item)
            if not m:
                problems.append(f"human_correct_expected_provisions item {item!r} is not 'document :: provision'")
                continue
            flags = eligible.get((m.group(1), m.group(2)))
            if flags is None:
                problems.append(f"human_correct_expected_provisions names {item!r}, which is not in the index")
            elif not any(flags):
                problems.append(f"human_correct_expected_provisions names {item!r}, whose chunks are all excluded "
                                "(not answer-eligible)")
        if problems:
            sub.errors += [f"{qid}: {p}" for p in problems]
        else:
            sub.rows[qid] = {**human, "_raw_text": {f: row[f] for f in TEXT_FIELDS}}
    if not sub.rows and not sub.errors:
        sub.warnings.append("submission contains no reviewed rows")
    return sub


# ---------------------------------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------------------------------
COMPARED_FIELDS = tuple(ENUM_FIELDS) + ("human_correct_expected_provisions",)


def _norm_provisions(value: str) -> tuple:
    items = []
    for p in filter(None, (x.strip() for x in value.split(";"))):
        m = PROVISION_ITEM_RE.match(p)
        items.append(f"{m.group(1)} :: {m.group(2)}" if m else p)
    return tuple(sorted(items))


def reconcile(submissions, *, benchmark=BENCHMARK, references=REFERENCES, min_reviewers: int = 1,
              generated_on: str | None = None) -> dict:
    """Reviewed-benchmark candidate. Refuses invalid submissions; never edits the machine benchmark."""
    bad = [s for s in submissions if not s.ok]
    if bad:
        raise ValueError("refusing to reconcile invalid submissions: " + ", ".join(s.path for s in bad))
    bench_bytes = Path(benchmark).read_bytes()
    bench = json.loads(bench_bytes)
    refs = load_references(references)
    reviews = collections.defaultdict(list)
    errors = []
    for s in submissions:
        for qid, h in s.rows.items():
            who = (h["reviewer_name"].casefold(), h["reviewer_designation"].casefold())
            if any((r["reviewer_name"].casefold(), r["reviewer_designation"].casefold()) == who for r in reviews[qid]):
                errors.append(f"{qid}: reviewed more than once by {h['reviewer_name']}")
                continue
            reviews[qid].append({
                "reviewer_name": h["reviewer_name"], "reviewer_designation": h["reviewer_designation"],
                "reviewed_on": h["reviewed_on"], "submission": Path(s.path).name, "submission_sha256": s.sha256,
                **{f: h[f] for f in ENUM_FIELDS},
                **h["_raw_text"]})  # free text preserved exactly as submitted
    if errors:
        raise ValueError("; ".join(errors))

    out_cases, counts = [], collections.Counter()
    for case in bench["cases"]:
        rs = reviews.get(case["id"], [])
        disagreements = {}
        for f in COMPARED_FIELDS:
            values = {(_norm_provisions(r[f]) if f == "human_correct_expected_provisions" else r[f]) for r in rs}
            if len(values) > 1:
                disagreements[f] = [{"reviewer_name": r["reviewer_name"], "value": r[f]} for r in rs]
        decisions = {r["human_decision"] for r in rs}
        if not rs:
            state = "unreviewed"
        elif "human_decision" in disagreements:
            state = "disputed"
        elif len(rs) < min_reviewers:
            state = "partially_reviewed"
        else:
            state = "reviewed"
        counts[state] += 1
        agreed = next(iter(decisions)) if state == "reviewed" else None
        proposed = {"correct": "human_confirmed", "incorrect": "human_rejected"}.get(agreed, "pending_human_review")
        proposals = sorted({_norm_provisions(r["human_correct_expected_provisions"]) for r in rs
                            if r["human_correct_expected_provisions"].strip()})
        out_cases.append({
            "id": case["id"],
            "machine": case,  # the original machine case, verbatim
            "chunk_refs": {kind: [{"chunk_id": e["chunk_id"], "location": e["location"],
                                   "review_refs": resolve_benchmark_chunk(e, refs)} for e in case[kind]]
                           for kind in ("expected_chunks", "excluded_chunks")},
            "review_state": state,
            "reviews": rs,
            "disagreements": disagreements,
            "agreed_decision": agreed,
            "proposed_reviewer_status": proposed,
            # Recorded only. Applying a correction to expected provisions is a separate, deliberate engineering step.
            "reviewer_proposed_expected_provisions": [list(p) for p in proposals],
            "legal_status": "not_legally_approved",
        })
    return {
        "schema_version": 1,
        "kind": "human-review benchmark candidate",
        "legal_status": LEGAL_STATUS,
        "generated_on": generated_on or dt.date.today().strftime("%d-%m-%Y"),
        "source_benchmark": {"path": str(Path(benchmark).name), "sha256": hashlib.sha256(bench_bytes).hexdigest()},
        "min_reviewers": min_reviewers,
        "submissions": [{"file": Path(s.path).name, "sha256": s.sha256, "reviewed_rows": len(s.rows),
                         "unreviewed_rows": len(s.unreviewed)} for s in submissions],
        "summary": {state: counts.get(state, 0) for state in ("reviewed", "partially_reviewed", "disputed",
                                                              "unreviewed")},
        "duplicate_chunk_ids": refs["duplicate_chunk_ids"],
        "cases": out_cases,
    }


# ---------------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------------
def _report(sub: Submission) -> None:
    status = "OK" if sub.ok else "INVALID"
    print(f"{status}: {sub.path} - {len(sub.rows)} reviewed, {len(sub.unreviewed)} unreviewed, "
          f"{len(sub.errors)} error(s)")
    for e in sub.errors[:200]:
        print(f"  error: {e}")
    for w in sub.warnings:
        print(f"  warning: {w}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    b = sp.add_parser("build-refs", help="snapshot stable chunk references from the preview index (read-only)")
    b.add_argument("--db-dir", default=PREVIEW_DB)
    b.add_argument("--out", default=REFERENCES)
    v = sp.add_parser("validate", help="validate completed reviewer CSVs")
    v.add_argument("csv", nargs="+")
    r = sp.add_parser("reconcile", help="validate, then write a reviewed-benchmark candidate")
    r.add_argument("csv", nargs="+")
    r.add_argument("--out", required=True)
    r.add_argument("--min-reviewers", type=int, default=1)
    a = ap.parse_args(argv)
    if a.cmd == "build-refs":
        data = build_references(a.db_dir)
        Path(a.out).write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {len(data['chunks'])} references; duplicate chunk ids: {list(data['duplicate_chunk_ids'])}")
        return 0
    subs = [validate(p) for p in a.csv]
    for s in subs:
        _report(s)
    if any(not s.ok for s in subs):
        return 1
    if a.cmd == "reconcile":
        out = Path(a.out).resolve()
        if out in (BENCHMARK.resolve(), TEMPLATE.resolve(), REFERENCES.resolve()):
            print("refusing to overwrite a machine input file")
            return 1
        try:
            data = reconcile(subs, min_reviewers=a.min_reviewers)
        except ValueError as e:
            print(f"error: {e}")
            return 1
        out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {out}: {data['summary']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
