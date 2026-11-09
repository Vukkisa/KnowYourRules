"""
FastAPI backend for the Telangana Traffic Rules Assistant.
Serves the frontend at /, answers questions at POST /chat and reports the knowledge-base state at GET /status.

Run with:
    uvicorn backend.server:app --reload --port 8000
(from the project root)

Scope: Telangana state instruments only. Central texts (MV Act, CMVR) and other states are not covered.
The Telangana knowledge base is under legal review (docs/legal-sources/telangana-traffic/), so:
  - the server starts without an index and reports it as unavailable instead of crashing;
  - penalty / fine / compounding questions get a fixed "not yet verified" reply, without calling the
    model, unless a valid legal approval record (TG_APPROVAL_FILE, see backend/legal_approval.py)
    explicitly approves penalty answers and matches the indexed documents hash for hash.
"""

import hashlib
import logging
import math
import os
import re
import threading
import time
import unicodedata
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from langchain.chat_models import init_chat_model
from langchain_chroma import Chroma
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import OllamaEmbeddings

from backend import hybrid_retrieval, legal_approval, rag_profiles

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=True)

if not os.environ.get("GROQ_API_KEY") or "placeholder" in os.environ.get("GROQ_API_KEY", ""):
    raise RuntimeError("GROQ_API_KEY is missing or still a placeholder in .env")

ASSISTANT_STATE = "Telangana"
# A separate directory and collection: the shared multi-state index is never read or modified here.
TG_COLLECTION = "telangana-traffic-rules"
TG_DB_DIR = Path(os.environ.get("TG_DB_DIR", BASE_DIR / "chroma_telangana_db"))


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


# Legal approval comes only from a structured record transcribed from the signed approval block in
# LEGAL-REVIEW-HANDOFF.md section 5 - never from a bare environment flag. No record = not approved.
APPROVAL_FILE = Path(os.environ.get("TG_APPROVAL_FILE", BASE_DIR / "legal" / "telangana-approval.json"))
# Public keys of the approval authority (see docs/approval-trust-model.md). Unset = no trusted keys = no approval.
TRUSTED_KEYS_FILE = Path(os.environ["TG_TRUSTED_KEYS_FILE"]) if os.environ.get("TG_TRUSTED_KEYS_FILE") else None
# Optional: the source documents; when set, they are hashed and compared with the record too.
CORPUS_DIR = Path(os.environ["TG_CORPUS_DIR"]) if os.environ.get("TG_CORPUS_DIR") else None
try:
    APPROVAL_RECHECK_SECONDS = max(30.0, float(os.environ.get("TG_APPROVAL_RECHECK_SECONDS", "300")))
except ValueError:
    APPROVAL_RECHECK_SECONDS = 300.0

embeddings_model = rag_profiles.ProfileEmbeddings(OllamaEmbeddings(model="nomic-embed-text"))


def open_store():
    """The Telangana collection, or None if it has not been built. Never creates a directory or collection."""
    if not TG_DB_DIR.is_dir():
        return None
    try:
        return Chroma(
            collection_name=TG_COLLECTION,
            embedding_function=embeddings_model,
            persist_directory=str(TG_DB_DIR),
            create_collection_if_not_exists=False,
        )
    except Exception:
        return None


def inspect_index(store) -> dict:
    """Index state for /status and the chat gate: 'missing', 'empty', 'invalid' or 'ready', plus chunk count."""
    if store is None:
        return {"index": "missing", "chunks": 0, "detail": "No Telangana index has been built."}
    try:
        metadatas = store.get(include=["metadatas"])["metadatas"]
    except Exception:
        return {"index": "invalid", "chunks": 0, "detail": "The Telangana index could not be read."}
    if not metadatas:
        return {"index": "empty", "chunks": 0, "detail": "The Telangana index has no chunks."}
    states = {(m or {}).get("state") for m in metadatas}
    if states != {ASSISTANT_STATE}:
        # Telangana-only by design: chunks without a state, or from another state / Central, are refused.
        return {"index": "invalid", "chunks": len(metadatas),
                "detail": "The index contains chunks that are not tagged Telangana; rebuild it."}
    return {"index": "ready", "chunks": len(metadatas), "detail": "Telangana index loaded."}


vector_store = open_store()
INDEX_INFO = inspect_index(vector_store)


def index_metadatas(store) -> list:
    try:
        return store.get(include=["metadatas"])["metadatas"] if store is not None else []
    except Exception:
        return []


# ---------------------------------------------------------------------------------------------------
# Approval lifecycle. Full validation (signature, record, index metadata, corpus hashes) runs at startup,
# on POST /approval/refresh, and every APPROVAL_RECHECK_SECONDS while approved. Every request runs a
# cheap fingerprint check; any change marks the approval "stale" (not approved, penalties off, no
# VERIFIED sources) until a full revalidation succeeds.
# ---------------------------------------------------------------------------------------------------
_approval_lock = threading.RLock()
APPROVAL = legal_approval.ApprovalStatus("absent")
KB_APPROVED = False
PENALTY_ANSWERS_ENABLED = False
# Verified title and instrument, keyed by the SHA-256 of the exact approved file - never by file name.
# Filled only from a valid approval record; empty otherwise, so every source is labelled unverified.
# VERIFIED status comes only from chunk metadata matched here; nothing the model writes can set it.
SOURCES: dict[str, tuple[str, str]] = {}
_FINGERPRINT = None
_LAST_FULL_CHECK = 0.0


