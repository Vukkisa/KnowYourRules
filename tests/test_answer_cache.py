"""Stage 5: backend/answer_cache.py in isolation (no server, no network). Server wiring, replay validation, invalidation
against a changed index and the legal pairs on real embeddings are in tests/test_answer_cache_real.py."""
import threading
import unittest

import numpy as np

from backend import answer_cache as ac


def cache(mode="semantic", clock=None, store=None, **kw):
    s = ac.Settings(mode=mode, **kw)
    return ac.AnswerCache(s, clock=clock or (lambda: 0.0), store=store)


def vec(angle):
    return [float(np.cos(angle)), float(np.sin(angle)), 0.0]


def put(c, q="is a helmet compulsory", angle=0.0, epoch="E1", cited=("c1",), context=("c1", "c2"), sources=(("s" * 64, "m1"),)):
    return c.put(ac.normalize_query(q), ac.signature(q), vec(angle), epoch, '{"answer":"x"}', context, cited, sources)


class SettingsTests(unittest.TestCase):
    def test_default_is_off(self):
        self.assertEqual(ac.settings_from_env({}).mode, "off")
        self.assertFalse(ac.settings_from_env({}).enabled)

    def test_modes_and_kill_switch(self):
        self.assertEqual(ac.settings_from_env({"TG_CACHE": "Exact"}).mode, "exact")
        self.assertTrue(ac.settings_from_env({"TG_CACHE": "semantic"}).semantic)
        for flag in ("1", "true", "YES"):
            self.assertEqual(ac.settings_from_env({"TG_CACHE": "semantic", "TG_CACHE_DISABLED": flag}).mode, "off")
        self.assertEqual(ac.settings_from_env({"TG_CACHE": "bogus"}).mode, "off")

    def test_bad_numbers_fall_back_to_safe_defaults(self):
        s = ac.settings_from_env({"TG_CACHE": "semantic", "TG_CACHE_SIMILARITY": "0.2", "TG_CACHE_TTL_SECONDS": "x",
                                  "TG_CACHE_MAX_ENTRIES": "-3"})
        self.assertEqual((s.similarity, s.ttl_seconds, s.max_entries),
                         (ac.DEFAULT_SIMILARITY, ac.DEFAULT_TTL_SECONDS, ac.DEFAULT_MAX_ENTRIES))
        self.assertEqual(ac.settings_from_env({"TG_CACHE": "semantic", "TG_CACHE_SIMILARITY": "0.97"}).similarity, 0.97)


class NormalizeTests(unittest.TestCase):
    def test_only_cosmetic_changes(self):
        a = ac.normalize_query("  Is a HELMET   compulsory?? ")
        self.assertEqual(a, ac.normalize_query("is a helmet compulsory"))
        self.assertEqual(ac.normalize_query("Learner’s licence"), ac.normalize_query("learner's licence"))

    def test_meaningful_words_survive(self):
        self.assertNotEqual(ac.normalize_query("Is a helmet not required"), ac.normalize_query("Is a helmet required"))
        self.assertNotEqual(ac.normalize_query("Age 16"), ac.normalize_query("Age 18"))


class ExactLayerTests(unittest.TestCase):
    def test_exact_hit_and_miss(self):
        c = cache("exact")
        self.assertTrue(put(c))
        self.assertIsNotNone(c.lookup_exact(ac.normalize_query("Is a helmet compulsory?"), "E1"))
        self.assertIsNone(c.lookup_exact(ac.normalize_query("Is a helmet optional?"), "E1"))

    def test_disabled_cache_stores_nothing(self):
        c = cache("off")
        self.assertFalse(put(c))
        self.assertEqual(c.snapshot()["entries"], 0)

    def test_nothing_is_stored_without_an_answer_or_citation(self):
        c = cache("exact")
        self.assertFalse(c.put("q", frozenset(), None, "E1", "", ("a",), ("a",), ()))   # no validated output
        self.assertFalse(c.put("q", frozenset(), None, "E1", "{}", (), ("a",), ()))     # no context
        self.assertFalse(c.put("q", frozenset(), None, "E1", "{}", ("a",), (), ()))     # nothing cited
        self.assertFalse(c.put("q", frozenset(), None, "E1", "x" * (ac.MAX_RAW_CHARS + 1), ("a",), ("a",), ()))
        self.assertEqual(c.snapshot()["entries"], 0)

    def test_expiry(self):
        now = [0.0]
        c = cache("exact", clock=lambda: now[0], ttl_seconds=100)
        put(c)
        key = ac.normalize_query("is a helmet compulsory")
        now[0] = 99
        self.assertIsNotNone(c.lookup_exact(key, "E1"))
        now[0] = 100
        self.assertIsNone(c.lookup_exact(key, "E1"))
        self.assertEqual(c.stats["invalidated_expired"], 1)
        self.assertEqual(c.snapshot()["entries"], 0)

    def test_lru_eviction_is_bounded(self):
        c = cache("exact", max_entries=3)
        for i in range(10):
            put(c, q=f"question number {i}")
        self.assertEqual(c.snapshot()["entries"], 3)
        self.assertEqual(c.stats["evicted"], 7)
        self.assertIsNotNone(c.lookup_exact(ac.normalize_query("question number 9"), "E1"))
        self.assertIsNone(c.lookup_exact(ac.normalize_query("question number 0"), "E1"))


