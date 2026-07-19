# Codex-Rosetta Full Audit Ledger

Audit opened: 2026-07-10 11:28 America/Edmonton  
Audit closed: 2026-07-10 12:45 America/Edmonton  
Profile: `.agent-work/audit/PROFILE.md` (`Draft`)  
Scope: current working tree at `/Users/ibobby/Projects/codex-rosetta/codex-rosetta`

| Area | Status | Severity | Files | Notes |
| --- | --- | --- | --- | --- |
| Repository reality and change surface | Reviewed | No Action | repository-wide dirty diff | Final status and diff inspected; no staged changes |
| Inbound HTTP request envelope | Reviewed, repaired | No Action | `_vendor/httpserver.py`, upstream `httpserver/**` | F-01 resolved with count, byte, and monotonic deadline limits |
| Upstream HTTP response envelope | Reviewed, repaired | No Action | `_vendor/httpclient.py`, `gateway/transport/http/transport.py`, upstream `httpclient/**` | F-02 resolved across sync/async response sections and gateway mapping |
| Provider metadata state | Reviewed, repaired | No Action | `gateway/proxy.py`, `gateway/app.py` | F-03 resolved with atomic hierarchical byte budgets and stable 413 |
| Public health error window | Reviewed, repaired | No Action | `observability/metrics.py`, `gateway/health.py` | F-04 resolved with an independent compact 3,600-second error window |
| URL-image worker lifecycle | Reviewed, repaired | No Action | `gateway/image_workers.py`, `google_genai/image_fetch.py` | F-05 resolved with fixed bounded daemon workers and non-blocking close |
| Auth, CORS, Admin, config activation | Reviewed | No Action | `gateway/auth.py`, `gateway/cors.py`, `gateway/admin/routes/**`, `gateway/config.py` | Existing negative tests and accepted semantics remain intact |
| Streaming, tool adaptation, deferred tools | Reviewed | No Action | `gateway/app.py`, `gateway/proxy.py`, `gateway/tool_adaptation.py`, `gateway/stream_*` | Terminal lifecycle and byte budgets reviewed |
| Observability persistence and crypto | Reviewed | No Action | `observability/**` | Retention, token redaction, and mapping recovery reviewed |
| Converter and Codex compatibility | Reviewed | No Action | converters and `docs/dev/version-compatibility/**` | Static source contract passes; live matrix remains an explicit release prerequisite |
| Release, CI, Docker, vendoring | Reviewed | Track as Debt | CI, Makefile, Docker, `_vendor` | Wheel and Compose smoke pass; external release provenance remains manual |
| Independent verification and simplification | Reviewed | No Action | tests and whole diff | Lint, full tests, focused regressions, packaging, Docker, and CodeGraph are green |

## 1. Repository reality and audit framing

- **Repository state:** `master` at `eb947426572ad7658c4b5ad19688fa68659a06b6`; `origin/master` is `d3e899aea478002d965b0a591fbedf803f80ddb1`. Final `git status --porcelain=v1` contains 127 entries. The tracked diff contains 97 files, 8,010 insertions, and 1,568 deletions. There is no staged diff.
- **Scope:** Current tracked and untracked gateway, observability, converter, HTTP vendor, CI, Docker, release, documentation, and test changes. The audit followed the Draft profile's Codex-facing priorities and extended into changed generic HTTP/security boundaries.
- **Quality priorities:** Correctness, availability/security, compatibility reliability, operability, and maintainability, followed by performance/cost and supply-chain provenance.
- **Preserved user work:** The pre-existing large dirty working tree was not reset, reverted, staged, committed, pushed, released, or deployed.
- **Accepted semantics:** The public-health token-only policy remains accepted and was not reopened. Public provider names, prompt/PII, ordinary password/secret/client-secret/proxy-password values, and error bodies remain accepted residual content; configured token/API-key/Bearer/Authorization values are redacted.

