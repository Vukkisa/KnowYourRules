# Priority 15 questions: legal-source map (CMVR focus)

First written 2026-11-16. **Reconciled 2026-11-16 (second pass)** against the documents obtained in `PRIORITY-SOURCE-ACQUISITION-REPORT.md`. **Research map only.** Nothing here is ingested, indexed, registered, activated or approved, and no legal approval is claimed. Companions: `PRIORITY-15-QUESTION-READINESS-REPORT.md` (readiness status and the documents still needed per question), `PRIORITY-CMVR-DOCUMENT-GAP-LIST.md`, `PRIORITY-SOURCE-ACQUISITION-REPORT.md`, `CENTRAL-MOTOR-VEHICLES-RULES-ACQUISITION-REPORT.md`, `CENTRAL-MOTOR-VEHICLES-RULES-SOURCE-REGISTER.md`, `MOTOR-VEHICLES-ACT-VERIFICATION-REPORT.md`.

Labels: VERIFIED, PARTIALLY VERIFIED, UNVERIFIED, UNRESOLVED. Readiness labels (SOURCE READY, PARTIALLY READY, NOT READY) are defined and assigned only in the readiness report.

Source keys used below:
- **ACT** = Motor Vehicles Act, India Code consolidation "as on 15 August 2026" (176 pages, SHA-256 `c619755eabb2085ec5ef8068777724223f3ec7e1cc1170aee0dd1608216dc482`). Intact, not a Gazette print, currency not established.
- **P332** = India Code CMVR file (332 pages, SHA-256 `0713616187252c43f5dc17cd1fa3bdf6f553477e8049f7a065c03bb892b92fed`; re-fetched and hash-matched 2026-11-16). Newest dated footnote 2016. Stale.
- **F1 to F12** = Gazette and MoRTH PDFs in `~/kyr-acquisition/2026-11-16/` (hashes in the acquisition report): F1 G.S.R. 575(E); F2 48(E); F3 634(E) (2017 Driving Regulations); F4 586(E); F5 38(E); F6 Act 32 of 2019; F7 S.O. 691(E); F8 126(E); F9 draft 758(E); F10 28(E); F11 112(E); F12 draft 26(E).
- **R07, R298, R540, R911, R973** = G.S.R. 07(E), 298(E), 540(E), 911(E), 973(E) of 2026. Re-fetched by their registered e-Gazette IDs on 2026-11-16 and hash-matched to the register (not a new search).
- **TG24, TG25, TG32, TG77** = Telangana G.O.Ms.No.24/2026, 25/2026, 32/2026 and 77/2025, held as PDFs in `KnowYourRules-repo/docs/legal-sources/telangana-traffic/source-documents/goir/`. Registry status for all: `official_text_commencement_unconfirmed`.
- **TMVR** = Telangana Motor Vehicles Rules, 1989, held only as HTML snapshots (registry status `unverified_snapshot`; incomplete at rule 217 per the handoff).

## 1. Bottom line (after reconciliation)

- **The central rule layer is now mostly in hand for four topics:** rule 167A (F1, F2), rule 167 as substituted (F2), the Motor Vehicles (Driving) Regulations, 2017 (F3, F4, F5) and the child-safety rule 138(7) (F7, F8). The remaining CMVR rules are still read from **P332, which is stale**.
- **The 1989 Rules of the Road Regulations are superseded** (F3, G.S.R. 634(E): "in supersession of the Rules of the Road Regulations, 1989 ... except as respects things done or omitted to be done before such supersession"). Every earlier citation to "reg 22, 27, 32 (1989)" was to a superseded text and is replaced in section 3.
- **Rule 167A is no longer missing.** G.S.R. 575(E) (11-08-2021) inserted it; G.S.R. 48(E) (20-01-2026) amended sub-rules (7) to (10) and substituted rule 167. Telangana G.O.Ms.No.32/2026 cites exactly these two notifications.
- **A red-light correction:** the Act text held shows s.184 Explanation clause (a) names "jumping a red light" as dangerous driving, and rule 167A(3)(v) lists it under s.184. The earlier map put red light only under s.177A. See section 5, item 7. This is a textual observation for the advocate, not a reading of the law.
- **Still blocking:** Telangana G.O.Ms.No.42/2020 (not found), the 7 unidentified 2026 CMVR amendments, the 2017 to 2025 amendment history, G.S.R. 525(E) of 2021, and the Telangana snapshot being unverified.

