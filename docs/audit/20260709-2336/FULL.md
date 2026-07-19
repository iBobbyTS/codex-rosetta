# Codex-Rosetta Audit Ledger

Audit started: 2026-07-09 23:36 America/Edmonton  
Repair completed: 2026-07-10 America/Edmonton  
Profile: `.agent-work/audit/PROFILE.md` (`Draft`)

| Area | Status | Severity | Files | Notes |
| --- | --- | --- | --- | --- |
| Repository state and change surface | Reviewed | Should Plan | working tree, `eb94742` | Large dirty snapshot; no staged changes and no clean reproducible revision |
| Gateway authentication, CORS, and Admin authorization | Reviewed | No Action | `gateway/auth.py`, `gateway/app.py`, `gateway/health.py`, `gateway/admin/routes/auth.py` | Finding A resolved: public health errors are token-redacted at ingestion and presentation |
| Config persistence and runtime activation | Reviewed | No Action | `gateway/config.py`, `gateway/admin/routes/_shared.py`, config/key routes | CAS, private modes, rollback, validation, and app-owned activation are covered |
| Cross-request state and tool mapping persistence | Reviewed | Track as Debt | `gateway/state_scope.py`, `gateway/proxy.py`, `gateway/tool_adaptation.py`, `observability/persistence.py` | Finding B resolved; single-process metadata/deferred-tool continuity remains accepted debt |
| Responses conversion, tools, and streaming | Reviewed | No Action | `converters/openai_responses/*`, `gateway/proxy.py`, stream helpers | Automated regressions pass; required live compatibility matrix remains incomplete |
| Observability, redaction, and retention | Reviewed | Track as Debt | `observability/*`, `gateway/health.py`, `gateway/stream_trace.py` | Health and tool mappings are token-safe; count-only error retention remains accepted debt |
| Release, CI, Docker, and compatibility ledger | Reviewed | Needs Follow-up | `.github/workflows/*`, `Makefile`, `docker/*`, scripts/docs | Local gates pass; manual release and live compatibility evidence require human review |
| Tests and independent verification | Reviewed | No Action | `tests/**`, lint/test/contract checks | 2,451 passed, 4 skipped; lint/type/contract/tag checks passed |
| Simplification and ownership boundaries | Reviewed | Track as Debt | `gateway/app.py`, `gateway/health.py`, `gateway/proxy.py`, `gateway/tool_adaptation.py`, `observability/persistence.py` | Health presentation extracted; broader coordinator decomposition is accepted debt |

## 1. Repository state and change surface

- **Status:** Reviewed
- **Severity:** Should Plan
- **Scope:** `git status --short --branch`; `git diff --stat`; `git diff --numstat`; `git diff --check`; `git log -5`; `git show eb94742`.
- **Focus:** stale-state risk, audit attribution, release safety, and preservation of user work.
- **Evidence:**
  - Branch `master` is one commit ahead of `origin/master` at `eb94742` (`feat(admin): add read-only tool catalog`).
  - After the repair, the unstaged tracked diff contains 76 files, 3,819 insertions, and 952 deletions; 17 additional files are untracked.
  - The dirty tree spans gateway, Admin, observability, conversion, Docker, CI, release tooling, compatibility docs, and tests.
  - No staged diff was present. `git diff --check` passed.
  - The ahead commit itself is broad (96 files, including tool catalog, documentation relocation, and retirement of automated release workflows), so its title does not communicate its full release/process scope.
- **Verification:** direct repository inspection; recent committed and current unstaged changes inspected.
- **Gaps / Assumptions:** authorship and completion are not inferred. This dirty snapshot must not be treated as a release-ready revision even though local automated checks are green.

## 2. Gateway authentication, CORS, and Admin authorization

