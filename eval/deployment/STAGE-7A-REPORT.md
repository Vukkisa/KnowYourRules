# Stage 7A — Deployment architecture and embedding-provider preflight

Status: **preflight complete; not deployed.** Nothing was uploaded, published or paid for. No live Groq, Gemini or hosted-embedding call was made. Nothing was committed.

Corrected target architecture (GitHub Pages replaces Vercel):

```
GitHub repo (source)
  ├─ GitHub Pages ── static frontend (build/pages) ──HTTPS, CORS──▶ Render Free: FastAPI (backend.server:app)
  │                                                                   ├─ query embeddings ──▶ hosted embedding API (OpenAI-compatible)
  │                                                                   ├─ generation: Groq → Gemini → safe "unavailable"
  │                                                                   └─ at start: verified snapshot ◀── Cloudflare R2 (immutable snapshots + active manifest)
  └─ local development: Ollama (embeddings + optional generation fallback), unchanged
```

No Vercel configuration or dependency exists in the repository (checked by search and by a test in `tests/test_pages_build.py`).

## 1. Result in one table

| Question | Answer | Evidence |
|---|---|---|
| Hosted embeddings without changing retrieval? | Plumbing proven; **real provider numerics not yet proven** (no key, no external call) | §4, §12 |
| Real index changed? | **No** (tree digest before = after) | §14 |
| Lifecycle registry changed? | **No** | §14 |
| All 20 sources still quarantined? | **Yes** | §14 |
| Static build compatible with GitHub Pages? | **Yes** (build, scan and tests; not yet deployed) | §8 |
| Fits 512 MB? | Measured peak 242 MB (cloud requirements, macOS RSS) — fits on paper; **must be re-measured on Render (Linux, 0.1 CPU)** | §6, §11 |
| Fits ~1 GB? | Comfortably | §6, §11 |
| Zero cost? | Hosting yes (Pages, Render Free, R2 free tier); **hosted embeddings are very cheap but not free** | §11 |
| Can it answer legal questions after deploy? | **No, by design**: no approval record or trusted keys exist, so it answers "unavailable" | §12 |

## 2. Existing embedding architecture (before this stage)

- Index built with Ollama `nomic-embed-text` (GGUF F16, nomic-bert v1.5): **768 dimensions**, unit-norm vectors (±5e-7), squared-L2 space, "structured" profile. Prefixes `search_document: ` (chunks) and `search_query: ` (queries) are applied by `rag_profiles.ProfileEmbeddings`.
- Collection `telangana-traffic-rules`: 590 chunks, 20 sources, all quarantined. Real index `chroma_telangana_preview_s11` (10 MB); real lifecycle registry `legal/lifecycle` (1.5 MB).
- Before this stage `backend/server.py` created `OllamaEmbeddings(model="nomic-embed-text")` at import, so the server could not start the search path without a local Ollama.
- Every Ollama-embedding dependency in the repository:

| File | Use | Cloud impact |
|---|---|---|
| `backend/server.py` | query embeddings | **replaced** by `embedding_provider.build_embeddings` (this stage) |
| `backend/build_telangana_index.py` | builds the real index (lazy import) | operator-only, local |
| `backend/build_index.py` | legacy builder | operator-only, local |
| `backend/document_lifecycle.py` (CLI, ~L1367) | operator re-embedding for lifecycle operations (lazy import) | operator-only, local |
| `eval/rag_bench.py`, `eval/verify_pipeline.py` | evaluation scripts | local |
| tests | fakes or real local Ollama | local |

None of the operator tools run on Render. `requirements-cloud.txt` does not install `langchain-ollama`; a test imports the server with that module blocked.

## 3. Embedding provider abstraction (`backend/embedding_provider.py`)