## 2. How the 15 were chosen (unchanged)

- The "validated frequent traffic questions research" and a question-to-source map do not exist as files. Nearest sets: `eval/telangana-retrieval-benchmark.json` (all labels `pending_human_review`) and `eval/legal-validation/stage-19-review-questions.md`.
- **No popularity ranking or search-frequency claim is made.** Ordered by theme.
- Criteria: public usefulness, Telangana relevance, dependence on central rules, realistic official source.
- 11 questions come from the benchmark (ids shown); 4 are additions (**A**): seat belts, number plates, transfer of ownership, window glass.
- Telangana columns come from the benchmark's expected provisions and the registry; the Telangana text was not re-verified here beyond G.O.Ms.No.24, 25, 32 and 77, which were read.

## 3. The 15 questions, corrected legal references

"Verified here" means the text was read from a held official document in this pass. "Later change" lists only changes actually identified. **Unknown later changes are not "none".**

| # | Question (benchmark id) | Motor Vehicles Act | CMVR rule | Driving Regulations 2017 | Telangana |
|---|---|---|---|---|---|
| 1 | Helmet on a two-wheeler in Telangana (TG-PQ-001, TG-GC-004) | **s.129** as substituted by Act 32 of 2019 s.44, in force 15-02-2022 (F6, F7): every person above four years, helmet to "such standards as may be prescribed by the Central Government"; Sikh turban proviso; second proviso lets Central rules provide for children below four. s.128. s.137(aa) | **138(7)** inserted by 126(E) (F8): after one year from 15-02-2022 publication; child 9 months to 4 years: safety harness, crash or bicycle helmet, speed not above 40 kmph. Supporting: 138(4)(f) (P332), 123 (P332). 07(E) edits "the first proviso" and "the second proviso" of an unnamed clause of 138(4) (R07; the clause letter is missing from both the English and Hindi text; the added words are vehicle categories, so it is not on its face the helmet clause (f)) | none | TMVR r.437 (snapshot) |
| 2 | Fine for no helmet (TG-PN-001) | **s.194D** (penalty Rs 1,000 and disqualification 3 months; covers contravention of s.129 "or the rules or regulations made thereunder"); s.194C (s.128). s.200(1) does not name s.194D in the Act text held | 138(7) now within the s.194D reach by its wording | none | Compounding G.O.Ms.No.42/2020 **not found** |
| 3 | **A** Seat belt (compulsory, penalty) | **s.194B(1), (2)** (Rs 1,000; child under 14) | **138(3)**, **138(6)** (child up to 12; M1 made on or after 01-10-2014; from 01-04-2016), 125(1), 125(1-A) (all P332). 167A(3)(vii) lists s.194B for electronic enforcement (F1) | none | none identified |
| 4 | Drunk driving penalty (TG-PN-002) | **s.185** (above 30 mg per 100 ml; first offence up to 6 months or Rs 10,000; repeat up to 2 years or Rs 15,000). s.200(1) does not name s.185 in the Act text held | Rule 21(1)(16) (P332): drink or drugs as a licensing-authority disqualification ground. 48(E) inserts a rule 21(1) clause (25) (five or more offences in a year from 01-01-2026) | none | none identified |
| 5 | Overspeeding fine, and are speed cameras valid (TG-PN-003, TG-GO-003 to 005, TG-GO-012) | **s.112** (limits), **s.183** (LMV Rs 1,000 to 2,000; medium and heavy Rs 2,000 to 4,000; repeat: licence impounded under s.206(4)), **s.136A**, s.200(1) names s.183(1) | **167A(1)** (approval certificate by a State designated authority, renewed yearly), **167A(3)(i)** (speed, ss.112 and 183), 167A(2), (4) to (6), (7) as amended; **rule 167** as substituted (F1, F2). All verified here | **reg 16** (speed): 16(3)(ii) bars speed above the maximum "notified by the competent authority"; 16(5) 25 km/h near construction site, school, hospital where signed (F3). Verified here | **TG32** (30-06-2026): Designated Authority under rule 167A(1), paras 4, 5. Speed-limit notifications under s.112(2): **not obtained** |
| 6 | Red signal challan (TG-PN-004) | **s.119** (obey mandatory signs and the driving regulations), **s.184 Explanation clause (a)** (jumping a red light amounts to dangerous driving; first offence 6 months to 1 year or fine Rs 1,000 to 5,000), **s.177A** (breach of s.118 regulations: warning, then Rs 500 to 1,000) with **s.177A(2)** (a contravention that is also punishable under another provision is dealt with under that provision only). s.200(1) names only **clause (c)** of the s.184 Explanation | **167A(3)(v)** lists red-light jumping under s.184 for electronic enforcement | **reg 12(1)** red traffic light (stop before the stop line or pedestrian crossing); reg 40 (knowledge of signs and signals). Unchanged by 586(E) and 38(E) clause 12 (F3, F4, F5). Verified here | none identified; compounding G.O. not found |
| 7 | Penalty for driving without a licence (TG-PN-006) | **s.3, s.181** (up to 3 months, or fine Rs 5,000, or both), s.200(1) names s.181 | Rule 3 (learner exemption), only for exceptions | none | Compounding G.O.Ms.No.42/2020 **not found** |
| 8 | Documents to carry and show (TG-PQ-016) | **s.130** (licence on demand by a police officer in uniform; s.130(3) insurance certificate and, for a transport vehicle, fitness certificate; the rest of s.130(3) not read) | **139** (P332; 15 days to produce) | **reg 38** as amended by 586(E) (F3, F4): transport vehicle documents (38(1)); non-transport licence, PUC, RC and insurance or photocopies (38(3)); production on demand (38(4)); "in physical or electronic form"; 38(5) no demand for physical copies after electronic inspection finds them valid and in force. Verified here | TMVR r.400 (officers who may demand the RC) (snapshot). **TG25 is about challan delivery, not documents; the earlier link is removed** |
| 9 | Duplicate licence and fee (TG-PQ-002, TG-PQ-003) | not read for this task | **18(3)** provisos (duplicate for a lost, torn or mutilated licence: confirmation from the issuing authority; 60 days) (P332, text read here); **32** fee table (row not located); 16 (form). Draft 902(E) (16-10-2026) is a draft | none | TMVR rules 14, 16, 17, 18 (snapshot; rule 18 states a duplicate-licence fee of rupees fifteen) |
| 10 | PUC certificate (TG-PQ-007) | **s.190(2)** | **115(7)** (valid PUC after the first year; six months; twelve for BS-IV), **115(8)** (valid across India), **116** (all P332, 115(7) and (8) read here). 112(E), 911(E), 973(E) edit rule 115(2), 115(18), 115E and 115G; **none edits 115(7), 115(8) or 116** (read here) | **reg 38(1)(f), 38(3)(a)**: PUC among the documents to carry (F3, F4) | TMVR r.484 to 486 (snapshot) |
| 11 | **A** Number plates (HSRP) (links TG-DL-003) | s.39, s.41(6) | **50**, **51** (P332). P332 appends the Motor Vehicles (New High Security Registration Plates) Order, 2001 (Appendix I, in force 28-09-2001 for new vehicles). G.S.R. 417(E) of 25-06-2025 (hydrogen vehicles) not obtained. 167A(3)(x) cites reg 36 | **reg 36** registration plates: displayed as prescribed; front and rear plates clearly visible and legible; no other letter, word, figure, picture or symbol; no load hiding the plate (F3). Verified here | TMVR r.80, r.432 (snapshot) |
| 12 | **A** Transfer of a used vehicle | **s.50** (not read here) | **55** (P332 heading reads "54"; the fee table row 6 and 28(E) both cite rule 55). **28(E) inserts rule 55(2)(v)** (No Objection Certificate in Form 28) "after clause (iv)" (F10). **P332 rule 55(2) has only clauses (i) to (iii)**, so a clause (iv) exists that no held document contains. Rule 81 fee table row 6 (half the registration fee), and **298(E)** edits serial (11A) (R298). Rule 58 and rule 62(1) also amended by 28(E) | none | Taxation instruments (tax clearance) **not examined** |
| 13 | E-challan and updating the mobile number (TG-GO-001, TG-GO-002) | **s.136A** | **167** as substituted by 48(E) (F2): challan by hand within 15 days or by electronic means within 3 days (167(3)); 45 days to pay or contest on the portal (167(5)); deemed acceptance (167(6)); non-processing of licence or registration applications and "Not to be Transacted" flag (167(12)). **167A(6), (7) as amended, (8) to (10)** (F1, F2). Verified here | none | **TG25** (01-06-2026): SMS, WhatsApp and e-mail authorised as electronic means under rule 167(3); owners to update mobile and e-mail on Vahan within one month of publication; **TG24** (01-06-2026): redressal authorities under 167(5). Both say they are to be published in the Telangana Gazette dated 02-06-2026; **that Gazette is not held** |
| 14 | Seized vehicle release (TG-PQ-013) | **s.207** | **167(13)** (F2): "Subject to orders of the court", a police officer or authorised officer "may detain the vehicle involved in the violation" in respect of challans under rule 167. Added in this pass; not in the first map | none | TMVR r.448A, r.448B (snapshot) |
| 15 | **A** Dark film on windows | s.190 context only | **100(2)** (P332, read here): windscreen and rear window not less than 70% visual light transmission; side windows not less than 50%; IS 2553 Part 2 (1992) | none | none identified |

