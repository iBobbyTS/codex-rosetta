# Codex-Rosetta Audit Ledger — 2026-07-09 23:02 MDT

| Area | Status | Severity | Files | Notes |
| --- | --- | --- | --- | --- |
| Audit framing and repository state | Reviewed | No Action | `.agent-work/audit/PROFILE.md`, repository diff | Profile loaded; large uncommitted change set confirmed |
| Authentication and admin mutation routes | Reviewed | Should Plan | `src/codex_rosetta/gateway/auth.py`, `src/codex_rosetta/gateway/admin/routes/*`, `src/codex_rosetta/gateway/app.py` | F-02 resolved: model-discovery client closes on all exit paths |
| Configuration and persistence | Reviewed | No Action | `src/codex_rosetta/gateway/config.py`, `src/codex_rosetta/observability/*` | Candidate validation, CAS, rollback, scoped persistence, and redaction reviewed |
| Proxy, streaming, tools, and cross-request state | Reviewed | Must Fix | `src/codex_rosetta/gateway/app.py`, `admin/routes/config.py`, `admin/routes/testing.py`, stores and persistence | F-01 resolved: request paths and hot reload use the owning app config |
| Converter and Codex compatibility | Reviewed | Must Fix | `converters/openai_responses/*`, compatibility docs/scripts | F-03 resolved: upgrade decision is pending with itemized evidence gaps |
| CI, release, container, and operations | Reviewed | Track as Debt | `.github/workflows/ci.yml`, `Makefile`, `docker/*`, release docs/scripts | Existing manual release-provenance limitation remains explicit |
| Test portfolio and independent verification | Reviewed | Should Plan | `tests/`, lint/test/compatibility/release commands | Multi-app and client-cleanup regressions added; full local gates and wheel smoke passed; live compatibility gaps remain explicit |

## Audit framing and repository state

- **Status:** Reviewed.
- **Scope:** Current checkout at `master`, current uncommitted working tree, recent commit history, `.agent-work/audit/PROFILE.md`.
- **Focus:** Repository reality, audit assumptions, changed-file blast radius, and source-of-truth conflicts.
- **Evidence:** `git status --short --branch` reports `master...origin/master [ahead 1]`, 74 tracked modified files and 14 untracked files in the current worktree. `git diff --stat` reports 3,358 insertions and 862 deletions. `.codegraph/` is present and was used before file-level search. The audit profile is `Draft` and limits its baseline primarily to Codex compatibility, but the current diff materially changes authentication, admin mutation routes, configuration persistence, redaction, release, and Docker behavior; those changed trust boundaries are included in this pass.
- **Verification:** Repository state, recent history, full diff scope, and final test/check outputs inspected directly. After the repair pass, the worktree still has 74 tracked modified files and now 16 untracked files (the two added regression files account for the increase); tracked diff is 3,413 additions / 920 deletions. HEAD remains `eb947426572ad7658c4b5ad19688fa68659a06b6`; no commit, push, PR, release, or deployment occurred.
- **Gaps / Assumptions:** Legal/privacy constraints, deployment topology, ASVS target, release signing, CI secret policy, SLOs, and vulnerability-response ownership remain unapproved profile fields. This pass assumes a gateway may be reachable beyond loopback because Docker and remote deployment are documented.

## Authentication and admin mutation routes

- **Status:** Reviewed.
- **Severity:** Should Plan.
- **Scope:** `gateway/auth.py`; Admin authentication, config, key, testing, observability, and model-discovery routes; route-level negative tests.
- **Focus:** Fail-closed authentication, Admin token lifecycle, login throttling, CORS, config/key mutation validation, bounded background tasks, and outbound-client cleanup.
- **Evidence:** Gateway and Admin APIs now require distinct credentials, Admin token comparison uses `hmac.compare_digest`, failed login state is TTL/cap bounded, config candidates validate before write/activation, and key mutations cannot remove the last access key. One outbound lifecycle defect remains: `fetch_upstream_models()` constructs `AsyncClient` at `src/codex_rosetta/gateway/admin/routes/config.py:1042`, but `await client.aclose()` is only reached after a successful `get()` at line 1046; the exception handler at lines 1047-1050 does not close it.
- **Verification:** A current-code reproduction replaced `AsyncClient` with a fake whose `get()` raises `RuntimeError("boom")`; the route returned its documented JSON error response while the fake reported `closed=False`. Full route/unit suite passes, but it has no failure-path close assertion for this handler.
- **Finding F-02:** A repeated failing/timeout model-discovery request can leave each dedicated async client/pool unclosed. Impact is Admin-only resource growth and degraded reliability; exact socket retention depends on the vendored client's failure cleanup. Recommended direction: use `async with AsyncClient(...) as client` or unconditional `finally: await client.aclose()`, with a failure-path regression.
- **Resolution:** **Resolved.** `fetch_upstream_models()` now uses `async with AsyncClient(...)` and explicitly re-raises `asyncio.CancelledError`. `tests/gateway/test_admin_model_discovery_cleanup.py` exercises success, connection failure, JSON parse failure, and cancellation; every case asserts one context entry and exactly one exit, with cancellation still propagating.
- **Gaps / Assumptions:** Browser UI layout/accessibility and real reverse-proxy behavior were not exercised.

