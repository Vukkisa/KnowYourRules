# Legal source completeness audit: Telangana traffic-law RAG

Audit date: 2026-11-15. Audit and planning only. Nothing was downloaded, ingested, approved, signed or deployed. No index, registry, source file, approval record, quarantine status, code or configuration was changed. This is the only file written. **No source named here is legally approved; "held" or "found" never means "current" or "authoritative".**

## 1. Summary

- **Held:** 20 indexed sources (13 HTML snapshots from the Telangana Transport Department site, 7 Telangana Government Orders as PDFs, 590 chunks) plus 3 files held on disk but not indexed (draft G.O. 54/2025, the 2008 Andhra Pradesh compounding order, and Rules of the Road Regulations 1989). All 23 file hashes were re-computed and match the recorded values. All 20 indexed sources are `pending` with no active version in the lifecycle registry (quarantined), and every chunk is `unverified`.
- **Missing primary law:** the Motor Vehicles Act, 1988 and the Central Motor Vehicles Rules, 1989 are not in the index. Both are cited as the source of authority by the held Telangana G.O.s (sections 65, 86(5), 212 of the Act; Rules 167 and 167A of the Rules). No current official consolidated text of either was confirmed in this audit.
- **Superseded instrument still held:** the Rules of the Road Regulations, 1989 appear to have been superseded by the Motor Vehicles (Driving) Regulations, 2017 (G.S.R. 634(E), 23 June 2017). That rests on secondary sources; the Gazette text was not read. The Telangana Transport Department still lists the 1989 regulations.
- **Amendment gaps are large.** The Telangana Motor Vehicles Rules snapshot carries no amendment citations. Rule 81 has been changed by six earlier orders (2014 to 2018), a 2025 draft and a 2025 final order, and a Rule 72-A insertion (2015) is reported (secondary). Only the two 2025 orders are held, and only the final one is indexed. The adaptation instrument that makes the 1989 Andhra Pradesh rules Telangana rules was not identified.
- **Conflicts found in the held record** (section 6): Rule 81 exists in the index in two incompatible versions; the manifest wrongly gives G.O. 10/2026 a commencement of 25-02-2026 (the G.O. text appoints 1 March 2026); G.O.Ms.No. 41 of 29-09-2015 is attributed both to Rule 72-A (secondary source) and to the Rule 81 chain (G.O. 54/2025 and 77/2025 text); G.O. 54/2025 and 77/2025 describe the 1989 gazette differently; and the older manifest rows are stale.
- **Scope decision needed:** the repository records a "Telangana-only" decision (08-11-2026) that marks the Motor Vehicles Act, 1988, the Central Motor Vehicles Rules and the Rules of the Road Regulations out of scope. This audit was asked to inventory them anyway. Whether they come into scope is for the project owner and counsel (question 1 in section 9). Several answer types the product handles (helmets, seat belts, speed, licences, penalties) cannot be grounded without them.

## 2. Method and limits

| Item | Detail |
|---|---|
| Repository evidence | Read-only: `docs/legal-sources/telangana-traffic/` (SOURCE-MANIFEST.md, DRAFT-telangana-manifest.json, SHA256SUMS, source documents), the Stage 6 lifecycle registry, `legal-status/source-status.json`, `docs/legal-source-audit.md` (27 Oct 2026, national corpus), and a scratch copy of the published index. |
| Hashes | Every held file was re-hashed (SHA-256) and compared with `source-status.json` and the manifest: 23 of 23 match. |
| Web evidence | Official Telangana Transport Department pages were opened and read. The India Code page for the Motor Vehicles Act (`/handle/123456789/1798`) returned HTTP 403 and could not be read. Everything else on the web comes from search-result summaries; I did not open those documents. Each external claim below is labelled **official page read**, **official link listed (not opened)**, or **secondary** (news, blogs, third-party sites). Secondary evidence is a lead, not proof. |
| Held PDFs | Page counts, first and last pages, and operative clauses of the held G.O.s were read from the files on disk. |
| Not done | No download, no copy of any new document, no Gazette retrieval, no legal judgment on what is in force. |
| Note on the older manifest | `SOURCE-MANIFEST.md` was prepared 29 Oct 2026 and carries later updates; its "Got/Read" columns are stale for several rows. This audit uses the files themselves. |

## 3. Existing sources

### 3.1 Indexed sources (20)

Columns: chunks = indexed chunks / of which `answer_eligible: false`. "Lifecycle" is the Stage 6 registry state and the text-status registry value. Neither is legal approval. The HTML snapshots were retrieved 29-10-2026 from the Transport Department site; they carry no document number, issuing-authority field, publication date or amendment citation. Each snapshot page header reads "Finance Department Govt. of Andhra Pradesh".

