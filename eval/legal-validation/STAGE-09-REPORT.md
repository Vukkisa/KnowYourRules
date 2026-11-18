# Stage 9: rule-heading parser fix applied

The Stage 8 fix ([`proposed-heading-fix.diff`](proposed-heading-fix.diff)) is applied to `backend/tg_ingest.py`. Effects:
- TMVR 186, TMVR 295-A, TMVTR 12-B and TMVTR 13 are now their own provisions.
- Every other provision in the 20 documents is unchanged.

What was not touched:
- The production or preview Chroma index, the sources, the manifest, the chunk flags, the benchmark and the review CSVs.
- Retrieval, answer generation and the validator.

Nothing is committed. Recognising a rule's identity correctly says nothing about whether its text is legally current.

## 1. Parser change (`backend/tg_ingest.py`, +20 lines, no line removed or edited)
Applied with `git apply` exactly as reviewed in Stage 8.
- **New `UNPUNCTUATED_HEADING_RE`:** `NNN`, an optional spaced `-X` suffix, an optional ` .`, an optional `(1)`, an optional title starting with a capital, then a **required** `:-`, `: -`, `:–` or `:—`.
- **New `_next_in_sequence(key, last_key)`:** true only for N+1 with no suffix, or the same N with the next suffix letter (none to A, A to B, and so on). It is false when there is no previous rule.
- **`segment()`:** tries the fallback only when **all** of these hold:
  - no existing pattern matched;
  - the block is text;
  - the document is not a G.O.;
  - the current provision is not a Schedule or Form;
  - the regex matches;
  - the number is next in sequence.
  A match is then treated exactly like an existing heading match, with no prefix. The existing monotonic check still applies.
- `PROVISION_PATTERNS`, `match_provision`, `SUB_RULE_RE`, `CLAUSE_RE` and every other existing rule are unchanged.
- **Rule 12-B title:** the regex makes the title optional, so 12-B gets `heading=""`. No title is invented.

## 2. Tests
| Run | Before (baseline, unpatched) | After |
|---|---|---|
| `tests/test_tg_ingest_headings.py` | 10 tests: 7 OK, 3 expected failures | **15 tests, all OK** |
| `tests/test_tg_ingest.py` (existing) | 45 OK | **45 OK** |
| Full suite (`unittest discover -s tests`) | 618 OK (3 expected failures) | **623 OK** |

Changes to the test file (nothing removed or weakened):
- **The 3 defect tests** (`HeadingWithoutFullStop`, previously `KnownDefect`):
  - Their `expectedFailure` decorators were removed, as Stage 8 required, and they now pass.
  - The 12-B/13 test also checks that 12-B's heading is `""` and 13's is `"Placeholder three"`.
- **The 7 existing-behaviour tests** are unchanged, and all pass.
- **New `FallbackLimits`, 5 tests**, covering what the fallback must reject:
  - a number that is not next in sequence (`188 (1) … :-` after 185; spaced `185 - B . … :-`);
  - no `:-` terminator;
  - a number followed by ordinary text (`186 of these rules shall apply :-`);
  - the first rule of a document, where there is no previous rule;
  - schedules and G.O.s.
- **One new test failed on its first run.** Its line `185-B Item :-` is matched by the pre-existing `PROVISION_PATTERNS[2]` (`NNN-X Title`), which has no sequence check. The fallback was not involved.
  - I corrected the test to exercise the fallback, using a spaced suffix that only the fallback reads.
  - The behaviour of pattern 2 is recorded as a limitation that existed before this change.

## 3. Chunk counts (built in memory; nothing written outside the scratch directory)
I ran `load_blocks` and `chunk_document` over all 20 manifest documents twice: once with the unpatched ingester (from `git show HEAD:backend/tg_ingest.py`) and once with the patched one.
- G.O. 53 has two provisions both identified as `SCHEDULE`. This existed before. Chunks are therefore keyed by occurrence.

| | Count |
|---|---|
| Current preview index | **586** |
| Unpatched parser | **586**, text identical to the index chunk for chunk |
| Patched parser | **590** (+4 net) |
| Unchanged chunks | 578 |
| Added | 5: Rule 186 parts 1-2, 295A, 12B, 13 |
| Removed | 1: Rule 185 part 6 of 6, whose text is now Rule 186 |
| Changed | 7: Rule 185 parts 1 to 5, Rule 295, Rule 12A |
| Documents touched | 2 of 20: `tmvr-1989-chap-5`, `tmvtr-1963` |

