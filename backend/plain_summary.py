"""
Optional "In simple terms" summary, validated fact by fact against the cited evidence.

The model may return a short list of plain-English facts next to its legal claims. Every fact carries the exact
evidence sentence(s) it restates (`quotes`). The backend accepts the summary only when ALL of this holds, and
otherwise drops the whole summary (never repairs it) while the legal answer is shown exactly as before:

  * the answer is a plain "sufficient" answer of at most MAX_LEGAL_CLAIMS direct claims (no conflict, no
    interpretation), and the summary cites only evidence the legal claims already cite;
  * each quote is a verbatim passage of the evidence it is attributed to;
  * each fact has exactly the numbers (ages, periods, dates, amounts, counts) of its quotes, the same comparators
    (within / after / before / at least / at most / more than / less than), and the same negation, obligation,
    permission and "without" meaning (a "no person under N shall" rule may be restated as "at least N");
  * every exception or condition marker of the quotes survives as a marker in the fact, and a fact adds none;
  * every word of a fact comes from its quotes, from a short neutral list, or from a small closed list of plain
    words each licensed by an evidence word - so no new fact, reason or example can be introduced;
  * every legal claim is covered: its numbers, markers and negation appear in the summary and its words are
    quoted (so no age, date, period, restriction, exception or proviso can be left out);
  * the summary text passes the same penalty check as the claims.

Lexical checks cannot prove meaning is preserved; they are deliberately strict, and any doubt means no summary.
"""

import logging
import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from backend import meaning_checks as mc

LABEL = "In simple terms"
LEGAL_LABEL = "Legal wording"
MAX_FACTS = 4
MAX_FACT_CHARS = 260
MAX_TOTAL_CHARS = 600
MAX_LEGAL_CLAIMS = 4
MIN_QUOTE_CHARS = 20
COVERAGE = 0.8          # share of a legal claim's content words that the summary's quotes must contain
RETAINED = 0.4          # share of its quotes' content words that a fact must still use (no wholesale omission)

_I = re.IGNORECASE
log = logging.getLogger("kyr.summary")

# Diagnostics only: each rejection reason maps to a fixed check name. The reason text itself may contain words of the
# summary or the evidence, so only the name (and the fact number) is ever logged.
_CHECK_NAMES = (
    ("short list", "not_a_short_list"), ("only for plain sufficient", "not_sufficient_answer"),
    ("too many legal claims", "too_many_claims"), ("interpretation claim", "interpretation_claim"),
    ("malformed", "malformed_fact"), ("too long", "too_long"), ("markup", "markup_or_link"),
    ("repeats an evidence id", "repeated_evidence_id"), ("do not cite", "uncited_evidence"),
    ("quote too short", "quote_too_short"), ("verbatim", "quote_not_verbatim"),
    ("none of its quotes", "evidence_without_quote"), ("identifiers absent", "identifier_not_in_evidence"),
    ("numbers differ", "numbers_differ"), ("comparison words", "comparison_words_differ"),
    ("negation differs", "negation_differs"), ("'without' differs", "without_differs"),
    ("permission the quoted", "permission_added"), ("drops the permission", "permission_dropped"),
    ("obligation the quoted", "obligation_added"), ("drops the duty", "duty_dropped"),
    ("alternative", "or_changed"), ("widens the rule", "every_added"), ("'every' / 'all'", "every_dropped"),
    ("scope word", "scope_word_dropped"), ("condition or inclusion of its quoted", "condition_or_inclusion_dropped"),
    ("drops the '", "condition_dropped"), ("adds a condition", "condition_added"), ("adds 'only'", "only_added"),
    ("hedges", "hedge_without_exception"), ("too little of its quoted", "too_little_retained"),
    ("leaves out part of its quoted", "list_item_dropped"), ("not in the quoted evidence", "unlicensed_words"),
    ("not covered by the summary", "claim_not_covered"), ("states [", "claim_number_missing"),
    ("condition that the summary leaves out", "claim_condition_missing"),
    ("restriction that the summary", "claim_restriction_missing"), ("'without' limit", "claim_restriction_missing"),
    ("limit (", "claim_limit_missing"), ("that the summary leaves out", "claim_condition_missing"),
    ("penalty", "penalty"),
)