Questions whose core answer needs no CMVR rule or regulation text: **2 (statutory penalty), 4, 7** and Q1's core duty (the Act). Q14 now has a central rule, 167(13), that the first map missed. These still need the Act and the Telangana instruments.

## 4. Rule-by-rule availability (every provision named above)

"Gazette PDF held" means a verified e-Gazette original of the text or the change.

| Provision | Used by | Text held? | Later change identified | Gazette PDF held? | Open point |
|---|---|---|---|---|---|
| **167A** | Q5, Q13 | **Yes, original (F1) and amendment (F2)** | 48(E) amends (7) to (10). 2021 to 2025 changes not checked. 7 unidentified 2026 amendments | F1, F2 | G.S.R. 525(E) of 02-08-2021 (cited in F1's footnote; F1's Hindi footnote disagrees with the English) not obtained |
| **167** | Q13 | **Yes, as substituted (F2)** | none identified after 48(E) in the held 2026 finals (R298, R540, R911, R973, F11) | F2 | The old rule 167 text is not in P332 at all (no "challan" in P332) |
| **138(7)** | Q1, Q2 | **Yes (F8)** | none identified | F8 | BIS standard for harness and helmet not held. Draft 758(E) (F9) is a draft; its rule text is the same in substance |
| Act s.129 and s.44 of Act 32/2019 | Q1, Q2 | Yes (ACT, F6, F7) | none identified | F6, F7 | Act currency after 15-08-2026 not fully established (Act verification report) |
| **Driving Regulations 2017** regs 12, 16, 36, 37, 38 | Q5, Q6, Q8, Q10, Q11 | **Yes (F3)** | 586(E) (reg 37 proviso; reg 38) (F4); 38(E) clause 12 ("rear view mirror" wording, not regs 12, 16, 36, 37, 38) (F5). Nothing later identified | F3, F4, F5 | Currency at 16-11-2026 is PARTIALLY VERIFIED: no replacement found, but the search was limited |
| 3 | Q7 | Yes (P332) | none known | – | – |
| 18(3) | Q9 | Yes (P332) | none known; draft 902(E) touches 16, 17A, 32 | 902(E) as draft | – |
| 21 | Q4 | Yes (P332) | **48(E) inserts a clause (25)**; P332 already has a clause (25) ("Using mobile phone while driving a vehicle") | F2 | Numbering collision, unresolved |
| 32 (fee table) | Q9 | Yes, OCR garbled | draft 902(E) only | – | Individual duplicate-licence row not located |
| 50, 51 | Q11 | Yes (P332) | none known; lead 417(E) (25-06-2025) | No | Chain 2016 to 2026 unknown; Order 2001 is in P332 Appendix I |
| 55 (heading "54" in P332) | Q12 | **Incomplete**: P332 lacks clause (iv) | **28(E) inserts (v)** | F10 | The notification that inserted (iv) is unidentified |
| 58, 62(1), 90(7), Form 28 | Q12 (context) | No | 28(E) (unpaid user fee) | F10 | – |
| 81 (fee table) | Q12 | Older table only | 298(E) edits serial (11A); drafts 76(E), 902(E) | R298 | Serial (11A) insertion notification unidentified |
| 100(2) | Q15 | Yes (P332) | none known | – | Post-2016 status unknown |
| 115(7), (8), 116 | Q10 | Yes (P332) | rule 115 edited elsewhere by F11, R911, R973; not these sub-rules | F11, R911, R973 | PUC validity text may be stale in other ways; unknown 7 amendments |
| 123, 125, 138(3), 138(4)(f), 138(6) | Q1, Q3 | Yes (P332) | 07(E) edits two provisos of an unnamed clause of 138(4), adding vehicle categories | R07 | The clause letter is absent from 07(E); which clause it amends is unresolved |
| 139 | Q8 | Yes (P332) | unknown | – | Electronic-form wording unknown |
| Rules of the Road Regulations 1989 | none now | P332 Appendix | **Superseded by F3** | F3 | Appendix is not to be cited as operative |

