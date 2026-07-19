# Codex-Rosetta Audit Ledger

| Area | Status | Severity | Files | Notes |
| --- | --- | --- | --- | --- |
| Repository reality and change scope | Reviewed | No Action | worktree, recent commits, audit profile | Large uncommitted cross-cutting change set verified directly |
| Gateway configuration and Admin control plane | Reviewed | No Action | `gateway/config.py`, `gateway/admin/routes/*`, `gateway/cors.py` | CAS/activation, auth, CORS, JSON and browser rendering sampled |
| Health, observability, and persistence | Reviewed | No Action | `gateway/health.py`, `observability/*` | Accepted token-only semantics preserved; retention/crypto sampled |
| Converter and tool protocol boundaries | Reviewed | No Action | converters, `gateway/tool_adaptation.py`, `gateway/web_search.py` | State ownership, quotas, replay and transport integration sampled |
| Inbound HTTP pre-auth envelope | Reviewed, repaired | No Action | upstream/vendored `httpserver.py`, `gateway/app.py`, `gateway/auth.py` | 5/10/30-second phase deadlines, pre-body auth, and 64-parser cap verified by raw sockets |
| Release, CI, and independent verification | Reviewed | No Action | workflows, Docker, tests | Lint, 2,746-item non-integration suite, wheel and isolated Compose smoke green; live matrix not run |

## Repository reality and audit framing

- **Status:** Reviewed.
- **Severity:** No Action after the inbound HTTP finding was repaired.
- **Scope:** Current `master` worktree at `eb94742`; `git status --short --branch`; recent commits; `.agent-work/audit/PROFILE.md`; repository instructions.
- **Focus:** Current repository state, prior audit resolution evidence, high-risk change surfaces, and profile assumptions.
- **Evidence:** `master` is one commit ahead of `origin/master`; the worktree contains a large unstaged, cross-cutting set of tracked and untracked changes across converters, gateway, observability, Docker, CI, docs, and tests. No staged diff was reported. The repository has `.codegraph/`. Round 17 reported two repaired body-logging findings and a green 2,737-item non-integration suite.
- **Verification:** Direct `git status`, `git log`, file inventory, profile, and previous ledger/report inspected.
- **Gaps / Assumptions:** The audit profile remains `Draft`; owner, legal/privacy, ASVS, SLO, supply-chain, signing, and SBOM decisions remain unapproved. This round proceeds because the user directly requested another audit; unresolved profile fields remain explicit gaps rather than blockers. Prior green test claims will not be reused as current proof without independent checks.

## Gateway configuration and Admin control plane

- **Status:** Reviewed.
- **Severity:** No Action.
- **Scope:** Config raw/env parsing, digest CAS and atomic write, Admin CRUD/activation/rollback, auth, CORS, login limiter, task state, and the Admin HTML rendering sinks.
- **Focus:** Lost updates, partial activation, credential exposure, origin authorization, JSON object boundaries, state isolation, bounded tasks, and stored/reflected DOM injection.
- **Evidence:** Admin mutations preserve `ConfigDocument.source_digest`, validate a complete candidate, prepare dependent state, write under an exclusive lock, activate while the lock is held, and compensate file/runtime state on failure. Admin JSON and CORS/auth boundaries are centralized. Dynamic HTML values sampled from providers, models, fetched model IDs, logs, profiling metadata, diagnostics, and tool catalog use `esc`, `escAttr`, `handlerArg`, or `textContent`; no exploitable new sink was confirmed. Module-global Admin model-test state remains bounded and single-process, consistent with prior accepted deployment assumptions.
- **Verification:** Source trace, current tests, and full suite.
- **Gaps / Assumptions:** No real browser, reverse proxy, or two-process shared-config deployment was exercised. Multi-replica/runtime activation remains outside the established single-process contract.

## Persistence, state, converters, and tool protocol

- **Status:** Reviewed.
- **Severity:** No Action.
- **Scope:** Gateway state scopes and cleanup, persistent localized tool mappings, AES-GCM key/payload ownership, quotas, request/error retention, URL-image worker/fetch boundaries, Responses/Chat/Google conversion changes, tool adaptation, and web search continuation.
- **Focus:** Principal/window isolation, fail-closed replay, encryption integrity, transaction/rollback behavior, bounded state, stream terminal cleanup, and protocol continuity.
- **Evidence:** Persistent tool mappings bind ciphertext AAD to principal/provider/model/session/call identity and enforce row/session/principal/global byte and count budgets in a write transaction. Request-local scopes remain isolated and cleared at terminal completion; persistent scopes require authenticated window identity. Converter/tool paths retain targeted regression coverage. No new cross-principal disclosure, lossy fallback, or unbounded retained-state path was confirmed.
- **Verification:** Source trace plus 2,741 passed/5 skipped full suite.
- **Gaps / Assumptions:** No credentialed live Codex/provider/agentabi flow, hostile DNS/proxy, multi-replica continuity, backup/restore drill, or load/cost test was run.

