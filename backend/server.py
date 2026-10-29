"""
FastAPI backend wrapping the RAG chain built in notebooks/rag_pipeline.ipynb.
Serves the frontend at / and answers questions at POST /chat.

Run with:
    uvicorn backend.server:app --reload --port 8000
(from the project root, GenAI/)
"""

import math
import os
import re
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

from backend import rag_profiles

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=True)

if not os.environ.get("GROQ_API_KEY") or "placeholder" in os.environ.get("GROQ_API_KEY", ""):
    raise RuntimeError("GROQ_API_KEY is missing or still a placeholder in .env")

# Queries must be embedded the way the index was built, so the profile is read from the index itself
# (see backend/rag_profiles.py). An index built before profiles were recorded is "baseline".
embeddings_model = rag_profiles.ProfileEmbeddings(OllamaEmbeddings(model="nomic-embed-text"))

vector_store = Chroma(
    collection_name="india-traffic-rules",
    embedding_function=embeddings_model,
    persist_directory=str(BASE_DIR / "chroma_langchain_db"),
)
INDEX_PROFILE = rag_profiles.profile_of_index(vector_store)
embeddings_model.profile = INDEX_PROFILE

llm = init_chat_model("openai/gpt-oss-120b", model_provider="groq")

def load_indexed_states(store) -> set[str]:
    """States (well, states + UTs + "Central") actually present in the index's chunk metadata.

    Raises instead of starting with an empty or unusable index. Read once at startup, so a
    rebuilt index needs a server restart.
    """
    try:
        metadatas = store.get(include=["metadatas"])["metadatas"]
    except Exception as e:
        raise RuntimeError(f"Could not read the vector index: {e}") from e
    if not metadatas:
        raise RuntimeError("The vector index is empty - run backend/build_index.py (it also recovers "
                           "an interrupted rebuild) before starting the server.")
    if any(not (m or {}).get("state") for m in metadatas):
        raise RuntimeError("Some indexed chunks have no 'state' metadata - rebuild with backend/build_index.py.")
    return {m["state"] for m in metadatas}


INDEXED_STATES = load_indexed_states(vector_store)

strict_template = """You are a traffic-rules assistant for India. Answer the question using ONLY
the context below, which comes from official government Acts, Rules and regulations. Cite the
source document and its state exactly as given in the "Source:" / "State:" tags on each context
chunk. The Source tag says whether the document is an Act or Rules - never call an Act "Rules" or
Rules an "Act". If a Source tag says the source is unverified, say so when you cite it.

{coverage_note}

If the context does not contain enough information to answer, say clearly that this specific
knowledge base does not cover it - do NOT use outside knowledge or guess. Never present a rule
from one state's documents as if it applies to a different state.

Context:
{context}

Question: {question}
"""
strict_prompt = ChatPromptTemplate.from_template(strict_template)


# Title and instrument of each indexed file, checked against the document's own title / short-title
# clause. Filenames are NOT reliable (two Central files carry other states' names), so anything
# not listed here is labelled unverified instead of guessed.
SOURCES = {
    "madhya-pradesh-mv-rules-1994-direct-pdf__a1988-59-b740e529.pdf":
        ("The Motor Vehicles Act, 1988", "Act"),
    "andaman-nicobar-islands-transport-acts-r__the-central-motor-vehicles-rules-1989-14ddf947.pdf":
        ("The Central Motor Vehicles Rules, 1989", "Rules"),
    "delhi-nct-transport-acts-and-rules-notif__delhi-motor-vehicles-rules-1993-as-amended-secreta-52c5b4c7.pdf":
        ("The Delhi Motor Vehicles Rules, 1993", "Rules"),
    "delhi-nct-transport-acts-and-rules-notif__the-delhi-motor-vehicle-taxation-act-r-2af515c1.pdf":
        ("The Delhi Motor Vehicles Taxation Act, 1962", "Act"),
    "delhi-nct-transport-acts-and-rules-notif__mact-6a89af46.pdf":
        ("The Delhi Motor Accidents Claims Tribunal Rules, 2008", "Rules"),
}


def describe_source(source_file: str) -> str:
    if source_file in SOURCES:
        title, instrument = SOURCES[source_file]
        return f"{title} ({instrument})"
    return f"Unverified source - title and whether it is an Act or Rules not verified (file: {source_file})"


