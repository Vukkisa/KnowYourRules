#!/usr/bin/env python3
"""Runs eval/final-evaluation-120.json against the assistant and scores each answer against the stated expectation.

Two ways to run it (standard library only; nothing in the application is changed or mocked):

  --mode local            in-process FastAPI TestClient against THIS working tree. No model, no retrieval index: it exercises the
                          deterministic layers (e-Challan lookup, penalty lock, other-state refusal, language notice). Questions whose
                          expected path is "model" are skipped, and any question that falls through to the model path is reported as
                          not evaluated, never as passed.
  --mode live --base-url  a Vercel PREVIEW deployment (real model); Production URLs are refused. The Preview's Protection Bypass for
                          Automation secret must be in the VERCEL_AUTOMATION_BYPASS_SECRET environment variable. Paced to stay under the 10-requests-per-minute limit; a 429 is retried after
                          the server's Retry-After, never worked around.

Scoring is rule-based and conservative. It checks behaviour class, cited evidence ids, invented amounts and combined totals. It does NOT
judge legal correctness: every model-path answer and every question with `needs_human_verification` is listed for a human."""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "eval" / "final-evaluation-120.json"

ANSWER_KINDS = {"website_amount", "answer", "conflict"}
REFUSAL_KINDS = {"restricted", "no_support", "out_of_scope", "missing_provision"}
NOT_EVALUABLE = {"unavailable", "development"}
AMOUNT = re.compile(r"(?:₹|\bRs\.?)\s*([\d,]+)")
NOTE_LINE = re.compile(r"^Your question mentions")


def figures(text: str) -> set:
    return {int(x.replace(",", "")) for x in AMOUNT.findall(text) if x.strip(",")}

# ---- live-mode safety: Preview only ----------------------------------------------------------------------------------------------
# Live evaluation sends the full question set to a deployed API. It is allowed against a Vercel Preview deployment of this project and
# nothing else. There is deliberately no flag, environment variable or other override: to evaluate Production, this guard would have to be
# edited in the source, in review.
#
# Production hostnames are listed explicitly because an immutable Production deployment URL has exactly the same shape as a Preview one.
# When a new Production deployment is made, its hostname must be added here (`vercel ls knowyourrules-api --environment production`).
PRODUCTION_HOSTS = frozenset({
    "knowyourrules-api.vercel.app",                                   # the Production API alias
    "knowyourrules-api-jayanths-projects-93d42e21.vercel.app",        # its team-scoped alias
    "knowyourrules-fmn74wo39-jayanths-projects-93d42e21.vercel.app",  # Production deployments
    "knowyourrules-1v2rg5ruw-jayanths-projects-93d42e21.vercel.app",
    "knowyourrules-mjd46d1cc-jayanths-projects-93d42e21.vercel.app",
    "knowyourrules-o2ztn8u2i-jayanths-projects-93d42e21.vercel.app",
    "knowyourrules-pvq81z3ri-jayanths-projects-93d42e21.vercel.app",
    "knowyourrules-9v7zzhhky-jayanths-projects-93d42e21.vercel.app",
    "knowyourrules-gtpqhsrvw-jayanths-projects-93d42e21.vercel.app",
    "knowyourrules-i6i84nr1i-jayanths-projects-93d42e21.vercel.app",  # a Production deployment (target production), though no longer aliased
    "knowyourrules-qre3ptwty-jayanths-projects-93d42e21.vercel.app",  # the previous Production deployment (corpus bundled)
    "knowyourrules-1tiag7mnw-jayanths-projects-93d42e21.vercel.app",  # the current Production deployment (token-budget fix)
})
_TEAM = "jayanths-projects-93d42e21"
# Only two shapes are accepted: a deployment URL (`knowyourrules-<9 chars>-<team>.vercel.app`) or a branch alias
# (`knowyourrules-api-git-<branch>-<team>.vercel.app`). The `main` and `master` branch aliases follow the production branch, so they are refused.
PREVIEW_HOST = re.compile(
    rf"knowyourrules-(?:[a-z0-9]{{9}}|api-git-(?!(?:main|master)-)[a-z0-9]+(?:-[a-z0-9]+)*)-{re.escape(_TEAM)}\.vercel\.app")
