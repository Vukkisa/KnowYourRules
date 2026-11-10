# OFFLINE REPLAY evaluation: grounded answers

> **OFFLINE REPLAY of recorded responses, not a fresh model evaluation.** No model calls were made: every response below was recorded during the live run(s) listed here and is re-checked by the CURRENT validator. Latency and token figures do not apply.

| Provenance | Value |
|---|---|
| recording | eval/real-model/recorded/2026-11-10-gpt-oss-120b.json (sha256 6830020652c1f205) |
| recorded model | openai/gpt-oss-120b |
| source | eval/real-model/results.json (run 2026-11-10 17:45 UTC, sha256 f738d42f2a7b4355) |
| source | eval/real-model/results-part2.json (run 2026-11-10 17:50 UTC, sha256 753b1925f2b48b6a) |
| repository HEAD commit | 473b9cd49a6d81a99278458e1dfff345669f6e11 |
| uncommitted changes anywhere in the repository (untracked files and this report included) | True |
| validator file `backend/real_groq_eval.py` | committed vs HEAD, sha256 8b8ae03920f8da66 |
| validator file `backend/answer_quality_eval.py` | committed vs HEAD, sha256 11d5c87f79c18555 |
| validator file `backend/server.py` | committed vs HEAD, sha256 70e49ab629d65fe7 |
| validator file `backend/grounded_answer.py` | committed vs HEAD, sha256 d5f4965f47a9e7e1 |
| validator file `backend/meaning_checks.py` | committed vs HEAD, sha256 7c7467c1c5c254fb |
| response hashes verified | 14 of 14 |
| replayed at (UTC) | 2026-11-10 18:31 |

Excluded from the recording (no usable response in that source): RG-08 in eval/real-model/results.json (api_failed), RG-09 in eval/real-model/results.json (api_failed), RG-10 in eval/real-model/results.json (api_failed)

| Case | Recorded response sha256 (verified before use) |
|---|---|
| RG-01 | d2762b325cfe944c55a994b10df8d6309f862d8da01a73b3ed5fdb78ebe9a483 |
| RG-02 | 3c7fd1f1dd17c22170c14e5d451c98c123f2c94ad584bedfc9cc98e922161ed6 |
| RG-03 | c3443955572ec69b79306ddc880e4fc33904107b42715a96d14be6d7ad8a3d11 |
| RG-04 | fa0d3316c0a236797b47f902de1750cc99311d45e8ad16117f9282d28c483a5e |
| RG-05 | 4eb111412dd3405bf86273c70dbf769e4979df8be957a207bbfee0f5ec011bd2 |
| RG-06 | 30e6ad1b682f42c9940dfbbe6fd710a2a39c2df3fca0f3b8e4b13a16c36c6898 |
| RG-07 | c2d6f97c2171ef68ed8670e3288759acecaebaf47133c918512f4741149ecf81 |
| RG-08 | 7a610703884f4bb3691136c6ed07a7c6a0f1dae98dc70f00d9ce147a7bc397ec |
| RG-09 | b6bd8ee7c9c591bbd1e7bcde91095cf2786c59b84a6c809827905c52baa876f1 |
| RG-10 | a49056b52b9c627c22e7789a09350f398cde444cde7fe841f543eb5993dc1973 |
| RG-11 | 612fa42c348a6a04109e2922feacc575848d17ba145dd2e8b13d1629a4d22b75 |
| RG-12 | 6c20dccecc91b0d7b9a425d22898225a8dcd98bf5c91a6bd5014c1088615f1bb |
| RG-13 | 36f1795011d0cadc7a24af4e31b3409917b0bbaa5d3bcaadc4b36d47973f221b |
| RG-14 | b3e6364597803026180ec946bf6e9fca5f188c4be6e7cee0a598cf480503c01c |

> All evaluation passages are SYNTHETIC test text (eval/answer-quality/fixtures.json), not Telangana legal provisions. These results do not measure legal correctness on real Telangana legal provisions. Validator acceptance does not prove legal correctness; legal meaning preservation needs manual review.

## 1. Configuration

