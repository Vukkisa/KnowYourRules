# Stage 24: source-status warning design (proposal only)

Nothing here is implemented. It does not decide LD-001/LD-002, and a warning is **not** legal certification.

## 1. Principle
Approval and currency are separate dimensions.
- **Approval** (signed record) answers: may this document be used at all?
- **Text status** answers: what do we know about whether this text is the current law?

Today the only user-visible signal is the "Verified/Unverified" badge, derived from approval. It disappears on approval, so the snapshot would look current. The design keeps text status independent of approval.

## 2. Status classes (per document, optionally per provision)
| `text_status` | Meaning | Default user warning |
|---|---|---|
| `verified_current` | Official text, currency confirmed by a recorded human decision | none |
| `official_currency_unconfirmed` | Official instrument (e.g. a held G.O.), Gazette/commencement not confirmed | "Commencement and current status not confirmed." |
| `unverified_snapshot` | Web consolidation; as-amended date unknown | "Taken from an unofficial web copy of unknown date; it may not reflect later amendments." |
| `known_amendments_unresolved` | Provision with a held amending instrument whose effect/commencement is unverified (Rule 81 + G.O. 77) | Snapshot warning **plus** "G.O.Ms.No. 77 (15-11-2025) contains amendments to this rule; its commencement and the consolidated current wording have not been established." |

Separately, `approval_state` (`awaiting_approval` / `approved`) stays as today. An approved document keeps its `text_status` warning.

## 3. Where the data lives
- **Source of truth:** a new reviewed file, e.g. `docs/legal-sources/telangana-traffic/source-status.json`, keyed by document `sha256` (and optional `provision_id`), with `text_status`, `warning_id`, `related_instruments`, and a `decision_ref` (e.g. LD-001) when a human decision changes it.
- Defaults derived mechanically from the manifest: `source_class=unverified_snapshot` → `unverified_snapshot`; `official` → `official_currency_unconfirmed`. Only a human-recorded decision can set `verified_current` or attach/remove a known amendment.
- Warning texts are fixed strings in code, selected by `warning_id`; never model-written.
- Optionally listed in the signed approval record (hash of `source-status.json`) so changes to it invalidate approval like any other input.

## 4. Flow
| Layer | Change |
|---|---|
| Ingestion / metadata | Copy `text_status`, `warning_id` into chunk metadata at the next approved rebuild, **or** look them up at runtime by `sha256`/`provision_id` (no rebuild; preferred, reversible) |
| Retrieval | No filtering by status (no exclusions implied). Optional: when a `known_amendments_unresolved` chunk is retrieved, record the related instrument ids for the warning |
| Grounded generation | Pass `text_status` in the evidence header (model context only). Not relied on for user safety |
| Citations | Backend appends a short status marker to the label, e.g. `… Rule 81 (…#4) — unofficial web copy` |
| API | New field `source_warnings: [{warning_id, text, applies_to: [citation numbers], related_instruments}]` and per-source `text_status`; `kind` unchanged |
| Frontend | Warning panel above sources when non-empty; badge shows two parts: approval ("Approved"/"Awaiting approval") and text status |
| Legacy dev mode | Same warnings appended after `DEV_OUTPUT_BANNER` |

Warnings are attached whenever a **cited** chunk has a non-`verified_current` status, independent of `KB_APPROVED`. Questions using words like "current/latest/now" add the generic currency sentence even if all cited text is official.

## 5. Tests the design would need
- Approved record + snapshot citation → warning still present.
- Rule 81 cited with or without G.O. 77 → `known_amendments_unresolved` warning naming G.O. 77.
- Q2-style "current" question → currency sentence.
- Warning text never claims the snapshot *is* outdated or that G.O. 77 *is* in force.
- Changing `source-status.json` without re-approval → approval goes stale (if bound into the record).

## 6. Governance
- Assigning `known_amendments_unresolved` to Rule 81 is a factual statement already documented (G.O. 77 held, commencement unverified); removing it or setting `verified_current` requires a human decision (LD-002).
- Whether Rule 81 stays answerable remains LD-001. This design works with any LD-001 outcome.
