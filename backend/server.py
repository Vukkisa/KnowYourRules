"""
FastAPI backend for the Telangana Traffic Rules Assistant.
Serves the frontend at /, answers questions at POST /chat and reports the knowledge-base state at GET /status.

Run with:
    uvicorn backend.server:app --reload --port 8000
(from the project root)

Scope: Telangana state instruments, plus selected Central provisions (Motor Vehicles Act extract, Driving Regulations 2017)
kept under their own "Central" tag. The Central Motor Vehicles Rules, 1989 and other states are not covered.
The Telangana knowledge base is under legal review (docs/legal-sources/telangana-traffic/), so:
  - the server starts without an index and reports it as unavailable instead of crashing;
  - penalty / fine / compounding questions get a fixed "not yet verified" reply, without calling the
    model. (The signed legal-approval record that used to open them was removed; they stay locked.)
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

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from langchain.chat_models import init_chat_model
from langchain_chroma import Chroma
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.documents import Document

from backend import (answer_cache, api_protection, chat_guards, document_identity, document_lifecycle, embedding_provider, exact_vector,
                     grounded_answer, hybrid_retrieval, index_snapshot, legal_approval, provision_validity_runtime, providers, rag_profiles,
                     release_gates, runtime_config, source_status)
from backend import offence_date as offence_routing

BASE_DIR = Path(__file__).resolve().parent.parent
# .env is read only when the process environment says TG_ENVIRONMENT=development, and never overrides it.
runtime_config.load_local_env()

ASSISTANT_STATE = "Telangana"
# Chunks the index may hold and /chat may serve. Central instruments are kept under their own "Central" tag, never relabelled
# as Telangana; any other state (or an untagged chunk) is still refused.
CENTRAL_STATE = "Central"
SERVED_STATES = (ASSISTANT_STATE, CENTRAL_STATE)
# A separate directory and collection: the shared multi-state index is never read or modified here.
TG_COLLECTION = "telangana-traffic-rules"
# Stage 7A: with TG_SNAPSHOT_STORE set, the index and the lifecycle registry come from ONE verified snapshot (backend/index_snapshot.py)
# and TG_DB_DIR / TG_LIFECYCLE_DIR must not be set. A snapshot that fails to load points both at paths that do not exist: the index
# is "missing" (nothing is ever created) and the lifecycle filter fails closed. Without TG_SNAPSHOT_STORE nothing changes.
SNAPSHOT = index_snapshot.activate_from_env()
_UNAVAILABLE_DIR = BASE_DIR / ".snapshot-unavailable"
if SNAPSHOT.enabled:
    TG_DB_DIR = SNAPSHOT.db_dir if SNAPSHOT.ready else _UNAVAILABLE_DIR / "index"
    _SNAPSHOT_LIFECYCLE_ENV = {"TG_LIFECYCLE_DIR": str(SNAPSHOT.lifecycle_dir if SNAPSHOT.ready else _UNAVAILABLE_DIR / "lifecycle")}
else:
    TG_DB_DIR = Path(os.environ.get("TG_DB_DIR", BASE_DIR / "chroma_telangana_db"))
    _SNAPSHOT_LIFECYCLE_ENV = None


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------------------------------
# Answer mode. Safe by default: with no configuration, no model is ever called and every question that passes
# the deterministic guards gets a fixed "not available" reply.
#   disabled      - default. No model client is even constructed.
#   grounded      - TG_GROUNDED_ANSWERS=1. Validated answers (see grounded_gate_errors).
#   legacy_dev    - TG_LEGACY_DEV_ANSWERS=1 AND TG_ENVIRONMENT=development AND a GROQ_API_KEY. Unvalidated
#                   free text, labelled as development output. For local development only.
#                   Rejected in staging and production. Not suitable for public legal-answer traffic: an operator
#                   who sets these variables deliberately gets unvalidated output, labelled as such.
#   misconfigured - an unsafe combination (both modes, dev mode outside development, dev mode without a key,
#                   an unrecognised TG_ENVIRONMENT). Behaves like disabled; never falls back to another mode.
# Configuration precedence and .env handling: see backend/runtime_config.py.
# ---------------------------------------------------------------------------------------------------
def resolve_answer_mode(grounded: bool, legacy_dev: bool, environment: str, groq_key: str) -> tuple[str, list]:
    problems = []
    environment = (environment or "").strip().lower()
    if environment and environment not in runtime_config.KNOWN_ENVIRONMENTS:
        problems.append("TG_ENVIRONMENT must be development, staging or production")
    if grounded and legacy_dev:
        problems.append("TG_GROUNDED_ANSWERS and TG_LEGACY_DEV_ANSWERS cannot both be enabled")
    if legacy_dev and environment != "development":
        problems.append("TG_LEGACY_DEV_ANSWERS requires TG_ENVIRONMENT=development")
    if legacy_dev and (not groq_key or "placeholder" in groq_key):
        problems.append("TG_LEGACY_DEV_ANSWERS requires a GROQ_API_KEY")
    if problems:
        return "misconfigured", problems
    if grounded:
        return "grounded", []
    if legacy_dev:
        return "legacy_dev", []
    return "disabled", []


GROUNDED_ANSWERS_ENABLED = env_flag("TG_GROUNDED_ANSWERS")
ANSWER_MODE, ANSWER_MODE_PROBLEMS = resolve_answer_mode(
    GROUNDED_ANSWERS_ENABLED, env_flag("TG_LEGACY_DEV_ANSWERS"), os.environ.get("TG_ENVIRONMENT", ""),
    os.environ.get("GROQ_API_KEY", ""))
if ANSWER_MODE_PROBLEMS:
    logging.getLogger(__name__).error("answer mode misconfigured, all answers disabled: %s", ANSWER_MODE_PROBLEMS)


# Optional: the source documents; when set, they are hashed and compared with the record too.
CORPUS_DIR = Path(os.environ["TG_CORPUS_DIR"]) if os.environ.get("TG_CORPUS_DIR") else None
try:
    APPROVAL_RECHECK_SECONDS = max(30.0, float(os.environ.get("TG_APPROVAL_RECHECK_SECONDS", "300")))
except ValueError:
    APPROVAL_RECHECK_SECONDS = 300.0

# Stage 7A: query embeddings come from EMBEDDING_PROVIDER (default ollama, exactly as before; openai_compatible for cloud). The choice is
# independent of the generation providers, never falls back to another provider, and every failure raises EmbeddingUnavailable.
EMBEDDING = embedding_provider.build_embeddings(embedding_provider.EmbeddingSettings.from_env())
embeddings_model = rag_profiles.ProfileEmbeddings(EMBEDDING)


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
    if ASSISTANT_STATE not in states or not states <= set(SERVED_STATES):
        # Telangana plus the separately tagged Central instruments only: chunks without a state, or from another state, are refused.
        return {"index": "invalid", "chunks": len(metadatas),
                "detail": "The index contains chunks that are not tagged Telangana or Central; rebuild it."}
    return {"index": "ready", "chunks": len(metadatas), "detail": "Telangana index loaded."}


vector_store = open_store()
INDEX_INFO = inspect_index(vector_store)


def index_metadatas(store) -> list:
    try:
        return store.get(include=["metadatas"])["metadatas"] if store is not None else []
    except Exception:
        return []


# ---------------------------------------------------------------------------------------------------
# Revalidation lifecycle. A signed legal-approval record (legal/telangana-approval.json, its .sig file and a
# trusted-keys file) is NOT required to answer: that gate was removed. What still decides whether a question can
# be answered is the source-status registry, the document lifecycle (only approved, active versions are served),
# the index, snapshot and embedding checks, and the rule-matrix release gates. Those inputs are validated at
# startup and on POST /approval/refresh; every request runs a cheap fingerprint check, and a change marks the
# inputs stale (grounded answers off) until a refresh succeeds.
# ---------------------------------------------------------------------------------------------------
_approval_lock = threading.RLock()
# "kb_approved" in /status and /chat, which the unchanged frontend turns into "Approved" / "Pending counsel" and the
# "not legally reviewed" badge. No signed record is read any more, so nothing can set it: it stays False, and no code
# path uses it to allow or block an answer.
KB_APPROVED = False
PENALTY_ANSWERS_ENABLED = False
# Verified title and instrument keyed by document SHA-256. It was filled only from a signed record; with that gone it
# stays empty, so every source keeps its unverified label. Nothing here can mark a source verified.
SOURCES: dict[str, tuple[str, str]] = {}


class _ServedHashes:
    """What a citation may name: a file hash the document lifecycle serves (the active version, or one retained for dated
    questions). With no lifecycle configured every well-formed hash passes, as everywhere else in the lifecycle filter."""

    def __contains__(self, sha256) -> bool:
        return LIFECYCLE.servable_on(sha256, True)


SERVED = _ServedHashes()
# Stage 25: text status of each source (legal-status/source-status.json).
SOURCE_STATUS_FILE = Path(os.environ.get("TG_SOURCE_STATUS_FILE", BASE_DIR / "legal-status" / "source-status.json"))
SOURCE_STATUS = source_status.Registry("absent", ["not loaded"])
_FINGERPRINT = None
_STALE = False
_LAST_VALIDITY_CHECK = 0.0
# Step 4: provision-level validity (backend/provision_validity_runtime.py), off by default and unchanged. Its own signed
# ledger chain is a separate opt-in layer; it still needs TG_APPROVAL_FILE / TG_TRUSTED_KEYS_FILE if someone turns it on, and
# it can only REMOVE chunks. The server no longer has an approval of its own to bind it to, so restrict mode serves nothing.
VALIDITY = provision_validity_runtime.from_env(
    os.environ, approval_file=Path(os.environ["TG_APPROVAL_FILE"]) if os.environ.get("TG_APPROVAL_FILE") else None,
    trusted_keys=Path(os.environ["TG_TRUSTED_KEYS_FILE"]) if os.environ.get("TG_TRUSTED_KEYS_FILE") else None,
    source_status_file=SOURCE_STATUS_FILE, corpus_dir=CORPUS_DIR)


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
    """Cheap: hash of the source-status registry, index id + count, corpus file sizes/mtimes, validity inputs."""
    return (
        _small_file_digest(SOURCE_STATUS_FILE),
        _index_fingerprint(),
        _corpus_fingerprint(),
        VALIDITY.fingerprint(),
    )


def load_source_status():
    """Registry validated against the index (and corpus, if configured). Invalid -> every source warns."""
    global SOURCE_STATUS
    metadatas = index_metadatas(vector_store) if INDEX_INFO["index"] == "ready" else None
    SOURCE_STATUS = source_status.load(SOURCE_STATUS_FILE, metadatas, corpus_dir=CORPUS_DIR)
    if not SOURCE_STATUS.valid:
        logging.getLogger(__name__).warning("source-status registry %s: %s", SOURCE_STATUS.state,
                                            SOURCE_STATUS.errors[:5])
    return SOURCE_STATUS


_DIAGNOSTICS = {"key": None, "value": []}


def source_status_diagnostics() -> list:
    """Categorised disagreements between the status file (git), the restored index and the lifecycle registry (R2 snapshot); see
    source_status.diagnose. Read-only: nothing is reconciled, approved or rewritten. Cached until an input changes."""
    lifecycle = globals().get("LIFECYCLE")
    lc_path = lifecycle.path if (lifecycle is not None and lifecycle.enabled) else None
    key = (approval_fingerprint(), lifecycle.digest() if lc_path is not None else None)
    if _DIAGNOSTICS["key"] != key:
        metadatas = index_metadatas(vector_store) if INDEX_INFO["index"] == "ready" else []
        _DIAGNOSTICS["value"] = source_status.diagnose(SOURCE_STATUS_FILE, metadatas, lc_path)
        _DIAGNOSTICS["key"] = key
        for d in _DIAGNOSTICS["value"]:
            logging.getLogger(__name__).warning("source-status consistency: category=%s document=%s", d["category"], d["document"])
    return _DIAGNOSTICS["value"]


def _load_validity():
    """Run the signed-ledger acceptance gate. No-op while the layer is off. approval_valid is False: the server has no
    approval record any more, so a layer that is switched on stays fail-closed."""
    global _LAST_VALIDITY_CHECK
    if VALIDITY.enabled:
        VALIDITY.load(index_metadatas(vector_store) if INDEX_INFO["index"] == "ready" else [],
                      registry_sha256=getattr(SOURCE_STATUS, "sha256", None) if SOURCE_STATUS.valid else None,
                      approval_valid=False)
        _LAST_VALIDITY_CHECK = time.monotonic()
        if VALIDITY.state != "accepted":
            logging.getLogger(__name__).warning("provision validity (%s): %s; %s", VALIDITY.mode, VALIDITY.state, VALIDITY.problems[:3])


def refresh_approval():
    """Full revalidation of the registry and validity inputs. The only way back from "stale"."""
    global _FINGERPRINT, _STALE
    with _approval_lock:
        _FINGERPRINT = approval_fingerprint()
        load_source_status()
        _STALE = False
        _load_validity()
        return not _STALE


def ensure_approval_current():
    """Per-request check. Marks the inputs stale on any detected change; never revalidates by itself."""
    global _FINGERPRINT, _STALE
    with _approval_lock:
        current = approval_fingerprint()
        if current != _FINGERPRINT:
            _FINGERPRINT = current
            _STALE = True
            VALIDITY.invalidate()      # a changed input never leaves an older acceptance in force; only refresh_approval re-accepts
            return
        if VALIDITY.enabled and VALIDITY.accepted and time.monotonic() - _LAST_VALIDITY_CHECK >= APPROVAL_RECHECK_SECONDS:
            _load_validity()           # periodic re-acceptance: a chain that no longer passes stops serving


refresh_approval()
INDEX_PROFILE = rag_profiles.profile_of_index(vector_store)
embeddings_model.profile = INDEX_PROFILE


def index_dimensions(store):
    """Dimensionality of the stored vectors (read-only), or None when it cannot be read."""
    try:
        got = store._collection.get(limit=1, include=["embeddings"])["embeddings"]
        return len(got[0]) if len(got) else None
    except Exception:  # noqa: BLE001
        return None


def configure_embedding_guard():
    """Tell the embedding guard what the index requires (size, model family, probe vectors) and, for a hosted provider, check it now.
    A failure here never stops the server: the guard simply refuses to produce query vectors (and /status says why)."""
    emb = (SNAPSHOT.manifest or {}).get("embedding", {}) if SNAPSHOT.ready else {}
    EMBEDDING.configure_index(dims=emb.get("dimensions") or (index_dimensions(vector_store) if vector_store is not None else None),
                              family=emb.get("family"), probes=emb.get("probes"), min_cosine=emb.get("min_cosine"))
    if EMBEDDING.settings.verification_required and EMBEDDING.probes and EMBEDDING.state in ("unverified", "unavailable"):
        try:
            EMBEDDING.verify()
        except embedding_provider.EmbeddingUnavailable as err:
            logging.getLogger(__name__).warning("embedding provider not verified at startup: %s", err.reason)
    logging.getLogger(__name__).warning("embedding provider: %s", {k: v for k, v in EMBEDDING.health().items() if k != "verification"})


configure_embedding_guard()

# The Groq client exists only in legacy development mode; in every other mode there is nothing to call.
llm = init_chat_model("openai/gpt-oss-120b", model_provider="groq") if ANSWER_MODE == "legacy_dev" else None


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
        ids = {i for i in PROVISION_CATALOGUE.get(ref, set()) if eligible_manifest(i)}   # Stage 6D: eligible documents only
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
    return eligible_lookup(LEXICAL_INDEX.lookup(message, list(dict.fromkeys(refs)), None if scope == CENTRAL else scope))


def eligible_lookup(lookup):
    """Stage 6D: the 'which instrument do you mean' candidates must not name documents the lifecycle does not serve. Candidates
    that are not eligible (or not recognised) are dropped; fewer than two left means there is nothing ambiguous to ask about.
    Matched documents are left alone: retrieve() filters them, and removing them here would change which retrieval path runs."""
    if not LIFECYCLE.enabled:
        return lookup
    names = {name: prefix for prefix, name in hybrid_retrieval.INSTRUMENTS.items()}
    kept = []
    for label, options in lookup.ambiguous:
        ok = []
        for option in options:
            go = re.match(r"G\.O\.Ms\.No\. (\d+)/(\d{4})$", option)
            if go:
                manifest = LEXICAL_INDEX.gos.get((int(go.group(1)), go.group(2)))
                if manifest and eligible_manifest(manifest):
                    ok.append(option)
            elif option in names and eligible_prefix(names[option]):
                ok.append(option)
        if len(ok) > 1:
            kept.append((label, ok))
    return hybrid_retrieval.Lookup(documents=lookup.documents, ambiguous=kept, missing_gos=lookup.missing_gos)


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
context below, which comes from Telangana state instruments (Rules, Acts and Government Orders) and
from a few selected Central provisions. Cite the source document exactly as given in the "Source:" tag on
each context chunk. The Source tag says whether the document is an Act, Rules or a G.O. - never call one
by another's name. If a Source tag says the source is unverified, say so when you cite it.

This knowledge base covers Telangana, plus selected sections of the Central Motor Vehicles Act, 1988 and
the Central Motor Vehicles (Driving) Regulations, 2017, kept separate and labelled Central. It does NOT
include the Central Motor Vehicles Rules, 1989 or any other state's law. If answering properly would
need those, say so plainly instead of filling the gap from memory.

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


def source_passage(doc, cited: bool = False) -> dict:
    """One retrieved chunk as the UI's "View source" shows it: the stored text without its header line, which
    repeats the document title, and a label built from metadata. The text itself is never rewritten.

    "cited" is True only when a validated grounded answer cites this chunk. Development output is unvalidated
    free text, so its chunks are only "retrieved": nothing confirms which of them the answer used."""
    m = doc.metadata
    label = " - ".join(x for x in (m.get("provision_id"), m.get("provision_heading")) if x) or "Passage"
    if (m.get("parts") or 1) > 1:
        label += f" (part {m.get('part')} of {m['parts']})"
    head, sep, body = doc.page_content.partition("\n")
    # Provenance of this one chunk. A source row may group several files of one document, so every passage
    # keeps its own chunk id, file, hash and location.
    return {"provision_id": m.get("provision_id") or None, "label": label, "text": body if sep else head,
            "cited": cited, "chunk_id": grounded_answer.chunk_id_of(m), "manifest_id": m.get("manifest_id") or None,
            "file": m.get("source_file", "unknown"), "sha256": chunk_hash(m), "chapter": m.get("chapter") or None,
            "location": m.get("location") or None}


def source_entries(docs, cited: bool = False) -> list[dict]:
    """Distinct source documents of the given chunks, for the UI, in retrieval order, each with its passages.
    Pass cited=True only for the chunks a validated grounded answer cites.

    One row is one logical document (backend/document_identity.py): the chapter files of the Rules share a row,
    listed under "files". Files are grouped only when they have a valid hash, the same approval state and approved
    title, and identical describing metadata; anything else keeps one row per file, as before. "file" and "sha256"
    are the first file of the row; "files" has all of them."""
    groupable = document_identity.consistent_document_ids(d.metadata for d in docs)
    entries, by_key = [], {}
    for d in docs:
        source_file = d.metadata.get("source_file", "unknown")
        h = chunk_hash(d.metadata)
        title, instrument = SOURCES.get(h, (None, None))
        doc_id = document_identity.logical_document_id(d.metadata)
        if h and doc_id in groupable:
            key = ("document", doc_id, h in SOURCES, title, instrument)
        else:  # no hash or inconsistent metadata: never merged with another file
            key, doc_id = h or ("file", source_file), d.metadata.get("manifest_id") or None
        if key not in by_key:
            by_key[key] = {"title": title or "Unverified source", "instrument": instrument,
                           "verified": h in SOURCES, "file": source_file, "sha256": h, "document_id": doc_id,
                           "files": [], "passages": []}
            entries.append(by_key[key])
        file_ref = {"file": source_file, "sha256": h, "manifest_id": d.metadata.get("manifest_id") or None}
        if file_ref not in by_key[key]["files"]:
            by_key[key]["files"].append(file_ref)
        passage = source_passage(d, cited)
        if passage not in by_key[key]["passages"]:
            by_key[key]["passages"].append(passage)
    for e in entries:  # text status is separate from "verified" (approval) and never derived from it
        statuses = {source_text_status(f["sha256"], docs) for f in e["files"]}
        e["text_status"] = next(s for s in STATUS_SEVERITY if s in statuses)  # the most cautious of its files
    return entries


# Most cautious first: a source shows the strongest status of any of its chunks in this answer.
STATUS_SEVERITY = ("known_amendments_unresolved", source_status.UNRECORDED, source_status.UNCONFIRMED_CURRENT,
                   "unverified_snapshot", "official_text_commencement_unconfirmed", "verified_current")


def source_text_status(sha256, docs) -> str:
    statuses = set()
    for d in docs:
        if chunk_hash(d.metadata) == sha256:
            s = SOURCE_STATUS.lookup(sha256, d.metadata.get("provision_id")).status
            statuses.add(source_status.UNCONFIRMED_CURRENT if s == "verified_current" else s)
    return next((s for s in STATUS_SEVERITY if s in statuses), source_status.UNRECORDED)


def source_warnings(docs, citation_numbers=None) -> list[dict]:
    return source_status.collect_warnings(SOURCE_STATUS, docs, citation_numbers, trust_verified=False)


def with_status_block(text: str, warnings: list[dict]) -> str:
    """Fixed-template warnings appended to the answer text, so every client (old or new) shows them."""
    if not warnings:
        return text
    lines = [f"- {w['text']}" + ("".join(f" [{n}]" for n in w["citations"]) if w.get("numbered") else "")
             for w in warnings]
    return text + "\n\nSource status:\n" + "\n".join(lines)


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


# How many of the vector search's top chunks fusion may not drop (RAG_VECTOR_PROTECT; 0 turns the guard off; default 3).
VECTOR_PROTECT = hybrid_retrieval.parse_vector_protect(os.environ.get("RAG_VECTOR_PROTECT", "3"), RETRIEVE_K)

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


# Vector search: "exact" ranks every stored chunk by the collection's own squared-L2 distance, with chunk id as
# tie-breaker, so identical stored data always gives identical results. "hnsw" keeps Chroma's approximate
# index, shown in Stage 15 to miss true nearest neighbours and to vary between opens of identical copies.
# RAG_VECTOR_SEARCH=hnsw is the explicit fallback; exact also falls back if its snapshot cannot be built.
VECTOR_SEARCH = os.environ.get("RAG_VECTOR_SEARCH", "exact").strip().lower()
if VECTOR_SEARCH not in ("exact", "hnsw"):
    VECTOR_SEARCH = "exact"


def _build_exact_index():
    if VECTOR_SEARCH != "exact" or vector_store is None:
        return None
    try:
        return exact_vector.ExactVectorIndex.from_store(vector_store)
    except Exception:
        return None


EXACT_INDEX = _build_exact_index()


def vector_search(question: str) -> list:
    """(Document, squared-L2 distance) pairs from the served states only (one filtered search per state, merged by distance);
    exact when available, otherwise Chroma's HNSW."""
    merged = []
    for state in SERVED_STATES:
        where = {"state": state}
        hits = None
        if EXACT_INDEX is not None:
            try:
                hits = EXACT_INDEX.similarity_search_with_score(question, k=RETRIEVE_K, filter=where)
            except ValueError:
                hits = None
        if hits is None:
            hits = vector_store.similarity_search_with_score(question, k=RETRIEVE_K, filter=where)
        if not isinstance(hits, list):
            return hits      # malformed result: passed on unchanged for relevant_docs() to reject
        merged.extend(hits)
    try:
        merged.sort(key=lambda item: float(item[1]))
    except (TypeError, ValueError, IndexError):
        return merged        # malformed scores: unsorted, and relevant_docs() drops them
    return merged[:RETRIEVE_K]


