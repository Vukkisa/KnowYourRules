# Telangana real-document validation report

**Prepared:** 08 November 2026. **Status: NOT APPROVED. No index built.** This report is technical. It contains no legal approval.

Companion files: [`DRAFT-telangana-manifest.json`](DRAFT-telangana-manifest.json) (draft, 14 entries), [`SOURCE-MANIFEST.md`](SOURCE-MANIFEST.md), [`EVIDENCE-GAP-REGISTER.md`](EVIDENCE-GAP-REGISTER.md).

All 57 files in `source-documents/` match `SHA256SUMS`, checked on 08-11-2026. No new G.O. files were found in the user's Downloads folder.

## 1. Real document inventory

| File (under `source-documents/`) | Title (as printed) | Issuing authority | Number | Dated | Type | Format | Source URL |
|---|---|---|---|---|---|---|---|
| `html-snapshots/tmvr-1989/middle-main-chap-1..12.htm` (12 files) | Telangana Motor Vehicles Rules, 1989 (rule 1) | Not stated on the page; header reads "Finance Department Govt. of Andhra Pradesh" | — | Not stated | Rules (consolidated web text) | HTML | `https://www.transport.telangana.gov.in/html/acts-rules/middle-main-chap-N.htm` (frame src of `main-chap-N.htm`) |
| `html-snapshots/tmvr-1989/` other 37 files (`index.html`, `main-`, `top-`, `left-main-chap-N`) | Navigation, frame sets, headers and contents lists | — | — | — | Not an instrument | HTML | Same site |
| `html-snapshots/tmvtr-1963/middle-ap-mv-tr-1963-main.htm` | Telangana Motor Vehicles Taxation Rules, 1963 (rule 1); page title "ANDHRA PRADESH MOTOR VEHICLES TAXATION RULES, 1963" | Not stated | — | Not stated | Rules (consolidated web text) | HTML | `…/acts-rules/middle-ap-mv-tr-%201963-main.htm` (frame src) |
| `html-snapshots/tmvtr-1963/` other 3 files | Frame set, header, contents | — | — | — | Not an instrument | HTML | Same site |
| `goir/13082025TRB_MS53.PDF` | Amendment to the Third, Sixth and Seventh Schedules … life tax – Notification | TR&B (Tr.I) Department, Government of Telangana | G.O.Ms.No. 53 | 13-08-2025 (G.O.); gazette 14-08-2025 directed, not obtained | G.O. (tax notification) | PDF, 5 pp. | goir.telangana.gov.in (form download; no file URL) |
| `goir/2025TRB_Ms54.pdf` | Amendment to rule 81 of the TMVR, preliminary notification | TR&B (Tr.I) Department, Government of Telangana | G.O.Ms.No. 54 | 13-08-2025 | **Draft** (s.212(1), objections invited) | PDF, 3 pp. | goir.telangana.gov.in |
| `transport-dept/2008trb_ms332_compounding.pdf` | Revision of compounding fee under s.86(5): amends rule 217 of the AP MV Rules, 1989 | **Government of Andhra Pradesh**, TR&B (Tr.I) | G.O.Ms.No. 332 | 13-11-2008 | G.O. (rules amendment, final) | PDF, 5 pp. | `https://www.transport.telangana.gov.in/html/pdf/2008trb_ms332_compounding.pdf` |
| `transport-dept/rules_of_the_road_regulations_1989.pdf` | Rules of the Road Regulations, 1989 | Central Government | S.O. 439(E) | 12-06-1989 | Central regulations | PDF, 5 pp. | `https://www.transport.telangana.gov.in/html/pdf/rules_of_the_road_regulations_1989.pdf` |

Effective dates are recorded for none of them. The documents themselves don't state one in a form that has been verified, so the manifest leaves it null.

## 2. Source verification

