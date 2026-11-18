"""Stage 4F: a narrow, evidence-bound exception for NEGATED eligibility status in the penalty check of a model answer.

Problem (Stage 4E): the penalty guard (server.answer_drift_reason -> penalty_lock_reason) is deliberately lexical and
conservative. Rule 6 / Rule 52 say the licensing authority may enquire "to ascertain that the applicant is not
disqualified or liable to be disqualified for holding a Licence". That sentence states an eligibility CHECK; it
states no penalty, amount, punishment or consequence. But two independent patterns fire on it: PENALTY_STRONG
(`disqualif\\w*` -> "penalty_term") and CONSEQUENCE_STRONG (`liable to` -> "consequence"). Fixing only the first would
move the rejection to the second.

What this module does, and no more:
  * It recognises exactly one construction: a NEGATED copula + "disqualified", optionally with "for the time being"
    in between and optionally followed by "or [is] liable to be disqualified"  ("is not disqualified", "are not
    disqualified", "isn't disqualified", "is not for the time being disqualified", "is not disqualified or liable to
    be disqualified"). The affirmative "is for the time being disqualified" is NOT recognised.
  * `mask()` blanks such a span in a piece of answer text ONLY IF a cited evidence passage contains the same
    construction (and, when the answer adds the "or liable to be disqualified" tail, the passage has the tail too).
    A model can therefore never introduce this wording on its own.
  * Everything else is untouched and still goes through the full, unchanged penalty check: a non-negated
    "disqualified", "disqualification", "shall be disqualified", suspension, cancellation, fines, offences, amounts,
    and any penalty word in the same claim. The USER-QUESTION lock (penalty_lock_reason on the question) is not
    affected at all.

This is not a legal interpretation. It encodes only the grammar of a negated status clause; whether a disqualification
PENALTY may be discussed stays locked behind legal approval.
"""
import re

_NEG = r"(?:(?:is|are|was|were|be|been)\s+not|isn['’]t|aren['’]t|wasn['’]t|weren['’]t)"
_TAIL = r"(?:\s+or\s+liable\s+to\s+be\s+disqualified)"
# Motor Vehicles Act ss.8, 9, 11 word the same eligibility check as "is not for the time being disqualified for holding
# or obtaining a driving licence". The words "for the time being" may sit between the negated copula and "disqualified".
_TIME_BEING = r"(?:for\s+the\s+time\s+being\s+)?"
NEGATED_STATUS = re.compile(rf"\b{_NEG}\s+{_TIME_BEING}disqualified\b(?P<tail>{_TAIL}?)", re.IGNORECASE)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "")


def _key(span: str) -> str:
    """Comparable form of a span: lower case, one space, contractions expanded ("isn't" -> "is not")."""
    span = span.lower().replace("’", "'")
    return re.sub(r"\b(is|are|was|were)n't\b", r"\1 not", span)


def constructions(text: str) -> list[tuple[int, int, str]]:
    """(start, end, comparable key) for every negated-status span in `text`."""
    t = _norm(text)
    return [(m.start(), m.end(), _key(m.group(0))) for m in NEGATED_STATUS.finditer(t)]


def _supported(key: str, evidence_keys: set) -> bool:
    # The answer's wording must occur in a cited passage word for word: the same copula (is/are/was...), and the
    # "or liable to be disqualified" tail only if the passage has it. A shorter answer span is fine when it is the
    # head of a longer source span ("is not disqualified" inside "is not disqualified or liable to be disqualified").
    return any(k == key or k.startswith(key + " or ") for k in evidence_keys)


def mask(text: str, evidence_passages) -> str:
    """`text` with every negated-status span that the cited evidence also contains replaced by a neutral phrase.
    Spans the evidence does not state in the same words are left in place, so the penalty check still sees them."""
    evidence_keys = {k for passage in evidence_passages for _s, _e, k in constructions(passage)}
    if not evidence_keys:
        return text
    normalised = _norm(text)
    out, last = [], 0
    for start, end, key in constructions(normalised):
        if not _supported(key, evidence_keys):
            continue
        out.append(normalised[last:start])
        out.append("is eligible")
        last = end
    if not out:
        return text
    out.append(normalised[last:])
    return "".join(out)
