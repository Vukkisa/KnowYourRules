"""
Offline grounded-answer quality evaluation (synthetic engineering fixtures only).

    python -m backend.answer_quality_eval [--fixtures eval/answer-quality/fixtures.json]
                                          [--json eval/answer-quality/results.json]
                                          [--markdown eval/answer-quality/REPORT.md]

Each fixture supplies synthetic evidence passages and a fixed model response. The runner drives the server's real
/chat handler in grounded mode (deterministic guards, follow-up handling, penalty lock, evidence contract, prompt,
validator, backend rendering) with only these substituted: the approval gate and index check (forced open),
retrieval (returns the fixture passages) and the generator (MockGenerator returning the fixture response). Groq is trapped
and the server is imported in disabled mode with no index, so no external model can be reached.

These metrics measure how the validator and pipeline TREAT model output. They are not legal accuracy or factual
correctness scores: there are no human-verified reference answers, and the passages are invented test text.
"""

import argparse
import collections
import contextlib
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

BASE_DIR = Path(__file__).resolve().parent.parent
FIXTURES = BASE_DIR / "eval" / "answer-quality" / "fixtures.json"
FIXTURE_SHA = "0" * 63 + "f"  # synthetic document hash for every fixture passage
DISCLAIMER = ("Synthetic engineering evaluation. Fixture passages are invented test text and expected outcomes "
              "describe validator behaviour only. Nothing here is a legal accuracy score, a legal reference answer "
              "or legal verification of the Telangana corpus.")
ACCEPTED = ("answer", "conflict")
REFUSALS = ("no_support", "restricted", "clarification")


# ---------------------------------------------------------------------------------------------------
# Pipeline loading (offline, trapped)
# ---------------------------------------------------------------------------------------------------
def load_pipeline():
    """Import the real server with no index, no approval file and every answer mode off, with Groq trapped."""
    calls = collections.Counter()
    import langchain_groq

    def blocked(*_a, **_k):
        calls["groq"] += 1
        raise RuntimeError("external model calls are blocked during answer-quality evaluation")
    for name in ("_generate", "_agenerate", "_stream", "_astream"):
        setattr(langchain_groq.ChatGroq, name, blocked)
    tmp = tempfile.mkdtemp(prefix="aq-eval-")
    env = {"TG_DB_DIR": str(Path(tmp) / "no-index"), "TG_APPROVAL_FILE": str(Path(tmp) / "no-approval.json"),
           "TG_ENVIRONMENT": "", "TG_GROUNDED_ANSWERS": "", "TG_LEGACY_DEV_ANSWERS": "", "TG_KB_APPROVED": "",
           "TG_PENALTY_ANSWERS": ""}
    with mock.patch.dict(os.environ, env):
        os.environ.pop("GROQ_API_KEY", None)
        previous = sys.modules.pop("backend.server", None)
        try:
            from backend import server
        finally:
            # Keep this evaluation-only instance private: restore whatever was imported before (normally nothing).
            if previous is not None:
                sys.modules["backend.server"] = previous
            else:
                sys.modules.pop("backend.server", None)
                if hasattr(sys.modules.get("backend"), "server"):
                    delattr(sys.modules["backend"], "server")
    if server.llm is not None or server.ANSWER_MODE != "disabled":
        raise RuntimeError("evaluation server must load in disabled mode without a model client")
    return server, calls


# ---------------------------------------------------------------------------------------------------
# Running one fixture
# ---------------------------------------------------------------------------------------------------
def fixture_docs(case, passages):
    from langchain_core.documents import Document
    docs = []
    for key in case["evidence"]:
        p = passages[key]
        docs.append(Document(page_content=p["text"], metadata={
            "state": "Telangana", "manifest_id": p["manifest_id"], "provision_id": p["provision_id"], "part": 1,
            "parts": 1, "title": "Synthetic fixture document", "document_number": "",
            "location": f"synthetic/{p['manifest_id']}#{p['provision_id']}", "sha256": FIXTURE_SHA,
            "source_file": "synthetic-fixture", "answer_eligible": True, "verification_status": "synthetic"}))
    return docs


