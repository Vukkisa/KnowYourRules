# Stage 10: stale rule-absence claims corrected

Only factual statements that Stage 8 and Stage 9 showed to be false were corrected. Changed:
- 1 manifest note;
- 2 reviewer flags, replaced by 1;
- 5 benchmark `notes` fields.

Not changed: the Chroma index, source documents, benchmark labels, review statuses, approval data, historical reports, Rule 81 data, retrieval, generation and the validator.

**"Present in the source" is not "legally current".** Nothing here verifies the legal status of any provision.

The five states this report keeps apart:

| State | Rule 186 / TMVTR Rule 13 / 295-A / 12-B, today |
|---|---|
| Present in the source snapshot | **yes**: proved by line and anchor, below |
| Correctly parsed | **yes, with the Stage 9 parser** (`backend/tg_ingest.py`, uncommitted). No, with the parser at HEAD |
| Indexed under its own identity | **no**: the preview index predates Stage 9 and was not rebuilt |
| Retrieved under its own identity | **no**: it follows from the previous row |
| Legally current | **unknown**: not verified against an official print or amendment history |

## 1. Stale claims found (full search of the worktree and of the main checkout's `docs/`)
| # | File | Field or location | Original text | Status |
|---|---|---|---|---|
| 1 | `docs/legal-sources/telangana-traffic/DRAFT-telangana-manifest.json` | `documents[tmvr-1989-chap-5].notes`, last sentence | "Rule 186 is listed in the chapter contents but absent from the text." | **false**; corrected |
| 2 | `docs/legal-sources/telangana-traffic/PREVIEW-CHUNK-FLAGS.json` | `flags[2]` (match `tmvr-1989-chap-5` / `Rule 185`) `.warning` | "Missing source: rule 186 is listed in the chapter contents but absent from this snapshot's text; no text for rule 186 is indexed." | **false**; replaced |
| 3 | same file | `flags[3]` (match `Rule 187`) `.warning` | same text | **false**; replaced |
| 4 to 8 | `eval/telangana-retrieval-benchmark.json` | `cases[TG-MP-001 … TG-MP-005].notes` | "Rule 186 is listed in the chapter contents but absent from the source text." | **false**; corrected |
| 9 | `docs/legal-sources/telangana-traffic/INGESTION-VALIDATION-REPORT.md` | line 75, table | "Matches every chapter's contents list except **rule 186** (listed, absent from the text)" | false; **historical report, not edited** (erratum below) |
| 10 | same file | line 76, table | "Matches the contents list (13 appears only as 13-A/13-B)" | false for TMVTR Rule 13; **not edited** (erratum) |
| 11 | same file | line 85 | "TMVR rule 186: in the contents, missing from the text. …" | false; **not edited** (erratum) |
| 12 | same file | line 219 | "Rule 186, rules 185/186/187, … all return `missing_provision`." | **true** as a record of the guard's behaviour at that time, and still true of the current index. Not changed |

**Checked and not stale:**
- **`eval/telangana-retrieval-review.csv`:** the MP and PN rows have empty `audit_notes`. Their `missing_provision` / `restricted` outcomes are **labels**, so they are handled in section 5.
- **Tests:**
  - `tests/test_server.py` (lines 653-697, 1012, 1165), `tests/test_grounded_answer.py:313-317` and `tests/test_retrieval_eval.py:28` use "Rule 186" as a synthetic *missing* example on fixture indexes.
  - They make no claim about the snapshot, so they were not changed. Renumbering them to an absent rule such as 999 is recommended.
- **`docs/legal-sources/EVIDENCE-GAP-REGISTER.md:172`:** this is MV Act **section** 186 (central), so it is unrelated.
- **`eval/REVIEW-PRIORITY.md`:** lists the questions only.
- **The `eval/results` and `eval/real-model` files:** only numeric matches.
- **The supplied review-summary PDF:** no match.
- **Stage 7-9 reports and `batch-01-*`:** already correct.
- **Rule 295-A and 12-B:** no stale absence claim exists anywhere.
- **TMVTR Rule 13:** the only stale claim is #10. No flag or manifest note mentions it.

## 2. Evidence
- **Source integrity:** all 57 source files match `SHA256SUMS`, both before and after.
- **Rule 186:** `html-snapshots/tmvr-1989/middle-main-chap-5.htm` line 752, `<strong><a name="58"></a>186</strong> (1) <strong>Conditions of permit in respect of a luxury tourist cab :-</strong>`.
  - With the Stage 9 parser it is `tmvr-1989-chap-5::Rule 186`, 2 parts, `#58`. Both parts match the snapshot **verbatim** (Stage 9 report, section 5).
