# OCI A1 deployment readiness audit

**Date: 2026-11-14.** Audit and report only. Branch `feature/telangana-assistant` in `KnowYourRules-tg`.
Nothing was deployed, no account or cloud resource was created, nothing was installed, committed or pushed, no provider was called, and the index, lifecycle registry, approval records and trusted keys were not touched (before/after tree hash of `chroma_telangana_preview*`, `legal/`, `legal-status/` identical: `e6cb24e10e2e52de`).
One test-only edit was made (section 7).

> **B1 resolved (2026-11-14, latest).** `scripts/check_cloud_env.py` now accepts `TG_SNAPSHOT_STORE=local` on a persistent mounted volume and still accepts R2. It requires `TG_CLOUD=1`, `TG_SNAPSHOT_MOUNT_POINT` (must be a real mount point), `TG_SNAPSHOT_LOCAL_DIR` (inside it, existing, writable, at least `TG_SNAPSHOT_MIN_FREE_MB` free, default 1024) and an explicit `TG_SNAPSHOT_WORK_DIR`, and it never creates a directory or falls back to a temporary path. Tests: `tests/test_local_snapshot_store.py`. The env block and unit in section 10 below are updated to match. The statements "Not changed" and "rejects local" in sections 2 and 3 describe the state before this change.
>
> **Decision (2026-11-14, later still).** The owner designated `chroma_telangana_preview_s11` as the OCI pilot index, with conditions. See `OCI-PRODUCTION-INDEX-AUDIT.md`, "Decision" and section 12 (verification results). B7 below is resolved by that decision.
>
> **Correction (2026-11-14, later).** Section 4 and blocker B7 below are superseded by `OCI-PRODUCTION-INDEX-AUDIT.md`. The dry-run snapshot used `chroma_telangana_preview` (586 chunks), which does **not** match the registry. The registry is bound to `chroma_telangana_preview_s11` (590 chunks); `document_lifecycle verify` reports the preview pairing as inconsistent and the s11 pairing as consistent. The snapshot `verify` result quoted below does not prove a correct pairing.

Labels: **VERIFIED** = run or read in this audit. **PRIOR** = established by an earlier report in `eval/deployment/` and not re-run. **ASSUMPTION** = not checked; verify on the VM.

## 1. Verdict

**Not ready to deploy today, for reasons that are not capacity.** Two things must change first: the start gate (`scripts/check_cloud_env.py`) rejects the local snapshot store an OCI VM would use, and there is no signed approval record, so a healthy deployment answers "unavailable" to every legal question. There is also no Dockerfile, systemd unit or Caddy config in the repository. Memory, storage and ARM64 are not obstacles.

## 2. Readiness checklist

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | ARM64 wheels for the runtime | OK | PRIOR: 103 packages resolve to aarch64 wheels for Python 3.11.9 (`stage7c/runtime/wheels_resolved.json`). Exact engine ran on aarch64 Linux in Docker (Stage 7B.2). |
| 1b | Docker configuration | **None exists** | VERIFIED: no Dockerfile, compose, Caddyfile or systemd unit in the repo. `render.yaml` is the only deployment file. Plan is systemd, no Docker (OCI-FEASIBILITY). |
| 2 | Model loading | OK | VERIFIED (code): `inprocess_nomic` memory-maps the 262 MB F16 GGUF, loads once, pins SHA-256 (`970aa74c...`), refuses any other file. Local blob exists, 274,290,656 bytes. |
| 2b | Memory and startup | OK | PRIOR: RSS 0.49-0.52 GB, cgroup peak 323 MB, 8 s import, 5 s first retrieval (Apple-silicon Docker, 2 CPUs). Not measured on Ampere. |
| 3 | Persistent Chroma storage | **Blocked by validator** | See B1. |
| 4 | Env vars, provider fallback | Partly | See section 5. |
| 5 | Uvicorn, proxy headers | **Needs flags** | See B4. |
| 6 | Proxy body limit, timeouts | **Not configured anywhere** | See B5. |
| 7 | HTTPS and domain | **Not started** | Needs a DuckDNS account (yours) and Caddy. PRIOR design only. |
| 8 | Health, shutdown, restart | Partly | See section 6. |
| 9 | Rate and session limits | OK | VERIFIED: defaults 10/min per client, 8,192-byte body, 2 concurrent questions, 500 sessions, 1,800 s idle; 1,697 tests pass. |
| 10 | Paid dependency | None found | See section 9. |

