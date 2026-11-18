"""Run by tests/test_lifecycle_parity_real.py in its own process: retrieve() for every question of the retrieval benchmark on
the real backend (temporary index copy, real Ollama query embeddings). Prints {question: [chunk identity digests]}.
No model is called. Whether the lifecycle filter is active is decided by TG_LIFECYCLE_DIR in the environment."""
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
logging.disable(logging.INFO)

import real_backend_probe as probe  # noqa: E402

from backend import document_lifecycle  # noqa: E402

srv = probe.srv


def run(cases):
    return {c["id"]: [[srv.chunk_identity(d), d.metadata["sha256"]] for d in srv.retrieve(c["question"])] for c in cases}


def main():
    """Both retrievals run in this ONE process on one open store, because HNSW results can differ between separate opens of
    identical copies (Stage 15); within a process they are repeatable. 'unfiltered' = lifecycle filter off, 'filtered' = as
    configured by TG_LIFECYCLE_DIR."""
    probe.open_grounded_gate(srv.vector_store.get(include=["metadatas"]))
    cases = json.loads((ROOT / "eval" / "telangana-retrieval-benchmark.json").read_text())["cases"]
    configured = srv.LIFECYCLE
    srv.LIFECYCLE = document_lifecycle.ServeFilter(None)
    unfiltered = run(cases)
    srv.LIFECYCLE = configured
    filtered = run(cases)
    print(json.dumps({"vector_search": srv.VECTOR_SEARCH, "lifecycle_enabled": configured.enabled,
                      "unfiltered": unfiltered, "filtered": filtered}))


if __name__ == "__main__":
    main()
