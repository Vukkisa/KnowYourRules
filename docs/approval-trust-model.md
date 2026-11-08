# Approval record: trust model and key management

Status: design for the Telangana assistant. No real approval record, signature or key exists.

## What is trusted
| Item | Who controls it | Where it lives |
|---|---|---|
| **Approval authority private key** (Ed25519) | The approval authority (the counsel, or someone they appoint) | On the authority's own machine or hardware token. **Never in this repository, the server or CI.** |
| **Trusted-keys file** (public keys only) | The deployment operator, installing keys the authority supplies through a separate channel | A path outside the repository given by `TG_TRUSTED_KEYS_FILE`, read-only to the server user |
| **Approval record** (`telangana-approval.json`) | Written from the signed handoff §5 | `TG_APPROVAL_FILE` |
| **Detached signature** (`telangana-approval.json.sig`) | Made by the authority over the exact bytes of the record | Next to the record |

The server trusts an approval only if the record's exact bytes carry a valid Ed25519 signature from a key in the trusted-keys file whose status permits it. It then checks the record against the index (and the corpus, if `TG_CORPUS_DIR` is set). With no trusted-keys file there are no trusted keys, so every record is rejected.

## Separation of duties
- **Signing** happens only offline, in `scripts/sign_approval_record.py`, using a private key path the authority supplies. The script refuses keys stored inside the repository. The server never imports it.
- **Verification** happens only in `backend/legal_approval.py`. It holds public keys only and has no signing code.
- **The operator** installs public keys and records but cannot produce a valid signature.

## Signature file
```json
{"schema_version": 1, "algorithm": "ed25519", "key_id": "<id>", "signature": "<base64 of 64 bytes>"}
```
The signature covers the record file's bytes exactly, so any change, even whitespace, invalidates it.

## Trusted-keys file and rotation
```json
{"schema_version": 1, "keys": [
  {"key_id": "<id>", "algorithm": "ed25519", "public_key": "<base64 of 32 raw bytes>",
   "status": "active" | "retired" | "revoked", "not_after": "YYYY-MM-DD" | null}
]}
```
- **active:** verifies new records.
- **retired:** still verifies records whose `approval_date` is on or before `not_after`, so existing approvals survive a planned rotation. It can't sign anything newer.
- **revoked:** never verifies. Use this when a key is compromised; every record it signed stops being trusted.
- Key IDs must be unique. Rotation means adding the new key as `active`, re-signing or issuing new records, then marking the old key `retired` (or `revoked`).

## Unsigned records
There is no production switch to accept unsigned records. Unsigned synthetic records are used only in unit tests of the record parser. Server tests sign their synthetic fixtures with throwaway keys generated in memory during the test.

## Conditions
A record may list conditions. Each one is either a plain string (unresolved) or `{"text", "resolved", "resolution"}`. Any unresolved condition keeps the approval inactive. Resolving a condition means the authority issues and signs a new record.

## Lifecycle
- **Startup:** full validation (signature, record, index metadata, corpus hashes if configured).
- **Every request:** a cheap fingerprint check:
  - hashes of the small record, signature and trusted-keys files;
  - the index collection's ID and chunk count;
  - size and modification time of the configured corpus files.

  Any change marks approval **stale**: not approved, penalties off, no VERIFIED sources. It stays that way until revalidated.
- **Revalidation:** `POST /approval/refresh` runs the full validation. A periodic full check (`TG_APPROVAL_RECHECK_SECONDS`, default 300) also catches changes the fingerprint can't see, such as metadata edited in place. If it fails, approval becomes invalid.

## Known limits
- Whoever controls the server can replace the trusted-keys file. Keep it outside the repository, owned by a different user, and monitored.
- A signature proves which key signed, not that the legal content is correct.
- A compromised retired key can backdate records up to its `not_after`. Revoke it instead.
- `/approval/refresh` triggers a full index scan. Put it behind the deployment's admin network or authentication.