PREVIEW_ONLY_NOTICE = ("Live evaluation is Preview-only. It sends the whole question set to the API, so it only runs against a Vercel Preview "
                       "deployment of this project, never Production. There is no override.")


class UnsafeBaseURL(ValueError):
    """The --base-url is Production, malformed, ambiguous or not a recognised Preview deployment."""


def validate_preview_base_url(raw) -> str:
    """Return the normalised `https://<host>` of a Preview deployment, or raise UnsafeBaseURL. Pure string work: it sends nothing."""
    if not isinstance(raw, str) or not raw:
        raise UnsafeBaseURL("the base URL is empty or not text")
    low = raw.lower()
    # Production is refused on the raw text, before any parsing, so no scheme, case, trailing dot or slash, path, port, user-info,
    # query or fragment can hide it. A Production hostname anywhere in the text is refused, even where it would not be the host.
    for host in sorted(PRODUCTION_HOSTS):
        if host in low:
            raise UnsafeBaseURL(f"{host} is a Production hostname")
    if raw != raw.strip() or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in raw) or "\\" in raw or "%" in raw:
        raise UnsafeBaseURL("the base URL has whitespace, control, non-ASCII, backslash or percent-encoded characters")
    try:
        parts = urlsplit(low)
        port = parts.port
    except ValueError as e:
        raise UnsafeBaseURL(f"the base URL cannot be parsed ({e})") from None
    if parts.scheme != "https":
        raise UnsafeBaseURL("the base URL must start with https:// (a scheme-less or non-https URL is ambiguous)")
    if "@" in parts.netloc or port is not None or parts.query or parts.fragment or ";" in low or "?" in low or "#" in low:
        raise UnsafeBaseURL("the base URL must be just https://<host>: no user-info, port, query, parameters or fragment")
    if parts.path not in ("", "/"):
        raise UnsafeBaseURL("the base URL must not have a path: the runner adds /chat itself")
    host = parts.netloc
    if not PREVIEW_HOST.fullmatch(host):
        raise UnsafeBaseURL(f"{host or '(no host)'} is not a recognised Preview deployment of knowyourrules-api")
    return f"https://{host}"


# ---- running ---------------------------------------------------------------------------------------------------------------------
class Local:
    def __init__(self):
        os.environ.setdefault("TG_ECHALLAN_FINES", "1")
        os.environ.setdefault("TG_RATE_LIMIT_REQUESTS", "1000")  # a test-run setting for this process only; production keeps its own value
        sys.path.insert(0, str(ROOT))
        from fastapi.testclient import TestClient
        from backend import server
        self.client = TestClient(server.app, raise_server_exceptions=False)

    def ask(self, question: str, sid: str):
        r = self.client.post("/chat", json={"message": question, "session_id": sid})
        try:
            return r.status_code, r.json()
        except Exception:  # noqa: BLE001
            return r.status_code, {"response": r.text[:300]}


# ---- Preview Deployment Protection -----------------------------------------------------------------------------------------------
# A Preview deployment is behind Vercel Deployment Protection. Vercel's "Protection Bypass for Automation" secret is sent in the
# `x-vercel-protection-bypass` header. The secret is read only from this environment variable and is never put in the URL, on a command line
# (visible in `ps`), in a log line, in an error message or in a results file: curl receives the header on stdin as a config file.
BYPASS_ENV = "VERCEL_AUTOMATION_BYPASS_SECRET"
BYPASS_HEADER = "x-vercel-protection-bypass"
_SECRET_FORMAT = re.compile(r"[A-Za-z0-9._~+/=-]{16,256}")  # Vercel's are 32 letters and digits; this also keeps the curl config line unambiguous
PROTECTION_STATUSES = {301, 302, 303, 307, 308, 401}  # the assistant itself never redirects or answers 401, so these are the protection layer


class MissingBypassSecret(RuntimeError):
    """The bypass secret is not set, or is not in a usable form. Never carries the value."""


class ProtectionRejected(RuntimeError):
    """Preview Deployment Protection answered instead of the assistant. Never carries the value."""


