"""Provision-level validity ledger: a pure, isolated library (roadmap Step 1, milestone M-A).

Step 4: only backend/provision_validity_runtime.py and ledger_acceptance.py import this file (tests/test_provision_validity.py
proves it); server.py imports only the wrapper. It reads no
index, writes no file and touches no approval record; it only parses a ledger and answers "what may the ledger say about
this chunk". Standard library only.

Rules this module enforces (roadmap invariants):

* I4  A validity fact counts only when ALL hold: ``kind == "commencement"``, ``state == "approved"``, its decision is
      ``approved``, the caller says the ledger is ``bound`` to a valid signed approval, and the ledger is not a fixture.
      ``Fact.candidate`` is never read.
* I3  The ledger can only restrict. ``resolve_chunk`` never returns AUTHORITATIVE or HISTORICAL in any reachable mode
      (``enforce`` is not built and ``ENFORCE_LOCKED`` is True). What the ledger would say with full trust is exposed as
      ``Verdict.opinion`` for shadow comparison only and must never be served. ``combine`` is the only sanctioned way to
      merge a verdict with a legacy class and it never returns a better class than the legacy one.
* I5  A chunk whose covered provisions do not share one interval is ``partial``: BLOCKED for current-law (undated)
      questions, never better than UNVERIFIED for dated ones, never authoritative.
* I6  A closed version is never returned for an undated question.
* I10 A ledger marked ``"fixture": true`` refuses to load unless the caller passes ``allow_fixture=True``, and even then it
      is never trusted.

Dates are integer yyyymmdd, inclusive at both ends, as everywhere else in the code base.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

__all__ = [
    "MODES", "ENFORCE_LOCKED", "SCHEMA_VERSION", "INTERVAL_RULE",
    "AUTHORITATIVE", "HISTORICAL", "UNVERIFIED", "NOT_IN_FORCE", "BLOCKED", "CLASSES",
    "LedgerError", "Fact", "Interval", "Version", "Operation", "Coverage", "Decision", "Instrument", "Provision",
    "Ledger", "Problem", "Verdict",
    "load_ledger", "validate", "resolve_chunk", "combine", "normalize_mode", "rank", "text_digest",
]

MODES = ("off", "shadow", "restrict")
ENFORCE_LOCKED = True  # `enforce` is not built. Nothing in this module reads this to unlock anything.
SCHEMA_VERSION = 1
INTERVAL_RULE = "day_before_successor_start"  # predecessor's last day = day before the successor's commencement

AUTHORITATIVE = "authoritative"
HISTORICAL = "historical"
UNVERIFIED = "unverified"
NOT_IN_FORCE = "not_in_force"
BLOCKED = "blocked"
CLASSES = (AUTHORITATIVE, HISTORICAL, UNVERIFIED, NOT_IN_FORCE, BLOCKED)
_RANK = {AUTHORITATIVE: 4, HISTORICAL: 3, UNVERIFIED: 2, BLOCKED: 0, NOT_IN_FORCE: 0}

VALIDITY_KIND = "commencement"
FACT_KINDS = ("commencement", "gazette_direction", "publication", "issue")  # only the first may feed validity
FACT_STATES = ("approved", "proposed", "unknown")
OP_TYPES = ("insert", "substitute", "delete", "omit", "repeal", "amend_words", "commence", "supersede_unidentified",
            "scope_note")
CLOSING_OPS = ("substitute", "delete", "omit", "repeal", "amend_words")
CREATING_OPS = ("insert", "substitute", "amend_words")
END_STATES = ("closed", "continuing_verified", "unverified")
DECISION_STATUSES = ("pending", "evidence_incomplete", "evidence_complete", "approved", "rejected", "revoked")
SELECTOR_KEYS = ("manifest_id", "sha256", "provision_id", "part", "parts", "page_start", "page_end", "text_sha256")

_INSTRUMENT_RE = re.compile(r"^([A-Z]{2}):([A-Z]+):([A-Za-z0-9.\-]+(?:/[0-9]{4})?)$")
_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-()]*$")
_DECISION_RE = re.compile(r"^LD-\d{3}$")
_OP_RE = re.compile(r"^OP-[A-Za-z0-9._\-]+$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


class LedgerError(ValueError):
    """The ledger is malformed, unsafe to load, or a fixture offered to a non-test caller."""


def rank(cls: str) -> int:
    """Class order for monotonicity (I3): authoritative > historical > unverified > blocked == not_in_force."""
    return _RANK[cls]


# ------------------------------------------------------------------------------------------------ data structures

@dataclass(frozen=True)
class Fact:
    state: str
    date: Optional[int]
    kind: str
    candidate: Optional[int] = None  # what the instrument text states. NEVER read by retrieval.
    evidence: tuple = ()
    decision_ref: Optional[str] = None


@dataclass(frozen=True)
class Interval:
    start: Optional[Fact]          # None = unknown start
    end_state: str                 # "closed" | "continuing_verified" | "unverified"
    end: Optional[Fact] = None     # closed: the closing operation's commencement fact; the last day is derived from it
    checked_through: Optional[int] = None
    decision_ref: Optional[str] = None  # continuing_verified: the decision approving the no-later-amendment search


@dataclass(frozen=True)
class Instrument:
    key: str
    kind: str
    jurisdiction: str
    manifest_ids: tuple


@dataclass(frozen=True)
class Provision:
    key: str
    parent: Optional[str]
    label: str


@dataclass(frozen=True)
class Version:
    key: str
    provision: str
    text_held: bool
    text_locators: tuple
    created_by_op: Optional[str]
    closed_by_op: Optional[str]
    interval: Interval


@dataclass(frozen=True)
class Operation:
    id: str
    type: str
    source: str
    locator: Optional[str]
    targets: tuple
    effective_from: Optional[Fact]
    scope_note: Optional[str]
    decision_ref: Optional[str]


@dataclass(frozen=True)
class Coverage:
    selector: Mapping
    provisions: tuple
    decision_ref: Optional[str]


@dataclass(frozen=True)
class Decision:
    decision_id: str
    status: str
    subject: str
    prepared_by: Optional[str]
    reviewer: Optional[str]
    replaces: Optional[str]


@dataclass(frozen=True)
class Ledger:
    sha256: str
    fixture: bool
    instruments: tuple
    provisions: tuple
    versions: tuple
    operations: tuple
    coverage: tuple
    decisions: tuple
    interval_rule: Optional[str] = None      # decision id approving INTERVAL_RULE (A11)
    freshness_days: Optional[int] = None
    freshness_ref: Optional[str] = None
    _dec: dict = field(default_factory=dict, init=False, repr=False, compare=False)
    _prov: dict = field(default_factory=dict, init=False, repr=False, compare=False)
    _ver: dict = field(default_factory=dict, init=False, repr=False, compare=False)
    _op: dict = field(default_factory=dict, init=False, repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, "_dec", {d.decision_id: d for d in self.decisions})
        object.__setattr__(self, "_prov", {p.key: p for p in self.provisions})
        object.__setattr__(self, "_op", {o.id: o for o in self.operations})
        by_prov: dict = {}
        for v in self.versions:
            by_prov.setdefault(v.provision, []).append(v)
        object.__setattr__(self, "_ver", {k: tuple(vs) for k, vs in by_prov.items()})


@dataclass(frozen=True)
class Problem:
    code: str       # C1..C5, C3b, C8, C11, S1, S2
    severity: str   # "error" | "warning" | "info"
    subject: str
    message: str


@dataclass(frozen=True)
class Verdict:
    cls: str                  # what the server may act on. Never AUTHORITATIVE/HISTORICAL from resolve_chunk (I3).
    reasons: tuple = ()
    provisions: tuple = ()
    covered: bool = False     # False: the ledger has nothing to say, the legacy path applies unchanged
    partial: bool = False     # I5
    opinion: Optional[str] = None  # INFORMATIONAL (shadow logging). The class under full trust. Never serve on it.


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------------------------ date helpers

def _is_date(n: Any) -> bool:
    if isinstance(n, bool) or not isinstance(n, int):
        return False
    try:
        _dt.date(n // 10000, n // 100 % 100, n % 100)
    except ValueError:
        return False
    return True


def _ord(n: int) -> int:
    return _dt.date(n // 10000, n // 100 % 100, n % 100).toordinal()


def _prev_day(n: int) -> Optional[int]:
    o = _ord(n) - 1
    if o < 1:
        return None
    d = _dt.date.fromordinal(o)
    return d.year * 10000 + d.month * 100 + d.day


# ------------------------------------------------------------------------------------------------ loading

def _fail(where: str, msg: str):
    raise LedgerError(f"{where}: {msg}")


def _strict(obj: Any, where: str, required=(), optional=()) -> dict:
    if not isinstance(obj, dict):
        _fail(where, "must be an object")
    missing = [k for k in required if k not in obj]
    extra = [k for k in obj if k not in required and k not in optional]
    if missing:
        _fail(where, f"missing key(s) {missing}")
    if extra:
        _fail(where, f"unknown key(s) {extra}")
    return obj


def _str(v: Any, where: str, *, none_ok: bool = False) -> Optional[str]:
    if v is None and none_ok:
        return None
    if not isinstance(v, str) or not v.strip():
        _fail(where, "must be a non-empty string")
    return v


def _list(v: Any, where: str) -> list:
    if not isinstance(v, list):
        _fail(where, "must be a list")
    return v


def _decision_ref(v: Any, where: str, decisions: dict, *, none_ok: bool = True) -> Optional[str]:
    if v is None and none_ok:
        return None
    if not isinstance(v, str) or not _DECISION_RE.match(v):
        _fail(where, "decision_ref must look like LD-nnn")
    if v not in decisions:
        _fail(where, f"decision_ref {v} is not in decisions")
    return v


def _evidence(v: Any, where: str) -> tuple:
    out = []
    for i, e in enumerate(_list(v, where)):
        e = _strict(e, f"{where}[{i}]", optional=("file", "sha256", "locator", "note"))
        for k, x in e.items():
            if not isinstance(x, str):
                _fail(f"{where}[{i}].{k}", "must be a string")
        out.append(dict(e))
    return tuple(out)


def _fact(obj: Any, where: str, decisions: dict) -> Fact:
    """A fact in a validity slot (start, closing/creating operation's effective_from). Only commencement is accepted."""
    o = _strict(obj, where, required=("state", "kind"), optional=("date", "candidate", "evidence", "decision_ref"))
    state, kind = o["state"], o["kind"]
    if state not in FACT_STATES:
        _fail(where, f"state must be one of {FACT_STATES}")
    if kind not in FACT_KINDS:
        _fail(where, f"kind must be one of {FACT_KINDS}")
    if kind != VALIDITY_KIND:
        _fail(where, f"kind {kind!r} may never feed validity (only {VALIDITY_KIND!r})")
    date = o.get("date")
    cand = o.get("candidate")
    if cand is not None and not _is_date(cand):
        _fail(where, "candidate must be a real yyyymmdd integer or null")
    ref = _decision_ref(o.get("decision_ref"), where, decisions)
    if state == "approved":
        if not _is_date(date):
            _fail(where, "an approved fact needs a real yyyymmdd date")
        if ref is None:
            _fail(where, "an approved fact needs a decision_ref")
    elif date is not None:
        _fail(where, "date may be set only when state is approved (put the quoted date in candidate)")
    return Fact(state, date, kind, cand, _evidence(o.get("evidence", []), where + ".evidence"), ref)


def _read(source: Any) -> bytes:
    if isinstance(source, (bytes, bytearray)):
        return bytes(source)
    if isinstance(source, (str, os.PathLike)):
        try:
            with open(source, "rb") as fh:
                return fh.read()
        except OSError as exc:
            raise LedgerError(f"cannot read ledger: {exc}") from None
    raise LedgerError("source must be bytes or a path")


def _no_dupes(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise LedgerError(f"duplicate JSON key {k!r}")
        out[k] = v
    return out


def load_ledger(source: Any, *, allow_fixture: bool = False) -> Ledger:
    """Parse a ledger from bytes or a path. Raises LedgerError on anything malformed. Sets ``.sha256`` over the raw bytes.

    A ledger with ``"fixture": true`` is refused unless the keyword ``allow_fixture`` is exactly True (I10). The server
    path (roadmap Step 6) calls this without the keyword, so no synthetic ledger can load there."""
    raw = _read(source)
    try:
        obj = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_dupes)
    except (UnicodeDecodeError, ValueError) as exc:
        raise LedgerError(f"not valid JSON: {exc}") from None
    if not isinstance(obj, dict):
        _fail("ledger", "top level must be an object")
    fixture = obj.get("fixture", False)
    if not isinstance(fixture, bool):
        _fail("ledger.fixture", "must be true or false")
    if fixture and allow_fixture is not True:
        _fail("ledger", "fixture ledger refused: synthetic data can only be loaded by tests (allow_fixture=True)")
    return _build(obj, hashlib.sha256(raw).hexdigest(), fixture)


def _build(obj: dict, sha: str, fixture: bool) -> Ledger:
    top = _strict(obj, "ledger", required=("schema_version",),
                  optional=("fixture", "note", "interval_rule", "freshness_window", "instruments", "provisions",
                            "versions", "operations", "coverage", "decisions"))
    sv = top["schema_version"]
    if isinstance(sv, bool) or sv != SCHEMA_VERSION:
        _fail("ledger.schema_version", f"must be {SCHEMA_VERSION}")

    decisions: dict = {}
    for i, d in enumerate(_list(top.get("decisions", []), "decisions")):
        w = f"decisions[{i}]"
        if not isinstance(d, dict):
            _fail(w, "must be an object")
        did = d.get("decision_id")
        if not isinstance(did, str) or not _DECISION_RE.match(did):
            _fail(w, "decision_id must look like LD-nnn")
        if did in decisions:
            _fail(w, f"duplicate decision {did}")
        if d.get("status") not in DECISION_STATUSES:
            _fail(w, f"status must be one of {DECISION_STATUSES}")
        reviewer = d.get("reviewer")
        rname = reviewer.get("name") if isinstance(reviewer, dict) else reviewer
        decisions[did] = Decision(did, d["status"], str(d.get("subject", "")), d.get("prepared_by"),
                                  rname if isinstance(rname, str) else None, d.get("replaces"))

    instruments = []
    seen_i = set()
    for i, o in enumerate(_list(top.get("instruments", []), "instruments")):
        w = f"instruments[{i}]"
        o = _strict(o, w, required=("key", "kind", "jurisdiction"), optional=("manifest_ids", "label"))
        m = _INSTRUMENT_RE.match(o["key"]) if isinstance(o["key"], str) else None
        if not m:
            _fail(w, "key must look like <JURIS>:<KIND>:<number>/<year>, e.g. TG:ACT:5/1963")
        if o["jurisdiction"] != m.group(1) or o["kind"] != m.group(2):
            _fail(w, "jurisdiction and kind must match the key prefix")
        if o["key"] in seen_i:
            _fail(w, f"duplicate instrument {o['key']}")
        seen_i.add(o["key"])
        mids = _list(o.get("manifest_ids", []), w + ".manifest_ids")
        for x in mids:
            _str(x, w + ".manifest_ids")
        instruments.append(Instrument(o["key"], o["kind"], o["jurisdiction"], tuple(mids)))

    def prov_instrument(key: Any, where: str) -> str:
        if not isinstance(key, str) or "#" not in key:
            _fail(where, "provision key must look like <instrument>#<path>")
        ins, path = key.split("#", 1)
        if ins not in seen_i:
            _fail(where, f"instrument {ins} is not declared")
        if not _PATH_RE.match(path):
            _fail(where, "bad provision path")
        return ins

    prov_raw = _list(top.get("provisions", []), "provisions")
    prov_keys = set()
    for i, p in enumerate(prov_raw):
        w = f"provisions[{i}]"
        p = _strict(p, w, required=("key",), optional=("parent", "label"))
        prov_instrument(p["key"], w)
        if p["key"] in prov_keys:
            _fail(w, f"duplicate provision {p['key']}")
        prov_keys.add(p["key"])
    provisions = []
    for i, p in enumerate(prov_raw):
        w = f"provisions[{i}]"
        parent = p.get("parent")
        if parent is not None:
            if parent not in prov_keys:
                _fail(w, f"parent {parent} is not a declared provision")
            if prov_instrument(parent, w) != prov_instrument(p["key"], w):
                _fail(w, "parent must belong to the same instrument")
        provisions.append(Provision(p["key"], parent, str(p.get("label", ""))))
    parents = {p.key: p.parent for p in provisions}
    for k in parents:  # no cycles
        seen, cur = set(), k
        while cur is not None:
            if cur in seen:
                _fail("provisions", f"parent cycle at {k}")
            seen.add(cur)
            cur = parents[cur]

    operations = []
    op_ids = set()
    for i, o in enumerate(_list(top.get("operations", []), "operations")):
        w = f"operations[{i}]"
        o = _strict(o, w, required=("id", "type", "source", "targets"),
                    optional=("locator", "effective_from", "scope_note", "decision_ref"))
        if not isinstance(o["id"], str) or not _OP_RE.match(o["id"]):
            _fail(w, "id must look like OP-...")
        if o["id"] in op_ids:
            _fail(w, f"duplicate operation {o['id']}")
        op_ids.add(o["id"])
        if o["type"] not in OP_TYPES:
            _fail(w, f"type must be one of {OP_TYPES}")
        if o["source"] not in seen_i:
            _fail(w, f"source {o['source']} is not a declared instrument")
        targets = _list(o["targets"], w + ".targets")
        if not targets:
            _fail(w, "needs at least one target")
        for t in targets:
            if t not in prov_keys:
                _fail(w, f"target {t} is not a declared provision")
        ef = o.get("effective_from")
        operations.append(Operation(
            o["id"], o["type"], o["source"], _str(o.get("locator"), w + ".locator", none_ok=True), tuple(targets),
            _fact(ef, w + ".effective_from", decisions) if ef is not None else None,
            _str(o.get("scope_note"), w + ".scope_note", none_ok=True),
            _decision_ref(o.get("decision_ref"), w, decisions)))
    op_by_id = {o.id: o for o in operations}

    versions = []
    vkeys = set()
    for i, v in enumerate(_list(top.get("versions", []), "versions")):
        w = f"versions[{i}]"
        v = _strict(v, w, required=("key", "provision", "text", "end"),
                    optional=("text_locators", "created_by_op", "closed_by_op", "start"))
        if v["provision"] not in prov_keys:
            _fail(w, f"provision {v['provision']} is not declared")
        if not isinstance(v["key"], str) or not re.match(r"^.+@\d+$", v["key"]) or v["key"].rsplit("@", 1)[0] != v["provision"]:
            _fail(w, "key must be <provision>@<n>")
        if v["key"] in vkeys:
            _fail(w, f"duplicate version {v['key']}")
        vkeys.add(v["key"])
        if v["text"] not in ("held", "not_held"):
            _fail(w, "text must be 'held' or 'not_held'")
        locs = tuple(_evidence(v.get("text_locators", []), w + ".text_locators"))
        cop, clo = v.get("created_by_op"), v.get("closed_by_op")
        for ref, kinds, nm in ((cop, CREATING_OPS, "created_by_op"), (clo, CLOSING_OPS, "closed_by_op")):
            if ref is not None:
                if ref not in op_by_id:
                    _fail(w, f"{nm} {ref} is not a declared operation")
                if op_by_id[ref].type not in kinds:
                    _fail(w, f"{nm} must be an operation of type {kinds}")
        if cop is not None and v.get("start") is not None:
            _fail(w, "start is derived from created_by_op; give one or the other")
        start = op_by_id[cop].effective_from if cop is not None else (
            _fact(v["start"], w + ".start", decisions) if v.get("start") is not None else None)
        e = _strict(v["end"], w + ".end", required=("state",), optional=("checked_through", "decision_ref"))
        es = e["state"]
        if es not in END_STATES:
            _fail(w, f"end.state must be one of {END_STATES}")
        if (es == "closed") != (clo is not None):
            _fail(w, "end.state 'closed' requires closed_by_op, and closed_by_op requires end.state 'closed'")
        ct = e.get("checked_through")
        dref = _decision_ref(e.get("decision_ref"), w + ".end", decisions)
        if es == "continuing_verified":
            if not _is_date(ct) or dref is None:
                _fail(w, "continuing_verified needs a real checked_through date and a decision_ref")
        elif ct is not None or dref is not None:
            _fail(w, "checked_through/decision_ref belong to continuing_verified only")
        versions.append(Version(v["key"], v["provision"], v["text"] == "held", locs, cop, clo,
                                Interval(start, es, op_by_id[clo].effective_from if clo else None, ct, dref)))

    coverage = []
    seen_sel = set()
    for i, c in enumerate(_list(top.get("coverage", []), "coverage")):
        w = f"coverage[{i}]"
        c = _strict(c, w, required=("selector", "provisions"), optional=("decision_ref",))
        sel = _strict(c["selector"], w + ".selector", required=SELECTOR_KEYS)
        for k in ("manifest_id", "provision_id"):
            _str(sel[k], f"{w}.selector.{k}")
        for k in ("sha256", "text_sha256"):
            if not isinstance(sel[k], str) or not _HEX64_RE.match(sel[k]):
                _fail(f"{w}.selector.{k}", "must be 64 lowercase hex characters")
        for k in ("part", "parts", "page_start", "page_end"):
            if isinstance(sel[k], bool) or not isinstance(sel[k], int):
                _fail(f"{w}.selector.{k}", "must be an integer")
        # The whole selector identifies an entry (pages and text hash included, as the matcher compares them). Two chunks that share
        # a provision label but differ in pages or text (the two "SCHEDULE" chunks of G.O. 53) are therefore distinct entries; an
        # entry identical in every field is still a duplicate.
        ident = tuple(sel[k] for k in SELECTOR_KEYS)
        if ident in seen_sel:
            _fail(w, "duplicate coverage selector")
        seen_sel.add(ident)
        provs = _list(c["provisions"], w + ".provisions")
        if not provs:
            _fail(w, "needs at least one provision")
        for p in provs:
            if p not in prov_keys:
                _fail(w, f"provision {p} is not declared")
        coverage.append(Coverage(dict(sel), tuple(dict.fromkeys(provs)), _decision_ref(c.get("decision_ref"), w, decisions)))

    rule = top.get("interval_rule")
    rule_ref = None
    if rule is not None:
        rule = _strict(rule, "interval_rule", required=("rule", "decision_ref"))
        if rule["rule"] != INTERVAL_RULE:
            _fail("interval_rule", f"only {INTERVAL_RULE!r} is supported")
        rule_ref = _decision_ref(rule["decision_ref"], "interval_rule", decisions, none_ok=False)
    fw = top.get("freshness_window")
    fdays = fref = None
    if fw is not None:
        fw = _strict(fw, "freshness_window", required=("days", "decision_ref"))
        if isinstance(fw["days"], bool) or not isinstance(fw["days"], int) or fw["days"] < 0:
            _fail("freshness_window.days", "must be a non-negative integer")
        fdays = fw["days"]
        fref = _decision_ref(fw["decision_ref"], "freshness_window", decisions, none_ok=False)

    return Ledger(sha, fixture, tuple(instruments), tuple(provisions), tuple(versions), tuple(operations),
                  tuple(coverage), tuple(decisions.values()), rule_ref, fdays, fref)


# ------------------------------------------------------------------------------------------------ trust

def _trusted(ledger: Ledger, bound: Any) -> bool:
    """Facts count only when the caller proves the ledger is bound (exactly True) and it is not a fixture (I4, I10)."""
    return bound is True and not ledger.fixture


def _approved(ledger: Ledger, ref: Optional[str], trusted: bool) -> bool:
    d = ledger._dec.get(ref) if ref else None
    return bool(trusted and d is not None and d.status == "approved")


def _fact_date(ledger: Ledger, fact: Optional[Fact], trusted: bool) -> Optional[int]:
    """The ONLY place a fact's date is read. `candidate` is never consulted."""
    if fact is None or not trusted:
        return None
    if fact.state != "approved" or fact.kind != VALIDITY_KIND or fact.date is None:
        return None
    return fact.date if _approved(ledger, fact.decision_ref, trusted) else None


def _resolve_interval(ledger: Ledger, v: Version, trusted: bool) -> tuple:
    """(start|None, end_state, end|None, checked_through|None) using approved facts only. Anything else is unknown."""
    iv = v.interval
    start = _fact_date(ledger, iv.start, trusted)
    if iv.end_state == "closed":
        d = _fact_date(ledger, iv.end, trusted)
        if d is not None and _approved(ledger, ledger.interval_rule, trusted):  # A11: derived ends need the approved rule
            last = _prev_day(d)
            if last is not None:
                return (start, "closed", last, None)
    elif iv.end_state == "continuing_verified" and _approved(ledger, iv.decision_ref, trusted):
        return (start, "continuing_verified", None, iv.checked_through)
    return (start, "unverified", None, None)


def _fresh(ledger: Ledger, checked_through: int, today: int, trusted: bool) -> bool:
    """No freshness window approved means nothing is fresh."""
    if ledger.freshness_days is None or not _approved(ledger, ledger.freshness_ref, trusted):
        return False
    return 0 <= _ord(today) - _ord(checked_through) <= ledger.freshness_days


# ------------------------------------------------------------------------------------------------ provision relations

def _ancestors(ledger: Ledger, key: str) -> list:
    out, cur = [], ledger._prov[key].parent
    while cur is not None:
        out.append(cur)
        cur = ledger._prov[cur].parent
    return out


def _related(ledger: Ledger, a: str, b: str) -> bool:
    return a == b or a in _ancestors(ledger, b) or b in _ancestors(ledger, a)


def _closure_issues(ledger: Ledger, trusted: bool) -> dict:
    """Inconsistent closure links, as {provision: {op_id: "unlinked" | "wrong_link"}} (review finding M1).

    A version ends only through ``closed_by_op``. Two ways that link can be wrong, both of which would otherwise leave
    text described as in force (or closed on the wrong date) while the ledger holds an approved closing operation:

    * unlinked   : an approved closing operation targets provision P (or an ancestor of P) while a version of P that is
                   neither created nor closed by it is still open at its date. "Still open" means: no closing link at all,
                   or a link to an operation that takes effect later. A link to an unapproved or earlier operation is not
                   flagged here (the unapproved operation already restricts the provision as pending).
    * wrong_link : a version's ``closed_by_op`` names an operation that does not target that version's provision or an
                   ancestor of it. This is structural and does not depend on approval.
    """
    out: dict = {}
    for prov, versions in ledger._ver.items():
        scope = [prov] + _ancestors(ledger, prov)
        for v in versions:
            clo = v.closed_by_op
            if clo is not None and not any(t in scope for t in ledger._op[clo].targets):
                out.setdefault(prov, {})[clo] = "wrong_link"
    for op in ledger.operations:
        if op.type not in CLOSING_OPS:
            continue
        d = _fact_date(ledger, op.effective_from, trusted)
        if d is None:
            continue
        for prov, versions in ledger._ver.items():
            if not any(t in ([prov] + _ancestors(ledger, prov)) for t in op.targets):
                continue
            for v in versions:
                if v.created_by_op == op.id or v.closed_by_op == op.id:
                    continue
                start = _fact_date(ledger, v.interval.start, trusted)
                if start is not None and start >= d:
                    continue                      # not yet in force when this operation takes effect
                if v.closed_by_op is not None:
                    dx = _fact_date(ledger, ledger._op[v.closed_by_op].effective_from, trusted)
                    if dx is None or dx <= d:
                        continue                  # already closed by an operation that is earlier or still unapproved
                out.setdefault(prov, {}).setdefault(op.id, "unlinked")
    return out


# ------------------------------------------------------------------------------------------------ validation

def validate(ledger: Ledger) -> list:
    """Static checks C1 to C5, C8, structural S1/S2, and informational C11. Judged on the ledger's own approved facts
    (as if bound). Does not raise; an `error` means the ledger must not be used."""
    probs: list = []
    P = probs.append
    trusted = True
    ins_by_key = {i.key: i for i in ledger.instruments}

    # C8: same-number instruments stay apart; nothing crosses jurisdictions.
    owners: dict = {}
    for i in ledger.instruments:
        for m in i.manifest_ids:
            owners.setdefault(m, set()).add(i.key)
    for m, ks in sorted(owners.items()):
        if len(ks) > 1:
            P(Problem("C8", "error", m, f"manifest id {m} is mapped to several instruments {sorted(ks)}"))
    for op in ledger.operations:
        sj = ins_by_key[op.source].jurisdiction
        for t in op.targets:
            tj = ins_by_key[t.split("#", 1)[0]].jurisdiction
            if sj != tj:
                P(Problem("C8", "error", op.id, f"operation from a {sj} instrument targets a {tj} provision {t}"))
    for c in ledger.coverage:
        mid = c.selector["manifest_id"]
        if mid not in owners:
            P(Problem("S2", "warning", mid, "coverage names a manifest id no instrument declares"))
            continue
        js = {ins_by_key[k].jurisdiction for k in owners[mid]}
        for p in c.provisions:
            pj = ins_by_key[p.split("#", 1)[0]].jurisdiction
            if pj not in js:
                P(Problem("C8", "error", mid, f"coverage of {mid} ({sorted(js)}) maps to a {pj} provision {p}"))

    # Intervals, C1 overlap, C2 gap, S1 inversion.
    for prov, vs in ledger._ver.items():
        res = [(v, _resolve_interval(ledger, v, trusted)) for v in vs]
        for v, (s, es, e, ct) in res:
            if s is not None and e is not None and s > e:
                P(Problem("S1", "error", v.key, "approved start is after the derived last day"))
        known = [(v, r) for v, r in res if r[0] is not None]
        for a in range(len(known)):
            for b in range(a + 1, len(known)):
                (va, ra), (vb, rb) = known[a], known[b]
                ea = ra[2] if ra[1] == "closed" else 99999999   # unverified or continuing end counts as open-ended
                eb = rb[2] if rb[1] == "closed" else 99999999
                if max(ra[0], rb[0]) <= min(ea, eb):
                    soft = "unverified" in (ra[1], rb[1])
                    P(Problem("C1", "warning" if soft else "error", prov,
                              f"versions {va.key} and {vb.key} both cover a date" + (" (an end is unverified)" if soft else "")))
        ordered = sorted(known, key=lambda x: x[1][0])
        for (va, ra), (vb, rb) in zip(ordered, ordered[1:]):
            if ra[1] == "closed" and rb[0] > ra[2] and _ord(rb[0]) - _ord(ra[2]) > 1:
                P(Problem("C2", "warning", prov, f"gap between {va.key} and {vb.key}"))

    # C3 orphan, C4 same-day ordering, C5 target absent from coverage.
    covered = {p for c in ledger.coverage for p in c.provisions}
    groups: dict = {}
    for op in ledger.operations:
        if op.type in CLOSING_OPS:
            for t in op.targets:
                if not ledger._ver.get(t):
                    P(Problem("C3", "warning", op.id, f"{op.type} target {t} has no version (predecessor missing)"))
                d = _fact_date(ledger, op.effective_from, trusted)
                if d is not None:
                    groups.setdefault((t, d), []).append(op.id)
        if op.type != "commence":
            for t in op.targets:
                if not any(_related(ledger, t, p) for p in covered):
                    P(Problem("C5", "warning", op.id, f"target {t} is absent from every coverage record"))
    for (t, d), ids in sorted(groups.items()):
        if len(ids) > 1:
            P(Problem("C4", "warning", t, f"operations {sorted(ids)} take effect on the same day {d}: ordering ambiguous"))

    # C3b (review M1): a closing operation and the versions it should close must agree.
    for prov, ops in sorted(_closure_issues(ledger, trusted).items()):
        for op_id, kind in sorted(ops.items()):
            msg = (f"approved closing operation {op_id} is not linked (closed_by_op) to the open version of {prov}"
                   if kind == "unlinked" else
                   f"a version of {prov} is closed by {op_id}, which does not target it")
            P(Problem("C3b", "error", prov, msg))

    # C11: candidates present without approval (informational; never read).
    for op in ledger.operations:
        f = op.effective_from
        if f is not None and f.candidate is not None and _fact_date(ledger, f, trusted) is None:
            P(Problem("C11", "info", op.id, "candidate date recorded without approval; never read"))
    return probs


# ------------------------------------------------------------------------------------------------ resolution

@dataclass(frozen=True)
class _PE:
    cls: str
    reasons: tuple
    sig: tuple


def _ordering_ambiguous(ledger: Ledger, trusted: bool) -> set:
    groups: dict = {}
    for op in ledger.operations:
        if op.type in CLOSING_OPS:
            d = _fact_date(ledger, op.effective_from, trusted)
            if d is not None:
                for t in op.targets:
                    groups.setdefault((t, d), set()).add(op.id)
    return {t for (t, _), ids in groups.items() if len(ids) > 1}


def _eval_provision(ledger: Ledger, prov: str, qd: Optional[int], today: int, trusted: bool, ambiguous: set,
                    closures: dict) -> _PE:
    point = today if qd is None else qd
    versions = ledger._ver.get(prov, ())
    resolved = [(v, _resolve_interval(ledger, v, trusted)) for v in versions]
    matching, unk, before, after = [], [], 0, 0
    for v, (s, es, e, ct) in resolved:
        n_unk = len(unk)
        if es == "closed" and point > e:
            after += 1
            continue
        if s is not None and point < s:
            before += 1
            continue
        if s is None:
            unk.append("start_unknown")
        elif es == "closed":
            if qd is None:
                unk.append("closed_not_current")      # I6: a closed version never answers an undated question
            else:
                matching.append((v, HISTORICAL))
        elif es == "continuing_verified":
            if qd is None:
                (matching.append((v, AUTHORITATIVE)) if _fresh(ledger, ct, today, trusted) else unk.append("not_fresh"))
            else:
                (matching.append((v, AUTHORITATIVE)) if qd <= ct else unk.append("beyond_checked_through"))
        else:
            unk.append("end_unverified")
        if matching and matching[-1][0] is v and not v.text_held:
            matching.pop()                              # no text held: never serve it
            unk.append("text_not_held")
        elif len(unk) > n_unk and not v.text_held:
            unk.append("text_not_held")
    reasons = list(dict.fromkeys(unk))
    if len(matching) > 1:
        cls, reasons = UNVERIFIED, reasons + ["overlap"]
    elif len(matching) == 1 and not unk:
        cls = matching[0][1]
    elif matching:
        cls, reasons = UNVERIFIED, reasons + ["ambiguous_versions"]
    elif unk:
        cls = UNVERIFIED
    elif not versions:
        cls, reasons = UNVERIFIED, ["no_version"]
    elif before and after:
        cls, reasons = UNVERIFIED, ["gap"]
    else:
        cls, reasons = NOT_IN_FORCE, ["before_start" if before else "after_end"]
    # Unapproved or unbound closing operations can only restrict: the provision may be changing, so it is never better
    # than UNVERIFIED. They are never read for a date.
    pending = [o.id for o in ledger.operations if o.type in CLOSING_OPS
               and any(_related(ledger, t, prov) for t in o.targets) and _fact_date(ledger, o.effective_from, trusted) is None]
    if pending:
        reasons.append("pending_operation")
        if _RANK[cls] > _RANK[UNVERIFIED]:
            cls = UNVERIFIED
    if prov in closures:                                 # M1: closure links disagree with the operations, for any date
        reasons.append("closure_unlinked")
        if _RANK[cls] > _RANK[UNVERIFIED]:
            cls = UNVERIFIED
    if any(_related(ledger, t, prov) for t in ambiguous):
        reasons.append("ordering_ambiguity")
        if _RANK[cls] > _RANK[UNVERIFIED]:
            cls = UNVERIFIED
    # Provisions share one interval only if class, resolved intervals, pending operations and ambiguity all agree.
    sig = (cls, tuple(sorted(((r[0] or 0), r[1], (r[2] or 0), (r[3] or 0)) for _, r in resolved)),
           tuple(sorted(pending)), any(_related(ledger, t, prov) for t in ambiguous))
    return _PE(cls, tuple(dict.fromkeys(reasons)), sig)


def _match_coverage(ledger: Ledger, md: Mapping, text: str):
    """("none"|"stale"|"match", [Coverage]). Same manifest_id + provision_id but any other difference is stale."""
    mid, pid = md.get("manifest_id"), md.get("provision_id")
    same = [c for c in ledger.coverage if c.selector["manifest_id"] == mid and c.selector["provision_id"] == pid]
    if not same:
        return "none", []
    th = text_digest(text)

    def eq(a, b):
        return type(a) is type(b) and a == b

    exact = [c for c in same if all(eq(c.selector[k], md.get(k)) for k in
                                    ("sha256", "part", "parts", "page_start", "page_end")) and c.selector["text_sha256"] == th]
    return ("match", exact) if exact else ("stale", [])


def _opinion(ledger: Ledger, md: Mapping, text: str, qd: Optional[int], today: int, trusted: bool) -> Verdict:
    status, recs = _match_coverage(ledger, md, text)
    if status == "none":
        return Verdict(UNVERIFIED, ("no_coverage",), (), False, False, None)
    if status == "stale":
        return Verdict(UNVERIFIED, ("stale_coverage",), (), True, False, UNVERIFIED)
    provs = tuple(dict.fromkeys(p for c in recs for p in c.provisions))
    ambiguous = _ordering_ambiguous(ledger, trusted)
    closures = _closure_issues(ledger, trusted)
    pes = [_eval_provision(ledger, p, qd, today, trusted, ambiguous, closures) for p in provs]
    reasons = list(dict.fromkeys(r for pe in pes for r in pe.reasons))
    partial = len({pe.sig for pe in pes}) > 1
    if partial:                                         # I5: never authoritative, blocked for current law
        if all(pe.cls == NOT_IN_FORCE for pe in pes):
            cls = NOT_IN_FORCE
        else:
            cls = UNVERIFIED if qd is not None else BLOCKED
        reasons.append("partial")
    else:
        cls = pes[0].cls
    if not all(_approved(ledger, c.decision_ref, trusted) for c in recs):
        reasons.append("coverage_unapproved")
        if _RANK[cls] > _RANK[UNVERIFIED]:
            cls = UNVERIFIED
    return Verdict(cls, tuple(dict.fromkeys(reasons)), provs, True, partial, cls)


def normalize_mode(mode: Any) -> str:
    """Anything that is not exactly off/shadow/restrict (including 'enforce') is 'off'."""
    if isinstance(mode, str) and mode.strip().lower() in MODES:
        return mode.strip().lower()
    return "off"


def resolve_chunk(ledger: Optional[Ledger], metadata: Mapping, text: str, query_date: Optional[int], today: int,
                  mode: str, *, bound: bool = False) -> Verdict:
    """What the ledger may say about one chunk. Fails closed; never raises on bad query input.

    mode off     : the ledger is not read; covered=False (legacy applies unchanged).
    shadow/restrict: the class is capped so the ledger can restrict but never create authority (I3). `opinion` shows
                   what full trust would say, for logging only.
    bound        : True only when the caller has verified that a valid signed approval binds this ledger (Step 2). Anything
                   but the object True is treated as unbound, and then no fact is trusted (I4)."""
    m = normalize_mode(mode)
    if m == "off":
        return Verdict(UNVERIFIED, ("mode_off",), (), False, False, None)
    if not isinstance(ledger, Ledger):
        return Verdict(UNVERIFIED, ("no_ledger",), (), False, False, None)
    if not _is_date(today) or (query_date is not None and not _is_date(query_date)):
        return Verdict(BLOCKED, ("bad_date_input",), (), True, False, None)
    if not isinstance(metadata, Mapping) or not isinstance(text, str):
        return Verdict(BLOCKED, ("bad_chunk_input",), (), True, False, None)
    op = _opinion(ledger, metadata, text, query_date, today, _trusted(ledger, bound))
    cls, reasons = op.cls, op.reasons
    if cls in (AUTHORITATIVE, HISTORICAL):               # I3: the ledger cannot create authority
        cls, reasons = UNVERIFIED, reasons + ("ledger_cannot_create_authority",)
    return Verdict(cls, reasons, op.provisions, op.covered, op.partial, op.opinion)


def combine(legacy_cls: str, verdict: Verdict) -> str:
    """Merge the legacy class with a ledger verdict: never better than the legacy class (I3). An uncovered chunk keeps its
    legacy class. An unknown legacy class fails closed."""
    if legacy_cls not in _RANK:
        return BLOCKED
    if not isinstance(verdict, Verdict) or not verdict.covered:
        return legacy_cls
    if verdict.cls not in _RANK:
        return BLOCKED
    if verdict.cls in (AUTHORITATIVE, HISTORICAL):      # a positive verdict neither promotes nor demotes
        return legacy_cls
    return verdict.cls if _RANK[verdict.cls] < _RANK[legacy_cls] else legacy_cls
