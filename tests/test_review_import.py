"""Tests for backend/review_import.py. The benchmark, template CSV and chunk references are the real (read-only)
repository files; every "completed" submission is a synthetic copy written to a temporary directory.
Reviewer names here are test fixtures, not real reviewers."""

import csv
import datetime as dt
import io
import json
import tempfile
import unittest
from pathlib import Path

from backend import review_import as ri

TODAY = dt.date(2026, 11, 20)
TEMPLATE_FIELDS, TEMPLATE_ROWS = ri._read_csv(ri.TEMPLATE)
GOOD = {"human_decision": "correct", "human_retrieved_passages_sufficient": "yes",
        "human_jurisdiction_correct": "yes", "human_instrument_correct": "yes",
        "human_source_current_and_applicable": "unknown", "human_supersession_checked": "yes",
        "human_should_be_refused": "no", "reviewed_on": "09-11-2026", "reviewer_name": "Test Reviewer A",
        "reviewer_designation": "Test fixture"}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.n = 0

    def rows(self):
        return [dict(r) for r in TEMPLATE_ROWS]

    def write(self, rows, fields=None, bom=False):
        self.n += 1
        path = Path(self.tmp.name) / f"sub{self.n}.csv"
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=fields or TEMPLATE_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
        path.write_bytes(("﻿" if bom else "").encode() + buf.getvalue().encode("utf-8"))
        return path

    def review(self, rows, qid, **fields):
        row = next(r for r in rows if r["id"] == qid)
        row.update({**GOOD, **fields})
        return rows

    def validate(self, path):
        return ri.validate(path, today=TODAY)

    def assert_error(self, sub, fragment):
        self.assertFalse(sub.ok)
        self.assertTrue(any(fragment in e for e in sub.errors), sub.errors[:5])


class ReferenceTests(unittest.TestCase):
    def test_references_are_unique_and_cover_the_index(self):
        refs = ri.load_references()
        self.assertEqual(len(refs["chunks"]), 586)
        self.assertEqual(sum(c["answer_eligible"] for c in refs["chunks"]), 572)
        self.assertEqual(len({c["ref"] for c in refs["chunks"]}), 586)

    def test_duplicate_go53_chunk_id_gets_two_distinct_refs(self):
        refs = ri.load_references()
        dup = refs["duplicate_chunk_ids"]["go-ms-53-2025-trb::SCHEDULE::part1of1"]
        self.assertEqual(len(dup), 2)
        self.assertNotEqual(dup[0], dup[1])
        self.assertEqual(list(refs["duplicate_chunk_ids"]), ["go-ms-53-2025-trb::SCHEDULE::part1of1"])
        same = [c for c in refs["chunks"] if c["chunk_id"] == "go-ms-53-2025-trb::SCHEDULE::part1of1"]
        self.assertEqual(len({c["document_sha256"] for c in same}), 1)   # same document hash ...
        self.assertEqual(len({c["text_sha256"] for c in same}), 2)       # ... different text and location
        self.assertEqual(len({c["location"] for c in same}), 2)

    def test_every_benchmark_chunk_resolves_to_exactly_one_ref(self):
        refs = ri.load_references()
        for case in json.loads(ri.BENCHMARK.read_text())["cases"]:
            for e in case["expected_chunks"] + case["excluded_chunks"]:
                self.assertEqual(len(ri.resolve_benchmark_chunk(e, refs)), 1, (case["id"], e["chunk_id"]))

    def test_ref_is_deterministic(self):
        meta = {"manifest_id": "d", "provision_id": "Rule 1", "part": 1, "parts": 1, "location": "f#page=2"}
        self.assertEqual(ri.review_ref(meta, ri.text_sha("x")), ri.review_ref(dict(meta), ri.text_sha("x")))
        self.assertNotEqual(ri.review_ref(meta, ri.text_sha("x")), ri.review_ref(meta, ri.text_sha("y")))


