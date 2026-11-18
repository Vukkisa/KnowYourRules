"""Stage 6D integration probe, run by tests/test_lifecycle_integration_real.py and eval/latency/stage6d/run_stage6d.sh in its
own process: the REAL backend.server FastAPI app (TestClient, real /chat /status /health), TG_LIFECYCLE_DIR set to a registry
COPY, TG_DB_DIR a COPY of a real index, real Ollama query embeddings, real retrieval (exact or hnsw), real validator, real answer
cache. The answering model is the deterministic stand-in of tests/answer_cache_gen.py; no generation provider is called.

Positive-path approval is simulated by patching the server's approval STATE (not by writing approval evidence): satisfy_gate()
makes every prerequisite of grounded_gate_errors() true except the lifecycle clause, which is the real code. No approval record,
signature or key is created for the real sources.

usage: lifecycle_integration_probe.py startup|partial   (env: APPROVED_IDS="tmvr-1989-chap-2,tmvr-1989-chap-8" for partial)"""
import json
import logging
import os
import sys
import tempfile
import time
import types
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
logging.disable(logging.INFO)
T0 = time.perf_counter()

import real_backend_probe as probe  # noqa: E402
from answer_cache_gen import Gen  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import document_lifecycle as dl  # noqa: E402
from backend import legal_approval as la  # noqa: E402
from backend import tg_manifest  # noqa: E402

srv = probe.srv
IMPORT_SECONDS = time.perf_counter() - T0
client = TestClient(srv.app)
STATE, DB = Path(os.environ["TG_LIFECYCLE_DIR"]) if os.environ.get("TG_LIFECYCLE_DIR") else None, Path(os.environ["TG_DB_DIR"])
CASES = json.loads((ROOT / "eval" / "telangana-retrieval-benchmark.json").read_text())["cases"]
out = {"scenario": sys.argv[1], "vector_search": srv.VECTOR_SEARCH, "import_seconds": round(IMPORT_SECONDS, 2),
       "startup": srv.LIFECYCLE_STARTUP, "violations": []}


class RecGen(Gen):
    """The stand-in model, recording exactly what a provider would have been sent."""

    def __init__(self, srv):
        super().__init__(srv)
        self.prompts, self.evidence_shas = [], []

    def generate(self, prompt, contract):
        self.prompts.append(prompt)
        self.evidence_shas += [e.sha256 for e in contract.evidence]
        return super().generate(prompt, contract)


gen = RecGen(srv)
srv.ANSWER_GENERATOR = gen
ALL_ROWS = ALL_SHAS = FORBIDDEN = None   # the index copy BEFORE any operation: the forbidden-text oracle


def satisfy_gate():
    """Everything grounded_gate_errors() demands except the lifecycle clause (real code), as a test fixture."""
    srv.GROUNDED_ANSWERS_ENABLED, srv.ANSWER_MODE = True, "grounded"
    srv.CORPUS_DIR = Path("/nonexistent/fixture-corpus")
    srv._FINGERPRINT = srv.approval_fingerprint()
    srv._STALE = False


def reload_status():
    """Re-read the source-status registry the way the server does, without the fixture's non-existent corpus directory
    (which would make the real registry look invalid for a reason unrelated to this test)."""
    keep, srv.CORPUS_DIR = srv.CORPUS_DIR, None
    try:
        return srv.load_source_status()
    finally:
        srv.CORPUS_DIR = keep


def chat(q, sid="s"):
    r = client.post("/chat", json={"message": q, "session_id": sid})
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    check_eligible(body)
    return r.status_code, body


def servable_now():
    return {s for s in ALL_SHAS if srv.LIFECYCLE.servable(s)}