def _small_file_digest(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest() if path is not None else None
    except OSError:
        return None


def _index_fingerprint():
    if vector_store is None:
        return None
    try:
        collection = getattr(vector_store, "_collection", None)
        if collection is not None:
            return (str(collection.id), collection.count())
        return ("ids", len(vector_store.get(include=[])["ids"]))
    except Exception:
        return ("unreadable",)


def _corpus_fingerprint():
    if CORPUS_DIR is None:
        return None
    try:
        return tuple(sorted((str(p), p.stat().st_size, p.stat().st_mtime_ns)
                            for p in CORPUS_DIR.rglob("*") if p.is_file()))
    except OSError:
        return ("unreadable",)


def approval_fingerprint():
    """Cheap: hashes of the small record/signature/key files, index id + count, corpus file sizes/mtimes."""
    return (
        _small_file_digest(APPROVAL_FILE),
        _small_file_digest(legal_approval.signature_path(APPROVAL_FILE)),
        _small_file_digest(TRUSTED_KEYS_FILE),
        _index_fingerprint(),
        _corpus_fingerprint(),
    )


def _apply_approval(status):
    global APPROVAL, KB_APPROVED, PENALTY_ANSWERS_ENABLED
    APPROVAL = status
    KB_APPROVED = status.general_answers
    PENALTY_ANSWERS_ENABLED = status.penalty_answers
    SOURCES.clear()  # same dict object, so nothing can keep a stale reference
    if KB_APPROVED:
        SOURCES.update({d.sha256: (d.title, d.instrument) for d in status.record.documents})


def _full_validation():
    if INDEX_INFO["index"] != "ready":
        if APPROVAL_FILE.exists():
            return legal_approval.ApprovalStatus("invalid", ["the Telangana index is not ready"])
        return legal_approval.ApprovalStatus("absent")
    return legal_approval.evaluate(APPROVAL_FILE, index_metadatas(vector_store),
                                   trusted_keys=TRUSTED_KEYS_FILE, corpus_dir=CORPUS_DIR)


def refresh_approval():
    """Full revalidation. The only way back to an approved state after a change."""
    global _FINGERPRINT, _LAST_FULL_CHECK
    with _approval_lock:
        _FINGERPRINT = approval_fingerprint()
        _apply_approval(_full_validation())
        _LAST_FULL_CHECK = time.monotonic()
        return APPROVAL


def ensure_approval_current():
    """Per-request check. Invalidates on any detected change; never re-approves by itself."""
    global _FINGERPRINT, _LAST_FULL_CHECK
    with _approval_lock:
        current = approval_fingerprint()
        if current != _FINGERPRINT:
            _FINGERPRINT = current
            if APPROVAL.state != "absent" or current[0] is not None:
                _apply_approval(legal_approval.ApprovalStatus(
                    "stale", ["approval inputs changed since the last validation; revalidation required"],
                    APPROVAL.record))
            return
        if APPROVAL.state == "valid" and time.monotonic() - _LAST_FULL_CHECK >= APPROVAL_RECHECK_SECONDS:
            status = _full_validation()
            _LAST_FULL_CHECK = time.monotonic()
            if status.state != "valid":
                _apply_approval(status)


refresh_approval()
INDEX_PROFILE = rag_profiles.profile_of_index(vector_store)
embeddings_model.profile = INDEX_PROFILE

llm = init_chat_model("openai/gpt-oss-120b", model_provider="groq")


def index_ready() -> bool:
    return INDEX_INFO["index"] == "ready"


# ---------------------------------------------------------------------------------------------------
# Missing-provision guard. An explicit "Rule N" reference to a rule that is not in the index is answered
# deterministically, without retrieval or any model call, so nearby or similar rules are never passed
# off as the requested one. The catalogue comes from the index's own provision metadata; an index without
# provision metadata (older builds) has no catalogue and the guard stays off.
# ---------------------------------------------------------------------------------------------------
INSTRUMENT_PREFIXES = {"tmvr": "tmvr-1989", "tmvtr": "tmvtr-1963"}


def build_provision_catalogue(metadatas) -> dict:
    """provision_id ("Rule 185") -> set of manifest_ids that contain it."""
    catalogue = {}
    for m in metadatas or []:
        m = m or {}
        if m.get("provision_id") and m.get("manifest_id"):
            catalogue.setdefault(m["provision_id"], set()).add(m["manifest_id"])
    return catalogue


PROVISION_CATALOGUE = build_provision_catalogue(index_metadatas(vector_store)) if index_ready() else {}

# 12A, 12-A, and "13 b" only at the end of the question or before punctuation ("Rule 5 A person" is not 5A).
_RULE_NUMBER = r"\d{1,3}(?:\s*-\s*[A-Za-z]|[A-Za-z](?![A-Za-z])|\s+[A-Za-z](?=\s*(?:[?.,;:)]|$)))?"
_RULE_LIST = rf"{_RULE_NUMBER}(?:\s*(?:,|&|/|\band\b|\bor\b|\bto\b|-)\s*{_RULE_NUMBER})*"
RULE_REFERENCE_RE = re.compile(rf"\b(?:sub-)?rules?\s*(?:no\.?|number|nos\.?)?\s*(?P<list>{_RULE_LIST})", re.IGNORECASE)
RULE_ITEM_RE = re.compile(
    r"(\d{1,3})(?:\s*-\s*([A-Za-z])(?![A-Za-z])|([A-Za-z])(?![A-Za-z])|\s+([A-Za-z])(?=\s*(?:[?.,;:)]|$)))?")
TAXATION_RE = re.compile(r"\btmvtr\b|taxation\s+rules", re.IGNORECASE)
MV_RULES_RE = re.compile(r"\btmvr\b|motor\s+vehicles?\s+rules", re.IGNORECASE)
# The Central Motor Vehicles Rules, 1989 are NOT in the corpus. Checked before MV_RULES_RE, whose
# "motor vehicles rules" would otherwise claim "Central Motor Vehicles Rules" for the TMVR.
CENTRAL_RULES_RE = re.compile(
    r"\bcentral\s+motor\s+vehicles?\s*(?:\([^)]{0,40}\)\s*)?rules\b|\bcmv\s*rules\b|\bcmvrs?\b", re.IGNORECASE)
CENTRAL = "cmvr-1989"
INSTRUMENT_NAMES = {"tmvr-1989": "Telangana Motor Vehicles Rules, 1989 (TMVR)",
                    "tmvtr-1963": "Telangana Motor Vehicles Taxation Rules, 1963 (TMVTR)",
                    CENTRAL: "Central Motor Vehicles Rules, 1989 (not in the Telangana sources)"}
# A citation of a Central rule inside an indexed document: "Rule 167A(1) of the Central Motor Vehicles Rules".
CENTRAL_CITATION_RE = re.compile(
    r"\brules?\s+(\d{1,3})\s*-?\s*([A-Z])?(?![A-Za-z])(?:\s*\([^)]{0,6}\))*\s+of\s+(?:the\s+)?(?:said\s+)?"
    r"(?:central\s+motor\s+vehicles?\s*(?:\([^)]{0,40}\)\s*)?rules|cmv\s*rules)", re.IGNORECASE)
# Asking for the rule itself ("what does it say", "text of", "explain Rule N"), not a question that merely mentions it.
RULE_TEXT_REQUEST_RE = re.compile(
    r"\bwhat\s+(?:does|do)\b.*\b(?:say|says|state|states|provide|provides|require|requires|mandate|contain|mean)\b"
    r"|\b(?:text|wording|contents?|provisions?)\s+of\b|\bfull\s+text\b|\bquote\b|\breproduce\b"
    r"|^\s*(?:please\s+)?(?:explain|summari[sz]e|define|show|read|describe)\b"
    r"|^\s*(?:what\s*(?:is|'s|are)|tell\s+me\s+about)\s+(?:the\s+)?(?:\w+\s+){0,2}rules?\s+\d", re.IGNORECASE)
MAX_RANGE = 20


def rule_reference_spans(message: str) -> list[tuple[str, int, int]]:
    """(reference, start, end) for each explicit rule reference, in order; a list ("rules 185, 186") shares
    one span. "sub-rule (2)" and plain numbers ("500 rupees", "2 wheeler") are not rule references."""
    spans = []
    for m in RULE_REFERENCE_RE.finditer(message):
        if m.group(0).lower().startswith("sub-"):
            continue  # "sub-rule 2" is part of a rule, not a rule number
        items = list(RULE_ITEM_RE.finditer(m.group("list")))
        between = [m.group("list")[a.end():b.start()] for a, b in zip(items, items[1:])]
        numbers = []
        for i, it in enumerate(items):
            suffix = (it.group(2) or it.group(3) or it.group(4) or "").upper()
            if i and re.search(r"\bto\b|-", between[i - 1]) and not suffix and numbers and numbers[-1][1] == "":
                start, end = numbers[-1][0], int(it.group(1))
                if 0 < end - start <= MAX_RANGE:
                    numbers.extend((n, "") for n in range(start + 1, end + 1))
                    continue
            numbers.append((int(it.group(1)), suffix))
        for n, suffix in numbers:
            spans.append((f"Rule {n}{suffix}", m.start(), m.end()))
    return spans


def rule_references(message: str) -> list[str]:
    """Explicit rule references in order, e.g. ["Rule 185", "Rule 186"]. "rules 185 to 187" expands short ranges."""
    refs = []
    for ref, _s, _e in rule_reference_spans(message):
        if ref not in refs:
            refs.append(ref)
    return refs


def _instrument_in(text: str) -> str | None:
    if CENTRAL_RULES_RE.search(text):
        return CENTRAL
    if TAXATION_RE.search(text):
        return INSTRUMENT_PREFIXES["tmvtr"]
    if MV_RULES_RE.search(text):
        return INSTRUMENT_PREFIXES["tmvr"]
    return None


def instrument_scope(message: str) -> str | None:
    """The one instrument the message names: "tmvtr-1963", "tmvr-1989" or CENTRAL; None if none or several."""
    named = set()
    if CENTRAL_RULES_RE.search(message):
        named.add(CENTRAL)
    rest = CENTRAL_RULES_RE.sub(" ", message)
    if TAXATION_RE.search(rest):
        named.add(INSTRUMENT_PREFIXES["tmvtr"])
    if MV_RULES_RE.search(TAXATION_RE.sub(" ", rest)):
        named.add(INSTRUMENT_PREFIXES["tmvr"])
    return named.pop() if len(named) == 1 else None


def reference_scope(message: str, start: int, end: int) -> str | None:
    """Instrument named right at a reference ("CMVR Rule 167A", "Rule 167A of the Central Motor Vehicles
    Rules"), else the single instrument the whole message names, else None (not established)."""
    after = re.match(r"\s*(?:\([^)]{0,6}\)\s*)*,?\s*(?:of|under|in)\s+(?:the\s+)?(?:said\s+)?(.{0,70})",
                     message[end:end + 90], re.IGNORECASE | re.DOTALL)
    if after and (scope := _instrument_in(after.group(1)[:60])):
        return scope
    before = re.search(r"\b(cmvr|cmv|central|tmvtr|tmvr)\s*(?:sub-)?$", message[max(0, start - 12):start], re.IGNORECASE)
    if before:
        word = before.group(1).lower()
        return CENTRAL if word in ("cmvr", "cmv", "central") else INSTRUMENT_PREFIXES[word]
    return instrument_scope(message)


def build_central_citations(docs) -> dict:
    """"Rule 167A" -> sorted labels of answer-eligible indexed documents that cite it as a Central rule.
    A citation shows the rule exists and what cites it; it is never treated as the rule's text."""
    cited = {}
    for d in docs or []:
        m = d.metadata or {}
        if m.get("answer_eligible") is False or m.get("state") not in (None, ASSISTANT_STATE):
            continue
        for c in CENTRAL_CITATION_RE.finditer(" ".join(d.page_content.split())):
            ref = f"Rule {int(c.group(1))}{(c.group(2) or '').upper()}"
            label = m.get("document_number") or m.get("title") or m.get("manifest_id")
            cited.setdefault(ref, set()).add(label)
    return {k: sorted(v) for k, v in cited.items()}


class RuleCheck:
    """Deterministic classification of every explicit rule reference in a message."""

    def __init__(self):
        self.missing, self.present = [], []     # Telangana rules not in / in the index
        self.central_text = []                  # [(ref, citing docs)]: asks for a Central rule's text
        self.central_cited = []                 # [(ref, citing docs)]: mentions a cited Central rule
        self.unresolved = []                    # [(ref, [instrument names])]: instrument not established


def classify_rule_references(message: str) -> RuleCheck:
    out = RuleCheck()
    if not PROVISION_CATALOGUE:
        return out
    wants_text = bool(RULE_TEXT_REQUEST_RE.search(message))
    seen = set()
    for ref, start, end in rule_reference_spans(message):
        scope = reference_scope(message, start, end)
        if (ref, scope) in seen:
            continue
        seen.add((ref, scope))
        ids = PROVISION_CATALOGUE.get(ref, set())
        cited = CENTRAL_CITATIONS.get(ref, [])
        if scope in (INSTRUMENT_PREFIXES["tmvr"], INSTRUMENT_PREFIXES["tmvtr"]):
            (out.present if any(i.startswith(scope) for i in ids) else out.missing).append(ref)
        elif scope == CENTRAL:
            if not cited:
                out.missing.append(f"{ref} of the Central Motor Vehicles Rules")
            else:
                (out.central_text if wants_text else out.central_cited).append((ref, cited))
        elif ids and cited:
            # In the Telangana index AND cited as a Central rule: which one is meant is not established.
            names = sorted({INSTRUMENT_NAMES[p] for p in INSTRUMENT_PREFIXES.values() if any(i.startswith(p) for i in ids)})
            out.unresolved.append((ref, names + [INSTRUMENT_NAMES[CENTRAL]]))
        elif ids:
            out.present.append(ref)
        elif cited:
            # Not a Telangana rule; indexed documents cite it only as a Central rule.
            (out.central_text if wants_text else out.central_cited).append((ref, cited))
        else:
            out.missing.append(ref)
    return out


def missing_rule_references(message: str) -> tuple[list[str], list[str]]:
    """(missing, present) explicit rule references; each is scoped by the instrument named at it or in the
    message. A rule number is never assumed to be a TMVR rule just because it is unqualified."""
    check = classify_rule_references(message)
    return check.missing, check.present


def central_rule_message(central_text) -> str:
    lines = [f"- **{ref}** is cited in {', '.join(docs)}" for ref, docs in central_text]
    return ("**That is a rule of the Central Motor Vehicles Rules, 1989, which are not in the Telangana "
            "sources.** The Telangana documents I have only cite it; they don't contain its text, so I won't "
            "say what it provides:\n\n" + "\n".join(lines) + "\n\nYou can ask what those Telangana documents "
            "say, or check the official Central text.")


# ---------------------------------------------------------------------------------------------------
# Hybrid retrieval (structured lookup + BM25 + vector, fused with RRF). RAG_RETRIEVAL_MODE=vector keeps the
# original vector-only path. The lexical index is built in memory from the stored chunks; an index without
# chunk text or provision metadata leaves it off, and retrieval falls back to vector-only.
# ---------------------------------------------------------------------------------------------------
RETRIEVAL_MODE = os.environ.get("RAG_RETRIEVAL_MODE", "hybrid").strip().lower()
if RETRIEVAL_MODE not in ("hybrid", "vector"):
    RETRIEVAL_MODE = "hybrid"
LEXICAL_INDEX = hybrid_retrieval.LexicalIndex.from_store(vector_store) if PROVISION_CATALOGUE else None
CENTRAL_CITATIONS = build_central_citations(LEXICAL_INDEX.docs) if LEXICAL_INDEX is not None else {}


def provision_lookup(message: str):
    if LEXICAL_INDEX is None:
        return None
    scope = instrument_scope(message)
    refs = [ref for ref, s, e in rule_reference_spans(message) if reference_scope(message, s, e) != CENTRAL]
    return LEXICAL_INDEX.lookup(message, list(dict.fromkeys(refs)), None if scope == CENTRAL else scope)


def missing_references(message: str) -> tuple[list[str], list[str]]:
    """Missing rule references plus G.O. numbers (or number/year) that are not in the index."""
    missing, present = missing_rule_references(message)
    lookup = provision_lookup(message)
    return (missing + lookup.missing_gos if lookup else missing), present


def ambiguous_references(message: str) -> list:
    """[(reference, [candidates])] for references that match more than one instrument or G.O."""
    lookup = provision_lookup(message)
    found = list(lookup.ambiguous) if lookup else []
    for ref, names in classify_rule_references(message).unresolved:
        if ref not in {r for r, _ in found}:
            found.append((ref, names))
    return found


def clarification_message(ambiguous) -> str:
    lines = [f"- **{ref}** appears in: {'; '.join(options)}" for ref, options in ambiguous]
    return ("Which instrument do you mean? I won't choose one for you:\n\n" + "\n".join(lines) +
            "\n\nAsk again naming it, for example \"TMVR Rule 10\" or \"TMVTR Rule 10\", or a G.O. number with "
            "its year.")


def missing_provision_message(missing: list[str], present: list[str]) -> str:
    names = ", ".join(missing)
    verb = "is" if len(missing) == 1 else "are"
    text = (f"**{names} {verb} not in the available source snapshot.** I have no text for "
            f"{'it' if len(missing) == 1 else 'them'}, so I won't answer from other rules in its place. "
            "The sources are unverified snapshots under legal review; check the official Telangana Transport "
            "Department text.")
    if present:
        text += f"\n\n{', '.join(present)} {'is' if len(present) == 1 else 'are'} available - ask about " \
                f"{'it' if len(present) == 1 else 'them'} on its own."
    return text


strict_template = """You are the Telangana Traffic Rules Assistant. Answer the question using ONLY the
context below, which comes from Telangana state instruments (Rules, Acts and Government Orders). Cite
the source document exactly as given in the "Source:" tag on each context chunk. The Source tag says
whether the document is an Act, Rules or a G.O. - never call one by another's name. If a Source tag
says the source is unverified, say so when you cite it.

This knowledge base covers Telangana only. It does NOT include the Central Motor Vehicles Act, 1988,
the Central Motor Vehicles Rules, 1989 or any other state's law. If answering properly would need
those, say so plainly instead of filling the gap from memory.

If the context does not contain enough information to answer, say clearly that this knowledge base
does not cover it - do NOT use outside knowledge or guess.

Context:
{context}

Question: {question}
"""
strict_prompt = ChatPromptTemplate.from_template(strict_template)


def chunk_hash(metadata) -> str | None:
    h = (metadata or {}).get("sha256")
    return h if isinstance(h, str) and legal_approval.SHA256_RE.match(h) else None


def describe_source(metadata) -> str:
    h = chunk_hash(metadata)
    if h in SOURCES:
        title, instrument = SOURCES[h]
        return f"{title} ({instrument})"
    return f"Unverified source - title and instrument type not verified (file: {(metadata or {}).get('source_file', 'unknown')})"


def source_entries(docs) -> list[dict]:
    """Distinct sources of the retrieved chunks, for the UI, in retrieval order."""
    entries, seen = [], set()
    for d in docs:
        source_file = d.metadata.get("source_file", "unknown")
        h = chunk_hash(d.metadata)
        key = h or ("file", source_file)
        if key in seen:
            continue
        seen.add(key)
        title, instrument = SOURCES.get(h, (None, None))
        entries.append({"title": title or "Unverified source", "instrument": instrument,
                        "verified": h in SOURCES, "file": source_file, "sha256": h})
    return entries


def format_docs(docs):
    return "\n\n".join(f"Source: {describe_source(d.metadata)}\n{d.page_content}" for d in docs)


# Any answer that mentions money or a penalty carries this note. It must not claim the text IS outdated.
PENALTY_PATTERN = re.compile(
    r"₹|\b(?:rs|inr)\b\.?|\brupees?\b|\b(?:fines?|penalty|penalties|compounding)\b"
    r"|\b(?:hundred|thousand|lakh|crore)\b",
    re.IGNORECASE,
)
PENALTY_NOTE = (
    "\n\n_Note: the date of the legal text this answer is based on has not been verified against the "
    "current official version. Amounts are amended from time to time - check the current official text "
    "before relying on any amount._"
)


def with_penalty_note(answer: str) -> str:
    return answer + PENALTY_NOTE if PENALTY_PATTERN.search(answer) else answer


# ---------------------------------------------------------------------------------------------------
# Penalty lock. Penalty / compounding topics stay locked until counsel approves them (the s.200
# schedule is missing). The decision is deterministic (rules and patterns, never the LLM) and
# deliberately conservative: when in doubt, lock. Tax amounts are not locked; they carry PENALTY_NOTE.
# ---------------------------------------------------------------------------------------------------
lock_log = logging.getLogger("knowyourrules.penalty_lock")

PENALTY_LOCKED_MESSAGE = (
    "**Penalties and compounding fees are not available yet.**\n\n"
    "The official Telangana compounding schedule has not been obtained, and the knowledge base has not "
    "been approved by legal counsel, so I can't give fine amounts, compounding fees, penalty points or "
    "other punishment details.\n\n"
    "For current amounts, check the official Telangana Transport Department or Hyderabad / Cyberabad / "
    "Rachakonda traffic police e-challan portals."
)

_I = re.IGNORECASE

# Always penalty intent on their own (Latin script). Covers common misspellings and romanised
# Hindi / Telugu terms.
PENALTY_STRONG = re.compile(
    r"\b(?:"
    r"p[ae]n+[ae]l+i?t(?:y|ies|ie|i)|pena?lt?y"                      # penalty, penality, panelty, penlty
    r"|fined|fines|fien[sd]?|fiens?|fyne"                            # fined / fines / misspellings of fine
    r"|e-?chall?a+n\w*|chall?a+n\w*|chell?an\w*|chal+aan\w*"         # challan, chalan, e-challan, chaalan
    r"|comp(?:o|ou|u)nd(?:ing|ed|able)|compunding"                   # compounding
    r"|punish\w*|imprison\w*|jail\w*|prison|arrest\w*|prosecut\w*"
    r"|offen[cs]es?|demerit\w*|penalty\s+points?|points?\s+on\s+(?:my\s+)?licen[cs]e"
    r"|seiz\w*|sieze\w*|impound\w*|confiscat\w*"
    r"|tow(?:ed|ing|s)?|tow\s+away"
    r"|disqualif\w*|detain\w*|detention|custody"
    r"|(?:take|took|taken|taking)\s+(?:away\s+)?(?:my|the|your)\s+(?:bike|car|vehicle|scooter|auto|licen[cs]e|dl|rc|keys?)"
    r"|lose\s+(?:my|the|your)\s+(?:licen[cs]e|dl|rc)\s+(?:for|because|over|due|if|after)"
    r"|booked|book\s+(?:me|a\s+case)|case\s+(?:filed|registered|booked)"
    r"|jurm(?:a|aa)n(?:a|aa)|jurmane|zurmana|jarim(?:a|aa)n(?:a|aa)?|dand(?:a|aa)?|saz(?:a|aa)|jabt|japthu|japtu"
    r")\b",
    _I,
)
# Native-script Hindi and Telugu terms. Matched as substrings: \b is unreliable around combining marks.
PENALTY_NATIVE = (
    "जुर्माना", "जुरमाना", "चालान", "दंड", "सज़ा", "सजा", "जब्त", "जुर्माने", "फाइन", "फ़ाइन",
    "జరిమానా", "జరిమాన", "ఫైన్", "చలాన్", "చలానా", "శిక్ష", "జప్తు", "అపరాధ రుసుము",
)

# "fine" is penalty intent only with context ("the fine for", "fine amount", "how much fine").
FINE_IN_CONTEXT = re.compile(
    r"\b(?:the|a|any|what|how\s+much|pay|paid|paying|charged?|impose[sd]?|levied|traffic|spot|heavy|huge|big)\s+fine\b"
    r"|\bfine\s+(?:amount|of|for|if|on|charged|imposed|levied|payable|paid|is|will|kitna|kitni|entha|enta|yentha|lagega|padega|kattali)\b"
    r"|\b(?:kitna|kitni|entha|enta|yentha)\s+fine\b|^\s*fine\s*\?\s*$",
    _I,
)
# Ordinary uses of "fine" ("is it fine to", "I'm fine", "fine print") - removed before the check above.
FINE_ORDINARY = re.compile(
    r"\b(?:is\s+it|is\s+that|it'?s|it\s+is|that'?s|that\s+is|be|are|was|feel|looks?|seems?|i'?m|i\s+am|we'?re|all|perfectly|totally|quite|just)"
    r"\s+(?:\w+\s+)?fine\b|\bfine\s+(?:print|tun\w*|art|dining|gold|sand)\b|\bfine\s*,\s*thanks?\b",
    _I,
)

# Licence / RC action words that are penalty intent only when tied to a licence or registration.
LICENCE_ACTION = re.compile(
    r"\b(?:cancel\w*|revok\w*|revocation|suspend\w*|suspension|withdraw\w*|blacklist\w*|ban(?:ned)?)\b"
    r".{0,40}\b(?:licen[cs]e|dl|rc|registration|permit)\b"
    r"|\b(?:licen[cs]e|dl|rc|registration|permit)\b.{0,40}"
    r"\b(?:cancel\w*|revok\w*|revocation|suspend\w*|suspension|withdraw\w*|blacklist\w*|ban(?:ned)?)\b",
    _I | re.DOTALL,
)

# Indirect "what happens / how much do I pay" wording; locked when combined with a violation cue.
CONSEQUENCE = re.compile(
    r"\b(?:what\s+(?:happens|will\s+happen|would\s+happen|happen)|what\s+if|what\s+(?:action|can\s+(?:they|police)\s+do)"
    r"|how\s+much\s+(?:do|will|would|should|must|have|has|to|did|is|am|are)\b|how\s+much\b.{0,30}\bpay"
    r"|(?:do|will|would|must|should)\s+i\s+(?:have\s+to\s+)?pay|what\s+do\s+i\s+(?:have\s+to\s+)?pay"
    r"|any\s+(?:action|problem|trouble)|get\s+(?:in|into)\s+trouble|is\s+it\s+(?:a\s+)?(?:crime|illegal)"
    r"|owe|charges?|charged|fee|fees|amount|cost|costs|how\s+much\s+for"
    # Romanised Hindi / Telugu: how much, pay, what will happen.
    r"|kitna|kitni|kitne|entha|enta|yentha|kattali|kattaali|katte|dena\s+pade\w*|bharna\s+pade\w*"
    r"|kya\s+hoga|kya\s+kare\w*|em\s+avtundi|em\s+avutundi|emavutundi|em\s+avuthundi|emi?\s+chesthar\w*)\b",
    _I | re.DOTALL,
)
# Always locked: asks about consequences outright.
CONSEQUENCE_STRONG = re.compile(r"\bconsequen\w*|\brepercussion\w*|\bliable\s+to\b|\bpunitive\b", _I)
VIOLATION_CUE = re.compile(
    r"\b(?:without\s+(?:a\s+|an\s+|the\s+|my\s+|any\s+|valid\s+|wearing\s+(?:a\s+)?)?"
    r"(?:helmet|licen[cs]e|dl|insurance|puc|pollution|seat\s?belt|rc|registration|permit|number\s+plate|documents?|papers|fitness)s?"
    r"|riding\s+without|driving\s+without|drive\s+without|ride\s+without"
    r"|\w+kapothe|lekapothe|lekunda|leka|nahi\s+(?:pehna|pehni|hai|tha)|bina|pakde|pakda|pakdi|pattukunte|pattukunnaru"
    r"|no\s+(?:helmet|licen[cs]e|dl|insurance|puc|seat\s?belt|rc|permit|number\s+plate)"
    r"|not\s+(?:wearing|having|carrying)|don'?t\s+(?:have|wear|carry)|didn'?t\s+(?:have|wear|carry|stop)"
    r"|forgot|caught|stopped\s+by|police|cops?|traffic\s+(?:police|cop)"
    r"|drunk|drink\w*\s+and\s+driv\w*|drunken|alcohol|violat\w*|break\w*\s+(?:the\s+)?(?:rule|law|signal)"
    r"|jump\w*|red\s+light|signal|over-?speed\w*|speeding|rash|dangerous\w*|triple\s+riding|wrong\s+side"
    r"|expired|unlicen[cs]ed|uninsured|underage|minor|mobile\s+phone|using\s+(?:a\s+)?phone|overload\w*"
    r"|illegal(?:ly)?\s+park\w*|no\s+parking|parked\s+(?:in|on|at)|honk\w*|tinted|black\s+film|modified\s+silencer)\b",
    _I,
)

# Answer drift: a money amount stated as an obligation, or near a violation, in a model answer.
AMOUNT = re.compile(
    r"(?:₹|\brs\.?|\binr\b)\s*[\d,]+|\b[\d,]+(?:\.\d+)?\s*(?:/-|rupees?|rs\b|inr\b)"
    r"|\b(?:one|two|three|four|five|six|seven|eight|nine|ten|fifty|hundred|thousand|lakh)\b[\w\s-]{0,30}\brupees?\b"
    r"|\b(?:\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|twenty-five"
    r"|thirty|forty|fifty|a)\s+(?:hundred|thousand|lakh)s?\b",
    _I,
)
MONEY_OBLIGATION = re.compile(
    r"\b(?:payable|pay|paid|liable|charged?|levied|leviable|imposed?|collected|recover\w*|deposit\w*|extend\s+to|up\s+to|upto)\b",
    _I,
)
TAX_OR_FEE_CONTEXT = re.compile(
    r"\b(?:fee|fees|tax|taxes|taxation|life\s+tax|quarterly\s+tax|cess|registration\s+fee|licen[cs]e\s+fee|test\s+fee"
    r"|application\s+fee|fees?\s+for\s+(?:registration|licen[cs]e|transfer|duplicate|renewal)|ex-?showroom|cost\s+of\s+the\s+vehicle)\b",
    _I,
)


NATIVE_AMOUNT_OR_CONSEQUENCE = ("ఎంత", "కట్టాలి", "ఏమవుతుంది", "ఏం అవుతుంది", "कितना", "कितने", "देना होगा", "देना पड़ेगा", "क्या होगा")
NATIVE_VIOLATION = ("లేకపోతే", "లేకుండా", "పట్టుకుంటే", "పోలీస్", "बिना", "पकड़े", "पकड़ा", "पुलिस", "नहीं पहन", "नहीं है")


TAX_DEFAULT_PENALTY = re.compile(
    r"\b(?:additional|extra|penal|late\s+(?:payment|fee)|delay\w*|belated|arrears?|default\w*|surcharge|interest\s+on\s+(?:unpaid|arrears)"
    r"|non-?payment|unpaid|evasion|evaded|failure\s+to\s+pay|fails?\s+to\s+pay|due\s+date|not\s+(?:paid|done|made)\s+within|in\s+addition\s+to\s+the\s+tax)\b",
    _I,
)


CAUGHT = re.compile(r"\b(?:caught|get\s+caught|pakde\s+gaye|pakda\s+gaya|pattukunte|pattukunnaru)\b", _I)


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text or "")).strip()


