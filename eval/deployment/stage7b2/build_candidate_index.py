"""Stage 7B.2: build a COMPLETELY SEPARATE candidate Chroma index (bge-small-en-v1.5, 384-d) from the 590 chunks of the real index.
Same ids, documents and metadata (source ids, hashes, provenance, answer_eligible, ...); only the vectors differ. The real index is read
only through a copy made by Stage 7B.1 (chunk_metadata.json / reference_set.json). usage: python3 build_candidate_index.py"""
import json
import shutil
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
import chromadb  # noqa: E402
from backend import document_lifecycle as dl  # noqa: E402

OUT = HERE / "candidate" / "index_bge_small"


def main():
    before = dl.tree_digest(ROOT / "chroma_telangana_preview_s11")
    ref = json.loads((ROOT / "eval/deployment/stage7b1/reference_set.json").read_text())
    meta = json.loads((HERE / "candidate" / "chunk_metadata.json").read_text())
    assert meta["ids"] == ref["ids"]
    vec = np.load(HERE / "candidate" / "bge_small_vectors.npz")["docs"]
    shutil.rmtree(OUT, ignore_errors=True)
    col = chromadb.PersistentClient(path=str(OUT)).create_collection(
        "telangana-traffic-rules", metadata=meta["collection_metadata"],
        configuration={"hnsw": {"space": "l2", "ef_construction": 100, "ef_search": 100, "max_neighbors": 16}})
    for i in range(0, len(vec), 200):
        col.add(ids=ref["ids"][i:i + 200], documents=ref["docs"][i:i + 200], metadatas=meta["metadatas"][i:i + 200], embeddings=vec[i:i + 200].tolist())
    print("candidate chunks:", col.count(), "dims:", vec.shape[1], "config:", col.configuration)
    print("candidate index tree digest:", dl.tree_digest(OUT))
    assert dl.tree_digest(ROOT / "chroma_telangana_preview_s11") == before, "REAL INDEX CHANGED"
    print("real index unchanged:", before)


if __name__ == "__main__":
    main()
