# Real-model evaluation artifacts

Everything here uses **synthetic passages** (`eval/answer-quality/fixtures.json` and the two fictional passages in
`cases.json`). Nothing here measures legal correctness on real Telangana provisions, and validator acceptance is
not legal validation. Manual legal review of every case is pending.

The files fall into four kinds of evidence. They answer different questions and must not be added together into one
accuracy figure.

| Kind | Files | What it shows | Model called? |
|---|---|---|---|
| Live model runs (historical) | `SMOKE-REPORT.md`, `smoke-results.json`, `REPORT.md`, `results.json`, `REPORT-part2.md`, `results-part2.json` | What `openai/gpt-oss-120b` actually answered on 2026-11-10, judged by the validator **as it was then** | Yes, on 2026-11-10 |
| Frozen recording | `recorded/2026-11-10-gpt-oss-120b.json` | The 14 answers above, copied once with sha256 hashes | No |
| Offline replay | `REPLAY-REPORT.md`, `replay-results.json` | How the **current** validator judges those same recorded answers | No |
| Mock sample | `SAMPLE-REPORT.md` | The report format, from hand-written mock responses | No |

Case definitions and expectations: `cases.json` (14 model cases, 2 no-model guard checks). Runner:
`backend/real_groq_eval.py`.

## Historical live runs (do not edit)

The live reports and results files are kept exactly as written by the runner, with one exception noted below.
Their headline metrics **predate later validator fixes** (the qualifier cross-reference fix and the stage 1
own-qualifier coverage rule), so they show how answers were judged at the time, not now. For the current
judgement of the same answers, see the offline replay.

Validator at the time of all three live runs: commit `7243584` **plus uncommitted working-tree changes** (the
evaluation runner and the validator as it stood before the cross-reference and stage 1 fixes). That exact working
tree was not committed, so it cannot be checked out again; the recorded answers, not the validator, are what the
replay preserves.

