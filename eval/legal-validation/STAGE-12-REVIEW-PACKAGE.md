# Stage 12: review package for six benchmark corrections

**PROPOSED, NOT APPLIED, NOT APPROVED.** Nothing in this package changes the benchmark, the review CSV, the chunk references, any approval record or any index.

- **Machine-readable version:** [`stage-12-proposed-corrections.json`](stage-12-proposed-corrections.json). It has the full current and proposed values, including every `source_passage`.
- **Two kinds of evidence, kept apart:**
  - **Source-text evidence** (this package): what the local snapshot file says and how the Stage 11 index splits it.
  - **Legal approval** (not given here): whether the text is correctly numbered, current and applicable. Only a qualified reviewer can give it, and it is outside `review_import`.

## A. How the review process actually works (`backend/review_import.py`)
- **Commands**
  - `validate <csv…>` **writes nothing**: it only prints and sets the exit code. This is a genuine dry-run.
  - `reconcile <csv…> --out F` writes **one new candidate file**. It refuses to write over the benchmark, the review CSV or the references.
  - `build-refs` overwrites `eval/telangana-chunk-references.json`. By default it reads `chroma_telangana_preview`, the **old** index.
- **Nothing applies a correction.**
  - No command edits `telangana-retrieval-benchmark.json`.
  - Reviewer corrections are recorded beside the machine labels, as `reviewer_proposed_expected_provisions` in the candidate file.
  - The guide says "the engineering team applies your decisions". That is a manual step with no tooling and no automatic check.
- **What makes a review valid**
  - The row must keep the exact template columns, ids and order, with every machine column unchanged.
  - `reviewer_name`, `reviewer_designation` and `reviewed_on` must be filled. The date is `DD-MM-YYYY`, between 09-11-2026 and today.
  - All seven enum fields must be filled with allowed values.
  - A comment is required for `partially_correct`, `incorrect`, `ambiguous` and `missing_source`.
  - Every item in `human_correct_expected_provisions` must exist in the **references file** and have at least one answer-eligible chunk.
- **Not checked:**
  - **No signature and no identity proof.** A name is free text, so a "review" is only as trustworthy as whoever handles the CSV.
  - **No hashes of the sources or the index.** The candidate file records the sha256 of the benchmark and of each submission, nothing more.
- **Drift detection** (`check_template`) compares only `question`, `category`, `expected_retrieval_outcome`, `expected_provisions`, `label_source` and `reviewer_status`.
  - It **does not** compare `notes`, `expected_chunks`, `excluded_chunks`, `expected_documents`, `expected_answer_eligible` or `expected_behaviour`.
  - So it would not detect the TG-GC-002 chunk change, or the Stage 10 note change.
- **Legal approval is a separate system.** It is the signed record in `backend/legal_approval.py` and `scripts/sign_approval_record.py`, which binds source-document hashes. **No approval record exists** in either checkout, and `review_import` never reads or writes one.

**Blocker found:** `telangana-chunk-references.json` (586 chunks, from the old index) has **no Rule 186**.
- If a reviewer enters `tmvr-1989-chap-5 :: Rule 186`, `validate` would reject it as "not in the index".
- The references must be rebuilt from `chroma_telangana_preview_s11` (decision D1) before reviewers can record these corrections.

## B. The six proposals

**Evidence common to all six**
- Source file: `html-snapshots/tmvr-1989/middle-main-chap-5.htm`, sha256 `61f019808cb6…`, and it matches `SHA256SUMS`.
- Rule 186 is at line 752, anchor `#58`: `186 (1) Conditions of permit in respect of a luxury tourist cab :-`.
- The anchors for Rules 185, 187 and 188 are `#57`, `#59` and `#60`.
- Index: `chroma_telangana_preview_s11`, whose content is verified identical to the build at `f944466`.

**Proposed chunks**

| Chunk | Location | Text sha256 (first 12) |
|---|---|---|
| Rule 185 part 1–5 of 5 | `#57` | d3983dc072e7, f99eeea5bd26, a0a39109a2f6, 0e65139cd7e9, f471b970181e |
| Rule 186 part 1 of 2, part 2 of 2 | `#58` | 58de60d02a3e, 785b6a9952ec |
| Rule 187 part 1 of 1 | `#59` | 1cf7111f8fd5 |
| Rule 188 part 1 of 1 | `#60` | e7bb2dff2e7b |