def check_name(reason: str | None) -> str | None:
    if not reason:
        return None
    return next((name for needle, name in _CHECK_NAMES if needle in reason), "other")


def log_outcome(request_id, supplied: bool, reason: str | None) -> None:
    """One concise line: whether the model supplied a summary, and if it was dropped, which check dropped it (and
    which fact, by number). Never the summary, question or evidence text."""
    if not supplied:
        log.info("summary %s: model supplied none", request_id)
    elif reason:
        m = re.match(r"fact (\d)", reason)
        log.info("summary %s: supplied, dropped by check=%s%s", request_id, check_name(reason),
                 f" fact={m.group(1)}" if m else "")
    else:
        log.info("summary %s: supplied, shown", request_id)


class SummaryFact(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: str = Field(min_length=1, max_length=MAX_FACT_CHARS)
    evidence_ids: list[str] = Field(min_length=1, max_length=3)
    quotes: list[Annotated[str, StringConstraints(min_length=MIN_QUOTE_CHARS, max_length=600)]] = Field(
        min_length=1, max_length=3)


# ---------------------------------------------------------------------------------------------------
# Lexical helpers
# ---------------------------------------------------------------------------------------------------
def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _spelling(text: str) -> str:
    text = re.sub(r"\blicen[cs]e", "licence", text, flags=_I)
    text = re.sub(r"\bmotor[ -]cycle", "motorcycle", text, flags=_I)
    return re.sub(r"\bre-(?=[a-z])", "re", text, flags=_I)


_ONES = {w: n for n, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen "
    "eighteen nineteen".split())}
_TENS = {w: 10 * n for n, w in enumerate("x x twenty thirty forty fifty sixty seventy eighty ninety".split())
         if w != "x"}
_MAGNITUDE = ("hundred", "thousand", "lakh", "lakhs", "crore", "crores", "million")
_ORDINALS = {w: n for n, w in enumerate(
    "x first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth".split()) if w != "x"}
_COUNTED = ("year", "month", "week", "day", "hour", "minute", "attempt", "time", "rupee", "person", "passenger",
            "kilometre", "kilometer", "metre", "meter", "cc")


def _digits(token: str) -> str:
    token = token.replace(",", "")
    try:
        f = float(token)
    except ValueError:
        return token
    return str(int(f)) if f == int(f) else str(f)


def number_values(text: str) -> set:
    """Every number in the text as a normalised string: digits, number words (compound too) and ordinals."""
    out = {"o" + _digits(m) for m in re.findall(r"\b(\d+)(?:st|nd|rd|th)\b", text, _I)}
    text = re.sub(r"\b\d+(?:st|nd|rd|th)\b", " ", text, flags=_I)
    out |= {_digits(m) for m in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}
    tokens = re.findall(r"[a-z]+", text.lower())
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in _TENS:
            value = _TENS[t]
            if i + 1 < len(tokens) and tokens[i + 1] in _ONES and 0 < _ONES[tokens[i + 1]] < 10:
                value += _ONES[tokens[i + 1]]
                i += 1
            out.add(str(value))
        elif t in _ONES:
            nxt = tokens[i + 1].rstrip("s") if i + 1 < len(tokens) else ""
            if t != "one" or nxt in _COUNTED:  # a bare "one" is usually a pronoun
                out.add(str(_ONES[t]))
        elif t in _MAGNITUDE:
            out.add(t.rstrip("s") if t != "lakhs" else "lakh")
        elif t in _ORDINALS:
            out.add(f"o{_ORDINALS[t]}")
        i += 1
    return out


# "under this Act", "within the meaning", "over a vehicle" are not limits: a bare preposition counts only before a number.
_NUMBER_AHEAD = (r"(?=\s+(?:the\s+age\s+of\s+|a\s+period\s+of\s+|a\s+(?:total\s+)?of\s+)?"
                 r"(?:\d|(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen"
                 r"|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)\b))")

