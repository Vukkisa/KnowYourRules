# Provision-level validity: implementation roadmap

Date: 16-11-2026. Review of `PROVISION-LEVEL-VALIDITY-DESIGN.md` plus a ten-step implementation plan.
Nothing in this roadmap has been implemented. No code, manifest, source document, approval record, index or registry was changed, and nothing was committed, pushed or deployed.
Test runner: `python3 -m unittest discover -s tests` (as in `.github/workflows/pages.yml`). Baseline from the previous task: 1971 tests, 106 skipped, 1 expected failure.

## 1. Architect's review of the design

The design is sound in its core (citation-keyed provisions, operation-derived versions, tri-state ends, asymmetric trust, ledger as authority). Reading it against `server.py`, `source_status.py` and `build_telangana_index.py` turned up gaps. The roadmap applies the amendments below; the design document itself is unchanged.

| # | Severity | Finding | Amendment applied in this roadmap |
|---|---|---|---|
| A1 | **High** | Design section 4.3 and decision 2 let counsel allow a `partial` chunk to answer current-law questions with a warning. This contradicts the stated priority. | **Closed.** A `partial` chunk never answers a current-law question and, in v1, is never authoritative for a dated question either. Section 12 decision 2 is removed. Historical use of a partial chunk waits for provision-level re-chunking |
| A2 | **High** | `source_status.load` requires the top-level keys to be exactly `{schema_version, jurisdiction, note, entries}` (`backend/source_status.py:188`). The design's `validity_ledger_sha256` key is a schema change to an approval-bound registry. | Step 2 makes the key optional in code and tests it on fixtures only. The real `legal-status/source-status.json` is not edited; that edit coincides with a re-signed approval and is a separately authorised task |
| A3 | **High** | The design does not cover the answer-cache replay check (`server.py` near line 1365, which calls `in_force_today`) or `approval_fingerprint()` (line 221). A cached answer could replay text the ledger now restricts. | Step 6 applies the resolver in the replay check and adds ledger digest and mode to the cache epoch and fingerprint **only when the flag is not off** |
| A4 | **High** | Design section 4.2 projects `valid_from`/`valid_to` into chunk metadata from the ledger. The existing routing treats those two keys as authority, so a projection would leak authority through the legacy path. | **No ledger-derived `valid_from`/`valid_to` is ever written to Chroma.** Only informational `vl_*` keys, and only on staging indexes. Those two keys stay manifest-derived |
| A5 | **High** | The live index has no `vl_*` keys and must not be touched, yet the design leans on them. | Runtime resolution uses the ledger plus **metadata that already exists** (`sha256`, `provision_id`, `part`, `parts`, `page_start`, `page_end`) and a hash of `page_content` computed at query time. No Chroma change is needed to run shadow or restrict mode |
| A6 | Medium | The design's "restrict-only if unapproved" was implicit. A flag-controlled ladder is clearer and safer. | Modes `off` (default), `shadow`, `restrict`. `enforce` (the only mode that can create authority) is **not built** and is code-locked, in the style of `release_gates.TELANGANA_LOCKED` |
| A7 | Medium | Fixtures arrive in design step 9, after the code they should drive. | Synthetic fixtures start in Step 1. Step 9 becomes the consolidated acceptance and parity suite |
| A8 | Medium | `source_status.py` accepts `decision_refs` only as `LD-nnn` (`DECISION_REF_RE`). A new `VD-` prefix would force another change on the approval-bound loader. | Validity decisions are numbered **LD-012 onward** in the existing Stage 22 register format. No new prefix |
| A9 | Medium | Existing `provision_overrides` in `source-status.json` are keyed by chunker `provision_id`. Merging them with the ledger would create two sources of truth. | They stay separate: source-status owns the **text-status warning**; the ledger owns **validity**. Both may restrict; neither is migrated into the other |
| A10 | Medium | Step 8 (lifecycle retention) touches a 1,539-line module and a persisted registry for little gain before provision-level chunks exist. | Kept as Step 8 but marked **deferrable**; nothing earlier depends on it |
| A11 | Low | The derived end date ("day before the successor starts") is a legal modelling rule. | Isolated in one function behind a ledger parameter `interval_rule`. Until an approved decision accepts the rule, derived ends are not computed and ends stay `unverified` |
| A12 | Low | Gazette evidence could be asserted without any file. | A decision citing a `gazette_print` must reference a file that is held and whose SHA-256 matches. None is held today, so none can be recorded |
| A13 | Low | Synthetic fixture dates could be mistaken for legal facts. | Fixture ledgers carry `"fixture": true`. The loader refuses them unless `allow_fixture=True`, which only tests pass |

