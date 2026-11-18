# Provision-level legal validity: technical design

Status: proposal, 16-11-2026. Nothing here is implemented. No code, manifest, source document, approval record, schema, signature mechanism or index was changed, and nothing was rebuilt, committed, pushed or deployed.
Inputs: `VALIDITY-RECONCILIATION-REPORT.md`, `SOURCE-VALIDITY-WORKSHEET.md`, `backend/source_status.py`, `backend/legal_approval.py`, `backend/tg_ingest.py`, the staging index metadata (read from a scratch copy), and the G.O. 53/2025 and 16/2026 PDFs.

**Legal content rule.** This document defines containers and rules. It states no legal conclusion. Where it shows a date for the G.O. 53 and G.O. 16 example, the date is a *candidate quoted from the instrument's own text*, marked unapproved, and the design guarantees the retrieval path never reads it.

## 1. Why the current model fails, in one table

| Need | Current model (one range per manifest document) | Failure |
|---|---|---|
| G.O. 16 deletes column 8 of what G.O. 53 substituted | One range for each G.O. | Close G.O. 53 (wrong: other columns remain) or leave it open (wrong: column 8 shows as law) |
| Rule 81 changed inside the chapter-4 snapshot | Range per chapter file | Chapter cannot be both "in force" and "rule 81 amended" |
| Original rules vs amending G.O.s | Versions link only by manifest `id` | Chapter 4 and G.O. 77 are never seen as touching one provision |
| Start known, end unknown | `verified_continuing` needs 99991231; `verified_closed` needs a real end | Only `unknown` is possible, so the known start is wasted |
| History retrievable, never current | File-level `historical_hashes` | A file cannot be current for some provisions and historical for others |
| `provision_id` stability | Chunker output: `SCHEDULE` appears twice in G.O. 53; `Paragraph 3` is split in two parts | Not a safe key |

Observed in the staging index: G.O. 53 has chunks `THIRD SCHEDULE`, `SIXTH SCHEDULE`, `SEVENTH SCHEDULE` (pages 3 to 4, `answer_eligible: False`) and two chunks both named `SCHEDULE`. G.O. 16 has one chunk `SEVENTH SCHEDULE` (pages 1 to 2, `answer_eligible: False`). A chunk is a page-range slice, not a legal provision, and column 8 sits *inside* the Seventh Schedule chunk.

## 2. Design principles

1. **Provisions are identified by legal citation, not by chunk.** A curated provision key is the unit of validity. Chunks are mapped to keys by reviewed coverage records.
2. **Operations create versions.** Validity intervals are derived from approved operations (insert, substitute, delete, repeal), not typed in per document.
3. **Three-state ends and two-state starts.** An end is `closed`, `continuing_verified` or `unverified`. A start is `known` or `unknown`. Unknown is explicit, never a missing field.
4. **Asymmetric trust.** Unapproved ledger entries may *restrict* what is served. Only approved, signed-bound entries may make text *authoritative*.
5. **Ledger is the authority; chunk metadata is a projection.** A mismatch fails closed.
6. **Absent ledger means today's behaviour.** The model is additive.
7. **Validity never enables anything.** It cannot turn on penalty answers, compounding, or the `historical_legal_explanations` gate. Those gates stay as they are.

## 3. Data model

### 3.1 Entities

| Entity | Key | Notes |
|---|---|---|
| **Instrument** | `<juris>:<kind>:<number>/<year>`, for example `TG:ACT:5/1963`, `IN:ACT:8/2026`, `TG:GO:53/2025` | The jurisdiction prefix keeps same-number Acts apart. The two Acts numbered 8 of 2026 become `IN:ACT:8/2026` and `TG:ACT:8/2026`. A manifest document maps to one instrument (many documents may map to one: the 12 chapter snapshots all map to `TG:RULES:TMVR-1989`) |
| **Provision** | `<instrument>#<path>`, for example `TG:ACT:5/1963#sch7.col8` | A legal place in a hierarchy (instrument, schedule, column, rule, sub-rule, paragraph). Independent of any file. Path syntax is fixed by the validator; the names are counsel-confirmed, not guessed |
| **Provision version** | `<provision>@<n>` | One text state. Carries `text_locators` (manifest id, sha256, location) or `text: not_held`. Has a derived interval |
| **Operation** | `OP-<instrument>-<n>` | An act done by an instrument to targets: insert, substitute, delete, repeal, commence, supersede. Has an effective-from fact and evidence |
| **Coverage record** | `(manifest_id, sha256, chunk selector)` to provision keys | Says which provisions a chunk contains. Needed because a chunk can span several provisions |
| **Decision record** | `VD-<nnn>` | Approval wrapper for any validity fact; section 7 |

