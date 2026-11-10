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
| max_calls | 28 |
| max_total_tokens | 150000 |
| timeout_s | 60.0 |
| price_in_per_mtok | None |
| price_out_per_mtok | None |
| cases_file | eval/real-model/cases.json |
| run_at_utc | 2026-11-10 17:45 |

JSON mode reason: grounded_answer.ANSWER_INSTRUCTIONS says 'Respond with ONE JSON object and nothing else' and parse_response() applies json.loads to the raw text with no cleanup.

Execution path: server.chat -> grounded_answer_question (follow-up and penalty guards) -> fixed synthetic retrieval -> grounded_answer.answer (evidence contract, prompt, generator call, validate, at most one conflict retry, validate) -> backend rendering and citations. Approval gate forced open for the run only; no approval record is read or written.

## 2. Cases

14 model cases and 2 no-model guard checks.

| Model-case status | Count |
|---|---|
| completed | 7 |
| provider_rejected_output | 0 |
| truncated | 0 |
| api_failed | 3 |
| incomplete | 0 |
| not_run | 4 |

completed = the model response reached the validator. provider_rejected_output = the provider refused the model's output (e.g. invalid JSON in JSON mode). truncated = output cut at the token limit. api_failed = infrastructure failure (timeout, network, authentication, rate limit, server). incomplete / not_run = stopped by the call limit, token budget or repeated infrastructure failures.

## 3. Model-case results among cases with a scorable response (7 of 14)

| Measure | Result |
|---|---|
| Expected-outcome agreement | 4/7 (57%) |
| First-pass validator acceptance | 4/7 (57%) |
| Final validator acceptance | 4/7 (57%): 4 substantive (answer or conflict), 0 accepted refusal or clarification |
| Retry frequency | 0/7 (0%) |
| Retry success (accepted after retry) | n/a (0 cases) |
| Citation correctness (answers and conflicts) | 4/4 (100%) |
| Condition/exception words preserved in claim text (lexical; cases with a condition) | 3/3 (100%) |
| Content words of required positions in claim text (lexical; cases with such words) | 1/1 (100%) |

## 4. Overall model-case achievement (all 14 model cases)

**Achieved: 4/14 (29%)**

| Not achieved | Count |
|---|---|
| expectation_failed | 3 |
| truncated | 0 |
| provider_rejected_output | 0 |

| Not scorable (counted in the denominator above, shown separately) | Count |
|---|---|
| infrastructure_failure | 3 |
| incomplete | 0 |
| not_run | 4 |

## 5. No-model guard checks

| | Result |
|---|---|
| Checks | 2 |
| Passing | 0 |
| Unexpected model calls | 0 |
| Not run | 2 |

## 6. Calls, latency, tokens, cost

| Measure | Result |
|---|---|
| Model calls by status | 10 {'ok': 7, 'rate_limited_http_429': 3} |
| Latency per call (s) | {'mean': 1.168, 'median': 1.482, 'max': 2.591} |
| Tokens | {'prompt_tokens': 5956, 'completion_tokens': 3213, 'total_tokens': 9169} |
| Estimated cost (USD) | not estimated (no prices given or no usage reported) |

Validator acceptance, citation correctness, lexical condition-word and content-word checks and expected-behaviour agreement are measured automatically. Legal meaning preservation is NOT measured: it is listed per case as pending manual review.

## 7. Case by case

| Case | Purpose | Status | Calls | Retry | First | Final | Outcome | Citations | Expected |
|---|---|---|---|---|---|---|---|---|---|
| RG-01 | direct_conflict | completed | 1 | no | accepted | accepted | conflict | ok | yes |
| RG-02 | rule_with_specific_exemption | completed | 1 | no | rejected | rejected | rejected | - | NO |
| RG-03 | one_sided_omits_qualifying_evidence | completed | 1 | no | rejected | rejected | rejected | - | NO |
| RG-04 | condition_must_be_kept | completed | 1 | no | accepted | accepted | answer | ok | yes |
| RG-05 | general_rule_with_override | completed | 1 | no | rejected | rejected | rejected | - | NO |
| RG-06 | condition_must_be_kept | completed | 1 | no | accepted | accepted | answer | ok | yes |
| RG-07 | exception_must_be_kept | completed | 1 | no | accepted | accepted | answer | ok | yes |
| RG-08 | one_sided_omits_qualifying_evidence | api_failed | 1 | no | - | - | rejected | - | - |
| RG-09 | condition_must_be_kept | api_failed | 1 | no | - | - | rejected | - | - |
| RG-10 | control_no_retry | api_failed | 1 | no | - | - | rejected | - | - |
| RG-11 | control_no_retry | not_run | 0 | no | - | - | - | - | - |
| RG-12 | insufficient_evidence | not_run | 0 | no | - | - | - | - | - |
| RG-13 | insufficient_evidence | not_run | 0 | no | - | - | - | - | - |
| RG-14 | follow_up_restated | not_run | 0 | no | - | - | - | - | - |
| RG-Z1 | vague_follow_up | not_run | 0 | no | - | - | - | - | - |
| RG-Z2 | penalty_restriction | not_run | 0 | no | - | - | - | - | - |

