"""Compare indexed Telangana chunks with the official source files they were built from.

Read-only technical check for the retrieval review (eval/legal-validation/). It answers one question: does the
text the index holds for a provision match the official file it cites? It says nothing about whether that file is
current or legally correct.

- No network, no API keys, no model calls. PDFs are read with the local `pdftotext` binary (poppler).
- The index is opened through SQLite in read-only mode (`mode=ro`); chromadb is not imported.
- Source files are only read. Their integrity is checked against `SHA256SUMS` in the source directory.

Usage (paths are arguments; nothing is hard-coded):

    python3 -m backend.source_compare --sources <source-documents dir> checksums
    python3 -m backend.source_compare --sources <dir> --index <chroma.sqlite3> compare "tmvr-1989-chap-8::Rule 437"
    python3 -m backend.source_compare --sources <dir> --index <chroma.sqlite3> find "tmvr-1989-chap-5" "Rule 18[0-9]"
    python3 -m backend.source_compare --sources <dir> context html-snapshots/tmvr-1989/middle-main-chap-5.htm "186\\."
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import unicodedata
from html.parser import HTMLParser
from pathlib import Path

_QUOTES = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "\xa0": " "}


# ---------------------------------------------------------------- checksums

def verify_checksums(source_dir) -> dict:
    """Check every file listed in <source_dir>/SHA256SUMS. Returns {"ok": [...], "mismatch": [...], "missing": [...]}."""
    root = Path(source_dir)
    result = {"ok": [], "mismatch": [], "missing": []}
    for line in (root / "SHA256SUMS").read_text().splitlines():
        if not line.strip():
            continue
        digest, _, rel = line.strip().partition("  ")
        rel = rel.strip().removeprefix("./")
        path = root / rel
        if not path.is_file():
            result["missing"].append(rel)
        elif hashlib.sha256(path.read_bytes()).hexdigest() == digest.lower():
            result["ok"].append(rel)
        else:
            result["mismatch"].append(rel)
    return result


# ---------------------------------------------------------------- official text

class _Visible(HTMLParser):
    _BREAKS = {"p", "br", "div", "tr", "li", "h1", "h2", "h3", "h4"}

    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if tag in self._BREAKS:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_text(raw: bytes) -> str:
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    parser = _Visible()
    parser.feed(text)
    return "".join(parser.out)


def pdf_text(path) -> str:
    """Text of a PDF via the local pdftotext binary (-layout). No network."""
    return subprocess.run(["pdftotext", "-layout", str(path), "-"], check=True, capture_output=True,
                          text=True).stdout


def official_text(source_dir, rel: str) -> str:
    path = Path(source_dir) / rel
    if path.suffix.lower() == ".pdf":
        return pdf_text(path)
    return html_text(path.read_bytes())


# ---------------------------------------------------------------- comparison

def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    for a, b in _QUOTES.items():
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip().lower()


def compare(chunk_body: str, official: str) -> dict:
    """Is the chunk body in the official text? Three levels: verbatim after whitespace/quote normalisation, the
    same ignoring all whitespace, and the longest matching prefix (to show where they diverge)."""
    nb, off = norm(chunk_body), norm(official)
    verbatim = nb in off
    no_ws = re.sub(r"\s", "", nb) in re.sub(r"\s", "", off)
    # The ingester joins PDF table-like gaps with " | ". Reported separately so it is never mistaken for a match.
    no_pipes = re.sub(r"[\s|]", "", nb) in re.sub(r"[\s|]", "", off)
    lo, hi = 0, len(nb)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if nb[:mid] in off:
            lo = mid
        else:
            hi = mid - 1
    return {"verbatim": verbatim, "ignoring_whitespace": no_ws, "ignoring_whitespace_and_pipes": no_pipes,
            "matched_prefix": lo, "length": len(nb),
            "divergence": None if verbatim else nb[max(0, lo - 40):lo + 120]}


# ---------------------------------------------------------------- index (read-only)

def index_chunks(index_path) -> list[dict]:
    """All chunk metadata rows from a Chroma SQLite file, opened read-only."""
    con = sqlite3.connect(f"file:{Path(index_path).resolve()}?mode=ro", uri=True)
    try:
        rows: dict = {}
        for eid, key, s, i, f, b in con.execute(
                "select id, key, string_value, int_value, float_value, bool_value from embedding_metadata"):
            rows.setdefault(eid, {})[key] = next((v for v in (s, i, f, b) if v is not None), None)
        return list(rows.values())
    finally:
        con.close()


def chunk_body(chunk: dict) -> str:
    """The indexed document is a one-line context header followed by the provision text."""
    return chunk["chroma:document"].partition("\n")[2]


def source_rel(chunk: dict) -> str:
    """Source file of a chunk, relative to the source-documents dir, from its `location` metadata."""
    return chunk["location"].split(" .. ")[0].split("#")[0]


def compare_provision(chunks: list[dict], source_dir, manifest_id: str, provision_id: str) -> list[dict]:
    parts = sorted((c for c in chunks if c.get("manifest_id") == manifest_id and c.get("provision_id") == provision_id),
                   key=lambda c: (c["location"], c["part"]))
    out = []
    for c in parts:
        rel = source_rel(c)
        res = compare(chunk_body(c), official_text(source_dir, rel))
        out.append({"provision": f"{manifest_id}::{provision_id}", "part": f"{c['part']}/{c['parts']}",
                    "location": c["location"], "answer_eligible": c.get("answer_eligible"),
                    "extraction_warning": c.get("extraction_warning") or "", **res})
    return out


def context(source_dir, rel: str, pattern: str, width: int = 1200, limit: int = 3) -> list[str]:
    text = re.sub(r"[ \t\xa0]+", " ", official_text(source_dir, rel))
    text = re.sub(r"\n\s*\n+", "\n", text)
    return [text[max(0, m.start() - 150):m.start() + width].replace("\n", " ¶ ")
            for m in list(re.finditer(pattern, text))[:limit]]


# ---------------------------------------------------------------- CLI

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="backend.source_compare", description=__doc__.split("\n\n")[0])
    ap.add_argument("--sources", required=True, help="source-documents directory containing SHA256SUMS")
    ap.add_argument("--index", help="Chroma SQLite file (opened read-only)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("checksums")
    c = sub.add_parser("compare")
    c.add_argument("provisions", nargs="+", help="manifest_id::provision_id")
    f = sub.add_parser("find")
    f.add_argument("manifest_id")
    f.add_argument("provision_regex")
    x = sub.add_parser("context")
    x.add_argument("rel")
    x.add_argument("pattern")
    x.add_argument("--width", type=int, default=1200)
    a = ap.parse_args(argv)

    if a.cmd == "checksums":
        r = verify_checksums(a.sources)
        print(json.dumps({k: len(v) for k, v in r.items()}))
        for k in ("mismatch", "missing"):
            for p in r[k]:
                print(f"{k}: {p}")
        return 0 if not (r["mismatch"] or r["missing"]) else 1
    if a.cmd == "context":
        for s in context(a.sources, a.rel, a.pattern, a.width):
            print(s, "\n")
        return 0
    if not a.index:
        ap.error("--index is required for compare and find")
    chunks = index_chunks(a.index)
    if a.cmd == "find":
        rx = re.compile(a.provision_regex)
        for c in sorted(chunks, key=lambda c: (c["location"], c["part"])):
            if c.get("manifest_id") == a.manifest_id and rx.fullmatch(c.get("provision_id", "")):
                print(c["provision_id"], c["part"], c["location"], c.get("provision_heading"))
        return 0
    for p in a.provisions:
        mid, _, pid = p.partition("::")
        res = compare_provision(chunks, a.sources, mid, pid)
        if not res:
            print(json.dumps({"provision": p, "in_index": False}))
        for r in res:
            print(json.dumps(r, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
