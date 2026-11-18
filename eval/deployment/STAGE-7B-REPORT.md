# Stage 7B: deployment infrastructure

**Status: the deployment code and configuration are implemented and tested offline. Cloud embeddings are BLOCKED** because no
genuinely free hosted provider of the index's exact model could be verified. Nothing was deployed, no account was created, no
hosted-embedding, Groq or Gemini call was made, nothing was paid for, the real index and lifecycle registry are unchanged, and all 20
legal sources are still pending (quarantined). Nothing is committed.

> **Measurement caveat (added in Stage 7B.1; the memory and start-up figures in section 7 are provisional).** Two coding sessions
> worked on Stage 7B at the same time and both ran `eval/deployment/stage7b/measure.py` against the same shared outputs. The two runs
> overlapped (their snapshot versions were stamped six seconds apart), so each ran on a machine that was also running the other
> measurement. This report did not say so when it was first written. Shared files affected: `eval/deployment/stage7b/measurements.json`
> and `eval/deployment/stage7b/measure.out` (whichever run finished last wrote them; the section 7 figures come from that file), and
> this report itself (`STAGE-7B-REPORT.md`, edited by both sessions; the text of its Memory and Tests sections was written by one session while the other was still
> preparing its own version of the same sections). The other run's numbers were printed to a console only and were not stored. Peak memory is per process and was less
> affected than timings, but the spread was wider than a controlled run shows. **Treat all section 7 numbers as provisional.** The
> original files are kept unmodified (their SHA-256 is recorded in `stage7b1/original_7b_evidence.sha256`); the controlled single-process
> re-run is stored separately in `eval/deployment/stage7b1/controlled/` and is described in `STAGE-7B1-REPORT.md`. Its upper-end peaks
> are higher than the section 7 table: the 7B table understated the worst case.

Target architecture (unchanged): GitHub (source) → GitHub Pages (static frontend) → Render Free (FastAPI) → Cloudflare R2 (immutable
index snapshots) → a hosted query-embedding provider (blocked) → generation Groq → Gemini → safe "unavailable"; Ollama is local
development only.

## 1. What is blocked, and what unblocks it

| Item | State | Needed to unblock |
|---|---|---|
| Cloud query embeddings | **Blocked.** The service starts, reports `corpus_ready=false` and answers 503 (never Ollama) until a provider is configured and passes the probe check. | An approved, zero-cost provider of `nomic-embed-text-v1.5` (section 3) |
| Live check of any provider | Not done (no accounts, no live calls, by instruction) | An account, then one server start with the provider configured: the probe check against the snapshot manifest runs at start and decides compatibility |
| R2 bucket, Render service, Pages site | Not created | Operator action (section 9) |
| Render memory on Linux | Unmeasured | A first run on Render's free instance (section 7) |
| Signed approval record and trusted keys | Do not exist (by design) | Human legal review; until then every legal question is answered "unavailable" |

## 2. Files

Created:
- `scripts/check_cloud_env.py`: offline validator of the cloud environment (names and reasons only, never values); runs in front of uvicorn.
- `tests/test_stage7b_embeddings.py` (22), `tests/test_stage7b_snapshots.py` (30), `tests/test_stage7b_deploy.py` (26).
- `eval/deployment/stage7b/`: `run_regressions.sh`, `run_real_per_module.sh`, `measure.py`, `measure_child.py`, logs, `measurements.json`, integrity digests.

Modified:
- `backend/embedding_provider.py`: `nomic_atlas` adapter, cloud guard (`cloud_mode`), docstring.
- `backend/index_snapshot.py`: publish read-back verification, resumable write-once uploads, `index_version`, store retries, download retry, safer `rollback`, clearer R2 configuration error.
- `deploy/render.yaml`, `deploy/cloud.env.example`, `.env.example`: Fireworks defaults removed; embedding variables have no default; `autoDeployTrigger: "off"`; validator in the start command; graceful shutdown; `MALLOC_ARENA_MAX=2`.
- `scripts/build_pages.py`: `--require-api-base`, Nomic key pattern in the secret scan. `.github/workflows/pages.yml`: uses `--require-api-base`.
- `tests/test_cloud_readiness.py` (two assertions that encoded the Fireworks default), `tests/test_cloud_embedding_real.py` (a Nomic-shaped fake and `test_12`).