def penalty_lock_reason(text: str) -> str | None:
    """Reason code if the text asks about penalties / enforcement, else None. Never calls the model."""
    t = _normalise(text)
    if not t:
        return None
    if any(term in t for term in PENALTY_NATIVE):
        return "native_term"
    if any(w in t for w in NATIVE_AMOUNT_OR_CONSEQUENCE) and any(w in t for w in NATIVE_VIOLATION):
        return "native_indirect"
    if PENALTY_STRONG.search(t):
        return "penalty_term"
    if FINE_IN_CONTEXT.search(FINE_ORDINARY.sub(" ", t)):
        return "fine_in_context"
    if LICENCE_ACTION.search(t):
        return "licence_action"
    if CONSEQUENCE_STRONG.search(t):
        return "consequence"
    if CONSEQUENCE.search(t) and VIOLATION_CUE.search(t):
        return "indirect_consequence"
    if AMOUNT.search(t) and VIOLATION_CUE.search(t):
        return "amount_with_violation"
    if CAUGHT.search(t) and VIOLATION_CUE.search(CAUGHT.sub(" ", t)):
        return "caught_with_violation"
    return None


def is_penalty_question(text: str) -> bool:
    return penalty_lock_reason(text) is not None


def answer_drift_reason(answer: str) -> str | None:
    """Reason code if a model answer states penalty content, including bare monetary penalties."""
    reason = penalty_lock_reason(answer)
    if reason:
        return reason
    t = _normalise(answer)
    if not AMOUNT.search(t):
        return None
    if TAX_DEFAULT_PENALTY.search(t):
        # Late-payment / default surcharges are penalties even inside a tax answer.
        return "tax_default_penalty"
    if not TAX_OR_FEE_CONTEXT.search(t):
        # Any amount not explained as a tax or fee is withheld (conservative).
        return "amount_obligation" if MONEY_OBLIGATION.search(t) else "unexplained_amount"
    return None


