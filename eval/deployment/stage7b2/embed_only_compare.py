"""Stage 7B.2: embedding-only comparison, no server, no hybrid, no guards: exact L2 search over the 590 stored chunks, scored against
the 108-question benchmark's expected provisions with the SAME metric definitions as backend/retrieval_eval.py (provision-level,
split parts de-duplicated, rank order kept). Nomic = the vectors stored in the real index (copied by Stage 7B.1) and today's Ollama
query vectors (Stage 7B.1 ollama_vectors.npz). Candidates = the vectors in candidate/. Never queries one model's documents with another model."""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
E71, E72 = ROOT / "eval/deployment/stage7b1", ROOT / "eval/deployment/stage7b2"
sys.path.insert(0, str(ROOT))
from backend import retrieval_eval as ev  # noqa: E402

ref = json.loads((E71 / "reference_set.json").read_text())
bench = json.loads((ROOT / "eval/telangana-retrieval-benchmark.json").read_text())["cases"]
META = json.loads((E72 / "candidate" / "chunk_metadata.json").read_text())
assert META["ids"] == ref["ids"]
keys = [f"{m['manifest_id']}::{m['provision_id']}" for m in META["metadatas"]]
qtext = ref["questions"]
by_text = {c["question"]: c for c in bench}
assert all(q in by_text for q in qtext)


def ranked(D, q, k=10, pool=None):
    d = ((D - q) ** 2).sum(1)
    order = np.lexsort((np.arange(len(d)), d))                   # distance, then position: deterministic
    out = []
    for i in order:
        if keys[i] not in out:
            out.append(keys[i])
        if len(out) >= k:
            break
    return out, d[order[:k]]


def score(D, Q):
    rows, per = [], []
    for q, text in zip(Q, qtext):
        c = by_text[text]
        if c["expected_retrieval_outcome"] != "retrieve" or not c["expected_provisions"]:
            continue
        rel = list(c["expected_provisions"])
        r, _ = ranked(D, q)
        per.append((c["id"], c["category"], r[:5], rel))
        rows.append((ev.recall_at_k(r, rel, 5), float(ev.hit_at_k(r, rel, 5)), ev.reciprocal_rank(r, rel), ev.recall_at_k(r, rel, 1), ev.recall_at_k(r, rel, 3)))
    a = np.mean(rows, 0)
    return {"scored_cases": len(rows), "recall@1": a[3], "recall@3": a[4], "recall@5": a[0], "hit@5": a[1], "mrr": a[2]}, per


def main():
    nom, ol = np.load(E71 / "reference_set.npz"), np.load(E71 / "ollama_vectors.npz")
    assert list(nom["ids"]) == ref["ids"], "stored-vector order differs from the reference set"
    cand = np.load(E72 / "candidate" / "bge_small_vectors.npz")
    runs = {"nomic-embed-text-v1.5 (stored docs, Ollama queries)": (nom["vecs"], ol["queries"]),
            "bge-small-en-v1.5 (query instruction)": (cand["docs"], cand["q_instr"]),
            "bge-small-en-v1.5 (no instruction)": (cand["docs"], cand["q_plain"])}
    out, per_all = {}, {}
    for name, (D, Q) in runs.items():
        m, per = score(D, Q)
        out[name], per_all[name] = {k: round(float(v), 4) if k != "scored_cases" else v for k, v in m.items()}, per
        print(f"{name:55} {out[name]}")
    # by category (hit@5 and MRR) for Nomic vs the candidate with the instruction
    cats = {}
    for name, per in per_all.items():
        for cid, cat, r5, rel in per:
            cats.setdefault(name, {}).setdefault(cat, []).append((float(any(x in r5 for x in rel)), ev.reciprocal_rank(r5, rel)))
    out["by_category"] = {n: {c: {"cases": len(v), "hit@5": round(float(np.mean([a for a, _ in v])), 3), "mrr": round(float(np.mean([b for _, b in v])), 3)}
                              for c, v in d.items()} for n, d in cats.items()}
    base, cand_i = per_all[list(runs)[0]], per_all[list(runs)[1]]
    reg = []
    for (cid, cat, r_b, rel), (_, _, r_c, _) in zip(base, cand_i):
        hb, hc = any(x in r_b for x in rel), any(x in r_c for x in rel)
        rb, rc = ev.reciprocal_rank(r_b, rel), ev.reciprocal_rank(r_c, rel)
        if hb != hc or abs(rb - rc) > 1e-9:
            reg.append({"id": cid, "category": cat, "expected": rel, "nomic_top5": r_b, "bge_top5": r_c, "hit@5": [hb, hc], "rr": [round(rb, 3), round(rc, 3)]})
    out["per_question_differences_nomic_vs_bge_instruction"] = reg
    out["worse"] = [r["id"] for r in reg if r["rr"][1] < r["rr"][0]]
    out["better"] = [r["id"] for r in reg if r["rr"][1] > r["rr"][0]]
    print("questions where bge is worse:", len(out["worse"]), "better:", len(out["better"]), "lost hit@5:", [r["id"] for r in reg if r["hit@5"] == [True, False]])
    (E72 / "candidate" / "embed_only_compare.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out["by_category"], indent=0)[:1800])


if __name__ == "__main__":
    main()
