# Codex-Rosetta Audit Ledger

Audit started: 2026-07-10 00:13 MDT

Profile: `.agent-work/audit/PROFILE.md` (Draft; owner and several security/release baselines remain undefined)

| Area | Status | Severity | Files | Notes |
| --- | --- | --- | --- | --- |
| Repository reality and diff inventory | Reviewed | No Action | repository-wide | Closing state: 77 tracked status entries, 19 untracked files; 4,041 insertions and 1,035 deletions in tracked diff |
| Gateway routing, auth, and headers | Reviewed | No Action | `src/codex_rosetta/gateway/{app,auth,cors,headers}.py` | F-01 resolved: protected preflight and auth-error responses now receive the route-specific CORS policy |
| Admin control-plane browser security | Reviewed | No Action | `gateway/admin/routes/auth.py`, `gateway/admin/admin.html` | F-02 resolved: every Admin HTML route sends CSP frame denial and `X-Frame-Options: DENY` |
| Admin input validation | Reviewed | No Action | `gateway/admin/routes/{_shared,auth,config,keys,profiling,testing}.py` | F-03 resolved: all Admin JSON routes share an object-root parser and profiling rejects non-integer counts |
| Config/admin hot reload and persistence | Reviewed | No Action | `src/codex_rosetta/gateway/config.py`, `gateway/admin/routes/_shared.py` | F-04 resolved: JSONC is parsed before recursive string-value substitution; CAS/rollback remains unchanged |
| Observability, redaction, and SQLite | Reviewed | No Action | `src/codex_rosetta/observability/*`, `gateway/health.py` | Token boundaries and state ownership reviewed; broader public health content is an explicitly accepted prior contract |
| Stream/tool/Codex compatibility | Reviewed | No Action | gateway stream/tool modules, Responses converter | State scope, terminal cleanup, compatibility contract and tests reviewed |
| Build, Docker, CI, and release | Reviewed | Track as Debt | `.github/workflows/ci.yml`, `docker/*`, `Makefile`, release scripts | Local gates pass; manual provenance and live release evidence remain explicit debt/gaps |
| Test portfolio and independent verification | Reviewed | No Action | `tests/**` | Lint/type, 2,519 passed tests, Codex contract, release contract, diff checks, and CodeGraph sync passed |

## Repository reality and diff inventory

- **Status:** Reviewed
- **Severity:** No Action; the intentionally dirty worktree remains uncommitted and was preserved.
- **Scope:** `git status --short`, current branch and recent history, `git diff --stat`, `git diff --numstat`.
- **Focus:** Worktree truth, review surface, stale-context risk, recent committed baseline.
- **Evidence:** Current branch is `master` at `eb94742`; `origin/master` is `d3e899a`. At close the worktree has 77 tracked status entries plus 19 untracked files. The tracked diff has 4,041 insertions and 1,035 deletions. No changes were committed, pushed, released, deployed, reset, or reverted during repair.
- **Verification:** Direct `git status --short`, branch/revision, numstat, relevant unstaged diff, staged-diff, and whitespace checks were run at audit close.
- **Gaps / Assumptions:** The large dirty snapshot contains pre-existing user work and is intentionally not treated as one releasable revision. Audit artifacts are ignored working files and are not part of the tracked diff.

## Gateway routing, auth, and headers

- **Status:** Reviewed
- **Severity:** No Action; F-01 resolved in the current worktree.
- **Scope:** `gateway/cors.py:8-32`; `gateway/auth.py:85-114,177-238`; `gateway/app.py:825-920`; `tests/gateway/test_app_headers.py:99-288`.
- **Focus:** Authentication ordering, CORS preflight, error-path response headers, upstream header allowlist, request-local identity.
- **Evidence:** `apply_cors_headers()` is now the single route-specific CORS policy. The auth hook exempts OPTIONS only for protected routes, applies Admin exact-origin CORS to Admin auth failures, and applies public wildcard CORS to API-key failures. Route-level tests cover allowed/denied Admin preflight, allowed-origin Admin 401, denied-origin Admin 401, all three protected `/v1` preflights, public API 401, and hot-reloaded Admin origins.
- **Trigger / failure path:** Browser sends an Authorization-bearing cross-origin API request (which requires preflight), or an allowed cross-origin Admin UI makes a request with a missing/expired token.
- **Impact:** The advertised wildcard `/v1` browser CORS path is unusable; allowed cross-origin Admin clients see an opaque CORS network failure instead of the intended 401/login recovery.
- **Resolution:** Implemented the suggested routing without weakening authentication of the subsequent real request. Admin origin checks remain exact allowlist matches and disallowed origins receive no CORS grant.
- **Verification:** Route-level regressions plus the full suite passed.
- **Gaps / Assumptions:** Cross-origin browser support is inferred from the explicit CORS implementation and comments. If it is not a supported contract, remove the permissive CORS surface and document that instead.