| Setting | Value |
|---|---|
| mode | replay |
| model | recorded openai/gpt-oss-120b (not called) |
| cases_file | eval/real-model/cases.json |
| run_at_utc | 2026-11-10 18:31 |

JSON mode reason: grounded_answer.ANSWER_INSTRUCTIONS says 'Respond with ONE JSON object and nothing else' and parse_response() applies json.loads to the raw text with no cleanup.

Execution path: server.chat -> grounded_answer_question (follow-up and penalty guards) -> fixed synthetic retrieval -> grounded_answer.answer (evidence contract, prompt, generator call, validate, at most one conflict retry, validate) -> backend rendering and citations. Approval gate forced open for the run only; no approval record is read or written.

## 2. Cases

14 model cases and 2 no-model guard checks.

| Model-case status | Count |
|---|---|
| completed | 14 |
| provider_rejected_output | 0 |
| truncated | 0 |
| api_failed | 0 |
| incomplete | 0 |
| not_run | 0 |
| not_recorded | 0 |

completed = the model response reached the validator. provider_rejected_output = the provider refused the model's output (e.g. invalid JSON in JSON mode). truncated = output cut at the token limit. api_failed = infrastructure failure (timeout, network, authentication, rate limit, server). incomplete / not_run = stopped by the call limit, token budget or repeated infrastructure failures.

## 3. Model-case results among cases with a scorable response (14 of 14)

| Measure | Result |
|---|---|
| Expected-outcome agreement | 13/14 (93%) |
| First-pass validator acceptance | 13/14 (93%) |
| Final validator acceptance | 13/14 (93%): 11 substantive (answer or conflict), 2 accepted refusal or clarification |
| Retry frequency | 0/14 (0%) |
| Retry success (accepted after retry) | n/a (0 cases) |
| Citation correctness (answers and conflicts) | 11/11 (100%) |
| Condition/exception words preserved in claim text (lexical; cases with a condition) | 7/7 (100%) |
| Content words of required positions in claim text (lexical; cases with such words) | 6/6 (100%) |

## 4. Overall model-case achievement (all 14 model cases)

**Achieved: 13/14 (93%)**

| Not achieved | Count |
|---|---|
| expectation_failed | 1 |
| truncated | 0 |
| provider_rejected_output | 0 |

| Not scorable (counted in the denominator above, shown separately) | Count |
|---|---|
| infrastructure_failure | 0 |
| not_recorded | 0 |
| incomplete | 0 |
| not_run | 0 |

## 5. No-model guard checks

| | Result |
|---|---|
| Checks | 2 |
| Passing | 2 |
| Unexpected model calls | 0 |
| Not run | 0 |

## 6. Calls, latency, tokens, cost

| Measure | Result |
|---|---|
| Recorded responses replayed by status (no model calls) | 14 {'ok': 14} |
| Latency per call (s) | not applicable (offline replay) |
| Tokens | not reported by provider |
| Estimated cost (USD) | not estimated (no prices given or no usage reported) |

Validator acceptance, citation correctness, lexical condition-word and content-word checks and expected-behaviour agreement are measured automatically. Legal meaning preservation is NOT measured: it is listed per case as pending manual review.

## 7. Case by case

