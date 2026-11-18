# Stage 23: Rule 81 mitigation options (none selected)

These are reversible options for LD-001. **None is chosen or implemented.** LD-001 and LD-002 stay `evidence_incomplete`; a human reviewer decides.

| # | Option | Where | User sees | Reversal | Rebuild? | Trade-offs |
|---|---|---|---|---|---|---|
| M1 | Do nothing until approval | — | Nothing (answers disabled today) | n/a | No | Safe only while answers stay disabled |
| M2 | Leave the snapshot out of the approval record | Approval record (handoff §5) | Rule 81 never used in approved mode; G.O. 77 alone may answer | Re-sign record | No | Loses base Rule 81 text; G.O. 77 amendments read without context |
| M3 | Set `answer_eligible=False` on the Rule 81 chunks | Chunk metadata | Same as M2 | Restore metadata from backup | Yes (approved rebuild) | Deterministic; affects benchmark rows TG-GO-007 etc. |
| M4 | Provision-level warning appended after citations when a cited chunk is Rule 81 (keyed by chunk id or a config list) | `server.py` response assembly | Fixed text: older snapshot; G.O.Ms.No. 77 (15-11-2025) amends it; commencement and current status unverified; consolidated wording cannot be established | Remove config entry | No | Deterministic, no model dependence; needs a test |
| M5 | Generic warning for every `source_class=unverified_snapshot` citation | `server.py` / citation label | Short "unverified web snapshot" suffix on labels | Revert code | No | Broad; covers Q2-style "current" questions on all TMVR rules; does not name G.O. 77 |
| M6 | Pair retrieval: when Rule 81 is retrieved, also include G.O. 77 chunks | `hybrid_retrieval` / `retrieve` | Both cited together | Revert code | No | Retrieval change; re-run benchmark; still no consolidated text |
| M7 | Route Rule 81 questions to a fixed `missing_provision`-style message | `server.py` pre-check | Deterministic refusal pointing to G.O. 77 and official sources | Revert code | No | Simple; blocks also benign questions |
| M8 | Pass `source_class` and a status note to the model prompt | `grounded_answer.build_prompt` | Depends on model | Revert code | No | Model-dependent; validator does not enforce it; weakest alone |

**Notes**
- M4/M5 can be combined with M2 or M3; M8 should not be used alone.
- Any option that changes answer eligibility for approved documents must also be reflected in the signed approval record.
- Wording in M4 must not claim the snapshot *is* outdated or that G.O. 77 is in force; both are unverified.