- **About "four new rule chunks":** there are 4 new **rules** but 5 new **chunks**, because Rule 186 (4,109 characters) needs 2 parts. One chunk is removed, so the net change is +4.
- **What the changed chunks contain:**
  - Rule 185 parts 1 to 3: only the header changes, from "part N of 6" to "part N of 5".
  - Rule 185 parts 4 and 5: repacked, now ending before `186 (1)`.
  - Rule 295 and Rule 12A: shortened to end before 295-A and 12-B.
- **No text was gained or lost.** In both touched documents, total body characters (186,962 and 21,528) and the multiset of text lines are identical before and after. Only provision boundaries moved.

## 4. The four headings
| Provision | Heading | Location | Parts | First words |
|---|---|---|---|---|
| tmvr-1989-chap-5 :: **Rule 186** | Conditions of permit in respect of a luxury tourist cab | `middle-main-chap-5.htm#58` | 2 | `186 (1) Conditions of permit …` |
| tmvr-1989-chap-5 :: **Rule 295A** | Painting of goods carriages carrying dangerous or hazardous goods | `#169` | 1 | `295-A . Painting of goods …` |
| tmvtr-1963 :: **Rule 12B** | *(empty; the source gives none)* | `middle-ap-mv-tr-1963-main.htm#13` | 1 | `12-B : - Whereby a notification …` |
| tmvtr-1963 :: **Rule 13** | Rates of penalty | `#14` | 1 | `13 Rates of penalty : - If the tax due …` |

The neighbouring rules are now separate:
- Rule 185 ends at `#57`, before `186 (1)`.
- Rule 295 ends at `#168`.
- Rule 12A ends at `#13`, before `12-B`, and Rule 13A starts at `#15`.
- Rule 187 is unchanged.

Rule 186 part 2 begins `(3) Conditions of permit in respect of a Motor Cab :-`. This follows the source's sub-rule structure and is not a new heading; it must not be read as a separate rule.

## 5. Source-text comparison (`backend/source_compare.compare`, each new or changed chunk against its own source file)
| Chunk | Result |
|---|---|
| Rule 185 parts 1 to 5, Rule 186 parts 1-2, Rule 295, Rule 12A, Rule 13 | **verbatim** |
| Rule 295A | **whitespace-only**: the source HTML splits `295 -A` across tags. The same difference existed inside the old Rule 295 chunk |
| Rule 12B | **whitespace-only**: same cause (`12 -B`). It existed inside the old Rule 12A chunk |

No chunk diverges. No chunk needed the "ignoring pipes" level.

## 6. Reviewer-warning investigation (Rule 185 and 187)
- **No code generates the warning.** `PREVIEW-CHUNK-FLAGS.json` is reviewer-authored data.
  - `build_telangana_index.load_chunk_flags` and `apply_chunk_flags` only validate the file and **append** each `warning` to the `extraction_warning` of every matching chunk.
  - A flag that matches no chunk is a build error.
- **Why the warning was written.** `INGESTION-VALIDATION-REPORT.md` (line 75) compared the provisions the parser found with each chapter's contents list, and reported *"Matches every chapter's contents list except rule 186 (listed, absent from the text)"*.
  - That check ran on the parser's output, so the parser defect made Rule 186 look absent.
  - The reviewer turned that result into the 185/187 flags. The same wording appears in two more places: the `tmvr-1989-chap-5` **manifest note**, and the `notes` of benchmark rows TG-MP-001 to 003 in `telangana-retrieval-benchmark.json`.
  - The same report says TMVTR *"13 appears only as 13-A/13-B"*, which the parser defect also caused.
- **Where the false claim reaches:**
  - **The flags:** `extraction_warning` on Rule 185 (all parts) and Rule 187.
  - **The manifest note:** it is copied into `manifest_notes` on every chunk of chapter 5.
  - **The reports and benchmark notes listed above.**
- **Does the logic or the data need to change?** Only the **data**.
  - The generating logic was the parser defect, now fixed.
  - The flag mechanism itself is correct.
  - The flags will still *match* after a rebuild, because Rules 185 and 187 still exist. So a rebuild without the correction would **silently** ship a Rule 186 chunk next to warnings saying Rule 186 is absent.