# A short or referential message right after a locked turn is treated as a continuation of it.
FOLLOW_UP_START = re.compile(
    r"^(?:and|also|or|but|so|then|what\s+about|how\s+about|same|for|in\s+case|if|what\s+if|even|ok(?:ay)?|and\s+if"
    r"|how\s+much|how\s+many|kitna|kitni|entha|enta|aur|mari|inka)\b", _I
)
FOLLOW_UP_REFERENCE = re.compile(r"\b(?:this|that|it|same|those|them|these|there|then|again|too|also|instead)\b", _I)
FOLLOW_UP_MAX_WORDS = 4


DUMMY_IT = re.compile(r"\bis\s+it\s+(?:mandatory|compulsory|necessary|required|possible|needed)\s+to\b", _I)
PROCEDURAL_TOPIC = re.compile(
    r"\b(?:rc|licen[cs]e|learner'?s?|registration|register|transfer|ownership|documents?|form|rto|apply|application"
    r"|renew\w*|duplicate|address|tax|process|procedure|eligibility|age)\b",
    _I,
)


def is_vague_follow_up(text: str) -> bool:
    t = _normalise(text)
    words = t.split()
    if FOLLOW_UP_START.search(t) or FOLLOW_UP_REFERENCE.search(DUMMY_IT.sub(" ", t)):
        return True
    if len(words) <= FOLLOW_UP_MAX_WORDS:
        # "RC transfer process" stands on its own; "for a bike?" and "cars?" do not.
        return not (len(words) >= 2 and PROCEDURAL_TOPIC.search(t))
    return False


