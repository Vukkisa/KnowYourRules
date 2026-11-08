"""
Dedicated builder for the Telangana-only index.

Writes ONLY the "telangana-traffic-rules" collection in its own Chroma directory (chroma_telangana_db by
default); the shared "india-traffic-rules" collection and directory are never opened. Builds go to a
staging collection, are validated, and only then swapped in; any failure leaves the previous index as it was.

The production directory is written only when a SIGNED approval record approves exactly the manifest's
documents. Unapproved builds (allow_unapproved) are refused there and must use a separate preview directory.

    python -m backend.build_telangana_index --manifest M.json --corpus DIR --approval A.json --trusted-keys K.json
"""

import argparse
import sys
from pathlib import Path
from uuid import uuid4

import chromadb
from langchain_chroma import Chroma

from backend import legal_approval, rag_profiles as rp, tg_ingest, tg_manifest

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_DIR = BASE_DIR / "chroma_telangana_db"
SHARED_DB_DIR = BASE_DIR / "chroma_langchain_db"
SHARED_COLLECTION = "india-traffic-rules"
COLLECTION = "telangana-traffic-rules"
STAGING = COLLECTION + "-staging"
PREVIOUS = COLLECTION + "-previous"
OWN_COLLECTIONS = {COLLECTION, STAGING, PREVIOUS}
BATCH_SIZE = 50
PROFILE = rp.PROFILES["structured"]  # chunks are provision-aligned; queries need the matching prefixes


class BuildError(Exception):
    pass


FLAG_MATCH_KEYS = {"manifest_id", "provision_id", "provision_kind", "has_table"}


def load_chunk_flags(path) -> list[dict]:
    """Reviewed extraction flags: [{"match": {...}, "warning": str, "answer_eligible": bool}].

    match keys: manifest_id (required), provision_id, provision_kind, has_table. Flags only ADD warnings or
    REMOVE answer eligibility; they never change legal text.
    """
    import json
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"schema_version", "flags"} or data["schema_version"] != 1:
        raise BuildError("chunk flags must be {schema_version: 1, flags: [...]}")
    for i, f in enumerate(data["flags"]):
        if not isinstance(f, dict) or set(f) != {"match", "warning", "answer_eligible"} \
                or not isinstance(f["match"], dict) or "manifest_id" not in f["match"] \
                or not set(f["match"]) <= FLAG_MATCH_KEYS or not isinstance(f["warning"], str) or not f["warning"].strip() \
                or not isinstance(f["answer_eligible"], bool):
            raise BuildError(f"chunk flag {i} is malformed")
    return data["flags"]


def apply_chunk_flags(chunks, flags) -> list[str]:
    """Apply flags in place. Returns problems (a flag matching no chunk is an error, not silently ignored)."""
    problems = []
    for i, f in enumerate(flags):
        hits = [c for c in chunks if all(c.metadata.get(k) == v for k, v in f["match"].items())]
        if not hits:
            problems.append(f"chunk flag {i} ({f['match']}) matches no chunk")
        for c in hits:
            joined = "; ".join(x for x in (c.metadata.get("extraction_warning", ""), f["warning"].strip()) if x)
            c.metadata["extraction_warning"] = joined
            c.metadata["answer_eligible"] = c.metadata.get("answer_eligible", True) and f["answer_eligible"]
    return problems


def approval_errors(entries, approval_path, trusted_keys) -> list[str]:
    """The signed record must approve exactly the manifest's documents, with no open conditions."""
    try:
        raw = Path(approval_path).read_bytes()
        record = legal_approval.parse_record_bytes(raw)
        legal_approval.verify_signature(raw, record, legal_approval.signature_path(approval_path),
                                        legal_approval.load_trusted_keys(trusted_keys))
    except OSError as e:
        return [f"cannot read approval record: {e.__class__.__name__}"]
    except legal_approval.ApprovalError as e:
        return [f"approval record rejected: {e}"]
    errors = []
    if record.unresolved_conditions:
        errors.append(f"{record.unresolved_conditions} approval condition(s) unresolved")
    manifest_hashes = {e.sha256 for e in entries}
    for e in entries:
        if e.sha256 not in record.hashes:
            errors.append(f"{e.id}: not approved (sha256 not in the approval record)")
    for d in record.documents:
        if d.sha256 not in manifest_hashes:
            errors.append(f"approved document {d.file!r} is not in the manifest")
    return errors


def prepare(manifest_path, corpus_dir, db_dir, approval_path=None, trusted_keys=None, allow_unapproved=False,
            chunk_flags=None):
    """Validate everything and produce chunks without touching any index. Returns (chunks, errors)."""
    db_dir = Path(db_dir).resolve()
    if db_dir == SHARED_DB_DIR.resolve():
        return [], ["refusing to write into the shared index directory"]
    try:
        entries = tg_manifest.load_manifest(manifest_path)
    except tg_manifest.ManifestError as e:
        return [], [f"manifest rejected: {e}"]
    errors = tg_manifest.file_errors(entries, corpus_dir)
    errors += [f"{e.id}: draft documents are never indexed" for e in entries if e.source_class == "draft"]
    if approval_path is not None:
        errors += approval_errors(entries, approval_path, trusted_keys)
    elif not allow_unapproved:
        errors.append("no approval record given: refusing to build")
    elif db_dir == DEFAULT_DB_DIR.resolve():
        errors.append("unapproved builds must use a separate preview directory, not the production one")
    if errors:
        return [], errors
    chunks = []
    for e in entries:
        try:
            blocks = tg_ingest.load_blocks(Path(corpus_dir) / e.file, e.format, e.file)
        except tg_ingest.IngestError as err:
            errors.append(f"{e.id}: {err}")
            continue
        chunks.extend(tg_ingest.chunk_document(blocks, e))
    if chunk_flags and not errors:
        try:
            errors += apply_chunk_flags(chunks, load_chunk_flags(chunk_flags))
        except (OSError, ValueError, BuildError) as err:
            errors.append(f"chunk flags rejected: {err}")
    return chunks, errors


