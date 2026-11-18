# Stage 15: retrieval reproducibility and ranking-failure analysis

**Investigation only.** I changed no retrieval code, embedding model, index, benchmark, review CSV or approval. There were no Groq or external calls and no commits. Every run used a copy of `chroma_telangana_preview_s11`; the live index is byte-identical (`data_level0.bin` `97aae309…`).
- Data: [`stage-15-reproducibility.json`](stage-15-reproducibility.json) (every query, chunk, rank, distance and fusion score, plus configuration and index identity).
- Analysis: [`stage-15-ranking-analysis.json`](stage-15-ranking-analysis.json).

## A. Reproducibility
**Configuration, constant in every run**
- Hybrid mode: structured lookup + BM25 (k1 1.5, b 0.75) + vector, fused with RRF (k = 60).
- `RETRIEVE_K = 6` chunks; `MAX_DISTANCE = 0.8`; l2 distance.
- Collection metadata `{"rag_profile": "structured"}`, so there are **no HNSW settings** and Chroma's defaults apply.
- Embeddings: `nomic-embed-text`, digest `0a109f422b47…`, query prefix `search_query: `.
- Index content: 590 chunks; document set `72e4cf91…`; stored embeddings `b7071f26…`, identical in every run.

**Five instrumented runs replayed exactly what `server.retrieve()` does:**
1. Copy A, opened for the first time.
2. Copy B, opened for the first time.
3. Copy C, opened for the first time, after restarting Ollama.
4. Copy A, opened a second time.
5. A copy of the directory used for the Stage 14 evaluation.