def log_lock(stage: str, reason: str, session_id: str, text: str) -> None:
    """Record why a reply was locked. No message content: a session hash, the stage and the text length."""
    session_tag = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:12]
    lock_log.info("penalty_lock stage=%s reason=%s session=%s chars=%d", stage, reason, session_tag, len(text or ""))


# Relevance gate on retrieved chunks: squared L2 distance in Chroma's "l2" space (LOWER = MORE relevant).
# The default comes from the index's retrieval profile (see backend/rag_profiles.py) and must be
# recalibrated on the approved Telangana corpus; override with RAG_MAX_DISTANCE.
DEFAULT_MAX_DISTANCE = INDEX_PROFILE.default_max_distance


def parse_max_distance(value) -> float:
    try:
        distance = float(value)
    except (TypeError, ValueError):
        return DEFAULT_MAX_DISTANCE
    return distance if math.isfinite(distance) and distance > 0 else DEFAULT_MAX_DISTANCE


MAX_DISTANCE = parse_max_distance(os.environ.get("RAG_MAX_DISTANCE"))
RETRIEVE_K = 6

NO_SUPPORT_MESSAGE = (
    "I couldn't find sufficiently relevant information in the Telangana documents I have, so I won't "
    "guess. Try rephrasing your question, or check the official Telangana Transport Department sources."
)
UNAVAILABLE_MESSAGE = (
    "The Telangana knowledge base isn't loaded yet, so I can't answer questions right now. The official "
    "documents are still being collected and reviewed."
)
OUT_OF_SCOPE_MESSAGE = (
    "I only cover **Telangana** traffic rules. Rules for {places} aren't in my knowledge base, and I won't "
    "apply Telangana rules to another state. Ask me about Telangana, or check that state's official "
    "transport department."
)


