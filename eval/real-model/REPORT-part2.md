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
| max_calls | 14 |
| max_total_tokens | 80000 |
| timeout_s | 60.0 |
| min_interval_s | 15.0 |
| price_in_per_mtok | None |
| price_out_per_mtok | None |
| cases_file | eval/real-model/cases.json |
| run_at_utc | 2026-11-10 17:50 |

JSON mode reason: grounded_answer.ANSWER_INSTRUCTIONS says 'Respond with ONE JSON object and nothing else' and parse_response() applies json.loads to the raw text with no cleanup.

Execution path: server.chat -> grounded_answer_question (follow-up and penalty guards) -> fixed synthetic retrieval -> grounded_answer.answer (evidence contract, prompt, generator call, validate, at most one conflict retry, validate) -> backend rendering and citations. Approval gate forced open for the run only; no approval record is read or written.

## 2. Cases

7 model cases and 2 no-model guard checks.

| Model-case status | Count |
|---|---|
| completed | 7 |
| provider_rejected_output | 0 |
| truncated | 0 |
| api_failed | 0 |
| incomplete | 0 |
| not_run | 0 |

completed = the model response reached the validator. provider_rejected_output = the provider refused the model's output (e.g. invalid JSON in JSON mode). truncated = output cut at the token limit. api_failed = infrastructure failure (timeout, network, authentication, rate limit, server). incomplete / not_run = stopped by the call limit, token budget or repeated infrastructure failures.

## 3. Model-case results among cases with a scorable response (7 of 7)

| Measure | Result |
|---|---|
| Expected-outcome agreement | 5/7 (71%) |
| First-pass validator acceptance | 5/7 (71%) |
| Final validator acceptance | 5/7 (71%): 3 substantive (answer or conflict), 2 accepted refusal or clarification |
| Retry frequency | 0/7 (0%) |
| Retry success (accepted after retry) | n/a (0 cases) |
| Citation correctness (answers and conflicts) | 3/3 (100%) |
| Condition/exception words preserved in claim text (lexical; cases with a condition) | 2/2 (100%) |
| Content words of required positions in claim text (lexical; cases with such words) | 2/2 (100%) |

## 4. Overall model-case achievement (all 7 model cases)

**Achieved: 5/7 (71%)**

| Not achieved | Count |
|---|---|
| expectation_failed | 2 |
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
| Checks | 2 |
| Passing | 2 |
| Unexpected model calls | 0 |
| Not run | 0 |

## 6. Calls, latency, tokens, cost

| Measure | Result |
|---|---|
| Model calls by status | 7 {'ok': 7} |
| Latency per call (s) | {'mean': 1.429, 'median': 1.719, 'max': 1.808} |
| Tokens | {'prompt_tokens': 5976, 'completion_tokens': 2485, 'total_tokens': 8461} |
| Estimated cost (USD) | not estimated (no prices given or no usage reported) |

Validator acceptance, citation correctness, lexical condition-word and content-word checks and expected-behaviour agreement are measured automatically. Legal meaning preservation is NOT measured: it is listed per case as pending manual review.

## 7. Case by case

| Case | Purpose | Status | Calls | Retry | First | Final | Outcome | Citations | Expected |
|---|---|---|---|---|---|---|---|---|---|
| RG-08 | one_sided_omits_qualifying_evidence | completed | 1 | no | accepted | accepted | conflict | ok | yes |
| RG-09 | condition_must_be_kept | completed | 1 | no | accepted | accepted | answer | ok | yes |
| RG-10 | control_no_retry | completed | 1 | no | rejected | rejected | rejected | - | NO |
| RG-11 | control_no_retry | completed | 1 | no | accepted | accepted | answer | ok | yes |
| RG-12 | insufficient_evidence | completed | 1 | no | accepted | accepted | no_support | - | yes |
| RG-13 | insufficient_evidence | completed | 1 | no | accepted | accepted | no_support | - | yes |
| RG-14 | follow_up_restated | completed | 1 | no | rejected | rejected | rejected | - | NO |
| RG-Z1 | vague_follow_up | completed | 0 | no | - | - | clarification | - | yes |
| RG-Z2 | penalty_restriction | completed | 0 | no | - | - | restricted | - | yes |

### Failures and unscored cases

- **RG-10** (completed): outcome rejected not in expected ['answer']
- **RG-14** (completed): outcome rejected not in expected ['answer', 'conflict']

### Full records

<details><summary><b>RG-08</b> - one_sided_omits_qualifying_evidence - completed - outcome conflict</summary>

**Question:** Can a goods vehicle carry people?  
**History turns:** 0

**Retrieved (synthetic):**

- E1 `goods` (Rule 245): Synthetic Rule 245. A goods vehicle shall not carry passengers, except the owner or hirer travelling with the goods.
- E2 `farm` (Rule 314): Synthetic Rule 314. A goods vehicle may carry farm labourers with the goods.