| Case | Purpose | Status | Calls | Retry | First | Final | Outcome | Citations | Expected |
|---|---|---|---|---|---|---|---|---|---|
| RG-01 | direct_conflict | completed | 1 | no | accepted | accepted | conflict | ok | yes |
| RG-02 | rule_with_specific_exemption | completed | 1 | no | accepted | accepted | conflict | ok | yes |
| RG-03 | one_sided_omits_qualifying_evidence | completed | 1 | no | accepted | accepted | answer | ok | yes |
| RG-04 | condition_must_be_kept | completed | 1 | no | accepted | accepted | answer | ok | yes |
| RG-05 | general_rule_with_override | completed | 1 | no | rejected | rejected | rejected | - | NO |
| RG-06 | condition_must_be_kept | completed | 1 | no | accepted | accepted | answer | ok | yes |
| RG-07 | exception_must_be_kept | completed | 1 | no | accepted | accepted | answer | ok | yes |
| RG-08 | one_sided_omits_qualifying_evidence | completed | 1 | no | accepted | accepted | conflict | ok | yes |
| RG-09 | condition_must_be_kept | completed | 1 | no | accepted | accepted | answer | ok | yes |
| RG-10 | control_no_retry | completed | 1 | no | accepted | accepted | answer | ok | yes |
| RG-11 | control_no_retry | completed | 1 | no | accepted | accepted | answer | ok | yes |
| RG-12 | insufficient_evidence | completed | 1 | no | accepted | accepted | no_support | - | yes |
| RG-13 | insufficient_evidence | completed | 1 | no | accepted | accepted | no_support | - | yes |
| RG-14 | follow_up_restated | completed | 1 | no | accepted | accepted | conflict | ok | yes |
| RG-Z1 | vague_follow_up | completed | 0 | no | - | - | clarification | - | yes |
| RG-Z2 | penalty_restriction | completed | 0 | no | - | - | restricted | - | yes |

### Failures and unscored cases

- **RG-05** (completed): outcome rejected not in expected ['answer']. Validator: claim 2: claim omits the 'notwithstanding' qualifier of the sentence it restates

### Full records

<details><summary><b>RG-01</b> - direct_conflict - completed - outcome conflict</summary>

**Question:** Must the keeper of a test registry stamp the test card in blue ink?  
**History turns:** 0

**Retrieved (synthetic):**

- E1 `fictional_stamp_must` (Fictional Clause A): Synthetic Clause A, fictional test text. The keeper of a test registry shall stamp the test card in blue ink.
- E2 `fictional_stamp_must_not` (Fictional Clause B): Synthetic Clause B, fictional test text. The keeper of a test registry shall not stamp the test card in blue ink.

**Expected:** outcomes ['conflict']; required ['E1', 'E2'], permitted ['E1', 'E2'], excluded []; condition words []; content words ['blue ink', 'shall not stamp']; retry None; model calls None  
**Why:** Fictional pair: E1 and E2 have the same actor (the keeper of a test registry), the same action and object (stamp the test card in blue ink) and no condition or scope limit; E1 requires it and E2 prohibits it, and neither says it prevails. The instructions (rule 9) require 'conflicting', one claim per side citing its own passage; an answer that picks one side is not acceptable.

- call 1: status ok, latency 0.0 s, usage None, finish stop

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

<details><summary><b>RG-02</b> - rule_with_specific_exemption - completed - outcome conflict</summary>

**Question:** Must riders wear helmets on rural roads?  
**History turns:** 0

**Retrieved (synthetic):**

- E1 `helmet` (Rule 437): Synthetic Rule 437. Every rider of a two-wheeler shall wear protective headgear, except a person exempted under sub-rule (2). (2) A Sikh wearing a turban is exempted.
- E2 `rural` (Rule 437A): Synthetic Rule 437A. Riders on rural roads are exempt from protective headgear.

**Expected:** outcomes ['answer', 'conflict']; required ['E2'], permitted ['E1', 'E2'], excluded []; condition words []; content words ['rural roads', 'exempt']; retry None; model calls None  
**Why:** E2 is the passage on rural roads (an exemption); E1 is the general duty. An answer must state the E2 exemption; citing E1 as well is permitted, not required.

- call 1: status ok, latency 0.0 s, usage None, finish stop

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
**First validation:** {'accepted': True, 'errors': [], 'checks': []}

**Retry:** not triggered - not eligible: first response accepted

**Final validation:** {'accepted': True, 'errors': [], 'checks': []}

**Pipeline errors:** none