- `EMBEDDING_PROVIDER` is `ollama` (default, unchanged behaviour) or `openai_compatible`. It is **independent of generation-provider selection**.
- **The hosted provider never falls back to Ollama**; Ollama never falls back to the cloud. A misconfigured provider yields a guard that refuses every call (`DisabledBackend`); it never builds a different provider. An unknown provider name becomes `invalid` and refuses.
- No default hosted model: `EMBEDDING_MODEL` is required (no silent substitution). Key required, `https` required (plain `http` only for loopback), no credentials or query string in the URL.
- Keys come only from the environment. The settings `repr` hides URL and key; `/status` shows the endpoint **host** only; a test greps logs, responses and subprocess output for the key.
- Every returned vector is checked: count, finite numbers, **dimension equal to the stored index**, unit length (hosted). A wrong dimension or unnormalised vector raises `EmbeddingIncompatible`, which is **permanent for the process**: a provider seen returning another kind of vector is never used again until restart (models are never mixed, even if the provider later behaves).
- Retries: hosted default 2 with exponential backoff, only for timeouts, connection errors, 5xx and 429 (a `Retry-After` longer than `EMBEDDING_MAX_RETRY_WAIT_SECONDS` is not waited for). 401/403 are permanent for a cooldown. Circuit breaker (`EMBEDDING_BREAKER_FAILURES`, cooldown) and a concurrency semaphore (`EMBEDDING_MAX_CONCURRENCY`, default 8).
- Failure behaviour: `/chat` returns **HTTP 503** with a fixed message (`EMBEDDING_ERROR`) — the question is not searched, not answered, no generation provider is called, nothing is substituted. If the guard is already known unusable, the grounded gate reports not-ready and `/chat` returns the existing "unavailable" reply.
- `cache_epoch()` now includes the embedding provider, so cached answers never cross providers.

### Environment variables (embedding)

`EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `EMBEDDING_MODEL_FAMILY`, `EMBEDDING_API_URL`, `EMBEDDING_API_KEY` (secret), `EMBEDDING_TIMEOUT_SECONDS` (hosted 10), `EMBEDDING_MAX_RETRIES` (hosted 2), `EMBEDDING_RETRY_BACKOFF_SECONDS`, `EMBEDDING_MAX_RETRY_WAIT_SECONDS`, `EMBEDDING_OLLAMA_BASE_URL`, `EMBEDDING_DIMENSIONS`, `EMBEDDING_SEND_DIMENSIONS`, `EMBEDDING_NORMALIZE`, `EMBEDDING_VERIFY` (auto|required|off), `EMBEDDING_MIN_COSINE` (0.995, floor 0.98), `EMBEDDING_BREAKER_FAILURES`, `EMBEDDING_BREAKER_COOLDOWN_SECONDS`, `EMBEDDING_MAX_CONCURRENCY`, `EMBEDDING_REVERIFY_SECONDS`. Local development needs none of them (`.env.example` documents them commented out).

## 4. Hosted integration and compatibility analysis

Selected integration: **Fireworks, OpenAI-compatible `POST /inference/v1/embeddings`, model `nomic-ai/nomic-embed-text-v1.5`** (768 dimensions, normalised, optionally resizable). Reasons: same model family as the index; the API does **not** add task prefixes, so the caller supplies `search_query: ` exactly as `ProfileEmbeddings` already does. Nomic Atlas was not chosen: its native API adds its own prefix via `task_type`, which would double-prefix queries. Pricing noted from the provider's page: about $0.008 per 1M input tokens (verify at deploy time).

Compatibility evidence measured on a temp copy of the real index:

- Re-embedding stored chunks through local Ollama with the document prefix reproduces the stored vectors (**cosine 1.0**, squared-L2 ≈ 4e-16).
- Without the prefix cosine is only **0.95–0.97**. This is why the acceptance threshold is **0.995** and why prefix handling is the main risk for any other provider.

How a hosted provider is verified against the index **without sending corpus text**:

1. At publish time the operator tool embeds three generic probe sentences with the index's own model and stores the vectors in the snapshot manifest (`embedding.probes`). It also re-embeds a sample of stored chunks locally and requires cosine ≥ 0.9999, so the probes certify the real index model.
2. At server start (and when re-verification is due) the hosted provider embeds the same probe sentences; the server compares cosines with the manifest vectors and refuses the provider below 0.995. Only these generic sentences and users' own queries are ever sent (tested: no chunk text, no `search_document:` text other than the probes).
3. Operator preflight before any deploy: `python -m backend.embedding_provider preflight --manifest <manifest.json>` with the real key, run once from a trusted machine.

**Not done:** the live hosted comparison, because no key exists and nothing may be sent externally in this stage. All hosted tests use a local fake that relays real Ollama vectors. They prove the client, verification and failure behaviour — not Fireworks' numerics.

**If a different model is ever needed** (migration plan, not performed): the index must be rebuilt from the source corpus with the new model on the operator machine (590 chunks, new dimensions possibly), published as a *new* snapshot whose manifest declares the new model and family, then `EMBEDDING_MODEL`/`TG_SNAPSHOT_EXPECT_FAMILY` switched together. The server refuses a mismatched provider/manifest pair, so a half-done migration fails closed. The existing index is never regenerated or edited by this stage.

## 5. Local vs cloud configuration

| | Local development | Cloud (Render) |
|---|---|---|
| Embeddings | Ollama `nomic-embed-text` (default) | `openai_compatible` hosted, **never Ollama** |
| Generation | Groq → Gemini → Ollama (dev fallback only) → safe unavailable | Groq → Gemini → safe unavailable (`OLLAMA_ENABLED=false`) |
| Index | `TG_DB_DIR` (directory) | verified R2 snapshot (`TG_DB_DIR` must stay unset) |
| Lifecycle registry | `TG_LIFECYCLE_DIR` | inside the same snapshot (`TG_LIFECYCLE_DIR` must stay unset) |
| Dependencies | `requirements.txt` | `requirements-cloud.txt` (no torch, transformers, langchain-ollama, boto3) |
| Frontend | served by FastAPI at `/` | GitHub Pages, API base baked in at build |
| CORS | none needed | `TG_CORS_ORIGINS` exact origin(s) |

Setting `TG_DB_DIR` or `TG_LIFECYCLE_DIR` together with snapshot mode is refused (misconfigured). An **empty** `TG_LIFECYCLE_DIR` still fails closed (Stage 6 behaviour, retested).

## 6. Measurements (`eval/deployment/stage7a/measure.py`, raw: `measurements.json`)

Machine: macOS arm64, 8 CPUs, 8 GB, Python 3.11.2, load average ≈ 3.4 at start (machine not idle: other work had just finished). RSS values are macOS resident size, which compresses memory; peak (`ru_maxrss`) is the more reliable column. **A 0.1-CPU Linux container will be slower and its RSS may differ.** The "hosted provider" is a local relay, so embedding latency below is Ollama's.

Process memory by stage (cloud requirements = transformers, torch, langchain-ollama, boto3 not importable; real index copy; exact mode):

| Stage | RSS MB | Peak MB |
|---|---|---|
| Python + psutil | 18 | 18 |
| `import chromadb` | 103 | 103 |
| + fastapi, langchain, langchain_chroma, requests | 129 | 129 |
| `import backend.server` (snapshot verify+extract, open store, exact index, BM25) | 197 | 214 |
| after 40 sequential retrievals | 202 | 232 |
| after concurrency 1/4/8/16 | 140 | **242** |

Same flow with the **full development environment** (transformers and torch installed): RSS after server import 264–278 MB, **peak 368 MB**, server import 5.1–5.9 s. The cause: `langchain.chat_models` → `langchain_core.language_models.base` does `try: from transformers import GPT2TokenizerFast`, so merely installing transformers makes the server import torch. The cloud requirements file avoids it: import time **1.6–1.9 s**, peak **242 MB** (−34 %).

Component isolation (no server; cloud requirements; real index copy):

| Component | Δ RSS (MB) | Notes |
|---|---|---|
| chromadb import | ≈ +87 | largest single item |
| langchain_chroma import | ≈ +20 | |
| open Chroma collection | ≈ +10 | HNSW loaded lazily |
| read all vectors, documents, metadata | ≈ +38 (peak +50) | 590 × 768 |
| ExactVectorIndex (float64 matrix) | ≈ +12 | matrix itself 3.5 MB; Python objects 6.6 MB |
| BM25 + provision lookup | ≈ +3 | Python objects 6.0 MB |

Chroma + its imports ≈ 155 of ≈ 190 MB. The corpus data structures (exact index + BM25) are small (< 20 MB); the **libraries**, not the data, dominate.

Startup and snapshot (local store; **not R2 bandwidth or latency**):

| Item | Value |
|---|---|
| publish (operator, includes re-embedding a sample and probes) | 6.1 s |
| snapshot size | index archive 4.1 MB (10.0 MB unpacked), registry 0.2 MB (1.5 MB unpacked) |
| download + verify / extract + verify / validate (index + lifecycle) | 0.007 s / 0.07 s / 0.25–0.30 s; total 0.33–0.38 s |
| server import incl. snapshot, cloud requirements | 1.6–1.9 s (cold run 1.85 s; no difference cold vs warm locally) |

On Render the dominant start-up costs will be pip-installed library imports on 0.1 CPU and the R2 download of ≈ 4.4 MB; neither can be measured here. Render's own cold start (≈ 1 minute after 15 minutes idle) comes on top.

Concurrency (exact mode, cloud requirements; each client issues 6 retrievals; embeddings via the relay, so Ollama serialises):

| Clients | Requests | Errors | Wall | p50 | p95 | Peak MB |
|---|---|---|---|---|---|---|
| 1 | 6 | 0 | 0.52 s | 86 ms | 97 ms | 232 |
| 4 | 24 | 0 | 0.36 s | 19 ms | 118 ms | 232 |
| 8 | 48 | 0 | 0.74 s | 35 ms | 203 ms | 232 |
| 16 | 96 | 0 | 1.58 s | 49 ms | 399 ms | 242 |

Sequential retrieval p50 61 ms, p95 82 ms. No errors and no memory growth with concurrency (the semaphore limits concurrent provider calls to 8). A real hosted provider will add network latency per query; this is unmeasured.

## 7. Persistent index architecture (`backend/index_snapshot.py`)

Store layout (R2 bucket, prefix `kyr/`):

```
kyr/active.json                          pointer: version, manifest_key, manifest sha256, previous (written LAST)
kyr/manifests/<version>.json             manifest (immutable)
kyr/snapshots/<version>/index.tar.gz     Chroma directory (immutable, deterministic tar.gz)
kyr/snapshots/<version>/lifecycle.tar.gz registry + audit chain (immutable)
```

Manifest fields: `version`, `created_at`, `created_by`, `notes`, `schema`; `index` {archive, sha256, tree_digest, size_bytes, unpacked_bytes, **chunk_count**, collection}; `lifecycle` {archive, sha256, tree_digest, sizes, registry sha256}; `embedding` {**model**, **family**, **dimensions**, min_cosine, doc/query prefix, **probes**}.

Publishing (operator, `python -m backend.index_snapshot publish`): works on a private copy of the index; refuses an empty index, a nameless operator, a registry the server would refuse (`check_lifecycle_dir`), and a model that cannot reproduce the stored vectors; objects are write-once; the pointer is written last, so a failed publish leaves the previous active version untouched. `rollback` repoints `active.json` after validating the target manifest.

Loading at start (`SnapshotManager.activate`): pointer → manifest (checksum from the pointer, optional pinned digest `TG_SNAPSHOT_PIN_SHA256`) → **stream download to a temp file with size and sha256 checked** → safe extract (regular files only; rejects absolute paths, `..`, links, devices, oversize) → tree digests → index check (chunk count, dimensions, profile, expected family) → registry check (sha256, then the Stage 6 `ServeFilter`: registry, audit chain, index/registry consistency). **The corpus is ready only if every step passes.**

Failure states reported in `/status.snapshot.state`: `misconfigured`, `manifest_missing`, `manifest_invalid`, `checksum_mismatch`, `pin_mismatch`, `snapshot_missing`, `archive_invalid`, `store_unavailable`, `index_invalid`, `embedding_incompatible`, `lifecycle_invalid`.

On failure the server **starts but is not ready**: `TG_DB_DIR`/`TG_LIFECYCLE_DIR` point at nonexistent paths under `.snapshot-unavailable`; nothing is created (tested: no directory, no empty index), the index reads "missing", the lifecycle fails closed, `/chat` serves nothing.

**No automatic fallback to the previous snapshot.** Rationale: an older snapshot carries an older lifecycle registry, so falling back could resurrect a document that was withdrawn or superseded after it. Rollback is an explicit operator act (`rollback`) and the previous version is kept in the bucket. The only automatic reuse is opt-in `TG_SNAPSHOT_ALLOW_STALE` (default off): serve the already **verified cached** copy of the same version if the store is unreachable. The local work directory keeps the active archive plus one previous.

R2 access: path-style S3 API with SigV4 implemented over `requests` (boto3 avoided to save memory); verified against the published AWS test vector and, in the real-backend test, over real HTTP against an R2-like server. Use a **read-only** token scoped to the bucket on Render; the write token stays on the operator machine.

## 8. GitHub Pages frontend (corrected architecture)

Inspected facts: the frontend has **no framework, bundler or package.json**: `frontend/index.html` (inline script) and `frontend/render.js`. Its only network calls are `fetch('/chat')` and `fetch('/status')`; CDN scripts (marked, DOMPurify) carry SRI hashes. FastAPI used to serve it at `/` and `/static`.

| Check | Result |
|---|---|
| Build command | `python3 scripts/build_pages.py --api-base https://<service>.onrender.com --out build/pages` (stdlib only, no Node) |
| Output directory | `build/pages` → `index.html`, `static/render.js`, `.nojekyll` |
| GitHub Actions | `.github/workflows/pages.yml`: **manual** (`workflow_dispatch`) only; permissions `contents: read, pages: write, id-token: write`; uses `vars.KYR_API_BASE_URL` (a repository *variable*, no secrets); runs the frontend and build tests, builds, then `configure-pages`, `upload-pages-artifact`, `deploy-pages`. Not run. |
| Repo subpath / base URL | Project Pages serve under `/<repo>/`. The built page uses only **relative** asset URLs (`static/render.js`), so it works at `https://<owner>.github.io/<repo>/` and at a custom domain root. No `<base>` tag needed. |
| API base URL | `<meta name="kyr-api-base">` is filled at build time; the inline script prefixes `/chat` and `/status` with it. Empty (local FastAPI serving) keeps the old same-origin behaviour. A meta tag was used because `tests/test_frontend.py` pins the exact `<script src>` list, so no new script could be added. |
| Client-side routing / refresh | **None exists**: single page, no history API, no deep links. Refresh and "New chat" are `location.reload()`, which reloads `index.html` and works on Pages. No 404-fallback hack is needed. |
| HTTPS | Pages serves HTTPS. The build **refuses** a non-https API base (only `http://localhost` with `--allow-local`, for testing) so mixed content cannot be shipped. |
| CORS | The backend allows only the exact origin(s) in `TG_CORS_ORIGINS` (https; `http` only for localhost; no wildcard, no path), methods GET/POST, header `Content-Type`, **no credentials**, preflight cache 600 s. The Pages *origin* is `https://<owner>.github.io` (no repo path). With the variable unset no CORS middleware is added. |
| Extra protection | The build injects a CSP meta (`base-uri 'self'; form-action 'none'; connect-src 'self' <api>; object-src 'none'`). |
| Secrets in frontend assets | The build scans the output and **fails** on key shapes, secret variable names, and the values of secret-like environment variables. The page needs no key at all: all provider keys stay on Render. |
| Vercel | No config, no dependency. |

