# Motor Vehicles Act, 1988: verification report (Stage 4B)

Written 2026-11-15. Verification of the file acquired in Stage 4A (`MOTOR-VEHICLES-ACT-ACQUISITION-REPORT.md`). The original PDF was not modified. Nothing was ingested, registered, approved or committed. **This report does not say the Act is current, and nothing here is legal approval.**

**Bottom line:** the file is intact and matches the acquisition report. It is an official India Code consolidation "As on the 15th August, 2026". All 50 image-only pages are readable at the level of headings, sign names and colour labels, with the defects and ambiguities listed in section 2.3. The checksum mismatch is **UNRESOLVED at byte level**, but the evidence shows the served file has the same content as the portal's own text extract for the 15-08-2026 version, and not the earlier 21-05-2025 version. No Act enacted after 15-08-2026 appears on India Code, but the Gazette and MoRTH could not be searched properly. The PDF is suitable to send to counsel **for review, with the caveats in section 7**.

## 1. File integrity

| Check | Acquisition report | Re-measured now | Match |
|---|---|---|---|
| Path | `~/kyr-acquisition/2026-11-15/Motor_Vehicles_Act_1988_OFFICIAL_UNVERIFIED.pdf` | same, mode `-r--r--r--` | yes |
| SHA-256 | `c619755eabb2085ec5ef8068777724223f3ec7e1cc1170aee0dd1608216dc482` | `c619755eabb2085ec5ef8068777724223f3ec7e1cc1170aee0dd1608216dc482` | **yes** |
| Size | 4,329,031 bytes | 4,329,031 bytes | yes |
| Pages | 176 | 176 (`pdfinfo`) | yes |
| MD5 | `75c9538c46d802bd13c6a8a0409c831f` | same | yes |
| PDF metadata | Word 2021, created 13-10-2026 IST | same; not encrypted | yes |

All later work used a copy (`work_copy.pdf` in the scratchpad, SHA-256 prefix `c619755eabb2085ec5ef` confirmed). The hash was recomputed again at the end of the stage (section 8).

## 2. Image-only pages 122 to 171

### 2.1 Method
- Rendered all 50 pages at 130 dpi from the working copy. Each is a single embedded raster image (about 540 to 650 px wide, roughly 93 to 100 ppi), so the scans are low resolution.
- **Viewed every page image (122 to 171) individually.** The viewer displayed each at about half the rendered size, so small dimension text was legible but not at print quality.
- Ran OCR on the working copy only: macOS Vision (`VNRecognizeTextRequest`, accurate mode, no language correction), run locally. OCR output was compared with what I saw on each page. OCR output is a working aid and **is not legal text**.

### 2.2 Page-by-page results

Part A is mandatory (regulatory) signs M3 to M36; Part B is cautionary signs C1 to C37; Part C is informatory signs E1 to E21 (the portal's page headings say "Cautionary signs of Schedule of the Motor Vehicles Act 1988" on p.139 and "Informatory signs…" on p.161). "Readable" means the title, sign picture, colour labels and size labels could be read on screen.

| Page | Content seen | Readable | Notes |
|---|---|---|---|
| 122 | M3 straight prohibited or no entry; M4A one way (prohibited, one direction) | Yes | |
| 123 | M4B one way; M5 vehicles prohibited both directions | Yes | |
| 124 | M6 all motor vehicles prohibited; M7 trucks prohibited | Yes | M7 carries a small Devanagari caption; faint at this resolution |
| 125 | M8 bullock carts and hand carts; M9 bullock carts | Yes | |
| 126 | M10 tongas; M11 hand carts | Yes | |
| 127 | M12 cycle; M13 pedestrians | Yes | |
| 128 | M14 right turn; M15 left turn | Yes | |
| 129 | M16 U-turn; M17 overtaking | Yes | |
| 130 | M18 horns; M19 no parking, with a definition-plate note | Yes | |
| 131 | M20 no stopping or standing; M21 speed limit "50" | Yes | **Bottom note breaks off mid-sentence ("…this may be specified on a") and p.132 starts a new sign with no continuation** |
| 132 | M22 width limit (2 m); M23 height limit (3.5 m) | Yes | See the note on p.131 |
| 133 | M24 length limit (10 m); M25 load limit (5 T); M26 axle load limit (4 T) | Yes | |
| 134 | M27 restriction ends; M28 compulsory turn left | Yes | |
| 135 | M29 compulsory ahead; M30 compulsory turn right | Yes | |
| 136 | M31 ahead or turn right; M32 ahead or turn left | Yes | |
| 137 | M33 keep left; M34 cycle track; M35 sound horn | Yes | |
| 138 | M36 compulsory bus stop | Yes | Only sign on the page |
| 139 | "Cautionary signs" header; C1 general design; C2 right hand curve | Yes | |
| 140 | C3 left hand curve; C4 right hairpin bend | Yes | |
| 141 | C5 left hairpin bend; C6 right reverse bend | Yes | |
| 142 | C7 left reverse bend; C8 steep ascent | Yes | |
| 143 | C9 steep descent; C10 narrow road ahead | Yes | |
| 144 | C11 road widens ahead; C12 narrow bridge | Yes | |
| 145 | C13 slippery road; C14 loose gravel | Yes | |
| 146 | C15 cycle crossing; C16 pedestrian crossing | Yes | |
| 147 | C17 school ahead; C18 men at work | Yes | |
| 148 | C19 cattle; C20 falling rocks | Yes | |
| 149 | C21 ferry; C22 cross road | Yes | |
| 150 | C23 gap in median; C24 side road right | Yes | Thin vertical scan line at the left edge |
| 151 | C25 side road left; C26A Y-intersection | Yes | |
| 152 | C26B and C26C Y-intersections | Yes | |
| 153 | C27 T-intersection; C28A staggered intersection | Yes | Thin vertical scan line at the left edge |
| 154 | C28B staggered intersection; C29A major road ahead | Yes | |
| 155 | C29B major road ahead; C30 roundabout | Yes | **Same content as p.156** |
| 156 | C29B major road ahead; C30 roundabout | Yes | **Duplicate of p.155 content.** Different embedded images (p.155 a 551x779 JPEG, p.156 a 539x722 PNG), so the source repeats the page |
| 157 | C31 dangerous dip; C32 hump or rough road | Yes | |
| 158 | C33 barrier ahead, with a note | Yes | |
| 159 | C34 unguarded level crossing (200 m); C35 (50 to 100 m) | Yes | Small dimension captions and notes are soft |
| 160 | C36 guarded level crossing (200 m); C37 (50 to 100 m) | Yes | Small captions are soft |
| 161 | "Informatory signs" header and "Part C"; E1 advance direction sign; E2 destination sign | Yes | |
| 162 | E3 direction sign; E4 re-assurance sign | Yes | |
| 163 | E5 place identification sign | Yes | |
| 164 | E6 public telephone; E7 petrol pump | Partly | **E7 caption and note are degraded and partly illegible**; E6 is legible |
| 165 | E8 hospital; E9 first-aid post | Yes | **E8 note is clipped at the right margin** ("…DISTANCE TO THE FACILIT…") |
| 166 | E10 eating place; E11 light refreshment | Yes | E11 note is cut off at the right margin |
| 167 | E12 resting place; E13 no through road | Yes | |
| 168 | E14 no through side road; E15 park this side | Yes | |
| 169 | E16 parking both sides; E17 parking lot, scooters and motor cycles | Yes | |
| 170 | E18 parking lot, cycles; E19 parking lot, taxis | Yes | E18 has a small Devanagari caption, faint; E19 heading has a scan smudge over its number |
| 171 | E20 parking lot, auto rickshaws; E21 parking lot, cycle rickshaws | Yes | |

On every page a diagonal "IndiaCode" watermark crosses the image. It does not hide the content. Printed page numbers (OCR of the footer) match the PDF page number on all 50 pages.

### 2.3 Unreadable or ambiguous content (summary)

1. **Truncated note, p.131:** a sentence about speed-limit signs for particular vehicle classes ends mid-sentence ("…specified on a"); p.132 does not continue it. Possible truncation in the source scan. Not established.
2. **Duplicate page content, pp.155 and 156.**
3. **Sign numbers M1 and M2 do not appear** on any of the 50 pages (the series starts at M3). I cannot tell from this file whether M1 and M2 were intentionally absent, were on p.121 (a text page, which I read only as a heading), or are missing. UNRESOLVED.
4. **Degraded or clipped captions:** p.164 (E7), p.165 (E8 note), p.166 (E11 note).
5. **Small text:** dimensions such as "NORMAL SIZE 65 mm" are legible on most pages but I did not check each measurement. Do not take measurements from OCR (section 3).
6. **Devanagari captions** (pp.124, 170) are faint, and the OCR was run in Latin mode only.

## 3. OCR quality and limits

- **Heading recovery is poor.** Of the 99 sign headings I read visually, OCR returned the exact sign code for **48** (about 49%). The misses are typical character confusions: "1" read as "I" (M10 → "MIO", M12 → "MI2", M14 → "MI4"), "8" read as "B" (M8 → "MB"), "2" read as "E" (M22 → "M2E", C26B → "C268"), and "4A/4B" read as "AA/AB".
- **Digits are unreliable:** dimension text came out as "40 CM" → "A0 CM", "GE CM"; "60mm" → "6O mm"; "1988" → "1088".
- **The OCR's own confidence is useless** (it printed 1.00 for wrongly read strings), so it cannot be used to filter output.
- **Page-number footers:** recovered on 50 of 50 pages.
- **Not covered:** Devanagari text, sign pictures and symbols (OCR reads only text), and colour information.
- **Use:** the OCR output (kept only in the scratchpad, outside the repository) is for locating text, not for legal use. These pages are a schedule of picture signs; any use of their specifications needs the images or a verified source.
- **Text pages (1 to 121 and 172 to 176):** these have a text layer (not OCR). I did not proofread it. I did check it against the portal's own text extract (section 4).

## 4. Checksum discrepancy

### 4.1 What was compared

| Item | Portal metadata record (read via India Code API before download) | File actually served and saved |
|---|---|---|
| Label | `A1988-59.pdf` (bitstream `031fe0a8-b3a6-4da2-b130-ec2e870fe4f2`) | same label and same URL |
| Size | **3,862,302 bytes** | **4,329,031 bytes** |
| MD5 | **`592f31dfd3de2e35768318311dca0697`** | **`75c9538c46d802bd13c6a8a0409c831f`** |
| SHA-256 | not recorded by the portal | `c619755eabb2085ec5ef8068777724223f3ec7e1cc1170aee0dd1608216dc482` |
| Dates | item first accessioned 20-08-2026 | PDF created 13-10-2026; server `last-modified` 21-10-2026 13:39:01 GMT |

The file the portal served through the browser pane has the same length and the same SHA-256 as my copy, so my copy is what India Code serves.

### 4.2 New evidence: the portal holds two text extracts of this file

Re-reading the item's bundles on the India Code API showed:
- **ORIGINAL bundle:** `Hh198859.pdf` (7,805,110 bytes, MD5 `4642b699735d77c93652b21ae71cbeb5`; presumably the legislative-history file) and `A1988-59.pdf` (the file above).
- **TEXT bundle:** two text extracts of the Act:
  - `aA1988-59.pdf.txt`, last modified **24-08-2026**: heading "[**As on the 21st May, 2025**]"; its amending-Acts list ends at Act 18 of 2023; it contains no "8 of 2026".
  - `A1988-59.pdf.txt`, last modified **12-09-2026**: heading "[**As on the 15th August, 2026**]"; its list includes the Jan Vishwas Act 2026 (8 of 2026).

So the portal text index had a 21-05-2025 version and later a 15-08-2026 version. The 21-05-2025 date matches the `eng.pdf` result found by search in Stage 2.

### 4.3 Content comparison

I compared the served PDF's text (`pdftotext`) with the portal's 12-09-2026 text extract by counting amendment tokens:

| Token | Served PDF | Portal 12-Sep text | Portal 24-Aug (2025) text |
|---|---|---|---|
| "w.e.f. dd-mm-yyyy" occurrences | 316 (16 distinct) | 316 (16 distinct), per-date counts identical | 278 (14 distinct) |
| "Act N of YYYY" citations | 262 (31 distinct) | 262 (31 distinct) | 196 (29 distinct) |
| "8 of 2026" | 48 | 48 | 0 |
| "32 of 2019" | 105 | 105 | 85 |
| "[Omitted]" | 18 | 18 | 18 |

### 4.4 Finding

- **Content:** the served PDF matches the portal's 15-08-2026 text and not the 21-05-2025 text. That is **supported** by the comparison above. It is a count comparison, not a word-for-word diff.
- **Why the stored size and MD5 differ:** the stored record does not describe the file now served. The evidence is consistent with the portal replacing or regenerating the PDF after the checksum was stored (the PDF was created 13-10-2026 and the server's last-modified is 21-10-2026, both later than the record's 20-08-2026 accession and later than the 12-09 text extract). It is not established which of these happened, whether the stored values belonged to an earlier 15-08-2026 build or to the 2025 file, or whether the checksum field is simply stale. I cannot obtain the file the stored MD5 describes.
- **Status: UNRESOLVED at byte level.** I found no sign of tampering and no proof against it. The portal's operator (NIC / Legislative Department) could confirm a replacement date. Re-downloading later and comparing the SHA-256 would show whether the served bytes change again.

## 5. Amendments published 15-08-2026 to 15-11-2026

"Opened" means I opened the page and read it; search-result snippets are not counted as verification.

| Finding | Source | Opened? | Result |
|---|---|---|---|
| **Acts on India Code, newest first by enactment date** | India Code Acts list (848 Acts) | **Yes** | Newest enactment is the Kerala (Alteration of Name) Act, 2026 (Act 18 of 2026), 14-08-2026. Next: Tribunals Reforms Act, 2026 (17 of 2026), 13-08-2026; Bankers' Books Evidence Act, 2026 (15 of 2026), 13-08-2026. **No Act with an enactment date from 15-08-2026 to 15-11-2026 appears.** The list may lag, and I did not check whether the three August Acts touch the Motor Vehicles Act (it is not in the Act's own list of amending Acts) |
| **The Jan Vishwas (Amendment of Provisions) Act, 2026 (8 of 2026)** | The served PDF (footnotes) | Yes | Provisions touching the Act are shown "w.e.f. 15-08-2026" and the PDF's own date is 15-08-2026. So this amendment is **in** the document, not after it. India Code holds amendment records for it, which I did not open |
| Commencement notification for the Act 8 of 2026 provisions relating to the Motor Vehicles Act (Schedule serial 51), appointing 15-08-2026 | Search results (simpliance.in and similar) | **No** | Consistent with the PDF's footnotes, but SECONDARY only |
| MoRTH notification adding AIS-100 (Rev. 1) under ss.109(3) and 110(1)(k), dated 19-10-2026, gazette 21-10-2026 | Search results only | No | This is subordinate legislation, not an amendment of the Act. SECONDARY |
| Central Motor Vehicles Rules amendment reported 23-10-2026 (Rule 115) | Search results only | No | Subordinate legislation. SECONDARY |
| **e-Gazette** | `https://egazette.gov.in` home page and "Recent Gazettes: Bill and Act" list | Yes (home and recent-uploads pages only) | The recent lists mostly show railway land notices. The home page's recent Extraordinary list had MoRTH items dated 14-11-2026 ("user fee notification…", "notification under Section 3A…"); the subjects are truncated and I did not open them. I did not run a keyword and date-range search, and a manually guessed search URL returned an error page. No Motor Vehicles Act amendment was seen |
| **MoRTH legislation page** | `https://morth.gov.in/en/motor-vehicle-legislation` | Loaded, but **blank** | The page is a script-rendered app and it failed in the browser pane (a JavaScript error), so no list could be read. India Code's MoRTH notification entries lag (the newest in my search was from 2022) |

