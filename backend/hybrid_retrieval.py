"""
Hybrid retrieval for the Telangana index: structured provision lookup + BM25 + the existing vector search,
combined with Reciprocal Rank Fusion.

Everything here is read-only and local. The lexical index is built in memory from the chunks already stored
in the Chroma collection (text and metadata unchanged); nothing is written back. Answer eligibility is NOT
decided here: candidates of every kind go through the server's single eligibility filter, so a chunk that
BM25 ranks highly is dropped exactly like one the vector search ranks highly.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from langchain_core.documents import Document

# Standard Okapi BM25 parameters (Robertson et al.) and the usual RRF constant (Cormack et al., 2009).
# None of them is tuned on the benchmark.
BM25_K1 = 1.5
BM25_B = 0.75
RRF_K = 60

INSTRUMENTS = {"tmvr-1989": "Telangana Motor Vehicles Rules, 1989 (TMVR)",
               "tmvtr-1963": "Telangana Motor Vehicles Taxation Rules, 1963 (TMVTR)"}
GO_MANIFEST_RE = re.compile(r"^go-(?:ms|rt)-(\d{1,4})-(\d{4})-")

# "G.O.Ms.No. 16/2026", "G.O. 16 of 2026", "GO Ms No 16", "G.O.Ms.No. 16 Dated: 20-03-2026", "GO 16/2026"
GO_REF_RE = re.compile(
    r"\b(?:g\.\s*o\.?|go\.?(?=\s*(?:\(?\s*(?:ms|rt)\b|no\b|\d{1,4}\s*/\s*\d{4})))"
    r"\s*(?:\(?\s*(?:ms|rt)\s*\)?\.?\s*)?(?:no\.?\s*)?(?P<num>\d{1,4})"
    r"(?:\s*(?:/|\bof\b|,|\bdated\b\s*:?|\bdt\.?\s*:?)\s*(?:\d{1,2}[.\-/]\d{1,2}[.\-/])?(?P<year>(?:19|20)\d{2}))?",
    re.IGNORECASE)
PARAGRAPH_REF_RE = re.compile(r"\bpara(?:graph)?\.?\s*(\d{1,3})\b", re.IGNORECASE)
STOPWORDS = frozenset(
    "a an and are as at be by can do does for from has have how i if in is it its me my of on or our say says "
    "should tell than that the their them then there these they this to under was we were what when where which "
    "who whom why will with you your".split())


def _go_token(num, year=None) -> str:
    return f"go{int(num)}" + (f"y{year}" if year else "")


def normalise(text: str) -> str:
    """Lower-case text with legal identifiers folded into single tokens:
    G.O. references -> "go16 go16y2026"; "13-A" / "13A" / "Rule 13 A" (at the end) -> "13a"."""
    def go(m):
        tokens = [_go_token(m.group("num"))]
        if m.group("year"):
            tokens.append(_go_token(m.group("num"), m.group("year")))
        return " " + " ".join(tokens) + " "
    t = GO_REF_RE.sub(go, text).lower()
    t = re.sub(r"\b(\d{1,3})\s*-\s*([a-z])\b", r"\1\2", t)
    t = re.sub(r"\b(rules?|sections?|para(?:graph)?s?)\s+(\d{1,3})\s+([a-z])(?=\s*(?:[?.,;:)]|$))", r"\1 \2\3", t)
    return t


def fold_plural(word: str) -> str:
    """Plural-only folding (Harman's S-stemmer), so "certificates" matches "certificate" and "issues" matches
    "issue". Only alphabetic words longer than 3 letters change; numbers, rule tokens like "12b" and G.O. tokens
    like "go32y2026" never do. No other suffixes are removed (Stage 17)."""
    if len(word) <= 3 or not word.isalpha():
        return word
    if word.endswith("ies") and not word.endswith(("eies", "aies")):
        return word[:-3] + "y"
    if word.endswith("es") and not word.endswith(("aes", "ees", "oes")):
        return word[:-1]
    if word.endswith("s") and not word.endswith(("us", "ss")):
        return word[:-1]
    return word


def tokenize(text: str) -> list[str]:
    return [fold_plural(w) for w in re.findall(r"[a-z0-9]+", normalise(text)) if w not in STOPWORDS]


class BM25:
    """Okapi BM25 with the non-negative (Lucene) idf."""

    def __init__(self, corpus_tokens, k1=BM25_K1, b=BM25_B):
        self.k1, self.b = k1, b
        self.tf = [Counter(toks) for toks in corpus_tokens]
        self.lengths = [len(toks) for toks in corpus_tokens]
        self.avgdl = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0
        df = Counter(term for tf in self.tf for term in tf)
        n = len(self.tf)
        self.idf = {t: math.log((n - d + 0.5) / (d + 0.5) + 1.0) for t, d in df.items()}

    def scores(self, query_tokens) -> list[float]:
        out = []
        for tf, length in zip(self.tf, self.lengths):
            s = 0.0
            for t in set(query_tokens):
                f = tf.get(t)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * length / self.avgdl))
            out.append(s)
        return out


def chunk_key(doc) -> tuple:
    """Identity of one stored chunk: its metadata identity plus its full text. Distinct provisions never share a
    key, even with similar text; chunks with missing or incomplete metadata are never merged unless their text
    is identical too. Every retrieval path reads the same stored text, so the key is stable across them."""
    m = getattr(doc, "metadata", None) or {}
    return (m.get("manifest_id"), m.get("provision_id"), m.get("part"), m.get("location"), m.get("sha256"),
            m.get("source_file"), getattr(doc, "page_content", None))


def instrument_of(manifest_id: str) -> str | None:
    for prefix in INSTRUMENTS:
        if (manifest_id or "").startswith(prefix):
            return prefix
    return None


@dataclass
class Lookup:
    """Result of structured lookup for one question."""
    documents: list = field(default_factory=list)          # exact matches, in reference and document order
    ambiguous: list = field(default_factory=list)          # [(reference, [instrument or G.O. labels])]
    missing_gos: list = field(default_factory=list)        # ["G.O.Ms.No. 99/2026"]


def lexical_text(doc) -> str:
    """Chunk text as BM25 sees it: the stored text without the chapter label in its header line (Stage 28).

    The chapter label is shared by every chunk of a chapter. It helps the embedding place a terse rule in its
    subject (Rule 455 "Applications" under "Claims Tribunals"), but as BM25 terms it lifts or sinks whole chapters
    on title words such as "drivers" or "conductors". The stored text and metadata are unchanged."""
    text, chapter = doc.page_content, (doc.metadata or {}).get("chapter")
    if not chapter:
        return text
    head, sep, body = text.partition("\n")
    return head.replace(f" - {chapter}", "", 1) + sep + body


CHAPTER_NUMBER_RE = re.compile(r"^CHAPTER\s+[IVXLC]+(?:-[A-Z])?\b", re.IGNORECASE)


def chapter_of(doc) -> tuple | None:
    """(document title, chapter label) of a chunk, or None when the chunk has no chapter."""
    m = getattr(doc, "metadata", None) or {}
    return (m.get("title"), m["chapter"]) if m.get("chapter") else None


def chapter_naming_terms(docs) -> dict:
    """For each chapter, the title words that occur in no other chapter title of the index (Stage 29):
    "conductor" names "Licensing of Conductors of Stage Carriages"; "motor" and "vehicle" name nothing, because
    several chapters share them. Words are tokenised like BM25 text; the chapter number is not a word."""
    words = {c: set(tokenize(CHAPTER_NUMBER_RE.sub(" ", c[1]))) for c in {chapter_of(d) for d in docs} - {None}}
    df = Counter(w for ws in words.values() for w in ws)
    return {c: frozenset(w for w in ws if df[w] == 1) for c, ws in words.items()}


class LexicalIndex:
    def __init__(self, documents, metadatas):
        self.docs = [Document(page_content=d, metadata=dict(m or {})) for d, m in zip(documents, metadatas)]
        self.chapter_terms = chapter_naming_terms(self.docs)
        fields = ("provision_id", "provision_heading", "title", "document_number")
        self.bm25 = BM25([tokenize(lexical_text(d) + " " + " ".join(str(d.metadata.get(f) or "") for f in fields))
                          for d in self.docs])
        self.by_provision = {}
        self.gos = {}  # (number, year) -> manifest_id
        for d in self.docs:
            m = d.metadata
            self.by_provision.setdefault((m.get("manifest_id"), m.get("provision_id")), []).append(d)
            g = GO_MANIFEST_RE.match(m.get("manifest_id") or "")
            if g:
                self.gos[(int(g.group(1)), g.group(2))] = m["manifest_id"]

    @classmethod
    def from_store(cls, store):
        """Build from a Chroma store, or None when the store cannot supply chunk text and metadata."""
        try:
            got = store.get(include=["documents", "metadatas"])
            documents, metadatas = got.get("documents"), got.get("metadatas")
        except Exception:
            return None
        if not documents or not metadatas or len(documents) != len(metadatas):
            return None
        if not any((m or {}).get("provision_id") for m in metadatas):
            return None
        return cls(documents, metadatas)

    def search(self, question: str, k: int) -> list:
        scores = self.bm25.scores(tokenize(question))
        ranked = sorted((i for i, s in enumerate(scores) if s > 0), key=lambda i: -scores[i])
        return [self.docs[i] for i in ranked[:k]]

    def spread_named_chapters(self, question: str, docs: list) -> list:
        """Reorder docs so that every chapter the question names leads with its best candidate (Stage 29).

        A question such as "badge rules for drivers and for conductors" names two chapters. When one chapter has
        many matching rules, they can fill the top of the list and push the other chapter's only rule to the end.
        If two or more named chapters have a candidate in docs, the best candidate of each later chapter moves up
        to directly follow the best candidate of the first. Nothing is added or removed, nothing moves ahead of
        the first named chapter's best candidate, and a question naming fewer than two chapters is unchanged."""
        asked = set(tokenize(question))
        named = {c for c, terms in self.chapter_terms.items() if terms & asked}
        best = []
        for d in docs:
            c = chapter_of(d)
            if c in named and all(chapter_of(b) != c for b in best):
                best.append(d)
        if len(best) < 2:
            return docs
        first = docs.index(best[0])
        rest = [d for d in docs[first + 1:] if all(d is not b for b in best)]
        return docs[:first] + best + rest

    def go_references(self, question: str) -> list[tuple]:
        refs = []
        for m in GO_REF_RE.finditer(question):
            ref = (int(m.group("num")), m.group("year"))
            if ref not in refs:
                refs.append(ref)
        return refs

    def lookup(self, question: str, rule_refs, scope: str | None) -> Lookup:
        """Exact provision matches. A rule number without an instrument that exists in both the TMVR and the
        TMVTR is reported as ambiguous and NOT matched; a G.O. number+year never matches another G.O."""
        out = Lookup()
        go_ids = []
        for num, year in self.go_references(question):
            hits = sorted(mid for (n, y), mid in self.gos.items() if n == num and (year is None or y == year))
            label = f"G.O.Ms.No. {num}" + (f"/{year}" if year else "")
            if not hits:
                out.missing_gos.append(label)
            elif len(hits) > 1:
                out.ambiguous.append((label, [f"G.O.Ms.No. {num}/{GO_MANIFEST_RE.match(h).group(2)}" for h in hits]))
            else:
                go_ids.append(hits[0])
        paragraphs = [f"Paragraph {n}" for n in PARAGRAPH_REF_RE.findall(question)]
        for mid in go_ids:
            wanted = [p for p in paragraphs if (mid, p) in self.by_provision]
            keys = [(mid, p) for p in wanted] if wanted else sorted(
                {k for k in self.by_provision if k[0] == mid}, key=lambda k: self._first_index(k))
            for key in keys:
                out.documents.extend(self.by_provision[key])
        for ref in rule_refs:
            holders = {instrument_of(mid) for (mid, pid) in self.by_provision if pid == ref} - {None}
            if scope:
                holders &= {scope}
            if len(holders) > 1:
                out.ambiguous.append((ref, [INSTRUMENTS[h] for h in sorted(holders)]))
                continue
            for (mid, pid), docs in self.by_provision.items():
                if pid == ref and instrument_of(mid) in holders:
                    out.documents.extend(docs)
        return out

    def _first_index(self, key) -> int:
        return self.docs.index(self.by_provision[key][0])


def parse_vector_protect(value, k: int = 6, default: int = 3) -> int:
    """RAG_VECTOR_PROTECT: an integer from 0 (guard off) to k; anything else falls back to the default."""
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return n if 0 <= n <= k else default


def protect_vector_leaders(top: list, candidates: list, vector_docs: list, protect: int, k: int) -> list:
    """Keep the vector search's `protect` best chunks in the final `k` (Stage 4D).

    Reciprocal-rank fusion gives a chunk found only by BM25 at rank r the same vote as one found only by the
    vector search at rank r, and ties go to the BM25 list. So a chunk the embedding model ranks 3rd can lose its
    place to two keyword-only chunks that merely share generic words (e.g. "application", "licence").
    `candidates` is the fused, filtered, de-duplicated list; a vector leader is protected only if it is in it,
    so every filter (state, approval, answer_eligible) still applies. Leaders missing from `top` are appended and
    the lowest-ranked unprotected chunks make room. Nothing is added that fusion had not already accepted, and the
    result never exceeds `k`. `protect` <= 0 returns `top` unchanged."""
    if protect <= 0:
        return top
    allowed = {chunk_key(d): d for d in candidates}
    leaders = []
    for d in vector_docs:
        key = chunk_key(d)
        if key in allowed and all(chunk_key(x) != key for x in leaders):
            leaders.append(allowed[key])
        if len(leaders) == protect:
            break
    present = {chunk_key(d) for d in top}
    missing = [d for d in leaders if chunk_key(d) not in present]
    if not missing:
        return top
    protected = {chunk_key(d) for d in leaders}
    kept = list(top)
    while len(kept) + len(missing) > k:
        for i in range(len(kept) - 1, -1, -1):
            if chunk_key(kept[i]) not in protected:
                del kept[i]
                break
        else:
            break
    return kept + missing


def reciprocal_rank_fusion(ranked_lists, k=RRF_K) -> list:
    """Fuse ranked Document lists by chunk identity. Each list votes 1/(k + rank); ties keep first-seen order."""
    score, first = {}, {}
    for ranked in ranked_lists:
        seen = set()
        for rank, doc in enumerate(ranked, 1):
            key = chunk_key(doc)
            if key in seen:
                continue
            seen.add(key)
            score[key] = score.get(key, 0.0) + 1.0 / (k + rank)
            first.setdefault(key, doc)
    order = sorted(first, key=lambda key: -score[key])  # sorted() is stable: ties keep insertion order
    return [first[key] for key in order]
