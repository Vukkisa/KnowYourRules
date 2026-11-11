"""
Telangana legal-document ingestion: HTML and PDF loaders plus legal-aware chunking.

Loaders turn a file into ordered Blocks (text or table) with exact source locations. The chunker groups
blocks into provisions (Rule / Section / Paragraph / Schedule / Form, under their Chapter) and emits one
chunk per provision. A provision that is too long is split only at its own sub-rule, clause or table-row
boundaries - two provisions are never combined in one chunk.
"""

import copy
import re
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup, Comment, NavigableString
from langchain_core.documents import Document
from pypdf import PdfReader

MAX_CHUNK_CHARS = 3500
MIN_DOC_CHARS = 200          # less extractable PDF text than this: the document is treated as empty
MIN_HTML_CHARS = 80          # HTML pages can legitimately hold one short rule (e.g. a one-rule chapter)
MIN_PAGE_CHARS = 20          # a page with images and less text than this needs OCR


class IngestError(Exception):
    """A document cannot be ingested safely (empty, scanned, unreadable)."""


@dataclass
class Block:
    kind: str                    # "text" | "table"
    text: str
    location: str                # "file#anchor" (HTML) or "file#page=N" (PDF)
    page: int | None = None
    header: str | None = None    # first row of a table, repeated when a table is split


# ---------------------------------------------------------------------------------------------------
# Heading patterns
# ---------------------------------------------------------------------------------------------------
CHAPTER_RE = re.compile(r"^\s*CHAPTER\s+([IVXLCDM]+|\d+)([A-Z]?)\b[.:\-\s]*(.*)$", re.IGNORECASE)
SCHEDULE_RE = re.compile(
    r"^\s*(?:THE\s+)?((?:FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH)\s+SCHEDULE"
    r"|SCHEDULE(?:\s*[-–]?\s*[IVXLC\d]+[A-Z]?)?)\b(.*)$", re.IGNORECASE)
FORM_RE = re.compile(r"^\s*FORM\s*[-–]?\s*([A-Z]{0,4}[-\s]?\d{1,3}[A-Z]{0,2})\b(.*)$")
_PREFIX = r"(?:(?P<prefix>Rule|Section|Sec\.|Regulation|Para(?:graph)?)\s+)?"
_NUMBER = r"(?P<num>\d{1,3})(?:-?(?P<suffix>[A-Z]{1,2}))?"
_TITLE_START = r"[A-Z\u2018\u201c'\"(\[]"
PROVISION_PATTERNS = [
    # "5. Title", "5.Title", "5A. Title", "12-A. Title", "Rule 5. Title", "5." (number on its own line)
    re.compile(rf"^\s*{_PREFIX}{_NUMBER}\.(?:\s*(?P<title>{_TITLE_START}.*))?$", re.IGNORECASE),
    # "Rule 5 Title", "Section 12 - Title"
    re.compile(rf"^\s*(?P<prefix>Rule|Section|Regulation)\s+{_NUMBER}\b[.:\-\u2013\s]*(?P<title>.*)$", re.IGNORECASE),
    # "13-B Title" (hyphenated insertion without a period)
    re.compile(r"^\s*(?P<num>\d{1,3})-(?P<suffix>[A-Z]{1,2})\s+(?P<title>[A-Z].*)$"),
]


# A heading written without the full stop after its number ("186 (1) Title :-", "295-A . Title:-", "12-B : -",
# "13 Title : -"). Accepted only when the line also carries the ":-" heading terminator and the number is the
# next one in sequence (see segment), so measurements ("408 Cms. to 432 Cms") and list items cannot match.
UNPUNCTUATED_HEADING_RE = re.compile(
    r"^\s*(?P<num>\d{1,3})(?:\s*-\s*(?P<suffix>[A-Z]))?\s*\.?\s*(?:\(1\)\s*)?"
    r"(?P<title>(?:[A-Z][^:]{0,150}?)?)\s*:\s*[-\u2013\u2014]")


def _next_in_sequence(key, last_key) -> bool:
    """186 after 185, 295A after 295, 12B after 12A, 13 after 12B."""
    if last_key is None:
        return False
    (n, s), (ln, ls) = key, last_key
    return (n == ln + 1 and s == "") or (n == ln and len(s) == 1 and s == (chr(ord(ls) + 1) if ls else "A"))