def relevant_docs(results) -> list:
    """Keep documents from (doc, distance) pairs whose distance is a real number within MAX_DISTANCE.

    Anything malformed - missing or non-numeric scores, NaN, wrong shape, empty text - is dropped.
    """
    kept = []
    for item in results or []:
        try:
            doc, distance = item
        except (TypeError, ValueError):
            continue
        if isinstance(distance, bool) or not isinstance(distance, (int, float)) or not math.isfinite(distance):
            continue
        if getattr(doc, "page_content", None) and distance <= MAX_DISTANCE:
            kept.append(doc)
    return kept


def retrieve(question: str) -> list:
    """Telangana-only retrieval: always filtered to state=Telangana, never Central or other states."""
    if vector_store is None:
        return []
    docs = relevant_docs(
        vector_store.similarity_search_with_score(question, k=RETRIEVE_K, filter={"state": ASSISTANT_STATE})
    )
    if RETRIEVAL_MODE == "hybrid" and LEXICAL_INDEX is not None:
        lookup = provision_lookup(question)
        # Every candidate, whichever list it came from, goes through the same filters below.
        docs = hybrid_retrieval.reciprocal_rank_fusion(
            [lookup.documents, LEXICAL_INDEX.search(question, RETRIEVE_K), docs])
    seen, unique = set(), []
    for d in docs:
        if d.metadata.get("state") != ASSISTANT_STATE:
            continue
        if KB_APPROVED and chunk_hash(d.metadata) not in SOURCES:
            continue  # approved mode: never use a chunk whose document is not in the approval record
        if d.metadata.get("answer_eligible") is False:
            continue  # flagged at build time (e.g. unreliable table extraction): stored for review only
        key = (d.metadata.get("source_file"), d.page_content[:80])
        if key not in seen:
            seen.add(key)
            unique.append(d)
    return unique[:RETRIEVE_K]


