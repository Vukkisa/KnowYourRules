# Human review guide: Telangana retrieval benchmark

This guide is for the person reviewing `eval/telangana-retrieval-review.csv`, which has one row per question in `eval/telangana-retrieval-benchmark.json` (108 questions).

## What exists and what does not

| | Status |
|---|---|
| Benchmark labels (expected provisions, passages, outcomes) | **Machine candidates.** Written by an engineer from provision headings and indexed text. No human has confirmed any of them. |
| `machine_retrieval_result` (PASS / PARTIAL / FAIL) | **Engineering validation only.** It says whether retrieval returned the provisions the *machine label* expected. It says nothing about whether the label or the law is right. |
| Source documents (20) | **Legally unverified.** All are `unverified` in the draft manifest. Several are web snapshots of consolidated text with no amendment history. |
| Human review fields | **Empty.** They are filled only by a named reviewer. |

A PASS means "the system found what an engineer guessed was relevant". It is **not** a statement that the answer is legally correct, current or complete. A human-confirmed benchmark row is also not legal approval of the corpus. That is a separate signed record (see `docs/legal-sources/telangana-traffic/LEGAL-REVIEW-HANDOFF.md`).

## Columns

Columns starting with `machine_` and `audit_notes` are generated. **Do not edit them.** If one is wrong, record that in the `human_` fields.

| Column | Meaning |
|---|---|
| `review_priority`, `priority_group`, `also_in_groups` | Suggested review order (see `REVIEW-PRIORITY.md`). |
| `machine_expected_outcome` | What the machine label says should happen: `retrieve`, `missing_provision`, `excluded_no_context`, `restricted` (penalty), `out_of_scope` or `clarification_required`. |
| `machine_expected_provisions`, `machine_expected_locations`, `machine_supporting_passage` | The provisions the label expects, where they are, and verbatim text from the indexed chunk. |
| `machine_excluded_chunks` | Chunks that must **not** be used (unreliable extraction, a draft G.O., a superseded schedule). |
| `machine_retrieved_top5` | The top five passages the system actually retrieved, with their opening text. |
| `machine_retrieval_result`, `machine_first_relevant_rank`, `machine_recall_at_5` | Machine scores against the machine label. |
| `audit_notes` | Known label problems found by the engineering audit. Read these first. |
| `reviewer_status` | Stays `pending_human_review` until a reviewer decides. The engineering team then updates the benchmark JSON from your decision. |

### Fields you fill in

Use only the values listed. Leave a field empty rather than guessing.

| Field | Values | What it records |
|---|---|---|
| `human_decision` | `correct`, `partially_correct`, `incorrect`, `ambiguous`, `missing_source`, `refuse_expected` | Your overall verdict (definitions below). |
| `human_correct_expected_provisions` | Provision list, e.g. `tmvr-1989-chap-8 :: Rule 437; tmvtr-1963 :: Rule 13A` | Fill in only when it differs from `machine_expected_provisions`. |
| `human_retrieved_passages_sufficient` | `yes`, `partly`, `no`, `n/a` | Could a careful reader answer the question from `machine_retrieved_top5` alone? Use `n/a` only when the expected outcome is not `retrieve`. |
| `human_jurisdiction_correct` | `yes`, `no`, `n/a` | Is everything Telangana law, with no Central or other-state text treated as Telangana's? |
| `human_instrument_correct` | `yes`, `no`, `n/a` | Is it the right instrument: TMVR, TMVTR, the Taxation Act, or the right G.O.? |
| `human_source_current_and_applicable` | `yes`, `no`, `unknown` | Is the provision in force today, in this form? |
| `human_supersession_checked` | `yes`, `no` | Did you check for a later G.O. or amendment? |
| `human_exceptions_or_conditions_missing` | Free text | Provisos, exemptions, conditions or definitions needed for a correct answer but not retrieved. |
| `human_missing_evidence` | Free text | Documents or provisions that should exist in the corpus but do not. |
| `human_should_be_refused` | `yes`, `no` | Should the assistant refuse or redirect instead of answering? |
| `human_comments` | Free text | Anything else, including why a label is wrong. |
| `reviewed_on` | `DD-MM-YYYY` | The date you reviewed the row. |
| `reviewer_name`, `reviewer_designation` | Your name and role | Required for any decision. Never filled in by anyone else. |

## How to assess a row

Work from the **original source document** (PDF or official page), not only from the passages in the CSV. Indexed text can contain extraction errors.

1. **Is the expected provision correct?** Read the question as a member of the public would mean it. Find the provision that actually governs it. Check that the expected provision is that one, and not a neighbouring rule with a similar heading. If several provisions are needed, list all of them. If the label lists provisions that are not needed, say so.
2. **Do the retrieved passages answer the question?** Ignore the rank numbers. Ask whether the five passages, read together, contain what is needed. A passage that only mentions the topic, or only cites another law, does not answer the question.
3. **Jurisdiction and instrument.** Telangana instruments only: TMVR 1989, TMVTR 1963, the Telangana Motor Vehicles Taxation Act and Telangana G.O.s.
   - A Telangana G.O. that *cites* a Central rule, such as CMVR Rule 167A, is not the Central rule's text.
   - "Rule 10" exists in both the TMVR and the TMVTR. Make sure the expected one matches what the question asks.