## 2. Global controls

### 2.1 Flags (all OFF by default)

| Flag | Values | Default | Meaning |
|---|---|---|---|
| `TG_PROVISION_VALIDITY` | `off`, `shadow`, `restrict` | unset = `off` | `off`: ledger never read. `shadow`: ledger resolved and compared, legacy result served. `restrict`: ledger may only demote. Any other value (including `enforce`) is logged and treated as `off` |
| `TG_VALIDITY_LEDGER_FILE` | path | `legal-status/provision-validity.json` | Read only when the flag is not `off`. A missing file means "no ledger" (legacy behaviour) |
| `--validity-ledger PATH` | build option | absent | Opt-in projection for a staging build only |
| `provision_validity.ENFORCE_LOCKED` | code constant | `True` | `enforce` is unreachable while this is `True`, whatever the environment says |

Flag parsing uses the existing `env_flag`-style helper in `server.py`.

### 2.2 Invariants (each becomes a named test)

| ID | Invariant | First enforced in |
|---|---|---|
| I1 | Flag unset: behaviour, outputs, cache epoch and approval fingerprint are byte-identical to today | Step 6 |
| I2 | `shadow` returns exactly the legacy documents in the legacy order | Step 6 |
| I3 | `restrict` is monotone: a chunk's class is never better than its legacy class (authoritative > unverified > blocked/dropped) | Step 1 (library), Step 6 (server) |
| I4 | A fact that is not `approved`, not bound by a valid signed approval, or only a `candidate` is never authoritative | Step 1 |
| I5 | A `partial` chunk never answers a current-law question and is never authoritative | Step 1, Step 6 |
| I6 | A closed or historical version is never returned for an undated question | Step 1, Step 6 |
| I7 | `/chat` gates (release gates, penalty and compounding locks, `historical_legal_explanations`, approval check) are unchanged and run before retrieval. The resolver is imported only by `server.py` and the new modules | Step 6, Step 9 |
| I8 | Live index, `legal/`, `legal-status/`, manifest, source documents and approval files are unchanged by any step. A sentinel test hashes them before and after | Step 1 onward |
| I9 | No approved decision without a human reviewer, evidence and a held file hash | Step 3 |
| I10 | Fixture ledgers cannot load in the server path | Step 1 |

### 2.3 Rollback model

- **Steps 1 to 5, 7 (without the build option), 9:** additive new files. Rollback is deletion of the new files.
- **Steps 2, 6, 7, 8:** small edits to existing files. Rollback is reverting that step's hunks. Step 6 is also reversible at runtime by unsetting the flag.
- **Data:** no step writes to live data. The ledger is a new file; removing it restores legacy behaviour.

## 3. Milestones

| Milestone | Steps | Runtime change | Gate to proceed |
|---|---|---|---|
| **M-A (smallest safe first)** | Step 1 | None | Section 4 acceptance |
| M-B | Steps 2, 3, 4 | None (code on the approval path, inert without the new key) | A2 and A8 accepted by the project owner |
| M-C | Steps 5, 7 | None to serving (offline tooling and staging builds) | M-B |
| M-D | Step 6 in `shadow` mode | Flag-gated, off by default | M-B; owner approves the flag name |
| M-E | Step 6 `restrict`, Step 9 | Flag-gated | Shadow parity 100% on the benchmark |
| M-F | Step 8, Step 10 | Flag-gated / operational | Separately authorised |
| `enforce` | not in this roadmap | n/a | Counsel decisions, signed binding of the ledger, a code change that unlocks `ENFORCE_LOCKED` |

### 3.1 Smallest safe first milestone: Step 1

**Deliver `backend/provision_validity.py` (pure library), synthetic fixtures and tests. Wire it into nothing.**