## 3. Blockers

| ID | Blocker | Kind |
|---|---|---|
| B0 | No A1 instance (Hyderabad AD-1 out of capacity) | External. Not attempted. |
| B1 | `check_cloud_env.py` requires `TG_SNAPSHOT_STORE=r2` and rejects `local`. VERIFIED by running it with a local-store environment: `ERROR TG_SNAPSHOT_STORE: must be r2`. The server itself supports `local` (`index_snapshot.store_from_env`). Options: (a) a reviewed change letting the validator accept `local` on a persistent disk, keeping the pin and integrity checks; (b) use R2, which needs a Cloudflare account whose zero-cost status and card requirement are NOT VERIFIED. I recommend (a). **Not changed.** | Code, needs your approval |
| B2 | No signed approval record or trusted keys exist (`docs/approval-trust-model.md`: "No real approval record, signature or key exists"). VERIFIED: `grounded_gate_errors()` blocks grounded answers unless a valid approval is present and `TG_KB_APPROVED` is set by it. A live pilot would show refusals only. The legal safeguards must not be loosened to change this. | Legal, yours |
| B3 | No snapshot is published, so no pin exists. A dry run works (section 4), but the real pin must be one you reviewed. | Operator |
| B4 | uvicorn defaults are `proxy_headers=True` and trusts `127.0.0.1`. VERIFIED in the installed uvicorn 0.46 `Config`. Behind Caddy on the same host it would rewrite the client address from `X-Forwarded-For` and conflict with `TG_TRUSTED_PROXIES`. Start with `--no-proxy-headers`. The `render.yaml` command does not have this flag. | Config |
| B5 | No reverse-proxy config exists. The app has no body-read timeout (PRIOR), so slow-body clients hold a connection until Caddy cuts them off. | Config |
| B6 | Domain and HTTPS: GitHub Pages is HTTPS, so the API needs a trusted certificate. DuckDNS needs your sign-in. Public IP persistence on OCI is NOT VERIFIED. | Yours |
| B7 | Which index is the production index is unresolved. The registry is bound to tree hash `140cd200...`. The dry run used `chroma_telangana_preview` (586 chunks, lifecycle validated). `chroma_telangana_preview_s11` is newer, and Stage 28 reports 590 chunks. Publish only the one the registry matches. | Operator |

## 4. What I verified by running

- **Snapshot path, offline, local store, scratchpad only.** `index_snapshot publish` of `chroma_telangana_preview` plus `legal/lifecycle`, then `verify`: state `ready`, 0 problems, 586 chunks, verify 3.5 s total on this Mac. Store size 8.0 MB. Pin printed. The scratchpad copy is not in the repository.
- **Environment gate.** `check_cloud_env.py` with an OCI-style local-store environment fails on `TG_SNAPSHOT_STORE`. With an r2-style environment its only error is the missing model file. It prints names only, never values.
- **Tests, keys scrubbed from the environment:** 1,697 tests, OK, 104 skipped, 1 expected failure, about 96 s. The skips are the real-index, real-model and live-provider tests, which need credentials or files this audit did not use. No provider was called.
- **Model weights** present locally; the Ollama blob name equals the pinned SHA-256.

## 5. Environment and provider fallback

