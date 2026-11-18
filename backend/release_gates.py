"""Fail-closed release gates and Section 200(1) disclosure.

Trust rules (this module adds no approval mechanism; the signed approval record was removed):
  * The rule matrix is DATA. Its own claims (release_status, signed_advocate_opinion_on_file, *_enabled)
    are never trusted beyond the gate values it lists, and the code locks below always win.
  * The Central penalty gate also needs penalty answers to be switched on, which stays off.
  * Telangana fine and compounding gates are locked in code. No matrix or record value opens them here;
    that needs a code change after counsel's written conclusion.

Everything here is pure: no I/O except load_matrix, no network, no model.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass, field

from backend import offence_date as od

# --- gates ---------------------------------------------------------------------------------------------------
CENTRAL_EXPLANATION = "central_statutory_explanation"
CENTRAL_PENALTY = "central_statutory_penalty_information"
TG_FINE = "telangana_fine_information"
TG_COMPOUNDING = "telangana_compounding_calculations"
HISTORICAL = "historical_legal_explanations"
CMVR_PROCEDURAL = "cmvr_procedural_explanations"
LITIGATION = "litigation_related_explanations"

ALL_GATES = (CENTRAL_EXPLANATION, CENTRAL_PENALTY, TG_FINE, TG_COMPOUNDING, HISTORICAL, CMVR_PROCEDURAL, LITIGATION)
TELANGANA_LOCKED = frozenset({TG_FINE, TG_COMPOUNDING})  # locked in code, whatever any file says

BLOCKED, RESTRICTED, CONTROLLED_DEMO = "blocked", "restricted", "controlled_demo"
_MATRIX_VALUE = {
    "BLOCKED": BLOCKED,
    "APPROVED_WITH_RESTRICTIONS": RESTRICTED,
    "APPROVED_FOR_CONTROLLED_DEMONSTRATION": CONTROLLED_DEMO,
}
_RANK = {BLOCKED: 0, RESTRICTED: 1, CONTROLLED_DEMO: 2}


class MatrixError(ValueError):
    pass


@dataclass(frozen=True)
class Rule200:
    rule_id: str
    paths: tuple          # normalised provision paths, or the bare section when whole_section
    whole_section: bool
    frequency: str        # ANY | SECOND_OR_SUBSEQUENT_ONLY
    commencement: dt.date
    verification_status: str


@dataclass(frozen=True)
class Matrix:
    sha256: str
    matrix_id: str
    gates: dict           # gate -> BLOCKED | RESTRICTED | CONTROLLED_DEMO, as the file states
    rules_200: tuple
    warnings: tuple = ()

    @property
    def s200_complete(self) -> bool:
        """'Not listed' is only meaningful if the list is present and every entry is marked VERIFIED. The module
        cannot prove completeness against the Act; that comparison is recorded in the hardening report."""
        return bool(self.rules_200) and all(r.verification_status == "VERIFIED" for r in self.rules_200)


# --- provision paths -----------------------------------------------------------------------------------------
_SECTION = re.compile(r"^(\d+[A-Z]{0,2})")


def normalise_path(text: str) -> str:
    """'MV_ACT_1988:s.182A(1)' -> '182A(1)'; 's.184:Explanation(c)' -> '184:Explanation(c)'; whitespace and
    case-insensitive 'section'/'s.' prefixes removed."""
    s = re.sub(r"\s+", "", str(text))
    s = re.sub(r"^MV_ACT_1988:", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^(?:section|sec\.?|s\.?)", "", s, flags=re.IGNORECASE)
    return s


def section_of(path: str) -> str:
    m = _SECTION.match(path)
    return m.group(1).upper() if m else ""


def _expand(provision: str) -> tuple:
    """'182A(1),(3),(4)' -> ('182A(1)', '182A(3)', '182A(4)'). Other forms are returned as one path."""
    p = normalise_path(provision)
    sec = section_of(p)
    rest = p[len(sec):]
    if sec and "," in rest and rest.startswith("("):
        return tuple(f"{sec}{part}" for part in re.findall(r"\([^()]+\)(?:\([^()]+\))*", rest))
    return (p,)


def parse_matrix(raw: bytes) -> Matrix:
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MatrixError(f"matrix is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise MatrixError("matrix must be a JSON object")
    meta = data.get("matrix_metadata")
    gates_in = data.get("feature_release_gates")
    if not isinstance(meta, dict) or not isinstance(gates_in, dict):
        raise MatrixError("matrix needs matrix_metadata and feature_release_gates objects")
    warnings = []
    gates = {}
    for g in ALL_GATES:
        v = gates_in.get(g)
        mapped = _MATRIX_VALUE.get(v) if isinstance(v, str) else None
        if mapped is None:
            if g in gates_in:
                warnings.append(f"gate {g}: unrecognised value {v!r}, treated as blocked")
            gates[g] = BLOCKED
        else:
            gates[g] = mapped
    for extra in set(gates_in) - set(ALL_GATES):
        warnings.append(f"unknown gate {extra!r} ignored")
    for flag in ("telangana_fee_calculation_enabled", "telangana_compounding_calculation_enabled"):
        if meta.get(flag) is True:
            warnings.append(f"{flag} is true in the file; ignored, Telangana gates are locked in code")
    for g in TELANGANA_LOCKED:
        if gates.get(g) != BLOCKED:
            warnings.append(f"gate {g} is not BLOCKED in the file; forced to blocked")
    if meta.get("signed_advocate_opinion_on_file") is True:
        warnings.append("signed_advocate_opinion_on_file is a self-asserted flag; not evidence, ignored")
    rules = []
    seen = set()
    for item in data.get("section_200_post_2026_08_15_rules") or []:
        try:
            rid = str(item["rule_id"])
            if rid in seen:
                raise MatrixError(f"duplicate rule_id {rid}")
            seen.add(rid)
            freq = item.get("frequency", "ANY")
            if freq not in ("ANY", "SECOND_OR_SUBSEQUENT_ONLY"):
                raise MatrixError(f"{rid}: unknown frequency {freq!r}")
            commence = dt.date.fromisoformat(item["commencement_date"])
            if commence != od.ACT_8_2026_DATE:
                raise MatrixError(f"{rid}: commencement {commence} differs from {od.ACT_8_2026_DATE}")
            whole = item.get("scope") == "WHOLE_SECTION"
            paths = _expand(item["provision"])
            if whole:
                paths = (section_of(paths[0]),)
            rules.append(Rule200(rid, paths, whole, freq, commence, str(item.get("verification_status", ""))))
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, MatrixError):
                raise
            raise MatrixError(f"bad section 200 rule entry: {exc!r}") from exc
    return Matrix(hashlib.sha256(raw).hexdigest(), str(meta.get("matrix_id", "")), gates, tuple(rules), tuple(warnings))


MAX_MATRIX_BYTES = 1 << 20
# Error codes only. Messages never carry paths, OS error text or file content.
ERR_NOT_FOUND, ERR_UNREADABLE, ERR_TOO_LARGE, ERR_INVALID = "not_found", "unreadable", "too_large", "invalid"


def load_matrix(path) -> tuple:
    """(Matrix | None, error_code | None). A missing or invalid file is not fatal; all gates just stay closed."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read(MAX_MATRIX_BYTES + 1)
    except FileNotFoundError:
        return None, ERR_NOT_FOUND
    except OSError:
        return None, ERR_UNREADABLE
    if len(raw) > MAX_MATRIX_BYTES:
        return None, ERR_TOO_LARGE
    try:
        return parse_matrix(raw), None
    except MatrixError:
        return None, ERR_INVALID