# Comparators, longest phrase first; each span is consumed so "not less than" is not also "less than".
_COMPARATORS = (
    (r"not\s+(?:later|more)\s+than|no\s+(?:later|more)\s+than|at\s+most|not\s+exceeding|up\s+to|maximum(?:\s+of)?"
     r"|or\s+(?:less|fewer|younger|below|under)|and\s+(?:below|under|younger)", "max"),
    (r"not\s+less\s+than|no\s+less\s+than|at\s+least|minimum(?:\s+of)?|or\s+(?:more|older|above|over)"
     r"|and\s+(?:above|over|older)", "min"),
    (rf"within{_NUMBER_AHEAD}", "within"),
    (rf"more\s+than|older\s+than|greater\s+than|(?:above|over|exceeding|exceeds?){_NUMBER_AHEAD}", "gt"),
    (rf"less\s+than|younger\s+than|fewer\s+than|(?:below|under){_NUMBER_AHEAD}", "lt"),
    (r"before|prior\s+to|preceding", "before"),
    (r"after|subsequent\s+to", "after"),
)
_COMPARATOR_RES = tuple((re.compile(rf"\b(?:{p})\b", _I), c) for p, c in _COMPARATORS)
_BOUNDED_NEG = re.compile(r"\b(?:not|no)\s+(?:be\s+)?(?:less|more|later|earlier|fewer|greater)\s+th[ae]n\b"
                          r"|\bnot\s+exceeding\b", _I)
_IDIOM = re.compile(r"\bas the case may be\b", _I)
# "after attaining the age of 16" and "from 16 years of age" both set a minimum age, not an order in time.
_AGE_FLOOR = re.compile(r"\b(?:after|on|upon)\s+(?:attaining|completing|reaching)\b|\bfrom\s+(?:the\s+age\s+of\s+)?"
                        r"(?=\w+\s+years?\b)", _I)
_WITHOUT = re.compile(r"\bwithout\b", _I)
_FAIL = re.compile(r"\bfail(?:s|ed|ing|ure)?\b|\bunsuccessful(?:ly)?\b", _I)   # "does not pass" restated plainly
_STRONG_OB = re.compile(r"\b(?:must|required|requires?|mandatory|compulsory|obligatory|obliged|ha(?:s|ve) to|needs? to)\b",
                        _I)
_NEGATED_MODAL = re.compile(r"\b(?:may|can)\s+not\b|\bcannot\b|\bcan['’]t\b", _I)
_BOUND_WORDS = frozenset({"minimum", "maximum", "older", "younger", "least", "most"})


def _comparators(sentence: str) -> set:
    found, text = set(), sentence
    if _AGE_FLOOR.search(text):
        found.add("min")
        text = _AGE_FLOOR.sub(" ", text)
    for rx, cls in _COMPARATOR_RES:
        if rx.search(text):
            found.add(cls)
            text = rx.sub(" ", text)
    return found


def _flags(text: str) -> dict:
    """Negation / obligation / permission / comparators / 'without', over the text's sentences. A rule stated
    negatively about a limit ("no person under N shall", "no more than N") is read as the limit it sets
    ("at least N", "at most N"), so the two phrasings compare equal."""
    neg = ob = perm = without = strong = False
    cmps = set()
    for s in (mc.sentences(text) or [text]):
        s = _IDIOM.sub(" ", s)
        plain = _BOUNDED_NEG.sub(" ", s)
        s_neg = bool(mc._NEG_RE.search(plain) or mc._PROHIBIT_RE.search(plain) or _FAIL.search(plain))
        modal = _NEGATED_MODAL.sub(" ", plain)  # "may not" / "cannot" are prohibitions, not permissions
        s_ob, s_perm = bool(mc._OBLIG_RE.search(modal)), bool(mc._PERM_RE.search(modal))
        s_cmp = _comparators(s)
        if s_neg and s_cmp & {"lt", "gt"}:
            s_cmp = {"min" if c == "lt" else "max" if c == "gt" else c for c in s_cmp}
            s_neg, s_ob = False, True
        neg, ob, perm = neg or s_neg, ob or s_ob, perm or s_perm
        strong = strong or bool(_STRONG_OB.search(modal))
        without = without or bool(_WITHOUT.search(s))
        cmps |= s_cmp
    return {"neg": neg, "ob": ob, "perm": perm, "cmp": cmps, "without": without, "strong": strong}


