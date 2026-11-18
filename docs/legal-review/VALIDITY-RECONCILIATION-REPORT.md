# Validity reconciliation report

Date: 16-11-2026. Reconciles `SOURCE-VALIDITY-WORKSHEET.md` with the legal-verification and approval work already in the repository.
No legal research was redone. No manifest, source document, approval record, code or index was changed. Nothing was committed, pushed or deployed.
This report supersedes two statements in the worksheet: the unresolved 15-08-2026 baseline row (section 3 of the worksheet) and item 5 of its priority-A list. It also corrects a miscount (section 7).

## 0. Premise check: no approved matrix or approval record exists

The task assumed a "final approved legal rule matrix" and "completed" legal verification and approval. The repository does not contain them:

- `eval/deployment/FINAL-LEGAL-ADVISOR-CLOSURE-REPORT.md`: "the completed approval could not be imported. The approval artifact is not present." The owner's sign-off is reported in chat only, with no advocate name, date, scope or signed record.
- `eval/deployment/LEGAL-ADVISOR-WORKSTREAM-HANDOVER.md`: a rule matrix, a Section 200 matrix and a counsel memorandum "do not exist".
- `eval/legal-validation/stage-22-legal-decision-register.json`: 11 decisions (LD-001 to LD-011), **0 approved**, 4 `pending`, 7 `evidence_incomplete`, every reviewer and decision field null.
- `legal-status/source-status.json`: all 20 entries carry `review: {reviewer: null, decision: null}`. 13 are `unverified_snapshot`, 7 are `official_text_commencement_unconfirmed`. None is `verified_current`.
- `legal/lifecycle/registry.json`: 20 sources, no active version; all quarantined. No signed `telangana-approval.json` exists.

So **nothing in the repository is counsel-approved**, and I have not treated anything as approved. "Established" below means *source-verified*: a primary instrument was opened and read in a recorded report. That is evidence, not approval, and it does not by itself satisfy a `verified_*` entry in the manifest.

Tiers used in this report:

| Tier | Meaning |
|---|---|
| **A: source-verified** | Primary instrument obtained and read; wording or date checked in a recorded report. Not counsel-approved |
| **B: candidate** | A date the instrument's own text states, held only as a department copy, Gazette print missing, repo status `commencement_unconfirmed` |
| **C: unresolved** | No usable evidence, or the evidence conflicts |

## 1. Findings already established, matched to source IDs

### 1.1 Tier A: source-verified

