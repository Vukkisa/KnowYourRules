# KnowYourRules: Manual Legal Document Acquisition Checklist (Stage 3)

Written 2026-11-15. For a human to follow. Nothing was downloaded to produce it, and nothing here is legally approved. IDs (R01 to R25) are those in `LEGAL-DOCUMENT-ACQUISITION-PLAN.md`; read its section 3.1 for the evidence behind each row.

**Scope:** Telangana traffic rules are primary; the central legislation they depend on is supporting context. This is not an all-India product. (The repository's older "Telangana-only" records were not changed; see the accompanying report.)

**Status words:** VERIFIED = official document directly inspected; SECONDARY = supported only by secondary reporting or an unopened listing; UNRESOLVED = no authoritative confirmation. Every item below is currently **SECONDARY or UNRESOLVED** unless marked otherwise. Nothing here counts as VERIFIED until you have followed the steps, and nothing is approved by being downloaded.

## A. Rules that apply to every download

1. **Official sites only.** The sites are India Code (`indiacode.nic.in`), MoRTH (`morth.gov.in`), the Gazette of India (`egazette.gov.in`), the Telangana Transport Department (`transport.telangana.gov.in`), the Telangana Gazette (`tggazette.cgg.gov.in`) and the Telangana G.O. register (`goir.telangana.gov.in`). Use a normal desktop browser, because automated fetches get HTTP 403 from India Code.
2. **Third-party copies** (PRS, news sites, law-firm blogs, compiler sites, Kanoon, search-result links, ebook sites) are leads only. If you must keep one, save it in a separate folder named `UNVERIFIED-THIRD-PARTY` and mark it so in the log. It never replaces the official copy.
3. **Save the original file** with the filename the site gives. Do not print-to-PDF, re-save, crop, annotate, OCR or convert it; that creates a different document with a different hash. For an HTML page that is the only form offered, use the browser's "Save Page As" with "Webpage, HTML only", and say so in the log.
4. **One new empty folder per session**, for example `~/kyr-acquisition/2026-11-DD/`. Keep it outside the repository. Do not put anything in the index, registry, `legal-status`, or `snapshot-store`.
5. **Hash before opening further.** Right after saving, run in Terminal, from that folder:

```bash
shasum -a 256 "FILENAME.pdf"
```

6. **Log one row per file** (template in section J): ID, exact title, issuing authority, document number, publication date, effective date if stated, page URL, direct file URL, date and time retrieved, browser, file size in bytes, SHA-256, page count, "As on" date, and notes.
7. **Check against the list in section B** before accepting a file. If any check fails, keep the file, mark the row "REJECTED: reason", and do not use it.
8. **Gazette prints beat department copies.** If both exist, collect both and log them as separate rows.
9. **Amendments and later versions** are named per document below. Collect them as separate files; never rely on a consolidated copy alone when the amendments are available.
10. **Stop and ask** if a page asks for a login, a payment, a CAPTCHA or an "accept terms" step you aren't comfortable with, or if a file looks different from what the page said.

## B. What to verify before accepting any download

- Title matches the exact title in this checklist (not a similar one).
- Issuing authority and, for a G.O. or notification, the department, number, year and date are printed on the document.
- Gazette items show the Gazette name, Part, Section, issue number and date in the header.
- Page count is plausible and the last page is a signature block, an "As on" note or a schedule end, not a cut-off.
- It is the **final** instrument, not a draft or "preliminary" notification, unless a draft is what the row asks for.
- For a "consolidated" or "as on" copy, record the as-on date and check it against the latest amendment you know of. A consolidation older than a known amendment is incomplete.
- The URL you downloaded from is on the official domain.

## C. Priority 1: Motor Vehicles Act, 1988 and amendments

### R01. The Motor Vehicles Act, 1988 (Act 59 of 1988), current consolidated text
- **Authority:** Parliament of India; administered by MoRTH. Published by the Legislative Department on India Code.
- **Site / page:** India Code, `https://www.indiacode.nic.in/handle/123456789/1798`. A search result also lists a file at `https://www.indiacode.nic.in/bitstream/123456789/1798/1/eng.pdf` headed "As on the 21st May, 2025". Treat that as a lead; confirm on the page. MoRTH page linked by the Transport Department: `https://www.morth.nic.in/motor-vehicles-act-1988-0` (not opened).
- **Steps:** (1) Open the India Code handle page in a desktop browser. (2) Find the "View/Open" or full-text link and the "Amendments" or "Subsequent amendments" list. (3) Download the full-text PDF. (4) Note the "As on" date on its first page. (5) If the page returns 403 or an error, wait and retry later, or reach the same Act through the India Code home page search for "Motor Vehicles Act, 1988". (6) If India Code stays blocked, try the MoRTH page above, then the Act as published in the Gazette of India.
- **Verify:** Act 59 of 1988, enacted 14-10-1988; the "As on" date; that it contains the 2019 amendments (new ss.25A, 62A, 62B, 110A, 134A, 136A per secondary reports) and Chapter XIII/XIV penalties.
- **Collect also:** every amending Act (R02) and the commencement notifications (R04). Check whether the "As on" date is before or after the amendments listed on the page.
- **Status:** SECONDARY. India Code returned 403 and the page was not opened.

### R02. The Motor Vehicles (Amendment) Act, 2019 (Act 32 of 2019)
- **Authority:** Parliament; assent 09-08-2019.
- **Site / page:** India Code, `https://www.indiacode.nic.in/repealedfileopen?rfilename=A2019-32.pdf` (listed in the audit, not opened); also reachable from the amendments list on the R01 page.
- **Steps:** Open the amendments list on the R01 page; select the 2019 Act; download. Also note any amendments after 2019 shown on that list.
- **Verify:** Act number 32 of 2019; date; that it lists the substituted penalty sections.
- **Collect also:** any later Act amending the 1988 Act (R03: Jan Vishwas 2026 and Motor Vehicles (Amendment) 2025 are reported but unconfirmed; check Parliament's site for whether either was enacted).
- **Status:** SECONDARY.

### R04. Commencement notifications for the 2019 Act and later amendments
- **Authority:** MoRTH.
- **Site / page:** Gazette of India `https://egazette.gov.in`; MoRTH notifications list `https://morth.gov.in`.
- **Steps:** On e-Gazette, search "Motor Vehicles (Amendment) Act, 2019" with "commencement" and the numbers reported in secondary sources: S.O. 3110(E) of 28-08-2019 and S.O. 859(E) of 25-02-2022. Download each hit and any others that appear (the schedule is reported incomplete).
- **Verify:** MoRTH as issuer; S.O. number and date; the sections and effective dates named.
- **Status:** SECONDARY (numbers from secondary reports only).

## D. Priority 2: Central Motor Vehicles Rules, 1989 and amendments

### R05. The Central Motor Vehicles Rules, 1989, current consolidated text
- **Authority:** MoRTH, under the Motor Vehicles Act, 1988. Original G.S.R. 590(E) of 02-06-1989 (secondary).
- **Site / page:** India Code (rules file listed in the audit as `.../ViewFileUploaded?...file=cmvr-1989.pdf`, not opened); MoRTH chapter PDFs, e.g. `https://morth.nic.in/sites/default/files/CMVR-chapter1_1.pdf` (not opened). The Transport Department's "Central Motor Vehicle Rules 1989" link goes only to the MoRTH home page.
- **Steps:** (1) Look on India Code under the Motor Vehicles Act 1988 handle for "Rules". (2) Check `https://morth.gov.in/en/motor-vehicle-legislation` in a desktop browser (the page returned only a banner to an automated fetch; it may need scripts). (3) If only chapter-by-chapter PDFs are offered, download all chapters and the schedules and forms, and log them as one set. (4) Record the "As on" date. (5) If no consolidated text current to November 2026 exists, **say so in the log**; do not substitute a compiler's consolidation.
- **Verify:** title; as-on date; that Rules 167 and 167A (relied on by Telangana G.O.s 24, 25, 32 of 2026) are present in their amended form.
- **Collect also:** all amending notifications (R06).
- **Status:** UNRESOLVED. No consolidated text current to Nov 2026 was confirmed.

### R06. CMVR amending notifications, 2014 to 2026
- **Authority:** MoRTH.
- **Site / page:** `https://egazette.gov.in` (Part II, Section 3(i)); MoRTH notifications list.
- **Steps:** Search e-Gazette for each, and download the official PDF:
  - G.S.R. 48(E), 20-01-2026 (Rule 167): required by G.O.s 24 and 25 of 2026.
  - G.S.R. 417(E), 25-05-2026 ("Eighth Amendment"; effective date reported as 25-05 or 29-05-2026, a conflict to settle from the text).
  - The reported 23-10-2026 amendment (Rule 115, E100 fuel), the toll-dues amendment, the draft G.S.R. 728(E) of 10-08-2026, and a reported 2026 amendment of the **central** Rule 81 fee table.
  - Secondary sources number the 2026 amendments inconsistently (a "Seventh" and "Eighth" both appear); record the numbering printed on each gazette page, not the number from news.
  - Earlier amendments back to those cited in the audit (for example G.S.R. 152(E) of 2014, 521(E) and 808(E) of 2019, 858(E) of 2022, 721(E) of 2024) only where counsel confirms they matter.
- **Verify:** G.S.R. number, date, MoRTH as issuer, final (not draft), and the commencement clause.
- **Status:** SECONDARY.

## E. Priority 3: Telangana Motor Vehicles Rules, 1989 and the adaptation order

### R09. Telangana Motor Vehicles Rules, 1989, base instrument as gazetted
- **Authority:** Government of Andhra Pradesh, Transport, Roads and Buildings (Tr.II) Department; G.O.Ms.No. 216, 07-08-1989; AP Gazette, Rules Supplement, Part I Extraordinary, 25-08-1989 (as cited in held G.O.s 54/2025 and 77/2025).
- **Site / page:** Telangana Gazette `https://tggazette.cgg.gov.in` (archive search); Transport Department Acts and Rules listing `https://www.transport.telangana.gov.in/html/actsrules.html` (menu link, not opened).
- **Steps:** (1) Open the Transport Department listing and look for a PDF of the Rules (the held HTML chapters are a web rendering, not the gazetted text). (2) In the Telangana Gazette portal, search by year 1989 and keywords "Motor Vehicles Rules". The portal's front page listed only 2015 items to an automated visit; use its search form. (3) If neither has it, record "not found on official sites" and raise it with counsel (Plan, questions 2 and 4).
- **Verify:** G.O.Ms.No. 216 and date 07-08-1989; Gazette header; whether it is the Andhra Pradesh text.
- **Status:** SECONDARY (citation read in held G.O. text only).

### R10. Telangana adaptation of the 1989 Andhra Pradesh rules
- **Authority:** Government of Telangana (instrument not identified). Section 101 of the Andhra Pradesh Reorganisation Act, 2014 allowed adaptation within two years (secondary).
- **Site / page:** Not known. Search the Telangana Gazette and GOIR for 2014 to 2016 orders on "adaptation" of Andhra Pradesh Motor Vehicles Rules, and ask the Transport Department (Commissioner's office) in writing.
- **Steps:** (1) Search GOIR (section F steps) under Transport, Roads and Buildings, 2014 to 2016, keywords "adaptation", "Motor Vehicles Rules". (2) Search the Telangana Gazette 2014 to 2016. (3) If nothing, send the question to the Transport Department and to counsel (Plan, question 4). Record the date and reply.
- **Verify:** the order names the 1989 Rules and the date from which they apply as Telangana rules.
- **Status:** UNRESOLVED.

### R11. Telangana MV Rules: consolidated current text and all amendment orders
- **Authority:** Transport, Roads and Buildings Department.
- **Site / page:** `https://www.transport.telangana.gov.in/html/actsrules.html` (not opened); GOIR.
- **Steps:** Open the listing, note every Telangana MV Rules item, download any PDF, and log each. Compare the HTML chapters we hold (hashes in the Plan, section 3.2) with any PDF.
- **Verify:** title; amendment citations; whether it says "as amended up to".
- **Collect also:** R12, R13.
- **Status:** UNRESOLVED.

### R12. Rule 81 amendment orders 2014 to 2018
- **Authority:** TR&B Department. G.O.Ms.No. 02 (17-06-2014), 41 (29-09-2015), 44 (15-10-2015), 95 (08-12-2016), 26 (24-04-2017), 52 (11-04-2018).
- **Site / page:** GOIR (section F); Telangana Gazette.
- **Steps:** Follow section F for each number and year. Note that G.O.Ms.No. 41 of 2015 is also reported for the Rule 72-A insertion; collect it once and log both uses.
- **Verify:** department TR&B; each G.O. names Rule 81; date and number match this list.
- **Status:** SECONDARY (cited in held G.O.s only).

### R13. Reported Rule 72-A insertion
- **Authority:** TR&B Department; reportedly G.O.Ms.No. 41 of 29-09-2015.
- **Steps:** As R12. Open the G.O. and write down which rules it actually amends (72, 72-A, 81).
- **Status:** SECONDARY (blog reproductions only).

## F. Priority 4: Telangana Government Orders and Gazette prints

### GOIR search route (for R10, R12, R13, R14, R15, R19, R21 to R23)
`https://goir.telangana.gov.in` is a search form with no direct file URLs, and it returns files through a form submission.

1. Open the page in a desktop browser.
2. Choose department **Transport Roads and Buildings** (the dropdown lists it), enter the G.O. number and year (or a date range), and submit.
3. Open the result; download the PDF. If the result opens in the same page without a filename, use the browser's download control and record the name it gives.
4. Log the department, G.O.Ms.No., date and the URL the browser shows after the search. A direct URL may not exist; say so.
5. If it returns no result, try the year alone and read the list; record "not found" with the search used.

### R21. Gazette prints of the held G.O.s
- **Authority:** Telangana Gazette (Commissionerate of Printing, Stationery and Stores Purchase).
- **Site:** `https://tggazette.cgg.gov.in`
- **Steps:** Use the portal's search to find, by date, the Extraordinary issues the held G.O.s direct: **14-08-2025** (G.O. 53/2025), **15-11-2025** (G.O. 77/2025), **01-03-2026** (G.O. 10/2026), **23-03-2026** (G.O. 16/2026), **02-06-2026** (G.O.s 24 and 25/2026). G.O. 32/2026 (30-06-2026) shows no gazette direction; search around that date. Also find the **preliminary notice** for Rule 81: "Telangana Gazette No. G-575, Part I Extraordinary, 13-08-2025" (read in held G.O. 77/2025), and the G.O. 54/2025 draft notice.
- **Verify:** the Gazette entry shows the same G.O. number and text as the held copy; record the Gazette issue number, Part and publication date.
- **Collect also:** if the Gazette text differs from the held G.O., keep both and flag the differences.
- **Status:** UNRESOLVED. The portal's front page showed no traffic-law entries to an automated visit.

### R22. Final notification for G.O.Ms.No. 24/2026
- **Authority:** TR&B Department; held G.O. dated 01-06-2026 says it publishes a "draft Notification" while the notification states it takes effect on publication.
- **Steps:** Find the Gazette print (R21) and any later final notification. Record which is which.
- **Status:** UNRESOLVED.

### R14. Penalty and compounding orders under s.200, current in Telangana
- **Authority:** TR&B Department / Transport Department. G.O.Ms.No. 42 (July 2020); a possible 2020 order `21102020TRB MS21` (seen only on a third-party site: https://images.tv9telugu.com/wp-content/uploads/2020/10/21102020TRB_MS21.pdf, **UNVERIFIED third-party; do not use**); AP-era G.O.s 54/2006, 242/2006, 334/2008 (named in the briefing PDF only).
- **Site / page:** Transport Department menu "Penalties" (links seen: `.../html/pdf/prosecution-11-03-10.pdf`, not opened; `.../html/pdf/2008trb_ms332_compounding.pdf`, held); GOIR; `https://www.transport.telangana.gov.in/html/gos-and-circulars.php` (not opened).
- **Steps:** (1) Open the "Penalties", "Prosecution" and "Compounding" menu items and the G.O.s and circulars page. (2) Download every compounding or penalty order listed. (3) Search GOIR for 2020 G.O.Ms.No. 42 and for the order that matches `21102020TRB MS21` (it would be Tr. Dept G.O.Ms.No. 21 of 21-10-2020 if the filename holds, which is unconfirmed). (4) Do not assume pre-2014 AP orders apply in Telangana; collect them for counsel only.
- **Verify:** each order names section 200 (or the section it amends) and gives the offence schedule or amounts; department and date; whether it is superseded.
- **Status:** UNRESOLVED.

### R15. The penalty-point "G.O. 26" named in the briefing PDF
- **Authority:** unknown.
- **Steps:** Search GOIR for G.O.Ms.No. 26 for all years from 2014 on, TR&B; read each; compare with the briefing PDF's reference. Log what each G.O. 26 is. Do not assume it is the 2017 Rule 81 order.
- **Status:** UNRESOLVED.

### R23. Telangana notifications under ss.112 and 115 and Commissionerate orders
- **Authority:** Government of Telangana; Commissioners of Police (Hyderabad, Cyberabad, Rachakonda).
- **Steps:** Lower priority. Search GOIR and the Gazette for speed-limit and vehicle-restriction notifications; record only those counsel asks for.
- **Status:** UNRESOLVED (not investigated).

## G. Priority 5: Telangana taxation legislation and amendments

### R16. Telangana Motor Vehicles Taxation Act, 1963 (Act 5 of 1963), adapted
- **Authority:** Government of Telangana; page header reads "Finance Department Govt. of Andhra Pradesh".
- **Site / page:** `https://transport.telangana.gov.in/html/acts-rules/main-ap-mv-ta-1963.htm` (opened; content frame `.../middle-ap-mv-ta-1963.htm`, sections 1 to 19, no amendment citations). Read by a delegated agent: re-read it yourself.
- **Steps:** Open it, save the content-frame page ("HTML only"), and hash it. Search the Telangana Gazette for later amendment Acts.
- **Verify:** whether the page shows any amendments; whether the text matches a gazetted adaptation (reportedly G.O.Ms.No. 2, TR&B; secondary).
- **Status:** the page is an official page opened by the agent (VERIFIED as a page); its **currency and amendment history are UNRESOLVED**.

### R17. Telangana Motor Vehicles Taxation (Amendment) Act, 2026 (reported Act 8 of 2026)
- **Authority:** Telangana Legislature.
- **Steps:** Search the Telangana Gazette for the Act (Bill 5 of 2026 passed 02-01-2026, secondary). Confirm the Act number and enactment date in the print; the "Act 8 of 2026" number currently comes only from a third-party copy of the 1963 Act. Commencement is appointed by held G.O. 10/2026 as 01-03-2026.
- **Verify:** title; Act number; assent date; the one-time road safety cess provisions (amounts differ across news reports: use the print only).
- **Status:** SECONDARY.

### R18. Other Taxation Amendment Acts (for example a reported 2023 Act)
- **Authority:** Telangana Legislature.
- **Steps:** Search the Telangana Gazette for "Motor Vehicles Taxation (Amendment) Act" for 2014 to 2026 and download each. The 2023 Act appears only on a third-party site (UNVERIFIED).
- **Status:** UNRESOLVED.

### R19. Taxation schedule orders
- **Authority:** TR&B Department.
- **Steps:** Via GOIR: G.O.Ms.No. 22 (07-05-2022, Seventh Schedule), G.O.Ms.No. 10 (2014), the 2021 EV exemption order, and earlier Third and Sixth Schedule orders. Held already: G.O.s 53/2025 and 16/2026.
- **Status:** SECONDARY.

### R20. Taxation Rules, 1963, complete text
- **Steps:** The held snapshot was indexed for Rules 1 to 17 only. Open the Transport Department Acts and Rules page and check for the full rules and any adaptation or amendment. Log what exists.
- **Status:** UNRESOLVED (completeness).

## H. Priority 6: Central driving regulations

### R07. The Motor Vehicles (Driving) Regulations, 2017
- **Authority:** MoRTH, under section 118 of the Motor Vehicles Act, 1988. G.S.R. 634(E), 23-06-2017 (secondary).
- **Site / page:** MoRTH `https://morth.gov.in/en/motor-vehicle-legislation?page=11` (listed in a search result, not opened); India Code regulations search; `https://egazette.gov.in`.
- **Steps:** Open the MoRTH legislation page in a desktop browser, go to page 11 or use the page's search for "Driving Regulations"; download the PDF named "634(E) Motor Vehicles (Driving) Regulations, 2017". Cross-check on e-Gazette (Part II, Section 3(i), 23-06-2017).
- **Verify:** G.S.R. 634(E); 23-06-2017; the sentence stating it supersedes the Rules of the Road Regulations, 1989 (needed to close reconciliation item 6); regulation count.
- **Status:** SECONDARY.

### R08. Driving Regulations amendment G.S.R. 38(E), 15-01-2024
- **Authority:** MoRTH.
- **Steps:** Find on e-Gazette or the MoRTH list; download; confirm it amends Regulations 8(1)(g), 8(3)(b) and 15(4) (secondary). Check for any other amendments.
- **Status:** SECONDARY.

## I. Other central items

- **R24: S.O. 1306(E), 12-03-2024, registration mark "TG".** MoRTH notifications list; file name seen in a search result: `8-SO 1306(E) 12 March 2024 TG registration mark Telangana.pdf`. SECONDARY.
- **R25: Supreme Court W.P.(C) 295 of 2012** (road safety; cited in held G.O. 32/2026). Supreme Court website. Collect only if counsel says judgments are in scope. UNRESOLVED.
- **R03: Jan Vishwas (Amendment of Provisions) Bill 2026; Motor Vehicles (Amendment) Bill 2025.** Check Parliament's site for enactment status; do not collect bill text as law. UNRESOLVED.

## J. Hand-back log template

Copy one row per file. A row with a blank hash is not finished.

| Field | Entry |
|---|---|
| Plan ID (R01 …) | |
| Exact title on the document | |
| Issuing authority | |
| Number and year | |
| Gazette header (Part, Section, issue, date) | |
| Publication date / effective date | |
| "As on" date (consolidations) | |
| Page URL | |
| Direct file URL (or "form post-back, none") | |
| Retrieved (date, time, browser) | |
| File name saved | |
| Size in bytes | |
| Pages | |
| **SHA-256** (`shasum -a 256 file`) | |
| Complete, final, not draft? (yes / no, why) | |
| Official domain? (yes / no) | |
| Verified by (name), date | |
| Result: ACCEPTED-FOR-REVIEW / REJECTED (reason) / NOT FOUND (search used) | |
| Notes | |

"ACCEPTED-FOR-REVIEW" means counsel can look at it. It does not approve it, ingest it, or change any source status.