def retrieve(question: str) -> list:
    """Retrieval filtered to the served states (Telangana and the separately tagged Central instruments), never another state."""
    return _retrieve(question, None)[0]


def retrieve_dated(question: str, offence_date):
    """(docs, TemporalRouting) for an offence date. Only chunks whose own valid_from/valid_to cover the date come
    back; chunks with no usable validity metadata are never returned (they are not evidence of the law on that date)."""
    return _retrieve(question, offence_date)


def _retrieve(question: str, offence_date) -> tuple:
    if vector_store is None or VALIDITY.serving_errors():
        # Step 4: in restrict mode nothing is retrieved until the signed ledger chain has been accepted.
        return [], (offence_routing.route_documents([], offence_date) if offence_date else None)
    docs = relevant_docs(vector_search(question))
    vector_docs, exact_lookup = docs, False
    if RETRIEVAL_MODE == "hybrid" and LEXICAL_INDEX is not None:
        lookup = provision_lookup(question)
        exact_lookup = bool(lookup.documents)
        # Every candidate, whichever list it came from, goes through the same filters below.
        docs = hybrid_retrieval.reciprocal_rank_fusion(
            [lookup.documents, LEXICAL_INDEX.search(question, RETRIEVE_K), docs])
    seen, unique = set(), []
    for d in docs:
        if d.metadata.get("state") not in SERVED_STATES:
            continue
        if not LIFECYCLE.servable_on(chunk_hash(d.metadata), offence_date is not None):
            # Stage 6: only the approved, active version of a document may be served (disabled without a registry). A DATED
            # question may also use a retained historical version; its own validity range then has to cover the date.
            continue
        if offence_date is None and not offence_routing.in_force_today(d.metadata):
            continue  # current law only: a text whose range ended, has not begun, or is malformed is not served as current
        if d.metadata.get("answer_eligible") is False:
            continue  # flagged at build time (e.g. unreliable table extraction): stored for review only
        # Chunk identity, not a text prefix: chunks of one G.O. share a long title header, so a prefix key
        # would collapse distinct paragraphs into one.
        key = hybrid_retrieval.chunk_key(d)
        if key not in seen:
            seen.add(key)
            unique.append(d)
    if VALIDITY.enabled:
        # Step 4: the accepted ledger may only remove what the checks above allowed (restrict) or log what it would (shadow).
        unique = VALIDITY.filter(unique, offence_date)
    routing = None
    if offence_date is not None:
        # Every candidate, from every list, is routed by its own validity dates before ranking is trimmed. Unversioned
        # and malformed chunks leave here: nothing downstream (fusion protection, chapter spreading) can bring them back.
        routing = offence_routing.route_documents(unique, offence_date)
        unique = list(routing.authoritative)
    top = unique[:RETRIEVE_K]
    if RETRIEVAL_MODE == "hybrid" and LEXICAL_INDEX is not None:
        if VECTOR_PROTECT and not exact_lookup:
            # Stage 4D: a keyword-only match must not push out one of the vector search's own best chunks.
            top = hybrid_retrieval.protect_vector_leaders(top, unique, vector_docs, VECTOR_PROTECT, RETRIEVE_K)
        top = LEXICAL_INDEX.spread_named_chapters(question, top)  # reorders the same chunks, never changes them
    top = hybrid_retrieval.promote_age_limit(question, top)  # reorders the same chunks, never adds or removes one
    return [with_text_status(d) for d in top], routing


