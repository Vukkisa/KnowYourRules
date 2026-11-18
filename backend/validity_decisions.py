"""Decision-record checks for the provision validity ledger (roadmap Step 3).

NOT WIRED INTO ANYTHING. No runtime module imports this file; only ``ledger_acceptance`` (itself unwired) calls it. It is a
pure checker: it opens no file, writes nothing, and changes nothing it is given.

What it checks
--------------
A ledger declares decisions (``LD-nnn``) and its facts, intervals, coverage records, interval rule and freshness window refer
to them. The ledger's own statements are not evidence. The Stage 22 decision register
(``eval/legal-validation/stage-22-legal-decision-register.json``, read-only here) is the human-maintained record, so
``check_decisions`` compares the ledger with it:

* every decision the ledger declares or uses exists in the register, once, with a well-formed ``LD-nnn`` id (A8);
* the ledger's copy (status, subject, preparer, reviewer) equals the register's: anything else is stale or forged;
* anything the ledger relies on cites a decision that is ``approved`` in the register. A reference to a pending, rejected,
  revoked, superseded or evidence-incomplete decision is rejected, and an unapproved decision never counts;
* an ``approved`` record is complete: reviewer name, designation and organisation (no placeholders, not a machine or an
  assistant), a real review date that is not in the future, a decision and rationale, a preparer who is not the reviewer,
  no open conditions, history ending in ``approved``, and evidence: every cited file (kind ``gazette_print`` included) must
  be a HELD file whose SHA-256 equals the recorded one (A12). Without a held-file table nothing can be verified, so an
  approved decision then fails closed;
* an approved fact carries evidence (file, SHA-256, locator) that its decision lists; a ``continuing_verified`` end needs the
  decision's recorded search with ``searched_on`` equal to ``checked_through``; a coverage record needs the decision's
  confirmation of the chunk-text hash and provision list;
* ``replaces`` chains are acyclic and a superseded decision cannot be cited.

What this does NOT do (Step 3 review M2, interim model "Option A")
-------------------------------------------------------------------
Nothing here authenticates a reviewer (this module does NOT authenticate any reviewer). The register's reviewer name, designation, history and review date are free text.
Since the acceptance gate now requires the register's exact SHA-256 to be bound through the signed source-status registry,
the register is ATTESTED by the offline approval authority (it signed a record that binds these exact bytes): that proves
the authority attested this register, NOT that the named reviewer approved the decision, and no reviewer key or signature
exists. The checks on names, history ordering, ``history[-1].by`` and synthetic wording are plausibility filters only; they
catch careless or machine-written records and cannot detect a plausible invented one. An approved decision must also be
pinned in the signed ledger (reviewer and preparer), so the register cannot change those two names without a re-signed chain.

``propose_status`` is the only status helper: it can write ``pending``, ``evidence_incomplete`` and ``evidence_complete``,
never ``approved`` (or any human-only status), and never edits a decided record. There is no code path here that approves.

Numbering: validity decisions are ``LD-012`` onward in the existing register format (A8). LD-001 to LD-011 are the real
Stage 22 records; none is approved, so a ledger citing them cannot carry an approved fact.
"""

from __future__ import annotations

import copy
import datetime as dt
import re
from typing import Any, Iterable, Mapping, Optional

from backend import provision_validity as _pv
from backend import source_status as _ss

__all__ = ["DecisionError", "Problem", "REGISTER_STATUSES", "TOOLING_STATUSES", "SOURCE_KINDS", "FIRST_VALIDITY_ID",
           "check_decisions", "cited_files", "propose_status", "register_is_fixture"]

Problem = _pv.Problem

REGISTER_STATUSES = ("pending", "evidence_incomplete", "evidence_complete", "approved", "rejected",
                     "requires_further_review", "revoked")
TOOLING_STATUSES = ("pending", "evidence_incomplete", "evidence_complete")   # the only statuses tooling may write
SOURCE_KINDS = ("gazette_print", "instrument_text", "commencement_notification", "amending_text", "search_record", "other")
FIRST_VALIDITY_ID = 12                                                         # LD-012 onward (A8)

