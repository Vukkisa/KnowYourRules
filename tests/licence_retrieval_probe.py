"""Run by tests/test_licence_retrieval.py in its own process: the real backend.server on a throw-away copy of a real
Telangana index (TG_DB_DIR) with real Ollama embeddings. No model is called and no approval is opened or written.
Prints one JSON document: for every question of eval/licence-retrieval-set.json and of the retrieval benchmark, the
provisions retrieve() returns with the vector-leader guard on (the default) and off (RAG_VECTOR_PROTECT=0 behaviour),
plus any retrieved chunk that is withheld (answer_eligible false) or listed as excluded by the benchmark."""
import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("GROQ_API_KEY", "offline-probe-not-real")  # never used: nothing here calls a model
logging.disable(logging.INFO)

import backend.server as srv  # noqa: E402

LIC = json.loads((ROOT / "eval" / "licence-retrieval-set.json").read_text())["cases"]
BENCH = json.loads((ROOT / "eval" / "telangana-retrieval-benchmark.json").read_text())["cases"]


def provisions(docs):
    return [f"{d.metadata.get('manifest_id')}::{d.metadata.get('provision_id')}" for d in docs]


def run(question, protect):
    srv.VECTOR_PROTECT = protect
    return srv.retrieve(question)


out = {"vector_search": srv.VECTOR_SEARCH, "default_protect": srv.VECTOR_PROTECT,
       "licence": {}, "licence_unguarded": {}, "benchmark": {}, "leaks": []}
default = out["default_protect"]
for c in LIC:
    out["licence"][c["id"]] = provisions(run(c["question"], default))
    out["licence_unguarded"][c["id"]] = provisions(run(c["question"], 0))
for c in BENCH:
    docs = run(c["question"], default)
    out["benchmark"][c["id"]] = provisions(docs)
    excluded = {x["chunk_id"].rsplit("::", 1)[0] for x in c["excluded_chunks"]}
    for d in docs:
        key = provisions([d])[0]
        if d.metadata.get("answer_eligible") is False or key in excluded:
            out["leaks"].append([c["id"], key])
for c in LIC:  # the licence questions too
    for d in run(c["question"], default):
        if d.metadata.get("answer_eligible") is False:
            out["leaks"].append([c["id"], provisions([d])[0]])
print(json.dumps(out))