**Conclusion:** I found **no official amendment to the Act dated 15-08-2026 to 15-11-2026**. That is an absence of evidence from sources that could not be searched thoroughly, not a finding that none exists. The Gazette search and the MoRTH page still need a person with a working browser session.

## 6. Unresolved issues

1. **Checksum mismatch**: cause UNRESOLVED (section 4).
2. **Currency after 15-08-2026**: not established; Gazette and MoRTH not searched properly.
3. **Page 131 truncated note**, **duplicate pages 155 and 156**, **M1 and M2 absent**: need comparison with another official copy (for example the earlier 21-05-2025 file, or the Gazette original).
4. **Degraded captions** on pp.164 to 166.
5. **Text pages 1 to 121 and 172 to 176 not proofread.**
6. **Texts of the seven amending Acts** and the **2019 Act commencement notifications** not obtained (carried over from the acquisition report).
7. **2019 Act enactment date**: India Code says 30-08-2019; earlier secondary notes said 09-08-2019.
8. **Same number, different Acts:** Jan Vishwas Act 8 of 2026 (central) and the reported Telangana taxation amendment "Act 8 of 2026": keep them apart.

## 7. Suitable to send to legal counsel?

**Yes, as an official-source copy for review, with these conditions stated in the cover note:**
- It is the India Code consolidation as on 15-08-2026, not a statement of current law.
- The checksum record disagrees with the served file (section 4); a re-download and hash comparison should be repeated before reliance.
- The defects and ambiguities in the road-sign schedule (section 2.3) lie outside the penalty and licensing sections, but counsel should know about them.
- Nothing in the file has been proofread against the Gazette, and no OCR or text extract is to be used as legal text.

**Not suitable for ingestion, indexing or approval.** No claim is made that the Act is current or approved.

## 8. What was done

- Original PDF unchanged: its SHA-256 and mode were re-checked at the end of the stage.
- New files: this report only. Scratch outputs (rendered pages, trimmed copies, OCR text, a Swift OCR helper, comparison scripts) are in the session scratchpad outside the repository. The acquisition folder holds only the original PDF.
- No change to the index, registry, status, quarantine, approvals, keys or code. No commit, push or deployment.
- Read-only India Code API calls and page views were made through the browser pane; the e-Gazette and MoRTH sites were opened without submitting any form.

## 9. Second pass: post-15-08-2026 amendments and notifications (dated 2026-11-15)

Sections 1 to 8 above are unchanged. This section adds a second search of the same window, 15-08-2026 to 15-11-2026, plus a separate check of subordinate legislation. Where it differs from section 5, this section is later and more complete (section 9.6 lists the differences).

