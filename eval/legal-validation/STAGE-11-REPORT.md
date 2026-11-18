# Stage 11: committed fixes, separate preview rebuild, retrieval validation

Technical verification only. **Nothing here is legal verification.** Retrieving a provision under the right identity says nothing about whether its text is legally current.

| State | Rule 186 / 295-A / TMVTR 12-B / TMVTR 13 |
|---|---|
| Present in the source snapshot | yes (Stage 8) |
| Correctly parsed | yes, at commit `14450cf` |
| Indexed under its own identity | **yes, in `chroma_telangana_preview_s11`**; still no in the original `chroma_telangana_preview` |
| Retrieved under its own identity | yes, rank 1 for a question naming it (section 4) |
| Legally current | **unknown**, not verified |

## 1. Commits (branch `feature/telangana-assistant`, not pushed)
| Commit | Files | Content |
|---|---|---|
| `14450cf` Recognise rule headings printed without a full stop after the number | `backend/tg_ingest.py` (+20), `tests/test_tg_ingest_headings.py` (new, 142 lines) | The Stage 9 parser fallback and its 15 tests |
| `f944466` Correct stale Rule 186 absence claims in preview metadata | `docs/legal-sources/telangana-traffic/DRAFT-telangana-manifest.json` (new to git), `docs/legal-sources/telangana-traffic/PREVIEW-CHUNK-FLAGS.json` (new to git), `eval/telangana-retrieval-benchmark.json` (±5 lines) | The Stage 10 corrections |

- **Pre-commit checks**
  - The tracked diff was only the two intended files.
  - JSON comparison of the benchmark against HEAD: only `cases[TG-MP-001…005].notes` changed. The labels, statuses and reviewer fields are unchanged.
  - Secret and personal-data scan of all 5 files (key patterns, `password`, `secret`, private keys, email, home path): no hits. The only matches were "Secretary" in pre-existing legal text.
- **Manifest and flags had never been in git.** They existed only, untracked, in the main checkout (`KnowYourRules-repo`, branch `main`).
  - By the user's choice, byte-identical copies were added to this branch at the same relative path. Their hashes match the main-checkout files (section 8).
  - The main checkout's copies were not touched. Source documents remain untracked.
  - The pre-correction originals are in `eval/legal-validation/stage-10-originals/` (untracked).
- **Each commit verified independently.** Fresh clones checked out at `14450cf` and at `f944466` each pass `python3 -m unittest discover -s tests`: 610 tests OK. The 13 `source_compare` tests are untracked, which is why 610 rather than 623.
- **Working tree after the commits:** nothing staged or modified. The untracked files are the same as before Stage 11 (`backend/source_compare.py`, `tests/test_source_compare.py`, `eval/legal-validation/`), plus the new index directory.

## 2. New preview index
- **Location:** `chroma_telangana_preview_s11/`, in the `KnowYourRules-tg` worktree. It is untracked; `.gitignore` covers only `chroma_telangana_preview/`.
- **Command** (built at HEAD `f944466`; the parser comes from `14450cf`, the metadata from `f944466`):
  ```bash
  python3 -m backend.build_telangana_index \
    --manifest docs/legal-sources/telangana-traffic/DRAFT-telangana-manifest.json \
    --corpus ../KnowYourRules-repo/docs/legal-sources/telangana-traffic/source-documents \
    --chunk-flags docs/legal-sources/telangana-traffic/PREVIEW-CHUNK-FLAGS.json \
    --preview-unapproved --db-dir chroma_telangana_preview_s11
  ```
  Output: "Done. Indexed 590 provision chunks from 20 documents into telangana-traffic-rules."
- **Configuration**, unchanged from the original index:
  - collection `telangana-traffic-rules`, `rag_profile=structured`, 768 dimensions;
  - embeddings from Ollama `nomic-embed-text:latest`, digest `0a109f422b47`, Ollama 0.40.16;
  - chromadb 1.5.9, langchain-chroma 0.2.6, langchain-ollama 0.3.10;
  - no approval record (`--preview-unapproved`). The production directory `chroma_telangana_db` does not exist and was not created.
- **Ollama** was not running. I started `ollama serve` on 127.0.0.1 for the build and evaluation and stopped it afterwards. It handled only local embedding calls: no network access and no Groq calls (`model_calls: {}` in every run).
- **Exact reproduction:** `build_telangana_index.prepare()` at `f944466`, run in memory, gives 590 chunks. Their text and metadata are **identical** to the 590 stored chunks.

