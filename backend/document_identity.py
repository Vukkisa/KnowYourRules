"""
Logical document identity: which source files are parts of one legal document.

The manifest has one entry per source FILE. A document published as several files (the Telangana Motor Vehicles
Rules, 1989: one saved page per chapter) therefore has several entries, each with its own SHA-256, that share a
title. The logical document id names the document those files belong to, so that the UI lists it once.

It is derived from metadata every chunk already carries, so existing indexes need no rebuild and the file-level
provenance (manifest_id, source_file, sha256) is never replaced:

  * the id is the chunk's manifest_id with a chapter-file suffix removed: "tmvr-1989-chap-3" -> "tmvr-1989";
  * a manifest_id without that suffix is its own document: "go-ms-77-2025-trb" stays "go-ms-77-2025-trb".

A shared id alone never merges files. consistent_document_ids() also requires the describing metadata to be identical, so an
amendment or a government order is never folded into the Rules it amends: it has its own manifest_id, and its
title, document type and number differ.
"""

import re

# "<document>-chap-<n>": the manifest's naming for one chapter file of a multi-file document.
CHAPTER_FILE_RE = re.compile(r"^(?P<document>[a-z0-9][a-z0-9._-]*?)-chap-\d{1,3}$")

# Metadata that must be identical in every file of one logical document.
DESCRIBING_FIELDS = ("title", "document_type", "document_number", "issuing_authority", "publication_date",
                     "jurisdiction", "source_class")


def logical_document_id(metadata) -> str | None:
    """Id of the legal document a chunk belongs to, or None when the chunk has no manifest identity."""
    manifest_id = (metadata or {}).get("manifest_id")
    if not isinstance(manifest_id, str) or not manifest_id:
        return None
    m = CHAPTER_FILE_RE.match(manifest_id)
    return m.group("document") if m else manifest_id


def description(metadata) -> tuple:
    """The describing metadata of a chunk's document; missing values compare equal to "" (how they are stored)."""
    return tuple((metadata or {}).get(f) or "" for f in DESCRIBING_FIELDS)


def consistent_document_ids(metadatas) -> set:
    """Logical document ids that every given chunk describes the same way. An id whose chunks disagree on title,
    type, number, authority, date, jurisdiction or source class is left out: its files are then listed one by one
    rather than merged on the strength of a file name."""
    seen, conflicting = {}, set()
    for m in metadatas:
        doc_id = logical_document_id(m)
        if doc_id is None:
            continue
        if seen.setdefault(doc_id, description(m)) != description(m):
            conflicting.add(doc_id)
    return set(seen) - conflicting