## Admin control-plane browser security

- **Status:** Reviewed
- **Severity:** No Action; F-02 resolved in the current worktree.
- **Scope:** `gateway/admin/routes/auth.py:18-32`; `tests/gateway/test_admin_page_routes.py:65-84`; Admin response headers.
- **Focus:** Clickjacking, session-token use, defense in depth for a privileged control plane.
- **Evidence:** `serve_admin_html()` now emits `Content-Security-Policy: frame-ancestors 'none'` and `X-Frame-Options: DENY` alongside the no-store policy. The parameterized route test asserts both headers for every registered Admin HTML alias.
- **Trigger / failure path:** An operator who has a valid token in gateway-origin local storage visits an attacker-controlled page that frames the reachable Admin UI and overlays or positions controls to induce privileged clicks.
- **Impact:** Clickjacking can drive provider/model/key/config mutations without exposing the token to the attacker. Blast radius is the gateway control plane.
- **Resolution:** Implemented the suggested narrow anti-framing policy without changing the current inline script/style execution contract.
- **Verification:** Route-level regression plus the full suite passed.
- **Gaps / Assumptions:** Reverse proxies may add these headers in some deployments, but no repository-owned baseline requires that and local/direct deployments do not receive them.

## Admin input validation

- **Status:** Reviewed
- **Severity:** No Action; F-03 resolved in the current worktree.
- **Scope:** `gateway/admin/routes/_shared.py:46-54`; all Admin `request.json()` consumers; `profiling.py:35-61`; `tests/gateway/test_admin_json_routes.py`.
- **Focus:** Untrusted JSON shape, error handling, repeated route patterns, unauthenticated error amplification.
- **Evidence:** `_parse_json_object()` is now the only Admin `request.json()` call site. Login, provider, model, model-group, server, bulk-model, keys, testing, and profiling routes return a consistent 400 for invalid JSON or a non-object root. Profiling catches `TypeError`/`ValueError` from integer conversion.
- **Trigger / failure path:** Valid JSON scalar/list bodies, or invalid scalar values such as a non-numeric profiling request count.
- **Impact:** Malformed client input becomes internal errors. The public login route can be used for unauthenticated exception/log amplification; authenticated routes are brittle for API clients and future UI changes.
- **Resolution:** Implemented the shared parser while retaining route-specific field validation.
- **Verification:** A route-level matrix covers six non-object JSON values across ten Admin mutation/login routes, plus the non-integer profiling case; lint/type and full suite passed.
- **Gaps / Assumptions:** This finding does not claim arbitrary code execution or authentication bypass.

## Config/admin hot reload and persistence

- **Status:** Reviewed
- **Severity:** No Action; F-04 resolved in the current worktree.
- **Scope:** `gateway/config.py:170-226`; startup `load_config()` and Admin `GatewayConfig.from_raw_with_env()`; `tests/gateway/test_config.py:69-106`; Admin config-route tests.
- **Focus:** JSONC parsing, environment-backed secrets, lost updates, atomicity, activation rollback, file permissions.
- **Evidence:** JSONC comments are stripped and the document is parsed before `_substitute_env_vars()` recursively walks dict/list/string values. Environment content therefore remains string data even when it contains quotes, backslashes, newlines, or JSON-looking fragments. Startup and Admin candidate construction share this behavior. Digest CAS, sidecar lock, 0600 atomic write/backup, fsync, prepare-before-write, and assignment-only activation paths remain covered.
- **Trigger / failure path:** A secret manager/environment supplies a syntactically meaningful JSON character in a password, API key, URL, or other placeholder.
- **Impact:** Legitimate strong credentials can prevent startup or Admin saves. Environment data can unexpectedly alter sibling configuration fields, weakening configuration provenance and validation assumptions.
- **Resolution:** Implemented parse-first recursive string substitution. Missing variables remain literal placeholders with a warning, preserving the prior unresolved-variable contract.
- **Verification:** Startup and Admin candidate regressions cover quote/backslash/newline and attempted sibling-field injection; lint/type and full suite passed.
- **Gaps / Assumptions:** Process environment control is normally privileged, so this is not presented as a remote privilege escalation. It is a correctness and configuration-boundary flaw.