| Document | Classification | Reason |
|---|---|---|
| TMVR 1989 chapters | **Historical or unverified snapshot** | The consolidated web text carries no amendment citations or "as amended" date. It is demonstrably outdated at rule 217 (amounts superseded by G.O.Ms.No. 332/2008) and not reconciled with the rule 81 amendments (G.O.Ms.No. 54/77 of 2025 and the 2014–2018 chain). Its header is an Andhra Pradesh department's. |
| TMVTR 1963 | **Historical or unverified snapshot** | The title shows "Andhra Pradesh" while rule 1 says Telangana. The adaptation instrument is unknown, and so is whether the text is current. |
| G.O.Ms.No. 53/2025 | **Official source but current applicability not verified** | Taken from the government's own register and read in full. The gazette print is not held, and later changes (e.g. G.O.Ms.No. 16/2026, Seventh Schedule) are unchecked. |
| G.O.Ms.No. 54/2025 | **Draft** | Preliminary notification. The final version is G.O.Ms.No. 77/2025, which hasn't been retrieved. |
| G.O.Ms.No. 332/2008 | **Official source but current applicability not verified** (pre-2014 Andhra Pradesh order) | Issued by the Government of AP. How it continues in Telangana is unestablished. It is permit compounding (s.86(5)), **not** the s.200 traffic-offence schedule. Penalty content, so locked in any case. |
| Rules of the Road Regulations, 1989 | **Out of scope** (Central) | Excluded by the Telangana-only decision of 08-11-2026. |
| Navigation and frame files (40) | Not an instrument | Not ingested. |
| Duplicates | **None** | No two files share a hash or a file name. |

Possible superseding orders and amendments still to check:
- **Rule 81 chain:** G.O.Ms.No. 02/2014, 41/2015, 44/2015, 95/2016, 26/2017, 52/2018, 54/2025 (draft) and 77/2025 (final).
- **Rule 217:** G.O.Ms.No. 332/2008, which itself may have been superseded.
- **Taxation schedules:** G.O.Ms.No. 22/2022 (cited by No. 53), 53/2025, 16/2026.
- **Taxation Act:** Act No. 8 of 2026 and its commencement notification, G.O.Ms.No. 10/2026.

No document is marked legally verified. "Official" here means only that the copy came from the issuing authority's own publication channel.

## 3. Draft manifest

`DRAFT-telangana-manifest.json`: 14 entries (12 TMVR chapters, TMVTR, G.O.Ms.No. 53/2025).
- **Validated** with `tg_manifest.load_manifest` and `file_errors`: schema, hashes and file references all pass.
- **Unknown fields are `null`.** Publication and effective dates are null for every entry. G.O. 53's order date (13-08-2025) is in its notes, because the schema's publication date means gazette publication and that print isn't held.
- **Labels:** the snapshots are `unverified_snapshot` / `unverified`. G.O. 53 is `official` / `metadata_checked`.
- **Excluded:**
  - G.O.Ms.No. 54/2025: a draft.
  - G.O.Ms.No. 332/2008: Andhra Pradesh instrument, applicability unestablished.
  - Rules of the Road: Central, out of scope.
  - The navigation files.

## 4. Extraction quality

Loaders were run on all 17 candidate documents. Validating against the real files exposed **seven loader defects**, all now fixed with synthetic regression tests:

1. Whole HTML pages were wrapped in a layout table and came out as a single "table" (largest chunk 187,033 characters, zero rules found). Layout tables are now walked through.
2. Text mixed with block elements in one container was dropped, losing rules 79–82, 130–159 and TMVTR 1–11. That text is now kept.
3. Rules separated only by `<br>` ran together. Paragraphs are now split at `<br>`, each keeping its own `<a name>` anchor.
4. Pages declared ISO-8859-1 contain Windows-1252 dashes and ellipses (`\x96`, `\x85`). They are now decoded as cp1252.
5. Headings with no space after the number ("308.Delegation") and hyphenated insertions ("12-A.", "13-B Acceptance") weren't recognised. Both are now handled.
6. Justified PDF lines ("2. Keep Left.—… sh   all drive") were taken for table rows, losing ROR regulation 2. A table now needs two or more consecutive lines with short cells.
7. A single huge table row could exceed the chunk limit. Chunk size is now guaranteed.

Headings now stop at ":-" or ".—" only, so "Duplicate – Issue of" keeps its dash.

**Results after the fixes:**

| Document | Provisions found | Check | Chunks | Largest chunk | Tables | Page or anchor locations |
|---|---|---|---|---|---|---|
| TMVR chapters 1–12 | 498 rules (1–486 plus inserted rules such as 80A, 83A, 97A, 351A, 476A) | Matches every chapter's contents list except **rule 186** (listed, absent from the text) | 525 | 3,641 | 5 | `file#N` anchors from the page's `<a name>` |
| TMVTR 1963 | Rules 1–17 with 12A, 13A, 13B, 14A, 15A, 15B | Matches the contents list (13 appears only as 13-A/13-B) | 22 | 3,378 | 1 | anchors |
| G.O.Ms.No. 53/2025 | Preamble, para 1, Third / Sixth / Seventh Schedules, and 2 further "SCHEDULE" sections | **Needs review** (below) | 7 | 2,049 | 5 | `file#page=N`, pp. 1–5 |
| G.O.Ms.No. 54/2025 (draft, excluded) | Paragraphs 1–8 | **Needs review**: numbered reference items became paragraphs 1–7 | 10 | 3,419 | 0 | pp. 1–3 |
| G.O.Ms.No. 332/2008 (excluded) | Paragraphs 1–4 | **Needs review**: the rule 217 table comes out as loose rows | 7 | 3,596 | 8 | pp. 1–5 |
| Rules of the Road (excluded) | Regulations 1–31 | Complete | 32 | 1,373 | 0 | pp. 1–5 |

