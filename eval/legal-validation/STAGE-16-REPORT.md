# Stage 16: deterministic exact vector retrieval

**Exact vector search is now the default for the 590-chunk Telangana corpus.** Setting `RAG_VECTOR_SEARCH=hnsw` restores Chroma's HNSW search.
- Unchanged: the embedding model, the index, BM25, the fusion step, the benchmark, the review CSV, the sources, Rule 81 and its metadata, answer generation and the validator.
- No Groq or external calls; nothing committed.
- Data: [`stage-16-evaluation.json`](stage-16-evaluation.json) and [`stage-16-retrieval-comparison.json`](stage-16-retrieval-comparison.json).

## A. Existing semantics, verified rather than assumed
| Question | Finding | Evidence |
|---|---|---|
| Metric | **Squared L2** (Chroma's default `l2`); lower is closer | The collection config is `{}` with no `hnsw:space`. Chroma's returned distances equal exact squared L2 to within 9.7e-08 |
| Normalised? | The stored vectors are unit-norm (0.99999944–1.00000057) | Computed from the stored embeddings. The code still uses squared L2, not cosine |
| Query embedding | `store.embeddings.embed_query`, which adds the `search_query: ` prefix (`rag_profiles.py:123`) | LangChain's `similarity_search_with_score` calls the same function |
| Scores to ranking | `relevant_docs` keeps results with a distance of 0.80 or less, in Chroma's order | `server.py:839` |
| Combination | The vector list is the third input to RRF (k = 60), after structured lookup and BM25 | `server.py` `retrieve()`, `hybrid_retrieval.py:190` |
| Duplicates and ties | RRF merges chunks by `chunk_key`, and ties keep insertion order. Chroma had no explicit tie-break | `hybrid_retrieval.py:87, 202` |

## B and D. Implementation
**`backend/exact_vector.py`** (new) defines `ExactVectorIndex`:
- **Inputs:** reads the stored IDs, embeddings, documents and metadata once from the collection, read-only.
- **Distance:** squared L2 in float64, computed element-wise. It avoids matrix-multiply routines, whose summation order can vary.
- **Order:** sorted by `(distance, chunk id)`, so ties are broken explicitly by chunk ID.
- **Filters:** flat equality filters only. Anything else raises `ValueError`, so the caller falls back rather than silently ignoring a filter.
- **Output:** the same `[(Document(page_content, metadata, id), distance)]` that LangChain's Chroma wrapper returns.
- **Refuses:** distance spaces other than `l2`, duplicate IDs, embeddings that are not finite, and mismatched lengths.
- **Returns nothing for:** an empty or invalid query, or `k` that is not a positive integer.

**`backend/server.py`** (+34 / −4):
- New `VECTOR_SEARCH` setting (from `RAG_VECTOR_SEARCH`, default `exact`), `EXACT_INDEX` built once at start-up, and a `vector_search()` function.
- `retrieve()` now calls `relevant_docs(vector_search(question))`. Everything after that is unchanged: fusion, Telangana and approval filters, `answer_eligible`, de-duplication.
- **Fallbacks to Chroma's HNSW:** `RAG_VECTOR_SEARCH=hnsw`, a failure to build the snapshot, or an unsupported filter.

## C. Exact vs approximate
**Determinism**
- **Exact:** 3 runs on 3 fresh byte-identical copies, plus a reopen of the first copy. All 4 signatures are identical (`6f470e39…`). The signature covers every chunk ID, distance and final list.
- **HNSW:** 3 runs on 3 fresh copies gave **3 different** signatures.

| HNSW run | Vector list differs from exact | Top-5 provisions differ |
|---|---|---|
| 1 | OS-001, OS-005 | OS-001, OS-005 |
| 2 | PQ-025, OS-002, OS-005 | OS-002, OS-005 |
| 3 | OS-005 | OS-005 |

- Where HNSW found the true neighbours, its distances equal exact ones to within 9.7e-08.
- The closest any benchmark distance comes to the 0.80 cut-off is 0.004, so no cut-off decision can change.

**The six focus questions**
| Question | Exact search | Finding |
|---|---|---|
| TG-OS-001 | Includes G.O. 32 Para 2 (true rank 2) | Stage 11 missed it through HNSW; Stage 14 had it. Not scored |
| TG-OS-002 | Includes G.O. 32 References (true rank 2) | Same as Stage 11; Stage 14 missed it. Not scored |
| TG-OS-005 | Same as Stages 11 and 14 | All three Stage 16 HNSW runs differed. Not scored |
| TG-PQ-007 | Rule 484 at rank 1, same as Stage 11 | Stage 14's 485-first order never comes out of exact search, which fits a Stage 14 HNSW miss |
| TG-MR-005 | Same as Stage 11 (Rule 83A) | Stage 14's Rule 452 is not reproduced |
| **TG-MR-008** | Rule 77 still at **rank 6** | **Not an HNSW problem.** A ranking and fusion issue, kept on record |

So exact search recovers the true nearest neighbours HNSW missed on the out-of-scope rows, and removes the run-to-run variation. It does not fix any scored miss: no scored row depended on an HNSW miss in these runs.

**Metrics on identical cohorts**
- All rows are scored with the **current labels**.
- **Cohort 74:** the 74 rows scored before Stage 14.
- **Cohort 79:** those plus TG-MP-001 to 005.

| Run | 74: hit@5 / recall@5 / MRR | 79: hit@5 / recall@5 / MRR |
|---|---|---|
| Stage 11, old index | 1.000 / 0.9527 / 0.8732 | 0.962 / 0.9072 / 0.8432 (the old index has no Rule 186) |
| Stage 11, `_s11` (HNSW) | 1.000 / 0.9527 / 0.8732 | 1.000 / 0.9557 / 0.8812 |
| Stage 14, `_s11` (HNSW) | 1.000 / 0.9527 / **0.8664** | 1.000 / 0.9557 / **0.8749** |
| Stage 16 HNSW, runs 1–3 | 1.000 / 0.9527 / 0.8732 | 1.000 / 0.9557 / 0.8812 |
| **Stage 16 exact** | **1.000 / 0.9527 / 0.8732** | **1.000 / 0.9557 / 0.8812** |

- Stage 14's lower MRR came from its HNSW run (TG-PQ-007), not from the label changes.
- Stage 14's reported MRR of 0.8749 should not be compared with Stage 11's reported 0.8732: they score different populations, 79 rows against 74.

**Performance**
| Measure | Exact | Chroma HNSW |
|---|---|---|
| Vector search, embedding excluded | **1.74 ms** per query | 3.63 ms |
| Per question, embedding included | about 31–49 ms | about 32–34 ms |
| Memory | 3.6 MB matrix; 21.5 MB peak while building | n/a |
| Snapshot build at start-up | 0.11 s | n/a |

The per-question time is dominated by the Ollama embedding call, so exact search adds no meaningful latency.

## E. Tests
**`tests/test_exact_vector.py`** (24 tests) covers:
- squared-L2 calculation, explicitly not plain L2 or cosine;
- ascending score order and the `k` limit;
- tie-breaking by chunk ID, independent of storage order;
- identical results on repeated queries and on a freshly built index;
- the Telangana equality filter, and unsupported filters raising so the caller falls back;
- `answer_eligible=False` passed through for the server to drop, and returned metadata being a copy;
- empty, blank or non-string queries, invalid `k`, wrong dimensions or non-finite values, an empty index, and bad construction;
- `from_store` using the default `l2` and the store's own embedding function, and refusing other distance spaces;
- the output matching LangChain's Chroma format, and fusing with BM25 lists;
- server integration: exact is the default, it applies the Telangana filter, and it falls back without a collection or on an unsupported filter;
- **a regression test against recorded behaviour:** the 590+ Stage 15 Chroma distances on questions where HNSW was exact, which squared L2 must reproduce in order and to 1e-6.

**Results**
- Full suite: **666 OK** by default, and **666 OK with `RAG_VECTOR_SEARCH=hnsw`**.
- `validate`: OK, 0 reviewed, 108 unreviewed, 0 errors.
- Official `retrieval_eval` with the new default, all 108 questions:
  - Retrieval (79 scored): hit@5 1.000, recall@5 0.9557, MRR 0.8812, precision@5 0.2532.
  - Guard: 12/12, reported separately.
  - 0 model calls; 0 excluded chunks retrieved. Rankings are identical to the exact runs above.

## Remaining failures (unchanged; see Stage 15)
- **Recall@5 below 1:** TG-PQ-002, PQ-017, PQ-021, **MR-008** (Rule 77 at rank 6), GO-003, **GO-007** (outdated Rule 81 first, no amendment metadata), GO-012.
- **Rule 12-B** shares 12-A's citation anchor `#13`.
- **BM25:** the last-digit noise from `set()` ordering is still there, and stemming is not done (both out of scope here).
- **Not legally verified:** no provision is claimed to be current.

## State
- **Branch:** `feature/telangana-assistant`, HEAD `f944466`.
- **Stage 16 changes:**
  - `M backend/server.py`
  - new `backend/exact_vector.py`
  - new `tests/test_exact_vector.py`
  - three new files in `eval/legal-validation/`
- **Still uncommitted from Stage 14:** the references, the benchmark, the CSV and `tests/test_review_import.py`.
- **Unchanged:** both live indexes, which were evaluated through copies only.
- The local Ollama server has been stopped.