def with_text_status(doc):
    """A copy of the document whose metadata carries its registry text status (the stored chunk is not changed)."""
    m = dict(getattr(doc, "metadata", None) or {})
    m["text_status"] = SOURCE_STATUS.lookup(m.get("sha256"), m.get("provision_id")).status
    return Document(page_content=doc.page_content, metadata=m, id=getattr(doc, "id", None))


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
contextualize_chain = (contextualize_prompt | llm | StrOutputParser()) if llm is not None else None


def format_history(history: list[dict]) -> str:
    if not history:
        return "(none yet)"
    lines = []
    for turn in history:
        lines.append(f"User: {turn['question']}")
        lines.append(f"Assistant: {turn['answer']}")
    return "\n".join(lines)


def contextualize_question(question: str, history: list[dict]) -> str:
    if not history or contextualize_chain is None:
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


# ---------------------------------------------------------------------------------------------------
# Grounded (evidence-contract) answering.
#
# Model-call paths in /chat (everything else - guards, retrieval, approval - is local):
#   1. contextualize_chain (Groq): rewrites follow-ups when there is chat history.   Legacy mode only.
#   2. strict_prompt | llm (Groq): free-text answer.                                    Legacy mode only.
#   3. ANSWER_GENERATOR.generate: grounded answer. Defaults to DisabledGenerator (no model), and is reached only
#      when grounded_gate_errors() is empty.
# With TG_GROUNDED_ANSWERS on, paths 1 and 2 are unreachable: follow-ups are handled locally and deterministically.
# With it off (the default), the legacy path is unchanged and CAN still call Groq when a key is configured.
# ---------------------------------------------------------------------------------------------------
# Grounded mode: Groq -> Gemini -> Ollama (backend/providers.py), still reached only after the gate above passes.
# Every other mode: DisabledGenerator, so nothing can be called.
ANSWER_GENERATOR: grounded_answer.AnswerGenerator = (
    providers.from_env() if ANSWER_MODE == "grounded" else grounded_answer.DisabledGenerator())
