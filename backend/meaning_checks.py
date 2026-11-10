"""
Meaning-preservation checks for grounded claims. HEURISTIC LAYER.

These checks are lexical and rule-based. They are deterministic (same input, same result) but they do NOT
establish semantic or legal correctness: they look for surface signals that a claim changed the meaning of the
sentence it restates, and reject conservatively when a potentially material signal is not preserved.

Checks (each returns (check_name, message) findings; any finding rejects the response):
  deontic            polarity/modality changed: must vs must not, prohibited vs permitted, required vs optional,
                     allowed vs not allowed, never, no-subject prohibitions ("No vehicle shall ...")
  exemption          an exemption word added or removed
  qualifier_omitted  a restated sentence's exception/condition/limitation marker is missing from the claim
  qualifier_altered  the marker is kept but the words of its clause are not
  qualifier_added    the claim adds a marker no anchor sentence has (an invented condition)
  composition        such an invented marker joins sentences from two or more different passages
  numeric_changed    a value (with its comparator and unit) is not stated in an anchor sentence
  numeric_omitted    a value attached to the restated part of a sentence is dropped
  numeric_association a value is taken from the clause describing a different case ("Rs 500 for a car" used
                     for a motor cycle)
  unverifiable_direct a "direct" claim does not closely restate any cited sentence, so its conditions cannot be
                     checked; fail closed (the model may mark it "interpretation")
  uncited_conflict   an uncited sentence states the same proposition (same actor and action, see proposition())
                     with the opposite polarity and adds nothing that narrows it; a definitive answer is rejected
  uncited_qualification  the same, but the uncited sentence narrows the proposition (an extra actor/object word,
                     an exemption for a narrower class, or a condition clause): it may qualify rather than
                     contradict; a definitive answer that ignores it is rejected as well

Terms: a claim sentence RESTATES an evidence sentence when it contains at least RESTATE_COVERAGE of the content
words of that sentence's main clause (the sentence with its qualifier clauses removed). ANCHORS are the restated
sentences, or, when none, the cited sentences with the highest word overlap.
"""

import re
from dataclasses import dataclass, field

_I = re.IGNORECASE
RESTATE_COVERAGE = 0.75
QUALIFIER_CLAUSE_COVERAGE = 1.0  # a claim's own qualifier clause keeps every content word (was 0.75)
CLAIM_SHARE = 0.25
CONFLICT_MIN_SHARED = 3
CONFLICT_SHARED_RATIO = 0.5

_NEG_RE = re.compile(r"\b(?:not|no|never|none|nor|neither|cannot|nobody|nothing|nowhere)\b|n't\b", _I)
_PROHIBIT_RE = re.compile(r"\b(?:prohibit(?:s|ed|ion)?|forbid(?:s|den)?|banned|bans?|barred|disallow(?:s|ed)?|"
                          r"impermissible)\b", _I)
_OBLIG_RE = re.compile(r"\b(?:shall|must|required|requires?|mandatory|compulsory|obligatory|obliged|"
                       r"ha(?:s|ve) to|needs? to)\b", _I)
_PERM_RE = re.compile(r"\b(?:may|can|allowed|allows?|permitted|optional|entitled)\b", _I)
_EXEMPT_RE = re.compile(r"\b(?:exempt(?:s|ed|ion)?|waived?)\b", _I)

# Canonical marker -> pattern. Clause markers open a qualifier clause; sequence markers are compared but do not.
MARKERS = {
    "except": r"\bexcept(?:ing)?\b|\bother than\b|\bsave for\b|\bapart from\b",
    "unless": r"\bunless\b",
    "provided": r"\bprovided(?: that)?\b",
    "subject_to": r"\bsubject to\b",
    "notwithstanding": r"\bnotwithstanding\b",
    "only": r"\bonly\b|\bsolely\b|\bexclusively\b",
    "if": r"\bif\b|\bwhen(?:ever)?\b",
    "because": r"\bbecause\b|\bwhereas\b|\bsince\b",
    "before": r"\bbefore\b|\bprior to\b|\bpreceding\b",
    "after": r"\bafter\b|\bsubsequent to\b",
}
CLAUSE_MARKERS = ("except", "unless", "provided", "subject_to", "notwithstanding", "only", "if", "because")
_MARKER_RES = {k: re.compile(v, _I) for k, v in MARKERS.items()}
_CLAUSE_START = re.compile("|".join(f"(?:{MARKERS[k]})" for k in CLAUSE_MARKERS), _I)
_CLAUSE_END = re.compile(r",|;|\b(?:shall|must|may|can|will|is|are|was|were)\b", _I)

