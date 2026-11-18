# KnowYourRules: Legal Document Acquisition Plan (Stage 2)

Written 2026-11-15. Planning only. Nothing was downloaded, ingested, indexed, committed or deployed. No registry, status, quarantine, approval, key or code file was changed. **No source in this plan is legally approved.** This file builds on `LEGAL-SOURCE-COMPLETENESS-AUDIT.md` (the audit) and does not repeat its per-document detail.

## 1. Summary

- **Scope used:** Telangana traffic rules as the primary jurisdiction, plus the central legislation they depend on as supporting context (the scope in the Stage 2 brief). The repository still records an earlier "Telangana-only" decision (08-11-2026). This plan follows the newer brief. Reconciling the repository record is a separate step that needs your approval.
- **Held locally (23 files):** the Telangana MV Rules 1989 as 12 HTML chapter snapshots, the Taxation Rules 1963 snapshot (Rules 1-17), 7 Telangana G.O.s (2025-26), and 3 files on disk but not indexed. Section 3.2 gives every hash.
- **Not held, and needed first (P0):** the Motor Vehicles Act 1988 as amended, the Central Motor Vehicles Rules 1989 as amended, the Telangana adaptation instrument, and the base Telangana MV Rules as gazetted.
- **Nothing outside the local files is VERIFIED.** India Code returned HTTP 403, the MoRTH legislation page returned no listing, and the Telangana Gazette and GOIR portals gave no usable entries. Everything else is SECONDARY or UNRESOLVED.
- **Biggest decisions for counsel:** which instrument governs conduct on the road (2017 Driving Regulations or the 1989 Rules of the Road), whether Telangana Rule 81 is the 2025 text or the HTML text, and which penalty and compounding orders apply in Telangana.

## 2. Evidence classes and what was opened

| Class | Meaning here |
|---|---|
| VERIFIED | An official document or official web page whose text was directly inspected. For the local files this means a retained copy, re-hashed, and read. It does **not** mean legally approved, current, or complete. |
| SECONDARY | Supported only by search-result summaries, news, third-party copies, or listings I did not open. Search snippets are not treated as legal evidence. |
| UNRESOLVED | Authoritative confirmation unavailable. |

Pages actually opened in this stage (HTML only; no PDF or file was opened or saved):

| Page | Result |
|---|---|
| `https://morth.gov.in/en/motor-vehicle-legislation` | Opened (HTTP 200). The fetch returned only the ministry banner, no legislation list. Possibly script-rendered. Listing is UNRESOLVED |
| `https://www.transport.telangana.gov.in/html/acts-rules/acts-rules.htm` | Opened (HTTP 200). Returned the site home page, "Last Modified on 03-November-2026". The menu points to the real listing at `https://www.transport.telangana.gov.in/html/actsrules.html` (not opened) |
| `https://transport.telangana.gov.in/html/acts-rules/main-ap-mv-ta-1963.htm` and content frame `middle-ap-mv-ta-1963.htm` | Opened (HTTP 200). Frame header reads "Finance Department Govt. of Andhra Pradesh"; body is the Taxation Act, sections 1 to 19; no amendment citations shown. This page is not the held Taxation Rules snapshot. Read by a delegated agent: re-inspect before relying on it |
| `https://www.indiacode.nic.in/handle/123456789/1798` | **HTTP 403.** Not opened. Retrying the same fetch will fail |
| `https://tggazette.cgg.gov.in` | Opened (HTTP 200). Front page lists only unrelated and 2015 vehicle-auction notices. No traffic-law entries found. Search form not used |
| `https://goir.telangana.gov.in` | Opened (HTTP 200). A search form only; no records listed. Form not submitted |

Search-result evidence from this stage (SECONDARY, snippets only, none opened) is marked "search result" below.

## 3. Document inventory

Priority: P0 essential primary legislation; P1 applicable rules and amendments; P2 supporting notifications and taxation; P3 historical or superseded. Dependencies use the IDs in section 5.

