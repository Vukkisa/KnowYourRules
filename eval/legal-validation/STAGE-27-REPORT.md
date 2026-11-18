# Stage 27: test portability fix and commit readiness

**Result:** the two legal-data tests now run fully in a fresh clone, against a pinned fixture kept in this repository. The two-commit plan passes on a local clone of HEAD in exact and HNSW modes. No production code, legal data, index or retrieval configuration changed; nothing was staged, committed or pushed. Machine-readable results: `stage-27-validation.json`.

## Changes
- **New `tests/fixtures/legal-data-snapshot.json`.** It pins:
  - the 63 `SHA256SUMS` entries;
  - the 20 manifest `{sha256, source_class}` entries;
  - the LD-001 and LD-002 `{status, decision, reviewer, review_date}` fields;
  - the SHA-256 of each source file it was taken from.

  It contains hashes and status fields only, no legal text.
- **`tests/test_source_status.py`** (backup: `stage-27-originals/test_source_status.py.pre-stage-27`):

| Test | Before | Now |
|---|---|---|
| `test_every_hash_matches_sha256sums_and_draft_manifest` | Read the sibling `KnowYourRules-repo`; skipped silently when absent | Always runs against the fixture. Same assertions, plus: each registry status must match the manifest `source_class` |
| `test_ld001_ld002_still_unresolved_in_the_register` | Read `eval/legal-validation/`; skipped silently when absent | Always runs. Stronger: status, decision, review date and the full reviewer must be unset, and every registry `decision_ref` must be a pinned decision |
| `test_pinned_snapshot_matches_live_legal_sources` (new) | – | Live `SHA256SUMS` and manifest must hash to the pinned values |
| `test_pinned_snapshot_matches_live_decision_register` (new) | – | Live LD-001/LD-002 fields must equal the pinned values |

- **Live checks:** the two new drift tests skip when the live files are absent. `KYR_REQUIRE_LEGAL_DATA=1` makes that a failure instead.
- **Tamper check:** setting LD-001 to `approved` in the fixture fails two tests. The fixture was then restored byte-identical.
- **D1 and D2 are unchanged.** They affect legacy development mode only; grounded mode blocks instead.

## Validation
- **Worktree:** 721 OK in exact mode and 721 OK in HNSW mode.
- **Standalone:** `test_source_status` 49, `test_server` 131, `test_legal_approval` 64 and `test_exact_vector` 24, all OK.
- **Fresh-clone simulation** (local `git clone` of `f944466` in the scratchpad, no network, no sibling repo, no `eval/legal-validation`):

| State | exact | HNSW |
|---|---|---|
| HEAD | 610 OK | 610 OK |
| HEAD + A | 634 OK, 1 skip | 634 OK, 1 skip |
| HEAD + A + B | 683 OK, 3 skips | 683 OK, 3 skips |

- **Skips in the clone:**
  - the two live drift checks (intended);
  - `test_stage15_record_agrees_with_squared_l2`. This one belongs to the earlier exact-vector work and has the same fresh-clone pattern; it is out of scope here.
- **Legal data:**
  - Checksums: 63/63 OK.
  - The registry is valid against the Stage 26 copy of the preview index (590 chunks, 20 documents) and against the corpus; its SHA-256 `5a174820…` is unchanged.
  - Rule 81 (chunks 83 and 84) is still `known_amendments_unresolved`.
  - LD-001 and LD-002 are still `evidence_incomplete` with no decision.
  - No approval record, key or signature exists.
  - The preview index is byte-identical to the Stage 23 copy.

## Worktree
- Nothing is staged. The tracked diff is unchanged since Stage 26; the only new item is `tests/fixtures/`.
- **Correction to Stage 26:** `tests/test_source_compare.py` (untracked) was missing from the classification. It is earlier work belonging with `backend/source_compare.py` (Stages 9–11), and it is in neither commit.
- **Left untouched:**
  - Stage 13–14 eval files: benchmark, CSV, chunk references, `test_review_import.py` and `test_benchmark_integrity.py`.
  - Stage 17: `hybrid_retrieval.py` and `test_bm25_plural.py`.
  - `source_compare.py` and its test, the preview index, and all reports and backups.

## Two-commit plan (prepared, not executed)
Run from `/Users/vj/Downloads/KnowYourRules-tg` on `feature/telangana-assistant`. Start from an empty index (`git diff --cached --name-only` prints nothing).

### Commit A: exact vector search (earlier work)
```bash
git add backend/exact_vector.py tests/test_exact_vector.py
```
Stage the pre-Stage-25 `server.py` into the index only; the working file is not touched:
```bash
git update-index --cacheinfo 100644,$(git hash-object -w eval/legal-validation/stage-25-originals/server.py.pre-stage-25),backend/server.py
```
Check the staged state:
```bash
git diff --cached --name-only
```
```bash
git show :backend/server.py | cmp - eval/legal-validation/stage-25-originals/server.py.pre-stage-25 && echo index-matches-backup
```
```bash
git diff --cached --stat
```
```bash
git diff --cached backend/server.py
```
Expect exactly 3 files; `server.py` should show +34/−4, covering the `exact_vector` import, `VECTOR_SEARCH`, `_build_exact_index` and `vector_search`.

**Do not** run `git add backend/server.py` for A: that would stage the Stage 25 version.

### Commit B: Stage 25 implementation + Stage 26/27 tests (after A is committed)
```bash
git add backend/server.py backend/source_status.py backend/legal_approval.py backend/grounded_answer.py frontend/index.html legal-status/source-status.json tests/test_server.py tests/test_legal_approval.py tests/test_source_status.py tests/fixtures/legal-data-snapshot.json
```
```bash
git diff --cached --name-only
```
```bash
git diff --cached --stat
```
Expect exactly 10 files; `server.py` should show about +99/−9 relative to A. Optionally add `eval/legal-validation/STAGE-2[5-7]-REPORT.md` and `eval/legal-validation/stage-2[5-7]-*.json`, never the `*-originals/` backups.

### Safety
- **Dependency:** B depends on A (the `backend.exact_vector` import and `srv.VECTOR_SEARCH`). Committing B without A would fail to import.
- **numpy:** `exact_vector.py` uses numpy, which `requirements.txt` does not list. chromadb installs it transitively, so the risk is low.
- **Blocking failures:** none found. A and A+B pass on a fresh clone in both modes.

## Rollback
```bash
cp -p eval/legal-validation/stage-27-originals/test_source_status.py.pre-stage-27 tests/test_source_status.py && rm -r tests/fixtures && rm eval/legal-validation/STAGE-27-REPORT.md eval/legal-validation/stage-27-validation.json
```
Stage 26 and Stage 25 rollbacks are unchanged; see their reports.
