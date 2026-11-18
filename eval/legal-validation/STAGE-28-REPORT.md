# Stage 28: chapter context for TMVR snapshot chunks (TG-PQ-017)

**Result:** Rule 455 now ranks 5th for TG-PQ-017 (it was not in the list at all), in both exact and HNSW modes.
- **Metrics:** recall@5 and hit@5 are unchanged and recall@3 rises (0.9040 → 0.9135). recall@1 (−0.0063) and MRR (−0.0042) fall slightly.
- **Trade-off:** TG-MR-007's Rule 37 slips from rank 5 to rank 6.
- **Needs a rebuild:** the effect requires rebuilding the index. I built and evaluated candidates only in the scratchpad; the preview index is unchanged.
- **Nothing special-cased:** no rule, question or wording is hardcoded.

## 1. Root cause
Question: "How do I apply for accident compensation before the Claims Tribunal?" It expects Rules 476 and 455 (TMVR chapter XI).

**Rule 455's chunk is terse and has no subject context.**
- The whole chunk reads: "455. Applications:- Every application for payment of compensation made under Section 166 shall be made in Form C.I.D. …"
- It never says *claim*, *tribunal* or *accident*. That context lives only in the chapter title, "Chapter-XI (Claims Tribunals - Establishment of)".

**The chapter title never reaches the index.**
- The TMVR snapshot pages (`middle-main-chap-N.htm`) have no chapter heading, so `segment()` leaves `chapter` empty. That is true of all 590 indexed chunks.
- The titles exist only in the snapshot's own `index.html` table of contents.

**Measured on a copy of the preview index:**

| Signal | Rule 455 rank | Notes |
|---|---|---|
| Vector (exact) | 14 (distance 0.6671) | The top 6 are other chapter XI rules |
| BM25 | 28 | Matches only `compensation`. The query has `apply`, the text has `application`; `claim` and `tribunal` are absent |
| Structured lookup | – | The question names no rule |
| Fusion (top 6 per list) | not retrieved | Neither list reaches it |

## 2. Approaches compared
All 108 questions, exact mode, scratchpad copies only. Baseline = Stage 17, reproduced exactly (same 108 lists as `stage-17-retrieval-comparison.json`).

| Approach | Rule 455 | recall@1 | recall@3 | recall@5 | MRR |
|---|---|---|---|---|---|
| Baseline (Stage 17) | – | 0.7046 | 0.9040 | 0.9726 | 0.8907 |
| Chapter title added to BM25 text only | – | 0.7046 | 0.9167 | 0.9662 | 0.8918 |
| General `-ication` → `-y` fold (apply ↔ application) | – | 0.7046 | 0.9040 | 0.9684 | 0.8928 |
| Both of the above | – | 0.7046 | 0.9167 | 0.9620 | 0.8939 |
| Fusing 20 candidates per list (with or without context) | – | 0.6920 | ≤0.8914 | ≤0.9620 | ≤0.8791 |
| Chapter in chunk header (embedding **and** BM25) | 5 | 0.6920 | 0.9262 | 0.9726 | 0.8812 |
| **Chapter in chunk header, BM25 without it (chosen)** | **5** | **0.6983** | **0.9135** | **0.9726** | **0.8865** |

- **Lexical-only changes cannot fix TG-PQ-017.** Even combined, Rule 455 reaches only BM25 rank 7, and the vector rank stays at 14.
- **Chapter context in the embedded text fixes it.**
- **As BM25 terms, chapter titles hurt.** A title is shared by every chunk in its chapter, so words like "drivers" and "conductors" lift whole chapters. That cost TG-MR-007 its Rule 37 entirely, and dropped TG-MR-008's Rule 43 from rank 1 to 3.
- **Not chosen:**
  - Query expansion or synonym lists: these need domain word lists, which risk special-casing.
  - A concept-matching layer: a new component, larger than the evidence supports.

## 3. Implementation
- **`backend/tg_ingest.py`**
  - New `snapshot_chapter(corpus_dir, rel_file)`. For `middle-main-chap-N.htm`, it reads the snapshot's `index.html` and returns the "Chapter-<N in Roman numerals> ( title )" entry, formatted like a heading found in the text: `CHAPTER XI CLAIMS TRIBUNALS - ESTABLISHMENT OF`.
  - It returns `""` when the file is not such a page, there is no table of contents, or no entry has the matching number.
  - `chunk_document(blocks, entry, default_chapter="")` applies the default only to provisions with no chapter heading in their text.
- **`backend/build_telangana_index.py`:** `prepare()` passes `snapshot_chapter(...)` to `chunk_document`.
- **`backend/hybrid_retrieval.py`:** new `lexical_text(doc)` removes the chapter label from the header line before BM25 tokenisation. Stored text and metadata are unchanged.
- **Unchanged:** exact vector search and the HNSW fallback, squared L2, `RETRIEVE_K`, RRF, BM25 parameters, plural folding, structured lookup, eligibility filters, and the API.

**Effect on a rebuilt index**, compared with a control rebuild that reproduces the preview index's lists exactly:
- The same 590 chunk identities, body text and eligibility.
- Only the header line and the `chapter` metadata change, on the 527 TMVR chunks. No other document changes.
- The source-status registry stays valid against the candidate, and both Rule 81 chunks stay `known_amendments_unresolved`.