## Configuration and persistence

- **Status:** Reviewed.
- **Severity:** No Action.
- **Scope:** `gateway/config.py`, Admin `_shared.py`, `observability/redaction.py`, `error_dump.py`, `persistence.py`, `request_log.py`, config/key/persistence tests.
- **Focus:** Validation, lost-update prevention, crash safety, activation ordering, file permissions, SQLite migration/scope, retention, and exact-token redaction.
- **Evidence:** `ConfigDocument.source_digest` is checked under a stable sidecar lock; writes use owner-only temporary files, atomic replacement, backup, fsync, and activation rollback. Runtime-dependent state is prepared before persistence, and assignment-only activation updates authentication, trace redaction, persistence redaction, CORS, and app config. Persistent tool mappings key on principal/provider/model/session/call. The documented token-only privacy boundary matches `SecretRedactor` behavior.
- **Verification:** Full suite, lint/type checks, config persistence/security tests, and `git diff --check` pass.
- **Gaps / Assumptions:** No crash-injection process test, backup restore drill, disk-full test, or concurrent multi-process load test was run. The accepted count-only diagnostic retention remains an explicit operational debt from prior audits.

## Proxy, streaming, tools, and cross-request state

- **Status:** Reviewed.
- **Severity:** Must Fix.
- **Scope:** `gateway/app.py`, `proxy.py`, `state_scope.py`, `tool_adaptation.py`, `stream_phase_buffer.py`, `stream_trace.py`, Admin config/testing helpers, state/persistence/stream tests.
- **Focus:** Request ownership, multi-instance state, cross-principal isolation, stream terminal ownership, phase buffer bounds, and cleanup.
- **Evidence:** Request-level state stores correctly scope by `GatewayStateScope(principal_id, provider_name, model, conversation_id)` and missing window IDs become request-local/non-persistent. However application configuration still has two owners: `create_app()` assigns module global `_config` at `gateway/app.py:849-852`, while `_proxy_handler`, embeddings, both model-list handlers, and web-search setup read `_config` at lines 430, 463-465, 556, 654-655, and 692-735. Admin helpers repeat the global read at `admin/routes/config.py:102-106` and `admin/routes/testing.py:148-152`, despite every app already owning `app.gateway_config`.
- **Verification:** Current-code reproduction created app A with only `model-a`, then app B with only `model-b`, then invoked app A's proxy handler for `model-a`. It returned HTTP 404 with `Configured models: model-b`, proving the second factory call redirected the first app's configuration reads. Full tests pass because they do not keep two apps live with distinct configs.
- **Finding F-01:** Multiple app instances in one process cross-talk through module-global configuration. The first app may route using the second app's models, provider endpoints/credentials, web-search policy, and model catalog. This violates the isolation implied by the app factory and can cause requests to be sent to the wrong upstream. Recommended direction: make `request.app.gateway_config` the request-path source of truth in all handlers/helpers; update only the owning app on hot reload, and retain the module global only if a documented compatibility API still needs it. Add a two-app route/config isolation regression.
- **Resolution:** **Resolved.** Module-global `gateway.app._config` was removed. `create_app()` assigns `gateway_config` immediately, proxy/embeddings/model-list handlers and Admin config/testing helpers read the owning `request.app`, and `_activate_gateway_config()` updates only that app. `tests/gateway/test_app_config_isolation.py` creates A then B and proves A still owns its route, provider base URL/auth header, web-search config, OpenAI/Google model catalog, embeddings config, Admin helpers, and hot-reload state while B remains unchanged.
- **Gaps / Assumptions:** Production normally runs one app per process, which reduces likelihood but does not repair the public factory contract or in-process embedding/tests.

## Converter and Codex compatibility