### Failures and unscored cases

- **RG-02** (completed): outcome rejected not in expected ['answer', 'conflict']
- **RG-03** (completed): outcome rejected not in expected ['answer', 'conflict']
- **RG-05** (completed): outcome rejected not in expected ['answer']
- **RG-08** (api_failed): not scored: case api_failed
- **RG-09** (api_failed): not scored: case api_failed
- **RG-10** (api_failed): not scored: case api_failed
- **RG-11** (not_run): not run: 3 consecutive infrastructure failures
- **RG-12** (not_run): not run: 3 consecutive infrastructure failures
- **RG-13** (not_run): not run: 3 consecutive infrastructure failures
- **RG-14** (not_run): not run: 3 consecutive infrastructure failures
- **RG-Z1** (not_run): not run: 3 consecutive infrastructure failures
- **RG-Z2** (not_run): not run: 3 consecutive infrastructure failures

### Full records

<details><summary><b>RG-01</b> - direct_conflict - completed - outcome conflict</summary>

**Question:** Must the keeper of a test registry stamp the test card in blue ink?  
**History turns:** 0

**Retrieved (synthetic):**

- E1 `fictional_stamp_must` (Fictional Clause A): Synthetic Clause A, fictional test text. The keeper of a test registry shall stamp the test card in blue ink.
- E2 `fictional_stamp_must_not` (Fictional Clause B): Synthetic Clause B, fictional test text. The keeper of a test registry shall not stamp the test card in blue ink.

**Expected:** outcomes ['conflict']; required ['E1', 'E2'], permitted ['E1', 'E2'], excluded []; condition words []; content words ['blue ink', 'shall not stamp']; retry None; model calls None  
**Why:** Fictional pair: E1 and E2 have the same actor (the keeper of a test registry), the same action and object (stamp the test card in blue ink) and no condition or scope limit; E1 requires it and E2 prohibits it, and neither says it prevails. The instructions (rule 9) require 'conflicting', one claim per side citing its own passage; an answer that picks one side is not acceptable.

- call 1: status ok, latency 1.702 s, usage {'prompt_tokens': 888, 'completion_tokens': 476, 'total_tokens': 1364}, finish stop

**First response:**
```
{
 "answer": "The keeper of a test registry shall stamp the test card in blue ink. [E1] The keeper of a test registry shall not stamp the test card in blue ink. [E2]",
 "evidence_sufficiency": "conflicting",
 "claims": [
  {
   "text": "The keeper of a test registry shall stamp the test card in blue ink.",
   "kind": "direct",
   "evidence_ids": [
    "E1"
   ]
  },
  {
   "text": "The keeper of a test registry shall not stamp the test card in blue ink.",
   "kind": "direct",
   "evidence_ids": [
    "E2"
   ]
  }
 ],
 "citations": [
  "E1",
  "E2"
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
The Telangana documents I have conflict on this, so this is not a definitive answer. Each source says:
- The keeper of a test registry shall stamp the test card in blue ink. [1]
- The keeper of a test registry shall not stamp the test card in blue ink. [2]

Cited:
[1] Synthetic fixture document, Fictional Clause A (synthetic/synthetic-fictional-registry#Fictional Clause A)
[2] Synthetic fixture document, Fictional Clause B (synthetic/synthetic-fictional-registry#Fictional Clause B)
```
**Final claims:** ['The keeper of a test registry shall stamp the test card in blue ink.', 'The keeper of a test registry shall not stamp the test card in blue ink.']  
**Final citations:** ['E1', 'E2']  
**Citation check:** {'missing_required': [], 'outside_permitted': [], 'excluded_cited': [], 'correct': True}  
**Condition words:** None  
**Content words:** {'required': ['blue ink', 'shall not stamp'], 'missing': [], 'preserved': True}  
**Legal meaning:** not assessed (synthetic passages; manual review required for any real-text claim)  
**Manual review:** pending  
**Expected behaviour achieved:** True 

