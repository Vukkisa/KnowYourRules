"""
Rebuilds the Chroma vector store with CORRECT state metadata on every chunk.

Fixes a real bug: two files were downloaded via other states' pages and kept those
states' source-name prefixes even though their actual content is the Central Motor
Vehicles Act/Rules (applies nationwide, not state-specific). Without a correct
"state" tag, retrieval had no way to filter by state and the LLM was citing the
Central Act as if it were Madhya Pradesh state law.

The live index is never touched until a complete replacement has been built and verified:
every file is validated first, the new index is built in a separate "staging" collection,
and only then is it swapped in. Any failure exits with code 1 and leaves the live index as it was.

Chunking and embedding follow RAG_PROFILE (backend/rag_profiles.py; default "structured"); the profile is
recorded on the collection so the server embeds queries to match. Roll back with RAG_PROFILE=baseline.

Run with:
    .venv/Scripts/python.exe backend/build_index.py
(from the project root, GenAI/)
"""

import os
import sys
import time
from pathlib import Path
from uuid import uuid4

import chromadb
from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_community.document_loaders import UnstructuredPDFLoader
from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

try:  # run as backend/build_index.py or imported as backend.build_index
    import rag_profiles as rp
except ImportError:
    from backend import rag_profiles as rp

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=True)

CORPUS = BASE_DIR / "data" / "raw" / "full_extraction"
DB_DIR = BASE_DIR / "chroma_langchain_db"

# (relative path, correct state) - the two "Central" entries are the files that were
# discovered via Madhya Pradesh's and Andaman & Nicobar's pages but are actually the
# nationwide Motor Vehicles Act/Rules, not state-specific content.
SCOPE_FILES_WITH_STATE = [
    ("state/madhya-pradesh-mv-rules-1994-direct-pdf__a1988-59-b740e529.pdf", "Central"),
    ("union-territory/andaman-nicobar-islands-transport-acts-r__the-central-motor-vehicles-rules-1989-14ddf947.pdf", "Central"),
    ("state/gujarat-commissionerate-of-transport-act__gmv-rules-1989-a99d3b52.pdf", "Gujarat"),
    ("state/gujarat-commissionerate-of-transport-act__bmv-taact-1958-ba51970a.pdf", "Gujarat"),
    ("state/gujarat-commissionerate-of-transport-act__bmv-tax-rule-1959-cb64db21.pdf", "Gujarat"),
    ("union-territory/delhi-nct-transport-acts-and-rules-notif__delhi-motor-vehicles-rules-1993-as-amended-secreta-52c5b4c7.pdf", "Delhi"),
    ("union-territory/delhi-nct-transport-acts-and-rules-notif__the-delhi-motor-vehicle-taxation-act-r-2af515c1.pdf", "Delhi"),
    ("union-territory/delhi-nct-transport-acts-and-rules-notif__mact-6a89af46.pdf", "Delhi"),
    ("state/mizoram-act-rules__the-mizoram-motor-vehicle-taxation-act1996-4d1a51ab.pdf", "Mizoram"),
    ("state/mizoram-act-rules__online-special-road-permit-dil-dan-kimchang-1-8ac37036.pdf", "Mizoram"),
    ("state/mizoram-act-rules__sop-for-vlteas-1893dd12.pdf", "Mizoram"),
    ("state-road-safety-authority-cell/himachal-pradesh-road-safety-cell__action-plan-2024-25-beaf0f7b.pdf", "Himachal Pradesh"),
    ("union-territory/andaman-nicobar-islands-transport-acts-r__an-motor-aggregator-scheme-dca46278.pdf", "Andaman & Nicobar"),
    ("union-territory/andaman-nicobar-islands-transport-acts-r__finedet-e27a23fe.pdf", "Andaman & Nicobar"),
    ("central-statutory-technical-body/cpcb-vehicular-exhaust-emission-standard__it-technical-activity-2108d906.pdf", "Central"),
] + [
    (f"state/{p.name}", "Haryana")
    for p in (CORPUS / "state").glob("haryana-hartrans-gov-in-acts-rules__*.pdf")
]

COLLECTION = "india-traffic-rules"
STAGING = COLLECTION + "-staging"
PREVIOUS = COLLECTION + "-previous"  # the old live index, kept only while a swap is in progress
BATCH_SIZE = 50
RETRY_DELAY = 2
# Diagnostic heuristic, not a quality bar: a real Act/Rules PDF has far more text than this, so a
# file below it almost certainly "loaded" without extracting anything (scanned PDF, missing parser
# model, empty download).
MIN_CHARS = 200


class BuildError(Exception):
    pass


def load_documents(files, corpus_dir, loader_cls=UnstructuredPDFLoader):
    """Load every file. Returns (docs, errors); errors name each file that failed validation."""
    docs, errors = [], []
    for rel_path, state in files:
        f = corpus_dir / rel_path
        if not f.is_file():
            errors.append(f"[{state}] {rel_path}: file not found")
            continue
        try:
            loaded = loader_cls(str(f), strategy="fast", mode="single").load()
        except Exception as e:
            errors.append(f"[{state}] {f.name}: failed to load ({e})")
            continue
        chars = sum(len(d.page_content.strip()) for d in loaded)
        if chars < MIN_CHARS:
            errors.append(f"[{state}] {f.name}: only {chars} characters extracted (under the {MIN_CHARS}-character "
                          f"check - scanned PDF, missing parser model, or empty file?)")
            continue
        for d in loaded:
            d.metadata["source_file"] = f.name
            d.metadata["state"] = state
        docs.extend(loaded)
        print(f"  [{state}] {f.name} ({chars} chars)", flush=True)
    return docs, errors