**Bottom line.** I found **no Act, ordinance, corrigendum or notification dated 15-08-2026 to 15-11-2026 that amends the text of the Motor Vehicles Act, 1988**, in the sources I could search. I do **not** conclude that none exists (section 9.4). I did find and open **one Gazette notification under the Act in the window** (the National Road Safety Council, section 9.2 B), **one final amendment to the Central Motor Vehicles Rules (CMVR)** (G.S.R. 911(E)), and **several drafts**, none of them final. I also confirmed from the Gazette the commencement notification behind the PDF's "w.e.f. 15-08-2026" footnotes.

"Opened" below means I fetched the document and read its text (or, for scans, the pages). Search-result snippets and third-party sites are not counted.

### 9.1 What was checked

| Source | What I did | Result |
|---|---|---|
| India Code, the Act's own record | Re-read the item and file records through the portal's read-only API (`https://indiacode.gov.in/server/api/core/items/2bbbcc40-38f1-4b15-ae94-646b85db4ee7`). Re-downloaded the PDF | **Served file unchanged since my first download:** same 4,329,031 bytes, same SHA-256 `c619755e…dc482`. The portal's stored checksum for the file still says 3,862,302 bytes / MD5 `592f31df…`, so the section 4 mismatch persists. The item record shows `lastModified` 2026-11-13. A second file sits in the same bundle: `Hh198859.pdf`, 7,805,110 bytes, MD5 `4642b699…` (not downloaded, language and content unknown) |
| India Code, records linked to the Act | Listed all 581 linked records (257 sections, 226 notifications, 94 rules, 2 schedules, 1 regulation, the Act) | **No record carries an enactment or notification date after 05-05-2022 in the notification and rule groups.** So India Code's linked subordinate-legislation list stops in 2022 and is **no evidence either way** for 2026. 54 records have a `lastModified` after 15-08-2026 (51 sections on 2026-10-12, 2 schedules on 2026-10-19, the Act on 2026-11-13). I could not tell whether those edits changed any text. The 2026-10-12 date is one day before the PDF's creation date (13-10-2026); that is an observation, not an explanation |
| India Code, Acts of 2026 | Searched the Acts collection for titles with "2026" (34 records) and probed Central Act numbers 18 to 22 of 2026 | Latest Central Acts present: Kerala (Alteration of Name) Act, 2026 (18 of 2026), 14-08-2026; Tribunals Reforms Act, 2026 and Bankers' Books Evidence Act, 2026, both 13-08-2026. **Central Act numbers 19 to 22 of 2026: no record** (the probe found number 18, so it works). Three amendment-type records have no stated enactment date (Industrial Relations Code (Amendment) Act, 2026; Transgender Persons (Protection of Rights) Amendment Act, 2026; Public Examinations (Prevention of Unfair Means) Amendment Act, 2026). Their titles do not concern motor vehicles and I did not open them. A date-range query returned zero even for a positive control, so I did not rely on it |
| MoRTH website (`https://morth.gov.in`) | The site now loads. In the browser pane I opened **Documents > Notifications/Gazette Notifications** (911 documents). I then read the JSON the page itself loads (`https://morth.gov.in/backend/api/gazettes-notifications`, `acts-and-rules`, `orders-and-notices`) | The "Motor Vehicle Legislation" group holds 583 files. Its entries dated since 2026-06-01 are in section 9.2. The Acts-and-Rules page does not host a consolidated Act; every "Motor Vehicles Act" entry links to the India Code page. Orders-and-notices entries since 15-08-2026 were read by title (about 45): none concerns the Act, apart from the 06-11-2026 Rent-A-Cab memorandum below |
| e-Gazette (`https://egazette.gov.in`) | Opened the home page, its Search menu and the Search-by-Ministry form. Fetched the Gazette PDFs by their Gazette IDs (`https://egazette.gov.in/WriteReadData/2026/<number>.pdf`) | **Gazette copies obtained for every in-window or relevant notification below that has an ID.** For 10 of them the MoRTH copy is **byte-identical** to the e-Gazette copy (same SHA-256). Two e-Gazette copies (S.O. 5745(E) and a 14-11-2026 item) have no MoRTH PDF to compare. For G.S.R. 911(E), the MoRTH file has an extra explanatory-note page and the Gazette pages' text matches the e-Gazette copy exactly. I did **not** run a ministry, date or keyword search (section 9.4) |

### 9.2 Confirmed findings

Hashes are SHA-256, first 16 characters; the files are in the session scratchpad, not in the repository (section 9.7). "Gazette" lines give the Gazette number and issue date from the page header. I did not validate the digital signatures on the PDFs.

**A. Amendment of the Act's text**

| Item | Finding |
|---|---|
| Acts or ordinances amending the Act, enacted 15-08-2026 to 15-11-2026 | **None found** on India Code (incomplete, section 9.4) or on MoRTH |

**B. Notifications issued under the Act**

| Instrument | Number and dates | Affected provision | Status and source |
|---|---|---|---|
| **Commencement of Jan Vishwas (Amendment of Provisions) Act, 2026 (8 of 2026), serial 51 of its Schedule (the Motor Vehicles Act)** | **S.O. 4100(E)**, dated 24-07-2026. Gazette Part II, s.3(ii), No. 3930, 24-07-2026 (ID CG-DL-E-25072026-274798). Appoints **15-08-2026** | The Act 8 of 2026 amendments to the Motor Vehicles Act, 1988 | **Confirmed.** Opened on MoRTH and e-Gazette (identical files, `4174e3ed2f696d53`). It **predates** the window but fixes the effective date the PDF's footnotes cite. The PDF has 17 footnotes saying "Act 8 of 2026 … (w.e.f. 15-08-2026)", consistent with this notification. I did not check each footnote against Act 8 of 2026 itself, which I did not obtain. MoRTH `https://morth.gov.in/backend/documents/uploaded/S%20O%204100%20dated%2024072026.pdf`; Gazette `https://egazette.gov.in/WriteReadData/2026/274798.pdf` |
| **National Road Safety Council constituted** | **S.O. 5745(E)**, dated 21-10-2026. Gazette Part II, s.3(ii), No. 5528, 22-10-2026 (ID CG-DL-E-23102026-277361). Effective on issue, as far as the text shows | Section 215 (the Council). Supersedes the resolution of 07-08-2023 (F. No. RT-25014/1/2015-RS) except for things done under it | **Confirmed, in the window.** The e-Gazette PDF's text layer drops digits, so I read the number, date and section from the rendered page. The MoRTH file is a Word document (`a33e0888b483663c`) with the member table, not the Gazette PDF. It does not change the Act's text. I have not recorded the members' personal details |

**C. Subordinate legislation (separate from the Act)**

