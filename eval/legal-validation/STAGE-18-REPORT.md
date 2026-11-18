# Stage 18: remaining retrieval failures and benchmark verification

**Decision: no code change.** None of the four scored failures shows a retrieval defect that could be fixed narrowly. Stage 17 stays the baseline, unchanged.
- **Metrics on the 79 scored rows (unchanged):** hit@5 1.000, recall@5 0.9726, MRR 0.8907. Guard 12/12.
- **Tests:** 672 OK by default and 672 OK with `RAG_VECTOR_SEARCH=hnsw`.
- No labels, CSV, reviewer status, approvals, sources or indexes were changed. No Groq or external calls; nothing committed.
- **Data:** [`stage-18-failure-analysis.json`](stage-18-failure-analysis.json) has the top 10, the vector and BM25 rank and score for each expected provision, the full chunk text and the metadata. [`stage-18-evaluation.json`](stage-18-evaluation.json) has the baseline and file SHAs.

**Every label below is `machine_candidate` / `pending_human_review`.** None of them is a human-approved legal conclusion. The possible label errors listed are for reviewers to decide.

## 1. Scored failures
| Question | Classification | Key evidence |
|---|---|---|
| **TG-PQ-002** "I lost my driving licence. How do I get a duplicate?" | **Benchmark expectation** | Expects Rules 16, 14, 17 and 18 (all in the corpus). Retrieved: 19, 24, 14, 15, 119 (rule 6 is TMVTR Rule 11). The official chapter-2 text has **Rule 15**, "Intimation when Licence lost or destroyed and application for duplicate" (Form LLD). That is the step for a lost licence, and it is **not expected**. **Rule 14** covers a duplicate with a new photograph after a Rule 13 photograph demand, which has nothing to do with loss. Retrieval is reasonable here |
| **TG-PQ-017** "How do I apply for accident compensation before the Claims Tribunal?" | **Corpus context** (retrieval weakness caused by the chunk text) | Rule 476 is at rank 1. **Rule 455** (an application for compensation under s.166, Form C.I.D.) is a valid expectation, but its chunk never contains "claim", "tribunal" or "accident", and the chapter-11 snapshot has no heading to supply them. It is vector rank 14 and BM25 rank 28. Both parts of Rule 476 take a slot each. Fixing it needs heading context in the indexed chunks, which means an index rebuild (out of scope) |
| **TG-GO-007** "Which 2025 G.O. finally amended Rule 81…" | **Unresolved legal status, and benchmark expectation** | Expects four G.O. 77 chunks. The structured lookup for "Rule 81" adds both parts of the outdated snapshot, at ranks 1 and 3. G.O. 77's Order, Paragraph 4 and Paragraph 3 are retrieved. Paragraph 2 ("no objections received", procedural) is vector rank 9 and BM25 rank 29. The corpus's **"Paragraph 4" is actually item 4 of the amendment schedule** (the substituted sub-rule (6)), not paragraph 4 of the order |
| **TG-GO-012** "Why did Telangana notify a Designated Authority under Rule 167A?" | **Retrieval weakness (vector), no narrow fix** | The Preamble is retrieved at rank 3. The Order is BM25 rank 5 but **vector rank 102**, and ends at fused rank 7. Paragraph 2 (the Supreme Court direction, the actual "why") is vector rank 21 and BM25 rank 7. All five results are from the correct G.O. 32. No generic change was shown to fix this without side effects |

**Possible label errors for reviewers (not changed):**
- **TG-PQ-002:** Rule 15 is missing, and Rule 14's relevance is questionable.
- **TG-GO-007:** whether procedural Paragraph 2 is needed, and the misleading "Paragraph 4" provision ID.

## 2. Rule 81 and G.O. 77 (TG-GO-007)
**Snapshot**
- Rule 81 in `tmvr-1989-chap-4` is an unverified HTML snapshot with no amendment citations.
- Its fee tiers run from Rs. 50,000 to Rs. 5,000; it uses Form RRMA and has sub-rules (1)–(6).

**G.O. 77 (G.O.Ms.No. 77, dated 15-11-2025)**
- A final notification under s.65 of the Act; G.O.Ms.No. 54 (13-08-2025) was the preliminary notification.
- It omits sub-rules (1), (2) and (4).
- It substitutes sub-rule (3) with new fees from Rs. 1,50,000 down to Rs. 6,000 (Rs. 3,000 for two-wheelers) and online-only applications.
- It substitutes (5) (online bidding) and (6).
- It directs publication in a Gazette extraordinary issue dated 15.11.2025.

**Known**
- The text of G.O. 77 and its date.
- The snapshot predates G.O. 77: its fees differ.

**Unknown**
- **Commencement:** G.O. 77 has no commencement clause, and the Gazette issue is not in the corpus.
- Whether the Gazette was actually published as directed.
- The content of the 2014–2018 G.O.s it cites (02/2014, 41/2015, 44/2015, 95/2016, 26/2017, 52/2018).
- Any amendment after 15-11-2025.

**Provenance gap:** `goir/2025TRB_Ms77.pdf` is **not in `SHA256SUMS`**.

**Conclusion:** the corpus cannot establish the current Rule 81. The snapshot must not be presented as current, and no dates or amendment metadata were added.

**Human legal review required**
1. Obtain the Gazette extraordinary dated 15.11.2025 and confirm publication and commencement.
2. Confirm there is no later amendment to Rule 81.
3. Obtain the 2014–2018 G.O.s.
4. Produce a consolidated Rule 81 and decide how to mark the outdated snapshot.
5. Record a checksum for G.O. 77.

## 3. Clarification questions (unscored, kept out of the 79-row metrics)
**TG-AM-003, "Tell me about the badge."**
- Lists Rules 37 and 66; Rule 66 is at rank 6, and Rule 37 is below rank 9.
- More than ten badge rules in chapters 2 and 3 score almost the same on the single word "badge".

**TG-AM-004, "How do I get a duplicate?"**
- Lists six provisions across licences, registration, permits and taxation; only Rules 120 and 228 make the top 5.
- Six targets cannot fit in five slots, so full recall is impossible by design.

Both rows exist to trigger a clarification question, not full retrieval.

## 4. Remaining issues
- **Scored failures:** TG-PQ-002, PQ-017, GO-007 and GO-012, classified above.
- **Several parts of one provision fill separate result slots** (Rule 476 in PQ-017; the Rule 81 snapshot in GO-007). This is a design choice to decide later, not a demonstrated defect.
- **Other open issues:** Rule 12-B still shares 12-A's anchor; BM25 still has the last-digit `set()` noise.
- **Not legal validation:** no provision is claimed to be current.