_ID_RE = re.compile(r"LD-\d{3}")
_ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_MACHINE_RE = re.compile(
    r"\b(?:assistants?|claude|chatgpt|gpt\d*|llms?|copilot|bots?|tooling|tools?|automated|automation|automatic|a\.?i|gemini|"
    r"anthropic|openai|bard|mistral|llama|deepseek|grok|robots?|scripts?|scripted|machine|generated|ml)\b|language\s+model",
    re.IGNORECASE)
_LEET = str.maketrans("013457@$", "oieastas")                  # "Cl4ude" -> "Claude": a digit swap does not hide a machine name
# Words that mark a record as invented test data. A register that is not flagged "fixture": true must not contain them.
_SYNTHETIC_RE = re.compile(r"\b(?:synthetic|fixture|throwaway|fake|mock|stub|sample|example|dummy|test(?:ing)?)\b", re.IGNORECASE)
_PLACEHOLDER_ONLY_RE = re.compile(r"(?:_+|tbd|todo|placeholder|n/?a|xxx+|dummy|lorem ipsum)", re.IGNORECASE)


class DecisionError(ValueError):
    """A status change that tooling is not allowed to make."""


# ------------------------------------------------------------------------------------------------ small helpers

def _text(v: Any) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _sha(v: Any) -> bool:
    return isinstance(v, str) and _ss.SHA256_RE.fullmatch(v) is not None


def _err(code: str, subject: str, message: str) -> Problem:
    return Problem(code, "error", subject, message)


def _machine_like(v: str) -> bool:
    return _MACHINE_RE.search(v) is not None or _MACHINE_RE.search(v.translate(_LEET)) is not None


def register_is_fixture(register: Any) -> bool:
    """True only when the register is an object that declares ``"fixture": true`` (a synthetic register)."""
    return isinstance(register, Mapping) and register.get("fixture") is True


def _today(today: Optional[dt.date]) -> dt.date:
    if today is None:
        return dt.date.today()
    if not isinstance(today, dt.date) or isinstance(today, dt.datetime):
        raise TypeError("today must be a date")
    return today


# ------------------------------------------------------------------------------------------------ the register

def _index_register(register: Any, out: list) -> dict:
    """{id: record} for well-formed, unique records; problems appended to `out`. A malformed register yields {}."""
    if not isinstance(register, Mapping):
        out.append(_err("D1", "register", "the decision register must be an object"))
        return {}
    sv = register.get("schema_version")
    if sv != 1 or isinstance(sv, bool):
        out.append(_err("D1", "register", "schema_version must be 1"))
    recs = register.get("decisions")
    if not isinstance(recs, list):
        out.append(_err("D1", "register", "decisions must be a list"))
        return {}
    by_id: dict = {}
    dup: set = set()
    for i, r in enumerate(recs):
        if not isinstance(r, Mapping):
            out.append(_err("D1", f"decisions[{i}]", "a decision record must be an object"))
            continue
        did = r.get("decision_id")
        if not isinstance(did, str) or _ID_RE.fullmatch(did) is None:
            out.append(_err("D2", f"decisions[{i}]", f"decision_id {did!r} must look like LD-nnn"))
            continue
        if did in by_id or did in dup:
            dup.add(did)
            by_id.pop(did, None)
            continue
        by_id[did] = r
    for did in sorted(dup):
        out.append(_err("D3", did, "decision id appears more than once in the register"))
    return by_id


def _replacement_problems(by_id: Mapping, out: list) -> set:
    """Checks `replaces`; returns the ids that an APPROVED record has replaced (superseded decisions)."""
    superseded: set = set()
    for did, r in sorted(by_id.items()):
        rep = r.get("replaces")
        if rep is None:
            continue
        if not isinstance(rep, str) or _ID_RE.fullmatch(rep) is None:
            out.append(_err("D12", did, "replaces must be null or an LD-nnn id"))
        elif rep == did:
            out.append(_err("D12", did, "a decision cannot replace itself"))
        elif rep not in by_id:
            out.append(_err("D12", did, f"replaces {rep}, which is not in the register"))
        elif r.get("status") == "approved":
            superseded.add(rep)
    for did in sorted(by_id):                              # cycles: walk the chain, bounded by the number of records
        seen, cur = set(), did
        while isinstance(cur, str) and cur in by_id and cur not in seen:
            seen.add(cur)
            cur = by_id[cur].get("replaces")
        if isinstance(cur, str) and cur in seen:
            out.append(_err("D12", did, "the replaces chain contains a cycle"))
    return superseded