Not touched: retrieval, ranking, fusion, thresholds, grounded-answer validation, lifecycle code, the 4F/4G masks, the real index, the real registry, the frontend source, `backend/server.py`.

## 3. Embeddings: free-tier research and compatibility

The index was built with Ollama `nomic-embed-text` (v1.5, 768 dimensions, unit norm, squared-L2, prefixes `search_document: ` / `search_query: `). Another model with the same dimensions cannot query it. All facts below were read from official pages on 2026-11-13; no account was created and no embedding call was made.

| Option | Same model? | Free? | Verdict |
|---|---|---|---|
| **Nomic Atlas embedding API** (`POST https://api-atlas.nomic.ai/v1/embedding/text`) | Yes: `nomic-embed-text-v1.5`, 768 dimensions (Matryoshka 64-768) | The plans page says the Free plan needs "no credit card" with "limited agent requests". **No embedding-specific free allowance is documented**, nor what happens after it. Rate limit: 1200 requests per 5 minutes per IP | **Candidate, unverified.** Not documented: whether vectors are L2-normalised; the exact prefix the server applies for `task_type`; batch size; whether an API key needs a card. An account is needed. |
| Hugging Face Inference Providers | No provider serves the model ("isn't deployed by any Inference Provider") | Free accounts get no credits; usage needs purchased credits or PRO | **Rejected** |
| Cloudflare Workers AI | **No.** Offers `bge-small/base/large-en-v1.5`, `bge-m3`, `embeddinggemma`, `qwen3-embedding`, `plamo`. No nomic model. `bge-base-en-v1.5` is also 768-d, which is exactly the trap | 10,000 neurons/day free; card requirement not stated | **Rejected: incompatible space** |
| Fireworks (`nomic-ai/nomic-embed-text-v1.5`) | Yes | **No** (paid per token) | **Removed as default**, not integrated |
| In-process ONNX on Render | Same weights, but a different numeric format than Ollama's GGUF | Free | **Not evaluated.** A 512 MB instance already runs at roughly 250-300 MB; model weights would likely not fit. Would need its own probe check. |
| A different free host for the whole backend (e.g. a Space with more RAM) | n/a | not researched | Outside the approved architecture; a decision for the owner |

**Implemented without assuming compatibility.**
- `EMBEDDING_PROVIDER` is `ollama` (local), `openai_compatible` (Stage 7A, any OpenAI-style `/embeddings` host) or `nomic_atlas` (new). None is a default in any cloud file.
- **Cloud guard:** when `TG_SNAPSHOT_STORE=r2`, `TG_CLOUD=1` or `RENDER=true`, an unset provider and `ollama` are configuration errors. The guard is then `misconfigured`, `/status` shows `corpus_ready=false`, `/chat` answers 503/unavailable, and no Ollama client is ever built (tested).
- **`nomic_atlas` adapter:** turns the application's `search_query: ` / `search_document: ` prefix into `task_type` and removes it from the text (the API has no "no task" mode); one request per task; a text with no recognisable prefix is refused before anything is sent; same timeout, bounded retry, Retry-After, circuit breaker and key-handling rules as the other hosted adapter.
- **Compatibility is decided by evidence at runtime, not by a label:** the manifest carries probe vectors made by the index's own model; before its first query the provider embeds the probe texts and each must reach cosine ≥ 0.995 against the reference. A wrong dimension, an unnormalised vector, a family label that is not `nomic-embed-text-v1.5`, or a probe mismatch makes the provider permanently incompatible for that process. Without probes a hosted provider is not trusted. No corpus text is ever sent to the provider.

Evidence this gives, honestly bounded: tests with a local fake prove the plumbing, the failure behaviour and, with a fake that relays real Ollama vectors, that the adapter's prefix round trip returns **identical retrieval to local Ollama** (exact mode; near-identical in HNSW). They do **not** prove that Nomic's server produces the same numbers as the local model; only the live probe check at first start can, and it fails closed if they differ.

## 4. R2 persistence (`backend/index_snapshot.py`)

Layout, load order and failure states are as in the Stage 7A report (section 7). Stage 7B closes the gaps against the 7B list:

