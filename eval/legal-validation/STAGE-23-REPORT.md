# Stage 23: Rule 81 answer-path exposure check

**Result:** today no user can see Rule 81 text: answer mode is `disabled` (no approval record), so every question returns `unavailable`. **If** answers were enabled with the snapshot approved, Rule 81 text would be shown with **no Rule-81-specific warning**: none of the four required warnings reaches the user.

**Changed files:** new files only, in `eval/legal-validation/`:
- this report;
- [`stage-23-rule81-answer-path.json`](stage-23-rule81-answer-path.json): trace, retrieved chunks, metadata, citations, responses;
- [`stage-23-mitigation-options.md`](stage-23-mitigation-options.md).

**Not changed:** code, sources, manifests, checksums, benchmark, indexes, approval records, LD-001/LD-002 (both still `evidence_incomplete`). No Groq or external calls; nothing committed.

## 1. Method
- Copy of `chroma_telangana_preview_s11`; local Ollama embeddings; `GROQ_API_KEY` unset.
- Run 1 (actual configuration): `retrieve()` and `POST /chat` via `TestClient`, exact and HNSW.
- Run 2 (hypothetical approved deployment, **in memory only**): gate and approval patched, retrieved hashes added to `SOURCES`, `MockGenerator` quoting evidence sentences. No file or approval record written.

## 2. Trace
| Stage | Code | Rule 81 behaviour |
|---|---|---|
| Metadata | `backend/tg_ingest.py:563` | `source_class=unverified_snapshot`, `verification_status=unverified`, `answer_eligible=True`, `effective_date=""`. No amended-by / superseded field |
| Vector search | `backend/server.py:878` | Filter is `state` only. Exact and HNSW gave **identical** top-6 for all 4 questions |
| Fusion and filters | `backend/server.py:889` | Drops `answer_eligible=False` and (approved mode) unapproved hashes. Rule 81 passes; no demotion or pairing with G.O. 77 |
| Model prompt | `backend/grounded_answer.py:192` | Header carries `verification_status: "unverified"` to the **model only**; `source_class` not passed; no snapshot/amendment instruction |
| Citation | `backend/grounded_answer.py:479` | `Telangana Motor Vehicles Rules, 1989, Rule 81 (html-snapshots/tmvr-1989/middle-main-chap-4.htm#4)`; no status |
| API | `backend/server.py:1142` | `response`, `kind`, `sources{title, instrument, verified, file, sha256}`. `with_penalty_note` adds a generic date note only if the answer mentions money |
| Frontend | `frontend/index.html:220, 254` | Kind tag; source badge "Verified"/"Unverified" from approval membership, not from `source_class` |

## 3. Four questions (exact = HNSW)
| ID | Question type | Rule 81 snapshot retrieved | G.O. 77 retrieved | Actual API | Simulated approved |
|---|---|---|---|---|---|
| Q1 | Names Rule 81 | Yes, ranks 2–3 | Yes (Order, Preamble, Para 4) | `unavailable` | `no_support` (mock claims rejected by validator) |
| Q2 | "Current" Rule 81 requirements | Yes, ranks 1–2 | **No** | `unavailable` | **`answer`**, citing Rule 81 twice, no warning |
| Q3 | G.O. 77 fees / online bidding | Yes, rank 2 | Yes (Para 3, Order, Preamble, References) | `unavailable` | `no_support` (mock rejection) |
| Q4 | Rule 81 with G.O. 77 | Yes, rank 2 | Yes (5 chunks) | `unavailable` | `no_support` (mock rejection) |

- Q2 is the riskiest: a "current" question retrieves only the snapshot and neighbouring rules, so nothing points to G.O. 77.
- Q1/Q3/Q4 simulated rejections come from the crude mock's paraphrase checks, not from any warning logic; with a real model they could be answered, mixing snapshot text and G.O. 77 text without a reconciliation note.

## 4. What the user sees vs internal only
| Required warning | Visible? |
|---|---|
| Rule 81 text is an older snapshot | **No** |
| G.O. 77 amends it | **No** (only if G.O. 77 happens to be cited alongside) |
| Commencement / current status unverified | **No** (generic `PENALTY_NOTE` only when money is mentioned) |
| Bot cannot establish the consolidated wording | **No** |

- **Internal only:** `source_class`, `verification_status` (also seen by the model), empty `effective_date`.
- **Partial, generic:** `PENALTY_NOTE`; "Unverified" badge (only for unapproved documents, so it would disappear once the snapshot is approved); `DEV_OUTPUT_BANNER` in `legacy_dev` (development only, not run: needs Groq).

## 5. Validation
- Full suite: 672 OK in exact mode, 672 OK in HNSW mode (includes `test_exact_vector`, `test_bm25_plural`, grounded-answer and server tests).
- Checksums: 63/63 OK (`shasum -a 256 -c SHA256SUMS`), untouched.

## Unresolved questions
- LD-001: should the snapshot stay answerable, with a warning, or be excluded? (unchanged)
- LD-002: evidence for a consolidated Rule 81. (unchanged)
- Would an approval record list `middle-main-chap-4.htm`? If not, approved mode already excludes it.
- Real-model behaviour on Q1/Q3/Q4 is untested (no Groq).
- Q2: should "current" questions on any snapshot provision trigger a general currency disclaimer?