_EXCEPTION_RE = re.compile(r"\bexcept(?:ing|ion)?\b|\bother than\b|\bapart from\b|\bsave\b|\bunless\b|\bexempt(?:s|ed|ion)?\b"
                           r"|\bexcluding\b|\bnot including\b|\botherwise\b", _I)
_CONNECTIVE_RE = re.compile(r"\bbut\b|\bhowever\b|\balthough\b|\bthough\b", _I)
_CONDITION_RE = re.compile(r"\bif\b|\bwhen(?:ever)?\b|\bwhere\b|\bprovided\b|\bonce\b|\bas long as\b|\bso long as\b"
                           r"|\bin case\b|\bon condition\b|\bsubject to\b|\bdepend(?:s|ing)? on\b", _I)
_ONLY_RE = re.compile(r"\bonly\b|\bsolely\b|\bexclusively\b", _I)
_HEDGE_RE = re.compile(r"\b(?:generally|usually|normally|typically|ordinarily|as a rule|in general)\b", _I)
_QUALIFIER_KEYS = frozenset({"except", "unless", "provided", "subject_to", "notwithstanding", "only", "if"})
_WHILE_CLAUSE = re.compile(r"\b(?:while|during|whilst)\b([^,;:()]{0,80})", _I)
_PARENTHETICAL = re.compile(r"\(([^()]{6,120})\)")


def _markers(text: str) -> set:
    found = mc._markers(text) & _QUALIFIER_KEYS
    if re.search(r"\bwhere\b|\bonce\b|\bin case\b", text, _I):
        found.add("if")
    return found


def _context_gap(source: str, fact: str) -> str | None:
    """Words the source puts in a "while ..." / "during ..." clause or in a parenthesis ("(or being carried on)")
    are conditions or inclusions; the fact must keep them (in its own phrasing: "in a public place" for "while in a
    public place")."""
    fact_stems = _stems(fact)
    for rx, share in ((_WHILE_CLAUSE, 1.0), (_PARENTHETICAL, 0.75)):
        for m in rx.finditer(source):
            words = _stems(m.group(1))
            if len(words) >= (1 if rx is _WHILE_CLAUSE else 2) and \
                    sum(1 for w in words if any(_same_word(w, f) for f in fact_stems)) / len(words) < share:
                return m.group(0).strip()
    return None


def _marker_gap(markers: set, fact: str) -> str | None:
    """The first marker of the source that the fact does not carry (any word of the matching family counts)."""
    has_exc = bool(_EXCEPTION_RE.search(fact) or _CONNECTIVE_RE.search(fact))
    has_cond = bool(_CONDITION_RE.search(fact))
    if markers & {"except", "notwithstanding"} and not has_exc:
        return "except"
    if markers & {"unless", "provided", "subject_to"} and not (has_exc or has_cond):
        return sorted(markers & {"unless", "provided", "subject_to"})[0]
    if "if" in markers and not (has_cond or has_exc):
        return "if"
    if "only" in markers and not _ONLY_RE.search(fact):
        return "only"
    return None


# Words that carry no legal content, and plain words licensed only when one of the listed evidence words is there.
_NEUTRAL = frozenset(mc.stem(w) for w in {"you", "your", "yours", "get", "gets", "got", "getting", "also", "then", "same", "new",
                      "person", "people", "someone", "anyone", "somebody", "everyone", "applicant", "driving", "but", "however",
                      "although", "though", "otherwise"})
_LICENSED = {"old": {"age"}, "reappear": {"appear", "again"}, "retake": {"reappear", "appear", "again", "repeat"},
             "wait": {"after", "before", "period", "interval"}, "waiting": {"after", "before", "period", "interval"},
             "valid": {"effective", "valid", "validity"}, "validity": {"effective", "valid", "validity"},
             "effective": {"valid", "validity", "effective"},
             "fail": {"pass"}, "failure": {"pass"}, "unsuccessful": {"pass"}, "unsuccessfully": {"pass"}}