def format_docs(docs):
    return "\n\n".join(
        f"Source: {describe_source(d.metadata.get('source_file', 'unknown'))}\nState: {d.metadata.get('state', 'unknown')}\n{d.page_content}"
        for d in docs
    )


# The indexed legal text has not been checked against the current official version, so any answer
# that mentions money or a penalty carries this note. It must not claim the text IS outdated.
PENALTY_PATTERN = re.compile(
    r"₹|\b(?:rs|inr)\b\.?|\brupees?\b|\b(?:fines?|penalty|penalties|compounding)\b"
    r"|\b(?:hundred|thousand|lakh|crore)\b",
    re.IGNORECASE,
)
PENALTY_NOTE = (
    "\n\n_Note: the date of the legal text this answer is based on has not been verified against the "
    "current official version. Fines and penalties are amended from time to time - check the current "
    "official text before relying on any amount._"
)


def with_penalty_note(answer: str) -> str:
    return answer + PENALTY_NOTE if PENALTY_PATTERN.search(answer) else answer


# Relevance gate on retrieved chunks. This collection uses Chroma's "l2" space, so the score from
# similarity_search_with_score() is the squared L2 distance; nomic-embed-text vectors are unit
# length, so distance = 2 - 2*cosine (0 = identical, up to 4; LOWER = MORE relevant).
# Default 0.88: measured on the indexed Central + Delhi corpus with 39 test questions, every question
# that should be answered had a best chunk at <= 0.848, and the clearly unrelated ones (cricket,
# recipe, gibberish, challan payment portal) were >= 0.915. It only screens out clearly unrelated
# questions - near-topic questions still rely on the grounding prompt. Recalibrate if the embedding
# model, distance space or corpus changes; override with RAG_MAX_DISTANCE.
# The default now comes from the index's retrieval profile: 0.88 (above) for "baseline"; a provisional
# 0.80 for "structured", whose task prefixes compress distances (see backend/rag_profiles.py).
DEFAULT_MAX_DISTANCE = INDEX_PROFILE.default_max_distance


def parse_max_distance(value) -> float:
    try:
        distance = float(value)
    except (TypeError, ValueError):
        return DEFAULT_MAX_DISTANCE
    return distance if math.isfinite(distance) and distance > 0 else DEFAULT_MAX_DISTANCE


MAX_DISTANCE = parse_max_distance(os.environ.get("RAG_MAX_DISTANCE"))

NO_SUPPORT_MESSAGE = (
    "I couldn't find sufficiently relevant information in the indexed official documents to answer "
    "that, so I won't guess. Try rephrasing your question about Indian traffic rules, or check the "
    "official sources directly."
)


def relevant_docs(results) -> list:
    """Keep documents from (doc, distance) pairs whose distance is a real number within MAX_DISTANCE.

    Anything malformed - missing or non-numeric scores, NaN, wrong shape, empty text - is dropped
    rather than treated as relevant.
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


def retrieve_for_state(question: str, state: str):
    """State-filtered retrieval with a Central-law fallback.

    Returns (docs, state_is_indexed). Central documents (the nationwide MV Act/Rules)
    are always included since they apply regardless of state; state-specific documents
    are added on top when that state is actually indexed. Only chunks that pass the
    relevance gate (MAX_DISTANCE) are returned.
    """
    central_docs = relevant_docs(
        vector_store.similarity_search_with_score(question, k=4, filter={"state": "Central"})
    )

    state_is_indexed = state in INDEXED_STATES and state != "Central"
    state_docs = []
    if state_is_indexed:
        state_docs = relevant_docs(
            vector_store.similarity_search_with_score(question, k=4, filter={"state": state})
        )

    seen = set()
    combined = []
    for d in state_docs + central_docs:
        key = (d.metadata.get("source_file"), d.page_content[:80])
        if key not in seen:
            seen.add(key)
            combined.append(d)

    return combined, (state_is_indexed or state == "Central")


contextualize_template = """Given the recent conversation history and a new message, rewrite the
new message as a fully self-contained question that includes whatever context from the history
is needed to understand it on its own (e.g. what violation, rule, or topic is being discussed).
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