def recover(client):
    names = {c.name for c in client.list_collections()}
    if PREVIOUS in names:
        if COLLECTION in names and client.get_collection(COLLECTION).count() > 0:
            client.delete_collection(PREVIOUS)
        else:
            if COLLECTION in names:
                client.delete_collection(COLLECTION)
            client.get_collection(PREVIOUS).modify(name=COLLECTION)
    if STAGING in names:
        client.delete_collection(STAGING)


def build_staging(client, chunks, embeddings):
    store = Chroma(client=client, collection_name=STAGING,
                   embedding_function=rp.ProfileEmbeddings(embeddings, PROFILE),
                   collection_metadata={rp.PROFILE_METADATA_KEY: PROFILE.name})
    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i:i + BATCH_SIZE]
        store.add_documents(documents=batch, ids=[str(uuid4()) for _ in batch])


def verify_staging(client, chunks, expected_hashes):
    if not chunks:
        raise BuildError("no chunks to index")
    staging = client.get_collection(STAGING)
    if (staging.metadata or {}).get(rp.PROFILE_METADATA_KEY) != PROFILE.name:
        raise BuildError(f"staging does not record rag_profile={PROFILE.name!r}")
    metadatas = staging.get(include=["metadatas"])["metadatas"]
    if len(metadatas) != len(chunks):
        raise BuildError(f"staging has {len(metadatas)} chunks, expected {len(chunks)}")
    for m in metadatas:
        m = m or {}
        if not legal_approval.SHA256_RE.match(str(m.get("sha256", ""))):
            raise BuildError("a staged chunk has no valid sha256")
        if m["sha256"] not in expected_hashes:
            raise BuildError("a staged chunk comes from a document outside the manifest")
        if m.get("jurisdiction") != tg_manifest.JURISDICTION or m.get("state") != tg_manifest.JURISDICTION:
            raise BuildError("a staged chunk is not tagged Telangana (mixed jurisdictions)")
        if not m.get("provision_id") or not m.get("location") or not m.get("title"):
            raise BuildError("a staged chunk is missing provision, location or title metadata")
        if not isinstance(m.get("answer_eligible"), bool):
            raise BuildError("a staged chunk has no answer_eligible flag")
    missing = expected_hashes - {m["sha256"] for m in metadatas}
    if missing:
        raise BuildError(f"{len(missing)} manifest document(s) produced no chunks")


def swap_in_staging(client):
    names = {c.name for c in client.list_collections()}
    had_live = COLLECTION in names
    if had_live:
        client.get_collection(COLLECTION).modify(name=PREVIOUS)
    client.get_collection(STAGING).modify(name=COLLECTION)
    if had_live:
        client.delete_collection(PREVIOUS)


def main(manifest_path, corpus_dir, db_dir=DEFAULT_DB_DIR, approval_path=None, trusted_keys=None,
         allow_unapproved=False, embeddings=None, out=print, chunk_flags=None) -> int:
    chunks, errors = prepare(manifest_path, corpus_dir, db_dir, approval_path, trusted_keys, allow_unapproved,
                             chunk_flags)
    if not errors and not chunks:
        errors = ["no chunks were produced"]
    if errors:
        out("Build FAILED - no index was changed:")
        for e in errors:
            out(f"  {e}")
        return 1
    expected = {c.metadata["sha256"] for c in chunks}
    client = chromadb.PersistentClient(path=str(db_dir))
    recover(client)
    try:
        if embeddings is None:  # only for real runs; tests always inject fakes
            from langchain_ollama import OllamaEmbeddings
            embeddings = OllamaEmbeddings(model="nomic-embed-text")
        build_staging(client, chunks, embeddings)
        verify_staging(client, chunks, expected)
    except Exception as e:
        if STAGING in {c.name for c in client.list_collections()}:
            client.delete_collection(STAGING)
        out(f"Build FAILED - the previous index was kept: {e}")
        return 1
    swap_in_staging(client)
    out(f"Done. Indexed {len(chunks)} provision chunks from {len(expected)} documents into {COLLECTION}.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build the Telangana-only index.")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--db-dir", default=str(DEFAULT_DB_DIR))
    ap.add_argument("--approval")
    ap.add_argument("--trusted-keys")
    ap.add_argument("--chunk-flags", help="reviewed extraction flags (JSON)")
    ap.add_argument("--preview-unapproved", action="store_true",
                    help="build without approval; only allowed into a non-production --db-dir")
    a = ap.parse_args()
    sys.exit(main(a.manifest, a.corpus, a.db_dir, a.approval, a.trusted_keys, a.preview_unapproved,
                  chunk_flags=a.chunk_flags))
