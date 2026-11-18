# Stage 8: ingester heading defect and Rule 81 version defect

Investigation only. Nothing in the corpus, sources, manifest, chunk flags, approval data, benchmark labels, Chroma
index, retrieval pipeline or answer generation was changed. The proposed parser fix is a diff that has **not**
been applied ([`proposed-heading-fix.diff`](proposed-heading-fix.diff)). **No statement here is a finding that any
provision is legally current.** A text match only shows fidelity to a local file.

## Summary
| # | Defect | Layer | Root cause | Fix |
|---|---|---|---|---|
| 1 | TMVR 186, TMVR 295-A, TMVTR 12-B and TMVTR 13 are folded into the rule before them | Provision identity and chunking | The heading has no full stop after its number, and no pattern in `PROVISION_PATTERNS` accepts that | Narrow fallback pattern plus a sequence gate (diff ready, not applied) |
| 2 | The TMVR Rule 81 snapshot predates G.O. 77 and ranks first | Amendment and version handling | The project has no model of amendments: no `amends` or `superseded_by` link, `effective_date` is null for all 20 documents, and retrieval has no rule for picking a version | Auditable amendment register plus warnings or eligibility at build time (proposal) |

The parser fix can ship on its own; see the Recommendation section.

---

## Part A: heading recognition

### How it works now (`backend/tg_ingest.py`)
- `segment()` starts a new provision when the first line of a block matches `match_provision()` **and** its number is higher than the last one (`_number_key(n) > last_key`). The monotonic check stops list items that count backwards.
- `PROVISION_PATTERNS`:
  1. `NNN.` or `NNN-A.`, with an optional `Rule`/`Section` prefix and a title starting with a capital letter. **It needs the full stop.**
  2. `Rule NNN Title`, which needs the word `Rule`, `Section` or `Regulation`.
  3. `NNN-A Title`, which needs a hyphenated letter suffix.
- So a bare `NNN Title` or `NNN (1) Title` matches no pattern, and the line stays in the previous provision.
- Can the current parser tell these apart?

| Line type | Example | Handled? |
|---|---|---|
| New rule heading with a full stop | `187. Conditions of permit ... :-` | yes |
| New rule heading without a full stop | `186 (1) Conditions of permit ... :-` | **no**; it is merged into the previous rule |
| Sub-rule or clause | `(2) ...`, `(xii) ...` | yes; patterns 1 to 3 never match a line starting with `(` |
| Numbered list item, counting backwards | `1. ...` inside Rule 40 | yes; the monotonic check |
| Numbered list item, counting forwards | `7. ...` inside Rule 5 | **would be treated as Rule 7**; no case found in the current sources (the gap check below found no spurious rule) |
| Number in a table or list body | `408 Cms. to 432 Cms` (Rule 334) | yes; no full stop straight after the number |
| Cross-reference at the start of a line | `Rule 190 shall apply ...` | **would match pattern 2** if 190 is higher than the last rule; none found in the current sources |
| G.O. citation | `Rule 167A(1) of ...` in a G.O. | yes; `G.O.` documents drop prefixed matches |

### Survey of all 13 `Rules` documents
I ran the ingester's own `load_blocks` and `segment`, read-only, over every TMVR chapter and the TMVTR (scripts in Reproduce).
- **Number gaps** in the recognised rules: only one, `185 -> 187` in chapter 5.
- **Numbered lines held inside another rule whose number is higher than that rule's** (candidate missed headings):

| Document | Absorbed into | Line in the source | Anchor | Real heading? |
|---|---|---|---|---|
| tmvr-1989-chap-5 | Rule 185 | `186 (1) Conditions of permit in respect of a luxury tourist cab :-` | `#58` | yes |
| tmvr-1989-chap-5 | Rule 295 | `295-A . Painting of goods carriages carrying dangerous or hazardous goods:-` | `#169` | yes (space before the full stop) |
| tmvtr-1963 | Rule 12A | `12-B : - Whereby a notification ...` (no title in the source) | `#13` | yes |
| tmvtr-1963 | Rule 12A | `13 Rates of penalty : - If the tax due ...` | `#14` | yes |
| tmvr-1989-chap-7 | Rule 334 | `408 Cms. to 432 Cms` (and 433, 497, 535) | `#25` | no; a measurement table |

- The gap check missed 295-A, 12-B and 13. 295-A and 12-B are lettered insertions, and `12A -> 13A` looks continuous.
- **TMVTR Rule 13 (Rates of penalty) is as invisible as Rule 186.** A question about it hits the missing-provision guard.
- Each real missed heading has its own `<a name>` anchor in the source page, so the HTML independently marks them as separate rules.