def answer_question(question: str, state: str, history: list[dict]) -> tuple[str, str]:
    """Returns (answer, contextualized_question) - the latter is what actually got retrieved/answered."""
    standalone_question = contextualize_question(question, history)

    docs, state_covered = retrieve_for_state(standalone_question, state)
    if not docs:
        # Nothing passed the relevance gate - don't ask the model to answer without support.
        return NO_SUPPORT_MESSAGE, standalone_question
    if state_covered:
        coverage_note = f"The user is in {state}. State-specific documents for {state} are included below where relevant, alongside the nationwide Central Motor Vehicles Act/Rules."
    else:
        coverage_note = (
            f"IMPORTANT: No documents for {state} specifically are indexed in this knowledge base. "
            f"The context below is ONLY the nationwide Central Motor Vehicles Act/Rules, plus possibly "
            f"other states' documents that happened to match semantically - those other states' rules "
            f"do NOT apply to {state} and must not be presented as if they do. Tell the user plainly "
            f"that {state}-specific rules aren't in this knowledge base yet, and only answer using the "
            f"Central (nationwide) provisions if any are relevant."
        )
    context = format_docs(docs)
    chain = strict_prompt | llm | StrOutputParser()
    answer = chain.invoke({"context": context, "question": standalone_question, "coverage_note": coverage_note})
    return answer, standalone_question

# Traffic rules vary by Indian state, so we need to know where the user is before
# answering. Session state is in-memory only (fine for a single local dev server;
# would need a real store - Redis, a DB row - for multiple server processes).
sessions: dict[str, dict] = {}

location_extraction_template = """Look at this message from someone asking about Indian traffic rules.

1. Does it mention (directly or indirectly) an Indian state, city, or 6-digit PIN code? If so,
   name the STATE it corresponds to (e.g. a mention of "Ahmedabad" or "380001" means "Gujarat").
   If no location is mentioned, answer NONE.
2. Is the user trying to find out something - a rule, a fine, a requirement, a consequence?
   This includes describing a situation or a violation even with NO question mark and NO
   interrogative phrasing (e.g. "I jumped a red light", "I wasn't wearing a seatbelt", "my bike
   has no insurance") - all of those imply "what happens / what's the rule for this" and count as
   YES. Only answer NO if the message is JUST a location and nothing else.

Examples:
- "navi mumbai" -> HAS_QUESTION: NO (just a location, nothing else)
- "I jumped a red light" -> HAS_QUESTION: YES (implies: what's the penalty for this)
- "my helmet is not ISI marked" -> HAS_QUESTION: YES (implies: is this legal / what's the fine)
- "what is the seatbelt fine" -> HAS_QUESTION: YES

Message: "{message}"

Respond in exactly this format, nothing else:
LOCATION: <state name or NONE>
HAS_QUESTION: <YES or NO>
"""
location_extraction_prompt = ChatPromptTemplate.from_template(location_extraction_template)
location_extraction_chain = location_extraction_prompt | llm | StrOutputParser()


def extract_location_and_intent(message: str) -> tuple[str | None, bool]:
    # Provider errors propagate on purpose - /chat turns them into a 503 instead of guessing.
    raw = location_extraction_chain.invoke({"message": message})
    location = None
    has_question = True
    for line in raw.splitlines():
        line = line.strip()
        if line.upper().startswith("LOCATION:"):
            value = line.split(":", 1)[1].strip()
            location = None if value.upper() == "NONE" else value
        elif line.upper().startswith("HAS_QUESTION:"):
            has_question = line.split(":", 1)[1].strip().upper().startswith("Y")
    return location, has_question


# Canonical names must match the "state" metadata used in the index (backend/build_index.py).
STATES_AND_UTS = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat",
    "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh",
    "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan",
    "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
    "Andaman & Nicobar", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi",
    "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry",
]
STATE_ALIASES = {
    "nct of delhi": "Delhi", "national capital territory of delhi": "Delhi", "new delhi": "Delhi",
    "delhi nct": "Delhi", "andaman and nicobar islands": "Andaman & Nicobar", "orissa": "Odisha",
    "pondicherry": "Puducherry", "uttaranchal": "Uttarakhand",
}
# Names that span more than one state/UT - always ask instead of picking one.
AMBIGUOUS_LOCATIONS = {"ncr", "delhi ncr", "national capital region"}
IGNORED_LOCATION_WORDS = {"", "india"}


def _location_key(text: str) -> str:
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


KNOWN_LOCATIONS = {_location_key(s): s for s in STATES_AND_UTS}
KNOWN_LOCATIONS.update({_location_key(k): v for k, v in STATE_ALIASES.items()})