## 5. Corrections log (what changed from the first version of this map)

1. **1989 Rules of the Road Regulations replaced** by the 2017 Driving Regulations. Mapping by subject: former reg 22 (traffic sign and traffic police) corresponds to reg 12 (traffic control signals), reg 13 (manual traffic control) and reg 24 (mandatory orders); former reg 27 (speed) to reg 16; former reg 32 (production of documents) to reg 38. "Corresponds" is a subject match for locating text, not a statement that the contents are equal.
2. **Rule 167A** moved from "No, unidentified" to held: F1 (original) and F2 (amended). The "insertion notification unidentified" entries are removed.
3. **Rule 167** added. It was not in the first map. It now carries Q13.
4. **Child-safety rule** moved from missing to held: rule 138(7) (F8), commenced via Act s.44 (F7). One year from 15-02-2022 applies by the rule's own words.
5. **Rule 138(4) edit by 07(E)** partly resolved: it adds vehicle categories ("L5, E-rickshaw, E-cart", "L7") to the first and second provisos of a clause of 138(4) whose letter is missing from the notification. It adds nothing about helmets. Which clause is unresolved.
6. **Q8 Telangana column**: G.O.Ms.No.25/2026 removed (it is about challan service). Moved to Q13 where the benchmark questions TG-GO-001 and TG-GO-002 belong.
7. **Q6 penalty provisions**: the first map named s.119, s.177A and s.177. The Act text held shows **s.184 Explanation (a)** also names red-light jumping, rule 167A(3)(v) cites s.184 for it, and s.177A(2) says another provision's penalty applies alone. Which applies is for the advocate; this map does not choose. (s.177 is not read here.)
8. **Q12**: the rule-55 text is shown to be **stale in a specific way** (clause (iv) missing). Not previously known.
9. **Q5**: reg 16 (2017) is added as the speed regulation.
10. **Unidentified 2026 amendments**: "at least 8 of 15" is corrected to **7** (the Third, Fourth and Fifth are 48(E), 112(E), 298(E)).
11. The footnote "**G.S.R. 76(E), 31-1-2000**" in P332 is still a different notification from the 2026 draft 76(E). Cite with the year.