## 3. Chunk counts
| | Original `chroma_telangana_preview` | New `chroma_telangana_preview_s11` |
|---|---|---|
| Chunks | 586 | **590** |
| Distinct provisions | 557 | 561 |
| `answer_eligible` true / false | 572 / 14 | 576 / 14 |

- **Added provisions:** `tmvr-1989-chap-5::Rule 186`, `Rule 295A`, `tmvtr-1963::Rule 12B`, `Rule 13`. **None removed.**
- **Re-split:** Rule 185 went from 6 parts to 5.
- **Chunk text:** 578 chunks identical; 8 only in the old index, 12 only in the new.
- **Source text conservation**, comparing body lines with each chunk's header line excluded:
  - `tmvr-1989-chap-5`: 1089 = 1089 lines, identical multisets.
  - `tmvtr-1963`: 76 = 76, identical.
  - All other documents are unchanged.
- **Every text difference is a chunk header line** ("Rule 185 … (part 1 of 6)" → "(part 1 of 5)", plus the new headers). No source text was lost or invented.

## 4. Provision identity checks (new index)
- **Common to all seven checks:**
  - "Retrievable" means the server's own `retrieve()` (hybrid) against the new index, with a question naming the rule. All seven ranked **1**.
  - "Guard" is `missing_references()`. It reports nothing missing for all seven.
  - All chunks are `provision_kind=Rule`, `answer_eligible=true`, `source_class=unverified_snapshot`.
  - TMVR source sha256 is `61f019808cb6…` (`middle-main-chap-5.htm`); TMVTR is `d7f805041083…` (`middle-ap-mv-tr-1963-main.htm`).

| Provision | Chunks | Location (citation) | Heading | Chunk text sha256 (first 12) | Warning |
|---|---|---|---|---|---|
| TMVR Rule 185 | 5 | `chap-5.htm#57` | Conditions to be attached to all permits | d3983dc072e7, f99eeea5bd26, a0a39109a2f6, 0e65139cd7e9, f471b970181e | none |
| TMVR Rule 186 | 2 | `chap-5.htm#58` | Conditions of permit in respect of a luxury tourist cab | 58de60d02a3e, 785b6a9952ec | identity note (section 5) |
| TMVR Rule 295 | 1 | `chap-5.htm#168` | Painting of goods Carriages | d813bdfb3698 | none |
| TMVR Rule 295A | 1 | `chap-5.htm#169` | Painting of goods carriages carrying dangerous or hazardous goods | bab6036d093e | none |
| TMVTR Rule 12A | 1 | `tr-1963-main.htm#13` | Liability for payment of tax in respect of motor vehicles kept for use | 89becb3d8581 | none |
| TMVTR Rule 12B | 1 | `tr-1963-main.htm#13` | "" (the source prints none; none invented) | 2d44ad670367 | none |
| TMVTR Rule 13 | 1 | `tr-1963-main.htm#14` | Rates of penalty | 9e167b924552 | none |

- **Each provision's text starts at its own heading:**
  - `185. Conditions…`
  - `186 (1) Conditions of permit i…`
  - `295. Painting…`
  - `295-A . Painting…`
  - `12-A. Liability…`
  - `12-B : - Whereby a notification…`
  - `13 Rates of penalty : -…`
- **Rule 185 no longer contains Rule 186 text.** Neither "186 (1)" nor "luxury tourist cab" appears in any Rule 185 part. In the old index both did.
- **Rule 186 is no longer reported missing.** For "Explain TMVR Rule 186" the guard reports `[]`; the old index reported `['Rule 186']`.
- **TMVTR Rule 13 is no longer reported missing.** For "Explain Rule 13 of the Telangana Motor Vehicles Taxation Rules" the guard reports `[]`; the old index reported `['Rule 13']`.
- **Old index, same questions:** 186, 295A, 12B and 13 had 0 chunks and were all reported missing.
- **Citation precision limit (not an identity error):** 12-B cites `#13`, the anchor of 12-A, because the source has no anchor at 12-B (source line 164: `12-B :`, with no `<a name>`). The location is the nearest preceding anchor, as for every block.