def normalize_state(raw: str | None) -> tuple[str | None, str]:
    """Map the extractor's free text to one canonical state.

    Returns (state, status) where status is "ok", "none", "ambiguous" or "multiple".
    Anything that doesn't map cleanly to exactly one known state never becomes a location.
    """
    if not raw:
        return None, "none"
    cleaned = re.sub(r"\(.*?\)", " ", raw)
    key = _location_key(cleaned)
    if key in AMBIGUOUS_LOCATIONS:
        return None, "ambiguous"
    if key in KNOWN_LOCATIONS:
        return KNOWN_LOCATIONS[key], "ok"
    # Split the raw text (before punctuation is stripped) so "Delhi, Gujarat" is seen as two parts.
    pieces = re.split(r"[,;/&]|\bvs\b|\bversus\b|\bor\b|\band\b", cleaned, flags=re.IGNORECASE)
    parts = [p for p in (_location_key(x) for x in pieces) if p not in IGNORED_LOCATION_WORDS]
    found = {KNOWN_LOCATIONS[p] for p in parts if p in KNOWN_LOCATIONS}
    if len(found) > 1:
        return None, "multiple"
    if found and len(found) < len(parts):
        return None, "ambiguous"
    if found:
        return found.pop(), "ok"
    return None, "none"


def state_from_pin(message: str) -> str | None:
    # Only the Delhi prefix (110xxx) is mapped: other PIN prefixes can cover more than one
    # state/UT, so those are left to the extractor and then validated by normalize_state.
    return "Delhi" if re.search(r"(?<!\d)110\d{3}(?!\d)", message) else None


# Lines that mimic the extractor's own output format are removed from user text, so a message
# can't hand the extractor a ready-made answer. normalize_state() is still the real gate.
CONTROL_LINE = re.compile(r"^\s*(?:LOCATION|HAS_QUESTION)\s*:.*$", re.IGNORECASE | re.MULTILINE)


def strip_control_lines(message: str) -> str:
    return CONTROL_LINE.sub("", message).strip()


app = FastAPI(title="India Traffic Rules RAG API")


class ChatRequest(BaseModel):
    message: str
    session_id: str


class ChatResponse(BaseModel):
    response: str


MAX_HISTORY_TURNS = 4
PROVIDER_ERROR = "The answering service is temporarily unavailable. Please try again in a minute."


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    session = sessions.setdefault(req.session_id, {"location": None, "pending_question": None, "history": []})
    message = strip_control_lines(req.message)

    try:
        raw_location, has_question = extract_location_and_intent(message)
    except Exception:
        raise HTTPException(status_code=503, detail=PROVIDER_ERROR)

    location, status = normalize_state(raw_location)
    pin_state = state_from_pin(message)
    if pin_state:
        location, status = pin_state, "ok"

    if status in ("ambiguous", "multiple"):
        # Don't guess which state's law applies - keep the question and ask for one state.
        if has_question:
            session["pending_question"] = message
        return ChatResponse(
            response="That could mean more than one state, and traffic rules differ by state. "
                     "Which single state, city, or PIN code should I use? You can ask about "
                     "another state afterwards."
        )

    if location:
        session["location"] = location
    else:
        # Without a location in this message it can't be "just a location", so it is never dropped.
        has_question = True

    if not session["location"]:
        # Still don't know where they are. If this message was a real question, remember it so
        # we can answer it automatically once the location comes in, instead of making them
        # repeat themselves.
        if has_question:
            session["pending_question"] = message
        return ChatResponse(
            response="Which state, city, or PIN code are you asking about? Traffic rules vary "
                     "by state in India, so let me know your location and I'll tailor the answer."
        )

    question_to_answer = None
    if has_question:
        session["pending_question"] = None
        question_to_answer = message
    elif session["pending_question"]:
        question_to_answer = session["pending_question"]
        session["pending_question"] = None

    if question_to_answer is None:
        return ChatResponse(
            response=f"Got it — I'll use {session['location']} for your questions. "
                     f"What would you like to know about traffic rules there?"
        )

    try:
        answer, standalone_question = answer_question(question_to_answer, session["location"], session["history"])
    except Exception:
        raise HTTPException(status_code=503, detail=PROVIDER_ERROR)
    session["history"].append({"question": standalone_question, "answer": answer})
    session["history"] = session["history"][-MAX_HISTORY_TURNS:]
    return ChatResponse(response=with_penalty_note(answer))


@app.get("/health")
def health():
    return {"status": "ok"}


FRONTEND_DIR = BASE_DIR / "frontend"


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