4. **Supersession and currency.** Check whether a later G.O. or Act amends, substitutes or omits the provision. The TMVR snapshots are consolidated web pages with no amendment dates, and are known to be out of date in places (for example Rule 217 amounts). G.O.Ms.No. 16/2026 amended the tax schedules. G.O.Ms.No. 24/2026 is a *draft* notification. If you cannot establish whether a provision is current, mark `human_source_current_and_applicable` = `unknown`.
5. **Exceptions and conditions.** A rule stated without its proviso, exemption or definition can mislead. Note anything a correct answer must include.
6. **Ambiguity.** If a reasonable reader could mean two different provisions ("What does Rule 10 say?", "What is the fee?"), the right outcome is a clarification question, not a guess.
7. **Should it be refused?** Penalties, fines and compounding amounts stay locked until separately approved. So do questions about Central law, other states, or material that is excluded or missing from the corpus. In those rows, check that refusal is the right outcome and that the label does not quietly expect an answer.

## Definitions

- **Correct retrieval:** every provision needed to answer the question correctly and completely, including its exceptions and conditions, is in the retrieved top five. Every one is the right jurisdiction and instrument, and nothing relied on is excluded or superseded.
- **Partially correct retrieval:** at least one needed provision is retrieved, but something needed is missing, such as a second rule, a proviso or a later amendment, or it is outranked by a misleading passage. An answer built from these passages could be incomplete.
- **Incorrect retrieval:** none of the needed provisions is retrieved. Or the passages relied on are the wrong jurisdiction or instrument, a neighbouring provision, excluded material, or superseded text.
- **Ambiguous question:** the question can reasonably refer to more than one provision or instrument, so it cannot be answered without asking the user. Record the candidate provisions in `human_comments`.
- **Missing legal source:** the provision or document needed to answer is not in the corpus. Examples: a TMVR rule number that is not indexed, the Central Motor Vehicles Rules, or an amendment G.O. that was never collected. Record what is missing in `human_missing_evidence`.
- **Legally unverified:** a source whose text, currency or authority has not been confirmed against an official publication by a qualified reviewer. **All 20 corpus documents are legally unverified today.** A `correct` benchmark decision does not change that. Legal verification of the corpus is recorded separately, in a signed approval record.

## Rules for reviewers

- Do not edit `machine_*` or `audit_notes` columns, and do not change `reviewer_status` yourself. The engineering team applies your decisions to the benchmark JSON and keeps the original machine labels for comparison.
- Every decision needs `reviewed_on`, `reviewer_name` and `reviewer_designation`. A row without them counts as unreviewed.
- If you are unsure, use `partially_correct` or `unknown` and explain why. Do not use `correct`.
- Review in priority order. Groups 1 to 3 are where machine labels are most likely to be wrong (see `REVIEW-PRIORITY.md`).

## Submitting a review

1. Copy `eval/telangana-retrieval-review.csv` and name the copy after yourself (for example `review-<name>.csv`). Fill in only the `human_*`, `reviewed_on`, `reviewer_name` and `reviewer_designation` columns. You may review some rows and leave others completely empty: an empty row is counted as unreviewed. A row with only some fields filled is rejected.
2. Do not add, remove, rename or reorder columns, and do not delete rows. Spreadsheet programs may add a byte-order mark or change line endings; that is accepted. Any other change to a `machine_*` column, `question`, `category`, `audit_notes` or `reviewer_status` rejects the whole file.
3. Every reviewed row needs:
   - a value in each multiple-choice field (see the table above);
   - your name, designation and a `DD-MM-YYYY` date (not in the future, and not before 09-11-2026);
   - `human_comments` when the decision is `partially_correct`, `incorrect`, `ambiguous` or `missing_source`;
   - `human_missing_evidence` when the decision is `missing_source`.
4. In `human_correct_expected_provisions`, write each provision as `document :: provision`, separated by `;`, for example `tmvr-1989-chap-8 :: Rule 437; tmvtr-1963 :: Rule 13A`. Each must exist in the index, and must not be a provision whose text is excluded (for example the G.O. 24/2026 draft or the G.O. 53/2025 schedules).
5. Send the file to the engineering team. They run:

   ```bash
   python -m backend.review_import validate review-<name>.csv
   ```

   which lists every problem by question ID. Fix the listed problems and send the file again.

### What happens to your decisions

- `python -m backend.review_import reconcile <files...> --out <candidate.json>` combines every valid submission into a **separate** candidate file. The benchmark JSON and this CSV are never modified.
- For each question, the candidate file keeps the original machine case unchanged, every reviewer's decision with name, designation, date and the submission's hash, and your comments exactly as written.
- Each question is marked `unreviewed`, `partially_reviewed` (fewer reviewers than required), `reviewed` (enough reviewers, same decision) or `disputed` (different decisions). Field-level differences, such as one reviewer answering `yes` and another `unknown`, are listed even when the decisions agree.
- A disputed question is never resolved automatically. It stays `pending_human_review` until the reviewers agree.
- Corrected expected provisions are recorded as proposals only. Engineering applies them to the benchmark in a separate, deliberate change.
- Only an agreed `correct` or `incorrect` becomes a *proposed* `human_confirmed` or `human_rejected` status. None of this is legal approval of the corpus or of any answer.

### Duplicate chunk ID

Two different G.O.Ms.No. 53/2025 chunks share the benchmark chunk ID `go-ms-53-2025-trb::SCHEDULE::part1of1`: one on page 4, and one on pages 4–5. Both are excluded from answers. Use the location to tell them apart. The candidate file gives each chunk an unambiguous reference: chunk ID, location and a hash of the chunk text (`eval/telangana-chunk-references.json`).
