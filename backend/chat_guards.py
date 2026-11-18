"""Deterministic pre-answer guards for /chat: release gates, Section 200(1) disclosure and offence-date bands.

Pure functions, no I/O, no model. They run before any retrieval or model call and only ever REFUSE or
DISCLOSE from verified data; they never add permissions. A guard returns None when the message is not in a
gated area, in which case the normal pipeline (which has its own checks) continues.

Gate decisions come from a release_gates.GateReport built from the signed approval; nothing here reads a
file or trusts the message for permission. Message classification is regex-based and conservative: a
message that matches a gated area is refused unless that gate is open.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from backend import offence_date as od
from backend import release_gates as rg

_I = re.IGNORECASE

COMPOUNDING_RE = re.compile(
    r"\bcompound(?:ing|able|ed|s)?\b|\b(?:section|sec\.?|s\.?)\s*200\b|\b200\s*\(\s*1\s*\)", _I)
AMOUNT_RE = re.compile(r"\b(?:how\s+much|amounts?|fees?|fines?|rs\.?|rupees?|inr|costs?|charges?|pay(?:able)?)\b|₹", _I)
MV_ACT_RE = re.compile(r"\bmotor\s+vehicles?\s+act\b|\bmv\s*act\b|\bmva\b", _I)
EXPLAIN_RE = re.compile(r"\b(?:explain|explains|meaning|means?|what\s+(?:does|is|do|are)|says?|provides?|summari[sz]e|"
                        r"describe|define|tell\s+me\s+about)\b", _I)
CMVR_RE = re.compile(r"\bcmvr\b|\bcentral\s+motor\s+vehicles?\s+rules\b", _I)
LITIGATION_RE = re.compile(
    r"\b(?:court|lok\s+adalat|writ|petition|litigation|lawsuit|sue|suing|legal\s+notice|file\s+a\s+case|"
    r"contest(?:ing)?\s+(?:a\s+|the\s+|my\s+)?challan)\b", _I)
REPEAT_RE = re.compile(r"\b(?:second|third|repeat(?:ed)?|again|subsequent|previously\s+convicted)\b", _I)
FIRST_RE = re.compile(r"\b(?:first\s+(?:time|offen[cs]e)|never\s+(?:been\s+)?(?:fined|convicted))\b", _I)

# "section 184", "Sec. 182A(3)", "s.190(2)(i)". An explicit prefix is required: bare numbers are never taken.
SECTION_RE = re.compile(r"\b(?:sections?|sec\.?|s\.)\s*(\d{1,3})([A-Za-z]{0,2})((?:\s*\(\s*[0-9A-Za-z]{1,4}\s*\))*)", _I)
SECTION_LIST_RE = re.compile(r"\b(?:sections?|sec\.?|s\.)\s*\d{1,3}[A-Za-z]{0,2}(?:\s*\([^)]{1,4}\))*\s*(?:,|and|&|/|or)\s*\d", _I)

LABELS = {
    rg.CENTRAL_EXPLANATION: "explanations of the Central Motor Vehicles Act",
    rg.CENTRAL_PENALTY: "Central statutory penalty and Section 200(1) information",
    rg.TG_FINE: "Telangana fines and penalties",
    rg.TG_COMPOUNDING: "Telangana compounding amounts and calculations",
    rg.HISTORICAL: "the law as it stood on an earlier offence date",
    rg.CMVR_PROCEDURAL: "Central Motor Vehicles Rules procedure",
    rg.LITIGATION: "court and litigation questions",
}
BLOCKED_TEMPLATE = (
    "**This part isn't available yet: {label}.**\n\n"
    "It has not been released after legal review, so I haven't answered it and nothing here states the law on it. "
    "You can still ask what the Telangana documents I have say about a rule or procedure, or check the official "
    "Telangana Transport Department and traffic police sources.")
SECTION_DATE_PROMPT = (" Please give the date of the offence (YYYY-MM-DD or DD-MM-YYYY), because the Section 200(1) "
                       "list that applies depends on it.")
ONE_SECTION_MESSAGE = ("Please ask about one Motor Vehicles Act section at a time, naming it as \"section 184\" or "
                       "\"section 182A(3)\", so each answer is checked against the right entry.")
NAME_SECTION_MESSAGE = ("Which Motor Vehicles Act section do you mean? Name it as \"section 184\" or \"section 182A(3)\" "
                        "and I will check it against the Section 200(1) list.")
BAD_DATE_MESSAGE = ("I couldn't use that offence date. Give it as YYYY-MM-DD or DD-MM-YYYY, as a real calendar date that "
                    "is not in the future. The date is not guessed from your question.")
TEMPORAL_UNVERIFIED_MESSAGE = (
    "**I can't confirm the law for that offence date.**\n\n"
    "None of the source text I hold is dated to cover {date}, so I haven't answered. Text without usable validity dates "
    "is not treated as the law on a particular date. Check the official sources for that date.")


@dataclass(frozen=True)
class Guard:
    kind: str                  # restricted | clarification | no_support | answer
    text: str
    gate: str | None = None    # the gate that blocked it, if any
    lock: bool = False         # penalty-adjacent: short follow-ups stay locked too
    section_200: str | None = None  # Section200Result.status when this reply is a Section 200(1) disclosure


def blocked(gate: str, lock: bool = False) -> Guard:
    return Guard("restricted", BLOCKED_TEMPLATE.format(label=LABELS[gate]), gate, lock)


def parse_request_date(value, today: dt.date | None = None):
    """(date | None, error_text | None). Absent is fine; an unusable value is an error, never ignored."""
    try:
        return od.parse_offence_date(value, today), None
    except od.OffenceDateError:
        return None, BAD_DATE_MESSAGE


def provisions_in(message: str) -> list:
    """Explicit Motor Vehicles Act provisions named in the message, canonical ('182A(3)'), in order, unique."""
    out = []
    for m in SECTION_RE.finditer(message or ""):
        if m.group(1) == "200" and not m.group(2):
            continue  # "Section 200(1)" names the list being asked about, not the provision being checked
        p = f"{m.group(1)}{m.group(2).upper()}" + re.sub(r"\s+", "", m.group(3))
        if p not in out:
            out.append(p)
    return out


def _section_200(message, matrix, report, d):
    provisions = provisions_in(message)
    if not provisions:
        return Guard("clarification", NAME_SECTION_MESSAGE)
    if len(provisions) > 1 or SECTION_LIST_RE.search(message):
        return Guard("clarification", ONE_SECTION_MESSAGE)
    repeat = True if REPEAT_RE.search(message) else (False if FIRST_RE.search(message) else None)
    res = rg.section_200_disclosure(matrix, report, provisions[0], d, repeat)
    if res.status == "unavailable":
        return blocked(rg.CENTRAL_PENALTY)
    if res.status == "date_required":
        return Guard("clarification", res.text + SECTION_DATE_PROMPT, section_200=res.status)
    if res.status == "pre_commencement":
        return Guard("no_support", res.text, section_200=res.status)
    if rg.phrasing_problems(res.text):
        return blocked(rg.CENTRAL_PENALTY)  # never emit wording that reads an omission as "not an offence"
    return Guard("answer", res.text, section_200=res.status)


def evaluate(message: str, matrix, report, d: dt.date | None, rule_reference_handled: bool = False,
             penalty_cue: bool = False) -> Guard | None:
    """The first guard that applies, or None to continue. `report` is a GateReport; `matrix` may be None.
    A compounding-vocabulary message always gets a guard (never None).
    `rule_reference_handled`: the message names an explicit rule ("Rule 167A"). Rule references are classified earlier in
    /chat (missing, Central text refused, Central citation answered only from the Telangana documents that cite it), so
    the CMVR gate is for CMVR questions that name no rule.
    `penalty_cue`: the message asks for penalty content even with the compounding words removed (the caller runs the
    penalty classifier on the stripped text), so it is not a plain "is it listed" question."""
    if COMPOUNDING_RE.search(message):
        if penalty_cue or AMOUNT_RE.search(message):
            return blocked(rg.TG_COMPOUNDING, lock=True)  # amounts and calculations: code-locked gate
        if not rg.gate_open(report, rg.CENTRAL_PENALTY):
            return blocked(rg.CENTRAL_PENALTY, lock=True)
        return _section_200(message, matrix, report, d)
    if LITIGATION_RE.search(message) and not rg.gate_open(report, rg.LITIGATION):
        return blocked(rg.LITIGATION)
    if CMVR_RE.search(message) and not rule_reference_handled and not rg.gate_open(report, rg.CMVR_PROCEDURAL):
        return blocked(rg.CMVR_PROCEDURAL)
    if (MV_ACT_RE.search(message) and SECTION_RE.search(message) and EXPLAIN_RE.search(message)
            and not rg.gate_open(report, rg.CENTRAL_EXPLANATION)):
        return blocked(rg.CENTRAL_EXPLANATION)
    if d is not None and od.band_for(d) != od.BAND_POST_2026 and not rg.gate_open(report, rg.HISTORICAL):
        return blocked(rg.HISTORICAL)
    return None
