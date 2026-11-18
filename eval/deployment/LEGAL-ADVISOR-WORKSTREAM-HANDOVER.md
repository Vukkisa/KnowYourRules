# Legal-advisor workstream handover

Date: 2026-11-16. Inspection and planning only. No code, index, registry, approval record, quarantine status, deployment configuration, benchmark or source file was changed. Nothing was ingested, committed or pushed.

Labels: **VERIFIED** (I read the file and its content supports the statement), **PARTIALLY VERIFIED**, **NOT LOCATED**, **NOT REVIEWED** (file exists; I did not read it in full), **REQUIRES ADVOCATE OPINION**.

Method: file discovery and keyword search (`gemini`, `advocate`, `counsel`, `sign-off`, `section 200`, `high court`, `reconcil`) across the `KnowYourRules-tg` worktree and `HANDOFF.md` in the `KnowYourRules-repo` checkout, then reading the files named below. Sections 1 to 3 rest on the files read; absence claims cover this search only.

## 1. Existing legal-review work and evidence located

| Artifact | What it is | Status |
|---|---|---|
| `eval/legal-validation/STAGE-22-REPORT.md`, `stage-22-legal-decision-register.json`, `stage-22-review-guide.md` | Register of 11 legal decisions LD-001 to LD-011 (Rule 81 snapshot, six cited G.O.s, G.O. 24, G.O. 16/53, G.O. 10/Act 8 of 2026, G.O. 25/32, G.O. 77 alternate file, AP G.O. 332/2008, Rules of the Road). **0 approved**, 4 `pending`, 7 `evidence_incomplete`. Every reviewer, date, decision and rationale field is `null`. Authorised approver is "legal counsel". | VERIFIED (read report and register head) |
| `eval/legal-validation/stage-21-legal-source-status.json`, `stage-21-review-questions.md` | Questions for human legal review (Rule 81 history, G.O. 77 publication, G.O. 54, archive file `74a6839d…`). | PARTIALLY VERIFIED (questions read; JSON not read in full) |
| `legal-status/source-status.json` | Text status per source. 13 TMVR HTML snapshots `unverified_snapshot`; 7 G.O. PDFs `official_text_commencement_unconfirmed`. `assigned_by` is "assistant … not a legal decision"; review blocks are `null`. Rule 81 carries `known_amendments_unresolved`. | PARTIALLY VERIFIED (head read) |
| `backend/legal_approval.py`, `docs/approval-trust-model.md` | Mechanism for one Ed25519-signed approval record. A signature proves the key, not legal correctness. | PARTIALLY VERIFIED (design described in Stage 22 and the trust model; code not reviewed) |
| `legal/telangana-approval.json` | The signed approval record. | **NOT LOCATED** (absent; Stage 24 also states this) |
| `eval/deployment/LEGAL-SOURCE-COMPLETENESS-AUDIT.md` (2026-11-15) | Audit of 20 indexed sources; 590 chunks all `unverified`; `kb_approved` false; lists open legal questions (e.g. which s.200 schedule applies in Telangana; whether pre-2014 AP orders apply; whether High Court case law is in scope, its question 13). | PARTIALLY VERIFIED |
| `eval/deployment/LEGAL-DOCUMENT-ACQUISITION-PLAN.md`, `LEGAL-MANUAL-ACQUISITION-CHECKLIST.md` | Acquisition planning and manual-download checklist. | NOT REVIEWED in full |
| `eval/deployment/MOTOR-VEHICLES-ACT-VERIFICATION-REPORT.md` | India Code consolidation "as on 15 August 2026"; the s.200(1) list is word-for-word verified against the Act text (row 110). State notifications under s.200 are outside its scope. | PARTIALLY VERIFIED (excerpts read) |
| `eval/deployment/PRIORITY-15-QUESTION-LEGAL-SOURCE-MAP.md`, `PRIORITY-15-QUESTION-READINESS-REPORT.md`, `PRIORITY-CMVR-DOCUMENT-GAP-LIST.md` | The 15-question mapping and readiness classes. Need corrections (section 6). | PARTIALLY VERIFIED |
| `eval/deployment/REMAINING-PRIORITY-SOURCE-ACQUISITION-REPORT.md`, `PRIORITY-SOURCE-ACQUISITION-REPORT.md`, `CENTRAL-MOTOR-VEHICLES-RULES-SOURCE-REGISTER.md` | Latest acquisition work (section 5). | VERIFIED (I produced them this session) |
| `eval/legal-validation/STAGE-08` to `STAGE-29` reports and JSON | Retrieval and benchmark stages, plus legal-status stages 19 to 26. | NOT REVIEWED in full (stages 8–18, 23–28 not read) |
| `HANDOFF.md` (untracked, `KnowYourRules-repo`, dated 2026-11-12) | Engineering handoff. States LD-001 and LD-002 "stay pending". Not a legal document. | PARTIALLY VERIFIED (head read) |