| Requirement | Implementation |
|---|---|
| Upload immutable snapshots | Write-once objects; an existing version's manifest is never replaced. |
| Active manifest only after a validated upload | `publish` writes archives, then the manifest, then **reads all of it back from the store** (`verify_uploaded`: manifest bytes, archive sizes and SHA-256) and only then writes `active.json`. A corrupted, lost or unreadable object means no pointer. |
| Interrupted uploads | An archive left by an interrupted publish of the same content is reused (not rewritten); different content under the same key is refused. A version exists only once its manifest does. A failed pointer write leaves the old snapshot active and the error names the command that activates the new one (`rollback --to <version>`). |
| Previous snapshot preserved | No store has a delete operation and none is issued (tested over an R2-shaped fake: only GET/HEAD/PUT). `active.json` records the previous version. |
| Failed downloads | Streamed to `.part`, size and SHA-256 checked, then moved; one retry when the transfer itself breaks; never retried on a checksum mismatch. The R2 client retries timeouts, connection errors, 429 and 5xx (2 retries, exponential backoff, re-signed each attempt); 403/404/400/412 are not retried. |
| Rollback | Reads the target snapshot back before repointing. Review its lifecycle registry first: an older registry can list a document that was later withdrawn. |
| Manifest metadata | `version` (identifier), `index.archive` (object key), `index.sha256`, `index.index_version` (new: `collection@<tree digest>`), `embedding.model` / `dimensions` / `family`, `index.chunk_count`, `created_at`, `lifecycle.registry_sha256` and `tree_digest`. All required by `validate_manifest`. |
| Credentials | Environment only; read-only token for the server. |

Operator notes: orphaned objects from an interrupted publish are harmless (unreferenced) and are never deleted automatically; two operators publishing at once is not guarded (the pointer is last-writer-wins).

## 5. Startup and recovery

Start: validator (`scripts/check_cloud_env.py`) → import `backend.server` → R2 client → pointer → manifest (checksum from the pointer, optional pin) → download with size/SHA-256 → safe extract → tree digests → index checks (chunk count, dimensions, profile, family) → registry checks (SHA-256, then the Stage 6 `ServeFilter`: registry, audit chain, index/registry consistency) → embedding guard configured from the manifest and verified against the probes → `corpus_ready` only if **every** step passed.

Every failure leaves a running but not-ready service: `/health` says alive, `/status` says why (`snapshot.state`, `embedding.state`), `/chat` answers "unavailable", nothing is created (no empty index), nothing is served. A warm restart re-hashes the cached archives instead of downloading them; a cold start from a fresh directory reproduces the same tree digests (tested). There is no automatic fallback to an older snapshot (an older registry could resurrect a withdrawn document); recovery is an explicit `rollback`.

## 6. GitHub Pages

`.github/workflows/pages.yml`: manual only (`workflow_dispatch`), minimal permissions (`contents: read`, `pages: write`, `id-token: write`), no secrets read, actions pinned to major versions, runs the frontend and build tests, then builds with `--require-api-base` (fails if `KYR_API_BASE_URL` is empty) and uploads `build/pages`. Tested: valid YAML, manual trigger only, build output directory equals the uploaded path, no other host referenced. The site is a single static page: no client-side routing, so refresh and deep links work; asset paths are relative so a project subpath works; output contains no `localhost`, no non-https URL, and no secret (a build handed sentinel secrets neither reads nor publishes them). Local development is unchanged (the API server still serves the page with an empty API base). Not run: the workflow was not executed and the site was not loaded cross-origin against a real backend.

## 7. Render

Blueprint `deploy/render.yaml`: one free web service, `autoDeployTrigger: "off"`, no disk, no extra instances. Start command: `python scripts/check_cloud_env.py && exec uvicorn backend.server:app --host 0.0.0.0 --port $PORT --workers 1 --no-server-header --timeout-graceful-shutdown 20`. Health check `/health` is liveness only; readiness is `corpus_ready` in `/status`. Secrets are `sync: false` and never in the file. The validator fails the deploy for: wrong environment, grounded answers off, local snapshot store, explicit directories, incomplete or non-https R2 settings, a missing or Ollama embedding provider, `OLLAMA_ENABLED` not false, any weakening flag (`TG_LEGACY_DEV_ANSWERS`, `TG_SNAPSHOT_ALLOW_STALE`, `EMBEDDING_VERIFY`, `TG_ENABLE_APPROVAL_REFRESH`, …) and CORS entries that are not exact https origins. It only warns (the service still answers "unavailable" safely) about a missing pin, a missing CORS origin, no generation key and no approval files.