def recover(client):
    """Finish or undo a swap that was interrupted, and drop any leftover staging collection."""
    names = {c.name for c in client.list_collections()}
    if PREVIOUS in names:
        live_ok = COLLECTION in names and client.get_collection(COLLECTION).count() > 0
        if live_ok:
            # The new index was already in place; the old copy is no longer needed.
            client.delete_collection(PREVIOUS)
        else:
            # Interrupted between the two renames (or the server created an empty live collection
            # meanwhile): put the previous index back.
            if COLLECTION in names:
                client.delete_collection(COLLECTION)
            client.get_collection(PREVIOUS).modify(name=COLLECTION)
            print("Recovered the previous index from an interrupted rebuild.", flush=True)
    if STAGING in names:
        client.delete_collection(STAGING)


def build_staging(client, splits, embeddings, profile=None):
    profile = profile or rp.PROFILES[rp.UNRECORDED_INDEX_PROFILE]
    store = Chroma(client=client, collection_name=STAGING, embedding_function=rp.ProfileEmbeddings(embeddings, profile),
                   collection_metadata={rp.PROFILE_METADATA_KEY: profile.name})
    uuids = [str(uuid4()) for _ in range(len(splits))]
    for i in range(0, len(splits), BATCH_SIZE):
        batch_docs = splits[i:i + BATCH_SIZE]
        batch_ids = uuids[i:i + BATCH_SIZE]
        for attempt in range(3):
            try:
                store.add_documents(documents=batch_docs, ids=batch_ids)
                break
            except Exception as e:
                last_error = e
                print(f"  batch {i}-{i+len(batch_docs)} attempt {attempt+1} failed: {e}", flush=True)
                time.sleep(RETRY_DELAY)
        else:
            raise BuildError(f"batch {i}-{i+len(batch_docs)} failed after 3 attempts: {last_error}")
        if i % 500 == 0:
            print(f"embedded {i}/{len(splits)}", flush=True)


def verify_staging(client, splits, profile=None):
    """Staging must hold exactly the expected chunks, each with state and source metadata, and record
    the profile it was built with (the server embeds queries according to that record)."""
    if not splits:
        raise BuildError("no chunks to index - refusing to replace the live index with an empty one")
    staging = client.get_collection(STAGING)
    if profile and (staging.metadata or {}).get(rp.PROFILE_METADATA_KEY) != profile.name:
        raise BuildError(f"staging does not record rag_profile={profile.name!r}")
    metadatas = staging.get(include=["metadatas"])["metadatas"]
    if len(metadatas) != len(splits):
        raise BuildError(f"staging has {len(metadatas)} chunks, expected {len(splits)}")
    if any(not (m or {}).get("state") or not (m or {}).get("source_file") for m in metadatas):
        raise BuildError("some staged chunks are missing state/source_file metadata")
    expected_states = {d.metadata["state"] for d in splits}
    staged_states = {m["state"] for m in metadatas}
    if staged_states != expected_states:
        raise BuildError(f"staged states {sorted(staged_states)} != expected {sorted(expected_states)}")


def swap_in_staging(client):
    """Rename live -> previous, staging -> live, then drop previous. No data is deleted before the
    new index is live; an interruption between the renames is undone by recover() on the next run."""
    names = {c.name for c in client.list_collections()}
    had_live = COLLECTION in names
    if had_live:
        client.get_collection(COLLECTION).modify(name=PREVIOUS)
    client.get_collection(STAGING).modify(name=COLLECTION)
    if had_live:
        client.delete_collection(PREVIOUS)


def main(corpus_dir=CORPUS, db_dir=DB_DIR, files=None, loader_cls=UnstructuredPDFLoader, embeddings=None, profile=None):
    try:
        profile = profile or rp.get_profile(os.environ.get("RAG_PROFILE"))
    except ValueError as e:
        print(f"\nBuild FAILED - the live index was not changed: {e}", flush=True)
        return 1
    print(f"Retrieval profile: {profile.name}", flush=True)
    check_haryana = files is None
    files = SCOPE_FILES_WITH_STATE if files is None else files
    print(f"{len(files)} files to index", flush=True)
    if not files:
        print("\nBuild FAILED - the live index was not changed: the file list is empty.", flush=True)
        return 1

    docs, errors = load_documents(files, corpus_dir, loader_cls)
    if check_haryana and not any(state == "Haryana" for _, state in files):
        errors.append(f"[Haryana] no files matched {corpus_dir / 'state'}/haryana-hartrans-gov-in-acts-rules__*.pdf")
    if errors:
        print("\nBuild FAILED - the live index was not changed. Files that failed validation:", flush=True)
        for e in errors:
            print(f"  {e}", flush=True)
        return 1

    all_splits = rp.split_documents(docs, profile, RecursiveCharacterTextSplitter)
    print(f"\nSplit {len(docs)} documents into {len(all_splits)} chunks.", flush=True)
    if not all_splits:
        print("\nBuild FAILED - the live index was not changed: splitting produced 0 chunks.", flush=True)
        return 1

    client = chromadb.PersistentClient(path=str(db_dir))
    recover(client)
    try:
        build_staging(client, all_splits, embeddings or OllamaEmbeddings(model="nomic-embed-text"), profile)
        verify_staging(client, all_splits, profile)
    except Exception as e:
        if STAGING in {c.name for c in client.list_collections()}:
            client.delete_collection(STAGING)
        print(f"\nBuild FAILED - the live index was not changed: {e}", flush=True)
        return 1

    swap_in_staging(client)
    states = sorted({d.metadata["state"] for d in all_splits})
    print(f"\nDone. Indexed {len(all_splits)} chunks from {len(docs)} files with profile '{profile.name}'; "
          f"states: {', '.join(states)}.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
