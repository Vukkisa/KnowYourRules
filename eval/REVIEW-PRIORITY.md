# Review priority: Telangana retrieval benchmark

Generated from `eval/telangana-retrieval-benchmark.json`, the review CSV and the preview index. Every case has one **primary** group (the highest-priority group it belongs to; this is `review_priority` in the CSV) and may also belong to lower-priority groups (`also_in_groups`). All 108 cases are `pending_human_review`.

`machine` is the engineering result against the machine label (PASS, PARTIAL or n/a for guard outcomes). It is **not** a legal assessment.

| Priority | Group | Primary cases | Cases in group |
|---|---|---|---|
| 1 | G.O.s and amendments | 21 | 21 |
| 2 | multiple provisions | 15 | 21 |
| 3 | superseded or excluded material | 0 | 9 |
| 4 | ambiguous rule numbers | 6 | 7 |
| 5 | guards: missing provision, Central law, out of scope, penalty | 23 | 24 |
| 6 | single-provision lookups | 43 | 43 |

## 1. G.O.s and amendments

**Why review:** G.O.s change the base rules and each other, are dated, and some are drafts (G.O. 24/2026) or contain unreliable tables (G.O. 53/2025 schedules). Machine labels were written from paragraph headings; whether a paragraph is operative, preliminary or merely recited needs a legal reader. Three of the seven PARTIAL results are here (GO-003, GO-007, GO-012).

| ID | Primary here | Machine | Question |
|---|---|---|---|
| TG-GO-001 | yes | PASS | Can traffic challans be sent to me by WhatsApp or SMS in Telangana? |
| TG-GO-002 | yes | PASS | Do vehicle owners need to update their mobile number and e-mail on the Vahan portal? |
| TG-GO-003 | yes | PARTIAL | Who certifies electronic enforcement devices such as speed cameras in Telangana? |
| TG-GO-004 | yes | PASS | Who chairs the Designated Authority for electronic enforcement devices? |
| TG-GO-005 | yes | PASS | How often must approval certificates for electronic enforcement devices be renewed? |
| TG-GO-006 | yes | PASS | When did the Telangana Motor Vehicles Taxation (Amendment) Act, 2026 come into force? |
| TG-GO-007 | yes | PARTIAL | Which 2025 G.O. finally amended Rule 81 on reservation of special registration numbers? |
| TG-GO-008 | yes | PASS | Were any objections received to the preliminary notification amending Rule 81? |
| TG-GO-009 | yes | PASS | Which earlier G.O.s are read in G.O.Ms.No. 77 of 2025? |
| TG-GO-010 | yes | PASS | What did G.O.Ms.No. 16 of 2026 change in the vehicle tax schedules? |
| TG-GO-011 | yes | PASS | What is G.O.Ms.No. 53 of 2025 about? |
| TG-GO-012 | yes | PARTIAL | Why did Telangana notify a Designated Authority under Rule 167A? |
| TG-EX-001 | yes | n/a | Who are the redressal authorities for contested challans in Hyderabad? |
| TG-EX-002 | yes | n/a | What does G.O.Ms.No. 24 of 2026 say? |
| TG-EX-003 | yes | n/a | Within how many months must Transport and Police migrate to the Sarathi and Vahan e-challan system? |
| TG-EX-004 | yes | n/a | What is the life tax rate for a new car under G.O.Ms.No. 53? |
| TG-EX-005 | yes | n/a | Is there an additional 2% tax on a second personal vehicle? |
| TG-EX-006 | yes | n/a | What does the Seventh Schedule of the Telangana Motor Vehicles Taxation Act say after 2026? |
| TG-EX-007 | yes | n/a | What is the life tax for an already registered vehicle by age? |
| TG-EX-008 | yes | n/a | What are the Third Schedule and Sixth Schedule life tax rates? |
| TG-OS-005 | yes | n/a | What did the Motor Vehicles (Amendment) Act, 2019 change? |

## 2. Multiple provisions

**Why review:** A complete answer needs more than one provision, so a label can be wrong by listing too many or too few. Recall@5 marks a row PARTIAL if any listed provision is missing, even when the main one is found, so over-broad labels look like retrieval failures. Four PARTIAL results are here.