**Memory and start-up (re-measured in 7B, `stage7b/measurements.json`, macOS arm64, 8 CPUs, machine not idle, load average about 5).** The 7B changes (retries, validator, adapter) are small; the numbers match Stage 7A.

| Configuration | Peak MB (3 runs) | Server import | Snapshot load (cold) |
|---|---|---|---|
| Cloud requirements (`requirements-cloud.txt`, torch/transformers blocked) | 212-233 (7A: 242) | 2.6-3.1 s | 0.57 s (download+verify 0.02, extract 0.08, registry/lifecycle checks 0.48) |
| Full development environment | 296-347 (7A: 368) | 8.6-9.6 s | 1.57 s |

The snapshot is 4.1 MB (index) + 0.2 MB (registry); the index unpacks to 10 MB. **Linux on Render is not measured.** Expected differences, stated as expectations not facts: glibc's per-thread arenas can raise resident memory (hence `MALLOC_ARENA_MAX=2`); shared libraries count the same; Render's own processes inside the 512 MB limit are not documented. Working budget: about 250-300 MB peak for the cloud set on Linux, leaving roughly 200 MB, which is thin but plausible for 590 chunks with exact search (no HNSW graph in memory). The 0.1 CPU share will make import, extraction and registry checks several times slower than here; at that ratio a cold start of tens of seconds plus about a minute of spin-up is the planning figure. Both must be confirmed on the first real start. Keep the cloud requirements: with torch installed the same server needs about 90-130 MB more.

## 8. Required environment variables

| Variable | Where | Value |
|---|---|---|
| `TG_ENVIRONMENT`, `TG_GROUNDED_ANSWERS`, `OLLAMA_ENABLED`, `TG_SNAPSHOT_STORE`, `TG_SNAPSHOT_PREFIX`, `TG_APPROVAL_FILE`, `TG_TRUSTED_KEYS_FILE`, `TG_SOURCE_STATUS_FILE`, `RAG_VECTOR_SEARCH`, `MALLOC_ARENA_MAX`, `PYTHON_VERSION` | blueprint (fixed) | `production`, `1`, `false`, `r2`, `kyr/`, secret-file paths, `legal-status/source-status.json`, `exact`, `2`, `3.11.9` |
| `R2_ACCOUNT_ID`, `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | dashboard (secret) | read-only token scoped to the bucket |
| `TG_SNAPSHOT_PIN_SHA256` | dashboard | optional; the reviewed manifest digest |
| `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `EMBEDDING_API_KEY` (+ `EMBEDDING_API_URL` for `openai_compatible`) | dashboard | **no default**; blocked until a provider is approved |
| `GROQ_API_KEY`, `GEMINI_API_KEY` | dashboard (secret) | optional; neither set means "unavailable" |
| `TG_CORS_ORIGINS` | dashboard | the Pages origin, e.g. `https://<owner>.github.io` |
| `KYR_API_BASE_URL` | GitHub repository **variable** | the Render service's https origin (public) |

## 9. Free-tier feasibility and billing risks

Verified on official pages on 2026-11-13 unless marked.

| Service | Free allowance | Risks for this project |
|---|---|---|
| GitHub Pages | Free for public repositories (not re-verified in 7B; private repositories need a paid plan) | None expected |
| Render Free web service | 512 MB RAM, 0.1 CPU, 750 free instance hours/month per workspace, spin-down after 15 minutes idle, about a minute to start, ephemeral disk, may be restarted at any time | Bandwidth and build minutes are included in unspecified workspace amounts; with **no payment method** overage suspends the free services, with one on file it can be billed. First request after idle waits about a minute (the frontend shows nothing meanwhile). Render may suspend a free service with unusually high outbound traffic. |
| Cloudflare R2 | 10 GB-month, 1 M Class A and 10 M Class B operations per month, free egress (Standard storage) | **Whether a payment method is needed to enable R2 is not stated on the pages read: unverified.** Each cold start is about 4 Class B reads (pointer, manifest, two archives); a snapshot is about 4.4 MB. Use is orders of magnitude inside the allowance. Failed-auth requests are not billed. |
| Nomic Atlas embeddings | Not documented for this endpoint (see section 3) | **Cannot be called zero-cost until verified.** Per-IP rate limit 1200 requests/5 min. |
| Groq, Gemini | Unchanged from Stage 7A (not called) | Provider terms can change |