| Component | Identical across runs? |
|---|---|
| Query embeddings (sha256 of every vector) | **Yes**, including after an Ollama restart |
| Exact vector search (brute force over the stored embeddings) | **Yes** |
| Structured lookup | **Yes** |
| BM25 chunk order | **Yes**. Scores differ only in the last floating-point digit (123 comparisons) |
| **HNSW vector search (Chroma's approximate index)** | **No.** Differs from exact search on 0–2 questions per run, and on different questions in different runs |
| Final ranking | **No.** 105 of 108 questions are stable; TG-OS-001, 002 and 005 vary |

- **Identical index copies do not give identical rankings.** Each first open of a copy rewrote its `data_level0.bin`, and three byte-identical copies ended up with three different hashes. A second open changed copy A again.
- **Every variation comes from HNSW returning a list that is not the true nearest-neighbour list.** For example, in TG-OS-001 it skips G.O. 32 Paragraph 2, which is exact rank 2. All other components were stable.
- **No scored metric changed** across these runs: the varying questions are all out-of-scope rows.
- **Where the BM25 last-digit noise comes from:** `hybrid_retrieval.py:79` sums over `set(query_tokens)`, whose order depends on Python's per-process hash seed. It changed no ranking in these runs, but it could break a near-tie.

## B. The four Stage 11 / Stage 14 discrepancies
| Question | Stage 11 | Stage 14 | Stage 15 runs | Cause |
|---|---|---|---|---|
| TG-OS-001 | …Rule 143, Rule 83 | …G.O. 32 Para 2, Rule 143 | Both orders seen | **HNSW variance, observed.** Exact rank 2 is G.O. 32 Para 2; some HNSW results skip it |
| TG-OS-002 | …G.O. 32 References… | …Rule 316, Rule 185… | Both orders seen | **HNSW variance, observed.** Exact rank 2 is G.O. 32 References; some HNSW results skip it |
| TG-PQ-007 | 484, 485, 486, 107 | 485, 484, 486, 400 | Stage 11 order in all 5 runs | **Vector side, by elimination; not reproduced** |
| TG-MR-005 | …485, Rule 83A | …485, Rule 452 | Stage 11 order in all 5 runs | **Vector side, by elimination; not reproduced** |

**Why TG-PQ-007 and MR-005 point to the vector side.** In every run, Rule 484 beats 485 by a clear RRF margin (0.03252 vs 0.03227), and BM25, lookup and embeddings never vary. The Stage 14 order is only reachable if the vector list had **left out Rule 484, its true nearest neighbour** (exact distance 0.494). In that case, 485 rises to vector rank 2 and outscores 484. Likewise, Rule 452 overtakes 83A, which are otherwise exactly tied at 1/66, only if one vector chunk drops out.
- That is the same kind of failure observed directly on the OS rows.
- The Stage 14 index state cannot be recovered: that copy has since been reopened, and the Stage 14 output saved provisions, not chunk lists. So for these two rows the cause is **consistent with HNSW variance but not directly reproduced**. Mark them **unresolved but bounded**.

**What is not the cause**, with evidence: query preprocessing, embeddings and Ollama restarts, BM25 ranking, structured lookup, configuration, chunk metadata and index content. All were identical.

**On file rewrites:** opening an index *does* rewrite `data_level0.bin` (observed), and HNSW results *do* differ between opens (observed). The mechanism linking the two inside Chroma was not investigated, and I'm not claiming one.

## C. The seven remaining retrieval gaps
Every expected provision exists in the index and is answer-eligible. Ranks are distinct provisions.

| Question | Expected provision: final / exact-vector / BM25 rank | Main competitors | Classification | Recommended fix (not applied) |
|---|---|---|---|---|
| TG-PQ-002 (duplicate licence) | 14: 3/2/6 · 16: –/10/12 · 17: –/6/9 · 18: –/16/14 | Rules 19, 24, **15**, 119, TMVTR 11 | Benchmark expectation; chunk budget | Human review: Rule 15 ("intimation when licence lost… application for duplicate") is retrieved but not expected. Four expected rules can't fit 6 chunks alongside close siblings |
| TG-PQ-017 (claims tribunal) | 476: 1/1/2 · 455: –/13/25 | Rules 471, 458, 462, 474 | Embedding similarity; benchmark expectation | Review whether Rule 455 (heading just "Applications") is required; if it is, add chapter context to its embedding title |
| TG-PQ-021 (park/halt) | 406: 1/1/4 · 407: 6/3/316 | Rules 335, 180, 256, 239 | Ranking (fusion) | Rule 407 says "parking place"; BM25 has no stemming. Add light stemming, evaluated across the whole benchmark |
| **TG-MR-008** (medical certificates) | 43: 2/1/10 · **77: 6/3/9** | Rules 337, 239, 47, 76 | Ranking (fusion) | Rules 43 and 77 share the same heading; lexical-only competitors outscore 77. Split the question into sub-queries, or keep slots for distinct provisions that share a top hit's heading. **Kept on record as a ranking failure** |
| TG-GO-003 (speed cameras) | Para 4: 3/5/6 · Order: –/171/5 · Para 5: 4/8/1 | G.O. 32 Para 3, Preamble, Para 6, Para 7 | Chunk budget; embedding similarity | Group a G.O.'s chunks into one unit. The Order chunk is mostly header text; review whether it should be expected |
| **TG-GO-007** (Rule 81 amendment) | Order: 2/1/1 · Para 2: –/7/26 · Para 3: 4/3/3 · Para 4: 3/2/4 | **Rule 81 at rank 1** | Structured lookup; missing version metadata | Part D. **Kept on record** |
| TG-GO-012 (why Designated Authority) | Order: –/100/5 · Para 2: –/21/7 · Preamble: 3/6/4 | G.O. 32 Paras 4–7, TMVR Rule 173 | Query formulation; embedding; chunk budget | The reason is in Para 2 (the Supreme Court direction). Use the G.O.-grouping fix; optionally tag recitals for "why" questions |

None is a missing source or a wrong chunk identity. No row should be fixed by tuning retrieval to that one row.

## D. Rule 81 safety (TG-GO-007)
**What the index holds**
- **Rule 81** (2 chunks) comes from an **unverified HTML snapshot** retrieved 29-10-2026. It has `source_class = unverified_snapshot`, empty `effective_date` and `publication_date`, and `answer_eligible = true`. The manifest note says "consolidated text with no amendment citations", known to be outdated elsewhere.
- **G.O.Ms.No. 77/2025** is an official copy dated 15-11-2025, with publication and effective dates null (no gazette print). It is the final notification amending Rule 81, and its Paragraph 4 substitutes sub-rule (6).

**Textual evidence**
- The snapshot's sub-rule (6) refers to clauses "(3) (i), (ii) and (iii)".
- G.O. 77's replacement refers to "(i)…(vii)", and the snapshot contains no clause "(vii)".
- So the snapshot **does not reflect G.O. 77's text**. That does **not** establish which text is legally in force.

**Why the old Rule 81 ranks first:** the question names "Rule 81", so the structured lookup returns both Rule 81 chunks.
- Rule 81 part 1 then gets three RRF votes: lookup rank 1, BM25 rank 6, vector rank 4. Score 0.0472.
- G.O. 77's Order gets two: BM25 rank 1, vector rank 1. Score 0.0328.
- The lookup vote decides it. Nothing in the metadata connects G.O. 77 to Rule 81.

**Missing metadata**
- `amends` / `amended_by` links (G.O. 77 → Rule 81 sub-rules (3) and (6)).
- A per-sub-rule version or "as at" date for the snapshot.
- G.O. 77's commencement date.
- A machine-readable supersession status on the Rule 81 chunks.
- Any retrieval rule that brings an amending instrument along with the provision it amends.

**Proposed design: amendment-aware retrieval** (not implemented)
1. **A reviewed amendment map, stored as data:** amending instrument → target provision and sub-rule, the action (substitute, insert or omit), and the effective date or null. It is filled from documents and human review, never inferred by code.
2. **At retrieval time:** when a mapped provision is returned, always add the amending G.O. chunks beside it, with the warning "amended by G.O.Ms.No. X; snapshot text may be outdated".
3. **Never present an amended sub-rule's snapshot text as current.** If effective dates are unknown, don't choose between versions: show both with the warning.
4. **Optional:** rank the snapshot sub-rule lower (without dropping it), so the G.O. comes first.
5. **Tests:**
   - TG-GO-007 returns G.O. 77 Order and Paragraph 4 together with Rule 81, plus the warning.
   - No test asserts legal currency.

## Recommendations, in order
1. **Reproducibility first.** For 590 chunks, make vector search exact (brute force over the stored embeddings), or raise HNSW `search_ef`. Then take a new baseline.
   - Also make BM25 summation order deterministic.
   - Record the vector, lexical and lookup lists with their scores in `retrieval_eval` output.
   - Keep evaluating through copies, recording `data_level0.bin` hashes.
2. **The Rule 81 amendment map and warning** (Part D), because it is a safety issue.
3. **G.O. chunk grouping** (TG-GO-003, TG-GO-012) and **slots for distinct provisions** (TG-MR-008).
4. **BM25 stemming** (TG-PQ-021), measured across all 108 questions.
5. **Human review of expectations** for TG-PQ-002, PQ-017, GO-003 and GO-012 (and for GO-007 Paragraph 2).

## Final state
- **Tests:** 642 pass. **`validate`:** OK, 0 reviewed, 108 unreviewed, 0 errors.
- **Git:** branch `feature/telangana-assistant`, HEAD `f944466`.
  - Modified, uncommitted from Stage 14: `eval/telangana-chunk-references.json`, `eval/telangana-retrieval-benchmark.json`, `eval/telangana-retrieval-review.csv`, `tests/test_review_import.py`.
  - Untracked: `backend/source_compare.py`, `chroma_telangana_preview_s11/`, `eval/legal-validation/`, `tests/test_benchmark_integrity.py`, `tests/test_source_compare.py`.
- **Unchanged:** both live indexes, the sources, the benchmark, the CSV, the references and the approval records.
- The local Ollama server started for embeddings has been stopped.
