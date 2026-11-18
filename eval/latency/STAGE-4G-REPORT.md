# Stage 4G: provider compatibility and validator robustness

Outcome: **Rule 6 correction tightened, two false-positive families narrowly cleared, one real defect fixed (curly
apostrophe), provider compatibility verified with mocks.** No live provider was called (no Groq, Gemini or Ollama
generation; Ollama was used only for retrieval embeddings, as in earlier stages). Nothing is staged or committed.
Raw outputs: `eval/latency/stage4g/`.

## 1. Stage 4F mask was too permissive (fixed)
The 4F mask accepted any "negated copula + disqualified" form once the cited passage had *some* such construction.
That let a model change the logic: "is not disqualified **or is** liable to be disqualified" (a different clause
structure from Rule 6) or "has not been disqualified" were neutralised on the strength of Rule 6's different wording.

Fix (`backend/eligibility_status.py`): a span is neutralised only if the **same normalised span** (case-insensitive,
curly apostrophe and contraction expanded) appears in a cited passage. A shorter claim span is supported by a longer
source span only when the source continues with " or ..." (head of the same clause). Anything else is left in place and
the unchanged penalty check rejects it. The user-question lock and `answer_drift_reason` are untouched.

## 2. Rule 6 wording matrix
Rule 6 reads: "...to ascertain that the applicant is not disqualified or liable to be disqualified for holding a Licence."
Two things are pinned independently, because the penalty gate runs last and grounding errors hide it
(`tests/test_rule6_paraphrases.py`, raw: `paraphrase_matrix.json`).

| Wording | Penalty gate | Accepted as interpretation claim | Why |
|---|---|---|---|
| Restates the sentence, with tail | clear | **yes** | Same span as source; claim restates the sentence; negation preserved |
| Restates the sentence, head only | clear | **yes** | "is not disqualified" is the head of the source's span |
| Contraction "isn't" / "isn’t" | clear | **yes** | Normalised to the source span; negation recognised (fix in section 4) |
| Exact short "The applicant is not disqualified." | clear | no | Penalty-clear, but the meaning layer sees 'negated' vs source 'prohibition'/modal; a direct claim must restate a whole sentence |
| Short with tail (same) | clear | no | Same reason |
| "does not fall under a disqualification" | **locked** | no | Noun form; not the source's wording |
| "eligible from the disqualification standpoint" | **locked** | no | Noun form, and an eligibility conclusion the source does not state |
| "has not been disqualified" | locked | no | Different tense; not in source |
| "must not be disqualified" | locked | no | Changes modality |
| "not disqualified or is liable to be disqualified" | locked | no | Inserted "is"; different logic |
| "is not currently disqualified" | locked | no | Added word; not in source |
| "is **not** disqualified" (markdown) | locked | no | Breaks the phrase; fails closed |
| "is disqualified" (non-negated) | locked | no | Penalty content |
| negated status plus "so the licence will be granted" | clear | no | Unsupported consequence caught by grounding, not the penalty gate |
| negated status plus "otherwise the licence is suspended" | locked | no | Penalty wording beside the status |

Citation validity: unknown evidence id rejected; the Rule 6 wording cited to a different passage (Rule 437) is both
ungrounded and **not** masked; citing Rule 6 alone is accepted even with unrelated passages in context.

No wording is accepted merely for being similar. Everything newly accepted is wording Rule 6 itself contains.

## 3. "Custody of badge" and "liable to indemnify"
Traced triggers: `custody` is in `PENALTY_STRONG` (meant for police detention); `liable\s+to` is in `CONSEQUENCE_STRONG`
(meant for legal liability). Both also occur in ordinary senses.

New `backend/benign_wording.py`, same evidence-bound design: a span is masked only when the identical normalised span is
in a cited passage. Two families only:
- possession: "[safe] custody [and production|delivery] of [the] badge(s) / trip-sheet(s) / luggage"
- physical: "liable to foul / injure / be over-turned"

Cleared on the real index (11 sentences change from locked to clear; `corpus_penalty_verdict_changes.json`):
Rules 6 and 52 (4F), 40, 70 (badge), 74, 185, 271 (luggage, trip-sheets), 201, 343, 327, 328 (physical).

**Left locked on purpose** (genuine or ambiguous legal sense): "liable to indemnify" (Rule 297, civil liability), liable
to pay / make good / convicted / suspended / disqualified / tax, and custody in the enforcement sense (Rules 13B, 297
agent custody, 405, 407, 408, 448A: police removal to "safe custody"). Penalty words beside a cleared phrase still lock
the answer (fine, seized, suspended, offence tested).

Decision on "liable to indemnify": **not a defect to fix now.** It is civil liability for loss of goods, but it is a legal
consequence of the kind the guard exists to hold; clearing it needs counsel, not a pattern.