## Inbound HTTP pre-auth envelope

- **Status:** Reviewed and repaired.
- **Severity:** No Action remains for the confirmed finding.
- **Scope:** Upstream `.agent-work/upstream/zerodep/httpserver/**`; generated upstream manifest/version metadata; officially re-vendored `src/codex_rosetta/_vendor/httpserver.py`; `src/codex_rosetta/gateway/app.py:create_app`; auth/CORS behavior; bilingual Gateway security docs; raw-socket tests.
- **Ownership / repair:** Upstream `httpserver 0.2.3` now owns a 5-second request-line deadline, 10-second header/trailer deadline, 30-second complete-body deadline, `before_body` policy hook, and non-waiting 64-parser process budget. Parser slots release on normal, early, error, disconnect, and cancellation paths. Early responses run after-request hooks. Gateway creates one auth hook and registers the same callable for both pre-body enforcement and direct-`_dispatch` fallback; socket requests skip the duplicate call while direct tests retain fail-closed authentication.
- **Authentication order:** Protected `/v1` and Admin API credentials are checked after bounded headers and before body bytes. Invalid Bearer/Admin credentials with `Content-Length: 50000000` and one body byte return 401 immediately with the expected CORS response. Valid keys still read and dispatch the body. Public Admin login/auth-check and `OPTIONS` remain public and are protected by body deadline, byte cap, and parser capacity.
- **Upstream provenance:** Baseline HEAD remains `fb84dd10ca736129f937740e44a485034b51258b`. The preserved pre-repair dirty patch hash is `ab6a13fbf883cce898ad34ccf10dd75c801740a0fa922ccc83acf17110da8639`; final complete dirty patch hash is `0c31e3037b22b413b44ced49e17efb759cc498a2c4aa736d2363604d44b8c3fa`. Official re-vendor used `python zerodep.py --local update httpserver --no-deps --dir .../_vendor`. After normalizing only the CLI-managed note header, upstream and vendor are byte-identical with SHA-256 `1489f17beb816ff72a353a4c5a16ddb0998da37c2673ca1b30b09af2da174d73`.
- **Verification:** Upstream Ruff/format/source `ty`, 78 correctness tests, `dep-check httpserver`, `make lint`, and `version-check` passed. Upstream pre-commit Ruff/format/ty passed; only the pre-existing dirty `httpclient/conftest.py::_HttpBinHandler::do_GET` complexipy finding remained. Main raw-socket/auth/CORS set passed 51 tests; full main suite passed 2,741/2,746 with 5 skipped. Python 3.10/3.13 core/Gateway wheel smoke passed. Isolated Compose returned healthy/version `0.144.0.r0` and rejected the declared 50 MB invalid request in 0.004 seconds.
- **Residual assumptions:** The 64-parser value is a fixed safety budget, not a measured production capacity target. No credentialed live Codex/provider load test or externally exposed saturation test ran. Network controls and TLS remain required for non-loopback deployments.

## Accepted health/redaction semantics

- **Status:** Reviewed.
- **Severity:** No Action under the explicit accepted contract.
- **Evidence:** Public health/readiness retain provider names, prompt/PII, ordinary password/secret/client-secret/proxy-password and non-token error text while configured token/API-key/Bearer/Authorization values are redacted. `.agent-work/audit/20260709-2336/REPORT.md` and later rounds record this as accepted semantics, and current regression tests enforce it.
- **Verification:** Focused health/auth/CORS tests passed. This round does not reopen or re-report the accepted residual.

## Release, CI, and independent verification

- **Status:** Reviewed.
- **Severity:** No Action for local gates; governance gaps remain accepted debt.
- **Evidence:** `conda run -n llm-rosetta make lint` passed Ruff check, format check for 294 files, and `ty check`. `conda run -n llm-rosetta make test` collected 2,746 items and returned 2,741 passed, 5 skipped, and 9 warnings. Focused raw-socket/auth/CORS coverage returned 51 passed. `make build`, Codex compatibility, release-version, Python 3.10/3.13 wheel, isolated Compose, `git diff --check`, and CodeGraph sync passed. Final repository status was checked directly; the repair did not stage, commit, push, release, or deploy.
- **Not run:** Integration tests requiring credentials, live Codex/provider/agentabi, browser Admin smoke, external GitHub Actions, vulnerability/license/SBOM/signing checks, load/capacity, backup/restore, release, deploy, or rollback.

## Simplification pass

- Repair extends the upstream HTTP parser's existing bounded-read owner and is officially re-vendored; no second Gateway parser was added.
- One pre-body authorization hook closes the ownership gap without weakening the authenticated request-size contract or duplicating auth logic.
- One app/server parser counter owns concurrency; no per-route semaphore or waiting-task queue was introduced.