## 5. Reviewer-warning checks (old vs new, by chunk)
| Warning | Old chunks | New chunks | Same chunks? |
|---|---|---|---|
| "Missing source: rule 186 is listed … absent …" (false) | 7 (Rule 185 ×6, Rule 187 ×1) | **0** | removed as intended |
| Rule 186 identity note | 0 | **2** (Rule 186 parts 1 and 2 only) | new as intended |
| G.O. 24/2026 draft/final status unresolved | 8 | 8 | yes |
| G.O. 53/2025 rate-table extraction unreliable | 5 | 5 | yes |
| G.O. 53/2025 pages 4–5 continue the Seventh Schedule | 2 | 2 | yes |
| G.O. 16/2026 amends G.O. 53's Seventh Schedule | 1 | 1 | yes |
| G.O. 53 superseded in part by G.O. 16/2026 | 1 | 1 | yes |
| TMVR rule 375 contents/body discrepancy | 1 | 1 | yes |

- Rules 185, 187, 295, 295A, 12A, 12B and 13 carry no warning.
- **The six unrelated warnings are on exactly the same chunks.**
- The 14 answer-ineligible chunks are the same 14.

## 6. Rule 81 safety (not fixed; observations only)
- **The old Rule 81 is still identifiable.**
  - It is `tmvr-1989-chap-4::Rule 81`, 2 parts, at `middle-main-chap-4.htm#4`, with text hashes `abaa416613ce…` and `e05120958e15…`.
  - It is unchanged from the original index; `chap-4` is byte-identical.
  - It still contains sub-rules (1), (2) and (4) and the Rs.50,000 figure.
- **G.O. 77/2025 is separately identifiable.** It is `go-ms-77-2025-trb`: Preamble, References, Order, Paragraphs 2 and 4, and Paragraph 3 in 2 parts. Rs.1,50,000 appears in Paragraph 3.
- **What the system does and doesn't claim:**
  - Every chunk carries `verification_status=unverified`. Rule 81 is `source_class=unverified_snapshot`. `effective_date` is empty everywhere.
  - `describe_source()` labels both as "Unverified source - title and instrument type not verified".
  - Nothing marks Rule 81 as current.
  - **But nothing marks it as amended either.** It has no `extraction_warning`, no `amended_by` metadata, and stays `answer_eligible=true`.
- **The versioning problem is still open.**
  - "What are the fees under TMVR Rule 81?" ranks G.O. 77 Paragraph 3 first and the stale Rule 81 second.
  - TG-GO-007 ranks the stale Rule 81 **first**.
  - An answer could quote the omitted sub-rules or the Rs.50,000 fees as if in force. The Stage 8 amendment-register proposal remains the fix.
  - No effective date has been assumed. G.O. 77 alone is not treated as enough to reconstruct the current Rule 81.

## 7. Benchmark retrieval comparison
- **Machine-readable results:** [`stage-11-retrieval-comparison.json`](stage-11-retrieval-comparison.json).
- **Run setup:**
  - `python3 -m backend.retrieval_eval --db-dir <dir>` in hybrid mode, all 108 cases, labels unchanged.
  - "Before" is a byte copy of `chroma_telangana_preview`, because Chroma writes to a directory when the server opens it.

**Aggregates:**

| Metric | Before | After |
|---|---|---|
| Scored cases | 74 | 74 |
| hit@5 / recall@5 / MRR | 1.000 / 0.953 / 0.873 | 1.000 / 0.953 / 0.873 |
| Guard accuracy (benchmark labels) | 12/12 | **7/12** |
| Excluded chunks leaked | 0 | 0 |
| Penalty locked | 6/6 | 6/6 |
| Model calls | 0 | 0 |

- **The guard-accuracy drop is the five TG-MP rows only**, whose labels still say `missing_provision`. Measured against the corrected identity, all five now pass. The drop is label debt, not a regression, and labels were not changed.

**The ten questions in focus** (expected = the existing benchmark label):