## 6. Cautions for whoever uses this

- **G.S.R. numbers repeat across years.** 48(E) of 2022 is not 48(E) of 2026; 76(E) of 2000 is not 76(E) of 2026.
- **The rule 21(1) clause "(25)" collision** (section 4) is unresolved and must not be quoted without both texts.
- **Act s.194B(2) says 14 years; rule 138(6) says 12.** Conflict recorded, not resolved.
- **F1's Hindi footnote and English footnote disagree** on the last amendment before 575(E) (English: 525(E) of 02-08-2021).
- **The Telangana GOs are "official text, commencement unconfirmed"** in the project registry. Reading them here did not change that.
- **P332 carries the 1989 Regulations and the HSRP Order 2001 as appendices.** Treat both as historic unless a held document says otherwise.
- **TMVR is a snapshot.** A keyword miss there is not proof of absence.

## 7. Boundaries

No application code, ChromaDB index, embedding configuration, source registry, approval record or legal decision register was touched. Nothing was ingested, activated or approved. No legal approval is claimed. Nothing was committed, pushed or deployed. No new Gazette search was run: the work used the 12 documents in `~/kyr-acquisition/2026-11-16/`, plus re-downloads of already-registered documents by their recorded URL or ID (P332 and five 2026 finals), each hash-checked against its register entry, plus Telangana PDFs already in the repository. Files changed: this file, `PRIORITY-CMVR-DOCUMENT-GAP-LIST.md`; created: `PRIORITY-15-QUESTION-READINESS-REPORT.md`.