Billing guardrails in the code: no paid host is configured anywhere (tested); the provider circuit breaker and bounded retries limit repeated calls after quota errors; nothing deploys automatically.

## 10. Tests

All commands are offline; no network or paid service is used (the only local service is Ollama for the real-backend modules).

| Suite | Exact | HNSW |
|---|---|---|
| Offline (`unittest discover`, real-backend tests skip) | 1343 run, OK (89 skipped, 1 expected failure) | 1343 run, OK (89 skipped, 1 expected failure) |
| Real backend, **one process per module**, 56 modules, `KYR_REQUIRE_REAL_BACKEND=1` | **1362 run, 0 failures, 0 skipped** | **1362 run, 0 failures, 0 skipped** |

(Stage 7A: 1264 offline / 1283 real. The difference is 78 new offline tests, plus `test_12` which needs the real index.)

New tests, by the 7B list:
- **Embeddings** (`test_stage7b_embeddings.py`, 22): local Ollama unchanged outside the cloud; cloud has no default provider and refuses Ollama (three triggers); Ollama is never built when hosted calls fail; Nomic request shape, task mapping, mixed batches, unprefixed text refused; missing/placeholder key, plain-http URL, missing model; malformed responses; 429 with Retry-After, long wait fails fast, bounded 5xx retries, timeout not retried, 401/403/422 not retried; quota exhaustion degrades to 503 and recovers; key never in exceptions, health or logs; model-family mismatch; dimension mismatch (permanent); unscaled vectors; probe check passes/fails; no probes means not trusted.
- **R2** (`test_stage7b_snapshots.py`, 30): interruption at every publish step leaves the previous snapshot active and loadable; interrupted first publish leaves nothing ready; resume without rewriting; failed pointer update; foreign content under an archive key refused; read-back catches a corrupted archive, a silently lost object and a corrupted manifest; rollback verifies first; earlier snapshots byte-identical after later publishes; no delete operation anywhere; manifest metadata present and enforced; R2 client retries (backoff, re-signing, which statuses are not retried, secret never in errors); broken downloads retried once, then not ready with nothing left behind; cold-start reproducibility and warm restart; over an R2-shaped fake, publish uses only GET/HEAD/PUT and the runtime only GET.
- **Startup** (same file, server level): missing, incomplete and insecure R2 configuration; corrupt registry or audit chain (`lifecycle_invalid`); index/registry disagreement (`index_invalid`); failed download on a cold start. Each: the server starts, `/health` is alive, `corpus_ready=false`, `/chat` is "unavailable", nothing is created. (The Stage 7A modules already cover the corrupt-snapshot, checksum, pin and hostile-archive cases.)
- **Frontend and deployment** (`test_stage7b_deploy.py`, 26): environment validator (every unsafe setting, no secret in output, script exit codes); blueprint (free plan, no paid resources, no embedding default, start command order, blocked until supplied); workflow validation (YAML, manual trigger, permissions, pinned actions, uploaded path equals build output, no other host); Pages build (https backend only, no localhost, no secret reaches output, Nomic key shape caught, no client-side routing, relative paths); local development still serves the page; Groq → Gemini → unavailable order with Ollama off and no provider called; secrets not in the frontend; no administration route and `/approval/refresh` is 404 in production. CORS behaviour is covered by the Stage 7A tests plus the validator's origin checks.
- **Real backend** (`test_cloud_embedding_real.py`, now 12): `test_12` runs the real server over a real index copy with the `nomic_atlas` adapter against a local Nomic-shaped fake that relays real Ollama vectors: retrieval equals local Ollama (identical in exact mode; HNSW within the Stage 7A tolerance), only `search_query`/`search_document` tasks reach the service and never with a prefix in the text, local Ollama is never contacted, state `ok` and `verified`.

Raw outputs: `stage7b/suite_offline_{exact,hnsw}.log`, `stage7b/real_{exact,hnsw}/` (one log per module, `summary.txt`), `stage7b/dev_cloud_real_exact.log`, `stage7b/measure.out`.

## 11. Known failures and unresolved issues

