"""Telangana Police e-Challan fine tables as a SECONDARY source of website-displayed amounts.

What this is: a deterministic lookup (no model call) over the 162 rows scraped from two pages of the Telangana Police e-Challan
website. An answer says "Amount displayed on the Telangana Police e-Challan website", cites the exact page, and carries the
website's own caveat. It never calls an amount a statutory fine, a Telangana compounding amount, or verified.

What it is not: legal evidence. It does not override the Motor Vehicles Act or any other legal source, it is never used to
check or correct a model answer, and the grounded-answer penalty guard is unchanged. Where the two tables disagree, both are
shown and the disagreement is stated; nothing is chosen, averaged or corrected. If an offence cannot be matched confidently the
caller gets a clarification, or nothing (and the existing penalty lock reply applies).

Provenance lives in backend/echallan_fines_data.json (built by scripts/build_echallan_fines_data.py from the read-only files in
research/). The loader checks the row hash, so an edited row switches the feature off instead of serving altered figures."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent / "echallan_fines_data.json"
ENV_SWITCH = "TG_ECHALLAN_FINES"  # OFF unless set to 1/true/yes/on: fine questions stay locked by default (fail closed)

AMOUNT_LABEL = "Amount displayed on the Telangana Police e-Challan website."
DISCLAIMER = ("These are indicative figures published on the Telangana Police website and may be subject to amendments. "
              "Please check the official e-Challan portal for the latest amount.")
NOT_VERIFIED = ("These figures are not independently verified statutory fines and are not Telangana compounding amounts. "
                "They do not replace the Motor Vehicles Act or any other legal source.")

CLASSES = ["2 Wheeler", "3 Wheeler", "4 Wheeler", "Lorry/DCM", "Truck/HMV"]


# ---- data ---------------------------------------------------------------------------------------------------------------
@dataclass
class Table:
    key: str
    url: str
    label: str


@dataclass
class Store:
    entries: list = field(default_factory=list)
    tables: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)
    error: str | None = None

    @property
    def ready(self):
        return self.error is None and bool(self.entries)


def _rows_hash(entries):
    canon = json.dumps([[e["id"], e["offence"], e["section"], e["amount_displayed"]] for e in entries], ensure_ascii=False)
    return hashlib.sha256(canon.encode()).hexdigest()


def enabled() -> bool:
    return os.environ.get(ENV_SWITCH, "").strip().lower() in {"1", "true", "yes", "on"}


def load(path: Path = DATA_PATH) -> Store:
    try:
        data = json.loads(Path(path).read_text())
        prov = data["provenance"]
        entries = data["entries"]
        if len(entries) != prov["entry_count"] or _rows_hash(entries) != prov["rows_sha256"]:
            return Store(error="row hash mismatch: the table was changed after it was built")
        tables = {k: Table(k, v["url"], v["label"]) for k, v in prov["tables"].items()}
        for e in entries:
            e["_tokens"] = tokens(e["offence"])
            e["_class_amounts"] = parse_wheel_amounts(e["amount_displayed"]) if e["table"] == "mv-act-rules" else None
        return Store(entries=entries, tables=tables, provenance=prov)
    except Exception as exc:  # unreadable data switches the feature off; it never serves partial figures
        return Store(error=f"{type(exc).__name__}: {exc}")


_STORE: Store | None = None


def store() -> Store:
    global _STORE
    if _STORE is None:
        _STORE = load()
    return _STORE


def status() -> dict:
    s = store()
    return {"enabled": enabled(), "ready": s.ready, "entries": len(s.entries), "error": s.error,
            "scraped_file_sha256": s.provenance.get("scraped_file_sha256"), "rows_sha256": s.provenance.get("rows_sha256"),
            "retrieved": s.provenance.get("retrieved"), "label": "website-displayed amounts, not independently verified"}


# ---- amounts ------------------------------------------------------------------------------------------------------------
def parse_wheel_amounts(text: str) -> dict:
    """'2 Wheeler: ₹100/- ; 3 Wheeler: ₹0/- ...' -> {'2 Wheeler': ('₹100/-', 100), ...}. Display strings are kept verbatim."""
    out = {}
    for part in text.split(";"):
        m = re.match(r"\s*([^:]+):\s*(.+?)\s*$", part)
        if m:
            amt = m.group(2)
            n = re.search(r"([\d,]+)", amt)
            out[m.group(1).strip()] = (amt, int(n.group(1).replace(",", "")) if n else None)
    return out


def numbers(text: str) -> set:
    return {int(x.replace(",", "")) for x in re.findall(r"(?:₹|Rs\.?)\s*([\d,]+)", text)}


# ---- matching -----------------------------------------------------------------------------------------------------------
STOP = set("""what is the a an of to my i me if in on be can will do does are by when how much for and or any it this that there
fine fines challan challans amount amounts penalty penalties charge charged cost costs rs rupees rupee inr pay paid payable tell
telangana hyderabad traffic police e echallan under as with at from should would get gets given give about charges applicable
imposed levied levy over area areas place places zone zones road roads while during after before at near full please much many whether happen happens caught got gets get""".split())
GENERIC = {"driv": 0.5, "wear": 0.5, "vehic": 0.5, "use": 0.5, "no": 0.3, "violat": 0.4, "of": 0.1, "carry": 0.6, "rule": 0.4,
           "offenc": 0.4, "park": 0.9, "person": 0.4, "motor": 0.4, "act": 0.2, "certificat": 0.3, "rid": 0.3, "person": 0.3, "us": 0.4, "regard": 0.2}
NEG = {"without", "no", "not", "wo", "w/o", "non", "never"}
ALIAS = {"license": "licence", "licenses": "licence", "licences": "licence", "dl": "licence", "phone": "mobile", "cell": "mobile",
         "cellphone": "mobile", "smartphone": "mobile", "seatbelt": "seatbelt", "belt": "seatbelt", "seat-belt": "seatbelt",
         "puc": "puc", "pollution": "puc", "drunk": "drunk", "drunken": "drunk", "alcohol": "drunk", "intoxicated": "drunk",
         "riding": "ride", "rider": "ride", "riders": "ride", "ride": "ride", "rash": "dangerous", "reckless": "dangerous", "speeding": "speed",
         "overspeeding": "speed", "overspeed": "speed", "jumping": "jump", "jump": "jump", "signals": "signal", "plates": "plate",
         "number-plate": "plate", "numberplate": "plate", "uturn": "uturn", "u-turn": "uturn", "wrongside": "wrong", "intoxicants": "drunk", "intoxicant": "drunk",
         "intoxicating": "drunk", "intoxication": "drunk", "substances": "drunk", "subtances": "drunk", "liquor": "drunk", "drinking": "drunk",
         "drink": "drunk", "consuming": "drunk"}
CLASS_WORDS = {"2 Wheeler": r"bike|bikes|motorcycle|motor\s*cycle|scooter|scooty|moped|two[\s-]*wheeler|2[\s-]*wheeler|two[\s-]*wheel",
               "3 Wheeler": r"three[\s-]*wheeler|3[\s-]*wheeler|auto[\s-]*rickshaw|rickshaw|\bauto\b",
               "4 Wheeler": r"\bcar\b|\bcars\b|jeep|\bsuv\b|four[\s-]*wheeler|4[\s-]*wheeler|\btaxi\b|\bcab\b",
               "Lorry/DCM": r"lorry|\bdcm\b|goods\s+vehicle|tractor",
               "Truck/HMV": r"\btruck\b|\bhmv\b|\bbus\b|heavy\s+(?:motor\s+)?vehicle"}
_CLASS_ONLY = re.compile(r"bikes?|motor\s*cycle|motorcycle|scooter|scooty|moped|two[\s-]*wheeler|2[\s-]*wheeler|cars?|jeep|suv|"
                         r"four[\s-]*wheeler|4[\s-]*wheeler|three[\s-]*wheeler|3[\s-]*wheeler|lorry|truck", re.I)


def _stem(w: str) -> str:
    if len(w) > 4 and w.endswith("ing"):
        w = w[:-3]
    elif len(w) > 4 and w.endswith("ed"):
        w = w[:-2]
    elif len(w) > 4 and w.endswith("es"):
        w = w[:-2]
    elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        w = w[:-1]
    if len(w) > 3 and w.endswith("e"):
        w = w[:-1]
    return w


TRIPLE_RIDING = re.compile(r"\b(?:(?:carry\w*|taking|riding\s+with|with|having)\s+)?(?:3|three)\s+(?:(?:people|persons?|passengers?|riders?|pillions?|guys|members)\b|(?:up\s+)?on\b)", re.I)


def _triple_riding(question: str) -> str:
    """"3 people on a bike" is triple riding; the same words about a car are not. Runs before class words are stripped from the question."""
    if re.search(CLASS_WORDS["2 Wheeler"], question, re.I):
        return TRIPLE_RIDING.sub(" triple riding ", question)
    return question


def tokens(text: str) -> set:
    t = text.lower().replace("w/o", " without ").replace("u/s", " ")
    t = re.sub(r"\bseat\s+belt\b", "seatbelt", t)
    t = re.sub(r"\bno[\s-]+parking\b", "no parking", t)
    t = re.sub(r"\bu[\s-]*turn\b", "uturn", t)
    t = re.sub(r"\b(?:red\s+light|signal\s+jump\w*|jump\w*\s+(?:the\s+|a\s+)?(?:red\s+)?(?:light|signal))\b", "signal jump", t)
    out = set()
    for w in re.findall(r"[a-z0-9]+", t):
        if w in STOP or w.isdigit():
            continue
        w = ALIAS.get(w, w)
        if w in NEG:
            out.add("no")
            continue
        out.add(_stem(w))
    out.discard("")
    return out


def weight(tok: str) -> float:
    return GENERIC.get(tok, 1.0)


def vehicle_class(question: str) -> str | None:
    found = [c for c, rx in CLASS_WORDS.items() if re.search(rx, question, re.I)]
    return found[0] if len(found) == 1 else None


def score(q: set, e: set) -> tuple[float, bool, bool]:
    """(score, guarded_strong, raw_strong). guarded_strong is False when one word is all the two texts share and it is a small part
    of the entry ("blocking" vs "...sheet blocked on auto"); such an entry is only used when the other table corroborates it."""
    if not q or not e:
        return 0.0, False, False
    qw = sum(weight(t) for t in q)
    common = q & e
    cov = sum(weight(t) for t in common) / qw
    ew = sum(weight(t) for t in e)
    prec = sum(weight(t) for t in common) / ew
    strong = any(weight(t) >= 0.9 for t in common)
    guarded = strong and not (sum(weight(t) for t in common) < 1.5 and prec < 0.25)
    return 0.75 * cov + 0.25 * prec, guarded, strong


# An entry about one specific kind of offence is only a candidate when the question mentions that kind: "speeding" is not "racing".
ONLY_IF_ASKED = {"rac": {"rac", "trail", "trial"}}


def _off_topic(q: set, e: set) -> bool:
    return any(k in e and not (q & ok) for k, ok in ONLY_IF_ASKED.items())


SECTION_Q = re.compile(r"\b(?:sections?|sec\.?|s\.)\s*(\d{2,3})\b", re.I)
AMOUNT_ASK = re.compile(r"\b(?:fines?|challans?|e-?challans?|penalt(?:y|ies)|how\s+much|amount|charge[sd]?|cost)\b|₹|\brs\b|\brupees?\b", re.I)
# These are not about an amount shown in the tables: leave them to the existing locks / grounded path.
OUT_OF_TABLE = re.compile(r"\b(?:imprison\w*|jail|prison|arrest\w*|points?|suspen\w*|cancel\w*|disqualif\w*|revok\w*|compound\w*|"
                          r"court|bail|punishment|sentence|tax|insurance\s+claim|refund|waive\w*|dispute|appeal|pay\s+online)\b", re.I)


@dataclass
class Match:
    kind: str  # "answer" | "clarify" | "none"
    entries: list = field(default_factory=list)  # chosen entries, both tables
    vehicle: str | None = None
    sections: list = field(default_factory=list)
    suggestions: list = field(default_factory=list)


# Questions that ask for the consequence of an offence without saying "fine": the existing penalty lock already treats these as penalty questions.
CONSEQUENCE_ASK = re.compile(r"\bwhat\s+(?:if|happens?|will\s+happen|would\s+happen)\b|\bconsequences?\b|\b(?:get|gets|got)\s+caught\b|\bcaught\b", re.I)
# A bare description of an offence ("Carrying 3 people on a bike"). Questions, requests and rule/permission wording are not this.
NOT_A_PHRASE = re.compile(r"^\s*(?:can|could|is|are|am|do|does|did|should|may|might|how|why|who|where|which|when|what|will|would|tell|explain|give|list|show)\b", re.I)
LEGAL_ASK = re.compile(r"\b(?:rules?|laws?|legal\w*|illegal|allowed|permit\w*|mandatory|compulsory|required?|requirements?|need\w*|procedure|process|apply|"
                       r"renew\w*|valid\w*|eligib\w*|documents?|age|limit|sections?|act)\b", re.I)


def _ask_mode(question: str) -> str | None:
    """"amount" (asks for a fine/amount), "consequence" (what if / what happens), "phrase" (bare offence description) or None."""
    if OUT_OF_TABLE.search(question):
        return None
    if AMOUNT_ASK.search(question):
        return "amount"
    if CONSEQUENCE_ASK.search(question):
        return "consequence"
    if 3 <= len(question.split()) <= 8 and not NOT_A_PHRASE.search(question) and not LEGAL_ASK.search(question):
        return "phrase"
    return None


def _wants_amount(question: str) -> bool:
    return _ask_mode(question) is not None


def find(question: str) -> Match:
    s = store()
    if not enabled() or not s.ready or not _wants_amount(question):
        return Match("none")
    veh = vehicle_class(question)
    sections = SECTION_Q.findall(question)
    q = tokens(_CLASS_ONLY.sub(" ", SECTION_Q.sub(" ", _triple_riding(question)))) - {"rid"}  # "ride" is context in a question; entries keep it
    pool = s.entries
    if sections:
        pool = [e for e in pool if set(sections) & set(e["act_sections"])]
        if not pool:
            return Match("clarify", vehicle=veh, sections=sections)
        if not q:  # "fine under section 122": every entry of that section, both tables, nothing chosen
            return Match("answer", entries=pool, vehicle=veh, sections=sections)
    chosen, weak, unconfirmed = [], [], {}
    for table in s.tables:
        scored = []
        for e in pool:
            if e["table"] != table or _off_topic(q, e["_tokens"]):
                continue
            sc, guarded, raw = score(q, e["_tokens"])
            scored.append((sc, guarded, raw, e))
        scored.sort(key=lambda x: -x[0])
        if not scored:
            continue
        best = scored[0][0]
        near = [e for sc, g, raw, e in scored if sc >= best - 0.15 and g]
        if best >= 0.62 and scored[0][1] and len(near) >= 6 and sum(weight(x) for x in q) <= 1.0:
            weak += near[:4]  # one general word ("parking") fits many different offences: ask which, do not pick one
        elif best >= 0.62 and scored[0][1]:
            chosen += [e for sc, g, raw, e in scored if sc >= best - 0.04 and g][:12]
        elif best >= 0.35 and scored[0][1]:
            weak += [e for sc, g, raw, e in scored[:3] if g and sc >= 0.35]
        elif best >= 0.62 and scored[0][2]:
            unconfirmed[table] = [e for sc, g, raw, e in scored if raw and sc >= best - 0.04][:3]
    for table, es in unconfirmed.items():  # one shared word is accepted only when the OTHER table confidently matched as well
        if chosen and not any(c["table"] == table for c in chosen):
            chosen += es
    if chosen:
        return Match("answer", entries=chosen, vehicle=veh, sections=sections)
    if weak and _ask_mode(question) != "phrase":  # a bare phrase is answered only when it clearly names an offence, never turned into a clarification
        return Match("clarify", suggestions=weak[:4], vehicle=veh, sections=sections)
    return Match("none", vehicle=veh)


# ---- rendering ----------------------------------------------------------------------------------------------------------
def _wheel_text(e: dict, veh: str | None) -> tuple[str, set]:
    amts = e["_class_amounts"]
    if veh and veh in amts:
        txt, n = amts[veh]
        return (f"{veh}: **{txt}**" if n else f"{veh}: {txt}"), ({n} if n else set())
    groups = {}
    for cls in CLASSES:
        if cls in amts:
            groups.setdefault(amts[cls][0], []).append(cls)
    parts, nums = [], set()
    for txt, cs in groups.items():
        n = amts[cs[0]][1] or 0
        label = "all vehicle classes" if len(cs) == len(CLASSES) else ", ".join(cs)
        parts.append(f"{label}: **{txt}**" if n > 0 else f"{label}: {txt}")
        if n > 0:
            nums.add(n)
    return "; ".join(parts), nums


def _plain_text(e: dict) -> tuple[str, set]:
    return f"**{e['amount_displayed']}**", numbers(e["amount_displayed"])


def _group_by_amount(entries, fn):
    groups = {}
    for e in entries:
        txt, nums = fn(e)
        groups.setdefault(txt, {"nums": nums, "items": []})["items"].append(e)
    return groups


_TOKEN = re.compile(r"(?:Rs\.?\s*[\d,]+/-|₹\s*[\d,]+/-|Rs\.?\s*[\d,]+|₹\s*[\d,]+)")


def _tokens_of(entry: dict, veh: str | None) -> list[str]:
    """Distinct non-zero amount strings of one row, exactly as printed."""
    if entry["table"] == "mv-act-rules":
        amts = entry["_class_amounts"]
        cols = [veh] if veh and veh in amts else CLASSES
        return [amts[c][0] for c in cols if c in amts and (amts[c][1] or 0) > 0]
    toks = _TOKEN.findall(entry["amount_displayed"])
    return toks if toks else [entry["amount_displayed"].strip().rstrip(".")]


def _headline_part(es: list, veh: str | None) -> str:
    seen = []
    for e in es:
        if e["table"] == "mv-act-rules":
            amts = e["_class_amounts"]
            groups = {}
            for c in ([veh] if veh and veh in amts else CLASSES):
                if c in amts and (amts[c][1] or 0) > 0:
                    groups.setdefault(amts[c][0], []).append(c)
            for amt, cs in groups.items():
                label = "" if (veh or len(cs) == len(CLASSES)) else ", ".join(cs) + " "
                tok = f"{label}{amt}"
                if tok not in seen:
                    seen.append(tok)
        else:
            for tok in _tokens_of(e, veh):
                if tok not in seen:
                    seen.append(tok)
    if not seen:
        return "₹0/- as printed" + (f" for {veh}" if veh else " for every vehicle class")
    return " or ".join(seen[:4]) + (" (and others)" if len(seen) > 4 else "")


def render(m: Match) -> str:
    s = store()
    veh = m.vehicle
    by_table = {k: [e for e in m.entries if e["table"] == k] for k in s.tables}
    if veh and by_table["mv-act-rules"]:  # a named vehicle class: drop wheel-wise rows that print zero for it when others do not
        keep = [e for e in by_table["mv-act-rules"] if (e["_class_amounts"].get(veh, ("", 0))[1] or 0) > 0]
        if keep:
            by_table["mv-act-rules"] = keep
    short = {"mv-act-rules": "wheel-wise table", "mvact": "plain table"}
    parts, shown = [], {}
    for key in s.tables:
        es = by_table[key]
        if es:
            parts.append(f"{short[key]}: {_headline_part(es, veh)}")
            shown[key] = {int(x.replace(",", "")) for e in es for tok in _tokens_of(e, veh) for x in re.findall(r"[\d,]+", tok) if x.strip(",")}
        else:
            parts.append(f"{short[key]}: no matching entry")
    both = bool(by_table["mv-act-rules"] and by_table["mvact"])
    wa, pa = shown.get("mv-act-rules", set()), shown.get("mvact", set())
    neither = both and not wa and not pa
    disagree = both and not neither and wa != pa
    topic = f"Section {', '.join(m.sections)}" if m.sections else "Result"
    lines = [f"**{topic}: " + "; ".join(parts) + ".**"]  # the amount comes first
    if disagree:
        lines.append("**The two website tables disagree.** I have shown both figures as printed and have not chosen between them or corrected either.")
    elif neither:
        lines.append("Neither table prints a rupee amount for this offence (see the entries below, shown as printed).")
    elif both:
        lines.append("Both website tables show the same figure.")
    else:
        lines.append("Only one of the two website tables has a matching entry, so there is nothing to compare it with.")
    lines += ["", f"_{AMOUNT_LABEL}_", ""]
    zero_shown = False
    for key, table in s.tables.items():
        es = by_table[key]
        if not es:
            continue
        lines.append(f"**[{table.label}]({table.url})**")
        fn = (lambda e: _wheel_text(e, veh)) if key == "mv-act-rules" else _plain_text
        for txt, g in _group_by_amount(es, fn).items():
            names = [f"“{e['offence']}” ({e['section']})" for e in g["items"]]
            listed = "; ".join(names[:5]) + (f"; and {len(names) - 5} more entries" if len(names) > 5 else "")
            lines.append(f"- {listed}: {txt}")
            zero_shown = zero_shown or (key == "mv-act-rules" and re.search(r"₹0/-", txt) is not None)
        lines.append("")
    notes = []
    if zero_shown:
        notes.append("A zero on the wheel-wise page is printed as shown; the page does not say whether it means no fine or not applicable."
                     + ("" if veh else " Tell me the vehicle type to see only that column."))
    if m.sections:
        notes.append("This lists every entry the tables cite under that section. It reports what the website's rows say, not a check against the Act.")
    notes.append(NOT_VERIFIED)
    for n in notes[:-1]:
        lines += [n, ""]
    lines += [notes[-1], "", f"_{DISCLAIMER}_"]
    return "\n".join(lines).strip()


def render_clarification(m: Match) -> str:
    if m.sections and not m.suggestions:
        return (f"I couldn't find Section {', '.join(m.sections)} in the two Telangana Police e-Challan tables, so I have no website "
                "amount for it. Tell me the offence in words (for example “no parking” or “no helmet”).")
    names = "; ".join(sorted({f"“{e['offence']}”" for e in m.suggestions}))
    return ("I couldn't match your question to one offence in the Telangana Police e-Challan tables with enough confidence to give an "
            f"amount. Did you mean one of these: {names}? Please name the offence (and the vehicle type) and I'll show the amount the "
            "website displays.")


def sources(m: Match) -> list[dict]:
    """Source rows for the reply: one per page actually used, each carrying the exact URL and the rows it supplied."""
    s = store()
    out = []
    for key, table in s.tables.items():
        es = [e for e in m.entries if e["table"] == key]
        if not es:
            continue
        out.append({"title": f"Telangana Police e-Challan: {table.label}", "instrument": "Website-displayed amounts (not independently verified)",
                    "verified": False, "file": table.url, "sha256": s.provenance["tables"][key].get("page_sha256"),
                    "document_id": f"echallan-{key}", "files": [{"file": table.url, "sha256": s.provenance["tables"][key].get("page_sha256"),
                                                                  "manifest_id": f"echallan-{key}"}],
                    "text_status": None, "jurisdiction": "Telangana", "url": table.url,
                    "passages": [{"provision_id": e["id"], "label": f"{e['offence']} | {e['section']}", "text": e["amount_displayed"],
                                  "cited": True, "chunk_id": f"echallan-{key}::{e['id']}", "manifest_id": f"echallan-{key}",
                                  "file": table.url, "sha256": s.provenance["tables"][key].get("page_sha256"), "location": table.url}
                                 for e in es[:20]]})
    return out