class SemanticLayerTests(unittest.TestCase):
    Q = "is a helmet compulsory"

    def look(self, c, angle, q=None, fresh=("c1", "c2"), epoch="E1"):
        q = q or self.Q
        return c.lookup_semantic(vec(angle), ac.signature(q), epoch, fresh)

    def test_threshold_boundary_is_inclusive(self):
        t = 0.95
        c = cache("semantic", similarity=t)
        put(c, angle=0.0)
        inside = float(np.arccos(t)) - 1e-4
        outside = float(np.arccos(t)) + 1e-4
        self.assertIsNotNone(self.look(c, inside))
        self.assertIsNone(self.look(c, outside))
        self.assertAlmostEqual(self.look(c, 0.0)[1], 1.0, places=6)
        # a similarity of exactly the threshold (0.8 = the 3-4-5 triangle) is a hit; just under it is not
        c8 = cache("semantic", similarity=0.8)
        c8.put("k", ac.signature(self.Q), [1.0, 0.0, 0.0], "E1", "{}", ("c1",), ("c1",), ())
        self.assertIsNotNone(c8.lookup_semantic([0.8, 0.6, 0.0], ac.signature(self.Q), "E1", ("c1",)))
        self.assertIsNone(c8.lookup_semantic([0.79, 0.613, 0.0], ac.signature(self.Q), "E1", ("c1",)))

    def test_equal_signature_is_required_even_at_similarity_one(self):
        c = cache("semantic")
        put(c, q="is a helmet compulsory on a two-wheeler")
        self.assertIsNone(self.look(c, 0.0, q="is a helmet compulsory on a four-wheeler"))
        self.assertIsNotNone(self.look(c, 0.0, q="Is a helmet compulsory on a two wheeler?"))

    def test_cited_chunks_must_be_in_the_fresh_context(self):
        c = cache("semantic")
        put(c, cited=("c1",), context=("c1", "c2"))
        self.assertIsNone(self.look(c, 0.0, fresh=("c2", "c3")))
        self.assertIsNotNone(self.look(c, 0.0, fresh=("c3", "c1")))

    def test_best_candidate_wins(self):
        c = cache("semantic", similarity=0.9)
        put(c, q="is a helmet compulsory", angle=0.30)
        put(c, q="is a helmet compulsory ", angle=0.10)   # same normalised key: replaces
        c2 = cache("semantic", similarity=0.9)
        c2.put("k1", ac.signature(self.Q), vec(0.30), "E1", "{}", ("c1",), ("c1",), ())
        c2.put("k2", ac.signature(self.Q), vec(0.10), "E1", "{}", ("c1",), ("c1",), ())
        entry, sim = self.look(c2, 0.0)
        self.assertEqual(entry.key, "k2")

    def test_bad_vectors_are_misses(self):
        c = cache("semantic")
        put(c)
        for bad in ([], [float("nan"), 0, 0], [0.0, 0.0, 0.0]):
            self.assertIsNone(c.lookup_semantic(bad, ac.signature(self.Q), "E1", ("c1",)))


