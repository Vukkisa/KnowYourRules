# Stage 26: independent audit of source-status warnings

**Result:** in grounded (production) mode, no path returns legal text without its source-status warning, and approval cannot remove a warning. Three defects found, none fixed:
- **D1 and D2 (low):** legacy development mode only.
- **D3 (medium):** test portability.

There is a commit-boundary hazard: `server.py` mixes Stage 25 with earlier exact-vector work.

## Changed in Stage 26
- `tests/test_source_status.py`: 5 tests added (42 → 47). Backup: `stage-26-originals/test_source_status.py.pre-stage-26`.
- New deliverables: this report, `stage-26-warning-audit.json`, `stage-26-approval-independence.json`, `stage-26-worktree-boundary.json`.
- No backend, frontend, registry, source, index or register changes. No approval record, key or signature; nothing staged, committed or pushed; no Groq calls.

## 1. Warning propagation
Full table: `stage-26-warning-audit.json`.
- **Grounded answer and conflict:** warnings come from the cited documents with their [n] numbers. They are appended as a "Source status:" block and returned in `source_warnings`. The penalty note is added after the block and does not remove it.
- **Non-answer kinds and generator failure:** fixed messages only, no evidence text, empty warnings.
- **Grounded clarification:** a model-written question with no warning. The validator blocks new identifiers and evidence text, so it is not legal text.
- **Exception while building warnings:** HTTP 503 with the provider error only, so the answer is withheld.
- **Frontend:** warnings show in the answer text and in a per-source badge (built with `textContent`). `source_warnings` itself is not rendered as a separate panel. The browser itself was not tested.
- **Index copy (read-only sqlite):** Rule 81 is chunks 83 and 84 and both match the override. The neighbours are Rule 80, 80A and 82; none of them carries Rule 81 text.

### Defects
| ID | Severity | Summary |
|---|---|---|
| D1 | low (dev only) | Chunks with no `sha256` from different files merge into one "not recorded" warning naming only the first file. All citations are still listed. Unreachable in grounded mode. |
| D2 | low (dev only) | Registry edits are not reloaded until `/approval/refresh` or a restart. Grounded mode blocks instead, because the approval goes stale. |
| D3 | low (**fixed**) | Corrected after the first report: the source-hash test did already skip; "no skip" was an error from a grep that missed `skipTest`. The real gap was that both this test and the LD-register test skip silently in a clean clone or CI, so the coverage is lost. **Fix:** `TG_LEGAL_SOURCES_DIR` overrides the sources path (default: the sibling checkout), and `KYR_REQUIRE_LEGAL_DATA=1` turns those skips into failures. Verified: present (OK), missing (skip), missing + strict (fail). Backup: `stage-26-originals/test_source_status.py.pre-d3-fix`. |

## 2. Approval independence
Details: `stage-26-approval-independence.json`. All checks pass.
- **Status lookup:** it does not read approval.
- **Warnings:** only `verified_current` that is bound by a valid approval is silent.
- **Registry binding:**
  - The registry's hash is inside the signed bytes.
  - Any registry change makes the approval stale, then invalid.
  - A registry that is missing or malformed means every source warns and answers are blocked.
- **Rule 81** is still `known_amendments_unresolved` (G.O. 77; LD-001/LD-002).
- **LD-001 and LD-002** are still `evidence_incomplete` with no decision.
- **Limitation (unchanged):** reviewer authorisation is not machine-checked.

## 3. Tests added (only for real gaps)
- `test_conflict_response_carries_warnings_after_approval`: covers the conflict path, mixed override and base status in one source, and the badge's most-cautious status.
- `test_multiple_chunks_of_one_approved_snapshot_give_one_warning`: one warning, citations [1, 2].
- `test_generator_failure_returns_no_legal_text`
- `test_warning_failure_withholds_the_answer`: 503 response, answer withheld.
- `test_snapshot_chunk_missing_from_registry_warns_after_approval`

The other requested cases were already covered by Stage 25 tests (listed in the audit JSON). No assertion was changed.

## 4. Worktree and commit boundary
Details: `stage-26-worktree-boundary.json`. Nothing is unexplained.
- **Earlier intentional work, not Stage 25:**
  - Benchmark JSON, review CSV, chunk references, `test_review_import.py` and `test_benchmark_integrity.py`: Stages 13–14.
  - `hybrid_retrieval.py` and `test_bm25_plural.py`: Stage 17.
  - `exact_vector.py` and `test_exact_vector.py`: Stages 15–16.
  - `source_compare.py`: Stages 9–11.
  - Preview index: Stage 11.
  - Each earlier stage's backup equals HEAD, and the files' mtimes predate Stage 22.
- **Hazard:** the working-copy `server.py` imports the untracked `exact_vector.py`, so Stage 25 cannot be committed alone.

**Recommended boundary.** Simulated on a scratch copy of HEAD; it adds no failures in exact or HNSW mode.
1. **Commit A (exact vector, earlier work):**
   - `backend/exact_vector.py`
   - `tests/test_exact_vector.py`
   - `backend/server.py` with the content of `stage-25-originals/server.py.pre-stage-25`. To stage it without touching the working file:
     ```bash
     git update-index --add --cacheinfo 100644,$(git hash-object -w eval/legal-validation/stage-25-originals/server.py.pre-stage-25),backend/server.py
     ```
2. **Commit B (Stage 25 + Stage 26 tests):**
   - `backend/source_status.py`, `legal-status/source-status.json`
   - `backend/legal_approval.py`, `backend/grounded_answer.py`, `backend/server.py`, `frontend/index.html`
   - `tests/test_server.py`, `tests/test_legal_approval.py`, `tests/test_source_status.py`
   - Optionally, the Stage 25/26 reports and JSON (not the `*-originals` backups).

Leave the Stage 13–17 eval and retrieval files, `source_compare.py`, the preview index and the backups out of B.

## 5. Validation
- **Full suite:** 719 OK in exact mode and 719 OK in HNSW mode (714 + 5).
- **Standalone:** `test_source_status` 47, `test_server` 131 and `test_legal_approval` 64, all OK.
- **Checksums:** 63/63 OK.
- **Registry:** valid against the index copy (20 documents) and the corpus. SHA-256 `5a174820…` is unchanged.
- **Preview index:** byte-identical to the Stage 23 copy. I read it only through a scratchpad copy.
- **Approval:** no `legal/` approval record exists.

## Rollback
- **Stage 26:**
  ```bash
  cp -p eval/legal-validation/stage-26-originals/test_source_status.py.pre-stage-26 tests/test_source_status.py && rm eval/legal-validation/STAGE-26-REPORT.md eval/legal-validation/stage-26-*.json
  ```
- **Stage 25:** use the instructions in `STAGE-25-REPORT.md`. Its backups are present and verified: the backed-up `server.py` contains the exact-vector code, so restoring it keeps that work.
