"""Answer cache for the grounded pipeline (Stage 5): data structure, query normalisation, the "same legal situation"
signature and the settings. No server, provider or vector-store imports: server.py wires it in.

What is cached is the model's VALIDATED raw output (one JSON string) for a question, nothing else. A hit never
returns stored text. It REPLAYS that output through the unchanged pipeline (live context documents, build_contract,
validate with the penalty gate and the Stage 4F/4G masks, render, live source warnings), so a hit is exactly as
validated as a fresh answer, and an answer whose sources changed is rejected by the same code that rejected it.

Layers (TG_CACHE):
  off       nothing is looked up or stored (default).
  exact     key = the normalised question. A hit skips embedding, retrieval and generation.
  semantic  exact first; otherwise a candidate needs ALL of: cosine similarity >= threshold; an identical
            "legal situation" signature (vehicle class, applicant category, place, numbers, dates, negation or modality,
            procedure, money); the question not being fee- or time-sensitive; and a FRESH retrieval returning exactly
            the context the cached answer was generated from. A hit skips generation only.
Anything else is a miss: fresh retrieval and generation. TG_CACHE_DISABLED=1 turns every layer off, whatever TG_CACHE says.

Entries carry an epoch (a digest of every input that decides what an answer may say: approval, source versions,
registry, index, embedding model, chunking, retrieval settings, validator code) and the identities of the chunks they
were built from. A different epoch, a missing or changed chunk, or an expired entry is a miss and the entry is dropped.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
import unicodedata
from collections import Counter, OrderedDict
from dataclasses import dataclass, field

import numpy as np

MODES = ("off", "exact", "semantic")
DEFAULT_TTL_SECONDS = 6 * 3600
DEFAULT_MAX_ENTRIES = 256
DEFAULT_SIMILARITY = 0.95
MIN_SIMILARITY = 0.80          # a configured threshold below this is ignored: it would be a guess, not a match
DEFAULT_VERIFY_SECONDS = 30.0
MAX_QUESTION_CHARS = 400
MAX_RAW_CHARS = 20000
TRUE = ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    mode: str = "off"
    ttl_seconds: float = DEFAULT_TTL_SECONDS
    max_entries: int = DEFAULT_MAX_ENTRIES
    similarity: float = DEFAULT_SIMILARITY
    verify_seconds: float = DEFAULT_VERIFY_SECONDS

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    @property
    def semantic(self) -> bool:
        return self.mode == "semantic"


def _number(value, default, lo, hi=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number) or number < lo or (hi is not None and number > hi):
        return default
    return number


def settings_from_env(environ=None) -> Settings:
    """TG_CACHE (off|exact|semantic, default off), TG_CACHE_DISABLED (kill switch), TG_CACHE_TTL_SECONDS,
    TG_CACHE_MAX_ENTRIES, TG_CACHE_SIMILARITY (0.80-1.0), TG_CACHE_VERIFY_SECONDS. Unknown values fall back to the
    safe default (an unknown mode is "off")."""
    env = os.environ if environ is None else environ
    mode = (env.get("TG_CACHE") or "off").strip().lower()
    if mode not in MODES or (env.get("TG_CACHE_DISABLED") or "").strip().lower() in TRUE:
        mode = "off"
    return Settings(
        mode=mode,
        ttl_seconds=_number(env.get("TG_CACHE_TTL_SECONDS"), DEFAULT_TTL_SECONDS, 1),
        max_entries=int(_number(env.get("TG_CACHE_MAX_ENTRIES"), DEFAULT_MAX_ENTRIES, 1, 100000)),
        similarity=_number(env.get("TG_CACHE_SIMILARITY"), DEFAULT_SIMILARITY, MIN_SIMILARITY, 1.0),
        verify_seconds=_number(env.get("TG_CACHE_VERIFY_SECONDS"), DEFAULT_VERIFY_SECONDS, 0))


# --------------------------------------------------------------------------------------------------------------------
# Normalisation: only changes that cannot change the legal question (case, spacing, quote style, final punctuation).
# Words are never dropped or reordered, so "not", numbers and names always survive.
# --------------------------------------------------------------------------------------------------------------------
def normalize_query(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = re.sub(r"\s+", " ", t).strip().casefold()
    return t.rstrip(" ?!.,;:")


# --------------------------------------------------------------------------------------------------------------------
# Cacheability: questions that carry personal identifiers are never stored, so nothing personal can be cached.
# --------------------------------------------------------------------------------------------------------------------
_EMAIL = re.compile(r"\S+@\S+\.\S+")
_LONG_DIGITS = re.compile(r"(?:\d[\s-]?){7,}")
_REGISTRATION = re.compile(r"\b[a-z]{2}[\s-]?\d{1,2}[\s-]?[a-z]{1,3}[\s-]?\d{3,4}\b", re.I)


def uncacheable_reason(question: str) -> str | None:
    q = question or ""
    if not q.strip():
        return "empty"
    if len(q) > MAX_QUESTION_CHARS:
        return "too_long"
    if _EMAIL.search(q) or _LONG_DIGITS.search(q):
        return "personal_identifier"
    if _REGISTRATION.search(q):
        return "vehicle_registration"
    return None


# --------------------------------------------------------------------------------------------------------------------
# The "legal situation" signature. A semantic hit requires the signatures to be EQUAL. It is deliberately a wide net
# built from word lists: a question that differs in any listed word, number or capitalised name is a different
# situation and a miss. Synonyms are NOT merged ("bike" and "motorcycle" differ), so the cache errs towards fresh
# answers. The embedding similarity is only a pre-filter; it cannot tell "two-wheeler" from "four-wheeler".
# --------------------------------------------------------------------------------------------------------------------
_PHRASES = [
    (r"\b(?:two|2)[\s-]*wheel(?:er|ers|ed)?\b", "twowheeler"),
    (r"\b(?:three|3)[\s-]*wheel(?:er|ers|ed)?\b", "threewheeler"),
    (r"\b(?:four|4)[\s-]*wheel(?:er|ers|ed)?\b", "fourwheeler"),
    (r"\bmotor[\s-]*cycles?\b", "motorcycle"),
    (r"\bmotor[\s-]*cabs?\b", "motorcab"),
    (r"\bmaxi[\s-]*cabs?\b", "maxicab"),
    (r"\b(?:auto[\s-]*rickshaws?|autos?)\b", "autorickshaw"),
    (r"\be[\s-]*rickshaws?\b", "erickshaw"),
    (r"\blight motor vehicles?\b", "lmv"),
    (r"\bheavy motor vehicles?\b", "hmv"),
    (r"\bmedium (?:goods|passenger) (?:motor )?vehicles?\b", "mgv"),
    (r"\bheavy (?:goods|passenger) (?:motor )?vehicles?\b", "hgv"),
    (r"\btransport vehicles?\b", "transportvehicle"),
    (r"\bnon[\s-]*transport\b", "nontransport"),
    (r"\bsecond[\s-]*hand\b", "secondhand"),
    (r"\blicen[cs]es?\b", "licence"),
    (r"\bw/o\b", "without"),
    (r"\bcan't\b|\bcannot\b|\bcan not\b", "cannot"),
    (r"\bdon't\b|\bdo not\b", "not"),
    (r"\b(?:isn't|aren't|wasn't|weren't|won't|doesn't|didn't|shouldn't|mustn't|needn't)\b", "not"),
]
_PHRASES = [(re.compile(p, re.I), r) for p, r in _PHRASES]

_NUMBER_WORDS = {w: str(n) for n, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen "
    "eighteen nineteen twenty".split())}
_NUMBER_WORDS.update({"thirty": "30", "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70", "eighty": "80",
                      "ninety": "90", "hundred": "100", "thousand": "1000", "lakh": "100000", "crore": "10000000",
                      "half": "0.5", "double": "2", "twice": "2", "single": "1", "once": "1"})

_LEXICON = {
    "veh": """twowheeler threewheeler fourwheeler motorcycle bike scooter scooty moped car jeep van bus minibus truck lorry
        tractor trailer autorickshaw erickshaw rickshaw taxi cab motorcab maxicab ambulance tanker tipper lmv hmv hgv mgv
        hpv mcwg mcwog goods passenger carriage stage transportvehicle nontransport commercial private public heavy light
        medium cycle bicycle cyclist electric battery ev hybrid imported secondhand school tourist vehicle""".split(),
    "who": """learner minor child children adult senior citizen woman women man men girl boy student disabled handicapped
        physically foreigner foreign nri tourist owner driver conductor rider pillion passenger pedestrian applicant
        holder employee employer agent dealer manufacturer police officer inspector examiner authority resident
        non-resident""".split(),
    "proc": """apply application renew renewal transfer surrender duplicate lost replace replacement change address
        upgrade endorse endorsement cancel revoke suspend register registration fitness permit licence badge certificate
        insurance puc pollution test examination exam age expire expiry expired validity valid period badge show
        production produce carry display plate number xerox copy original digital""".split(),
    "mod": """not no never without cannot must may shall should need needs require required requirement mandatory
        compulsory optional allowed allow permitted permit prohibited prohibit ban banned exempt exempted exemption
        except unless only also any all every each both either neither if when whether whom whose""".split(),
    "time": """before after since until till from during within date year month day week hour old older new newer latest
        current currently now today yesterday tomorrow previous earlier recent recently amended amendment amend repeal
        repealed omitted substituted effective january february march april may june july august september october
        november december deadline""".split(),
    "cmp": "more less than above below under over minimum maximum least most between upto atleast exceed exceeding".split(),
    "money": """fee fees tax taxes charge charges cost price amount rs rupee rupees paise fare payment pay paid refund
        deposit stamp duty lakh crore""".split(),
    "loc": """hyderabad secunderabad cyberabad warangal karimnagar nizamabad khammam nalgonda adilabad medak mahbubnagar
        rangareddy sangareddy siddipet suryapet jagtial mancherial nirmal peddapalli bhadradri kothagudem mulugu
        narayanpet wanaparthy gadwal vikarabad kamareddy medchal malkajgiri jangaon bhupalpally mahabubabad
        city district town village rural urban municipal corporation highway nh ghat ghats outer ring road orr
        airport border state interstate inter-state""".split(),
    "inst": "act central cmvr tmvr tmvtr go order schedule chapter form amendment notification".split(),
}
_TIME_SENSITIVE = frozenset("today now current currently latest recent recently yesterday tomorrow deadline new newer "
                            "amended amendment amend repealed omitted substituted effective".split())
_NEUTRAL_CAPS = frozenset({"i", "telangana", "ts", "india", "indian", "tg"})


def _stem(w: str) -> str:
    w = w.replace("'", "").replace("-", "")
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith(("ses", "xes", "ches", "shes")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


_WORD_TO_KIND: dict[str, str] = {}
for _kind, _words in _LEXICON.items():
    for _w in _words:
        _WORD_TO_KIND.setdefault(_stem(_w), _kind)
_TOKEN = re.compile(r"\d+(?:[.,]\d+)*[a-z]{0,2}|[a-z]+(?:['-][a-z]+)*", re.I)


def _canonical(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").replace("’", "'")
    for pattern, repl in _PHRASES:
        t = pattern.sub(repl, t)
    return t


def signature(question: str) -> frozenset:
    """Everything in the question that can change which legal situation it describes (see the block comment above)."""
    text = _canonical(question)
    sig = set()
    first = True
    for m in _TOKEN.finditer(text):
        raw = m.group(0)
        low = raw.lower()
        if raw[0].isdigit():
            sig.add("num:" + low.replace(",", ""))
        else:
            stem = _stem(low)
            if low in _NUMBER_WORDS:
                sig.add("num:" + _NUMBER_WORDS[low])
            kind = _WORD_TO_KIND.get(stem)
            if kind:
                sig.add(f"{kind}:{stem}")
            if raw[0].isupper() and not first and low not in _NEUTRAL_CAPS and not kind:
                sig.add("cap:" + low)
        first = False
    return frozenset(sig)


def risk_flags(question: str) -> frozenset:
    """Reasons to use the exact layer only. 'money': fees, taxes, amounts. 'time': dates and 'current/latest'
    wording. Neither is ever answered from a merely similar question."""
    flags = set()
    for item in signature(question):
        kind, _, word = item.partition(":")
        if kind == "money":
            flags.add("money")
        elif kind == "time" and (word in _TIME_SENSITIVE or word in {_stem(m) for m in (
                "january february march april may june july august september october november december".split())}):
            flags.add("time")
        elif kind == "num" and re.fullmatch(r"(?:19|20)\d\d", word):
            flags.add("time")
        elif kind == "num" and re.fullmatch(r"\d{4,}", word):
            flags.add("money")  # a large bare number is an amount or a registration, never a rule reference
    return frozenset(flags)


def unit_vector(vector) -> np.ndarray | None:
    v = np.asarray(vector, dtype=np.float64)
    if v.ndim != 1 or v.size == 0 or not np.isfinite(v).all():
        return None
    n = np.linalg.norm(v)
    return (v / n).astype(np.float32) if n > 0 else None


def digest(*parts) -> str:
    """Stable short digest of JSON-able parts: used for epochs and chunk identities."""
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()[:32]


class EmbeddingMemo:
    """Memoises an embed_query function by its exact input text. Transparent: the same text always gives the same vector
    from the same model, so retrieval sees exactly what it would have computed. Bounded; thread safe."""

    def __init__(self, embed, size=512, key=""):
        self._embed, self._size, self._key = embed, size, key
        self._memo: OrderedDict = OrderedDict()
        self._lock = threading.Lock()
        self.hits = self.misses = 0
        self.compute_ms = 0.0

    def __call__(self, text):
        k = (self._key, text)
        with self._lock:
            if k in self._memo:
                self._memo.move_to_end(k)
                self.hits += 1
                return list(self._memo[k])
        t0 = time.perf_counter()
        vec = self._embed(text)
        elapsed = (time.perf_counter() - t0) * 1000
        with self._lock:
            self.misses += 1
            self.compute_ms += elapsed
            self._memo[k] = tuple(vec)
            while len(self._memo) > self._size:
                self._memo.popitem(last=False)
        return list(vec)


@dataclass
class Entry:
    key: str
    signature: frozenset
    vector: np.ndarray | None
    epoch: str
    raw: str                       # the validated model output (JSON text), replayed on a hit
    context_ids: tuple             # ordered identities of the chunks the answer was generated from
    cited_ids: tuple
    sources: tuple                 # (sha256, manifest_id) of every context document: the versions it depends on
    flags: frozenset = frozenset()
    created: float = 0.0
    expires: float = 0.0
    hits: int = 0
    size: int = field(default=0)

    def measure(self) -> int:
        self.size = (len(self.key) + len(self.raw) + sum(len(c) for c in self.context_ids)
                     + sum(len(s) + len(m or "") for s, m in self.sources)
                     + (self.vector.nbytes if self.vector is not None else 0) + 256)
        return self.size


class MemoryStore:
    """Entry container (an LRU). Replaceable, so storage failures can be exercised."""

    def __init__(self):
        self.items: OrderedDict[str, Entry] = OrderedDict()

    def get(self, key):
        return self.items.get(key)

    def touch(self, key):
        self.items.move_to_end(key)

    def put(self, key, entry):
        self.items[key] = entry
        self.items.move_to_end(key)

    def delete(self, key):
        self.items.pop(key, None)

    def values(self):
        return list(self.items.values())

    def oldest(self):
        return next(iter(self.items), None)

    def __len__(self):
        return len(self.items)


class AnswerCache:
    def __init__(self, settings: Settings, clock=time.monotonic, store=None):
        self.settings, self.clock = settings, clock
        self.store = store if store is not None else MemoryStore()
        self._lock = threading.RLock()
        self.stats = Counter()
        self._epoch = None

    # -- helpers ------------------------------------------------------------------------------------------------------
    def _guard(self, name, fn, default=None):
        """Every storage operation: an exception is a miss (or a skipped store), never an error for the caller."""
        try:
            return fn()
        except Exception:  # noqa: BLE001 - the cache must never break an answer
            self.stats["storage_errors"] += 1
            self.stats[f"storage_errors_{name}"] += 1
            return default

    def _drop(self, entry, reason):
        self._guard("delete", lambda: self.store.delete(entry.key))
        self.stats["invalidated"] += 1
        self.stats[f"invalidated_{reason}"] += 1

    def note_epoch(self, epoch):
        """Called with the current epoch: when it changes, every older entry is dead and is swept at once."""
        with self._lock:
            if epoch == self._epoch:
                return
            first = self._epoch is None
            self._epoch = epoch
            if first:
                return
            for e in self._guard("scan", lambda: self.store.values(), []):
                if e.epoch != epoch:
                    self._drop(e, "epoch")
            self.stats["epoch_changes"] += 1

    def _live(self, entry, epoch):
        if entry.epoch != epoch:
            self._drop(entry, "epoch")
            return False
        if self.clock() >= entry.expires:
            self._drop(entry, "expired")
            return False
        return True

    # -- lookups --------------------------------------------------------------------------------------------------------
    def lookup_exact(self, key, epoch) -> Entry | None:
        with self._lock:
            entry = self._guard("get", lambda: self.store.get(key))
            if entry is None or not self._live(entry, epoch):
                return None
            self._guard("touch", lambda: self.store.touch(key))
            return entry

    def lookup_semantic(self, vector, sig, epoch, context_ids) -> tuple[Entry, float] | None:
        """Best entry with equal signature, cosine >= threshold and every chunk it cites present in the FRESH
        context; None otherwise. The caller must still replay (re-validate) the entry against that fresh context."""
        v = unit_vector(vector)
        if v is None:
            return None
        best, best_sim = None, -1.0
        fresh = set(context_ids)
        with self._lock:
            for e in self._guard("scan", lambda: self.store.values(), []):
                if e.vector is None or e.signature != sig:
                    continue
                if not self._live(e, epoch):
                    continue
                sim = float(np.dot(e.vector, v))
                if sim >= self.settings.similarity and set(e.cited_ids) <= fresh and sim > best_sim:
                    best, best_sim = e, sim
            if best is not None:
                self._guard("touch", lambda: self.store.touch(best.key))
        return (best, best_sim) if best is not None else None

    # -- writes ---------------------------------------------------------------------------------------------------------
    def put(self, key, sig, vector, epoch, raw, context_ids, cited_ids, sources, flags=frozenset()) -> bool:
        if not self.settings.enabled or not raw or len(raw) > MAX_RAW_CHARS or not context_ids or not cited_ids:
            self.stats["store_skipped"] += 1
            return False
        now = self.clock()
        entry = Entry(key, sig, unit_vector(vector) if vector is not None else None, epoch, raw, tuple(context_ids),
                      tuple(cited_ids), tuple(sources), frozenset(flags), now, now + self.settings.ttl_seconds)
        entry.measure()
        with self._lock:
            if self._epoch is not None and epoch != self._epoch:
                self.stats["store_skipped"] += 1  # the epoch moved while the answer was being generated
                return False

            def _store():
                while len(self.store) >= self.settings.max_entries and self.store.get(key) is None:
                    oldest = self.store.oldest()
                    self.store.delete(oldest)
                    self.stats["evicted"] += 1
                self.store.put(key, entry)
                return True
            ok = self._guard("put", _store, False)
            self.stats["stored" if ok else "store_failed"] += 1
            return bool(ok)

    def drop(self, entry, reason):
        with self._lock:
            self._drop(entry, reason)

    def invalidate_source(self, ident) -> int:
        """Drop every entry built from the document with this SHA-256 or manifest id (an update, replacement,
        amendment of that document or its deletion). Returns how many were dropped."""
        n = 0
        with self._lock:
            for e in self._guard("scan", lambda: self.store.values(), []):
                if any(ident in (sha, manifest) for sha, manifest in e.sources):
                    self._drop(e, "source")
                    n += 1
        return n

    def clear(self):
        with self._lock:
            for e in self._guard("scan", lambda: self.store.values(), []):
                self._guard("delete", lambda e=e: self.store.delete(e.key))

    def snapshot(self) -> dict:
        with self._lock:
            entries = self._guard("scan", lambda: self.store.values(), [])
            return {"mode": self.settings.mode, "entries": len(entries), "bytes": sum(e.size for e in entries),
                    "similarity": self.settings.similarity, "ttl_seconds": self.settings.ttl_seconds,
                    "max_entries": self.settings.max_entries, "counters": dict(self.stats)}