| ID | Primary here | Machine | Question |
|---|---|---|---|
| TG-PQ-002 | yes | PARTIAL | I lost my driving licence. How do I get a duplicate? |
| TG-PQ-006 | yes | PASS | When am I not allowed to use the horn? |
| TG-PQ-007 | yes | PASS | Where can I get a pollution under control certificate? |
| TG-PQ-009 | yes | PASS | Can a taxi driver refuse to start the meter? |
| TG-PQ-013 | yes | PASS | My vehicle was seized. How do I get it released? |
| TG-PQ-017 | yes | PARTIAL | How do I apply for accident compensation before the Claims Tribunal? |
| TG-PQ-021 | yes | PARTIAL | Where are vehicles allowed to park or halt? |
| TG-MR-001 | yes | PASS | Compare Rule 437 and Rule 427. |
| TG-MR-002 | yes | PASS | What do rules 16 and 18 say about duplicate licences? |
| TG-MR-003 | yes | PASS | Explain rules 371 and 379 on taxi meters. |
| TG-MR-004 | yes | PASS | What do rules 448A and 448B say about seizure and release of vehicles? |
| TG-MR-005 | yes | PASS | Summarise rules 484 to 486 on pollution certificates. |
| TG-MR-006 | yes | PASS | What do rules 187 and 188 say about permit conditions? |
| TG-MR-007 | yes | PASS | What are the badge rules for drivers and for conductors? |
| TG-MR-008 | yes | PARTIAL | Who issues medical certificates for drivers and for conductors? |
| TG-GO-003 | no | PARTIAL | Who certifies electronic enforcement devices such as speed cameras in Telangana? |
| TG-GO-005 | no | PASS | How often must approval certificates for electronic enforcement devices be renewed? |
| TG-GO-007 | no | PARTIAL | Which 2025 G.O. finally amended Rule 81 on reservation of special registration numbers? |
| TG-GO-008 | no | PASS | Were any objections received to the preliminary notification amending Rule 81? |
| TG-GO-011 | no | PASS | What is G.O.Ms.No. 53 of 2025 about? |
| TG-GO-012 | no | PARTIAL | Why did Telangana notify a Designated Authority under Rule 167A? |

## 3. Superseded or excluded material

**Why review:** These rows test that excluded text (G.O. 24 draft, G.O. 53 schedules, G.O. 16 Seventh Schedule) is never used. A reviewer must confirm that each exclusion is right and that the question has no other, eligible source the system should have used instead. Two G.O. 53 chunks share one chunk ID.

| ID | Primary here | Machine | Question |
|---|---|---|---|
| TG-GO-009 | no | PASS | Which earlier G.O.s are read in G.O.Ms.No. 77 of 2025? |
| TG-EX-001 | no | n/a | Who are the redressal authorities for contested challans in Hyderabad? |
| TG-EX-002 | no | n/a | What does G.O.Ms.No. 24 of 2026 say? |
| TG-EX-003 | no | n/a | Within how many months must Transport and Police migrate to the Sarathi and Vahan e-challan system? |
| TG-EX-004 | no | n/a | What is the life tax rate for a new car under G.O.Ms.No. 53? |
| TG-EX-005 | no | n/a | Is there an additional 2% tax on a second personal vehicle? |
| TG-EX-006 | no | n/a | What does the Seventh Schedule of the Telangana Motor Vehicles Taxation Act say after 2026? |
| TG-EX-007 | no | n/a | What is the life tax for an already registered vehicle by age? |
| TG-EX-008 | no | n/a | What are the Third Schedule and Sixth Schedule life tax rates? |

## 4. Ambiguous rule numbers

**Why review:** Rule numbers repeat across the TMVR and the TMVTR, and short questions ("What is the fee?") have many candidates. A reviewer decides whether clarification is right, or whether one reading is clearly intended.

| ID | Primary here | Machine | Question |
|---|---|---|---|
| TG-MR-002 | no | PASS | What do rules 16 and 18 say about duplicate licences? |
| TG-AM-001 | yes | n/a | What does Rule 10 say? |
| TG-AM-002 | yes | n/a | What does Rule 1 say? |
| TG-AM-003 | yes | n/a | Tell me about the badge. |
| TG-AM-004 | yes | n/a | How do I get a duplicate? |
| TG-AM-005 | yes | n/a | What is the fee? |
| TG-AM-006 | yes | n/a | Can I park there? |

## 5. Guards: missing provision, Central law, out of scope, penalty

**Why review:** The expected behaviour is a deterministic refusal. Review confirms that each provision really is absent from the official instruments (not just from the snapshots), that Central-law questions really have no Telangana answer, and that the penalty-locked questions are ones that should stay locked.