Why this is the smallest safe cut:
- No existing file is modified, so I8 holds trivially.
- No flag is needed, because no runtime module imports it. An AST test enforces that.
- It needs no counsel decision, no approval, no Gazette evidence, no index and no real legal data. Fixtures are synthetic and refuse to load in the server path (A13).
- It is the executable specification for every later step. If the model is wrong, the only cost is deleting new files.
- It already proves the three hardest invariants (I3, I4, I5) before anything can serve text.

If a still smaller cut is wanted: Step 1a (types, loader, validator, fixtures) first, Step 1b (resolver) second. They share one test file and one module.

## 4. The ten steps

Dependency order: `1 -> {2, 3, 5} ; {1,3} -> 4 ; {1,2,3} -> 6 ; {1,5,6} -> 7 ; {1,3,6} -> 8 ; {1..7} -> 9 ; 9 -> 10`. Step 8 is optional and deferrable.

---

### Step 1: ledger library (M-A)

**Files**
- Create `backend/provision_validity.py`.
- Create `tests/test_provision_validity.py`.
- Create `tests/fixtures/provision_validity/` with synthetic ledgers: `go53_go16_synthetic.json`, `rule81_conflicting_targets.json`, `same_number_acts.json`, `overlap.json`, `gap.json`, `stale_coverage.json`, `unapproved_and_candidate.json`, `partial_chunk.json`. Each carries `"fixture": true` and obviously synthetic dates.
- Modify: none.

**Depends on:** none.

**Data structures and interfaces**
```python
MODES = ("off", "shadow", "restrict"); ENFORCE_LOCKED = True
class LedgerError(ValueError)
@dataclass(frozen=True) class Fact:      state, date, kind, candidate, evidence, decision_ref   # candidate is never read
@dataclass(frozen=True) class Interval:  start: Fact|None, end_state: "closed"|"continuing_verified"|"unverified", end: Fact|None, checked_through: int|None
@dataclass(frozen=True) class Version, Operation, Coverage(selector), Decision, Ledger(sha256, ...)
def load_ledger(source, *, allow_fixture=False) -> Ledger          # bytes or path; raises LedgerError; sets .sha256
def validate(ledger) -> list[Problem]                              # C1-C5, C8 and structural checks
def resolve_chunk(ledger, metadata, text, query_date, today, mode, *, bound=False) -> Verdict
Verdict: cls in (AUTHORITATIVE, HISTORICAL, UNVERIFIED, NOT_IN_FORCE, BLOCKED), reasons: tuple, provisions: tuple
```
- Selector match uses `sha256`, `provision_id`, `part`, `parts`, `page_start`, `page_end` and SHA-256 of `text` (A5). Mismatch gives `UNVERIFIED` with reason `stale_coverage`.
- Only facts with `kind == "commencement"`, `state == "approved"`, a decision that is `approved`, and `bound=True` can produce `AUTHORITATIVE`. Under `mode in ("shadow", "restrict")` the resolver never returns a class better than `UNVERIFIED` for a chunk the ledger does not already demote; the demotion-only rule is I3.
- Derived ends are computed only if the ledger carries an approved `interval_rule` decision (A11).

**Tests**
- Unit: every row of design section 5.1 (dated and undated); tri-state ends; derivation rule on and off; coverage staleness; C1 to C5 and C8 detection; `candidate` ignored; non-commencement date kinds rejected; fixture refusal (I10).
- Property (seeded, deterministic): random ledgers and chunks give I3, I4 and I5 (partial never current-law, never authoritative).
- Isolation: AST test that no module under `backend/` imports `provision_validity` (the allowed-importer list is edited in Step 6).
- Sentinel (I8): hashes `DRAFT-telangana-manifest.json`, `legal-status/source-status.json` and the `legal/` tree before and after.
- Regression: full suite unchanged.

**Acceptance**
- New tests pass; the full suite passes with the same skip and expected-failure counts, plus the new tests.
- `git diff` shows only new files.
- Property tests run at least 2,000 seeded cases with no violation.
- No fixture loads without `allow_fixture=True`.

**Rollback:** delete the new files.
**Runtime behaviour:** none (infrastructure only).

---

### Step 2: approval-binding hook in the source-status loader