def check_eligible(body):
    """Invariant on EVERY response: each cited passage belongs to a version that is servable right now."""
    ok = servable_now()
    for src in body.get("sources", []) or []:
        for p in src.get("passages", []) or []:
            if p.get("sha256") not in ok:
                out["violations"].append({"cited_ineligible": p.get("sha256"), "label": p.get("label")})
        if src.get("sha256") and src["sha256"] not in ok:
            out["violations"].append({"source_ineligible": src["sha256"]})


def check_provider_stage(allowed):
    """Nothing quarantined/ineligible may ever have been sent to the (stand-in) provider."""
    bad_ev = [s for s in gen.evidence_shas if s not in allowed]
    leaked = [i for i, p in enumerate(gen.prompts) for body in FORBIDDEN if body in p]
    return {"prompts": len(gen.prompts), "evidence_items": len(gen.evidence_shas), "ineligible_evidence": len(bad_ev),
            "forbidden_text_in_prompts": len(leaked)}


def retrieval_all():
    res, sha_counts = {}, Counter()
    for c in CASES:
        shas = [d.metadata.get("sha256") for d in srv.retrieve(c["question"])]
        res[c["id"]] = shas
        sha_counts.update(shas)
    return res, sha_counts


def unfiltered_retrieval_shas():
    configured, srv.LIFECYCLE = srv.LIFECYCLE, dl.ServeFilter(None)
    try:
        return {s for c in CASES for s in (d.metadata.get("sha256") for d in srv.retrieve(c["question"]))}
    finally:
        srv.LIFECYCLE = configured


def snapshot_rows():
    if srv.vector_store is None:
        return []
    rows = srv.vector_store.get(include=["documents", "metadatas"])
    return [((m or {}).get("sha256"), d.partition("\n")[2] or d) for d, m in zip(rows["documents"], rows["metadatas"])]


def prepare_oracle(approved_shas=None):
    """Remember every chunk of the index as it was BEFORE any operation, and the text of those that are not approved."""
    global ALL_ROWS, ALL_SHAS, FORBIDDEN
    ALL_ROWS = snapshot_rows()
    ALL_SHAS = sorted({s for s, _ in ALL_ROWS if s})
    approved_shas = servable_now() if approved_shas is None else approved_shas
    ok_bodies = {b for s, b in ALL_ROWS if s in approved_shas}
    FORBIDDEN = sorted({b for s, b in ALL_ROWS if s not in approved_shas and len(b) > 60} - ok_bodies)