### Proposed minimal fix ([`proposed-heading-fix.diff`](proposed-heading-fix.diff), 20 added lines, not applied)
- Add a fallback, `UNPUNCTUATED_HEADING_RE`. It is tried only when no existing pattern matches, only outside G.O.s, schedules and forms, and only if **both** of these hold:
  1. The line has the heading terminator `:-` or `: -` after an optional `-A`, ` .` and `(1)`.
  2. The number is **the next in sequence** (`_next_in_sequence`): N+1 with no suffix, or the same N with the next letter (186 after 185, 295A after 295, 12B after 12A, 13 after 12B).
- Existing patterns and behaviour are unchanged. The gate rejects measurement lines (no `:-`) and forward list items (not N+1).

**Measured effect.** I segmented all 20 manifest documents with the original and the patched parser:

| | Before | After |
|---|---|---|
| Total chunks | 586 (identical to the current index) | 590 |
| Provisions changed | | Rule 186 and 295A added (chap-5); Rule 12B and 13 added (TMVTR); Rules 185, 295 and 12A shortened |
| Every other document and provision | | identical (block counts and identifiers) |
| Rule 185 | 6 parts; parts 5 and 6 hold Rule 186 text (`#57 .. #58`) | 5 parts, all `#57` |
| Rule 186 | absent | 2 parts, `#58`, heading "Conditions of permit in respect of a luxury tourist cab" |

**Text check** with `source_compare.compare`:
- Every new or changed chunk is `verbatim` against the official snapshot, except **295A and 12B**. Those two match only `ignoring_whitespace`: the source splits `295 -A` and `12 -B` across tags.
- The same difference already existed inside the old Rule 295 and Rule 12A chunks.
- So the fix changes provision **identity** and leaves the **text** unchanged.
- **Rule 12B** has an empty heading because the source gives it none. It should be flagged for review, not given an invented title.

### Tests ([`tests/test_tg_ingest_headings.py`](../../tests/test_tg_ingest_headings.py), 10 tests, synthetic)
- **7 behaviour tests that must still pass after any fix:**
  - 185 and 187 headings are recognised;
  - sub-rules and clauses never open a provision;
  - backward list items stay inside the rule;
  - measurement lines (`408 Cms. to 432 Cms`) are not headings;
  - `12-A.` insertions work;
  - G.O. paragraphs are never Rules;
  - the HTML anchor is kept.
- **3 `expectedFailure` tests that record the defect:** Rule 186; `295-A .`; `12-B : -` followed by `13 Title : -`.
- The tests ran in two places:
  - **Current worktree:** the full suite of 618 tests passes, with 3 expected failures.
  - **Scratch copy with the diff applied:**
    - The 3 defect tests report *unexpected success*. When the fix is applied, their decorators must be removed.
    - All 7 behaviour tests pass, and so does `test_tg_ingest.py`.
    - One failure is unrelated: `test_real_groq_eval…file_state` needs a `.git` directory, which the copy lacks.

---

## Part B: amendments and versions (Rule 81)

### How Rule 81 enters the index
- `tmvr-1989-chap-4`: Transport Department snapshot `middle-main-chap-4.htm#4`, retrieved 29-10-2026.
  - It is consolidated web text with no amendment dates.
  - `Rule 81` part 1 has sub-rules (1) to (5), with fees from Rs.1000 to Rs.50,000. Part 2 has sub-rule (6), which refers to "(3) (i), (ii) and (iii)".
- `go-ms-77-2025-trb`: the G.O. PDF from GOIR, chunked as Preamble, References, Order and Paragraphs 2 to 4.
  - "Paragraph 4" is actually amendment item 4. See batch 1.
- G.O. 54/2025, the **preliminary** (draft) notification of the same amendment, is in `goir/` but **not in the manifest**, so it is not indexed. That is correct, and it must stay that way.

### Why the stale text ranks first
- When a question names "Rule 81", `server.provision_lookup` puts the **exact** `tmvr-1989-chap-4::Rule 81` chunks at the head of the lookup list.
- `reciprocal_rank_fusion` then fuses the lookup, BM25 and vector lists. Both Rule 81 chunks are first in the lookup list and are also matched by BM25 on "Rule 81".
- The amendment cannot be pulled in or preferred, for three reasons:
  - **No link.** No manifest field or chunk metadata says G.O. 77 amends TMVR Rule 81 (the manifest schema has no `amends` or `superseded_by` field).
  - **No dates.** `effective_date` and `publication_date` are null for all 20 documents, and the index metadata `effective_date` is `""` on all 586 chunks.
  - **No version rule.** `hybrid_retrieval` and `server` contain no logic about supersession, recency or version, and nothing in the backend reads `effective_date`.
