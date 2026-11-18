"""Stage 7B.2: (1) per-question first-relevant rank, Nomic vs bge-small, through the full server retrieval pipeline (hybrid, exact), from the
retrieval_eval outputs; (2) the relevance gate: the server drops chunks whose squared-L2 distance exceeds a threshold calibrated on Nomic
(profile default_max_distance). Does that threshold mean the same thing in the bge-small space, and does top-1 distance still separate
answerable questions from out-of-scope ones? Computed from the stored/candidate vectors only (exact L2, no model calls)."""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
E71, E72 = ROOT / "eval/deployment/stage7b1", ROOT / "eval/deployment/stage7b2"
sys.path.insert(0, str(ROOT))
from backend import rag_profiles as rp  # noqa: E402

base = json.loads((E72 / "baseline/retrieval_exact.json").read_text())
cand = json.loads((E72 / "candidate/retrieval/bge_small_instr_hybrid_exact.json").read_text())
cm = {r["id"]: r for r in cand["rows"]}


def first(r):
    rel = set(r["relevant"])
    return next((i + 1 for i, k in enumerate(r["ranked"]) if k in rel), None)


rows, worse, better = [], [], []
for b in base["rows"]:
    if b["outcome"] != "retrieve" or not b["relevant"]:
        continue
    c = cm[b["id"]]
    fb, fc = first(b), first(c)
    rows.append({"id": b["id"], "category": b["category"], "nomic_first_relevant_rank": fb, "bge_first_relevant_rank": fc})
    key = lambda x: x if x else 99  # noqa: E731
    (worse if key(fc) > key(fb) else better if key(fc) < key(fb) else []).append(rows[-1]) if key(fc) != key(fb) else None
out = {"hybrid_exact_pipeline": {"cases": len(rows), "bge_worse": worse, "bge_better": better,
                                 "missing_from_top5": {"nomic": [r["id"] for r in rows if not r["nomic_first_relevant_rank"] or r["nomic_first_relevant_rank"] > 5],
                                                       "bge": [r["id"] for r in rows if not r["bge_first_relevant_rank"] or r["bge_first_relevant_rank"] > 5]}}}

# ---- relevance gate
ref = json.loads((E71 / "reference_set.json").read_text())
bench = {c["question"]: c for c in json.loads((ROOT / "eval/telangana-retrieval-benchmark.json").read_text())["cases"]}
nom, ol = np.load(E71 / "reference_set.npz"), np.load(E71 / "ollama_vectors.npz")
bg = np.load(E72 / "candidate/bge_small_vectors.npz")
gate = rp.PROFILES[rp.DEFAULT_BUILD_PROFILE].default_max_distance
top1 = {}
for name, D, Q in (("nomic", nom["vecs"], ol["queries"]), ("bge", bg["docs"], bg["q_instr"])):
    top1[name] = np.array([float(((D - q) ** 2).sum(1).min()) for q in Q])
labels = [bench[q]["expected_retrieval_outcome"] for q in ref["questions"]]
ans = np.array([l == "retrieve" for l in labels])
oos = np.array([l in ("out_of_scope", "missing_provision") for l in labels])


def auroc(pos, neg):
    return float(np.mean([(p < n) + 0.5 * (p == n) for p in pos for n in neg]))     # smaller distance = more answerable


gate_out = {"profile_gate_squared_l2_calibrated_on_nomic": gate, "answerable_cases": int(ans.sum()), "out_of_scope_or_missing_cases": int(oos.sum())}
for name, t in top1.items():
    gate_out[name] = {"top1_distance_answerable": {"min": round(float(t[ans].min()), 3), "median": round(float(np.median(t[ans])), 3), "max": round(float(t[ans].max()), 3)},
                      "top1_distance_out_of_scope": {"min": round(float(t[oos].min()), 3), "median": round(float(np.median(t[oos])), 3), "max": round(float(t[oos].max()), 3)},
                      "answerable_passing_the_nomic_gate": f"{int((t[ans] <= gate).sum())}/{int(ans.sum())}",
                      "out_of_scope_passing_the_nomic_gate": f"{int((t[oos] <= gate).sum())}/{int(oos.sum())}",
                      "auroc_answerable_vs_out_of_scope": round(auroc(t[ans], t[oos]), 3)}
out["relevance_gate"] = gate_out
(E72 / "candidate/hybrid_diff_and_gate.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out["hybrid_exact_pipeline"]["missing_from_top5"]))
print("worse:", [(r["id"], r["nomic_first_relevant_rank"], r["bge_first_relevant_rank"]) for r in worse])
print("better:", [(r["id"], r["nomic_first_relevant_rank"], r["bge_first_relevant_rank"]) for r in better])
print(json.dumps(gate_out, indent=1))