**Not located by name or content:** `LEGAL-REVIEW-HANDOFF.md` (referenced by Stage 22 as the source of the §5 sign-off block; the file is not in the worktree); a Section 200 reconciliation document; a rule matrix; a counsel checklist or legal-issues memorandum for counsel; any Telangana High Court verification. High Court appears only as an open scope question (completeness audit, question 13) and a search remark in the acquisition report (a search result mentioning a High Court judgment on s.200(1) compounding; not used, not verified).

## 2. Gemini review artifacts

**NOT LOCATED.** "Gemini" matches only deployment and provider configuration (`requirements-cloud.txt`, `.env.example`, `deploy/*`, provider tests). No file contains a legal conclusion attributed to Gemini. I read only the file list, not the matched lines, so a Gemini mention inside those files is unconfirmed but they are configuration and test files. Anything Gemini concluded lives outside the project artifacts and is treated as unknown. If it exists as a transcript, it needs to be supplied and treated as AI analysis, not as evidence.

## 3. Advocate sign-off evidence

**NONE FOUND.** Specifically:
- `legal/telangana-approval.json` is absent; no key, signature or reviewer identity exists (Stage 22, Stage 24).
- All 11 register decisions have null reviewer and decision fields.
- All `source-status.json` entries are assistant defaults, none `verified_current`.
- No signed opinion, no advocate name, no enrolment number and no engagement record was found.
- No document found *states* that sign-off exists. The materials I read consistently say the opposite. Weak points to check, since I did not read every file: any report that uses "approved" for the document set (the indexed `answer_eligible` flag is an extraction flag, not approval, per the audit), and `docs/legal-sources/telangana-traffic/DRAFT-telangana-manifest.json` and the lifecycle registry (`legal/lifecycle/`) for approval-like fields (NOT REVIEWED).

## 4. Unresolved legal questions (all REQUIRE ADVOCATE OPINION unless marked)

1. **Rule 81 TMVR:** which text is current (snapshot vs G.O. 77 of 15-11-2025), commencement, and amendments after it (LD-001, LD-002).
2. **Six cited G.O.s (2014–2018):** subjects and whether each amended Rule 81 (LD-003).
3. **G.O. 24, G.O. 16/53, G.O. 10/Act 8 of 2026, G.O. 25, G.O. 32:** draft/final, Gazette publication, effect, answerability without the Central rules (LD-004 to LD-008).
4. **G.O. 332/2008 (AP) and 2006 AP orders:** whether they apply in Telangana (LD-010).
5. **Compounding in Telangana under s.200:** which order governs (G.O.Ms.No.42/2020 not located); whether a compounding order exists for each offence the benchmark covers; whether the amount is a Telangana-notified amount or the statutory fine.
6. **Section 200(1) as substituted from 15 August 2026:** the consolidation text was verified, but I did not verify the commencement notification, transitional treatment, or offence-date applicability. Whether offences omitted from the list remain punishable or have another enforcement route is a legal question, not to be inferred from the list.
7. **s.184 (Explanation (a)) vs s.177A for red-light jumping** (Q6).
8. **s.194D, s.185, s.181:** no compounding order or CMVR provision identified (Q-specific, see readiness report).
9. **Rule 167A and Rule 55(2)(iv):** history and wording unresolved. These are sourcing gaps first, then legal questions.
10. **Offence-date law:** the project has no verified mechanism or opinion on which version applies to a past offence.
11. **Telangana licence fees / duplicate licence fee:** not established (sourcing gap).
12. **Scope:** whether Telangana High Court orders and Commissionerate notifications are in scope.

## 5. Effect of the latest source-acquisition findings

- **Strengthened (PARTIALLY VERIFIED → better evidenced):** Rule 81 serial (11A) now traced to G.S.R. 714(E) of 04-10-2021 (from 01-04-2022) and restructured by G.S.R. 850(E) of 11-11-2025; rule 32 traced to G.S.R. 1183(E) of 2016 and 271(E) of 2017. The sixteenth amendment 525(E) amends rule 81 only. The seven 2026 amendments do not touch rules 167, 167A, 32 or 55, and do not amend rule 81 (Fifth Amendment 298(E) of 2026, not among the seven, changed one rule 81 entry). These cover the **Central** rules only; the Telangana TMVR Rule 81 question (LD-001) is a different instrument and is unaffected.
- **Unchanged / still blocking:** G.O.Ms.No.42/2020, Rule 55(2)(iv), the Telangana fee notification, the 2021–2025 Rule 167A history (not enumerated, so "no amendment" is not established), the Telangana Gazette copies of G.O. 24 and 25, and s.112(2) speed-limit notifications.
- **Corrects earlier statements** (nine corrections in section 6 of the acquisition report): the rule 32 duplicate-licence row is absent from the 2016 table (not garbled); the 332-page file holds the pre-2016 rule 32 table; 417(E) of 2025 (HSRP) is not 417(E) of 2026; rule 55 is stale beyond clause (iv).
- **Effect on prior legal conclusions:** none of the Telangana-specific questions in section 4 is resolved by the new documents. No benchmark question changed status. Q2, Q5, Q6, Q7, Q9, Q12 and Q13 stay blocked.
- **Evidence quality:** the newly acquired files are e-Gazette originals (read-only, SHA-256 recorded). Their currentness is not claimed.