if isinstance(ANSWER_GENERATOR, providers.ProviderOrchestrator):
    logging.getLogger("kyr.providers").info("grounded providers: %s", providers.safe_json(
        {p["name"]: {k: p[k] for k in ("model", "enabled", "configured")}
         for p in ANSWER_GENERATOR.status()["providers"]}))
PROVIDERS_UNAVAILABLE_MESSAGE = (
    "The answer service is temporarily unavailable, so I can't answer from the Telangana documents right now. "
    "Please try again later, or check the official Telangana Transport Department sources."
)

GROUNDED_UNAVAILABLE_MESSAGE = (
    "Answers from the Telangana documents aren't available yet: they need a completed legal review first. "
    "Please check the official Telangana Transport Department sources."
)
DEV_OUTPUT_BANNER = ("DEVELOPMENT OUTPUT - unverified model text, not a Telangana legal answer and not legal "
                     "advice. Do not rely on it.\n\n")
GROUNDED_FOLLOW_UP_MESSAGE = (
    "Please ask your full question on its own (for example, name the rule, vehicle or document) - I don't "
    "rewrite follow-up questions in this mode."
)


def grounded_gate_errors() -> list[str]:
    """Every prerequisite for grounded generation; any entry blocks it. No signed approval record is required."""
    errors = []
    if not GROUNDED_ANSWERS_ENABLED or ANSWER_MODE != "grounded":
        errors.append("grounded answers are not enabled")
    if CORPUS_DIR is None:
        errors.append("no corpus directory configured, so source files are not hash-checked")
    if _STALE:
        errors.append("source inputs changed since the last validation; revalidation required")
    if not SOURCE_STATUS.valid:
        errors.append(f"source-status registry is {SOURCE_STATUS.state}")
    if PENALTY_ANSWERS_ENABLED:
        errors.append("penalty answers are enabled")
    if LIFECYCLE.enabled and not LIFECYCLE.ready():
        errors.append("document lifecycle registry is not ready: no approved, consistent document can be served")
    if EMBEDDING.state in ("misconfigured", "incompatible"):
        errors.append("query embedding provider is misconfigured or incompatible with the index")
    if SNAPSHOT.enabled and not SNAPSHOT.ready:
        errors.append("index snapshot is not loaded and verified")
    errors.extend(VALIDITY.serving_errors())  # restrict: no legal chunk before the signed ledger chain has been accepted
    return errors


# Stage 6: document lifecycle registry (TG_LIFECYCLE_DIR). Unset = no extra filtering. Set = fail-closed: a chunk is served
# only if its file hash is the approved, active version of its source (backend/document_lifecycle.py). Read-only here.
LIFECYCLE = document_lifecycle.ServeFilter.from_env(_SNAPSHOT_LIFECYCLE_ENV)  # snapshot mode: the snapshot's own registry directory
if LIFECYCLE.enabled:
    # Stage 6D: check the registry and audit chain at startup and tell the filter what the index really holds. Whatever this
    # finds, the filter stays on: an unreadable/inconsistent state serves nothing, it never falls back to unrestricted retrieval.
    import collections as _collections
    LIFECYCLE.reconcile(_collections.Counter((m or {}).get("sha256") for m in index_metadatas(vector_store)))
    LIFECYCLE_STARTUP = LIFECYCLE.health()
    logging.getLogger(__name__).warning("document lifecycle filter enabled: state=%s servable_documents=%s problems=%s",
                                        LIFECYCLE_STARTUP["state"], LIFECYCLE_STARTUP["servable_documents"],
                                        LIFECYCLE_STARTUP["problems"][:3])
else:
    LIFECYCLE_STARTUP = {"enabled": False}
MANIFEST_SHAS: dict = {}
for _m in index_metadatas(vector_store) if LIFECYCLE.enabled else []:
    if (_m or {}).get("manifest_id") and (_m or {}).get("sha256"):
        MANIFEST_SHAS.setdefault(_m["manifest_id"], set()).add(_m["sha256"])


def eligible_manifest(manifest_id) -> bool:
    """Does the lifecycle serve any version of this document? (Always True when the lifecycle is not enabled.)"""
    if not LIFECYCLE.enabled:
        return True
    return any(LIFECYCLE.servable(sha) for sha in MANIFEST_SHAS.get(manifest_id, ()))


def eligible_prefix(prefix: str) -> bool:
    return any(eligible_manifest(m) for m in MANIFEST_SHAS if m.startswith(prefix))

# ---------------------------------------------------------------------------------------------------
# Stage 5: answer cache (backend/answer_cache.py). Off unless TG_CACHE=exact|semantic; TG_CACHE_DISABLED=1 is a kill
# switch. It stores only the validated raw model output and REPLAYS it through build_contract + validate (penalty gate
# and Stage 4F/4G masks included) against live context documents on every hit. It sits after the approval gate, the
# penalty lock and the vague-follow-up check, so none of those can be bypassed.
# ---------------------------------------------------------------------------------------------------
CACHE_SETTINGS = answer_cache.settings_from_env()
ANSWER_CACHE = answer_cache.AnswerCache(CACHE_SETTINGS)
if CACHE_SETTINGS.semantic:  # transparent memo: the cache lookup and the retrieval share one query embedding
    embeddings_model.embed_query = answer_cache.EmbeddingMemo(embeddings_model.embed_query,
                                                              key=f"{getattr(embeddings_model.base, 'model', '')}")
_CODE_DIGEST = answer_cache.digest([hashlib.sha256((BASE_DIR / "backend" / f).read_bytes()).hexdigest()
                                    for f in ("grounded_answer.py", "meaning_checks.py", "eligibility_status.py",
                                              "benign_wording.py", "answer_cache.py")
                                    if (BASE_DIR / "backend" / f).is_file()])
_LIVE = {"at": 0.0, "fp": None, "map": {}}


