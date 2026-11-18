# Stage 17: targeted retrieval quality (TG-MR-008)

**One change: BM25 tokenisation now folds plurals to singular** (Harman's S-stemmer, `hybrid_retrieval.fold_plural`). This fixes TG-MR-008: Rule 77 moves from rank 6 to rank 2.
- **Unchanged:** exact vector search (still the default), squared L2, the 0.80 cut-off, the `search_query: ` prefix, BM25 k1/b, structured lookup, RRF, the eligibility filters, and the API and citation formats.
- **Not changed:** benchmark labels, the review CSV, sources, Rule 81, approval records, answer generation and the validator. File SHAs match Stage 14 (see `stage-17-evaluation.json`).
- No Groq or external calls, no commits, and the live index is untouched (evaluated on copies).
- **Rollback:** `stage-17-originals/hybrid_retrieval.py.pre-stage-17`.
- Data: [`stage-17-evaluation.json`](stage-17-evaluation.json) and [`stage-17-retrieval-comparison.json`](stage-17-retrieval-comparison.json).

## 1. Cause of TG-MR-008
Question: "Who issues medical certificates for drivers and for conductors?" It expects TMVR Rule 43 (chapter 2) and Rule 77 (chapter 3).

**Vector search (exact)**
- Rule 43 is at rank 1 (distance 0.5470) and Rule 77 at rank 3 (0.5493), so vector search is not the problem.

**BM25: the defect**
- The query tokens were `issues, medical, certificates, drivers, conductors`.
- Rule 77's text says "issue" and "certificate". It never uses the plural forms in the question, so only `medical` matched.
- Rule 77 ranked 9th in BM25, outside the top-6 list that goes into fusion.
- Chunks matching the plural words ranked above it: Rule 337 (`drivers`, `conductors`), 239, 76 and 469/468 (`issues`).

**Structured lookup:** no matches, because the question names no rule.

**Fusion**
- Rule 77 got only its vector vote, 1/63.
- That tied Rule 76's BM25 vote (1/63). RRF keeps insertion order on ties, and the BM25 list is fused first, so Rule 76 took rank 5 and Rule 77 fell to rank 6.

**Root cause:** BM25 did not match plural forms in a question against singular forms in the provision text. The tie-break was a secondary factor and was left unchanged; nothing showed it was a defect.

## 2. Fix
- `fold_plural` is applied inside `tokenize`, the single tokeniser used for both indexed text and queries:
  - `-ies` becomes `-y`;
  - `-es` loses its `s`, except after a, e or o;
  - `-s` is removed, except after u or s.
- Only alphabetic words longer than 3 letters change. Rule and G.O. tokens such as `12b` or `go32y2026` are untouched.
- No other suffixes are removed (`issuing` stays `issuing`).
- It is not a special case for TG-MR-008.
- With the fix, Rule 77's BM25 score rises above Rule 337's, and the final order is Rule 43 at rank 1 and Rule 77 at rank 2.

## 3. Regression evaluation (all 108 questions; same 79 scored rows, current labels)
| Metric | Stage 16 | Stage 17 |
|---|---|---|
| hit@5 | 1.000 | 1.000 |
| recall@1 | 0.6857 | 0.7046 |
| recall@3 | 0.9167 | **0.9040** |
| recall@5 | 0.9557 | **0.9726** |
| precision@5 | 0.2532 | 0.2608 |
| MRR | 0.8812 | **0.8907** |

**Other checks**
- Guard: 12/12 in both stages.
- Excluded chunks retrieved: 0 out of 623.
- Model calls: 0.
- Determinism: Stage 17 gave 4 identical signatures (`0716ecd7…`) on 4 fresh copies. Stage 16 reproduced on 3 copies (`d9c6b903…`).
- 63 of 108 final lists changed, mostly lower-ranked filler; expected-provision ranks changed on 11 questions.

**Fixed (recall@5 failure becomes a pass)**
| Question | Change |
|---|---|
| TG-MR-008 | Rule 77: rank 6 → 2. Rule 43: 2 → 1 |
| TG-PQ-021 | Rule 407: rank 6 → 5. Rule 406: 1 → 2 |
| TG-GO-003 | G.O. 32 Order: not in the list → rank 5 |

**Moved up:** TG-PQ-001 and GC-004 (Rule 437: 2 → 1); TG-AM-004 (Rule 120: 2 → 1); TG-MR-007 (Rule 66: 3 → 1); TG-GO-005 (Order: 2 → 1).

**Regressions** (all still in the top 5; they explain the recall@3 drop)
| Question | Change | Why |
|---|---|---|
| TG-MR-007 | Rule 37: rank 2 → 5 | `drivers`/`conductors` now also match singular text in the conductor rules, which compete with the driver-badge rule |
| TG-PQ-023 | Rule 54: rank 2 → 4 | `conductor's` now matches every chapter-3 conductor rule, so more of them compete |
| TG-PQ-011 | Rule 252: rank 1 → 2 | `vehicles`/`goods` match more goods-vehicle text |
| TG-PQ-021 | Rule 406: rank 1 → 2 | In exchange for Rule 407 entering the top 5 |
| TG-GO-005 | Paragraph 5: rank 1 → 2 | Swapped with Order; both expected and both still in the top 2 |

**The six Stage 16 focus questions**
| Question | Stage 17 |
|---|---|
| TG-OS-001, OS-002, OS-005 | Out-of-scope rows; final lists unchanged |
| TG-PQ-007 | Unchanged (Rule 484 at rank 1) |
| TG-MR-005 | Unchanged (Rules 484, 486 and 485 at ranks 1, 2 and 4) |
| TG-MR-008 | **Fixed** (ranks 1 and 2) |

**Tests**
- Full suite: **672 OK** by default and **672 OK with `RAG_VECTOR_SEARCH=hnsw`**. That includes 6 new tests in `tests/test_bm25_plural.py`: folding rules, no other suffixes, identifiers untouched, tokeniser order, and the TG-MR-008-shaped plural/singular match.
- `validate`: OK, 0 reviewed, 108 unreviewed, 0 errors.

## 4. Remaining failures and legal limitations
**Scored recall@5 below 1:**
- TG-PQ-002 and PQ-017;
- TG-GO-007: the old Rule 81 snapshot is still retrieved first;
- TG-GO-012.

**Clarification rows** with partial expected lists: TG-AM-003 and AM-004. These are not counted in the 79 scored rows.

**TG-GO-007 / Rule 81: unresolved**
- The snapshot is outdated.
- No amendment metadata was invented.
- It must not be presented as current law.

**Other open issues**
- Rule 12-B still shares 12-A's citation anchor `#13`.
- BM25 still has the last-digit `set()` noise.
- Fuller stemming (`-ing`, `-ed`) was deliberately not added.

**Not legal validation:** better retrieval does not establish that any provision is current or correct.