def startup_scenario():
    prepare_oracle()
    out["health"] = {"status": client.get("/health").status_code, "body": client.get("/health").json()}
    st = client.get("/status")
    out["status"] = {"code": st.status_code, "lifecycle": st.json().get("lifecycle"), "kb_approved": st.json()["kb_approved"],
                     "legal_review": st.json()["legal_review"], "index": st.json()["index"], "chunks": st.json()["chunks"]}
    res, counts = retrieval_all()
    out["retrieval"] = {"questions": len(res), "empty": sum(not v for v in res.values()), "shas": sorted(counts),
                        "unfiltered_shas": sorted(unfiltered_retrieval_shas())}
    qs = [c["question"] for c in CASES[:4]]
    out["chat_real_gate"] = [(lambda r: {"status": r[0], "kind": r[1].get("kind"), "text": r[1].get("response", "")[:90],
                                         "sources": len(r[1].get("sources", []))})(chat(q)) for q in qs]
    out["catalogue_replies"] = [(lambda r: {"q": q, "kind": r[1].get("kind"), "text": r[1].get("response", "")[:100]})(chat(q))
                                for q in ("What does Rule 10 say?", "What does Rule 9999 say?", "What does TMVR Rule 437 say?",
                                          "What does G.O.Ms.No. 10 of 2026 say?")]
    out["gate_errors_real"] = srv.grounded_gate_errors()[:3]
    routes = set()
    for r in srv.app.routes:
        methods = getattr(r, "methods", None)
        if methods is None:
            routes.add(("MOUNT", r.path))
        else:
            routes |= {(m, r.path) for m in methods if m not in ("HEAD", "OPTIONS")}
    routes -= {("GET", "/openapi.json"), ("GET", "/docs"), ("GET", "/docs/oauth2-redirect"), ("GET", "/redoc")}
    sample = client.post("/chat", json={"message": CASES[0]["question"], "session_id": "contract"})
    out["contracts"] = {
        "routes": sorted(f"{m} {p}" for m, p in routes),
        "chat_keys": sorted(sample.json()), "chat_status": sample.status_code,
        "kb_approved_field": sample.json().get("kb_approved"),
        "cors_header_present": "access-control-allow-origin" in {k.lower() for k in sample.headers},
        "cors_middleware": any("CORS" in type(m.cls).__name__ if hasattr(m, "cls") else False for m in srv.app.user_middleware)
                           or any("CORSMiddleware" in str(m) for m in srv.app.user_middleware),
        "root_status": client.get("/").status_code, "static_status": client.get("/static/index.html").status_code,
        "startup_handlers": len(srv.app.router.on_startup), "shutdown_handlers": len(srv.app.router.on_shutdown),
        "approval_refresh_present": ("POST", "/approval/refresh") in routes}
    satisfy_gate()
    out["gate_errors_satisfied"] = srv.grounded_gate_errors()
    out["chat_gate_satisfied"] = [(lambda r: {"status": r[0], "kind": r[1].get("kind"), "text": r[1].get("response", "")[:90],
                                              "sources": len(r[1].get("sources", []))})(chat(q)) for q in qs]
    out["cache"] = srv.ANSWER_CACHE.snapshot()
    out["provider_stage"] = check_provider_stage(set())
    out["servable_hashes"] = sorted(servable_now())


def delta(before):
    after = dict(srv.ANSWER_CACHE.stats)
    return {k: after.get(k, 0) - before.get(k, 0) for k in after if after.get(k, 0) != before.get(k, 0)}


def real_embeddings():
    from langchain_ollama import OllamaEmbeddings

    from backend import build_telangana_index as btx
    from backend import rag_profiles as rp
    return rp.ProfileEmbeddings(OllamaEmbeddings(model="nomic-embed-text"), btx.PROFILE)


def refresh_after_operation():
    """What an operator does after a lifecycle operation: the collection was swapped, so reopen it and refresh approval state."""
    srv.vector_store = srv.open_store()
    satisfy_gate()


def served(q, sid="s"):
    code, body = chat(q, sid)
    return {"status": code, "kind": body.get("kind"), "cited": sorted({p["sha256"] for s in body.get("sources", []) for p in s["passages"]}),
            "warnings": len(body.get("source_warnings", []))}, body