class InvalidationTests(unittest.TestCase):
    def test_other_epoch_is_a_miss_and_the_entry_is_dropped(self):
        c = cache("exact")
        put(c, epoch="E1")
        self.assertIsNone(c.lookup_exact(ac.normalize_query("is a helmet compulsory"), "E2"))
        self.assertEqual(c.stats["invalidated_epoch"], 1)

    def test_epoch_change_sweeps_old_entries(self):
        c = cache("exact")
        c.note_epoch("E1")
        for i in range(5):
            put(c, q=f"q {i}", epoch="E1")
        c.note_epoch("E2")
        self.assertEqual(c.snapshot()["entries"], 0)
        self.assertEqual(c.stats["epoch_changes"], 1)

    def test_a_late_store_from_an_old_epoch_is_refused(self):
        c = cache("exact")
        c.note_epoch("E1")
        c.note_epoch("E2")
        self.assertFalse(put(c, epoch="E1"))

    def test_invalidate_one_source_keeps_the_others(self):
        c = cache("exact")
        put(c, q="about rule six", sources=(("a" * 64, "doc-a"),))
        put(c, q="about rule fifty two", sources=(("b" * 64, "doc-b"),))
        put(c, q="about both", sources=(("a" * 64, "doc-a"), ("b" * 64, "doc-b")))
        self.assertEqual(c.invalidate_source("doc-a"), 2)      # by manifest id
        self.assertEqual(c.snapshot()["entries"], 1)
        self.assertEqual(c.invalidate_source("b" * 64), 1)     # by file hash
        self.assertEqual(c.snapshot()["entries"], 0)
        self.assertEqual(c.invalidate_source("nothing"), 0)

    def test_digest_changes_with_every_input(self):
        base = ac.digest("fp", ["sha1"], "nomic", 1000, 6)
        for changed in (("fp2", ["sha1"], "nomic", 1000, 6), ("fp", ["sha1", "sha2"], "nomic", 1000, 6),
                        ("fp", ["sha1"], "other-model", 1000, 6), ("fp", ["sha1"], "nomic", 500, 6)):
            self.assertNotEqual(base, ac.digest(*changed))
        self.assertEqual(base, ac.digest("fp", ["sha1"], "nomic", 1000, 6))


class FailingStore(ac.MemoryStore):
    def __init__(self, fail):
        super().__init__()
        self.fail = set(fail)

    def _maybe(self, op):
        if op in self.fail:
            raise OSError(f"{op} failed")

    def get(self, key):
        self._maybe("get")
        return super().get(key)

    def put(self, key, entry):
        self._maybe("put")
        super().put(key, entry)

    def values(self):
        self._maybe("values")
        return super().values()


class StorageFailureTests(unittest.TestCase):
    def test_failing_reads_are_misses_not_errors(self):
        c = cache("semantic", store=FailingStore({"get", "values"}))
        self.assertIsNone(c.lookup_exact("k", "E1"))
        self.assertIsNone(c.lookup_semantic(vec(0), frozenset(), "E1", ("c1",)))
        self.assertGreaterEqual(c.stats["storage_errors"], 2)

    def test_failing_write_is_reported_and_harmless(self):
        c = cache("exact", store=FailingStore({"put"}))
        self.assertFalse(put(c))
        self.assertEqual((c.stats["store_failed"], c.stats["stored"]), (1, 0))


