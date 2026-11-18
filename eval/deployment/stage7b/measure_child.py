"""One measured process. usage: measure_child.py server|components   env: KYR_BLOCK=1 hides transformers/torch/langchain_ollama/boto3
(what the cloud requirements file does not install). Prints one JSON line. Memory is RSS of THIS process only."""
import json
import os
import resource
import statistics
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
T0 = time.perf_counter()
if os.environ.get("KYR_BLOCK") == "1":
    for m in ("transformers", "torch", "langchain_ollama", "boto3", "botocore", "sentence_transformers", "tensorflow"):
        sys.modules[m] = None   # `import m` raises ImportError, as if it were not installed
import psutil  # noqa: E402

PROC = psutil.Process()
MARKS = {}


def peak_mb():
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return r / 2**20 if sys.platform == "darwin" else r / 1024


def mark(name):
    MARKS[name] = {"rss_mb": round(PROC.memory_info().rss / 2**20, 1), "peak_mb": round(peak_mb(), 1), "t": round(time.perf_counter() - T0, 2)}


def deep_size(o, seen=None):
    seen = seen if seen is not None else set()
    if id(o) in seen:
        return 0
    seen.add(id(o))
    n = sys.getsizeof(o)
    if isinstance(o, dict):
        n += sum(deep_size(k, seen) + deep_size(v, seen) for k, v in o.items())
    elif isinstance(o, (list, tuple, set, frozenset)):
        n += sum(deep_size(i, seen) for i in o)
    elif hasattr(o, "__dict__"):
        n += deep_size(vars(o), seen)
    return n


def server():
    mark("python+psutil")
    import chromadb  # noqa: F401
    mark("import chromadb")
    import fastapi, langchain, langchain_chroma, requests  # noqa: F401,E401
    mark("import fastapi/langchain/langchain_chroma")
    t = time.perf_counter()
    import backend.server as srv
    MARKS["server_import_seconds"] = round(time.perf_counter() - t, 2)
    mark("import backend.server (snapshot+store+exact+bm25)")
    out = {"vector_search": srv.VECTOR_SEARCH, "snapshot": srv.SNAPSHOT.public(), "embedding_state": srv.EMBEDDING.health().get("state"),
           "modules_loaded": {m: (m in sys.modules and sys.modules[m] is not None) for m in ("torch", "transformers", "langchain_ollama", "boto3")}}
    from fastapi.testclient import TestClient
    from backend import document_lifecycle as dl
    client = TestClient(srv.app)
    st = client.get("/status").json()
    mark("TestClient + /status")
    out["status"] = {"index": st.get("index"), "chunks": st.get("chunks"), "corpus_ready": st.get("corpus_ready")}
    cases = json.loads((ROOT / "eval" / "telangana-retrieval-benchmark.json").read_text())["cases"]
    qs = [c["question"] for c in cases]
    srv.LIFECYCLE = dl.ServeFilter(None)   # measure the search itself (the real registry quarantines everything, so nothing would be searched)
    lat = []
    for q in qs[:40]:
        t = time.perf_counter()
        srv.retrieve(q)
        lat.append(time.perf_counter() - t)
    mark("after 40 sequential retrievals (embed+exact+BM25+fusion)")
    out["sequential_ms"] = {"p50": round(statistics.median(lat) * 1000), "p95": round(sorted(lat)[int(len(lat) * .95) - 1] * 1000), "max": round(max(lat) * 1000)}
    conc = {}
    for n in (1, 4, 8, 16):
        lats, errs = [], []

        def worker(i):
            for q in qs[40 + i:40 + i + 6]:
                t = time.perf_counter()
                try:
                    srv.retrieve(q)
                    lats.append(time.perf_counter() - t)
                except Exception as e:   # noqa: BLE001
                    errs.append(type(e).__name__ + ":" + str(getattr(e, "reason", ""))[:30])
        t = time.perf_counter()
        ths = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        [th.start() for th in ths]
        [th.join() for th in ths]
        wall = time.perf_counter() - t
        conc[n] = {"requests": n * 6, "ok": len(lats), "errors": sorted(set(errs)), "n_errors": len(errs), "wall_s": round(wall, 2),
                   "p50_ms": round(statistics.median(lats) * 1000) if lats else None,
                   "p95_ms": round(sorted(lats)[max(int(len(lats) * .95) - 1, 0)] * 1000) if lats else None,
                   "peak_mb": round(peak_mb(), 1), "rss_mb": round(PROC.memory_info().rss / 2**20, 1)}
    out["concurrency"] = conc
    mark("after concurrency 1/4/8/16")
    out["marks"] = MARKS
    print(json.dumps(out))


def components():
    mark("python+psutil")
    import chromadb
    mark("import chromadb")
    from langchain_chroma import Chroma
    mark("import langchain_chroma")
    from backend import exact_vector, hybrid_retrieval
    mark("import exact_vector+hybrid_retrieval")

    class NoEmbed:
        def embed_query(self, t): raise RuntimeError("not used")
        def embed_documents(self, t): raise RuntimeError("not used")
    store = Chroma(collection_name="telangana-traffic-rules", embedding_function=NoEmbed(), persist_directory=os.environ["TG_DB_DIR"],
                   create_collection_if_not_exists=False)
    mark("open Chroma collection (hnsw loaded lazily)")
    got = store._collection.get(include=["embeddings", "documents", "metadatas"])
    mark("read all embeddings+documents+metadatas")
    out = {"chunks": len(got["ids"])}
    idx = exact_vector.ExactVectorIndex.from_store(store)
    mark("build ExactVectorIndex (float64 matrix)")
    out["exact_matrix_mb"] = round(idx.matrix.nbytes / 2**20, 2)
    import gc
    del got
    gc.collect()
    lex = hybrid_retrieval.LexicalIndex.from_store(store)
    mark("build LexicalIndex (BM25 + provision lookup)")
    out["bm25_python_objects_mb"] = round(deep_size(lex) / 2**20, 2)
    out["exact_python_objects_mb"] = round(deep_size(idx) / 2**20, 2)
    out["marks"] = MARKS
    print(json.dumps(out))


if __name__ == "__main__":
    {"server": server, "components": components}[sys.argv[1]]()