- **Status:** Reviewed.
- **Severity:** Must Fix.
- **Scope:** Responses converter/context/type changes, reasoning/tool public helpers, `docs/dev/version-compatibility/*`, compatibility checker, and related tests.
- **Focus:** New wire shapes, source-contract automation, itemized upgrade gates, live-test evidence, and revision traceability.
- **Evidence:** Converter changes are small typing/shape hardening changes and pass the full suite. `make check-codex-compat` matches source commit `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`. The user-facing compatibility record contradicts its own rules: `docs/dev/version-compatibility/README.md:81-86` requires every `possibly unchanged` or `changed` compatibility point to receive a real Codex/API test before acceptance. The upgrade report nevertheless says live tests are complete and the upgrade is approved (`reports/20260709-codex-v0.144.0.md:3,152-154`) while its itemized table at lines 72-95 leaves numerous changed/possibly-unchanged points as `Plan`, `not triggered`, or otherwise unverified (agent-facing API, history/compact/fork/resume, deferred tools, UI phase, web search, reasoning, model switches, and multi-agent). The report also binds its Rosetta side to `419e6f9` at line 16, while current HEAD is `eb947426572ad7658c4b5ad19688fa68659a06b6` plus 74 tracked and 14 untracked implementation/test/doc paths.
- **Verification:** The compatibility checker passes, but it explicitly labels 12 contract groups only `Possibly unchanged`; it does not replace the required live matrix. Current `git rev-parse HEAD`, `git status`, and report lines were compared directly.
- **Finding F-03:** The release ledger makes an approval claim unsupported by its itemized evidence and does not identify the Rosetta revision containing the implemented fixes. This can allow a compatibility release to be accepted while mandatory real scenarios remain unverified and makes later reproduction impossible. Recommended direction: either execute and record every triggered point against an exact clean Rosetta commit, or mark the status/decision pending and clearly separate supported, tested, unverified, and unsupported points. Do not approve until the repository's explicit gate is satisfied.
- **Resolution:** **Resolved as a ledger correction.** The upgrade report, compatibility README, and compatibility-point ledger now say `Pending / not approved`; they record the audited dirty snapshot at HEAD `eb947426…` (74 tracked modified, 14 untracked, tracked diff 3,358 additions / 862 deletions at audit time), distinguish `tested`, `unverified / not triggered`, and `unsupported` item by item, preserve the controlled DeepSeek evidence without treating it as native GPT evidence, and require a future exact clean commit plus all triggered live gates before approval. No release tag, publisher, PyPI, Docker publication, or business behavior was changed.
- **Gaps / Assumptions:** The external trace/session cited by the report was not replayed. The finding does not dispute the one controlled DeepSeek run; it concerns the uncovered triggered points and stale revision identity.

## CI, release, container, and operations

- **Status:** Reviewed.
- **Severity:** Track as Debt.
- **Scope:** `.github/workflows/ci.yml`, `Makefile`, Dockerfile/entrypoint/compose, manual release docs, version check script.
- **Focus:** Minimum/current Python, clean-wheel source, publishing authority, tag contract, rollback, and provenance.
- **Evidence:** CI runs lint/type/full non-integration tests and clean-wheel smoke on Python 3.10/3.13. Docker builds only the current checkout wheel and runs as an unprivileged user after ownership setup. PyPI/Docker publishing targets are fail-closed, and the manual tag validator passes for `v0.144.0.r0`. The repository explicitly accepts a manual GitHub Release flow without checksums, signing, SBOM, clean-commit/tag-target enforcement, or a tag-triggered workflow.
- **Verification:** `make check-release-version RELEASE_TAG=v0.144.0.r0` passed. A wheel built from the current checkout installed successfully in clean Python 3.10 and 3.13 environments; core/Google converter imports, gateway import, and `codex-rosetta-gateway --version` passed in both. Docker daemon build, remote CI, and release publication were not run.
- **Existing debt:** Manual release provenance remains a tracked supply-chain limitation with project/release maintainer ownership; revisit before wider distribution or after the Draft profile defines a stronger baseline. The compatibility approval mismatch is reported separately as F-03 because it violates an existing mandatory gate, not merely an undefined provenance control.
- **Gaps / Assumptions:** GitHub branch protection, secret scopes, dependency vulnerability/license status, and actual release permissions were not inspected.

## Test portfolio and independent verification