_LICENSED_STEMS = {mc.stem(k): {mc.stem(x) for x in v} for k, v in _LICENSED.items()}


def _stems(text: str) -> set:
    return mc.words(_spelling(text))


def _same_word(a: str, b: str) -> bool:
    return a == b or (min(len(a), len(b)) >= 4 and (a.startswith(b) or b.startswith(a)))


# Words that only frame a sentence ("where the applicant ... for a period of ...") and need not be repeated.
_GENERIC = frozenset(mc.stem(w) for w in ("applicant", "period", "where", "such", "person", "persons"))


def _retained(quote_stem: str, fact_stems: set) -> bool:
    """The quote word is in the fact, or the fact's plain word is licensed by it ("fail" for "not pass")."""
    if any(_same_word(quote_stem, f) for f in fact_stems):
        return True
    return any(quote_stem in _LICENSED_STEMS.get(f, ()) for f in fact_stems)


def _unlicensed_words(fact: str, source: str, hedge_ok: bool) -> list:
    """Words of the fact that neither the evidence (its quotes and the direct claims citing the same passage) nor
    the closed lists above account for."""
    allowed = _stems(source)
    raw = {mc.stem(t) for t in re.findall(r"[a-z][a-z'-]*", _spelling(source).lower())}
    if hedge_ok:
        fact = _HEDGE_RE.sub(" ", fact)
    bad = []
    for w in sorted(_stems(fact)):
        if w in _NEUTRAL or w in _BOUND_WORDS or any(_same_word(w, a) for a in allowed):
            continue
        if _LICENSED_STEMS.get(w, set()) & raw:
            continue
        bad.append(w)
    return bad


# ---------------------------------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------------------------------
def _strip_ids(text: str) -> str:
    """The text without legal identifiers (rule/section numbers, Act names, enumerators) - but WITH dates and
    years kept, because those must be stated in a summary."""
    from backend import grounded_answer as ga  # lazy: grounded_answer imports this module
    for rx in ga._IDENTIFIER_SPANS:
        if rx in (ga.DATE_NUM_RE, ga.DATE_DMY_RE, ga.DATE_MDY_RE, ga.YEAR_RE):
            continue
        text = rx.sub(" ", text)
    return ga.ACT_RE.sub(" ", text)


_FORBIDDEN_TEXT = re.compile(r"[\[\]*_`<>|\\\n]|https?:|www\.|\(interpretation\)", _I)


_OR = re.compile(r"\bor\b|\beither\b|\bwhichever\b", _I)
_ALL = re.compile(r"\b(?:every|each|all|everyone|everybody)\b", _I)
# Words that say WHICH vehicles, roads or persons a rule covers: never dropped from a summary.
_SCOPE_WORDS = frozenset({"public", "private", "commercial", "transport", "goods", "passenger", "heavy", "light",
                          "night", "highway", "school", "hired", "hire"})


def _scope_problem(quotes: str, text: str) -> str | None:
    """'and' turned into 'or', 'any' into 'every', or a scope word ("public", "goods", "transport") dropped: each
    changes who or what a rule covers."""
    if _OR.search(text) and not _OR.search(quotes):
        return "introduces an alternative ('or') that the quoted evidence does not"
    if _OR.search(quotes) and not _OR.search(text):
        return "drops an alternative ('or') of the quoted evidence"
    if _ALL.search(text) and not _ALL.search(quotes):
        return "widens the rule to everyone / everything ('every', 'all') beyond the quoted evidence"
    if _ALL.search(quotes) and not _ALL.search(text):
        return "drops the 'every' / 'all' of the quoted evidence"
    fact_stems = _stems(text)
    for w in sorted(_stems(quotes) & _SCOPE_WORDS):
        if not any(_same_word(w, f) for f in fact_stems):
            return f"drops the scope word '{w}' of the quoted evidence"
    return None


_MODAL = re.compile(r"\b(?:shall|may|must|can|will|should)\b", _I)