# --- effective gates -----------------------------------------------------------------------------------------
@dataclass(frozen=True)
class GateReport:
    gates: dict
    reasons: dict = field(default_factory=dict)
    matrix_sha256: str | None = None
    matrix_warnings: tuple = ()


def effective_gates(matrix, penalty_answers: bool = False) -> GateReport:
    """Every gate defaults to blocked. A gate opens only if all hold: the matrix grants it, it is not locked in code, and (for
    the Central penalty gate) penalty answers are switched on. No signed approval record is involved."""
    gates, reasons = {}, {}
    for g in ALL_GATES:
        if g in TELANGANA_LOCKED:
            gates[g], reasons[g] = BLOCKED, "locked in code: Telangana notification and counsel conclusion required"
        elif matrix is None:
            gates[g], reasons[g] = BLOCKED, "no valid rule matrix loaded"
        elif g == CENTRAL_PENALTY and penalty_answers is not True:
            gates[g], reasons[g] = BLOCKED, "penalty answers are not enabled"
        else:
            gates[g] = matrix.gates.get(g, BLOCKED)
            reasons[g] = "matrix value" if gates[g] != BLOCKED else "matrix: blocked"
    return GateReport(gates, reasons, matrix.sha256 if matrix else None, matrix.warnings if matrix else ())


def gate_open(report: GateReport, gate: str) -> bool:
    return _RANK.get(report.gates.get(gate, BLOCKED), 0) > 0