</details>

<details><summary><b>RG-02</b> - rule_with_specific_exemption - completed - outcome rejected</summary>

**Question:** Must riders wear helmets on rural roads?  
**History turns:** 0

**Retrieved (synthetic):**

- E1 `helmet` (Rule 437): Synthetic Rule 437. Every rider of a two-wheeler shall wear protective headgear, except a person exempted under sub-rule (2). (2) A Sikh wearing a turban is exempted.
- E2 `rural` (Rule 437A): Synthetic Rule 437A. Riders on rural roads are exempt from protective headgear.

**Expected:** outcomes ['answer', 'conflict']; required ['E2'], permitted ['E1', 'E2'], excluded []; condition words []; content words ['rural roads', 'exempt']; retry None; model calls None  
**Why:** E2 is the passage on rural roads (an exemption); E1 is the general duty. An answer must state the E2 exemption; citing E1 as well is permitted, not required.

- call 1: status ok, latency 2.591 s, usage {'prompt_tokens': 891, 'completion_tokens': 520, 'total_tokens': 1411}, finish stop

**First response:**
```
{
 "answer": "Every rider of a two-wheeler shall wear protective headgear, except a Sikh wearing a turban. Riders on rural roads are exempt from protective headgear.",
 "evidence_sufficiency": "conflicting",
 "claims": [
  {
   "text": "Every rider of a two-wheeler shall wear protective headgear, except a Sikh wearing a turban.",
   "kind": "direct",
   "evidence_ids": [
    "E1"
   ]
  },
  {
   "text": "Riders on rural roads are exempt from protective headgear.",
   "kind": "direct",
   "evidence_ids": [
    "E2"
   ]
  }
 ],
 "citations": [
  "E1",
  "E2"
 ],
 "refusal_reason": null,
 "clarification_question": null
}
```
**First validation:** {'accepted': False, 'errors': ['claim 1: claim drops an exemption stated by the cited sentence', "claim 1: claim keeps 'except' but changes its clause"], 'checks': [{'layer': 'heuristic', 'check': 'exemption'}, {'layer': 'heuristic', 'check': 'qualifier_altered'}]}

**Retry:** not triggered - not eligible: rejected for exemption, qualifier_altered (retry is only for uncited-evidence findings)

**Final validation:** {'accepted': False, 'errors': ['claim 1: claim drops an exemption stated by the cited sentence', "claim 1: claim keeps 'except' but changes its clause"], 'checks': [{'layer': 'heuristic', 'check': 'exemption'}, {'layer': 'heuristic', 'check': 'qualifier_altered'}]}

**Pipeline errors:** ['claim 1: claim drops an exemption stated by the cited sentence', "claim 1: claim keeps 'except' but changes its clause"]

**Displayed answer:**
```
I couldn't find sufficiently relevant information in the Telangana documents I have, so I won't guess. Try rephrasing your question, or check the official Telangana Transport Department sources.
```
**Final claims:** []  
**Final citations:** []  
**Citation check:** None  
**Condition words:** None  
**Content words:** None  
**Legal meaning:** not assessed (synthetic passages; manual review required for any real-text claim)  
**Manual review:** pending  
**Expected behaviour achieved:** False ["outcome rejected not in expected ['answer', 'conflict']"]

</details>

<details><summary><b>RG-03</b> - one_sided_omits_qualifying_evidence - completed - outcome rejected</summary>

**Question:** Is protective headgear compulsory for every rider of a two-wheeler?  
**History turns:** 0

**Retrieved (synthetic):**

- E1 `helmet` (Rule 437): Synthetic Rule 437. Every rider of a two-wheeler shall wear protective headgear, except a person exempted under sub-rule (2). (2) A Sikh wearing a turban is exempted.
- E2 `rural` (Rule 437A): Synthetic Rule 437A. Riders on rural roads are exempt from protective headgear.

