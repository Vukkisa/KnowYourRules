"""Stage 7B.2 Path A on LINUX under a cgroup limit: ONE process = the real FastAPI backend module (backend.server, cloud requirements
only) opened on a COPY of the real index, with the exact nomic-embed-text-v1.5 numpy engine attached as the in-process query embedder, then
real retrievals (embed + exact search + BM25 + fusion). Reads the container's cgroup counters. No network use, no Ollama, no model call.
Runs inside the container started by run_linux.sh. Prints one JSON line."""
import json
import os
import statistics
import sys
import threading
import time
from pathlib import Path

T0 = time.perf_counter()
sys.path.insert(0, "/app")
sys.path.insert(0, "/app/eval/deployment/stage7b1")
import psutil  # noqa: E402

PROC = psutil.Process()
CG = Path("/sys/fs/cgroup")
MARKS = {}


def cg(name):
    try:
        return (CG / name).read_text().strip()
    except OSError:
        return None


def mark(name):
    cur, peak = cg("memory.current"), cg("memory.peak")
    MARKS[name] = {"rss_mb": round(PROC.memory_info().rss / 2**20, 1), "cgroup_current_mb": round(int(cur) / 2**20, 1) if cur else None,
                   "cgroup_peak_mb": round(int(peak) / 2**20, 1) if peak and peak.isdigit() else None, "t": round(time.perf_counter() - T0, 2)}
    print("MARK", name, MARKS[name], file=sys.stderr, flush=True)


class Adapter:
    """Replaces the provider client under the profile wrapper; the profile still adds the nomic task prefixes."""
    model, provider = "nomic-embed-text", "in-process-numpy"

    def __init__(self, eng):
        self.eng = eng

    def embed_query(self, text):
        return self.eng.embed([text])[0].tolist()

    def embed_documents(self, texts):
        return [v.tolist() for v in self.eng.embed(list(texts))]


def main():
    mark("python+psutil")
    import backend.server as srv
    mark("import backend.server (store+exact+BM25 built)")
    from backend import document_lifecycle as dl
    from nomic_numpy import NomicNumpy
    srv.LIFECYCLE = dl.ServeFilter(None)          # measure the search itself (the real registry quarantines everything)
    eng = NomicNumpy("/data/nomic.gguf", "/data/tokenizer.json")
    mark("numpy engine constructed (weights mmapped)")
    srv.embeddings_model.base = Adapter(eng)
    cases = json.loads(Path("/app/eval/telangana-retrieval-benchmark.json").read_text())["cases"]
    qs = [c["question"] for c in cases]
    out = {"vector_search": srv.VECTOR_SEARCH, "chunks": len(srv.EXACT_INDEX) if srv.EXACT_INDEX is not None else None,
           "cgroup": {k: cg(k) for k in ("memory.max", "memory.swap.max", "cpu.max")}}
    srv.retrieve(qs[0])
    mark("first retrieval (cold)")
    lat, errs = [], []
    NSEQ = int(os.environ.get("KYR_NSEQ", "40"))
    for q in qs[1:1 + NSEQ]:
        t = time.perf_counter()
        try:
            srv.retrieve(q)
            lat.append(time.perf_counter() - t)
            print("retrieval", len(lat), round(lat[-1], 2), "s", file=sys.stderr, flush=True)
        except Exception as e:   # noqa: BLE001
            errs.append(type(e).__name__)
    mark("after 40 sequential retrievals")
    out["sequential_ms"] = {"n": len(lat), "p50": round(statistics.median(lat) * 1000), "p95": round(sorted(lat)[max(int(len(lat) * .95) - 1, 0)] * 1000),
                            "max": round(max(lat) * 1000), "errors": errs}
    conc = {}
    pos = 41
    for n in ((4,) if os.environ.get("KYR_CONC", "1") == "1" else ()):
        lats, cerrs = [], []

        def worker(i, qq):
            t = time.perf_counter()
            try:
                srv.retrieve(qq)
                lats.append(time.perf_counter() - t)
            except Exception as e:   # noqa: BLE001
                cerrs.append(type(e).__name__)
        for rnd in range(3):
            ths = [threading.Thread(target=worker, args=(i, qs[pos + rnd * n + i])) for i in range(n)]
            t = time.perf_counter()
            [x.start() for x in ths]
            [x.join() for x in ths]
            conc[f"round{rnd + 1}_wall_s"] = round(time.perf_counter() - t, 2)
        conc.update({"concurrent": n, "ok": len(lats), "errors": cerrs, "p50_ms": round(statistics.median(lats) * 1000) if lats else None,
                     "max_ms": round(max(lats) * 1000) if lats else None})
    out["concurrency"] = conc
    mark("after 3 rounds of 4 concurrent retrievals")
    out["cgroup_end"] = {k: cg(k) for k in ("memory.events", "memory.peak", "memory.current", "cpu.stat")}
    out["cpu_seconds_total"] = round(int(dict(l.split() for l in cg("cpu.stat").splitlines())["usage_usec"]) / 1e6, 1)
    out["marks"] = MARKS
    print(json.dumps(out))


if __name__ == "__main__":
    main()
