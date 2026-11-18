"""Real integration test for the life-tax question (Stage 2): the real backend, a real Chroma index, real Ollama.

Run like tests/test_view_source_real.py (same KYR_REAL_INDEX_DIR, KYR_REQUIRE_REAL_BACKEND and RAG_VECTOR_SEARCH);
the index is copied first. tests/real_backend_probe.py (section "tax") says what is not real: the legal gate is
opened in that process only and no model is called. Three deterministic generators stand in for the model.

What a correct system does today: the two-wheeler life-tax rates are only in the G.O.Ms.No. 53 Third Schedule,
which the reviewed chunk flags withhold from answers. So no rate may ever reach a generator, a source row or an
answer; an honest model refuses; a model that invents rates is rejected by the validator.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_view_source_real import REQUIRED, ROOT, INDEX_DIR, missing
from test_life_tax import GO_53_PARAGRAPH_1, RULE_13_TEXT, THIRD_SCHEDULE_OPENING

GO_53 = "go-ms-53-2025-trb"
TAXATION_RULES = "tmvtr-1963"
SCHEDULE_RATES = ("9%", "12%", "15%", "18%")


def body(text):
    return text.partition("\n")[2]


def squash(text):
    return re.sub(r"\s+", " ", text).strip()


class RealLifeTaxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reason = missing()
        if reason and REQUIRED:
            raise AssertionError(f"real backend test required but cannot run: {reason}")
        if reason:
            raise unittest.SkipTest(reason)
        cls.tmp = tempfile.mkdtemp(prefix="kyr-real-tax-")
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        copy = Path(cls.tmp) / "index"
        shutil.copytree(INDEX_DIR, copy)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("TG_", "GROQ_", "GEMINI_", "PROVIDER_"))}
        env["TG_DB_DIR"] = str(copy)
        run = subprocess.run([sys.executable, str(ROOT / "tests" / "real_backend_probe.py"), "tax"], cwd=ROOT,
                             env=env, capture_output=True, text=True, timeout=600)
        if run.returncode != 0:
            raise AssertionError("probe failed:\n" + run.stderr[-3000:])
        cls.out = json.loads(run.stdout.strip().splitlines()[-1])
        stored = cls.out["stored"]
        cls.eligible = {(m, p, t) for m, p, ok, t in stored if ok is not False}
        withheld = [(m, p, t) for m, p, ok, t in stored if ok is False]
        eligible_ids = {(m, p) for m, p, _ in cls.eligible}
        cls.withheld_ids = {(m, p) for m, p, _ in withheld} - eligible_ids
        cls.withheld_texts = [squash(t) for _, _, t in withheld if len(squash(t)) >= 40]
        cls.quoting = cls.out["quoting"]
        cls.all_runs = ([r for rs in cls.quoting.values() for r in rs] + cls.out["refusing"] + cls.out["fabricated"]
                        + cls.out["development_penalty"])

    def chunks(self, manifest_id, provision_id):
        return [t for m, p, _, t in self.out["stored"] if (m, p) == (manifest_id, provision_id)]

    def passages(self, run):
        return [p for s in run["body"]["sources"] for p in s["passages"]]

    def assert_no_withheld_text(self, text, where):
        flat = squash(text)
        for w in self.withheld_texts:
            self.assertNotIn(w, flat, f"withheld schedule text appears in {where}")

    def test_index_mode_and_withheld_schedule_present(self):
        self.assertEqual(self.out["status"]["index"], "ready")
        self.assertEqual(self.out["vector_search"], os.environ.get("RAG_VECTOR_SEARCH", "exact"))
        self.assertIn((GO_53, "THIRD SCHEDULE"), self.withheld_ids)
        self.assertTrue(self.withheld_texts)

    def test_withheld_schedule_is_a_vector_hit_but_never_retrieved(self):
        original = self.quoting["life_tax"][0]
        self.assertTrue(any(ok is False and m == GO_53 for m, _, ok, _ in original["vector"]),
                        "the filter is untested: no withheld G.O. 53 chunk among the raw vector hits")
        for run in self.all_runs:
            for m, p, ok, _ in run["retrieved"]:
                self.assertIsNot(ok, False, f"{run['question']}: retrieved withheld {m}::{p}")

    def test_withheld_schedule_never_reaches_generator_sources_or_answer(self):
        for run in self.all_runs:
            q = run["question"]
            for shown in run["evidence_seen"]:
                for chunk_id, passage in shown:
                    self.assertNotIn(tuple(chunk_id.split("::")[:2]), self.withheld_ids, f"{q}: shown {chunk_id}")
                    self.assert_no_withheld_text(passage, f"evidence for {q!r}")
            for p in self.passages(run):
                self.assertNotIn((p["manifest_id"], p["provision_id"]), self.withheld_ids, f"{q}: listed {p['label']}")
                self.assert_no_withheld_text(p["text"], f"a source passage for {q!r}")
            self.assert_no_withheld_text(run["body"]["response"], f"the answer to {q!r}")
            for rate in SCHEDULE_RATES:
                self.assertNotIn(rate, run["body"]["response"], f"{q}: answer states a schedule rate")

    def test_life_tax_phrasings_answer_only_from_stored_eligible_chunks(self):
        for run in self.quoting["life_tax"]:
            q = run["question"]
            self.assertEqual((run["status"], run["body"]["kind"]), (200, "answer"), q)
            self.assertTrue(any(m == TAXATION_RULES for m, _, _, _ in run["retrieved"]), q)
            passages = self.passages(run)
            self.assertTrue(passages and all(p["cited"] for p in passages), q)
            for p in passages:
                self.assertIn((p["manifest_id"], p["provision_id"], p["text"]), self.eligible, f"{q}: {p['label']}")

    def test_related_tax_questions_retrieve_the_taxation_rules(self):
        for run in self.quoting["related"]:
            q = run["question"]
            self.assertEqual(run["status"], 200, q)
            self.assertIn(run["body"]["kind"], ("answer", "no_support"), q)
            self.assertTrue(any(m == TAXATION_RULES for m, _, _, _ in run["retrieved"]), q)
            for p in self.passages(run):
                self.assertIn((p["manifest_id"], p["provision_id"], p["text"]), self.eligible, f"{q}: {p['label']}")

    def test_unsupported_questions_have_no_evidence_in_the_index(self):
        eligible = [t for _, _, t in self.eligible]
        self.assertFalse([t for t in eligible if re.search(r"green\s+tax", t, re.I)])
        self.assertFalse([t for t in eligible if re.search(r"electric", t, re.I) and re.search(r"\btax", t, re.I)])

    def test_refusing_generator_ends_in_not_found(self):
        penalty = {r["question"] for r in self.quoting["penalty"]}
        for run in self.out["refusing"]:
            if run["question"] in penalty:
                continue
            self.assertEqual((run["status"], run["body"]["kind"], run["body"]["sources"]), (200, "no_support", []),
                             run["question"])
            self.assertTrue(run["evidence_seen"], run["question"])

    def test_fabricated_rates_are_rejected(self):
        for run in self.out["fabricated"]:
            q = run["question"]
            self.assertTrue(run["evidence_seen"] and run["evidence_seen"][0], f"{q}: the generator was not called")
            self.assertEqual((run["status"], run["body"]["kind"], run["body"]["sources"]), (200, "no_support", []), q)
            self.assertNotIn("two-wheeler costing", run["body"]["response"], q)

    def test_penalty_question_stays_locked(self):
        runs = (self.quoting["penalty"] + [r for r in self.out["refusing"] if r["question"] in
                                           {x["question"] for x in self.quoting["penalty"]}]
                + self.out["development_penalty"])
        self.assertEqual(len(runs), 3)
        for run in runs:
            self.assertEqual((run["status"], run["body"]["kind"], run["body"]["sources"]), (200, "restricted", []))
            self.assertEqual(run["evidence_seen"], [], "a locked question must not reach the generator")

    def test_offline_fixture_texts_are_the_stored_chunks(self):
        third = self.chunks(GO_53, "THIRD SCHEDULE")
        self.assertEqual(len(third), 1)
        self.assertTrue(third[0].startswith(body(THIRD_SCHEDULE_OPENING)))
        self.assertEqual(self.chunks(GO_53, "Paragraph 1"), [body(GO_53_PARAGRAPH_1)])
        self.assertIn((GO_53, "THIRD SCHEDULE"), self.withheld_ids)
        self.assertNotIn((GO_53, "Paragraph 1"), self.withheld_ids)
        rule_13 = self.chunks(TAXATION_RULES, "Rule 13")
        if rule_13:  # newer index: Rule 13 is its own chunk
            self.assertEqual(rule_13, [body(RULE_13_TEXT)])
        else:  # older index: Rule 13 is stored inside another Taxation Rules chunk
            self.assertTrue(any(squash(body(RULE_13_TEXT)) in squash(t)
                                for m, _, _, t in self.out["stored"] if m == TAXATION_RULES))


if __name__ == "__main__":
    unittest.main()