**Files**
- Modify `backend/source_status.py`: accept an optional top-level `validity_ledger_sha256` (the exact-keys check becomes required keys plus this one optional key); expose `Registry.validity_ledger_sha256`; add `verify_ledger_binding(registry, ledger_sha256) -> list[str]`.
- Create `tests/test_source_status_ledger_binding.py`.
- Do **not** modify `legal-status/source-status.json`, `backend/legal_approval.py`, `scripts/sign_approval_record.py` or the record schema.

**Depends on:** Step 1 (ledger hash function).

**Interfaces**
- `Registry.validity_ledger_sha256: str | None`.
- Key present: must be 64 lowercase hex. Any other top-level key is still rejected.

**Tests**
- Unit: key absent loads exactly as before; present and valid; malformed hex; mismatch with the ledger; extra top-level keys still rejected.
- Integration (fixtures only): a fixture source-status naming a fixture ledger hash, bound by a fixture signed record (`UNSIGNED_TEST_ONLY` helper as in the existing tests); editing the ledger makes `verify_ledger_binding` fail and the approval check stale.
- Regression: `test_source_status.py`, `test_stage7c_source_status.py`, `test_legal_approval.py`, `test_eligibility_status.py` pass unmodified. Loading the real `legal-status/source-status.json` returns a registry equal to the pre-change one, and its SHA-256 is unchanged.

**Acceptance:** all existing source-status and approval tests pass with no edits; the real registry file is byte-identical (I8).
**Rollback:** revert `source_status.py`; the key is never present in real data.
**Runtime behaviour:** none while the key is absent. Treat as an approval-path code change needing owner sign-off (A2).

---

### Step 3: decision-record checks

**Files**
- Create `backend/validity_decisions.py`, `tests/test_validity_decisions.py`.
- Modify: none. The register `eval/legal-validation/stage-22-legal-decision-register.json` is read, never written.

**Depends on:** Step 1.

**Interfaces**
- `check_decisions(ledger, register, *, corpus_files=None, today=None) -> list[Problem]`.
- `propose_status(decision, new_status)` refuses `approved`; there is no code path by which tooling sets `approved`.
- Rules: `approved` needs reviewer name, designation and organisation, a real review date not in the future, a rationale, and a `prepared_by` different from the reviewer; placeholders rejected (same pattern as `source_status.PLACEHOLDER_RE`); evidence by fact type (design section 7); `replaces` chain acyclic; a revoked decision voids its facts back to `unknown`; decision ids match `LD-\d{3}` (A8); evidence of kind `gazette_print` must cite a held file with a matching SHA-256 (A12).

**Tests**
- Unit: each rule, and each fabrication pattern (null reviewer, placeholder reviewer, self-approval, future date, missing rationale, Gazette claim without a file, Gazette claim with a wrong hash).
- Integration: the 11 real LD records parse read-only; none is `approved`, so a ledger citing them cannot carry an approved fact.
- Regression: Stage 22 register consumers unchanged.

**Acceptance:** a ledger with any approved decision lacking a human reviewer, evidence or a held file hash fails to load; no real record is modified.
**Rollback:** delete the new module and test.
**Runtime behaviour:** none.

---

### Step 4: manifest adapter

**Files**
- Create `backend/validity_adapter.py`, `tests/test_validity_adapter.py`.
- Modify: none (`tg_manifest.py` unchanged).

**Depends on:** Steps 1 and 3.

**Interfaces**
- `ledger_from_manifest(entries) -> Ledger`: each document becomes an implicit whole-document provision `<instrument>#*`. `unknown` produces no entry. `verified_continuing` and `verified_closed` produce versions with `origin: "manifest_legacy"`. A legacy fact has no decision, so it is never `approved`; the legacy routing (`valid_from`/`valid_to` in chunk metadata) keeps serving it exactly as today. The adapter exists for comparison and migration, not for authority.
- `instrument_key(entry) -> str` gives jurisdiction-prefixed keys (C8).

**Tests**
- Unit: the 20 real entries (read-only) yield zero versions; synthetic `verified_*` entries round-trip.
- Differential parity: over a date grid and a synthetic chunk set, adapter-ledger verdicts equal `offence_date.route_documents` and `in_force_today`. 100% agreement required.
- Regression: `test_validity_index.py` (39 tests) and `test_tg_ingest.py` unchanged.

**Acceptance:** parity is 100%; real manifest byte-identical.
**Rollback:** delete the new files.
**Runtime behaviour:** none.