| ID | Primary here | Machine | Question |
|---|---|---|---|
| TG-MP-001 | yes | n/a | What does Rule 186 say? |
| TG-MP-002 | yes | n/a | Explain TMVR rule 186. |
| TG-MP-003 | yes | n/a | What are the conditions in Rule 186 of the Telangana Motor Vehicles Rules? |
| TG-MP-004 | yes | n/a | Compare rules 185, 186 and 187. |
| TG-MP-005 | yes | n/a | What do rules 186 and 188 say? |
| TG-MP-006 | yes | n/a | What is rule 999 of the Telangana Motor Vehicles Rules? |
| TG-MP-007 | yes | n/a | What does TMVTR rule 99 say? |
| TG-MP-008 | yes | n/a | Explain Rule 600 of the TMVR. |
| TG-GC-001 | yes | PASS | What does Rule 188 say? |
| TG-GC-002 | yes | PASS | What does Rule 185 say? |
| TG-GC-003 | yes | PASS | What does TMVTR rule 13A say? |
| TG-GC-004 | yes | PASS | helmet rule for 2 wheeler riders |
| TG-PN-001 | yes | n/a | What is the fine for not wearing a helmet in Telangana? |
| TG-PN-002 | yes | n/a | How much is the penalty for drunk driving? |
| TG-PN-003 | yes | n/a | What is the fine for overspeeding? |
| TG-PN-004 | yes | n/a | What is the challan amount for jumping a red signal? |
| TG-PN-005 | yes | n/a | What is the fine under Rule 186? |
| TG-PN-006 | yes | n/a | How much do I have to pay if I am caught driving without a licence? |
| TG-OS-001 | yes | n/a | What does Section 185 of the Motor Vehicles Act, 1988 say? |
| TG-OS-002 | yes | n/a | Is FASTag mandatory under the Central Motor Vehicles Rules? |
| TG-OS-003 | yes | n/a | What are the Bharat Stage VI emission norms? |
| TG-OS-004 | yes | n/a | How do I apply for an International Driving Permit? |
| TG-OS-005 | no | n/a | What did the Motor Vehicles (Amendment) Act, 2019 change? |
| TG-OS-006 | yes | n/a | How is a national permit for goods carriages granted under the Central Motor Vehicles Rules? |

## 6. Single-provision lookups

**Why review:** One rule, usually named in the question, with a PASS result. Lowest risk, but the expected rule's text still comes from unverified snapshots, so currency (amendments since the snapshot) still needs checking.

| ID | Primary here | Machine | Question |
|---|---|---|---|
| TG-DL-001 | yes | PASS | What does Rule 437 of the Telangana Motor Vehicles Rules say? |
| TG-DL-002 | yes | PASS | What does Rule 2 of the TMVR define? |
| TG-DL-003 | yes | PASS | What is Rule 80 on registration marks? |
| TG-DL-004 | yes | PASS | Explain TMVR Rule 371 on taxi-meters. |
| TG-DL-005 | yes | PASS | What is Rule 427 about? |
| TG-DL-006 | yes | PASS | What does TMVR Rule 244 say? |
| TG-DL-007 | yes | PASS | What does Rule 389A provide? |
| TG-DL-008 | yes | PASS | What does Rule 191 require? |
| TG-DL-009 | yes | PASS | What is Rule 18 about the fee for a duplicate licence? |
| TG-DL-010 | yes | PASS | What does Rule 37 say about the driver's badge? |
| TG-DL-011 | yes | PASS | What are the duties of conductors under Rule 74? |
| TG-DL-012 | yes | PASS | Who issues a certificate of fitness under Rule 107? |
| TG-DL-013 | yes | PASS | What does Rule 177 say about permits for autorickshaws? |
| TG-DL-014 | yes | PASS | What does Rule 294A say about motor cycle taxis? |
| TG-DL-015 | yes | PASS | What does Rule 406 say about parking places? |
| TG-DL-016 | yes | PASS | What does Rule 448B say about release of detained vehicles? |
| TG-DL-017 | yes | PASS | What does Rule 451 require about insurance certificates? |
| TG-DL-018 | yes | PASS | What does Rule 471 say about judgment and award of compensation? |
| TG-DL-019 | yes | PASS | What does Rule 484 say about issuing Pollution Under Control certificates? |
| TG-DL-020 | yes | PASS | What powers does Rule 454 give police officers? |
| TG-DL-021 | yes | PASS | What does TMVTR Rule 11 say about duplicate licences? |
| TG-DL-022 | yes | PASS | What does Rule 314 say about blue lights? |
| TG-DL-023 | yes | PASS | What does Rule 430 say about dazzling lights? |
| TG-DL-024 | yes | PASS | What does Rule 297A cover? |
| TG-DL-025 | yes | PASS | What does Rule 426 say about carrying dangerous substances? |
| TG-PQ-001 | yes | PASS | Do I have to wear a helmet on a two-wheeler in Telangana? |
| TG-PQ-003 | yes | PASS | How much does a duplicate driving licence cost? |
| TG-PQ-004 | yes | PASS | Can autorickshaws carry school children? |
| TG-PQ-005 | yes | PASS | Is smoking allowed on buses? |
| TG-PQ-008 | yes | PASS | Who is allowed to put a blue light on a car? |
| TG-PQ-010 | yes | PASS | Do bus passengers have to pay the fare when asked? |
| TG-PQ-011 | yes | PASS | Can a goods vehicle carry people? |
| TG-PQ-012 | yes | PASS | Can I tow my friend's bicycle or motorbike with my motorcycle? |
| TG-PQ-014 | yes | PASS | Do I have to keep the permit inside the vehicle? |
| TG-PQ-015 | yes | PASS | Can I attach a trailer to my motorcycle? |
| TG-PQ-016 | yes | PASS | Which officers can ask me to show my vehicle's registration certificate? |
| TG-PQ-018 | yes | PASS | Do I need an insurance certificate before a permit is issued? |
| TG-PQ-019 | yes | PASS | Can I keep my headlights on high beam in traffic? |
| TG-PQ-020 | yes | PASS | Is it allowed to jump on or off a bus while it is moving? |
| TG-PQ-022 | yes | PASS | Can a goods carriage transport animals? |
| TG-PQ-023 | yes | PASS | What education do I need to get a conductor's licence? |
| TG-PQ-024 | yes | PASS | Can passengers travel standing in a stage carriage bus? |
| TG-PQ-025 | yes | PASS | What happens to a vehicle left abandoned on the road? |