def match_provision(line: str):
    """(prefix, number, title) if the line opens a numbered provision, else None."""
    for pattern in PROVISION_PATTERNS:
        m = pattern.match(line)
        if m:
            g = m.groupdict()
            return g.get("prefix"), g["num"] + (g.get("suffix") or "").upper(), g.get("title") or ""
    return None


SUB_RULE_RE = re.compile(r"^\s*\((\d{1,3}[A-Z]?)\)")
CLAUSE_RE = re.compile(r"^\s*\(([a-z]{1,2}|[ivx]{1,5})\)")
NUMBER_ONLY_RE = re.compile(r"^\s*(?:(?:Rule|Section)\s+)?\d{1,3}[A-Z]{0,2}\.\s*$", re.IGNORECASE)
HEADING_MAX_CHARS = 160
KIND_BY_TYPE = {"Act": "Section", "Rules": "Rule", "Regulations": "Regulation"}
GO_REFERENCES_RE = re.compile(r"^\s*Read\s+(?:the\s+following|also)\b", re.IGNORECASE)
# Upper-case ORDER heading ("ORDER:", "O R D E R:", "&&& ORDER:"); "Order dated ..." citations don't match.
GO_ORDER_RE = re.compile(r"^\s*(?:[&*]+\s*)?(?:O\s+R\s+D\s+E\s+R|ORDER)\s*[:.-]")


def _clean(text: str) -> str:
    return re.sub(r"[ \t ]+", " ", text).strip()


# ---------------------------------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------------------------------
BLOCK_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "div", "pre", "blockquote", "dt", "dd", "caption", "td",
              "th", "center", "section", "article"}
SKIP_TAGS = {"script", "style", "noscript", "head", "nav", "form", "button", "iframe"}


def _anchor(el):
    for node in [el, *el.parents]:
        if getattr(node, "attrs", None):
            for attr in ("id", "name"):
                if node.attrs.get(attr):
                    return str(node.attrs[attr])
    return None