def _dropped_item(quote: str, fact_stems: set) -> str | None:
    """An item of a comma-separated list in the quote ("A, B, C and D": documents, conditions, vehicle classes) that
    the fact does not carry in full, so a list is never summarised with an entry missing."""
    for clause in re.split(r";|:|\.(?=\s|$)", quote):
        parts = re.split(r",(?!\d{3}\b)", clause)
        # a real list ends "..., B and C" / "..., B or C"; commas around "subject to ..." or "on application ..." do not
        if len(parts) < 3 or not re.search(r"\b(?:and|or)\b", parts[-1], _I) or _MODAL.search(parts[-1]):
            continue
        items = parts[1:-1] + re.split(r"\b(?:and|or)\b", parts[-1], maxsplit=1, flags=_I)
        for item in items:
            words = _stems(item)
            if not 1 <= len(words) <= 8 or _MODAL.search(item):
                continue
            if sum(1 for w in words if any(_same_word(w, f) for f in fact_stems)) / len(words) < 0.75:
                return item.strip()
    return None


def _fact_problem(fact: SummaryFact, known: dict, cited_ids: set, hedge_ok: bool, claims=()) -> str | None:
    from backend import grounded_answer as ga
    if _FORBIDDEN_TEXT.search(fact.text):
        return "fact contains markup, a link or a citation marker"
    if len(set(fact.evidence_ids)) != len(fact.evidence_ids):
        return "fact repeats an evidence id"
    for i in fact.evidence_ids:
        if i not in known or i not in cited_ids:
            return f"fact cites {i}, which the legal claims do not cite"
    passages = [_norm(known[i].passage) for i in fact.evidence_ids]
    used = set()
    for q in fact.quotes:
        nq = _norm(q)
        if len(nq) < MIN_QUOTE_CHARS:
            return "quote too short"
        hit = [i for i, p in zip(fact.evidence_ids, passages) if nq in p]
        if not hit:
            return "quote is not a verbatim passage of the cited evidence"
        used.update(hit)
    if used != set(fact.evidence_ids):
        return "fact cites evidence that none of its quotes comes from"

    quotes = " ".join(fact.quotes)
    text = _spelling(fact.text)
    supported = set().union(*(ga.evidence_identifiers(known[i]) for i in fact.evidence_ids))
    invented = ga.identifiers(text) - supported
    if invented:
        return f"fact names identifiers absent from its evidence: {sorted(invented)}"
    if number_values(_strip_ids(text)) != number_values(_strip_ids(quotes)):
        return "numbers differ from the quoted evidence"
    qf, ff = _flags(quotes), _flags(text)
    if qf["cmp"] != ff["cmp"]:
        return "comparison words (within/after/before/at least/at most/more/less) differ from the quoted evidence"
    for key, label in (("neg", "negation"), ("without", "'without'")):
        if qf[key] != ff[key]:
            return f"{label} differs from the quoted evidence"
    if ff["perm"] and not qf["perm"]:
        return "states a permission the quoted evidence does not"
    if ff["ob"] and not qf["ob"]:
        return "states an obligation the quoted evidence does not"
    if qf["strong"] and not ff["ob"]:
        return "drops the duty (must / required to) in the quoted evidence"
    if qf["perm"] and not (qf["ob"] or qf["neg"]) and not ff["perm"]:
        return "drops the permission in the quoted evidence"
    scope = _scope_problem(quotes, text)
    if scope:
        return scope
    lost = _context_gap(quotes, text)
    if lost:
        return f"leaves out a condition or inclusion of its quoted evidence: {lost!r}"
    gap = _marker_gap(_markers(quotes), text)
    if gap:
        return f"drops the '{gap}' condition of the quoted evidence"
    if (_EXCEPTION_RE.search(text) or _CONDITION_RE.search(text) or _ONLY_RE.search(text)) and not _markers(quotes):
        return "adds a condition or exception the quoted evidence does not state"
    if _ONLY_RE.search(text) and "only" not in _markers(quotes):
        return "adds 'only'"
    if _HEDGE_RE.search(text) and not hedge_ok:
        return "hedges ('generally') although no claim states an exception"
    claim_text = " ".join(c.text for c in claims if set(c.evidence_ids) & set(fact.evidence_ids))
    quote_stems, fact_stems = _stems(quotes) - _GENERIC, _stems(text)
    if quote_stems and sum(1 for q in quote_stems if _retained(q, fact_stems)) / len(quote_stems) < RETAINED:
        return "uses too little of its quoted evidence (parts of it are left out)"
    for q in fact.quotes:
        item = _dropped_item(q, fact_stems)
        if item:
            return f"leaves out part of its quoted evidence: {item!r}"
    bad = _unlicensed_words(text, f"{quotes} {claim_text}", hedge_ok)
    if bad:
        return f"uses words that are not in the quoted evidence: {bad[:5]}"
    return None