### 3.1 Required documents not held

| ID | Document | Issuing authority | Number / date | Effective | Form | Official location | Opened? | Status | Pri |
|---|---|---|---|---|---|---|---|---|---|
| R01 | **Motor Vehicles Act, 1988**, current consolidated text | Parliament; administered by MoRTH | Act 59 of 1988, 14-10-1988 (search result); in force 01-07-1989 (search result) | Section-wise, per amendments | Consolidated wanted | India Code `https://www.indiacode.nic.in/handle/123456789/1798`. A search result lists `https://www.indiacode.nic.in/bitstream/123456789/1798/1/eng.pdf` headed "As on the 21st May, 2025" | No (403) | SECONDARY. The 21-05-2025 date is **earlier than** the 2026 changes in R03, so it cannot be assumed current | P0 |
| R02 | **Motor Vehicles (Amendment) Act, 2019** (individual amendment) | Parliament | Act 32 of 2019, 09-08-2019 | S.O. 3110(E) of 28-08-2019 and S.O. 859(E) of 25-02-2022 reported (SECONDARY) | Individual | India Code `https://www.indiacode.nic.in/repealedfileopen?rfilename=A2019-32.pdf` (listed in audit, not opened) | No | SECONDARY | P0 |
| R03 | Later central amendments or pending bills: Jan Vishwas (Amendment of Provisions) Bill 2026; Motor Vehicles (Amendment) Bill 2025 | Parliament | Unknown | Unknown | Bills | Lok Sabha / Rajya Sabha / PRS (third party) | No | UNRESOLVED (existence and status unconfirmed) | P2 |
| R04 | **Commencement notifications** for the 2019 Act and any later amendment | MoRTH | S.O. 3110(E) 28-08-2019; S.O. 859(E) 25-02-2022; others unknown | n/a | Individual | `https://egazette.gov.in` | No | SECONDARY | P1 |
| R05 | **Central Motor Vehicles Rules, 1989**, current consolidated text | MoRTH | G.S.R. 590(E), 02-06-1989 (SECONDARY) | Per amendment | Consolidated wanted | India Code (`.../ViewFileUploaded?...file=cmvr-1989.pdf`, listed in audit); MoRTH `https://morth.gov.in` chapter PDFs | No | UNRESOLVED. No consolidated text current to Nov 2026 found; one search found none on MoRTH | P0 |
| R06 | **CMVR amending notifications** relied on by held G.O.s or reported for 2026: G.S.R. 48(E) of 20-01-2026 (Rule 167); Eighth Amendment G.S.R. 417(E) of 25-05-2026; an amendment reported 23-10-2026 (Rule 115, E100); a Fifth Amendment reported to revise Rule 81 fees (central Rule 81, not the Telangana rule); toll-dues amendment; draft G.S.R. 728(E) of 10-08-2026 | MoRTH | As listed. **Amendment numbering is inconsistent across secondary sources** (a "Seventh" and an "Eighth" both appear) | Eighth: 25-05-2026 vs 29-05-2026 conflict | Individual | `https://egazette.gov.in` (search results list `.../WriteReadData/2026/273980.pdf`, `269155.pdf`, `269807.pdf`, `271968.pdf`; contents not opened, not identified) | No | SECONDARY | P1 |
| R07 | **Motor Vehicles (Driving) Regulations, 2017** | MoRTH, under s.118 | G.S.R. 634(E), 23-06-2017 | On publication (SECONDARY) | Individual (original) | Listed on `https://morth.gov.in/en/motor-vehicle-legislation?page=11` (search result); India Code regulations search | No | SECONDARY | P1 |
| R08 | Driving Regulations amendment **G.S.R. 38(E), 15-01-2024** (Regs 8 and 15) | MoRTH | 15-01-2024 | Unknown | Individual | `https://egazette.gov.in` | No | SECONDARY (one compiled version) | P1 |
| R09 | **Telangana MV Rules, 1989: base instrument as gazetted** | Govt of Andhra Pradesh, TR&B (Tr.II) | G.O.Ms.No. 216, 07-08-1989; AP Gazette Rules Supplement 25-08-1989 (as cited in held G.O.s 54/2025, 77/2025) | 1989 | Individual | AP/Telangana Gazette archive; Telangana e-Gazette `https://tggazette.cgg.gov.in` | No | SECONDARY (citation read in held text; instrument not seen) | P0 |
| R10 | **Telangana adaptation of the 1989 AP rules** (Reorganisation Act s.101 route) | Government of Telangana | Not identified | Unknown | Individual | Unknown | No | UNRESOLVED | P0 |
| R11 | **Telangana MV Rules: consolidated current text and all amendment orders** | Government of Telangana, TR&B | Unknown | Unknown | Consolidated plus individual | Transport Department listing `https://www.transport.telangana.gov.in/html/actsrules.html` (menu link, not opened); GOIR; e-Gazette | No | UNRESOLVED. The held HTML snapshot has no amendment citations and is outdated at Rule 217 | P1 |
| R12 | **Rule 81 amendment chain 2014-2018:** G.O.Ms.No. 02 (17-06-2014), 41 (29-09-2015), 44 (15-10-2015), 95 (08-12-2016), 26 (24-04-2017), 52 (11-04-2018) | TR&B | As listed (cited in held G.O.s 54/2025, 77/2025) | Unknown | Individual | GOIR (form postback, no direct URL); e-Gazette | No | SECONDARY (citations only) | P1 until the current Rule 81 text is settled, then P3 |
| R13 | Reported **Rule 72-A** insertion (G.O.Ms.No. 41 of 29-09-2015) | TR&B | G.O. number collides with R12 | Unknown | Individual | GOIR; e-Gazette | No | SECONDARY (blog reproductions) | P1 |
| R14 | **Penalty and compounding orders under s.200** MV Act, current in Telangana: G.O.Ms.No. 42 (July 2020); lead `21102020TRB MS21` on a third-party host; AP G.O.s 54/2006, 242/2006, 334/2008 (named in the briefing PDF only) | TR&B / Transport Dept | Unknown | Unknown | Individual | Transport Department "Penalties" pages (menu links `.../html/pdf/prosecution-11-03-10.pdf`, `.../html/pdf/2008trb_ms332_compounding.pdf`; the second is held); GOIR | No (the prosecution PDF not opened) | UNRESOLVED | P1 |
| R15 | **G.O. "26" penalty-point order** named in the briefing PDF | Unknown | Number ambiguous | Unknown | Individual | GOIR | No | UNRESOLVED | P1 |
| R16 | **Telangana MV Taxation Act, 1963** (adapted), consolidated with amendments | Government of Telangana | Act 5 of 1963; adaptation reportedly G.O.Ms.No. 2, TR&B (SECONDARY) | Unknown | Consolidated wanted | Transport Department page above (opened; no amendment citations); PRS copy (third party) | Yes, HTML | VERIFIED as an official page. Currency and amendment history UNRESOLVED | P2 |
| R17 | **Telangana MV Taxation (Amendment) Act, 2026** | Telangana Legislature | Act 8 of 2026 (the number comes from a PRS copy of Act 5 of 1963; gazette text unseen); Bill 5 of 2026, introduced and passed 02-01-2026 (SECONDARY) | 01-03-2026 per held G.O. 10/2026 | Individual | Telangana e-Gazette | No | SECONDARY | P2 |
| R18 | Earlier Taxation Amendment Acts, for example a "Telangana MV Taxation (Amendment) Act, 2023" (third-party site) and any others | Telangana Legislature | Unknown | Unknown | Individual | Telangana e-Gazette | No | UNRESOLVED (new lead) | P2 |
| R19 | **Taxation schedule history:** G.O.Ms.No. 22 (07-05-2022), G.O.Ms.No. 10 (2014), 2021 EV exemption order, earlier Third and Sixth Schedule orders | TR&B | As listed | Unknown | Individual | GOIR | No | SECONDARY (cited in held G.O.s and briefing PDF) | P2 / P3 |
| R20 | **Taxation Rules, 1963**: complete text and adaptation | Government of Telangana | None shown | Unknown | Consolidated wanted | Transport Department HTML (held, Rules 1-17 only in the index) | Held | UNRESOLVED (completeness) | P2 |
| R21 | **Gazette prints** for held G.O.s 53, 77 (2025) and 10, 16, 24, 25, 32 (2026) | Telangana e-Gazette | Gazette dates directed in the G.O.s (14-08-2025, 15-11-2025, 01-03-2026, 23-03-2026, 02-06-2026) | Establishes publication and effective dates | Individual | `https://tggazette.cgg.gov.in` | No | UNRESOLVED | P1 |
| R22 | **Final Telangana notification of G.O. 24/2026** (the held copy is "draft"/"final" ambiguous) | TR&B | 01-06-2026 | Unknown | Individual | Telangana e-Gazette | No | UNRESOLVED | P1 |
| R23 | Telangana notifications under **ss.112 and 115** (speed limits, restrictions); Commissionerate notifications (Hyderabad, Cyberabad, Rachakonda) | Government of Telangana / Commissioners of Police | Unknown | Unknown | Individual | e-Gazette; GOIR | No | UNRESOLVED (not investigated) | P2 |
| R24 | **S.O. 1306(E), 12-03-2024**, registration mark "TG" | MoRTH | 12-03-2024 | Unknown | Individual | `https://morth.gov.in/sites/default/files/notifications_document/8-SO 1306(E) 12 March 2024 TG registration mark Telangana.pdf` (search result) | No | SECONDARY | P2 |
| R25 | Supreme Court W.P.(C) 295 of 2012 and other judicial directions the held G.O.s rely on | Supreme Court of India | W.P.(C) 295 of 2012 (named in held G.O. 32/2026) | n/a | Judgment | Supreme Court website | No | UNRESOLVED; counsel to decide whether judgments are in scope | P2 |