# --- Section 200(1) disclosure -------------------------------------------------------------------------------
NOT_LISTED_PHRASE = ("not included in Section 200(1) of the Motor Vehicles Act, 1988, as amended with effect "
                     "from 15 August 2026")
NOT_LISTED_CAVEAT = ("That statement is only about compounding under Section 200(1). It does not mean the "
                     "conduct is not an offence, that no penalty applies, or that no other enforcement "
                     "mechanism exists.")
LISTED_CAVEAT = ("Whether an offence is compoundable under Section 200(1) is separate from the statutory "
                 "penalty, any State-notified compounding amount, and who may collect it.")


# '182A(3)', '190(2)(i)', '198(b)', '184:Explanation(c)'. Anything else is rejected rather than guessed at.
PROVISION_FORMAT = re.compile(r"^\d{1,3}[A-Z]{0,2}(?:\([0-9A-Za-z]{1,4}\))*(?::Explanation\([a-z]\)(?:\([0-9A-Za-z]{1,4}\))*)?$", re.ASCII)


@dataclass(frozen=True)
class Section200Result:
    status: str   # unavailable | date_required | pre_commencement | listed | listed_conditionally |
                  # partially_listed | not_listed
    text: str | None
    rule_ids: tuple = ()


def section_200_disclosure(matrix, report: GateReport, provision: str, offence_date: dt.date | None,
                           repeat_offence: bool | None = None) -> Section200Result:
    """Say whether `provision` (e.g. '182A(3)', '190(2)(i)', '184:Explanation(c)') is in the Section 200(1)
    list for an offence on `offence_date`. Never states or implies a rupee amount."""
    if matrix is None or not matrix.s200_complete or not gate_open(report, CENTRAL_PENALTY):
        return Section200Result("unavailable", None)
    if not isinstance(provision, str) or not PROVISION_FORMAT.match(normalise_path(provision)):
        return Section200Result("unavailable", None)  # unparseable input must never read as "not listed"
    if offence_date is None:
        return Section200Result("date_required", od.DATE_REQUIRED_NOTE)
    if offence_date < od.ACT_8_2026_DATE:
        return Section200Result(
            "pre_commencement",
            "The Section 200(1) list in force from 15 August 2026 is not the list for an offence on "
            f"{offence_date.isoformat()}, and this check does not cover the earlier text.")
    q = normalise_path(provision)
    sec = section_of(q)
    if not sec:
        return Section200Result("unavailable", None)
    exact, partial = [], []
    for r in matrix.rules_200:
        for p in r.paths:
            if section_of(p) != sec:
                continue
            if r.whole_section or q == p or q.startswith(p + "(") or q.startswith(p + ":"):
                exact.append(r)
            elif p.startswith(q) and len(p) > len(q):
                partial.append(r)
    if exact:
        r = exact[0]
        if r.frequency == "SECOND_OR_SUBSEQUENT_ONLY" and repeat_offence is not True:
            how = "only for a second or subsequent offence" if repeat_offence is False else \
                  "only for a second or subsequent offence; whether this is one was not stated"
            return Section200Result("listed_conditionally",
                                    f"{provision} is listed in Section 200(1) {how}. {LISTED_CAVEAT}", (r.rule_id,))
        return Section200Result("listed", f"{provision} is listed in Section 200(1). {LISTED_CAVEAT}", (r.rule_id,))
    if partial:
        return Section200Result(
            "partially_listed",
            f"Only part of {provision} is listed in Section 200(1). Name the exact sub-section or clause.",
            tuple(r.rule_id for r in partial))
    return Section200Result("not_listed", f"{provision} is {NOT_LISTED_PHRASE}. {NOT_LISTED_CAVEAT}")


# --- phrasing guard ------------------------------------------------------------------------------------------
_OVERREACH = re.compile(
    r"\b(?:not\s+(?:an?\s+)?(?:offen[cs]e|punishable|penali[sz]ed|finable)|no\s+(?:fine|penalty|punishment)"
    r"|cannot\s+be\s+(?:fined|penali[sz]ed|prosecuted)|(?:is|are)\s+not\s+(?:illegal|unlawful))\b",
    re.IGNORECASE,
)


def phrasing_problems(answer: str) -> list:
    """Flags wording that reads a Section 200(1) omission as 'not punishable'. Returns the matched snippets.
    The fixed caveats above are removed first: they contain these words only to deny them."""
    text = (answer or "").replace(NOT_LISTED_CAVEAT, "").replace(LISTED_CAVEAT, "")
    return [m.group(0) for m in _OVERREACH.finditer(text)]