1. **Cloud embeddings are blocked** (section 1). The Nomic adapter exists and is tested against fakes only. Unverified for the live service: a free allowance for the embedding endpoint, vector normalisation, the exact prefix the server applies, whether an API key needs a card, and what the per-IP limit (1200 requests per 5 minutes) means behind Render's shared outbound addresses. If Nomic's vectors fail the probe check (cosine < 0.995) the service stays not ready by design.
2. **The single-process real-backend hang from Stage 7A is still unresolved.** It is avoided, not fixed, by running one process per module (all 56 modules, both modes, completed with no hang or Chroma error this time). Do not run the whole real-backend suite in one process and trust the result.
3. **HNSW is not run-to-run deterministic.** Exact mode asserts strict equality of hosted/Nomic-adapter and local retrieval; HNSW asserts near-identity (the Stage 7A tolerance).
4. **Unverified billing facts:** whether R2 needs a payment method to enable; whether Render's free tier needs one at creation; Render's included bandwidth and build-minute amounts. A card on file turns overage from suspension into charges.
5. **Linux memory and CPU on Render are unmeasured** (section 7). The 512 MB margin is a working estimate.
6. **Cold-start experience is unchanged:** after 15 idle minutes the first request waits about a minute plus the snapshot load, and the frontend shows no message and has no fetch timeout. Not changed in 7B to avoid touching the frontend source.
7. **Nothing ran on the real platforms:** the Render blueprint, the `sync: false` prompts, the secret files, the Pages workflow and cross-origin browser calls were validated structurally and against Render's and GitHub's documentation, not by running them. `autoDeployTrigger` replaces the deprecated `autoDeploy` per Render's documentation.
8. **The validator cannot see what a token can do:** it cannot tell that the R2 credentials are read-only; that stays an operator instruction.
9. **Publishing:** two operators publishing at once are not guarded (pointer is last-writer-wins); objects left by an interrupted publish are never deleted.
10. **No signed approval record or trusted keys exist** (by design), so even a fully deployed service answers every legal question with "unavailable" until a human completes legal review.
11. GitHub Pages being free only for public repositories on a free account was not re-verified in 7B.
12. `tests/test_server.py` and other working-tree changes that predate Stage 7 are not mine and were not touched.

## 12. Confirmations

- **Nothing was deployed or paid for.** No workflow ran, no Render service, R2 bucket or Pages site was created, no account was made, no billing was activated, nothing was committed.
- **No live calls:** no hosted-embedding call, no Groq call, no Gemini call. Documentation pages were read; no embedding endpoint was contacted.
- **The real index is unchanged:** tree digest before and after `140cd2008980f7e64858a8089d81f0346f758db1eda4d8c5c390418eac0ebe29` (same as Stage 6D and 7A). Snapshots were published only from temporary copies, to temporary local stores.
- **The real lifecycle registry is unchanged:** tree digest before and after `5f4094d88cf9b770b7210749fdadddfeea4d4c0cfd168c39bb3b905767bbdbe3`; `verify` reports "consistent", `audit-verify` reports "audit history intact" (run on temporary copies; `stage7b/final_*.txt`).
- **All 20 legal sources remain pending/quarantined:** 20 of 20 pending, none active (`stage7b/final_status.json`). No approval record, trusted key or signature was created.
- Retrieval ranking, fusion, thresholds, grounded-answer validation, lifecycle enforcement, the Groq → Gemini fallback and the 4F/4G masks were not changed; no administration endpoint was added; no Vercel configuration exists.

Sources read (official pages, 2026-11-13): docs.nomic.ai (text-embedding, embed API reference, rate limits, plans), nomic.ai/pricing, huggingface.co/docs/inference-providers/pricing, huggingface.co/nomic-ai/nomic-embed-text-v1.5, developers.cloudflare.com (Workers AI pricing and models, R2 pricing and limits), render.com/docs (free, blueprint-spec, configure-environment-variables, python-version).

## 13. Reproduce

```
bash eval/deployment/stage7b/run_regressions.sh          # offline + real-backend (per module), exact and hnsw, then integrity digests
python3 eval/deployment/stage7b/measure.py                # memory / startup measurements (needs local Ollama)
python3 scripts/check_cloud_env.py                        # validate a candidate cloud environment
python3 scripts/build_pages.py --api-base https://<service>.onrender.com --out build/pages --require-api-base
```