# ------------------------------------------------------------------------------------------------ approved record

def _approved_record_problems(did: str, r: Mapping, today: dt.date, held: Optional[Mapping], out: list,
                              fixture: bool = False) -> None:
    """Everything an `approved` register record must have. Evidence files must be held with a matching SHA-256."""
    rv = r.get("reviewer")
    name = None
    if not isinstance(rv, Mapping):
        out.append(_err("D6", did, "approved needs a reviewer with name, designation and organisation"))
    else:
        for k in ("name", "designation", "organisation"):
            v = rv.get(k)
            if not _text(v):
                out.append(_err("D6", did, f"reviewer.{k} is missing"))
            elif _ss.PLACEHOLDER_RE.search(v):
                out.append(_err("D6", did, f"reviewer.{k} looks like a placeholder"))
            elif _machine_like(v):
                out.append(_err("D6", did, f"reviewer.{k} names a machine or an assistant; only a human may approve"))
        name = rv.get("name") if _text(rv.get("name")) else None
    d = r.get("review_date")
    if not isinstance(d, str) or _ISO_RE.fullmatch(d) is None:
        out.append(_err("D6", did, "review_date must be YYYY-MM-DD"))
    else:
        try:
            if dt.date.fromisoformat(d) > today:
                out.append(_err("D6", did, "review_date is in the future"))
        except ValueError:
            out.append(_err("D6", did, "review_date is not a real date"))
    for k in ("decision", "rationale"):
        v = r.get(k)
        if not _text(v) or _PLACEHOLDER_ONLY_RE.fullmatch(v.strip()):
            out.append(_err("D6", did, f"{k} is missing or a placeholder"))
    pb = r.get("prepared_by")
    if not _text(pb):
        out.append(_err("D6", did, "prepared_by is missing"))
    elif name is not None and pb.strip().casefold() == name.strip().casefold():
        out.append(_err("D6", did, "prepared_by is the reviewer: self-approval"))
    if r.get("conditions") != []:
        out.append(_err("D6", did, "conditions must be an empty list on an approved decision (open conditions keep it inactive)"))
    hist = r.get("history")
    if not isinstance(hist, list) or not hist or not isinstance(hist[-1], Mapping) or hist[-1].get("status") != "approved":
        out.append(_err("D6", did, "history must end with an entry whose status is approved"))
    else:
        _history_problems(did, hist, r.get("review_date"), name, today, out)
    if not fixture:
        texts = [(f"reviewer.{k}", rv.get(k)) for k in ("name", "designation", "organisation")] if isinstance(rv, Mapping) else []
        texts += [(k, r.get(k)) for k in ("prepared_by", "decision", "rationale")]
        for k, v in texts:
            if isinstance(v, str) and _SYNTHETIC_RE.search(v):
                out.append(_err("D6", did, f"{k} carries synthetic or test wording but the register is not flagged as a fixture"))
    _evidence_problems(did, r, held, out)


def _history_problems(did: str, hist: list, review_date: Any, reviewer: Optional[str], today: dt.date, out: list) -> None:
    """Plausibility of the recorded history. This is a filter on what the register SAYS; it authenticates nobody (see the
    trust model: the register is attested by the approval authority's signature, not signed by the reviewer)."""
    prev = None
    for i, h in enumerate(hist):
        d = h.get("date") if isinstance(h, Mapping) else None
        if not isinstance(d, str) or _ISO_RE.fullmatch(d) is None:
            out.append(_err("D6", did, f"history[{i}].date must be YYYY-MM-DD"))
            return
        try:
            day = dt.date.fromisoformat(d)
        except ValueError:
            out.append(_err("D6", did, f"history[{i}].date is not a real date"))
            return
        if day > today:
            out.append(_err("D6", did, f"history[{i}].date is in the future"))
        if prev is not None and day < prev:
            out.append(_err("D6", did, f"history[{i}].date is earlier than the entry before it"))
        prev = day
    last = hist[-1]
    if last.get("date") != review_date:
        out.append(_err("D6", did, "the approving history entry's date must equal review_date"))
    by = last.get("by")
    if not _text(by) or reviewer is None or by.strip().casefold() != reviewer.strip().casefold():
        out.append(_err("D6", did, "the approving history entry must be by the named reviewer"))


