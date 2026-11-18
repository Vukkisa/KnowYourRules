"""OCI pilot Stage 2: session lifecycle. Deterministic and offline: a fake monotonic clock (no sleeps), the store tested directly,
and the real server on the fake-backed import of tests/test_server.py. No network, no model, no Groq or Gemini call.

Contract under test (backend/api_protection.py SessionStore, wired into POST /chat):
  expire idle sessions first; a live session is never evicted (locked or not); when every slot is live a NEW session is refused
  with a graceful 503 + Retry-After; activity refreshes the idle timer; an expired session cannot be revived."""
import json
import random
import re
import threading
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import test_server as ts
from backend import api_protection as ap
from test_api_protection import Clock, ServerIntegrationTests, server  # noqa: F401  (helpers; the class is not re-run here)

ROOT = Path(__file__).resolve().parent.parent
Q = "How do I apply for a learner's licence?"


def fresh(**state):
    return {"history": [], **state}


class StoreTests(unittest.TestCase):
    def store(self, max_sessions=3, ttl=100, clock=None):
        clock = clock or Clock()
        return ap.SessionStore(max_sessions, ttl, clock=clock), clock

    # 1 / 2 / 3: creation below capacity, at capacity, beyond capacity
    def test_creation_below_capacity(self):
        s, _ = self.store(max_sessions=5)
        for key in "abc":
            s[key] = fresh()
        self.assertEqual((len(s), sorted(s)), (3, ["a", "b", "c"]))

    def test_creation_exactly_at_capacity_succeeds(self):
        s, _ = self.store(max_sessions=3)
        made = [s.setdefault(k, fresh()) for k in "abc"]
        self.assertEqual(len(s), 3)
        self.assertEqual([s[k] for k in "abc"], made)

    def test_a_new_session_beyond_capacity_is_refused_and_nothing_is_created(self):
        s, _ = self.store(max_sessions=3)
        for key in "abc":
            s[key] = fresh()
        with self.assertRaises(ap.SessionCapacityExceeded):
            s.setdefault("d", fresh())
        with self.assertRaises(ap.SessionCapacityExceeded):
            s["e"] = fresh()
        self.assertEqual((len(s), sorted(s), "d" in s, "e" in s), (3, ["a", "b", "c"], False, False))

    def test_existing_sessions_keep_working_at_capacity(self):
        s, _ = self.store(max_sessions=2)
        a = s.setdefault("a", fresh())
        s.setdefault("b", fresh())
        self.assertIs(s.setdefault("a", fresh()), a)
        self.assertIs(s["a"], a)
        s["a"] = a                                           # re-assigning an existing key is not a creation

    def test_the_refusal_says_when_a_slot_frees_up(self):
        s, clock = self.store(max_sessions=2, ttl=100)
        s["a"] = fresh()                                     # t=0
        clock.advance(30)
        s["b"] = fresh()                                     # t=30
        clock.advance(20)                                    # t=50: "a" (the first to go) has 50 s left
        with self.assertRaises(ap.SessionCapacityExceeded) as caught:
            s["c"] = fresh()
        self.assertEqual(caught.exception.retry_after, 50)
        clock.advance(49.5)                                  # half a second left rounds UP, never to 0
        with self.assertRaises(ap.SessionCapacityExceeded) as caught:
            s["c"] = fresh()
        self.assertEqual(caught.exception.retry_after, 1)
        clock.advance(0.5)                                   # "a" is now exactly ttl idle: alive
        with self.assertRaises(ap.SessionCapacityExceeded):
            s["c"] = fresh()
        clock.advance(0.01)
        s["c"] = fresh()                                     # "a" has expired and freed its slot
        self.assertEqual(sorted(s), ["b", "c"])

    # 4 / 5: expiry and refresh
    def test_an_idle_session_expires_just_after_the_ttl(self):
        s, clock = self.store(ttl=100)
        s["a"] = fresh()
        clock.advance(100)
        self.assertIn("a", s)                                # exactly ttl: still alive
        clock.advance(0.001)
        self.assertNotIn("a", s)
        self.assertEqual(len(s), 0)

    def test_activity_refreshes_the_idle_timer(self):
        for touch in (lambda s: s["a"], lambda s: s.setdefault("a", fresh()), lambda s: s.__setitem__("a", s["a"])):
            s, clock = self.store(ttl=100)
            s["a"] = fresh()
            for _ in range(5):                               # 5 x 60 s = 300 s of life, far beyond one ttl
                clock.advance(60)
                touch(s)
            self.assertIn("a", s)
            clock.advance(101)
            self.assertNotIn("a", s)

    def test_looking_without_using_does_not_extend_a_session(self):
        s, clock = self.store(ttl=100)
        s["a"] = fresh()
        clock.advance(60)
        _ = ("a" in s, len(s), list(s))                      # membership, size and iteration are not activity
        clock.advance(41)
        self.assertNotIn("a", s)

    # 6: expired sessions cannot be revived
    def test_an_expired_session_is_gone_and_a_new_request_starts_empty(self):
        s, clock = self.store(ttl=100)
        old = s.setdefault("a", fresh(last_locked=True))
        old["history"].append({"question": "q", "answer": "a"})
        clock.advance(101)
        with self.assertRaises(KeyError):
            s["a"]
        again = s.setdefault("a", fresh())
        self.assertIsNot(again, old)
        self.assertEqual(again, {"history": []})            # no history and no lock flag come back

    def test_a_stale_holder_cannot_write_an_expired_session_back(self):
        s, clock = self.store(ttl=100)
        held = s.setdefault("a", fresh())                    # an in-flight request holds this object
        clock.advance(101)
        s.setdefault("other", fresh())                       # any access runs the expiry
        held["history"].append({"question": "late", "answer": "late"})
        held["last_locked"] = True
        self.assertNotIn("a", s)
        self.assertEqual(s.setdefault("a", fresh()), {"history": []})

    def test_pop_and_delete_of_an_expired_session_find_nothing(self):
        s, clock = self.store(ttl=100)
        s["a"], s["b"] = fresh(), fresh()
        clock.advance(101)
        self.assertIsNone(s.pop("a", None))
        with self.assertRaises(KeyError):
            del s["b"]

    # 7: expired sessions are removed before capacity is checked
    def test_expired_sessions_free_their_slots_before_the_capacity_check(self):
        s, clock = self.store(max_sessions=3, ttl=100)
        for key in "abc":
            s[key] = fresh()
        clock.advance(101)
        for key in "xyz":                                    # the table was full, yet three new ones fit
            s[key] = fresh()
        self.assertEqual(sorted(s), ["x", "y", "z"])
        self.assertEqual(len(s._data), 3)                    # and the expired ones are really gone from memory

    def test_only_the_expired_sessions_are_removed(self):
        s, clock = self.store(max_sessions=3, ttl=100)
        s["old"] = fresh()
        clock.advance(60)
        live1, live2 = s.setdefault("live1", fresh(last_locked=True)), s.setdefault("live2", fresh())
        clock.advance(41)                                    # "old" is 101 idle; the others 41
        new = s.setdefault("new", fresh())
        self.assertEqual(sorted(s), ["live1", "live2", "new"])
        self.assertIs(s["live1"], live1)
        self.assertIs(s["live2"], live2)
        self.assertIs(s["new"], new)

    # 8: a non-expired session is never silently evicted
    def test_live_sessions_are_never_evicted_locked_or_not(self):
        s, _ = self.store(max_sessions=4)
        originals = {"l1": s.setdefault("l1", fresh(last_locked=True)), "u1": s.setdefault("u1", fresh()),
                     "l2": s.setdefault("l2", fresh(last_locked=True, history=[{"question": "q", "answer": "a"}])),
                     "u2": s.setdefault("u2", fresh())}
        snapshots = {k: json.dumps(v, sort_keys=True) for k, v in originals.items()}
        refused = 0
        for i in range(2000):
            try:
                s.setdefault(f"new{i}", fresh())
            except ap.SessionCapacityExceeded:
                refused += 1
        self.assertEqual(refused, 2000)
        self.assertEqual(sorted(s), ["l1", "l2", "u1", "u2"])
        for key, obj in originals.items():
            self.assertIs(s[key], obj)
            self.assertEqual(json.dumps(obj, sort_keys=True), snapshots[key])

    def test_least_recently_used_is_not_special_when_full(self):
        s, _ = self.store(max_sessions=2)
        s["a"], s["b"] = fresh(), fresh()
        s["a"]                                               # "b" is now the least recently used
        with self.assertRaises(ap.SessionCapacityExceeded):
            s["c"] = fresh()
        self.assertEqual(sorted(s), ["a", "b"])

    # 9: concurrency
    def test_concurrent_creation_at_capacity_admits_exactly_the_capacity(self):
        s, _ = self.store(max_sessions=50, ttl=1000)
        barrier, ok, refused, lock = threading.Barrier(40), [], [], threading.Lock()

        def worker(n):
            barrier.wait()
            for i in range(25):
                try:
                    s.setdefault(f"t{n}-{i}", fresh())
                    with lock:
                        ok.append(1)
                except ap.SessionCapacityExceeded:
                    with lock:
                        refused.append(1)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(40)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual((len(ok), len(refused), len(s)), (50, 950, 50))

    def test_concurrent_requests_for_one_new_session_share_one_object(self):
        s, _ = self.store(max_sessions=1000)
        barrier, same = threading.Barrier(40), []

        def worker():
            barrier.wait()
            same.append(s.setdefault("shared", fresh()))

        threads = [threading.Thread(target=worker) for _ in range(40)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(len({id(x) for x in same}), 1)
        self.assertEqual(len(s), 1)

    def test_concurrent_access_and_expiry_keep_every_invariant(self):
        clock = Clock()
        s = ap.SessionStore(20, 50, clock=clock)
        survivors = {f"keep{i}": s.setdefault(f"keep{i}", fresh()) for i in range(5)}
        errors, stop = [], threading.Event()
        barrier = threading.Barrier(9)

        def toucher():                                       # keeps the "keep" sessions alive and reads them
            barrier.wait()
            while not stop.is_set():
                for key in survivors:
                    try:
                        assert s[key] is survivors[key]
                    except Exception as error:
                        errors.append(repr(error))
                        return

        def churner(seed):
            rng = random.Random(seed)
            barrier.wait()
            for _ in range(3000):
                try:
                    s.setdefault(f"c{rng.randrange(100)}", fresh())
                    len(s)
                    list(s)
                except ap.SessionCapacityExceeded:
                    pass
                except Exception as error:
                    errors.append(repr(error))
                    return

        def ticker():                                        # the only thing that moves time; always inside the ttl for "keep"
            barrier.wait()
            for _ in range(2000):
                clock.advance(0.01)                          # 20 s in total, well inside the 50 s ttl of the touched sessions

        threads = [threading.Thread(target=toucher)] + [threading.Thread(target=churner, args=(n,)) for n in range(7)] + \
                  [threading.Thread(target=ticker)]
        [t.start() for t in threads]
        [t.join() for t in threads[1:]]
        stop.set()
        threads[0].join()
        self.assertEqual(errors, [])
        self.assertLessEqual(len(s), 20)
        for key, obj in survivors.items():
            self.assertIs(s[key], obj)
            self.assertEqual(obj, {"history": []})            # nothing in the store ever altered a conversation

    def test_expiry_never_touches_conversation_contents(self):
        s, clock = self.store(max_sessions=10, ttl=100)
        keep = s.setdefault("keep", fresh(last_locked=True, history=[{"question": "q", "answer": "a"}]))
        before = json.dumps(keep, sort_keys=True)
        s.setdefault("gone", fresh())
        for _ in range(5):
            clock.advance(60)
            s["keep"]
            s.setdefault("gone", fresh())                    # expires and recreates around the survivor
        self.assertEqual(json.dumps(s["keep"], sort_keys=True), before)

    def test_the_default_clock_is_monotonic(self):
        from unittest import mock
        s = ap.SessionStore()
        with mock.patch("time.time", side_effect=AssertionError("wall clock must not be used")):
            s["a"] = fresh()
            self.assertIn("a", s)

    def test_it_behaves_like_the_dict_it_replaces(self):
        s, _ = self.store(max_sessions=5)
        s["a"] = fresh()
        self.assertEqual((len(s), list(s), s["a"]), (1, ["a"], {"history": []}))
        self.assertEqual({k: len(v["history"]) for k, v in s.items()}, {"a": 0})
        self.assertEqual(s.pop("a"), {"history": []})
        with self.assertRaises(KeyError):
            s["zzz"]
        s["b"] = fresh()
        s.clear()
        self.assertEqual(len(s), 0)

    def test_impossible_parameters_are_rejected(self):
        for args in ((0, 10), (5, 0), (-1, 10)):
            with self.assertRaises(ap.ConfigError):
                ap.SessionStore(*args)


class ConfigTests(unittest.TestCase):
    # 11: configuration
    def test_the_defaults_are_500_sessions_and_30_minutes(self):
        c = ap.config_from_env({})
        self.assertEqual((c.max_sessions, c.session_ttl_seconds), (500, 1800))
        self.assertEqual((ap.DEFAULT_MAX_SESSIONS, ap.DEFAULT_SESSION_TTL_SECONDS), (500, 1800))
        self.assertEqual((ap.SessionStore().max_sessions, ap.SessionStore().ttl), (500, 1800.0))

    def test_valid_values_are_used(self):
        c = ap.config_from_env({"TG_SESSION_MAX": "40", "TG_SESSION_TTL_SECONDS": "120"})
        self.assertEqual((c.max_sessions, c.session_ttl_seconds, c.problems), (40, 120, ()))

    def test_invalid_values_fall_back_to_the_defaults_without_echoing_the_value(self):
        for name, attr, default in (("TG_SESSION_MAX", "max_sessions", 500), ("TG_SESSION_TTL_SECONDS", "session_ttl_seconds", 1800)):
            for bad in ("abc", "0", "-1", "1.5", "1e3", "9" * 12, "٣", "0x10", "everything-SECRET"):
                c = ap.config_from_env({name: bad})
                self.assertEqual(getattr(c, attr), default, (name, bad))
                self.assertEqual(len(c.problems), 1, (name, bad))
                self.assertIn(name, c.problems[0])
                if len(bad) > 3:
                    self.assertNotIn(bad, c.problems[0])
            low, high = ap.RANGES[name]
            self.assertEqual(ap.config_from_env({name: str(low)}).problems, ())
            self.assertEqual(ap.config_from_env({name: str(high)}).problems, ())
            self.assertEqual(len(ap.config_from_env({name: str(low - 1)}).problems), 1)
            self.assertEqual(len(ap.config_from_env({name: str(high + 1)}).problems), 1)

    def test_the_env_example_documents_the_same_defaults(self):
        text = (ROOT / "deploy" / "cloud.env.example").read_text()
        self.assertRegex(text, r"(?m)^# TG_SESSION_MAX=500\b")
        self.assertRegex(text, r"(?m)^# TG_SESSION_TTL_SECONDS=1800\b")
        self.assertNotRegex(text, r"TG_SESSION_MAX=2000|TG_SESSION_TTL_SECONDS=3600")


class RealAppTests(unittest.TestCase):
    """The real /chat on the fake-backed server. The store's clock is replaced by a fake one so expiry is deterministic."""

    def setUp(self):
        self.addCleanup(ts.FAKE_SEARCH.update, {"fn": None})
        self.addCleanup(ts.FAKE_LLM.update, {"fn": lambda prompt: "stub answer"})

    def app(self, max_sessions="3", **env):
        srv, client = server(TG_SESSION_MAX=max_sessions, TG_RATE_LIMIT_REQUESTS="1000", **env)
        srv.sessions._clock = Clock()
        return srv, client, srv.sessions._clock

    def chat(self, client, sid, message=Q):
        return client.post("/chat", json={"message": message, "session_id": sid})

    def test_new_sessions_up_to_the_limit_work_and_the_next_is_refused_gracefully(self):
        srv, client, _ = self.app("3")
        self.assertEqual([self.chat(client, f"s{i}").status_code for i in range(3)], [200, 200, 200])
        r = self.chat(client, "s3")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json(), {"detail": ap.GENERIC_SESSIONS_FULL})
        self.assertGreaterEqual(int(r.headers["retry-after"]), 1)
        self.assertNotIn("Traceback", r.text)
        self.assertEqual((len(srv.sessions), "s3" in srv.sessions), (3, False))

    def test_existing_conversations_continue_at_capacity_with_their_state(self):
        srv, client, _ = self.app("2")
        self.chat(client, "a")
        self.chat(client, "b")
        self.assertEqual(self.chat(client, "c").status_code, 503)
        before = srv.sessions["a"]
        self.assertEqual(self.chat(client, "a", "What documents are needed for it?").status_code, 200)
        self.assertIs(srv.sessions["a"], before)
        self.assertEqual(len(before["history"]), 2)

    def test_after_the_idle_timeout_the_slot_is_free_and_the_old_conversation_is_gone(self):
        srv, client, clock = self.app("2")
        self.chat(client, "a")
        self.chat(client, "b")
        self.assertEqual(self.chat(client, "c").status_code, 503)
        clock.advance(1801)
        self.assertEqual(self.chat(client, "c").status_code, 200)
        self.assertEqual(self.chat(client, "a").status_code, 200)               # "a" starts again, empty
        self.assertEqual(len(srv.sessions["a"]["history"]), 1)

    def test_activity_keeps_a_conversation_alive_past_one_timeout(self):
        srv, client, clock = self.app("2")
        for _ in range(4):
            self.chat(client, "talker")
            clock.advance(1000)                                                  # 4000 s in total, more than twice the 1800 s
        self.assertEqual(len(srv.sessions["talker"]["history"]), 4 if srv.MAX_HISTORY_TURNS >= 4 else srv.MAX_HISTORY_TURNS)

    def test_a_penalty_lock_survives_a_flood_and_still_applies(self):
        srv, client, _ = self.app("5")
        r = self.chat(client, "locked", "What is the fine for no helmet?")
        self.assertEqual(r.json()["kind"], "restricted")
        self.assertTrue(srv.sessions["locked"]["last_locked"])
        refused = [self.chat(client, f"flood-{i}").status_code for i in range(60)]
        self.assertEqual(refused.count(200), 4)                                  # the four free slots
        self.assertEqual(set(refused) - {200, 503}, set())
        self.assertTrue(srv.sessions["locked"]["last_locked"])                   # never evicted to make room
        self.assertEqual(self.chat(client, "locked", "for cars?").json()["kind"], "restricted")   # sticky lock still holds

    def test_a_lock_does_not_outlive_an_idle_expiry_but_cannot_be_washed_away_before_it(self):
        srv, client, clock = self.app("5")
        self.chat(client, "locked", "What is the fine for no helmet?")
        clock.advance(1800)                                                      # exactly the timeout: still locked
        self.assertEqual(self.chat(client, "locked", "for cars?").json()["kind"], "restricted")
        clock.advance(1801)                                                      # genuinely idle: forgotten
        self.assertNotIn("locked", srv.sessions)

    def test_the_penalty_gate_itself_is_unchanged_for_existing_and_new_sessions(self):
        srv, client, _ = self.app("2")
        self.assertEqual(self.chat(client, "x", "What is the fine for no helmet?").json()["kind"], "restricted")
        self.assertEqual(self.chat(client, "y").status_code, 200)
        self.assertEqual(self.chat(client, "x", "What is the fine for no helmet?").json()["kind"], "restricted")

    def test_a_refused_new_session_gets_no_processing_and_no_model_call(self):
        srv, client, _ = self.app("1")
        self.chat(client, "a")
        calls = []
        ts.FAKE_LLM["fn"] = lambda prompt: calls.append(prompt) or "stub"
        self.assertEqual(self.chat(client, "b").status_code, 503)
        self.assertEqual(calls, [])
        self.assertEqual(srv.QUESTION_SLOTS.in_use, 0)

    def test_concurrent_new_sessions_through_the_real_app_never_exceed_the_limit(self):
        srv, client, _ = self.app("5", TG_MAX_CONCURRENT_QUESTIONS="32")   # isolate the session limit from the question-slot limit
        results, lock = [], threading.Lock()
        barrier = threading.Barrier(12)

        def worker(n):
            barrier.wait()
            r = self.chat(client, f"c{n}")
            with lock:
                results.append(r.status_code)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(12)]
        [t.start() for t in threads]
        [t.join(30) for t in threads]
        self.assertEqual(sorted(set(results)), [200, 503])
        self.assertEqual((results.count(200), results.count(503), len(srv.sessions)), (5, 7, 5))

    def test_the_settings_reach_the_real_app_and_invalid_ones_fall_back(self):
        srv, _ = server()
        self.assertEqual((srv.sessions.max_sessions, srv.sessions.ttl), (500, 1800.0))
        srv, _ = server(TG_SESSION_MAX="0", TG_SESSION_TTL_SECONDS="forever")
        self.assertEqual((srv.sessions.max_sessions, srv.sessions.ttl), (500, 1800.0))
        self.assertEqual(len(srv.PROTECTION.problems), 2)
        status = TestClient(srv.app).get("/status").json()["protection"]
        self.assertEqual((status["max_sessions"], status["session_ttl_seconds"]), (500, 1800))

    # 12: existing session identifiers
    def test_the_identifiers_the_frontend_generates_are_accepted(self):
        html = (ROOT / "frontend" / "index.html").read_text()
        self.assertIn("crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random()", html)
        srv, client, _ = self.app("10")
        uuid = "3f2b8c1e-5a4d-4e6f-9b7a-0123456789ab"
        fallback = "1731561234567" + "0.123456789012345"                          # String(Date.now()) + Math.random()
        for sid in (uuid, fallback, "s", "y" * 128, "sess-ünï-తెలుగు"):
            self.assertEqual(self.chat(client, sid).status_code, 200, sid)
            self.assertIn(sid, srv.sessions)
        self.assertEqual(self.chat(client, "z" * 129).status_code, 422)
        self.assertEqual(self.chat(client, "").status_code, 200)                  # unchanged: an empty id was always accepted
        self.assertTrue(re.fullmatch(r"[0-9a-f-]{36}", uuid))


if __name__ == "__main__":
    unittest.main()