class ConcurrencyTests(unittest.TestCase):
    def test_parallel_puts_and_lookups_keep_the_cache_consistent(self):
        c = cache("semantic", max_entries=20)
        errors = []

        def worker(n):
            try:
                for i in range(200):
                    q = f"question {n % 5} {i % 30}"
                    put(c, q=q, angle=(i % 7) * 0.01)
                    c.lookup_exact(ac.normalize_query(q), "E1")
                    c.lookup_semantic(vec(0.0), ac.signature(q), "E1", ("c1",))
                    if i % 50 == 0:
                        c.invalidate_source("m1")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(errors, [])
        self.assertLessEqual(c.snapshot()["entries"], 20)

    def test_embedding_memo_is_consistent_under_threads(self):
        calls = []
        memo = ac.EmbeddingMemo(lambda t: (calls.append(t), [float(len(t)), 1.0])[1], size=4)
        out = []
        threads = [threading.Thread(target=lambda: out.append(memo("abc"))) for _ in range(20)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertTrue(all(o == [3.0, 1.0] for o in out))
        self.assertEqual(memo.hits + memo.misses, 20)
        memo("a"), memo("bb"), memo("ccc"), memo("dddd"), memo("eeeee")
        self.assertLessEqual(len(memo._memo), 4)
        v = memo("abc")
        v.append(9)   # a caller cannot corrupt the memo
        self.assertEqual(memo("abc"), [3.0, 1.0])


class SameSituationTests(unittest.TestCase):
    """Wording that must NOT share an answer: the signatures differ (or a risk flag removes the semantic layer)."""
    DIFFERENT = [
        ("vehicle class", "Do I need a helmet on a two-wheeler?", "Do I need a helmet on a four-wheeler?"),
        ("vehicle class, spelled out", "helmet on a 2 wheeler", "helmet on a 4 wheeler"),
        ("vehicle type", "Is a helmet compulsory on a motorcycle?", "Is a helmet compulsory on a bus?"),
        ("applicant age", "Can a person aged 16 get a licence?", "Can a person aged 18 get a licence?"),
        ("age in words", "Can a person aged sixteen get a licence?", "Can a person aged eighteen get a licence?"),
        ("provision", "What does Rule 6 say?", "What does Rule 52 say?"),
        ("provision suffix", "What does Rule 13 say?", "What does Rule 13B say?"),
        ("location", "Is a helmet required in Hyderabad?", "Is a helmet required in Warangal?"),
        ("location, unlisted name", "Is a helmet required in Bhongir?", "Is a helmet required in Armoor?"),
        ("negation", "Is a helmet required for pillion riders?", "Is a helmet not required for pillion riders?"),
        ("negation, contraction", "Is a helmet required?", "Isn't a helmet required?"),
        ("applicant category", "Can a minor get a licence?", "Can a senior citizen get a licence?"),
        ("applicant circumstance", "Can a learner drive alone?", "Can an owner drive alone?"),
        ("date", "What was the rule before 2019?", "What was the rule after 2019?"),
        ("year", "Registration rule in 2020?", "Registration rule in 2022?"),
        ("procedure", "How do I renew a licence?", "How do I apply for a licence?"),
        ("document", "Who can apply for a licence?", "Who can apply for a permit?"),
        ("fee", "What is the fee for a learner's licence?", "What is the fee for a driving licence?"),
        ("modality", "A rider must wear a helmet", "A rider may wear a helmet"),
    ]
    SAME = [
        ("case and punctuation", "Is a helmet compulsory?", "is a helmet compulsory"),
        ("hyphenation", "helmet for two-wheeler riders", "helmet for two wheeler riders"),
        ("digit and word for the wheel count", "helmet for 2 wheelers", "helmet for two-wheeler"),
        ("licence spelling", "What is a driving license?", "What is a driving licence?"),
        ("apostrophe style", "learner’s licence", "learner's licence"),
    ]

    def test_materially_different_questions_never_share_a_signature(self):
        for label, a, b in self.DIFFERENT:
            with self.subTest(label=label):
                same = ac.signature(a) == ac.signature(b)
                flagged = bool(ac.risk_flags(a) or ac.risk_flags(b))
                self.assertTrue(not same or flagged, (label, sorted(ac.signature(a)), sorted(ac.signature(b))))

    def test_cosmetic_variants_share_a_signature(self):
        for label, a, b in self.SAME:
            with self.subTest(label=label):
                self.assertEqual(ac.signature(a), ac.signature(b), (sorted(ac.signature(a)), sorted(ac.signature(b))))

    def test_a_capitalised_word_inside_a_sentence_counts_as_a_name(self):
        # deliberate: an unlisted place or person is recognised only by its capital letter, so this errs towards a miss
        self.assertNotEqual(ac.signature("is a Helmet compulsory"), ac.signature("is a helmet compulsory"))

    def test_fee_and_date_questions_use_the_exact_layer_only(self):
        for q in ("What is the life tax for a two-wheeler?", "What is the fee for a licence?", "Rs 500 for a licence?",
                  "What is the current rule?", "What is the latest amendment?", "What was the rule in 2019?",
                  "The rule in January", "Amount payable for 50000"):
            with self.subTest(q=q):
                self.assertTrue(ac.risk_flags(q), q)
        for q in ("Is a helmet compulsory?", "What happens when a licence application is received?"):
            self.assertFalse(ac.risk_flags(q), q)

    def test_personal_identifiers_are_never_cacheable(self):
        for q in ("My number is 9876543210, can I drive?", "email me at a@b.com about licences",
                  "Vehicle TS09AB1234 helmet rule?", "TS 09 EA 1234 transfer ownership", "x" * 500, "   "):
            with self.subTest(q=q[:30]):
                self.assertIsNotNone(ac.uncacheable_reason(q))
        self.assertIsNone(ac.uncacheable_reason("Is a helmet compulsory for riders aged 18?"))


if __name__ == "__main__":
    unittest.main()