def _sources(r: Mapping) -> Optional[list]:
    src = r.get("supporting_sources")
    return src if isinstance(src, list) else None


def _evidence_problems(did: str, r: Mapping, held: Optional[Mapping], out: list) -> None:
    src = _sources(r)
    if not src:
        out.append(_err("D7", did, "approved needs at least one supporting source"))
        return
    seen: dict = {}
    for i, s in enumerate(src):
        w = f"supporting_sources[{i}]"
        if not isinstance(s, Mapping):
            out.append(_err("D7", did, f"{w} must be an object"))
            continue
        f, h, kind = s.get("file"), s.get("sha256"), s.get("kind", "other")
        if not _text(f):
            out.append(_err("D7", did, f"{w}.file is missing"))
            continue
        if not _sha(h):
            out.append(_err("D7", did, f"{w}.sha256 must be 64 lowercase hex characters"))
            continue
        if kind not in SOURCE_KINDS:
            out.append(_err("D7", did, f"{w}.kind must be one of {list(SOURCE_KINDS)}"))
        if f in seen and seen[f] != h:
            out.append(_err("D7", did, f"{w}: file {f!r} is cited with two different hashes"))
        seen[f] = h
        if held is None:
            out.append(_err("D8", did, f"{w}: no table of held files was supplied, so {f!r} cannot be verified"))
        elif f not in held:
            out.append(_err("D8", did, f"{w}: {f!r} is not a held file" +
                            (" (a Gazette print must be held, A12)" if kind == "gazette_print" else "")))
        elif held[f] != h:
            out.append(_err("D8", did, f"{w}: the SHA-256 of held file {f!r} does not match the record"))


# ------------------------------------------------------------------------------------------------ ledger references

def _facts(ledger: Any):
    """(where, fact) for every fact slot of the ledger."""
    for op in ledger.operations:
        if op.effective_from is not None:
            yield f"operation {op.id}.effective_from", op.effective_from
    for v in ledger.versions:
        if v.interval.start is not None:
            yield f"version {v.key}.start", v.interval.start
        if v.interval.end is not None:
            yield f"version {v.key}.end", v.interval.end


def _references(ledger: Any) -> list:
    """(decision id, where, role, payload) for everything in the ledger that refers to a decision."""
    refs = []
    for where, f in _facts(ledger):
        if f.decision_ref is not None:
            refs.append((f.decision_ref, where, "fact", f))
    for op in ledger.operations:
        if op.decision_ref is not None:
            refs.append((op.decision_ref, f"operation {op.id}", "operation", op))
    for v in ledger.versions:
        iv = v.interval
        if iv.end_state == "continuing_verified" and iv.decision_ref is not None:
            refs.append((iv.decision_ref, f"version {v.key}.end", "continuing", iv))
    for i, c in enumerate(ledger.coverage):
        if c.decision_ref is not None:
            refs.append((c.decision_ref, f"coverage[{i}]", "coverage", c))
    if ledger.interval_rule is not None:
        refs.append((ledger.interval_rule, "interval_rule", "rule", None))
    if ledger.freshness_ref is not None:
        refs.append((ledger.freshness_ref, "freshness_window", "freshness", None))
    return refs


def cited_files(ledger: Any, register: Any) -> list:
    """Relative file names whose bytes a caller must hash to build the held-file table: the sources of every register record
    the ledger declares or uses, and the evidence files of its facts. Names only; nothing is opened. Never raises."""
    try:
        by_id = _index_register(register, [])
        ids = {d.decision_id for d in ledger.decisions} | {r[0] for r in _references(ledger)}
        out = set()
        for did in ids:
            for s in (_sources(by_id.get(did, {})) or []):
                if isinstance(s, Mapping) and _text(s.get("file")):
                    out.add(s["file"])
        for _, f in _facts(ledger):
            for e in f.evidence:
                if _text(e.get("file")):
                    out.add(e["file"])
        return sorted(out)
    except Exception:  # noqa: BLE001 - a helper for building a table; callers fail closed on a missing entry
        return []