No document needs OCR: every PDF page has a text layer. Every chunk carries its hash, title, jurisdiction, provision, location and source-class metadata.

**Needs manual review before a preview index:**
1. **TMVR rule 186:** in the contents, missing from the text. Is it a source defect, or a rule that was omitted or repealed?
2. **TMVR contents vs text mismatch:** the contents list rule 375 as "'For Hire' to be painted", but the text's rule 375 is "Means of communication between passengers and driver". The text also has rules (375, 392, 420, 447, 449, 450) whose contents entries differ. Numbering needs checking against an official print.
3. **No chapter headings for TMVR/TMVTR:** chapter titles live in the separate header frames, so chunk `chapter` is empty. Location is still exact.
4. **No TMVR schedules or forms:** the snapshot contains rules only. Schedules the rules refer to (e.g. the Fourth Schedule) are absent.
5. **G.O.Ms.No. 53 tables:**
   - The tax-rate tables come out with column headers split across several lines.
   - Two extra "SCHEDULE" sections (18 and 2,012 characters) need checking against the PDF.
   - Rates should be read from the PDF, not the chunk text.
6. **G.O. paragraph structure (No. 54, No. 332):** numbered reference lists become paragraphs. Neither document is in the draft manifest.
7. **Heuristic boundaries:**
   - 21 TMVR rules were split at clause level and 8 at sub-rule level, because each is longer than 3,500 characters.
   - None was combined with another rule.
   - Splits were checked on synthetic fixtures only; a sample should be read by a person.

## 5. Missing documents

**Instruments referred to but not held:**
- G.O.Ms.No. 77/2025, 10/2026, 16/2026, 24/2026, 25/2026 and 32/2026 were retrieved on 09-11-2026; see section 7.
- **Telangana Motor Vehicles Taxation Act, 1963 (Act 5 of 1963):** text.
- **Act No. 8 of 2026:** text.
- **Telangana Gazette Extraordinary of 14-08-2025:** the print of G.O.Ms.No. 53.
- **Earlier G.O.s:**
  - G.O.Ms.No. 22/2022: earlier life-tax schedules.
  - G.O.Ms.No. 02/2014, 41/2015, 44/2015, 95/2016, 26/2017 and 52/2018: the rule 81 chain.
- **Base TMVR text:** AP G.O.Ms.No. 216 of 07-08-1989.
- **Adaptation orders:** the Andhra Pradesh Reorganisation Act, 2014 order(s) adapting the TMVR and TMVTR.
- **TMVR schedules and forms**, and an **official consolidated TMVR text with its amendment history.**
- **Compounding and enforcement:** the s.200 compounding schedule (G.O.Ms.No. 42/2020 or its successor), the 2006 compounding G.O.s 54 and 242, and penalty-point G.O.Ms.No. 26 (identity unresolved).
- **The summary's nine archived PDFs**, register gap G1.

## 6. Preview-index readiness decision

**Not ready to build yet: needs review.** The decision is not "ready" because:
- The inventory and extraction report are complete but **not yet reviewed**. Under this milestone's rule, nothing is built until they are.
- Review items 1, 2 and 5 affect what a preview index would say.

**After review, a preview-only index is technically feasible** for the 14 draft-manifest entries. That would be 554 provision chunks, built into a separate preview directory (never `chroma_telangana_db`) with `--preview-unapproved`. Every answer would be labelled unverified, and penalties stay locked.

It is **not suitable for production**:
- The core texts are unverified snapshots, one known to be outdated.
- No counsel approval exists.
- The key compounding schedule and the Taxation Act are missing.

Recommended next steps:
1. The user reviews items 1–7 of section 4.
2. ~~Download the six missing GOIR G.O.s.~~ Done 09-11-2026 (section 7).
3. If approved, build a preview index into a temporary directory and spot-check 20 answers against the source pages.

## 7. Added 09-11-2026: six GOIR G.O.s

The user downloaded these from goir.telangana.gov.in. Each is a valid PDF with a text layer, and each has been added to the draft manifest as `official` and `unverified`, with dates left null. The manifest now has 20 entries and no file errors. Nothing has been indexed.

