# Stage 21: legal source review and version status

**Purpose:** record what the repository can prove about its legal sources. **No provision is declared current**, and the register has no `current` field.

**Changed files:** new files only, all in `eval/legal-validation/`:
- this report;
- [`stage-21-legal-source-status.json`](stage-21-legal-source-status.json): the register, separating verified facts from unresolved points;
- [`stage-21-review-questions.md`](stage-21-review-questions.md): 14 questions.

**Not changed:** sources, manifests, checksums, retrieval code, indexes, the benchmark, the CSV and approvals. No downloads, no external calls, nothing committed.

## 1. Six historical G.O.s
The six are G.O.Ms.No. 02 (17-06-2014), 41 (29-09-2015), 44 (15-10-2015), 95 (08-12-2016), 26 (24-04-2017) and 52 (11-04-2018), all TR&B (Transport-I).

| Point | Finding |
|---|---|
| Where cited | The "Read" lists of G.O. 54 and G.O. 77, and the TG-GO54 row in `SOURCE-MANIFEST.md` |
| Subject | **Not stated in any held document** |
| Relationship to Rule 81 | **Inferred only** from being cited by two Rule 81 orders. Not verified for any of them individually |
| Copies | None in either checkout or any inventory |
| Missing | Each order, its Gazette publication, and its subject |

The base rules, AP G.O.Ms.No. 216 of 07-08-1989, are also only cited. The summary's "GOMS10-2014" is a different order, G.O.Ms.No. 10/2014.

## 2. Rule 81 chronology
**Corpus records:** two chunks, both `answer_eligible=True` and `unverified_snapshot`, with no amendment metadata. Structured lookup returns both of them.

| Instrument | Date | Clauses | Changes established by text | Publication evidence | Commencement evidence | Status | Missing |
|---|---|---|---|---|---|---|---|
| AP G.O.Ms.No. 216 | 07-08-1989 | Base rules | None held | Cited: AP Gazette 25-08-1989, pp. 1–135 | None | Cited only | Text, Gazette |
| G.O.s 02/2014 – 52/2018 (6) | 2014–2018 | Unknown | None | None | None | Cited only; link to Rule 81 unverified | Orders, subjects, Gazettes |
| Web snapshot | Retrieved 29-10-2026 | (1)–(6) | n/a: Form RRMA, fees from Rs. 50,000 to Rs. 5,000 | None (web consolidation) | None | Unverified; which amendments it reflects is unknown | As-amended date |
| G.O.Ms.No. 54 | 13-08-2025 | Proposed: omit (1), (2), (4); substitute (3), (5), (6) | None (a draft under s.212(1)) | G.O. 77 recites Gazette G-575 of 13.08.2025; not held | n/a | Draft; G.O. 77's text says it was finalised by G.O. 77 | Gazette G-575 |
| G.O.Ms.No. 77 | 15-11-2025 | Omit (1), (2), (4); substitute (3), (5), (6) | **Confirmed text:** online-only applications; fees from Rs. 1,50,000 to Rs. 6,000 (Rs. 3,000 for two-wheelers); current number Rs. 2,000; online bidding; 15-day production deadline | The order directs a Gazette issue of 15.11.2025; not held | **None:** no commencement clause | Held and checksummed | Gazette, commencement, the `74a6839d…` file |
| Any later instrument | After 15-11-2025 | Unknown | None | Not searched | None | Unknown | A search of the Gazette and GOIR |

**What is confirmed and what is not**
- **Confirmed text change:** only G.O. 77's printed amendments.
- **Assumed legal effect:** that G.O. 77 took effect on Gazette publication. This is an assumption, not evidence.
- **Unknown:** commencement, and any later amendments.

No consolidated text was produced.

## 3. G.O. 24/2026
**Document:** G.O.Ms.No. 24, TR&B (TR-I), 01-06-2026, on Rule 167(5) of the Central Motor Vehicles Rules: authorities that dispose of contested challans.

**Wording**
- **The order** says it "decided to publish the draft Notification, as required under Rule 167".
- **The body** is headed "NOTIFICATION" and gives redressal authorities, jurisdiction, filing and migration to the national e-challan system (Sarathi/Vahan).
- **Paragraph 5:** "This Notification shall come into force from the date of its publication in the Telangana Gazette."