- **Status:** Reviewed
- **Severity:** No Action
- **Resolution status:** Resolved
- **Scope:** `src/codex_rosetta/gateway/auth.py:34-43,83-115,175-226`; `gateway/app.py:419-639,736-784,845-975`; `gateway/admin/routes/auth.py`; Admin route registration; relevant auth/CORS/header tests.
- **Focus:** public/protected route boundaries, constant-time comparisons, principal isolation, login throttling, CORS preflight, header forwarding, client-IP trust, and secret/error exposure.
- **Evidence:**
  - `/v1/responses`, `/v1/models`, and `/v1/embeddings` require a configured access key and set a stable principal ID. The internal Admin test token uses a reserved principal. Current downstream routes outside that set were removed and have negative route tests.
  - Admin API routes require `X-Admin-Token`; login uses `hmac.compare_digest`; the failure store is bounded; untrusted forwarded IP headers are intentionally ignored and the reverse-proxy shared-bucket limitation is documented.
  - Admin CORS is same-origin by default or exact-origin allowlisted, with explicit preflight denial tests.
  - Client authorization and `x-codex-window-id` are not forwarded upstream; only request ID, User-Agent, and OpenResponses-Version are allowed.
- **Finding A — unauthenticated health endpoints disclosed raw upstream/internal errors (resolved):**
  - **Trigger:** any failed proxied request records its response/error string through `_record_telemetry()` into `MetricsCollector._ProviderStats.last_error`. A caller without credentials then requests `/health`; `/health/ready` also returns provider snapshots when critical.
  - **Concrete code:** `MetricsCollector.record_request()` passes `error_detail` at `observability/metrics.py:194-230`; `provider_health_snapshot()` returns `last_error` at `metrics.py:232-243`; `handle_health()` and `handle_health_ready()` return that snapshot at `gateway/app.py:736-784`; auth does not protect those health paths.
  - **Observed reproduction:** recording `error_detail='Authorization failed for Bearer sk-provider-secret; prompt=user@example.com'` and calling `handle_health()` produced HTTP 200 containing the exact provider name, bearer token, and email in `providers.private-provider.last_error`.
  - **Impact at audit time:** unauthenticated network callers could recover API tokens from upstream error text. Provider names, PII, prompts, and other non-token diagnostics remain intentionally public under the accepted health contract.
  - **Resolution:** `MetricsCollector` now redacts API-token fields, configured token values, and Bearer values before retaining `last_error`. `gateway/health.py` owns public health/readiness payloads and applies the current runtime redactor again, covering values retained before startup or config rotation. Admin config activation prepares and commits the metrics redactor alongside auth, stream trace, persistence, and CORS state.
  - **Preserved data contract:** provider names, email/PII, prompts, ordinary `password`/`secret`/`client_secret`/proxy-password fields, and non-token error text remain visible. Only token/API-key/Authorization fields, Bearer values, and exact configured token values are replaced.
- **Verification:** route-level `/health` and `/health/ready` tests inject the original raw disclosure shape and prove both token removal and non-token preservation. Metrics ingestion and config-hot-reload tests cover the two defense layers. Final lint/type and full tests passed.
- **Gaps / Assumptions:** no external reverse proxy or browser was exercised. The audit assumes health routes may be reachable whenever the gateway bind address is externally reachable.

## 3. Config persistence and runtime activation

- **Status:** Reviewed
- **Severity:** No Action
- **Scope:** `src/codex_rosetta/gateway/config.py`; `gateway/admin/routes/_shared.py`; config/key CRUD routes; `tests/gateway/test_config_persistence.py`, `test_admin_config_routes.py`, and `test_app_config_isolation.py`.
- **Focus:** validation, file modes, atomic replacement, lost updates, rollback, hot reload, secret masking, CORS normalization, mandatory credentials, and multiple app instances.
- **Evidence:**
  - Config writes use an owner-only lock, content-digest compare-and-swap for loaded documents, fsynced temporary files, an owner-only backup, atomic replacement, and exact rollback when activation fails.
  - Runtime dependencies are prepared before persistence; activation is synchronous and app-owned, replacing prior module-global config state.
  - Mandatory non-empty Admin password and gateway access keys are validated; IDs and key values are unique; the internal principal is reserved; credential visibility defaults off; bind defaults to loopback.
  - Admin responses mask provider/access/Tavily keys and never return the Admin password.