- **Order:** Groq (`openai/gpt-oss-120b`) then Gemini (`gemini-2.5-flash`), then a fixed "unavailable" reply. VERIFIED (code, `providers.py`): bounded retries, never loops, Ollama can be disabled and the gate requires `OLLAMA_ENABLED=false`.
- **Fail-closed gate** refuses to start on forbidden variables (`TG_KB_APPROVED`, `TG_PENALTY_ANSWERS`, `TG_LEGACY_DEV_ANSWERS`, `TG_SNAPSHOT_ALLOW_STALE`, `TG_ENABLE_APPROVAL_REFRESH`, and others) and on `EMBEDDING_MIN_COSINE` below 0.995.
- **No overall deadline.** Defaults: 30 s per call, 1 retry, up to 5 s wait. Worst case with both providers failing slowly: about 2 x (30 + 5 + 30) = 130 s, plus 4-7 s retrieval. The page's default wait is 30 s, so the page can give up while the server still holds one of two question slots. Proposal (ASSUMPTION, untested): `PROVIDER_TIMEOUT_SECONDS=12`, `PROVIDER_MAX_RETRIES=0` gives a worst case near 30 s.
- Free-tier limits for Groq, Gemini and the account terms were not re-checked (PRIOR).
- **Exposure:** FastAPI's `/docs` and `/openapi.json` are on by default (no `docs_url=None`). Proxy only `/chat`, `/status`, `/ready`, `/health`.

## 6. Health, shutdown, restart

- `/health` is liveness only. `/ready` is 200 only when snapshot, pin, index chunk count, lifecycle registry and audit chain, source-status registry, embedding and CORS all pass; otherwise 503. VERIFIED (code).
- **Shutdown:** no lifespan hook. uvicorn handles SIGTERM; `--timeout-graceful-shutdown 20` ends open requests after 20 s. Chat handlers are synchronous, run in the thread pool.
- **Restart:** sessions, rate-limit counters and penalty locks are in memory and are lost. The snapshot is re-verified on each start (0.1 s extract, 3.4 s validate here).
- **Hang detection does not exist.** `Restart=on-failure` covers crashes only. A cron check of `/ready` is proposed below (ASSUMPTION).

## 7. Test change

`tests/test_session_lifecycle.py`: `test_concurrent_new_sessions_through_the_real_app_never_exceed_the_limit` (my Stage 2 test) failed 6 of 6 runs in this audit, with 4 successes instead of 5. Cause: 12 simultaneous requests also raced the 2-question concurrency limit, so a request that held a session could get a busy 503. It passed in Stage 2 only because of timing. Fix: the test now sets `TG_MAX_CONCURRENT_QUESTIONS=32`, isolating the session limit. 8 of 8 isolated runs and the full suite pass. The product code was not wrong.

## 8. Memory, storage and consumption

| Resource | Figure | Basis |
|---|---|---|
| RAM, steady | about 0.5 GB of 12 GB | PRIOR, Docker aarch64 |
| RAM, cgroup peak | 323 MB | PRIOR |
| Model weights on disk | 262 MiB | VERIFIED |
| Snapshot, one version | 8.0 MB packed | VERIFIED |
| Python environment | not measured | ASSUMPTION: under 2 GB |
| Boot volume | 50 GB (counts against the 200 GB) | PRIOR |
| Retrieval cost | about 6-7 CPU-s each; 3.65 s p50 at 2 CPUs; 4 concurrent p50 11.2 s | PRIOR, not measured on Ampere |
| Throughput ceiling | about 0.3 questions/s (about 18/min) for the whole VM | derived: 2 CPUs / 6.5 CPU-s |
| Egress | negligible against 10 TB/month | PRIOR |

Monthly compute stays within the 1,500 OCPU-hour and 9,000 GB-hour allowance only at 2 OCPU / 12 GB or less (PRIOR).

## 9. Risks to zero-cost operation

