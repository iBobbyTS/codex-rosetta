# Codex-Rosetta Audit Ledger

| Area | Status | Severity | Files | Notes |
| --- | --- | --- | --- | --- |
| Repository reality and change scope | Reviewed | No Action | repository-wide uncommitted diff | Existing broad user work preserved; repair remained local to Admin runtime, transport limit parameters, tests, and security docs |
| Gateway ingress and API request state | Reviewed | No Action | `src/codex_rosetta/gateway/{app,auth,cors,health,state_scope}.py` | Auth, limits, CORS, request/window state cleanup |
| Admin mutable runtime state | Reviewed | No Action | `gateway/admin/runtime.py`, `gateway/admin/routes/{auth,testing}.py`, `gateway/admin/__init__.py`, `gateway/app.py` | F-01 resolved with one app-owned runtime per `create_app()` |
| Admin model-test retention | Reviewed | No Action | `gateway/admin/runtime.py`, `gateway/admin/routes/testing.py`, `gateway/transport/http/transport.py` | F-02 resolved with 4 MiB per-read/per-record and 32 MiB per-app completed budgets |
| Gateway proxy and stream lifecycle | Reviewed | No Action | `src/codex_rosetta/gateway/{proxy,stream_trace,stream_phase_buffer}.py` | Streaming, cancellation, telemetry |
| Persistence and observability | Reviewed | No Action | `src/codex_rosetta/observability/**` | Redaction, encrypted mappings, retention, SQLite lifecycle |
| Converter and image path | Reviewed | No Action | `converters/google_genai/**`, `gateway/image_workers.py` | Remote image fetch and conversion |
| Vendored HTTP/SSE provenance | Reviewed | No Action | `_vendor/{httpclient,httpserver,sse}.py`, `.agent-work/upstream/zerodep/**` | Official upstream patch/re-vendor provenance reverified; no repair edit |
| Build, CI, Docker, release | Reviewed | Track as Debt | `.github/**`, `docker/**`, `Makefile`, `pyproject.toml` | Local gates and isolated Compose smoke pass; external release/integration evidence remains incomplete |
| Tests and independent verification | Reviewed | No Action | `tests/**` and project gates | Targeted, full-suite, wheel, and Compose verification passed |

## Audit framing

- Profile: `.agent-work/audit/PROFILE.md` (`Status: Draft`).
- Primary quality attributes: correctness and reliability first; then security, operability, and maintainability.
- Scope: the current large uncommitted Gateway/security/reliability change set, followed by a bounded repair of the two round-20 findings.
- Constraints: preserve all user work; do not edit `src/codex_rosetta/_vendor/**`; do not commit, push, open a PR, release, or deploy.
- Remaining profile gaps: owner/legal baseline/security standard/CI trust boundary remain undefined; live credentialed provider and agentabi tests require external access.

## Repository reality and prior-audit reconciliation

- **Status:** Reviewed.
- **Scope:** Current `master` working tree, `git status --short`, current unstaged/untracked diff, Draft audit profile, round-10/12/18/19 ledgers, current source, and the round-20 repair diff.
- **Evidence:** The audit began with 98 tracked modified files plus additions. The repair did not reset, revert, stage, commit, push, release, or deploy any user work. `git diff --check` and `git diff --cached --check` pass.
- **Prior-state check:** Round 19 closed the malformed converted-SSE finding. Round 20 independently found two Admin control-plane issues; both now have visible implementation and executable verification evidence below.
- **Gaps:** The profile remains Draft and its owner, legal/privacy baseline, ASVS target, SLO/error budget, incident response, SBOM/signing, and production deployment model remain undefined.

## F-01 resolved: module-global Admin state crossed app authentication boundaries

- **Status:** Reviewed; resolved.
- **Severity after repair:** No Action.
- **Original scope:** Former module-level `_login_failures` in `gateway/admin/routes/auth.py` and `_test_tasks` in `gateway/admin/routes/testing.py`.
- **Original impact:** Failed logins, task lookup/cancellation, cleanup, and capacity crossed separately configured `create_app()` Admin boundaries. A task ID could expose another app's result.
- **Repair:** `gateway/admin/runtime.py` now provides `AdminRuntimeState`, `AdminLoginLimiter`, and `AdminTestTaskStore`. `setup_admin()` creates exactly one owner for each app; routes resolve it from `request.app`; config hot reload preserves the owner; `run_gateway()` closes that app's runtime before other resources. Shutdown cancels/awaits and clears only its own tasks. No mutable request state remains at module scope.
- **Isolation evidence:** Two-app route tests verify app-A failures do not block app B, cross-app GET/cancel return 404, cleanup/capacity do not cross stores, hot reload preserves the app owner, and two `create_app()` calls have different runtime/limiter/store identities.
- **Lifecycle evidence:** Async shutdown verification confirms app A cancels and awaits its active task, clears its completed result and byte accounting, and leaves app B running until B is explicitly closed.
- **Concurrency evidence:** A threaded limiter test records 200 failures atomically under one app owner.

## F-02 resolved: Admin model-test results had no resident-memory budget