**Displayed answer:**
```
The Telangana documents I have conflict on this, so this is not a definitive answer. Each source says:
- Every rider of a two-wheeler shall wear protective headgear, except a Sikh wearing a turban. [1]
- Riders on rural roads are exempt from protective headgear. [2]

Cited:
[1] Synthetic fixture document, Rule 437 (synthetic/synthetic-tmvr#Rule 437)
[2] Synthetic fixture document, Rule 437A (synthetic/synthetic-tmvr#Rule 437A)
```
**Final claims:** ['Every rider of a two-wheeler shall wear protective headgear, except a Sikh wearing a turban.', 'Riders on rural roads are exempt from protective headgear.']  
**Final citations:** ['E1', 'E2']  
**Citation check:** {'missing_required': [], 'outside_permitted': [], 'excluded_cited': [], 'correct': True}  
**Condition words:** None  
**Content words:** {'required': ['rural roads', 'exempt'], 'missing': [], 'preserved': True}  
**Legal meaning:** not assessed (synthetic passages; manual review required for any real-text claim)  
**Manual review:** pending  
**Expected behaviour achieved:** True 

</details>

<details><summary><b>RG-03</b> - one_sided_omits_qualifying_evidence - completed - outcome answer</summary>

**Question:** Is protective headgear compulsory for every rider of a two-wheeler?  
**History turns:** 0

**Retrieved (synthetic):**

- E1 `helmet` (Rule 437): Synthetic Rule 437. Every rider of a two-wheeler shall wear protective headgear, except a person exempted under sub-rule (2). (2) A Sikh wearing a turban is exempted.
- E2 `rural` (Rule 437A): Synthetic Rule 437A. Riders on rural roads are exempt from protective headgear.

**Expected:** outcomes ['answer', 'conflict']; required ['E1', 'E2'], permitted ['E1', 'E2'], excluded []; condition words ['turban']; content words ['rural roads']; retry None; model calls None  
**Why:** E1 states the duty with its own exception (a Sikh wearing a turban); E2 exempts riders on rural roads, which qualifies 'every rider'. A complete answer keeps the E1 exception and cites the E2 exemption.

- call 1: status ok, latency 0.0 s, usage None, finish stop

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
**First validation:** {'accepted': True, 'errors': [], 'checks': []}

**Retry:** not triggered - not eligible: first response accepted

**Final validation:** {'accepted': True, 'errors': [], 'checks': []}

**Pipeline errors:** none

**Displayed answer:**
```
Every rider of a two-wheeler shall wear protective headgear. [1] A Sikh wearing a turban is exempted. [1] Riders on rural roads are exempt from protective headgear. [2]

Cited:
[1] Synthetic fixture document, Rule 437 (synthetic/synthetic-tmvr#Rule 437)
[2] Synthetic fixture document, Rule 437A (synthetic/synthetic-tmvr#Rule 437A)
```
**Final claims:** ['Every rider of a two-wheeler shall wear protective headgear.', 'A Sikh wearing a turban is exempted.', 'Riders on rural roads are exempt from protective headgear.']  
**Final citations:** ['E1', 'E2']  
**Citation check:** {'missing_required': [], 'outside_permitted': [], 'excluded_cited': [], 'correct': True}  
**Condition words:** {'required': ['turban'], 'missing': [], 'preserved': True}  
**Content words:** {'required': ['rural roads'], 'missing': [], 'preserved': True}  
**Legal meaning:** not assessed (synthetic passages; manual review required for any real-text claim)  
**Manual review:** pending  
**Expected behaviour achieved:** True 

</details>

<details><summary><b>RG-04</b> - condition_must_be_kept - completed - outcome answer</summary>

**Question:** Can a learner drive a motor car?  
**History turns:** 0

**Retrieved (synthetic):**

- E1 `learner` (Rule 305): Synthetic Rule 305. A learner may drive a motor car, provided that a licensed instructor sits beside the learner.

**Expected:** outcomes ['answer']; required ['E1'], permitted ['E1'], excluded []; condition words ['licensed instructor sits beside']; content words []; retry None; model calls None  
**Why:** E1 permits it only with the proviso that a licensed instructor sits beside the learner (instructions rule 4).

- call 1: status ok, latency 0.0 s, usage None, finish stop

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

- call 1: status ok, latency 0.0 s, usage None, finish stop

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

- call 1: status ok, latency 0.0 s, usage None, finish stop

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

- call 1: status ok, latency 0.0 s, usage None, finish stop

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

