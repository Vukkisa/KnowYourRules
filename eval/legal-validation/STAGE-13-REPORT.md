# Stage 13: rebuilt chunk references and benchmark-correction transaction preview

**PROPOSED, NOT APPLIED, NOT APPROVED.** The benchmark, the review CSV, the live `eval/telangana-chunk-references.json`, every index, every source and every approval record are unchanged. No legal approval is claimed.

## Files
| File | Purpose |
|---|---|
| `stage-13-telangana-chunk-references.candidate.json` | New references, generated from `chroma_telangana_preview_s11` (590) |
| `stage-13-originals/telangana-chunk-references.pre-stage-13.json` | Byte-identical backup of the live file (586, sha256 `31dd5e8faa56…`) |
| `stage-13-reference-diff.json` | Old vs new, checks, identities, provenance |
| `stage-13-proposed-benchmark-patch.json` | Exact benchmark and CSV changes, dry-run results |

**Why the new references are a candidate, not installed.** I installed them at the live path, ran the suite, and 2 tests failed; I then restored the original. Both failures are expected and can only be cleared by changes outside this stage:
- `tests/test_review_import.py:59–60` hardcode 586 references and 572 answer-eligible (the candidate has 590 and 576).
- `tests/test_review_import.py:78` requires every benchmark chunk to resolve. TG-GC-002's `Rule 185::part*of6` no longer exist, so this passes only once P6 is applied.

So the references, P6 and the test counts must land in **one change**.

## A. Baseline
- Branch `feature/telangana-assistant`, HEAD `f944466`. Stage 9 parser fix `14450cf2957…`; Stage 10 metadata `f944466fc6c…`. Untracked: `backend/source_compare.py`, `tests/test_source_compare.py`, `eval/legal-validation/`, `chroma_telangana_preview_s11/`.
- `chroma_telangana_preview_s11`: 590 embeddings. Original `chroma_telangana_preview`: 586, byte-identical before and after (read only via read-only SQLite).
- Hashes (first 16): benchmark `80061e7544d95ef8`, review CSV `e6ddfdd8a1857fd6`, references `31dd5e8faa56f7ab`, manifest `c850b3c745f9a6cf`, flags `4f3833d702c69d6a` (branch and main checkout identical), chapter 5 source `61f019808cb69abb`.

## B. Generation
- **Reused** `backend/review_import.py build_references` unchanged: `python3 -m backend.review_import build-refs --db-dir <copy of _s11> --out <scratch file>`.
- **Run against copies**, because Chroma rewrites `chroma.sqlite3` on open. The copy's document set hashes identical to `_s11` (`72e4cf91be15…`, read-only SQLite).
- **Reproducible:** two runs on two separate copies gave byte-identical output (`2e06f8ed2608a281…`). The output contains no timestamp; generation time is recorded in the diff JSON.
- Source commits `14450cf`, `f944466`. No parser, chunking, embedding or retrieval setting was touched.

## C. Verification (all pass)
| Check | Result |
|---|---|
| Old / new reference count | 586 / 590 |
| Every reference resolves to a real `_s11` chunk; every chunk has one reference | yes / yes |
| References unique; format and keys identical to the old file | yes / yes |
| All fields (document, provision, part, location, document sha256, text sha256, answer_eligible) match index metadata | 590/590 |
| Unaffected old references present and identical | 578/578 |
| Duplicate chunk ID | unchanged: `go-ms-53-2025-trb::SCHEDULE::part1of1` (two distinct refs) |
| Answer-eligible | 572 → 576 (the 4 net new chunks) |

**Identities**
| Provision | Old | New |
|---|---|---|
| TMVR 185 | 6 parts, `#57`, `#57..#58`, `#58` | **5 parts, all `#57`**, no `186 (1)` or "luxury tourist cab" text |
| TMVR 186 | absent | **2 parts, `#58`**; part 1 body starts `186 (1)`; no Rule 185 heading text |
| TMVR 187, 188 | `#59`, `#60` | unchanged |
| TMVR 295 / 295A | 295 only (`#168`, with 295-A folded in) | 295 `#168`, **295A `#169`** |
| TMVTR 12A | 1 part, `#13..#14` (12-B and 13 folded in) | 1 part, `#13`; contains no `12-B` text |
| TMVTR 12B | absent | **own provision**, body starts `12-B : -`, location `#13` |
| TMVTR 13 | absent | own provision, `#14` |

- **12-B is not mapped to 12-A.** It has its own provision ID and text hash. It shares **location** `#13` with 12-A because the source gives 12-B no anchor; that limitation is unchanged and recorded in the diff JSON.

**Differences:** 8 removed, 12 added, 0 changed in place. All fall in seven provisions, each explained by the Stage 9 parser fix (185, 186, 295, 295A, 12A, 12B, 13). **Unexplained differences: none.**

