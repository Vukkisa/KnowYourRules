# Stage 4D: driving-licence retrieval recall (Rule 6)

Data and scripts: `eval/latency/stage4d/` (`licence_probe.py`, `retrieval_variants.py`, and their JSON outputs, one per
vector mode). Index: a throw-away copy of the real 590-chunk index. No legal source text, approval state, withheld
flag, provider priority, validator threshold or provider setting was touched. No caching.

## 0. Two corrections to the brief (mine, from Stage 4C)

1. **Rule 6 does not state licence requirements.** Its heading is "Lincensing authority may make enquiries" (the typo is
   in the source). Its text: on receiving "an application for a driving Licence or for an authorization to drive a
   transport vehicle" the licensing authority "may make such enquiries as may reasonably be necessary to establish the
   identity of the applicant and to ascertain that the applicant is not disqualified". I called it "the application
   text" in Stage 4C; that overstated it. I searched all chunks: **the Telangana corpus has no provision listing the
   requirements for getting a driving licence** (those are in the Central Motor Vehicles Rules, which are not stored).
   For "What are the requirements for getting a driving licence?" the honest answer is a refusal, and Rule 6 is at most
   background.
2. **The benchmark has no general licence-application question.** The questions in play were the Stage 4 live
   question ("What are the requirements for getting a driving licence in Telangana?") and the probe question ("How do
   I apply for a learner's licence in Telangana?"). I used both as the "original" questions.

## 1. Reproduction (exact and HNSW, same results on every probe question)

Settings: hybrid retrieval, `RETRIEVE_K=6`, distance gate `MAX_DISTANCE=0.8` (squared L2), 590 chunks.
Rule 6's position in each stage (the chunk exists, is `answer_eligible`, and has correct metadata):

| Question | Vector rank (distance) | BM25 rank | Final rank |
|---|---|---|---|
| What are the requirements for getting a driving licence? | 22 (0.413; top-6 cut 0.370) | none | none |
| How do I apply for a learner's licence? | 7 (0.451) | none | none |
| How do I apply for a driving licence? | 6 (0.395) | none | none |
| **What happens after I submit a driving licence application?** | **3 (0.398)** | none | **none** |
| Can the licensing authority make enquiries about my identity when I apply…? | 1 (0.314) | 1 | 1 |
| What does Rule 6 … say? | not in vector top-6 | 1 (lookup) | 1 |

## 2. Diagnosis

| Suspect | Finding |
|---|---|
| Distance gate / thresholds | Not a factor: every candidate is ≤ 0.46, the gate is 0.8. |
| Chunk text, metadata, numbering, heading | Correct: `Rule 6`, `answer_eligible: true`, one whole chunk (474 chars), approved source. |
| Evidence-eligibility filters | Not a factor: Rule 6 passes state, approval and eligibility filters when it is reached. |
| Exact vs HNSW | Identical top-6 and identical final lists for all probe questions. |
| Query embedding | Behaves sensibly: "requirements" questions land nearest Rules 62, 45, 7 (0.33–0.34), and Rule 6 is 22nd because its content (enquiries) does not match "requirements". |
| **Fusion** | **Root cause for the one real miss.** |

**Root cause.** For "What happens after I submit a driving licence application?", Rule 6 is the vector search's 3rd
hit but has no BM25 vote. Reciprocal-rank fusion scores it 1/63. Two chapter-12 fee chunks that match only on generic
words ("application", "licence") are BM25 ranks 2 and 3: Rule 477 (1/62) outranks it, and Rule 486 (1/63) ties with it
and wins because ties keep first-seen order and the BM25 list is fused before the vector list. With six slots filled by
Rules 5, 25, 14, 8, 477 and 486, Rule 6 is 7th and is cut.

This is not a general recall problem. Six further paraphrases that I did not use to design anything all retrieved
Rule 6 at rank 1 or 2 even without the fix. The miss is narrow: 1 of 12 Rule 6 phrasings tried.

## 3. Alternatives compared

Fixed licence set `eval/licence-retrieval-set.json` (16 questions: 6 where Rule 6 answers, 3 corpus-gap, 7 unrelated
licence questions) plus the 108-question retrieval benchmark. **The 16 labels are mine and not human-reviewed**
(see the file's `labelling`). `must-recall` is over the 12 questions with a required provision. `set-prec` is the share
of the 6 returned chunks that are required or related (low in absolute terms because few provisions exist per topic).
Exact and HNSW gave the same table.

| Variant | must-recall | set-prec | must-exclude hits | bench hit@5 | MRR | recall@5 | leak | bench answers changed |
|---|---|---|---|---|---|---|---|---|
| V0 baseline | 11/12 | 0.281 | 0 | 1.000 | 0.8907 | 0.9726 | 0 | 0 |
| V1 k = 8 | 12/12 | 0.227 | 0 | 1.000 | 0.8939 | 0.9684 | 0 | 106 |
| V2 vector weight ×2 | 11/12 | 0.281 | 0 | 0.987 | 0.8949 | 0.9473 | 0 | 99 |
| V3 protect vector top-2 | 11/12 | 0.281 | 0 | 1.000 | 0.8907 | 0.9726 | 0 | 1 |
| V4 protect vector top-3 | 12/12 | 0.292 | 0 | 1.000 | 0.8907 | 0.9726 | 0 | 8 |
| V5 strip "in Telangana" from the query | 12/12 | 0.302 | 0 | 1.000 | 0.8992 | 0.9684 | 0 | 10 |
| V7 12 candidates, final 6 | 12/12 | 0.302 | 0 | 1.000 | 0.8854 | 0.9557 | 0 | 67 |
| V8 tie-break toward vector list | 12/12 | 0.292 | 0 | 1.000 | 0.9055 | 0.9684 | 0 | 82 |
| V11 protect top-4 unless exact lookup | 12/12 | 0.292 | 0 | 1.000 | 0.8907 | 0.9684 | 0 | 26 |
| **V10 protect top-3 unless exact lookup (adopted)** | **12/12** | **0.292** | **0** | **1.000** | **0.8907** | **0.9726** | **0** | **1** |

- Raising top-k (V1) also fixes it, but it hands the model two more chunks for every question and lowers precision. It
  changes 106 of 108 answers.
- V5 and V8 raise MRR but lower recall@5 and rewrite 10 and 82 answers. Whether that trade is good needs the
  human-reviewed benchmark, so they are not adopted.
- V4 (protect always) swapped noise for noise on 7 explicit "What does Rule N say?" questions, so V10 skips the guard
  when a structured rule lookup matched.

## 4. Change made (V10)

`hybrid_retrieval.protect_vector_leaders()`: the vector search's 3 best chunks stay in the final 6 unless an exact rule
lookup matched. Only chunks that fusion already accepted and that passed every filter can be restored, so the guard
cannot bring back a withheld, unapproved or other-state chunk. `RAG_VECTOR_PROTECT` (default 3, `0` = off) is the
switch.

Effect on the 108 benchmark questions: one answer changes (TG-PQ-023, conductor's licence education: Rule 69 → Rule 55;
neither is an expected provision). Metrics are identical to baseline and nothing leaks. On the licence set it changes
three answers: LIC-001 gains Rule 6 (the fix, replacing Rule 486), and LIC-008 and LIC-012 swap one unrelated chunk
(Rule 425 → 47, Rule 69 → 55). Nothing in the "must exclude" lists was introduced.

Files: `backend/hybrid_retrieval.py` (guard + env parser), `backend/server.py` (`retrieve()`, `VECTOR_PROTECT`),
`eval/licence-retrieval-set.json` (new), `tests/test_licence_retrieval.py` (new), `tests/licence_retrieval_probe.py`
(new). Backups: `heading-fusion-originals/{server,hybrid_retrieval}.py.pre-stage4d`.

## 5. Tests and results

`tests/test_licence_retrieval.py` has 8 offline unit tests of the guard (restore, no-op, off switch, filtered leader
never re-added, protected chunks not evicted, size ≤ k, duplicates, env parsing), 3 set-integrity tests, and 8
real-backend tests that run both exact and HNSW in every invocation:
- Rule 6 is retrieved for all 6 questions it answers, and every `must_include` is retrieved;
- the 6 unrelated licence questions with a Rule 6 exclusion never retrieve it (or any other `must_exclude` item);
- the unguarded run misses Rule 6 on LIC-001 (documents the root cause);
- every retrievable benchmark question still gets an expected provision;
- no withheld or benchmark-excluded chunk is retrieved, over the whole benchmark and the licence set;
- exact and HNSW agree on every licence question.

Full suites (exact and HNSW): **offline 907 tests, OK (11 skipped); real backend 926 tests, OK.** Before: 888 and 907.
One run failed because my first draft of an env-parsing test imported the real `backend.server` into the offline
suite and broke an existing test; I moved the parser into `hybrid_retrieval.py` so tests never import the server.

## 6. Limitations

- **Thin margin.** `3` was chosen because Rule 6 is the vector search's 3rd hit for the failing question. 2 does not
  fix it; 4 lowers recall@5 and rewrites 26 answers. The guard prevents one failure mode, not a recall guarantee. It
  was developed against one failing case and 16 unreviewed labels.
- **No gain is demonstrable on held-out phrasings**, because the baseline already hit them.
- **"Requirements" and "how do I apply" questions still do not retrieve Rule 6** (vector ranks 22 and 6). That is
  correct: Rule 6 does not state requirements. These questions will keep ending in a refusal until the Central rules
  are added to the corpus, which is a source and legal-review decision, not a retrieval one.
- **HNSW varies between opens** of identical copies (Stage 15). On the benchmark, 0–3 of 108 questions differ from
  exact between runs, with or without the guard (TG-MP-001 or TG-OS-005 in my runs), so the suite asserts exact/HNSW
  agreement on the licence set only. The licence set agreed in every run I made.
- The guard is skipped when an exact rule lookup matched, and it applies only in hybrid mode.
- No live provider was called, so the end-to-end answer for these questions was not re-measured.