<details><summary><b>RG-08</b> - one_sided_omits_qualifying_evidence - completed - outcome conflict</summary>

**Question:** Can a goods vehicle carry people?  
**History turns:** 0

**Retrieved (synthetic):**

- E1 `goods` (Rule 245): Synthetic Rule 245. A goods vehicle shall not carry passengers, except the owner or hirer travelling with the goods.
- E2 `farm` (Rule 314): Synthetic Rule 314. A goods vehicle may carry farm labourers with the goods.

**Expected:** outcomes ['answer', 'conflict']; required ['E1', 'E2'], permitted ['E1', 'E2'], excluded []; condition words ['owner or hirer']; content words ['farm labourers']; retry None; model calls None  
**Why:** E1 prohibits passengers except the owner or hirer; E2 permits farm labourers with the goods. Both bear on 'people', so both must be cited.

- call 1: status ok, latency 0.0 s, usage None, finish stop

**First response:**
```
{
 "answer": "A goods vehicle shall not carry passengers, except the owner or hirer travelling with the goods. A goods vehicle may carry farm labourers with the goods.",
 "evidence_sufficiency": "conflicting",
 "claims": [
  {
   "text": "A goods vehicle shall not carry passengers, except the owner or hirer travelling with the goods.",
   "kind": "direct",
   "evidence_ids": [
    "E1"
   ]
  },
  {
   "text": "A goods vehicle may carry farm labourers with the goods.",
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
- A goods vehicle shall not carry passengers, except the owner or hirer travelling with the goods. [1]
- A goods vehicle may carry farm labourers with the goods. [2]

Cited:
[1] Synthetic fixture document, Rule 245 (synthetic/synthetic-tmvr#Rule 245)
[2] Synthetic fixture document, Rule 314 (synthetic/synthetic-tmvr#Rule 314)
```
**Final claims:** ['A goods vehicle shall not carry passengers, except the owner or hirer travelling with the goods.', 'A goods vehicle may carry farm labourers with the goods.']  
**Final citations:** ['E1', 'E2']  
**Citation check:** {'missing_required': [], 'outside_permitted': [], 'excluded_cited': [], 'correct': True}  
**Condition words:** {'required': ['owner or hirer'], 'missing': [], 'preserved': True}  
**Content words:** {'required': ['farm labourers'], 'missing': [], 'preserved': True}  
**Legal meaning:** not assessed (synthetic passages; manual review required for any real-text claim)  
**Manual review:** pending  
**Expected behaviour achieved:** True 

</details>

<details><summary><b>RG-09</b> - condition_must_be_kept - completed - outcome answer</summary>

**Question:** When may vehicles halt at a bus bay?  
**History turns:** 0

**Retrieved (synthetic):**

- E1 `park407` (Rule 407): Synthetic Rule 407. Vehicles may halt at a bus bay only to pick up or set down passengers.

**Expected:** outcomes ['answer']; required ['E1'], permitted ['E1'], excluded []; condition words ['pick up or set down passengers']; content words []; retry None; model calls None  
**Why:** E1 permits halting only to pick up or set down passengers.

- call 1: status ok, latency 0.0 s, usage None, finish stop

**First response:**
```
{
 "answer": "Vehicles may halt at a bus bay only to pick up or set down passengers.",
 "evidence_sufficiency": "sufficient",
 "claims": [
  {
   "text": "Vehicles may halt at a bus bay only to pick up or set down passengers.",
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
Vehicles may halt at a bus bay only to pick up or set down passengers. [1]

Cited:
[1] Synthetic fixture document, Rule 407 (synthetic/synthetic-tmvr#Rule 407)
```
**Final claims:** ['Vehicles may halt at a bus bay only to pick up or set down passengers.']  
**Final citations:** ['E1']  
**Citation check:** {'missing_required': [], 'outside_permitted': [], 'excluded_cited': [], 'correct': True}  
**Condition words:** {'required': ['pick up or set down passengers'], 'missing': [], 'preserved': True}  
**Content words:** None  
**Legal meaning:** not assessed (synthetic passages; manual review required for any real-text claim)  
**Manual review:** pending  
**Expected behaviour achieved:** True 

