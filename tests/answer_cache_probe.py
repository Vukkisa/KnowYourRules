"""Run by tests/test_answer_cache_real.py (and by hand for eval/latency/stage5/) in its own process: the real backend.server
with TG_CACHE=semantic on a throw-away COPY of a real Telangana index, real Ollama embeddings, real retrieval, real validator,
the real cache. Only the answering model is replaced by tests/answer_cache_gen.Gen (quotes validated evidence sentences;
counts calls). NO live provider is called. Prints one JSON document as its last stdout line."""
import json
import logging
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
logging.disable(logging.INFO)

import real_backend_probe as probe  # noqa: E402
from answer_cache_gen import Gen  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import answer_cache as ac  # noqa: E402

srv = probe.srv
client = TestClient(srv.app)
gen = Gen(srv)
FIRST = "Is a helmet compulsory for two-wheeler riders?"
SPACED = "Is a helmet compulsory for two wheeler riders?"        # same situation, different words
OTHER_WHEELS = "Is a helmet compulsory for four-wheeler riders?"  # different vehicle class
NEGATED = "Is a helmet not compulsory for two-wheeler riders?"
DEFAULT = srv.CACHE_SETTINGS
OFF = ac.Settings(mode="off")
out = {"vector_search": srv.VECTOR_SEARCH, "scenarios": {}}


def chat(q, sid="s"):
    r = client.post("/chat", json={"message": q, "session_id": sid})
    return r.status_code, (r.json() if r.status_code == 200 else {})


def counters():
    return dict(srv.ANSWER_CACHE.stats)


def delta(before):
    after = counters()
    return {k: after.get(k, 0) - before.get(k, 0) for k in after if after.get(k, 0) != before.get(k, 0)}


def fresh_body(q):
    """What the pipeline answers with the cache OFF, for comparison with a cache hit."""
    srv.CACHE_SETTINGS = OFF
    try:
        return chat(q, "fresh")[1]
    finally:
        srv.CACHE_SETTINGS = DEFAULT


def reset(mode="quote"):
    srv.ANSWER_CACHE.clear()
    srv.ANSWER_CACHE.stats.clear()
    srv.ANSWER_CACHE._epoch = None
    srv._LIVE.update(fp=None, at=0.0, map={})
    gen.calls, gen.mode = 0, mode


def scenario(name):
    def deco(fn):
        reset()
        try:
            out["scenarios"][name] = fn()
        except Exception as exc:  # noqa: BLE001
            out["scenarios"][name] = {"exception": f"{type(exc).__name__}: {exc}"}
        return fn
    return deco