def read_bypass_secret(env=None) -> str:
    value = (os.environ if env is None else env).get(BYPASS_ENV, "")
    if not value.strip():
        raise MissingBypassSecret(
            f"{BYPASS_ENV} is not set. The Preview is behind Vercel Deployment Protection, and the runner needs the project's Protection Bypass "
            f"for Automation secret in that environment variable (it is read from the environment only; there is no flag for it)")
    if not _SECRET_FORMAT.fullmatch(value):
        raise MissingBypassSecret(f"{BYPASS_ENV} is set but is not in the form of a Vercel bypass secret (letters, digits and . _ ~ + / = - only, 16 to 256 characters, "
                                  f"no spaces or line breaks). The value is not shown")
    return value


class Live:
    def __init__(self, base: str, pace: float, secret: str | None = None):
        self.url, self.pace, self.last = validate_preview_base_url(base) + "/chat", pace, 0.0  # checked again here: nothing can reach curl unchecked
        self._sends_to = self.url  # the only address the secret may ever be sent to
        self._secret = read_bypass_secret() if secret is None else secret  # after the URL check, so Production is refused first, whatever the environment holds

    def __repr__(self):
        return f"Live(url={self.url!r})"  # never the secret

    def _curl(self, body: str):
        if self.url != self._sends_to:
            raise RuntimeError("the request address changed after validation; refusing to send the bypass secret anywhere else")
        # the secret travels on stdin as a curl config line, not in argv, the URL or the environment of the child
        config = f'header = "{BYPASS_HEADER}: {self._secret}"\n'
        r = subprocess.run(["curl", "-s", "-i", "-m", "90", "-K", "-", "-X", "POST", self.url, "-H", "content-type: application/json", "-d", body],
                           input=config, capture_output=True, text=True)
        return (r.stdout or "").replace(self._secret, "[redacted]")

    def ask(self, question: str, sid: str):
        for attempt in range(4):
            wait = self.pace - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            body = json.dumps({"message": question, "session_id": sid})
            out = self._curl(body)
            head, _, payload = re.split(r"(\r?\n\r?\n)", out, maxsplit=1) if re.search(r"\r?\n\r?\n", out) else (out, "", "")
            m = re.match(r"HTTP/\S+ (\d+)", head)
            status = int(m.group(1)) if m else 0
            if status in PROTECTION_STATUSES:  # stop at the first one: 120 "not evaluated" rows would say nothing
                raise ProtectionRejected(f"Preview Deployment Protection answered HTTP {status} instead of the assistant, so the bypass secret was not accepted. "
                                         f"Check that {BYPASS_ENV} is this project's Protection Bypass for Automation secret and that it is enabled for it")
            if status == 429 and attempt < 3:
                ra = re.search(r"(?i)retry-after: (\d+)", head)
                time.sleep(min(int(ra.group(1)) if ra else 30, 70) + 1)
                continue
            try:
                return status, json.loads(payload)
            except Exception:  # noqa: BLE001
                return status, {"response": payload[:300]}
        return 429, {}


# ---- scoring ---------------------------------------------------------------------------------------------------------------------
def behaviour_of(status: int, data: dict) -> str:
    kind = data.get("kind")
    if status != 200 or kind in NOT_EVALUABLE or not kind:
        return "not_evaluated"
    if kind in ANSWER_KINDS:
        text = data.get("response", "")
        return "partial" if ("**Not matched:**" in text or "could not be matched" in text) else "answer"
    if kind == "clarification":
        return "clarification"
    if kind in REFUSAL_KINDS:
        return "refusal"
    return "not_evaluated"


def reason_of(kind, text: str) -> str | None:
    """Why the assistant did not answer, read from its own wording (for the report; it does not change any score)."""
    if kind in ANSWER_KINDS or not kind:
        return None
    t = text or ""
    if "English questions only" in t:
        return "english_only_notice"
    if "Penalties and compounding fees are not available yet" in t:
        return "penalty_lock"
    if "released after legal review" in t or "isn't available yet" in t:
        return "legal_review_gate"
    if "don't rewrite follow-up questions" in t:
        return "follow_up_mode"
    if "Please ask a question about traffic law" in t:
        return "off_topic_prompt"
    return {"out_of_scope": "other_state", "no_support": "no_support", "clarification": "clarification"}.get(kind, kind)