contextualize_template = """Given the recent conversation history and a new message, rewrite the
new message as a fully self-contained question that includes whatever context from the history
is needed to understand it on its own (e.g. what rule or topic is being discussed).
Resolve references like "that", "it", or "this" using the history. If the new message is already
self-contained, return it unchanged. Do NOT answer the question - only rewrite it.

Conversation history (most recent last):
{history}

New message: "{message}"

Respond with ONLY the rewritten, self-contained question - no commentary.
"""
contextualize_prompt = ChatPromptTemplate.from_template(contextualize_template)
contextualize_chain = contextualize_prompt | llm | StrOutputParser()


def format_history(history: list[dict]) -> str:
    if not history:
        return "(none yet)"
    lines = []
    for turn in history:
        lines.append(f"User: {turn['question']}")
        lines.append(f"Assistant: {turn['answer']}")
    return "\n".join(lines)


def contextualize_question(question: str, history: list[dict]) -> str:
    if not history:
        return question
    try:
        return contextualize_chain.invoke({"history": format_history(history), "message": question}).strip()
    except Exception:
        return question


# Other states / UTs, used only to say "not covered" - never to switch jurisdiction.
OTHER_STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat",
    "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh",
    "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan",
    "Sikkim", "Tamil Nadu", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
    "Andaman and Nicobar", "Chandigarh", "Dadra and Nagar Haveli", "Daman and Diu", "Delhi",
    "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry",
]
OTHER_PLACE_ALIASES = {
    "new delhi": "Delhi", "orissa": "Odisha", "pondicherry": "Puducherry", "uttaranchal": "Uttarakhand",
    "mumbai": "Maharashtra", "pune": "Maharashtra", "bengaluru": "Karnataka", "bangalore": "Karnataka",
    "chennai": "Tamil Nadu", "kolkata": "West Bengal", "ahmedabad": "Gujarat", "vijayawada": "Andhra Pradesh",
    "visakhapatnam": "Andhra Pradesh", "vizag": "Andhra Pradesh", "noida": "Uttar Pradesh", "gurugram": "Haryana",
    "gurgaon": "Haryana",
}
_PLACE_NAMES = {s.lower(): s for s in OTHER_STATES} | OTHER_PLACE_ALIASES
_PLACE_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(p) for p in sorted(_PLACE_NAMES, key=len, reverse=True)) + r")\b", re.IGNORECASE
)