def main():
    probe.open_grounded_gate(srv.vector_store.get(include=["metadatas"]))
    srv.ANSWER_GENERATOR = gen

    @scenario("exact_hit")
    def _():
        s1, a = chat(FIRST)
        c1 = gen.calls
        s2, b = chat(FIRST, "another-user")
        s3, c = chat("  is a HELMET compulsory for two-wheeler riders ?? ", "third-user")
        return {"statuses": [s1, s2, s3], "kinds": [a["kind"], b["kind"], c["kind"]], "generations": [c1, gen.calls],
                "identical_to_first": [a == b, a == c], "counters": counters(), "sources": len(a["sources"])}

    @scenario("semantic_hit_equals_fresh_answer")
    def _():
        _, a = chat(FIRST)
        before = counters()
        _, hit = chat(SPACED)
        d = delta(before)
        calls_after_hit = gen.calls
        fresh = fresh_body(SPACED)
        return {"kinds": [a["kind"], hit["kind"]], "delta": d, "generations_after_hit": calls_after_hit,
                "hit_equals_fresh": hit == fresh, "generations_total": gen.calls}

    @scenario("different_legal_situation_is_a_miss")
    def _():
        res = {}
        chat(FIRST)
        for label, q in (("vehicle class", OTHER_WHEELS), ("negation", NEGATED),
                         ("location", "Is a helmet compulsory for two-wheeler riders in Warangal?"),
                         ("age", "Is a helmet compulsory for two-wheeler riders aged 12?")):
            before, calls = counters(), gen.calls
            _, r = chat(q)
            res[label] = {"kind": r["kind"], "generated": gen.calls - calls, "delta": delta(before)}
        return res

    @scenario("fee_and_date_questions_are_exact_only")
    def _():
        q = "What is the life tax for a two-wheeler?"
        chat(q)
        before = counters()
        chat("What is the life tax for a two wheeler?")  # would be a semantic hit were it not fee-related
        return {"delta": delta(before), "entries": srv.ANSWER_CACHE.snapshot()["entries"]}

    @scenario("unsupported_and_unvalidated_are_not_cached")
    def _():
        res = {}
        for mode in ("refuse", "malformed", "fabricate"):
            reset(mode)
            _, r = chat(FIRST)
            res[mode] = {"kind": r["kind"], "entries": srv.ANSWER_CACHE.snapshot()["entries"]}
        reset("penalty")
        _, r = chat(FIRST)
        res["penalty_wording"] = {"kind": r["kind"], "entries": srv.ANSWER_CACHE.snapshot()["entries"]}
        reset("refuse")
        chat(FIRST)
        chat(FIRST)
        res["refusal_is_regenerated_not_replayed"] = {"generations": gen.calls,
                                                     "entries": srv.ANSWER_CACHE.snapshot()["entries"]}
        reset()
        before = gen.calls
        _, r = chat(FIRST)
        res["recovers_after_failures"] = {"kind": r["kind"], "generated": gen.calls - before}
        return res

    @scenario("poisoned_entry_is_not_served")
    def _():
        chat(FIRST)
        entry = next(iter(srv.ANSWER_CACHE.store.items.values()))
        doc = json.loads(entry.raw)
        doc["claims"][0]["text"] += " The fee is Rs. 9999 for every applicant."
        doc["answer"] = doc["claims"][0]["text"]
        entry.raw = json.dumps(doc)  # tampered after validation
        before, calls = counters(), gen.calls
        _, r = chat(FIRST)
        return {"kind": r["kind"], "mentions_fabrication": "9999" in r.get("response", ""), "regenerated": gen.calls - calls,
                "delta": delta(before)}

    @scenario("penalty_question_stays_locked")
    def _():
        chat(FIRST)
        _, r = chat("What is the fine if a two-wheeler rider has no helmet?")
        _, r2 = chat("What is the penalty for not wearing a helmet?")
        return {"kinds": [r["kind"], r2["kind"]]}

    @scenario("vague_follow_up_never_uses_the_cache")
    def _():
        chat(FIRST, "conv")
        _, r = chat("and for a bike?", "conv")
        return {"kind": r["kind"]}

    @scenario("personal_identifiers_are_not_cached")
    def _():
        _, r = chat("My vehicle TS09AB1234 is a two-wheeler: is a helmet compulsory?")
        return {"kind": r["kind"], "entries": srv.ANSWER_CACHE.snapshot()["entries"],
                "bypassed": counters().get("bypass_uncacheable", 0)}

    @scenario("cache_off_never_stores_or_hits")
    def _():
        srv.CACHE_SETTINGS = OFF
        try:
            chat(FIRST), chat(FIRST)
        finally:
            srv.CACHE_SETTINGS = DEFAULT
        return {"generations": gen.calls, "entries": srv.ANSWER_CACHE.snapshot()["entries"], "counters": counters()}

    # ---- invalidation ----------------------------------------------------------------------------------------------
    def warm_then(change, restore=None, q=FIRST):
        reset()
        _, a = chat(q)
        warm_calls, entries = gen.calls, srv.ANSWER_CACHE.snapshot()["entries"]
        undo = change()
        before = counters()
        _, b = chat(q)
        res = {"warm_generations": warm_calls, "entries_before": entries, "after": b.get("kind"),
               "regenerated": gen.calls - warm_calls, "delta": delta(before), "same_answer": a == b}
        if undo:
            undo()
        return res

    def set_attr(obj, name, value):
        old = getattr(obj, name)
        setattr(obj, name, value)
        return lambda: setattr(obj, name, old)

    first_sha = next(iter(srv.SOURCES))

    @scenario("invalidation_source_withdrawn_from_approval")
    def _():
        def change():
            cited = {s["sha256"] for s in chat(FIRST)[1]["sources"] for s in s["passages"]} if False else None
            saved = dict(srv.SOURCES)
            srv.SOURCES.clear()
            return lambda: (srv.SOURCES.update(saved))
        return warm_then(change)

    @scenario("invalidation_new_amendment_ingested")
    def _():
        def change():
            srv.SOURCES["f" * 64] = ("Fixture amendment", "Amendment")
            return lambda: srv.SOURCES.pop("f" * 64, None)
        return warm_then(change)

    @scenario("invalidation_index_rebuilt_or_changed")
    def _():
        real = srv._index_fingerprint
        return warm_then(lambda: set_attr(srv, "_index_fingerprint", lambda: ("rebuilt-collection-id", 590)))

    @scenario("invalidation_embedding_model_changed")
    def _():
        return warm_then(lambda: set_attr(srv.embeddings_model.base, "model", "another-embedding-model"))

    @scenario("invalidation_chunking_configuration_changed")
    def _():
        return warm_then(lambda: set_attr(srv.rag_profiles, "CHUNK_SIZE", 500))

    @scenario("invalidation_retrieval_setting_changed")
    def _():
        return warm_then(lambda: set_attr(srv, "RETRIEVE_K", 5))

    @scenario("invalidation_validator_code_changed")
    def _():
        return warm_then(lambda: set_attr(srv, "_CODE_DIGEST", "different-validator-digest"))

    @scenario("invalidation_answer_generator_replaced")
    def _():
        return warm_then(lambda: set_attr(srv, "ANSWER_GENERATOR", Gen(srv)))

    @scenario("invalidation_ttl_expired")
    def _():
        clock = [1000.0]
        old = srv.ANSWER_CACHE.clock
        srv.ANSWER_CACHE.clock = lambda: clock[0]
        try:
            def change():
                clock[0] += DEFAULT.ttl_seconds + 1
            return warm_then(change)
        finally:
            srv.ANSWER_CACHE.clock = old

    @scenario("invalidation_cited_chunk_edited_in_place")
    def _():
        # Same id, same count: the epoch does not change. Only the dependency check (chunk identity) can notice.
        reset()
        _, a = chat(FIRST)
        entry = next(iter(srv.ANSWER_CACHE.store.items.values()))
        col = srv.vector_store._collection
        known = srv.live_chunks()
        victim = known[entry.cited_ids[0]]
        got = col.get(include=["documents", "metadatas", "embeddings"])
        idx = got["documents"].index(victim.page_content)
        cid, old_text, emb = got["ids"][idx], got["documents"][idx], [float(x) for x in got["embeddings"][idx]]
        col.update(ids=[cid], documents=[old_text + " [amended text]"], embeddings=[emb])
        srv._LIVE.update(at=0.0)
        before, calls = counters(), gen.calls
        try:
            _, b = chat(FIRST)
        finally:
            col.update(ids=[cid], documents=[old_text], embeddings=[emb])
            srv._LIVE.update(at=0.0)
        return {"kind": b["kind"], "regenerated": gen.calls - calls, "delta": delta(before)}

    @scenario("invalidation_cited_chunk_deleted")
    def _():
        reset()
        _, a = chat(FIRST)
        entry = next(iter(srv.ANSWER_CACHE.store.items.values()))
        col = srv.vector_store._collection
        victim = srv.live_chunks()[entry.cited_ids[0]]
        got = col.get(include=["documents", "metadatas", "embeddings"])
        idx = got["documents"].index(victim.page_content)
        saved = (got["ids"][idx], got["documents"][idx], got["metadatas"][idx])
        saved = saved + (got["embeddings"][idx],)
        col.delete(ids=[saved[0]])
        srv._LIVE.update(at=0.0)
        before, calls = counters(), gen.calls
        try:
            _, b = chat(FIRST)
            cited_ids_now = {srv.chunk_identity(d) for d in srv.live_chunks().values()}
        finally:
            col.add(ids=[saved[0]], documents=[saved[1]], metadatas=[saved[2]], embeddings=[[float(x) for x in saved[3]]])
            srv._LIVE.update(at=0.0, fp=None)
        return {"kind": b["kind"], "regenerated": gen.calls - calls, "delta": delta(before),
                "stale_answer_served": counters().get("hit_exact", 0) > 0, "deleted_chunk_still_listed": entry.cited_ids[0] in cited_ids_now}

    @scenario("invalidation_one_document_only")
    def _():
        reset()
        chat(FIRST)
        chat("What happens when a driving licence application is received?")
        e1, e2 = list(srv.ANSWER_CACHE.store.items.values())
        sha = e1.sources[0][0]
        only = [e for e in (e1, e2) if all(s != sha for s, _ in e.sources)]
        dropped = srv.ANSWER_CACHE.invalidate_source(sha)
        return {"entries_before": 2, "dropped": dropped, "entries_after": srv.ANSWER_CACHE.snapshot()["entries"],
                "entries_not_depending_on_it": len(only)}

    # ---- concurrency -----------------------------------------------------------------------------------------------
    @scenario("concurrent_identical_requests")
    def _():
        results, errors = [], []

        def worker(i):
            try:
                results.append(chat(FIRST, f"user-{i}")[1])
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        bodies = {json.dumps(r, sort_keys=True) for r in results}
        return {"errors": errors, "answers": len(results), "distinct_bodies": len(bodies),
                "kinds": sorted({r["kind"] for r in results}), "generations": gen.calls,
                "entries": srv.ANSWER_CACHE.snapshot()["entries"]}

    @scenario("cross_user_isolation")
    def _():
        chat(FIRST, "alice")
        _, b = chat(FIRST, "bob")
        sessions_before = {k: len(v["history"]) for k, v in srv.sessions.items()}
        return {"bob_body_is_fresh_body": b == fresh_body(FIRST), "history_lengths": sessions_before,
                "response_mentions_session": "alice" in json.dumps(b) or "bob" in json.dumps(b)}

    @scenario("no_withheld_source_in_cached_answers")
    def _():
        chat(FIRST)
        _, hit = chat(FIRST, "other")
        shas = {p["sha256"] for s in hit["sources"] for p in s["passages"]}
        return {"all_cited_sources_approved": all(h in srv.SOURCES for h in shas), "hit_mentions_third_schedule":
                "THIRD SCHEDULE" in json.dumps(hit).upper(), "sources": len(hit["sources"])}

    @scenario("storage_failure_is_harmless")
    def _():
        class Broken(ac.MemoryStore):
            def get(self, key):
                raise OSError("disk")

            def put(self, key, entry):
                raise OSError("disk")

            def values(self):
                raise OSError("disk")
        old = srv.ANSWER_CACHE.store
        srv.ANSWER_CACHE.store = Broken()
        try:
            s1, a = chat(FIRST)
            s2, b = chat(FIRST)
        finally:
            srv.ANSWER_CACHE.store = old
        return {"statuses": [s1, s2], "kinds": [a.get("kind"), b.get("kind")], "generations": gen.calls,
                "storage_errors": counters().get("storage_errors", 0)}

    print(json.dumps(out, default=str))


if __name__ == "__main__":
    main()