### 3.2 Facts that carry a date

Every date is a **fact object**, never a bare value:

```json
{"state": "approved" | "proposed" | "unknown",
 "date": 20260323 | null,            // read by retrieval only when state == approved
 "kind": "commencement",             // only commencement may feed validity; "gazette_direction", "publication", "issue" are recorded, never used
 "candidate": 20260323 | null,       // what the instrument text states; NEVER read by retrieval
 "evidence": [{"file","sha256","locator","note"}],
 "decision_ref": "VD-007" | null}
```

This enforces the date vocabulary of the worksheet in the data: issue, gazette direction and publication dates have their own `kind` and the loader refuses them as validity dates.

### 3.3 Version interval

```
start: known(date) | unknown          derived from the creating operation's effective_from, or from a base fact
end:   closed(date)                   derived from the closing operation, or entered as a fact
     | continuing_verified(checked_through, decision_ref)
     | unverified                     default
```

Derivation rule for a closing operation (one global modelling assumption, which counsel must approve once, section 12 item 1): the predecessor's last day is the day before the operation's effective-from date, and the successor starts on that date. Inclusive on both ends, as the code already does. If the effective-from is not approved, the end is `unverified`, not guessed.

### 3.4 Operation types

| Type | Effect on targets | Successor text |
|---|---|---|
| `insert` | New version, start = effective_from | In the amending instrument's own text |
| `substitute` | Closes predecessor, opens successor | Text held in the amending instrument (locator) |
| `delete` / `omit` | Closes predecessor, no successor; target state `deleted` | None. Predecessor stays as history |
| `repeal` | Closes predecessor (whole instrument or provision subtree) | None |
| `amend_words` ("for X substitute Y") | Closes predecessor, opens successor | `derived_unavailable` unless a reviewed consolidated text is held. The amending text is shown only with a fixed warning |
| `commence` | Supplies effective_from to *another instrument* (G.O. 10 to `TG:ACT:8/2026`) | None. It carries no content of its own |
| `supersede_unidentified` | Records an open question ("in supersession of any order inconsistent therewith" in G.O. 24) | None. Blocks nothing automatically; flagged for counsel |
| `scope_note` | Text qualifier such as "at registration of new vehicles only" | Stored as a note. Never evaluated, never used to widen or narrow validity |

Reserved and not modelled in v1: court stays and strike-downs (`external_event`), renumbering, and word-level consolidation.

## 4. Ledger file and Chroma representation

### 4.1 Ledger

`legal-status/provision-validity.json` (new, schema_version 1), peer of `source-status.json`:

```
instruments[]     instrument key, kind, jurisdiction, manifest_ids[]
provisions[]      provision key, parent, label
versions[]        version key, provision, text_locators | not_held, created_by_op, closed_by_op | null,
                  start (fact), end {closed|continuing_verified|unverified}
operations[]      op id, type, source instrument + locator, targets[], effective_from (fact), scope_note, decision_ref
coverage[]        manifest_id, sha256, chunk selector {provision_id, part, parts, page_start, page_end, text_sha256}, provisions[]
decisions[]       VD records (section 7)
```

Coverage selectors carry a `text_sha256` of the chunk text at mapping time. If the chunker output later changes, the mapping is **stale** and the chunk is treated as unverified until remapped.

### 4.2 Chroma projection (additive keys, all optional)

