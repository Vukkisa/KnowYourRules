"""Stage 7B.2 Path B runtime cost: bge-small-en-v1.5 exported to ONNX fp32 (from the LOCAL cache; nothing downloaded) and run with
onnxruntime + tokenizers only (no torch). Fidelity vs the torch reference vectors (candidate/bge_small_vectors.npz), RSS, latency, CPU.
usage: python3 pathB_onnx_measure.py export <onnx_path>   |   python3 pathB_onnx_measure.py run <label> <onnx_path> <out.json>"""
import hashlib
import json
import os
import resource
import sys
import threading
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
E72 = ROOT / "eval/deployment/stage7b2"
mode = sys.argv[1]
if mode == "export":
    sys.path.insert(0, str(E72))
    import torch
    import bge_candidate as b
    m = b.Bge()
    t = m.tok(["probe sentence"], return_tensors="pt")

    class W(torch.nn.Module):
        def __init__(s, x):
            super().__init__()
            s.x = x

        def forward(s, input_ids, attention_mask, token_type_ids):
            return torch.nn.functional.normalize(s.x(input_ids=input_ids, attention_mask=attention_mask, token_type_ids=token_type_ids).last_hidden_state[:, 0], dim=1)
    torch.onnx.export(W(m.model).eval(), (t["input_ids"], t["attention_mask"], t["token_type_ids"]), sys.argv[2], opset_version=17, dynamo=False,
                      input_names=["input_ids", "attention_mask", "token_type_ids"], output_names=["emb"],
                      dynamic_axes={k: {0: "b", 1: "s"} for k in ("input_ids", "attention_mask", "token_type_ids")} | {"emb": {0: "b"}})
    print("exported", sys.argv[2], hashlib.sha256(Path(sys.argv[2]).read_bytes()).hexdigest(), os.path.getsize(sys.argv[2]) // 2**20, "MB")
    sys.exit(0)

import onnxruntime as ort  # noqa: E402
import psutil  # noqa: E402
from tokenizers import Tokenizer  # noqa: E402

label, onnx_path, outp = sys.argv[2], sys.argv[3], sys.argv[4]
proc = psutil.Process()
mb = lambda: round(proc.memory_info().rss / 2**20, 1)  # noqa: E731
import glob  # noqa: E402
snap = glob.glob(os.path.expanduser("~/.cache/huggingface/hub/models--BAAI--bge-small-en-v1.5/snapshots/*"))[0]
res = {"label": label, "onnx_sha256": hashlib.sha256(Path(onnx_path).read_bytes()).hexdigest(), "onnx_mb": round(os.path.getsize(onnx_path) / 2**20, 1),
       "onnxruntime": ort.__version__, "rss_mb": {"start": mb()}}
t0 = time.perf_counter()
so = ort.SessionOptions()
so.intra_op_num_threads = int(os.environ.get("ORT_THREADS", "1"))
sess = ort.InferenceSession(onnx_path, so, providers=["CPUExecutionProvider"])
tok = Tokenizer.from_file(snap + "/tokenizer.json")
tok.enable_truncation(512)
tok.enable_padding()
res["load_seconds"] = round(time.perf_counter() - t0, 2)
res["rss_mb"]["after load"] = mb()
INSTR = "Represent this sentence for searching relevant passages: "


def emb(texts):
    e = tok.encode_batch(texts)
    ids = np.array([x.ids for x in e], dtype=np.int64)
    am = np.array([x.attention_mask for x in e], dtype=np.int64)
    return sess.run(None, {"input_ids": ids, "attention_mask": am, "token_type_ids": np.zeros_like(ids)})[0]


ref = json.loads((ROOT / "eval/deployment/stage7b1/reference_set.json").read_text())
want = np.load(E72 / "candidate/bge_small_vectors.npz")["q_instr"]
lat, cos = [], []
c0 = proc.cpu_times()
for q, w in zip(ref["questions"], want):
    t = time.perf_counter()
    v = emb([INSTR + q])[0]
    lat.append((time.perf_counter() - t) * 1000)
    cos.append(float(v @ w))
c1 = proc.cpu_times()
res["queries_vs_torch_reference_cosine"] = {"n": len(cos), "min": min(cos), "mean": float(np.mean(cos))}
res["query_latency_ms"] = {"p50": round(float(np.percentile(lat, 50)), 1), "p95": round(float(np.percentile(lat, 95)), 1), "max": round(max(lat), 1)}
res["cpu_seconds_per_query"] = round(((c1.user + c1.system) - (c0.user + c0.system)) / len(lat), 4)
res["rss_mb"]["after 108 queries"] = mb()
docs = [ref["docs"][i] for i in range(0, 590, 59)]
t = time.perf_counter()
emb(docs[:4])
res["longest_batch_ms"] = round((time.perf_counter() - t) * 1000, 1)
out = [0] * 4
qs = [INSTR + q for q in ref["questions"][:4]]
th = [threading.Thread(target=lambda i=i: (emb([qs[i]]), out.__setitem__(i, time.perf_counter()))) for i in range(4)]
t = time.perf_counter()
[x.start() for x in th]
[x.join() for x in th]
res["concurrent_4_requests_wall_ms"] = round((max(out) - t) * 1000, 1)
res["rss_mb"]["after concurrency"] = mb()
res["ru_maxrss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20, 1)
Path(outp).write_text(json.dumps(res, indent=1))
print(json.dumps(res, indent=1))
