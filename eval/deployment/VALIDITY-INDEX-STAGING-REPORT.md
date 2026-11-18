# Validity-date index preparation: staging report

Scope: manifest schema, ingestion, lifecycle and retrieval now understand `valid_from` / `valid_to`; a staging index was
built and compared with the manifest. No production index was replaced. No legal date was entered. No approval record,
schema or signature was touched. Nothing committed, pushed or deployed.

## 1. Verdict

The code is ready for a safe rebuild. The data is not: **all 20 manifest sources have unknown validity**, so a rebuild today
produces 590 unversioned chunks and every dated question stays refused (the intended fail-closed result).
A rebuild becomes useful only after counsel-verified dates are entered in the manifest.

## 2. What changed

| Area | Change |
|---|---|
| Manifest (`tg_manifest.py`) | Optional keys `valid_from`, `valid_to` (int YYYYMMDD), `validity_status` (`unknown` / `verified_continuing` / `verified_closed`), `validity_basis` (evidence, required whenever dates are set). Omitted = `unknown`. Existing manifests parse unchanged. |
| Rules enforced | Dates need a verified status; `99991231` only with `verified_continuing`; closed needs a real end date; real calendar dates, ints only (no strings, bools, floats); `valid_from <= valid_to`; basis required. |
| Ingestion (`tg_ingest.py`) | Chunk metadata always has `validity_status`; `valid_from`/`valid_to` only when verified. Unknown = both keys absent (Chroma cannot store None), which the router reads as unversioned. `effective_date` is never used as a validity date. |
| Build (`build_telangana_index.py`) | `verify_staging` also fails the build on malformed ranges, chunks that disagree with the manifest, or documents with no chunks. |
| `index_validity.py` (new) | Chunk checks and the index-vs-manifest report (versioned / unversioned / flagged-unknown counts). |
| Lifecycle (`document_lifecycle.py`) | Registry versions record validity. A superseded version stays in the index **as history** only if it was once approved and has a verified closed range; otherwise it leaves the index as before. `servable_hashes` is unchanged (active approved version only), so history is never current law. New `close_validity(source, version, valid_to, basis, by)`: audited, evidence required, only from `verified_continuing`, a closed range is never edited; updates index rows in place or brings a superseded version back as history. Overlapping retained ranges are refused at approve, rollback and close. `ServeFilter.servable_on(sha, dated)` adds history for dated questions only; count mismatch still closes it. Health reports `historical_documents`. |
| Retrieval (`server.py`, `offence_date.py`) | Undated questions drop chunks whose range ended, has not begun, or is malformed (`in_force_today`); unversioned chunks behave as before. Dated questions may use history, then route by each chunk's own range. Two versions of one provision both claiming the date cancel out (`conflicts`, `CONFLICT_NOTE`). The signed-approval check (`SOURCES`) applies to history too: an unapproved historical file is never served. |

The `historical_legal_explanations` release gate is untouched and still blocks historical answers in `/chat` without a valid signed approval. Penalty and compounding locks are untouched.

## 3. Staging build and comparison

Built with the real embedder (`nomic-embed-text`) into `chroma_telangana_staging_validity/` (git-ignored), from
`docs/legal-sources/telangana-traffic/DRAFT-telangana-manifest.json`, `--preview-unapproved`, with `PREVIEW-CHUNK-FLAGS.json`.
It is a separate directory; no existing index or snapshot was opened for writing.
Compare with: `python3 scripts/compare_staging_validity.py --manifest <manifest> --db-dir chroma_telangana_staging_validity`.

- 590 chunks, 20 documents, 0 chunks outside the manifest, 0 manifest documents without chunks.
- Inconsistencies between index and manifest: **0**.
- Validity: 0 versioned, 590 unversioned. All 20 sources flagged `unknown`: tmvr-1989-chap-1 to -12, tmvtr-1963, go-ms-53-2025-trb, go-ms-77-2025-trb, go-ms-10-2026-trb, go-ms-16-2026-trb, go-ms-24-2026-trb, go-ms-25-2026-trb, go-ms-32-2026-trb.
- Retrieval, 5 sample queries, top 8 each: undated 8/8 usable as current law (unchanged behaviour); for each of 2018-05-01, 2022-03-10 and 2026-09-01: 0 authoritative, 8 unverified, 0 dropped. So a dated question gets "cannot confirm the law for that date", not an answer from undated text.
- Missing dates: all 20. Inconsistent dates: none.

## 4. Ready for a safe rebuild, and not

Ready:
- Schema, build-time validation, lifecycle history, overlap refusal, retrieval and approval checks, with tests.
- A rebuild from the current manifest is safe: same chunks plus `validity_status: unknown`; undated behaviour unchanged.

Not ready (needs people, not code):
1. Counsel-verified `valid_from` / `valid_to` / `validity_basis` for each source. Several G.O. notes in the manifest mention commencement dates (for example G.O.Ms.No. 10 of 2026); these are drafts of unreviewed notes and were **not** copied. The 1989 rules snapshots are noted as outdated and unverified, so they likely stay `unknown`.
2. Closing dates for any superseded text, entered through `close_validity` with evidence.
3. Fingerprint and cache epoch change on rebuild: publish a new snapshot and re-run the approval refresh. The signed approval binds file hashes, not chunk metadata, so approval is not invalidated by this change but must be re-checked.
4. The live lifecycle registry has no validity fields for existing versions (treated as unknown). Entering dates there means re-ingesting versions or using `close_validity`; existing registries load unchanged.

## 5. Known limits

- Versions are linked by manifest `id`. Two different manifest ids covering the same provision are not detected as overlapping.
- The registry is the authority for which versions are kept; chunk metadata is the authority for dates at query time. Registry/chunk date drift is prevented at ingest and by `close_validity`, not re-checked at serve time.
- `close_validity` has no CLI command yet; it is a library call.
- Historical answers in `/chat` still need the `historical_legal_explanations` gate opened by a signed approval.
- The 106 skipped tests were not run.
