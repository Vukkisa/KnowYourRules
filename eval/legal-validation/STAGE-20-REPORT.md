# Stage 20: legal source inventory reconciliation

**Note:** the Stage 20 request text ended partway through step 3 ("Search both checkouts and all existing source inventories"). Steps 1–3 are done, and the deliverables follow the Stage 19 pattern:
- this report;
- [`stage-20-source-inventory.json`](stage-20-source-inventory.json).

**Results**
- All 63 source files are now checksummed: `shasum -c` gives 63/63 OK, and `source_compare` gives 63 OK, 0 mismatched, 0 missing.
- 672 tests pass in both exact and HNSW modes.
- No legal text, retrieval, index, benchmark, CSV or approval changes. No external calls; nothing committed.

## Changed files
In the main checkout under `docs/legal-sources/telangana-traffic/` (untracked). Backups are in `stage-20-originals/`.

| File | Change |
|---|---|
| `source-documents/SHA256SUMS` | 5 lines appended, for the 2026 G.O.s (58 → 63) |
| `SOURCE-MANIFEST.md` | 5 file-table rows added. The Stage 19 note now says that all six GOIR downloads are checksummed |

## 1. Discrepancies before this stage
Disk holds 63 source files (excluding `SHA256SUMS` and `.DS_Store`), 10 of them PDFs.

| Category | Files |
|---|---|
| Present and checksummed | 58: 53 HTML snapshots; GOIR No. 53, 54 and 77; 2 Transport Department PDFs |
| **Present, not checksummed** | **5:** GOIR 2026 Nos. 10, 16, 24, 25 and 32 (now fixed) |
| Checksum or manifest entry with no file | None |
| Present but not in the draft manifest | G.O. 54 (deliberately excluded as a draft that No. 77 superseded); the two Transport Department PDFs (no reason recorded); the HTML index and left-hand frame files (by design) |
| Present but not in the `SOURCE-MANIFEST.md` file table | The 5 G.O.s from 2026 (now fixed) |
| Duplicate IDs or content; mismatch between draft manifest and disk | None |
| Conflicting identity | **G.O. 77:** the supplied summary records `TMVR-1989-GO77-2025.pdf` (`74a6839d…`). That file is absent, and its hash differs from the held file (`3de90735…`). Unresolved (gap G1) |
| Outside `source-documents/` | `supplied/…Legal_Review_Summary.pdf`: a secondary summary, not a legal source |

## 2. The five 2026 G.O.s
All five share the following:
- downloaded by the user from GOIR on 09-11-2026 (ingestion report, section 7);
- macOS download origin `goir.telangana.gov.in`;
- SHA-256 equal to the draft manifest's;
- not digitally signed, and no Gazette print is held.

**The checksums record file integrity only, not legal status.**

| File | G.O. and date | Type (from its own text) |
|---|---|---|
| `2026TRB_Ms10.pdf`, 28,107 B, `df0ee935…` | No. 10, 25-02-2026 | Commencement notification for Act No. 8 of 2026. The Act itself is not held |
| `2026TRB_Ms16.pdf`, 19,604 B, `139f9645…` | No. 16, 20-03-2026 | Notification amending the Seventh Schedule of the TMVT Act. Its text says it is in force from 23-03-2026 |
| `2026TRB_Ms24.pdf`, 35,456 B, `ba0c9516…` | No. 24, 01-06-2026 | CMV Rule 167 notification (challan disposal authorities). **Draft or final is unresolved:** the order says it "decided to publish the draft Notification", but the notification comes into force on publication |
| `2026TRB_Ms25.pdf`, 26,515 B, `c9bd1ff3…` | No. 25, 01-06-2026 | CMV Rule 167 notification (electronic challans) |
| `2026TRB_Ms32.pdf`, 21,096 B, `4bb6273f…` | No. 32, 30-06-2026 | Order notifying a Designated Authority under CMV Rule 167A(1) |

## 3. The six missing G.O.s (Rule 81)
The orders are G.O.Ms.No. 02 (17-06-2014), 41 (29-09-2015), 44 (15-10-2015), 95 (08-12-2016), 26 (24-04-2017) and 52 (11-04-2018).

**Searched:**
- every file in both checkouts, by date string;
- all PDFs;
- `SHA256SUMS`, the draft manifest and `SOURCE-MANIFEST.md`;
- the supplied summary.

**Result:** only citations were found, in G.O. 54 and 77, the manifest and the eval files. **There is no copy of any of the six.**
- The summary's `TMVTA-1963-GOMS10-2014` is G.O.Ms.No. 10 of 2014 (a tax exemption), not No. 02 of 2014.
- Their effect on Rule 81 is unknown; they are only cited in the "Read" lists.

## Verified facts vs unresolved questions
**Verified**
- The identity, size, hash and download origin of all 10 PDFs.
- No hash conflicts between disk, `SHA256SUMS` and the draft manifest.

**Unresolved (human review)**
- G.O. 24: draft or final?
- Gazette publication and commencement of G.O. 77, 24, 25 and 32.
- The content of the six missing Rule 81 orders.
- The conflicting G.O. 77 identity (`74a6839d…`).
- Why the two Transport Department PDFs are not in the draft manifest.
- The pending "superseded in part" flag on G.O. 53's Seventh Schedule chunk after G.O. 16.
- Rule 81's currency remains unresolved; the snapshot must not be presented as current.