### 3.2 Documents held locally

All 23 SHA-256 values were recomputed in the audit and matched the recorded ones. They are copies as obtained; none is a signed or approved text. Chunk counts and lifecycle state are in the audit, section 3.1. All 20 indexed items are `pending`, `active_version: null`.

| ID | Document | Held file / URL | SHA-256 | Priority | Status |
|---|---|---|---|---|---|
| H01 | TMVR 1989, chapter 1 (Rules 1-2) | `.../html/acts-rules/middle-main-chap-1.htm` | `977a89529881d166fc391ba37a3aeda6845bb7e3ff190e4f15caf4ad3fd98108` | P1 | VERIFIED copy; currency UNRESOLVED |
| H02 | chapter 2 (Rules 3-45) | `.../middle-main-chap-2.htm` | `08e13e074d928a5fc86f63e02a8984382d770a25ecea82579c631694b5503149` | P1 | same |
| H03 | chapter 3 (Rules 46-78) | `.../middle-main-chap-3.htm` | `968e1b246ea425f830c218c4ece6601ebcfc1f889c0d036d40112fd81e1be24c` | P1 | same |
| H04 | chapter 4 (Rules 79-129; contains Rule 81) | `.../middle-main-chap-4.htm` | `d901ad962697002883f18c9f4c97f530de64966931f13bbd91d49708b391a3ba` | P1 | same; **conflicts with G.O. 77/2025** |
| H05 | chapter 5 (Rules 130-297) | `.../middle-main-chap-5.htm` | `61f019808cb69abb6bb4b1c17b91a5687e2d2f323d15af1c4d5e9beb3d502a52` | P1 | same; Rule 217 outdated |
| H06 | chapter 6 (Rules 298-309) | `.../middle-main-chap-6.htm` | `53d1f93beb379d501a76aec101108f4c396b505dac6826a03a52a2ade66f7bb4` | P1 | same |
| H07 | chapter 7 (Rules 310-395) | `.../middle-main-chap-7.htm` | `a29464d004db4cc84d2aad756268640b636c5fbcf116f263f6548e86b3d61139` | P1 | same |
| H08 | chapter 8 (Rules 396-450) | `.../middle-main-chap-8.htm` | `f86f82fd3f240aa4895674d79428578baf093facd6e58f5d20b43deddfd0c201` | P1 | same |
| H09 | chapter 9 (Rules 451-453) | `.../middle-main-chap-9.htm` | `bb99e00241e40bfa7f642535c48373421e56d9fec9092f23a299a184c675dfc4` | P1 | same |
| H10 | chapter 10 (Rule 454) | `.../middle-main-chap-10.htm` | `3ec9f467e0ea62af6520de3ee26ad4f32c53722c2ff2ba67c46a79ee3d091925` | P1 | same |
| H11 | chapter 11 (Rules 455-476) | `.../middle-main-chap-11.htm` | `168867c0093a17ba8117283e512fd20ce6b57104f3722d4ea163a54b21ed91ec` | P1 | same |
| H12 | chapter 12 (Rules 477-486) | `.../middle-main-chap-12.htm` | `9fa4fcb57db09b2705a7283678a7708a26e1b6639e6268a058d87998adbf1b91` | P1 | same |
| H13 | Taxation Rules 1963 (Rules 1-17 indexed) | `.../middle-ap-mv-tr-%201963-main.htm` | `d7f805041083683044d203a942d3223894f51526389ecd5b4d67e76344e5d291` | P2 | VERIFIED copy; completeness UNRESOLVED |
| H14 | G.O.Ms.No. 53/2025 (13-08-2025), Taxation Act schedules | `goir/13082025TRB_MS53.PDF` | `a93f8daa6865eccd2ee646494c10883d98fb0e7c99d3a0f4c64dffe803c15c18` | P2 | VERIFIED department copy; Gazette print not held |
| H15 | G.O.Ms.No. 77/2025 (15-11-2025), Rule 81 final | `goir/2025TRB_Ms77.pdf` | `3de907353bdf37415df25f10d45b05e336bd29c077285fae2c9bda2655f7be71` | P1 | same |
| H16 | G.O.Ms.No. 10/2026 (25-02-2026), commencement of Act 8 of 2026 | `goir/2026TRB_Ms10.pdf` | `df0ee9357b05ca4db9a187481ff2c8ac50c4a9d2ca05f91800e9bc4161f8c5fd` | P2 | same |
| H17 | G.O.Ms.No. 16/2026 (20-03-2026), Seventh Schedule | `goir/2026TRB_Ms16.pdf` | `139f96454954a4b77b3f07a796946827c29a81754f9a782e3e25dd5dfc76e0d5` | P2 | same |
| H18 | G.O.Ms.No. 24/2026 (01-06-2026), CMV Rule 167(5) | `goir/2026TRB_Ms24.pdf` | `ba0c9516575ed081181da4288c1395a19ad416bc9e9981c56f65b522b7007905` | P1 | same; draft or final UNRESOLVED |
| H19 | G.O.Ms.No. 25/2026 (01-06-2026), CMV Rule 167(3) | `goir/2026TRB_Ms25.pdf` | `c9bd1ff3a7e02a3c5324965835dd81ddea9f30df831adf0cb4387f8d3f374872` | P1 | same |
| H20 | G.O.Ms.No. 32/2026 (30-06-2026), CMV Rule 167A(1) | `goir/2026TRB_Ms32.pdf` | `4bb6273f8c13c08d7e15a64ad063c4ad868beaf527c469c6f1975b71a57f8629` | P1 | same |
| H21 | G.O.Ms.No. 54/2025 (13-08-2025), **draft** Rule 81 notification (not indexed) | `goir/2025TRB_Ms54.pdf` | `2965f7be670264ed339c062d0caecb41d799d7e192e2ba5b9bc7184d0a5840f7` | P3 | VERIFIED copy; superseded by H15 |
| H22 | G.O.Ms.No. 332, 13-11-2008, Government of **Andhra Pradesh** (not indexed) | `transport-dept/2008trb_ms332_compounding.pdf` | `3fb415be037dcf3b64bd3da86b37e337256335cd9cb619df7dd8e5081a2bd533` | P3 | VERIFIED copy; Telangana continuation UNRESOLVED; permit compounding, not the s.200 schedule |
| H23 | Rules of the Road Regulations 1989, S.O. 439(E) (not indexed; regulations 1-31 only) | `transport-dept/rules_of_the_road_regulations_1989.pdf` | `1242880c31e134e22490527f244ce38ac9a7264ad6a26782b9fad15041e1990f` | P3 | VERIFIED copy; probably superseded (R07); completeness UNRESOLVED |

