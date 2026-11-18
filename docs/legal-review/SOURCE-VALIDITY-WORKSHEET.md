# Source-validity verification worksheet (20 Telangana sources)

Prepared 16-11-2026 for counsel. Companion to `eval/deployment/VALIDITY-INDEX-STAGING-REPORT.md`.

**Status of this document: a worksheet, not a verification.** No source is marked verified. The manifest
(`docs/legal-sources/telangana-traffic/DRAFT-telangana-manifest.json`) was not changed. No date below has been entered
anywhere. Where a G.O. states its own commencement, that wording is quoted as a *candidate* to be confirmed against the
Gazette print, never as a verified date. Nothing here is legal advice.

## 1. Summary

- All 20 sources are `validity_status: unknown` in the index. Every manifest entry still has `verification_status: unverified`, `publication_date: null`, `effective_date: null`.
- **None of the 20 can be used for current-law or historical questions today.** Reason: no Gazette print of any of them has been obtained, and none has a verified range.
- Only 4 of the 20 carry a commencement wording in the document text itself: G.O.Ms.No. 53/2025, 10/2026, 16/2026 and (by direction to publish) 24/2026 and 25/2026. These are candidates only (section 4).
- The 12 Rules chapters (1989) and the Taxation Rules 1963 are unverified web snapshots of an Andhra Pradesh-era text. Their dates cannot be proposed from the snapshots at all.
- **Coverage warning.** These 20 sources do not contain the Motor Vehicles Act 1988, the Central Motor Vehicles Rules, the Telangana Taxation Act 1963 (Act 5 of 1963), Act 8 of 2026, or any s.200 fine/compounding schedule. Validity work on these 20 cannot, by itself, unlock questions about helmets, seat belts, drink driving, over-speeding or fines. Those need sources outside this set (EVIDENCE-GAP-REGISTER G3, G7, G11).

### Date vocabulary used below

| Term | Meaning | Where it sits |
|---|---|---|
| Issue date | Date printed on the G.O. (for example 15-11-2025) | `document_number` line of the G.O. |
| Gazette direction date | Date the G.O. *directs* the notification to appear in the Gazette | G.O. ORDER paragraph; not proof that it was published that day |
| Publication date | Date actually printed on the Gazette | Gazette print (none obtained) |
| Commencement date | Date the text becomes law | Notification's own clause, a commencement notification, or the Act/Rule's own commencement rule |
| `valid_from` | Commencement of that text as law | Counsel to set from commencement evidence |
| `valid_to` | Last day it was law. `99991231` only when counsel verifies it is still in force | Repeal, supersession, omission or substitution evidence |

Publication is never copied into `valid_from`. A date that only appears as "the Gazette dated X" in a G.O. is a *direction*, not a publication.

### Use classes

- **Current-law**: may be answered as today's law. **Historical**: may be answered for an offence on a past date. **Neither**: not usable for either.
- Today: every source is **Neither**. The "Target" column says what each could become *if* the evidence in section 5 is obtained.

## 2. The 20 sources, ranked for common Telangana traffic questions

Rank reflects how often the topic arises (licence, registration and special numbers, road tax, e-challan, permits) and how many other sources depend on it.