Verified by `tests/test_pages_build.py` (10) and an actual trial build. **Not verified:** a real deploy to Pages and a real browser call to a deployed Render service (HTTPS cannot be exercised locally). One UX gap: after 15 idle minutes Render needs about a minute to wake, and the page has no cold-start message or request timeout — the first question may appear to hang (see §13).

## 9. Deployment configuration prepared (nothing applied)

- `deploy/render.yaml` — Render Blueprint: free plan, python runtime, `autoDeploy: false`, build `pip install --no-cache-dir -r requirements-cloud.txt`, start `uvicorn backend.server:app --host 0.0.0.0 --port $PORT --workers 1 --no-server-header`, `healthCheckPath: /health`. Import path `backend.server:app` verified (the app object exists at import; no startup/shutdown handlers).
- `requirements-cloud.txt` — pinned; excludes transformers, torch, langchain-ollama, boto3.
- `deploy/cloud.env.example` — placeholders only.
- `.github/workflows/pages.yml`, `scripts/build_pages.py` — §8.
- `/health` is `{"status":"ok"}` and never implies corpus readiness. `/status` has `corpus_ready` (true only if approval gate, index, lifecycle, embedding guard **and** snapshot are all ready), plus `embedding` and `snapshot` blocks.
- `/approval/refresh` returns 404 in staging/production unless `TG_ENABLE_APPROVAL_REFRESH` is set. No public lifecycle admin endpoint exists (route list asserted).
- Render's health check hits `/health`, so a snapshot failure does not cause a restart loop; `/status` tells the truth.