</details>

<details><summary><b>RG-10</b> - control_no_retry - completed - outcome answer</summary>

**Question:** Must every rider of a two-wheeler wear protective headgear?  
**History turns:** 0

**Retrieved (synthetic):**

- E1 `helmet` (Rule 437): Synthetic Rule 437. Every rider of a two-wheeler shall wear protective headgear, except a person exempted under sub-rule (2). (2) A Sikh wearing a turban is exempted.
- E2 `fasten` (Rule 439): Synthetic Rule 439. Every rider of a two-wheeler shall fasten the protective headgear securely.

**Expected:** outcomes ['answer']; required ['E1'], permitted ['E1', 'E2'], excluded []; condition words ['turban']; content words []; retry False; model calls None  
**Why:** E1 answers the question (with its exception). E2 (fasten securely) is complementary, not contradicting, so a correct answer citing E1 should be accepted without a retry.

- call 1: status ok, latency 0.0 s, usage None, finish stop

**First response:**
```
{
 "answer": "Every rider of a two-wheeler shall wear protective headgear, except a Sikh wearing a turban is exempted.",
 "evidence_sufficiency": "sufficient",
 "claims": [
  {
   "text": "Every rider of a two-wheeler shall wear protective headgear, except a Sikh wearing a turban is exempted.",
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
Every rider of a two-wheeler shall wear protective headgear, except a Sikh wearing a turban is exempted. [1]

Cited:
[1] Synthetic fixture document, Rule 437 (synthetic/synthetic-tmvr#Rule 437)
```
**Final claims:** ['Every rider of a two-wheeler shall wear protective headgear, except a Sikh wearing a turban is exempted.']  
**Final citations:** ['E1']  
**Citation check:** {'missing_required': [], 'outside_permitted': [], 'excluded_cited': [], 'correct': True}  
**Condition words:** {'required': ['turban'], 'missing': [], 'preserved': True}  
**Content words:** None  
**Legal meaning:** not assessed (synthetic passages; manual review required for any real-text claim)  
**Manual review:** pending  
**Expected behaviour achieved:** True 

</details>

<details><summary><b>RG-11</b> - control_no_retry - completed - outcome answer</summary>

**Question:** I lost my driving licence. How do I get a duplicate?  
**History turns:** 0

**Retrieved (synthetic):**

- E1 `dup16` (Rule 16): Synthetic Rule 16. A holder who loses a driving licence shall apply to the licensing authority for a duplicate licence.
- E2 `dup18` (Rule 18): Synthetic Rule 18. The application for a duplicate driving licence shall be made in Form 7 with the fee specified in the Schedule.

**Expected:** outcomes ['answer']; required ['E1', 'E2'], permitted ['E1', 'E2'], excluded []; condition words []; content words ['Form 7']; retry False; model calls None  
**Why:** E1 says to apply to the licensing authority; E2 gives the form. Complementary steps, no conflict.

- call 1: status ok, latency 0.0 s, usage None, finish stop

**First response:**
```
{
 "answer": "A holder who loses a driving licence shall apply to the licensing authority for a duplicate licence. The application for a duplicate driving licence shall be made in Form 7 with the fee specified in the Schedule.",
 "evidence_sufficiency": "sufficient",
 "claims": [
  {
   "text": "A holder who loses a driving licence shall apply to the licensing authority for a duplicate licence.",
   "kind": "direct",
   "evidence_ids": [
    "E1"
   ]
  },
  {
   "text": "The application for a duplicate driving licence shall be made in Form 7 with the fee specified in the Schedule.",
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
A holder who loses a driving licence shall apply to the licensing authority for a duplicate licence. [1] The application for a duplicate driving licence shall be made in Form 7 with the fee specified in the Schedule. [2]

Cited:
[1] Synthetic fixture document, Rule 16 (synthetic/synthetic-tmvr#Rule 16)
[2] Synthetic fixture document, Rule 18 (synthetic/synthetic-tmvr#Rule 18)
```
**Final claims:** ['A holder who loses a driving licence shall apply to the licensing authority for a duplicate licence.', 'The application for a duplicate driving licence shall be made in Form 7 with the fee specified in the Schedule.']  
**Final citations:** ['E1', 'E2']  
**Citation check:** {'missing_required': [], 'outside_permitted': [], 'excluded_cited': [], 'correct': True}  
**Condition words:** None  
**Content words:** {'required': ['Form 7'], 'missing': [], 'preserved': True}  
**Legal meaning:** not assessed (synthetic passages; manual review required for any real-text claim)  
**Manual review:** pending  
**Expected behaviour achieved:** True 