## 4. Curly apostrophe (real defect)
`meaning_checks._NEG_RE` did not treat "isn’t" as a negation, so a faithful restatement was rejected ("claim reads as
'permission' but the cited sentence reads as 'prohibition'"). Fixed with `n['’]t\b`. Verified that dropping the negation
is still rejected and a curly negation against a non-negated source is still a mismatch.

## 5. Provider compatibility (mocked HTTP, real abstraction, real index copy)
`tests/rule6_provider_probe.py`: real `/chat`, retrieval, context assembly, validator, `ProviderOrchestrator`, request
builders, response extraction, error classification and retries. Only provider HTTP is faked. Identical in exact and HNSW
(`provider_exact.json`, `provider_hnsw.json`).

| Style (each of Groq, Gemini, Ollama alone) | Result |
|---|---|
| verbatim; with whitespace; restated; contraction; non-breaking space | **answer**, 1 cited source, source warning present |
| markdown-bold "**not**"; noun "does not fall under a disqualification"; penalty sentence beside the status | `no_support`, `penalty content withheld (penalty_term)` |
| fenced ```` ```json ````; prose-wrapped JSON | `no_support`, `malformed JSON` (fails closed) |
| honest refusal | `no_support`, not retried elsewhere |
| Gemini with a `thought` part | answer; thought part not used |

Chain behaviour: Groq quota -> Gemini (`groq: quota_exhausted`); Groq 503 -> retry -> Gemini; Groq and Gemini quota ->
Ollama; all down -> `unavailable`. A validation-rejected candidate gets exactly one validated candidate from the next
provider (both are validated; `groq: validation_rejected`); two rejections -> `no_support`, Ollama not asked. Rule 6 is in
every request; the Third Schedule is never sent.

## 6. Tests and regression (logs in `stage4g/suite_*.log`)
| Suite | Exact | HNSW | Stage 4F |
|---|---|---|---|
| Offline full | 963 OK (27 skipped, 1 expected failure) | 963 OK (27 skipped, 1 expected failure) | 936 OK (19 skipped) |
| Real backend (index copy) | 982 OK (1 expected failure) | 982 OK (1 expected failure) | 955 OK |
| `test_eligibility_status.py` | 22 OK | same file | 21 |
| `test_benign_wording.py` (new) | 10 OK | same file | n/a |
| `test_rule6_paraphrases.py` (new) | 8 OK (1 expected failure) | same file | n/a |
| `test_grounded_answer.py` | 53 OK | same file | 53 |
| `test_meaning_checks.py` | 22 OK | same file | unchanged |
| `test_licence_retrieval.py` (both modes inside) | 19 OK | | 19 |

Changed assertions: `SUPPORTED_FORMS` in `test_eligibility_status.py` now lists only wording Rule 6 contains; forms the old
mask over-accepted moved to `NOT_IN_RULE6` as rejections (intended, documented in the file).

## 7. Remaining legal and technical uncertainties
1. **Counsel sign-off still outstanding** for both masks (4F status wording, 4G ordinary-sense wording). Each is isolated;
   revert by removing the `mask` calls in `grounded_answer.validate` (one expression).
2. **Known gap, pinned with `expectedFailure`:** "The applicant is eligible to hold a licence." is accepted as an
   interpretation of Rule 6. It has no penalty wording; the meaning layer's 50% overlap lets it through. Rule 6 says the
   authority may *enquire* whether the applicant is disqualified, not that eligibility follows. Not fixed: raising the
   interpretation threshold affects every provision.
3. Fenced or prose-wrapped JSON and markdown-bold negations fail closed. Never observed live; no leniency added.
4. "Liable to indemnify", liable to pay/make good, and enforcement custody remain locked (section 3).
5. Mocked bodies are built from the evidence actually sent. How live Groq, Gemini and Ollama phrase Rule 6 is still
   untested; the Gemini live benchmark stays blocked until quota is confirmed.
6. Rule 6 text comes from an unofficial web copy; the source-status warning still appears.

## Files
Modified: `backend/grounded_answer.py` (import + penalty-input expression), `backend/meaning_checks.py` (`_NEG_RE`),
`backend/eligibility_status.py` (verbatim-support rule), `tests/test_eligibility_status.py`.
New: `backend/benign_wording.py`, `tests/test_benign_wording.py`, `tests/test_rule6_paraphrases.py`,
`tests/rule6_provider_probe.py`, `tests/test_rule6_provider_compat_real.py`, `eval/latency/STAGE-4G-REPORT.md`,
`eval/latency/stage4g/`, backups `eval/legal-validation/heading-fusion-originals/{eligibility_status,meaning_checks}.py.pre-stage4g`
and `test_eligibility_status.py.pre-stage4g`.
Reproduce: `RAG_VECTOR_SEARCH=exact|hnsw TG_DB_DIR=<index COPY> GROQ_API_KEY=offline-probe-not-real python3 tests/rule6_provider_probe.py`.