| ID | Document / content | Source URL | SHA-256 | Chunks | Lifecycle and text status |
|---|---|---|---|---|---|
| tmvr-1989-chap-1 | TMVR 1989, chapter 1 (HTML frame `middle-main-chap-1.htm`); Rules 1-2 | `https://www.transport.telangana.gov.in/html/acts-rules/middle-main-chap-1.htm` | `977a89529881d166fc391ba37a3aeda6845bb7e3ff190e4f15caf4ad3fd98108` | 3 / 0 | pending; active_version None; text status `unverified_snapshot` |
| tmvr-1989-chap-2 | TMVR 1989, chapter 2 (HTML frame `middle-main-chap-2.htm`); Rules 3-45 | `https://www.transport.telangana.gov.in/html/acts-rules/middle-main-chap-2.htm` | `08e13e074d928a5fc86f63e02a8984382d770a25ecea82579c631694b5503149` | 43 / 0 | pending; active_version None; text status `unverified_snapshot` |
| tmvr-1989-chap-3 | TMVR 1989, chapter 3 (HTML frame `middle-main-chap-3.htm`); Rules 46-78 | `https://www.transport.telangana.gov.in/html/acts-rules/middle-main-chap-3.htm` | `968e1b246ea425f830c218c4ece6601ebcfc1f889c0d036d40112fd81e1be24c` | 33 / 0 | pending; active_version None; text status `unverified_snapshot` |
| tmvr-1989-chap-4 | TMVR 1989, chapter 4 (HTML frame `middle-main-chap-4.htm`); Rules 79-129 | `https://www.transport.telangana.gov.in/html/acts-rules/middle-main-chap-4.htm` | `d901ad962697002883f18c9f4c97f530de64966931f13bbd91d49708b391a3ba` | 55 / 0 | pending; active_version None; text status `unverified_snapshot` |
| tmvr-1989-chap-5 | TMVR 1989, chapter 5 (HTML frame `middle-main-chap-5.htm`); Rules 130-297 | `https://www.transport.telangana.gov.in/html/acts-rules/middle-main-chap-5.htm` | `61f019808cb69abb6bb4b1c17b91a5687e2d2f323d15af1c4d5e9beb3d502a52` | 195 / 0 | pending; active_version None; text status `unverified_snapshot` |
| tmvr-1989-chap-6 | TMVR 1989, chapter 6 (HTML frame `middle-main-chap-6.htm`); Rules 298-309 | `https://www.transport.telangana.gov.in/html/acts-rules/middle-main-chap-6.htm` | `53d1f93beb379d501a76aec101108f4c396b505dac6826a03a52a2ade66f7bb4` | 12 / 0 | pending; active_version None; text status `unverified_snapshot` |
| tmvr-1989-chap-7 | TMVR 1989, chapter 7 (HTML frame `middle-main-chap-7.htm`); Rules 310-395 | `https://www.transport.telangana.gov.in/html/acts-rules/middle-main-chap-7.htm` | `a29464d004db4cc84d2aad756268640b636c5fbcf116f263f6548e86b3d61139` | 89 / 0 | pending; active_version None; text status `unverified_snapshot` |
| tmvr-1989-chap-8 | TMVR 1989, chapter 8 (HTML frame `middle-main-chap-8.htm`); Rules 396-450 | `https://www.transport.telangana.gov.in/html/acts-rules/middle-main-chap-8.htm` | `f86f82fd3f240aa4895674d79428578baf093facd6e58f5d20b43deddfd0c201` | 57 / 0 | pending; active_version None; text status `unverified_snapshot` |
| tmvr-1989-chap-9 | TMVR 1989, chapter 9 (HTML frame `middle-main-chap-9.htm`); Rules 451-453 | `https://www.transport.telangana.gov.in/html/acts-rules/middle-main-chap-9.htm` | `bb99e00241e40bfa7f642535c48373421e56d9fec9092f23a299a184c675dfc4` | 3 / 0 | pending; active_version None; text status `unverified_snapshot` |
| tmvr-1989-chap-10 | TMVR 1989, chapter 10 (HTML frame `middle-main-chap-10.htm`); Rule 454 | `https://www.transport.telangana.gov.in/html/acts-rules/middle-main-chap-10.htm` | `3ec9f467e0ea62af6520de3ee26ad4f32c53722c2ff2ba67c46a79ee3d091925` | 1 / 0 | pending; active_version None; text status `unverified_snapshot` |
| tmvr-1989-chap-11 | TMVR 1989, chapter 11 (HTML frame `middle-main-chap-11.htm`); Rules 455-476 | `https://www.transport.telangana.gov.in/html/acts-rules/middle-main-chap-11.htm` | `168867c0093a17ba8117283e512fd20ce6b57104f3722d4ea163a54b21ed91ec` | 24 / 0 | pending; active_version None; text status `unverified_snapshot` |
| tmvr-1989-chap-12 | TMVR 1989, chapter 12 (HTML frame `middle-main-chap-12.htm`); Rules 477-486 | `https://www.transport.telangana.gov.in/html/acts-rules/middle-main-chap-12.htm` | `9fa4fcb57db09b2705a7283678a7708a26e1b6639e6268a058d87998adbf1b91` | 12 / 0 | pending; active_version None; text status `unverified_snapshot` |
| tmvtr-1963 | Taxation Rules 1963 (HTML frame); only Rules 1-17 (with 12A, 12B, 13A, 13B, 14A, 15A, 15B) indexed | `https://www.transport.telangana.gov.in/html/acts-rules/middle-ap-mv-tr-%201963-main.htm` | `d7f805041083683044d203a942d3223894f51526389ecd5b4d67e76344e5d291` | 24 / 0 | pending; active_version None; text status `unverified_snapshot` |
| go-ms-53-2025-trb | `goir/13082025TRB_MS53.PDF` | goir.telangana.gov.in (no direct file URL; form postback) | `a93f8daa6865eccd2ee646494c10883d98fb0e7c99d3a0f4c64dffe803c15c18` | 7 / 5 | pending; active_version None; text status `official_text_commencement_unconfirmed` |
| go-ms-77-2025-trb | `goir/2025TRB_Ms77.pdf` | goir.telangana.gov.in (no direct file URL; form postback) | `3de907353bdf37415df25f10d45b05e336bd29c077285fae2c9bda2655f7be71` | 7 / 0 | pending; active_version None; text status `official_text_commencement_unconfirmed` |
| go-ms-10-2026-trb | `goir/2026TRB_Ms10.pdf` | goir.telangana.gov.in (no direct file URL; form postback) | `df0ee9357b05ca4db9a187481ff2c8ac50c4a9d2ca05f91800e9bc4161f8c5fd` | 3 / 0 | pending; active_version None; text status `official_text_commencement_unconfirmed` |
| go-ms-16-2026-trb | `goir/2026TRB_Ms16.pdf` | goir.telangana.gov.in (no direct file URL; form postback) | `139f96454954a4b77b3f07a796946827c29a81754f9a782e3e25dd5dfc76e0d5` | 2 / 1 | pending; active_version None; text status `official_text_commencement_unconfirmed` |
| go-ms-24-2026-trb | `goir/2026TRB_Ms24.pdf` | goir.telangana.gov.in (no direct file URL; form postback) | `ba0c9516575ed081181da4288c1395a19ad416bc9e9981c56f65b522b7007905` | 8 / 8 | pending; active_version None; text status `official_text_commencement_unconfirmed` |
| go-ms-25-2026-trb | `goir/2026TRB_Ms25.pdf` | goir.telangana.gov.in (no direct file URL; form postback) | `c9bd1ff3a7e02a3c5324965835dd81ddea9f30df831adf0cb4387f8d3f374872` | 3 / 0 | pending; active_version None; text status `official_text_commencement_unconfirmed` |
| go-ms-32-2026-trb | `goir/2026TRB_Ms32.pdf` | goir.telangana.gov.in (no direct file URL; form postback) | `4bb6273f8c13c08d7e15a64ad063c4ad868beaf527c469c6f1975b71a57f8629` | 9 / 0 | pending; active_version None; text status `official_text_commencement_unconfirmed` |