**Expected:** outcomes ['answer', 'conflict']; required ['E1', 'E2'], permitted ['E1', 'E2'], excluded []; condition words ['turban']; content words ['rural roads']; retry None; model calls None  
**Why:** E1 states the duty with its own exception (a Sikh wearing a turban); E2 exempts riders on rural roads, which qualifies 'every rider'. A complete answer keeps the E1 exception and cites the E2 exemption.

- call 1: status ok, latency 1.781 s, usage {'prompt_tokens': 898, 'completion_tokens': 568, 'total_tokens': 1466}, finish stop

**First response:**
```
{
 "answer": "Every rider of a two-wheeler shall wear protective headgear. A Sikh wearing a turban is exempted. Riders on rural roads are exempt from protective headgear.",
 "evidence_sufficiency": "sufficient",
 "claims": [
  {
   "text": "Every rider of a two-wheeler shall wear protective headgear.",
   "kind": "direct",
   "evidence_ids": [
    "E1"
   ]
  },
  {
   "text": "A Sikh wearing a turban is exempted.",
   "kind": "direct",
   "evidence_ids": [
    "E1"
   ]
  },
  {
   "text": "Riders on rural roads are exempt from protective headgear.",
   "kind": "direct",
   "evidence_ids": [
    "E2"
   ]
  }
 ],
 "citations": [
  "E1",
  "E2"
 ],
 "refusal_reason": null,
 "clarification_question": null
}
```
**First validation:** {'accepted': False, 'errors': ["claim 1: claim omits the 'except' qualifier of the sentence it restates"], 'checks': [{'layer': 'heuristic', 'check': 'qualifier_omitted'}]}

**Retry:** not triggered - not eligible: rejected for qualifier_omitted (retry is only for uncited-evidence findings)

**Final validation:** {'accepted': False, 'errors': ["claim 1: claim omits the 'except' qualifier of the sentence it restates"], 'checks': [{'layer': 'heuristic', 'check': 'qualifier_omitted'}]}

**Pipeline errors:** ["claim 1: claim omits the 'except' qualifier of the sentence it restates"]

**Displayed answer:**
```
I couldn't find sufficiently relevant information in the Telangana documents I have, so I won't guess. Try rephrasing your question, or check the official Telangana Transport Department sources.
```
**Final claims:** []  
**Final citations:** []  
**Citation check:** None  
**Condition words:** None  
**Content words:** None  
**Legal meaning:** not assessed (synthetic passages; manual review required for any real-text claim)  
**Manual review:** pending  
**Expected behaviour achieved:** False ["outcome rejected not in expected ['answer', 'conflict']"]

</details>

<details><summary><b>RG-04</b> - condition_must_be_kept - completed - outcome answer</summary>

**Question:** Can a learner drive a motor car?  
**History turns:** 0

**Retrieved (synthetic):**

- E1 `learner` (Rule 305): Synthetic Rule 305. A learner may drive a motor car, provided that a licensed instructor sits beside the learner.

**Expected:** outcomes ['answer']; required ['E1'], permitted ['E1'], excluded []; condition words ['licensed instructor sits beside']; content words []; retry None; model calls None  
**Why:** E1 permits it only with the proviso that a licensed instructor sits beside the learner (instructions rule 4).

- call 1: status ok, latency 0.867 s, usage {'prompt_tokens': 801, 'completion_tokens': 275, 'total_tokens': 1076}, finish stop

**First response:**
```
{
 "answer": "A learner may drive a motor car, provided that a licensed instructor sits beside the learner.",
 "evidence_sufficiency": "sufficient",
 "claims": [
  {
   "text": "A learner may drive a motor car, provided that a licensed instructor sits beside the learner.",
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
A learner may drive a motor car, provided that a licensed instructor sits beside the learner. [1]

Cited:
[1] Synthetic fixture document, Rule 305 (synthetic/synthetic-tmvr#Rule 305)
```
**Final claims:** ['A learner may drive a motor car, provided that a licensed instructor sits beside the learner.']  
**Final citations:** ['E1']  
**Citation check:** {'missing_required': [], 'outside_permitted': [], 'excluded_cited': [], 'correct': True}  
**Condition words:** {'required': ['licensed instructor sits beside'], 'missing': [], 'preserved': True}  
**Content words:** None  
**Legal meaning:** not assessed (synthetic passages; manual review required for any real-text claim)  
**Manual review:** pending  
**Expected behaviour achieved:** True 