## 4. Benchmark comparison
All 108 questions; 79 scored. Record: `stage-28-evaluation.json`.

| Metric | Stage 17 exact | Stage 28 exact | Stage 17 HNSW | Stage 28 HNSW |
|---|---|---|---|---|
| hit@5 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| recall@1 | 0.7046 | 0.6983 | 0.7046 | 0.6983 |
| recall@3 | 0.9040 | 0.9135 | 0.9040 | 0.9135 |
| recall@5 | 0.9726 | 0.9726 | 0.9726 | 0.9726 |
| precision@5 | 0.2608 | 0.2608 | 0.2608 | 0.2608 |
| MRR | 0.8907 | 0.8865 | 0.8907 | 0.8865 |

- Guard 12/12, excluded chunks retrieved 0, model calls 0 in every run.
- A repeat on a fresh copy gave identical lists.
- 61 lists changed in exact mode and 60 in HNSW mode, mostly lower-ranked filler. The full lists are in the record.

**Expected-provision rank changes (identical in exact and HNSW)**

| Question | Change | |
|---|---|---|
| TG-PQ-017 | Rule 455: – → 5 | **fixed** (target) |
| TG-PQ-003 | Rule 18: 4 → 3 | better |
| TG-MR-004 | Rule 448A: 1 → 2, Rule 448B: 2 → 1 | swap, both top 2 |
| TG-MR-008 | Rule 77: 2 → 1, Rule 43: 1 → 3 | swap, both top 3 |
| TG-GO-003 | Paragraph 5: 4 → 2, Paragraph 4: 3 → 4 | mixed, both top 4 |
| TG-PQ-002 | Rule 14: 3 → 4 | worse, still top 5 |
| TG-PQ-007 | Rule 484: 1 → 2 | worse, still top 2 |
| TG-MR-007 | Rule 37: 5 → 6 | **worse: leaves the top 5** (still retrieved, rank 6) |

recall@5 gaps: before, TG-PQ-002, **TG-PQ-017**, TG-GO-007 and TG-GO-012; after, TG-PQ-002, **TG-MR-007**, TG-GO-007 and TG-GO-012.

## 5. Tests
- **New `tests/test_chapter_context.py`** (14 tests):
  - `snapshot_chapter`: table of contents, never guessed, Roman numerals.
  - Chunk header and metadata, with unchanged chunk identities and body.
  - A chapter heading in the text wins over the default.
  - `prepare()` labels snapshot pages without writing an index.
  - `lexical_text` and BM25 ignore chapter words.
  - Recorded regression (TG-PQ-017 in the top 5; no hit@5, recall@5, guard or leakage regression; no expected provision lost from the list; exact and HNSW agree).
  - Mutation checks: removing the BM25 exclusion, or the ingest default, makes the relevant tests fail.
- **`tests/test_tg_ingest.py`:** one stub (`mislabelled`) now passes through the new optional argument; its assertions are unchanged. Backup in `stage-28-originals/`.
- **Full suite:** 735 OK in exact mode and 735 OK in HNSW mode (721 + 14). Checksums: 63/63.

## 6. Limitations
- **Needs an approved rebuild.** The live and preview indexes still have empty chapters, so the improvement appears only after the next approved rebuild. I did not rebuild or replace any index.
- **Not a free win:**
  - It trades TG-MR-007 (Rule 37 now at rank 6) for TG-PQ-017.
  - recall@1 and MRR fall slightly.
  - recall@3 and the target question improve.
- **Overfitting risk:** leaving the chapter out of BM25 was chosen after comparing two variants on this same benchmark. Both use the same source data and neither is tuned per question, but a held-out set would be needed to confirm it generalises.
- **Coverage:** only TMVR snapshot pages get chapters, because that is the only snapshot with a table of contents. PDFs already take chapter headings from their text.
- **Still failing recall@5:** TG-PQ-002, TG-GO-007 and TG-GO-012, unchanged.
- **The recorded regression tests read `stage-28-evaluation.json`** (untracked). They skip without it, or fail under `KYR_REQUIRE_LEGAL_DATA=1`.

## Constraints
- **Not changed:** source text, the benchmark, labels, the review CSV, chunk references (file SHAs as in Stage 17), the registry (`5a174820…`), Rule 81's warning, and the preview index (byte-identical to the Stage 23 copy).
- No Groq or external calls; embeddings came from local Ollama on 127.0.0.1. Nothing was staged, committed or pushed.
- Earlier uncommitted work (Stages 13–17) is preserved. `stage-28-originals/hybrid_retrieval.py.pre-stage-28` includes the uncommitted Stage 17 change.

## Rollback
```bash
cd /Users/vj/Downloads/KnowYourRules-tg && O=eval/legal-validation/stage-28-originals && cp -p $O/tg_ingest.py.pre-stage-28 backend/tg_ingest.py && cp -p $O/build_telangana_index.py.pre-stage-28 backend/build_telangana_index.py && cp -p $O/hybrid_retrieval.py.pre-stage-28 backend/hybrid_retrieval.py && cp -p $O/test_tg_ingest.py.pre-stage-28 tests/test_tg_ingest.py && rm tests/test_chapter_context.py
```