</details>

<details><summary><b>RG-12</b> - insufficient_evidence - completed - outcome no_support</summary>

**Question:** Do car passengers have to wear seat belts?  
**History turns:** 0

**Retrieved (synthetic):**

- E1 `helmet` (Rule 437): Synthetic Rule 437. Every rider of a two-wheeler shall wear protective headgear, except a person exempted under sub-rule (2). (2) A Sikh wearing a turban is exempted.

**Expected:** outcomes ['no_support']; required [], permitted [], excluded ['E1']; condition words []; content words []; retry None; model calls None  
**Why:** E1 concerns headgear for two-wheeler riders and says nothing about seat belts.

- call 1: status ok, latency 0.0 s, usage None, finish stop

**First response:**
```
{
 "answer": "",
 "evidence_sufficiency": "insufficient",
 "claims": [],
 "citations": [],
 "refusal_reason": "The evidence does not address car passenger seat belt requirements.",
 "clarification_question": null
}
```
**First validation:** {'accepted': True, 'errors': [], 'checks': []}

**Retry:** not triggered - not eligible: first response accepted

**Final validation:** {'accepted': True, 'errors': [], 'checks': []}

**Pipeline errors:** none

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
**Expected behaviour achieved:** True 

</details>

<details><summary><b>RG-13</b> - insufficient_evidence - completed - outcome no_support</summary>

**Question:** How long is a permit valid?  
**History turns:** 0

**Retrieved (synthetic):**

- E1 `permit` (Rule 191): Synthetic Rule 191. The permit shall be carried in the vehicle at all times and produced on demand by an officer of the Transport Department.

**Expected:** outcomes ['no_support']; required [], permitted [], excluded ['E1']; condition words []; content words []; retry None; model calls None  
**Why:** E1 says where the permit is carried and to whom it is produced; it states no validity period.

- call 1: status ok, latency 0.0 s, usage None, finish stop

**First response:**
```
{
 "answer": "",
 "evidence_sufficiency": "insufficient",
 "claims": [],
 "citations": [],
 "refusal_reason": "The provided evidence does not contain any information about the duration of permit validity.",
 "clarification_question": null
}
```
**First validation:** {'accepted': True, 'errors': [], 'checks': []}

**Retry:** not triggered - not eligible: first response accepted

**Final validation:** {'accepted': True, 'errors': [], 'checks': []}

**Pipeline errors:** none

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
**Expected behaviour achieved:** True 

</details>

<details><summary><b>RG-14</b> - follow_up_restated - completed - outcome conflict</summary>

**Question:** Must riders wear helmets on rural roads as well?  
**History turns:** 1

**Retrieved (synthetic):**

- E1 `helmet` (Rule 437): Synthetic Rule 437. Every rider of a two-wheeler shall wear protective headgear, except a person exempted under sub-rule (2). (2) A Sikh wearing a turban is exempted.
- E2 `rural` (Rule 437A): Synthetic Rule 437A. Riders on rural roads are exempt from protective headgear.

**Expected:** outcomes ['answer', 'conflict']; required ['E2'], permitted ['E1', 'E2'], excluded []; condition words []; content words ['rural roads', 'exempt']; retry None; model calls None  
**Why:** Same passages and expectation as RG-02, asked as a self-contained follow-up with history. Grounded mode does not rewrite follow-ups; the restated question is answered on its own.

- call 1: status ok, latency 0.0 s, usage None, finish stop