def run_case(server, case, passages) -> dict:
    ga = server.grounded_answer
    docs = fixture_docs(case, passages)
    # The model's first response, then (optionally) its response to the conflict-aware retry. A fixture without
    # "retry_response" models a generator that repeats itself.
    outputs = [r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)
               for r in (case["model_response"], case.get("retry_response", case["model_response"]))]
    gen = ga.MockGenerator(fn=lambda _p, _c: outputs[min(len(gen.calls), 2) - 1])
    captured = []
    real_answer = ga.answer

    def spy(*a, **k):
        result = real_answer(*a, **k)
        captured.append(result)
        return result
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(server, "grounded_gate_errors", lambda: []))
        stack.enter_context(mock.patch.object(server, "retrieve", lambda q: list(docs)))
        stack.enter_context(mock.patch.object(server, "ANSWER_GENERATOR", gen))
        stack.enter_context(mock.patch.dict(server.SOURCES, {FIXTURE_SHA: ("Synthetic fixture document", "Rules")}))
        stack.enter_context(mock.patch.object(ga, "answer", spy))
        stack.enter_context(mock.patch.object(server, "log_lock", lambda *a, **k: None))
        # The full /chat order: out-of-scope, penalty lock (incl. sticky), index, missing provision, Central text,
        # ambiguity, then grounded answering. Only the index check and approval refresh are bypassed.
        stack.enter_context(mock.patch.object(server, "ANSWER_MODE", "grounded"))
        stack.enter_context(mock.patch.object(server, "index_ready", lambda: True))
        stack.enter_context(mock.patch.object(server, "ensure_approval_current", lambda: None))
        sid = f"answer-quality-eval-{case['id']}"
        server.sessions[sid] = {"history": [dict(h) for h in case["history"]]}
        try:
            response = server.chat(server.ChatRequest(message=case["question"], session_id=sid))
        finally:
            server.sessions.pop(sid, None)
    reply = {"kind": response.kind, "answer": response.response}
    result = captured[0] if captured else None
    outcome = result.kind if result is not None and result.kind == "rejected" else reply["kind"]
    row = {"id": case["id"], "category": case["category"], "adversarial": case["adversarial"],
           "tags": case["tags"], "expected": case["expected_outcome"], "outcome": outcome,
           "server_kind": reply["kind"], "generator_calls": len(gen.calls),
           "errors": list(result.errors) if result is not None else [], "displayed": reply["answer"],
           "expected_error_contains": case.get("expected_error_contains"), "known_gap": case.get("known_gap"),
           "checks": [{"layer": c["layer"], "check": c["check"]} for c in (result.checks if result else [])]}
    parsed = None
    if gen.calls:
        parsed, _ = ga.parse_response(outputs[min(len(gen.calls), 2) - 1])
        row["schema_valid"] = parsed is not None
    if result is not None and outcome in ACCEPTED and parsed is not None:
        row.update(_accepted_checks(ga, parsed, result))
    return row


def _accepted_checks(ga, parsed, result) -> dict:
    """Independent re-checks of an accepted answer. They reuse the validator's identifier and word functions, so
    they confirm consistency of the pipeline, not an independent judgement."""
    known = result.contract.by_id()
    cites = [i for c in parsed.claims for i in c.evidence_ids]
    valid_cites = [i for i in cites if i in known and known[i].answer_eligible is True and known[i].chunk_id]
    complete = [bool(c.evidence_ids) for c in parsed.claims]
    mapped = []
    for c in parsed.claims:
        cited = [known[i] for i in c.evidence_ids if i in known]
        supported = set().union(*(ga.evidence_identifiers(e) for e in cited)) if cited else set()
        words = ga._content_words(ga._plain(c.text))
        pool = set().union(*(ga._content_words(e.passage) for e in cited)) if cited else set()
        overlap = len(words & pool) / len(words) if words else 1.0
        mapped.append(bool(cited) and ga.identifiers(c.text) <= supported and overlap >= ga.MIN_SUPPORT[c.kind])
    rendered, _ = ga.render(parsed, result.contract)
    return {"citations_total": len(cites), "citations_valid": len(valid_cites),
            "claims_total": len(parsed.claims), "claims_cited": sum(complete),
            "citation_set_exact": set(parsed.citations) == set(cites), "claims_mapped": sum(mapped),
            "displayed_from_claims": result.text == rendered}


# ---------------------------------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------------------------------
def rate(num, den):
    return {"rate": round(num / den, 4) if den else None, "numerator": num, "denominator": den}


def passed(row) -> bool:
    if row["outcome"] != row["expected"]:
        return False
    want = row.get("expected_error_contains")
    return not want or any(want in e for e in row["errors"])


