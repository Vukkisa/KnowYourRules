# Stage 29: named-chapter ordering (TG-MR-007) on top of Stage 28

**Result:** TG-MR-007's Rule 37 moves from rank 6 to rank 2, and TG-PQ-017 keeps Rule 455 at rank 5, in both exact and HNSW modes.
- **Metrics:** recall@5 rises to 0.9789 (Stage 17 and Stage 28: 0.9726) and recall@3 to 0.9198. hit@5, recall@1 and MRR equal Stage 28.
- **Scope of the change:** it reorders the six chunks already returned for a question; it never adds or drops one. On the benchmark it fires on two questions of 108.
- **Still below Stage 17:** recall@1 (0.6983 vs 0.7046) and MRR (0.8865 vs 0.8907) are unchanged from Stage 28.
- **Needs a rebuild:** chapter metadata is empty in the live and preview indexes, so the change does nothing there. I evaluated on scratchpad copies only.
- **Nothing special-cased:** no question ID, rule number or wording is in the retrieval code.

## 1. How chapter context changes ranking (Stage 28)
- **Documents:** the chapter title is in the header line of each TMVR chunk, so it is part of the embedded text. BM25 reads the chunk without it (`lexical_text`).
- **Queries, structured lookup, fusion:** unchanged. So Stage 28 changes ranking only through the vector list.

## 2. Traces
Ranks in each list (top 6 of each list are fused); "final" is the rank among distinct provisions.

**TG-PQ-017** "How do I apply for accident compensation before the Claims Tribunal?" (expects Rules 476, 455)

| Signal | Stage 17 | Stage 28 | Stage 29 |
|---|---|---|---|
| Vector, Rule 455 | 14 (0.6671) | 5 (0.5367) | 5 |
| BM25, Rule 455 | 28 | 28 | 28 |
| Structured lookup | none | none | none |
| Final, Rule 455 | not retrieved | 5 | 5 |
| Final, Rule 476 | 1 | 1 | 1 |

**TG-MR-007** "What are the badge rules for drivers and for conductors?" (expects Rules 37, 66)

| Signal | Stage 17 | Stage 28 | Stage 29 |
|---|---|---|---|
| Vector, Rule 37 | 4 (0.4016) | 6 (0.4221) | 6 |
| BM25, Rule 37 | 5 | 5 | 5 |
| Structured lookup | none | none | none |
| Final, Rule 37 | 5 | 6 | 2 |
| Final, Rule 66 | 1 | 1 | 1 |

## 3. Why Rule 37 lost its place
- The question asks about two subjects. Chapter III (conductors) has five badge rules (66, 67, 69, 70, 71); chapter II (drivers) has one (Rule 37).
- With "Licensing of Conductors of Stage Carriages" in their headers, Rules 70 and 69 move closer to the question (distances 0.4664 → 0.3799 and 0.4479 → 0.3824) and overtake Rule 37, whose distance worsens slightly (0.4016 → 0.4221).
- Fusion scores then put Rule 37 last of the six: Rule 69 0.03151, Rule 70 0.03125, Rule 71 0.03102, Rule 37 0.03054.
- Rule 37 was still returned (the server returns six chunks); the benchmark scores the top five.

## 4. Approaches compared
All 108 questions, exact mode, scratchpad copies. "Gaps" are scored questions missing an expected provision from the top five.