Also on disk, not a legal source: the briefing PDF `supplied/Telangana_Traffic_Law_Legal_Review_Summary.pdf` (SHA-256 `6ce1603d034e3b57223027df9c1994f977432ab06d252b7c8e6a38fcf17f89f5`). It names nine archived PDFs that exist in no searched location. Its hash for G.O. 77 (`74a6839d...`) does not match the held file.

## 4. Reconciliation plan for the existing audit issues

Each item says what closes it. None can be closed from the files held today.

| # | Issue | What is known | Documents needed | Closing condition | Leave unresolved if |
|---|---|---|---|---|---|
| 1 | **Rule 81: HTML text vs G.O. 77/2025** | H04 Rule 81(6) cites (3)(i)-(iii) and (5). G.O. 77 substitutes (3) and (6) over (3)(i)-(vii), and omits (1), (2), (4). Fee scales differ (G.O. 77: Rs 6,000 to Rs 1,50,000) | R11, R12, R21 (Gazette print of G.O. 77) | A gazetted G.O. 77 plus the full chain give a reconstructed Rule 81 that counsel signs off as the current text | Any link in the chain is missing. Do not state any Rule 81 fee as current meanwhile |
| 2 | **G.O. 10/2026 commencement date** | The manifest says 25-02-2026. The held text appoints **1 March 2026** as the date Act 8 of 2026 comes into force; 25-02-2026 is the G.O. date. A search result agrees on 1 March 2026 (SECONDARY) | H16 (held), R17, R21 | Gazette print of G.O. 10 and the Act 8 of 2026 text confirm 01-03-2026. Then the manifest row is corrected in a separately authorised step | The Gazette print is not found |
| 3 | **Missing Rule 81 amendments 2014-2018** | Six G.O.s are cited in held G.O.s but not held | R12 | All six obtained from GOIR or e-Gazette, hashed, and mapped to sub-rules. Note the G.O. 41 collision with item 5 | Any is unobtainable. Counsel decides whether G.O. 77's substitutions make them immaterial |
| 4 | **Telangana adaptation of the 1989 AP rules** | Not identified. Reorganisation Act s.101 allowed adaptation within two years (SECONDARY) | R10, R09, R11 | The adaptation order is found and read, or counsel confirms the legal basis by other means | Not found. Record the gap; do not assume the AP text applies as Telangana law without counsel |
| 5 | **Reported Rule 72-A insertion** | Reported by G.O.Ms.No. 41 of 29-09-2015 (blog reproductions). The index has no Rule 72A. The same G.O. number appears in the Rule 81 chain | R13, R12 | The G.O. text is read, shows what it amends, and the manifest records the correct number and date | G.O. 41 turns out to be one order amending both rules, or a different order. Record as unresolved |
| 6 | **Rules of the Road 1989 vs Driving Regulations 2017** | H23 holds regs 1-31 only. G.S.R. 634(E) of 23-06-2017 reportedly supersedes it (secondary). The Transport Department still lists the old PDF | R07, R08, H23 | The gazetted 2017 text, read, states the supersession and its date; counsel confirms there is no Telangana-specific reservation | The 2017 text cannot be opened. Keep H23 un-ingested either way |
| 7 | **Ambiguous G.O. 26** | The briefing PDF cites a penalty-point "G.O. 26". G.O.Ms.No. 26 of 24-04-2017 is in the Rule 81 chain. Not searched | R15, R12 | The briefing PDF's reference is traced to a document with number, date and department, or declared unfindable | No such order exists. Remove any reliance on it in a separate step |
| 8 | **Stale manifest entries** | Got/Read columns are wrong for 7 G.O.s; the G.O. 77 hash in the briefing PDF differs from the held file; the manifest is dated 29-10 but has 09-11 entries; some Transport Department links lead to an index page or the MoRTH home page | Local files and the Transport Department listing `actsrules.html` | A corrected manifest is proposed as a diff for approval. This plan does not edit it | n/a (record-keeping only) |
| 9 | **G.O. 54/2025 draft vs final** | H21 is the draft (preliminary) under s.212(1), 13-08-2025. H15 is the final, 15-11-2025. Preliminary notice reportedly Telangana Gazette No. G-575, Part I Extraordinary, 13-08-2025 (read in G.O. 77 text) | R21, H21, H15 | The Gazette prints for both are obtained and the dates reconciled. H21 stays out of the corpus except as history | Prints not found. Keep H21 flagged "draft" |