### 3.2 Facts about each indexed document

| Source | Type and issuing authority | Number and date | Complete? | Amendments or superseding versions known |
|---|---|---|---|---|
| Telangana Motor Vehicles Rules, 1989 (12 chapter files) | State rules. Base instrument issued by the Government of Andhra Pradesh, Transport, Roads & Buildings (Tr.II) Dept. Page frame says Andhra Pradesh; Rule 1 says Telangana | G.O.Ms.No. 216, 07-08-1989; Andhra Pradesh Gazette (Rules Supplement, Part I Extraordinary) 25-08-1989, pp. 1-135 (as cited in G.O. 332/2008 and G.O. 54/2025 text). Telangana adaptation instrument: **not identified** | Rule text numbered 1 to 486 with no gap in the index (letter-suffixed rules such as 80A and 217A are present; **Rule 72A is not**). Forms, schedules and appendices are not in the index and their presence in the snapshot was not checked | Yes, many (section 5.3). The snapshot shows no amendment citations and is known to be outdated at Rule 217 (pre-2008 amounts) |
| Telangana Motor Vehicles Taxation Rules, 1963 | State rules. Page title says Andhra Pradesh; Rule 1 says Telangana | No number or date shown | **Unverified.** Only Rules 1-17 (with suffixed rules) are in the index | Unknown. Adaptation and amendments not identified |
| G.O.Ms.No. 53/2025 (`13082025TRB_MS53.PDF`, 5 pp.) | Telangana, Transport, Roads & Buildings (Tr.I) Dept; notification under s.17 of Act 5 of 1963 | 13-08-2025; Gazette Extraordinary directed for 14-08-2025 (Gazette print not held) | Full 5 pages with signature block. Extraction of the rate tables is unreliable (5 of 7 chunks excluded) | Refers to G.O.Ms.No. 22 of 07-05-2022 (not held) for the earlier schedules. Further amended by G.O. 16/2026 (Seventh Schedule). Third and Sixth Schedule history not held |
| G.O.Ms.No. 77/2025 (`2025TRB_Ms77.pdf`, 3 pp.) | Same department; final notification under s.65 MV Act, 1988 | 15-11-2025; Gazette Extraordinary directed for 15-11-2025 (print not held). Preliminary notice: Telangana Gazette No. G-575 Part I Extraordinary, 13-08-2025 | Full 3 pages | Amends Rule 81 of the Telangana MV Rules: omits sub-rules (1), (2), (4); substitutes (3) (special-number fees, online reservation) and (6). Follows G.O. 54/2025 (draft, held, not indexed). Earlier Rule 81 orders cited, none held: 02/2014, 41/2015, 44/2015, 95/2016, 26/2017, 52/2018 |
| G.O.Ms.No. 10/2026 (`2026TRB_Ms10.pdf`, 1 p.) | Same department; notification under ss.3 and 17 of Act 5 of 1963 | 25-02-2026; Gazette Extraordinary directed for 01-03-2026 (print not held) | Full page. **Act No. 8 of 2026 itself is not held** | Appoints 1 March 2026 as the date Act 8 of 2026 comes into force (text read) |
| G.O.Ms.No. 16/2026 (`2026TRB_Ms16.pdf`, 2 pp.) | Same department; s.17 notification | 20-03-2026; Gazette directed for 23-03-2026 (print not held) | Full 2 pages. 1 of 2 chunks excluded | Amends the Seventh Schedule (removes the additional 2% on second or later personalised vehicles up to 10 seats); builds on G.O. 22/2022 and 53/2025 |
| G.O.Ms.No. 24/2026 (`2026TRB_Ms24.pdf`, 3 pp.) | Same department; exercises CMV Rule 167(5), a central rule | 01-06-2026; Gazette directed for 02-06-2026 (print not held) | Full 3 pages. All 8 chunks excluded: the order says it publishes a "draft Notification" but the notification states it comes into force on publication. **Draft or final is unresolved** | Refers to CMV Rules as amended by G.S.R. 48(E) of 20-01-2026 (not held) |
| G.O.Ms.No. 25/2026 (`2026TRB_Ms25.pdf`, 2 pp.) | Same department; exercises CMV Rule 167(3) | 01-06-2026; Gazette directed for 02-06-2026 (print not held) | Full 2 pages | Same dependency on CMV Rule 167 as amended |
| G.O.Ms.No. 32/2026 (`2026TRB_Ms32.pdf`, 2 pp.) | Same department; Designated Authority under CMV Rule 167A(1), following Supreme Court W.P.(C) 295 of 2012 | 30-06-2026; no gazette direction or commencement clause found | Full 2 pages | Depends on CMV Rule 167A (not held) |

