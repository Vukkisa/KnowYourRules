# Real-model evaluation: grounded answers

> All evaluation passages are SYNTHETIC test text (eval/answer-quality/fixtures.json), not Telangana legal provisions. These results do not measure legal correctness on real Telangana legal provisions. Validator acceptance does not prove legal correctness; legal meaning preservation needs manual review.

## 1. Configuration

| Setting | Value |
|---|---|
| mode | real |
| model | openai/gpt-oss-120b |
| temperature | 0.0 |
| seed | 7 |
| json_mode | True |
| max_completion_tokens | 4096 |
| max_calls | 1 |
| max_total_tokens | 10000 |
| timeout_s | 60.0 |
| price_in_per_mtok | None |
| price_out_per_mtok | None |
| cases_file | eval/real-model/cases.json |
| run_at_utc | 2026-11-10 17:40 |

JSON mode reason: grounded_answer.ANSWER_INSTRUCTIONS says 'Respond with ONE JSON object and nothing else' and parse_response() applies json.loads to the raw text with no cleanup.

Execution path: server.chat -> grounded_answer_question (follow-up and penalty guards) -> fixed synthetic retrieval -> grounded_answer.answer (evidence contract, prompt, generator call, validate, at most one conflict retry, validate) -> backend rendering and citations. Approval gate forced open for the run only; no approval record is read or written.

## 2. Cases

1 model cases and 0 no-model guard checks.

| Model-case status | Count |
|---|---|
| completed | 1 |
| provider_rejected_output | 0 |
| truncated | 0 |
| api_failed | 0 |
| incomplete | 0 |
| not_run | 0 |

completed = the model response reached the validator. provider_rejected_output = the provider refused the model's output (e.g. invalid JSON in JSON mode). truncated = output cut at the token limit. api_failed = infrastructure failure (timeout, network, authentication, rate limit, server). incomplete / not_run = stopped by the call limit, token budget or repeated infrastructure failures.

## 3. Model-case results among cases with a scorable response (1 of 1)

| Measure | Result |
|---|---|
| Expected-outcome agreement | 1/1 (100%) |
| First-pass validator acceptance | 1/1 (100%) |
| Final validator acceptance | 1/1 (100%): 1 substantive (answer or conflict), 0 accepted refusal or clarification |
| Retry frequency | 0/1 (0%) |
| Retry success (accepted after retry) | n/a (0 cases) |
| Citation correctness (answers and conflicts) | 1/1 (100%) |
| Condition/exception words preserved in claim text (lexical; cases with a condition) | 1/1 (100%) |
| Content words of required positions in claim text (lexical; cases with such words) | n/a (0 cases) |

## 4. Overall model-case achievement (all 1 model cases)

**Achieved: 1/1 (100%)**

| Not achieved | Count |
|---|---|
| expectation_failed | 0 |
| truncated | 0 |
| provider_rejected_output | 0 |

| Not scorable (counted in the denominator above, shown separately) | Count |
|---|---|
| infrastructure_failure | 0 |
| incomplete | 0 |
| not_run | 0 |

## 5. No-model guard checks

| | Result |
|---|---|
| Checks | 0 |
| Passing | 0 |
| Unexpected model calls | 0 |
| Not run | 0 |

## 6. Calls, latency, tokens, cost

| Measure | Result |
|---|---|
| Model calls by status | 1 {'ok': 1} |
| Latency per call (s) | {'mean': 1.378, 'median': 1.378, 'max': 1.378} |
| Tokens | {'prompt_tokens': 801, 'completion_tokens': 390, 'total_tokens': 1191} |
| Estimated cost (USD) | not estimated (no prices given or no usage reported) |

Validator acceptance, citation correctness, lexical condition-word and content-word checks and expected-behaviour agreement are measured automatically. Legal meaning preservation is NOT measured: it is listed per case as pending manual review.

## 7. Case by case

| Case | Purpose | Status | Calls | Retry | First | Final | Outcome | Citations | Expected |
|---|---|---|---|---|---|---|---|---|---|
| RG-04 | condition_must_be_kept | completed | 1 | no | accepted | accepted | answer | ok | yes |

### Failures and unscored cases

None.

### Full records

<details><summary><b>RG-04</b> - condition_must_be_kept - completed - outcome answer</summary>

**Question:** Can a learner drive a motor car?  
**History turns:** 0

**Retrieved (synthetic):**

- E1 `learner` (Rule 305): Synthetic Rule 305. A learner may drive a motor car, provided that a licensed instructor sits beside the learner.

**Expected:** outcomes ['answer']; required ['E1'], permitted ['E1'], excluded []; condition words ['licensed instructor sits beside']; content words []; retry None; model calls None  
**Why:** E1 permits it only with the proviso that a licensed instructor sits beside the learner (instructions rule 4).

- call 1: status ok, latency 1.378 s, usage {'prompt_tokens': 801, 'completion_tokens': 390, 'total_tokens': 1191}, finish stop

**First response:**
```
{
 "answer": "A learner may drive a motor car provided that a licensed instructor sits beside the learner.",
 "evidence_sufficiency": "sufficient",
 "claims": [
  {
   "text": "A learner may drive a motor car provided that a licensed instructor sits beside the learner.",
   "kind": "direct",
   "evidence_ids": [
    "E1"
   ]
  }
 ],
 "citations": [
  "E1"
 ],
 "refusal_reason": null,
 "clarification_question": null
}
```
**First validation:** {'accepted': True, 'errors': [], 'checks': []}

**Retry:** not triggered - not eligible: first response accepted

**Final validation:** {'accepted': True, 'errors': [], 'checks': []}

**Pipeline errors:** none

**Displayed answer:**
```
A learner may drive a motor car provided that a licensed instructor sits beside the learner. [1]

Cited:
[1] Synthetic fixture document, Rule 305 (synthetic/synthetic-tmvr#Rule 305)
```
**Final claims:** ['A learner may drive a motor car provided that a licensed instructor sits beside the learner.']  
**Final citations:** ['E1']  
**Citation check:** {'missing_required': [], 'outside_permitted': [], 'excluded_cited': [], 'correct': True}  
**Condition words:** {'required': ['licensed instructor sits beside'], 'missing': [], 'preserved': True}  
**Content words:** None  
**Legal meaning:** not assessed (synthetic passages; manual review required for any real-text claim)  
**Manual review:** pending  
**Expected behaviour achieved:** True 

</details>

## 8. Limitations and recommendations

- Synthetic passages only: no result here speaks to real Telangana provisions or legal correctness.
- Expected behaviour is engineering expectation derived from the synthetic text, not a reviewed legal reference answer; no human-reviewed cases exist yet (all retrieval-review rows are pending).
- Condition-word and content-word checks are lexical (exact words); a faithful paraphrase fails them and an answer can contain the words with the meaning changed. Manual review is required before drawing conclusions.
- Retrieval is fixed per case, so retrieval quality is not measured.
- One run at temperature 0 with a fixed seed is not a reliability estimate; provider output can still vary between runs.
- The Groq adapter exists only in this runner; the server's grounded mode still uses DisabledGenerator.
- Recommendation: before any real-text run, have reviewers fill the human-review sheet and turn reviewed rows into cases with their own required and permitted citations.

