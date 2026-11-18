"""Coverage tooling for the provision-validity ledger (Step 5). DEVELOPMENT TOOL: the server never imports it.

Read-only: maps each chunk to the exact provision identifiers it already carries, so humans can later prepare a real ledger's
``coverage`` section. It approves nothing and invents nothing: every proposal is ``status: "proposed"``, with no provision key, no
decision and no date. "verified" means only that a chunk is reproduced exactly from a hash-checked source file AND is present,
byte for byte, in the index; it says nothing about legal validity. The index is read straight from its SQLite file
(``mode=ro&immutable=1``): no Chroma client, nothing written. Output goes only under ``dev-output/``.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote

from backend import tg_ingest, tg_manifest
from backend.tg_manifest import SHA256_RE, sha256_file

SELECTOR_KEYS = ("manifest_id", "sha256", "provision_id", "part", "parts", "page_start", "page_end", "text_sha256")  # == provision_validity's (a test pins it)
CLASSES = ("verified", "candidate", "ambiguous", "unmapped")
MAX_LISTED = 200
STATEMENT = ("DEVELOPMENT OUTPUT, NOT A LEDGER. Nothing here approves any source, provision, mapping or date. 'verified' means only that a "
             "chunk is reproduced exactly from a hash-checked source file and present byte for byte in the index. Instrument keys, "
             "commencement dates and decisions are not supplied and must come from counsel.")


class ReadError(Exception):
    """An input could not be read safely."""


class OutputRefused(Exception):
    """The output location is not allowed."""


def selector_for(md, text):
    """The exact selector (the ledger's own keys) of a chunk, or None if its metadata is malformed. Nothing is repaired or guessed."""
    if not (isinstance(md, dict) and isinstance(text, str) and text.strip()
            and all(isinstance(md.get(k), str) and md[k].strip() for k in ("manifest_id", "provision_id"))
            and SHA256_RE.match(str(md.get("sha256")))
            and all(type(md.get(k)) is int for k in ("part", "parts", "page_start", "page_end")) and 1 <= md["part"] <= md["parts"]):
        return None
    return {**{k: md[k] for k in SELECTOR_KEYS[:-1]}, "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def identity(sel):
    """The provision a chunk belongs to (label, part). Chunks sharing it are siblings; only a FULL selector match is a mapping."""
    return tuple(sel[k] for k in ("manifest_id", "sha256", "provision_id", "part", "parts"))


def read_index_chunks(db_dir):
    """Every chunk of a Chroma directory, read read-only from its SQLite file. Raises ReadError on anything unexpected."""
    path = Path(db_dir) / "chroma.sqlite3"
    if not path.is_file() or path.is_symlink():
        raise ReadError("no chroma.sqlite3 in the index directory")
    before = sha256_file(path)
    try:
        con = sqlite3.connect(f"file:{quote(str(path.resolve()))}?mode=ro&immutable=1", uri=True)
        try:
            con.execute("PRAGMA query_only = ON")
            names = dict(con.execute("SELECT id, name FROM collections"))
            rows = con.execute("SELECT e.id, e.embedding_id, s.collection FROM embeddings e JOIN segments s ON s.id = e.segment_id "
                               "WHERE s.scope = 'METADATA' ORDER BY e.id").fetchall()
            meta = defaultdict(dict)
            for rid, key, sv, iv, fv, bv in con.execute("SELECT id, key, string_value, int_value, float_value, bool_value FROM embedding_metadata"):
                meta[rid][key] = sv if sv is not None else iv if iv is not None else fv if fv is not None else None if bv is None else bool(bv)
        finally:
            con.close()
    except sqlite3.Error as exc:
        raise ReadError(f"the index could not be read ({exc.__class__.__name__})") from None
    if sha256_file(path) != before:
        raise ReadError("the index file changed while it was read")
    chunks = [{"id": str(eid), "metadata": {k: v for k, v in meta.get(rid, {}).items() if k != "chroma:document"},
               "text": meta.get(rid, {}).get("chroma:document")} for rid, eid, _ in rows]
    return {"chunks": chunks, "collections": sorted({names.get(c, "?") for _, _, c in rows}), "sha256": before}


def read_source_chunks(manifest_path, corpus_dir):
    """Re-chunk every held source file exactly as the index builder does (offline, deterministic). A draft, missing, unreadable or
    hash-mismatched file yields no chunks and is reported by its ``file_state``."""
    docs, chunks = [], []
    for e in tg_manifest.load_manifest(manifest_path):
        errors = tg_manifest.file_errors([e], corpus_dir)
        state = ("draft" if e.source_class == "draft" else "ok" if not errors else "stale_hash" if "sha256 does not match" in errors[0]
                 else "missing" if "not found" in errors[0] else "unreadable")
        if state == "ok":
            try:
                made = tg_ingest.chunk_document(tg_ingest.load_blocks(Path(corpus_dir) / e.file, e.format, e.file), e,
                                                tg_ingest.snapshot_chapter(corpus_dir, e.file))
                chunks += [{"id": f"{e.id}#{i}", "metadata": dict(d.metadata), "text": d.page_content} for i, d in enumerate(made)]
            except Exception:  # noqa: BLE001 - one unreadable source must not hide the others
                state = "unreadable"
        docs.append({"entry": e, "file_state": state})
    return {"documents": docs, "chunks": chunks}


def analyze(source, index=None, *, registry=None, index_error=None):
    """The coverage report (a JSON-serialisable dict). ``index`` is ``read_index_chunks``' result, or None."""
    entries = {d["entry"].id: d["entry"] for d in source["documents"]}
    held = {d["entry"].id: d["entry"].sha256 for d in source["documents"] if d["file_state"] == "ok"}
    known = {e.sha256 for e in entries.values()}
    src = [(c, selector_for(c["metadata"], c["text"])) for c in source["chunks"]]
    idx = [(c, selector_for(c["metadata"], c["text"])) for c in (index["chunks"] if index else [])]
    src_by, idx_by = defaultdict(list), defaultdict(list)
    for by, rows in ((src_by, src), (idx_by, idx)):
        for _, sel in rows:
            if sel:
                by[identity(sel)].append(sel)

    results = []          # one row per chunk: source chunks first, then index chunks the sources cannot account for

    def add(cls, origin, c, sel, *reasons, deployed=None):
        m = c["metadata"] if isinstance(c["metadata"], dict) else {}
        results.append({"class": cls, "origin": origin, "chunk_id": c["id"], "reasons": list(reasons), "deployed_selector": deployed,
                        "manifest_id": m.get("manifest_id"),
                        "provision_id": m.get("provision_id"), "selector": sel,
                        "validity_metadata": {k: m[k] for k in ("validity_status", "valid_from", "valid_to") if k in m}})

    for c, sel in src:
        if sel is None:
            add("unmapped", "source", c, None, "malformed_metadata")
            continue
        hits = idx_by.get(identity(sel), [])
        if src_by[identity(sel)].count(sel) > 1:          # identical in every field, pages and text included (the ledger rejects it)
            add("ambiguous", "source", c, sel, "duplicate_selector_in_source")
        elif index is None:
            add("candidate", "source", c, sel, "index_unreadable" if index_error else "index_not_supplied")
        elif hits.count(sel) > 1:
            add("ambiguous", "source", c, sel, "duplicate_selector_in_index")
        elif sel in hits:
            add("verified", "source", c, sel)
        else:
            add("candidate", "source", c, sel, "index_text_or_pages_differ_from_source" if hits else "not_indexed",
                deployed=hits[0] if len(hits) == 1 else None)      # the one deployed chunk for this provision part: its own selector is what is served
    for c, sel in idx:
        if sel is None:
            add("unmapped", "index", c, None, "malformed_metadata")
        elif idx_by[identity(sel)].count(sel) > 1:
            if sel not in src_by.get(identity(sel), []):                  # otherwise the source-side row already carries the ambiguity
                add("ambiguous", "index", c, sel, "duplicate_selector_in_index")
        elif sel["sha256"] not in known:
            add("unmapped", "index", c, sel, "stale_or_unknown_source_hash")
        elif sel["sha256"] not in held.values():
            add("unmapped", "index", c, sel, "source_file_not_held_or_stale")
        elif held.get(sel["manifest_id"]) != sel["sha256"]:
            add("unmapped", "index", c, sel, "manifest_id_does_not_match_hash")
        elif identity(sel) not in src_by:
            add("unmapped", "index", c, sel, "no_source_chunk_for_this_provision")

    parts = defaultdict(set)                                      # provisions the sources contain: (manifest_id, provision_id) -> parts
    for sels in src_by.values():
        for s in sels:
            parts[(s["manifest_id"], s["provision_id"])].add(s["part"])
    have = defaultdict(set)
    for i in idx_by:
        have[(i[0], i[2])].add(i[3])
    missing = [{"manifest_id": m, "provision_id": p} for (m, p) in sorted(parts) if not have.get((m, p))] if index else []
    gaps = [{"manifest_id": m, "provision_id": p, "missing_parts": sorted(ps - have[(m, p)])}
            for (m, p), ps in sorted(parts.items()) if index and have.get((m, p)) and not ps <= have[(m, p)]]
    labels = defaultdict(set)
    for m, p in parts:
        labels[p].add(m)

    docs = []
    for d in source["documents"]:
        e = d["entry"]
        status = registry.lookup(e.sha256).status if registry is not None else "registry_not_supplied"
        docs.append({"manifest_id": e.id, "file": e.file, "sha256": e.sha256, "source_class": e.source_class,
                     "verification_status": e.verification_status, "file_state": d["file_state"], "registry_status": status,
                     "source_pending_or_unapproved": status != "verified_current" or e.verification_status != "verified",
                     "approval": "not evaluated by this tool", "source_chunks": sum(1 for c, _ in src if c["metadata"].get("manifest_id") == e.id),
                     "indexed_chunks": sum(1 for c, _ in idx if c["metadata"].get("manifest_id") == e.id)})
    pending = {d["manifest_id"]: d for d in docs}
    proposals = []
    for r in results:
        if r["origin"] == "source" and r["class"] in ("verified", "candidate"):
            blocked = ["instrument key and provision keys not assigned (counsel)", "no decision_ref (counsel)"]
            d = pending[r["manifest_id"]]
            if d["source_pending_or_unapproved"]:
                blocked.append(f"source is pending or unapproved (registry status: {d['registry_status']})")
            if r["class"] == "candidate":
                blocked.append("candidate, not verified: " + ", ".join(r["reasons"]))
            dep = r.get("deployed_selector")
            proposals.append({"selector": dep or r["selector"], "source_selector": r["selector"] if dep else None,
                              "provisions": [], "decision_ref": None, "status": "proposed",
                              "mapping_class": r["class"], "source_provision_label": r["provision_id"],
                              "loadable_as_ledger_coverage": False, "blocked_by": blocked})

    def listing(cls):
        rows = [r for r in results if r["class"] == cls]
        return {"items": rows[:MAX_LISTED], "omitted": max(0, len(rows) - MAX_LISTED)}

    return {"kind": "validity-coverage-report", "development_only": True, "not_a_ledger": True, "statement": STATEMENT,
            "inputs": {"documents": len(docs), "source_chunks": len(src), "index_chunks": len(idx) if index else None,
                       "index_state": "read" if index else "unreadable" if index_error else "not_supplied", "index_error": index_error,
                       "index_collections": index["collections"] if index else [], "index_file_sha256": index["sha256"] if index else None},
            "chunk_counts": {c: sum(1 for r in results if r["class"] == c) for c in CLASSES},
            "provisions": {"in_source": len(parts), "without_indexed_chunks": len(missing) if index else None,
                           "with_missing_parts": len(gaps) if index else None,
                           "labels_shared_by_several_documents": sum(1 for v in labels.values() if len(v) > 1)},
            "documents": docs, "provisions_without_indexed_chunks": missing[:MAX_LISTED], "provisions_with_missing_parts": gaps[:MAX_LISTED],
            "ambiguous": listing("ambiguous"), "unmapped": listing("unmapped"), "candidates": listing("candidate"),
            "provision_labels_shared_by_several_documents": sorted(p for p, v in labels.items() if len(v) > 1)[:MAX_LISTED],
            "validity_metadata_present_on_chunks": dict(Counter(k for r in results for k in r["validity_metadata"])),
            "proposed_coverage": proposals}


def render_markdown(rep):
    c, p, i = rep["chunk_counts"], rep["provisions"], rep["inputs"]
    out = ["# Validity coverage report (DEVELOPMENT OUTPUT, NOT A LEDGER)", "", rep["statement"], "", "## Inputs",
           f"- Documents: {i['documents']}; chunks reproduced from held sources: {i['source_chunks']}; index: {i['index_state']}"
           + (f" ({i['index_error']})" if i["index_error"] else "") + f"; chunks read from the index: {i['index_chunks']}", "",
           "## Chunk mapping", "| Class | Chunks |", "|---|---:|", *[f"| {k} | {c[k]} |" for k in CLASSES], "",
           "verified = identical selector in source and index (unique); candidate = reproduced from a held source but not confirmed in "
           "the index; ambiguous = a selector identical in every field occurs twice; unmapped = malformed metadata or an index chunk no held source reproduces.",
           "", "## Provisions", f"- In the source files: {p['in_source']}", f"- With no indexed chunk: {p['without_indexed_chunks']}",
           f"- With parts missing from the index: {p['with_missing_parts']}",
           f"- Labels shared by several documents: {p['labels_shared_by_several_documents']}", "", "## Documents",
           "| Manifest id | File state | Registry status | Pending/unapproved | Source chunks | Indexed chunks |", "|---|---|---|---|---:|---:|",
           *[f"| {d['manifest_id']} | {d['file_state']} | {d['registry_status']} | {'yes' if d['source_pending_or_unapproved'] else 'no'} | "
             f"{d['source_chunks']} | {d['indexed_chunks']} |" for d in rep["documents"]]]
    for title, rows, total in (("Provisions with no indexed chunk", rep["provisions_without_indexed_chunks"], p["without_indexed_chunks"]),
                               *[(t, rep[k]["items"], len(rep[k]["items"]) + rep[k]["omitted"])
                                 for t, k in (("Ambiguous chunks", "ambiguous"), ("Unmapped chunks", "unmapped"), ("Candidate chunks", "candidates"))]):
        out += ["", f"## {title}"] + ([f"- {r['manifest_id']} / {r['provision_id']}" + (f": {', '.join(r['reasons'])}" if "reasons" in r else "")
                                      for r in rows[:50]] or ["None."])
        if (total or 0) > min(len(rows), 50):
            out.append(f"- ... and {total - min(len(rows), 50)} more (see the JSON report)")
    return "\n".join(out + ["", f"## Proposed coverage entries: {len(rep['proposed_coverage'])}",
                            "Each is `status: proposed` with no provision key and no decision; none can be loaded as ledger coverage as it stands.", ""])


def check_output_dir(out_dir, repo_root, *, protected=()):
    """The resolved output directory, or OutputRefused. Only a real directory under <repo>/dev-output, never overlapping an input."""
    root, raw = Path(repo_root).resolve(), Path(out_dir)
    out = raw.resolve()
    if raw.is_symlink() or (root / "dev-output").resolve() not in out.parents:
        raise OutputRefused("output must be a (non-link) directory under dev-output/")
    if any(out == Path(g).resolve() or Path(g).resolve() in out.parents or out in Path(g).resolve().parents for g in protected):
        raise OutputRefused("output overlaps an input")
    if out.is_dir() and any(out.glob("*.sqlite3")):
        raise OutputRefused("output next to an index is refused")
    return out


def write_report(rep, out_dir, repo_root, *, protected=(), overwrite=False):
    """Write exactly coverage-report.json and coverage-report.md. Never overwrites unless asked; writes nowhere else."""
    out = check_output_dir(out_dir, repo_root, protected=protected)
    files = {"coverage-report.json": json.dumps(rep, indent=2, sort_keys=True) + "\n", "coverage-report.md": render_markdown(rep)}
    out.mkdir(parents=True, exist_ok=True)
    if not overwrite and any((out / n).exists() or (out / n).is_symlink() for n in files):
        raise OutputRefused("a report already exists here (use overwrite)")
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf-8")
    return [str(out / n) for n in files]
