"""Stage 7B.2 Path A, independent run: the exact nomic-embed-text-v1.5 weights (Ollama's GGUF blob) in the torch-free numpy engine of
Stage 7B.1, compared with (1) fresh vectors from the local Ollama server and (2) the vectors STORED in the real index (copied by 7B.1).
Also: load time, RSS, single-query latency, concurrent-request behaviour, CPU time. Threads are fixed by the caller's environment
(VECLIB_MAXIMUM_THREADS / OMP_NUM_THREADS). usage: python3 pathA_independent.py <label> <out.json>"""
import json
import os
import resource
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import psutil
import requests

ROOT = Path(__file__).resolve().parents[3]
E71 = ROOT / "eval/deployment/stage7b1"
sys.path.insert(0, str(E71))
from gguf_reader import ollama_blob  # noqa: E402
from nomic_numpy import NomicNumpy  # noqa: E402

label, outp = sys.argv[1], sys.argv[2]
WITH_DOCS = len(sys.argv) > 3 and sys.argv[3] == "docs"      # documents are embedded at BUILD time on the operator machine; the cloud only embeds queries
TOKENIZER = Path(__file__).resolve().parent / "pathA" / "tokenizer.json"   # derived once from the GGUF vocabulary (7B.1 build_tokenizer); no torch needed to use it
proc = psutil.Process()
mb = lambda: round(proc.memory_info().rss / 2**20, 1)  # noqa: E731


def ollama(text):
    r = requests.post("http://127.0.0.1:11434/api/embed", json={"model": "nomic-embed-text", "input": text}, timeout=120).json()
    return np.asarray(r["embeddings"][0], dtype=np.float32)


ref = json.loads((E71 / "reference_set.json").read_text())
stored = np.load(E71 / "reference_set.npz")
assert list(stored["ids"]) == ref["ids"]
res = {"label": label, "threads_env": {k: os.environ.get(k) for k in ("VECLIB_MAXIMUM_THREADS", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS")},
       "rss_mb": {"python+numpy start": mb()}}
t0 = time.perf_counter()
blob = ollama_blob()[1] if isinstance(ollama_blob(), tuple) and len(ollama_blob()) > 1 else "ollama blob"
cpu0 = proc.cpu_times()
eng = NomicNumpy(ollama_blob()[0], str(TOKENIZER))
res["load_seconds"], res["blob"] = round(time.perf_counter() - t0, 2), blob
res["rss_mb"]["after model load"] = mb()

qs = ["search_query: " + q for q in ref["questions"]]
lat, cos_o, tcpu = [], [], proc.cpu_times()
for q in qs:
    t = time.perf_counter()
    v = eng.embed([q])[0]
    lat.append((time.perf_counter() - t) * 1000)
    cos_o.append(float(v @ ollama(q)))
cpu1 = proc.cpu_times()
res["rss_mb"]["after 108 queries"] = mb()
res["queries_vs_ollama_cosine"] = {"n": len(cos_o), "min": min(cos_o), "mean": float(np.mean(cos_o))}
res["query_latency_ms"] = {"p50": round(float(np.percentile(lat, 50)), 1), "p95": round(float(np.percentile(lat, 95)), 1), "max": round(max(lat), 1)}
res["cpu_seconds_per_query"] = round(((cpu1.user + cpu1.system) - (tcpu.user + tcpu.system)) / len(qs), 3)

idx = list(range(0, len(ref["docs"]), 5)) if WITH_DOCS else []                      # every 5th chunk: 118 documents, a spread over every document
cos_o2, cos_s, dl = [], [], []
for i in idx:
    t = time.perf_counter()
    v = eng.embed(["search_document: " + ref["docs"][i]])[0]
    dl.append((time.perf_counter() - t) * 1000)
    cos_s.append(float(v @ stored["vecs"][i]))
    cos_o2.append(float(v @ ollama("search_document: " + ref["docs"][i])))
if idx:
    res["documents_vs_stored_index_cosine"] = {"n": len(cos_s), "min": min(cos_s), "mean": float(np.mean(cos_s))}
    res["documents_vs_ollama_cosine"] = {"n": len(cos_o2), "min": min(cos_o2), "mean": float(np.mean(cos_o2))}
    res["document_latency_ms"] = {"p50": round(float(np.percentile(dl, 50)), 1), "p95": round(float(np.percentile(dl, 95)), 1), "max": round(max(dl), 1)}
res["rss_mb"]["after documents (longest chunk 3681 chars)"] = mb()

# concurrency: 4 simultaneous single-query requests, 3 rounds, wall time vs one request
def one(q, out, i):
    t = time.perf_counter()
    eng.embed([q])
    out[i] = (time.perf_counter() - t) * 1000
rounds = []
for r in range(3):
    out = [0] * 4
    th = [threading.Thread(target=one, args=(qs[r * 4 + i], out, i)) for i in range(4)]
    t = time.perf_counter()
    [x.start() for x in th]
    [x.join() for x in th]
    rounds.append({"wall_ms": round((time.perf_counter() - t) * 1000, 1), "per_request_ms": [round(x, 1) for x in out]})
res["concurrent_4_requests"] = rounds
res["rss_mb"]["after concurrency"] = mb()
res["ru_maxrss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20, 1)   # macOS: bytes
res["machine"] = {"cpu": "Apple M1", "logical_cpus": os.cpu_count(), "note": "macOS: no cgroup / 0.1 CPU limit is possible here"}
Path(outp).write_text(json.dumps(res, indent=1))
print(json.dumps({k: res[k] for k in res if k not in ("machine", "threads_env", "concurrent_4_requests")}, indent=1)); print("concurrent:", res["concurrent_4_requests"])