**Expected:** outcomes ['answer', 'conflict']; required ['E1', 'E2'], permitted ['E1', 'E2'], excluded []; condition words ['owner or hirer']; content words ['farm labourers']; retry None; model calls None  
**Why:** E1 prohibits passengers except the owner or hirer; E2 permits farm labourers with the goods. Both bear on 'people', so both must be cited.

- call 1: status ok, latency 1.767 s, usage {'prompt_tokens': 870, 'completion_tokens': 510, 'total_tokens': 1380}, finish stop

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

- call 1: status ok, latency 1.719 s, usage {'prompt_tokens': 800, 'completion_tokens': 329, 'total_tokens': 1129}, finish stop

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

<details><summary><b>RG-10</b> - control_no_retry - completed - outcome rejected</summary>

**Question:** Must every rider of a two-wheeler wear protective headgear?  
**History turns:** 0

**Retrieved (synthetic):**

- E1 `helmet` (Rule 437): Synthetic Rule 437. Every rider of a two-wheeler shall wear protective headgear, except a person exempted under sub-rule (2). (2) A Sikh wearing a turban is exempted.
- E2 `fasten` (Rule 439): Synthetic Rule 439. Every rider of a two-wheeler shall fasten the protective headgear securely.

**Expected:** outcomes ['answer']; required ['E1'], permitted ['E1', 'E2'], excluded []; condition words ['turban']; content words []; retry False; model calls None  
**Why:** E1 answers the question (with its exception). E2 (fasten securely) is complementary, not contradicting, so a correct answer citing E1 should be accepted without a retry.

- call 1: status ok, latency 1.071 s, usage {'prompt_tokens': 901, 'completion_tokens': 349, 'total_tokens': 1250}, finish stop

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
**First validation:** {'accepted': False, 'errors': ["claim 1: claim keeps 'except' but changes its clause"], 'checks': [{'layer': 'heuristic', 'check': 'qualifier_altered'}]}

**Retry:** not triggered - not eligible: rejected for qualifier_altered (retry is only for uncited-evidence findings)

**Final validation:** {'accepted': False, 'errors': ["claim 1: claim keeps 'except' but changes its clause"], 'checks': [{'layer': 'heuristic', 'check': 'qualifier_altered'}]}

**Pipeline errors:** ["claim 1: claim keeps 'except' but changes its clause"]

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

<details><summary><b>RG-11</b> - control_no_retry - completed - outcome answer</summary>

**Question:** I lost my driving licence. How do I get a duplicate?  
**History turns:** 0

**Retrieved (synthetic):**

- E1 `dup16` (Rule 16): Synthetic Rule 16. A holder who loses a driving licence shall apply to the licensing authority for a duplicate licence.
- E2 `dup18` (Rule 18): Synthetic Rule 18. The application for a duplicate driving licence shall be made in Form 7 with the fee specified in the Schedule.

**Expected:** outcomes ['answer']; required ['E1', 'E2'], permitted ['E1', 'E2'], excluded []; condition words []; content words ['Form 7']; retry False; model calls None  
**Why:** E1 says to apply to the licensing authority; E2 gives the form. Complementary steps, no conflict.

- call 1: status ok, latency 1.77 s, usage {'prompt_tokens': 885, 'completion_tokens': 425, 'total_tokens': 1310}, finish stop

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

- call 1: status ok, latency 0.912 s, usage {'prompt_tokens': 822, 'completion_tokens': 177, 'total_tokens': 999}, finish stop

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

- call 1: status ok, latency 0.959 s, usage {'prompt_tokens': 805, 'completion_tokens': 198, 'total_tokens': 1003}, finish stop

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

<details><summary><b>RG-14</b> - follow_up_restated - completed - outcome rejected</summary>

**Question:** Must riders wear helmets on rural roads as well?  
**History turns:** 1

**Retrieved (synthetic):**

- E1 `helmet` (Rule 437): Synthetic Rule 437. Every rider of a two-wheeler shall wear protective headgear, except a person exempted under sub-rule (2). (2) A Sikh wearing a turban is exempted.
- E2 `rural` (Rule 437A): Synthetic Rule 437A. Riders on rural roads are exempt from protective headgear.

**Expected:** outcomes ['answer', 'conflict']; required ['E2'], permitted ['E1', 'E2'], excluded []; condition words []; content words ['rural roads', 'exempt']; retry None; model calls None  
**Why:** Same passages and expectation as RG-02, asked as a self-contained follow-up with history. Grounded mode does not rewrite follow-ups; the restated question is answered on its own.

- call 1: status ok, latency 1.808 s, usage {'prompt_tokens': 893, 'completion_tokens': 497, 'total_tokens': 1390}, finish stop

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

