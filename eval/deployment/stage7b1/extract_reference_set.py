"""Read stored vectors + chunk text from a COPY of the real index, and the benchmark questions. Writes reference_set.npz / .json.
The real index is only digested (before/after) and copied; it is never opened by Chroma."""
import json
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from backend.document_lifecycle import tree_digest  # noqa: E402

REAL = ROOT / "chroma_telangana_preview_s11"
before = tree_digest(str(REAL))
tmp = Path(tempfile.mkdtemp(prefix="kyr-7b1-idx-"))
shutil.copytree(REAL, tmp / "index")
import chromadb  # noqa: E402

col = chromadb.PersistentClient(path=str(tmp / "index")).get_collection("telangana-traffic-rules")
got = col.get(include=["embeddings", "documents", "metadatas"])
vecs = np.asarray(got["embeddings"], dtype=np.float32)
docs = list(got["documents"])
ids = list(got["ids"])
cfg = col.configuration if hasattr(col, "configuration") else None
bench = json.loads((ROOT / "eval/telangana-retrieval-benchmark.json").read_text())
questions = [c["question"] for c in bench["cases"]]
np.savez_compressed(OUT / "reference_set.npz", vecs=vecs, ids=np.array(ids))
(OUT / "reference_set.json").write_text(json.dumps({"ids": ids, "docs": docs, "questions": questions, "metadatas": got["metadatas"][:3]}, ensure_ascii=False))
norms = np.linalg.norm(vecs, axis=1)
after = tree_digest(str(REAL))
info = {"chunks": len(ids), "dims": int(vecs.shape[1]), "norm_min": float(norms.min()), "norm_max": float(norms.max()), "norm_mean": float(norms.mean()),
        "questions": len(questions), "chunk_chars_min": min(map(len, docs)), "chunk_chars_max": max(map(len, docs)),
        "non_ascii_chunks": sum(any(ord(ch) > 127 for ch in d) for d in docs), "collection_configuration": str(cfg)[:400],
        "index_digest_before": before, "index_digest_after": after, "index_unchanged": before == after}
(OUT / "reference_set_info.json").write_text(json.dumps(info, indent=1))
shutil.rmtree(tmp, ignore_errors=True)
print(json.dumps(info, indent=1))