## 6. Exact documents that must be updated (not updated in this task)

1. `PRIORITY-15-QUESTION-READINESS-REPORT.md`, `PRIORITY-15-QUESTION-LEGAL-SOURCE-MAP.md`, `PRIORITY-CMVR-DOCUMENT-GAP-LIST.md`: apply the nine corrections in `REMAINING-PRIORITY-SOURCE-ACQUISITION-REPORT.md` section 6.
2. `LEGAL-SOURCE-COMPLETENESS-AUDIT.md`: mark which Central-rule items are now resolved; keep Telangana items open.
3. `stage-22-legal-decision-register.json`: only a human reviewer sets decisions. The assistant may add evidence or set `pending` / `evidence_incomplete`. Candidate new records: G.O.42/2020 compounding, s.200(1) substitution and offence-date, s.184 vs s.177A, Rule 167A history. New records would be an approved task of their own.
4. `legal-status/source-status.json`: no change until counsel reviews. Do not set `verified_current`.
5. A new counsel memorandum and a Section 200 matrix (do not exist; section 7, steps 3 and 4).
6. After sign-off only: `legal/telangana-approval.json` (signed), and then the gating code paths. Out of scope until sign-off exists.

## 7. Sequenced plan to obtain formal Telangana advocate sign-off

1. **Freeze scope.** Project owner decides what the product will answer (rule text only, or penalties and compounding) and whether High Court orders are in scope. Counsel engagement depends on this.
2. **Close what is purely documentary, once:** obtain G.O.Ms.No.42/2020 and the Telangana Gazette copies of G.O. 24, 25 and 32 through the Transport Department, the Telangana Gazette office or counsel's own channel. Rule 55(2)(iv): ask the Transport Commissionerate or counsel. Do not run another broad search; the acquisition report documents the failed routes.
3. **Prepare the legal-issues memorandum** (one per section 4 item): question, provisions, primary evidence with hashes, what is missing, options. Mark as AI-prepared assistance, not opinion. Include a Section 200 matrix listing, per offence, punishability, compoundability, statutory penalty, Telangana amount, collecting authority, and offence-date version, with unverified cells left blank rather than filled.
4. **Engage a qualified Telangana advocate** (Telangana High Court practice, motor-vehicles experience). Record name, enrolment number, date and scope in a file the project owner controls, not invented by the assistant.
5. **Counsel verifies High Court material:** relevant Telangana High Court judgments or interim orders on compounding, fines or enforcement; the project does not rely on AI search for this.
6. **Obtain the written, signed opinion** covering: each section 4 question; conditions (e.g. warnings, scope exclusions); the offence-date rule; and whether fine and compounding outputs may be enabled and on what basis.
7. **Record conclusions** in the Stage 22 register by the reviewer (not the assistant), with named reviewer, date and rationale. Store the opinion file and hash outside code.
8. **Final legal-readiness and controlled-corpus release audit:** check each opinion condition against the corpus, then the signed approval record (`legal/telangana-approval.json`) with the key held by the approval authority.
9. Only then consider enabling any disabled output, each as a separate approved change.

## 8. Current legal release status and restrictions

- **Release status:** **NOT LEGALLY APPROVED.** No advocate opinion, no signed approval record, no `verified_current` source. 0 of 11 decisions approved.
- **Telangana fine and compounding amount outputs: remain disabled.** No Telangana compounding order (G.O.Ms.No.42/2020) or fee notification is held.
- Statutory fine, compoundability under s.200, Telangana-notified amount, collecting authority and offence-date law must be treated as separate questions; none is established for Telangana.
- The s.200(1) allowlist substituted from 15 August 2026 must not be used as a list of punishable offences, and omission from it must not be read as "not punishable" or "no other enforcement".
- AI analysis, including this document, is not an advocate's opinion.
- Technical source readiness is not legal approval. Index flags (`answer_eligible`, `kb_approved`) are not approval.
- No legal answering is enabled by this document; no safeguard is weakened.

## 9. Boundaries of this task

Created only this file. No code, frontend, index, embeddings, retrieval configuration, benchmark, source registry, legal register, approval record, trusted keys or quarantine status was changed. No ingestion, deployment, commit or push. No further acquisition was performed.
