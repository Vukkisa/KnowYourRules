# Stage 25: hash-bound legal source-status warnings

**Result:** every source now carries a text status from a hash-bound registry. The status is shown to users as fixed backend warnings, and approval never removes it. The registry's SHA-256 must be named in the signed approval record. Rule 81 is `known_amendments_unresolved`, citing G.O. 77 and LD-001/LD-002.
- **Answers stay disabled:** no approval record, key or signature was created.
- **LD-001 and LD-002 are unchanged** (`evidence_incomplete`). Rule 81 stays answer-eligible and is not marked current.

## Changed files
| File | Change |
|---|---|
| `legal-status/source-status.json` (new) | Registry: 20 entries (13 `unverified_snapshot`, 7 `official_text_commencement_unconfirmed`), 1 provision override (Rule 81), 0 `verified_current`, all reviewer fields null. SHA-256 `5a174820…` |
| `backend/source_status.py` (new) | Parser and validator, index and corpus hash checks, lookup with overrides, fixed `TEMPLATES`, de-duplicated `collect_warnings` |
| `backend/legal_approval.py` | Optional record field `source_status_sha256`; `source_status_errors()`; `evaluate(source_status_file=...)` |
| `backend/server.py` | Loads the registry with the approval; fingerprint includes it; gate requires a valid, bound registry; `retrieve()` annotates `text_status` on copies; `source_entries` adds `text_status`; new `SourceWarning` model and `ChatResponse.source_warnings`; a "Source status:" block appended to answer/conflict/development text |
| `backend/grounded_answer.py` | `Evidence.text_status` (default None), passed in the evidence header |
| `frontend/index.html` | Second badge for text status, separate from the approval badge |
| `tests/test_source_status.py` (new) | 42 tests |
| `tests/test_server.py`, `tests/test_legal_approval.py` | Fixtures bind a synthetic registry; assertions updated where Stage 25 intentionally changes output (additive fields, appended status block, binding required). No check weakened |
| `eval/legal-validation/stage-25-*` | Deliverables and backups |

**Not changed:** sources, manifests, `SHA256SUMS`, benchmark, CSV, decision register, retrieval ranking, answer eligibility, and the preview index (see the incident below).

## Design points
- **Statuses:** `verified_current`, `official_text_commencement_unconfirmed`, `unverified_snapshot`, `known_amendments_unresolved`.
  - A source with no valid entry gets `status_not_recorded`.
  - `verified_current` that is not covered by a valid, bound approval shows `verified_current_not_approved`.
- **Registry rules:**
  - Each entry is bound to a file SHA-256, checked against index metadata and corpus files.
  - Duplicates, malformed hashes, missing entries and mismatches all make the registry invalid. An invalid registry blocks grounded answers, and every source then warns.
  - `verified_current` needs a complete human review block (name, designation, organisation, date, decision, rationale) plus a decision reference.
- **Warnings:**
  - Text comes only from fixed templates and never claims the snapshot *is* outdated or that G.O. 77 *is* in force.
  - One warning per (source, override, status), listing the citations it covers.
- **Compatibility:**
  - `source_warnings` and `text_status` are additive fields.
  - Old clients still see the warnings, because they are appended to `response`.

## Approval integrity
See `stage-25-approval-integrity.json`.
- **Binding:** `source_status_sha256` sits inside the signed bytes. Editing the binding breaks the signature, and editing the registry breaks the hash match.
- **Server behaviour:** any registry change makes the approval `stale` immediately, and `invalid` after a refresh.
- **Backward compatibility: fail closed.** Pre-Stage-25 records still parse, but `evaluate` rejects them with "re-approval required". No real record exists, so nothing currently valid is lost.

## Warning propagation (index copy, exact = HNSW)
| Question | Warnings (status: citations) |
|---|---|
| Q1: names Rule 81 | official order: 1, 4, 5 · **Rule 81: 2, 3** · snapshot (chap 5): 6 |
| Q2: "current" Rule 81 | **Rule 81: 1, 2** · snapshot (chap 4): 3–5 · snapshot (chap 8): 6 |
| Q3: G.O. 77 fees | official order: 1, 3–6 · **Rule 81: 2** |
| Q4: Rule 81 with G.O. 77 | official order: 1, 3–6 · **Rule 81: 2** |

The Stage 23 gap is closed: the Rule 81 warning names G.O. 77 and states that the commencement and consolidated wording are unestablished, including on Q2.

## Validation
- **Full suite:** 714 OK in exact mode and 714 OK in HNSW mode (672 before, plus 42 new).
- **Standalone** (`python3 -m unittest discover -s tests -p '<file>.py'`): `test_source_status` 42 OK, `test_legal_approval` 64 OK, `test_server` 131 OK.
- **Checksums:** 63/63 OK.
- **Registry:** valid against a copy of the preview index (20/20 documents) and against the corpus files.

## Incidents (disclosed)
- **The preview index was opened directly, not through a copy.** I opened `chroma_telangana_preview_s11` with chromadb in Stage 24 and early in Stage 25, and chromadb rewrote `chroma.sqlite3` and `data_level0.bin`.
  - **Content check:** logical content was identical to the Stage 23 copy (590 chunks; ids, text, metadata and embeddings).
  - **Fix:** I restored the bytes from that copy, and the index is now byte-identical to it.
  - **As-found copy kept** in the scratchpad: `/private/tmp/claude-501/-Users-vj-Downloads-KnowYourRules-repo/e711426c-6f55-49fe-8882-bea62108ad89/scratchpad/s23/preview_s11_as_found_stage25`.
- **`tests/test_legal_approval.py` was edited before it was backed up.**
  - The backup was reconstructed by reversing the two edits, and the result is byte-identical to `git HEAD`.
  - It is stored as `stage-25-originals/test_legal_approval.py.reconstructed-pre-stage-25`.

## Limitations
- **What the code can and cannot check:** it checks that a review block is complete, not that the reviewer was authorised. Authorisation comes from the signed approval binding the registry.
- **Severity:** a source's badge shows its most cautious chunk status for that answer. A per-provision status is in `source_warnings`.
- **Undocumented record field:** handoff §5 and `docs/approval-trust-model.md` (untracked, not edited) do not yet describe `source_status_sha256`.
- **Untested here:** real-model behaviour (no Groq), and the browser rendering (static checks only).

## Rollback
```bash
cd /Users/vj/Downloads/KnowYourRules-tg
O=eval/legal-validation/stage-25-originals
cp -p $O/legal_approval.py.pre-stage-25 backend/legal_approval.py
cp -p $O/server.py.pre-stage-25 backend/server.py
cp -p $O/grounded_answer.py.pre-stage-25 backend/grounded_answer.py
cp -p $O/index.html.pre-stage-25 frontend/index.html
cp -p $O/test_server.py.pre-stage-25 tests/test_server.py
cp -p $O/test_legal_approval.py.reconstructed-pre-stage-25 tests/test_legal_approval.py
rm backend/source_status.py tests/test_source_status.py && rm -r legal-status
```
After rollback the suite should be back to 672 tests.