## Observability, redaction, and SQLite

- **Status:** Reviewed
- **Severity:** No Action for the current explicitly accepted contract.
- **Scope:** `observability/redaction.py`, `metrics.py`, `persistence.py`, `error_dump.py`, `request_log.py`; `gateway/health.py`; persistence and health tests.
- **Focus:** Token redaction, prompt/PII retention, owner-only files, schema migration, scoped tool mappings, request/stream result updates.
- **Evidence:** Current writes redact configured token values, bearer/authorization values, token/API-key fields, including encoded function arguments. SQLite files and sidecars are owner-only and tool mappings are principal/provider/model/window scoped. The public health payload still exposes provider names and ordinary password/PII text in `last_error`; a current reproduction confirmed it. However, `.agent-work/audit/20260709-2336/REPORT.md` explicitly records this token-only public-health content as an accepted contract, so it is not reclassified as a new Must Fix finding in this pass.
- **Verification:** Source, tests, prior accepted audit decision, direct health payload reproduction, and full suite.
- **Gaps / Assumptions:** The accepted public-health information contract is not clearly disclosed in versioned user-facing security docs; owner should confirm whether the prior local audit artifact is sufficient as the authoritative decision record.

## Stream/tool/Codex compatibility

- **Status:** Reviewed
- **Severity:** No Action in reviewed code; external/live gaps remain.
- **Scope:** `gateway/proxy.py`, `state_scope.py`, `tool_adaptation.py`, `stream_phase_buffer.py`, `stream_trace.py`, Responses converter/stream context, tool ops, compatibility ledger and script.
- **Focus:** Principal/window scoping, TTL/capacity, mapping persistence, normal/error/cancel/disconnect cleanup, namespace/tool_search, Responses event restoration, Codex source contract.
- **Evidence:** App-owned stores are scoped consistently by `GatewayStateScope`; missing window IDs are request-local and non-persistent. Persistent mappings use the full compound scope and remove legacy unscoped rows. Stream terminal ownership closes sources and records telemetry exactly once across covered paths. Namespace/custom tool changes have meaningful tests. `make check-codex-compat` reports 13 high-confidence unchanged groups, 12 possibly unchanged groups, and no changed group at source commit `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`.
- **Verification:** CodeGraph call paths, source/tests, full suite, current compatibility gate.
- **Gaps / Assumptions:** The report remains `Pending / not approved`; no live Codex/provider, agentabi, compact/resume/fork, multi-replica, or WebSocket run was performed.

## Build, Docker, CI, and release

- **Status:** Reviewed
- **Severity:** Track as Debt
- **Scope:** `.github/workflows/ci.yml`, `Makefile`, `docker/*`, `pyproject.toml`, `scripts/check_release_version.py`, release docs.
- **Focus:** Python matrix, source-wheel integrity, disabled publishing, manual release provenance, rollback.
- **Evidence:** CI runs lint/type/full non-integration tests and core/gateway wheel smoke on Python 3.10/3.13. Local Docker build requires the current checkout wheel and publishing targets are disabled. The release validator correctly enforces source/tag spelling and equality. Release provenance, clean revision, compatibility report evidence, signing and SBOM remain manual and are already recorded as debt/pending release authorization.
- **Verification:** Static inspection; release tag contract command passed; no Docker daemon or GitHub Actions run.
- **Gaps / Assumptions:** No image build/scan, GitHub-hosted CI, signing, SBOM, release or rollback exercise.

## Test portfolio and independent verification

- **Status:** Reviewed
- **Severity:** No Action for available local gates; all four finding regressions are present.
- **Scope:** repository test suite, lint/type checks, compatibility/release commands, current/recent diffs.
- **Evidence / Verification:** `conda run -n llm-rosetta make lint` passed (Ruff, format, ty). `conda run -n llm-rosetta make test` passed with 2,519 passed, 4 skipped, 9 warnings on Python 3.14.6. `make check-codex-compat` passed with 13 high-confidence unchanged groups, 12 possibly unchanged groups, and no changed group at source commit `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`. `make check-release-version RELEASE_TAG=v0.144.0.r0`, `git diff --check`, staged diff check, direct status/diff review, and `codegraph sync` passed.
- **Gaps / Assumptions:** Local execution did not reproduce CI's Python 3.10/3.13 matrix and did not run external integration, real browser, live Codex/provider/agentabi, Docker, load/capacity, dependency-vulnerability, or restore tests.