Additional reconciliations the audit raised, folded in here: Rule 217 (H05 shows pre-2008 amounts; H22 is an AP order that may or may not carry over), the G.O. 24/2026 draft-or-final ambiguity (R22), the central Eighth Amendment effective-date conflict (R06), and the inconsistent central amendment numbering.

## 5. Dependency map

Arrows read "needs". Priorities in brackets.

```
Penalty / compounding answers
  R14 s.200 orders [P1] -> R01 MV Act as amended [P0] (ss.177-200 offences and penalties)
                         -> R02, R04 (what 2019 changes are in force)
                         -> R10 / R09 (Telangana authority to compound)

Telangana MV Rules (current text)
  R11 consolidated [P1] -> R09 base 1989 rules [P0]
                        -> R10 adaptation instrument [P0]
                        -> R12 Rule 81 chain [P1->P3], R13 Rule 72-A [P1]
                        -> H15 G.O. 77 (held) -> R21 Gazette print [P1]
  all Telangana rules   -> R01 (they are made under ss.65, 86, 212 and others)

Central rules
  R05 CMVR consolidated [P0] -> R01
  R06 CMVR amendments [P1]   -> R05
  held G.O.s H18, H19, H20   -> R05 + R06 (G.S.R. 48(E), Rules 167, 167A)

Conduct on the road
  R07 Driving Regulations 2017 [P1] -> R01 (s.118)
  R08 G.S.R. 38(E) 2024 [P1]        -> R07
  H23 Rules of the Road 1989 [P3]   -> superseded by R07 (to be confirmed)

Taxation
  R16 Act 5 of 1963 [P2] -> adaptation instrument (secondary: G.O. 2)
  R17 Act 8 of 2026 [P2] -> R16; commencement H16 -> R21
  H14, H17 schedule orders [P2] -> R16, R19, R20
```