- **Status:** Reviewed; resolved.
- **Severity after repair:** No Action.
- **Original scope:** Count-only 128-task retention, 50,000,000-byte auxiliary success reads, eager `resp.json()`, and retained decoded Python objects.
- **Original impact:** Sequential successful Admin tests could retain approximately 6.4 GB of raw bodies before Python object expansion and poll-time reserialization.
- **Repair:** Admin self-calls pass explicit 4 MiB success and error limits to `request_bounded_response()`. The helper resolves ordinary defaults at call time, preserving test/runtime override behavior. Results remain bounded UTF-8 JSON bytes in `AdminTestTaskStore`; GET decodes only a temporary public value. Each retained record, including metadata, is capped at 4 MiB; completed records share a 32 MiB per-app budget; the 128-record cap remains; running tasks count toward records but not completed bytes. Enforcement is lock-atomic, evicts only that store's oldest completed records, and never evicts active work.
- **Overflow behavior:** `Content-Length` and incremental body counting reject over-limit bodies before full JSON decoding. `_run_test_task()` records a stable 502 diagnostic (`Admin model-test upstream response exceeds 4194304 bytes`) without a partial body. A compact 507 diagnostic handles retained-record/aggregate capacity failure.
- **Boundary evidence:** Exact 4 MiB auxiliary reads succeed; 4 MiB plus one byte closes the response and raises the stable domain overflow. Store tests cover oversize per-task replacement, the default 32 MiB aggregate, oldest-completed eviction, active preservation, 128 active records with no evictable completion, normal/error/cancel/TTL/eviction accounting, and an aggregate too small even for the compact diagnostic without negative accounting.
- **Packaging evidence:** Python 3.10.20 and 3.13.2 independently installed the built wheel, imported `AdminRuntimeState`, created isolated owners, reserved/finished/read a task, and confirmed the 4 MiB constant.

## Gateway runtime, persistence, transport, and converter review

- **Status:** Reviewed; no additional open finding confirmed.
- **Scope:** Auth-before-body parser path; CORS; request/window scope; stream telemetry and cleanup; persistent encrypted tool mappings; redaction/retention; Google URL-image fetch and worker pool; primary/auxiliary HTTP body and SSE limits; Responses/Google changed converter paths.
- **Evidence:** Protected `/v1` requests authenticate before body consumption; non-window state uses a private UUID scope and is cleared on every terminal path; persistent mappings bind principal/provider/model/session/call AAD and enforce hierarchical budgets; image URLs reject private/mixed DNS answers and use bounded app-owned workers; HTTP bodies, SSE lines/events, and auxiliary requests use explicit limits.
- **Gaps:** No credentialed live provider/Codex/agentabi, hostile live DNS/proxy, real client disconnect, backup/restore, multi-replica, or production load test was run.

## Vendored runtime provenance

- **Status:** Reviewed; no action.
- **Scope:** Round-10/12/18 audit evidence, `.agent-work/audit/20260710-1128/UPSTREAM_BASELINE.md`, `.agent-work/audit/20260710-1547/UPSTREAM_BASELINE.md`, `.agent-work/upstream/zerodep`, and current vendor files.
- **Evidence:** Prior rounds captured upstream dirty-patch baselines, patch hashes, correctness tests, version bumps, official `zerodep.py --local update ...` re-vendor, and normalized source equality. Round 20 repeated normalized SHA-256 comparisons: current upstream/vendor `httpclient`, `httpserver`, and `sse` matched after only CLI-managed install-note normalization. The repair made no `_vendor` edit.
- **Assumption:** The upstream dirty patch remains intentionally uncommitted/unpushed under existing authorization boundaries.

## Independent verification and simplification

- **Focused tests:** 57 focused repair tests passed. The expanded Admin/transport/app/lifecycle group returned **243 passed, 1 skipped**.
- **Full suite:** `make test` returned **2765 passed, 5 skipped, 9 warnings**.
- **Static gates:** `make lint` passed Ruff, format check for 296 files, and `ty check`; `git diff --check` and `git diff --cached --check` passed.
- **Build and contracts:** `make build`, `make check-codex-compat`, and `make check-release-version RELEASE_TAG=v0.144.0.r0` passed. Compatibility source commit was `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`; `Changed: None`.
- **Wheel smoke:** Python 3.10.20 and 3.13.2 both printed `admin-runtime-wheel-smoke-ok` from the built `0.144.0.post0` wheel.
- **Compose smoke:** An isolated three-service Compose project used the current local wheel image, two Gateway configs, and a loopback upstream returning over 4 MiB. The Admin task produced the stable 502 diagnostic with no body; polling its ID through the other Gateway returned 404; five app-A failures produced app-A 429 while valid app-B login remained 200. All created containers, network, image, configs, and databases were removed after inspection.
- **CodeGraph:** `codegraph sync` completed and reported the index already up to date.
- **Not run:** Credentialed integration tests, external GitHub Actions, vulnerability/license/SBOM/signing checks, browser Admin smoke, production deploy/rollback, backup/restore, or production capacity/load tests.
- **Simplification:** Repair deleted module-global ownership instead of adding app IDs to shared dictionaries, and uses one bounded app-owned task store rather than a parallel cache or decoded-object retention path.