**First response:**
```
{
 "answer": "Riders of a two-wheeler must wear protective headgear, except a Sikh wearing a turban. Riders on rural roads are exempt from protective headgear.",
 "evidence_sufficiency": "conflicting",
 "claims": [
  {
   "text": "Riders of a two-wheeler must wear protective headgear, except a Sikh wearing a turban.",
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
**First validation:** {'accepted': True, 'errors': [], 'checks': []}

**Retry:** not triggered - not eligible: first response accepted

**Final validation:** {'accepted': True, 'errors': [], 'checks': []}

**Pipeline errors:** none

**Displayed answer:**
```
The Telangana documents I have conflict on this, so this is not a definitive answer. Each source says:
- Riders of a two-wheeler must wear protective headgear, except a Sikh wearing a turban. [1]
- Riders on rural roads are exempt from protective headgear. [2]

Cited:
[1] Synthetic fixture document, Rule 437 (synthetic/synthetic-tmvr#Rule 437)
[2] Synthetic fixture document, Rule 437A (synthetic/synthetic-tmvr#Rule 437A)
```
**Final claims:** ['Riders of a two-wheeler must wear protective headgear, except a Sikh wearing a turban.', 'Riders on rural roads are exempt from protective headgear.']  
**Final citations:** ['E1', 'E2']  
**Citation check:** {'missing_required': [], 'outside_permitted': [], 'excluded_cited': [], 'correct': True}  
**Condition words:** None  
**Content words:** {'required': ['rural roads', 'exempt'], 'missing': [], 'preserved': True}  
**Legal meaning:** not assessed (synthetic passages; manual review required for any real-text claim)  
**Manual review:** pending  
**Expected behaviour achieved:** True 

</details>

<details><summary><b>RG-Z1</b> - vague_follow_up - completed - outcome clarification</summary>

**Question:** and for a bike?  
**History turns:** 1

**Retrieved (synthetic):**

- - `helmet` (Rule 437): Synthetic Rule 437. Every rider of a two-wheeler shall wear protective headgear, except a person exempted under sub-rule (2). (2) A Sikh wearing a turban is exempted.

**Expected:** outcomes ['clarification']; required [], permitted [], excluded []; condition words []; content words []; retry None; model calls 0  
**Why:** Grounded mode answers a context-dependent follow-up with a fixed request to restate it, before any model call.


**First response:**
_none_
**First validation:** None

**Retry:** not triggered - no first validation (no model response)

**Final validation:** None

**Pipeline errors:** none

**Displayed answer:**
```
Please ask your full question on its own (for example, name the rule, vehicle or document) - I don't rewrite follow-up questions in this mode.
```
**Final claims:** []  
**Final citations:** []  
**Citation check:** None  
**Condition words:** None  
**Content words:** None  
**Legal meaning:** not assessed (synthetic passages; manual review required for any real-text claim)  
**Manual review:** pending  
**Expected behaviour achieved:** True 

</details>

<details><summary><b>RG-Z2</b> - penalty_restriction - completed - outcome restricted</summary>

**Question:** and what is the fine?  
**History turns:** 1

**Retrieved (synthetic):**

- - `helmet` (Rule 437): Synthetic Rule 437. Every rider of a two-wheeler shall wear protective headgear, except a person exempted under sub-rule (2). (2) A Sikh wearing a turban is exempted.

**Expected:** outcomes ['restricted']; required [], permitted [], excluded []; condition words []; content words []; retry None; model calls 0  
**Why:** Penalty questions are locked before generation in grounded mode.


**First response:**
_none_
**First validation:** None

**Retry:** not triggered - no first validation (no model response)

**Final validation:** None

**Pipeline errors:** none

**Displayed answer:**
```
**Penalties and compounding fees are not available yet.**

The official Telangana compounding schedule has not been obtained, and the knowledge base has not been approved by legal counsel, so I can't give fine amounts, compounding fees, penalty points or other punishment details.

For current amounts, check the official Telangana Transport Department or Hyderabad / Cyberabad / Rachakonda traffic police e-challan portals.
```
**Final claims:** []  
**Final citations:** []  
**Citation check:** None  
**Condition words:** None  
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