def cache_epoch() -> str:
    """Digest of every input that decides what an answer may say. Any change makes every older entry unusable."""
    return answer_cache.digest(
        _FINGERPRINT, _STALE, sorted(SOURCES),
        getattr(SOURCE_STATUS, "sha256", None), INDEX_PROFILE.name, INDEX_PROFILE.chunking, INDEX_PROFILE.query_prefix,
        INDEX_PROFILE.doc_prefix, rag_profiles.CHUNK_SIZE, rag_profiles.CHUNK_OVERLAP,
        getattr(getattr(embeddings_model, "base", None), "model", None), getattr(getattr(embeddings_model, "base", None), "provider", None),
        RETRIEVAL_MODE, RETRIEVE_K, MAX_DISTANCE,
        VECTOR_PROTECT, VECTOR_SEARCH, PENALTY_ANSWERS_ENABLED, type(ANSWER_GENERATOR).__name__, id(ANSWER_GENERATOR),
        _CODE_DIGEST, LIFECYCLE.digest(), VALIDITY.digest())


def chunk_identity(doc) -> str:
    return answer_cache.digest(hybrid_retrieval.chunk_key(doc))


def live_chunks() -> dict:
    """identity -> stored chunk, read from the live collection (re-read when the index fingerprint changes or every
    TG_CACHE_VERIFY_SECONDS)."""
    fp, now = _index_fingerprint(), time.monotonic()
    if fp != _LIVE["fp"] or now - _LIVE["at"] >= CACHE_SETTINGS.verify_seconds:
        got = vector_store.get(include=["documents", "metadatas"])
        _LIVE.update(fp=fp, at=now, map={chunk_identity(d): d for d in (
            Document(page_content=t, metadata=m or {}) for t, m in zip(got["documents"], got["metadatas"]))})
    return _LIVE["map"]


def cache_context(ids):
    """The cached answer's context documents, as the live index has them and under retrieve()'s own filters; None if
    any is gone, changed, no longer approved or not answer-eligible."""
    try:
        known = live_chunks()
    except Exception:
        return None
    docs = []
    for i in ids:
        d = known.get(i)
        m = getattr(d, "metadata", None) or {}
        if (d is None or m.get("state") not in SERVED_STATES or m.get("answer_eligible") is False
                or not LIFECYCLE.servable(chunk_hash(m))
                or not offence_routing.in_force_today(m)):
            return None
        docs.append(with_text_status(d))
    if VALIDITY.enabled and len(VALIDITY.filter(docs)) != len(docs):
        return None  # a cached answer may not use a chunk the signed ledger would now remove
    return docs


def cache_replay(question: str, entry, docs):
    """Validate the cached model output again, now, against these documents. (text, cited, cited_docs) or None."""
    contract, kept = grounded_answer.build_contract(question, docs)
    res = grounded_answer.validate(entry.raw, contract, penalty_reason=answer_drift_reason)
    if not res.ok or res.answer is None or res.answer.evidence_sufficiency != "sufficient":
        return None
    text, cited = grounded_answer.render(res.answer, contract)
    index = {e.evidence_id: n for n, e in enumerate(contract.evidence)}
    cited_docs = [kept[index[e.evidence_id]] for e in cited]
    if tuple(chunk_identity(d) for d in cited_docs) != entry.cited_ids:
        return None
    if provision_validity_runtime.citation_errors(cited, cited_docs, SERVED):
        return None
    return text, cited, cited_docs


def cached_response(question: str, text: str, cited, cited_docs) -> dict:
    """Same assembly as a fresh answer: backend-built Cited block, live sources, live source warnings."""
    text += "\n\nCited:\n" + "\n".join(f"[{n}] {grounded_answer.citation_label(e)}" for n, e in enumerate(cited, 1))
    warnings = [dict(w, numbered=True) for w in source_warnings(cited_docs, list(range(1, len(cited_docs) + 1)))]
    return {"kind": "answer", "answer": with_status_block(text, warnings), "sources": source_entries(cited_docs, cited=True),
            "question": question, "source_warnings": [{k: v for k, v in w.items() if k != "numbered"} for w in warnings]}


def cache_sweep():
    """Drop cache entries from an older epoch as soon as the epoch has moved, even on requests that are then refused (a blocked
    state must not leave answers from before it lying around). Never raises."""
    if CACHE_SETTINGS.enabled:
        try:
            ANSWER_CACHE.note_epoch(cache_epoch())
        except Exception:  # noqa: BLE001
            pass


def cache_begin(question: str):
    if not CACHE_SETTINGS.enabled:
        return None
    if answer_cache.uncacheable_reason(question):
        ANSWER_CACHE.stats["bypass_uncacheable"] += 1
        return None
    epoch = cache_epoch()
    ANSWER_CACHE.note_epoch(epoch)
    flags = answer_cache.risk_flags(question)
    return {"key": answer_cache.normalize_query(question), "epoch": epoch, "flags": flags,
            "sig": answer_cache.signature(question), "semantic": CACHE_SETTINGS.semantic and not flags}


def cache_exact(question: str, ctx):
    entry = ANSWER_CACHE.lookup_exact(ctx["key"], ctx["epoch"])
    if entry is None:
        return None
    docs = cache_context(entry.context_ids)
    replay = cache_replay(question, entry, docs) if docs is not None else None
    if replay is None:
        ANSWER_CACHE.drop(entry, "source" if docs is None else "revalidation")
        return None
    entry.hits += 1
    ANSWER_CACHE.stats["hit_exact"] += 1
    return cached_response(question, *replay)


def cache_query_vector(question: str):
    try:
        return embeddings_model.embed_query(question)
    except Exception:
        return None


def cache_semantic(question: str, ctx, docs):
    """Only after a FRESH retrieval: the cached answer must have been generated from exactly this context."""
    vector = cache_query_vector(question)
    found = ANSWER_CACHE.lookup_semantic(vector, ctx["sig"], ctx["epoch"], [chunk_identity(d) for d in docs]) \
        if vector is not None and docs else None
    if found is None:
        return None
    entry, similarity = found
    replay = cache_replay(question, entry, docs)
    if replay is None:
        # The entry may be perfectly good for the question it was made for; it just does not validate for this one.
        ANSWER_CACHE.stats["semantic_replay_rejected"] += 1
        return None
    entry.hits += 1
    ANSWER_CACHE.stats["hit_semantic"] += 1
    return cached_response(question, *replay)


def cache_store(question: str, ctx, docs, result):
    if not (result.kind == "answer" and not result.errors and result.raw and result.cited_docs):
        ANSWER_CACHE.stats["store_skipped"] += 1
        return
    vector = cache_query_vector(question) if ctx["semantic"] else None
    ANSWER_CACHE.put(ctx["key"], ctx["sig"], vector, ctx["epoch"], result.raw, [chunk_identity(d) for d in docs],
                     [chunk_identity(d) for d in result.cited_docs],
                     sorted({(chunk_hash(d.metadata) or "", d.metadata.get("manifest_id")) for d in docs}), ctx["flags"])


