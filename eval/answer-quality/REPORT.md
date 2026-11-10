# Grounded-answer quality evaluation (synthetic)

> Synthetic engineering evaluation. Fixture passages are invented test text and expected outcomes describe validator behaviour only. Nothing here is a legal accuracy score, a legal reference answer or legal verification of the Telangana corpus.

- Fixtures: 94 (61 adversarial)
- External model calls: {'groq': 0}; server answer mode at load: `disabled`, model client constructed: False
- Unexpected failures: 0; known validator gaps still open: 0

## Metrics

| Metric | Result |
|---|---|
| expected outcome agreement | 100.0% (94/94) |
| schema validity rate | 96.7% (88/91) |
| malformed output rejection rate | 100.0% (3/3) |
| citation validity rate | 100.0% (37/37) |
| invalid citation rejection rate | 100.0% (5/5) |
| citation completeness | 100.0% (36/36) |
| claim to evidence mapping | 100.0% (36/36) |
| unsupported claim rejection rate | 100.0% (48/48) |
| correct refusal rate | 100.0% (7/7) |
| over refusal rate | 0.0% (0/28) |
| conflict detection rate | 100.0% (12/12) |
| identifier validation rate | 100.0% (10/10) |
| answer consistency | 100.0% (94/94) |
| displayed text from claims only | 100.0% (28/28) |
| guarded cases without generation | 100.0% (3/3) |
| negation change rejection rate | 100.0% (8/8) |
| exception omission rejection rate | 100.0% (6/6) |
| condition change rejection rate | 100.0% (2/2) |
| numeric change rejection rate | 100.0% (7/7) |
| composition rejection rate | 100.0% (2/2) |
| uncited conflict rejection rate | 100.0% (2/2) |
| false positive rate on controls | 0.0% (0/14) |
| conflict retries | 7 |
| conflict retries accepted | 3 |
| generator calls total | 98 |

## Which layer rejected

Deterministic checks (schema, evidence IDs, citation sets, status, answer = claims, identifiers, penalty) are exact rules. Heuristic checks (word overlap and the lexical meaning-preservation checks in `backend/meaning_checks.py`) only look for surface signals of a meaning change; passing them does not show that meaning or law is preserved.

- Rejected cases: 59 - deterministic only 17, heuristic only 37, both 5

| Check | Rejected cases |
|---|---|
| deterministic:answer_equals_claims | 1 |
| deterministic:citation_set | 2 |
| deterministic:evidence_id | 2 |
| deterministic:identifier | 11 |
| deterministic:penalty | 2 |
| deterministic:schema | 3 |
| deterministic:status | 1 |
| heuristic:composition | 3 |
| heuristic:deontic | 10 |
| heuristic:numeric_association | 2 |
| heuristic:numeric_changed | 7 |
| heuristic:numeric_omitted | 9 |
| heuristic:qualifier_added | 2 |
| heuristic:qualifier_altered | 2 |
| heuristic:qualifier_omitted | 11 |
| heuristic:uncited_qualification | 4 |
| heuristic:unverifiable_direct | 5 |
| heuristic:word_overlap | 3 |

## By category

| Category | Passed |
|---|---|
| central_vs_telangana | 3/3 |
| changed_condition | 2/2 |
| clarification | 1/1 |
| combined_provisions | 1/1 |
| composition | 3/3 |
| conflicting_evidence | 11/11 |
| direct_explanation | 3/3 |
| exception_omission | 8/8 |
| follow_up | 3/3 |
| incorrect_citation | 3/3 |
| insufficient_evidence | 2/2 |
| missing_citation | 3/3 |
| missing_exception | 2/2 |
| multi_provision | 2/2 |
| negation_reversal | 2/2 |
| negation_variation | 10/10 |
| numeric_change | 12/12 |
| penalty | 2/2 |
| prompt_injection | 2/2 |
| same_rule_different_claim | 1/1 |
| schema | 3/3 |
| uncited_conflict | 4/4 |
| unsupported_amount | 2/2 |
| unsupported_date | 2/2 |
| unsupported_percentage | 2/2 |
| unsupported_rule_number | 3/3 |
| unsupported_schedule | 2/2 |

## Failures

None.