</details>

<details><summary><b>RG-05</b> - general_rule_with_override - completed - outcome rejected</summary>

**Question:** Can a learner drive a motor car on a national highway?  
**History turns:** 0

**Retrieved (synthetic):**

- E1 `learner` (Rule 305): Synthetic Rule 305. A learner may drive a motor car, provided that a licensed instructor sits beside the learner.
- E2 `highway` (Rule 306): Synthetic Rule 306. Notwithstanding anything in rule 305, a learner shall not drive on a national highway.

**Expected:** outcomes ['answer']; required ['E2'], permitted ['E1', 'E2'], excluded []; condition words []; content words ['not drive on a national highway']; retry None; model calls None  
**Why:** E2 opens 'Notwithstanding anything in rule 305', so the synthetic text itself says E2 prevails over E1 for national highways: the passages do not conflict. Only an answer that states the E2 prohibition and cites E2 is acceptable; a 'conflicting' response, or one that omits the prohibition, ignores the override.

- call 1: status ok, latency 1.573 s, usage {'prompt_tokens': 880, 'completion_tokens': 486, 'total_tokens': 1366}, finish stop

**First response:**
```
{
 "answer": "A learner may drive a motor car, provided that a licensed instructor sits beside the learner. A learner shall not drive on a national highway.",
 "evidence_sufficiency": "sufficient",
 "claims": [
  {
   "text": "A learner may drive a motor car, provided that a licensed instructor sits beside the learner.",
   "kind": "direct",
   "evidence_ids": [
    "E1"
   ]
  },
  {
   "text": "A learner shall not drive on a national highway.",
   "kind": "direct",
   "evidence_ids": [
    "E2"
   ]
  }
 ],
 "citations": [
  "E1",
  "E2"
 ],
 "refusal_reason": null,
 "clarification_question": null
}
```
**First validation:** {'accepted': False, 'errors': ["claim 2: claim omits the 'notwithstanding' qualifier of the sentence it restates"], 'checks': [{'layer': 'heuristic', 'check': 'qualifier_omitted'}]}

**Retry:** not triggered - not eligible: rejected for qualifier_omitted (retry is only for uncited-evidence findings)

**Final validation:** {'accepted': False, 'errors': ["claim 2: claim omits the 'notwithstanding' qualifier of the sentence it restates"], 'checks': [{'layer': 'heuristic', 'check': 'qualifier_omitted'}]}

**Pipeline errors:** ["claim 2: claim omits the 'notwithstanding' qualifier of the sentence it restates"]

**Displayed answer:**
```
I couldn't find sufficiently relevant information in the Telangana documents I have, so I won't guess. Try rephrasing your question, or check the official Telangana Transport Department sources.
```
**Final claims:** []  
**Final citations:** []  
**Citation check:** None  
**Condition words:** None  
**Content words:** None  
**Legal meaning:** not assessed (synthetic passages; manual review required for any real-text claim)  
**Manual review:** pending  
**Expected behaviour achieved:** False ["outcome rejected not in expected ['answer']"]

</details>

<details><summary><b>RG-06</b> - condition_must_be_kept - completed - outcome answer</summary>

**Question:** Can a school bus carry standing passengers?  
**History turns:** 0

**Retrieved (synthetic):**

- E1 `schoolbus` (Rule 307): Synthetic Rule 307. A school bus may carry standing passengers only when all seats are occupied.

**Expected:** outcomes ['answer']; required ['E1'], permitted ['E1'], excluded []; condition words ['all seats are occupied']; content words []; retry None; model calls None  
**Why:** E1 permits standing passengers only when all seats are occupied; dropping that condition changes the rule.

- call 1: status ok, latency 1.53 s, usage {'prompt_tokens': 797, 'completion_tokens': 470, 'total_tokens': 1267}, finish stop

**First response:**
```
{
 "answer": "A school bus may carry standing passengers only when all seats are occupied. [E1]",
 "evidence_sufficiency": "sufficient",
 "claims": [
  {
   "text": "A school bus may carry standing passengers only when all seats are occupied.",
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
A school bus may carry standing passengers only when all seats are occupied. [1]

Cited:
[1] Synthetic fixture document, Rule 307 (synthetic/synthetic-tmvr#Rule 307)
```
**Final claims:** ['A school bus may carry standing passengers only when all seats are occupied.']  
**Final citations:** ['E1']  
**Citation check:** {'missing_required': [], 'outside_permitted': [], 'excluded_cited': [], 'correct': True}  
**Condition words:** {'required': ['all seats are occupied'], 'missing': [], 'preserved': True}  
**Content words:** None  
**Legal meaning:** not assessed (synthetic passages; manual review required for any real-text claim)  
**Manual review:** pending  
**Expected behaviour achieved:** True 

