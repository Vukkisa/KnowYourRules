"""Numerical agreement: Ollama (production path) vs independent GGUF re-implementation vs the vectors stored in the index.
Stage 7B.1. Local only: talks to the local Ollama on localhost, no hosted service. One process; run nothing else beside it.
Raw outputs: ollama_vectors.npz, torch_pooled_raw.npz, compare_ollama_result.json."""
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))
import nomic_runtime as nr  # noqa: E402

DOC_P, Q_P = "search_document: ", "search_query: "
ref = json.loads((HERE / "reference_set.json").read_text())
docs, questions = ref["docs"], ref["questions"]
stored = np.load(HERE / "reference_set.npz")["vecs"]
res = {"n_docs": len(docs), "n_questions": len(questions)}

# --- 1. Ollama through the production path (langchain_ollama via the profile wrapper), cached -------------------------------------
cache = HERE / "ollama_vectors.npz"
if cache.exists():
    z = np.load(cache)
    od, oq = z["docs"], z["queries"]
else:
    from langchain_ollama import OllamaEmbeddings
    from backend.rag_profiles import ProfileEmbeddings, PROFILES
    emb = ProfileEmbeddings(OllamaEmbeddings(model="nomic-embed-text"), PROFILES["structured"])
    t = time.time()
    oq = np.asarray([emb.embed_query(q) for q in questions], dtype=np.float32)
    od = np.asarray(emb.embed_documents(docs), dtype=np.float32)
    res["ollama_embed_seconds"] = round(time.time() - t, 1)
    np.savez_compressed(cache, docs=od, queries=oq)
cos = lambda a, b: np.sum(a * b, 1) / (np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1))
stat = lambda c: {"min": float(c.min()), "p01": float(np.percentile(c, 1)), "mean": float(c.mean()), "max": float(c.max())}
res["ollama_vs_stored_docs_cosine"] = stat(cos(od, stored))          # does today's Ollama still reproduce the index?
res["ollama_norms"] = {"min": float(np.linalg.norm(od, axis=1).min()), "max": float(np.linalg.norm(od, axis=1).max())}

# --- 2. Reference implementation from the same GGUF weights ------------------------------------------------------------------------
g, digest, tok = nr.load()
res["gguf_blob"] = digest
model = nr.NomicTorch(g)


def pooled_all(texts, batch=8):
    order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
    out = np.zeros((len(texts), 768), dtype=np.float32)
    for s in range(0, len(texts), batch):
        idx = order[s:s + batch]
        ids, mask, _ = nr.encode_batch(tok, [texts[i] for i in idx])
        out[idx] = model.pooled(ids, mask).numpy()
    return out


t = time.time()
pq = pooled_all([Q_P + q for q in questions])
res["torch_fp32_query_seconds_total"] = round(time.time() - t, 1)
t = time.time()
pd = pooled_all([DOC_P + d for d in docs])
res["torch_fp32_doc_seconds_total"] = round(time.time() - t, 1)
np.savez_compressed(HERE / "torch_pooled_raw.npz", docs=pd, queries=pq)

unit = lambda a: a / np.linalg.norm(a, axis=1, keepdims=True)
ln = lambda a: (a - a.mean(1, keepdims=True)) / np.sqrt(a.var(1, keepdims=True) + 1e-5)   # F.layer_norm without affine
res["variants"] = {}
for name, f in (("mean_pool_l2 (llama.cpp/Ollama behaviour)", unit), ("layernorm_then_l2 (published ST recipe)", lambda a: unit(ln(a)))):
    vd, vq = f(pd), f(pq)
    res["variants"][name] = {"docs_vs_ollama_cosine": stat(cos(vd, od)), "queries_vs_ollama_cosine": stat(cos(vq, oq)), "docs_vs_stored_cosine": stat(cos(vd, stored)),
                             "docs_max_abs_diff_vs_ollama": float(np.abs(vd - od).max())}

# --- 3. Does the difference change retrieval? top-k over the stored vectors, exact L2 (== cosine for unit vectors) -------------------
def topk(qv, k=10):
    d = ((qv[:, None, :] - stored[None, :, :]) ** 2).sum(-1)
    return np.argsort(d, axis=1)[:, :k]


base = topk(oq)
res["retrieval"] = {}
for name, f in (("mean_pool_l2", unit), ("layernorm_then_l2", lambda a: unit(ln(a)))):
    cand = topk(f(pq))
    res["retrieval"][name] = {
        "top1_same": float((cand[:, 0] == base[:, 0]).mean()),
        "top5_set_same": float(np.mean([set(cand[i, :5]) == set(base[i, :5]) for i in range(len(base))])),
        "top10_set_same": float(np.mean([set(cand[i]) == set(base[i]) for i in range(len(base))])),
        "top5_order_same": float(np.mean([list(cand[i, :5]) == list(base[i, :5]) for i in range(len(base))]))}

# --- 4. Token counts against Ollama's own prompt_eval_count (tokenizer agreement) -----------------------------------------------------
import requests
sample = [Q_P + q for q in questions] + [DOC_P + d for d in docs[::5]]
mism, rows = 0, []
for s in sample:
    r = requests.post("http://localhost:11434/api/embed", json={"model": "nomic-embed-text", "input": s}, timeout=60).json()
    ours = len(tok.encode(s).ids)
    if r.get("prompt_eval_count") != ours:
        mism += 1
        rows.append({"text": s[:80], "ollama": r.get("prompt_eval_count"), "ours": ours})
res["token_count_check"] = {"texts": len(sample), "mismatches": mism, "examples": rows[:8]}
(HERE / "compare_ollama_result.json").write_text(json.dumps(res, indent=1))
print(json.dumps(res, indent=1))