## Known label issues (from the engineering audit; labels unchanged)

| ID | Issue |
|---|---|
| TG-AM-004 | 6 expected provisions: check whether all are needed |
| TG-EX-004 | chunk ID go-ms-53-2025-trb::SCHEDULE::part1of1 is shared by 2 indexed chunks (goir/13082025TRB_MS53.PDF#page=4; goir/13082025TRB_MS53.PDF#page=4 .. goir/13082025TRB_MS53.PDF#page=5); identify by location |
| TG-EX-005 | chunk ID go-ms-53-2025-trb::SCHEDULE::part1of1 is shared by 2 indexed chunks (goir/13082025TRB_MS53.PDF#page=4; goir/13082025TRB_MS53.PDF#page=4 .. goir/13082025TRB_MS53.PDF#page=5); identify by location / excluded_chunks lists go-ms-53-2025-trb::SEVENTH SCHEDULE::part1of1 @ goir/13082025TRB_MS53.PDF#page=3 .. goir/13082025TRB_MS53.PDF#page=4 2 times / excluded_chunks lists go-ms-53-2025-trb::SCHEDULE::part1of1 @ goir/13082025TRB_MS53.PDF#page=4 2 times / excluded_chunks lists go-ms-53-2025-trb::SCHEDULE::part1of1 @ goir/13082025TRB_MS53.PDF#page=4 .. goir/13082025TRB_MS53.PDF#page=5 2 times |
| TG-EX-006 | chunk ID go-ms-53-2025-trb::SCHEDULE::part1of1 is shared by 2 indexed chunks (goir/13082025TRB_MS53.PDF#page=4; goir/13082025TRB_MS53.PDF#page=4 .. goir/13082025TRB_MS53.PDF#page=5); identify by location |
| TG-EX-007 | chunk ID go-ms-53-2025-trb::SCHEDULE::part1of1 is shared by 2 indexed chunks (goir/13082025TRB_MS53.PDF#page=4; goir/13082025TRB_MS53.PDF#page=4 .. goir/13082025TRB_MS53.PDF#page=5); identify by location |
| TG-EX-008 | chunk ID go-ms-53-2025-trb::SCHEDULE::part1of1 is shared by 2 indexed chunks (goir/13082025TRB_MS53.PDF#page=4; goir/13082025TRB_MS53.PDF#page=4 .. goir/13082025TRB_MS53.PDF#page=5); identify by location |
| TG-GO-003 | 3 expected provisions: check whether all are needed / machine result PARTIAL: some expected provisions not in the top 5 / expected G.O. 32 'Order' chunk is never retrieved by vector search; check it is needed |
| TG-GO-007 | 4 expected provisions: check whether all are needed / machine result PARTIAL: some expected provisions not in the top 5 |
| TG-GO-012 | 3 expected provisions: check whether all are needed / machine result PARTIAL: some expected provisions not in the top 5 / expected G.O. 32 'Order' and 'Paragraph 2' chunks may be broader than the question |
| TG-MR-005 | 3 expected provisions: check whether all are needed |
| TG-MR-008 | machine result PARTIAL: some expected provisions not in the top 5 |
| TG-PQ-002 | 4 expected provisions: check whether all are needed / machine result PARTIAL: some expected provisions not in the top 5 |
| TG-PQ-017 | machine result PARTIAL: some expected provisions not in the top 5 |
| TG-PQ-021 | machine result PARTIAL: some expected provisions not in the top 5 |