- **Upgrading to Pay As You Go** ends the guarantee. Never do it. Exceeding 2 OCPU / 12 GB risks A1 being disabled and deleted 30 days after the trial ends (PRIOR).
- **Idle reclamation:** this service uses under 20% CPU, network and memory almost all the time, so it would count as idle. The action Oracle takes is NOT STATED. Padding load is not recommended. Keep a backup of the snapshot and model off the VM.
- **R2** (if chosen): free-tier terms and card requirement not verified.
- **DuckDNS** may suspend a subdomain without notice. Certificate lifetime drops to 64 days on 2027-02-10.
- **Provider free tiers** can change or throttle. The fallback is a refusal, not a charge. Free-tier terms were not re-checked.
- **Block volume** beyond the free 200 GB, or more than 5 backups, would cost money. Nothing here needs either.
- **Capacity and Neoverse speed** are unknown until an instance exists.

## 10. Setup on the OCI VM (do not run yet)

**Files, all in the repository and none installed by anything:**

| File | Installed at |
|---|---|
| `deploy/oci/kyr.service` | `/etc/systemd/system/kyr.service` |
| `deploy/oci/Caddyfile` | `/etc/caddy/Caddyfile` |
| `deploy/oci/kyr.env.example` | `/etc/kyr/kyr.env` (copy, fill in, owner root, mode 0600) |

Prerequisites: an A1 VM exists; the persistent block volume is attached; a hostname you own (for example a DuckDNS name) resolves to the VM; the OCI security list and the VM firewall allow inbound 22, 80 and 443 only (never 8000); the snapshot has been published and its pin reviewed. Commands assume Oracle Linux 9 (ASSUMPTION: confirm `python3.11` and Caddy packages exist; neither was checked).

**1. Volume.** Format it once, then mount it at `/srv/kyr` through `/etc/fstab` so systemd has a mount unit to depend on. `nofail` lets the VM boot without the volume, and the service then refuses to start:
```bash
sudo mkfs.ext4 -L kyr-data /dev/oracleoci/oraclevdb          # first time only; device name is an assumption
sudo mkdir -p /srv/kyr
echo 'LABEL=kyr-data /srv/kyr ext4 defaults,_netdev,nofail 0 2' | sudo tee -a /etc/fstab
sudo systemctl daemon-reload && sudo mount /srv/kyr
mountpoint /srv/kyr                                          # must print "is a mountpoint"
```

**2. User, directories, code, virtualenv.**
```bash
sudo useradd --system --home-dir /opt/kyr --shell /usr/sbin/nologin kyr
sudo mkdir -p /opt/kyr/app /srv/kyr/snapshots /srv/kyr/work /srv/kyr/model
sudo chown -R kyr:kyr /srv/kyr                               # the volume is the service's; the code stays root-owned
# copy the files listed in deploy/deployment-manifest.json into /opt/kyr/app  (root-owned, world-readable)
sudo python3.11 -m venv /opt/kyr/venv
sudo /opt/kyr/venv/bin/pip install --no-cache-dir -r /opt/kyr/app/requirements-cloud.txt
```
Copy the model file to `/srv/kyr/model/nomic-embed-text-v1.5.f16.gguf` and check `sha256sum` prints `970aa74c0a90ef7482477cf803618e776e173c007bf957f635f1015bfcfef0e6`. Copy the published snapshot (the `kyr/` tree) into `/srv/kyr/snapshots/`.

**3. Environment file.**
```bash
sudo mkdir -p /etc/kyr && sudo cp /opt/kyr/app/deploy/oci/kyr.env.example /etc/kyr/kyr.env
sudo chown root:root /etc/kyr/kyr.env && sudo chmod 0600 /etc/kyr/kyr.env
sudoedit /etc/kyr/kyr.env      # keys, the reviewed pin, your Pages origin
```