### Required secrets and variables

| Name | Where | Secret? |
|---|---|---|
| `GROQ_API_KEY`, `GEMINI_API_KEY` | Render | yes |
| `EMBEDDING_API_KEY` | Render | yes |
| `R2_ACCOUNT_ID`, `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` (read-only token) | Render | yes |
| `TG_SNAPSHOT_PIN_SHA256` (optional, sha256 of the reviewed manifest) | Render | yes (integrity pin) |
| `TG_CORS_ORIGINS` (`https://<owner>.github.io`) | Render | no |
| approval record `telangana-approval.json`, `trusted-keys.json` | Render Secret Files | approval record + public keys; **do not exist yet** |
| `KYR_API_BASE_URL` (Render service URL) | GitHub repository **variable** | no |
| fixed values (in `render.yaml`) | `TG_ENVIRONMENT=production`, `TG_GROUNDED_ANSWERS=1`, `OLLAMA_ENABLED=false`, `EMBEDDING_PROVIDER`, `EMBEDDING_API_URL`, `EMBEDDING_MODEL`, `TG_SNAPSHOT_STORE=r2`, `TG_SNAPSHOT_PREFIX=kyr/`, `RAG_VECTOR_SEARCH=exact` | no |
| R2 write token, operator name | operator machine only, for `publish` | yes — **never on Render** |