- So retrieval behaves exactly as designed. The defect is missing data and missing policy, not a ranking bug.

### Can G.O. 77 reconstruct the amended Rule 81?
G.O. 77, text checked with `pdftotext`, does the following "in rule 81":
1. omits sub-rules (1), (2) and (4);
2. substitutes sub-rule (3), with a seven-tier fee table from Rs.1,50,000 down to Rs.6,000, a two-wheeler fee of Rs.3000, a current-number proviso of Rs.2000, and an online-only application (viii);
3. substitutes sub-rule (5), with online bidding in clauses (i) to (iv);
4. substitutes sub-rule (6).

The snapshot has sub-rules (1) to (6) and no more. Taken mechanically, every surviving sub-rule, (3), (5) and (6), comes **entirely from G.O. 77**. That makes the amended text technically constructible. It is **not legally established**, for four reasons:
- The snapshot's base is unverified. G.O. 77 cites earlier amendments (G.O.s 02/2014, 41/2015, 44/2015, 95/2016, 26/2017 and 52/2018) that are not held. It is unknown whether the snapshot reflects them, or whether Rule 81 had sub-rules beyond (6) or different numbering at 15-11-2025.
- Commencement is unknown. G.O. 77 directs publication in the Gazette dated 15.11.2025 but gives no separate commencement date, and the Gazette print is not held.
- Later amendments after 15-11-2025 have not been searched for.
- The heading and any provisos outside the sub-rules are not addressed by the G.O.

**Do not generate a consolidated Rule 81** without legal review of these four points.

### Other provisions possibly affected (not assumed outdated)
| Instrument in corpus | Amending or related instrument | Held? | Status |
|---|---|---|---|
| TMVR Rule 81 | G.O. 77/2025 | yes | snapshot predates the amendment (confirmed above) |
| TMVR Rule 217 | (not identified) | no | the manifest note already says the pre-2008 amounts are known to be outdated |
| Third, Sixth and Seventh Schedules of the TMVT **Act** | G.O. 53/2025; G.O. 16/2026 (also cites G.O. 22/2022) | G.O.s yes; G.O. 22/2022 and the Act no | the schedules exist only as G.O. chunks. The latest G.O. 16 amends a text that is not held |
| TMVT Act | Act No. 8 of 2026 (commencement: G.O. 10/2026) | Act no | NEEDS_SOURCE (batch 1, GO-006) |
| All other TMVR and TMVTR rules | unknown | n/a | snapshots carry no amendment history, so currency is **unknown**, not confirmed |

G.O.s 24, 25 and 32 act under central CMVR Rule 167 or 167A and amend no Telangana provision in the corpus.

### Proposed minimal, auditable versioning strategy
1. **Amendment register** (new reviewed data file, e.g. `amendments.json`, kept beside the manifest and signed with it). One record per amending instruction:
   - `amending_id`, `item` (for example "G.O. 77 item 2");
   - `target` (for example `tmvr-1989-chap-4::Rule 81`), `sub_units` (`(1)`, `(2)`, `(4)`), `action` (`omit`, `substitute` or `insert`);
   - `gazette_date`, `commencement` (null if unknown), `evidence` (file, page, quote);
   - `reviewer`, `status`.
   It is written by people, never inferred.
2. **Build-time effect, with no text rewriting.** For each target with a reviewed `omit` or `substitute` record, `build_telangana_index` adds an `extraction_warning` naming the amending G.O. It also sets `amended_by` metadata, for example "Rule 81 (1), (2), (4) omitted and (3), (5), (6) substituted by G.O.Ms.No. 77/2025".
   - A policy decision, made by people, chooses between two treatments of the stale chunk: warn but keep it eligible, or set `answer_eligible=false`.
   - This reuses the existing `PREVIEW-CHUNK-FLAGS.json` path, so retrieval and answer generation need no change.
3. **Lookup expansion (later, separate change).** When an exact lookup hits a target with `amended_by`, the amending chunks are appended to the lookup list, so the G.O. text is always in context next to the old text.
4. **Consolidated text (only after legal sign-off).** Add a separate `source_class: "consolidated_by_reviewer"` document with its own provenance, never overwriting the official snapshot.