Settings common to all three runs (from each results file's `config`): model `openai/gpt-oss-120b`, temperature
0.0, seed 7, JSON mode on, `max_completion_tokens` 4096, timeout 60 s, SDK retries disabled.

### Smoke test: `SMOKE-REPORT.md`, `smoke-results.json`

- Run at 2026-11-10 17:40 UTC; case RG-04 only; `max_calls` 1, `max_total_tokens` 10,000, no pacing.
- 1 call, completed; 801 prompt + 390 completion = 1,191 tokens; 1/1 expected outcome.
- An earlier smoke attempt ended in an API failure; its output files were overwritten by this run and are not
  available.

### Live run 1: `REPORT.md`, `results.json`

- Run at 2026-11-10 17:45 UTC; all 16 cases; `max_calls` 28, `max_total_tokens` 150,000, no pacing.
- RG-01 to RG-07 completed. RG-08, RG-09 and RG-10 failed with **HTTP 429** (Groq tokens-per-minute limit); after
  three consecutive infrastructure failures the runner stopped, so RG-11 to RG-14 and both guard checks were
  **not run**.
- 10 calls (7 ok, 3 rate-limited); 9,169 tokens.
- Headline at the time: 4/14 model cases achieved (stale; see the replay).
- **Edited after the run:** the 429 error text contained the Groq organisation ID. It was replaced with
  `[REDACTED_ORG]` in `REPORT.md` and `results.json` (3 occurrences each) after the run. No other change was made,
  and no recorded model response was affected.

### Paced rerun: `REPORT-part2.md`, `results-part2.json`

- Run at 2026-11-10 17:50 UTC; cases RG-08 to RG-14 and both guard checks (the cases run 1 did not complete);
  `max_calls` 14, `max_total_tokens` 80,000, `min_interval_s` 15 (pacing added after the rate-limit stop).
- 7 calls, all ok; 8,461 tokens; guard checks 2/2.
- Headline at the time: 5/7 achieved (stale; see the replay).
- **RG-08, RG-09 and RG-10 in the frozen recording come from this run**, not from run 1.
- An earlier attempt of this rerun was interrupted by hand while waiting between calls and wrote no output.

## Frozen recording: `recorded/2026-11-10-gpt-oss-120b.json`

- 14 responses, one per model case: RG-01 to RG-07 from `results.json`, RG-08 to RG-14 from `results-part2.json`.
  Each entry keeps the case ID, source file, run time, call index, status, `finish_reason`, the response text and
  its sha256. The two source files' own sha256 values are stored too.
- Run 1's failed RG-08 to RG-10 attempts are listed under `excluded`. They had no response and none was invented.
- **"Verbatim"** means identical to the response text the runner stored in the results file, which it stored
  after its key/org redaction pass. That pass found nothing to redact in any of these responses (no redaction
  marker, no key- or org-like string). It does not mean the raw bytes the provider sent: the SDK had already decoded
  them.
- Every response finished with `finish_reason` "stop". No retry was triggered in either live run, so the recording
  holds first-call answers only.
- Loading the recording checks the schema and every hash; any mismatch, missing response or response not marked
  verbatim refuses the whole replay.

## Offline replay: `REPLAY-REPORT.md`, `replay-results.json`

Reproduce (no key, no network, no model call):

```bash
python3 -m backend.real_groq_eval --replay eval/real-model/recorded/2026-11-10-gpt-oss-120b.json --markdown eval/real-model/REPLAY-REPORT.md --json eval/real-model/replay-results.json
```

- It runs the recorded answers through the **current local validator** on the same path as a live run (the
  server's `/chat` handler, grounded mode, validator, conflict retry, rendering). It is **not a fresh model
  evaluation**: no client is built, no call is made, and `--replay` with `--real` is refused.
- The report records the recording's sha256, each response hash and the sources. For the validator it records
  three different things, which must not be confused:
  - **repository HEAD commit**: the last commit, which may not contain the validator that ran;
  - **uncommitted changes anywhere in the repository**: true if anything differs from HEAD, including untracked
    files and the report being written, so it says nothing specific about the validator;
  - **each validator source file** (`backend/real_groq_eval.py`, `answer_quality_eval.py`, `server.py`,
    `grounded_answer.py`, `meaning_checks.py`): its state against HEAD (committed, modified or untracked) and its
    sha256. These hashes identify the validator that ran, committed or not.

  The current replay files were generated before the stage 1-4 changes were committed, so they show validator
  files as modified or untracked. Regenerate them after committing; they will then show the files as committed.
- Current result: 13 of 14 model cases achieved; guard checks 2/2. RG-05 is rejected: the recorded answer states
  "A learner shall not drive on a national highway" but drops "Notwithstanding anything in rule 305", the override
  the case tests.
- Statuses: `not_recorded` means the pipeline asked for a response the recording does not hold (for example a
  retry the live run never made, which can happen when the current validator is stricter than the one used live).
  Nothing is substituted; the case is not scored and counts in the denominator as not scorable. `incomplete` and
  `not_run` mean the call limit, token budget or repeated infrastructure failures stopped the run; in replay these
  do not occur unless the budget is changed.

## Mock sample: `SAMPLE-REPORT.md`

Generated by `python3 -m backend.real_groq_eval` (no flags) from the hand-written `sample_mock_responses` in
`cases.json`. Its numbers say nothing about any model; RG-03 and RG-06 miss on purpose to show failure handling.

## Other evidence (outside this folder, not model evaluation)

| Evidence | Where | Last result |
|---|---|---|
| Unit and mocked tests | `tests/` (`python3 -m unittest discover -s tests`) | all passing |
| Answer-quality fixtures (validator behaviour on fixed responses) | `eval/answer-quality/` | 94 rows, unchanged by stages 1-3 |
| Real-index uncited-conflict probe (1,059 preview-index sentences, planted negations) | ad hoc script, not yet in the repository | 1/1,059 flagged; planted 464, 432, 430 of 475 |
| Verbatim real-text probe (each sentence cited to its own chunk) | ad hoc script, not yet in the repository | 5/1,059 rejected (`numeric_omitted`) |

## Integrity of the historical files

sha256 at the time this README was written. If any differs, the file has changed since.

| File | sha256 |
|---|---|
| `REPORT.md` | `42b5e64461b1c351181ec0fa7cdd167168f44037da4aabc2dde6949882c97456` |
| `results.json` | `f738d42f2a7b4355291f37c7f2bcbdbdf4626f61c8499a2b0444b8b7679cc75f` |
| `REPORT-part2.md` | `0476ca6b666776fb5265143429b21f8cf537be714c5977bbfb0c99923dbb485e` |
| `results-part2.json` | `753b1925f2b48b6aba0f445230aa76fb7e1a861983254b21c88e4b451cb8f4d7` |
| `SMOKE-REPORT.md` | `169b3a338d3dd28a0474dfdab49a66c083a813bf9e549f5c160dc176f3d07e85` |
| `smoke-results.json` | `a05c70e9b8c9f24c411b67fd2a14b3d84cca24b442b1a85618246e1043dad1ba` |
| `recorded/2026-11-10-gpt-oss-120b.json` | `6830020652c1f2053a87008cf776f09f7a6f0a6fe1623801a3ec837864c4bedc` |