### 3.3 Held on disk but not indexed

| File | What it is | SHA-256 | Note |
|---|---|---|---|
| `goir/2025TRB_Ms54.pdf` (3 pp.) | G.O.Ms.No. 54/2025, 13-08-2025: **draft** (preliminary) notification amending Rule 81 under s.212(1) | `2965f7be670264ed339c062d0caecb41d799d7e192e2ba5b9bc7184d0a5840f7` | Superseded by the final G.O. 77/2025. Correctly not indexed |
| `transport-dept/2008trb_ms332_compounding.pdf` (5 pp.) | G.O.Ms.No. 332, 13-11-2008, **Government of Andhra Pradesh**: revision of permit-related compounding sums under s.86(5) of the MV Act (amends AP Rule 217). Not the s.200 offence schedule | `3fb415be037dcf3b64bd3da86b37e337256335cd9cb619df7dd8e5081a2bd533` | Pre-2014. How it continues in Telangana is unestablished |
| `transport-dept/rules_of_the_road_regulations_1989.pdf` (5 pp.) | Rules of the Road Regulations, 1989, S.O. 439(E), 12-06-1989, in force 01-07-1989. The copy holds regulations 1 to 31 and ends at regulation 31; the official total was not checked | `1242880c31e134e22490527f244ce38ac9a7264ad6a26782b9fad15041e1990f` | Probably superseded (section 5.4). Completeness unverified |

Also held: `supplied/Telangana_Traffic_Law_Legal_Review_Summary.pdf` (SHA-256 `6ce1603d034e3b57223027df9c1994f977432ab06d252b7c8e6a38fcf17f89f5`), a briefing and not a legal source. It names nine archived PDFs that do not exist in any searched location.

## 4. Missing sources and where to get them

Availability notes: "official" means a government or statutory-body site. Nothing was downloaded.

