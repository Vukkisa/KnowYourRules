"""
Retrieval-only evaluation of the Telangana preview index against eval/telangana-retrieval-benchmark.json.

No answer is generated and no model grades anything: every metric compares retrieved chunk identifiers with
the benchmark's expected identifiers. Groq is trapped so any model call fails loudly and is counted.

    TG_DB_DIR=chroma_telangana_preview python -m backend.retrieval_eval [--out results.json]
"""

import argparse
import collections
import json
import os
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
BENCHMARK = BASE_DIR / "eval" / "telangana-retrieval-benchmark.json"
K = 5


# ---------------------------------------------------------------------------------------------------
# Pure metrics (ranked list of "manifest_id::provision_id" against a set of relevant ids)
# ---------------------------------------------------------------------------------------------------
def recall_at_k(ranked, relevant, k) -> float:
    """Share of relevant provisions found in the top k."""
    return len(set(ranked[:k]) & set(relevant)) / len(set(relevant)) if relevant else 0.0


def hit_at_k(ranked, relevant, k) -> bool:
    return bool(set(ranked[:k]) & set(relevant))


def precision_at_k(ranked, relevant, k) -> float:
    """Relevant results among the top k, over k (an empty slot counts as not relevant)."""
    return sum(1 for r in ranked[:k] if r in set(relevant)) / k


def reciprocal_rank(ranked, relevant) -> float:
    for i, r in enumerate(ranked, 1):
        if r in set(relevant):
            return 1.0 / i
    return 0.0


def mean(values) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


# ---------------------------------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------------------------------
def load_server(db_dir):
    os.environ["TG_DB_DIR"] = str(Path(db_dir).resolve())
    os.environ.setdefault("GROQ_API_KEY", "offline-eval-key-not-real")
    calls = collections.Counter()
    import langchain_groq

    def blocked(*_a, **_k):
        calls["groq"] += 1
        raise RuntimeError("model calls are blocked during retrieval evaluation")
    for name in ("_generate", "_agenerate", "_stream", "_astream"):
        setattr(langchain_groq.ChatGroq, name, blocked)
    from backend import server
    return server, calls


def provision_key(metadata) -> str:
    return f"{metadata['manifest_id']}::{metadata['provision_id']}"


def ranked_provisions(docs) -> list[str]:
    """Distinct provisions in rank order (split parts of one provision count once)."""
    out = []
    for d in docs:
        key = provision_key(d.metadata)
        if key not in out:
            out.append(key)
    return out


def evaluate(server, cases) -> dict:
    rows = []
    guard = getattr(server, "missing_references", server.missing_rule_references)
    for case in cases:
        missing, _present = guard(case["question"])
        penalty = server.penalty_lock_reason(case["question"])
        started = time.perf_counter()
        docs = server.retrieve(case["question"])
        elapsed = time.perf_counter() - started
        excluded_ids = {c["chunk_id"].rsplit("::", 1)[0] for c in case["excluded_chunks"]}
        leaked = [provision_key(d.metadata) for d in docs
                  if d.metadata.get("answer_eligible") is False or provision_key(d.metadata) in excluded_ids]
        rows.append({"id": case["id"], "category": case["category"], "outcome": case["expected_retrieval_outcome"],
                     "relevant": case["expected_provisions"], "ranked": ranked_provisions(docs),
                     "retrieved_chunks": len(docs), "guard_blocked": bool(missing), "missing": missing,
                     "penalty_locked": bool(penalty), "leaked": leaked, "seconds": elapsed})
    return summarise(rows)


