# Vercel Hobby pilot readiness — KnowYourRules backend

Date: 2026-11-15. Builds on `VERCEL-FEASIBILITY-AUDIT.md` (which said NO-GO; you then selected Vercel Hobby for a low-traffic recruiter demo).
Labels: **VERIFIED** = checked here (code, tests, or the local rehearsal), **DOCUMENTED** = official Vercel page (URL and its last-updated date), **ESTIMATED**, **UNKNOWN**.

## 1. Decision

**NO-GO for a public launch or any claim that this works on Vercel. GO for one private preview deployment test**, after the operator steps in section 9.

- The minimum compatibility code is written and tested offline. Nothing was deployed; no Vercel account, project or service was touched.
- Live compatibility is **not** claimed. Eight things only a real deployment can show are listed in section 7 and 9.
- Three protections cannot be guaranteed on Vercel (section 6): the rate limit, the concurrency limit and sessions are per instance, and the monthly CPU quota can be exhausted by traffic. They were not weakened; they are documented as limits.
- One decision is yours: where the 262 MiB model file is downloaded from (section 4).

## 2. What changed

| File | Change |
|---|---|
| `backend/vercel_app.py` (new) | Entry point. Runs `vercel_runtime.prepare()`, then `from backend.server import app`. The server itself is untouched and knows nothing about Vercel. |
| `backend/vercel_runtime.py` (new) | Fills in fixed Vercel defaults, **refuses to start** on any unsafe configuration, and downloads the pinned model into `/tmp` with integrity checks. |
| `backend/api_protection.py` | New opt-in `TG_CLIENT_IP_SOURCE=vercel` (default off, unchanged behaviour). Reads the visitor from `X-Forwarded-For`, accepting exactly one valid IP, otherwise one shared stricter bucket. Honoured only when `VERCEL` is set. |
| `pyproject.toml` (new) | Dependencies = `requirements-cloud.txt` pin for pin, `requires-python >=3.12,<3.15`, `[tool.vercel] entrypoint = "backend.vercel_app:app"`, not packaged as a library. |
| `vercel.json` (new) | Only `maxDuration: 300` for the function. No rewrites, headers or routes. |
| `.vercelignore` (new) | Allow-list: `backend`, `frontend`, `legal`, `legal-status`, `snapshot-store`, `pyproject.toml`, `vercel.json`. Keeps the research `requirements.txt` (torch, jupyter), both index directories, the model, notebooks, eval, tests and data out of the upload. |
| `deploy/vercel/vercel.env.example` (new) | Placeholders only. |
| `tests/test_vercel_pilot.py` (new, 61 tests) | Section 8. |
| `tests/test_pages_build.py` | One guard widened: it said "no Vercel anywhere". It now forbids Vercel only in the Pages workflow, scripts, Render/OCI files and `requirements-cloud.txt`, and allows the Vercel files above. |

Not changed: retrieval, grounded answers, legal gates, provider chain, embedding code, both indexes, the registry, `legal/`, `legal-status/`, `backend/server.py`, `backend/index_snapshot.py`.

## 3. Vercel facts used