def grounded_answer_question(question: str, history: list[dict], session_id: str = "", offence_date=None) -> dict:
    """Grounded mode. No legacy model call can happen here: the only model entry point is ANSWER_GENERATOR,
    after every approval prerequisite has passed."""
    gate = grounded_gate_errors()
    if gate:
        logging.getLogger(__name__).info("grounded answers blocked: %s", gate)
        cache_sweep()
        return {"kind": "unavailable", "answer": GROUNDED_UNAVAILABLE_MESSAGE, "sources": [], "question": question}
    if history and is_vague_follow_up(question):
        # Deterministic: a context-dependent follow-up is not rewritten by a model; the user restates it.
        return {"kind": "clarification", "answer": GROUNDED_FOLLOW_UP_MESSAGE, "sources": [], "question": question}
    reason = penalty_lock_reason(question)  # penalties stay locked in grounded mode, whatever the approval says
    if reason:
        log_lock("grounded_question", reason, session_id, question)
        return {"kind": "restricted", "answer": PENALTY_LOCKED_MESSAGE, "sources": [], "question": question,
                "lock_reason": reason}
    # The answer cache is keyed on the question alone, so a dated question never reads or writes it.
    cache_ctx = cache_begin(question) if offence_date is None else None
    if cache_ctx:
        hit = cache_exact(question, cache_ctx)
        if hit:
            return hit
        ANSWER_CACHE.stats["miss_exact"] += 1
    # Stage 4: per-stage wall-clock timings for the log line (perf_counter; no content, no secrets)
    started = time.perf_counter()
    routing = None
    if offence_date is not None:
        retrieved, routing = retrieve_dated(question, offence_date)
    else:
        retrieved = retrieve(question)
    docs = list(retrieved)  # retrieve() already serves only what the document lifecycle serves
    retrieval_ms = (time.perf_counter() - started) * 1000
    if offence_date is not None and not docs:
        return temporal_refusal(question, offence_date, routing)
    if cache_ctx and cache_ctx["semantic"]:
        hit = cache_semantic(question, cache_ctx, docs)
        if hit:
            return hit
        ANSWER_CACHE.stats["miss_semantic"] += 1
    orchestrator = ANSWER_GENERATOR if isinstance(ANSWER_GENERATOR, providers.ProviderOrchestrator) else None
    session = orchestrator.session() if orchestrator else None
    answer_started = time.perf_counter()
    stages: dict = {}  # local per-stage ms accumulated across every answer() call
    result = grounded_answer.answer(question, docs, session or ANSWER_GENERATOR, penalty_reason=answer_drift_reason,
                                    stage_ms=stages)
    candidates = 1
    # A candidate the validator rejected may be replaced by ONE answer from the next provider (bounded by
    # PROVIDER_VALIDATION_FALLBACKS); it goes through the same answer()/validate() pipeline from scratch. A refusal
    # or "insufficient evidence" is never "rejected", so it is never sent to another model.
    while (session and result.kind == "rejected" and not session.exhausted and not session.blocked
           and candidates <= orchestrator.settings.validation_fallbacks and session.advance("validation_rejected")):
        if result.errors:
            logging.getLogger(__name__).warning("grounded answer %s: %s", result.contract.request_id, result.errors)
        candidates += 1
        result = grounded_answer.answer(question, docs, session, penalty_reason=answer_drift_reason,
                                        stage_ms=stages)
    answer_ms = (time.perf_counter() - answer_started) * 1000
    mapping_errors = (provision_validity_runtime.citation_errors(result.cited, result.cited_docs, SERVED)
                      if result.kind in ("answer", "conflict") else [])
    if mapping_errors:  # every citation must map to one approved document and one provision, or nothing is cited
        logging.getLogger(__name__).warning("grounded answer %s: citation mapping failed: %s", result.contract.request_id,
                                            mapping_errors[:3])
    if cache_ctx and result.kind == "answer" and not mapping_errors:
        cache_store(question, cache_ctx, docs, result)  # never raises: storage errors are counted, not propagated
    if result.errors:
        logging.getLogger(__name__).warning("grounded answer %s: %s", result.contract.request_id, result.errors)
    produced = bool(session) and any(a.outcome == "ok" for a in session.attempts)
    if session and session.exhausted and not produced:
        kind = "unavailable"  # every provider failed: a safe reply, never an ungrounded answer
    else:
        kind = {"answer": "answer", "conflict": "conflict", "clarification": "clarification"}.get(result.kind,
                                                                                                   "no_support")
    if mapping_errors:
        kind = "no_support"  # fail closed: an answer whose citations do not map exactly is withheld

    def finish(response: dict) -> dict:
        if session:
            summary = dict(session.summary(), request_id=result.contract.request_id, candidates=candidates,
                           validation=result.kind, validation_errors=len(result.errors), final=kind)
            generation_ms, wait_ms = summary.get("generation_ms") or 0, summary.get("wait_ms") or 0
            summary["timings_ms"] = {
                "retrieval": round(retrieval_ms, 1),
                "answer": round(answer_ms, 1),               # every answer() call: contract, prompt, model, validation
                "generation": generation_ms,                 # provider HTTP time inside it, every attempt
                "retry_wait": wait_ms,                       # back-off sleeps between retries
                "local": round(max(answer_ms - generation_ms - wait_ms, 0.0), 1),  # contract, prompt, validation, render
                "response": round((time.perf_counter() - response_started) * 1000, 1),  # sources and warnings
                "total": round((time.perf_counter() - started) * 1000, 1)}
            # contract / prompt / validate / render: the parts of "local" that answer() can separate
            summary["local_stages_ms"] = {k: round(v, 2) for k, v in sorted(stages.items())}
            orchestrator.record_request({k: v for k, v in summary.items() if k != "calls"})
            logging.getLogger("kyr.providers").info("grounded generation %s", providers.safe_json(summary))
        return response

    response_started = time.perf_counter()
    if kind == "unavailable":
        return finish({"kind": "unavailable", "answer": PROVIDERS_UNAVAILABLE_MESSAGE, "sources": [],
                       "question": question})
    text = result.text if kind != "no_support" else NO_SUPPORT_MESSAGE
    if kind in ("answer", "conflict"):  # [n] markers refer to these backend-built labels, never model-written ones
        text += "\n\nCited:\n" + "\n".join(f"[{n}] {grounded_answer.citation_label(e)}"
                                         for n, e in enumerate(result.cited, 1))
    sources = source_entries(result.cited_docs, cited=True) if kind in ("answer", "conflict") else []
    warnings = []
    if kind in ("answer", "conflict"):
        warnings = [dict(w, numbered=True) for w in
                    source_warnings(result.cited_docs, list(range(1, len(result.cited_docs) + 1)))]
        text = with_status_block(text, warnings)
    out = {"kind": kind, "answer": text, "sources": sources, "question": question,
           "source_warnings": [{k: v for k, v in w.items() if k != "numbered"} for w in warnings]}
    if offence_date is not None:
        out["temporal"] = temporal_info(offence_date, routing)
    return finish(out)


def penalty_lock_active() -> bool:
    """True unless the Telangana fine gate is open. That gate is locked in code (release_gates.TELANGANA_LOCKED), so
    this is True today whatever the approval record or TG_PENALTY_ANSWERS says."""
    return not release_gates.gate_open(current_release_gates()[2], release_gates.TG_FINE)


def temporal_info(offence_date, routing) -> dict:
    return {"offence_date": offence_date.isoformat(), "law_band": offence_routing.band_for(offence_date),
            "notes": list(routing.notes) if routing is not None else []}


def temporal_refusal(question: str, offence_date, routing) -> dict:
    """No chunk is dated to cover the offence date: no model call, nothing presented as the law on that date."""
    return {"kind": "no_support", "answer": chat_guards.TEMPORAL_UNVERIFIED_MESSAGE.format(date=offence_date.isoformat()),
            "sources": [], "question": question, "temporal": temporal_info(offence_date, routing)}


def answer_question(question: str, history: list[dict], session_id: str = "", offence_date=None) -> dict:
    """Returns {"kind", "answer", "sources", "question", "lock_reason"}; "question" is what was retrieved/answered.

    The caller has already checked the raw message (and the sticky lock) before this runs, so the
    rewrite below is never reached for a message that is itself a penalty question.
    """
    def locked(stage, reason, text):
        log_lock(stage, reason, session_id, text)
        return {"kind": "restricted", "answer": PENALTY_LOCKED_MESSAGE, "sources": [], "question": standalone_question,
                "lock_reason": reason}

    if ANSWER_MODE == "grounded":
        if offence_date is not None:
            return grounded_answer_question(question, history, session_id, offence_date)
        return grounded_answer_question(question, history, session_id)  # never reaches the legacy model calls
    if ANSWER_MODE != "legacy_dev":
        # disabled or misconfigured: no model call, no fallback to another mode
        return {"kind": "unavailable", "answer": GROUNDED_UNAVAILABLE_MESSAGE, "sources": [], "question": question}
    standalone_question = contextualize_question(question, history)
    lock_on = penalty_lock_active()
    if lock_on:
        # A follow-up like "and for a bike?" can turn into a penalty question once rewritten.
        reason = penalty_lock_reason(standalone_question)
        if reason:
            return locked("rewritten_question", reason, standalone_question)

    routing = None
    if offence_date is not None:
        docs, routing = retrieve_dated(standalone_question, offence_date)
        if not docs:
            return temporal_refusal(standalone_question, offence_date, routing)
    else:
        docs = retrieve(standalone_question)
    if not docs:
        return {"kind": "no_support", "answer": NO_SUPPORT_MESSAGE, "sources": [], "question": standalone_question}
    chain = strict_prompt | llm | StrOutputParser()
    answer = chain.invoke({"context": format_docs(docs), "question": standalone_question})
    if lock_on:
        # The model drifted into penalty territory from a non-penalty question: withhold it.
        reason = answer_drift_reason(answer)
        if reason:
            return locked("answer_drift", reason, answer)
    # Development output only: unvalidated model text, never presented as a Telangana legal answer.
    warnings = source_warnings(docs)
    out = {"kind": "development", "answer": with_status_block(DEV_OUTPUT_BANNER + answer, warnings),
           "sources": source_entries(docs), "question": standalone_question, "source_warnings": warnings}
    if offence_date is not None:
        out["temporal"] = temporal_info(offence_date, routing)
    return out


# Session state is in-memory only, and bounded (OCI pilot Stage 1): a capped, idle-expiring store instead of an unbounded dict.
# It is created before the app so the limits come from the same validated configuration. See api_protection.SessionStore.
PROTECTION = api_protection.config_from_env()      # read once; also used below for the request guards
sessions = api_protection.SessionStore(PROTECTION.max_sessions, PROTECTION.session_ttl_seconds)

