# Approval and trust model

Status: current. There is **no signed approval record, detached signature or trusted-keys file** in the serving path. Nothing here is a legal opinion.

## What decides whether a source is served
- **The document lifecycle registry** (`legal/lifecycle/`, `backend/document_lifecycle.py`) is the only approval state. A source version is served only when it is `approved` and the active version, and its SHA-256 matches the indexed corpus file.
- **Approval basis.** `bootstrap --approval-basis TEXT` approves the documents that pass the other checks (an unambiguous id and file, an entry in the source-status registry, a matching corpus hash) and records the text verbatim in the tamper-evident audit log. The operator name and basis are unauthenticated labels: the registry records `identity_assurance: operator-supplied-unauthenticated`. They state who is said to have approved and on what basis; they do not prove it.
- **Current basis.** All 20 source versions were activated on 2026-11-17 on the project owner's statement that the legal advisor's review of the project materials was completed. No reviewer name, designation, review date or signature is on file, so this is an owner-attested basis, not an authenticated legal approval.
- **Central sources.** Three Central sources (an extract of the Motor Vehicles Act, 1988, the Motor Vehicles (Driving) Regulations, 2017 and their 2020 amendment) were added on 2026-11-17 on the project owner's instruction, in the same lifecycle registry and on the same kind of basis; the legal advisor's review did not cover them. They are tagged `Central`, never relabelled as Telangana, and their text status is `official_text_commencement_unconfirmed`: official text whose latest in-force version is not confirmed. The Central Motor Vehicles Rules, 1989 are not served.

## What approval does not change
- **Source verification status** (`legal-status/source-status.json`): sources stay `unverified_snapshot` or `official_text_commencement_unconfirmed` until independently confirmed. Answers carry the matching warning ("unofficial web copy of unknown date").
- **Reporting flag.** `/status.kb_approved` stays `false`, so the UI keeps its "Pending counsel" and "not legally reviewed" labels. It blocks nothing.
- **Penalties.** Fine, penalty and compounding answers stay locked in code (`backend/release_gates.py`); approval does not open them.
- **Citations.** Every cited passage must map to one served document hash and the stored chunk, or the answer is withheld.

## Staleness
A change to the lifecycle registry, the index, the corpus or the validity inputs marks the server **stale**, which blocks grounded answers until `POST /approval/refresh` revalidates. `/approval/refresh` triggers a full index scan: put it behind the deployment's admin network or authentication. It is not exposed on the Vercel deployment.

## Known limits
- Whoever controls the registry directory controls approval. The audit log is tamper-evident (hash chain), not tamper-proof, and the basis is not authenticated.
- Approval says nothing about whether the text is current or official; that is the source-verification status above.

## Optional provision-level validity layer (off by default)
The sections below describe `TG_PROVISION_VALIDITY` (`backend/provision_validity_runtime.py`, `backend/ledger_acceptance.py`). It is a separate, opt-in layer that still uses a signed chain (Ed25519 record, trusted-keys file) for a provision-validity ledger. It is off by default and fail-closed, and it is **not** needed for the document lifecycle or for answering. No ledger, register or manifest exists, so `restrict` would currently serve nothing. The server does not read `TG_APPROVAL_FILE` or `TG_TRUSTED_KEYS_FILE` for anything else.

## Provision-validity decision records: attestation, not reviewer authentication
This applies only to the offline acceptance gate for a provision-validity ledger (`backend/ledger_acceptance.py`; since Step 4 the server reaches it only through `backend/provision_validity_runtime.py`, see the next section).

