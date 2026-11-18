# Telangana remediation plan

**Prepared:** 29 October 2026 · **Indexing: BLOCKED.**

## Order of work
1. **Retrieve the official files** (needs approval to download) into `source-documents/`, recording URL, date, size and SHA-256:
   - **GOIR:** G.O.Ms.No. 53, 54 and 77 of 2025; G.O.Ms.No. 10, 16, 24, 25 and 32 of 2026
   - **Transport Department:** `2008trb_ms332_compounding.pdf` and `rules_of_the_road_regulations_1989.pdf`
   - **HTML snapshots:** the TMVR 1989 chapters and the TMVTR 1963 pages
2. **Locate the missing instruments** through other official routes: the department, the Telangana Gazette, the GOIR archive, or India Code, which is reachable again:
   - the text of Act No. 8 of 2026
   - Act 5 of 1963
   - G.O.Ms.No. 42 of 2020
   - G.O.Ms.No. 26
   - the 2006 compounding G.O.s
   - the 2014 and 2021 exemption orders
   - the adaptation orders
3. **Read and record** each file: title, number, date, issuing authority, provisions and commencement. Update `SOURCE-MANIFEST.md`.
4. **Hand to counsel** for the decisions in `COUNSEL-CHECKLIST.md` and the Section 5 sign-off.
5. **Technical decision**, after approval: how Telangana is indexed (see below).
6. **Build through the staged workflow**, then validate.

## Technical preconditions for indexing (after legal approval)
- **Index scope: decided, Telangana only (user, 08-11-2026).**
  - Build a separate Telangana-only collection or directory, holding Telangana state instruments only, with no Central texts.
  - The server must then retrieve from Telangana only. Today `retrieve_for_state` always adds Central chunks, so that needs a reviewed code change.
  - It must say plainly that other states and Central law aren't covered.
  - The existing shared index is left untouched.
- **File list and labels.** Add the approved Telangana files to the file list with `state="Telangana"`, and add verified titles to `SOURCES` in `backend/server.py`. Without them, citations show "Unverified source".
- **Chunking for HTML.** HTML sources need a loader, because the builder only loads PDFs today.
- **Tests.** Cover the file list, titles, and Telangana retrieval with a state filter, using fixtures, not legal text.
- **Retrieval profile.** If the `structured` retrieval profile (branch `comp-rag-optimization`) is adopted, recalibrate its relevance gate on the approved corpus.
- **Validation after the build:**
  - chunk counts per file
  - `state` metadata
  - Telangana questions retrieve only Telangana and Central chunks
  - citations show verified titles
  - penalty answers carry the "date not verified" note

## Status
- **Step 1:** partly done. Three PDFs and two HTML snapshots are retrieved.
- **Still to retrieve:** seven GOIR G.O.s. They need a person to click Download in the register, because the browser blocked repeated automatic downloads.
- **Steps 2–6:** not started.

**No index was built or changed.**