- **TMVTR Rule 13:** `html-snapshots/tmvtr-1963/middle-ap-mv-tr-1963-main.htm` line 168, `<a name="14" id="14"></a>13 Rates of penalty : -`.
  - With the Stage 9 parser it is `tmvtr-1963::Rule 13`, 1 part, `#14`, **verbatim**.
- **Cause of the false claims:** the original validation compared the parser's output with the contents lists. The headings have no full stop after the number, so the parser folded them into the previous rule (Stage 8, Part A).

## 3. What changed, and how history is kept
| File | Field | Change | Tracked in git? |
|---|---|---|---|
| `DRAFT-telangana-manifest.json` | `tmvr-1989-chap-5.notes` | last sentence replaced (below); no other field or document changed (2-line raw diff) | no (main checkout `docs/` is untracked) |
| `PREVIEW-CHUNK-FLAGS.json` | flags 2-3 | the two Rule 185/187 absence flags are replaced by **one** flag on `Rule 186`. The other 6 flags are byte-identical, and the formatting is preserved (12-line raw diff) | no |
| `eval/telangana-retrieval-benchmark.json` | `TG-MP-001…005.notes` | note text replaced (below); every other field of every case, and the top-level keys, unchanged (verified by JSON comparison) | **yes** (`git diff`: 5 lines) |

**Preserving history:**
- The original files are copied byte-for-byte to `eval/legal-validation/stage-10-originals/`:
  - `DRAFT-telangana-manifest.json`, sha256 `738c901d0523…`;
  - `PREVIEW-CHUNK-FLAGS.json`, `cdc3033a7999…`;
  - `telangana-retrieval-benchmark.json`, `cf13d4497b14…`.
- Each corrected text quotes the original wording, gives the correction date and points to Stage 9 or 10, so the provenance stays inside the record itself.
- The flag schema allows only `match`, `warning` and `answer_eligible`, so the provenance went into the warning text.

**New manifest sentence:**
> Rule 186 is present in this snapshot's text (anchor #58, source line 752: '186 (1) Conditions of permit in respect of a luxury tourist cab :-'); its heading has no full stop after the number. Corrected 11-11-2026 (Stage 10): this note previously read 'Rule 186 is listed in the chapter contents but absent from the text.', a finding caused by a parser defect fixed in Stage 9 (eval/legal-validation/STAGE-09-REPORT.md). Presence in the snapshot says nothing about legal currency.