- **Verification:** full test suite and lint/type checks passed; persistence conflict, file-mode, rollback, and multi-app isolation tests were inspected.
- **Gaps / Assumptions:** no crash-injection or multi-process filesystem stress test was run. `fcntl` keeps the supported persistence path Unix-oriented, consistent with the current macOS/Linux/Docker environment.

## 4. Cross-request state and tool mapping persistence

- **Status:** Reviewed
- **Severity:** Track as Debt
- **Resolution status:** Mapping exposure resolved; deployment continuity accepted
- **Scope:** `gateway/state_scope.py`; state stores in `gateway/proxy.py` and `gateway/tool_adaptation.py`; `observability/persistence.py:534-646`; lifecycle and isolation tests.
- **Focus:** tenant/principal isolation, key rotation stability, request-local fallback, bounded stores, cleanup, restart continuity, and sensitive state retention.
- **Evidence:**
  - State is namespaced by stable principal ID, provider, model, and conversation/window. Requests without a window use a non-persistent request-local ID.
  - Provider metadata, localized tool mappings, and deferred tool search use app-owned roots with bounded size/TTL behavior; shutdown clears all roots; same window IDs are isolated across principals.
  - Persistent localization rows use the same scope and a default 24-hour TTL; expired rows are cleaned periodically.
- **Finding B — persisted tool mappings bypassed the persistence redactor (resolved):**
  - **Trigger:** a localized `Bash`, `Write`, `Edit`, or similar tool call contains a configured API token, Bearer value, or explicit token/API-key field, and the request has `x-codex-window-id` so the mapping is persisted.
  - **Concrete code:** `_persist_tool_mapping()` forwards the complete localized/native calls at `gateway/proxy.py:598-621`; `PersistenceManager.upsert_tool_call_mapping()` serializes both dictionaries directly with `json.dumps()` at `observability/persistence.py:534-572`, unlike request logs, error dumps, metrics, and profile updates that call `redact_sensitive()`.
  - **Observed reproduction:** with `PersistenceManager(token_values={'sk-live-secret'})`, persisting a `Bash` call containing `Bearer sk-live-secret` and an `exec_command` call containing the token left `secret_in_original=True` and `secret_in_codex=True` in the SQLite row.
  - **Impact at audit time:** owner-only file permissions reduced exposure, but API tokens could remain in `gateway.db` for up to 24 hours and enter backups. Other command, file, prompt, PII, password, and secret content remains intentionally available for replay under the accepted token-only policy.
  - **Resolution:** `PersistenceManager.upsert_tool_call_mapping()` now applies its existing token-only redactor to both tool-call shapes before serialization. Encoded JSON in `function.arguments` is recursively inspected for token fields while byte-identical non-token argument strings are preserved. When matching current raw Codex history against a persisted mapping, the gateway applies the same redactor only to a comparison copy; the live history object is not rewritten. A successful localized replay contains `[REDACTED]` where a token existed and retains all other command, file, prompt, PII, password, and secret content.
- **Verification:** a raw SQLite assertion proves configured tokens, Bearer values, and encoded API-key fields are absent while email and ordinary password/secret fields remain. Restart tests close and reopen `PersistenceManager`, load the redacted mapping, match raw history, and restore localized calls. The gateway-level non-streaming regression proves cache/history continuity through the complete proxy path.
- **Gaps / Assumptions:** no multi-process/multi-replica deployment was tested. Provider metadata and deferred tool catalogs remain in-memory only, so a restart or load-balanced request can lose those compatibility aids; this is a reliability limitation to confirm against deployment expectations.

## 5. Responses conversion, tools, and streaming