| Row | Expected | Top 5 after | Correct identity | Benchmark pass before → after | Failure type | Outdated-source risk | Label needs human review |
|---|---|---|---|---|---|---|---|
| TG-MP-001 "What does Rule 186 say?" | missing_provision | **186**, 188, GO25 Preamble, 183, GO25 References | Rule 186, at rank 1 | pass → **fail** | before: missing source (parser); now none | currency unknown | **yes**: retrieve Rule 186 |
| TG-MP-002 "Explain TMVR rule 186." | missing_provision | **186**, 188, GO25 Preamble, 181, GO25 References | Rule 186, at rank 1 | pass → **fail** | same | unknown | **yes**: retrieve Rule 186 |
| TG-MP-003 conditions in Rule 186 | missing_provision | **186**, 185, 188, 187 | Rule 186, at rank 1 | pass → **fail** | same | unknown | **yes**: retrieve Rule 186 |
| TG-MP-004 compare 185, 186, 187 | missing_provision | 185, 187, **186** | Rules 185–187, all in the top 3 | pass → **fail** | same | unknown | **yes**: Rules 185, 186, 187 |
| TG-MP-005 rules 186 and 188 | missing_provision | 188, **186**, 217, 217A, chap-3 67 | Rules 186 and 188, at ranks 1–2 | pass → **fail** | same | unknown | **yes**: Rules 186, 188 |
| TG-GC-002 "What does Rule 185 say?" | retrieve Rule 185 | 185, 235 | Rule 185, at rank 1 | pass → pass | none at provision level | unknown | **yes**: `expected_chunks` name `part1of6…part6of6`, but only 5 parts exist (`part6of6` was Rule 186 text) |
| TG-PN-005 fine under Rule 186 | restricted | 186, TMVTR 17, 288A, 217A, 216 | Rule 186 | pass → pass (penalty lock; the guard no longer also blocks) | none | unknown | no: `restricted` is still right |
| TG-GO-007 G.O. that amended Rule 81 | GO77 Order, Paras 2, 3, 4 | **stale Rule 81**, GO77 Order, Para 4, Para 3 | GO77 Order, Paras 2, 3 | pass → pass (unchanged) | ranking: Para 2 not in the top 5 | **HIGH**: stale Rule 81 ranked 1st | yes: over-broad (REVIEW-BATCH-01) |
| TG-MR-008 medical certificates | Rules 43, 77 | 337, **43**, 239, 47, 76 | Rules 43, 77 | hit → hit, recall 0.5 (unchanged) | **ranking**: Rule 77 is indexed but not in the top 5 | unknown | no (label correct) |
| TG-GO-003 who certifies speed cameras | GO32 Para 4, Order, Para 5 | GO32 Para 3, Preamble, **Para 4**, **Para 5**, Para 6 | GO32 Para 4 | hit → hit (unchanged) | Order not in the top 5 (label over-broad) | unknown; central CMVR r.167/167A outside the corpus | yes: over-broad (REVIEW-BATCH-01) |

**Other rows whose top 5 changed** (10, all side effects of the four new chunks):
- **Retrieve rows, no loss of expected provisions:**
  - DL-013: rank order only.
  - DL-025: 295A replaces 295 at rank 5.
  - MR-006: Rule 186 added.
  - GO-002: Rule 186 replaces GO77 Para 3, which was not expected.
- **`excluded_no_context` rows EX-004, EX-005 and EX-007:** TMVTR 12B or 13 enter the top 5. Leakage is still 0.
- **PN-002 (restricted):** TMVTR 13 enters the top 5; it stays locked.
- **OS-001 and OS-006 (out of scope):** these rows retrieved 5 provisions before and still do. Abstention is unchanged.
- **The other 88 rows are identical.**

## 8. SHA-256 and integrity
- **98 protected files hashed before and after:**
  - the original index directory;
  - the main checkout's `docs/legal-sources/telangana-traffic/` (57 sources, manifest, flags and reviewer documents);
  - the review CSV, chunk references and benchmark;
  - `eval/legal-validation/`;
  - the branch's `docs/legal-sources/`.

  **The only difference is the new `stage-11-retrieval-comparison.json`.** This report was written after the hash run.
- **Key hashes:**