def other_places(message: str) -> list[str]:
    """States other than Telangana that the message names, in order of first mention."""
    found = []
    text = re.sub(r"\s+", " ", message.replace("&", " and "))
    for m in _PLACE_PATTERN.finditer(text):
        state = _PLACE_NAMES[m.group(1).lower()]
        if state not in found:
            found.append(state)
    return found


def answer_question(question: str, history: list[dict], session_id: str = "") -> dict:
    """Returns {"kind", "answer", "sources", "question", "lock_reason"}; "question" is what was retrieved/answered.

    The caller has already checked the raw message (and the sticky lock) before this runs, so the
    rewrite below is never reached for a message that is itself a penalty question.
    """
    def locked(stage, reason, text):
        log_lock(stage, reason, session_id, text)
        return {"kind": "restricted", "answer": PENALTY_LOCKED_MESSAGE, "sources": [], "question": standalone_question,
                "lock_reason": reason}

    standalone_question = contextualize_question(question, history)
    if not PENALTY_ANSWERS_ENABLED:
        # A follow-up like "and for a bike?" can turn into a penalty question once rewritten.
        reason = penalty_lock_reason(standalone_question)
        if reason:
            return locked("rewritten_question", reason, standalone_question)

    docs = retrieve(standalone_question)
    if not docs:
        return {"kind": "no_support", "answer": NO_SUPPORT_MESSAGE, "sources": [], "question": standalone_question}
    chain = strict_prompt | llm | StrOutputParser()
    answer = chain.invoke({"context": format_docs(docs), "question": standalone_question})
    if not PENALTY_ANSWERS_ENABLED:
        # The model drifted into penalty territory from a non-penalty question: withhold it.
        reason = answer_drift_reason(answer)
        if reason:
            return locked("answer_drift", reason, answer)
    return {"kind": "answer", "answer": answer, "sources": source_entries(docs), "question": standalone_question}


# Session state is in-memory only (fine for a single local dev server).
sessions: dict[str, dict] = {}

app = FastAPI(title="Telangana Traffic Rules Assistant API")


class ChatRequest(BaseModel):
    message: str
    session_id: str


class Source(BaseModel):
    title: str
    instrument: str | None = None
    verified: bool
    file: str
    sha256: str | None = None


class ChatResponse(BaseModel):
    response: str
    kind: str  # answer | no_support | restricted | out_of_scope | unavailable | missing_provision | clarification
    sources: list[Source] = []
    kb_approved: bool


MAX_HISTORY_TURNS = 4
PROVIDER_ERROR = "The answering service is temporarily unavailable. Please try again in a minute."


def reply(kind: str, text: str, sources=()) -> ChatResponse:
    return ChatResponse(response=text, kind=kind, sources=list(sources), kb_approved=KB_APPROVED)


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    ensure_approval_current()
    session = sessions.setdefault(req.session_id, {"history": []})
    message = req.message.strip()

    def restricted(stage, reason):
        log_lock(stage, reason, req.session_id, message)
        session["last_locked"] = True
        return reply("restricted", PENALTY_LOCKED_MESSAGE)

    places = other_places(message)
    if places:
        return reply("out_of_scope", OUT_OF_SCOPE_MESSAGE.format(places=", ".join(places)))
    # Both lock checks run before any model call (including the contextual rewrite).
    if not PENALTY_ANSWERS_ENABLED:
        reason = penalty_lock_reason(message)
        if reason:
            return restricted("message", reason)
        if session.get("last_locked") and is_vague_follow_up(message):
            return restricted("sticky_follow_up", "follows_locked_turn")
    if not index_ready():
        return reply("unavailable", UNAVAILABLE_MESSAGE)
    missing, present = missing_references(message)
    if missing:
        # Deterministic: no retrieval, no rewrite, no model call, nothing substituted for the missing rule.
        return reply("missing_provision", missing_provision_message(missing, present))
    central_text = classify_rule_references(message).central_text
    if central_text:
        # Asks what a Central rule says: only citations of it are indexed, never its text. No model call.
        return reply("missing_provision", central_rule_message(central_text))
    ambiguous = ambiguous_references(message)
    if ambiguous:
        # "Rule 10" exists in both the TMVR and the TMVTR: ask, never pick one silently. No model call.
        return reply("clarification", clarification_message(ambiguous))

    try:
        result = answer_question(message, session["history"], req.session_id)
    except Exception:
        raise HTTPException(status_code=503, detail=PROVIDER_ERROR)
    session["last_locked"] = result["kind"] == "restricted"
    if result["kind"] == "answer":
        session["history"].append({"question": result["question"], "answer": result["answer"]})
        session["history"] = session["history"][-MAX_HISTORY_TURNS:]
        return reply("answer", with_penalty_note(result["answer"]), result["sources"])
    return reply(result["kind"], result["answer"])


@app.post("/approval/refresh")
def approval_refresh():
    """Revalidate the approval record against the index (and corpus). Full scan: keep behind admin access."""
    status_ = refresh_approval()
    return {"approval": status_.state, "approval_errors": status_.errors, "kb_approved": KB_APPROVED,
            "penalty_answers": PENALTY_ANSWERS_ENABLED}


@app.get("/status")
def status():
    ensure_approval_current()
    return {
        "state": ASSISTANT_STATE,
        "index": INDEX_INFO["index"],
        "chunks": INDEX_INFO["chunks"],
        "detail": INDEX_INFO["detail"],
        "profile": INDEX_PROFILE.name,
        "kb_approved": KB_APPROVED,
        "legal_review": "approved" if KB_APPROVED else "pending",
        "penalty_answers": PENALTY_ANSWERS_ENABLED,
        # No reviewer details here; problems are technical descriptions only.
        "approval": APPROVAL.state,
        "approval_errors": APPROVAL.errors,
        "corpus_version": APPROVAL.record.corpus_version if KB_APPROVED else None,
    }


@app.get("/health")
def health():
    return {"status": "ok"}


FRONTEND_DIR = BASE_DIR / "frontend"


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