## 2. Resolved finding F-01: inbound HTTP header sections lacked an aggregate safety envelope

- **Resolution:** Upstream `httpserver` was advanced from `0.2.1` to `0.2.2`, then re-vendored with the official local zerodep flow. `_read_header_section()` now enforces 100 fields, 64 KiB including framing/final delimiter, and one 10-second monotonic deadline that individual reads cannot renew.
- **Coverage:** The bounded parser is used for inbound request headers and chunked trailers. Oversized sections produce stable 431 responses; deadline expiry follows the existing timeout handling and closes the connection.
- **Evidence:** `src/codex_rosetta/_vendor/httpserver.py` is byte-identical to normalized upstream output. Seven targeted inbound tests passed, and `httpserver/test_httpserver_correctness.py` passed 65 tests.
- **Status:** **Resolved.** The former unauthenticated pre-auth memory/task exhaustion path now has deterministic count, byte, and time ceilings.

## 3. Resolved finding F-02: upstream response headers bypassed the body/SSE envelope

- **Resolution:** Upstream `httpclient` was advanced from `0.4.5` to `0.4.6`, then re-vendored. Both synchronous and asynchronous response-section readers enforce 100 fields, 64 KiB, and a 10-second monotonic deadline.
- **Coverage:** The same envelope applies to final response headers, interim `100 Continue`, redirect responses, proxy `CONNECT`, and trailers. The gateway maps `HttpResponseLimitError` to a stable `UpstreamSafetyError` without reflecting hostile header content.
- **Evidence:** `src/codex_rosetta/_vendor/httpclient.py` is byte-identical to normalized upstream output. The outbound header set passed 13 tests; the complete httpclient correctness suite passed 165 tests before two additional CONNECT regressions were added, and both new CONNECT tests passed separately. Main-repository HTTP transport coverage passed 23 tests.
- **Status:** **Resolved.** The body/SSE envelope no longer has an unbounded response-header predecessor.

## 4. Resolved finding F-03: provider metadata state was count-bounded but byte-unbounded

- **Resolution:** `ProviderMetadataStore` now canonicalizes metadata to stable UTF-8 JSON bytes and applies default budgets of 1 MiB per entry, 8 MiB per scope, 16 MiB per principal, 64 MiB per application, plus the existing 10,000-entry cap.
- **Atomicity and fairness:** Batch/replacement accounting is computed before mutation. Capacity failure retains old state. Count-based eviction is limited to the same principal, so one principal cannot evict another principal's continuity state. Expiry and replacement update all counters under one shared `RLock`.
- **Error contract:** `ProviderMetadataCapacityError` maps to a stable gateway 413 response.
- **Evidence:** Metadata/state regressions passed 29 tests, covering canonical Unicode size, exact boundaries, atomic replacement/batches, TTL accounting, same-principal eviction, cross-principal isolation, concurrency, stream/non-stream caching, and gateway mapping.
- **Status:** **Resolved.** Retained cross-request metadata now has deterministic hierarchical memory ownership.

## 5. Resolved finding F-04: `errors_last_hour` retained only five minutes

- **Resolution:** Metrics now own a separate `_ErrorCountWindow` with a 3,600-second monotonic horizon. It stores only seconds that contain errors and keeps a running total; the original five-minute latency/request series is unchanged.
- **Evidence:** Metrics/health regressions passed 30 tests, including 300/301/3,599/3,600-second behavior and provider/error filtering.
- **Status:** **Resolved.** The public field name now matches the actual retained interval without allocating a dense 3,600-point series.

## 6. Resolved finding F-05: image worker close could keep the interpreter alive