- **What is bound.** The signed approval record binds the source-status registry's SHA-256. The registry may carry three hashes: `validity_ledger_sha256`, `validity_decision_register_sha256` (the exact bytes of the decision register) and `validity_evidence_manifest_sha256` (the exact bytes of the canonical evidence manifest). The manifest lists every evidence file with its relative path, SHA-256 and size. Changing the register, the manifest, a listed file or the registry breaks the signed chain. The gate also refuses links below the evidence directory and a register, manifest or approval from another jurisdiction.
- **What that proves.** The offline approval authority attested these exact bytes: this register, and the evidence it lists, are what it signed. It is the only trust anchor, with the same key, signer and trusted-keys file as before. No signature scheme was added.
- **What it does not prove (interim "attestation" model).** It does **not authenticate** the reviewer. The reviewer's name, designation, review date and history are free text in the register; nobody signed a decision with a personal key. Do not describe a decision as cryptographically verified, personally signed or independently approved by that reviewer. The plausibility checks in `backend/validity_decisions.py` (a named human, not a machine, history ending in the reviewer on the review date, reviewer and preparer pinned in the signed ledger, no synthetic wording in an unflagged register) are filters for careless or machine-written records. A plausible invented record, attested by the authority, passes them.
- **Missing trust requirement (no reviewer key exists).** Independent reviewer authentication would need decisions that this repository cannot make for the owner and counsel: who the reviewers are and how their keys are generated and held; an identity, role and jurisdiction bound to each key (the trusted-keys format has none); whether the approval authority may authorize reviewer keys or a separate root is required; a canonical, domain-separated payload per decision with revocation and freshness rules; and a rule that the server never holds a reviewer key. Until then no reviewer key mechanism is built and none may be invented. The approval authority therefore carries the whole legal risk of an attested register.
- **`production=True` is not proof of a production key.** For an accepted chain, `Acceptance.production` is `False` only when the ledger or register is flagged as a fixture (a rejected chain is never `production`). It says nothing about the trusted key: a chain signed by a throwaway key that is listed in the trusted-keys file reports `production=True`. Provisioning that file (which keys are listed, that none is a test key, and keeping it outside the repository and the data directory) is the deployment operator's responsibility; the gate cannot check it.
- **Still open.** Replay of an older, validly signed set (no freshness or sequence policy) and the other items in `docs/legal-review/` are unchanged.

## Provision-level validity in the application (Step 4)
- **Off by default.** `TG_PROVISION_VALIDITY` unset or `off` changes nothing and reads no file. `shadow` runs the acceptance gate and logs what the ledger would remove. `restrict` requires the gate to pass before any legal chunk is retrieved or served, and then lets the ledger only **remove** chunks. Any other value, including `enforce` (still locked), serves nothing.
- **Inputs.** `TG_VALIDITY_LEDGER_FILE`, `TG_VALIDITY_DECISION_REGISTER_FILE`, `TG_VALIDITY_EVIDENCE_MANIFEST_FILE`, `TG_VALIDITY_EVIDENCE_DIR`, plus the existing approval, trusted-keys, registry and corpus settings. The accepted chain must be bound to the same registry the server uses. The server no longer holds a signed approval of its own, so the layer's approval check cannot pass: `restrict` stays fail-closed until that layer is deliberately redesigned.
- **What is removed.** A chunk is kept only if the existing checks already allow it **and** the accepted ledger covers it exactly and says it is in force (undated: authoritative; dated: authoritative or historical). Pending, unapproved, unverified, expired, not-yet-commenced, partially covered, stale-coverage and uncovered chunks are removed. The ledger never creates authority.
- **Citations.** Every cited passage must map to one approved source file hash, one provision and the stored chunk; otherwise the answer is withheld. Penalty and compounding questions are refused before retrieval exactly as before; nothing here opens them.
- **Fail closed.** An unaccepted, stale, rejected or misconfigured chain refuses `/chat`. A changed input withdraws the acceptance; only a refresh re-accepts. No real ledger, register or manifest exists yet, so a `restrict` deployment currently serves nothing.
- **Deferred, not implemented: replay protection.** An older, validly signed set is still accepted; the sequence number, expiry and operator-supplied minimum sequence that would prevent it are a deferred limitation (the approved design is recorded separately). The operator's floor and clock depend on the deployment's own trust boundary.

## Activation requirement (outstanding)

`restrict` mode cannot serve legal answers until the operator and the approval authority supply, outside this repository: the authority's Ed25519 public key in the trusted-keys file (`TG_TRUSTED_KEYS_FILE`); a signed approval record carrying the real reviewer name, designation, review date and decision; the approved decision register; the validity ledger (instrument keys, provision keys, `valid_from`/`valid_to`) built from the deployed index's selectors; and the evidence manifest with its held evidence files. No such record exists in this repository and none may be fabricated. Until they are entered and the acceptance gate accepts them, `TG_PROVISION_VALIDITY` stays off (default) or `/chat` is refused (`restrict`).

## Known limits of the optional validity layer
- Whoever controls the server can replace the trusted-keys file. Keep it outside the repository, owned by a different user, and monitored.
- A signature proves which key signed, not that the legal content is correct.
- A compromised retired key can backdate records up to its `not_after`. Revoke it instead.
- A signed decision register is an attestation by the approval authority, not proof that the named reviewer approved anything (see the provision-validity section above). There is no reviewer key.
