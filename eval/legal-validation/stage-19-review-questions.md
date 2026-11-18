# Stage 19: reviewer questions (benchmark labels)

**For reviewers only.** No labels, CSV reviewer fields, approval records or expected chunks have been changed.
- Both rows are `machine_candidate` / `pending_human_review`.
- The observations below come from the official source text. They are not legal conclusions.

## TG-PQ-002: "I lost my driving licence. How do I get a duplicate?"
**Currently expected:** TMVR Rules 16, 14, 17 and 18 (chapter 2).

**Question 1: should Rule 15 be expected?**
- Official text: "15. Intimation when Licence lost or destroyed and application for duplicate", requiring written intimation in Form LLD.
- It is the first step after a loss, and Rule 16 depends on it ("Upon receipt of intimation and application specified in Rule 15").
- Retrieval already returns it, at rank 4.

**Question 2: should Rule 14 stay?**
- Official text: "14. Duplicate Licence with new photograph". It follows a Rule 13 demand for a recent photograph.
- It does not concern a lost licence.

**Question 3: should Rule 19 or Rule 24 be expected?**
- Rule 19 is "Delivery of lost Licence"; Rule 24 is "Issue of duplicate Learner's Licence".
- Both are currently retrieved but not expected. Optional.

## TG-GO-007: "Which 2025 G.O. finally amended Rule 81 on reservation of special registration numbers?"
**Currently expected:** G.O. 77 Order, Paragraph 2, Paragraph 3 and Paragraph 4.

**Question 4: is Paragraph 2 needed?**
- It says only that no objections were received and the final notification is published.
- The answer ("G.O.Ms.No. 77 of 15-11-2025") is in the Order and Paragraph 3.

**Question 5: what does "Paragraph 4" refer to?**
- The chunk labelled `go-ms-77-2025-trb::Paragraph 4` is **item 4 of the amendment schedule**: "For sub-rule (6) the following shall be substituted".
- It is not paragraph 4 of the order, which has only paragraphs 1 to 3.
- Should the label refer to the amendment item? Or should the chunk ID be corrected at the next approved rebuild?

**Question 6: should the old Rule 81 snapshot be treated as relevant or as superseded for this question?**
- Its legal status is unresolved; see `stage-19-source-provenance.json`.