| File | sha256 |
|---|---|
| `chroma_telangana_preview/chroma.sqlite3` (original, untouched) | `1950d5b3f781c4e73e50b354b19c285463134ee890dd2018a71a6efb4811457d` |
| `eval/telangana-retrieval-review.csv` (untouched) | `e6ddfdd8a1857fd6f1204a697485f5463229764d054607d2c8100d8ac82245d1` |
| `eval/telangana-chunk-references.json` (untouched, now stale) | `31dd5e8faa56f7ab4980de91278672c2c3dacb6176ecc78058e2ca8cc96fb8b7` |
| `DRAFT-telangana-manifest.json` (branch = main checkout) | `c850b3c745f9a6cf6d6d4323958986a3f38ed9e715849576ace5b1b29f64657d` |
| `PREVIEW-CHUNK-FLAGS.json` (branch = main checkout) | `4f3833d702c69d6aebcb3fe8daaa157b85f28aa7d6fd11429c123816a679550d` |
| `backend/tg_ingest.py` @ `14450cf` | `7d1157fb669cf5365b26052379e19cd4755eed8a2624d993262d52685f681fc6` |
| `chroma_telangana_preview_s11/chroma.sqlite3`, right after build | `68e8abc0994a3a8db437c4dcac0c36e1953db1011a06a6dc4b6414e442e8473c` |
| same, after the evaluation opened it | `35ab530f7cd366050602eb379a15db26055df9158b18988087d9da55613e2a34` |

- **The new index's files changed when the server opened it**: `chroma.sqlite3` and `data_level0.bin` were rewritten by Chroma.
  - A re-read after the evaluation still gives 590 chunks.
  - Its contents are still identical to the in-memory build from `f944466`.
  - So byte hashes of a Chroma directory only identify it until something opens it. The content check is the reliable identity.
- **Sources:** `shasum -c SHA256SUMS` gives 57/57 OK.

## 9. Tests
- **Worktree:** `python3 -m unittest discover -s tests` gives **623 tests, OK**, before the commits and again after the build.
- **Clean clones:** at `14450cf`, 610 OK; at `f944466`, 610 OK (the untracked `source_compare` tests are absent there).

## 10. Remaining blockers and next step
- **Before any further step, four blockers remain:**
  - **Benchmark labels are stale.** TG-MP-001…005 (`missing_provision`) and TG-GC-002 (`expected_chunks`) need human approval through `review_import`. The proposals are in STAGE-10-REPORT.md section 6 and in the comparison JSON. Until they are approved, guard accuracy reads 7/12 on a correct index.
  - **`eval/telangana-chunk-references.json` is stale.** It still lists Rule 185 `part6of6`. It needs regenerating from the new index after the labels are approved.
  - **Rule 81 versioning is open.** The stale text is answer-eligible, unwarned, and ranked first for TG-GO-007.
  - **No legal verification yet.** That covers the numbering of the four rules, 12-B's missing title, and the currency of every snapshot rule.
- **Other issues, unchanged since REVIEW-BATCH-01:**
  - ranking misses on TG-MR-008 (Rule 77) and TG-GO-007 (Paragraph 2);
  - pipe artifacts in G.O. text.
- **The original `chroma_telangana_preview` is still the default.** `retrieval_eval` and the server use it unless `TG_DB_DIR` or `--db-dir` points at `chroma_telangana_preview_s11`. Nothing was switched over.
- **Recommended next step:**
  1. A human reviews and approves the TG-MP-001…005 and TG-GC-002 label proposals through `review_import`.
  2. Regenerate the chunk references against `chroma_telangana_preview_s11`.
  3. Re-run this evaluation, where the guard should be 12/12.
  4. Decide whether `_s11` replaces the original preview.

  The Rule 81 amendment register (STAGE-08 proposal) is a separate stage.

## Exactly what changed
- **Committed:**
  - `14450cf`: `backend/tg_ingest.py`, `tests/test_tg_ingest_headings.py`.
  - `f944466`: the branch copies of `DRAFT-telangana-manifest.json` and `PREVIEW-CHUNK-FLAGS.json`, plus `eval/telangana-retrieval-benchmark.json` (notes only).
  - Not pushed.
- **Rebuilt:** nothing was rebuilt in place. A new directory, `chroma_telangana_preview_s11/`, was built (untracked, about 10 MB).
- **Created, untracked:** `eval/legal-validation/STAGE-11-REPORT.md` and `eval/legal-validation/stage-11-retrieval-comparison.json`.
- **Untouched:**
  - the original `chroma_telangana_preview/`;
  - all 57 official source files and `SHA256SUMS`;
  - the main checkout's manifest, flags and reviewer documents;
  - `eval/telangana-retrieval-review.csv` and `eval/telangana-chunk-references.json`;
  - benchmark labels, statuses and approval records;
  - Rule 81 data;
  - retrieval, generation and validator code;
  - Stage 7–10 reports and `stage-10-originals/`.
- **Not run:** `review_import`, any Groq or network call, any push.