**Shared legal caveats (all six)**
- Whether "186" is the correct number in an official print. The heading has no full stop.
- Rule 186 part 2 begins `(3) Conditions of permit in respect of a Motor Cab`. The snapshot doesn't settle whether motor-cab conditions belong to Rule 186.
- Whether the text is current.

### P1–P3. TG-MP-001, TG-MP-002, TG-MP-003
- **Questions:**
  - 001: "What does Rule 186 say?"
  - 002: "Explain TMVR rule 186."
  - 003: "What are the conditions in Rule 186 of the Telangana Motor Vehicles Rules?"
- **Current value:**
  - `category=missing_provision`, `expected_retrieval_outcome=missing_provision`;
  - `expected_documents`, `expected_provisions` and `expected_chunks` empty;
  - `expected_answer_eligible=false`, `expected_behaviour=refuse_missing_provision_no_substitution`.
- **Proposed value:**
  - `expected_retrieval_outcome=retrieve`, `expected_documents=[tmvr-1989-chap-5]`, `expected_provisions=[tmvr-1989-chap-5::Rule 186]`;
  - `expected_chunks` = Rule 186 parts 1 and 2 of 2;
  - `expected_answer_eligible=true`, `expected_behaviour=answer_from_sources`;
  - `category` per D2.
- **Evidence from Stage 11:**
  - Old index: guard returned `['Rule 186']` and Rule 185 was ranked first.
  - New index: guard returns `[]`, and Rule 186 is **rank 1** for all three.
- **Mechanically supported:** yes.
- **Legal interpretation still needed:** yes, the shared caveats.
- **If accepted:** the rows become scored retrieval cases, and guard accuracy on `_s11` returns to 12/12. The missing-provision guard is still tested by TG-MP-006, 007 and 008 (Rules 999, 99 and 600).
- **If rejected:** the rows keep asserting that Rule 186 is absent, so the benchmark rewards an index that hides it.

### P4. TG-MP-004: "Compare rules 185, 186 and 187."
- **Current value:** as P1.
- **Proposed value:**
  - expected provisions are Rules 185, 186 and 187;
  - the chunks are 185 parts 1–5, 186 parts 1–2 and 187 part 1 (8 chunks);
  - the other fields are as P1.
- **Evidence:** Stage 11 retrieves 185, 187 and 186 at ranks 1–3. The old guard blocked the question.
- **Mechanically supported:** yes.
- **Legal interpretation:** the shared caveats, plus D4 (whether every part of Rule 185 is "expected" for a comparison).
- **If accepted:** recall@5 is 1.0.
- **If rejected:** as P1.

### P5. TG-MP-005: "What do rules 186 and 188 say?"
- **Proposed value:** expected provisions are Rules 186 and 188; the chunks are 186 parts 1–2 and 188 part 1.
- **Evidence:** Stage 11 ranks 188 first and 186 second. The old guard blocked the question.
- **Mechanically supported:** yes. **Legal interpretation:** the shared caveats.
- **If accepted or rejected:** as P1.

### P6. TG-GC-002: "What does Rule 185 say?"
- **Current value:** `expected_provisions=[Rule 185]` (correct, unchanged). `expected_chunks` lists six chunks, `Rule 185::part1of6` to `part6of6`.
- **Proposed value:** `expected_chunks` becomes `Rule 185::part1of5` to `part5of5`, all at `#57`, with `source_passage` equal to the first 240 characters of each chunk. That is the same convention as the existing entries, which I checked.
- **Evidence:**
  - In the old index, **part 5 of 6 was mixed**:
    - its location spans `#57 .. #58`;
    - characters 0–2338 are Rule 185, and `186 (1)` begins at character 2339 (about 1,084 characters of Rule 186);
    - part 6 of 6 is entirely Rule 186 (`(h) the Luxury Tourist Cab permit…`).
    - So the error affected part 5 as well as part 6.
  - In `_s11`, none of the five Rule 185 parts contains `186 (1)` or "luxury tourist cab".
