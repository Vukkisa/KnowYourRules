"""Compare a staging Chroma index with the reviewed source manifest: validity metadata and retrieval. Read-only.

  python3 scripts/compare_staging_validity.py --manifest M.json --db-dir chroma_telangana_staging_validity [--queries Q.txt]

Checks every chunk's valid_from / valid_to / validity_status against the manifest entry with the same sha256, lists sources
whose validity is not verified, and runs sample queries through the same temporal routing /chat uses, so the report shows what a
dated question would receive. It never writes to the index and never infers a date.
"""

import argparse
import datetime as dt
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chromadb  # noqa: E402
from langchain_core.documents import Document  # noqa: E402

from backend import build_telangana_index as btx  # noqa: E402
from backend import index_validity as iv  # noqa: E402
from backend import offence_date as od  # noqa: E402
from backend import rag_profiles as rp  # noqa: E402
from backend import tg_manifest as tm  # noqa: E402

QUERIES = ["What is the fee for a driving licence?", "helmet rules for two-wheeler riders", "registration of a new vehicle",
           "transport department notification on penalties", "rules about driving schools"]
DATES = [dt.date(2018, 5, 1), dt.date(2022, 3, 10), dt.date(2026, 9, 1)]


def main(manifest, db_dir, queries=QUERIES, embeddings=None, out=print) -> int:
    entries = tm.load_manifest(manifest)
    col = chromadb.PersistentClient(path=str(db_dir)).get_collection(btx.COLLECTION)
    got = col.get(include=["metadatas", "documents"])
    rep = iv.report(got["metadatas"], entries)
    out(f"index: {rep['chunks']} chunks from {len(rep['sources'])} sources; manifest: {len(entries)} documents")
    out(f"versioned chunks: {rep['versioned']}  unversioned chunks: {rep['unversioned']}  without validity_status: {rep['unflagged']}")
    out(f"sources with unverified validity (flagged): {len(rep['unknown'])} of {len(entries)}")
    for i in rep["unknown"]:
        out(f"  - {i}")
    out(f"inconsistencies between index and manifest: {len(rep['problems'])}")
    for p in rep["problems"][:25]:
        out(f"  ! {p}")
    by_id = {e.id: e for e in entries}
    out("per-source: id | manifest status | chunks | versioned | index status")
    for sid, row in rep["sources"].items():
        e = by_id.get(sid)
        out(f"  {sid} | {e.validity_status if e else '?'} | {row['chunks']} | {row['versioned']} | {','.join(row['status'])}")
    if embeddings is None:
        from langchain_ollama import OllamaEmbeddings
        embeddings = OllamaEmbeddings(model="nomic-embed-text")
    emb = rp.ProfileEmbeddings(embeddings, btx.PROFILE)
    out("retrieval (top 8 per query): undated routing, then each sample offence date")
    today = dt.date.today()
    for q in queries:
        res = col.query(query_embeddings=[emb.embed_query(q)], n_results=8, include=["metadatas", "documents"])
        docs = [Document(page_content=d, metadata=m) for d, m in zip(res["documents"][0], res["metadatas"][0])]
        known = {e.sha256 for e in entries}
        stray = [d for d in docs if d.metadata["sha256"] not in known]
        cur = [d for d in docs if od.in_force_today(d.metadata, today)]
        line = [f"undated: {len(cur)}/{len(docs)} usable as current law", f"outside manifest: {len(stray)}"]
        for d0 in DATES:
            r = od.route_documents(docs, d0)
            line.append(f"{d0}: authoritative {len(r.authoritative)}, unverified {len(r.unverified)}, dropped {r.dropped}")
        out(f"  {q!r}: " + "; ".join(line))
    status = Counter(m.get("validity_status", "(none)") for m in got["metadatas"])
    out(f"index validity_status counts: {dict(status)}")
    return 1 if rep["problems"] else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--db-dir", required=True)
    a = ap.parse_args()
    sys.exit(main(a.manifest, a.db_dir))