- **Status:** Reviewed.
- **Severity:** Should Plan.
- **Scope:** Changed and adjacent tests across gateway/Admin, config, persistence, stream lifecycle, converter compatibility, release checks, and the complete non-integration suite.
- **Focus:** Behavioral assertions, negative paths, integration-boundary realism, skipped tests, and whether passing automation supports each claim.
- **Evidence:** The suite has strong negative coverage for auth/CORS/config rollback, state scoping, stream terminal behavior, redaction, Responses conversion, dual-app configuration ownership, and model-discovery cleanup. The compatibility ledger now treats its partial live run as partial evidence and keeps mandatory live gaps pending; ordinary unit tests are not used to close that evidence gap.
- **Verification:** `conda run -n llm-rosetta make lint` passed (Ruff check, 276-file format check, and ty). `conda run -n llm-rosetta make test` collected 2,448 tests and finished `2444 passed, 4 skipped, 9 warnings` on Python 3.14.6. The focused repair set finished `48 passed`. `conda run -n llm-rosetta make check-codex-compat` passed against Codex source `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`, while still reporting 12 groups as `Possibly unchanged`. `conda run -n llm-rosetta make check-release-version RELEASE_TAG=v0.144.0.r0` passed. Current-checkout wheel smoke passed in clean Python 3.10 and 3.13 environments. `git diff --check` and `codegraph sync` passed.
- **Skipped / not run:** Integration tests requiring real API keys, agentabi, the complete triggered live Codex matrix, native GPT route, compact/resume/fork/restart, multi-agent/plugin/MCP/web-search/UI phase, browser UI, Docker daemon build, GitHub Actions, release publication, load/capacity, recovery drills, and dependency vulnerability/license scans.
- **Gaps / Assumptions:** Remote CI and external trace claims remain manual evidence. The compatibility status remains pending despite green local automation and wheel smoke.

## Simplification pass

- F-01 is a duplicated-state-owner problem. The smallest simplification is to remove request-path dependence on module `_config` and reuse the already-present `app.gateway_config`; no new service or registry is needed.
- F-02 should reuse the established `async with AsyncClient(...)` pattern already present in `gateway/web_search.py` and Admin observability routes; no cleanup helper is justified.
- F-03 is a reporting-state correction, not a request for more compatibility branches. Keep one itemized ledger, bind it to one exact revision, and downgrade the approval until the existing gate is met.
- No deletion or broad refactor is recommended for `GatewayStateScope`, `SecretRedactor`, config CAS/activation preparation, or stream telemetry ownership; these are coherent single-owner boundaries with meaningful regression coverage.

## Consolidated findings

### F-01 — Module-global gateway config crosses app instances — Resolved

- **Severity:** Must Fix.
- **Trigger:** Construct two `App` objects with distinct `GatewayConfig` values in the same process, then serve a request through the first app after the second factory call.
- **Impact:** Wrong routing table, provider endpoint/credentials, web-search policy, model catalog, and Admin test/config behavior can be selected. Blast radius is every earlier app instance in the process.
- **Evidence strength:** Reproduced on current code; response from app A names app B's model set.
- **Fix direction:** Use `request.app.gateway_config` throughout request handlers and Admin helpers; add dual-app regression.
- **Repair verification:** The module global is gone; all request/config helper reads and hot reload are app-owned. Dual-app regression covers routing, credentials, web search, both model catalogs, embeddings, Admin helpers, and isolated activation.

### F-02 — Upstream model-discovery client is not closed on failure — Resolved

- **Severity:** Should Plan.
- **Trigger:** `AsyncClient.get()` raises (connection error, timeout, or unexpected response failure) before line 1046.
- **Impact:** Repeated authenticated Admin probes can retain client/pool resources and degrade the process.
- **Evidence strength:** Reproduced with a current-code fake client; `closed=False` after the handler returns its error response.
- **Fix direction:** Use the existing async-context-manager pattern and test the raising path.
- **Repair verification:** Async context management closes exactly once after success, connection failure, parse failure, and cancellation; cancellation propagates.

### F-03 — Compatibility approval contradicts mandatory live-test and revision gates — Resolved

- **Severity:** Must Fix.
- **Trigger:** Treat the current upgrade report/status as release approval.
- **Impact:** A release can claim Codex 0.144.0 compatibility without the repository-required real tests for numerous changed/possibly-unchanged points, and without an exact Rosetta revision containing the fixes.
- **Evidence strength:** Direct contradiction among versioned source-of-truth documents plus current git state.
- **Fix direction:** Mark approval pending until all triggered scenarios are recorded against an exact clean revision, or execute the complete matrix and update the report atomically.
- **Repair verification:** All three compatibility sources now agree on pending/not approved, preserve controlled third-party evidence, itemize unsupported/unverified paths, and bind the audit-time dirty snapshot without claiming it is a release revision.

## Audit limitations and human review

- The project audit profile remains Draft and ownerless; legal/privacy, threat model, SLO, release provenance, CI-secret, incident-response, dependency, and SBOM/signing baselines need owner approval.
- The repair pass changed only the ownership and cleanup paths required by F-01/F-02 plus the F-03 evidence ledger; no new business semantics were introduced.
- Real provider/model behavior, browser behavior, Docker/remote deployment, and hosted service configuration were not exercised.
- Existing debts D-01 (web-search total call/time/cost budget) and D-02 (manual release provenance) remain recorded in the previous audit; they were not reclassified as new findings here.
