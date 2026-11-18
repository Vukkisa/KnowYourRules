"""Run by tests/test_document_lifecycle_real.py in its own processes (phase a, then phase b = a restart): the real
backend.server with TG_CACHE=semantic and TG_LIFECYCLE_DIR on a throw-away COPY of a real index, real Ollama query
embeddings, real retrieval and validator, the real lifecycle module with the real embedding function. The answering
model is the deterministic stand-in of tests/answer_cache_gen.py. NO live provider is called.
Phase a bootstraps the registry (before the server is imported), warms the cache, ingests and approves an amended copy
of the document the answer cites, and withdraws nothing; phase b starts a fresh server on the mutated index."""
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
logging.disable(logging.INFO)

phase = sys.argv[1]
STATE = Path(os.environ["TG_LIFECYCLE_DIR"])
DB = Path(os.environ["TG_DB_DIR"])
MARK = "Amended by the Stage 6 test."


def real_embeddings():
    from langchain_ollama import OllamaEmbeddings
    from backend import build_telangana_index as btx
    from backend import rag_profiles as rp
    return rp.ProfileEmbeddings(OllamaEmbeddings(model="nomic-embed-text"), btx.PROFILE)


from backend import document_lifecycle as dl  # noqa: E402

if phase == "a" and not (STATE / "registry.json").is_file():   # one-time explicit import, before any server exists
    import chromadb
    import shutil
    from lifecycle_fixtures import BASIS
    peek = Path(tempfile.mkdtemp(prefix="kyr-peek-")) / "i"
    shutil.copytree(DB, peek)
    metas = chromadb.PersistentClient(path=str(peek)).get_collection(
        "telangana-traffic-rules", embedding_function=None).get(include=["metadatas"])["metadatas"]
    dl.Lifecycle(STATE, DB, embeddings=real_embeddings()).bootstrap("probe-operator", BASIS)   # synthetic basis, test data only

import real_backend_probe as probe  # noqa: E402
from answer_cache_gen import Gen  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import tg_manifest  # noqa: E402

srv = probe.srv
client = TestClient(srv.app)
gen = Gen(srv)
Q = "Is a helmet compulsory for two-wheeler riders?"
out = {"phase": phase, "vector_search": srv.VECTOR_SEARCH}


def chat(q=Q, sid="s"):
    r = client.post("/chat", json={"message": q, "session_id": sid})
    return r.status_code, (r.json() if r.status_code == 200 else {})


def shas(body):
    return {p["sha256"] for s in body.get("sources", []) for p in s.get("passages", [])}


def delta(before):
    after = dict(srv.ANSWER_CACHE.stats)
    return {k: after.get(k, 0) - before.get(k, 0) for k in after if after.get(k, 0) != before.get(k, 0)}


def main():
    probe.open_grounded_gate(srv.vector_store.get(include=["metadatas"]))
    srv.ANSWER_GENERATOR = gen
    lc = dl.Lifecycle(STATE, DB, embeddings=real_embeddings())
    out["lifecycle_enabled"] = srv.LIFECYCLE.enabled
    out["verify_at_start"] = lc.verify()
    s1, a = chat()
    s2, b = chat("Is a helmet compulsory for two wheeler riders?", "other")
    out["warm"] = {"status": [s1, s2], "kinds": [a["kind"], b["kind"]], "cited": sorted(shas(a)),
                   "counters": dict(srv.ANSWER_CACHE.stats)}
    if phase == "a":
        old_sha = next(iter(shas(a)))
        reg = lc.load()
        sid = next(k for k, v in reg["sources"].items() if any(r["sha256"] == old_sha for r in v["versions"].values()))
        snap = lc._read_snapshot(old_sha)
        text = "\n".join(c["text"] for c in snap["chunks"])
        work = Path(tempfile.mkdtemp(prefix="kyr-lifecycle-corpus-"))
        (work / "amended.txt").write_text(text + "\n" + MARK)
        new_sha = tg_manifest.sha256_file(work / "amended.txt")
        m0 = snap["chunks"][0]["metadata"]

        def chunker(entry, corpus):
            chunks = []
            for i, c in enumerate(snap["chunks"]):
                md = dict(c["metadata"], sha256=new_sha)
                chunks.append(dl.Chunk(c["text"] + (f"\n{MARK}" if i == 0 else ""), md))
            return chunks
        entry = tg_manifest.ManifestEntry(
            id=sid, title=m0["title"], document_type=m0["document_type"], issuing_authority=m0["issuing_authority"] or None,
            document_number=m0["document_number"] or None, publication_date=None, effective_date=None, source_url=None,
            file="amended.txt", jurisdiction="Telangana", format="html", source_class=m0["source_class"],
            verification_status=m0["verification_status"], sha256=new_sha, notes=None)
        lc.chunker = chunker
        r = lc.ingest(entry, work, by="probe-operator")
        pending_ok = chat(Q, "pending-check")[1]
        out["pending"] = {"ingest": r, "kind": pending_ok["kind"], "new_sha_in_response": new_sha in shas(pending_ok),
                          "old_sha_in_response": old_sha in shas(pending_ok),
                          "index_has_new": new_sha in {m["sha256"] for m in srv.vector_store.get(include=["metadatas"])["metadatas"]}}
        before = dict(srv.ANSWER_CACHE.stats)
        ap = lc.approve(sid, r["version"], by="probe-operator", note="amendment")
        out["approve"] = {k: ap[k] for k in ("embedded", "reused", "replaced")}
        srv.vector_store = srv.open_store()  # what a refresh/restart does: the swap replaced the collection object
        code, c = chat(Q, "after-approve")
        out["after_approve_in_process"] = {"status": code, "kind": c.get("kind"), "old_sha_in_response": old_sha in shas(c),
                                           "cache_delta": delta(before), "hit": bool(delta(before).get("hit_exact") or
                                                                                      delta(before).get("hit_semantic"))}
        out["state"] = {"sid": sid, "old": old_sha, "new": new_sha, "version": r["version"]}
        (STATE / "probe_state.json").write_text(json.dumps(out["state"]))
        out["verify_after"] = lc.verify()
    else:
        st = json.loads((STATE / "probe_state.json").read_text())
        out["state"] = st
        out["restart"] = {"new_sha_served": st["new"] in shas(a), "old_sha_served": st["old"] in shas(a),
                          "kind": a["kind"], "status_after_restart": lc.status()[st["sid"]]}
        before = dict(srv.ANSWER_CACHE.stats)
        lc.rollback(st["sid"], 1, by="probe-operator", note="probe rollback")
        srv.vector_store = srv.open_store()
        code, c = chat(Q, "after-rollback")
        out["after_rollback_in_process"] = {"status": code, "kind": c.get("kind"), "new_sha_in_response": st["new"] in shas(c),
                                            "cache_delta": delta(before),
                                            "hit": bool(delta(before).get("hit_exact") or delta(before).get("hit_semantic"))}
        out["verify_after"] = lc.verify()
    print(json.dumps(out, default=str))


if __name__ == "__main__":
    main()