# ------------------------------------------------------------------------------------------------ the check

def check_decisions(ledger: Any, register: Any, *, corpus_files: Optional[Mapping] = None,
                    today: Optional[dt.date] = None) -> list:
    """Compare the ledger with the decision register. Returns Problems; every problem is an `error`, and a ledger with any
    error must be rejected. An empty list means only that these checks passed (not that the ledger is correct).

    ``corpus_files`` maps a relative file name to the SHA-256 of the held file. ``None`` means "nothing could be verified",
    which makes every approved decision fail closed. ``today`` bounds review dates; the acceptance gate passes its own
    trusted clock, never a caller's."""
    out: list = []
    try:
        today = _today(today)
        held = None if corpus_files is None else dict(corpus_files)
        fixture = register_is_fixture(register)
        by_id = _index_register(register, out)
        superseded = _replacement_problems(by_id, out)
        refs = _references(ledger)
        declared = {d.decision_id: d for d in ledger.decisions}
        needed = sorted(set(declared) | {r[0] for r in refs})

        # per decision: existence, agreement with the ledger's copy, and (when approved) a complete record
        status_of: dict = {}
        for did in needed:
            r = by_id.get(did)
            if r is None:
                out.append(_err("D4", did, "the decision is not in the decision register"))
                continue
            st = r.get("status")
            if st not in REGISTER_STATUSES:
                out.append(_err("D1", did, f"status must be one of {list(REGISTER_STATUSES)}"))
                continue
            status_of[did] = st
            d = declared.get(did)
            if d is not None:
                if d.status != st:
                    out.append(_err("D5", did, f"stale: the ledger says {d.status!r}, the register says {st!r}"))
                if d.subject != r.get("subject"):
                    out.append(_err("D5", did, "the ledger's subject differs from the register's (an id reused for another matter?)"))
                if d.prepared_by is not None and d.prepared_by != r.get("prepared_by"):
                    out.append(_err("D5", did, "the ledger's prepared_by differs from the register's"))
                rv = r.get("reviewer")
                if d.reviewer is not None and (not isinstance(rv, Mapping) or d.reviewer != rv.get("name")):
                    out.append(_err("D5", did, "the ledger's reviewer differs from the register's"))
            if st == "approved":
                _approved_record_problems(did, r, today, held, out, fixture)
                if d is None or d.reviewer is None or d.prepared_by is None:
                    out.append(_err("D15", did, "an approved decision must be declared in the signed ledger with its reviewer and "
                                    "preparer, so the attested register cannot change them unnoticed"))
                if did in superseded:
                    out.append(_err("D12", did, "this decision has been replaced by a later approved decision"))
        approved = {d for d, s in status_of.items() if s == "approved" and d not in superseded}

        # every reference must land on an approved decision, and approved facts need evidence the decision lists
        for did, where, role, payload in refs:
            if did not in by_id:
                continue                                              # already reported as D4
            if did not in approved:
                st = status_of.get(did, "unknown")
                why = "revoked" if st == "revoked" else ("superseded" if did in superseded else f"{st}")
                out.append(_err("D14", where, f"relies on {did}, which is {why}, not approved: an unapproved decision never counts"))
                continue
            rec = by_id[did]
            if role == "fact":
                _fact_evidence_problems(did, where, payload, rec, held, out)
            elif role == "continuing":
                _search_problems(did, where, payload, rec, out)
            elif role == "coverage":
                _coverage_problems(did, where, payload, rec, out)
        for d in ledger.decisions:                                     # a declared-approved decision must really be approved
            if d.status == "approved" and d.decision_id in by_id and d.decision_id not in approved:
                out.append(_err("D14", d.decision_id, "the ledger declares this decision approved but it is not approved in the register"))
    except Exception as exc:  # noqa: BLE001 - a checker that cannot finish has not passed
        out.append(_err("D0", "check_decisions", f"the check could not be completed ({exc.__class__.__name__})"))
    seen, uniq = set(), []
    for p in out:
        k = (p.code, p.subject, p.message)
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


