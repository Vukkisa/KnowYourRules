"""Stage 4G: two further evidence-bound, word-sense exceptions for the penalty check of a model answer.

Same mechanism and same guarantees as backend/eligibility_status.py: a span is neutralised for the penalty check ONLY if a
passage the claim cites contains the same span (compared case-insensitively, hyphens as spaces). The model cannot
introduce the wording. The penalty guard itself and the user-question lock are untouched; anything else in the claim,
or in another claim, is still checked in full.

The penalty guard is deliberately lexical ("when in doubt, lock"). Two of its trigger words have an ordinary sense
that has nothing to do with enforcement. The corpus was searched for every sentence the guard flags; these are the
only ordinary-sense families that are exact, closed and clearly not a legal consequence:

  possession  "custody" of a document or load: custody (and production|delivery) of badge / trip-sheet / luggage
              (Rules 40, 70, 74, 185, 271). NOT neutralised: a vehicle in police custody, "place of safe custody",
              "released from custody" (Rules 13B, 405, 407, 408, 448A are enforcement) or goods in an agent's custody (297).
  physical    "liable to" meaning "apt to": liable to foul / injure / be over-turned (Rules 201, 327, 328, 343).
              NOT neutralised: liable to pay / indemnify / make good / be convicted / be suspended or cancelled / tax
              (legal liability: Rules 12, 12A, 123, 187, 216, 297, 408, 420). "Liable to indemnify" is a civil
              liability, a legal consequence, and stays locked for legal review.

This is word-sense disambiguation of four closed phrases, not a legal interpretation.
"""
import re

POSSESSION = re.compile(
    r"\b(?:safe\s+)?custody(?:\s+and\s+(?:production|delivery))?\s+of\s+(?:the\s+)?(?:badges?|trip[\s-]*sheets?|luggage)\b",
    re.IGNORECASE)
PHYSICAL = re.compile(r"\bliable\s+to\s+(?:foul|injure|be\s+over-?turned)\b", re.IGNORECASE)
FAMILIES = ((POSSESSION, "possession"), (PHYSICAL, "likely"))


def _key(span: str) -> str:
    return re.sub(r"[\s-]+", " ", span.lower())


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "")


def mask(text: str, evidence_passages) -> str:
    """`text` with each exempt span that a cited passage also contains replaced by a neutral word."""
    out = _norm(text)
    changed = False
    for rx, neutral in FAMILIES:
        keys = {_key(m.group(0)) for passage in evidence_passages for m in rx.finditer(_norm(passage))}
        if not keys:
            continue

        def sub(m, keys=keys, neutral=neutral):
            return neutral if _key(m.group(0)) in keys else m.group(0)
        new = rx.sub(sub, out)
        changed = changed or new != out
        out = new
    return out if changed else text