- **Status:** Reviewed
- **Severity:** No Action
- **Scope:** current diffs in `converters/openai_responses/converter.py`, `stream_context.py`, `tool_ops.py`, `gateway/proxy.py`, `stream_phase_buffer.py`, `tool_adaptation.py`, and their tests.
- **Focus:** namespace tools, custom/freeform `exec`, output item restoration, tool localization history, stream termination, telemetry finalization, bounded phase buffering, deferred tool search, and web-search bridging.
- **Evidence:**
  - Namespace tool aggregation now tolerates malformed/non-list `tools` values.
  - Provider passthrough typing was narrowed without changing wire behavior; custom tool and namespace public typing matches converter behavior.
  - Stream telemetry remains open until actual generator completion and finalizes once on EOF, exception, close, or cancellation.
  - Phase buffering is bounded by event count and bytes and disables inference instead of dropping stream content when limits are exceeded.
  - Full converter/gateway regression suite passed.
- **Verification:** `make check-codex-compat` found all high-confidence contracts unchanged and no changed contract keys at source commit `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`.
- **Gaps / Assumptions:** the repository's own upgrade report is correctly marked `Pending / not approved`. Native GPT, malformed `exec` recovery, compact/resume/fork, plugin/MCP/deferred tools, real web search, UI phase, Desktop/request-user-input, changed error paths, and multi-agent continuation remain unverified live scenarios.

## 6. Observability, redaction, and retention

- **Status:** Reviewed
- **Severity:** Track as Debt
- **Scope:** `observability/redaction.py`, `error_dump.py`, `persistence.py`, `request_log.py`, `gateway/stream_trace.py`, health and Admin metrics routes.
- **Focus:** token redaction, file permissions, payload caps, error retention, stream lifecycle, public/private metrics boundaries, and failure isolation.
- **Evidence:**
  - Error bodies, converted bodies, response text, request-log fields, metrics persistence, profile updates, and stream trace records use targeted token/API-key/Bearer redaction.
  - SQLite/config/trace directories and files are explicitly owner-only. Error body size is capped before compression; count pruning and orphan-body cleanup are documented.
  - Observability failures are best-effort and do not replace successful proxy responses.
  - Public health now uses ingestion and presentation redaction; see resolved Finding A.
  - Persistent tool mappings now use the same targeted redactor without breaking restart replay; see resolved Finding B.
- **Verification:** redaction/error-dump/stream tests passed; the former disclosure and raw-mapping reproductions are now negative regression tests.
- **Gaps / Assumptions:** no total-byte or age-based error-dump retention exists; the security guide discloses this. No restore/backup drill or WAL corruption recovery was run.

## 7. Release, CI, Docker, and compatibility ledger

- **Status:** Reviewed
- **Severity:** Needs Follow-up
- **Scope:** `.github/workflows/ci.yml`, `.github/workflows/docker-safety.yml`, `Makefile`, `docker/*`, `scripts/check_codex_compatibility.py`, `scripts/check_release_version.py`, release and compatibility docs.
- **Focus:** supported Python versions, clean-wheel install, local-source Docker provenance, secret-safe build context, version/tag contract, source baseline, rollback, and release authorization.
- **Evidence:**
  - CI now covers Python 3.10 and 3.13, lint/type/full non-integration tests, and clean-wheel smoke installs for core and gateway extras.
  - Docker builds require the current checkout's local wheel and copy only `dist/` plus the entrypoint; `.dockerignore` excludes common credential/config paths.
  - Package and Docker publishing targets are disabled; docs explicitly define a manual GitHub Release process and rollback limitations.
  - The tag checker accepts `v0.144.0.r0` for source `0.144.0.r0`.
  - Sibling source contract matches commit `2e8c3756…`; the installed CLI is `0.144.1`, while the package/report target remains `0.144.0.r0`. These are correctly treated as separate identifiers, but the current installed CLI is not evidence for the 0.144.0 report.
- **Verification:** contract and release-tag checks passed.
- **Gaps / Assumptions:** no Docker build, image scan/SBOM, artifact signing, clean Python 3.10/3.13 local smoke, GitHub branch-protection inspection, or release rollback exercise was run. Manual release controls are human-enforced; the Draft audit profile leaves provenance/signing expectations undefined.

## 8. Tests and independent verification