def cited(data: dict) -> tuple[set, set]:
    ids, provs = set(), set()
    for s in data.get("sources") or []:
        for p in s.get("passages") or []:
            pid = p.get("provision_id")
            if pid:
                ids.add(pid)
                provs.add(f"{p.get('manifest_id') or s.get('document_id') or ''}::{pid}")
    return ids, provs


def score(q: dict, status: int, data: dict) -> dict:
    exp, alts = q["expected_behavior"], set(q["acceptable_alternatives"])
    actual = behaviour_of(status, data)
    ev = q["expected_evidence"]
    text = data.get("response", "") or ""
    ids, provs = cited(data)
    flags, detail = [], {}
    groups = ev["offence_groups"] or ([ev["echallan_entries"]] if ev["echallan_entries"] else [])
    covered = [g for g in groups if set(g) & ids]
    detail["groups_expected"], detail["groups_cited"] = len(groups), len(covered)
    stat_hit = [p for p in ev["statutory_provisions"] if p.split("::")[1] in ids]
    detail["statutory_expected"], detail["statutory_cited"] = len(ev["statutory_provisions"]), len(stat_hit)

    out = {"actual_behavior": actual, "kind": data.get("kind"), "http": status, "flags": flags, "detail": detail, "reason": reason_of(data.get("kind"), text)}
    if actual == "not_evaluated":
        out["outcome"] = "not_evaluated"
        return out

    in_scope = {exp} | alts
    answerish = actual in ("answer", "partial")
    ok_class = actual in in_scope or (answerish and bool(in_scope & {"answer", "partial"}))

    # amounts: every rupee figure must be printed in a cited source row (user-stated figures are quoted back as unconfirmed, not used)
    shown = figures("\n".join(l for l in text.splitlines() if not NOTE_LINE.match(l)))
    if answerish and shown:
        source_fig = set()
        for s in data.get("sources") or []:
            for p in s.get("passages") or []:
                source_fig |= figures(p.get("text", ""))
        if data.get("kind") != "website_amount" or not shown <= source_fig:
            flags.append("amount_not_in_cited_source")
            detail["unsupported_figures"] = sorted(shown - source_fig) if data.get("kind") == "website_amount" else sorted(shown)
    head = next((l for l in text.splitlines() if l.startswith("**Result:")), "")
    if answerish and re.search(r"₹0\b", head):
        flags.append("zero_shown_as_fine")
    if q["total_requested"] and answerish and not re.search(r"I can't give one|not added|have not added", text):
        flags.append("combined_total_not_refused")

    if not ok_class:
        if answerish and exp in ("refusal", "clarification"):
            out["outcome"] = "incorrect_answer"
        elif actual in ("refusal", "clarification") and exp in ("answer", "partial"):
            out["outcome"] = "incorrect_refusal"
        else:
            out["outcome"] = "incorrect_answer" if answerish else "incorrect_refusal"
        return out

    if actual == "refusal":
        out["outcome"] = "correct_refusal"
    elif actual == "clarification":
        out["outcome"] = "correct_clarification"
    else:
        has_expect = bool(groups or ev["statutory_provisions"])
        multi = len(groups) >= 2
        if has_expect:
            ok_cite = (len(covered) == len(groups) if groups else True) and (bool(stat_hit) if ev["statutory_provisions"] else True)
            if groups and not covered:
                flags.append("citation_failure")
            if ev["statutory_provisions"] and not stat_hit:
                flags.append("citation_failure")
            if multi and len(covered) < len(groups):
                flags.append("multi_offence_failure")
            if not ok_cite and groups and covered and "citation_failure" not in flags:
                pass
            if "citation_failure" in flags or "amount_not_in_cited_source" in flags or "zero_shown_as_fine" in flags or "combined_total_not_refused" in flags:
                out["outcome"] = "incorrect_answer"
            elif not ok_cite:  # some, not all, of several offences were cited
                out["outcome"] = "incomplete_answer"
            else:
                out["outcome"] = "correct_partial" if exp == "partial" else "correct_answer"
        else:  # an answer is tolerated here but nothing is defined to check it against
            out["outcome"] = "unchecked_answer"
            flags.append("no_evidence_defined")
    if exp == "refusal" and answerish and out["outcome"] in ("correct_answer", "correct_partial"):
        out["outcome"] = "correct_partial"
    return out