## 10. Legal and lifecycle safeguards (unchanged, retested)

Retrieval, ranking, fusion, thresholds, grounded-answer validation and the 4F/4G masks were not changed. In the real-backend tests with the real registry in a snapshot: **no passage is served** (quarantined corpus), `/health` stays OK while `corpus_ready` is false. With a throwaway-key 2-of-20 fixture on a copy, only the two approved documents are ever retrieved while the unfiltered control reaches quarantined ones. Registry and audit chain are verified at snapshot load (corrupt or mismatched registry → `lifecycle_invalid`, not ready). Cache hits keep revalidating eligibility (Stage 6 tests pass). No pre-answer catalogue reply was changed.

## 11. Free-tier feasibility (assessed from the measurements; limits to be verified at deploy time)

| Resource | What is known | Verify at deploy time |
|---|---|---|
| Render Free web service | docs page: 750 instance hours/month, spins down after 15 min idle, ≈ 1 min to spin up, ephemeral filesystem, no persistent disk, may restart any time, outbound ports 25/465/587 blocked, "not for production". RAM/CPU are **not on the docs page**; search results said 512 MB / 0.1 CPU | current RAM, CPU, hours, sleep behaviour, region |
| 512 MB | measured peak 242 MB (cloud requirements); 368 MB if torch/transformers are importable. Leaves ≈ 270 MB headroom on paper. macOS RSS ≠ Linux RSS; CPU at 0.1 core is unmeasured | re-measure on Render (`/proc/self/status`, first request, 8 concurrent) before trusting |
| ~1 GB | comfortable in every configuration measured | — |
| Cloudflare R2 | free tier per search results: 10 GB, 1M Class A, 10M Class B ops/month, free egress. This index ≈ 4.4 MB; one start = a handful of GET/HEAD | confirm free-tier terms and that a card is not required |
| GitHub Pages | static hosting, HTTPS, free for public repositories | private-repo Pages needs a paid plan on some tiers; Pages bandwidth/size limits |
| Hosted embeddings | Fireworks ≈ $0.008 / 1M tokens: negligible but **not free**; an account (possibly a card) is needed | pricing, free credits, rate limits, endpoint/model id, that the model returns prefix-free 768-d vectors |
| Generation | Groq and Gemini free tiers, unchanged | limits (Gemini live testing remains paused) |

Honest conclusion: hosting is free; **a zero-cost hosted embedding provider was not confirmed**. A free provider exists only if it serves nomic-embed-text-v1.5 without adding prefixes (or with a mapping that reproduces `search_query: ` vectors at cosine ≥ 0.995). The preflight command is the test for any candidate.

## 12. Tests

New (all passing): `tests/test_embedding_provider.py` (36), `tests/test_index_snapshot.py` (32), `tests/test_pages_build.py` (10), `tests/test_cloud_readiness.py` (24), real-backend `tests/test_cloud_embedding_real.py` (11).

