# Legal decision register: reviewer guide

The register is `stage-22-legal-decision-register.json`. It holds 11 decisions, LD-001 to LD-011. **None is decided.** The assistant drafted the options and recorded the evidence.

## Who decides
| Decision | Authority |
|---|---|
| Legal status, versions and supersession (LD-001 to LD-010) | Legal counsel, the approval authority in `docs/approval-trust-model.md` |
| Consolidated Rule 81 (LD-002) | Counsel only. The text must then be listed in the signed approval record |
| Scope (LD-011) | The project owner, with counsel |

Benchmark review (`review_import`) is **not** legal approval and cannot settle any of these.

## Statuses
| Status | Meaning | Who may set it |
|---|---|---|
| `pending` | Evidence is enough to decide; waiting for a reviewer | The assistant or a reviewer |
| `evidence_incomplete` | Cannot be decided until the listed evidence is obtained | The assistant or a reviewer |
| `approved` | One option has been approved | **Human reviewer only** |
| `rejected` | The proposals have been rejected | **Human reviewer only** |
| `requires_further_review` | The reviewer asked for more work | **Human reviewer only** |

## How to record a decision
1. Read `question`, `evidence_available` and `supporting_sources`. Check each hash with `shasum -a 256 -c SHA256SUMS`.
2. If evidence from `evidence_required` is missing, leave the status as `evidence_incomplete` or add what was obtained. A new source file needs its own checksum line.
3. Choose one option, or write your own, and fill in:
   - `reviewer.name`, `reviewer.designation` and `reviewer.organisation`;
   - `review_date` (YYYY-MM-DD);
   - `decision` (the option and its exact wording);
   - `rationale`, citing the sources relied on;
   - any `conditions`.
4. Set `status` and add a `history` entry: `{date, status, by}`.
5. Anything that changes answer eligibility for approved documents must also go into the signed approval record (handoff §5 → `telangana-approval.json` + `.sig`). The register alone does not activate anything.
6. Implementation happens afterwards, with backups: chunk metadata at an approved rebuild, or answer warnings. It is recorded in `history`.

**Rules**
- Never fill in reviewer fields on someone else's behalf.
- Never set `approved` without a name, date and rationale.

## Priority order
1. **LD-001, Rule 81 eligibility.** Exclude, warn, or leave unchanged until LD-002 is resolved. The snapshot stays answerable and is not presented as current law meanwhile.
2. **LD-002 / LD-003, evidence for a consolidated Rule 81.** The Gazette and commencement of G.O. 77, the six cited G.O.s, and any later amendments.
3. **LD-004, G.O. 24.** Draft or final; the Gazette of 02-06-2026.
4. **LD-005 → LD-006, G.O. 16 and G.O. 53.** Confirm the column-8 deletion first. Only then decide on the superseded-in-part flag (the chunk is already non-answerable).
5. **LD-007 to LD-011:** Act No. 8/2026, G.O. 25 and 32, the `74a6839d` file, G.O. 332/2008, and the Rules of the Road.