# ---- driver ----------------------------------------------------------------------------------------------------------------------
def run(mode: str, base: str | None, pace: float, only_ids=None):
    ds = json.loads(DATASET.read_text(encoding="utf-8"))["questions"]
    runner = Local() if mode == "local" else Live(base, pace)
    results = []
    for i, q in enumerate(ds):
        if only_ids and q["id"] not in only_ids:
            continue
        if mode == "local" and q["expected_path"] == "model":
            results.append({"id": q["id"], "outcome": "not_evaluated", "reason": "model path: needs a live model and index", "actual_behavior": "not_evaluated"})
            continue
        status, data = runner.ask(q["question"], f"final-eval-{mode}-{i}")
        r = score(q, status, data)
        if mode == "local" and r["outcome"] == "not_evaluated":
            r["reason"] = "fell through to the model path, which cannot run locally"
        r.update({"id": q["id"], "response_excerpt": (data.get("response") or "")[:300].replace("\n", " "),
                  "sources_cited": sorted({p.get("provision_id") for s in data.get("sources") or [] for p in s.get("passages") or [] if p.get("provision_id")})})
        results.append(r)
        print(f"{q['id']:<6}{r['outcome']:<22}{r['actual_behavior']:<14}{(r['kind'] or ''):<15}{q['question'][:55]}", flush=True)
    return ds, results


def summarise(ds, results):
    by = {r["id"]: r for r in results}
    qs = {q["id"]: q for q in ds}
    c = Counter(r["outcome"] for r in results)
    flags = Counter(f for r in results for f in r.get("flags", []))
    cats = defaultdict(Counter)
    for i, r in by.items():
        cats[qs[i]["category"]][r["outcome"]] += 1
    human = [i for i in by if qs[i].get("needs_human_verification") or by[i].get("actual_behavior") in ("answer", "partial") and qs[i]["expected_path"] == "model"]
    reasons = Counter(r.get("reason") for r in results if r["outcome"] == "incorrect_refusal")
    return {"incorrect_refusal_reasons": dict(reasons), "total_in_dataset": len(ds), "evaluated": sum(v for k, v in c.items() if k != "not_evaluated"), "outcomes": dict(c), "flags": dict(flags),
            "by_category": {k: dict(v) for k, v in cats.items()}, "needs_human_ids": human}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["local", "live"], required=True)
    ap.add_argument("--base-url")
    ap.add_argument("--pace", type=float, default=7.0, help="seconds between live requests (the API allows 10 per minute)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", help="comma-separated question ids")
    a = ap.parse_args()
    if a.mode == "live" and not a.base_url:
        ap.error("--base-url is required for live mode")
    if a.base_url is not None:  # checked in either mode, before anything runs or any file is written
        try:
            a.base_url = validate_preview_base_url(a.base_url)
        except UnsafeBaseURL as e:
            sys.exit(f"REFUSED: {e}.\n{PREVIEW_ONLY_NOTICE}\nUse the URL of a Preview deployment (`vercel ls knowyourrules-api --environment preview`).")
    if a.mode == "live":  # before the first request: a missing or unusable secret stops the run here
        try:
            read_bypass_secret()
        except MissingBypassSecret as e:
            sys.exit(f"STOPPED: {e}.")
    try:
        ds, results = run(a.mode, a.base_url, a.pace, set(a.only.split(",")) if a.only else None)
    except (ProtectionRejected, MissingBypassSecret) as e:
        sys.exit(f"STOPPED: {e}. Nothing was written.")
    summary = summarise(ds, results)
    Path(a.out).write_text(json.dumps({"mode": a.mode, "base_url": a.base_url, "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                       "summary": summary, "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary["outcomes"], indent=1))


if __name__ == "__main__":
    main()
