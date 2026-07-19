# Codex-Rosetta Audit Ledger

Audit started: 2026-07-10 07:36 MDT
Repair closure verified: 2026-07-10 MDT
Profile: .agent-work/audit/PROFILE.md (Draft)

| Area | Status | Severity | Files | Notes |
| --- | --- | --- | --- | --- |
| Repository reality and diff inventory | Reviewed | No Action | repository-wide | HEAD eb94742; existing dirty worktree preserved; 88 tracked changes and 23 untracked files |
| Gateway request and state lifecycle | Reviewed; resolved | No Action | google_genai/image_fetch.py, content/converter path, gateway/proxy.py | F-01 historical Must Fix: SSRF, unbounded read, and event-loop blocking are closed |
| Outbound proxy ownership | Reviewed; resolved | No Action | google_genai/image_fetch.py and tests | F-02 historical Should Plan: direct fetch explicitly disables process proxies |
| Admin route dispatch | Reviewed; resolved | No Action | gateway/admin/routes/{__init__,profiling}.py | F-03 historical Should Plan: download route is reachable before typed index route |
| Admin query validation | Reviewed; resolved | No Action | gateway/admin/routes/{_shared,observability}.py | F-04 historical Should Plan: invalid and excessive integers return 400 |
| Config hot reload and persistence retention | Reviewed; resolved | No Action | gateway/config.py, gateway/admin/routes/_shared.py, observability/persistence.py | F-05 historical Should Plan: caps hot-reload transactionally with immediate prune and compensation |
| Persistence, auth, CORS, state scope, and stream lifecycle | Reviewed | No Action | gateway and observability modules | Prior repairs remain coherent in sampled paths; accepted token-only/public-health policy was not reopened |
| Converter/Codex contract | Reviewed | No Action | converters, tool adaptation, compatibility docs/scripts | Automated contract gate passed; live provider matrix remains pending |
| Build, packaging, Docker, release, and CI | Reviewed | Track as Debt | pyproject.toml, Makefile, docker/**, .github/workflows/ci.yml | Existing manual provenance/live deployment gaps remain; no new blocking defect found |
| Test portfolio and independent verification | Reviewed | No Action | tests/** | Lint/type and 2,581 non-integration tests passed after repairs |

## Repository reality and diff inventory

- **Status:** Reviewed.
- **Severity:** No Action for repository state; user work is intentionally preserved.
- **Scope:** Git status, ahead commit, staged/unstaged inventory, relevant repair diffs, current audit artifacts, and CodeGraph.
- **Evidence:** Branch master is one commit ahead of origin/master at eb947426572a. The worktree currently has 88 tracked changes and 23 untracked files, with no staged changes. The repair was made on top of this pre-existing dirty tree; no reset, revert, staging, commit, push, release, or deployment was performed.
- **Verification:** Direct Git inspection, relevant diff review, current source inspection, and CodeGraph call-path review.
- **Gaps / Assumptions:** The audit profile remains Draft. The worktree intentionally includes much more user work than the five repair surfaces, so a clean working tree is not a completion criterion.

## F-01: Arbitrary, unbounded, synchronous URL-image fetch in the Google bridge

- **Status:** Reviewed; resolved.
- **Historical severity:** Must Fix.
- **Scope:** src/codex_rosetta/converters/google_genai/image_fetch.py; content_ops.py; message_ops.py; converter.py; gateway/proxy.py; corresponding converter and gateway tests.
- **Resolution:** URL retrieval now goes through one ImageFetchPolicy/fetch_image_url boundary. It allows only HTTP(S), rejects URL userinfo, rejects private, loopback, link-local, multicast, reserved, unspecified, and otherwise non-global addresses, requires every DNS answer to be public, and pins direct connections to validated numeric addresses. Redirect targets are revalidated on every hop and redirect count is bounded. MIME type, Content-Length, and actual streamed bytes are bounded; errors do not echo the requested URL or response body.
- **Async behavior:** Google-target request conversion now runs through asyncio.to_thread, keeping the synchronous urllib operation off the event-loop thread.
- **Verification:** Direct source and CodeGraph inspection; tests/converters/google_genai/test_image_fetch.py covers unsafe schemes/addresses, mixed DNS answers, redirects, proxy policy, numeric connection pinning, MIME and byte limits, sanitized failures, and loopback pipeline rejection. tests/gateway/test_proxy_image_conversion.py verifies Google conversion runs on a worker thread and non-Google conversion does not.
- **Remaining gaps / assumptions:** No real public image or external provider was contacted. An explicitly configured application proxy is treated as the trusted DNS and egress owner; the direct path is the DNS-rebinding-protected path.

## F-02: The absent-proxy image branch trusted process environment proxies

- **Status:** Reviewed; resolved.
- **Historical severity:** Should Plan.
- **Scope:** src/codex_rosetta/converters/google_genai/image_fetch.py and tests/converters/google_genai/test_image_fetch.py.
- **Resolution:** fetch_image_url always installs an explicit ProxyHandler. When proxy_url is absent it uses ProxyHandler({}), so HTTP_PROXY and HTTPS_PROXY cannot silently change egress. When proxy_url is present, only that application-owned proxy is installed.
- **Verification:** The regression sets stale process proxy variables and asserts an empty proxy map plus pinned direct handlers; the explicit-proxy regression asserts only the configured proxy map and no direct pinned handler.
- **Remaining gaps / assumptions:** Application proxy availability and its own DNS policy were not live-tested.

## F-03: Profiling ZIP download route was unreachable

- **Status:** Reviewed; resolved.
- **Historical severity:** Should Plan.
- **Scope:** src/codex_rosetta/gateway/admin/routes/__init__.py and tests/gateway/test_admin_json_routes.py.
- **Resolution:** The static /admin/api/profiling/results/download route is registered before the dynamic route, and the dynamic route is constrained to <int:index>.
- **Verification:** Dispatch-level regression creates a profiling result, requests the authenticated download route, verifies HTTP 200 and application/zip, opens the archive, and checks its exact file name and HTML bytes.
- **Remaining gaps / assumptions:** Browser UI interaction was not run; the actual route/ZIP contract is covered through app dispatch.

## F-04: Malformed Admin numeric query parameters returned 500

- **Status:** Reviewed; resolved.
- **Historical severity:** Should Plan.
- **Scope:** src/codex_rosetta/gateway/admin/routes/_shared.py; observability.py; tests/gateway/test_admin_json_routes.py.
- **Resolution:** One _bounded_int_qp helper now enforces exactly one value, integer parsing, and endpoint-specific lower/upper bounds. metrics seconds, request-log limit/offset, and error-dump limit/offset return structured 400 responses for invalid input.
- **Verification:** Dispatch-level parameterized coverage includes non-integers, duplicate values, negative values, zero where disallowed, and excessive values, plus valid defaults and pagination.
- **Remaining gaps / assumptions:** Bounds are intentionally local to the existing Admin APIs; no new global validation framework was introduced.

## F-05: Request-log retention limits did not hot-reload with the config

- **Status:** Reviewed; resolved.
- **Historical severity:** Should Plan.
- **Scope:** src/codex_rosetta/observability/persistence.py; gateway/admin/__init__.py; gateway/admin/routes/_shared.py; gateway/config.py; persistence/config/admin tests.
- **Resolution:** Persistence policy now has prepare_update, commit_update, and rollback_update tokens covering the redactor and both caps. Lowering a cap prunes immediately inside one SQLite transaction. A failed prune or commit restores rows and old live values; a later config-write failure compensates a committed policy update, including pruned rows. Startup immediately prunes existing rows to current caps. The zero-row provider-name backfill path commits its transaction so later policy activation can begin safely.
- **Config durability:** write_config atomically writes the candidate and fsyncs its directory before runtime activation. A pre-activation fsync failure restores the exact original file without activating runtime state. A post-activation failure restores the file and the runtime/persistence state.
- **Verification:** App-level tests cover immediate hot-reload/prune, post-activation restoration, and isolation between two app instances. SQLite tests cover lower/increased caps, rollback, partial-prune failure, commit failure, restart convergence, and the zero-row transaction. Config persistence tests cover fsync ordering and exact file restoration.
- **Remaining gaps / assumptions:** Production backup/restore and multi-process concurrency were not exercised. Error-dump retention remains deliberately independent from request-log error_max.

## Reviewed areas with no new action

- **Status:** Reviewed.
- **Severity:** No Action beyond the resolved findings above.
- **Scope:** Gateway auth/CORS, Admin login and key routes, config CAS/backup/rollback, app-scoped stores, encrypted tool mappings and key lifecycle, stream terminal outcomes, redaction/public health, Responses converter/tool adaptation, Docker/build/release/CI paths.
- **Evidence:** Existing access-key principal isolation, exact Admin-origin checks, owner-only atomic config writes, authenticated encrypted mapping storage, explicit completed/error/cancelled stream outcomes, bounded phase buffers, and current-wheel Docker path remained coherent in sampled paths.
- **Gaps / Assumptions:** Public-health PII/error visibility, count-only diagnostic retention, single-process deferred/provider metadata, manual release provenance, and coordinator size remain previously accepted or documented debt, not new findings.

## Independent verification

- Direct make lint and make test initially exited 2 because the current shell did not have ruff or pytest on PATH. The exact errors were make: ruff: No such file or directory and make: pytest: No such file or directory. This was an environment invocation failure, not a project test result.
- conda run -n llm-rosetta make lint: passed; Ruff check, Ruff format check for 283 files, and ty check all passed.
- conda run -n llm-rosetta make test: 2,581 passed, 4 skipped, 9 warnings on Python 3.14.6.
- make check-codex-compat: passed at Codex source commit 2e8c3756f95789c215d9ea9a5ade6ec377934b3f; 14 high-confidence unchanged groups, 12 possibly unchanged groups, and no changed group.
- make check-release-version RELEASE_TAG=v0.144.0.r0: passed with release version 0.144.0.r0.
- git diff --check and git diff origin/master --check: passed.
- codegraph sync: passed; 15 changed files synchronized.
- Not run: real provider/API/agentabi matrix, native GPT, compact/resume/fork, browser UI, WebSocket, GitHub Actions, load/capacity, dependency vulnerability/license scan, production backup/restore, release/deploy/rollback, Python 3.10/3.13 wheel smoke, or Compose smoke.
- Wheel and Compose smoke were not repeated because F-01 through F-05 did not change dependency metadata, package inclusion rules, Docker files, or Compose configuration. CI and release automation remain the required external confirmation.

## Simplification pass

- F-01 and F-02 were resolved through one bounded image fetcher rather than parallel urllib branches.
- F-03 was resolved through route order and the existing typed-route facility.
- F-04 was resolved through one narrow helper at the existing Admin shared boundary.
- F-05 extended the existing activation transaction and persistence owner; it did not add a second configuration service.
- No repair requires a follow-up structural refactor before merge. The principal remaining complexity is the already-large gateway/config coordination surface, which should continue to be protected by transaction and dispatch-level tests.