- **Mechanically supported:** yes. **Legal interpretation:** none for the mapping, which follows the anchor `#58` boundary. The numbering and currency caveats still apply.
- **Field changed:** `expected_chunks` only.
  - The drift check does not compare it, so the review CSV's `machine_expected_locations` and `machine_supporting_passage` would go stale silently (D5).
- **If accepted:** the chunk IDs resolve against `_s11` and the rebuilt references.
- **If rejected:** all six expected chunk IDs fail to resolve on `_s11`.

### Records each proposal would touch
- **P1–P5**
  - Benchmark fields: `expected_retrieval_outcome`, `expected_documents`, `expected_provisions`, `expected_chunks`, `expected_answer_eligible`, `expected_behaviour`, plus `category` (D2) and `label_source` (D3).
  - The **review CSV** row's machine columns must be changed in the same step, or `check_template` rejects every submission ("differs from the benchmark").
  - The repo has no generator for that CSV.
- **P6:** benchmark `expected_chunks`; the CSV columns are optional but would otherwise be stale.
- **All six:** `reviewer_status` stays `pending_human_review`. Only a reviewer's validated decision should move it.

## D. Dry-run and verification
- **Ran** `python3 -m backend.review_import validate eval/telangana-retrieval-review.csv`. This is read-only.
  - Result: `OK … 0 reviewed, 108 unreviewed, 0 error(s)`, so the template and benchmark currently agree.
- **Not done:** I didn't fill a CSV with a made-up reviewer to "test" the proposals. That would simulate an approval. The Rule 186 rejection above is established by reading the code and the references file instead.
- **Hashes:** 106 files hashed before and after:
  - both indexes;
  - the main checkout's sources, manifest and flags, and the branch copies;
  - the benchmark, review CSV and references;
  - `eval/legal-validation/`.

  **The differences are the two new Stage 12 files, plus two byte changes inside `chroma_telangana_preview_s11`** (`chroma.sqlite3` and `data_level0.bin`).
  - Chroma rewrites those files whenever a `PersistentClient` opens the directory, even only to read it, which I did to collect the chunk evidence.
  - A read-only SQLite check afterwards shows the same 590 chunk texts as the build at `f944466`, so the content is unchanged.
- **Confirmed:**
  - No approval was created, and no benchmark field, CSV row or chunk reference changed.
  - The original `chroma_telangana_preview` is byte-identical; it was read only through a copy.
  - No index was built or replaced. No commits were made.

## E. Issues these corrections do **not** fix
- **TG-MR-008:** a ranking miss. Rule 77 is indexed but not in the top 5.
- **TG-GO-007 and Rule 81:** the stale `tmvr-1989-chap-4::Rule 81` is ranked first, answer-eligible and unwarned. Amendment and currency handling (G.O. 77/2025) is unresolved.
- **TMVTR 12-B:** it cites anchor `#13`, which is 12-A's, because the source has no anchor at 12-B. 12-B also has no printed title.
- **TG-GC-002:** P6 corrects the chunk references but is awaiting approval. The CSV columns for this row also need regenerating.
- **Not legally verified:** the numbering of Rules 186, 295-A and 12-B and TMVTR Rule 13, and the currency of every snapshot rule.

## Decisions for you
| # | Decision | Recommendation |
|---|---|---|
| D1 | Rebuild `eval/telangana-chunk-references.json` from `chroma_telangana_preview_s11` (`build-refs --db-dir chroma_telangana_preview_s11`), so that reviewers can name Rule 186 | yes, as its own commit |
| D2 | New `category` for TG-MP-001…005 | `guard_control`, so they stay in the guard set as "must not block" cases |
| D3 | `label_source` for corrected rows | keep `machine_candidate` (the labels are still machine-derived), and record the correction in `notes` |
| D4 | TG-MP-004: expect all 5 parts of Rule 185, or the provisions only | the provisions are 185/186/187; all parts listed as `expected_chunks` |
| D5 | How to update the review CSV's machine columns for the 6 rows | edit those rows by hand in the same commit as the benchmark, then re-run `validate` |
| D6 | Approve, reject or defer each of P1–P6 individually | each needs your explicit yes. Applying them is a separate engineering edit, not a `review_import` step |