def summarise(rows) -> dict:
    scored = [r for r in rows if r["outcome"] == "retrieve" and r["relevant"]]
    guard_cases = [r for r in rows if r["outcome"] == "missing_provision" or r["category"] == "guard_control"]
    guard_ok = [r for r in guard_cases if r["guard_blocked"] == (r["outcome"] == "missing_provision")]
    failures = [r for r in scored if not hit_at_k(r["ranked"], r["relevant"], K)]
    retrieved_total = sum(r["retrieved_chunks"] for r in rows)
    leaked_total = sum(len(r["leaked"]) for r in rows)
    by_cat = collections.defaultdict(list)
    for r in scored:
        by_cat[r["category"]].append(r)
    oos = [r for r in rows if r["outcome"] == "out_of_scope"]
    amb = [r for r in rows if r["outcome"] == "clarification_required"]
    penalty = [r for r in rows if r["outcome"] == "restricted"]
    return {
        "cases": len(rows),
        "categories": dict(collections.Counter(r["category"] for r in rows)),
        "retrieval": {
            "scored_cases": len(scored),
            "recall@1": mean(recall_at_k(r["ranked"], r["relevant"], 1) for r in scored),
            "recall@3": mean(recall_at_k(r["ranked"], r["relevant"], 3) for r in scored),
            "recall@5": mean(recall_at_k(r["ranked"], r["relevant"], 5) for r in scored),
            "hit@5": mean(hit_at_k(r["ranked"], r["relevant"], 5) for r in scored),
            "precision@5": mean(precision_at_k(r["ranked"], r["relevant"], 5) for r in scored),
            "mrr": mean(reciprocal_rank(r["ranked"], r["relevant"]) for r in scored),
            "failure_rate": len(failures) / len(scored) if scored else 0.0,
            "by_category": {c: {"cases": len(v), "hit@5": mean(hit_at_k(r["ranked"], r["relevant"], 5) for r in v),
                                "mrr": mean(reciprocal_rank(r["ranked"], r["relevant"]) for r in v)}
                            for c, v in sorted(by_cat.items())},
        },
        "guard": {"cases": len(guard_cases), "correct": len(guard_ok),
                  "accuracy": len(guard_ok) / len(guard_cases) if guard_cases else 0.0},
        "leakage": {"retrieved_chunks": retrieved_total, "excluded_chunks_retrieved": leaked_total,
                    "rate": leaked_total / retrieved_total if retrieved_total else 0.0,
                    "cases_with_leak": [r["id"] for r in rows if r["leaked"]]},
        "penalty": {"cases": len(penalty), "locked": sum(r["penalty_locked"] for r in penalty)},
        "out_of_scope": {"cases": len(oos), "abstained": sum(1 for r in oos if r["retrieved_chunks"] == 0),
                         "retrieved": {r["id"]: r["ranked"][:3] for r in oos if r["retrieved_chunks"]}},
        "ambiguous": {"cases": len(amb), "note": "the pipeline has no clarification step; candidates retrieved shown",
                      "candidates_in_top5": {r["id"]: [x for x in r["ranked"][:5] if x in r["relevant"]] for r in amb}},
        "failures": [{"id": r["id"], "expected": r["relevant"], "top5": r["ranked"][:5]} for r in failures],
        "latency_ms": {"mean": 1000 * mean(r.get("seconds", 0.0) for r in rows),
                       "max": 1000 * max((r.get("seconds", 0.0) for r in rows), default=0.0)},
        "rows": rows,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Retrieval-only evaluation (no answer generation).")
    ap.add_argument("--db-dir", default=os.environ.get("TG_DB_DIR", BASE_DIR / "chroma_telangana_preview"))
    ap.add_argument("--benchmark", default=BENCHMARK)
    ap.add_argument("--mode", choices=("vector", "hybrid"), help="override RAG_RETRIEVAL_MODE")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    cases = json.loads(Path(a.benchmark).read_text(encoding="utf-8"))["cases"]
    server, calls = load_server(a.db_dir)
    if a.mode:
        server.RETRIEVAL_MODE = a.mode
    result = evaluate(server, cases)
    result["mode"] = server.RETRIEVAL_MODE if getattr(server, "LEXICAL_INDEX", None) is not None else "vector"
    result["model_calls"] = dict(calls)
    result["review_status"] = dict(collections.Counter(c["reviewer_status"] for c in cases))
    if a.out:
        Path(a.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