_NUM_WORDS = {w: n for n, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen twenty".split())}
_NUM_WORDS.update({"thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "ninety": 90, "hundred": 100})
_ORD_WORDS = {w: n for n, w in enumerate(
    "zeroth first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth".split())}
_COMPARATORS = {
    "within": "within", "not later than": "by", "no later than": "by", "not more than": "max", "at most": "max",
    "not exceeding": "max", "up to": "max", "maximum of": "max", "more than": "gt", "above": "gt", "over": "gt",
    "exceeding": "gt", "less than": "lt", "below": "lt", "under": "lt", "not less than": "min",
    "at least": "min", "minimum of": "min"}
_CMP_ALT = "|".join(sorted((re.escape(k) for k in _COMPARATORS), key=len, reverse=True))
_NUMW_ALT = "|".join(sorted(_NUM_WORDS, key=len, reverse=True))
_QTY_RE = re.compile(
    rf"(?:\b(?P<cmp>{_CMP_ALT})\s+)?(?:(?P<cur>₹|\brs\b\.?|\binr\b)\s*)?"
    rf"(?P<num>\d[\d,]*(?:\.\d+)?|\b(?:{_NUMW_ALT}))(?![\w-])"
    r"(?:\s*(?P<pct>%|per\s*cent\b|percent\b))?(?:\s*/-)?(?:\s+(?P<rup>rupees?)\b)?(?:\s+(?P<unit>[a-z]+))?", _I)
_ORD_RE = re.compile(rf"\b(?P<ord>{'|'.join(_ORD_WORDS)}|\d+(?:st|nd|rd|th))\s+(?P<unit>[a-z]+)", _I)
_ABBREV_END = re.compile(r"(?:\bNo|\bRs|\bMs|\bG\.O|\bSec|\bDt|\bviz|\bi\.e|\be\.g|\bvs)\.$", _I)

_STOP = frozenset(
    "a an and are as at be been by could do does for from has have in into is it its might of on or should such "
    "that the their there these they this to was were which who will with without any all every each per than "
    "so also his her he she him them".split())
_FUNCTION = (_STOP | set(_NUM_WORDS) | set(_ORD_WORDS)
             | {"not", "no", "never", "none", "nor", "neither", "cannot", "shall", "must", "may", "can", "need",
                "needs", "required", "require", "requires", "mandatory", "compulsory", "allowed", "allow", "allows",
                "permitted", "optional", "prohibited", "prohibit", "forbidden", "except", "excepting", "unless",
                "provided", "subject", "notwithstanding", "only", "solely", "exclusively", "if", "when", "whenever",
                "because", "whereas", "since", "before", "after", "prior", "within", "more", "less", "least",
                "most", "above", "below", "under", "over", "exceeding", "up", "rs", "inr", "per", "cent", "percent",
                "rupee", "rupees", "other", "save", "apart"})


def stem(w: str) -> str:
    w = w.lower()
    if w.endswith("ies") and len(w) > 4:
        w = w[:-3] + "y"
    elif w.endswith("ied") and len(w) > 4:
        w = w[:-3] + "y"
    elif w.endswith("ing") and len(w) > 5:
        w = w[:-3]
    elif w.endswith("ed") and len(w) > 4:
        w = w[:-2]
    elif w.endswith("s") and not w.endswith("ss") and len(w) > 3:
        w = w[:-1]
    return w[:-1] if w.endswith("e") and len(w) > 3 else w


def words(text: str) -> set:
    return {stem(t) for t in re.findall(r"[a-z][a-z'-]*", (text or "").lower()) if t not in _FUNCTION and len(t) > 1}


_STRUCTURAL_LINE = re.compile(r"^\s*(?:\(|\d{1,3}[A-Za-z]?\s*[.)]|[ivx]{1,5}\)|»|•|-\s|Provided\b|Explanation\b)", _I)


def _blocks(text: str) -> list[str]:
    """Join wrapped lines; keep structural lines (headers, sub-rules, provisos, list items) separate."""
    blocks = []
    for line in (text or "").split("\n"):
        if not line.strip():
            continue
        if blocks and not _STRUCTURAL_LINE.match(line) and not re.search(r"[.:;!?]\s*$|:-\s*$", blocks[-1]) \
                and not re.search(r"\s-\s(?:Rule|Paragraph|Order|Preamble|References|Section)\b", blocks[-1]):
            blocks[-1] += " " + line.strip()
        else:
            blocks.append(line.strip())
    return blocks


def sentences(text: str) -> list[str]:
    parts = [p for b in _blocks(text) for p in re.split(r"(?<=[.;])\s+(?=[(A-Z\"'])", b)]
    out = []
    for p in parts:
        if out and _ABBREV_END.search(out[-1]):
            out[-1] += " " + p
        else:
            out.append(p)
    return [s for s in out if words(s)]


@dataclass
class Sentence:
    evidence_id: str
    text: str                      # identifier-stripped
    main_words: set
    qualifier_words: dict          # marker -> content words of its clause
    markers: set
    deontic: str
    exempt: bool
    main_deontic: str
    main_exempt: bool
    quantities: list = field(default_factory=list)  # (qty, clause_index, post_words)
    clauses: int = 1


def deontic(text: str) -> str:
    """'prohibition' | 'obligation' | 'permission' | 'negated' | 'plain' (lexical approximation)."""
    neg, pro = len(_NEG_RE.findall(text)), len(_PROHIBIT_RE.findall(text))
    ob, perm = bool(_OBLIG_RE.search(text)), bool(_PERM_RE.search(text))
    if pro or (neg % 2 and (ob or perm)):
        return "prohibition"
    if neg % 2:
        return "negated"
    return "obligation" if ob else "permission" if perm else "plain"


def _markers(text: str) -> set:
    return {k for k, rx in _MARKER_RES.items() if rx.search(text)}


def _split_qualifiers(text: str) -> tuple[str, dict]:
    """(main clause text, {marker: clause text}) - each qualifier clause runs from its marker to the next comma,
    semicolon or main verb."""
    main, clauses, pos = [], {}, 0
    for m in _CLAUSE_START.finditer(text):
        if m.start() < pos:
            continue
        main.append(text[pos:m.start()])
        end = _CLAUSE_END.search(text, m.end())
        stop = end.start() if end else len(text)
        kind = next(k for k in CLAUSE_MARKERS if _MARKER_RES[k].fullmatch(m.group(0)) or
                    _MARKER_RES[k].match(m.group(0)))
        clauses.setdefault(kind, "")
        clauses[kind] += " " + text[m.start():stop]
        pos = stop
    main.append(text[pos:])
    return " ".join(main), clauses


def _qty_value(m) -> tuple:
    raw = m.group("num").lower()
    value = str(_NUM_WORDS[raw]) if raw in _NUM_WORDS else raw.replace(",", "").removesuffix(".00")
    if m.group("cur") or m.group("rup"):
        unit = "rupee"
    elif m.group("pct"):
        unit = "percent"
    else:
        u = (m.group("unit") or "").lower()
        unit = stem(u) if u and u not in _STOP else ""
    return (_COMPARATORS.get((m.group("cmp") or "").lower(), ""), value, unit)


def quantities(text: str) -> list:
    """[(qty, clause_index, post_words)] where qty = (comparator, value, unit) and post_words are the content
    words after the value in its clause (what the value is attached to)."""
    out = []
    clauses = re.split(r",(?!\d{3}\b)|;|\band\b|\bwhereas\b", text, flags=_I)  # keep "1,000" whole
    for ci, clause in enumerate(clauses):
        for m in _QTY_RE.finditer(clause):
            out.append((_qty_value(m), ci, words(clause[m.end():])))
        for m in _ORD_RE.finditer(clause):
            o = m.group("ord").lower()
            n = _ORD_WORDS.get(o) if o in _ORD_WORDS else int(re.sub(r"\D", "", o))
            out.append((("ord", str(n), stem(m.group("unit"))), ci, words(clause[m.end():])))
    return out


def analyse(evidence_id: str, text: str) -> Sentence:
    main, quals = _split_qualifiers(text)
    return Sentence(evidence_id, text, words(main), {k: words(v) for k, v in quals.items()}, _markers(text),
                    deontic(text), bool(_EXEMPT_RE.search(text)), deontic(main), bool(_EXEMPT_RE.search(main)),
                    quantities(text))


def _all_words(s: Sentence) -> set:
    return s.main_words | set().union(*s.qualifier_words.values())


def _core(s: Sentence) -> set:
    """Main-clause words; the whole sentence when the main clause is too short to identify it (e.g. a proviso whose
    main clause is just 'shall be Rs. 1000')."""
    return s.main_words if len(s.main_words) >= 2 else _all_words(s)


def _restates(claim_words: set, s: Sentence) -> bool:
    """The claim contains most of the sentence's core, AND the sentence accounts for a real share of the claim
    (so a long claim does not 'restate' every short sentence whose words it happens to contain)."""
    core = _core(s)
    return (len(core) >= 2 and len(claim_words & core) >= RESTATE_COVERAGE * len(core)
            and len(claim_words & _all_words(s)) >= CLAIM_SHARE * len(claim_words))


def _restated(claim_words: set, ev: list) -> list:
    """Restated sentences. When some sentence matches the claim almost exactly, only those count, so a verbatim
    claim is not also held to its near-identical siblings (e.g. other items of the same list)."""
    found = [s for s in ev if _restates(claim_words, s)]
    jac = lambda s: len(claim_words & _all_words(s)) / len(claim_words | _all_words(s) or {""})  # noqa: E731
    exact = [s for s in found if jac(s) >= 0.9]
    return exact or found


# ---------------------------------------------------------------------------------------------------
# Propositions (lexical): actor, modal anchor, action head, object. Used only to decide whether two sentences
# address the same proposition; no parse of legal meaning is attempted.
# ---------------------------------------------------------------------------------------------------
_ANCHOR_RE = re.compile(r"\b(?:shall|must|may|can(?:not)?|need(?:s)?|will|is|are|was|were|has|have|does|do)\b", _I)
_BE = frozenset({"be", "been", "being"})
# "not less than 406 millimetres" is a bound on a value, not a negation of the proposition.
_BOUND_RE = re.compile(r"\b(?:not|no)\s+(?:be\s+)?(?:less|more|later|earlier|fewer|greater)\s+th[ae][nt]\b"
                       r"|\bnot\s+(?:be\s+)?(?:below|above)\b"  # "not below the rank of"
                       r"|\bnot\s+(?:be\s+)?exceeding\b", _I)
# Where a sentence's own position is read from (each found in the real-index residual review):
_NUMBER_ABBREV_RE = re.compile(r"\b[Nn]os?\.(?=\S|\s*\d)")  # "letter No.11831", "No.G-575", "Act No. 8"
_IDIOM_RE = re.compile(r"\bas the case may be\b", _I)          # not the sentence's modal
# Relative clauses ("goods which shall not be carried") are compared separately; the 'that' of a result clause
# ("so placed that ...", "such that ...") is not one: that clause IS the requirement.
_RESULT_CLAUSE_RE = re.compile(r"\b(?:so|such)\s+(?:\w+\s+){0,4}that\b", _I)
_LEAD_COND_RE = re.compile(r"^\s*(?:\(\s*[0-9ivxa-z]{1,4}\s*\)\s*)*(?:if|when|whenever|where|wherever|unless|"
                           r"in case)\b", _I)
_LEAD_COND_END = re.compile(r",(?!\d{3}\b)")
_DEFINITION_RE = re.compile(r"^\W*[“\"'‘][^”\"'’]{1,60}[”\"'’]\s+(?:means|includes)\b"
                            r"|\bunless the context otherwise requires\b", _I)  # '"Agent" means ...'
_TITLE_PREFIX_RE = re.compile(r"^[^.;]*?:\s*[-–]\s*(?=\S)")  # "Title:- text" (not a trailing "namely:-")
# "Telangana Motor Vehicles Rules, 1989 - Rule 421 - Speed of towing vehicle" (identifiers may be stripped away)
_TITLE_SEPARATOR_RE = re.compile(r"\s[-–]\s")
# a condition or exception that follows the modal carries its own negations ("... if the application is not made")
_TRAILING_COND_RE = re.compile(r"\b(?:if|unless|provided|when|whenever|where|wherever|in case|except)\b", _I)
_PREPOSITIONS = frozenset({"on", "at", "in", "for", "with", "by", "upon", "after", "before", "within", "under",
                           "from", "to", "of"})
_PASSIVE_RE = re.compile(r"^(?:is|are|was|were)\b|^\w+\s+(?:not\s+)?(?:be|been)\b", _I)
_STRONG_MODAL_RE = re.compile(r"\b(?:shall|must|may|cannot|need)\b", _I)
# Actor words that do not by themselves identify a class of actor ("vehicle", "authority"), and filler from
# "in the case of", "in respect of", "the following".
GENERIC_ACTOR = frozenset({"vehicl", "motor", "authority", "person", "cas", "respect", "follow", "such", "concern",
                           "said"})
def _strip_title(text: str) -> str:
    """Remove a leading "Title:- " - only when the prefix is title-like (no strong modal: "... shall be as
    follows:- ..." is not a title)."""
    m = _TITLE_PREFIX_RE.match(text)
    return text[m.end():] if m and not _STRONG_MODAL_RE.search(m.group(0)) else text


_ADVERBIAL = frozenset({"time", "times", "clearly", "duly", "further", "thereafter", "therein", "thereof"})
# A pair of positions that can coexist when they concern different objects (a duty to do A, a ban on doing B).
# A ban vs a permission, or a duty vs a release ("need not"), on different objects may still be a carve-out.
_COEXIST_ON_DIFFERENT_OBJECTS = {frozenset({"obligation", "prohibition"}), frozenset({"prohibition", "plain"}),
                                 frozenset({"negated", "plain"})}
# Words that do not by themselves say which thing an action applies to: two objects sharing only these are
# different objects. "given": a participle ("indication given by", "notice given to").
NON_LINKING_OBJECT_WORDS = frozenset({"given"})
ACTOR_SHARE = 0.5      # shared actor words / the smaller actor
EXEMPT_OBJECT_SHARE = 0.5  # exempted-thing words found in the other side's action + object


@dataclass
class Proposition:
    actor: set
    action: str            # stem of the first content word after the anchor, or "exempt"
    obj: set               # remaining content words of the main clause (for "exempt": what is exempted from)
    polarity: str          # deontic() of the main clause
    exempt: bool
    clause_markers: set    # qualifier clauses of the whole sentence
    qualifier_words: set = field(default_factory=set)  # content words of those clauses
    embedded: list = field(default_factory=list)        # embedded_clauses() of the main clause
    passive: bool = False  # "particulars shall be exhibited": the actor is what the action applies to
    core_obj: set = field(default_factory=set)  # obj without trailing conditions ("... when a signal is given")
    result: "tuple | None" = None  # result_clause() of the core clause ("so constructed that ...")

    @property
    def target(self) -> set:
        """What the action applies to: the object, plus the grammatical subject of a passive."""
        return self.obj | self.actor if self.passive else self.obj


def states_no_position(text: str) -> bool:
    """Definitions and document/rule titles state no obligation, prohibition or permission of their own."""
    if _DEFINITION_RE.search(_strip_title(text)):
        return True
    return len(_TITLE_SEPARATOR_RE.findall(text)) >= 2 and not _STRONG_MODAL_RE.search(text)


def position_text(text: str) -> "str | None":
    """The part of a sentence that carries its own position: without a leading title ("Title:- "), the idiom 'as
    the case may be', and a leading condition ("If ..., "). None for a definition, a title, or a sentence that is
    only a condition (no comma closes it), which states no position."""
    if states_no_position(text):
        return None
    t = _IDIOM_RE.sub(" ", _strip_title(text))
    if _LEAD_COND_RE.match(t):
        # the condition ends at its comma, or at the first strong modal when that comes first (or no comma)
        end, m = _LEAD_COND_END.search(t), _STRONG_MODAL_RE.search(t)
        if m and (not end or m.start() < end.start()):
            before = t[:m.start()].lower().split()[-5:]
            t = (" no " if {"no", "neither"} & set(before) else " ") + t[m.start():]
        elif end:
            t = t[end.end():]
        else:
            return None  # only a condition: no position of its own
    return t


def _clean(main: str) -> str:
    return _BOUND_RE.sub(" ", _NUMBER_ABBREV_RE.sub(" ", main))


def polarity(main: str, *, relative: bool = False) -> str:
    """deontic() of a main clause, ignoring number abbreviations and value bounds, and (unless relative=True) the
    relative clauses after the modal ("goods which shall not be carried"): those are compared separately."""
    t = _clean(main)
    m = _ANCHOR_RE.search(t)
    if m and not relative:
        r = _relative_start(t, m.end())
        if r is not None:
            t = t[:r]
    return deontic(t)


def _relative_start(t: str, pos: int) -> "int | None":
    """Start of the first relative clause after pos that is not the 'that' of a result clause ('so placed that')."""
    results = [m.end() for m in _RESULT_CLAUSE_RE.finditer(t)]
    for r in re.finditer(r"\b(?:which|that|who|whom|whose)\b", t[pos:], _I):
        if pos + r.end() not in results:
            return pos + r.start()
    return None


def embedded_clauses(main: str) -> list:
    """[(antecedent words, clause content words, deontic)] of each relative clause after the modal; the
    antecedent is the (up to) three words before the relative pronoun ("the goods which ...")."""
    t = _clean(main)
    m = _ANCHOR_RE.search(t)
    if not m:
        return []
    out, start = [], _relative_start(t, m.end())
    while start is not None:
        nxt = _relative_start(t, start + 1)
        part = t[start:nxt]
        out.append((words(" ".join(t[:start].split()[-3:])), words(part), deontic(part)))
        start = nxt
    return out


def embedded_opposed(a: list, b: list) -> bool:
    """A relative clause of one sentence and one of the other say substantially the same thing about the same
    antecedent with the opposite polarity ("... direct that a fresh certificate shall (not) be obtained"; not
    "goods which shall not be carried" vs "luggage which may be carried")."""
    for ante_a, wa, da in a:
        for ante_b, wb, db in b:
            shared = wa & wb
            if (ante_a & ante_b or not (ante_a or ante_b)) and shared and \
                    len(shared) >= 0.5 * max(len(wa), len(wb)) and frozenset({da, db}) in _OPPOSED:
                return True
    return False


def _core_clause(pos: str) -> str:
    """The position text without the conditions or exceptions that follow the first strong modal ("... need not be
    in Form C.R if the vehicle is used ..."). _split_qualifiers ends such a clause at its own verb, which leaves the
    rest of the condition (and its negations) in the main clause; here each runs to the next comma, semicolon or
    strong modal (so "may, and if so required shall, ..." keeps its second position)."""
    m = _STRONG_MODAL_RE.search(pos)
    if not m:
        return pos
    out, i = [pos[:m.end()]], m.end()
    for c in _TRAILING_COND_RE.finditer(pos, m.end()):
        if c.start() < i:
            continue
        out.append(pos[i:c.start()])
        end = re.compile(r"[,;]|" + _STRONG_MODAL_RE.pattern, _I).search(pos, c.end())
        i = end.start() if end else len(pos)
    out.append(pos[i:])
    return " ".join(out)


def _without_trailing_conditions(pos: str) -> str:
    """The position text up to the first condition or exception after the first strong modal. For the object only:
    a condition says when the action applies, not what it applies to (polarity keeps _core_clause, which resumes
    after a comma so a second position is not lost)."""
    m = _STRONG_MODAL_RE.search(pos)
    c = _TRAILING_COND_RE.search(pos, m.end()) if m else None
    return pos[:c.start()] if c else pos


def result_clause(core: str) -> "tuple | None":
    """(subject words, content words) of the first result clause after the modal ("so constructed that a seat is
    provided ..."): in such a sentence that clause is the requirement. None when there is none, or when it is empty
    ("so constructed that, -" before a list)."""
    m = _ANCHOR_RE.search(core)
    r = _RESULT_CLAUSE_RE.search(core, m.end()) if m else None
    clause = core[r.end():] if r else ""
    if not words(clause):
        return None
    a = _ANCHOR_RE.search(clause)
    return words(clause[:a.start()]) if a else set(), words(clause)


def same_result(a: tuple, b: tuple) -> bool:
    """Two result clauses state the same requirement: the same subject (or neither has one) and substantially the
    same content (the measure embedded_opposed uses). Otherwise they are separate requirements."""
    (sa, wa), (sb, wb) = a, b
    shared = wa & wb
    return bool((sa & sb or not (sa or sb)) and shared and len(shared) >= 0.5 * max(len(wa), len(wb)))


def _content_tokens(text: str) -> list:
    """[(stem, follows a preposition)] for content words; values and their units ("406 millimetres") excluded."""
    raw = re.findall(r"[a-z][a-z'-]*", _QTY_RE.sub(" ", text).lower())
    return [(stem(t), i > 0 and raw[i - 1] in _PREPOSITIONS) for i, t in enumerate(raw)
            if t not in _FUNCTION and t not in _BE and t not in _ADVERBIAL and len(t) > 1]


def proposition(text: str) -> "Proposition | None":
    """None when the main clause has no modal/verb anchor, no actor before it, or no action after it (headings,
    fragments, clauses that start with the verb). Such sentences are never matched as conflicting."""
    pos = position_text(text)
    if pos is None:
        return None
    main, quals = _split_qualifiers(pos)
    m = _ANCHOR_RE.search(main)
    if not m:
        return None
    actor, rest = words(main[:m.start()]), main[m.start():]
    if not actor:
        return None
    core = _split_qualifiers(_core_clause(pos))[0]       # polarity and action come from the core clause
    cm = _ANCHOR_RE.search(core)
    core_rest = core[cm.start():] if cm else rest
    ex = _EXEMPT_RE.search(rest)
    if ex:
        action, obj = "exempt", words(rest[ex.end():])
    else:
        tokens = _content_tokens(rest)
        if not tokens:
            return None
        # the first content word not governed by a preposition ("may on application sanction"); else the first
        head = _content_tokens(core_rest) or tokens
        action = next((t for t, after_prep in head if not after_prep), head[0][0])
        obj = {t for t, _p in tokens} - {action}
    bare = _split_qualifiers(_without_trailing_conditions(pos))[0]
    bm = _ANCHOR_RE.search(bare)
    core_obj = (words(bare[bm.start():]) & obj) if bm else obj
    return Proposition(actor, action, obj, polarity(core), action == "exempt" or bool(_EXEMPT_RE.search(main)),
                       _markers(text) & set(CLAUSE_MARKERS), set().union(*(words(q) for q in quals.values())),
                       embedded_clauses(core), bool(_PASSIVE_RE.match(rest)), core_obj, result_clause(core))


def same_proposition(a: Proposition, b: Proposition) -> bool:
    shared = a.actor & b.actor
    if not shared or len(shared) < ACTOR_SHARE * min(len(a.actor), len(b.actor)):
        return False
    if not shared - GENERIC_ACTOR and a.actor != b.actor:
        # only a generic word ("vehicle") links the actors: require a specific word in what both actions apply to
        # (e.g. the same "particulars" exhibited)
        link = (a.target & b.target) - GENERIC_ACTOR
        if not link:
            return False
    if (a.action == "exempt") != (b.action == "exempt"):
        ex, other = (a, b) if a.action == "exempt" else (b, a)
        target = {other.action} | other.obj
        return bool(ex.obj) and len(ex.obj & target) >= EXEMPT_OBJECT_SHARE * len(ex.obj)
    return a.action == b.action


def narrows(u: Proposition, c: Proposition) -> bool:
    """The uncited proposition adds an actor or object word, or a condition clause, that the claim lacks."""
    return bool(u.actor - c.actor or u.obj - c.obj - {c.action} or u.clause_markers - c.clause_markers)


_OPPOSED = {frozenset({"prohibition", "obligation"}), frozenset({"prohibition", "permission"}),
            frozenset({"negated", "plain"}), frozenset({"prohibition", "plain"}),
            frozenset({"obligation", "negated"})}  # "shall wear" vs "need not wear"


# A qualifier clause that names a sub-rule, clause or sub-section ("except a person exempted under sub-rule (2)"),
# and the sentence of the SAME passage that opens with that number ("(2) A Sikh wearing a turban is exempted.").
_XREF_RE = re.compile(r"\b(?:sub-?\s*rules?|sub-?\s*sections?|clauses?|items?)\s*\(\s*([0-9a-z]{1,4})\s*\)", _I)


def _inside_quotes(text: str, pos: int) -> bool:
    before = text[:pos]
    return before.count("\u201c") > before.count("\u201d") or before.count('"') % 2 == 1


def _safe_referent(text: str) -> bool:
    """A referent that can stand in for its reference only when it states a plain, unconditional position: no
    negation or modal (a negated or discretionary exemption is a different rule), no condition or exception of
    its own, and no value (a value omitted from the claim would not be detected)."""
    main = re.sub(r"^\s*\(\s*[0-9a-z]{1,4}\s*\)", " ", text, flags=_I)
    return deontic(main) == "plain" and not (_markers(main) & set(CLAUSE_MARKERS)) and not quantities(main)


def _cross_references(raw: str, passage_sentences: list, strip) -> tuple:
    """({marker: [referent text (identifier-stripped)]}, {markers whose clause holds a reference}).

    Read from the raw sentence: identifier stripping removes "sub-rule (2)". A reference counts only inside its
    qualifier clause (from the marker to the clause end) and outside quotation marks. A marker is resolved only if
    EVERY reference in its clause resolves to exactly one sentence of the same passage that opens with that number
    and states a safe referent; otherwise it stays unresolved (the original checks apply unchanged)."""
    resolved, pointers = {}, set()
    for m in _CLAUSE_START.finditer(raw):
        marker = next((k for k in CLAUSE_MARKERS if _MARKER_RES[k].match(m.group(0))), None)
        end = _CLAUSE_END.search(raw, m.end())
        refs = [x for x in _XREF_RE.finditer(raw, m.end(), end.start() if end else len(raw))
                if not _inside_quotes(raw, x.start())]
        if not refs or marker is None:
            continue
        pointers.add(marker)
        texts = []
        for x in refs:
            num = re.escape(x.group(1))
            hits = [t for t in passage_sentences if t is not raw and re.match(rf"\s*\(\s*{num}\s*\)", t, _I)]
            if len(hits) != 1 or not _safe_referent(hits[0]):
                texts = None  # missing, duplicated or conditional referent: do not resolve this clause
                break
            texts.append(strip(hits[0]))
        if texts:
            resolved.setdefault(marker, []).extend(texts)
    return resolved, pointers


def _referent_words(text: str) -> set:
    """What a referent sentence says, without its exemption predicate ("... is exempted"): an "except" clause
    already expresses the exemption."""
    return words(text) - words(" ".join(_EXEMPT_RE.findall(text)))


def _covers_all(have: set, need: set) -> bool:
    """Every content word: a stated exception or condition stands in for another only when nothing is left out
    (no 75% allowance here; it would let a place, actor or object of the exception drop)."""
    return bool(need) and need <= have


def _negations(text: str) -> int:
    return len(_NEG_RE.findall(_BOUND_RE.sub(" ", text or ""))) % 2


_DOUBLED_END = re.compile(r"([b-df-hj-np-tv-z])\1$")


def _inflection_free(ws: set) -> set:
    """Stems with a doubled final consonant collapsed ("travell" from "travelling" -> "travel", as from "travels"),
    used only where a qualifier clause must be kept word for word: an inflection is not an omission."""
    return {_DOUBLED_END.sub(r"\1", w) for w in ws}


_PRONOUN_RE = re.compile(r"\b(?:he|him|his|she|her|it|its|they|them|their)\b", _I)
_PLURAL_PRONOUNS = frozenset({"they", "them", "their"})


def _rule_subject_head(text: str) -> "tuple | None":
    """(stem, plural) of the head word of a sentence's rule-subject: the last content word before the first
    preposition, in the text before the main clause's modal or verb anchor ("Every learner shall" -> learner;
    "A goods vehicle shall" -> vehicle; "Every rider of a two-wheeler shall" -> rider). None when there is no
    subject before the anchor (a sentence that opens with its qualifier, a heading)."""
    main = _split_qualifiers(text)[0]
    if _CLAUSE_START.match(text.strip()):
        return None
    m = _ANCHOR_RE.search(main)
    if not m:
        return None
    head = None
    for t in re.findall(r"[A-Za-z][A-Za-z'-]*", main[:m.start()]):
        low = t.lower()
        if low in _PREPOSITIONS:
            break
        if low not in _FUNCTION and len(low) > 1:
            head = low
    if head is None:
        return None
    return stem(head), head.endswith("s") and not head.endswith("ss")


def _subject_pronoun_accounts_for(missing: set, source_text: str, claim_clause: str) -> bool:
    """The only allowance to full coverage of a claim's own qualifier clause: the single missing word is the head
    of the source's rule-subject and the claim's clause refers to it with exactly one pronoun that agrees in
    number ("... sits beside the learner" -> "... sits beside them"). Nothing else (objects, eligibility, actor
    characteristics, time, place, values) can be excused."""
    head = _rule_subject_head(source_text)
    pronouns = [x.lower() for x in _PRONOUN_RE.findall(claim_clause or "")]
    if head is None or missing != {head[0]} or len(pronouns) != 1 or pronouns[0] in ("it", "its"):
        return False  # "it"/"its" may name a thing in the clause (the vehicle), not the rule-subject
    return pronouns[0] in _PLURAL_PRONOUNS if head[1] else True


def check_claim(claim_text: str, kind: str, cited: dict, uncited: dict, *, strip, definitive: bool,
                siblings: tuple = ()) -> list:
    """cited/uncited: {evidence_id: passage text}. strip: removes legal identifiers (rule numbers, dates ...) so
    their digits are not read as quantities. definitive: the response claims sufficiency (not a conflict).
    siblings: ((text, evidence IDs), ...) - the other claims of the same answer. A qualifier is not omitted when a
    sibling that cites the qualifier's own passage states all of it with the same negation (the user sees every
    claim); a clause that only points to a sub-rule must be stated by its referent."""
    findings = []
    ev, xrefs, pointer_markers = [], {}, {}
    for i, p in cited.items():
        raw_sentences = sentences(p)
        for raw in raw_sentences:
            a = analyse(i, strip(raw))
            ev.append(a)
            refs, pointers = _cross_references(raw, raw_sentences, strip)
            xrefs[id(a)] = {k: [(_referent_words(t), t) for t in v] for k, v in refs.items()}
            pointer_markers[id(a)] = pointers
    sibs = [(strip(t), frozenset(ids)) for t, ids in siblings]
    for cs in sentences(claim_text) or [claim_text]:
        c = analyse("claim", strip(cs))
        cw = words(c.text)
        restated = _restated(cw, ev)
        if restated:
            anchors = restated
        else:
            if kind == "direct":
                findings.append(("unverifiable_direct", "direct claim does not closely restate any cited sentence, "
                                 "so its conditions cannot be checked"))
                continue
            best = max((len(cw & (s.main_words | set().union(*s.qualifier_words.values()))) for s in ev), default=0)
            anchors = [s for s in ev if best and len(cw & (s.main_words | set().union(*s.qualifier_words.values())))
                       == best]
        if not anchors:
            continue
        # deontic polarity and modality
        allowed = {s.deontic for s in anchors} | {s.main_deontic for s in anchors}
        if c.deontic not in allowed and not (not restated and c.deontic == "plain"):
            findings.append(("deontic", f"claim reads as '{c.deontic}' but the cited sentence reads as "
                             f"'{'/'.join(sorted({s.deontic for s in anchors}))}' (negation or modality changed)"))
        if c.exempt and not any(s.exempt for s in anchors):
            findings.append(("exemption", "claim adds an exemption the cited sentence does not state"))
        # a restated exemption sentence is not dropped when it is the referent of a kept qualifier whose referents
        # the claim states in full
        covered_texts = {t for s in restated for k, refs in xrefs.get(id(s), {}).items()
                         if k in c.markers and all(_covers_all(c.qualifier_words.get(k, set()), rw) for rw, _t in refs)
                         for _rw, t in refs}
        if restated and not c.exempt and any(s.main_exempt and s.text not in covered_texts for s in restated):
            findings.append(("exemption", "claim drops an exemption stated by the cited sentence"))
        # qualifiers. A kept qualifier is compared with the claim's OWN clause for that marker: words elsewhere in
        # the claim (its main clause) never fill in a word dropped from the clause.
        claim_clauses = _split_qualifiers(c.text)[1]
        for s in restated:
            for marker, qwords in s.qualifier_words.items():
                clause_have = _inflection_free(c.qualifier_words.get(marker, set()))
                missing = _inflection_free(qwords) - clause_have
                clause_text = _split_qualifiers(s.text)[1].get(marker, "")
                referents = xrefs.get(id(s), {}).get(marker, [])
                if marker not in c.markers:
                    # stated by another claim citing this passage: the whole clause, or (for a clause that only
                    # points to a sub-rule) every referent in full, with the same negation as its source
                    if marker in pointer_markers.get(id(s), set()):
                        stated = bool(referents) and any(
                            s.evidence_id in ids and all(_covers_all(words(t), rw) and _negations(t) == _negations(rt)
                                                         for rw, rt in referents)
                            for t, ids in sibs)
                    else:
                        stated = any(s.evidence_id in ids and _covers_all(words(t), qwords)
                                     and _negations(t) == _negations(clause_text) for t, ids in sibs)
                    if not stated:
                        findings.append(("qualifier_omitted", f"claim omits the '{marker}' qualifier of the sentence "
                                         "it restates"))
                elif qwords and len(clause_have & _inflection_free(qwords)) < \
                        QUALIFIER_CLAUSE_COVERAGE * len(_inflection_free(qwords)) \
                        and not _subject_pronoun_accounts_for(missing, s.text, claim_clauses.get(marker, "")) \
                        and not (referents and all(_covers_all(c.qualifier_words.get(marker, set()), rw)
                                                   for rw, _t in referents)
                                 and all(_negations(_split_qualifiers(c.text)[1].get(marker, "")) == _negations(rt)
                                         for _rw, rt in referents)):
                    findings.append(("qualifier_altered", f"claim keeps '{marker}' but changes its clause"))
            for marker in ("before", "after"):
                if marker in s.markers and marker not in c.markers:
                    findings.append(("qualifier_omitted", f"claim omits the '{marker}' sequence of the sentence it "
                                     "restates"))
        anchor_markers = set().union(*(s.markers for s in anchors))
        added = c.markers - anchor_markers
        if added:
            sources = {s.evidence_id for s in anchors}
            check = "composition" if len(sources) > 1 else "qualifier_added"
            findings.append((check, f"claim adds {sorted(added)} not present in the cited sentence(s)"
                             + (" and links separate provisions" if check == "composition" else "")))
        # quantities, compared with their comparator, unit and the case they are attached to
        for q, _ci, _post in c.quantities:
            options = [(s, ci, post) for s in anchors for (aq, ci, post) in s.quantities if aq == q]
            if not options:
                findings.append(("numeric_changed", f"value {q} is not stated in the cited sentence"))
                continue
            claim_values = {cq for cq, _x, _y in c.quantities}

            def consistent(opt):
                s, ci, post = opt
                # rivals: other values of the same unit, in other clauses, that the claim does not also state
                rivals = [p for (aq, cj, p) in s.quantities
                          if aq[2] == q[2] and aq != q and cj != ci and aq not in claim_values]
                return not any((cw & (p - post)) for p in rivals)
            if not any(consistent(o) for o in options):
                findings.append(("numeric_association", f"value {q} is stated for a different case in the cited "
                                 "sentence"))
        claim_qs = {q for q, _ci, _p in c.quantities}
        for s in restated:
            for q, _ci, post in s.quantities:
                if not (q[0] or q[2]):
                    continue  # a bare number (list item, enumerator) is not treated as a material value
                attached = not post or len(cw & post) >= RESTATE_COVERAGE * len(post)
                if attached and q not in claim_qs:
                    findings.append(("numeric_omitted", f"claim drops value {q} of the sentence it restates"))
        # uncited contradictory or qualifying evidence
        if definitive:
            findings += _uncited_findings(c, strip(cs), uncited, strip)
    return list(dict.fromkeys(findings))


def _uncited_findings(c: Sentence, claim_text: str, uncited: dict, strip) -> list:
    """Uncited sentences on the same proposition with the opposite polarity. When the claim itself has no parsable
    proposition, the older subject-word test is kept (it over-fires, but restricting it measurably missed more)."""
    out = []
    cp = proposition(claim_text)
    for eid, passage in uncited.items():
        for us in sentences(passage):
            u_text = strip(us)
            if cp is None:
                c_pos, u_pos = position_text(claim_text), position_text(u_text)
                if c_pos is None or u_pos is None:
                    continue  # a definition, title or bare condition states no position to contradict
                u = analyse(eid, u_text)
                uw = _all_words(u)
                shared = c.main_words & uw
                c_pol, u_pol = (polarity(_split_qualifiers(t)[0], relative=True) for t in (c_pos, u_pos))
                if len(shared) >= CONFLICT_MIN_SHARED and len(shared) >= CONFLICT_SHARED_RATIO * len(uw) and (
                        frozenset({c_pol, u_pol}) in _OPPOSED or c.main_exempt != u.main_exempt):
                    out.append(("uncited_conflict", f"uncited evidence {eid} may contradict this claim; use "
                                "'conflicting' and cite both"))
                continue
            up = proposition(u_text)
            if up is None or not same_proposition(cp, up):
                continue
            pair = frozenset({cp.polarity, up.polarity})
            if not (pair in _OPPOSED or cp.exempt != up.exempt or embedded_opposed(cp.embedded, up.embedded)):
                continue
            # "... capacity of the vehicle" is not the object; an object stated only inside a qualifier clause
            # ("shall be used only on the routes ...") is still an object; words of a trailing condition are not
            # ("... when a signal to stop is being given by a traffic sign"), nor a participle alone ("given")
            c_obj = (cp.core_obj or cp.obj or cp.qualifier_words) - cp.actor
            u_obj = (up.core_obj or up.obj or up.qualifier_words) - up.actor
            if (pair in _COEXIST_ON_DIFFERENT_OBJECTS and cp.exempt == up.exempt and c_obj and u_obj
                    and not (c_obj & u_obj) - NON_LINKING_OBJECT_WORDS):
                continue  # e.g. "shall carry a first-aid box" / "shall not carry more persons than ..."
            if cp.result and up.result and not same_result(cp.result, up.result):
                continue  # "so constructed that a person may sit ..." / "... that the driver has a clear view"
            if narrows(up, cp):
                out.append(("uncited_qualification", f"uncited evidence {eid} may qualify this claim (an exemption, "
                            "condition or narrower case of the same proposition); cite it rather than answer "
                            "definitively without it"))
            else:
                out.append(("uncited_conflict", f"uncited evidence {eid} may contradict this claim; use "
                            "'conflicting' and cite both"))
            break  # one finding per uncited passage
    return out

