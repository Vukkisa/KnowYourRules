# Retrieval review: batch 1 (10 rows)

Technical verification only. **None of this is legal approval.** The review CSV, corpus, index, manifest and
approval data are unchanged. No label correction has been applied; proposed corrections need a human reviewer.

Per-row evidence: [`batch-01-results.csv`](batch-01-results.csv).

## What a row is
Each of the 108 rows in `eval/telangana-retrieval-review.csv` is a benchmark question with a machine-written label
(expected provisions and outcome), not a provision. Three things are measured separately:

| Measurement | Question | Column |
|---|---|---|
| Source text | Does the indexed chunk match the official file it cites? | `text_comparison` |
| Benchmark label | Does the label name the provisions that govern the question? | `label_assessment` |
| Retrieval | Does the top 5 contain what a correct answer needs? | `retrieval_assessment` |

`review_status` adds currency and applicability, which this review cannot settle (see Limits).

## Results

| Row | Text | Label | Retrieval | Status |
|---|---|---|---|---|
| TG-GO-001 | match | correct | pass | NEEDS_LEGAL_REVIEW |
| TG-GO-003 | match (Para 4 after removing `\|`) | over-broad | adequate | NEEDS_LEGAL_REVIEW |
| TG-GO-006 | match | correct | pass | NEEDS_SOURCE (Act 8/2026 text) |
| TG-GO-007 | match (Para 3 after removing `\|`) | over-broad | adequate; stale Rule 81 ranked 1st | OUTDATED corpus Rule 81 + NEEDS_LEGAL_REVIEW |
| TG-EX-002 | n/a (excluded) | correct | n/a (guard) | NEEDS_SOURCE (final G.O. 24?) |
| TG-MR-008 | match | correct | **fail** (Rule 77 missing) | NEEDS_LEGAL_REVIEW |
| TG-PQ-002 | match | **incorrect** (14 in, 15 out) | **fail** (Rules 16-18 missing) | WRONG_IDENTIFIER + NEEDS_LEGAL_REVIEW |
| TG-DL-001 | match | correct | pass | NEEDS_LEGAL_REVIEW |
| TG-AM-001 | match | correct | n/a (clarify) | VERIFIED (technical only) |
| TG-MP-001 | Rule 186 text indexed under Rule 185 | **incorrect** (186 exists) | found, wrong ID | WRONG_IDENTIFIER + NEEDS_LEGAL_REVIEW |

Counts: 10 inspected; 1 technically verified; 2 incorrect labels and 2 over-broad; 2 need a source; 8 need legal review.

## Findings

**Actual retrieval failures**
- TG-MR-008: Rule 77 (medical certificates for conductors) is not in the top 5.
- TG-PQ-002: of Rules 15-18, only Rule 15 is retrieved. Rules 16 (issue), 17 (photographs) and 18 (fee) are missing.
- TG-GO-007 (minor): Para 2 of G.O. 77 (no objections, final notification) is not in the top 5. The Order, which is enough to answer, is at rank 2.

**Benchmark-label problems**
- TG-PQ-002: Rule 14 is about a new photograph after a Rule 13 demand. Rule 15 (report the loss on Form LLD) is the missing first step. Proposed: Rules 15, 16, 17, 18.
- TG-MP-001: Rule 186 is not missing. Official source line 752 reads `186 (1) Conditions of permit in respect of a luxury tourist cab`. The label `missing_provision` is wrong.
- TG-GO-003 and TG-GO-007 are over-broad. Their PARTIAL results come from the label, not from retrieval.

**Corpus and ingestion problems** (affect citations and answers, not just the benchmark)
- **Rule 186 mis-segmented.** The source writes `186` with no full stop. `backend/tg_ingest.py` `PROVISION_PATTERNS[0]` requires `NNN.`, so the Rule 186 text was folded into `Rule 185` parts 5-6.
  - An answer would cite Rule 185 for Rule 186 text.
  - The missing-provision guard refuses a rule that exists.
  - TG-MP-002 to 005 and TG-PN-005 probably share this cause (not reviewed).
- **Stale Rule 81.** The TMVR snapshot still has sub-rules (1), (2) and (4), with fees up to Rs.50,000. G.O. 77 (15-11-2025) omits those sub-rules and sets fees up to Rs.1,50,000. The snapshot ranks first for Rule 81 questions.
- **Pipe artifacts.** The ingester inserts ` | ` between words in some G.O. table-like lines (G.O. 32 Para 4, G.O. 77 Para 3 part 1). The words match otherwise.
- **Mislabelled G.O. 77 paragraph.** `Paragraph 4` is amendment item 4 of the notification, not a G.O. paragraph, and it also carries the distribution list.
- **Central dependencies outside the corpus:** CMVR r.167/167A (GO-001, GO-003) and MV Act s.129 (DL-001). Answers can be incomplete.

**No authoritative source held**
- TG-GO-006: the text of Act No. 8 of 2026.
- TG-EX-002: whether G.O. 24/2026 (a draft by its own ORDER) was finalised.

## Limits
- Sources are the files in `docs/legal-sources/telangana-traffic/source-documents/`: GOIR G.O. PDFs and Transport Department HTML snapshots retrieved 29-10-2026. These live in the main checkout and are not tracked in git. All 57 match `SHA256SUMS`.
- The snapshots are consolidated web text with no amendment dates, so a match proves fidelity to the snapshot, not currency.
- No later G.O. or gazette search was done. Central instruments are out of scope.

## Reproduce
No network, API key or model call. The index is opened read-only. Needs `pdftotext` (poppler).

```bash
SRC=../KnowYourRules-repo/docs/legal-sources/telangana-traffic/source-documents   # wherever the source files are
IDX=chroma_telangana_preview/chroma.sqlite3
python3 -m backend.source_compare --sources "$SRC" checksums
python3 -m backend.source_compare --sources "$SRC" --index "$IDX" compare "tmvr-1989-chap-5::Rule 185" "go-ms-77-2025-trb::Paragraph 3"
python3 -m backend.source_compare --sources "$SRC" --index "$IDX" find tmvr-1989-chap-5 "Rule 18[0-9]"
python3 -m backend.source_compare --sources "$SRC" context html-snapshots/tmvr-1989/middle-main-chap-5.htm "186 \(1\)" --width 300
```

`compare` reports four levels: `verbatim` (after normalising whitespace and quotes), `ignoring_whitespace`,
`ignoring_whitespace_and_pipes`, and `matched_prefix`/`divergence`. Tests: `tests/test_source_compare.py`.

## Next step
1. Human review of the proposed label changes (TG-PQ-002, TG-GO-003, TG-GO-007, TG-MP-001) through `review_import`.
2. Engineering decision on the Rule 186 heading pattern and the stale Rule 81 snapshot. Both need a re-ingest, which is out of scope here.
3. Then batch 2, starting with TG-MP-002 to 005 and TG-PN-005.