**Points against it being a draft**
- No objection period, and no reference to s.212.
- The companion G.O. 25 (same date, same reference letter) says "publish Notification", without "draft".

**Other evidence**
- **Publication:** directed for the Gazette of 02-06-2026, but the note to the printer leaves the date blank. No Gazette copy is held.
- **Other labels:** only the Stage 7 ingestion note mentions the ambiguity, and no final notification is referenced anywhere.

**Status: unresolved, not classified as final.**

## 4. Other 2026 G.O.s
| G.O. | Change | Stated effective date | Underlying text held? | Could supersede corpus content? | Needed |
|---|---|---|---|---|---|
| 10 (25-02-2026) | Appoints 01-03-2026 as the commencement of Act No. 8 of 2026 (TMVT Amendment) | 01-03-2026 (appointed date) | **No.** The Act is not held | Unknown, because the Act's content is unknown | Act No. 8/2026; Gazette of 01.03.2026 |
| 16 (20-03-2026) | Deletes **column No. 8** of the TMVT Seventh Schedule: the extra 2% on second or later personal vehicles | "with effect from 23.03.2026" | Partly: G.O. 53's schedule is held; G.O. 22/2022 is not | **Yes**, see below | Gazette of 23.03.2026; G.O. 22/2022 |
| 25 (01-06-2026) | SMS, WhatsApp and e-mail as ways to serve challans under CMVR Rule 167 | "with immediate effect"; Gazette directed for 02.06.2026 | No (CMVR is out of scope) | None identified | Gazette; CMVR Rule 167 as amended |
| 32 (30-06-2026) | Six-member Designated Authority under CMVR Rule 167A(1) | **None stated** | No | None identified | CMVR 167A; G.S.R. 575(E) and 48(E); Supreme Court orders; Gazette |

**G.O. 16 and G.O. 53**
**Verified**
- G.O. 16 cites G.O. 53.
- G.O. 53 paragraph 3 substitutes the whole Seventh Schedule. Its column (8) is headed "Second or more personalized vehicles upto a seating capacity of ten (10) in all owned by an individual".
- G.O. 16 deletes "column No.8" with that same description.

**Affected chunk:** `go-ms-53-2025-trb::SEVENTH SCHEDULE::part1of1` (pages 3–4). It is **already `answer_eligible=False`** because of unreliable table extraction, so answers do not use it today.

**Flag not applied.** A reviewer should first confirm the Gazette of 23.03.2026 and that nothing later changed the column.

## 5. Inventory anomalies (nothing deleted or replaced)
- **`2008trb_ms332_compounding.pdf`:** an Andhra Pradesh G.O. (332/2008) on permit compounding. It is deliberately excluded from the draft manifest because its "applicability is unestablished".
- **`rules_of_the_road_regulations_1989.pdf`:** Central (S.O. 439(E)). Deliberately excluded under the user's scope decision of 08-11-2026.
- **`74a6839d…`:** the supplied summary lists an archive file `TMVR-1989-GO77-2025.pdf` with this hash, truncated in the PDF. The file is absent, so whether it is a Gazette print, a different download or an error cannot be determined.
- **G.O. 54:** a draft. G.O. 77's own text says it was published (Gazette G-575), drew no objections and is finalised by G.O. 77. It is excluded from the manifest, and the file is kept and checksummed.

## 6. Validation
- **Checksums:** 63/63 OK with `shasum -c`; `source_compare checksums` gives 63 OK, 0 mismatched, 0 missing.
- **Tests:** 672 OK in exact mode and 672 OK in HNSW mode.

## Questions requiring human legal review
See `stage-21-review-questions.md`. In summary:
- The subjects of the six G.O.s, and whether each amended Rule 81.
- What the Rule 81 snapshot reflects.
- The Gazette publication and commencement of G.O. 77, and confirmation of G.O. 54's publication.
- Any amendments to Rule 81 since November 2025.
- What the `74a6839d…` file is.
- How to treat the snapshot meanwhile.
- Whether G.O. 24 is a draft or final.
- The content of Act No. 8/2026.
- Confirming the G.O. 16 → G.O. 53 column 8 supersession.
- Whether G.O. 25 and 32 should stay eligible, and G.O. 32's effective date.
- Whether G.O. 332/2008 applies in Telangana.
- Confirming that the Rules of the Road stay excluded.