Order that follows from the map: R01 and R05 before any rule or order that cites them; R09 and R10 before R11; R21 before any effective-date statement.

## 6. Recommended acquisition sequence

Each step needs your written go-ahead first, because acquiring means downloading, which this stage did not do. Stop after each step for review.

1. **Primary legislation (P0).** R01 and R02 (from India Code, or MoRTH), R05. India Code returns 403 to automated fetches, so the likely route is a person downloading from the official page in a browser and handing over the file with its source URL and date.
2. **Telangana foundation (P0).** R09 and R10. If R10 cannot be found, stop and ask counsel (question 4) before continuing with Telangana rules.
3. **Gazette confirmation for held G.O.s (P1, R21, R22).** This closes reconciliation items 2 and 9, and underpins every effective date.
4. **Telangana rules current text (P1).** R11 via the Transport Department `actsrules.html` page and GOIR; then R12 and R13 for reconciliation items 1, 3, 5.
5. **Central rules updates (P1).** R04, R06 (resolve the numbering and effective-date conflicts), R07, R08.
6. **Penalty and compounding orders (P1).** R14, R15. Without these, no penalty answer can be grounded.
7. **Taxation (P2).** R16 (re-inspect the opened page), R17, R18, R20, R19.
8. **Supporting notifications (P2).** R23, R24, R25, R03 (watch items).
9. **History (P3).** Pre-2014 AP orders and superseded instruments, only where counsel says they affect a current answer.