| G.O. | Subject (from ABSTRACT) | Dated | Pages | Chunks | Extraction |
|---|---|---|---|---|---|
| Ms.77/2025 | Rule 81 TMVR amendment: final notification (follows the No. 54 draft) | 15-11-2025 | 3 | 12 | **Needs review:** each "Read" reference item becomes its own paragraph chunk (same defect as No. 54) |
| Ms.10/2026 | Commencement date of Act No. 8 of 2026 (TMVT Amendment Act) | 25-02-2026 | 1 | 1 | OK. The Act itself is still not held |
| Ms.16/2026 | Seventh Schedule TMVT Act: removes the extra 2% tax on second and further personal vehicles | 20-03-2026 | 2 | 2 | OK. The text says it is in force from 23-03-2026 |
| Ms.24/2026 | CMV Rule 167(5): authorities for disposal of challans | 01-06-2026 | 3 | 6 | **Needs review:** the order calls it a "draft Notification", yet the notification commences on gazette publication. Draft or final is unresolved |
| Ms.25/2026 | CMV Rule 167(3): electronic challans | 01-06-2026 | 2 | 1 | OK |
| Ms.32/2026 | EMES Designated Authority under CMV Rule 167A(1) | 30-06-2026 | 2 | 3 | **Needs review:** the body is mislabelled "Paragraph 167A" (taken from the rule number) |

Review points:
- **Penalties:** none of the six contains penalty amounts. No. 16 changes tax rates, which is not penalty content.
- **Superseded content:** No. 77 supersedes the draft No. 54, which stays excluded. No. 16 changes the Seventh Schedule set by No. 53, so No. 53's Seventh Schedule chunk now needs a "superseded in part" flag before any build.
- **Central rules:** Nos. 24, 25 and 32 act under the Central Motor Vehicles Rules, which are not in the corpus.
- **Gazette prints:** none of the six gazette prints has been obtained.

## 8. Targeted validation of the six G.O.s (09-11-2026)

No index was built or changed.

- **G.O. 77/2025, reference list:** fixed in `tg_ingest.segment`, G.O. documents only. The "Read the following" list is now one `References` chunk, with items 1–10 in their original order. Text after the `ORDER:` heading is an `Order` chunk, and only bare-numbered paragraphs (2, 3, 4…) become provisions. The same fix removes the spurious "167A." and "Rule 167A" provisions from G.O. 32, which are citations. The regression test is `test_go_reference_list_is_one_ordered_references_block`. No block text is lost in any of the 20 documents. G.O. 53's chunk IDs are unchanged.
- **G.O. 10/2026:** the commencement statement matches the PDF. The Government appoints 01-03-2026 as the date Act No. 8 of 2026 comes into force. The only extraction difference is "1st", which comes out as "1 st". **Dependency:** Act No. 8 of 2026 is not held, and its contents have not been inferred.
- **G.O. 16/2026:** checked against the PDF. It deletes **column No. 8 only** of the Seventh Schedule: the additional 2% on second or more personalised vehicles of up to 10 seats owned by an individual, at registration of new vehicles. Paragraph 4 puts it in force from 23-03-2026. **Narrow supersession of G.O. 53:** new flags make G.O. 53's `SEVENTH SCHEDULE` chunk and its `SCHEDULE` chunks (pages 4–5, the continuation of the Seventh Schedule table) ineligible for answers, along with G.O. 16's own Seventh Schedule chunk. G.O. 53's preamble and paragraph 1 stay eligible. Its Third and Sixth Schedules were already ineligible for extraction reasons and are **not** marked superseded.
- **G.O. 24/2026:** read in full. The draft or final question is **unresolved**:
  - **Draft indicators:** the ORDER speaks of publishing the "draft Notification", and the endorsement's gazette date is blank.
  - **Final indicators:** no objections are invited; the wording is operative and supersedes inconsistent orders; paragraph 5 commences it on gazette publication.

  `source_class` stays `official` and every chunk is flagged not answer-eligible until review. The table of 31 police districts is fully preserved.

## 9. G.O. 25 and G.O. 32 validation, and cross-checks (09-11-2026)

These are **extraction checks only**: the text and structure match the PDFs. They are not legal verification. Every document stays `unverified`. No index was built or changed.