</details>

<details><summary><b>RG-07</b> - exception_must_be_kept - completed - outcome answer</summary>

**Question:** Can a goods vehicle carry passengers?  
**History turns:** 0

**Retrieved (synthetic):**

- E1 `goods` (Rule 245): Synthetic Rule 245. A goods vehicle shall not carry passengers, except the owner or hirer travelling with the goods.

**Expected:** outcomes ['answer']; required ['E1'], permitted ['E1'], excluded []; condition words ['owner or hirer']; content words []; retry None; model calls None  
**Why:** E1 prohibits passengers except the owner or hirer travelling with the goods.

- call 1: status ok, latency 1.434 s, usage {'prompt_tokens': 801, 'completion_tokens': 418, 'total_tokens': 1219}, finish stop

**First response:**
```
{
 "answer": "A goods vehicle shall not carry passengers, except the owner or hirer travelling with the goods. [E1]",
 "evidence_sufficiency": "sufficient",
 "claims": [
  {
   "text": "A goods vehicle shall not carry passengers, except the owner or hirer travelling with the goods.",
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
A goods vehicle shall not carry passengers, except the owner or hirer travelling with the goods. [1]

Cited:
[1] Synthetic fixture document, Rule 245 (synthetic/synthetic-tmvr#Rule 245)
```
**Final claims:** ['A goods vehicle shall not carry passengers, except the owner or hirer travelling with the goods.']  
**Final citations:** ['E1']  
**Citation check:** {'missing_required': [], 'outside_permitted': [], 'excluded_cited': [], 'correct': True}  
**Condition words:** {'required': ['owner or hirer'], 'missing': [], 'preserved': True}  
**Content words:** None  
**Legal meaning:** not assessed (synthetic passages; manual review required for any real-text claim)  
**Manual review:** pending  
**Expected behaviour achieved:** True 

</details>

<details><summary><b>RG-08</b> - one_sided_omits_qualifying_evidence - api_failed - outcome rejected</summary>

**Question:** Can a goods vehicle carry people?  
**History turns:** 0

**Retrieved (synthetic):**

- E1 `goods` (Rule 245): Synthetic Rule 245. A goods vehicle shall not carry passengers, except the owner or hirer travelling with the goods.
- E2 `farm` (Rule 314): Synthetic Rule 314. A goods vehicle may carry farm labourers with the goods.

**Expected:** outcomes ['answer', 'conflict']; required ['E1', 'E2'], permitted ['E1', 'E2'], excluded []; condition words ['owner or hirer']; content words ['farm labourers']; retry None; model calls None  
**Why:** E1 prohibits passengers except the owner or hirer; E2 permits farm labourers with the goods. Both bear on 'people', so both must be cited.

- call 1: status rate_limited_http_429, latency 0.117 s, usage None, finish None, error RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-120b` in organization `[REDACTED_ORG]` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Used 7149, Requested 1346. Please try again in 3.7125s. Need more tokens? Upgrade to Dev Tier 

**First response:**
_none_
**First validation:** None

**Retry:** not triggered - no first validation (no model response)

**Final validation:** None

**Pipeline errors:** ['generator error: EvalCallFailed']

**Displayed answer:**
```
I couldn't find sufficiently relevant information in the Telangana documents I have, so I won't guess. Try rephrasing your question, or check the official Telangana Transport Department sources.
```
**Final claims:** []  
**Final citations:** []  
**Citation check:** None  
**Condition words:** None  
**Content words:** None  
**Legal meaning:** not assessed (synthetic passages; manual review required for any real-text claim)  
**Manual review:** pending  
**Expected behaviour achieved:** None ['not scored: case api_failed']

</details>

<details><summary><b>RG-09</b> - condition_must_be_kept - api_failed - outcome rejected</summary>

**Question:** When may vehicles halt at a bus bay?  
**History turns:** 0

**Retrieved (synthetic):**

- E1 `park407` (Rule 407): Synthetic Rule 407. Vehicles may halt at a bus bay only to pick up or set down passengers.

**Expected:** outcomes ['answer']; required ['E1'], permitted ['E1'], excluded []; condition words ['pick up or set down passengers']; content words []; retry None; model calls None  
**Why:** E1 permits halting only to pick up or set down passengers.

- call 1: status rate_limited_http_429, latency 0.045 s, usage None, finish None, error RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-120b` in organization `[REDACTED_ORG]` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Used 7133, Requested 1276. Please try again in 3.0675s. Need more tokens? Upgrade to Dev Tier 