| Finding | Instrument and evidence | Source ID in the 20 | Integer if later entered |
|---|---|---|---|
| Central: MV Act 1988 amendments in serial 51 of Act 8 of 2026 commence **15-08-2026** | S.O. 4100(E) of 24-07-2026 (Gazette Part II s.3(ii) No. 3930, ID CG-DL-E-25072026-274798), opened. Act 8 of 2026 text read (e-Gazette ID CG-DL-E-08042026-271642); 56 of 57 footnotes verified, 1 marginal-heading mismatch (s.210A) (`MOTOR-VEHICLES-ACT-VERIFICATION-REPORT.md` sections 9.2, 10) | **None.** This is Central law, outside the 20 | 20260815 (Central MV Act only) |
| Telangana Act 8 of 2026 is appointed to commence **01-03-2026** | G.O.Ms.No. 10/2026 operative text: "appoints the 1st day of March, 2026". Wording checked against the PDF 09-11-2026 (manifest note). Confirmed in `LEGAL-SOURCE-COMPLETENESS-AUDIT.md` 5.5 and 6.2 item 1 | `go-ms-10-2026-trb` | 20260301 (the Act's commencement) |
| G.O.Ms.No. 16/2026 states it is in force **w.e.f. 23-03-2026** and deletes column 8 of the Seventh Schedule | Para 4 and scope read and checked against the PDF 09-11-2026 (manifest note; LD-005 evidence) | `go-ms-16-2026-trb` | 20260323 |

Tier A for the State items is limited: the text is read from the department G.O. copy. The Telangana Gazette print is not held for any of them, and the repo's own status for all seven G.O.s stays `official_text_commencement_unconfirmed`. These dates therefore support a candidate, not a verified entry (section 5).

### 1.2 Tier B: candidates stated in the instrument's own text

| Source ID | Wording | Candidate | Caveat |
|---|---|---|---|
| `go-ms-53-2025-trb` | "shall come into force with effect from 14.08.2025" (para 2); directs Gazette Extraordinary 14.08.2025 | 20250814 | Found while preparing the worksheet; no earlier recorded review checked it. Gazette print missing |
| `go-ms-25-2026-trb` | "with immediate effect"; directs Gazette 02.06.2026 | 20260602 only if the Gazette is dated 02-06-2026 | Commencement is tied to publication, which is not evidenced. LD-008 pending |

### 1.3 Tier C: unresolved, by source

| Source ID | Why |
|---|---|
| `go-ms-77-2025-trb` | No commencement clause in the text. 15-11-2025 is a Gazette *direction*. LD-001 to LD-003, LD-009 open |
| `go-ms-24-2026-trb` | Order says "draft Notification"; notification commences on publication. Draft or final unresolved (LD-004) |
| `go-ms-32-2026-trb` | No Gazette direction or commencement clause (LD-008) |
| `tmvr-1989-chap-1` to `-12`, `tmvtr-1963` | Unverified snapshots. Rule 1(3) commencement notification, Telangana adaptation instrument and amendment lists are not held |

No date was taken from an issue date, a Gazette direction, a snapshot date or a draft note. The 25-02-2026 issue date of G.O. 10 is the trap the older manifest fell into (audit 6.2 item 1); the current manifest holds `effective_date: null`.

## 2. The 1 March 2026 and 15 August 2026 "conflict" is not a conflict

Two different Acts both carry the number 8 of 2026, and they amend different statutes.

| | Act A (Central) | Act B (Telangana) |
|---|---|---|
| Title | The Jan Vishwas (Amendment of Provisions) Act, 2026, No. 8 of 2026 | The Telangana Motor Vehicles Taxation (Amendment) Act, 2026, No. 8 of 2026 |
| Amends | Many Central enactments; **serial 51** is the Motor Vehicles Act, 1988 (59 of 1988) | The Telangana Motor Vehicles Taxation Act, 1963 (Act 5 of 1963) |
| Enacted | Assent 07-04-2026; Gazette of India 08-04-2026 | Bill 5 of 2026, reported passed 02-01-2026 (secondary); text not held |
| Commencement instrument | **S.O. 4100(E)**, 24-07-2026, under s.1(2) of the Act, appoints **15-08-2026** for serial 51 | **G.O.Ms.No. 10**, 25-02-2026, under ss.3 and 17 of the Taxation Act, appoints **01-03-2026** |
| Source ID in the 20 | none | `go-ms-10-2026-trb` |
| Evidence tier | A (Gazette opened) | A-limited (department G.O. copy) |

Consequences:

- The 15-08-2026 band in `backend/offence_date.py` ("Act 8 of 2026, S.O. 4100(E) commencement") refers to **Act A**, the Central MV Act amendments. It is correct for Central MV Act provisions such as s.200 and has no bearing on `go-ms-10-2026-trb` or the Telangana taxation sources.
- `go-ms-10-2026-trb` carries Act B's 01-03-2026. Do not apply the 15-08-2026 band to it.
- The Act verification report already says to keep the two apart (section 8, item 8). The code comment does not.
- Still open, not part of this resolution: Act A's section 3 (10 per cent fine revision every three years) was not tested for commencement and interplay with s.199B. The content of Act B and its effect on the Taxation Act schedules are unknown (LD-007).

## 3. Source-by-source reconciliation

Legend for the last column: **UNKNOWN** = must stay `unknown`. **After sign-off** = could receive metadata once counsel approves the evidence (section 5).

| # | Source ID | Established (tier) | Candidate | Unresolved | Partial / supersession | Metadata |
|---|---|---|---|---|---|---|
| 1 | `tmvr-1989-chap-1` | none | none | Rule 1(3) commencement notification; adaptation; base G.O.Ms.No. 216 of 07-08-1989 Gazette print. Snapshot header says Andhra Pradesh | Definitions (rule 2) amended since? unknown | UNKNOWN |
| 2 | `tmvr-1989-chap-2` | none | none | Same, plus licensing-fee rule amendments | Unknown per-rule amendments | UNKNOWN |
| 3 | `tmvr-1989-chap-3` | none | none | Same | Same | UNKNOWN |
| 4 | `tmvr-1989-chap-4` | none | none | Same. Rule 81 text in snapshot differs from G.O. 77 (LD-001, LD-002) | **Rule 81** changed by G.O. 77/2025 and six unheld orders (2014 to 2018, LD-003); reported Rule 72-A (2015, secondary); G.O. 41 of 2015 attributed to both chains (audit 6.2 item 3) | UNKNOWN |
| 5 | `tmvr-1989-chap-5` | none | none | Same | **Rule 217** table pre-2008; G.O. 332/2008 (AP, held, not indexed) revises it; applicability in Telangana unresolved (LD-010) | UNKNOWN |
| 6 | `tmvr-1989-chap-6` | none | none | Same | Unknown | UNKNOWN |
| 7 | `tmvr-1989-chap-7` | none | none | Same | Unknown | UNKNOWN |
| 8 | `tmvr-1989-chap-8` | none | none | Same | Unknown | UNKNOWN |
| 9 | `tmvr-1989-chap-9` | none | none | Same | Unknown | UNKNOWN |
| 10 | `tmvr-1989-chap-10` | none | none | Same; section references (130, 133, 158, 202, 203) vs later Central amendments unchecked | Unknown | UNKNOWN |
| 11 | `tmvr-1989-chap-11` | none | none | Same | Unknown | UNKNOWN |
| 12 | `tmvr-1989-chap-12` | none | none | Same | Unknown | UNKNOWN |
| 13 | `tmvtr-1963` | none | none | Adaptation instrument (reportedly G.O.Ms.No. 2, secondary); amendments; only rules 1 to 17 are indexed (audit 5.5) | Partial coverage of the Rules | UNKNOWN |
| 14 | `go-ms-53-2025-trb` | none | 20250814 (Tier B) | Gazette print of 14-08-2025; G.O.Ms.No. 22/2022 base not held; effect of Act B on the schedules (LD-007) | **Partly superseded by G.O. 16/2026** (column 8 of the Seventh Schedule only; LD-005, LD-006). Five of seven chunks already excluded from answering for extraction reasons | UNKNOWN today. After sign-off only with a provision-level split (section 4) |
| 15 | `go-ms-77-2025-trb` | none | none | Commencement clause; Gazette print; LD-001 to LD-003, LD-009 (alternate file hash `74a6839d...` absent) | Amends rule 81 only. The register says it omits (1), (2), (4) and substitutes (3), (5), (6); the audit says it substitutes (3) and (6). The held text must settle this before any provision-level entry | UNKNOWN |
| 16 | `go-ms-10-2026-trb` | 20260301 as Act B's commencement (Tier A, limited) | | Act B text not held; Gazette print of 01-03-2026; whether this G.O.'s own range equals the Act's | None. An appointing notification has no schedule content of its own | After sign-off, with a modelling decision (section 4, item 6) |
| 17 | `go-ms-16-2026-trb` | 20260323 (Tier A, limited) | | Gazette print of 23-03-2026; amendments after that date not searched | It is the superseding half of the G.O. 53 pair | After sign-off. Closest to ready |
| 18 | `go-ms-24-2026-trb` | none | none | Draft or final (LD-004); G.S.R. 48(E) of 20-01-2026 not held; the orders it supersedes are unnamed | "in supersession of any order inconsistent therewith": unidentified | UNKNOWN |
| 19 | `go-ms-25-2026-trb` | none | 20260602 conditional (Tier B) | Gazette print; LD-008 pending; G.S.R. 48(E) | None known | After sign-off, if the Gazette print confirms the date |
| 20 | `go-ms-32-2026-trb` | none | none | Commencement clause absent; whether an administrative order needs a range (LD-008) | None known | UNKNOWN |

Totals: **16 must remain unknown** (the 13 snapshots plus G.O. 77, 24 and 32). **4 are candidates for metadata after counsel sign-off**: G.O. 16, G.O. 10, G.O. 25 and G.O. 53 (G.O. 53 only with a provision-level split). **0 can receive verified metadata today.**

## 4. What the one-range-per-document schema cannot represent

The manifest holds one `valid_from`/`valid_to` per document and the index holds one range per chunk set derived from it. Established or reported cases it cannot express:

1. **G.O. 53 and G.O. 16.** G.O. 16 deletes column 8 of the Seventh Schedule only. G.O. 53 stays in force for the rest. Closing G.O. 53 as a whole would be wrong; leaving it open would present column 8 as current law. The Stage 22 register (LD-006) wants a chunk-level "superseded in part" flag. `source-status.json` already has `provision_overrides` for text status, but the validity schema has no equivalent.
2. **Rule 81 inside `tmvr-1989-chap-4`.** G.O. 77 changes only rule 81. The chapter is a single document with six unheld earlier orders and a snapshot that predates G.O. 77. The versions link only by manifest `id`, so chapter 4 and `go-ms-77-2025-trb` are not recognised as overlapping provisions.
3. **Rule 217 inside `tmvr-1989-chap-5`.** Pre-2008 table; the revising instrument (G.O. 332/2008) is outside the 20 and its applicability is unresolved.
4. **Per-rule amendments in all 12 chapters.** Any chapter-wide range implies every rule shares one commencement and one end date. Amendment lists are not held.
5. **Reported Rule 72-A (2015)** and G.O. 41 of 2015 appear in two chains. Unresolved.
6. **G.O. 10 as an appointing notification.** It has no operative content of its own. The date it fixes belongs to Act B, which is not held. The schema cannot say "this document commences another document".
7. **G.O. 24's supersession** of unnamed earlier orders.
8. **Start known, end unknown.** `verified_continuing` needs `valid_to = 99991231`, and `verified_closed` needs a real end date. A source with a stated commencement and no search for later amendment fits neither. Under the current rules it can only be `unknown`.
9. **Consolidations labelled "as on" a date** (the MV Act PDF "as on 15-08-2026"). That is a currency date, not a commencement date. It cannot serve as `valid_from`. The same applies to Central law generally: Act A changed 45 items in one Schedule serial on one date, and a pre-15-08-2026 text would be needed for earlier offence dates.

## 5. Which sources can safely receive verified metadata

- **None today.** For every source, at least one of these is missing: counsel sign-off (0 of 11 decisions approved), a Gazette print, or a search showing no later change.
- A `verified_*` entry carries a `validity_basis` and implies the date is legally verified. Entering one before counsel approves would present unapproved evidence as verified. The approval record, schema and signature stay untouched.
- **Order in which metadata could be entered after sign-off:** G.O. 16, G.O. 10 (after the modelling decision), G.O. 25 (if the Gazette confirms), G.O. 53 (after the provision-level split).
- Even then, `valid_to = 99991231` needs a recorded check that nothing later amended or repealed the instrument. No such check exists for any State instrument.

## 6. Missing central legislation and fine-schedule sources (separate from the 20-source exercise)

These belong to a different work stream. They do not change any of the 20 sources' status.

**Central legislation (Telangana-only scope decision of 08-11-2026 currently excludes it; LD-011 and counsel question 1 pending)**

| Item | State |
|---|---|
| Motor Vehicles Act 1988, consolidated | India Code PDF "as on 15-08-2026" obtained and verified; stored checksum mismatch unresolved; "a copy for counsel's review, not for ingestion". Not in the index |
| Jan Vishwas Act 2026 (Act A) and S.O. 4100(E) | Obtained, Tier A. Act A s.3 commencement untested |
| MV Act before 15-08-2026 (for historical offence dates) | Only the 21-05-2025 portal text index seen; transitional treatment of pre-15-08-2026 offences unresolved |
| CMVR 1989 | No current official consolidation (India Code files stale to about 2016-17). Principal G.S.R. 590(E) of 02-06-1989 not obtained. 7 final 2026 amendments identified; at least 8 unidentified; many 2017-2025 amendments unincorporated |
| G.S.R. 48(E) of 20-01-2026; Rule 167A history 2021-2025; G.S.R. 575(E) of 11-08-2021 | Needed to read G.O. 24, 25 and 32 correctly; not held or not enumerated |
| Motor Vehicles (Driving) Regulations 2017 | Not held. Rules of the Road Regulations 1989 held, not indexed, probably superseded (secondary) |
| S.O. 1306(E) of 12-03-2024 (TG registration mark) | Not opened |

**Telangana sources outside the 20**

| Item | State |
|---|---|
| Telangana Taxation Act 1963 (Act 5 of 1963) and Act B text | Not held |
| G.O.Ms.No. 22 of 07-05-2022 and earlier schedule orders | Not held |
| Gazette prints for G.O. 53, 77 (2025) and 10, 16, 24, 25, 32 (2026) | Not held |
| Telangana adaptation of the 1989 rules and the Taxation Act | Not identified |
| G.O.Ms.No. 02/2014, 41/2015, 44/2015, 95/2016, 26/2017, 52/2018; Rule 72-A order | Not held (LD-003) |
| G.O. 54/2025 (draft) | Held, not indexed |

**Fine and compounding schedule (no penalty answer may be enabled)**

| Item | State |
|---|---|
| G.O.Ms.No. 42/2020 | GOIR returned "No Records Found"; not located. Compounding schedule undetermined |
| 2020 order "21102020TRB MS21", G.O.Ms.No. 54/2006, 242/2006, 334/2008 | Leads only; not located or opened |
| G.O. 332/2008 (AP) | Held. It is permit compounding under s.86(5) and rule 217, **not** a fine schedule. Applicability LD-010 pending |
| G.O.Ms.No. 26 (penalty points) | Not searched; number collides with G.O. 26 of 24-04-2017 (rule 81 chain) |
| s.200 matrix and counsel memorandum | Do not exist. s.200(1) text as substituted from 15-08-2026 is verified word for word; transition for earlier offences and the offence-date rule are unresolved |
| s.184 vs s.177A; s.194D, s.185, s.181; Rule 55(2)(iv); Telangana fee notification; s.112(2) speed notifications; Telangana High Court material | Open or not investigated |

## 7. Corrections to the worksheet

- Baseline conflict: resolved in section 2.
- Worksheet summary said 4 of the 20 carry commencement wording but then listed five G.O.s. Correct statement: G.O. 53, 10, 16 and 25 state a commencement; G.O. 24 states commencement on publication but is draft-or-final unresolved; G.O. 77 and 32 state none.
- Worksheet said G.O. 77 substitutes sub-rule (3). The register and audit disagree on which sub-rules are substituted (item 15 of section 3).
- Worksheet row for G.O. 10 treated 01-03-2026 only as "the Act's date". That stands: it is Act B's commencement.

## 8. Remaining engineering changes (none made)

1. **Provision-level validity.** Add per-provision or per-chunk validity overrides to the manifest, in the manner of `provision_overrides` in `source-status.json`, so a partial supersession (G.O. 53 column 8; rule 81; rule 217) can be expressed without closing the whole document.
2. **Partial range state.** Add a state for "commencement known, end unverified". It should drop chunks for dates before `valid_from` and never count as authoritative evidence. Today it can only be `unknown`.
3. **Cross-document links.** Link versions by provision across manifest ids (`amends` or `supersedes_provisions`), so chapter 4 against G.O. 77 and G.O. 53 against G.O. 16 are detected. Today versions link only by manifest `id`.
4. **Approval gate on verified metadata.** Refuse `verified_*` entries that lack a reference to an approved decision (an approved LD record or signed review block with an evidence hash). This keeps validity entries from becoming a back door around the approval mechanism.
5. **Separate date kinds.** Carry gazette-direction, publication and commencement dates as distinct fields, with a test proving only commencement can reach `valid_from`. Add an `as_on_date` for consolidations, usable only as a lower bound on currency.
6. **Appointing notifications.** Decide how an instrument like G.O. 10 attaches its date to a document not held, for example a `commences` reference to the Act's manifest id.
7. **Same-number Acts.** Disambiguate the `offence_date.py` comment (Central Act A, not the Telangana Act B). Confirm the three bands are only applied to Central MV Act chunks, and add a test with two instruments both numbered 8 of 2026 so routing cannot cross-apply.
8. **Registry validity.** The 20 lifecycle versions have no validity fields. Add a CLI for `close_validity` and registry entry of validity, as listed in the staging report.
9. **Serve-time drift check.** Registry and chunk date drift is checked only at ingest and close; add a serve-time check.
10. **Comparison tool.** Extend `scripts/compare_staging_validity.py` to diff the staging index against the approved-evidence register (once one exists) as well as the manifest.
11. **Central-law versioning.** If Central texts come into scope, the index needs dated versions of one Act (pre- and post-15-08-2026) with provision-level ranges. That is the same schema change as item 1.

None of these is needed for a safe rebuild of the existing 590 chunks; that rebuild remains safe and changes nothing but `validity_status: unknown`.

## 9. What would unlock metadata entry

- Counsel decisions on LD-001 to LD-008 (at minimum LD-004, LD-005, LD-006, LD-007, LD-008) recorded in the register, and the signed approval record produced offline by the approval authority.
- Telangana Gazette prints for G.O. 53, 10, 16 and 25.
- A recorded no-later-amendment check for each of those four.
- Engineering items 1, 2 and 4 above.