| Approach | recall@1 | recall@3 | recall@5 | MRR | TG-PQ-017 | TG-MR-007 | New gaps |
|---|---|---|---|---|---|---|---|
| Stage 17 | 0.7046 | 0.9040 | 0.9726 | 0.8907 | no | yes | – |
| Stage 28 | 0.6983 | 0.9135 | 0.9726 | 0.8865 | yes | no | – |
| At most 4 of the top 5 from one chapter or document | 0.6983 | 0.9135 | 0.9747 | 0.8865 | yes | yes | TG-GO-003 |
| At most 3 | 0.6983 | 0.9093 | 0.9589 | 0.8844 | yes | yes | TG-PQ-023, TG-GO-003; hit@5 0.9747 |
| At most 4, chunks with a chapter only | 0.6983 | 0.9135 | 0.9789 | 0.8865 | yes | yes | none, but 7 other top-five lists change |
| Query-term coverage rerank | 0.6983 | 0.9135 | 0.9747 | 0.8865 | yes | yes | TG-GO-003; 13 other lists change |
| Second vector list from chapter-free embeddings | 0.7015 | 0.9167 | 0.9557 | 0.8907 | no | no | TG-PQ-021, TG-GO-003 |
| Chapter and chapter-free vector lists merged first | 0.7141 | 0.9230 | 0.9536 | 0.9097 | no | no | TG-PQ-009, TG-PQ-021 |
| Header: chapter after the heading | 0.6983 | 0.9008 | 0.9726 | 0.8854 | yes | no | – |
| Header: chapter title without its number | 0.7046 | 0.9167 | 0.9726 | 0.8939 | yes | no | – |
| Named chapters, late one moved to fifth place | 0.6983 | 0.9135 | 0.9789 | 0.8865 | yes | yes | none |
| **Named chapters lead (chosen)** | **0.6983** | **0.9198** | **0.9789** | **0.8865** | **yes** | **yes** | **none** |

- **Header wording cannot fix TG-MR-007:** all three header forms leave Rule 37 at rank 6.
- **Blanket diversity rules fix it but disturb unrelated questions:** they put an off-topic chunk in fifth place (e.g. Rule 14 for the autorickshaw permit question), and the cap is fragile (4 works, 3 loses a hit).
- **Two embeddings per chunk lose TG-PQ-017** and would double the stored vectors.
- **Chosen over "fifth place":** same recall@5, better recall@3, and it does not depend on the benchmark's cut-off of five.
- **Not implemented:** dropping the chapter number from the header restores Stage 17's recall@1 and beats its MRR, but it does not address TG-MR-007 and is one more choice made on this benchmark. It is a candidate for a later stage.

## 5. Implementation
- **`backend/hybrid_retrieval.py`**
  - `chapter_naming_terms(docs)`: for each chapter in the index, the title words found in no other chapter title ("conductor" names chapter III; "motor" and "vehicle" name nothing). Built once with the lexical index, from the index's own metadata.
  - `LexicalIndex.spread_named_chapters(question, docs)`: if the question uses naming words of two or more chapters that each have a chunk in `docs`, the best chunk of each later chapter moves up to follow the best chunk of the first. Otherwise `docs` is returned as is.
- **`backend/server.py`:** `retrieve()` applies it to the six chunks it is about to return (hybrid mode only), after the eligibility filters.
- **Unchanged:** vector search (exact and HNSW), BM25, structured lookup, fusion, `RETRIEVE_K`, eligibility filters, source-status warnings, the API, ingestion and the builder.

## 6. Benchmark
All 108 questions; 79 scored. Record: `stage-29-evaluation.json`.

| Metric | Stage 17 | Stage 28 | Stage 29 exact | Stage 29 HNSW |
|---|---|---|---|---|
| hit@5 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| recall@1 | 0.7046 | 0.6983 | 0.6983 | 0.6983 |
| recall@3 | 0.9040 | 0.9135 | 0.9198 | 0.9198 |
| recall@5 | 0.9726 | 0.9726 | 0.9789 | 0.9789 |
| precision@5 | 0.2608 | 0.2608 | 0.2633 | 0.2633 |
| MRR | 0.8907 | 0.8865 | 0.8865 | 0.8865 |

- Guard 12/12, excluded chunks retrieved 0, model calls 0 in every run. A repeat on a fresh copy gave identical lists.
- The Stage 17 and Stage 28 exact lists were reproduced exactly before comparing.

**Top-five changes against Stage 28 (exact): two questions**

| Question | Stage 28 | Stage 29 |
|---|---|---|
| TG-MR-007 | 66, 67, 69, 70, 71 (Rule 37 sixth) | 66, **37**, 67, 69, 70 |
| TG-MR-008 | 77, 78, 43, 47, 44 | 77, **43**, 78, 47, 44 |

- Both ask about "drivers and conductors". Every other list is identical, and both questions return the same six provisions as before.

**Top-five changes against Stage 17 (exact): 54 questions**, all but the two above inherited from Stage 28. Expected-provision rank changes:

| Question | Change |
|---|---|
| TG-PQ-017 | Rule 455: not retrieved → 5 |
| TG-MR-007 | Rule 37: 5 → 2 |
| TG-PQ-003 | Rule 18: 4 → 3 |
| TG-GO-003 | Paragraph 5: 4 → 2, Paragraph 4: 3 → 4 |
| TG-MR-008 | Rule 77: 2 → 1, Rule 43: 1 → 2 |
| TG-MR-004 | Rule 448A: 1 → 2, Rule 448B: 2 → 1 |
| TG-PQ-002 | Rule 14: 3 → 4 |
| TG-PQ-007 | Rule 484: 1 → 2 |

- The 54 question IDs and their lists are in the record (`comparison.exact.top5_changed_vs_stage17`).
- **New regressions:** none. No expected provision leaves the top five against Stage 17 or Stage 28.
- **Remaining recall@5 gaps:** TG-PQ-002, TG-GO-007, TG-GO-012 (the same three as before Stage 28).

**Exact and HNSW**
- Metrics are identical, and no scored question differs in its top five.
- One full list differs (TG-PQ-025, below the top five). HNSW lists also varied between runs on the same copy for TG-AM-001, TG-OS-001 and TG-PQ-025; none is one of the two reordered questions.
- The reorder fired on the same two questions in both modes, and on none with the baseline index.

## 7. Tests
- **New `tests/test_named_chapters.py`** (19 tests):
  - Naming words: only words unique to one chapter title; the chapter number is not a word.
  - Reorder: two and three named chapters, same chunks kept, one named chapter unchanged, shared words name nothing, nothing moves ahead of the first named candidate, an index without chapters never reorders.
  - `server.retrieve`: reorders a question naming two chapters; other questions and chapter-free indexes keep the fused order.
  - Recorded regression: Rule 455 and Rule 37 in the top five in both modes; no metric below Stage 28; no expected provision lost against Stage 17 or 28; only the two questions change; exact and HNSW agree.
  - Mutation checks: removing the server call, requiring three chapters, or counting shared words each make tests fail.
- **Full suite:** 754 OK in exact mode and 754 OK in HNSW mode (735 + 19), with `KYR_REQUIRE_LEGAL_DATA=1`. Checksums: 63/63.

## 8. Files changed
| File | Why |
|---|---|
| `backend/hybrid_retrieval.py` | Naming words per chapter and the reorder |
| `backend/server.py` | `retrieve()` applies the reorder to the returned chunks |
| `tests/test_named_chapters.py` (new) | Unit, server and recorded regression tests |
| `eval/legal-validation/stage-29-evaluation.json` (new) | Metrics, ranked lists and comparisons |
| `eval/legal-validation/stage-29-originals/` (new) | Backups of the two backend files |

## 9. Limitations
- **Thin evidence:** two benchmark questions trigger the reorder, and both have the same "drivers and conductors" shape. It was designed after seeing TG-MR-007, so a held-out set is needed to confirm it generalises.
- **It is a reorder:** the answer model already received Rule 37 as the sixth chunk under Stage 28. The gain is in ordering and in the top-five metric.
- **Naming words come from chapter titles:** a question that uses a title word in another sense (e.g. "state", "power") could trigger it. The effect is limited to moving one returned chunk up.
- **Only TMVR chunks have chapters** after a rebuild; G.O. chunks are never reordered.
- **The recorded regression tests read `stage-29-evaluation.json`** (untracked). They skip without it, or fail under `KYR_REQUIRE_LEGAL_DATA=1`.

## Constraints
- **Not changed:** source text, the benchmark and its labels, the review CSV, approvals, the source-status registry (`5a174820…`), Rule 81's warning, and both preview indexes (no file modified).
- No Groq or external calls; embeddings came from local Ollama on 127.0.0.1. Nothing was staged, committed or pushed, and earlier uncommitted work is preserved.

## Rollback
```bash
cd /Users/vj/Downloads/KnowYourRules-tg && O=eval/legal-validation/stage-29-originals && cp -p $O/hybrid_retrieval.py.pre-stage-29 backend/hybrid_retrieval.py && cp -p $O/server.py.pre-stage-29 backend/server.py && rm tests/test_named_chapters.py
```