class ValidationTests(Base):
    def test_blank_template_is_valid_and_unreviewed(self):
        sub = self.validate(ri.TEMPLATE)
        self.assertTrue(sub.ok, sub.errors[:3])
        self.assertEqual((len(sub.rows), len(sub.unreviewed)), (0, 108))

    def test_template_agrees_with_benchmark(self):
        self.assertEqual(ri.check_template(TEMPLATE_ROWS, json.loads(ri.BENCHMARK.read_text())["cases"]), [])

    def test_valid_review_with_bom_and_crlf(self):
        rows = self.review(self.rows(), "TG-DL-001")
        for r in rows:
            r["machine_retrieved_top5"] = r["machine_retrieved_top5"].replace("\n", "\r\n")  # spreadsheet line ends
        sub = self.validate(self.write(rows, bom=True))
        self.assertTrue(sub.ok, sub.errors[:3])
        self.assertEqual(list(sub.rows), ["TG-DL-001"])

    def test_missing_row(self):
        self.assert_error(self.validate(self.write(self.rows()[1:])), "missing question id")

    def test_duplicate_row(self):
        rows = self.rows()
        self.assert_error(self.validate(self.write(rows + [rows[0]])), "duplicate question id")

    def test_unknown_id(self):
        rows = self.rows()
        rows.append({**rows[0], "id": "TG-XX-999"})
        self.assert_error(self.validate(self.write(rows)), "unknown question id")

    def test_modified_machine_data_is_rejected(self):
        for col, value in (("machine_retrieval_result", "PASS"), ("machine_expected_provisions", "x :: Rule 1"),
                           ("machine_supporting_passage", "edited"), ("question", "edited?"),
                           ("reviewer_status", "human_confirmed"), ("machine_recall_at_5", "1.0"),
                           ("audit_notes", "")):
            rows = self.rows()
            target = next(r for r in rows if r[col] != value)
            target[col] = value
            self.assert_error(self.validate(self.write(rows)), f"machine column {col} was modified")

    def test_added_or_removed_columns_rejected(self):
        rows = self.rows()
        self.assert_error(self.validate(self.write(rows, fields=TEMPLATE_FIELDS[:-1])), "columns differ")
        for r in rows:
            r["extra"] = ""
        self.assert_error(self.validate(self.write(rows, fields=TEMPLATE_FIELDS + ["extra"])), "columns differ")

    def test_missing_reviewer_identity(self):
        for f in ("reviewer_name", "reviewer_designation", "reviewed_on"):
            rows = self.review(self.rows(), "TG-DL-001", **{f: ""})
            self.assert_error(self.validate(self.write(rows)), f"{f} is empty")

    def test_invalid_dates(self):
        for value, msg in (("2026-11-15", "not a valid"), ("31-02-2026", "not a valid"), ("15/11/2026", "not a valid"),
                           ("01-01-2027", "in the future"), ("01-01-2025", "before the benchmark")):
            rows = self.review(self.rows(), "TG-DL-001", reviewed_on=value)
            self.assert_error(self.validate(self.write(rows)), msg)

    def test_invalid_decisions_and_enum_values(self):
        for f, value in (("human_decision", "approved"), ("human_decision", "Correct"),
                         ("human_jurisdiction_correct", "maybe"), ("human_supersession_checked", "n/a")):
            rows = self.review(self.rows(), "TG-DL-001", **{f: value})
            self.assert_error(self.validate(self.write(rows)), "is not one of")

    def test_required_human_fields_and_justifications(self):
        rows = self.review(self.rows(), "TG-DL-001", human_instrument_correct="")
        self.assert_error(self.validate(self.write(rows)), "human_instrument_correct is empty")
        rows = self.review(self.rows(), "TG-DL-001", human_decision="incorrect")
        self.assert_error(self.validate(self.write(rows)), "needs human_comments")
        rows = self.review(self.rows(), "TG-MP-001", human_decision="missing_source", human_comments="absent",
                           human_retrieved_passages_sufficient="n/a")
        self.assert_error(self.validate(self.write(rows)), "needs human_missing_evidence")
        rows = self.review(self.rows(), "TG-DL-001", human_retrieved_passages_sufficient="n/a")
        self.assert_error(self.validate(self.write(rows)), "only for non-retrieval outcomes")

    def test_partially_filled_row_is_not_treated_as_unreviewed(self):
        rows = self.rows()
        rows[0]["human_comments"] = "started but not finished"
        self.assert_error(self.validate(self.write(rows)), "human_decision is empty")

    def test_excluded_passage_cannot_be_named_as_expected(self):
        for item, msg in (("go-ms-24-2026-trb :: Order", "all excluded"),
                          ("go-ms-53-2025-trb :: SCHEDULE", "all excluded"),
                          ("tmvr-1989-chap-8 :: Rule 9999", "not in the index"),
                          ("Rule 437", "is not 'document :: provision'")):
            rows = self.review(self.rows(), "TG-DL-001", human_decision="incorrect", human_comments="c",
                               human_correct_expected_provisions=item)
            self.assert_error(self.validate(self.write(rows)), msg)
        rows = self.review(self.rows(), "TG-DL-001", human_decision="partially_correct", human_comments="c",
                           human_correct_expected_provisions="tmvr-1989-chap-8 :: Rule 437; tmvtr-1963 :: Rule 13A")
        self.assertTrue(self.validate(self.write(rows)).ok)