Coverage of the brief: local Ollama config; hosted config with mocked HTTP; missing key; timeout; rate limit; invalid dimensions; unnormalised vectors; incompatible model; cloud refusing Ollama; safe embedding failure; snapshot download and checksum; missing manifest; corrupt snapshot; failed index initialisation; lifecycle verification at startup and readiness; cache and retrieval regression; credentials never in frontend assets, logs, responses or subprocess output; Pages build.

Real-backend scenarios (`test_cloud_embedding_real.py`, real index/registry **copies**, real Ollama vectors through a local fake hosted API, no generation provider):

1. Hosted retrieval equals local-Ollama retrieval for all benchmark questions (filtered and unfiltered; strict equality in exact mode, tolerance in hnsw — see below).
2. Only approved documents are served from a snapshot; the unfiltered control proves the test could fail.
3. A snapshot of the real registry serves nothing; `/health` still OK; `corpus_ready` false.
4. No corpus text is sent to the provider; only queries and the manifest's generic probes.
5. 401, 429, 500, timeout, bad JSON, empty data, wrong dimensions, unscaled vectors → safe refusal, no generator call, no source, no key anywhere.
6. Transient failures recover on the next question; incompatible vectors stay refused for the process.
7. Provider down at start → not ready → 503 → recovers without restart; the canary socket (where Ollama would be) records **zero** connections in hosted mode.
8. A provider returning another model's vectors is refused at start and stays refused after it starts behaving.
9. Corrupt archive → `checksum_mismatch`, not ready, nothing created, nothing served; missing manifest pointer → `manifest_missing`; store repaired → ready on the next start.
10. Snapshot downloaded over real HTTP from an R2-like server with SigV4 headers.
11. Manifest describes 590 chunks, 768 dimensions, family `nomic-embed-text-v1.5`.

Regression suites (`eval/deployment/stage7a/run_regressions.sh`; logs `suite_*.log`):

| Suite | Mode | Result | Log |
|---|---|---|---|
| Offline (real-backend tests skip) | exact | **1264 tests OK** (88 skipped, 1 expected failure) | `suite_offline_exact.log` |
| Offline | hnsw | **1264 tests OK** (88 skipped, 1 expected failure) | `suite_offline_hnsw.log` |
| Real backend, real index copy, local Ollama, no generation provider; one process per module (53 modules) | exact | **1283 tests, 0 failures, 0 skipped** | `real_exact/` (`summary.txt` + one log per module) |
| Real backend, same | hnsw | **1283 tests, 0 failures, 0 skipped** | `real_hnsw/` |

Hosted-vs-local retrieval parity over the 108 benchmark questions (`parity_exact.json`, `parity_hnsw.json`):

| Mode | Unfiltered identical | Mean overlap | Top result changed | Lifecycle-filtered identical |
|---|---|---|---|---|
| exact | 100% (strict equality asserted) | 1.00 | 0 | 100% |
| hnsw | 96% | 0.99 | 0 | 98.2% |

**Things to know about these runs (not hidden):**

1. **HNSW is approximate and not run-to-run deterministic.** Three HNSW runs of the parity test gave different numbers: the first failed the old strict-equality assertion, a second showed 100 % identical unfiltered results (1 of 108 differing after the lifecycle filter), and the final run (table above) 96.3 % identical with one question at overlap 0.5. The top result never changed. The HNSW assertion is therefore a tolerance (≥ 90 % identical, mean overlap ≥ 0.97, no changed top result), while exact mode asserts strict equality. This is the vector index's approximation, not a provider effect: both paths use the same stored vectors and (in this test) the same query vectors.
2. **A single-process full real-backend run is unreliable on this machine, and I did not find the root cause.** Running all modules in one process produced a hang and then errors starting at `test_serve_filter_hardening` ("Error in compaction: Error purging logs" from Chroma, then 500s in `test_server`, `test_source_status`, `test_tg_ingest`; 124 failures in one run). It reproduced with the new Stage 7A real test *excluded* and passed with it included in other runs, so the new test is not the (sole) cause. The same modules each pass alone, in halves, and in the offline suite. The laptop also slept during some long runs (wall-clock jumps of hours in the logs), which may have contributed. Stage 6D's single-process run passed (1170 tests), so this is a regression in test-process robustness that I could not attribute. Mitigations used: the real-backend suite runs one process per module under `caffeinate` (`run_real_per_module.sh`), and the new real test releases Chroma clients before deleting its temp directories. A follow-up should find whether it is the growing number of in-process Chroma indexes (the new offline modules add several) or a Chroma version issue.
3. A 15-minute pre-existing-baseline run (new modules removed) was started to settle (2) but did not complete before I stopped it; I make no claim about it.
4. All real-backend runs used Ollama for query embeddings and the deterministic stand-in answerer; no Groq or Gemini call was made.