def summarise(rows, consistency) -> dict:
    accepted = [r for r in rows if r["outcome"] in ACCEPTED and "claims_total" in r]
    called = [r for r in rows if "schema_valid" in r]
    tag = lambda t: [r for r in rows if t in r["tags"]]  # noqa: E731
    schema_bad = tag("schema_invalid")
    cites_bad = tag("citation_invalid")
    unsupported = tag("unsupported")
    identifiers = tag("identifier")
    conflicts = tag("conflict")
    refusals = [r for r in rows if r["expected"] in REFUSALS]
    should_answer = [r for r in rows if r["expected"] in ACCEPTED]
    metrics = {
        "expected_outcome_agreement": rate(sum(passed(r) for r in rows), len(rows)),
        "schema_validity_rate": rate(sum(r["schema_valid"] for r in called), len(called)),
        "malformed_output_rejection_rate": rate(sum(r["outcome"] == "rejected" for r in schema_bad), len(schema_bad)),
        "citation_validity_rate": rate(sum(r["citations_valid"] for r in accepted),
                                       sum(r["citations_total"] for r in accepted)),
        "invalid_citation_rejection_rate": rate(sum(r["outcome"] == "rejected" for r in cites_bad), len(cites_bad)),
        "citation_completeness": rate(sum(r["claims_cited"] for r in accepted if r["citation_set_exact"]),
                                      sum(r["claims_total"] for r in accepted)),
        "claim_to_evidence_mapping": rate(sum(r["claims_mapped"] for r in accepted),
                                          sum(r["claims_total"] for r in accepted)),
        "unsupported_claim_rejection_rate": rate(sum(r["outcome"] == "rejected" for r in unsupported),
                                                 len(unsupported)),
        "correct_refusal_rate": rate(sum(r["outcome"] == r["expected"] for r in refusals), len(refusals)),
        "over_refusal_rate": rate(sum(r["outcome"] not in ACCEPTED for r in should_answer), len(should_answer)),
        "conflict_detection_rate": rate(sum(r["outcome"] == r["expected"] for r in conflicts), len(conflicts)),
        "identifier_validation_rate": rate(sum(r["outcome"] == "rejected" and
                                               any("identifiers absent" in e for e in r["errors"])
                                               for r in identifiers), len(identifiers)),
        "answer_consistency": rate(sum(consistency.values()), len(consistency)),
        "displayed_text_from_claims_only": rate(sum(r["displayed_from_claims"] for r in accepted), len(accepted)),
        "guarded_cases_without_generation": rate(
            sum(r["generator_calls"] == 0 for r in rows if r["expected"] in ("restricted",) or
                (r["expected"] == "clarification" and r["category"] == "follow_up")),
            sum(1 for r in rows if r["expected"] in ("restricted",) or
                (r["expected"] == "clarification" and r["category"] == "follow_up"))),
    }
    def rejected_rate(tag_name):
        rs = [r for r in rows if tag_name in r["tags"] and r["expected"] == "rejected"]
        return rate(sum(r["outcome"] == "rejected" for r in rs), len(rs))
    controls = tag("control")
    metrics.update({
        "negation_change_rejection_rate": rejected_rate("negation"),
        "exception_omission_rejection_rate": rejected_rate("exception"),
        "condition_change_rejection_rate": rejected_rate("condition"),
        "numeric_change_rejection_rate": rejected_rate("numeric"),
        "composition_rejection_rate": rejected_rate("composition"),
        "uncited_conflict_rejection_rate": rejected_rate("uncited_conflict"),
        "false_positive_rate_on_controls": rate(sum(r["outcome"] == "rejected" for r in controls), len(controls)),
    })
    retried = [r for r in rows if r["generator_calls"] == 2]
    metrics.update({
        "conflict_retries": len(retried),
        "conflict_retries_accepted": sum(r["outcome"] in ACCEPTED for r in retried),
        "generator_calls_total": sum(r["generator_calls"] for r in rows),
    })
    rejected = [r for r in rows if r["outcome"] == "rejected"]
    layers = {
        "rejected_cases": len(rejected),
        "deterministic_only": sum(all(c["layer"] == "deterministic" for c in r.get("checks", [])) for r in rejected),
        "heuristic_only": sum(all(c["layer"] == "heuristic" for c in r.get("checks", [])) for r in rejected),
        "both": sum(len({c["layer"] for c in r.get("checks", [])}) == 2 for r in rejected),
        "check_counts": dict(sorted(collections.Counter(
            f"{c['layer']}:{c['check']}" for r in rejected for c in {(x["layer"], x["check"]): x
                                                                      for x in r.get("checks", [])}.values()).items())),
    }
    failures = [r for r in rows if not passed(r)]
    by_cat = collections.defaultdict(lambda: {"cases": 0, "passed": 0})
    for r in rows:
        by_cat[r["category"]]["cases"] += 1
        by_cat[r["category"]]["passed"] += passed(r)
    return {
        "disclaimer": DISCLAIMER,
        "cases": len(rows), "adversarial_cases": sum(r["adversarial"] for r in rows),
        "metrics": metrics,
        "rejections_by_layer": layers,
        "by_category": dict(sorted(by_cat.items())),
        "failures": [{"id": r["id"], "category": r["category"], "expected": r["expected"], "outcome": r["outcome"],
                      "errors": r["errors"], "known_gap": r["known_gap"]} for r in failures],
        "unexpected_failures": [r["id"] for r in failures if not r["known_gap"]],
        "known_gaps_still_open": [r["id"] for r in failures if r["known_gap"]],
        "known_gaps_now_passing": [r["id"] for r in rows if r["known_gap"] and passed(r)],
        "rows": rows,
    }