## D. Proposed corrections
**`guard_control` checked in code, not by name** (`backend/retrieval_eval.py:104–106`):
- The guard set is `outcome == "missing_provision"` **or** `category == "guard_control"`. A row is correct iff `guard_blocked == (outcome == "missing_provision")`.
- So `guard_control` + `retrieve` means "the guard must **not** block", and the row is also scored for retrieval. This is pinned by `tests/test_retrieval_eval.py:29`, and the four existing `guard_control` rows use exactly this shape.
- Guard set after the patch: TG-MP-006…008 (must block) + TG-GC-001…004 and the five corrected rows (must not block) = 12.

**TG-MP-004 coverage:** every one of the 102 retrieve-provisions in the benchmark lists **all** of its parts, including multi-rule TG-MR-005 (Rule 486, 3 parts). Listing all 5 Rule 185 parts follows the benchmark's own convention; listing a subset would be the exception.

**Benchmark changes** (full values in the patch JSON)
| Row | Fields changed | Proposed |
|---|---|---|
| TG-MP-001, 002, 003 | category, outcome, documents, provisions, chunks, answer_eligible, behaviour, notes | `guard_control`, `retrieve`, Rule 186 parts 1–2 of 2 |
| TG-MP-004 | same | Rules 185 (5 parts), 186 (2), 187 (1): 8 chunks |
| TG-MP-005 | same | Rules 186 (2), 188 (1): 3 chunks |
| TG-GC-002 | `expected_chunks` only | Rule 185 parts 1–5 of 5, all `#57` |

- `source_passage` is the first 240 characters of each chunk body, the convention verified on TG-GC-001.
- `notes` keeps the Stage 10 text and appends a Stage 13 sentence stating the change is a machine-candidate proposal, not legally verified.
- **Preserved on all six:** `label_source = machine_candidate`, `reviewer_status = pending_human_review`, `reviewed_by` and `reviewed_on` null.

**Review CSV changes**
| Row | Columns changed |
|---|---|
| TG-MP-001…005 | `category`, `machine_expected_outcome`, `machine_expected_provisions`, `machine_expected_locations`, `machine_supporting_passage` |
| TG-GC-002 | `machine_expected_locations`, `machine_supporting_passage` |

- Formats inferred from the file and matched on 108/108 rows: locations `doc :: provision (location)` joined by `; `; passages `source_passage.strip()` joined by `\n---\n`.
- **Not regenerated** (stale old-index run output): `machine_retrieved_top5`, `machine_retrieval_result`, `machine_first_relevant_rank`, `machine_recall_at_5` (D7). The drift check does not compare them.
- All human and reviewer columns unchanged. Only these 6 rows differ (row-by-row comparison).

## E. Would `review_import` accept it? (dry-run, scratch copies only)
| State | `validate` |
|---|---|
| Current benchmark + current CSV + candidate references | OK, 0 errors |
| Proposed benchmark + proposed CSV + candidate references | **OK, 0 errors**; every expected chunk resolves to exactly one reference |
| Proposed benchmark + **current** CSV | **15 errors**: category, outcome and provisions drift on TG-MP-001…005 |
| Proposed benchmark + proposed CSV + **old** references | OK, but only because no row is reviewed |

- **Caveat:** with 0 reviewed rows, `validate` never runs the provision-existence check. Whether a reviewer can name Rule 186 was checked directly: it is answer-eligible in the candidate references and absent from the live ones.
- `validate` also never checks that benchmark `expected_chunks` resolve. Today's TG-GC-002 chunks do not resolve against the candidate, and only the unit test at line 78 catches that.
- The live CLI `validate eval/telangana-retrieval-review.csv` still reports OK: 0 reviewed, 108 unreviewed, 0 errors.

## Integrity
- **Tests:** `python3 -m unittest discover -s tests` passed, 623 tests (repo state after restoring the live references).
- **No changes to:** sources, manifest, flags, the original index or approval records.
- **Not run:** `reconcile`. No commits and no network calls.
- **New files only:** the four listed above plus this report. Proposed benchmark/CSV exist only in scratch; their hashes are in the patch JSON.

## Decisions requiring human approval
| # | Decision | Recommendation |
|---|---|---|
| D1 | Install the candidate references | Yes, **in the same commit** as P6 and the test-count update |
| D2 | `guard_control` for TG-MP-001…005 | Yes; the code confirms "must not block" semantics |
| D3 | Keep `label_source = machine_candidate` | Yes |
| D4 | TG-MP-004 lists all 5 Rule 185 parts | Yes; it is the benchmark's existing convention |
| D5 | Hand-edit the 6 CSV rows with the benchmark | Yes, exactly as in the patch JSON |
| D6 | Approve, reject or defer P1–P6 individually | Each needs your explicit yes |
| D7 | The four stale run columns | Leave them, or regenerate from a Stage 11 run |
| D8 | Update `tests/test_review_import.py:59–60` to 590/576 | Needed if D1 is approved |

Legal questions remain open and are **not** settled by any of this: whether "186" is the correct number, whether the motor-cab conditions in Rule 186 part 2 belong to it, the 12-B numbering and anchor, and whether any snapshot rule is current.