### Handling rules to apply at each acquisition (for when authorised)

- Take each file only from the official URL, record the URL, retrieval time and server-reported date, and hash it with SHA-256 before opening it.
- Keep it in its own new directory outside the index; ingest nothing and change no registry or status until counsel has reviewed it.
- Keep Gazette prints, department copies and HTML renderings as separate records; never merge them by title.
- Mark a provision "current" only when every amendment to it is accounted for; otherwise record "amendment history incomplete".
- Treat third-party copies (PRS, news sites, compilers, law-firm blogs, search-result links) as leads only.

## 7. Questions for legal counsel

1. Is Telangana-primary with central supporting law the intended scope, and should the repository's earlier "Telangana-only" record be revised?
2. How did the 1989 Andhra Pradesh Motor Vehicles Rules become Telangana rules, and which instrument is the authority (section 101 of the 2014 Reorganisation Act, a specific G.O., or other)?
3. Is the Motor Vehicles (Driving) Regulations 2017 the only operative conduct regulation, and is the 1989 Rules of the Road Regulations wholly superseded?
4. If no Telangana adaptation order can be found, what is the position on relying on the AP-era text?
5. Which text of Telangana Rule 81 governs: the Transport Department HTML text or the G.O. 77/2025 text? Does G.O. 77 leave sub-rules (5) and (7) onwards intact?
6. Which are the current s.200 compounding and penalty orders applicable in Telangana, and do pre-2014 AP orders (54/2006, 242/2006, 334/2008) still apply?
7. What is "G.O. 26" in the briefing PDF, and is it the 2017 Rule 81 order or a different penalty-point order?
8. Was G.O. 24/2026 published as a draft or final notification, and when did it take effect?
9. Is the Eighth Amendment to the CMV Rules effective 25-05-2026 (gazette) or 29-05-2026?
10. What is the status of the Jan Vishwas Bill 2026 and the Motor Vehicles (Amendment) Bill 2025? Do any of their changes now apply?
11. Can an official gazetted copy, as opposed to a department G.O. copy, be required before any effective date is stated?
12. Is the Telangana Taxation Act, 1963 (and Act 8 of 2026, plus any 2023 amendment Act) in scope for a traffic-rules product, or only the schedule G.O.s?
13. Are judgments (for example Supreme Court W.P.(C) 295 of 2012) and Commissionerate notifications in scope?
14. Who signs off a document as "verified and current", and what record should show that sign-off?

## 8. Limits of this plan

- **Opened this stage:** six HTML pages (section 2). The MoRTH page returned no listing, India Code returned 403, and the two Telangana portals gave no usable entries. Therefore **no document outside the local files is VERIFIED.**
- **The Taxation Act page read** was read by a delegated agent. I did not read that page myself, so re-inspect it before use.
- **Search results** (India Code listings, MoRTH page 11, e-Gazette PDF links, PRS, news) supply every SECONDARY entry above. Their dates and amendment numbers are inconsistent in places and are not legal evidence.
- **Not checked:** the Transport Department `actsrules.html` listing, `gos-and-circulars.php`, the prosecution PDF, forms and schedules in the held rules, and whether other Telangana or central instruments (for example PRS Bill 11 of 2026 from a search result, unidentified) bear on traffic rules.
- **No approval is implied.** Every status above is evidence quality only. All 20 indexed sources remain `pending` and quarantined as before.