- **G.O. 25/2026:** 3 chunks (Preamble, References, Order).
  - Words are identical to an independent `pdftotext` extraction (476 in each), and the chunks match the block stream exactly.
  - The notification has no numbered paragraphs, so a single Order chunk is correct.
  - These points were verified in the Order chunk:
    - **Power:** CMV Rule 167(3).
    - **Wording:** "with immediate effect" authorises SMS, WhatsApp and e-mail for serving challans issued under Rule 167(1) or (2).
    - **Obligation:** owners must update their mobile number and e-mail on Vahan within one month of publication.
    - **Deemed service:** after that period, service is deemed.
  - **Source quirks kept as written:** "http:/vahan.parivahan.gov.in" (one slash) and "(SMS) i.e., Whatsapp or e-mail".
  - **Dependencies, not inferred:**
    - CMV Rules 1989, Rule 167 as amended by G.S.R. 48(E) of 20-01-2026; not in the corpus.
    - The gazette print; the endorsement's gazette date is blank.
  - **Open question:** "with immediate effect" sits beside a directed gazette date of 02-06-2026, and how the two relate needs review.
  - The distribution list is included in the Order chunk.
- **G.O. 32/2026:** 10 chunks (Preamble, References, Order, Paragraphs 2–7).
  - The former "Paragraph 167A" and "Rule 167A" false provisions are gone. "167A." inside reference 4 now stays in the References chunk.
  - Paragraph 4 carries all six members (i)–(vi), and Paragraph 5 all three powers (i)–(iii).
  - Paragraphs 2–7 match the source numbering, and the chunks match the block stream exactly.
  - Words match `pdftotext` except that "co-opted" is split across a line by pypdf ("co- opted"). The wording is otherwise kept.
  - **Dependencies:** CMV Rule 167A and the Supreme Court orders in W.P.(C) 295/2012 are cited, not held.
- **Cross-checks:**
  - **G.O. 77:** one References chunk, items 1–10 in order.
  - **G.O. 10:** "appoints the 1 st day of March, 2026". The ordinal is split by extraction, and the date is correct.
  - **G.O. 16 flags:** they match only G.O. 53's `SEVENTH SCHEDULE` (1 chunk) and `SCHEDULE` (2) chunks, plus G.O. 16's `SEVENTH SCHEDULE` (1).
  - **G.O. 24:** all 8 chunks ineligible.
  - **G.O. 53:** the Third and Sixth Schedules carry only the extraction warning. The Seventh Schedule chunks carry both the extraction warning and the separate supersession warning.
  - **Source hashes:** all 20 manifest hashes match the files.
  - **Flags:** the 8 flags match 5, 1, 6, 1, 1, 2, 1 and 8 chunks respectively; none matches nothing.
  - **Chunk totals:** 586 chunks across the 20 documents, 572 of them eligible to answer. This is a dry run only; nothing was indexed.

## 10. Refreshed preview index: 20 documents (09-11-2026)

This is a preview-only build in `KnowYourRules-tg/chroma_telangana_preview` (git-ignored), made with `--preview-unapproved` and local Ollama `nomic-embed-text`. **It is not legally verified and not production-ready.**

- **Pre-build dry run:** all checks passed.
  - 20 documents; every hash matches the manifest.
  - 586 chunks: 572 eligible to answer, 14 excluded.
  - Every chunk is tagged Telangana and `unverified`.
  - G.O. 24 has all 8 chunks excluded.
  - G.O. 53's Third and Sixth Schedules carry only the extraction warning.
  - The G.O. 16 supersession flags hit exactly 4 chunks: G.O. 53's Seventh Schedule (1) and its continuation (2), and G.O. 16's Seventh Schedule (1).
- **Stored contents:** 586 chunks from 20 documents in one collection, identical in text and metadata to freshly regenerated chunks.
- **Retrieval:** 19 of 19 answer-eligible documents return their own provisions.
  - The TMVR and TMVTR queries reused provision headings, so they are an easy test.
  - The G.O. queries were natural-language questions.
  - G.O. 25 returns its single Order chunk; G.O. 32 returns its Order chunk and Paragraph 5.
- **Exclusions:** five queries aimed at G.O. 24, G.O. 53's schedules and the superseded Seventh Schedule.
  - The excluded chunks rank highly in raw similarity search: 4–6 of the top 6.
  - **None** gets past `retrieve()`, so none can enter answer context.
- **Guards:**
  - Rule 186, rules 185/186/187, rule 999 and TMVTR rule 99 all return `missing_provision`.
  - Five penalty questions, including a vague follow-up, return `restricted`.
  - Generation and retrieval were set to fail if called during these tests; 0 Groq calls were made.
- **Other indexes:** the shared index (`chroma_langchain_db`) and production index (`chroma_telangana_db`) are absent before and after, in all three checkouts. Only the preview directory changed.