- **Resolution:** The app-owned image worker pool no longer uses `ThreadPoolExecutor`. It starts a fixed number of daemon `threading.Thread` workers and a queue bounded to the worker count. Capacity remains held until a worker actually finishes.
- **Close behavior:** `close()` marks the owner closed, cancels active tokens, wakes semaphore waiters, drains/cancels queued work, enqueues one sentinel per daemon worker, and never joins a stuck worker.
- **Evidence:** Worker/subprocess coverage passed seven tests. A subprocess regression starts a 30-second stuck worker, times out the request, closes the pool, and proves the interpreter exits within a two-second test timeout.
- **Status:** **Resolved.** Stuck blocking work can no longer hold process exit, while queued and waiting work is deterministically cancelled.

## 7. Upstream/vendor integrity

- Upstream workspace: `.agent-work/upstream/zerodep`, retained as a dirty local patch; no upstream commit or push was performed.
- Version/manifest/diff checks passed. Upstream lint passed.
- Official `zerodep.py --local add ...` re-vendored `httpclient`, `httpserver`, and the manifest-selected `sse` dependency; all three vendored files match normalized upstream output.
- `conda run -n llm-rosetta make dep-check` passed with `all modules up-to-date, nothing to check` after the required module version bumps.
- The full `httpserver` directory command is intentionally not repeated: its prior failures were environmental benchmark ephemeral-port exhaustion and an overlong nested Unix socket path, not correctness-test failures. The correctness file itself passed 65 tests.

## 8. Independent verification

- `conda run -n llm-rosetta make lint`: passed; Ruff check, Ruff format check, and `ty check` are green.
- `conda run -n llm-rosetta make test`: passed; **2,694 passed, 4 skipped, 9 warnings**.
- Cross-module regression set for all five repairs: **117 passed**.
- Focused main-repository sets: metadata/state **29 passed**; metrics/health **30 passed**; worker/subprocess **7 passed**; HTTP transport **23 passed**.
- `conda run -n llm-rosetta make check-codex-compat`: passed against source commit `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`; Changed: None, with 12 contract groups still classified as Possibly unchanged.
- `conda run -n llm-rosetta make check-release-version RELEASE_TAG=v0.144.0.r0`: passed.
- `git diff --check`: passed.
- Python wheel smoke: one current-checkout `0.144.0.r0` wheel installed into clean Python **3.10.20** and **3.13.2** venvs. Core import, Google converter import, gateway import, and `codex-rosetta-gateway --version` passed on both runtimes.
- Compose smoke: the versioned Compose configuration validated; its build installed the current local wheel and produced `codex-rosetta-gateway-local:0.144.0.r0`. Because user port 8765 was already occupied, an isolated equivalent runtime used port 18765. `/health` returned status `ok`, container version was `0.144.0.r0`, and the test container/network were removed.
- `codegraph sync`: passed; 14 changed files and 872 nodes were synchronized.

## 9. Remaining limitations and human review

- Not run: `tests/integration/**`, live provider/API/agentabi/Codex matrix, browser Admin UI smoke, load/capacity tests, external GitHub Actions, dependency vulnerability/license scanning, backup/restore drill, or real release/deploy/rollback.
- The compatibility report remains Pending/not approved until checklist-triggered real Codex/API tests pass. Static contract success is not equivalent to live compatibility acceptance.
- The Draft audit profile still lacks an owner, legal/privacy constraints, ASVS target, SLO/error budget, incident-response baseline, provenance/signing policy, and SBOM/dependency-governance policy.
- Manual release provenance and multi-replica continuity remain accepted debt. No production action was authorized or attempted.

## 10. Simplification and maintainability conclusion

- F-01/F-02 were fixed in their upstream parser owners and re-vendored, avoiding a second gateway parser.
- F-03 extends the existing metadata store rather than creating a parallel state service.
- F-04 adds a compact error-only aggregate without changing the established five-minute metrics series.
- F-05 replaces executor lifecycle ambiguity with one explicit, fixed, bounded owner; it does not add replacement-thread growth or blocking joins.
- No open Must Fix or Should Plan finding remains from this round. `CURRENT.md` is absent because the audit is complete.