---

## Part C: impact assessment, by layer

| Item | Source text | Identity and chunking | Amendment and version | Retrieval ranking | Benchmark label |
|---|---|---|---|---|---|
| Rule 185 | matches (all 6 parts verbatim) | **wrong**: parts 5 and 6 are Rule 186 | unknown | GC-002 PASS (top 1 is part 1) | GC-002 correct; its expected chunk will be "part 1 of 5" after the fix |
| Rule 186 | matches (inside the 185 chunks; after the fix, 2 parts verbatim) | **missing**: the text is filed as Rule 185 | unknown | text retrievable only as "Rule 185" | MP-001 to 003 **wrong** (`missing_provision`) |
| Rule 81 | matches the snapshot | correct | **outdated** against G.O. 77 | stale chunk ranks 1st (GO-007) | no row asks about the fee or procedure, a coverage gap |
| TG-MP-001 | n/a | caused by defect 1 | n/a | n/a (guard) | wrong; proposed `retrieve` with Rule 186 |
| TG-MP-002 / 003 | n/a | same | n/a | n/a | same (not human-reviewed) |
| TG-MP-004 (185, 186, 187) | n/a | same | n/a | n/a | likely `retrieve` for all three |
| TG-MP-005 (186, 188) | n/a | same | n/a | n/a | likely `retrieve` |
| TG-PN-005 (fine under 186) | n/a | same | n/a | n/a | `restricted` is probably still right, but the missing-provision basis is wrong |
| TG-GO-007 | matches (Para 3 after removing pipes) | "Paragraph 4" is mislabelled | stale Rule 81 at rank 1 | Para 2 not in top 5 (minor) | over-broad |
| TG-GO-008 / 009 | not compared | unaffected | unaffected (they ask about the G.O., not the rule) | PASS | not reviewed |
| TG-GC-003 (TMVTR 13A) | n/a | its neighbours 12A, 12B and 13 change; 13A does not | n/a | PASS; unchanged | correct |

There is no benchmark row for TMVTR Rule 13, 12-B or TMVR 295-A, so their defect is invisible to the benchmark.

**Other files that encode the wrong premise** (not changed):
- `PREVIEW-CHUNK-FLAGS.json` attaches a reviewer warning to TMVR Rule 185 **and** Rule 187: *"rule 186 is listed in the chapter contents but absent from this snapshot's text"*. **The snapshot does contain it**, at line 752, anchor `#58`. Every answer citing Rule 185 or 187 currently carries this incorrect warning.
- `tests/test_server.py` (lines 653 to 697, 919) and `tests/test_grounded_answer.py:313-317` use "Rule 186" as the stock *missing* rule. They run on synthetic fixtures, so they pass either way, but after the fix they would be misleading. A truly absent number such as 999 would be better.

---

## Files that would change for the approved fixes
**Parser fix:**
1. `backend/tg_ingest.py`: apply `proposed-heading-fix.diff`.
2. `tests/test_tg_ingest_headings.py`: remove the three `expectedFailure` decorators.
3. `docs/legal-sources/telangana-traffic/PREVIEW-CHUNK-FLAGS.json`: reviewer correction of the Rule 185 and 187 warnings, and a new flag for Rule 12B's empty heading.
4. Index rebuild (`chroma_telangana_preview`) through `build_telangana_index`, under its own approval.
5. `eval/telangana-retrieval-review.csv` and `eval/telangana-retrieval-benchmark.json`: labels for MP-001 to 005, PN-005 and GC-002, **only through `review_import` with human approval**.
6. Optional: `tests/test_server.py` and `tests/test_grounded_answer.py`, changing the missing-rule example from 186 to 999.

**Versioning fix:**
1. `backend/tg_manifest.py` (or a new loader) for the amendment-register schema.
2. A new reviewed register file beside the manifest.
3. `backend/build_telangana_index.py` to turn register records into `extraction_warning` and `amended_by` metadata.
4. Its tests.
5. Later, and separately: `backend/hybrid_retrieval.py` for lookup expansion.

## Recommendation
**The parser fix is safe to implement on its own, before and without the versioning fix.**
- The two defects touch disjoint code: `segment()` against the manifest, build and lookup.
- The parser fix changes four provisions in two documents and no others, and keeps every text byte (verified).
- Rule 81 is unaffected by it.
- Conditions:
  - Correct the Rule 185 and 187 chunk flag in the same review, otherwise the rebuilt index keeps a false warning.
  - Fix the MP and PN labels through `review_import` before the benchmark is re-run.
  - Have a human confirm that 12-B, 13 and 295-A are rule headings, as their source anchors suggest.