| Variable | Value | Why |
|---|---|---|
| `TG_ENVIRONMENT`, `TG_GROUNDED_ANSWERS`, `OLLAMA_ENABLED` | `production`, `1`, `false` | Grounded, approval-gated answers only; no Ollama |
| `TG_CLOUD` | `1` | Keeps the cloud safeguards with a local store (required by the validator) |
| `TG_SNAPSHOT_STORE`, `TG_SNAPSHOT_MOUNT_POINT`, `TG_SNAPSHOT_LOCAL_DIR`, `TG_SNAPSHOT_WORK_DIR`, `TG_SNAPSHOT_MIN_FREE_MB` | `local`, `/srv/kyr`, `/srv/kyr/snapshots`, `/srv/kyr/work`, `1024` | Persistent snapshot; the validator refuses an unmounted or temporary path |
| `TG_SNAPSHOT_PIN_SHA256`, `TG_SNAPSHOT_EXPECT_FAMILY` | your reviewed pin, `nomic-embed-text-v1.5` | Integrity pin; embedding family |
| `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL_FILE`, `EMBEDDING_MODEL_SHA256` | `inprocess_nomic`, the file above, the SHA-256 above | The index's own model, in process |
| `GROQ_API_KEY`, `GEMINI_API_KEY` | yours | Groq, then Gemini, then "unavailable" |
| `PROVIDER_TIMEOUT_SECONDS`, `PROVIDER_MAX_RETRIES` | `12`, `0` | Worst case about 31 s, inside the proxy's 60 s |
| `TG_TRUSTED_PROXIES` | `127.0.0.1,::1` | Only the local Caddy may supply a client address |
| `TG_CORS_ORIGINS` | `https://<owner>.github.io` | Exact origin of the Pages site |
| `TG_APPROVAL_FILE`, `TG_TRUSTED_KEYS_FILE` | unset until a signed record exists | Without them legal questions answer "unavailable" |

No rate-limit, size, concurrency or session variable is set: the defaults (10 per minute per client, 8,192 bytes, 2 concurrent, 500 sessions, 30 minutes idle) stay in force.

**4. Validate, then start the API.**
```bash
sudo bash -c 'set -a; . /etc/kyr/kyr.env; set +a; runuser -u kyr --preserve-environment -- /opt/kyr/venv/bin/python /opt/kyr/app/scripts/check_cloud_env.py'   # as the service user, so the write probe is meaningful
sudo cp /opt/kyr/app/deploy/oci/kyr.service /etc/systemd/system/kyr.service
sudo systemd-analyze verify /etc/systemd/system/kyr.service
sudo systemctl daemon-reload && sudo systemctl enable --now kyr
curl -fsS http://127.0.0.1:8000/ready            # 200 with every check "ok"; "answering": false until an approval exists
sudo ss -ltnp | grep 8000                         # must show 127.0.0.1:8000 only
```

**5. Caddy and HTTPS.** Install Caddy from its official package (ASSUMPTION: availability on Oracle Linux 9), then:
```bash
sudo mkdir -p /etc/caddy /etc/systemd/system/caddy.service.d
echo 'KYR_DOMAIN=<your-hostname>' | sudo tee /etc/caddy/caddy.env && sudo chmod 0644 /etc/caddy/caddy.env
printf '[Service]\nEnvironmentFile=/etc/caddy/caddy.env\n' | sudo tee /etc/systemd/system/caddy.service.d/kyr.conf
sudo cp /opt/kyr/app/deploy/oci/Caddyfile /etc/caddy/Caddyfile
KYR_DOMAIN=<your-hostname> caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl daemon-reload && sudo systemctl enable --now caddy
curl -fsS https://<your-hostname>/health          # {"status":"ok"} over a Let's Encrypt certificate
curl -s -o /dev/null -w '%{http_code}\n' https://<your-hostname>/ready     # 404: not exposed
```
Caddy keeps its certificates in its data directory (normally `/var/lib/caddy`). Losing it forces a new certificate; keep it on a volume that survives.