---

### Step 5: coverage tooling

**Files**
- Create `backend/validity_coverage.py` (`selector_for(metadata, text)`, `matches(selector, metadata, text)`, `chunk_text_sha256`), `scripts/propose_validity_coverage.py`, `tests/test_validity_coverage.py`.
- Modify: none.

**Depends on:** Step 1.

**Interfaces**
- `Selector = {manifest_id, sha256, provision_id, part, parts, page_start, page_end, text_sha256}`.
- The script re-chunks the held source documents through `tg_ingest` (deterministic, offline) and writes a **proposal** JSON with every coverage entry `status: "proposed"`, `decision_ref: null`. It never opens Chroma, so it cannot touch an index.
- It refuses an output path inside `legal/`, `legal-status/`, `docs/legal-sources/` or any Chroma directory, and refuses to overwrite an existing ledger.
- It lists chunks that cannot be mapped automatically (tables, extraction-flagged chunks) for manual mapping.

**Tests**
- Unit: determinism; one changed character breaks `matches`; the two `SCHEDULE` chunks of G.O. 53 get distinct selectors (page range plus text hash) using fixture data.
- Integration: the script on a synthetic corpus in a temp directory; forbidden-output-path refusal; no write outside `--out`.
- Regression: `test_tg_ingest.py`, `test_tg_ingest_headings.py` unchanged.

**Acceptance:** run on the 20 real sources, written to the scratchpad, the proposal contains no approved or authoritative entry, and lists the G.O. 53 Seventh Schedule table as unmapped. No tracked file changes.
**Rollback:** delete the new files.
**Runtime behaviour:** none (offline tooling).

---

### Step 6: server integration (flag-gated)

**Files**
- Modify `backend/server.py`:
  - flag and ledger-path parsing (`TG_PROVISION_VALIDITY`, `TG_VALIDITY_LEDGER_FILE`);
  - guarded ledger load at startup;
  - hook in `_retrieve`, after the `in_force_today` check and before `routing`;
  - the same check in the cache-replay guard;
  - ledger digest and mode in `approval_fingerprint()` and the cache epoch, **only when mode is not `off`**;
  - mode and ledger state in the existing status payload.
- Create `backend/provision_validity_runtime.py` (thin runtime wrapper), `tests/test_provision_validity_server.py`.
- Modify `.env.example` to document both variables, commented out.
- Do not modify `chat_guards.py`, `release_gates.py`, `grounded_answer.py`, `legal_approval.py` or `offence_date.py`.

**Depends on:** Steps 1, 2 and 3 (Step 4 for parity tests).

**Interfaces**
```python
class ValidityRuntime:
    @classmethod load(mode, path, registry, approval_active) -> ValidityRuntime   # never raises; invalid -> .invalid=True
    apply(docs, offence_date, today) -> tuple[list, ShadowReport]
    status() -> {"mode", "ledger_sha256", "valid", "chunks_demoted"}              # no file paths
```
- `off`: no file is opened; `apply` is not called.
- `shadow`: returns `docs` unchanged and in the same order; logs a bounded `validity-shadow` line per difference.
- `restrict`: removes `NOT_IN_FORCE` and `BLOCKED` chunks; for dated questions moves non-authoritative chunks out of `routing.authoritative`; never adds or promotes.
- Invalid ledger in `restrict`: dated questions get no authoritative chunks, undated questions behave as today, status shows `valid: false`.
- `partial` chunks are removed from undated results (I5).

**Tests**
- Unit: mode parsing (unknown value gives `off` plus a warning); `enforce` is treated as `off`.
- Integration (fake vector store, as in `tests/test_server.py`): I1 with the flag unset (golden outputs, cache epoch, fingerprint); I2 shadow equals legacy; I3 restrict never promotes; I5, I6; the replay guard drops a restricted chunk; changing the ledger changes the cache epoch; `off` never opens the file (patch `open`, assert uncalled).
- `/chat` non-interference (I7): the gate order is unchanged; with the `historical_legal_explanations` gate closed, a dated question is still refused even when the ledger would label text authoritative.
- Isolation: the AST allowed-importer list becomes exactly `server.py` and the new runtime module.
- Regression: `test_server.py`, `test_chat_release_gates.py`, `test_release_gates.py`, `test_grounded_answer.py`, `test_answer_cache.py`, `test_serve_filter_hardening.py`, `test_conflict_detection.py`, `test_conflict_residuals.py`, `test_hybrid_retrieval.py`, `test_legal_approval.py`, `test_validity_index.py`.