app = FastAPI(title="Telangana Traffic Rules Assistant API")

# OCI pilot Stage 1: in-process protection of POST /chat only (rate limit per client, request-body cap, concurrent-question cap).
# Counters live in this process: per worker, not distributed, so production keeps ONE worker. Installed before CORS so that the
# CORS middleware wraps it and the frontend can read a 429/413. See backend/api_protection.py.
app.add_middleware(api_protection.ProtectionMiddleware, config=PROTECTION)
QUESTION_SLOTS = api_protection.ConcurrencyLimiter(PROTECTION.max_concurrent)

# Stage 7A: the static frontend (GitHub Pages) is another origin. Off unless TG_CORS_ORIGINS lists exact origins; never "*", never
# credentials, only the two methods and one header the frontend uses. Same-origin use (served by this app) needs none of it.
CORS_ORIGINS, CORS_REJECTED = runtime_config.cors_origins()
CORS_PROBLEMS = runtime_config.cors_problems()      # production: an explicit, non-empty, valid, non-localhost list is mandatory
if CORS_REJECTED:
    logging.getLogger(__name__).error("TG_CORS_ORIGINS entries ignored (must be exact https origins): %s", CORS_REJECTED)
for _problem in CORS_PROBLEMS:
    logging.getLogger(__name__).error("CORS configuration: %s (CORS stays closed: no browser origin is allowed)", _problem)
if CORS_ORIGINS:
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
                       allow_credentials=False, max_age=600)


class ChatRequest(BaseModel):
    message: str
    session_id: str = Field(max_length=api_protection.MAX_SESSION_ID_LENGTH)   # the frontend sends a 36-character UUID
    # Date of the offence, YYYY-MM-DD or DD-MM-YYYY. Never inferred from the message. Absent: no date-specific claim is made.
    offence_date: str | None = Field(default=None, max_length=32)


class SourcePassage(BaseModel):
    provision_id: str | None = None
    label: str
    text: str
    cited: bool = False  # True: a validated grounded answer cites it. False: retrieved only (development output)
    chunk_id: str | None = None  # manifest::provision::part{n}of{m}, as in the retrieval benchmark
    manifest_id: str | None = None
    file: str | None = None  # the file this chunk was read from; a source row can group several
    sha256: str | None = None
    chapter: str | None = None
    location: str | None = None


class SourceFile(BaseModel):
    file: str
    sha256: str | None = None
    manifest_id: str | None = None


class Source(BaseModel):
    title: str
    instrument: str | None = None
    verified: bool
    file: str  # first file of the row; "files" lists every file
    sha256: str | None = None
    document_id: str | None = None  # logical document: chapter files of one instrument share it
    files: list[SourceFile] = []
    text_status: str | None = None  # Stage 25: registry text status; independent of "verified" (approval)
    passages: list[SourcePassage] = []  # the chunks this answer used from the source, for "View source"


class SourceWarning(BaseModel):
    warning_id: str
    status: str
    text: str  # fixed backend template, never model-written
    source_file: str | None = None
    sha256: str | None = None
    provision_id: str | None = None
    related_instruments: list[str] = []
    decision_refs: list[str] = []
    citations: list[int] = []


class ChatResponse(BaseModel):
    response: str
    kind: str  # answer | conflict | development | no_support | restricted | out_of_scope | unavailable | missing_provision | clarification
    sources: list[Source] = []
    kb_approved: bool
    source_warnings: list[SourceWarning] = []
    offence_date: str | None = None   # echoed only when the request carried a valid one
    law_band: str | None = None       # offence_date.band_for(); a label, not a statement of what the law was
    notes: list[str] = []             # fixed backend notes about temporal evidence


MAX_HISTORY_TURNS = 4
PROVIDER_ERROR = "The answering service is temporarily unavailable. Please try again in a minute."
EMBEDDING_ERROR = ("The search service is temporarily unavailable, so your question was not searched or answered. "
                   "Please try again in a minute.")


def reply(kind: str, text: str, sources=(), warnings=(), temporal=None) -> ChatResponse:
    temporal = temporal or {}
    return ChatResponse(response=text, kind=kind, sources=list(sources), kb_approved=KB_APPROVED,
                        source_warnings=list(warnings), offence_date=temporal.get("offence_date"),
                        law_band=temporal.get("law_band"), notes=list(temporal.get("notes", ())))


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    ensure_approval_current()
    try:
        session = sessions.setdefault(req.session_id, {"history": []})
    except api_protection.SessionCapacityExceeded as full:
        # Every slot holds a live conversation. A new one is refused (never an existing one evicted); nothing was processed.
        raise HTTPException(status_code=503, detail=api_protection.GENERIC_SESSIONS_FULL,
                            headers={"Retry-After": str(full.retry_after)})
    message = req.message.strip()

    def restricted(stage, reason):
        log_lock(stage, reason, req.session_id, message)
        session["last_locked"] = True
        return reply("restricted", PENALTY_LOCKED_MESSAGE)

    places = other_places(message)
    if places:
        return reply("out_of_scope", OUT_OF_SCOPE_MESSAGE.format(places=", ".join(places)))
    # The offence date is explicit input only. An unusable one is refused, never dropped (dropping it would answer
    # as if no date had been given).
    offence_date, date_error = chat_guards.parse_request_date(req.offence_date)
    if date_error:
        return reply("clarification", date_error)
    matrix, _matrix_error, gates = current_release_gates()
    temporal = {"offence_date": offence_date.isoformat(), "law_band": offence_routing.band_for(offence_date)} if offence_date else None
    if chat_guards.COMPOUNDING_RE.search(message):
        # Compounding vocabulary is penalty vocabulary to the classifier below, so this runs first. It can only refuse, ask
        # for the offence date or name a Section 200(1) listing status from the verified matrix: never an amount, and a
        # message that also asks for penalty content once the compounding words are removed is refused.
        penalty_cue = penalty_lock_reason(chat_guards.COMPOUNDING_RE.sub(" ", message)) is not None
        guard = chat_guards.evaluate(message, matrix, gates, offence_date, penalty_cue=penalty_cue)
        logging.getLogger(__name__).info("chat guard: kind=%s gate=%s section_200=%s", guard.kind, guard.gate, guard.section_200)
        session["last_locked"] = True  # a short follow-up ("and for a bike?") to a compounding turn stays locked
        text = PENALTY_LOCKED_MESSAGE if guard.kind == "restricted" else guard.text  # one message for the penalty family
        return reply(guard.kind, text, temporal=temporal)
    # Both lock checks run before any model call (including the contextual rewrite). The Telangana fine gate is
    # locked in code, so this holds whatever TG_PENALTY_ANSWERS or the approval record says.
    if not release_gates.gate_open(gates, release_gates.TG_FINE):
        reason = penalty_lock_reason(message)
        if reason:
            return restricted("message", reason)
        if session.get("last_locked") and is_vague_follow_up(message):
            return restricted("sticky_follow_up", "follows_locked_turn")
    if not index_ready() or not integrity_ready():
        return reply("unavailable", UNAVAILABLE_MESSAGE)
    if LIFECYCLE.enabled and not LIFECYCLE.ready():
        # Stage 6D: no consistent approved document: nothing, not even "which instrument do you mean" or "no such rule", may be
        # said about the contents of documents that are not served.
        cache_sweep()
        return reply("unavailable", GROUNDED_UNAVAILABLE_MESSAGE)
    if VALIDITY.serving_errors():
        # Step 4 (restrict): the signed ledger chain has not been accepted, so nothing may be said about the legal corpus.
        cache_sweep()
        return reply("unavailable", GROUNDED_UNAVAILABLE_MESSAGE)
    missing, present = missing_references(message)
    if missing:
        # Deterministic: no retrieval, no rewrite, no model call, nothing substituted for the missing rule.
        return reply("missing_provision", missing_provision_message(missing, present))
    rule_check = classify_rule_references(message)
    central_text = rule_check.central_text
    if central_text:
        # Asks what a Central rule says: only citations of it are indexed, never its text. No model call.
        return reply("missing_provision", central_rule_message(central_text))
    ambiguous = ambiguous_references(message)
    if ambiguous:
        # "Rule 10" exists in both the TMVR and the TMVTR: ask, never pick one silently. No model call.
        return reply("clarification", clarification_message(ambiguous))
    guard = chat_guards.evaluate(message, matrix, gates, offence_date, rule_reference_handled=bool(rule_references(message)))
    if guard:
        # Release gates, Section 200(1) disclosure and date bands: deterministic, no retrieval, no model call.
        logging.getLogger(__name__).info("chat guard: kind=%s gate=%s section_200=%s", guard.kind, guard.gate, guard.section_200)
        if guard.lock:
            session["last_locked"] = True
        return reply(guard.kind, guard.text, temporal=temporal)

    try:
        # Only the expensive part holds a permit; the deterministic replies above never do. No waiting: busy means refused.
        with QUESTION_SLOTS.slot():
            result = (answer_question(message, session["history"], req.session_id, offence_date) if offence_date is not None
                      else answer_question(message, session["history"], req.session_id))
    except api_protection.CapacityExceeded:
        raise HTTPException(status_code=503, detail=api_protection.GENERIC_BUSY,
                            headers={"Retry-After": str(api_protection.BUSY_RETRY_AFTER_SECONDS)})
    except embedding_provider.EmbeddingUnavailable:
        # Stage 7A: the question could not be embedded, so it was NOT searched and NOT answered. Nothing is substituted.
        raise HTTPException(status_code=503, detail=EMBEDDING_ERROR)
    except Exception:
        raise HTTPException(status_code=503, detail=PROVIDER_ERROR)
    session["last_locked"] = result["kind"] == "restricted"
    if result["kind"] in ("answer", "conflict", "development"):
        session["history"].append({"question": result["question"], "answer": result["answer"]})
        session["history"] = session["history"][-MAX_HISTORY_TURNS:]
        text = with_penalty_note(result["answer"])
        notes = (result.get("temporal") or {}).get("notes") or ()
        if notes:
            text += "\n\n" + "\n".join(notes)
        return reply(result["kind"], text, result["sources"], result.get("source_warnings", ()), result.get("temporal"))
    return reply(result["kind"], result["answer"], temporal=result.get("temporal"))