# Site navigation that is not part of any instrument ("« Previous", "Back to Chapters", "Next »").
NAV_RE = re.compile(r"^(?:[«»|\s]|previous|next|back\s+to\s+chapters|back|top|home|contents)+$", re.IGNORECASE)
LAYOUT_CELL_TAGS = ["div", "p", "table", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre"]
LAYOUT_CELL_CHARS = 400


def _is_layout_table(table) -> bool:
    """Tables used for page layout (cells holding paragraphs or very long text) are walked, not kept as data."""
    for cell in table.find_all(["td", "th"]):
        if cell.find_parent("table") is not table:
            continue
        if cell.find(LAYOUT_CELL_TAGS) is not None or len(cell.get_text(" ", strip=True)) > LAYOUT_CELL_CHARS:
            return True
    return False


ANCHOR_MARK = "\x01"
BREAK_MARK = "\x00"


def _leaf_paragraphs(el, inherited_anchor):
    """Split an element's inline content at <br> line breaks. Returns ([(text, anchor)], last_anchor), where
    anchor is the nearest <a name>/<... id> at or before the paragraph start, so each rule keeps its location."""
    el = copy.copy(el)
    for a in el.find_all(lambda t: t.attrs.get("name") or t.attrs.get("id")):
        a.insert_before(NavigableString(f"{ANCHOR_MARK}{a.attrs.get('name') or a.attrs.get('id')}{ANCHOR_MARK}"))
    for br in el.find_all("br"):
        br.replace_with(NavigableString(BREAK_MARK))
    anchor, out = inherited_anchor, []
    for para in el.get_text(" ").split(BREAK_MARK):
        parts = para.split(ANCHOR_MARK)
        names = parts[1::2]
        text = _clean(" ".join(parts[0::2]))
        if names and not _clean(parts[0]):
            anchor = names[0]  # the anchor opens this paragraph
        if text:
            out.append((text, anchor))
        if names:
            anchor = names[-1]
    return out, anchor


def _table_rows(table):
    rows = []
    for tr in table.find_all("tr"):
        if tr.find_parent("table") is not table:
            continue  # nested table rows belong to the nested table
        cells = [_clean(c.get_text(" ", strip=True)) for c in tr.find_all(["td", "th"], recursive=False)]
        if any(cells):
            rows.append(" | ".join(cells))
    return rows


def _parse_html(raw: bytes):
    soup = BeautifulSoup(raw, "html.parser")
    # Pages declared (or guessed) as Latin-1 are in practice Windows-1252 (dashes, ellipses).
    if (soup.original_encoding or "").lower() in {"iso-8859-1", "latin-1", "windows-1252", "ascii"}:
        soup = BeautifulSoup(raw, "html.parser", from_encoding="cp1252")
    return soup


def _is_block(el) -> bool:
    return el.name in BLOCK_TAGS or el.name == "table"


def load_html(path, rel_name: str | None = None) -> list[Block]:
    """Ordered text and table blocks of an HTML file, each with a 'file#anchor' location.

    Handles legacy layouts: layout tables are walked through, and inline text mixed with block elements
    in the same container is kept (split at <br>) instead of being dropped.
    """
    name = rel_name or Path(path).name
    soup = _parse_html(Path(path).read_bytes())
    for tag in soup.find_all(SKIP_TAGS):
        tag.decompose()
    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        c.extract()
    blocks, counter = [], 0
    root = soup.body or soup

    def fallback_location():
        nonlocal counter
        counter += 1
        return f"{name}#block-{counter}"

    def emit_inline(nodes, anchor):
        wrapper = soup.new_tag("div")
        for node in nodes:
            wrapper.append(copy.copy(node))
        paragraphs, anchor = _leaf_paragraphs(wrapper, anchor)
        fallback = fallback_location()
        for text, a in paragraphs:
            if not NAV_RE.match(text):
                blocks.append(Block("text", text, f"{name}#{a}" if a else fallback))
        return anchor

    def walk(el, anchor):
        own = el.attrs.get("id") or el.attrs.get("name") if getattr(el, "attrs", None) else None
        anchor = own or anchor
        buffer = []
        for child in list(el.children):
            if isinstance(child, NavigableString):
                buffer.append(child)
                continue
            if child.name in SKIP_TAGS:
                continue
            contains_block = child.find(_is_block) is not None
            if not _is_block(child) and not contains_block:
                buffer.append(child)  # inline element (a, strong, span, font, br ...)
                continue
            if buffer:
                anchor = emit_inline(buffer, anchor)
                buffer = []
            if child.name == "table" and not _is_layout_table(child):
                rows = _table_rows(child)
                if rows and not all(NAV_RE.match(r) for r in rows):
                    loc = child.attrs.get("id") or child.attrs.get("name") or anchor
                    blocks.append(Block("table", "\n".join(rows), f"{name}#{loc}" if loc else fallback_location(),
                                        header=rows[0]))
                continue
            anchor = walk(child, anchor)
        if buffer:
            anchor = emit_inline(buffer, anchor)
        return anchor

    walk(root, None)
    # Rejoin "5." + "Title" when a page splits the rule number from its heading.
    merged = []
    for b in blocks:
        if merged and merged[-1].kind == "text" and NUMBER_ONLY_RE.match(merged[-1].text) and b.kind == "text":
            merged[-1] = Block("text", f"{merged[-1].text} {b.text}", merged[-1].location)
            continue
        merged.append(b)
    return merged


# ---------------------------------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------------------------------
TABLE_GAP_RE = re.compile(r"\S(?: {3,}|\t+)\S")
TABLE_CELL_MAX = 40   # justified prose has long "cells"; real table cells are short


def _is_table_line(line: str) -> bool:
    if not TABLE_GAP_RE.search(line):
        return False
    return max(len(c.strip()) for c in re.split(r" {3,}|\t+", line)) <= TABLE_CELL_MAX


def _page_has_images(page) -> bool:
    """True if the page lists an image XObject AND its content stream draws an XObject (Do)."""
    try:
        xobjects = page.get("/Resources", {}).get("/XObject", {})
        xobjects = xobjects.get_object() if hasattr(xobjects, "get_object") else xobjects
        images = [k for k in xobjects if xobjects[k].get_object().get("/Subtype") == "/Image"]
        if not images:
            return False
        contents = page.get_contents()
        data = contents.get_data() if contents is not None else b""
        return any(re.search(re.escape(str(k)).encode() + rb"\s+Do\b", data) for k in images)
    except Exception:
        return True  # cannot tell: treat as possibly scanned (fail closed)


def load_pdf(path, rel_name: str | None = None) -> list[Block]:
    """Ordered blocks of a PDF with page numbers. Raises IngestError for empty or scanned documents."""
    name = rel_name or Path(path).name
    try:
        reader = PdfReader(str(path))
        pages = list(reader.pages)
    except Exception as e:
        raise IngestError(f"{name}: unreadable PDF ({e.__class__.__name__})") from e
    blocks, ocr_pages, total = [], [], 0
    for number, page in enumerate(pages, start=1):
        try:
            text = page.extract_text(extraction_mode="layout") or ""
        except Exception:
            text = ""
        stripped = text.strip()
        if len(stripped) < MIN_PAGE_CHARS and _page_has_images(page):
            ocr_pages.append(number)
            continue
        total += len(stripped)
        row_loc = f"{name}#page={number}"
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        gapped = [_is_table_line(ln) for ln in lines]
        i = 0
        while i < len(lines):
            j = i
            while j < len(lines) and gapped[j]:
                j += 1
            if j - i >= 2:
                # Two or more consecutive column-aligned lines: a table. A single gapped line is
                # justified text (e.g. "2. Keep Left.-The driver ... sh   all drive") and stays text.
                rows = [" | ".join(_clean(c) for c in re.split(r" {3,}|\t+", ln) if c.strip()) for ln in lines[i:j]]
                blocks.append(Block("table", "\n".join(rows), row_loc, number, header=rows[0]))
                i = j
                continue
            blocks.append(Block("text", _clean(lines[i]), row_loc, number))
            i += 1
    if ocr_pages:
        raise IngestError(f"{name}: OCR required - page(s) {ocr_pages} contain only images (scanned)")
    if total < MIN_DOC_CHARS:
        raise IngestError(f"{name}: only {total} characters of text extracted - empty document")
    return blocks


def load_blocks(path, fmt: str, rel_name: str | None = None) -> list[Block]:
    if fmt == "html":
        blocks = load_html(path, rel_name)
        if sum(len(b.text) for b in blocks) < MIN_HTML_CHARS:
            raise IngestError(f"{rel_name or Path(path).name}: too little text in HTML - empty document")
        return blocks
    if fmt == "pdf":
        return load_pdf(path, rel_name)
    raise IngestError(f"unsupported format {fmt!r}")


# ---------------------------------------------------------------------------------------------------
# Provisions and chunks
# ---------------------------------------------------------------------------------------------------
@dataclass
class Provision:
    kind: str                     # Rule | Section | Regulation | Paragraph | Schedule | Form | Preamble | References | Order
    number: str                   # "5", "5A", "FIRST SCHEDULE", "" for the preamble
    heading: str
    chapter: str
    blocks: list = field(default_factory=list)

    @property
    def identifier(self) -> str:
        if self.kind in ("Preamble", "References", "Order"):
            return self.kind
        if self.kind in ("Schedule", "Form"):
            return self.number
        return f"{self.kind} {self.number}"


# A heading ends at ":-" or ".-" (any dash). A bare dash is part of the heading ("Duplicate - Issue of").
HEADING_END_RE = re.compile(r"\s*[:.]\s*[-–—]+\s*")


def _heading(text: str) -> str:
    return _clean(HEADING_END_RE.split(text, maxsplit=1)[0])[:HEADING_MAX_CHARS]


def _number_key(number: str):
    m = re.match(r"(\d+)([A-Z]*)", number.upper())
    return (int(m.group(1)), m.group(2)) if m else (0, "")


def segment(blocks, document_type: str) -> list[Provision]:
    """Group blocks into provisions. Numbered lines that go backwards (list items inside a rule) or appear
    inside a schedule/form are kept as text, so they cannot start a spurious provision.

    In a G.O., the "Read the following" list is kept whole, in order, as one References provision up to
    the ORDER heading: its numbered items are citations, not operative paragraphs."""
    default_kind = KIND_BY_TYPE.get(document_type, "Paragraph")
    chapter = ""
    current = Provision("Preamble", "", "", "")
    provisions = [current]
    last_key = None
    awaiting_chapter_title = False
    in_references = False
    for b in blocks:
        first = b.text.splitlines()[0] if b.text else ""
        short = len(first) <= HEADING_MAX_CHARS
        if document_type == "G.O." and b.kind == "text":
            if not in_references and current.kind == "Preamble" and GO_REFERENCES_RE.match(first):
                current = Provision("References", "", "", chapter, [b])
                provisions.append(current)
                in_references = True
                continue
            if in_references:
                if GO_ORDER_RE.match(first):
                    in_references = False
                    current = Provision("Order", "", "", chapter, [])  # ORDER text before paragraph 2
                    provisions.append(current)
                    last_key = None
                else:
                    current.blocks.append(b)
                    continue
        if b.kind == "text" and short and (m := CHAPTER_RE.match(first)):
            chapter = _clean(f"CHAPTER {m.group(1).upper()}{m.group(2)} {m.group(3)}")
            awaiting_chapter_title = not m.group(3).strip()
            continue
        if awaiting_chapter_title:
            awaiting_chapter_title = False
            # "CHAPTER I" followed by a short upper-case title line ("PRELIMINARY").
            if b.kind == "text" and short and first.isupper() and not match_provision(first):
                chapter = f"{chapter} {_clean(first)}"
                continue
        if b.kind == "text" and short and (m := SCHEDULE_RE.match(first)):
            current = Provision("Schedule", _clean(m.group(1).upper()), _clean(m.group(2)), chapter, [b])
            provisions.append(current)
            continue
        if b.kind == "text" and short and (m := FORM_RE.match(first)):
            current = Provision("Form", f"FORM {_clean(m.group(1))}", _clean(m.group(2)), chapter, [b])
            provisions.append(current)
            continue
        found = match_provision(first) if b.kind == "text" else None
        if (not found and b.kind == "text" and document_type != "G.O." and current.kind not in ("Schedule", "Form")
                and (u := UNPUNCTUATED_HEADING_RE.match(first))
                and _next_in_sequence(_number_key(u["num"] + (u["suffix"] or "")), last_key)):
            found = (None, u["num"] + (u["suffix"] or ""), u["title"] or "")
        if found and document_type == "G.O." and found[0]:
            found = None  # a G.O.'s own paragraphs are bare numbers; "Rule 167A(1) of ..." is a citation
        if found and current.kind not in ("Schedule", "Form"):
            prefix, number, heading = found
            key = _number_key(number)
            if last_key is None or key > last_key:
                kind = {"sec.": "Section", "section": "Section", "rule": "Rule", "regulation": "Regulation",
                        "para": "Paragraph", "paragraph": "Paragraph"}.get((prefix or "").lower(), default_kind)
                current = Provision(kind, number, _heading(heading), chapter, [b])
                provisions.append(current)
                last_key = key
                continue
        current.blocks.append(b)
    return [p for p in provisions if p.blocks]


def _units(blocks, boundary_re):
    """Split a provision's blocks into units that start at boundary_re matches (sub-rules or clauses)."""
    units, current = [], []
    for b in blocks:
        if current and b.kind == "text" and boundary_re.match(b.text):
            units.append(current)
            current = []
        current.append(b)
    if current:
        units.append(current)
    return units


def _text(blocks) -> str:
    return "\n".join(b.text for b in blocks)


def _split_table(block, limit):
    rows = block.text.split("\n")
    header, body = rows[0], rows[1:]
    parts, current = [], [header]
    for row in body:
        if len("\n".join(current + [row])) > limit and len(current) > 1:
            parts.append(Block("table", "\n".join(current), block.location, block.page, header))
            current = [header]
        current.append(row)
    parts.append(Block("table", "\n".join(current), block.location, block.page, header))
    return parts


def _split_text_block(block, limit):
    pieces, current = [], ""
    sentences = []
    for sentence in re.split(r"(?<=[.;:])\s+", block.text):
        while len(sentence) > limit:  # no usable punctuation: wrap at the last space within the limit
            cut = sentence.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            sentences.append(sentence[:cut])
            sentence = sentence[cut:].strip()
        sentences.append(sentence)
    for sentence in sentences:
        if current and len(current) + len(sentence) + 1 > limit:
            pieces.append(current)
            current = ""
        current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return [Block("text", p, block.location, block.page) for p in pieces]


def _pack(units, limit):
    """Pack consecutive units (all from ONE provision) into groups within limit."""
    groups, current = [], []
    for u in units:
        if current and len(_text(current + u)) > limit:
            groups.append(current)
            current = []
        current = current + u
    if current:
        groups.append(current)
    return groups


def split_provision(p: Provision, limit=MAX_CHUNK_CHARS):
    """Returns (groups_of_blocks, split_method). Splits only at this provision's own boundaries."""
    if len(_text(p.blocks)) <= limit:
        return [p.blocks], "whole"
    method = "sub-rule"
    units = _units(p.blocks, SUB_RULE_RE)
    refined = []
    for u in units:
        if len(_text(u)) <= limit:
            refined.append(u)
            continue
        method = "clause"
        for c in _units(u, CLAUSE_RE):
            if len(_text(c)) <= limit:
                refined.append(c)
                continue
            for b in c:  # last resort inside one unit: table rows, then sentences
                if len(b.text) <= limit:
                    refined.append([b])
                elif b.kind == "table":
                    method = "table-rows"
                    # Leave room for the provision heading that is packed with the first part.
                    for t in _split_table(b, int(limit * 0.8)):
                        if len(t.text) <= limit:
                            refined.append([t])
                        else:  # a single row longer than the limit
                            refined.extend([[x] for x in _split_text_block(t, limit)])
                else:
                    method = "sentences"
                    refined.extend([[t] for t in _split_text_block(b, limit)])
    return _pack(refined, limit), method


def _location(blocks):
    locs = list(dict.fromkeys(b.location for b in blocks))
    return locs[0] if len(locs) == 1 else f"{locs[0]} .. {locs[-1]}"


def chunk_document(blocks, entry) -> list[Document]:
    """Legal-aware chunks of one manifest entry. Every chunk carries full source and provision metadata.

    Chroma accepts only str/int/float/bool metadata, so unknown values are stored as "" (never guessed).
    """
    docs = []
    for p in segment(blocks, entry.document_type):
        groups, method = split_provision(p)
        for i, group in enumerate(groups, start=1):
            pages = [b.page for b in group if b.page is not None]
            context = " - ".join(x for x in (entry.title, p.chapter, p.identifier,
                                               p.heading) if x)
            label = f"{context} (part {i} of {len(groups)})" if len(groups) > 1 else context
            docs.append(Document(page_content=f"{label}\n{_text(group)}", metadata={
                "sha256": entry.sha256,
                "source_file": Path(entry.file).name,
                "manifest_id": entry.id,
                "title": entry.title,
                "document_type": entry.document_type,
                "issuing_authority": entry.issuing_authority or "",
                "document_number": entry.document_number or "",
                "publication_date": entry.publication_date or "",
                "effective_date": entry.effective_date or "",
                "jurisdiction": entry.jurisdiction,
                "state": entry.jurisdiction,          # the server filters on "state"
                "source_class": entry.source_class,
                "verification_status": entry.verification_status,
                "source_url": entry.source_url or "",
                "provision_kind": p.kind,
                "provision_id": p.identifier,
                "provision_heading": p.heading,
                "chapter": p.chapter,
                "location": _location(group),
                "page_start": min(pages) if pages else -1,
                "page_end": max(pages) if pages else -1,
                "part": i,
                "parts": len(groups),
                "split_method": method,
                "has_table": any(b.kind == "table" for b in group),
                "manifest_notes": entry.notes or "",   # provenance and jurisdiction warnings, verbatim
                "extraction_warning": "",              # set by reviewed chunk flags at build time
                "answer_eligible": True,               # False = stored for review, never used to answer
            }))
    return docs