| Instrument | Number and dates | Rules affected, enabling sections | Status and source |
|---|---|---|---|
| **CMVR, final: flex-fuel vehicles (E85/E100)** | **G.S.R. 911(E)**, dated 23-10-2026. Gazette Part II, s.3(i), No. 840, 23-10-2026 (ID CG-DL-E-26102026-277423). F. No. RT-11028/06/2025-MVL. Comes into force on publication in the Gazette (rule 1(2), "save as otherwise provided") | CMVR rules **115 and 115E** (emission-related tables and notes). Made under s.110. Finalises draft G.S.R. 313(E) of 27-04-2026 | **Confirmed final.** Opened. MoRTH file `d524f824687ad30f`; e-Gazette file `8d4d54644715…` (differs only by the explanatory-note page; Gazette text identical). Gazette `https://egazette.gov.in/WriteReadData/2026/277423.pdf` |
| CMVR, **draft**: licence forms and documents | **G.S.R. 902(E)**, dated 16-10-2026. Gazette Part II, s.3(i), No. 831, 21-10-2026 (ID CG-DL-E-21102026-277305). 30-day objection period from 21-10-2026 | Substitutes rule 4; omits rule 6; amends rules 11, 14, 16, 17A, 32 and 81 (serial 7); inserts a rule after 16; amends Forms 1A, 2, 3, 4A and others. Under ss.27 (several clauses), 139(1)(a) and 211A | **Draft only, not in force.** Opened in full structure, not every word (51 pages, Hindi and English). `6e140875be49e4eb` |
| CMVR, **draft**: vehicle standards | **G.S.R. 760(E)**, dated 21-08-2026. Gazette No. 694, 25-08-2026 (ID CG-DL-E-27082026-275815) | Section 110. Described by MoRTH as a "draft STREE notification" | **Draft only.** Opened (4 pages). `280ec1892acedccd`. MoRTH lists it twice; both files are identical |
| CMVR, **draft**: headlight glare | **G.S.R. 736(E)**, dated 13-08-2026. Gazette No. 670, 17-08-2026 (ID CG-DL-E-19082026-275578) | Section 110 | **Draft only.** Dated before the window; the Gazette copy was issued inside it. `3e65c4024684e0c6` |
| CMVR, **draft** | **G.S.R. 728(E)**, dated 10-08-2026. Gazette No. 664, 13-08-2026 (ID CG-DL-E-17082026-275517) | Sections 39, 64 (several clauses), 88(14)(a), 211 | **Draft only.** Dated before the window. `788b493278b90879` |
| All India Tourist Vehicles (Permit) Rules, 2023, **draft** | **G.S.R. 729(E)**, dated 10-08-2026. Gazette No. 665, 13-08-2026 (ID CG-DL-E-17082026-275518) | Section 88(14) read with 88(9) | **Draft only.** Dated before the window. `6df3b6cf311d0f5d` |
| CMVR, **draft** (before the window) | **G.S.R. 649(E)**, 21-07-2026 (Gazette No. 590, 22-07-2026, ID CG-DL-E-24072026-274771); **G.S.R. 643(E)**, 17-07-2026 (Gazette No. 584, 20-07-2026, ID CG-DL-E-21072026-274675) | 649: proviso to s.39 and s.64(k), (p). 643: ss.19(1)(f), 27(n), 110(1)(g), (m), 137(d), 157(2), 164C, 210C, 211A, 215C, among others. MoRTH describes 643 as giving effect to amendments made in the Motor Vehicles Act | **Drafts only.** Outside the window; recorded because **final versions might fall inside it** (section 9.5). `cfeed3b0e4392037`, `33e7b9b177dd2905` |
| Memorandum: draft **Rent-A-Cab Scheme, 2026**, superseding the 1989 Scheme | Office Memorandum No. RT-11014/01/2026-MVL, **06-11-2026**. Comments by **05-12-2026**. Under s.75 | Section 75 scheme (not the Act's text) | **Draft, comment stage only.** Opened the memorandum (22-page scan, `9b4d83390deec542`; the draft scheme's pages were not read in full). **MoRTH lists this item with the wrong file:** the "Motor Vehicle Legislation" row for 06-11-2026 links an 81-page letter dated 28-10-2025 (SOP for electronic enforcement, rule 167A CMVR, s.136A), not the Rent-A-Cab draft. The correct file is on the home page and in the Orders-and-notices list |
| Memorandum: draft revised **Automotive Light Standards** | O.M. listed 20-08-2026; comments by 18-09-2026 | Not stated in what I read | **Draft, comment stage only.** One page opened and read by OCR text (the date in the OCR is unclear, so I rely on MoRTH's listing date). The enclosed draft notification was not read. `b57d576403bfc912` |

**Not relevant, opened or read:** S.O. 3568(E) of 29-06-2026 (Gazette 01-07-2026) fixes 15-07-2026 for Act 8 of 2026 provisions about a **different** Act, the Control of National Highways (Land and Traffic) Act, 2002, serial 56 (`f557c986bf16b641`). Of the 14-11-2026 items on the e-Gazette home page, I opened one (ID 277924; S.O. 6176(E), under the National Highways Authority of India Act). The two whose subject lines cite "Section 3A" (IDs 277921 and 277922) I did not open; by subject they look like National Highways Act matters, which is an inference. G.S.R. 917 (26-10-2026, National Highways fee rules) is not under this Act and was not opened. G.S.R. 382(E) of 14-05-2026 (road ambulances, draft) was fetched by mistake and is before the window.

### 9.3 What these findings do and do not show about the PDF

- The PDF's "w.e.f. 15-08-2026" footnotes are now **supported by a primary Gazette notification** (S.O. 4100(E)), not only by secondary summaries.
- **Nothing found changes the Act's text after 15-08-2026.** Notifications in the window act under the Act (s.215, s.110, s.212) and do not amend it.
- S.O. 4100(E) refers to **serial 51 of the Schedule** to Act 8 of 2026. I did not obtain Act 8 of 2026, so I cannot say whether it also has MV-Act provisions with a different commencement (for example a part not covered by that serial).
- The consolidated PDF is **not** a statement of current law. The CMVR changes above sit in the Rules, not in the PDF.

### 9.4 Incomplete searches

1. **e-Gazette ministry, date and keyword search: not run.** I opened the Search page, reached the Search-by-Ministry form and selected the Ministry of Road Transport and Highways in the drop-down. The browser pane then refused the next click on the page ("This site is not approved for tool access"). I did not work around that, and no results page was produced. The e-Gazette's "Recent Uploads" page returned an error to a plain request. So **the Gazette was checked only by fetching IDs found on MoRTH, plus the home page's recent list**, which covers only the last few days.
2. **MoRTH lists only what MoRTH uploaded.** Its list can omit Gazette notifications, and one entry already points to the wrong file. Its search box did not filter when I called the API with a search term (the same list came back), so I read the full lists instead.
3. **India Code's linked notification list stops in 2022** (section 9.1), and its date-range search was unreliable. So **India Code cannot show a notification issued after 2022 under this Act**.
4. **Corrigenda:** no corrigendum search was possible. I saw none in the MoRTH lists.
5. **Commencement notifications for the 2019 Act and for the earlier amending Acts:** not searched in this pass.
6. **State notifications** (for example Telangana's under s.200) are outside this check.

### 9.5 Unresolved leads

| Lead | Why it matters | Next step |
|---|---|---|
| Final versions of drafts G.S.R. 643(E), 649(E), 728(E), 736(E), 760(E), 902(E) | A final CMVR amendment may be issued inside or after the window | Gazette search by Ministry and date, or MoRTH monthly re-check |
| "AIS-100 (Rev. 1)" notification, reported 19-10-2026, Gazette 21-10-2026 (from section 5, search-result only) | Subordinate legislation under ss.109(3) and 110(1)(k) | **Not found** in any MoRTH list I read. Unopened and **SECONDARY only** |
| Act 8 of 2026 text and Gazette print | To check each of the PDF's 17 footnotes | Obtain the Act from India Code or the Gazette |
| `Hh198859.pdf` (7,805,110 bytes) in the Act's India Code record | Might be a second language version or a different consolidation | Fetch and read, on instruction |
| The 54 India Code records modified after 15-08-2026 | Might reflect text changes | Compare section text with the PDF, on instruction |
| MoRTH 06-11-2026 listing points to the wrong file | Shows MoRTH's list can be wrong | Mention to MoRTH if relied on |

### 9.6 Differences from section 5

- Section 5 said the MoRTH page rendered blank. **It now loads**, and its data can be read.
- Section 5 listed the commencement notification (Schedule serial 51) as search-result only. It is now **opened and confirmed** (S.O. 4100(E)).
- Section 5 listed a "CMVR amendment reported 23-10-2026 (Rule 115)" as search-result only. It is now **opened and confirmed** as G.S.R. 911(E), which amends rules 115 and 115E.
- Section 5 said the e-Gazette recent lists were seen but not opened. One of the 14-11-2026 MoRTH items is now opened and is a National Highways matter; two others (IDs 277921, 277922) are still unopened.
- The India Code finding in section 5 is unchanged (no Act after 14-08-2026) and now has a positive-control check (Act 18 of 2026 found; 19 to 22 not found).

### 9.7 Files fetched, files changed

- **Fetched for reading:** 16 files from MoRTH (15 PDFs and 1 Word file, including the same G.S.R. 760(E) file twice) and 13 Gazette PDFs from e-Gazette (IDs 272755, 273984, 274675, 274771, 274798, 275517, 275518, 275578, 275815, 277305, 277361, 277423, 277924). Gazette IDs 277921 and 277922 were only seen on the home page. Fetched files, extracts and the India Code JSON answers are in `/private/tmp/claude-501/-Users-vj-Downloads-KnowYourRules-repo/626eb518-0a64-43ba-a91e-e5f904c6beec/scratchpad/v4c/`, outside the repository. None was placed in the acquisition folder, ingested or registered.
- **Original PDF:** unchanged. Re-hashed at the start of this pass (`c619755e…dc482`) and the re-download matched it.
- **Changed in the repository:** this report only (section 9 appended; sections 1 to 8 not edited).
- **Not changed:** the index, ChromaDB, the source registry, approvals, quarantine, keys, application code. No commit, push or deployment.

## 10. Jan Vishwas Act 2026: check of the footnotes against the Act (dated 2026-11-16)

Sections 1 to 9 above are unchanged. This section tests whether the consolidation labelled "As on the 15th August, 2026" correctly reflects the Motor Vehicles Act amendments made by the Jan Vishwas (Amendment of Provisions) Act, 2026 (Act 8 of 2026). It stays on that one question and is not a wider search.

**Bottom line**
- **The official Gazette text of Act 8 of 2026 was obtained** and read.
- **All 17 references you asked about are VERIFIED:** amendment wording and consolidated wording match, and S.O. 4100(E) supports 15-08-2026 for each.
- **"17" is an undercount.** The PDF has **57** footnote lines citing Act 8 of 2026 with a 15-08-2026 date: 17 written "15-08-2026" and **40 written "15-8-2026"**. My earlier count (section 9.3 and a search used in section 9) matched only the first format. I checked all 57.
- **56 of the 57 are VERIFIED. One is INCORRECT:** the marginal heading of section 210A reads "fine or penalties" in the PDF, but the Act inserts "fines or". It is a one-letter difference, but it is a demonstrable mismatch.
- **One further difference has no Act 8 of 2026 source:** section 132(1)(b) lost the word "or" between the 21-05-2025 and 15-08-2026 consolidations (section 10.6, D2). It is not one of the 57 references, so it is reported separately and left UNRESOLVED.
- This does not make the Act current or approved, and it does not change section 7: the PDF remains a copy for counsel's review, not for ingestion.

### 10.1 Official source for Act 8 of 2026

| Item | Value |
|---|---|
| Title and number | The Jan Vishwas (Amendment of Provisions) Act, 2026, **No. 8 of 2026**; Bill No. 104-F of 2026, "as passed by the Houses of Parliament" |
| Dates | Assent **07-04-2026**; published **08-04-2026** by the Ministry of Law and Justice (Legislative Department), Gazette of India Extraordinary, Part II, Section 1, No. 13 |
| e-Gazette ID | CG-DL-E-08042026-271642 |
| Official URL | `https://egazette.gov.in/WriteReadData/2026/271642.pdf` |
| File | 186 pages, A4, **1,985,125 bytes**, created 08-04-2026 (iTextSharp) |
| **SHA-256** | `d38327aac56a1dd06d44caed79eba8c328c82d981f9060edb6f8232176fb3ea6` |
| Where the amendments are | Section 2 amends the enactments in column (4) of the Schedule "to the extent and in the manner mentioned in column (5)". **Serial 51** (1988, No. 59, The Motor Vehicles Act, 1988) is on Gazette pages 71 to 79 and has **45 lettered items, (A) to (ZS)** |
| How I found it | A web search gave a lead to this e-Gazette ID. I downloaded the file myself and checked its first page (title, "No. 8 of 2026", assent date, Gazette number) and serial 51 before using it. I did not rely on the search result. India Code's own copy of Act 8 of 2026 was **not** located in this pass. I did not validate the PDF's digital signature |
| Short-title text | Section 1(2): in force on a date the Central Government appoints by notification, and "different dates may be appointed for amendments relating to different enactments mentioned in the Schedule" |

### 10.2 Commencement: is 15-08-2026 supported?

**Yes, for all of serial 51.** S.O. 4100(E), dated 24-07-2026 (Gazette Part II, s.3(ii), No. 3930; e-Gazette ID CG-DL-E-25072026-274798; section 9.2 B), uses the power in section 1(2) of Act 8 of 2026 and appoints "the 15th day of August, 2026 as the date on which the provisions of the said Act, in so far as it relates to serial number 51 and the entries relating thereto in the Schedule to the said Act, relating to the Motor Vehicles Act, 1988 (59 of 1988), shall come into force." The notification works at the level of the whole serial, so it supports the same date for every one of the 45 items (A) to (ZS). It gives no item-level exceptions.

Not covered by that notification, and not tested here: Act 8 of 2026's section 3 (a 10 per cent revision of fines and penalties after every three years from commencement of the Act, with a proviso deferring to an enactment's own revision scheme). I did not check whether, or when, section 3 has been brought into force or how it interacts with the Motor Vehicles Act's section 199B. It does not affect the 57 footnotes.

### 10.3 Method and limits

1. Listed every footnote line in the PDF text that cites Act 8 of 2026 or a "15-08-2026" / "15-8-2026" date, with its PDF page (the printed page number is the same) and the provision it sits against.
2. Read serial 51 from the Gazette text, item by item.
3. Compared each amending instruction with the consolidated wording: the words inserted or substituted, the words omitted, and where the footnote marker sits.
4. For long substitutions (sections 177, 177A, 190, 194F, 198, 198A, 200), compared the Act's new text with the PDF's text with whitespace ignored. For short word changes, searched the PDF for the new words in the right section.
5. Where two texts looked different, I rendered both pages and read the images (section 190, section 210A, section 168(4)).
6. As a cross-check I diffed the portal's two text extracts for this Act (as on 21-05-2025 and as on 15-08-2026; see section 4.2). Every substantive change between them matched an Act 8 of 2026 item, except those in 10.6 D2 and D3. That diff is not an official text and was used to find differences, not to prove wording.

Limits: I compared the **amended words**. I did not proofread the rest of the Act (section 6, item 5 stands). The Gazette text layer glues some words together ("shallbe", "notdisposing", "forbodilyinjuryordamagetoproperty"); in the cases I checked against the page image (sections 190 and 168(4)) the print is normal, so I treated those as extraction artefacts. I did not check every such case visually. I did not read Act 8 of 2026 outside serial 51.

### 10.4 The 17 references you listed

"PDF p." is the page of the consolidated PDF. "Gazette p." is the page of the Act 8 of 2026 PDF. All 17 are VERIFIED: the consolidated wording matches the Act item, and S.O. 4100(E) supports 15-08-2026.

| # | PDF p. | Footnote wording in the PDF | MV Act provision | Act 8 of 2026 item (Gazette p.) | Result and what I compared |
|---|---|---|---|---|---|
| 1 | 16 | 2. Sub-section (8) omitted by Act 8 of 2026, s. 2 and Sch., (w.e.f. 15-08-2026). | s.8(8) | (A) (71) | **VERIFIED.** Asterisks and marker 2 sit after s.8(7) and before s.9; (8) is absent |
| 2 | 17 | 2. Subs-section (9) omitted by Act 8 of 2026, s. 2 and Sch. (w.e.f. 15-08-2026). | s.9(9) | (B) (71) | **VERIFIED.** Asterisks after s.9(8). The footnote's own typing ("Subs-section") is a typo in the PDF, not in the amendment |
| 3 | 19 | 1. Sub-section (4) omitted by Act 8 of 2026, s. 2 and Sch. (w.e.f. 15-08-2026). | s.12(4) | (C) (71) | **VERIFIED.** Asterisks sit between s.12(3) and the 2019 sub-section (5) |
| 4 | 19 | 8. Ins. by Act 8 of 2026, s. 2 and Sch., (w.e.f. 15-08-2026). | s.14(2), proviso after clause (iv) | (D) (71) | **VERIFIED.** Text identical: "Provided that every driving licence shall, notwithstanding its expiry under this sub-section, continue to be effective for a period of thirty days from the date of such expiry." Placed after clause (iv), as the Act directs |
| 5 | 19 | 10. Subs. by Act 8 of 2026, s. 2 and Sch., for "expiry" (w.e.f. 15-08-2026). | s.15(1): "with effect from the date of its renewal" | (E)(i) (71) | **VERIFIED.** "expiry" is now "renewal" |
| 6 | 20 | 1. Subs. by Act 8 of 2026, s. 2 and Sch., for proviso (w.e.f. 15-08-2026). | s.15(1), first proviso | (E)(ii) (71) | **VERIFIED.** Text identical: "Provided that in any case where the application for the renewal of a licence is made within a period of one year prior to date of its expiry, the driving licence shall be renewed with effect from the date of its expiry:". The 2025 extract had the older "either one year prior … or within one year after …" wording, now gone |
| 7 | 22 | 4. Clause (c) of sub-section (1) of section 132, omitted by Act 8 of 2026, s. 2 and Sch. (w.e.f. 15-08-2026). | s.20(2), first place | (F)(i) (72) | **VERIFIED.** The PDF reads "convicted of an offence under 4*** section 134 or section 185" |
| 8 | 22 | 5. Clause (c) of sub-section (1) of section 132 or, omitted by ibid., (w.e.f. 15-08-2026). | s.20(2), second place | (F)(ii) (72) | **VERIFIED.** The PDF reads "relatable to 5*** section 134" |
| 9 | 30 | 2. Subs. by Act 8 of 2026, s. 2 and Sch., for "whose jurisdiction" (w.e.f. 15-08-2026). | s.40: "in which he has the residence" | (G) (72) | **VERIFIED** |
| 10 | 40 | 1. Subs. by Act 8 of 2026, s. 2 and Sch., for "fourteen days" (w.e.f. 15-08-2026). | s.55(1): "within thirty days" | (H) (72) | **VERIFIED** |
| 11 | 55 | 2. Ins. by Act 8 of 2026, s. 2 and Sch. (w.e.f. 15-08-2026). | s.75 marginal heading: "renting of motor cabs and motor cycles" | (J)(i) (72) | **VERIFIED** |
| 12 | 56 | 1. Ins. by Act 8 of 2026, s. 2 and Sch. (w.e.f. 15-08-2026). | s.75(2)(g): "motor cabs and motor cycles may be rented" | (J)(ii) (72) | **VERIFIED** |
| 13 | 60 | 1. Subs. by Act 8 of 2026, s. 2 and Sch., for "Chapters X, XI and XII" (w.e.f. 15-08-2026). | s.84(f): "Chapters XI and XII" | (K) (72) | **VERIFIED** |
| 14 | 68 | 1. Sub-section (2), clause (xii), omitted by Act 8 of 2026, s. 2 and Sch. (w.e.f. 15-08-2026). | s.96(2)(xii) | (L) (72) | **VERIFIED.** Asterisks sit between clauses (xi) and (xiii) |
| 15 | 91 | 1. Subs. by Act 8 of 2026, s. 2 and Sch., for "fourteen days" (w.e.f. 15-08-2026). | s.157(2): "within thirty days" | (M) (72) | **VERIFIED** |
| 16 | 97 | 6. Ins. by Act 8 of 2026, s. 2 and Sch. (w.e.f. 15-08-2026). | s.166, proviso after sub-section (3) | (Q) (73) | **VERIFIED.** Text identical: the Claims Tribunal may entertain an application "after the expiry of the said period of six months … but within a further period not exceeding twelve months, if it is satisfied that the applicant was prevented by sufficient cause …" |
| 17 | 98 | 4. Ins. by Act 8 of 2026, s. 2 and Sch. (w.e.f. 15-08-2026). | s.168(4) and its proviso | (S) (73) | **VERIFIED.** Same twelve-month disposal wording. The Gazette text layer shows "notdisposing"; the page image shows "not disposing", as in the PDF |

### 10.5 The other 40 footnotes (written "15-8-2026")

These are the same population of footnotes, in the second date format. Same method and the same commencement basis. Several footnotes cover more than one place in the text.

| PDF p. | Footnote | MV Act provision | Act item (Gazette p.) | Result |
|---|---|---|---|---|
| 46 | 2 | s.65(2)(k): words "sub-section (13) of section 41 or" omitted | (I) (72) | VERIFIED |
| 92 | 1 | s.161(4)(b): "liable to penalty which shall not be less than one lakh rupees but which may extend to five lakh rupees" | (N) (72) | VERIFIED |
| 93 | 1 | s.163(3) and s.164(4) with Explanation (one footnote, marker 1 used twice) | (O) (72), (P) (73) | VERIFIED. Both texts identical, including "section 116 of the Bharatiya Nyaya Sanhita, 2023 (45 of 2023)" |
| 98 | 1 | s.167: "without prejudice to the provisions of Chapter X" omitted | (R) (73) | VERIFIED |
| 100 | 1, 2, 3 | s.177 and 177A substituted; s.178 "liable for a penalty" (four places); s.178(3) "while being on duty" | (T) (73), (U)(i), (U)(ii) (74) | VERIFIED |
| 101 | 1, 3, 7 | s.179(1) "liable to penalty"; s.179(2) new wording; s.182(2) "liable to penalty of ten thousand rupees" | (V)(i), (V)(ii), (W) (74) | VERIFIED |
| 102 | 1, 2 | s.182B heading "Penalty"; "liable for a penalty" | (X)(i), (X)(ii) (74) | VERIFIED |
| 103 | 8, 10 | s.186: "liable for the first contravention with penalty"; "subsequent contravention with penalty" | (Y)(i), (Y)(ii) (74) | VERIFIED |
| 104 | 6, 10 | s.190(1) and (2) substituted; s.192(1) "liable for the first offence with a penalty which may extend" | (Z) (75), (ZA) (75) | VERIFIED. I read s.190 on the Gazette page image and it matches the PDF |
| 105 | 2, 5 | s.192A(1) "liable to penalty of ten thousand rupees and for any subsequent contravention with penalty of twenty thousand rupees"; s.192B(1) "liable for a penalty" | (ZB) (75), (ZC)(i) (76) | VERIFIED |
| 106 | 1, 4, 8, 10, 12, 15 | s.192B(2) and s.193(2) "liable for a penalty"; s.193(1) "for the first offence with penalty"; s.193(3) new wording; s.194(1) "liable to penalty", "additional penalty"; s.194(1A) | (ZC)(ii) (76), (ZD) (76), (ZE)(i), (ZE)(ii) (76) | VERIFIED. See D3 about footnote 8 |
| 107 | 1, 4, 5, 6 | s.194(2); ss.194A, 194B (two places), 194C and 194D "liable for a penalty"; s.194E new wording; s.194F substituted | (ZE)(iii), (ZF) to (ZI) (76), (ZJ), (ZK) (77) | VERIFIED |
| 108 | 1, 3, 5, 6 | s.196 base-premium penalty wording; s.198 substituted; s.198A(1) inserted words; s.198A(2) substituted | (ZL) (77), (ZM), (ZN)(a), (ZN)(b) (78) | VERIFIED. The PDF's s.194F ends with a double bracket, "]]" (D3) |
| 109 | 1 | s.198A(3)(g): "or the State Government, as the case may be" | (ZN)(c) (78) | VERIFIED |
| 110 | 1, 2, 4 | s.199B heading "and penalties"; "The fines and penalties"; s.200(1) list of compoundable offences | (ZO) (78), (ZP) (79) | VERIFIED. The s.200(1) list is word for word the Act's list |
| 115 | 2 | s.210A marginal heading | (ZQ)(i) (79) | **INCORRECT.** See D1 |
| 115 | 3 | s.210A: "to be applied to each fine or penalty under this Act and such modified fine or penalty" | (ZQ)(ii) (79) | VERIFIED |
| 115 | 4 | s.210C(ba): "the manner in which warning for contraventions shall be recorded under this Chapter;" | (ZR) (79) | VERIFIED |
| 116 | 1 | s.212(4): "sub-section (3) of section 161" in place of "sub-section (1) of section 163" | (ZS) (79) | VERIFIED |

Coverage the other way: all **45** items (A) to (ZS) of serial 51 appear in the consolidation. None is missing and none is footnoted at a place the Act does not name.

### 10.6 Discrepancies and uncertainties

**D1. Section 210A, marginal heading: INCORRECT (wording).** PDF p. 115, footnote 2.
- **Act 8 of 2026, item (ZQ)(i), Gazette p. 79:** "in the marginal heading, after the words "to increase", the words "fines or" shall be inserted". The heading becomes "Power of State Government to increase fines or penalties."
- **PDF p. 115:** "210A. Power of State Government to increase 2[fine or] penalties."
- **What differs:** the PDF says "fine or", the Act says "fines or". I read the text layers and both page images; they agree with each other. The 21-05-2025 extract had "Power of State Government to increase penalties", so the insertion itself is real.
- **Why it matters:** low. It is a heading, and the body of s.210A is correct (footnote 3 is VERIFIED). It shows the consolidation was not word-for-word with the Act, so a retrieval system or a reader quoting the PDF would carry the PDF's wording.
- **Evidence needed:** India Code's confirmation or the Legislative Department's own consolidation. I did not change the PDF or its extracted text.

**D2. Section 132(1)(b): wording changed with no Act 8 of 2026 source. UNRESOLVED.** PDF p. 81.
- The 21-05-2025 extract reads "...will become, unmanageable, **or** 4* * * * *". The 15-08-2026 PDF reads "...will become, unmanageable, 2* * * * *". The word "or" at the end of clause (b) is gone.
- Serial 51 has **no item for section 132.** The only Act 8 of 2026 mentions of section 132 are the s.20(2) omissions (references 7 and 8), which do not touch s.132 itself. Footnote 2 on p. 81 is the 1994 Act's omission of clause (c).
- **Why it matters:** a possible silent editorial change in the consolidation. It may be a correct tidy-up (clause (c) was omitted in 1994) or an error. I cannot tell which from these sources.
- **Evidence needed:** the Gazette text of section 132 as amended in 1994 and the 2019 Act, or India Code's note on the change.

**D3. Footnote formatting inconsistencies (no change to meaning).**
- Two date formats ("15-08-2026" and "15-8-2026"). This is why a search for one format found only 17 of 57.
- p. 17 footnote 2: "Subs-section (9)", should read "Sub-section (9)".
- p. 98 footnote 1: "Act 8 of 2026 and Sch." omits "s. 2".
- p. 106 footnote 8: "Subs. by s. 2 and Sch., ibid." follows footnote 7, which cites Act 32 of 2019, so "ibid." points to the wrong Act on a strict reading. The amendment itself, s.193(3), matches Act 8 of 2026 (ZD)(iii).
- p. 93 footnote 1 and p. 107 footnote 4 each serve several places in the text.
- p. 108 line 4: the s.194F text ends "]]".
- p. 22 footnotes 4 and 5 describe the omitted words, not the section's own provision.

**D4. Quiet corrections between the 2025 and 2026 extracts (not Act 8 of 2026).** Spelling and spacing fixes: "belive" to "believe", "neces sary" to "necessary", "diplaying" to "displaying", "execuse" to "excuse", "e-cart" to "E-cart" (section 2A heading, in the arrangement of sections and in the text), "there under" to "thereunder", and some punctuation. They are not footnoted. I list them so that a reader comparing versions is not surprised.

**D5. Corrections to earlier statements.**
- Section 9.3 says the PDF has "17 footnotes saying 'Act 8 of 2026 … (w.e.f. 15-08-2026)'". The correct figure is 57 footnote lines across two date formats (17 + 40).
- The acquisition report's section 6, row 7, names India Code records `24946995-5c8c-46da-be54-230d95776539` and `f86e9c98-e3c5-4c1f-ab00-50604293b2b2` as amendment records for Act 8 of 2026. I have now opened them: they are Jan Vishwas records for the **Clinical Establishments Act, 2010** and the **Legal Metrology Act, 2009**, not for the Motor Vehicles Act. Those two ids should not be cited for this Act. I found no India Code amendment record for the Motor Vehicles Act under Act 8 of 2026. I did not edit the acquisition report.

### 10.7 What is still needed

1. India Code's or the Legislative Department's own consolidation, or confirmation of D1 and D2 from either.
2. The 1994 and 2019 Gazette texts for section 132 (D2).
3. A check of Act 8 of 2026 sections 3 to 5 against the Motor Vehicles Act (section 3, the fine revision, is a separate commencement question).
4. The same footnote-to-Act comparison for the **other** amending Acts (1994, 2000, 2001, 2015, 2019, 2023). This pass covered Act 8 of 2026 only.

### 10.8 Overall conclusion

For the amendments made by Act 8 of 2026, the consolidated PDF is accurate in substance. All 45 items of serial 51 are reflected, all 57 footnotes citing the Act have a matching Gazette instruction, and the 15-08-2026 effective date is supported by S.O. 4100(E). One heading is mistyped ("fine or" for "fines or", section 210A), and one unexplained wording change sits outside the Act's items (section 132(1)(b), "or" dropped). Neither affects the penalty amounts or time limits the Act changed. This is a check of Act 8 of 2026 only. It is not legal advice, not approval, and not a statement that the Act is current.

### 10.9 Files and boundaries

- **Fetched for this check:** the Gazette PDF of Act 8 of 2026 (hash above), and the portal's two text extracts for the Motor Vehicles Act (`d09c0ddb…` as on 21-05-2025, 453,964 bytes; `a6454f94…` as on 15-08-2026, 459,278 bytes). Working files, page images and scripts are in `/private/tmp/claude-501/-Users-vj-Downloads-KnowYourRules-repo/626eb518-0a64-43ba-a91e-e5f904c6beec/scratchpad/v4d/`, outside the repository.
- **Original PDF** (`c619755e…dc482`): unchanged.
- **Changed in the repository:** this report only (section 10 appended; sections 1 to 9 not edited).
- **Not changed:** application code, the index, ChromaDB, the source registry, approvals, the legal decision register. Nothing ingested or activated, nothing committed, pushed or deployed.

## 11. Remaining gaps: section 132(1)(b), the three-year fine revision, section 210A (dated 2026-11-16)

Sections 1 to 10 are unchanged. The 17-footnote count was already corrected in section 10 (57 references: 17 + 40) and needs no further correction. Its findings and evidence stand.

**Bottom line**
- **Section 132(1)(b): the omitted "or" is not supported by any amending instruction.** I read the amending text of all seven amending Acts for section 132. Only the 1994 Act (section 40) touches section 132, and it omits clause (c) only. India Code's own section page for section 132 still has the "or". So the 15-08-2026 PDF departs from the Act as amended and from India Code's own section record. I classify it as a **probable consolidation error**. I could not see the 1988 original, so I cannot say who made the change or why.
- **Three-year fine revision (section 3 of Act 8 of 2026): on its face it does not apply to Motor Vehicles Act fines.** Its proviso defers to an enactment's own revision provision, and the Motor Vehicles Act has one (section 199B). Section 199B may itself need a Central notification. **I found no official notification revising any fine up to 16-11-2026**, but the Gazette search was incomplete. Several legal points go to counsel (11.2).
- **Section 210A: heading only.** The operative sentence matches the Act. India Code's own section page shows the same "[fine or]" heading as the PDF, so the slip is in India Code's consolidation, not only in the downloaded file.

### 11.1 Section 132(1)(b)

**Documents obtained.** All were fetched into the session scratchpad, outside the repository.

| Document | Identification | Source and URL | Size (bytes) | SHA-256 |
|---|---|---|---|---|
| **Motor Vehicles (Amendment) Act, 1994** | No. 54 of 1994, dated **10-09-1994** (read from the page image). Commencement of section 40: 14-11-1994 according to the consolidation's footnotes; the commencement notification was **not** obtained. The Act is shown on India Code as repealed by Act 30 of 2001 | India Code, amendment record `5b8bb00d-7c4e-476a-8f5f-b846c16dd708`: `https://indiacode.gov.in/server/api/core/bitstreams/22c198a8-1e7d-4a99-ab0c-8b2fee4a202c/content` (file `1994-54.pdf`, text layer) | 940,195 | `a9052b639f24bbc9ba0d0c1b5c1072280116663af4ae1a23064c3468d5f03a47` |
| Same Act, second India Code file | Same Act (image-only scan) | India Code record `07e9543f-e3b3-453a-a0d2-96a9379bf31b`: `https://indiacode.gov.in/server/api/core/bitstreams/50e89d65-9813-467b-9d95-14e71e1a90fe/content` (`A1994-54.pdf`) | 835,679 | `ab3b032f3070e4abe5e9885d940295d3bb01b828b8a02ddcd015a5a50ca845be` |
| **Motor Vehicles (Amendment) Act, 2019** | No. 32 of 2019, assent **09-08-2019**; Gazette Extraordinary, Part II s.1, **No. 51**, 09-08-2019 | e-Gazette: `https://egazette.gov.in/WriteReadData/2019/210413.pdf` | 1,250,015 | `488b7fc7b2051f4583501e6c06de8afb75a65a1de4f003cd8979f93c066b2b8d` |
| Commencement of the 2019 Act | **S.O. 3110(E)**, 28-08-2019, Gazette Part II s.3(ii), No. 2841 (appoints 01-09-2019 for listed sections); **S.O. 3147(E)**, 30-08-2019, No. 2880 (section 1 from 01-09-2019) | MoRTH: `https://morth.gov.in/backend/old_files/notifications_document/S.O.%203110(E)%20dated%2028%20august%202019%20regarding%20implementation%20of%20certain%20sections%20of%20Motor%20Vehicles%20(Amendment)%20Act,%202019.pdf` and `https://morth.gov.in/backend/old_files/notifications_document/S.O.%203147(E)%20dated%2030%20August%202019%20regarding%20implementation%20of%20Section%201%20of%20the%20MV%20(Amendment)%20Act,%202019.pdf` | 277,840; 256,287 | `08d5c7db21cced4ccc0407d30792e353c5b46dba24c67d9f0c802f4bb9c1f62c`; `1870da17ee746197f6f58933af096dd9219a2ec1d6f391bd01e9a618d7480353` |
| Jan Vishwas (Amendment of Provisions) Act, 2023 | No. 18 of 2023, assent 11-08-2023; Gazette No. 21, ID CG-DL-E-12082023-248047 | e-Gazette: `https://egazette.gov.in/WriteReadData/2023/248047.pdf` | 293,682 | `23cb77f3b4905932d5ca94179eac97e48e27b01b2a1b70a7e57d3900b0ed1222` |
| Motor Vehicles (Amendment) Acts of 2000 (27 of 2000), 2001 (39 of 2001), 2015 (3 of 2015) | Short Acts, two pages each | India Code copies (`A2000-27.pdf`, `2001-39.pdf`, `A2015-3.pdf`) | 70,267; 44,656; 95,400 | `23b3728b3a54a3d0…`; `b9e79061169f636b…`; `ae67c698e229d188…` |

The 1994 Act is not on e-Gazette in this search (I did not find it), so the India Code scan is the best official copy I have. Pre-2019 texts are scans or India Code copies; I did not compare them with a Gazette print.

**Did each of the seven amending Acts touch section 132?**

| Amending Act | Result |
|---|---|
| 1994 (54 of 1994) | **Yes, section 40 only.** PDF p. 10 (read from the page image): "In section 132 of the principal Act, in sub-section (1),— (a) for the words "may reasonably be necessary", the words "may for such reasonable time as may be necessary, but not exceeding twenty-four hours" shall be substituted; (b) for clause (a), the following clause shall be substituted, namely:— "(a) when required to do so by any police officer not below the rank of a Sub-Inspector in uniform, in the event of the vehicle being involved in the occurrence of an accident to a person, animal or vehicle or of damage to property, or"; (c) clause (c) shall be omitted." The 1994 Act has no other section 132 reference (section 39 amends section 131) |
| 2000, 2001, 2015 | No. Sections amended: 2000: 52, 58, 66, new 217A; 2001: 66, 67; 2015: new section 2A, then 7, 9, 27 |
| 2019 | No. The Gazette text has no amendment of section 132 (it inserts section 134A after section 134) |
| Jan Vishwas 2023 | No. Serial 26 (Motor Vehicles Act): sections 192A, 200(1), 215(3) only |
| Jan Vishwas 2026 | No. Serial 51 has no item for section 132 (section 10, 10.4 and 10.6 D2) |

**Wording compared**

| Version | Section 132(1)(b) ending |
|---|---|
| 1994 instruction (above) | Clause (b) is not mentioned. The only change near it is "(c) clause (c) shall be omitted." |
| India Code text as on **21-05-2025** | "…will become, unmanageable, **or** 4* * * * *" |
| India Code **section record** for section 132 (item `835b859c-97b9-4bda-927b-e1614ae47ba0`, last modified 10-07-2026) | "…will become, unmanageable, **or** 3 * * * * *" |
| India Code text as on **15-08-2026** and the downloaded PDF, p. 81 | "…will become, unmanageable, 2* * * * *" (**no "or"**) |

**Finding: not legally supported; probable consolidation error.** The amendment text that omits clause (c) does not remove the "or" after clause (b), and no other amending instruction touches the clause. India Code's own section page still carries the "or". So the three India Code sources disagree: two keep the "or", the 15-08-2026 consolidation drops it. I cannot say whether the "or" belongs to the original 1988 text; I did not obtain the 1988 Gazette. Everything I have, including the 1994 instruction, points the same way. **The remaining uncertainty is about intent (a deliberate tidy-up of the "or" left dangling after clause (c) was omitted, or an error), not about what the amending Acts say.** The practical effect of the missing word is small, but a reader quoting the PDF would be quoting wording that no amending Act supports. It needs a decision from India Code or counsel.

**Side findings from this pass**
- **A likely explanation for the checksum mismatch in section 4.** India Code serves its PDFs with a stamped "India Code" text overlay. For the 2019 and 2023 Acts I could compare with an e-Gazette original: the e-Gazette 2019 file has the same size and MD5 as India Code's stored record (1,250,015 bytes, `2197279aa54342519ab03ed632d23f3b`), and the e-Gazette 2023 file has the same MD5 as India Code's stored record (`062a3416a3c2a91cfe163c9f334e076e`). The files India Code actually served were larger (1,273,280 and 336,133 bytes) and carry the stamp in their text layer. The Motor Vehicles Act PDF's stray letters ("e", "od", "aC", "di", "In") look like the same stamp. This is **consistent with** the stored checksum being the unstamped original and the served file being the stamped one. It is not proof for the Motor Vehicles Act, because I have no unstamped copy of it. Section 4 stays UNRESOLVED at byte level, with this as the leading explanation.
- **2019 enactment date.** The Gazette shows assent on **09-08-2019**. India Code's 30-08-2019 matches the date of S.O. 3147(E), not the Act's assent. This resolves section 6, item 7: 09-08-2019 is the Act's date.
- **India Code mis-filed file.** The ORIGINAL file of India Code's record for the 2019 Act (`3cd17228-7078-42a2-b353-14d399d1b8ed`) is a **Jharkhand** compounding notification, not the Act.
- **Repeal of the 2019 Act as an amending Act.** The Repealing and Amending Act, 2025 (No. 37 of 2025, assent 20-12-2025, Gazette ID CG-DL-E-21122025-268699; SHA-256 `15e7fb5f220e56d6f8c7545370d0837cd263e5322fca68a2a39a6413cb5a7f4d`) lists "2019, 32, The Motor Vehicles (Amendment) Act, 2019" in its First Schedule, with a savings clause (section 4). I did not analyse the effect; the amendments the 2019 Act made to the Motor Vehicles Act remain in the consolidation. It does not change the section 132 finding.

### 11.2 Section 3 of the Jan Vishwas Act, 2026 (three-year fine revision)

**Text (Act 8 of 2026, Gazette p. 2, section 3, "Revision of fines and penalties"):** "The fines and penalties provided under various provisions in the enactments mentioned in the Schedule shall be increased by ten per cent. of the minimum amount of fine or penalty, as the case may be, prescribed therefor, after the expiry of every three years from the date of commencement of this Act: Provided that notwithstanding anything contained in this section, if any enactment mentioned in the Schedule provides the manner of revision of fines and penalties therein, only the said provision shall be applicable for increase of fines and penalties for provisions of such enactment."

**What it applies to.** On its face it covers the fines and penalties in every enactment in the Schedule, which includes the Motor Vehicles Act (serial 51). The proviso then excludes any enactment that provides its own manner of revision. The Motor Vehicles Act does:
- **Section 199B** (PDF p. 110, heading and wording as amended by Act 8 of 2026): "199B. Revision of fines and penalties.—The fines and penalties as provided in this Act shall be increased by such amount not exceeding ten per cent. in value of the existing fines, on an annual basis on 1st day of April of each year from the date of commencement of the Motor Vehicles (Amendment) Act, 2019 (32 of 2019), as may be notified by the Central Government."
- **Section 210A** (PDF p. 115): a State may, by notification, specify a multiplier of one to ten applied to each fine or penalty, under conditions set by the Central Government.

On that reading, **section 3 of the 2026 Act does not itself revise Motor Vehicles Act penalties; only section 199B (and State multipliers under section 210A) do.** That is a reading of the text, not a legal opinion. Item (ZO) of serial 51 widened section 199B's heading and first words from "fines" to "fines and penalties", so the new "penalty" wording in the amended sections is within section 199B from 15-08-2026.

**Commencement.**
- Section 1(2) of Act 8 of 2026 allows different dates for different enactments. **S.O. 4100(E)** appoints 15-08-2026 for "the provisions of the said Act, in so far as it relates to serial number 51 and the entries relating thereto in the Schedule". It does not name section 3. **Whether section 3 is in force for the Motor Vehicles Act is therefore not clear from the notification.** If it commenced for the Act on 15-08-2026, "after the expiry of every three years" would first fall at 15-08-2029. Because of the proviso, that date would not apply to Motor Vehicles Act fines.
- **Section 199B** was inserted by section 85 of the 2019 Act. S.O. 3110(E) appoints 01-09-2019 for "Section 78 to 87 (both inclusive)", so section 199B has been in force since **01-09-2019**. Its revision date is 1 April each year "from the date of commencement of the 2019 Act, as may be notified by the Central Government".

**Automatic or needing a notification?**
- Section 3 of the 2026 Act reads as automatic (no notification), once commenced, but is displaced for this Act by its proviso.
- **Section 199B:** the words "as may be notified by the Central Government" can be read as qualifying the commencement date (which S.O. 3110(E) fixed) or as requiring a notification for each increase. The text does not settle it. **Unresolved; counsel.**
- **Section 210A:** needs a notification by each State. The Centre notified the conditions in **S.O. 3310(E)**, 25-09-2020 (Gazette Part II s.3(ii), No. 2958, ID CG-DL-E-26092020-222012; SHA-256 `64db29595b4f1f12c81272e45218f913c3428542be6454329f4b981cfc221b6d`). State multiplier notifications were not searched.

**An overlapping provision I noticed.** Section 3 of the **2023** Jan Vishwas Act (Gazette p. 1 to 2) has the same three-year 10 per cent rule **without** a proviso. The Motor Vehicles Act is in its Schedule (serial 26, sections 192A, 200(1), 215(3)), and the consolidation shows those amendments "w.e.f. 13-01-2025". If that Act's section 3 applies to the Motor Vehicles Act, the first three-year point would be 13-01-2028. I did not obtain the 2023 commencement notification, and I did not analyse how the two Acts interact. **Unresolved; counsel.**

**Search for revision notifications up to 16-11-2026.**
- MoRTH: I re-read its Gazette Notifications list on 16-11-2026 (still 911 documents; newest 06-11-2026) and scanned its titles for fine revision, penalty increases, section 199B, multipliers and compounding. The only hits were S.O. 3310(E) (above), G.S.R. 584(E) of 25-09-2020 (CMVR offences and procedure, opened, not a fine revision; `0a610777403d9841d6d1b94f225111680e9e7c9e8c2268bc8aefa00001be4793`) and two 2021 fee-revision rules for registration and fitness fees (not fines). The MoRTH Orders list (about 2,100 titles) had none.
- Web search found no such notification.
- **I found no official notification revising any fine or penalty under section 199B up to 16-11-2026. That is not a finding that none exists:** the e-Gazette keyword and date search is still not run (section 9.4), and title scans can miss a notification with a general title.
- **I have not calculated, and do not publish, any revised amount.** No official source I found establishes one.

### 11.3 Section 210A: recheck

| Source | Wording |
|---|---|
| **Act 8 of 2026, item (ZQ)(i), Gazette p. 79** | "In section 210A,— (i) in the marginal heading, after the words "to increase", the words "fines or" shall be inserted;" |
| **Act 8 of 2026, item (ZQ)(ii), Gazette p. 79** | "(ii) for the words "to be applied to each fine under this Act and such modified fine", the words "to be applied to each fine or penalty under this Act and such modified fine or penalty" shall be substituted." |
| **Downloaded PDF, p. 115** | "210A. Power of State Government to increase 2[fine or] penalties.—Subject to conditions made by the Central Government, a State Government, shall, by notification in the Official Gazette, specify a multiplier, not less than one and not greater than ten, 3[to be applied to each fine or penalty under this Act and such modified fine or penalty], shall be in force in such State…" |
| India Code **section record** for 210A (item `1038a4e1-d769-4093-80d7-6bb889f51aea`, last modified 12-10-2026), page text | "210A. Power of State Government to increase 2 [fine or] penalties.—…[to be applied to each fine or penalty under this Act and such modified fine or penalty]…" (same as the PDF); the record's own title field still reads "Power of State Government to increase penalties." |
| India Code text as on 21-05-2025 | Heading "Power of State Government to increase penalties." |

**Confirmed.** The Act inserts "fines or" in the heading; the PDF (and India Code's own section page) shows "fine or". **The difference is confined to the marginal heading.** Item (ZQ)(ii), the only instruction that changes the operative sentence, is reproduced word for word, so the operative provision is unaffected. Whether a marginal heading carries any legal weight is for counsel. Status stays INCORRECT for the heading reference (section 10.5, PDF p. 115 footnote 2) and VERIFIED for the operative reference (footnote 3). The Act's heading reads "fines or penalties".

### 11.4 What remains unresolved

1. **Section 132(1)(b):** the reason for dropping "or" (error or deliberate tidy-up); the 1988 original text; and a Gazette print of the 1994 Act (only India Code scans were used).
2. **Section 199B:** whether each annual increase needs a Central notification; whether any has been issued (e-Gazette search not run); whether section 3 of the 2026 Act is in force for this Act; how the 2023 Act's section 3 applies, and the 2023 commencement notification (13-01-2025 is from the consolidation's footnotes only).
3. **Section 210A:** nothing further beyond the heading; State multiplier notifications were not searched.
4. **Checksum mismatch (section 4):** a likely explanation (stamping), unproven for this file.

### 11.5 Files and boundaries

- **Fetched for this pass:** the documents in 11.1 and 11.2 (hashes above), the two India Code section records (132 and 210A), and re-reads of the MoRTH list. Working files and page images are in `/private/tmp/claude-501/-Users-vj-Downloads-KnowYourRules-repo/626eb518-0a64-43ba-a91e-e5f904c6beec/scratchpad/v4e/`, outside the repository. Some e-Gazette IDs next to a known 2019 Gazette ID were probed to find the 2019 Act's Gazette; the rest were discarded.
- **Original PDF** `c619755e…dc482`: unchanged.
- **Changed in the repository:** this report only (section 11 appended).
- **Not changed:** application code, the index, ChromaDB, the source registry, approvals, the legal decision register. Nothing ingested or activated, nothing committed, pushed or deployed. No legal approval is claimed.
