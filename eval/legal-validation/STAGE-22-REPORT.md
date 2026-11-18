# Stage 22: legal review decision workflow

**Result:** a structured register of 11 legal decisions (LD-001 to LD-011) and a reviewer guide.
- **Decided: none.** 4 are `pending`, 7 are `evidence_incomplete`, and 0 are `approved`, `rejected` or `requires_further_review`.
- No reviewer identities were created; every reviewer, date, decision and rationale field is `null`.

**Changed files:** new files only, in `eval/legal-validation/`:
- this report;
- [`stage-22-legal-decision-register.json`](stage-22-legal-decision-register.json);
- [`stage-22-review-guide.md`](stage-22-review-guide.md).

**Not changed:** sources, manifests, checksums, the benchmark, indexes, retrieval and answer generation. No external calls; nothing committed.

## 1. Existing mechanisms, and why they are not enough
| Mechanism | What it does | Gap for source-version decisions |
|---|---|---|
| `backend/legal_approval.py` + `docs/approval-trust-model.md` | Verifies a single Ed25519-signed approval record for the whole approved document set, written from handoff §5. Fails closed | No record, key or signature exists yet. It has **no per-provision version, supersession or warning fields**, and no place for evidence or rationale per question |
| Handoff §5 sign-off block | Blank form: reviewer, decision, conditions | One decision for the whole corpus |
| `backend/review_import.py` | Benchmark label review | Explicitly "NOT LEGAL APPROVAL" |
| `SHA256SUMS` / `SOURCE-MANIFEST.md` | File integrity and provenance | No legal status |

**Design:** the register records each decision with its evidence and source hashes. An approved decision changes nothing by itself. Changes to answer eligibility must also go into the signed approval record, and are implemented later with backups.

## 2. Register
Each record has these fields:
- `decision_id`, `priority`, `subject`, `question`;
- `evidence_available` and `evidence_required`;
- `proposed_options`, marked as drafts and not decisions;
- `status` and `authorized_approver`;
- `reviewer` {name, designation, organisation}, `review_date`, `decision`, `rationale`, `conditions`;
- `supporting_sources` (file and SHA-256), the linked `stage_21_questions`, `would_change_if_approved`, and `history`.

| ID | Subject | Status |
|---|---|---|
| **LD-001** | Rule 81 snapshot: answerable, excluded, or answerable with a warning | evidence_incomplete |
| **LD-002** | Rule 81: the evidence required before restoring eligibility, and approval of a consolidated version (counsel only, then the signed record) | evidence_incomplete |
| LD-003 | The six cited G.O.s from 2014–2018: subject, and whether each amended Rule 81 | evidence_incomplete |
| **LD-004** | G.O. 24: draft or final, and Gazette publication | evidence_incomplete |
| **LD-005** | G.O. 16 deletes column 8 of G.O. 53's Seventh Schedule, with effect from 23-03-2026 | evidence_incomplete (Gazette) |
| **LD-006** | Superseded-in-part flag on the G.O. 53 Seventh Schedule chunk (depends on LD-005; the chunk is already non-answerable) | pending |
| LD-007 | G.O. 10 / Act No. 8 of 2026 | evidence_incomplete |
| LD-008 | Whether G.O. 25 and G.O. 32 stay answerable without the Central rules | pending |
| LD-009 | The alternative G.O. 77 file `74a6839d…` | evidence_incomplete |
| LD-010 | Whether G.O. 332/2008 (Andhra Pradesh) applies | pending |
| LD-011 | Rules of the Road stay excluded (scope) | pending |

**Rule 81 options (LD-001)**
- **A:** exclude until a consolidated text is approved.
- **B:** keep answerable, with a warning that the text may be superseded by G.O. 77.
- **C:** no change.

Until a decision is made, current behaviour continues, and nothing presents the snapshot as current law.

## 3. Validation
- **Checksums:** 63/63 OK with `shasum -c`; `source_compare` gives 63 OK.
- **Tests:** 672 OK in exact mode and 672 OK in HNSW mode.
