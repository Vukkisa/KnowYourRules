# Stage 19: legal source integrity and provenance

**Integrity correction made:** G.O.Ms.No. 77/2025's SHA-256 has been added to `SHA256SUMS`, and the source manifest records it.
- No retrieval, answer-generation, index, benchmark, CSV or approval changes. No Groq or external calls; nothing committed.
- Data: [`stage-19-source-provenance.json`](stage-19-source-provenance.json); reviewer note: [`stage-19-review-questions.md`](stage-19-review-questions.md).

## Changed files
All source paths are in the main checkout under `docs/legal-sources/telangana-traffic/`, which is untracked.

| File | Change | Rollback |
|---|---|---|
| `source-documents/SHA256SUMS` | Appended `3de90735…be71  ./goir/2025TRB_Ms77.pdf`; now 58 lines | `stage-19-originals/SHA256SUMS.pre-stage-19` |
| `SOURCE-MANIFEST.md` | Added a file-table row for G.O. 77. Added an update note above the stale "Not retrieved" paragraph, which is kept as the original record | `stage-19-originals/SOURCE-MANIFEST.md.pre-stage-19` |
| `eval/legal-validation/` | 3 new deliverables, plus the backups above | n/a |

The PDF itself and `DRAFT-telangana-manifest.json` are unchanged.

## 1. Source integrity: verified facts
**Before Stage 19**
- All 57 entries in `SHA256SUMS` verified.
- Six G.O. PDFs were present but unlisted: No. 77/2025 and Nos. 10, 16, 24, 25 and 32 of 2026.

**G.O. 77 file**
- **Path and size:** `source-documents/goir/2025TRB_Ms77.pdf`, 33,646 bytes, 3 pages.
- **SHA-256:** `3de907353bdf37415df25f10d45b05e336bd29c077285fae2c9bda2655f7be71`.
- **The hash is consistent across records:**
  - it equals the hash in `DRAFT-telangana-manifest.json`;
  - that manifest is the source of the 12 indexed `go-ms-77-2025-trb` chunks;
  - the ingestion report (section 7) records the user downloading the file from goir.telangana.gov.in on 09-11-2026.
- **Download origin:** macOS metadata (`kMDItemWhereFroms`) shows `https://goir.telangana.gov.in/Default.aspx`.
- **File timestamps:** PDF created 03-11-2025 and modified 15-11-2025, which matches the G.O. date.
- **Classification:** the original file as served by the official GOIR register, not a derived copy. It is **not digitally signed** and **not a Gazette print**.

**Convention**
- `SOURCE-MANIFEST.md` states "every SHA-256 is listed in `source-documents/SHA256SUMS`". G.O. 54 was appended in the same `<sha>  ./goir/<file>` format.
- So adding G.O. 77 restores that rule; it does not create a new practice.

**Validation after the change**
- `shasum -c`: 58/58 OK.
- `backend.source_compare checksums`: `{"ok": 58, "mismatch": 0, "missing": 0}`.

**Not verifiable**
- Authenticity rests only on the download origin.
- An earlier summary recorded a different file, `TMVR-1989-GO77-2025.pdf` (SHA-256 `74a6839d…`). That file is absent and cannot be compared (gap G1).

**Left unchanged:** the five 2026 G.O. PDFs are still unlisted in `SHA256SUMS`, though their hashes are in the draft manifest. They are the same kind of gap and were left out of scope for this stage.

## 2. Earlier amendment provenance
G.O. 77 (and G.O. 54) cite six earlier TR&B (Tr-I) orders:
- G.O.Ms.No. 02 (17-06-2014)
- G.O.Ms.No. 41 (29-09-2015)
- G.O.Ms.No. 44 (15-10-2015)
- G.O.Ms.No. 95 (08-12-2016)
- G.O.Ms.No. 26 (24-04-2017)
- G.O.Ms.No. 52 (11-04-2018)

**None of them exists anywhere in either checkout.** Their relationship to Rule 81 is only that they are cited in the "Read" list of the Rule 81 amendment orders; whether and how each one amended Rule 81 is not stated. Nothing was retrieved or inferred.

## 3. Rule 81 version status
| Element | Status |
|---|---|
| Snapshot (TMVR chapter 4, retrieved 29-10-2026) | Held but unverified. Sub-rules (1)–(6), Form RRMA, fees from Rs. 50,000 to Rs. 5,000. Which amendments it reflects is unknown |
| G.O. 77 changes | Held (official GOIR PDF). Omits (1), (2) and (4); substitutes (3) (online applications, fees from Rs. 1,50,000 to Rs. 6,000, or Rs. 3,000 for two-wheelers), (5) (online bidding) and (6) (allotment and cancellation) |
| Commencement | **Unknown.** There is no commencement clause; it only directs Gazette publication dated 15.11.2025 |
| Gazette evidence | **Missing** for G.O. 77, and for G.O. 54 (G-575, 13.08.2025) |
| 2014–2018 amendments | **Missing**: the six G.O.s above |
| Amendments after November 2025 | **Unknown**; not checked against any source |
| Consolidated Rule 81 | **Not produced**: it needs authoritative sources and human legal approval |
| Snapshot | Not replaced. It stays indexed unchanged and **must not be presented as current** |

## 4. Benchmark review package
See `stage-19-review-questions.md`. It covers six questions:
- **TG-PQ-002:** whether to add Rule 15, whether to keep Rule 14, and whether Rules 19 and 24 belong.
- **TG-GO-007:** whether Paragraph 2 is needed, what the "Paragraph 4" chunk really is (amendment item 4), and how to treat the old snapshot.

Nothing was applied.

## 5. Validation
- **Checksums:** 58/58 OK with `shasum`, and 58 OK with `source_compare`.
- **Tests:** full suite OK by default and OK with `RAG_VECTOR_SEARCH=hnsw` (672 tests).
- **Retrieval baseline unchanged:** Stage 17's recall@5 0.9726, MRR 0.8907 and hit@5 1.000. No retrieval code was touched.

## Unresolved legal questions (human review required)
1. Was G.O. 77 published in the Gazette on 15.11.2025, and when did it come into force?
2. What did G.O.s 02/2014, 41/2015, 44/2015, 95/2016, 26/2017 and 52/2018 change in Rule 81, and does the snapshot reflect them?
3. Has Rule 81 been amended after 15-11-2025?
4. What is the authoritative consolidated text of Rule 81? It needs counsel approval before anything replaces or flags the snapshot.
5. Is the absent `TMVR-1989-GO77-2025.pdf` (`74a6839d…`) a different version of G.O. 77?
6. Should the five unlisted 2026 G.O. PDFs be added to `SHA256SUMS` in the same way?
