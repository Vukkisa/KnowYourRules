"""Retrieval profiles: how documents are chunked and embedded, and the matching relevance gate.

build_index.py records the profile it used in the Chroma collection's metadata ("rag_profile") and
server.py reads it back at startup, so queries are always embedded the same way as the index. An index
built before profiles existed has no such metadata and is treated as "baseline".

    baseline    RecursiveCharacterTextSplitter(1000, 200) over the whole document; nomic-embed-text
                with no task prefix; gate at squared L2 <= 0.88. The original pipeline.
    structured  one chunk per Section/Rule (long ones split 1000/200, short neighbours merged);
                nomic's "search_document: " / "search_query: " task prefixes; gate 0.80.

Rollback: rebuild with RAG_PROFILE=baseline. Evidence: eval/results/analysis_v1.md (synthetic corpus).
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    name: str
    chunking: str           # "fixed" | "structure"
    doc_prefix: str
    query_prefix: str
    default_max_distance: float


PROFILES = {
    "baseline": Profile("baseline", "fixed", "", "", 0.88),
    # 0.80 is provisional: chosen on the synthetic benchmark so false refusals stay at or below the
    # baseline's. Recalibrate on an approved real corpus; RAG_MAX_DISTANCE still overrides it.
    "structured": Profile("structured", "structure", "search_document: ", "search_query: ", 0.80),
}
DEFAULT_BUILD_PROFILE = "structured"
UNRECORDED_INDEX_PROFILE = "baseline"  # indexes built before profiles were recorded
PROFILE_METADATA_KEY = "rag_profile"

CHUNK_SIZE, CHUNK_OVERLAP = 1000, 200
MIN_HEADINGS = 3          # fewer than this and a document is not treated as sectioned
MIN_SECTION_CHARS = 200   # shorter sections are merged into the next one (numbered list items etc.)

# A provision heading at the start of a line: "Section 12.", "Rule 5.", "184. Driving ...", "3A) ...".
HEADING = re.compile(r"^[ \t]*(?:(?:section|sec\.|rule|regulation)[ \t]+)?\d{1,3}[a-z]{0,2}[.)][ \t]+\S",
                     re.IGNORECASE | re.MULTILINE)


def get_profile(name):
    """The named profile; None or "" means the build default. Unknown names raise ValueError."""
    name = (name or DEFAULT_BUILD_PROFILE).strip().lower()
    if name not in PROFILES:
        raise ValueError(f"unknown RAG_PROFILE {name!r}; expected one of {', '.join(sorted(PROFILES))}")
    return PROFILES[name]


def profile_of_index(store):
    """The profile recorded on a langchain Chroma store's collection, or the unrecorded default."""
    collection = getattr(store, "_collection", None)
    metadata = getattr(collection, "metadata", None) or {}
    name = metadata.get(PROFILE_METADATA_KEY) if isinstance(metadata, dict) else None
    return PROFILES.get(name, PROFILES[UNRECORDED_INDEX_PROFILE])


def section_spans(text):
    """(start, end) spans of the sections of text, or None if it does not look sectioned.

    Text before the first heading is kept as its own span; sections shorter than MIN_SECTION_CHARS are
    merged into the following one so stray numbered lines do not become tiny chunks.
    """
    starts = [m.start() for m in HEADING.finditer(text)]
    if len(starts) < MIN_HEADINGS:
        return None
    bounds = ([0] if text[:starts[0]].strip() else []) + starts + [len(text)]
    spans, pending = [], None
    for s, e in zip(bounds, bounds[1:]):
        s = pending if pending is not None else s
        if e - s < MIN_SECTION_CHARS and e != len(text):
            pending = s
            continue
        spans.append((s, e))
        pending = None
    if pending is not None:
        spans.append((pending, len(text)))
    return [(s, e) for s, e in spans if text[s:e].strip()]


def split_documents(docs, profile, splitter_cls):
    """Chunk loaded documents for the profile. splitter_cls is RecursiveCharacterTextSplitter (injectable).

    Every chunk keeps the document's metadata plus "start_index" into the document text; structured
    chunks also carry "section" (the heading line) and "chunking" ("structure" or "fixed-fallback").
    """
    splitter = splitter_cls(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP, add_start_index=True)
    if profile.chunking == "fixed":
        return splitter.split_documents(docs)

    from langchain_core.documents import Document
    sections = []
    for doc in docs:
        text = doc.page_content
        spans = section_spans(text)
        if spans is None:
            sections.append(Document(page_content=text, metadata=dict(doc.metadata, chunking="fixed-fallback", section_start=0)))
            continue
        for s, e in spans:
            heading = text[s:e].strip().splitlines()[0][:120]
            sections.append(Document(page_content=text[s:e], metadata=dict(doc.metadata, chunking="structure", section=heading, section_start=s)))
    chunks = splitter.split_documents(sections)
    for c in chunks:
        c.metadata["start_index"] = c.metadata.pop("section_start", 0) + c.metadata.get("start_index", 0)
    return chunks


class ProfileEmbeddings:
    """Wraps a LangChain embeddings object, adding the profile's task prefixes (texts are stored unprefixed)."""

    def __init__(self, base, profile=None):
        self.base = base
        self.profile = profile or PROFILES[UNRECORDED_INDEX_PROFILE]

    def embed_documents(self, texts):
        return self.base.embed_documents([self.profile.doc_prefix + t for t in texts])

    def embed_query(self, text):
        return self.base.embed_query(self.profile.query_prefix + text)