- **Status:** Reviewed
- **Severity:** No Action
- **Commands and results:**
  - `git diff --check` — passed.
  - `make lint` / `make test` in the unactivated shell — environment failure only (`ruff`/`pytest` not found).
  - `conda run -n llm-rosetta make lint` — final run passed: Ruff check, Ruff format check (277 files), and `ty check`.
  - `conda run -n llm-rosetta make test` — passed: 2,451 passed, 4 skipped, 9 warnings in 5.92 seconds on Python 3.14.6.
  - Targeted health/config tests — 52 passed.
  - Targeted redaction/persistence/tool-adaptation tests — 93 passed; the two restart/proxy replay regressions also passed after the final fixture update.
  - `make check-codex-compat` — passed; no contract changes block the check.
  - `conda run -n llm-rosetta make check-release-version RELEASE_TAG=v0.144.0.r0` — passed.
  - `codegraph sync` — passed; one changed indexed file and 38 nodes were synchronized.
- **Test quality:** new tests exercise real config files/SQLite, app dispatch, rollback, auth boundaries, store isolation, stream generator lifecycle, token redaction, and packaged-resource loading. Some Admin route modules remain lightly covered by line coverage, but the highest-risk changed paths have behavioral tests.
- **Not run:** integration tests requiring API keys, agentabi matrix, real Codex/API live scenarios, Docker build, clean-wheel install in Python 3.10/3.13, and package build from the dirty snapshot.

## 9. Simplification and ownership boundaries

- **Status:** Reviewed
- **Severity:** Track as Debt
- **Resolution status:** Health ownership resolved; remaining decomposition accepted
- **Scope:** `gateway/app.py` (983 lines), `gateway/proxy.py` (2,655), `gateway/tool_adaptation.py` (1,524), and `observability/persistence.py` (1,118), plus the current diff distribution.
- **Focus:** god modules, change concentration, reusable boundaries, deletion opportunities, and AI-local patch accumulation.
- **Finding C — cross-cutting coordinator modules continue to accumulate unrelated responsibilities (accepted debt):**
  - `app.py` owns telemetry, stream wrapping, request parsing/routing, health, lifecycle jobs, auth, CORS, and route registration.
  - `proxy.py` owns conversion, upstream error translation, persistent mappings, metadata caches, deferred tool ranking, web-search rounds, stream processing, trace integration, and transport orchestration.
  - The pre-repair snapshot added substantial code to `app.py`, `proxy.py`, and persistence while simultaneously introducing new lifecycle/security semantics.
  - **Impact:** future compatibility changes require broad context and make security/stream lifecycle review harder even with strong tests.
  - **Resolution in this repair:** public health/readiness presentation moved from `app.py` into the focused `gateway/health.py` owner. `app.py` now only obtains metrics and returns the HTTP response. The high-risk mapping fix reuses the existing `PersistenceManager` redactor instead of adding a parallel security abstraction.
  - **Accepted debt:** broader extraction of stream telemetry, a dedicated tool-mapping repository, and deferred-tool search ownership remains intentionally deferred. Trigger a follow-up when one of those areas next receives non-local behavior, when multi-process deployment becomes supported, or when the same responsibility needs a third implementation.
- **Simplification constraints:** no new generic helper is recommended solely for two call sites. Preserve provider-neutral converter boundaries and avoid moving gateway-specific compatibility logic into generic converters.
- **Verification:** size/churn and responsibility mapping inspected; the health owner extraction and persistence-redactor reuse are covered by the final lint/type and regression suite.

## Final gaps and assumptions

- The Draft audit profile lacks an owner, approved threat actors/risk tolerance, SLOs, vulnerability-response policy, CI secret/permission baseline, build provenance/signing target, and SBOM expectation.
- The former public health disclosure and raw SQLite token retention are covered by negative regression tests and resolved in the current working tree.
- Provider metadata and deferred-tool state remain single-process; count-only error-dump retention and manual release provenance remain accepted debt under the explicit task boundaries.
- This audit did not claim live Codex 0.144.0 compatibility or release readiness; the repository report remains pending.