def _coverage_problem(claims, facts: list, summary_text: str) -> str | None:
    quoted = " ".join(q for f in facts for q in f.quotes)
    quote_stems = _stems(quoted)
    s_numbers = number_values(_strip_ids(_spelling(summary_text)))
    s_flags = _flags(summary_text)
    for n, c in enumerate(claims, 1):
        text = _spelling(c.text)
        words = _stems(text)
        if words:
            hit = sum(1 for w in words if any(_same_word(w, q) for q in quote_stems)) / len(words)
            if hit < COVERAGE:
                return f"legal claim {n} is not covered by the summary's quotes ({hit:.0%})"
        missing = number_values(_strip_ids(text)) - s_numbers
        if missing:
            return f"legal claim {n} states {sorted(missing)} that the summary leaves out"
        gap = _marker_gap(_markers(text), summary_text)
        if gap:
            return f"legal claim {n} has a '{gap}' condition that the summary leaves out"
        lost = _context_gap(text, summary_text)
        if lost:
            return f"legal claim {n} has {lost!r} that the summary leaves out"
        c_flags = _flags(text)
        if c_flags["neg"] and not s_flags["neg"]:
            return f"legal claim {n} states a restriction that the summary leaves out"
        if c_flags["without"] and not s_flags["without"]:
            return f"legal claim {n} has a 'without' limit that the summary leaves out"
        if c_flags["cmp"] - s_flags["cmp"]:
            return f"legal claim {n} has a limit ({sorted(c_flags['cmp'] - s_flags['cmp'])}) that the summary leaves out"
    return None


def check(raw, answer, contract, *, penalty_reason=None, mask=None) -> tuple:
    """(facts, None) when the summary is accepted; (None, reason) when it is dropped; (None, None) when absent.
    `answer` is the already-validated GroundedAnswer. `mask(text, passages)` is the penalty-masking applied to claims."""
    if raw is None or raw == []:
        return None, None
    if not isinstance(raw, list) or len(raw) > MAX_FACTS:
        return None, "summary is not a short list of facts"
    if answer.evidence_sufficiency != "sufficient":
        return None, "summaries are shown only for plain sufficient answers"
    claims = answer.claims
    if not claims or len(claims) > MAX_LEGAL_CLAIMS:
        return None, "too many legal claims to summarise safely"
    if any(c.kind != "direct" for c in claims):
        return None, "an interpretation claim is not summarised"
    try:
        facts = [SummaryFact.model_validate(item) for item in raw]
    except ValidationError:
        return None, "malformed summary fact"
    if sum(len(f.text) for f in facts) > MAX_TOTAL_CHARS:
        return None, "summary too long"
    known, cited_ids = contract.by_id(), set(answer.citations)
    hedge_ok = any(_markers(c.text) - {"only", "if", "while"} for c in claims)
    for n, f in enumerate(facts, 1):
        problem = _fact_problem(f, known, cited_ids, hedge_ok, claims)
        if problem:
            return None, f"fact {n}: {problem}"
    summary_text = " ".join(f.text for f in facts)
    problem = _coverage_problem(claims, facts, summary_text)
    if problem:
        return None, problem
    if penalty_reason is not None:
        passages = [known[i].passage for i in sorted(cited_ids) if i in known]
        masked = mask(summary_text, passages) if mask else summary_text
        reason = penalty_reason(masked)
        if reason:
            return None, f"penalty content withheld ({reason})"
    return facts, None