**6. Frontend.** On the operator machine: `python3 scripts/build_pages.py --api-base https://<your-hostname> --out build/pages`. The hostname goes into the page and its Content-Security-Policy.

**7. Optional hang watchdog** (ASSUMPTION; `Restart=on-failure` only covers crashes): a root cron entry `*/2 * * * * curl -fsS -m 5 http://127.0.0.1:8000/ready >/dev/null || systemctl restart kyr`.

## 10a. What was tested here and what still needs the VM

**Tested (offline, `tests/test_oci_deploy_config.py`, 29 tests, 2 skipped; all passing):**
- The unit parses; ExecStart is parsed by uvicorn's own CLI: host `127.0.0.1`, port 8000, one worker, `--no-proxy-headers`, no reload, 20 s graceful shutdown.
- A real uvicorn started with the unit's flags listens on loopback only (a non-loopback address of this machine refuses the connection) and, with `--no-proxy-headers`, keeps the real peer address and ignores a spoofed `X-Forwarded-For`. Without the flag, uvicorn does trust it (the control).
- The unit requires `/srv/kyr` three ways (`RequiresMountsFor`, `AssertPathIsMountPoint`, and the validator in `ExecStartPre`), runs as the non-root `kyr` user, restarts only on failure, reads a mandatory environment file outside the repository, and sets no capability.
- Caddy file structure (a small parser): one site, a placeholder hostname with no default, one upstream `127.0.0.1:8000` matching the unit's port, only `/chat`, `/status` and `/health` proxied (all exist in the application), a 404 for everything else, 16 KB body cap (above the application's 8,192), 10 s header and 15 s body read timeouts, `X-Forwarded-For` replaced with the single peer address, no trusted proxies, no custom TLS.
- The response timeouts exceed the worst-case answer time computed from the documented provider settings.
- The environment example passes `check_cloud_env.py` once its placeholders are filled in, and is refused when the volume is not a mount. It sets no limit, approval or weakening variable, uses the exact Nomic file hash, and contains only placeholders; no secret shape appears in any of the three files.
- No load balancer, tunnel, external proxy or other paid or third-party service is referenced.
- Mutation check: weakening each of ten settings (host `0.0.0.0`, flag removed, mount dependency removed, two workers, root user, smaller body cap, long read timeout, forwarded header copied from the client, public upstream, `/ready` exposed) makes the tests fail.

**Not verified; needs a real OCI VM (skipped here because neither program exists on this Mac):**
- `systemd-analyze verify` on the unit. The tests skip if it is absent and pass through if it exists.
- `caddy validate` on the Caddyfile. Directive names (`servers { timeouts { read_header read_body write idle } }`, `request_body { max_size }`, `header_up`, `transport http { dial_timeout response_header_timeout }`) are from memory of Caddy 2 and are unchecked against the installed version.
- That the hardening settings do not break Python, numpy or Chroma on the VM (`ProtectSystem=full`, `PrivateTmp`, `PrivateDevices`, `RestrictAddressFamilies`, `MemoryMax=4G`). `MemoryDenyWriteExecute` and `SystemCallFilter` are deliberately not set.
- That `RequiresMountsFor` finds a mount unit: it needs the `/etc/fstab` entry in step 1.
- That Caddy returns 413 for an oversized body and closes slow connections as configured; that Let's Encrypt issues the certificate (port 80 reachable, hostname resolving); renewal; the public IP surviving a stop and start.
- Oracle Linux package names, the block device name, and the real speed on Ampere.
- That a proxied request reaches the application with the single forwarded address and the rate limiter then sees the real client.

## 11. Limitations of this audit

- Nothing ran on OCI hardware, under real uvicorn, or behind Caddy. Caddy syntax and the Oracle Linux package names are unchecked.
- Memory and latency figures are from earlier reports on a different CPU.
- The 104 skipped tests were not run.
- The audit used `chroma_telangana_preview` for the dry run only; it does not decide which index is production.