- **Smallest safe correction, for a separate reviewed change.** Nothing was edited here.
  1. `PREVIEW-CHUNK-FLAGS.json`:
     - Remove the two Rule 186 "Missing source" flags (185, 187).
     - Add one flag on `tmvr-1989-chap-5 / Rule 186`, for example: "Heading printed without a full stop after the rule number; recognised by the Stage 9 sequence fallback. Verify numbering against an official print." Keep `answer_eligible` as a reviewer decision.
     - Add a similar flag on `tmvtr-1963 / Rule 12B` for its missing title.
     - Record in the reviewer notes who withdrew the old flags and why, citing Stage 8 and Stage 9. The old text stays in git and in this report for provenance.
  2. The manifest `tmvr-1989-chap-5` note: replace the last sentence. This is a manifest change and goes through the manifest approval process.
  3. The benchmark notes for MP-001 to 003 and the review CSV labels go through `review_import` with human approval.
  4. `INGESTION-VALIDATION-REPORT.md`: add an erratum rather than rewriting the original finding.
- **Is the correction needed for the parser fix itself?** No. The code change and tests stand alone. The correction **must** happen before or together with the next index rebuild.

## 7. Integrity (SHA-256)
I hashed 36 files before any edit and again after all work. **All the protected files are byte-identical.** Only `backend/tg_ingest.py` and `tests/test_tg_ingest_headings.py`, the two intended edits, differ.

| Set | Files | Result |
|---|---|---|
| Source documents named in the manifest | 20 | identical |
| `DRAFT-telangana-manifest.json` | 1 | identical (`738c901d0523…`) |
| `chroma_telangana_preview/*` | 9 | identical (`chroma.sqlite3` `1950d5b3f781…`) |
| `PREVIEW-CHUNK-FLAGS.json` | 1 | identical (`cdc3033a7999…`) |
| `eval/telangana-retrieval-review.csv` | 1 | identical (`e6ddfdd8a185…`) |
| `eval/telangana-retrieval-benchmark.json` | 1 | identical (`cf13d4497b14…`) |
| `eval/legal-validation/batch-01-results.csv` | 1 | identical |
| `backend/tg_ingest.py` | 1 | **changed**, as intended (`38d58aafedb9…` before) |
| `tests/test_tg_ingest_headings.py` | 1 | **changed**, as intended |

`review_import` was not run and no index was built. No network or Groq call was made.

## 8. Limitations and next step
**Limitations:**
- **Pattern 2 accepts `NNN-X Title` with no sequence check.** This existed before (`PROVISION_PATTERNS[2]`) and was not changed. No spurious match occurs in the current sources: the gap check and the before/after comparison show none.
- **Forward list items and line-initial "Rule NNN …" references** can still open a provision through the existing patterns 1 and 2, but only if their number is higher than the last rule's. No case exists in the current sources.
- **The fallback assumes rules are numbered in sequence.** A rule printed without a full stop *after a gap*, for example 186 when 185 is itself missing, would still be missed.
- **Heading confirmation:** a person should confirm that 12-B, 13 and 295-A are rule headings. Their source anchors suggest it, but no official print has been checked.
- **The `(1)` stripping:** Rule 186's heading leaves out the `(1)` that starts the line. The text keeps it.
- **Missing-provision guard:** the server's guard reads provision IDs from the index. Until the index is rebuilt, questions about Rule 186 or TMVTR Rule 13 still return `missing_provision`.

**Recommended next step**, one approved change:
1. Correct the reviewer data as in section 6 (flags and manifest note), with a reviewer's sign-off.
2. Rebuild the **preview** index with `build_telangana_index --preview-unapproved` into a new directory, and confirm 590 chunks and the flags applied.
3. Re-run the retrieval benchmark.
4. Propose label changes for TG-MP-001 to 005, TG-PN-005 and TG-GC-002 through `review_import`, for human approval.

## Reproduce
```bash
SRC=../KnowYourRules-repo/docs/legal-sources/telangana-traffic/source-documents
python3 -m unittest discover -s tests -p "test_tg_ingest*.py" -v
python3 -m unittest discover -s tests
git diff backend/tg_ingest.py                 # the 20 added lines
git show HEAD:backend/tg_ingest.py > /tmp/orig_tg_ingest.py   # unpatched parser, for the before/after build
python3 -m backend.source_compare --sources "$SRC" checksums
python3 -m backend.source_compare --sources "$SRC" context html-snapshots/tmvr-1989/middle-main-chap-5.htm "186 \(1\)" --width 200
```

The before/after build loads `/tmp/orig_tg_ingest.py` with `importlib.util.spec_from_file_location`. It then calls `chunk_document(load_blocks(...), entry)` for every `tg_manifest.load_manifest(...)` entry with both parsers, keys chunks by `(manifest_id, provision_id, part, occurrence)`, and compares each new or changed body with `source_compare.compare` against `source_compare.official_text(SRC, source_rel(meta))`.