**The versioning fix needs a legal decision first:** warn or exclude, and the four open points on the Rule 81 base text.

## Unresolved legal questions
1. Whether the Rule 81 snapshot equals the rule as it stood just before 15-11-2025, given the six earlier amending G.O.s that are not held.
2. The commencement date of G.O. 77: Gazette publication on 15-11-2025, or another date. The Gazette print is not held.
3. Whether any amendment after G.O. 77 exists.
4. The currency of every snapshot rule. The snapshots carry no amendment history.
5. TMVTR Rule 12-B has no heading in the source. Its title needs an official print.
6. Whether the TMVT Act schedules (G.O. 53 and 16) can be answered without the Act and G.O. 22/2022.

## Integrity: SHA-256 before and after
- I hashed 173 files before inspection and again afterwards, and **all 173 are identical**. The set:
  - every git-tracked file in the worktree;
  - every file under `chroma_telangana_preview/`;
  - every file under `docs/legal-sources/telangana-traffic/`, including the sources, manifest, chunk flags and approval-related notes.
- Key files:

| File | SHA-256 (prefix) |
|---|---|
| `eval/telangana-retrieval-review.csv` | `e6ddfdd8a185…` |
| `eval/telangana-retrieval-benchmark.json` | `cf13d4497b14…` |
| `chroma_telangana_preview/chroma.sqlite3` | `1950d5b3f781…` |
| `DRAFT-telangana-manifest.json` | `738c901d0523…` |
| `PREVIEW-CHUNK-FLAGS.json` | `cdc3033a7999…` |
| `backend/tg_ingest.py` | `38d58aafedb9…` |

- `git diff` is empty. The only new files are untracked: this report, `proposed-heading-fix.diff` and `tests/test_tg_ingest_headings.py`.

## Reproduce
No network, no API key, no model. The index is read-only. Needs `pdftotext`. The scripts for the survey and the before/after comparison are short and inline here. They import the ingester and only read.

```bash
SRC=../KnowYourRules-repo/docs/legal-sources/telangana-traffic/source-documents
IDX=chroma_telangana_preview/chroma.sqlite3
python3 -m backend.source_compare --sources "$SRC" checksums
python3 -m backend.source_compare --sources "$SRC" --index "$IDX" find tmvr-1989-chap-5 "Rule (18[5-7]|29[5-6]).*"
python3 -m backend.source_compare --sources "$SRC" --index "$IDX" find tmvtr-1963 "Rule 1[2-4].*"
python3 -m backend.source_compare --sources "$SRC" context html-snapshots/tmvtr-1963/middle-ap-mv-tr-1963-main.htm "13 Rates of penalty" --width 200
python3 -m backend.source_compare --sources "$SRC" --index "$IDX" compare "tmvr-1989-chap-4::Rule 81"
pdftotext -layout "$SRC/goir/2025TRB_Ms77.pdf" - | grep -n "sub-rule"
python3 -m unittest discover -s tests -p "test_tg_ingest_headings.py" -v
git apply --check eval/legal-validation/proposed-heading-fix.diff   # checks only; do not apply without approval
```

Survey of missed headings, using the ingester's own loader:

```python
import json, re
from pathlib import Path
from backend import tg_ingest as ti
SRC = Path("../KnowYourRules-repo/docs/legal-sources/telangana-traffic/source-documents")
man = json.load(open(SRC.parent / "DRAFT-telangana-manifest.json"))["documents"]
for d in man:
    if d["document_type"] != "Rules": continue
    provs = ti.segment(ti.load_blocks(SRC / d["file"], d["format"], d["file"]), "Rules")
    have = {p.number for p in provs if p.kind == "Rule"}
    for p in provs:
        for b in p.blocks[1:]:
            m = b.kind == "text" and re.match(r"^\s*(\d{1,3})(?:\s*-\s*([A-Z]))?\b", b.text)
            if m and (n := m[1] + (m[2] or "")) not in have and ti._number_key(n) > ti._number_key(p.number or "0"):
                print(d["id"], p.identifier, "<-", b.text[:80], b.location)
```

For the before/after comparison, load the patched module with `importlib.util.spec_from_file_location` on a copy that has the diff applied. Then compare `segment()` and `chunk_document()` per manifest entry, and check each chunk body with `source_compare.compare`.
