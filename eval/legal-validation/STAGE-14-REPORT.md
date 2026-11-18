# Stage 14: corrected references and benchmark integrated, then evaluated

**Applied to the working tree. Nothing is committed or pushed.** These are mechanical benchmark corrections. They are **not** legal approval and do **not** confirm that any provision is currently valid law. No approval record was created, and no reviewer status changed. Machine-readable results: [`stage-14-evaluation.json`](stage-14-evaluation.json).

## Approvals (user's chat message, 11-11-2026)
- **P1–P6:** approved "as mechanical benchmark corrections, not as legal certification or confirmation of current legal validity".
- **D1:** install the Stage 13 candidate references.
- **D7:** regenerate the four review-CSV result columns using the new index.
- **D8:** update the test counts to 590 references and 576 answer-eligible.

## Part A findings
These were recorded before any change; the gate version of this report documented them.
- The candidate has 590 references, 576 of them answer-eligible.
- `test_review_import.py:59–61` pins the old index size: an out-of-date number, but a useful tripwire. Updated, not removed.
- `test_review_import.py:74–78` requires every benchmark chunk to resolve: a real rule. Left unchanged, and it passes.

## Transaction
**1. Pre-checks**
- The live files matched their Stage 13 hashes: references `31dd5e8f…`, benchmark `80061e75…`, CSV `e6ddfdd8…`.
- Rollback copies are in `stage-14-originals/*.pre-stage-14` (the references, benchmark, CSV and `test_review_import.py`).

**2. Installed**
| File | Change |
|---|---|
| `eval/telangana-chunk-references.json` | Stage 13 candidate, byte for byte (`2e06f8ed…`, 590 references) |
| `eval/telangana-retrieval-benchmark.json` | P1–P6 exactly as in `stage-13-proposed-benchmark-patch.json`; only those 6 rows differ |
| `eval/telangana-retrieval-review.csv` | The Stage 13 machine columns for the 6 rows, plus the D7 result columns, which changed on 30 rows |
| `tests/test_review_import.py` | The 3 count pins: 586→590, 572→576, 586→590 |

**3. Guards inside the transaction**
- On all 108 rows, every human and reviewer column, `reviewer_status` and `machine_label_source` were confirmed unchanged.
- `validate` and the full test suite then ran, with automatic restore on failure. Both passed, so **no rollback was needed**.

**4. Preserved on the 6 corrected rows**
- `label_source = machine_candidate`
- `reviewer_status = pending_human_review`
- `reviewed_by` and `reviewed_on` are still null

### How the D7 columns were regenerated
- **No generator exists in the repo**, so I reconstructed the format and checked it against the old index.
  - The result, rank and recall columns reproduce the current CSV on all 108 rows.
  - The top-5 column (`n. doc::provision | first 240 characters, whitespace collapsed`) reproduces 95 of 108 rows.
  - The other 13 list *different documents* rather than differently formatted ones. The CSV was produced by an earlier retriever than the one committed alongside it.
- **The new values come from a copy of `_s11`**, so the index itself was never opened. Mode: hybrid. Retrieval is deterministic: two runs on the old index were identical.
- Every changed cell is in the evaluation JSON (`d7_regenerated_columns`), with its old and new value.

## Part D: new tests (`tests/test_benchmark_integrity.py`, 19 tests)
| Area | Checks |
|---|---|
| Expected provisions | Every one is in the references and answer-eligible; expected chunks cover exactly the expected provisions; every part is listed |
| Chunks that don't resolve | An out-of-date chunk ID (old `Rule 185::part6of6`) resolves to nothing; so does a correct ID at the wrong location; Rule 185 has 5 parts and none at `#58`; Rule 186 has 2 parts |
| Rule 12-B | It is its own provision with its own text and reference, while sharing 12-A's anchor (a known limitation) |
| Duplicates | `build_references` refuses identical chunks (tested with a fake Chroma); a chunk ID shared by different texts is recorded, not merged; the live references are unique |
| Benchmark/CSV mismatch | The live CSV matches the benchmark; a changed outcome or category is detected; **the location and passage columns are checked against the expected chunks**, which `check_template` does not do |
| `guard_control` | Correct only when not blocked; still scored for retrieval; `missing_provision` is correct only when blocked; the benchmark's guard rows are pinned |
| Corrected rows | Still `machine_candidate`, pending review, with no reviewer |

No existing check was weakened. The only edits to existing tests are the three D8 count pins.