def _fact_evidence_problems(did, where, fact, rec, held, out) -> None:
    if fact.state != "approved":
        return                                                        # a non-approved fact is inert; its reference was already checked
    if not fact.evidence:
        out.append(_err("D9", where, f"an approved fact needs evidence (file, SHA-256, locator); {did} backs it"))
        return
    listed = {(s.get("file"), s.get("sha256")) for s in (_sources(rec) or []) if isinstance(s, Mapping)}
    for i, e in enumerate(fact.evidence):
        w = f"{where}.evidence[{i}]"
        f, h, loc = e.get("file"), e.get("sha256"), e.get("locator")
        if not _text(f) or not _sha(h) or not _text(loc):
            out.append(_err("D9", w, "evidence needs a file, a 64-hex SHA-256 and a locator"))
        elif (f, h) not in listed:
            out.append(_err("D9", w, f"{f!r} with this hash is not among {did}'s supporting sources"))
        elif held is not None and held.get(f) != h:
            out.append(_err("D8", w, f"{f!r} is not held with this SHA-256"))


def _search_problems(did, where, iv, rec, out) -> None:
    sr = rec.get("search_record")
    if not isinstance(sr, Mapping):
        out.append(_err("D10", where, f"a continuing_verified claim needs {did}'s recorded no-later-amendment search (search_record)"))
        return
    for k in ("scope", "searcher", "result"):
        if not _text(sr.get(k)):
            out.append(_err("D10", where, f"search_record.{k} is missing"))
    srcs = sr.get("sources")
    if not isinstance(srcs, list) or not srcs or not all(_text(x) for x in srcs):
        out.append(_err("D10", where, "search_record.sources must list what was searched"))
    on = sr.get("searched_on")
    if isinstance(on, bool) or not isinstance(on, int) or on != iv.checked_through:
        out.append(_err("D10", where, "search_record.searched_on must equal the ledger's checked_through"))


def _coverage_problems(did, where, cov, rec, out) -> None:
    cc = rec.get("coverage_confirmation")
    items = [cc] if isinstance(cc, Mapping) else (cc if isinstance(cc, list) else None)
    if not items or not all(isinstance(x, Mapping) for x in items):
        out.append(_err("D11", where, f"a coverage record needs {did}'s coverage_confirmation (chunk text hash and provisions)"))
        return
    want = (cov.selector.get("text_sha256"), sorted(cov.provisions))
    for x in items:
        provs = x.get("provisions")
        if x.get("text_sha256") == want[0] and isinstance(provs, list) and sorted(map(str, provs)) == want[1]:
            return
    out.append(_err("D11", where, "no coverage_confirmation matches this record's chunk text hash and provision list"))


# ------------------------------------------------------------------------------------------------ status proposals

def propose_status(decision: Mapping, new_status: str, *, by: str = "tooling", date: Optional[dt.date] = None) -> dict:
    """A copy of `decision` with a tooling-writable status and a history entry. Raises DecisionError for ``approved`` and
    for every other human-only status, and for a record that a human has already decided. Never mutates its input."""
    if not isinstance(decision, Mapping):
        raise DecisionError("a decision record must be an object")
    if new_status not in TOOLING_STATUSES:
        raise DecisionError(f"tooling may only write {list(TOOLING_STATUSES)}; {new_status!r} needs a human reviewer")
    if decision.get("status") in ("approved", "rejected", "requires_further_review", "revoked"):
        raise DecisionError("a decided record is never edited; record a new decision that replaces it")
    if not _text(by):
        raise DecisionError("by must name who made the change")
    out = copy.deepcopy(dict(decision))
    out["status"] = new_status
    hist = out.get("history")
    out["history"] = (list(hist) if isinstance(hist, list) else []) + [
        {"date": (date or dt.date.today()).isoformat(), "status": new_status, "by": by}]
    return out