# Stage 7A: read once at startup, like every other setting.
APPROVAL_REFRESH_ENABLED = (runtime_config.deployment_environment() not in ("staging", "production")
                            or env_flag("TG_ENABLE_APPROVAL_REFRESH"))


@app.post("/approval/refresh")
def approval_refresh():
    """Revalidate the source-status registry and validity inputs against the index (and corpus). Full scan: keep behind admin access."""
    if not APPROVAL_REFRESH_ENABLED:
        # Stage 7A: a public, unauthenticated full scan on a small host is an admin endpoint; off outside development unless chosen.
        raise HTTPException(status_code=404, detail="Not Found")
    refresh_approval()
    return {"approval": "not_required", "approval_errors": [], "kb_approved": KB_APPROVED,
            "penalty_answers": PENALTY_ANSWERS_ENABLED}


RULE_MATRIX_FILE = Path(os.environ.get("TG_RULE_MATRIX_FILE", BASE_DIR / "legal" / "rule-matrix.json"))
_MATRIX_CACHE = {"key": None, "value": (None, release_gates.ERR_NOT_FOUND)}


def _load_rule_matrix():
    """Cached by (mtime, size) so a public GET cannot force a file read and parse on every request."""
    try:
        st = RULE_MATRIX_FILE.stat()
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        key = None
    if key is None or key != _MATRIX_CACHE["key"]:
        _MATRIX_CACHE["value"] = release_gates.load_matrix(RULE_MATRIX_FILE)
        _MATRIX_CACHE["key"] = key
    return _MATRIX_CACHE["value"]


def current_release_gates():
    """Read-only. Gates open only as the rule matrix allows and never past the code locks (Telangana fines and
    compounding stay locked); a signed approval record is no longer needed."""
    ensure_approval_current()
    matrix, matrix_error = _load_rule_matrix()
    report = release_gates.effective_gates(matrix, PENALTY_ANSWERS_ENABLED)
    return matrix, matrix_error, report


@app.get("/release-gates")
def release_gates_view():
    """The same gate report /chat enforces (current_release_gates). Exposes gate states and coarse booleans, never
    paths, hashes, reviewer details, matrix content or error text."""
    matrix, matrix_error, report = current_release_gates()
    return {"gates": report.gates, "approval_valid": False,
            "matrix_loaded": matrix is not None, "matrix_problem": matrix_error is not None}


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
        "answer_mode": ANSWER_MODE,
        **({"validity_layer": VALIDITY.status()} if VALIDITY.enabled else {}),   # Step 4: mode and state only, no paths
        # No reviewer details here; problems are technical descriptions only.
        "approval": "not_required",
        "approval_errors": [],
        "corpus_version": None,
        # Names, models, switches and whether a key is set - never a key.
        "providers": (ANSWER_GENERATOR.status() if isinstance(ANSWER_GENERATOR, providers.ProviderOrchestrator)
                      else {"order": [], "providers": [], "available": False, "last_request": None}),
        # Stage 7A: query-embedding provider state (names, model, state; never a key, never a full URL).
        "embedding": {k: v for k, v in EMBEDDING.health().items() if k != "verification"},
        **({"snapshot": SNAPSHOT.public()} if SNAPSHOT.enabled else {}),
        # Only present when TG_LIFECYCLE_DIR is set. Process health is /health; corpus readiness is here.
        **({"lifecycle": dict(LIFECYCLE.health(), corpus_ready=corpus_ready())} if LIFECYCLE.enabled else {}),
        # True only when EVERY component the corpus needs is loaded and consistent (approval, index, lifecycle, embeddings, snapshot).
        "corpus_ready": corpus_ready(),
        "readiness": {k: ("ok" if v else "failed") for k, v in readiness_report()["checks"].items()},
        "cors": {"origins_configured": len(CORS_ORIGINS), "problems": CORS_PROBLEMS},
        "protection": PROTECTION.public(),      # limits and counts only: no proxy addresses, no client data
        "source_status": {"state": SOURCE_STATUS.state, **source_status.summarize(source_status_diagnostics())},
    }


def corpus_ready() -> bool:
    """Process health (/health) says nothing about this. The corpus is ready only when every required component is."""
    return bool(INDEX_INFO["index"] == "ready" and LIFECYCLE.ready() and EMBEDDING.ready()
                and (not SNAPSHOT.enabled or SNAPSHOT.ready))


@app.get("/health")
def health():
    """LIVENESS only: the process is up and answering HTTP. It says nothing about the corpus; see /ready (and /status)."""
    return {"status": "ok"}


PRODUCTION_LIKE = runtime_config.is_production_like()      # read once at startup, like every other setting
# Strict readiness (a restored snapshot, a lifecycle registry and a valid status registry are all REQUIRED) applies to a snapshot deployment
# and to any production-like cloud deployment. A self-hosted process that reads local directories keeps its previous behaviour.
STRICT_READINESS = SNAPSHOT.enabled or (PRODUCTION_LIKE and embedding_provider.cloud_mode())


def readiness_report() -> dict:
    """Every technical precondition for serving, each reduced to ok/failed (no paths, no secrets, no approval material).
    Readiness is about integrity, not legal approval: a verified snapshot whose sources are all still pending is READY and simply
    serves nothing (corpus_ready / `answering` says whether anything can be answered). Any failed check keeps readiness false."""
    strict = STRICT_READINESS
    checks = {}
    if SNAPSHOT.enabled:
        checks["snapshot_restore"] = SNAPSHOT.ready
        checks["snapshot_pinned"] = SNAPSHOT.ready and (SNAPSHOT.pinned or not PRODUCTION_LIKE)
    else:
        checks["snapshot_restore"] = not strict          # a cloud deployment must run from a restored, verified snapshot
        checks["snapshot_pinned"] = not strict
    manifest_chunks = ((SNAPSHOT.manifest or {}).get("index") or {}).get("chunk_count") if SNAPSHOT.ready else None
    checks["index_present"] = (INDEX_INFO["index"] == "ready" and INDEX_INFO["chunks"] > 0
                               and (manifest_chunks is None or INDEX_INFO["chunks"] == manifest_chunks))
    if LIFECYCLE.enabled:
        checks["lifecycle_registry_and_audit"] = LIFECYCLE.health().get("state") == "ok"
    else:
        checks["lifecycle_registry_and_audit"] = not strict
    checks["source_status_registry"] = SOURCE_STATUS.valid or not strict     # invalid/absent/mismatched status file: nothing may be answered
    checks["embedding"] = EMBEDDING.state == "ok"
    checks["configuration"] = not CORS_PROBLEMS
    return {"ready": all(checks.values()), "checks": checks}


def integrity_ready() -> bool:
    """The part of readiness that gates answering inside /chat (the embedding provider keeps its own, more specific, error path)."""
    r = readiness_report()["checks"]
    # the index itself is gated by index_ready() just before this call; /ready additionally compares its chunk count with the manifest
    return all(r[k] for k in ("snapshot_restore", "snapshot_pinned", "lifecycle_registry_and_audit"))


@app.get("/ready")
def readiness(response: Response):
    """READINESS: 200 only when the corpus was restored and verified and every check passes, otherwise 503. Cheap: no outbound calls."""
    report = readiness_report()
    if not report["ready"]:
        response.status_code = 503
    return {"ready": report["ready"], "answering": corpus_ready(),
            "checks": {k: ("ok" if v else "failed") for k, v in report["checks"].items()}}


FRONTEND_DIR = BASE_DIR / "frontend"


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