## Part E results
- **Tests:** 642 passed (623 existing plus 19 new).
- **`validate`:** OK, 0 reviewed, 108 unreviewed, 0 errors.
- **Questions run:** all 108, on a copy of `_s11`, with 0 model calls and 0 excluded chunks retrieved.

**Retrieval** (only rows expecting `retrieve` that name provisions)
| Run | Scored | hit@5 | recall@5 | MRR | precision@5 |
|---|---|---|---|---|---|
| Stage 11: old index, old labels | 74 | 1.000 | 0.9527 | 0.8732 | 0.2486 |
| Stage 11: `_s11`, old labels | 74 | 1.000 | 0.9527 | 0.8732 | 0.2486 |
| **Stage 14: `_s11`, corrected labels** | **79** | **1.000** | **0.9557** | **0.8749** | **0.2532** |
| Stage 14, the original 74 only | 74 | 1.000 | 0.9527 | 0.8664 | |

**Guard** (reported separately from retrieval)
| Run | Correct |
|---|---|
| Stage 11, old index | 12 / 12 |
| Stage 11, `_s11` with the old labels | 7 / 12 (5 out-of-date "Rule 186 missing" labels) |
| **Stage 14** | **12 / 12**: TG-MP-006, 007 and 008 blocked (Rules 999, 99 and 600); TG-GC-001…004 and TG-MP-001…005 not blocked |

**The corrected rows**
| Row | Result |
|---|---|
| TG-MP-001, 002, 003 | Rule 186 at rank 1, recall 1.0 |
| TG-MP-004 | Rules 185, 187 and 186 at ranks 1–3, recall 1.0 |
| TG-MP-005 | Rules 188 and 186 at ranks 1–2, recall 1.0 |
| TG-GC-002 | Rule 185 at rank 1, recall 1.0 |

**Retrieval misses remaining** (recall@5 below 1, with no complete misses)
| Row | Recall | Note |
|---|---|---|
| TG-PQ-002 | 0.25 | |
| TG-PQ-017 | 0.5 | |
| TG-PQ-021 | 0.5 | |
| **TG-MR-008** | 0.5 | **Kept on record:** Rule 77 is not in the top 5 |
| TG-GO-003 | 0.667 | |
| **TG-GO-007** | 0.75 | **Kept on record:** the outdated `tmvr-1989-chap-4::Rule 81` ranks **first**, is answer-eligible and carries no warning; the G.O. 77/2025 amendment is not modelled |
| TG-GO-012 | 0.333 | |

**Changes against the Stage 11 old-index baseline:** 20 rows, all listed in the JSON.
- The 6 corrected rows.
- New provisions now appear in the top 5: Rule 295A in DL-025 and OS-006, Rule 186 in MR-006 and GO-002, and Rule 13 in EX-004 and PN-002. The other affected rows are EX-005, EX-007, PN-005, OS-002 and DL-013.
- Only TG-PQ-007 changes a score: rank 1→2, still a hit.

**Unexplained run-to-run difference**
- On the same `_s11` content, 4 questions rank differently than in the Stage 11 run: TG-PQ-007, MR-005, OS-001 and OS-002.
- This is behind the original-74 MRR moving from 0.8732 to 0.8664.
- **Hypothesis, not verified:** Stage 12 opened `_s11` in Chroma, which rewrote its search-graph file, and that changes approximate nearest-neighbour results.
- No hit@5 result changes.

## Integrity
- **Unchanged (byte-identical):** both indexes, all source files, the manifest and the flags. This stage used index copies only.
- **Changed:** the 4 files listed in the transaction table, plus new files in `eval/legal-validation/` and `tests/test_benchmark_integrity.py`.
- **Not done:** no Groq calls, network calls, approval records, reviewer-status changes or commits. The local Ollama server I started for embeddings has been stopped.

## Remaining blockers
- **No human review yet:** all 108 rows are `pending_human_review`, and no legal approval record exists.
- **Rule 81 and TG-GO-007:** amendment and currency handling are not implemented.
- **TG-MR-008:** a ranking failure.
- **Rule 12-B:** shares 12-A's citation anchor `#13`.
- **The run-to-run ranking difference** above, which is not yet explained.
- **Not legally verified:** the numbering of Rules 186, 295-A and 12-B and TMVTR Rule 13, and the currency of every snapshot rule.
- **The production index is not replaced:** `_s11` is still a preview.
- **To roll back:** copy `stage-14-originals/*.pre-stage-14` over the four live files.