| # | Source | Official location (status) | Held? | Notes |
|---|---|---|---|---|
| 1 | **Motor Vehicles Act, 1988** (59 of 1988), consolidated | India Code: https://www.indiacode.nic.in/handle/123456789/1798 (official; HTTP 403 from this environment). MoRTH page linked by the Transport Department: https://www.morth.nic.in/motor-vehicles-act-1988-0 (official link listed, not opened) | No | The earlier audit (27 Oct 2026) found the corpus copy outdated (latest amending Act 3 of 2015). The Amendment Act is Act 32 of 2019 (https://www.indiacode.nic.in/repealedfileopen?rfilename=A2019-32.pdf, listed, not opened). Later changes: see 5.1 |
| 2 | **Central Motor Vehicles Rules, 1989**, consolidated | India Code (https://www.indiacode.nic.in/ViewFileUploaded?path=AC_BR_59_851_00005_00005_1712231779316%2Frulesindividualfile%2F&file=cmvr-1989.pdf, listed, not opened); MoRTH chapter PDFs (https://morth.nic.in/sites/default/files/CMVR-chapter1_1.pdf, listed, not opened); MoRTH notifications list https://morth.gov.in | No | The Transport Department's "Central Motor Vehicle Rules 1989" link goes only to the MoRTH home page |
| 3 | **Motor Vehicles (Driving) Regulations, 2017** and amendments | India Code lists it (search result: https://www.indiacode.nic.in/handle/123456789/1362/simple-search?query=Motor+Vehicles+(Driving)+Regulations,+2017.&searchradio=regulation); Gazette of India: https://egazette.gov.in | No | Replacement for the Rules of the Road Regulations, 1989 (secondary evidence) |
| 4 | **Rules of the Road Regulations, 1989** | https://www.transport.telangana.gov.in/html/pdf/rules_of_the_road_regulations_1989.pdf (official page read) | Yes (not indexed) | Probably superseded by item 3 |
| 5 | **Telangana Motor Vehicles Rules, 1989**: amendment orders and Gazette originals | Telangana e-Gazette: https://tggazette.cgg.gov.in (official, listed); Government Order Issue Register: https://goir.telangana.gov.in (official, used for held G.O.s) | Partly (snapshot plus G.O.s 54 and 77 of 2025) | Missing: G.O.Ms.No. 02/2014, 41/2015, 44/2015, 95/2016, 26/2017, 52/2018 (Rule 81 chain), the reported Rule 72-A order, any other amendment, and the 1989 base text as gazetted |
| 6 | **Adaptation of the 1989 Andhra Pradesh rules to Telangana** | Not identified. Section 101 of the Andhra Pradesh Reorganisation Act, 2014 allowed adaptation within two years (secondary) | No | A CAG report (secondary) says the State MV Rules "have been adapted" without naming the order |
| 7 | **Telangana Motor Vehicles Taxation Act, 1963** (Act 5 of 1963) | Transport Department HTML page `https://transport.telangana.gov.in/html/acts-rules/main-ap-mv-ta-1963.htm` (official link listed on the page I read; not opened). Third-party copy on PRS (not authoritative) | No | The older manifest says "no text retrieved"; the official page link exists. Adaptation reportedly by G.O.Ms.No. 2, TR&B (secondary, CAG report) |
| 8 | **Telangana Motor Vehicles Taxation (Amendment) Act, 2026** (Act 8 of 2026) | Telangana Gazette (Part IV-A or Acts series); Bill 5 of 2026 is on PRS (third party) | No | G.O. 10/2026 confirms it comes into force on 1 March 2026. News reports describe a one-time road safety cess with conflicting amounts (secondary). Enacted text not held |
| 9 | Earlier Taxation-Act G.O.s: G.O.Ms.No. 22 of 07-05-2022 (Seventh Schedule), earlier Third and Sixth Schedule orders, G.O.Ms.No. 10 of 2014 and the 2021 EV exemption order (named in the summary PDF only) | GOIR | No | Needed to build the schedule history behind G.O.s 53/2025 and 16/2026 |
| 10 | **Compounding and penalty orders under s.200 MV Act** | GOIR and Transport Department site. Lead only: a 2020 order "21102020TRB MS21" appears on a third-party host (https://images.tv9telugu.com/wp-content/uploads/2020/10/21102020TRB_MS21.pdf; not opened, issuer and scope unverified). The summary PDF names G.O.Ms.No. 42 (July 2020), 54/2006, 242/2006, 334/2008, which are not located | No | Needed before any penalty answer. Applicability of pre-2014 Andhra Pradesh orders to Telangana is unestablished |
| 11 | **G.O.Ms.No. 26 (penalty-point system)**, per the summary PDF | Not searched | No | Possible number collision with G.O.Ms.No. 26 of 24-04-2017 in the Rule 81 chain |
| 12 | CMV Rules amending notifications relied on by held G.O.s: G.S.R. 48(E) of 20-01-2026 (Rule 167 changes) | MoRTH / e-Gazette | No | Needed to read G.O.s 24 and 25 correctly |
| 13 | Central notification S.O. 1306(E), 12 March 2024, registration mark for Telangana ("TG") | https://morth.gov.in/sites/default/files/notifications_document/8-SO 1306(E) 12 March 2024 TG registration mark Telangana.pdf (listed in a search result; not opened) | No | Related to registration numbers and the Rule 81 chain |
| 14 | Gazette prints for G.O.s 53, 77 (2025) and 10, 16, 24, 25, 32 (2026) | Telangana e-Gazette | No | The held copies are department G.O. copies; publication and effective dates are recorded as null for all of them |

Items **not investigated** and possibly relevant to later answers: Telangana notifications under ss.112 and 115 (speed limits, restrictions), Hyderabad and other Commissionerate traffic notifications, and Telangana High Court judgments (the manifest records none identified).

## 5. Amendment and version register

"Known" means named in a held official document or in a source labelled below. Nothing here declares any provision current.

### 5.1 Motor Vehicles Act, 1988 (not held)

| Event | Detail | Evidence |
|---|---|---|
| Original | Act 59 of 1988 | Cited in all held G.O.s |
| Amendment Act 32 of 2019 (9 Aug 2019) | Revised penalties, new ss.25A, 62A, 62B, 110A, 134A, 136A and others | Secondary (summary of India Code PDF, not opened) |
| Commencement notifications | S.O. 3110(E) of 28-08-2019 (many sections from 1 Sep 2019); S.O. 859(E) of 25-02-2022 (ss.50-57, 93); s.212 amendment shown as effective 1 Apr 2021 | Secondary; incomplete schedule |
| Earlier amendment | Act 3 of 2015 is the latest in the Delhi-hosted corpus copy | Earlier repo audit (27 Oct 2026) |
| Pending or reported | Jan Vishwas (Amendment of Provisions) Bill, 2026 (reported to amend about 20 provisions of the Act, including a licence-renewal grace period); a Motor Vehicles (Amendment) Bill, 2025 (reported). Status of both **unverified** | Secondary news; not checked against Parliament records |
| Gap | No official consolidated current text confirmed. The India Code page could not be read | |

### 5.2 Central Motor Vehicles Rules, 1989 (not held)

| Event | Detail | Evidence |
|---|---|---|
| Original | G.S.R. 590(E), 2 June 1989 | Secondary |
| Amendments | A long run of amending notifications to 2026, for example G.S.R. 152(E) (2014), 521(E) and 808(E) (2019), 858(E) (2022), 721(E) (2024); G.S.R. 48(E) of 20-01-2026 (Rule 167, cited in held G.O.s 24 and 25); Eighth Amendment Rules, G.S.R. 417(E), 25-05-2026; a draft G.S.R. 728(E) of 10-08-2026; a further amendment reported on 23-10-2026 | Mix of official G.O. text (G.S.R. 48(E)), earlier repo audit, and secondary summaries. India Code's amendment table (as seen in search results) ended around 2017, so it lags |
| Effective date detail | One secondary source dates the Eighth Amendment's effect from 29-05-2026, the gazette date being 25-05-2026 | Conflict, unresolved |
| Gap | No official consolidated text current to Nov 2026 confirmed | |

### 5.3 Telangana Motor Vehicles Rules, 1989 (held as HTML snapshot)

| Event | Detail | Evidence |
|---|---|---|
| Original | G.O.Ms.No. 216, TR&B (Tr.II), 07-08-1989; AP Gazette 25-08-1989 | G.O. 54/2025 and 77/2025 text (held) |
| Rule 81 chain | G.O.Ms.No. 02 (17-06-2014), 41 (29-09-2015), 44 (15-10-2015), 95 (08-12-2016), 26 (24-04-2017), 52 (11-04-2018): none held | Listed in the "read" lists of G.O.s 54/2025 and 77/2025 (held) |
| Rule 81, 2025 | G.O. 54/2025 (draft, 13-08-2025) then G.O. 77/2025 (final, 15-11-2025): omits sub-rules (1), (2), (4); substitutes (3) and (6) | Held and read |
| Rule 72-A | G.O.Ms.No. 41, 29-09-2015, reportedly inserts a new Rule 72-A and revises provisos of Rule 72 (stage carriage driver may act as conductor). The index has no Rule 72A | Secondary (blog reproductions) |
| Rule 217 | Revised by AP G.O.Ms.No. 332 of 13-11-2008 (held, not indexed). The indexed Rule 217 still shows pre-2008 amounts | Held G.O. and the manifest |
| Other | No other amendment is identified. The Telangana Transport Department page gives no amendment history. The snapshot cannot be assumed to include later amendments | Official page read |
| Effect | See the unresolved conflicts in 6.1 | |

### 5.4 Rules of the Road Regulations, 1989 (held, not indexed)

| Event | Detail | Evidence |
|---|---|---|
| Original | S.O. 439(E), 12-06-1989; in force 01-07-1989 | Held PDF footnote |
| Supersession | Motor Vehicles (Driving) Regulations, 2017, G.S.R. 634(E), 23-06-2017, "in supersession of the Rules of the Road Regulations, 1989"; effective on publication | Secondary (search summary quoting the notification; a Kerala Police circular and Vikaspedia page). The Gazette text was not read |
| Later amendment | G.S.R. 38(E), 15-01-2024 (Regulations 8 and 15) | Secondary, one compiled version |
| Transport Department | Still lists the 1989 PDF | Official page read |

### 5.5 Telangana Motor Vehicles Taxation Act, 1963, Rules, and 2025-26 orders

| Event | Detail | Evidence |
|---|---|---|
| Act 5 of 1963 | Adapted to Telangana, reportedly by G.O.Ms.No. 2, TR&B | Secondary (CAG report) |
| Third, Sixth, Seventh Schedules | G.O.Ms.No. 22 (07-05-2022) then G.O.Ms.No. 53 (13-08-2025, held) | G.O. text (held) |
| Seventh Schedule, 2026 | G.O.Ms.No. 16 (20-03-2026, held) removes the additional 2% | G.O. text (held) |
| Act 8 of 2026 | Introduced as Bill 5 of 2026 and reported passed 2 Jan 2026; commencement appointed as 1 March 2026 by G.O. 10/2026 | G.O. 10 text (held); bill history secondary |
| Taxation Rules, 1963 | Held snapshot, Rules 1-17 only in the index; adaptation and amendments unknown | |
| Gap | Whether G.O. 53/2025's schedules were modified other than by G.O. 16/2026 is unknown. Full Act text not held | |

## 6. Duplicate and conflicting versions, and record errors

### 6.1 Conflicts between indexed texts

1. **Rule 81 in two versions.** The indexed HTML Rule 81 and the indexed G.O. 77/2025 Para 4 both appear in retrieval. The HTML Rule 81(6) refers to sub-rules (3)(i), (ii), (iii) and (5); G.O. 77 substitutes sub-rule (6) over (3)(i) to (vii) and omits sub-rules (1), (2), (4). They agree on the "within 15 days" reservation period but differ on structure and on the special-number fee scale (the G.O. 77 scale runs from Rs 6,000 to Rs 1,50,000). Which text is current depends on whether G.O. 77 took effect and on the unheld 2014-2018 orders (counsel question 4).
2. **Rule 217** in the index is known to be pre-2008, and G.O. 332/2008 (held, not indexed) revises it.
3. **Taxation schedules.** G.O. 53/2025 and G.O. 16/2026 both amend the Seventh Schedule; five of seven chunks of G.O. 53 and one of two of G.O. 16 are excluded from answering for extraction reasons.
4. **Draft versus final.** G.O. 54/2025 (draft) is held but not indexed. G.O. 24/2026 is indexed but excluded and its draft/final status is unresolved.

### 6.2 Record errors and inconsistencies found

| # | Item | Detail |
|---|---|---|
| 1 | Manifest, G.O. 10/2026 | The manifest gives its "commencement" as 25-02-2026. The G.O. text is dated 25-02-2026 and appoints **1 March 2026** as the commencement date of Act 8 of 2026 |
| 2 | G.O. 54 vs G.O. 77 | G.O. 54/2025 describes the 1989 gazette publication as the Andhra Pradesh Gazette of 25-08-1989; G.O. 77/2025 calls the same publication the Telangana Gazette of 25-08-1989 |
| 3 | G.O.Ms.No. 41 of 29-09-2015 | Named in the Rule 81 chain (held G.O. text) and, in secondary blog reproductions, as the order inserting Rule 72-A. Whether one G.O. did both, or one source is wrong, is unresolved |
| 4 | G.O. number 26 | G.O.Ms.No. 26 of 24-04-2017 is in the Rule 81 chain; the summary PDF calls "G.O.Ms.No. 26" the penalty-point order. Unresolved |
| 5 | Manifest "Got/Read" columns | Show "No" for G.O.s 77/2025 and 10, 16, 24, 25, 32 of 2026, which are held. The summary PDF's recorded hash for G.O. 77 (`74a6839d...`) does not match the file held (`3de90735...`) |
| 6 | Manifest dating | Prepared 29-10-2026 but records events up to 09-11-2026 |
| 7 | Transport Department links | Its "TG Motor Vehicles Act/Rules" entries lead to an index page, and the CMV Rules entry leads to the MoRTH home page; neither is a document |
| 8 | 2008 order title | The title reads "Andhra Pradesh Motor Vehicles Rules Act, 1989 ... Motor Vehicles Act 1989" (the Acts are 1988) |
| 9 | Scope statement | The manifest says "Telangana-only decision 08-11-2026" yet the held G.O.s rely on central law |

### 6.3 Duplicates on disk

- The snapshot folder holds 49 files for the Rules (`top-`, `left-`, `main-` and `middle-` frames per chapter, plus index and 12 `middle-main-chap-N` text frames). Only the 12 `middle-main-chap` text frames and one taxation frame are indexed; the other frames repeat navigation content.
- The Gujarat packages under `docs/legal-sources/` are separate and not part of this register.

## 7. Recommended acquisition order

Order is by dependency: what the held, indexed Telangana documents rely on, and what the product's common questions need. It is a proposal, not a legal decision.

1. **Scope decision first** (owner, counsel): whether the Motor Vehicles Act, 1988 and Central Rules enter scope. The Telangana G.O.s already depend on them.
2. **Motor Vehicles Act, 1988**, consolidated, with the 2019 Act, commencement notifications, and any 2025-2026 amendment (status of the Jan Vishwas Bill to be confirmed). Needed for helmets, seat belts, speed, licences, offences, and the powers under ss.65, 86(5), 200 and 212 used by the Telangana orders.
3. **Central Motor Vehicles Rules, 1989**, consolidated, plus G.S.R. 48(E) of 20-01-2026 and the 2026 amendments. Needed to read G.O.s 24, 25 and 32 and equipment rules.
4. **Motor Vehicles (Driving) Regulations, 2017** and amendments; then retire the Rules of the Road Regulations, 1989 from consideration (counsel to confirm).
5. **Telangana Motor Vehicles Rules**: the six Rule 81 orders, the Rule 72-A order, any other amendment, the Gazette originals, and the adaptation instrument. Resolves the Rule 81 conflict and the snapshot's currency.
6. **Telangana compounding and penalty orders under s.200** (2020 order lead, G.O. 42/2020, 2006 orders, G.O. 26 penalty points). Required before any penalty answer.
7. **Taxation**, only if taxation questions are in scope: Act 5 of 1963 (official TD page), Act 8 of 2026, G.O. 22/2022 and earlier schedule orders, Taxation Rules in full.
8. **Gazette prints** for the seven held G.O.s, to set publication and effective dates.
9. Telangana traffic notifications (speed limits, restrictions) and case law, if counsel wants them.

## 8. Existing approval and quarantine status (no change made)

- Lifecycle registry (Stage 6): all 20 sources `pending`, `active_version: null`, bootstrap note "no signed approval exists; all sources quarantined".
- Text-status registry: 13 `unverified_snapshot`, 7 `official_text_commencement_unconfirmed`. Only a human reviewer may set `verified_current`.
- Index: 590 chunks, all `verification_status: unverified`; 576 `answer_eligible` and 14 not (eligibility is an extraction flag, not approval). `kb_approved` is false.
- No approval record, signature or trusted key exists, and none was created.

## 9. Questions for legal counsel

1. Is the Motor Vehicles Act, 1988 and the Central Motor Vehicles Rules in scope for answers, given the Telangana-only scope decision of 08-11-2026?
2. Which text of the Telangana Motor Vehicles Rules is authoritative: the Transport Department HTML, the AP Gazette original plus gazetted amendments, or a consolidation? What is the adaptation instrument?
3. Were the Rules of the Road Regulations, 1989 superseded in full by the Motor Vehicles (Driving) Regulations, 2017? Does any Telangana instrument keep them alive?
4. Which Rule 81 text applies today? Did G.O. 77/2025 take effect on publication, and how do the 2014-2018 orders interact with it?
5. Is G.O. 24/2026 a draft or a final notification, and when did it take effect?
6. Do G.O.s 24, 25 and 32 of 2026 depend on G.S.R. 48(E) (20-01-2026) as published, and are they in force on their dates?
7. Which compounding schedule under s.200 applies in Telangana, and do pre-2014 Andhra Pradesh orders (2006, 2008) still apply? Does Telangana apply the penalties of the 2019 Amendment Act?
8. Is G.O.Ms.No. 26 the penalty-point order, and is it the same as the 2017 Rule 81 order number?
9. Was G.O.Ms.No. 41 of 29-09-2015 the order that inserted Rule 72-A, the Rule 81 amendment, or both?
10. Are the life-tax schedules of G.O. 53/2025, as changed by G.O. 16/2026, in force, and are taxation and the Act 8 of 2026 cess in the product's scope?
11. Is a department G.O. copy from the register sufficient evidence, or is the Gazette print required for publication and effective dates?
12. Is a consolidated copy hosted by MoRTH, India Code or a state portal acceptable where no official Gazette consolidation exists, and who certifies currency?
13. Should case law (Telangana High Court) or police Commissionerate notifications be in scope?

## 10. What this audit does not establish

- It does not say which provisions are in force, correct or complete. Where amendment history is incomplete, the affected provisions are listed above and not declared current.
- External findings other than the Transport Department pages and the held files come from search summaries and are labelled secondary.
- No source here is approved. Acquisition, ingestion and approval need separate, explicit authorisation.