| Rank | Source ID | Document | Type | Status now | Proposed `valid_from` | Proposed `valid_to` | Check amendment / supersession / repeal / commencement? | Use now | Target |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `tmvr-1989-chap-1` | Telangana MV Rules 1989, rule 1-2 (title, commencement, definitions) | Rules (state) | unknown | None. Rule 1(3) says the rules commence on a date the Government appoints by notification; that notification is not held | None | Yes: commencement notification, Telangana adaptation, all amendments | Neither | Current + historical, gating for chapters 2-12 |
| 2 | `tmvr-1989-chap-4` | TMVR 1989, rules 79-129 (registration; rule 81 special numbers) | Rules (state) | unknown | None | None | Yes: rule 81 amended by G.O.Ms.No. 77/2025; earlier rule 81 orders 02/2014, 41/2015, 44/2015, 95/2016, 26/2017, 52/2018 not held | Neither | Current + historical |
| 3 | `go-ms-77-2025-trb` | Amendment to rule 81 TMVR (special-number fees), final | G.O. notification (rules amendment) | unknown | None. Candidate: gazette direction 15-11-2025 (20251115) is a direction only. Document contains **no** commencement clause | None | Yes: commencement; relationship to G.O.Ms.No. 54/2025 (preliminary); any later rule 81 change | Neither | Current + historical |
| 4 | `tmvr-1989-chap-2` | TMVR 1989, rules 3-45 (driving licences, duplicates, badges, medical certificate, state register) | Rules (state) | unknown | None | None | Yes: adaptation, amendments, fee changes | Neither | Current + historical |
| 5 | `go-ms-53-2025-trb` | Amendment to Third, Sixth, Seventh Schedules of Taxation Act 1963 (life-tax enhancement) | G.O. notification | unknown | Candidate 20250814: text says "come into force with effect from 14.08.2025". Gazette print needed | None. **Partly** superseded by G.O.Ms.No. 16/2026 (column 8 of Seventh Schedule only); rest not marked superseded | Yes: G.O.Ms.No. 16/2026, G.O.Ms.No. 22/2022, Act 8 of 2026 effect | Neither | Current + historical |
| 6 | `go-ms-10-2026-trb` | Commencement notification for Act 8 of 2026 (Taxation (Amendment) Act) | G.O. commencement notification | unknown | Candidate 20260301 as the Act's commencement ("1st day of March, 2026"). This is the Act's date, not necessarily this notification's own `valid_from` (counsel to decide how to model) | None | Yes: Act 8 of 2026 text (not held) | Neither | Current + historical, gating for tax |
| 7 | `go-ms-16-2026-trb` | Amendment to Seventh Schedule (deletes column 8, extra 2% on second personalised vehicle) | G.O. notification | unknown | Candidate 20260323: para 4 says "with effect from 23.03.2026". Gazette print needed | None | Yes: G.O.Ms.No. 22/2022, 53/2025 base; Act 8 of 2026 interplay | Neither | Current + historical |
| 8 | `tmvtr-1963` | Telangana MV Taxation Rules 1963 | Rules (state) | unknown | None | None | Yes: adaptation instrument, amendments, relation to Act 5 of 1963 | Neither | Current + historical |
| 9 | `go-ms-24-2026-trb` | Redressal authorities for challans, CMVR rule 167(5) | G.O. notification (possibly draft) | unknown | None. Order para says "draft Notification"; notification para 5 commences on Gazette publication (directed 02-06-2026). Draft or final not established | None | Yes: draft vs final; G.S.R. 48(E) of 20-01-2026; earlier orders it supersedes | Neither | Current only if confirmed final |
| 10 | `go-ms-25-2026-trb` | Electronic means (SMS, WhatsApp, e-mail) for challans, CMVR rule 167(3) | G.O. notification | unknown | Candidate 20260602 only if Gazette print confirms: text says "with immediate effect" and directs Gazette of 02.06.2026 | None | Yes: G.S.R. 48(E); publication date | Neither | Current + historical |
| 11 | `go-ms-32-2026-trb` | EMES Designated Authority, CMVR rule 167A(1) | G.O. (order constituting a body) | unknown | None. No gazette direction or commencement clause in the text | None | Yes: whether it needs publication to take effect at all | Neither | Counsel decides (administrative order) |
| 12 | `tmvr-1989-chap-5` | TMVR 1989, rules 130-296 (RTAs, permits; includes rule 217 table) | Rules (state) | unknown | None | None | Yes: rule 217 table known outdated; G.O.Ms.No. 332/2008 (AP) | Neither | Current + historical (rule 217 only after reconciliation) |
| 13 | `tmvr-1989-chap-7` | TMVR 1989, rules 310-383 (lamps, mirrors, vehicle construction/equipment) | Rules (state) | unknown | None | None | Yes | Neither | Current + historical |
| 14 | `tmvr-1989-chap-8` | TMVR 1989, rules 396-450 (traffic signs, parking, weighing, abandoned vehicles) | Rules (state) | unknown | None | None | Yes | Neither | Current + historical |
| 15 | `tmvr-1989-chap-3` | TMVR 1989, rules 46-78 (conductors' licences, badges) | Rules (state) | unknown | None | None | Yes | Neither | Current + historical |
| 16 | `tmvr-1989-chap-11` | TMVR 1989, rules 455-476 (compensation claims, Form CWF) | Rules (state) | unknown | None | None | Yes: amendments after Central Act changes | Neither | Current + historical |
| 17 | `tmvr-1989-chap-6` | TMVR 1989, rules 298-309 (State transport schemes) | Rules (state) | unknown | None | None | Yes | Neither | Low value |
| 18 | `tmvr-1989-chap-12` | TMVR 1989, rules 477-486 (refund of fees, pollution testing stations) | Rules (state) | unknown | None | None | Yes | Neither | Low value |
| 19 | `tmvr-1989-chap-9` | TMVR 1989, rules 451-453 (insurance certificate for permits) | Rules (state) | unknown | None | None | Yes | Neither | Low value |
| 20 | `tmvr-1989-chap-10` | TMVR 1989, rule 454 (transport officers' powers under ss.130, 133, 158, 202, 203) | Rules (state) | unknown | None | None | Yes | Neither | Low value |

Titles: chapters 1-12 are all titled "Telangana Motor Vehicles Rules, 1989" in the manifest; the descriptions above come from the snapshots' rule headings. Full G.O. titles are in the manifest.

## 3. Dependencies and overlapping provisions

```
Motor Vehicles Act 1988 (Central, not held)
 ├─ s.65 → TMVR 1989 (base: AP G.O.Ms.No. 216, 07-08-1989; Telangana adaptation instrument NOT identified)
 │    ├─ chap 1 (rule 1(3): commencement by notification, NOT held) ──► gates validity of chap 2-12
 │    ├─ chap 4 rule 81 ◄── G.O.Ms.No. 77/2025 (final) ◄── G.O.Ms.No. 54/2025 (preliminary, in GOIR, NOT one of the 20)
 │    │                  ◄── earlier rule 81 orders 02/2014, 41/2015, 44/2015, 95/2016, 26/2017, 52/2018 (not held)
 │    └─ chap 5 rule 217 ◄── G.O.Ms.No. 332/2008 (AP, compounding of permit offences; not one of the 20)
 └─ s.212 prior-publication rule → G.O. 54 (30-day objections) → G.O. 77

Telangana Taxation Act 1963 (Act 5 of 1963, NOT held) ── s.3, s.17
 ├─ Taxation Rules 1963 (`tmvtr-1963`; adaptation instrument unknown)
 ├─ Schedules 3, 6, 7 ◄── G.O.Ms.No. 22/2022 (not held) ◄── G.O.Ms.No. 53/2025 ◄── G.O.Ms.No. 16/2026 (column 8 of Seventh Schedule)
 └─ Act 8 of 2026 (Amendment Act, NOT held) ◄── G.O.Ms.No. 10/2026 (commencement 01-03-2026)

Central MV Rules 1989, rules 167, 167A (Central, not held), as amended by G.S.R. 48(E) of 20-01-2026
 ├─ G.O.Ms.No. 24/2026 (rule 167(5) redressal authorities)  ── "in supersession of any order inconsistent therewith" (the orders it supersedes are not identified)
 ├─ G.O.Ms.No. 25/2026 (rule 167(3) electronic means)
 └─ G.O.Ms.No. 32/2026 (rule 167A(1) Designated Authority; Supreme Court W.P.(C) 295/2012 orders 02-09-2024, 07-10-2025)
```

Overlaps and ordering risks:

| Overlap | Sources | Risk | What the validity ranges must show |
|---|---|---|---|
| Rule 81 text in the snapshot vs G.O. 77/2025 | `tmvr-1989-chap-4` and `go-ms-77-2025-trb` | The chapter shows pre-amendment text. Rule 81(1), (2) and (4) were omitted and (3) substituted by G.O. 77. Both would claim the same provision | Chapter 4 cannot carry an open range while the snapshot reproduces pre-2025 rule 81. Needs a consolidated text or a provision-level split |
| Rule 217 table vs 2008 order | `tmvr-1989-chap-5` | Snapshot shows pre-2008 amounts | Same: cannot be `verified_continuing` as a whole document |
| Seventh Schedule, column 8 | `go-ms-53-2025-trb` and `go-ms-16-2026-trb` | G.O. 16 deletes column 8 only. G.O. 53 stays in force for the rest | The index schema holds one range per **document**. A partial supersession cannot be expressed. Counsel must decide whether G.O. 53 keeps an open range with a note, or provision-level modelling is added. Do not close G.O. 53 as a whole |
| Act 8 of 2026 vs the schedules | `go-ms-10-2026-trb`, `go-ms-53-2025-trb`, `go-ms-16-2026-trb` | Act text not held, so its effect on the schedules is unknown | Needs the Act |
| Rule 167 notifications | `go-ms-24-2026-trb` and any earlier rule 167 order | "in supersession of any order inconsistent therewith" | The superseded orders need identifying |
| Offence-date band baseline | `backend/offence_date.py` | The code comment says 15-08-2026 is the commencement of "Act 8 of 2026, S.O. 4100(E)". G.O.Ms.No. 10/2026 appoints **01-03-2026** for the *Telangana* Taxation (Amendment) Act 8 of 2026 | These may be two different Acts (S.O. numbering suggests a Central notification) or an error in the baseline. Counsel to confirm which instrument the 15-08-2026 band refers to. Not resolved here, not changed |

## 4. Candidate dates stated inside the documents (for counsel to confirm, not to adopt)

These are quoted from the department G.O. copies held in the repository. They are **not** verified and **not** proposed for the manifest until the Gazette print confirms them.

| Source | Date wording in the document | Kind of date | Integer if confirmed | Gap |
|---|---|---|---|---|
| `go-ms-53-2025-trb` | "shall come into force with effect from 14.08.2025"; directs Gazette Extraordinary of 14.08.2025; G.O. issued 13-08-2025 | Commencement (stated) and gazette direction | `valid_from` 20250814 | Gazette print of 14-08-2025 not obtained |
| `go-ms-10-2026-trb` | Appoints "the 1st day of March, 2026" as the Act's commencement; directs Gazette 01.03.2026; G.O. dated 25-02-2026 | Commencement of the Act | 20260301 (for the Act) | Act text not held; whether this G.O.'s own range is the same needs counsel |
| `go-ms-16-2026-trb` | "with effect from 23.03.2026"; directs Gazette 23.03.2026; G.O. dated 20-03-2026 | Commencement (stated) | `valid_from` 20260323 | Gazette print not obtained |
| `go-ms-25-2026-trb` | "with immediate effect"; directs Gazette 02.06.2026; G.O. dated 01-06-2026 | Commencement tied to publication | 20260602 only if the Gazette is dated 02-06-2026 | Gazette print not obtained |
| `go-ms-24-2026-trb` | Comes into force on Gazette publication (directed 02-06-2026) | Commencement tied to publication | none until draft/final is settled | Order says "draft Notification". The date is not usable until the status is established |
| `go-ms-77-2025-trb` | No commencement clause found. Gazette direction 15-11-2025 | None stated | none | Commencement rule for a s.65/s.212 amendment needs counsel; Gazette print needed |
| `go-ms-32-2026-trb` | G.O. dated 30-06-2026; no Gazette direction, no commencement clause | None stated | none | Counsel decides whether an administrative order needs a validity range |

Every `valid_to` stays unset. `99991231` is not proposed for any source: no source has been verified as continuing in force.

## 5. Per-source evidence needed

### 5.1 `tmvr-1989-chap-1` to `tmvr-1989-chap-12` (Telangana Motor Vehicles Rules, 1989)

Evidence common to all 12 chapters (obtain once, apply to each):

1. **Base instrument**: AP G.O.Ms.No. 216, Transport, Roads & Buildings (Tr.II), 07-08-1989; Rules Supplement to Part I Extraordinary, AP Gazette 25-08-1989 (cited in G.O.Ms.No. 54/2025 and 77/2025). Need the Gazette print.
2. **Commencement notification** under rule 1(3) ("on such date as the State Government may appoint"). This is the primary evidence for `valid_from`. Not held.
3. **Telangana adaptation instrument** (AP Reorganisation Act 2014, s.101/s.102 or equivalent order) making the AP text Telangana's. Not identified. Page headers still read "Finance Department Govt. of Andhra Pradesh" (chapter 8 reads "Andhra Pradesh Control of Transport Vehicles").
4. **Complete amendment list** since 1989, from the Telangana Gazette or a Transport Department consolidated text with an "as amended up to" date. The snapshots carry no amendment citations and no currency date (all taken 29-10-2026).
5. **Official consolidated text** or counsel's decision that the HTML snapshot may serve as source text (COUNSEL-CHECKLIST item).
6. **Repeal/replacement check**: any later set of Telangana rules replacing the 1989 rules.

Because these are web snapshots with no instrument identity, the earliest honest status is `unknown` until items 1-4 are held. After that: `valid_from` from item 2; `valid_to = 99991231` only when item 4 shows no replacement. Amendments made to individual rules break the "whole chapter in force as shown" assumption (see rule 81 and rule 217 overlaps, section 3).

| Chapter | Covers | Chapter-specific check | Common-question value |
|---|---|---|---|
| 1 | Rules 1-2: title, application, commencement, definitions | Rule 1(3) commencement notification; definitions amended by later G.Os | High: gates the others |
| 2 | Rules 3-45: driving licence authority, tests, appeals, duplicates, badges, medical certificate, state register | Fee rules (duplicate licence, medical certificate) amended since 1989? Check each fee rule against Gazette amendments | High (licence questions) |
| 3 | Rules 46-78: conductors' licences, badges, duties | Same as chapter 2 | Medium |
| 4 | Rules 79-129: registration, **rule 81**, number plates, fees | Rule 81: G.O. 77/2025 and six earlier orders (2014-2018). Snapshot shows rule 81 fees from Rs 50,000, "not yet compared with G.O.Ms.No. 77/2025" | High |
| 5 | Rules 130-296: RTAs, permits, **rule 217 table** | Rule 217: replaced by G.O.Ms.No. 332/2008 (AP) amounts; how that continues in Telangana is unestablished; this is permit compounding under s.86(5), not a traffic-fine schedule | Medium (commercial vehicles) |
| 6 | Rules 298-309: State transport schemes (s.99) | Amendments | Low |
| 7 | Rules 310-383: lamps, mirrors, vehicle construction and equipment | Amendments; overlap with Central CMVR equipment rules | Medium |
| 8 | Rules 396-450: weighing, traffic signs, parking, abandoned vehicles | Amendments; overlap with Central rules and police powers | Medium |
| 9 | Rules 451-453: insurance for permits | Amendments | Low |
| 10 | Rule 454: transport officers' powers (ss.130, 133, 158, 202, 203) | Check that section references survive later Central Act amendments | Low |
| 11 | Rules 455-476: compensation claims (Form CWF) | Amendments after Central Act changes to Chapter X/XII | Low |
| 12 | Rules 477-486: refund of fees, pollution testing stations | Amendments | Low |

### 5.2 `tmvtr-1963` (Telangana Motor Vehicles Taxation Rules, 1963)

- Rule 1 reads "Telangana Motor Vehicles Taxation Rules, 1963" while the page title reads "Andhra Pradesh". Adaptation instrument unknown.
- Need: the base instrument (AP rules of 1963, issuing G.O. and Gazette date); the Telangana adaptation; the amendment history; the commencement under the rules themselves.
- Depends on the Taxation Act 1963 (Act 5 of 1963, not held). Overlaps in subject with G.O. 53/2025 and 16/2026.
- Use: Neither now. Target: current + historical, after the above.

### 5.3 `go-ms-77-2025-trb`: rule 81 amendment, final

- Primary evidence needed: Telangana Gazette Extraordinary Part I print of 15-11-2025 (publication date, commencement wording); confirmation the preliminary notification G.O.Ms.No. 54/2025 was published in Gazette No. G-575 Part-I Extraordinary of 13-08-2025 with the 30-day objection period.
- Legal question for counsel: the G.O. has no commencement clause. What is the commencement of a final rules amendment under s.65 and s.212 read with the General Clauses principle? Do not infer it.
- Check: later changes to rule 81 after 15-11-2025; earlier rule 81 orders (2014-2018) to decide what history applies to offence dates before this G.O.
- `valid_to` for the pre-amendment rule 81 text will follow from this G.O.'s commencement. This is a historical-answer dependency: a question about a special number before the commencement needs the earlier text, which is not held.

### 5.4 `go-ms-53-2025-trb`: life-tax schedules

- Primary evidence: Gazette print of 14-08-2025 (publication date and the stated commencement 14.08.2025).
- Check: G.O.Ms.No. 22/2022 (the base the Seventh Schedule had before) is not held. G.O.Ms.No. 16/2026 deletes column 8 of the Seventh Schedule only.
- Check: effect of Act 8 of 2026 on the Third, Sixth and Seventh Schedules.
- Check: manifest title is the document ABSTRACT, which says "under section 3"; the notification text says section 17. Counsel to confirm the empowering section for citation.
- `valid_to`: do not close as a whole; see the partial-supersession row in section 3.

### 5.5 `go-ms-10-2026-trb`: commencement of Act 8 of 2026

- Primary evidence: Gazette print of 01-03-2026; the text of Act 8 of 2026 (Telangana Motor Vehicles Taxation (Amendment) Act, 2026), including any provision fixing or delegating commencement.
- This G.O. says nothing about the Act's contents. Without the Act, no chunk of this G.O. explains what changed on 01-03-2026.
- Clarify against the baseline band in `backend/offence_date.py` (15-08-2026, "Act 8 of 2026, S.O. 4100(E)"); see section 3.
- Question for counsel: model this G.O.'s own range, or attach the Act's commencement to the Act once the Act is held.
- Evidence-gap link: G3, G4 (the "Road Safety Cess" and 7.5% rate remain unverified and unlinked to this Act; GOIR names Act 8 of 2026, not a cess).

### 5.6 `go-ms-16-2026-trb`: Seventh Schedule amendment

- Primary evidence: Gazette print dated 23-03-2026; confirmation of the stated effective date 23.03.2026.
- Base: G.O.Ms.No. 22/2022 and 53/2025 as cited in the text. G.O. 22/2022 not held.
- Scope (read from the PDF): column 8 only. Additional 2% on second or more personalised vehicles (up to 10 seats, individual owner, registration of new vehicles only).
- Check: any amendment after 23-03-2026; interplay with Act 8 of 2026.

### 5.7 `go-ms-24-2026-trb`: challan redressal authorities (rule 167(5))

- **Blocking question: draft or final?** ORDER para 1 says "publish the draft Notification". The notification itself operates in the present tense, supersedes inconsistent orders, and commences on Gazette publication. The endorsement's gazette date is blank. The manifest already flags every chunk "not answer-eligible".
- Primary evidence: the Gazette print of 02-06-2026 (or confirmation it was never published as final); a final notification if this was a draft.
- Check: G.S.R. 48(E) of 20-01-2026 text (Central, not held); the earlier State orders it supersedes (unidentified).
- Date handling: no date may be proposed until draft/final is settled.

### 5.8 `go-ms-25-2026-trb`: electronic challans (rule 167(3))

- Primary evidence: Gazette print of 02-06-2026; confirmation that "with immediate effect" runs from publication.
- Check: G.S.R. 48(E) of 20-01-2026; whether other State orders on electronic delivery of challans existed before.
- The G.O. dated 01-06-2026 is the issue date; the notice is directed for 02-06-2026. Keep these apart.

### 5.9 `go-ms-32-2026-trb`: EMES Designated Authority (rule 167A(1))

- Primary evidence: counsel's view of whether this is an administrative constitution order or a notification that needs Gazette publication to take effect; the Gazette print if published.
- Check: the Supreme Court orders of 02-09-2024 and 07-10-2025 in W.P.(C) No. 295 of 2012; G.S.R. 575(E) of 11-08-2021 and G.S.R. 48(E) of 20-01-2026 (Central, not held).
- Date handling: no commencement or Gazette wording was found in the extracted text. Do not infer one from the issue date 30-06-2026.

## 6. Evidence still needed, consolidated

Priority A (unlocks the most common questions):
1. Commencement notification and Gazette print of the 1989 rules (rule 1(3)); Telangana adaptation instrument.
2. Gazette print of G.O.Ms.No. 77/2025 (15-11-2025) and preliminary G.O.Ms.No. 54/2025 (13-08-2025, Gazette No. G-575); earlier rule 81 orders (2014-2018).
3. Consolidated, dated text of rules 3-45 (licensing) with amendment citations.
4. Gazette print of G.O.Ms.No. 53/2025 (14-08-2025) and G.O.Ms.No. 16/2026 (23-03-2026); G.O.Ms.No. 22/2022; text of Act 5 of 1963 and Act 8 of 2026; Gazette print of G.O.Ms.No. 10/2026 (01-03-2026).
5. Resolution of the 15-08-2026 baseline vs 01-03-2026 (Act 8 of 2026).

Priority B:
6. Taxation Rules 1963: adaptation and amendment history.
7. G.O.Ms.No. 24/2026 draft-or-final ruling and Gazette print; G.O.Ms.No. 25/2026 Gazette print; G.O.Ms.No. 32/2026 counsel ruling; G.S.R. 48(E).
8. Rule 217 reconciliation with G.O.Ms.No. 332/2008 and Telangana's continuation of it.

Priority C: amendment lists for rules chapters 3, 5-12.

Cross-cutting decisions for counsel:
- Whether the HTML snapshots may serve as source text at all (COUNSEL-CHECKLIST).
- How to model a partial supersession (G.O. 16 vs G.O. 53) in a one-range-per-document schema.
- Whether the AP-era 2006 and 2008 orders apply in Telangana (AP Reorganisation Act 2014).
- Whether an administrative G.O. (G.O. 32) needs a validity range.

## 7. Entry rules once evidence arrives (no action taken now)

- `validity_status` stays `unknown` until counsel signs off the range and records the evidence in `validity_basis`.
- `verified_continuing` requires `valid_to = 99991231` and a basis that shows no repeal or supersession. `verified_closed` requires a real end date and its basis.
- Closing a superseded version after approval goes through the audited `close_validity` operation, not a manifest edit.
- This worksheet is not approval evidence and carries no signature.

## 8. What this worksheet did not do

- No manifest, source document, approval record, schema or signature change. No code change, so no tests were run.
- No index rebuild, commit, push or deploy.
- No Gazette or website was checked. Everything above comes from the repository's manifest, notes, source PDFs and HTML snapshots.
