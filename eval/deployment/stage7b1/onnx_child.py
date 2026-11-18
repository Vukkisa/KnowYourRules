"""One measured process: load an ONNX variant with onnxruntime (no torch), embed the reference set, report memory/latency/agreement.
usage: onnx_child.py MODEL.onnx TOKENIZER.json OUT.json [threads]
Only numpy, tokenizers, onnxruntime and psutil are imported: the runtime the Render backend would have to carry.
Agreement is measured against the vectors of the real Ollama path (ollama_vectors.npz) and the stored index vectors."""
import json
import resource
import sys
import time
from pathlib import Path

import numpy as np
import psutil

HERE = Path(__file__).resolve().parent
proc = psutil.Process()
rss = lambda: round(proc.memory_info().rss / 2**20, 1)
marks = {"python+numpy+psutil": rss()}
from tokenizers import Tokenizer  # noqa: E402
import onnxruntime as ort  # noqa: E402

marks["after import tokenizers+onnxruntime"] = rss()
model, tokpath, outpath = sys.argv[1], sys.argv[2], sys.argv[3]
threads = int(sys.argv[4]) if len(sys.argv) > 4 else 1
tok = Tokenizer.from_file(tokpath)
t0 = time.time()
if not model.endswith(".onnx"):                    # pure-numpy engine over the F16 GGUF weights (no onnxruntime, no torch)
    import os
    sys.path.insert(0, str(HERE))
    from nomic_numpy import NomicNumpy
    eng = NomicNumpy(model, tokpath)
    load_s = round(time.time() - t0, 2)
    marks["after session load"] = rss()

    def emb(texts):
        return eng.embed(texts)
else:
    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    so.inter_op_num_threads = 1
    sess = ort.InferenceSession(model, so, providers=["CPUExecutionProvider"])
    load_s = round(time.time() - t0, 2)
    marks["after session load"] = rss()
    emb = None


def _ort_emb(texts):
    encs = tok.encode_batch(texts)
    T = max(len(e.ids) for e in encs)
    ids = np.zeros((len(encs), T), dtype=np.int64)
    mask = np.zeros((len(encs), T), dtype=np.int64)
    for i, e in enumerate(encs):
        ids[i, :len(e.ids)] = e.ids
        mask[i, :len(e.ids)] = 1
    return sess.run(None, {"input_ids": ids, "attention_mask": mask})[0]


if emb is None:
    emb = _ort_emb
ref = json.loads((HERE / "reference_set.json").read_text())
docs, questions = ref["docs"], ref["questions"]
ov = np.load(HERE / "ollama_vectors.npz")
stored = np.load(HERE / "reference_set.npz")["vecs"]
Q, D = "search_query: ", "search_document: "
t0 = time.time()
emb([Q + questions[0]])
first_s = round(time.time() - t0, 3)
marks["after first query"] = rss()
lat, qv = [], []
for q in questions:
    t = time.time()
    qv.append(emb([Q + q])[0])
    lat.append(time.time() - t)
qv = np.asarray(qv)
marks["after 108 single queries"] = rss()
long_text = Q + " ".join(docs[int(np.argmax([len(d) for d in docs]))].split()[:400])
n_tok = len(tok.encode(long_text).ids)
t = time.time()
emb([long_text])
long_s = round(time.time() - t, 3)
marks["after longest input"] = rss()
sel = list(range(0, len(docs), 3))
dv = np.asarray([emb([D + docs[i]])[0] for i in sel])
marks["after 197 documents"] = rss()
cos = lambda a, b: np.sum(a * b, 1) / (np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1))
stat = lambda c: {"min": round(float(c.min()), 7), "p01": round(float(np.percentile(c, 1)), 7), "mean": round(float(c.mean()), 7)}


def topk(v, k=10):
    return np.argsort(((v[:, None, :] - stored[None, :, :]) ** 2).sum(-1), axis=1)[:, :k]


b, c = topk(ov["queries"]), topk(qv)
res = {"model_file": Path(model).name, "model_mb": round(Path(model).stat().st_size / 2**20, 1), "threads": threads, "session_load_s": load_s,
       "first_query_s": first_s, "query_latency_ms": {"p50": round(float(np.percentile(lat, 50)) * 1000, 1), "p95": round(float(np.percentile(lat, 95)) * 1000, 1),
                                                     "max": round(max(lat) * 1000, 1)},
       "long_input_tokens": n_tok, "long_input_s": long_s, "rss_mb": marks, "ru_maxrss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20, 1),
       "queries_vs_ollama_cosine": stat(cos(qv, ov["queries"])), "docs_vs_ollama_cosine_sample197": stat(cos(dv, ov["docs"][sel])),
       "docs_vs_stored_cosine_sample197": stat(cos(dv, stored[sel])),
       "retrieval_vs_ollama": {"top1_same": float((b[:, 0] == c[:, 0]).mean()), "top5_set_same": float(np.mean([set(b[i, :5]) == set(c[i, :5]) for i in range(len(b))])),
                               "top10_set_same": float(np.mean([set(b[i]) == set(c[i]) for i in range(len(b))]))},
       "unit_norm_ok": bool(np.allclose(np.linalg.norm(qv, axis=1), 1.0, atol=1e-3))}
Path(outpath).write_text(json.dumps(res, indent=1))
print(json.dumps(res, indent=1))