**Acceptance:** with the flag unset the full suite passes with zero changed expectations; shadow output equals legacy on the existing benchmark queries; restrict is monotone; I1 to I7 pass.
**Rollback:** unset `TG_PROVISION_VALIDITY` (immediate); revert the `server.py` hunks.
**Runtime behaviour:** **changes runtime behaviour, but only when the flag is `shadow` or `restrict`. Default off.** This is the first step that can affect serving.

---

### Step 7: staging projection and reporting

**Files**
- Modify `backend/build_telangana_index.py`: opt-in `--validity-ledger PATH`; writes informational `vl_ledger`, `vl_provisions`, `vl_state` into **staging** indexes only; `verify_staging` checks projection against the ledger (C9, C10). Never writes `valid_from` or `valid_to` from the ledger (A4).
- Modify `backend/index_validity.py`: report covered, partial and stale chunks.
- Modify `scripts/compare_staging_validity.py`: `--ledger` shadow-diff mode.
- Create `tests/test_validity_projection.py`.

**Depends on:** Steps 1, 5 and 6.

**Interfaces:** projection keys `vl_ledger: str`, `vl_provisions: str` (`|`-joined), `vl_state: "none"|"uniform"|"partial"|"blocked"`.

**Tests**
- Unit: projection of the synthetic G.O. 53/16 ledger onto synthetic chunks; no `valid_*` key is ever produced.
- Integration (fake embedder, temp directory): a default build has a metadata key set identical to today (golden); with the option, only the three `vl_*` keys are added; the build refuses the live directory name (`chroma_telangana_db`) and any directory already holding the live collection; the existing "unapproved builds are refused in the live directory" rule still holds.
- Regression: `test_tg_ingest.py`, `test_validity_index.py`, `test_index_snapshot.py`.

**Acceptance:** default build output unchanged; no `vl_*` key in any default build; projection never contains authority keys; a before/after file-tree hash of the live index directory (if present) is identical.
**Rollback:** revert the three modified files; delete staging directories.
**Runtime behaviour:** none to serving. Offline and staging only.

---

### Step 8: lifecycle retention (optional, deferrable)

**Files**
- Modify `backend/document_lifecycle.py`: `retainable` consults provision closures; a `partially_historical` state; `close_validity` becomes an adapter over ledger operations.
- Create `tests/test_validity_lifecycle.py` (uses `tests/lifecycle_fixtures.py` and temp registries).

**Depends on:** Steps 1, 3 and 6.

**Interfaces:** an optional `ledger_sha256` field on a registry version record; the old format loads unchanged.

**Tests**
- Unit and integration: a file stays active while any provision is current; a superseded file is retained as history only if its closures are approved; a partially closed file never serves a closed provision as current.
- Regression: `test_document_lifecycle.py`, `test_document_lifecycle_real.py`, `test_lifecycle_*`, `test_serve_filter_hardening.py`. Tests assert every registry path is under a temp directory; the real `legal/lifecycle` is never opened.

**Acceptance:** all lifecycle tests pass unmodified; a legacy registry loads with identical digest.
**Rollback:** revert the module hunks; the flag off disables the new retention logic.
**Runtime behaviour:** yes when the flag is on. **Recommendation: defer** until Step 6 has soaked in shadow mode and provision-level re-chunking exists, since partial chunks never answer (A10).

---

### Step 9: acceptance and parity suite

**Files**
- Create `tests/test_provision_validity_acceptance.py`, extend `tests/fixtures/provision_validity/`, create `scripts/validity_shadow_parity.py`.
- Modify: none.

**Depends on:** Steps 1 to 7 (Step 8 optional).