## 13. Remaining blockers

1. **No live hosted-provider validation.** Needs a key and a one-off operator preflight (cosine ≥ 0.995 against the manifest probes). Until then the hosted path is proven only against a relay of real Ollama vectors.
2. **No approval record, trusted keys or signatures exist** (and none were created). The deployed service will answer "unavailable" for legal questions until a legitimate approval is produced in a later stage.
3. **Render RAM/CPU unverified.** Peak 242 MB measured on macOS; 0.1-CPU Linux start-up time and RSS unmeasured.
4. **Cold start ≈ 1 minute** after idle, plus snapshot download on every start (ephemeral disk). The Pages frontend has no cold-start message or fetch timeout; a short "waking up" notice is a recommended follow-up, but changing UI behaviour was out of scope here.
5. **Hosted embeddings are not free** (Fireworks). A free provider with prefix-compatible nomic vectors was not found or validated.
6. **R2 network path unmeasured** (SigV4 and the download path were exercised only against local HTTP and mocks).
7. GitHub Pages and Render deploys were not performed; the cross-origin browser call and HTTPS are untested end to end.
8. Free-tier limits quoted here come from public pages and search results and must be re-checked.

## 14. Integrity confirmations

| Item | Result |
|---|---|
| Real index `chroma_telangana_preview_s11` tree digest | `140cd2008980f7e64858a8089d81f0346f758db1eda4d8c5c390418eac0ebe29` — **identical before and after every Stage 7A run, and identical to the Stage 6D digest** (`final_integrity.txt`) |
| Real lifecycle registry `legal/lifecycle` tree digest | `5f4094d88cf9b770b7210749fdadddfeea4d4c0cfd168c39bb3b905767bbdbe3` — **unchanged** |
| `registry.json` sha256 | `219df1c7105036c1fec8c38bff378519652d80a710bebc34e8cc98e9cd29de2a` |
| `audit.jsonl` sha256 | `12f285a7fbaeb129ef3e8e742082237f93f52174e8363ce04dfcf6757a5232c7` |
| Lifecycle `verify` / `audit-verify` (on copies) | `consistent` / `audit history intact` (`final_verify.txt`, `final_audit_verify.txt`) |
| Source states (`final_status.json`) | **20 sources, all `pending` (quarantined), 0 with an active version** |
| Approval records, trusted keys, signatures for the real corpus | **none created.** The only signed approvals are throwaway-key fixtures on temporary copies, deleted after each test |
| Real index uploaded or modified | **no.** Every snapshot, publish, download and measurement used temporary copies; the R2 path was only exercised against a local HTTP server |
| Embeddings regenerated | **no** (sample re-embedding at publish time is read-only comparison) |
| Ranking, fusion, thresholds, grounded-answer validation, 4F/4G masks | not changed |
| Commits, deploys, paid services, live Groq/Gemini/hosted-embedding calls | **none** |

## 15. Files

Created: `backend/embedding_provider.py`, `backend/index_snapshot.py`, `scripts/build_pages.py`, `.github/workflows/pages.yml`, `requirements-cloud.txt`, `deploy/render.yaml`, `deploy/cloud.env.example`, five test modules plus `tests/cloud_embedding_probe.py`, and `eval/deployment/stage7a/` (measure.py, measure_child.py, measurements.json, run_regressions.sh, logs).

Modified: `backend/server.py` (embedding guard, snapshot, CORS, `/status` fields, 503 handling, approval-refresh gate), `backend/runtime_config.py` (`cors_origins`), `frontend/index.html` (API base meta tag, prefixed fetches), `.env.example`. `tests/test_server.py` and other pre-existing working-tree changes are not part of this stage. Backups of replaced originals are in `eval/legal-validation/heading-fusion-originals/`.

Reproduce: `bash eval/deployment/stage7a/run_regressions.sh`; `python3 eval/deployment/stage7a/measure.py`.
