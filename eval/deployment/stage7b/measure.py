"""Stage 7B resource preflight. Reproduce:  python3 eval/deployment/stage7b/measure.py   (needs local Ollama with nomic-embed-text)
Everything runs on temporary COPIES of the real index and the real lifecycle registry; their digests are checked before and after.
The 'hosted provider' is a local relay of real Ollama vectors (no external host is contacted), so embedding LATENCY here is
Ollama's, not a hosted provider's; the MEMORY of the client path (HTTP, JSON, validation) is real."""
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psutil
import requests

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
HERE = Path(__file__).resolve().parent
KEY = "kyr-measure-key-0123456789"
INDEX = ROOT / "chroma_telangana_preview_s11"
REGISTRY = ROOT / "legal" / "lifecycle"
from backend import document_lifecycle as dl  # noqa: E402
from backend import index_snapshot as snap  # noqa: E402
from backend.embedding_provider import INDEX_FAMILY  # noqa: E402


def ollama_embed(texts):
    r = requests.post("http://127.0.0.1:11434/api/embed", json={"model": "nomic-embed-text", "input": list(texts)}, timeout=120)
    r.raise_for_status()
    return r.json()["embeddings"]


class Relay(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        vecs = ollama_embed(data["input"])
        raw = json.dumps({"object": "list", "data": [{"index": i, "embedding": v} for i, v in enumerate(vecs)], "model": "relay"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def child(mode, env_extra, block):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TG_", "GROQ_", "GEMINI_", "PROVIDER_", "RAG_", "EMBEDDING_", "R2_"))}
    env.update(ANONYMIZED_TELEMETRY="False", GROQ_API_KEY="measure-not-real", RAG_VECTOR_SEARCH="exact", TG_CACHE="semantic",
               KYR_BLOCK="1" if block else "0", PYTHONWARNINGS="ignore", **env_extra)
    t = time.perf_counter()
    run = subprocess.run([sys.executable, str(HERE / "measure_child.py"), mode], cwd=ROOT, env=env, capture_output=True, text=True, timeout=1500)
    if run.returncode != 0:
        raise SystemExit(f"child {mode} block={block} failed:\n{run.stderr[-2500:]}")
    out = json.loads(run.stdout.strip().splitlines()[-1])
    out["wall_seconds"] = round(time.perf_counter() - t, 2)
    return out


def main():
    load = psutil.getloadavg()
    result = {"machine": {"platform": platform.platform(), "python": sys.version.split()[0], "cpus": psutil.cpu_count(), "ram_gb": round(psutil.virtual_memory().total / 2**30, 1),
                          "loadavg_at_start": [round(x, 2) for x in load], "note": "a developer laptop, not a 0.1-CPU / 512 MB container: absolute times are optimistic"}}
    before = (dl.tree_digest(INDEX), dl.tree_digest(REGISTRY))
    tmp = Path(tempfile.mkdtemp(prefix="kyr-7a-measure-"))
    try:
        idx, st = tmp / "index", tmp / "state"
        shutil.copytree(INDEX, idx)
        shutil.copytree(REGISTRY, st)
        store_root = tmp / "store"
        store = snap.PrefixedStore(snap.LocalObjectStore(store_root), "kyr/")
        t = time.perf_counter()
        manifest = snap.publish(store, idx, st, embed=ollama_embed, embedding_model="nomic-embed-text", family=INDEX_FAMILY, created_by="stage7b-measure")
        result["publish"] = {"seconds": round(time.perf_counter() - t, 2), "version": manifest["version"],
                             "index_archive_mb": round(manifest["index"]["size_bytes"] / 2**20, 2), "index_unpacked_mb": round(manifest["index"]["unpacked_bytes"] / 2**20, 2),
                             "lifecycle_archive_mb": round(manifest["lifecycle"]["size_bytes"] / 2**20, 2), "lifecycle_unpacked_mb": round(manifest["lifecycle"]["unpacked_bytes"] / 2**20, 2),
                             "chunks": manifest["index"]["chunk_count"], "dimensions": manifest["embedding"]["dimensions"]}
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Relay)
        httpd.daemon_threads = True
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base_env = {"EMBEDDING_PROVIDER": "openai_compatible", "EMBEDDING_API_URL": f"http://127.0.0.1:{httpd.server_address[1]}/v1",
                    "EMBEDDING_API_KEY": KEY, "EMBEDDING_MODEL": "nomic-ai/nomic-embed-text-v1.5", "OLLAMA_ENABLED": "false",
                    "OLLAMA_HOST": "127.0.0.1:1", "TG_SNAPSHOT_STORE": "local", "TG_SNAPSHOT_LOCAL_DIR": str(store_root), "TG_ENVIRONMENT": "production"}
        # direct (no snapshot) components of the index, on the copy
        result["components_full"] = child("components", {"TG_DB_DIR": str(idx)}, block=False)
        result["components_cloud_requirements"] = child("components", {"TG_DB_DIR": str(idx)}, block=True)
        runs = {}
        for cfg, block in (("full_environment", False), ("cloud_requirements", True)):
            runs[cfg] = []
            for i in range(3):
                work = tmp / f"work-{cfg}"
                if i == 0:
                    shutil.rmtree(work, ignore_errors=True)   # run 0 is a COLD start (download + verify + extract); 1 and 2 reuse the cached archives
                r = child("server", dict(base_env, TG_SNAPSHOT_WORK_DIR=str(work)), block=block)
                r["cold_start"] = i == 0
                runs[cfg].append(r)
        result["server_runs"] = runs
        httpd.shutdown()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    after = (dl.tree_digest(INDEX), dl.tree_digest(REGISTRY))
    result["real_index_and_registry_unchanged"] = before == after
    result["real_index_tree_digest"], result["real_registry_tree_digest"] = before
    out = HERE / "measurements.json"
    out.write_text(json.dumps(result, indent=1))
    print(json.dumps({k: result[k] for k in ("machine", "publish", "real_index_and_registry_unchanged")}, indent=1))
    for cfg, rs in runs.items():
        for r in rs:
            m = r["marks"]
            print(cfg, "cold" if r["cold_start"] else "warm", "import_s", m["server_import_seconds"], "rss_after_import", m["import backend.server (snapshot+store+exact+bm25)"]["rss_mb"],
                  "peak_total", m["after concurrency 1/4/8/16"]["peak_mb"], "snapshot_s", r["snapshot"]["seconds"].get("total"))


if __name__ == "__main__":
    main()