**Contents**
- The G.O. 53/16 scenario of design section 8.5 with synthetic dates, one test per table cell, in three ledger states (unapproved, approved with unverified end, approved with `continuing_verified`).
- Rule 81 with a deliberately inconsistent target list (the ledger refuses approval).
- Every conflict C1 to C11; same-number Acts (`IN:ACT:8/2026` versus `TG:ACT:8/2026`); stale coverage; restrict-only without binding.
- Fabrication guards: no approved decision without a reviewer; no Gazette evidence without a held file; fixtures refuse to load in the server path; `candidate` is never read.
- `/chat` non-interference end to end.
- Parity script: runs `eval/telangana-retrieval-benchmark.json` queries with the flag off and in shadow mode against a throwaway copy and compares the returned chunk lists.

**Acceptance:** all tests pass; parity script reports 100% identical lists; I1 to I10 each have at least one named passing test.
**Rollback:** delete the new files.
**Runtime behaviour:** none (tests and offline script).

---

### Step 10: full verification and operational readiness

Operational step, not code. Each action needs separate authorisation.

1. Run the full suite and record counts.
2. Build a **new** staging index in a new directory with `--validity-ledger` pointing at a *proposal* ledger (no approved facts), then run `compare_staging_validity.py --ledger`.
3. Run the server on staging with `TG_PROVISION_VALIDITY=shadow` and review the shadow log.
4. Record a before/after hash of the live index tree and protected files.
5. Report which sources and provisions are ready, from the decision register and ledger.
6. Only after counsel approval, Gazette evidence and a re-signed approval by the approval authority (offline, using the existing signing script): bind the ledger hash in `source-status.json`. The agent does not sign.

**Acceptance:** suite green with the baseline skip and expected-failure counts; staging comparison shows 0 inconsistencies; shadow parity 100%; the live index tree hash is identical.
**Rollback:** delete the staging directory; unset the flag.
**Runtime behaviour:** none unless the owner sets the flag outside staging.

## 5. Cross-step test matrix

| Concern | Steps | Tests |
|---|---|---|
| Unapproved never authoritative (I4) | 1, 3, 6, 9 | property test, fabrication tests, server integration |
| Partial never answers current law (I5) | 1, 6, 9 | property test, replay-guard test, G.O. 53/16 scenario |
| Historical not current (I6) | 1, 6, 9 | undated query tests |
| `/chat` safeguards intact (I7) | 6, 9 | gate-order and gate-closed tests; AST isolation |
| Live data untouched (I8) | every step | sentinel hash test |
| Flags off by default (I1, I2) | 6, 9 | golden outputs, cache epoch, fingerprint, `open` never called |
| No fabricated approval or Gazette evidence (I9) | 3, 9 | decision and evidence validators |

## 6. Decisions and dependencies the owner must settle

| Before | Decision |
|---|---|
| Step 2 | Accept the source-status schema extension (A2), or choose the direct approval-record binding as a separate task |
| Step 3 | Accept LD-012 onward numbering (A8) |
| Step 6 | Flag names and the `off`/`shadow`/`restrict` ladder; keep `enforce` locked |
| `enforce` (not scheduled) | Counsel: the interval rule, the freshness window, instrument key scheme, treatment of appointing notifications such as G.O. 10, effect of unnamed supersession; plus Gazette prints, no-later-amendment searches and a re-signed approval |

## 7. Risks specific to implementation

| Risk | Mitigation |
|---|---|
| `server.py` is large and central; a hook error affects all answers | Single small hunk, flag default off, golden tests for I1 and I2, isolation test |
| Approval-bound loader change (Step 2) | Optional key, byte-identical real registry, existing tests unmodified |
| Authority leakage through legacy keys | A4: no ledger-derived `valid_*` in Chroma, ever |
| Chunker drift invalidates coverage | Text-hash selector; stale means unverified |
| Over-restriction hides valid text | Shadow mode first; shadow log reviewed before `restrict`; restrict is reversible by env |
| Reviewer capacity | Restrict mode delivers safety gains without any approval |
| Schedule tables yield few usable chunks | Accepted in v1; provision-level re-chunking is a later, separate task |
| Flag values mistyped | Unknown values map to `off` and log a warning |

## 8. What this roadmap does not do

- It does not implement anything, rebuild an index, or alter any manifest, source document, approval record, registry or live data.
- It does not provide counsel approval or Gazette evidence, and it blocks any record claiming either without a reviewer and a held file.
- It does not unlock penalty or compounding answers, or the `historical_legal_explanations` gate.