**New flag** (`tmvr-1989-chap-5` / `Rule 186`):
- `answer_eligible: true`, the same value the withdrawn flags had, so eligibility does not change.
- Warning text:
> Identity note: the heading of rule 186 is printed without a full stop after the number ('186 (1) Conditions of permit in respect of a luxury tourist cab :-', anchor #58), so before the Stage 9 parser fix its text was indexed as part of rule 185. Earlier flags on rules 185 and 187 said rule 186 was absent from this snapshot; that was wrong and they were withdrawn on 11-11-2026 (Stage 10). The text matches the snapshot verbatim; rule numbering and legal currency are not verified against an official print.

**New benchmark note** (TG-MP-001 to 005):
> Corrected 11-11-2026 (Stage 10): Rule 186 is present in the chapter 5 source text (anchor #58, heading printed without a full stop after the number). The original note read 'Rule 186 is listed in the chapter contents but absent from the source text.', a finding caused by a parser defect fixed in Stage 9. The preview index was built before that fix and has no Rule 186 provision, so this row's machine label (missing_provision) is unchanged and awaits human review; see eval/legal-validation/STAGE-10-REPORT.md. Not legally verified.

**Erratum for `INGESTION-VALIDATION-REPORT.md`** (recorded here instead of editing the historical report):
- Lines 75 and 85: Rule 186 is present in the chapter 5 text at `#58`.
- Line 76: TMVTR has a plain Rule 13 ("Rates of penalty", `#14`) as well as 13-A and 13-B.
- All three were artefacts of the heading defect fixed in Stage 9.

## 4. Preview flags: how they are made, and before/after
**How the flags are made:**
- `PREVIEW-CHUNK-FLAGS.json` is **written by reviewers by hand**. No code generates it.
- `build_telangana_index.load_chunk_flags` validates its schema. `apply_chunk_flags` **appends** each `warning` to `extraction_warning` on every matching chunk and ANDs `answer_eligible`. A flag that matches no chunk is a build error.
- **No warning is copied from the manifest notes.** The manifest note goes into a separate field, `manifest_notes`, which `chunk_document` copies verbatim onto every chunk of that document.
- The false manifest sentence and the false flags were therefore two independent copies of the same mistaken finding.

**"Regenerated"** here means the flags were applied in memory exactly as the build does. No index was written:
- **Before:** the parser at HEAD with the original manifest and flags.
- **After:** the Stage 9 parser with the corrected manifest and flags.
- **Check:** the "before" run reproduces the preview index's `extraction_warning` and `answer_eligible` for all 586 chunks exactly.

| Warning (first words) | Chunks before | Chunks after |
|---|---|---|
| "Missing source: rule 186 is listed in the chapter contents but absent …" | **7** (Rule 185 ×6, Rule 187 ×1) | **0** |
| "Identity note: the heading of rule 186 is printed without a full stop …" | 0 | **2** (Rule 186 parts 1-2) |
| "Amends G.O.Ms.No. 53/2025's Seventh Schedule …" | 1 | 1 |
| "Contents/body discrepancy: … rule 375 …" | 1 | 1 |
| "Draft or final status unresolved … (G.O. 24)" | 8 | 8 |
| G.O. 53 rate-table warnings (3 distinct texts) | 2 + 2 + 1 | 2 + 2 + 1 |

**Verification:**
- **Rule 185:** 5 parts, `#57`, with no warning (it was "186 absent").
- **Rule 187:** 1 part, `#59`, with no warning (it was "186 absent").
- **Rule 186:** 2 parts, `#58`, `provision_id` `Rule 186`, carrying the identity note.
- **TMVTR Rule 13:** 1 part, `#14`, with no warning. It never had an absence flag.
- **Rule 295A and 12B:** no warning, as before.
- **Unrelated warnings:** all 6 are unchanged in text and in which chunks carry them, and no warning disappeared apart from the false one.
- **Manifest note:** the corrected text is on all chunks of chapter 5, and the old false sentence appears nowhere.
- **Fail-closed check:** with the corrected flags, building with the **pre-Stage-9 parser** fails with "chunk flag 2 (… Rule 186) matches no chunk". The index therefore cannot be rebuilt from the old parser without the problem showing.

No rebuild was needed for this verification, so there was no blocker.

## 5. Proposed benchmark-label corrections (NOT applied; for human review through `review_import`)
These are valid **only after** the preview index is rebuilt with the Stage 9 parser. Against the current index, Rule 186 is not a provision, so the current labels describe the index's behaviour correctly.

| Row | Question | Current label | Proposed label | Kind of problem |
|---|---|---|---|---|
| TG-MP-001 | What does Rule 186 say? | `missing_provision`, no provisions | `retrieve`; `tmvr-1989-chap-5::Rule 186`; behaviour: answer from sources | incorrect factual note (fixed) and incorrect label. Not a retrieval failure (the text is retrievable as "Rule 185"). Legal review needed |
| TG-MP-002 | Explain TMVR rule 186. | same | same as MP-001 | same |
| TG-MP-003 | What are the conditions in Rule 186 …? | same | same as MP-001 | same |
| TG-MP-004 | Compare rules 185, 186 and 187. | same | `retrieve`; Rules 185, 186, 187 | same |
| TG-MP-005 | What do rules 186 and 188 say? | same | `retrieve`; Rules 186, 188 | same |
| TG-PN-005 | What is the fine under Rule 186? | `restricted` (penalty lock) | **no change proposed**. The penalty lock applies to any fine question. Rule 186 sets permit conditions and states no fine | no factual note to correct. A reviewer should confirm the label |
| TG-GC-002 | What does Rule 185 say? | `retrieve`; Rule 185; expected chunks `part1of6` to `part6of6` | expected chunks `part1of5` to `part5of5`. Drop `part6of6`, whose text (Luxury Tourist Cab conditions) is Rule 186 | incorrect expected-chunk label caused by the identity defect |

**Related changes for the reviewer:**
- If MP-001 to 005 move to `retrieve`, the `missing_provision` category keeps MP-006 to 008 (rules 999, TMVTR 99, 600), which really are absent.
- `eval/telangana-chunk-references.json` is generated from the index by `review_import.build_references`. It will need regenerating after a rebuild, because the Rule 185 chunk IDs change from `…of6` to `…of5`.
- No benchmark row covers TMVTR Rule 13, 12-B or TMVR 295-A.

## 6. Tests
| Run | Result |
|---|---|
| `test_tg_ingest*.py` (ingester, headings, chunk-flag tests: `test_chunk_flags_mark_chunks_ineligible…`, `test_flag_matching_nothing_or_malformed_fails_the_build`, `test_flags_and_notes_are_stored_in_the_index`) | 60 OK |
| `test_retrieval_eval.py` (benchmark schema) | 3 OK |
| `test_review_import.py` | 25 OK |
| `test_source_compare.py` | 13 OK |
| Full suite, before the edits | 623 OK |
| Full suite, after the edits | **623 OK** |

Also checked:
- The real `PREVIEW-CHUNK-FLAGS.json` passes `load_chunk_flags`, with 7 flags.
- `review_import.check_template` finds **no drift** between the review CSV and the edited benchmark. `notes` is not a template column.
- Labels, statuses and `reviewed_*` fields are unchanged.

## 7. Integrity (SHA-256, 181 files before and after)
The set: every file under `docs/legal-sources/telangana-traffic/`, every file under `chroma_telangana_preview/`, every git-tracked file, and the untracked Stage 7-9 files.
- **Changed, as intended (3):**
  - `DRAFT-telangana-manifest.json`, `738c901d0523…` → `c850b3c745f9…`
  - `PREVIEW-CHUNK-FLAGS.json`, `cdc3033a7999…` → `4f3833d702c6…`
  - `eval/telangana-retrieval-benchmark.json`, `cf13d4497b14…` → `80061e7544d9…`
- **Identical:** every other file.
  - That includes the 57 source files, all 9 index files (`chroma.sqlite3` `1950d5b3f781…`), the review CSV (`e6ddfdd8a185…`), the chunk references, `INGESTION-VALIDATION-REPORT.md` and every other reviewer document.
  - It also includes `backend/tg_ingest.py`, which is unchanged since Stage 9.
- Three `reference/*.ipynb` entries showed up as changed only because their names contain spaces; `git diff -- reference` confirms they are unchanged.

`review_import` was not run and no index was built. No network or Groq call was made, and nothing is committed.

## 8. Remaining risks
- **The preview index still holds the false warnings** on Rules 185 and 187, the old manifest sentence in `manifest_notes`, and no Rule 186 or TMVTR Rule 13 provision. Until a rebuild, answers citing Rule 185 or 187 carry the false warning, and questions about Rule 186 or TMVTR Rule 13 get `missing_provision`.
- **The corrected flags need the Stage 9 parser.** A rebuild from the old parser fails, which is intended. Commit the parser fix before rebuilding.
- **Legal:**
  - the numbering of 186, 295-A, 12-B and 13 against an official print;
  - the TMVTR 12-B title, which is absent from the source;
  - the currency of every snapshot rule;
  - Rule 81 (Stage 8).
- **Retrieval:** whether Rule 186 ranks well once indexed is unmeasured until the rebuild and benchmark re-run.
- **Tests:** the synthetic tests that use "Rule 186" as the missing example could mislead future readers.

## 9. Files
**Modified (3):**
- `/Users/vj/Downloads/KnowYourRules-repo/docs/legal-sources/telangana-traffic/DRAFT-telangana-manifest.json` (the `tmvr-1989-chap-5` note)
- `/Users/vj/Downloads/KnowYourRules-repo/docs/legal-sources/telangana-traffic/PREVIEW-CHUNK-FLAGS.json` (flags 2-3 → 1 flag)
- `eval/telangana-retrieval-benchmark.json` (5 `notes` fields)

**Created:**
- `eval/legal-validation/STAGE-10-REPORT.md`
- `eval/legal-validation/stage-10-originals/DRAFT-telangana-manifest.json`, `PREVIEW-CHUNK-FLAGS.json` and `telangana-retrieval-benchmark.json` (byte-for-byte originals)

**Uncommitted from earlier stages, unchanged now:**
- `backend/tg_ingest.py`
- `backend/source_compare.py`
- the tests `test_source_compare.py` and `test_tg_ingest_headings.py`
- the Stage 7-9 files in `eval/legal-validation/`

**Untouched:**
- `chroma_telangana_preview/` (all 9 files)
- all source documents and `SHA256SUMS`
- `eval/telangana-retrieval-review.csv`
- `eval/telangana-chunk-references.json`
- `INGESTION-VALIDATION-REPORT.md` and the other reviewer documents
- the approval records, Rule 81 and G.O. data
- all `backend/` code (retrieval, generation, validator, `review_import`)
- all tests

## Recommended next step
One approved change:
1. Commit the Stage 9 parser fix together with these corrections.
2. Rebuild the **preview** index into a new directory and confirm 590 chunks and the flag table in section 4.
3. Regenerate the chunk references and re-run the retrieval benchmark.
4. Then submit the section 5 label proposals through `review_import` for human approval.