| Key | Type | Meaning |
|---|---|---|
| `vl_provisions` | str, `|`-joined provision keys | Coverage keys. Used for conflict detection and display, not for `where` filtering (Chroma cannot filter lists) |
| `vl_state` | str | `none` (no coverage, legacy), `uniform`, `partial`, `blocked` |
| `valid_from`, `valid_to` | int yyyymmdd | **Only** when `vl_state == uniform` and the interval is fully approved; same meaning as today, so existing routing keeps working |
| `vl_end_state` | str | `closed`, `continuing_verified`, `unverified` |
| `vl_checked_through` | int | Horizon of a `continuing_verified` end |
| `vl_ledger` | str | First 16 hex of the ledger SHA-256 the projection was built from |

Runtime resolution reads the ledger. The chunk projection is checked against it at startup: a wrong `vl_ledger`, or a `vl_state` that disagrees with a recomputation, makes that chunk `unverified`. Editing the ledger after approval therefore changes nothing silently, and a ledger change that only alters intervals does not need a rebuild. A change to coverage does.

### 4.3 What `partial` means

A chunk is `partial` when its covered provisions do not share one interval: some are in force, some deleted, some unknown. The Seventh Schedule chunk of G.O. 53 is the example. A `partial` chunk is never authoritative and, for current-law answers, is `blocked` unless counsel approves showing it with a fixed warning (open decision, section 12). Re-chunking at provision level is the long-term fix and needs reviewed table extraction first.

## 5. Retrieval semantics

Let `d` be the offence date (or none) and `T` today. For each chunk the resolver returns one of: `authoritative`, `historical_authoritative`, `unverified`, `not_in_force` (drop), `blocked`.

### 5.1 Per covered provision, one version at a time

Select the version(s) whose approved interval could cover the date; then:

| Query | Start | End | Result |
|---|---|---|---|
| dated `d` | known, `d < start` | any | `not_in_force`, drop. Allowed because a known commencement is a *negative* fact |
| dated `d` | known, `d >= start` | closed, `d <= end` | `historical_authoritative` (or `authoritative` if the version is also current) |
| dated `d` | known, `d >= start` | closed, `d > end` | `not_in_force`, drop |
| dated `d` | known, `d >= start` | continuing_verified, `d <= checked_through` | authoritative |
| dated `d` | known, `d >= start` | continuing_verified, `d > checked_through` | `unverified` |
| dated `d` | known, `d >= start` | unverified | `unverified` (the end may precede `d`) |
| dated `d` | unknown | any | `unverified` |
| dated `d` | no version (`text: not_held` or gap) | | `unverified`, with the "no text held for that date" note |
| undated | known, `start <= T` | continuing_verified and fresh | authoritative |
| undated | known, `start <= T` | unverified / stale | `unverified` current-law warning (today's behaviour for unversioned text; never promoted) |
| undated | | closed | `not_in_force` for current law; kept for dated questions only |

"Fresh" means `checked_through` is within a freshness window. The window is a counsel and product decision; the design supplies the parameter and defaults to *no window approved, so nothing is fresh*.

### 5.2 Per chunk

- All covered provisions give the same class: the chunk takes it.
- Covered provisions differ: `partial`, never authoritative.
- Any covered provision is `blocked` or conflicted: `blocked`.
- No coverage: `vl_state: none`, the legacy path (existing `valid_from`/`valid_to` or unversioned) applies unchanged.

### 5.3 Historical versus current

A version is **servable as current** only when it is `continuing_verified` and fresh and approved. A **closed** version is `historical`: it stays in the index, is served only to dated questions whose date lies inside its interval, and is never returned for an undated question. This is the existing `historical_hashes` rule lifted from file to provision. The file-level lifecycle keeps a file *active* while any of its provisions is current, and the file's stale provisions are protected by the chunk-level `partial` rule.

## 6. Conflict detection

Run statically when the ledger is loaded and dynamically per query.

| # | Conflict | Detection | Outcome |
|---|---|---|---|
| C1 | Overlap: two versions of one provision both cover a date | Interval intersection on approved starts and ends. An `unverified` end counts as open-ended for this check | Ledger load error for approved data; at query time both versions are `unverified` |
| C2 | Gap: no version covers a date between known intervals | Walk versions in order | Mark gap. Query returns `unverified`, never the nearest version |
| C3 | Predecessor of an operation is missing | A `substitute`/`delete` target has no version | The operation is `orphan`. The version before it is recorded `text: not_held` with an unknown start (G.O. 53's base from G.O. 22/2022 is the case) |
| C4 | Two operations, same provision, same effective date | Group by (provision, effective date) | Ordering ambiguous: both unverified |
| C5 | Operation names a provision absent from every held text | Target path missing in coverage | Warn. Operation stays `proposed` |
| C6 | Snapshot text vs amending operation | A coverage record from an `unverified_snapshot` source covers a provision that an approved operation changed | Snapshot version marked `pre-amendment` for dates on or after the operation. For chapter 4 rule 81 this makes the snapshot chunk `blocked` for current law |
| C7 | Cross-document, same provision key, two chunks both authoritative | Group retrieved chunks by `vl_provisions` | Replaces the current `(manifest_id, provision_id)` check; both go to `unverified`, `conflicts` counted |
| C8 | Same-number instruments | Key includes jurisdiction | A routing test must show `IN:ACT:8/2026` data cannot touch `TG:ACT:8/2026` |
| C9 | Stale coverage | `text_sha256` mismatch | Chunk `unverified` |
| C10 | Projection drift | `vl_ledger` or recomputed `vl_state` mismatch | Chunk `unverified` |
| C11 | Candidate dates present without approval | `candidate` set, state not `approved` | Informational. Never read |

## 7. Approval requirements

Every validity fact (a start date, an end date, a `continuing_verified` claim, an operation's targets, a coverage record, a supersession) sits behind a **decision record**:

```json
{"decision_id": "VD-0xx",
 "subject": "go-16 deletes sch7.col8 effective ...",
 "question": "...", "evidence_available": [], "evidence_required": [],
 "status": "pending" | "evidence_incomplete" | "evidence_complete" | "approved" | "rejected" | "revoked",
 "prepared_by": "...", "reviewer": {"name","designation","organisation"}, "review_date", "decision", "rationale", "conditions"[],
 "replaces": "VD-0yy" | null}
```

Rules:

1. **Only a human reviewer sets `approved`.** Tooling may write `pending`, `evidence_incomplete` and `evidence_complete`. This is the same split the Stage 22 register uses (LD-001 to LD-011), so VD and LD share one register and one reviewer workflow. LD-004 to LD-008 become the first VD records.
2. **Evidence by fact type:**

| Fact | Minimum evidence recorded in the decision |
|---|---|
| Commencement date | The instrument's operative clause or commencement notification, by file hash and locator, plus the Gazette print if the clause ties commencement to publication |
| Closing date | The closing operation's text and its own approved effective-from |
| `continuing_verified` | A recorded no-later-amendment search: scope, sources searched, date searched (becomes `checked_through`), searcher, result |
| Provision identity and operation targets | The amending text locator and counsel confirmation of the legal path |
| Coverage record | Chunk text hash and reviewer confirmation of the provision list |

3. **Binding to the signed approval without changing the approval schema.** The approval record already names `source_status_sha256`, so editing `source-status.json` invalidates the signature. The design adds a top-level `validity_ledger_sha256` to `source-status.json`. Changing the ledger then changes the source-status file, which changes the hash the signed record names. No change to `legal_approval.py`, the record schema or the signing script is needed. The one code change is in `source_status.py` (accept and verify the new key). If counsel would rather name the ledger hash in the approval record directly, that is a schema change to the approval record and the signing script, and must be a separate, explicitly authorised task.
4. **Asymmetric trust.** A ledger entry whose decision is not `approved`, or a ledger not bound by the active signed approval, runs in **restrict-only mode**: it can drop, block or mark `partial`, and can never make text authoritative.
5. **Append-only history.** An approved decision is never edited. A change is a new decision with `replaces`, mirrored into an audit log like `legal/lifecycle/audit.jsonl`.
6. **Freshness.** A `continuing_verified` fact lapses to `unverified` for current-law answers when `checked_through` is older than the freshness window, once counsel sets one.
7. **Separation of roles.** The loader refuses `approved` records where `prepared_by` equals the reviewer name.

## 8. Worked example: G.O. 53/2025 and G.O. 16/2026

Dates in this section are **candidates quoted from the instrument text**; each stays unapproved and is never read by retrieval until a decision approves it.

### 8.1 Instruments and provisions

| Key | Meaning | Held? |
|---|---|---|
| `TG:ACT:5/1963` | Telangana Motor Vehicles Taxation Act, 1963 (text not held) | no |
| `TG:ACT:5/1963#sch7` | Seventh Schedule | via G.O. 53 text |
| `TG:ACT:5/1963#sch7.col8` | Column 8 and its entries ("Second or more personalized vehicles up to ten seats owned by an individual", additional 2%, at registration of new vehicles only) | via G.O. 53 text (pages 3 to 4) |
| `TG:ACT:5/1963#sch7.col1..col7` and the remainder | Other columns | via G.O. 53 text |
| `TG:GO:53/2025`, `TG:GO:16/2026` | Amending instruments | manifest ids `go-ms-53-2025-trb`, `go-ms-16-2026-trb` |

Provision path names (`sch7`, `col8`) are proposals; counsel confirms the citation form.

### 8.2 Operations

| Op | Type | Source and locator | Targets | Effective-from fact |
|---|---|---|---|---|
| `OP-GO53-1` | `substitute` | G.O. 53, the paragraph substituting the Seventh Schedule (pages 3 to 4; register LD-005 evidence) | `#sch7` (all columns) | `state: proposed`, `date: null`, `candidate: 20250814`, candidate basis "G.O. 53 para 2: comes into force with effect from 14.08.2025", kind `commencement`, decision `VD-a` (pending) |
| `OP-GO16-1` | `delete` | G.O. 16, AMENDMENT clause: "column No.8, and the entries relating thereto ... shall be deleted" | `#sch7.col8` only | `state: proposed`, `date: null`, `candidate: 20260323`, basis "G.O. 16 para 4", decision `VD-b` (pending) |
| `OP-GO16-scope` | `scope_note` | G.O. 16, same clause | `#sch7.col8` | note: "at registration of new vehicles only". Not evaluated |

Not modelled: G.O. 22/2022, the earlier Seventh Schedule order, which G.O. 53 and G.O. 16 cite and which is not held. It becomes version `sch7@0` with `text: not_held`, start `unknown`.

### 8.3 Versions and intervals once both decisions are approved

| Version | Start | End | Servable |
|---|---|---|---|
| `sch7@0` (base, G.O. 22/2022, not held) | unknown | closed, derived from `OP-GO53-1` | never; no text |
| `sch7.col1..7@1`, `sch7.rest@1` (G.O. 53) | `OP-GO53-1` date | `unverified` until a no-later-amendment search is approved, then `continuing_verified(checked_through)` | dated: after start only if end approved; current: only if `continuing_verified` and fresh |
| `sch7.col8@1` (G.O. 53) | `OP-GO53-1` date | closed, derived from `OP-GO16-1` | historical only, and only for dates inside the interval |

### 8.4 Coverage

One reviewed coverage record: chunk `go-ms-53-2025-trb` / `SEVENTH SCHEDULE` / part 1 of 1 / pages 3 to 4 covers `sch7.col1`..`sch7.col8` and the rest. Its `vl_state` is `partial` once `col8` closes while the others stay open or unverified. Likewise the G.O. 16 chunk covers `sch7.col8` (as the deleting instrument), not as text of the schedule.

### 8.5 Behaviour, with symbols `D53` (start of G.O. 53 text) and `D16` (start of G.O. 16 deletion)

| Query date | Ledger entries unapproved | Both approved, G.O. 53 end `unverified` | Both approved, G.O. 53 `continuing_verified` for other columns |
|---|---|---|---|
| Before `D53` | legacy (unversioned) | `sch7@0`: no text held, `unverified` with note | same |
| `D53` to before `D16` | legacy | col8 chunk: `unverified` (end unverified) | `partial` chunk; col8 provision `historical_authoritative` only if counsel allows partial display; otherwise `blocked` |
| On or after `D16` | legacy, plus **restrict-only**: the chunk is marked `partial` and cannot be authoritative | `partial`, never authoritative; column 8 never presented as current | same; other columns authoritative only when chunks are re-cut at provision level |
| Undated | legacy (the chunk is already `answer_eligible: False`) | `partial` and blocked as current | same |

What the example shows:

- The G.O. 53 *file* stays active (not closed as a whole), yet column 8 can never be served as current once `OP-GO16-1` is approved. Today's schema cannot do this.
- The unapproved state is already *safer than today*: the proposed deletion restricts the chunk without any approval, because restriction is allowed in the safe direction.
- Because the Seventh Schedule is one table chunk, the other columns also stay non-authoritative until chunks are cut at provision level. That is the cost of the v1 chunk model, stated rather than hidden.

### 8.6 Second example, briefly: rule 81

`TG:RULES:TMVR-1989#r81` has sub-rule provisions `r81.sr1` ... `r81.srN`. The held G.O. 77 text is the source for an operation with `targets` for each sub-rule it omits or substitutes. The register (LD-001) and the audit disagree on which sub-rules are substituted ((3), (5), (6) or (3), (6)), so **the ledger refuses to approve the operation until a reviewer settles the target list against the held text**. Conflict C6 then marks the chapter-4 snapshot chunk `pre-amendment`. No other part of chapter 4 changes.

## 9. Migration

| Phase | Change | Behaviour change |
|---|---|---|
| M0 | Add `backend/validity_ledger.py` (loader, validator, resolver). Empty ledger | None |
| M1 | Adapter: each existing manifest entry becomes an implicit whole-document provision `<instrument>#*`. `unknown` gives no entry. `verified_continuing` and `verified_closed` map to `continuing_verified` and `closed`. Existing 20 manifests (all `unknown`) produce no entries | None, test proves identical routing |
| M2 | Coverage proposals: a script derives candidate coverage from chunker `provision_id` for rule and paragraph chunks. Output is a proposal file with `status: proposed`. Tables are listed for manual mapping | None |
| M3 | Shadow mode: the server resolves with the ledger and with the legacy path, logs differences, serves legacy. Extend `scripts/compare_staging_validity.py` to diff | None |
| M4 | Chroma projection keys (`vl_*`) on a staging index only; existing `valid_from`/`valid_to` unchanged | Staging only |
| M5 | After counsel approval and a bound signature: switch serving to ledger resolution for covered chunks. Uncovered chunks stay legacy | Covered chunks only |
| M6 | Lifecycle: registry versions record `ledger_sha256`; `retainable` consults provision closures; file-level `close_validity` becomes an adapter over ledger operations | Historical retention |
| M7 | Re-chunk tables at provision level for provisions where extraction is reviewed | Retrieval granularity |

Rollback: remove the ledger file and `validity_ledger_sha256`; behaviour returns to M0. Chroma `vl_*` keys are ignored when no ledger is loaded.

## 10. Backward compatibility and fail-closed rules

| Condition | Result |
|---|---|
| No ledger file | Today's behaviour exactly |
| Ledger malformed, wrong schema, unresolved reference, or overlap among approved versions | Ledger rejected. Approval treated as inactive for the validity feature (same pattern as an invalid source-status registry). Dated questions refuse; undated behave as today. Error logged |
| Ledger present but not bound by a valid signed approval | Restrict-only mode |
| Entry not `approved` | Restrict-only for that entry |
| Candidate dates, gazette-direction, publication, issue dates | Never read as validity |
| Start unknown or end unverified | Never authoritative for dated queries after the start; never current-law authoritative |
| `continuing_verified` with stale `checked_through` | `unverified` for current law |
| Stale coverage hash or projection drift | Chunk `unverified` |
| `partial` chunk | Never authoritative |
| Any conflict (C1, C2, C4, C7) | Both sides `unverified`; none of the versions is used |
| Penalty, compounding, fine and historical-explanation gates | Unchanged. Validity cannot open them |
| Index built without `vl_*` | Legacy path |

The existing chunk keys (`valid_from`, `valid_to`, `validity_status`) stay valid for the legacy path, and the manifest keys added in the earlier task keep working through the M1 adapter.

## 11. Implementation steps, risks

### 11.1 Steps (ordered; each ships behind a flag that defaults to off)

1. Write `backend/validity_ledger.py`: schema, loader, validator (C1 to C5), resolver (section 5). Unit tests: version interval derivation, tri-state ends, each row of the section 5.1 table.
2. `source_status.py`: accept and verify top-level `validity_ledger_sha256`. Tests: tamper, missing, mismatched hash.
3. Decision-record checks: role separation, evidence by fact type, `replaces` chain. Tests mirroring the Stage 22 register rules.
4. Adapter M1: manifest `validity_*` to implicit whole-document provisions. Test: all 20 current entries yield zero ledger entries and routing is unchanged.
5. Coverage tooling (M2): proposal generator and `text_sha256` staleness check.
6. Resolver integration in `offence_date.route_documents` and `server._retrieve` (provision-aware conflict C7, classes `partial` and `blocked`), behind a flag. Replace the `(manifest_id, provision_id)` clash key with provision keys when `vl_provisions` exists.
7. Chroma projection and `index_validity` / `build_telangana_index.verify_staging` extensions; staging build only. Extend `compare_staging_validity.py` (shadow-mode diff, section 9 M3).
8. Lifecycle: `retainable` by provision closure; `close_validity` adapter.
9. Fixture suite using the G.O. 53/16 example with **synthetic dates**, plus rule 81 with a deliberately conflicting target list, same-number Acts (C8), gap (C2), stale coverage (C9), restrict-only mode, and a proof that candidate fields are never read.
10. Full suite run, then staging rebuild, comparison, and approval refresh as separate, explicitly authorised tasks.

### 11.2 Risks

| Risk | Why it matters | Mitigation |
|---|---|---|
| **Modelling assumptions are legal** (end = day before successor's start; day-of-commencement semantics) | A wrong global rule corrupts every interval | Isolate in one function; require counsel approval once; make it a ledger-level parameter |
| **Chunk granularity** | Tables and multi-provision chunks yield `partial`, so little text becomes authoritative in v1 | Accept for v1; M7 re-chunking where extraction is reviewed |
| **Curation load** | Provision keys, coverage and decisions are manual; 12 chapters of rules are large | Prioritise by the worksheet ranking (registration, licensing, tax, e-challan); leave the rest legacy |
| **Stale `continuing_verified`** | A search is true only through its date; law changes | `checked_through` and freshness window; default no window, so nothing is fresh |
| **Single approval binding** | Putting the ledger hash in `source-status.json` couples two files' edits | Document it; offer the direct approval-record binding as a separately authorised alternative |
| **False assurance** | An approved ledger does not make text the law; the texts behind `not_held` provisions are missing | Fixed warning templates; "no text held" notes; no change to gates |
| **Chunker drift** | A re-chunk silently invalidates mappings | `text_sha256` coverage check, C9 |
| **Projection vs ledger drift** | Two representations | Ledger authority and startup recomputation (C10) |
| **Reviewer capacity** | Approval is the bottleneck; evidence (Gazette prints) is not held | Restrict-only mode delivers safety gains without approvals; authoritative status waits |
| **Same-number and cross-jurisdiction collisions** | Already occurred with Act 8 of 2026 | Jurisdiction in the instrument key; test C8 |
| **Performance** | Per-chunk resolution on each query | Ledger indexed in memory by provision; resolution is O(covered provisions) per chunk |
| **Scope creep into Central law** | The same model is needed for the MV Act (many provisions, one commencement date), but Central scope is undecided (LD-011) | Design is jurisdiction-neutral; no Central data added now |

### 11.3 What this does not solve

- Missing texts: the Taxation Act, Act 8 of 2026 (Telangana), G.O. 22/2022, six rule 81 orders, Gazette prints, and the compounding schedule.
- Word-level amendments without a consolidated text (`derived_unavailable`).
- Whether any date is correct. That stays a counsel decision.

## 12. Decisions needed from counsel and the project owner

1. Accept the interval derivation rule (predecessor ends the day before the successor's commencement; inclusive ends).
2. May a `partial` chunk be shown for current law with a fixed warning, or is it blocked?
3. Freshness window for `continuing_verified`, or no window (nothing is ever fresh without re-verification).
4. Provision path names and the instrument key scheme.
5. How `commence` notifications (G.O. 10) attach to an Act that is not held.
6. Whether an unnamed supersession ("any order inconsistent therewith") must block `continuing_verified` for related provisions.
7. Whether to bind the ledger through `source-status.json` (no approval-schema change) or directly in the approval record (schema change, separate task).
8. Whether `VD-` decisions share the existing LD register or form a second register.