**First response:**
_none_
**First validation:** None

**Retry:** not triggered - no first validation (no model response)

**Final validation:** None

**Pipeline errors:** ['generator error: EvalCallFailed']

**Displayed answer:**
```
I couldn't find sufficiently relevant information in the Telangana documents I have, so I won't guess. Try rephrasing your question, or check the official Telangana Transport Department sources.
```
**Final claims:** []  
**Final citations:** []  
**Citation check:** None  
**Condition words:** None  
**Content words:** None  
**Legal meaning:** not assessed (synthetic passages; manual review required for any real-text claim)  
**Manual review:** pending  
**Expected behaviour achieved:** None ['not scored: case api_failed']

</details>

<details><summary><b>RG-10</b> - control_no_retry - api_failed - outcome rejected</summary>

**Question:** Must every rider of a two-wheeler wear protective headgear?  
**History turns:** 0

**Retrieved (synthetic):**

- E1 `helmet` (Rule 437): Synthetic Rule 437. Every rider of a two-wheeler shall wear protective headgear, except a person exempted under sub-rule (2). (2) A Sikh wearing a turban is exempted.
- E2 `fasten` (Rule 439): Synthetic Rule 439. Every rider of a two-wheeler shall fasten the protective headgear securely.

**Expected:** outcomes ['answer']; required ['E1'], permitted ['E1', 'E2'], excluded []; condition words ['turban']; content words []; retry False; model calls None  
**Why:** E1 answers the question (with its exception). E2 (fasten securely) is complementary, not contradicting, so a correct answer citing E1 should be accepted without a retry.

- call 1: status rate_limited_http_429, latency 0.044 s, usage None, finish None, error RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-120b` in organization `[REDACTED_ORG]` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Used 7127, Requested 1421. Please try again in 4.11s. Need more tokens? Upgrade to Dev Tier to

**First response:**
_none_
**First validation:** None

**Retry:** not triggered - no first validation (no model response)

**Final validation:** None

**Pipeline errors:** ['generator error: EvalCallFailed']

**Displayed answer:**
```
I couldn't find sufficiently relevant information in the Telangana documents I have, so I won't guess. Try rephrasing your question, or check the official Telangana Transport Department sources.
```
**Final claims:** []  
**Final citations:** []  
**Citation check:** None  
**Condition words:** None  
**Content words:** None  
**Legal meaning:** not assessed (synthetic passages; manual review required for any real-text claim)  
**Manual review:** pending  
**Expected behaviour achieved:** None ['not scored: case api_failed']

</details>

#### RG-11: not run (3 consecutive infrastructure failures)

#### RG-12: not run (3 consecutive infrastructure failures)

#### RG-13: not run (3 consecutive infrastructure failures)

#### RG-14: not run (3 consecutive infrastructure failures)

#### RG-Z1: not run (3 consecutive infrastructure failures)

#### RG-Z2: not run (3 consecutive infrastructure failures)

## 8. Limitations and recommendations

- Synthetic passages only: no result here speaks to real Telangana provisions or legal correctness.
- Expected behaviour is engineering expectation derived from the synthetic text, not a reviewed legal reference answer; no human-reviewed cases exist yet (all retrieval-review rows are pending).
- Condition-word and content-word checks are lexical (exact words); a faithful paraphrase fails them and an answer can contain the words with the meaning changed. Manual review is required before drawing conclusions.
- Retrieval is fixed per case, so retrieval quality is not measured.
- One run at temperature 0 with a fixed seed is not a reliability estimate; provider output can still vary between runs.
- The Groq adapter exists only in this runner; the server's grounded mode still uses DisabledGenerator.
- Recommendation: before any real-text run, have reviewers fill the human-review sheet and turn reviewed rows into cases with their own required and permitted citations.

