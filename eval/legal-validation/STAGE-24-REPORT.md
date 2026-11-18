# Stage 24: approval scope and Rule 81 warning design

**Changed files:** new files only, in `eval/legal-validation/`:
- this report;
- [`stage-24-approval-scope.json`](stage-24-approval-scope.json);
- [`stage-24-test-failure-analysis.json`](stage-24-test-failure-analysis.json);
- [`stage-24-warning-design.md`](stage-24-warning-design.md).

**Not changed:** code, tests, approval records, indexes, sources, manifests, LD-001/LD-002. No signatures, no Groq/external calls, nothing committed.

## 1. Approval coverage
- **No approval record exists** (`legal/telangana-approval.json` absent). The approved set is whatever a signed record's `documents` list names (`backend/legal_approval.py:122`); no code generates it.
- **Rule 81 source:** both chunks (`b46d621c…`, `6e085556…`) carry `source_file=middle-main-chap-4.htm`, `sha256=d901ad96…`, identical to `SHA256SUMS` and manifest entry `tmvr-1989-chap-4` (`unverified_snapshot`). 55 chunks in the preview index come from that file.
- **Coverage is all-or-nothing:** `index_errors()` (`legal_approval.py:374`) rejects any indexed hash missing from the record; `corpus_errors()` (`:349`) does the same for corpus files, and the grounded gate requires `TG_CORPUS_DIR` (`server.py:1011`). So **any valid record for the current index must include `middle-main-chap-4.htm`**, and that enables both Rule 81 chunks (`answer_eligible=True`, `server.py:889`).
- **Correction to Stage 23 M2:** leaving the snapshot out of the record without rebuilding the index makes the record invalid and disables all answers. M2 is only viable combined with a rebuild that omits the file.
- **Stage 23 simulation:** representative for retrieval, citations and the absence of warnings. Not exact: it added only retrieved hashes to `SOURCES`, used placeholder titles/instruments, bypassed the gate, used a mock generator and the preview index (no production index `chroma_telangana_db` exists).

## 2. Targeted test "failures"
- **Cause:** invocation error. `python3 -m unittest tests.test_exact_vector tests.test_bm25_plural` fails with `ModuleNotFoundError` because `tests/` has no `__init__.py`. No test code ran.
- **Standalone, correct form** (`python3 -m unittest discover -s tests -p '<file>.py'`):

| Module | exact | HNSW |
|---|---|---|
| `test_exact_vector` | 24 OK | 24 OK |
| `test_bm25_plural` | 6 OK | 6 OK |

- No order dependence, shared state, env-var, fixture, Ollama/index or nondeterminism issue: both modules use fixtures only. Tests unchanged.

## 3. Warning design
See `stage-24-warning-design.md`. Key points:
- Separate **text status** (`verified_current`, `official_currency_unconfirmed`, `unverified_snapshot`, `known_amendments_unresolved`) from **approval state**; approval never removes a text-status warning.
- Status kept in a reviewed `source-status.json` keyed by sha256/provision, looked up at runtime (reversible, no rebuild).
- Backend-fixed warning texts in a new `source_warnings` API field and citation suffix; frontend panel and two-part badge. No exclusions implied; no legal decision made.

## 4. Validation
- Full suite: 672 OK (exact), 672 OK (HNSW).
- Checksums: 63/63 OK.

## Unresolved
- LD-001, LD-002 (unchanged).
- Whether `source-status.json` should be bound into the signed approval record.
- Who may set `verified_current` (proposed: counsel only, via a register decision).