def evaluate(fixtures_path=FIXTURES) -> dict:
    data = json.loads(Path(fixtures_path).read_text(encoding="utf-8"))
    server, calls = load_pipeline()
    rows, consistency = [], {}
    server_log = logging.getLogger("backend.server")
    level = server_log.level
    server_log.setLevel(logging.CRITICAL)  # rejections are expected here; they are reported, not logged
    try:
        rows, consistency = _run_all(server, data)
    finally:
        server_log.setLevel(level)
    result = summarise(rows, consistency)
    result["fixtures"] = {"path": str(Path(fixtures_path).name), "status": data["status"]}
    result["external_model_calls"] = dict(calls) or {"groq": 0}
    result["server_answer_mode"] = server.ANSWER_MODE
    result["server_llm_client"] = server.llm is not None
    return result


def _run_all(server, data):
    rows, consistency = [], {}
    for case in data["cases"]:
        first = run_case(server, case, data["passages"])
        second = run_case(server, case, data["passages"])
        keys = ("outcome", "server_kind", "errors", "displayed", "generator_calls")
        consistency[case["id"]] = all(first[k] == second[k] for k in keys)
        rows.append(first)
    return rows, consistency


# ---------------------------------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------------------------------
def markdown(result) -> str:
    m = result["metrics"]
    fmt = lambda v: str(v) if isinstance(v, int) else "n/a" if v["rate"] is None else \
        f"{v['rate']:.1%} ({v['numerator']}/{v['denominator']})"  # noqa: E731
    lines = ["# Grounded-answer quality evaluation (synthetic)", "", f"> {result['disclaimer']}", "",
             f"- Fixtures: {result['cases']} ({result['adversarial_cases']} adversarial)",
             f"- External model calls: {result['external_model_calls']}; server answer mode at load: "
             f"`{result['server_answer_mode']}`, model client constructed: {result['server_llm_client']}",
             f"- Unexpected failures: {len(result['unexpected_failures'])}; known validator gaps still open: "
             f"{len(result['known_gaps_still_open'])}", "",
             "## Metrics", "", "| Metric | Result |", "|---|---|"]
    lines += [f"| {k.replace('_', ' ')} | {fmt(v)} |" for k, v in m.items()]
    lb = result["rejections_by_layer"]
    lines += ["", "## Which layer rejected", "",
              "Deterministic checks (schema, evidence IDs, citation sets, status, answer = claims, identifiers, "
              "penalty) are exact rules. Heuristic checks (word overlap and the lexical meaning-preservation checks "
              "in `backend/meaning_checks.py`) only look for surface signals of a meaning change; passing them does "
              "not show that meaning or law is preserved.", "",
              f"- Rejected cases: {lb['rejected_cases']} - deterministic only {lb['deterministic_only']}, heuristic "
              f"only {lb['heuristic_only']}, both {lb['both']}", "", "| Check | Rejected cases |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in lb["check_counts"].items()]
    lines += ["", "## By category", "", "| Category | Passed |", "|---|---|"]
    lines += [f"| {k} | {v['passed']}/{v['cases']} |" for k, v in result["by_category"].items()]
    lines += ["", "## Failures", ""]
    if not result["failures"]:
        lines.append("None.")
    else:
        lines += ["| Case | Category | Expected | Outcome | Known gap |", "|---|---|---|---|---|"]
        for f in result["failures"]:
            lines.append(f"| {f['id']} | {f['category']} | {f['expected']} | {f['outcome']} | "
                         f"{(f['known_gap'] or 'no - unexpected').replace('|', '/')} |")
    if result["known_gaps_now_passing"]:
        lines += ["", f"Known gaps now passing (update the fixture notes): {result['known_gaps_now_passing']}"]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Offline grounded-answer quality evaluation (synthetic fixtures).")
    ap.add_argument("--fixtures", default=FIXTURES)
    ap.add_argument("--json")
    ap.add_argument("--markdown")
    a = ap.parse_args(argv)
    result = evaluate(a.fixtures)
    if a.json:
        Path(a.json).write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    report = markdown(result)
    if a.markdown:
        Path(a.markdown).write_text(report, encoding="utf-8")
    print(report)
    return 1 if result["unexpected_failures"] or result["external_model_calls"].get("groq") else 0


if __name__ == "__main__":
    sys.exit(main())