class ReconcileTests(Base):
    def reconcile(self, *subs, **kw):
        return ri.reconcile([self.validate(s) for s in subs], generated_on="20-11-2026", **kw)

    def case(self, out, qid):
        return next(c for c in out["cases"] if c["id"] == qid)

    def test_machine_benchmark_preserved_and_states_counted(self):
        before = ri.BENCHMARK.read_bytes()
        text = "Line one,\nwith \"quotes\" and ₹ and trailing space "
        rows = self.review(self.rows(), "TG-DL-001", human_comments=text, human_missing_evidence="G.O. text\nmissing")
        out = self.reconcile(self.write(rows))
        self.assertEqual(ri.BENCHMARK.read_bytes(), before)
        bench = {c["id"]: c for c in json.loads(before)["cases"]}
        for c in out["cases"]:
            self.assertEqual(c["machine"], bench[c["id"]])
            self.assertEqual(c["legal_status"], "not_legally_approved")
        self.assertIn("NOT LEGAL APPROVAL", out["legal_status"])
        self.assertEqual(out["summary"], {"reviewed": 1, "partially_reviewed": 0, "disputed": 0, "unreviewed": 107})
        c = self.case(out, "TG-DL-001")
        self.assertEqual(c["reviews"][0]["human_comments"], text)  # preserved exactly, not stripped
        self.assertEqual(c["reviews"][0]["human_missing_evidence"], "G.O. text\nmissing")
        self.assertEqual((c["agreed_decision"], c["proposed_reviewer_status"]), ("correct", "human_confirmed"))
        self.assertEqual(c["reviews"][0]["submission_sha256"], out["submissions"][0]["sha256"])

    def test_corrections_are_recorded_not_applied(self):
        rows = self.review(self.rows(), "TG-DL-001", human_decision="partially_correct", human_comments="add 13A",
                           human_correct_expected_provisions="tmvtr-1963 :: Rule 13A; tmvr-1989-chap-8 :: Rule 437")
        c = self.case(self.reconcile(self.write(rows)), "TG-DL-001")
        self.assertEqual(c["machine"]["expected_provisions"], ["tmvr-1989-chap-8::Rule 437"])
        self.assertEqual(c["reviewer_proposed_expected_provisions"],
                         [["tmvr-1989-chap-8 :: Rule 437", "tmvtr-1963 :: Rule 13A"]])
        self.assertEqual(c["proposed_reviewer_status"], "pending_human_review")  # partial is not a confirmation

    def test_disagreement_between_reviewers_is_recorded(self):
        a = self.write(self.review(self.rows(), "TG-GO-003"))
        b = self.write(self.review(self.rows(), "TG-GO-003", reviewer_name="Test Reviewer B",
                                   human_decision="incorrect", human_comments="Order paragraph is not needed",
                                   human_jurisdiction_correct="yes"))
        out = self.reconcile(a, b, min_reviewers=2)
        c = self.case(out, "TG-GO-003")
        self.assertEqual(c["review_state"], "disputed")
        self.assertIsNone(c["agreed_decision"])
        self.assertEqual(c["proposed_reviewer_status"], "pending_human_review")
        self.assertEqual({d["value"] for d in c["disagreements"]["human_decision"]}, {"correct", "incorrect"})
        self.assertNotIn("human_jurisdiction_correct", c["disagreements"])
        self.assertEqual(out["summary"]["disputed"], 1)

    def test_agreement_and_minimum_reviewers(self):
        a = self.write(self.review(self.rows(), "TG-DL-002"))
        b = self.write(self.review(self.rows(), "TG-DL-002", reviewer_name="Test Reviewer B",
                                   human_source_current_and_applicable="yes"))
        self.assertEqual(self.case(self.reconcile(a, min_reviewers=2), "TG-DL-002")["review_state"],
                         "partially_reviewed")
        c = self.case(self.reconcile(a, b, min_reviewers=2), "TG-DL-002")
        self.assertEqual((c["review_state"], c["agreed_decision"]), ("reviewed", "correct"))
        self.assertIn("human_source_current_and_applicable", c["disagreements"])  # field-level, decision agrees

    def test_same_reviewer_twice_and_invalid_submissions_are_refused(self):
        a = self.write(self.review(self.rows(), "TG-DL-001"))
        with self.assertRaises(ValueError):
            self.reconcile(a, a)
        bad = self.rows()[1:]
        with self.assertRaises(ValueError):
            self.reconcile(self.write(bad))

    def test_duplicate_chunk_ids_resolved_in_output(self):
        out = self.reconcile(self.write(self.review(self.rows(), "TG-EX-004", human_decision="refuse_expected",
                                                    human_retrieved_passages_sufficient="n/a",
                                                    human_should_be_refused="yes")))
        self.assertIn("go-ms-53-2025-trb::SCHEDULE::part1of1", out["duplicate_chunk_ids"])
        refs = [r for e in self.case(out, "TG-EX-004")["chunk_refs"]["excluded_chunks"]
                if e["chunk_id"] == "go-ms-53-2025-trb::SCHEDULE::part1of1" for r in e["review_refs"]]
        self.assertEqual(len(refs), 2)
        self.assertEqual(len(set(refs)), 2)
        self.assertEqual(self.case(out, "TG-EX-004")["proposed_reviewer_status"], "pending_human_review")

    def test_cli_refuses_to_overwrite_machine_inputs_and_rejects_invalid(self):
        good = self.write(self.review(self.rows(), "TG-DL-001"))
        bad = self.write(self.rows()[1:])
        with unittest.mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(ri.main(["validate", str(bad)]), 1)
            self.assertEqual(ri.main(["reconcile", str(good), "--out", str(ri.BENCHMARK)]), 1)
            out = Path(self.tmp.name) / "candidate.json"
            self.assertEqual(ri.main(["reconcile", str(good), "--out", str(out)]), 0)
        self.assertEqual(json.loads(out.read_text())["summary"]["reviewed"], 1)


import unittest.mock  # noqa: E402

if __name__ == "__main__":
    unittest.main()
