"""Compare configurations from a rag_bench run: paired bootstrap vs the baseline, per-query-type breakdown,
and a relevance-gate threshold calibrated on dev and evaluated on test.

    python3 eval/analyze.py eval/results/run_v1.json > eval/results/analysis_v1.md
"""

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rag_bench as rb  # noqa: E402

BASELINE = "chunker=fixed-1000/200 (baseline) | embedder=nomic (baseline) | retrieval=dense | rerank=none"


def gate_eval(pq, queries, dev_ids):
    """Pick the top-score threshold maximising (correct refusals + kept answerable) on dev; apply to test."""
    def score_split(ids, thr):
        ans = [q for q in queries if q["id"] in ids and q["gold"]]
        una = [q for q in queries if q["id"] in ids and not q["gold"]]
        kept = sum(pq[q["id"]]["top_score"] >= thr for q in ans)
        refused = sum(pq[q["id"]]["top_score"] < thr for q in una)
        return kept, len(ans), refused, len(una)
    dev = {q["id"] for q in queries if q["id"] in dev_ids}
    test = {q["id"] for q in queries if q["id"] not in dev_ids}
    candidates = sorted({pq[q["id"]]["top_score"] for q in queries if q["id"] in dev})
    best = max(candidates, key=lambda t: (lambda k, na, r, nu: k / na + r / nu)(*score_split(dev, t)))
    k, na, r, nu = score_split(test, best)
    return best, 1 - k / na, r / nu


def main(path):
    run = json.loads(Path(path).read_text(encoding="utf-8"))
    queries = rb.load_queries(rb.DATA / "queries_v1.json")
    dev_ids = {q["id"] for q in rb.split_ids(queries)[0]}
    test_ans = [q for q in queries if q["gold"] and q["id"] not in dev_ids]
    order = ("chunker", "embedder", "retrieval", "rerank")
    def norm(key):
        parts = dict(part.split("=", 1) for part in key.split(" | "))
        return " | ".join(f"{k}={parts[k]}" for k in order)
    pq = {norm(k): v for k, v in run["per_query"].items()}
    base = pq[BASELINE]

    # rank configs on DEV mrr, report TEST
    dev_rows = {(" | ".join(f"{k}={r[k]}" for k in ("chunker", "embedder", "retrieval", "rerank"))): r
                for r in run["rows"] if r["split"] == "dev" and "mrr" in r}
    test_rows = {(" | ".join(f"{k}={r[k]}" for k in ("chunker", "embedder", "retrieval", "rerank"))): r
                 for r in run["rows"] if r["split"] == "test" and "mrr" in r}
    ranked = sorted(dev_rows, key=lambda k: -dev_rows[k]["mrr"])

    print("# Analysis of", Path(path).name, "\n")
    print("Configurations ranked by **dev** MRR; metrics below are on the held-out **test** split "
          f"({len(test_ans)} answerable test queries). Δ = test MRR minus baseline, with a paired-bootstrap 95% CI.\n")
    print("| rank | config | dev MRR | test MRR | Δ MRR [95% CI] | test recall@4 | test nDCG@4 | AUROC (test) | gate: test false-refusal / correct-refusal | latency ms |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for i, key in enumerate(ranked[:12] + ([BASELINE] if BASELINE not in ranked[:12] else []), 1):
        a = [base[q["id"]]["mrr"] for q in test_ans]
        b = [pq[key][q["id"]]["mrr"] for q in test_ans]
        d, lo, hi = rb.paired_bootstrap(a, b)
        thr, fr, cr = gate_eval(pq[key], queries, dev_ids)
        t = test_rows[key]
        print(f"| {i if key in ranked[:12] else 'base'} | {key} | {dev_rows[key]['mrr']:.3f} | {t['mrr']:.3f} | {d:+.3f} [{lo:+.3f}, {hi:+.3f}] | "
              f"{t['recall@4']:.3f} | {t['ndcg@4']:.3f} | {t['auroc_answerable']:.3f} | {fr:.2f} / {cr:.2f} | {t['latency_ms_mean']:.0f} |")

    print("\n## MRR by query type (all answerable queries, dev+test)\n")
    types = sorted({q["type"] for q in queries if q["gold"]})
    show = [BASELINE] + [k for k in ranked[:4] if k != BASELINE]
    print("| type | n | " + " | ".join(f"cfg{i}" for i in range(len(show))) + " |")
    print("|---|---|" + "---|" * len(show))
    for ty in types:
        qs = [q for q in queries if q["gold"] and q["type"] == ty]
        print(f"| {ty} | {len(qs)} | " + " | ".join(f"{statistics.fmean(pq[k][q['id']]['mrr'] for q in qs):.2f}" for k in show) + " |")
    print()
    for i, k in enumerate(show):
        print(f"- cfg{i}: {k}")

    print("\n## Failures of the top dev configuration on test (MRR < 1)\n")
    top = ranked[0]
    for q in test_ans:
        m = pq[top][q["id"]]
        if m["mrr"] < 1:
            print(f"- {q['id']} ({q['type']}, {q['state']}): \"{q['query']}\" gold={q['gold']} mrr={m['mrr']:.2f} (baseline {base[q['id']]['mrr']:.2f})")

    print("\n## Environment\n")
    env = run["environment"]
    print("```json")
    print(json.dumps({k: env[k] for k in ("python", "platform", "packages", "git_commit", "hf_revisions", "dataset_sha256")}, indent=1))
    print("```")
    print("\nTimings:", json.dumps({k: (round(v, 2) if isinstance(v, float) else v) for k, v in run["timings"].items() if not k.startswith("n_chunks")}))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "eval/results/run_v1.json")