| Fact | Status |
|---|---|
| Entry point syntax `[tool.vercel] entrypoint = "package.module:app"`; the FastAPI page uses `backend.server:app`; auto-detected names include `app.py`, `index.py`, `server.py` | DOCUMENTED — [Python runtime](https://vercel.com/docs/functions/runtimes/python) (2026-08-12), [FastAPI](https://vercel.com/docs/frameworks/backend/fastapi) (2026-11-14) |
| Python 3.12 (default), 3.13, 3.14; set through `pyproject.toml`, `.python-version` or `Pipfile.lock` | DOCUMENTED — Python runtime |
| Dependencies from `pyproject.toml`, `requirements.txt` or Pipfile. **Precedence and installer (uv or pip): not stated** | UNKNOWN — handled by uploading only `pyproject.toml` |
| Python bundle 500 MB uncompressed; no tree-shaking; Large Functions beta needs opt-in | DOCUMENTED — [Limitations](https://vercel.com/docs/functions/limitations) (2026-08-24) |
| `.vercelignore` is supported; allow-list form (`/*` then `!path`) is documented | DOCUMENTED — [vercel-ignore](https://vercel.com/docs/deployments/vercel-ignore) (2025-03-12) |
| `functions` → `maxDuration` up to the plan maximum (Hobby 300 s); memory cannot be set with fluid compute | DOCUMENTED — [vercel.json](https://vercel.com/docs/project-configuration/vercel-json) (2026-08-14; page truncated), Limitations |
| Vercel overwrites `X-Forwarded-For` with the client's public IP "to prevent IP spoofing"; no proxy IP list is given | DOCUMENTED — [Request headers](https://vercel.com/docs/headers/request-headers) (2025-12-13) |
| Writable `/tmp` up to 500 MB; filesystem otherwise read-only; persistence of `/tmp` between invocations | DOCUMENTED size ([Runtimes](https://vercel.com/docs/functions/runtimes), 2026-08-12); persistence UNKNOWN |
| Whether module import time counts toward `maxDuration`; any initialisation limit | UNKNOWN — not stated |
| Hobby source upload size limit | UNKNOWN — not stated |
| That Vercel sets the `VERCEL` environment variable | General knowledge; I did not find it on a page I read. The code uses it only as a safety condition (see section 6) |

## 4. How the model and the snapshot are loaded

**Model.** The pinned file is 274,290,656 bytes, SHA-256 `970aa74c…ef0e6`. With about 415 MB of dependencies it cannot ship inside a 500 MB Python bundle without Large Functions, whose availability on Hobby is UNKNOWN. So it is downloaded into `/tmp` on a cold start (`backend/vercel_runtime.py`):
- size and SHA-256 are checked **while streaming**, the file is written to a `.part` file, fsynced and renamed into place only if both match;
- an existing file is re-hashed and reused, otherwise replaced; a corrupt file is never trusted;
- `flock` serialises processes sharing a `/tmp`: in the test, four racing workers produce one download;
- https only, no credentials in the URL, redirects may not leave https, 150 s time budget, one retry for a transient network error, none for a checksum mismatch;
- the URL (which may be a pre-signed link) never appears in a log or an error;
- the engine still hashes the file when it loads it, and the probe-vector check against the snapshot manifest still runs.

**The host of the file is your decision.** I checked the Hugging Face `nomic-ai/nomic-embed-text-v1.5-GGUF` f16 file: its size (274,290,560) and SHA-256 (`f7af6f66…`) **do not match** the pinned model, so it must not be used. The pinned file is the Ollama blob. Its public content-addressed URL `https://registry.ollama.ai/v2/library/nomic-embed-text/blobs/sha256:970aa74c…` answered a HEAD request with HTTP 200 and `content-length: 274290656`, which equals the pinned size. That HEAD check was later followed by a full download and verification (section 10): the artifact is confirmed, the host's long-term stability is not. It is a third-party service and not documented as a stable download CDN; the SHA-256 check makes a wrong or tampered file harmless, but the host can still be unavailable or rate-limit a 274 MB fetch on every cold start. Alternatives (a different host you trust, or Large Functions with the file in the bundle) need your choice. Nothing is hard-coded: `KYR_MODEL_URL` is required in the Vercel environment.

**Snapshot.** The verified snapshot (about 4.4 MB) ships in the bundle under `snapshot-store/` (`TG_SNAPSHOT_STORE=local`, read-only) and is restored into a **per-process** directory under `/tmp` (about 16 MB each) by the existing `index_snapshot` code: manifest, pin, archive hashes, tree digest, chunk count, 768 dimensions, family, lifecycle registry and audit chain. Per-process directories remove the only shared-path hazard (the restore stages archives under fixed names). The real s11 snapshot **has not been published into the repository**: `snapshot-store/` does not exist yet (section 9, step 1).

## 5. Limits check

| Limit | Result |
|---|---|
| Bundle 500 MB | ESTIMATED about 422 MB: the dependency closure is 415 MB unpacked on macOS (106 packages); the upload is 6.7 MB (63 files, VERIFIED in the rehearsal bundle, including the 4.4 MB snapshot). About 78 MB margin. Linux wheel sizes are UNKNOWN; my PyPI check failed on a certificate error, so I have no Linux numbers. `VERCEL_ANALYZE_BUILD_OUTPUT=1` (reported for Vercel builds; confirm) should list sizes at build time. |
| `/tmp` 500 MB | The model (274 MB) plus one restore (16 MB) is about 290 MB. Each additional process on the same instance adds 16 MB. |
| Memory 2 GB | VERIFIED on macOS: 481 MB after start-up, 655 MB after chat traffic. Linux and Vercel unmeasured. |
| Duration 300 s | `maxDuration` 300. Start-up measured 10.1 s on macOS with the model already present; the real cold start adds the download (UNKNOWN) and Linux CPU time (earlier measurements put start-up CPU at about 13.5 s). Whether import time counts toward the limit is UNKNOWN. |
| Provider calls | Worst case about 31 s with `PROVIDER_TIMEOUT_SECONDS=12` and `PROVIDER_MAX_RETRIES=0` (in the env example). |
| Request body | The app's 8,192-byte cap is far below Vercel's 4.5 MB. |

## 6. Safeguards

| Safeguard | On Vercel |
|---|---|
| Fail-closed legal answering, grounded validation, citations, approval gates, source status | **Preserved** (code unchanged). No signed approval exists, so every legal question is "unavailable". Rehearsal: `/ready` 200 with `answering: false`; `/chat` returned the "not available yet" answer. |
| Groq → Gemini → unavailable; no Ollama | **Preserved.** The start-up validator refuses `OLLAMA_ENABLED=true`. Rehearsal: 0 outbound HTTP calls with no keys set. |
| Nomic model, prefixes, 768 dimensions, s11, registry hash binding | **Preserved.** Same engine and hash; the rehearsal snapshot was built from a copy of s11 and carries its `140cd200…` binding in its version name. Query vectors were 768-dimensional. Exact parity on Vercel's CPU and Python 3.12 is **UNKNOWN** until the benchmark runs there. |
| Per-client rate limit (10 per minute) | **Preserved per instance only.** Keyed by the visitor's IP from `X-Forwarded-For`, which Vercel documents as overwritten. Rehearsal: ten requests accepted, then 429; a different IP accepted. **Not global across instances.** Vercel's instance count cannot be capped from what I read. If the platform does not deliver a single valid address, everyone shares one stricter bucket, never a free one. |
| Concurrency limit (2 questions) | **Per instance only.** More instances can run more questions at once, which spends CPU quota faster. |
| Session limits (500, 1,800 s) | **Per instance only, and lost when the instance goes away.** A visitor may lose conversation context mid-chat. Not guaranteed. |
| Route-based protection | Matches the exact path `POST /chat`. If the platform changes the path the guard would silently not apply. **UNKNOWN until a preview shows a 429 after ten requests.** |
| Monthly Active CPU quota (4 h) | **Not mitigated.** About 6–7 CPU-seconds per question (measured elsewhere) means roughly 2,000 questions a month; at the limit the feature stays unavailable for up to 30 days (DOCUMENTED, [Hobby plan](https://vercel.com/docs/plans/hobby), 2026-11-12). The rate limit does not stop a distributed flood. |
| Hobby terms | "Personal or non-commercial use"; Vercel may disable a Hobby project (DOCUMENTED, [Terms](https://vercel.com/legal/terms) §4, 2026-10-19). A free portfolio demo is probably acceptable; "commercial" is not defined on the pages I read. |
| Other routes | `/docs`, `/openapi.json`, `/` and `/static` are served by the function, and any request to them can trigger a heavy cold start. Keep the frontend on GitHub Pages as it is now. `/approval/refresh` returns 404 (rehearsal). |

Also observed, not caused by this work: two threads of **one process** restoring a snapshot at once fail intermittently inside chromadb's client creation (a `KeyError`). Production restores once per process at import, so it does not apply, and the concurrency tests therefore use separate processes. Do not add threaded restores.

## 7. Verification and what it does not show

**Tests (VERIFIED, offline, `tests/test_vercel_pilot.py`, 61 tests, stable over repeated runs):**
- **Files and entry point:** dependencies equal `requirements-cloud.txt`; no research package can be installed; the entry point has documented syntax and points at the unchanged server; the API contract decorators are unchanged; `vercel.json` is duration-only and within the Hobby maximum; the allow-list is exact, the upload is under 20 MB, and no model, index or `requirements.txt` is in it. The test copies only the allow-listed paths and imports `backend.server` there, so an omitted path would fail.
- **Environment example and validation:** placeholders only; 15 unsafe settings are refused (Ollama, `EMBEDDING_VERIFY=off`, missing or malformed pin, a different model, another store, a missing client-IP source, wrong paths, plain-http or credentialed model URL, and so on); messages name variables and never echo values; defaults never overwrite the operator and never invent a safeguard.
- **Model download (injected fake network):** atomic landing, reuse, corrupt-file replacement, wrong bytes, truncation, oversize, announced-size mismatch, transient retry, 4xx not retried, 5xx retried once, missing file and URL, plain http never contacted, time budget, no free space, response always closed, four racing workers download once, stuck lock times out, redirect downgrade refused, the download URL never appears in an error, `prepare()` validates before it downloads anything and refuses non-pinned bytes.
- **Fail closed at import:** importing the entry point with no configuration fails and names the missing variables; the server is never imported.
- **Client identity:** configuration rules; one valid IP accepted; lists, repeats, garbage and empty values go to one shared bucket; a forged prefix cannot buy a fresh bucket; the peer address is ignored in this mode; default behaviour unchanged; header ignored when `VERCEL` is unset.
- **Snapshot:** a read-only bundle restores into a writable directory and is never written to; three parallel processes restore separate verified copies; a tampered archive, missing archive, wrong pin, unexpected family and empty bundle all fail closed.
- **Mutation check:** removing the allow-list, the Ollama check, the single-header rule, the checksum check, the redirect check, and adding a `torch` dependency each made tests fail; the files were restored (verified with `cmp`).
- **Full offline suite:** 1,813 tests OK (1,752 before plus 61), 106 skipped, 1 expected failure. Run on Python 3.11, **not** 3.12.

**Local rehearsal (VERIFIED on macOS, not Vercel):** a scratch copy containing only the allow-listed paths, the real model file (its SHA-256 matched the pin), and a snapshot published from a **copy** of s11 into the scratch directory, with the real engine and the entry point. Results: `/ready` 200, every check ok, `answering: false`; embedding verified; 768-dimensional query vector; `/chat` 200 with the fail-closed answer; ten accepted then 429 for one client, a second client accepted; `/approval/refresh` 404; 0 outbound requests; start-up 10.1 s; 481 MB after start-up, 655 MB after traffic. To write the snapshot manifest, `index_snapshot publish` called the local Ollama for the 6 stored chunks plus 3 probe texts; that snapshot lives only in the scratchpad (its pin is for the rehearsal and must not be reused). Both index directories, the registry and the status files hash identically before and after (39 files), and `chroma_telangana_preview_s11` still has tree digest `140cd200…`. `tests/chroma.sqlite3` is the empty test artefact already listed in the earlier index audit.

**Not verified at all:** that Vercel accepts the entry point and `pyproject.toml`, which installer it uses, the real bundle size, Python 3.12 and Linux/x86 numerical parity, the model download from the chosen host and its duration, whether import time counts toward the limit, `/tmp` behaviour, the `X-Forwarded-For` value the function actually sees, that `/chat` is protected under the real path, cold-start time, and CPU use per question on Vercel.

## 8. Unresolved limitations

1. The model host is undecided, and a 274 MB download on each cold start is a cost in time, CPU quota and third-party reliance.
2. The real s11 snapshot is not published or pinned yet.
3. Rate limit, concurrency limit and sessions are per instance; the CPU quota can be exhausted; a 30-day lockout is possible.
4. No signed legal approval exists: every legal question stays "unavailable" on Vercel too.
5. The bundle margin is thin (about 78 MB) and rests on macOS sizes.
6. Python 3.12 is untested.
7. Hobby non-commercial terms apply and Vercel can disable the project.

## 9. Exact next steps

1. **Publish and pin the real snapshot** on your machine (this uses local Ollama for manifest probes): `python -m backend.index_snapshot publish` against `chroma_telangana_preview_s11` and `legal/lifecycle` into a new `snapshot-store/` directory (store settings as in the env example: `TG_SNAPSHOT_STORE=local`, `TG_SNAPSHOT_LOCAL_DIR=snapshot-store`), review the manifest, run `pin`, and keep the printed `TG_SNAPSHOT_PIN_SHA256`. The 4.4 MB `snapshot-store/` becomes part of the deployment (committing it is your call; nothing was committed).
2. **Decide the model host** and set `KYR_MODEL_URL` (https only). If you accept the Ollama registry candidate, a one-off download on your machine can confirm its SHA-256 before the deployment (I did not download it).
3. In a **new private Vercel project** (Hobby, no card), set the variables in `deploy/vercel/vercel.env.example`, with the real keys, pin, model URL and `TG_CORS_ORIGINS`. Set `VERCEL_ANALYZE_BUILD_OUTPUT=1` for the first build.
4. Deploy a **preview**, then check, in order: build installs and the bundle is under 500 MB; the function starts (a refusal message names the variable); `/ready` 200 and `/status` embedding verified; the cold-start time and download time; `POST /chat` gives the fail-closed answer; **eleven rapid requests from one client give a 429** (proves the path match and the client-IP header); a second network is not limited by the first; `/status` shows `client_ip_source: vercel`; repeated cold starts leave `/tmp` within 500 MB.
5. Run the 108-case retrieval benchmark against the preview or a copy of its runtime; require the same hit@5 / recall@5 / MRR as the Stage 17 record.
6. Only after those pass, point `kyr-api-base` in the GitHub Pages build at the Vercel URL, and decide how to watch the CPU quota (Vercel's usage page).

If step 4 shows the bundle over 500 MB, the model download too slow, or the rate-limit test failing, stop: the options then are Large Functions (if offered on Hobby) or returning to OCI.

## 10. Model source verified (2026-11-15, follow-up)

Candidate: `https://registry.ollama.ai/v2/library/nomic-embed-text/blobs/sha256:970aa74c…ef0e6`, downloaded through the real `vercel_runtime.ensure_model` code path into a scratch directory, then checked independently. No Ollama server call, no change to the model, embedding configuration, index, registry, pin or retrieval code.

| Check | Result |
|---|---|
| Size | VERIFIED 274,290,656 bytes (the pinned size) |
| SHA-256 | VERIFIED `970aa74c0a90ef7482477cf803618e776e173c007bf957f635f1015bfcfef0e6` (the pin); `cmp` shows it is **byte-identical** to the local Ollama blob the engine already uses |
| Format | VERIFIED GGUF version 3, architecture `nomic-bert`, name `nomic-embed-text-v1.5`, 12 layers, width 768, 12 heads, pooling 1, 112 tensors, F16 (`general.file_type` 1) |
| Loader | VERIFIED `nomic_local.NomicEngine` loads it with the pin enforced and `identity_problems` empty; no engine change |
| Embeddings | VERIFIED 13 `search_query:` texts (short, rule-number, long, one-word) plus a `search_document:` text: 768 dimensions, norms 0.99999994 to 1.0000001, bit-identical to the engine on the local blob (cosine 1.0, max difference 0). Unprefixed text is refused. The 3 probe vectors stored in a snapshot manifest (made by Ollama at publish time) match with cosine 0.99999976 to 1.0 (floor 0.995, documented engine tolerance 0.9999993) |
| Credentials | VERIFIED none sent or needed. GET returns a 307 to a pre-signed Cloudflare R2 URL (https, `X-Amz-Expires` 86,400 s) generated per request; the URL to put in `KYR_MODEL_URL` carries no secret, and the signed link is never stored |
| Behaviour | VERIFIED range requests work (206, `Content-Range` total 274,290,656); five probes over 15 s all returned 206 in about 1 s; no rate-limit headers seen. Full download 40.0 s wall, 3.0 CPU-s, 46 MB peak memory on this Mac. The code's https-only redirect rule accepted the R2 redirect |
| Local note | This Mac's Python had no CA bundle, so the first attempt failed with a certificate error; it passed with `SSL_CERT_FILE` set to the certifi bundle (verification stayed on). Vercel's Python is not expected to need that, but it is UNKNOWN |

**Recommendation: GO** to use this artifact through `KYR_MODEL_URL` for the preview test. The bytes are exactly the pinned model and the engine loads it unchanged.

**Not established (stability, not correctness):** Ollama does not document direct blob download; community tools use this path, but I found no Ollama terms, SLA or retention promise (the digest is immutable, but the blob could be moved or withdrawn). Whether Vercel's network reaches the registry and R2, and how long the download takes there, is UNKNOWN until the preview. A wrong or missing file can only make the function refuse to start, never serve a different model. If you need more than a demo's reliability, keep a fallback: Large Functions with the file in the bundle, or a host you control serving the same bytes.

## 11. Real s11 snapshot published and pinned (2026-11-15, follow-up)

`snapshot-store/` now holds the real pilot snapshot (5 files, 4.4 MB; uncommitted). Published from a scratch copy of `chroma_telangana_preview_s11` and `legal/lifecycle` with `python -m backend.index_snapshot publish`, the in-process Nomic engine (pinned SHA-256 `970aa74c...`) and no Ollama. `EMBEDDING_VERIFY=off` was set for that one run only, because probes cannot exist before the first publish; publish's own re-embedding check (6 stored chunks, floor 0.9999) still ran and gave a minimum cosine of 0.99997333.

| Item | Value | Label |
|---|---|---|
| Version | `20261115T130522Z-140cd20089` | VERIFIED |
| **`TG_SNAPSHOT_PIN_SHA256`** (manifest SHA-256) | `5546de235e57d3e4e10d8080343febb99566e61c8cdc1f06b1093f2d767af38c` | VERIFIED (a pin is a public checksum, not a secret) |
| Index archive SHA-256 / size | `0973e1c6...1848` / 4,321,974 bytes | VERIFIED |
| Lifecycle archive SHA-256 | `1c133365...2774` | VERIFIED |
| Chunks / sources / events | 590 / 20 / 21 | VERIFIED |
| Index tree digest | `140cd200...be29`, equal to the registry's `bootstrap.index_tree_sha256` | VERIFIED |
| Registry / audit SHA-256 | `219df1c7...de2a` / `12f285a7...232c7`, equal to the earlier audit | VERIFIED |
| Embedding | `nomic-embed-text-v1.5`, 768 dimensions, unit norm, `search_document: ` / `search_query: `, floor 0.995, 3 probes | VERIFIED |

Checks: tree digest and `document_lifecycle verify` (`consistent`) and `audit-verify` (`audit history intact`) on the staged copy before publishing and again on the extracted archives; `index_snapshot verify` (`ready`, no problems, 3.2 s); archive SHA-256 equal to the manifest; the extracted trees equal the originals; no lock file in the archive. Restore rehearsal with the real, unchanged `backend.vercel_app` on a scratch bundle holding only the `.vercelignore` allow-list (6.8 MB, 62 files), a read-only `snapshot-store/`, a scratch `TMPDIR` and the pin: `/ready` 200 with every check `ok` (snapshot restore 0.4 s, pinned, 590 chunks, embedding verified against the 3 probes), `answering` false, legal questions answered "not available yet", 10 questions accepted, then 429 for one client IP while another IP was accepted, `/approval/refresh` 404, 0 outbound HTTP calls. A wrong pin gave `pin_mismatch`, `/ready` 503, 0 chunks. All 29 files of the original index, `legal/` and `legal-status/` hash the same before and after. Full suite: 1,813 tests OK, 106 skipped, 1 expected failure.

Not shown: restore on Vercel's Linux/Python 3.12 runtime, and that `kyr-pilot-operator` (the name recorded in the manifest) is acceptable to you. Set the pin above in the Vercel project; if the snapshot is ever republished the pin changes.

## 12. Preview deployment review (2026-11-15, follow-up)

Reviewed `vercel.json`, `.vercelignore`, `pyproject.toml`, `deploy/vercel/vercel.env.example`, `snapshot-store/` and the runtime. Step-by-step instructions: `VERCEL-PREVIEW-SETUP-GUIDE.md`. Nothing deployed, no account connected, no key entered, nothing committed.

**Changed (3 items):**
1. `pyproject.toml`: `requires-python` `>=3.12,<3.15` to `>=3.12,<3.13`. PyPI shows `numpy==1.26.4` has a Linux wheel only for Python 3.12; Vercel's documentation does not say which version a range selects, so 3.13 or 3.14 could have forced a source build and failed. All 103 packages resolved with `pip --platform manylinux x86_64 --python-version 3.12 --only-binary` are wheels (metadata only, nothing installed); none is a research or development package. The compressed wheels total 128 MB; installed size on Vercel is NOT MEASURED (limit 500 MB).
2. `deploy/vercel/vercel.env.example`: the real pin and the verified `KYR_MODEL_URL` replace the placeholders; `TG_SOURCE_STATUS_FILE` is removed (a relative path depends on the working directory; unset uses the bundled file by absolute path, tested from two working directories).
3. `tests/test_vercel_pilot.py`: the Python test now asserts exactly 3.12; a new test asserts that the pin in the example equals the SHA-256 of the published manifest and `active.json`.

**Confirmed:** `snapshot-store/` is in the upload (63 files, 6.95 MB; emulated with the `.vercelignore` rules; no `.env`, key, model, index, SQLite file or `requirements.txt`; no credential pattern in any uploaded text file). A clean staging folder made with `rsync` of the seven allow-listed paths holds the same 63 files. It restores and serves identically to the earlier rehearsal (read-only store, pin, 0 outbound calls, 10 accepted questions then 429, `/approval/refresh` 404, answering false).

**Found, not changed:** Vercel's documentation does not state that `.vercelignore` applies to Git-integration deployments, so the guide deploys from the staging folder with the CLI. `.vercelignore` still uploads `legal/lifecycle` (a public copy of the registry the runtime never reads; kept, because a test pins the allow-list). No lock file, so transitive versions float at build time. Vercel Authentication's default scope and cross-origin behaviour are not stated.

## 13. Model held in memory (2026-11-15, follow-up; NOT deployed)

**Why:** the first preview deployment failed at start-up with `ModelFetchError: no_space`. Vercel reported a 411.59 MB bundle and about 82 MiB free; the model needs 261.6 MiB plus the old 64 MiB margin. The bundle and `/tmp` appear to share about 500 MB (392.5 MiB + 82 MiB is about 475 MiB; inferred, not documented). Sections 4 and 10 describe the earlier `/tmp` download; sections 1 to 9 are otherwise unchanged. **The earlier deployment does not work, and this change has not been deployed or tested on Vercel.**

**Change:** `vercel_runtime.fetch_model_to_memory` streams the pinned model into an anonymous private `mmap`, checking the byte count and SHA-256 while streaming; only a verified buffer is stored (`nomic_local.set_memory_model`). `EMBEDDING_MODEL_SOURCE=memory` makes the provider build `NomicEngine(None, pin, buffer=...)`, which hashes the buffer again before parsing and keeps a reference to it. No model file and no lock file is written. The file path (`EMBEDDING_MODEL_FILE`) is unchanged for development and is refused on Vercel. `ensure_model` (the `/tmp` download) is kept, unused.

| Local measurement (this Mac, real model and snapshot, scratch `TMPDIR`) | Value | Label |
|---|---|---|
| Download into memory, real registry URL (size and SHA-256 checked while streaming) | 27.2 s (the same download took about 40 s earlier); 0.8 s from a local file | MEASURED locally; Vercel network UNKNOWN |
| Second hash inside the engine / engine initialisation including it | 0.27 s / 0.35 s | MEASURED |
| Snapshot restore (verify, extract, validate) | 0.4 s | MEASURED |
| `backend.server` import (embedding, index, lifecycle) | 8.8 s | MEASURED |
| Cold start total, network case | 36.4 s (about 10 s with the model already local) | MEASURED locally; **a Vercel cold start is ESTIMATED at 60 to 90 s** (slower CPU share, network) |
| RSS after the download / after start-up / after 12 questions | 314 MB / 719 MB / 719 MB peak | MEASURED; Vercel limit 2 GB (DOCUMENTED) |
| Written to `/tmp` | 16.6 MB (snapshot work directory), no `.gguf`, `.part` or `.lock` file | MEASURED; about 66 MiB of the 82 MiB would remain (ESTIMATED) |
| `/ready` | 200, all seven checks `ok`, 590 chunks, `answering` false; legal questions "restricted"/"unavailable", 0 sources; 8 more questions accepted, then 429; 0 provider calls | MEASURED |
| Wrong byte in the download (same size) | refused (`checksum_mismatch`), nothing in memory, no file written | MEASURED |
| Model never loaded | snapshot restores, `/ready` 503 (`embedding` failed), nothing answers | MEASURED |

**Tests:** 41 new tests (38 in `tests/test_vercel_memory_model.py`, 3 net in the frontend tests), full suite 1,855 OK, 106 skipped, 1 expected failure. Three deliberate breakages (no hash check, engine ignores the pin for buffers, the page sends while starting) each made tests fail. Buffer-backed embeddings are bit-identical to file-backed ones for the tiny fixture and for the real model (768 dimensions).

**Page:** default wait 30 s to 120 s; "The service is starting; the first request may take a little longer."; no sending while the first status check or a question is pending (typed text is kept); the `/status` call is made once with the full wait, and the 6 automatic retries were removed because each could wake another copy of the function. A manual "Try again" remains.

**Still unknown until a preview deployment:** Vercel's network access and speed to the registry, whether module-import time counts against `maxDuration`, the real `/tmp` free space, whether a concurrent request during a cold start starts a second instance (and a second 274 MB download), and the Active CPU cost of each cold start (about 16 CPU-s locally). A 2 GB instance holds about 719 MB, so two concurrent questions fit.

**Rollback:** pre-change copies of the nine edited files are in `~/kyr-backups/pre-memory-loader/` (nothing is committed). Copy them back over the same relative paths in the project and delete `tests/test_vercel_memory_model.py`. In code, restoring the old behaviour is `prepare()` calling `ensure_model` and `apply_defaults` setting `EMBEDDING_MODEL_FILE` again.