def partial_scenario():
    approved_ids = os.environ["APPROVED_IDS"].split(",")
    lc = dl.Lifecycle(STATE, DB, embeddings=real_embeddings())
    reg = lc.load()
    approved = {s: reg["sources"][s]["versions"]["1"]["sha256"] for s in approved_ids}
    approved_shas = set(approved.values())
    prepare_oracle(approved_shas)
    out["registry"] = {"servable_expected": sorted(approved_shas), "sources": len(reg["sources"]),
                       "states": dict(Counter(v["state"] for s in reg["sources"].values() for v in s["versions"].values()))}
    out["verify"] = lc.verify()
    satisfy_gate()
    out["gate_errors"] = srv.grounded_gate_errors()
    out["health"] = srv.LIFECYCLE.health()
    res, counts = retrieval_all()
    unf = unfiltered_retrieval_shas()
    out["retrieval"] = {"shas": sorted(counts), "within_approved": set(counts) <= approved_shas, "non_empty": sum(bool(v) for v in res.values()),
                        "unfiltered_includes_quarantined": bool(unf - approved_shas)}
    # questions the approved documents can answer, and questions only quarantined documents could
    good, only_quarantined = [], []
    id_of = {sha: sid for sid, sha in approved.items()}
    for c in CASES:
        exp = set(c.get("expected_documents") or [])
        if exp and exp <= set(approved_ids):
            good.append(c["question"])
        elif exp and not (exp & set(approved_ids)):
            only_quarantined.append(c["question"])
    warm = []
    for q in good:
        info, body = served(q)
        if info["kind"] == "answer":
            warm.append((q, info, body))
        if len(warm) == 3:
            break
    out["cold"] = [{"q": q[:60], **i} for q, i, _ in warm]
    out["cold_all_cited_in_approved"] = all(set(i["cited"]) <= approved_shas and i["cited"] for _, i, _ in warm)
    out["warnings_on_cold"] = all(i["warnings"] >= 1 for _, i, _ in warm)
    # warm cache: exact, then a semantic neighbour; bodies must equal the cold answers (same warnings, same citations)
    hits, same = [], []
    for q, i, body in warm:
        before = dict(srv.ANSWER_CACHE.stats)
        info, again = served(q, "another-user")
        hits.append(bool(delta(before).get("hit_exact")))
        same.append(again == body)
    out["warm"] = {"hit_exact": hits, "identical_to_cold": same}
    qq = {"q": warm[0][0]}
    sem_before = dict(srv.ANSWER_CACHE.stats)
    info, sbody = served(warm[0][0].replace("two-wheeler", "two wheeler").replace("  ", " ") + " ")
    out["warm"]["variant_kind"] = info["kind"]
    out["warm"]["variant_cache_delta"] = delta(sem_before)
    # quarantined-only questions: nothing from a quarantined document
    qinfo = [served(q)[0] for q in only_quarantined[:8]]
    out["quarantined_only_questions"] = {"asked": len(qinfo), "cited_ineligible": sum(not set(i["cited"]) <= approved_shas for i in qinfo),
                                         "kinds": dict(Counter(i["kind"] for i in qinfo))}
    import re as _re
    inelig = next(ref for ref, ids in sorted(srv.PROVISION_CATALOGUE.items())
                  if ids and _re.fullmatch(r"Rule \d+", ref) and not any(srv.eligible_manifest(i) for i in ids))
    amb_info, amb_body = served("What does Rule 10 say?")
    inel_info, inel_body = served(f"What does TMVR {inelig} say?")
    out["catalogue_replies"] = {
        "rule_10_exists_in_quarantined_tmvtr": "Rule 10" in srv.PROVISION_CATALOGUE and any(
            i.startswith("tmvtr") for i in srv.PROVISION_CATALOGUE["Rule 10"]),
        "rule_10_reply_kind": amb_info["kind"], "rule_10_names_ineligible_instrument": bool(
            _re.search(r"Taxation|TMVTR|1963", amb_body.get("response", ""))),
        "ineligible_only_ref": inelig, "ineligible_only_kind": inel_info["kind"],
        "ineligible_only_text": inel_body.get("response", "")[:90],
        "lookup_ambiguous_for_go": [list(map(str, a))[:1] for a in (srv.provision_lookup("What does G.O.Ms.No. 10 say?").ambiguous or [])]}
    out["provider_stage_before_ops"] = check_provider_stage(approved_shas)
    # cache storage failure and cache off never produce unvalidated answers
    class Broken(srv.answer_cache.MemoryStore):
        def get(self, k): raise OSError("x")
        def put(self, k, e): raise OSError("x")
        def values(self): raise OSError("x")
    keep = srv.ANSWER_CACHE.store
    srv.ANSWER_CACHE.store = Broken()
    broken = served(warm[0][0], "broken-store")[0]
    srv.ANSWER_CACHE.store = keep
    off = srv.CACHE_SETTINGS
    srv.CACHE_SETTINGS = srv.answer_cache.Settings(mode="off")
    before = dict(srv.ANSWER_CACHE.stats)
    off_r = served(warm[0][0], "cache-off")[0]
    out["cache_modes"] = {"broken_store": broken, "off": off_r, "off_cache_delta": delta(before)}
    srv.CACHE_SETTINGS = off

    # ---- runtime corruption of registry/audit: cached answers must not bypass it
    q0 = warm[0][0]
    reg_path, mirror = STATE / "registry.json", STATE / "audit.jsonl"
    good_reg, good_mirror = reg_path.read_bytes(), mirror.read_bytes()
    corruptions = {}

    def corrupt(name, fn):
        fn()
        before = dict(srv.ANSWER_CACHE.stats)
        info, body = served(q0, "corrupt-" + name)
        corruptions[name] = {"kind": info["kind"], "cited": info["cited"], "hit": bool(delta(before).get("hit_exact") or delta(before).get("hit_semantic")),
                             "health": srv.LIFECYCLE.health()["state"], "retrieved": sorted({d.metadata.get("sha256") for d in srv.retrieve(q0)})}
        reg_path.write_bytes(good_reg)
        mirror.write_bytes(good_mirror)
    corrupt("registry_garbage", lambda: reg_path.write_text("{garbage"))
    corrupt("registry_deleted", lambda: reg_path.unlink())

    def edit_event():
        r = json.loads(good_reg)
        r["events"][3]["note"] = "forged"
        reg_path.write_text(json.dumps(r, indent=1, sort_keys=True))
    corrupt("audit_chain_edited", edit_event)
    corrupt("mirror_deleted", lambda: mirror.unlink())
    corrupt("mirror_garbage", lambda: mirror.write_text("not json\n"))
    out["corruption"] = corruptions
    before = dict(srv.ANSWER_CACHE.stats)
    info, body = served(q0, "restored")
    out["after_restore"] = {"kind": info["kind"], "hit": bool(delta(before).get("hit_exact")), "health": srv.LIFECYCLE.health()["state"]}

    # ---- warning metadata: registry missing one entry => every source reads "status not recorded"; never dropped
    status_file = Path(srv.SOURCE_STATUS_FILE)
    good = json.loads(status_file.read_text())
    broken_reg = dict(good, entries=good["entries"][1:])
    tmp = Path(tempfile.mkdtemp(prefix="kyr-status-")) / "source-status.json"
    tmp.write_text(json.dumps(broken_reg))
    keep_file = srv.SOURCE_STATUS_FILE
    srv.SOURCE_STATUS_FILE = tmp
    reload_status()
    srv._FINGERPRINT = srv.approval_fingerprint()
    srv._STALE = False
    wr_gate = srv.grounded_gate_errors()
    info_w, body_w = served(q0, "bad-status")
    docs = srv.retrieve(q0)
    direct = srv.source_warnings(docs, list(range(1, len(docs) + 1)))
    out["warning_metadata_missing"] = {"registry_state": srv.SOURCE_STATUS.state, "gate_errors": wr_gate[:2], "kind": info_w["kind"],
                                       "retrieved_docs": len(docs), "warnings_generated_directly": len(direct),
                                       "warning_status_ids": sorted({w["status"] for w in direct})}
    srv.SOURCE_STATUS_FILE = keep_file
    reload_status()
    satisfy_gate()
    out["after_status_restore"] = {"state": srv.SOURCE_STATUS.state, "gate_errors": srv.grounded_gate_errors()}

    # ---- lifecycle transitions with a running app (cache warm)
    def settle_and_ask(label, qs):
        refresh_after_operation()
        res = []
        for q in qs:
            before = dict(srv.ANSWER_CACHE.stats)
            info, _ = served(q, "ops-" + label)
            res.append(dict(info, q=q[:50], hit=bool(delta(before).get("hit_exact") or delta(before).get("hit_semantic")),
                            invalidated=delta(before).get("invalidated_epoch", 0)))
        return res

    ops = {}
    asked = [q for q, _, _ in warm]
    # (a) reject a quarantined document: its chunks leave the index, nothing else changes
    qid = next(s for s in reg["sources"] if s not in approved_ids)
    r = lc.reject(qid, 1, by="integration-test", note="6D reject check")
    ops["reject_quarantined"] = {"result": r, "after": settle_and_ask("reject", asked)}
    # (b) supersede: an amended copy of the first approved document is approved; its hash is not in the running index snapshot
    sid = approved_ids[0]
    old_sha = approved[sid]
    snap = lc._read_snapshot(old_sha)
    work = Path(tempfile.mkdtemp(prefix="kyr-6d-corpus-"))
    (work / "amended.txt").write_text("\n".join(c["text"] for c in snap["chunks"]) + "\nAmended in the 6D test.")
    new_sha = tg_manifest.sha256_file(work / "amended.txt")
    m0 = snap["chunks"][0]["metadata"]
    lc.chunker = lambda entry, corpus: [dl.Chunk(c["text"] + ("\nAmended in the 6D test." if i == 0 else ""), dict(c["metadata"], sha256=new_sha))
                                        for i, c in enumerate(snap["chunks"])]
    entry = tg_manifest.ManifestEntry(id=sid, title=m0["title"], document_type=m0["document_type"], issuing_authority=m0["issuing_authority"] or None,
                                      document_number=m0["document_number"] or None, publication_date=None, effective_date=None, source_url=None,
                                      file="amended.txt", jurisdiction="Telangana", format="html", source_class=m0["source_class"],
                                      verification_status=m0["verification_status"], sha256=new_sha, notes=None)
    ing = lc.ingest(entry, work, by="integration-test")
    pend = settle_and_ask("pending-amendment", asked)      # pending content is not served; the active version keeps serving
    ap = lc.approve(sid, ing["version"], by="integration-test", note="6D supersede check")
    entries_before_sup = srv.ANSWER_CACHE.snapshot()["entries"]
    sup = settle_and_ask("superseded", asked)
    entries_after_sup = srv.ANSWER_CACHE.snapshot()["entries"]
    ops["pending_amendment"] = pend
    ops["supersede"] = {"approve": {k: ap[k] for k in ("replaced", "embedded")}, "after": sup, "old_sha": old_sha, "new_sha": new_sha,
                        "old_servable": srv.LIFECYCLE.servable(old_sha), "new_servable_in_running_app": srv.LIFECYCLE.servable(new_sha),
                        "cache_entries_before_blocked_requests": entries_before_sup, "cache_entries_after_blocked_requests": entries_after_sup}
    # (c) rollback to the original: the answers built before the supersede may be served again, but only after revalidation
    rb = lc.rollback(sid, 1, by="integration-test", note="6D rollback check")
    back = settle_and_ask("rollback", asked)
    ops["rollback"] = {"result": {k: rb[k] for k in ("replaced", "embedded")}, "after": back, "old_servable": srv.LIFECYCLE.servable(old_sha),
                       "new_servable": srv.LIFECYCLE.servable(new_sha)}
    # (d) withdraw the second approved document
    wsid = approved_ids[1]
    lc.withdraw(wsid, 1, by="integration-test", note="6D withdraw check")
    wd = settle_and_ask("withdraw", asked)
    ops["withdraw"] = {"after": wd, "withdrawn_servable": srv.LIFECYCLE.servable(approved[wsid])}
    out["ops"] = ops
    out["verify_after"] = lc.verify()
    out["audit_after"] = lc.audit_check()
    out["provider_stage_final"] = check_provider_stage(approved_shas | {new_sha})
    out["cache_final"] = srv.ANSWER_CACHE.snapshot()["counters"]


def main():
    if sys.argv[1] == "startup":
        startup_scenario()
    else:
        partial_scenario()
    print(json.dumps(out, default=str))


if __name__ == "__main__":
    main()
