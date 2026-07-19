# Codex-Rosetta Audit Ledger

Audit date: 2026-07-09 MDT
Repair verification date: 2026-07-09 MDT
Profile: `.agent-work/audit/PROFILE.md` (`Draft`)
Baseline: `eb94742` with a large uncommitted audit-fix worktree

| Area | Status | Severity | Files | Notes |
| --- | --- | --- | --- | --- |
| Repository and audit baseline | Reviewed | No Action | `AGENTS.md`, `.agent-work/audit/PROFILE.md`, working tree | Current repository state and the complete post-repair diff were rechecked. |
| Gateway auth and request routing | Reviewed | No Action | `src/codex_rosetta/gateway/{app,auth,proxy}.py`, `gateway/{tool_adaptation,state_scope,embeddings}.py` | F-01 and F-02 are repaired with lifecycle and public-route regressions. |
| Admin mutation and config durability | Reviewed | No Action | `src/codex_rosetta/gateway/admin/routes/*`, `gateway/{config,auth,stream_trace}.py` | F-03, F-04, and F-05 are repaired with failure-stage transaction tests. |
| Persistence and observability | Reviewed | No Action | `src/codex_rosetta/observability/*`, `gateway/app.py` | F-06 now finalizes stream telemetry exactly once at the terminal event. |
| Streaming and converter compatibility | Reviewed | Track as Debt | `gateway/stream_*`, `converters/openai_responses/*`, `gateway/web_search.py` | Compatibility gates pass; D-01 remains intentionally unmodified. |
| Release, CI, Docker, documentation | Reviewed | Track as Debt | `.github/workflows/ci.yml`, `Makefile`, `docker/*`, `docs/*` | Wheel smoke passes; D-02 and Draft-profile governance gaps remain. |
| Independent verification | Reviewed | No Action | focused tests, full suite, lint/type, wheel, Codex contract | All six repaired paths and repository-level gates are green. |

## Repository and audit baseline

- **Status:** Reviewed.
- **Severity:** No Action.
- **Scope:** Current branch/HEAD, complete worktree diff, project rules, Draft audit profile, and the earlier 2026-07-09 audit reports.
- **Focus:** Audit framing, stale-state risk, scope boundaries, preservation of user work, and confirmation that repairs are visible in the current tree.
- **Evidence:** HEAD remains `eb94742`. The current worktree has 74 tracked modified files and 14 untracked implementation/test/documentation files, with 3,358 additions and 862 deletions in the tracked diff. No `_vendor/**` modification is present. The extra files added during this repair are `tests/gateway/test_state_root_lifecycle.py` and `tests/gateway/test_stream_telemetry_lifecycle.py`; all prior user/audit work remains present.
- **Verification:** `git status --short`, `git diff --stat`, `git diff --numstat`, `git diff --check`, full audit ledger reread, and post-change CodeGraph exploration/sync.
- **Gaps / Assumptions:** Profile owner, legal/privacy baseline, SLOs, ASVS/security baseline, CI secret policy, artifact signing, and SBOM expectations remain unapproved. This pass assumes the gateway may be exposed beyond loopback and treats provider/client/Admin inputs as untrusted.

## Gateway auth and request routing

- **Status:** Reviewed.
- **Severity:** No Action after repair.
- **Scope:** `gateway/app.py::_proxy_handler`, `gateway/auth.py`, `gateway/state_scope.py`, `gateway/proxy.py::{close_resources,ProviderMetadataStore,WindowToolSearchStore,_resolve_state_stores}`, `gateway/tool_adaptation.py::CodexToolLocalizationStore`, embeddings dispatch, and state lifecycle tests.
- **Focus:** Authentication, principal propagation, cross-principal isolation, cross-instance cleanup, malformed input behavior, and bounded state.
- **Finding F-01 (Resolved):** The app now owns distinct metadata, localization, and window-tool root stores and passes them explicitly into both proxy paths. Each store has a root marker and root-only `clear_all()`; scoped views cannot clear shared state. `close_resources()` uses explicit `is not None` selection, accepts all three roots, and clears both discovered and deferred window tools. `run_gateway()` supplies every app-owned root at shutdown. Same-process cleanup/restart coverage confirms all three state families are empty and a new app receives different roots.
- **Finding F-02 (Resolved):** `_proxy_handler` and the independent embeddings entry point reject every parsed non-dict JSON value with HTTP 400 before model extraction. Route-level tests cover list, null, string, integer, boolean, and float payloads for both registered public POST routes (`/v1/responses` and `/v1/embeddings`).
- **Evidence:** `tests/gateway/test_state_root_lifecycle.py`, `tests/gateway/test_provider_metadata_store.py`, `tests/gateway/test_window_tool_search_store.py`, `tests/gateway/test_tool_adaptation.py`, and `tests/gateway/test_downstream_routes.py` pass. The combined six-finding focused run completed with 272 passed.
- **Gaps / Assumptions:** Process exit already frees memory; the repaired contract additionally supports documented cleanup and same-process app reuse. No multi-process claim is made.

## Admin mutation and config durability

- **Status:** Reviewed.
- **Severity:** No Action after repair.
- **Scope:** Config load/write/CAS/backup, `_prepare_gateway_activation`, `_commit_gateway_config`, `_activate_gateway_config`, auth rotation, stream-trace/persistence redactors, key CRUD, CORS state, and Admin config tests.
- **Focus:** Atomicity, validation, rollback, secret handling, authentication state, and hot reload.
- **Finding F-03 (Resolved):** Auth credentials/Admin token, stream-trace config/redactor, persistence redactor, and normalized CORS are fully constructed before `write_config()` begins. The activation callback performs assignment-only commits and swaps app/module config last. Reload uses the same prepare-then-commit path. Failure injection at auth, trace, persistence, and CORS preparation proves disk bytes, module `_config`, app config, auth, trace, persistence, and CORS all remain on the old state.
- **Finding F-04 (Resolved):** `validate_api_key_label()` is the single label contract: string, at most 128 characters, with empty strings allowed. `GatewayConfig._validate()` and Admin create/update routes both call it; dict/list/oversize candidates return 400 without modifying the config, while duplicate-key conflicts remain 409. Metrics and request-log persistence are best effort and log warnings rather than replacing proxy responses; a forced request-log failure leaves the successful response at 200.
- **Finding F-05 (Resolved):** `admin_cors_origins` must be a list of HTTP(S) origin strings without credentials, path, query, or fragment. Origins are canonicalized (case, trailing slash, default port), deduplicated, and normalized values are persisted. The app reads `app.admin_cors_origins` at request time, and config activation replaces its immutable tuple. Tests prove a substring origin is denied and an old-to-new reload immediately changes preflight from old=403/new=204.
- **Evidence:** `tests/gateway/test_admin_config_routes.py`, `tests/gateway/test_admin_key_routes.py`, `tests/gateway/test_config.py`, `tests/gateway/test_app_headers.py`, `tests/gateway/test_auth.py`, and `tests/gateway/test_stream_trace.py` pass, including four prepared-activation failure stages and normalized CORS persistence.
- **Gaps / Assumptions:** Admin routes remain intentionally privileged. CORS is defense in depth alongside the Admin token; no claim is made that CORS alone is authentication.

## Persistence and observability

- **Status:** Reviewed.
- **Severity:** No Action after repair.
- **Scope:** `SecretRedactor`, SQLite persistence, request log, metrics/provider health, stream profiles, trace JSONL, and `gateway/app.py` stream instrumentation.
- **Focus:** Token leakage, file permissions, retention, migration, stream lifecycle, error accounting, cancellation, disconnects, and observability failure isolation.
- **Finding F-06 (Resolved):** A streaming request now writes an initial request-log row after response construction but leaves metrics and `active_streams` open. `_InstrumentedStream` owns the terminal lifecycle: normal exhaustion records the response status (normally 200), generator failure records 502, and cancellation/early `aclose()` records 499. Source closure and finalization are guarded exactly once. Finalization records full duration, decrements the gauge, updates total/error/stream counters and provider health, and updates the existing request-log status/duration/error/profile. RequestLog and SQLite persistence now expose terminal-result update methods.
- **Evidence:** Route-level tests hold a stream open and observe `active_streams == 1` with zero completed requests, then verify completion returns the gauge to zero. Separate tests cover generator failure, repeated `aclose()` without double counting, explicit task cancellation, provider error health, in-memory request-log final state, and SQLite terminal-field persistence.
- **Verification:** Stream/observability adjacency run completed with 87 passed before the cancellation case was added; the final combined focused run (including cancellation) completed with 272 passed. Full suite also passes.
- **Gaps / Assumptions:** A real socket disconnect was not exercised over TCP; explicit `aclose()` covers the HTTP server's disconnect cleanup contract, and task cancellation covers cancellation propagation at the wrapped iterator boundary.

## Streaming and converter compatibility

- **Status:** Reviewed.
- **Severity:** Track as Debt only for D-01.
- **Scope:** OpenAI Responses converter/tool namespace handling, stream context, phase buffer, trace logging, direct passthrough, web-search bridge, tool localization, and Codex compatibility ledger/checker.
- **Focus:** SSE lifecycle ordering, terminal events, reasoning and opaque-item preservation, tool signals, phase inference, forward compatibility, capacity, and real Codex contract drift.
- **Evidence:** Phase buffering remains bounded and direct Responses traffic preserves raw SSE. The stream wrapper delegates chunks unchanged and closes the underlying generator. The Codex source contract reports no blocking changes at `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`.
- **Debt D-01 (Unchanged by request):** Hosted web search bounds rounds but not calls per round, total searches, total wall time, or Tavily cost. Owner: gateway/web-search maintainers. Revisit before broad untrusted/high-volume enablement or after quota/cost incidents. Suggested direction remains per-round/total-call and wall-time budgets with deterministic failed-tool results.
- **Verification:** Converter, phase, tool-adaptation, trace, web-search, full-suite, and compatibility checks pass.
- **Gaps / Assumptions:** No real provider, agentabi, WebSocket, Responses Lite, compact/resume/fork, or multi-client system test ran.

## Release, CI, Docker, and documentation

- **Status:** Reviewed.
- **Severity:** Track as Debt.
- **Scope:** Python matrix, Ruff/format/ty gates, clean-wheel smoke, Docker local-wheel contract, manual-release validator/runbook, bilingual security docs, compatibility ledger, and agent rules.
- **Focus:** Build integrity, version/tag consistency, rollback, provenance, deployment defaults, documentation drift, and agent-facing truth sources.
- **Evidence:** An isolated copy of the current dirty tree built `codex_rosetta-0.144.0.post0-py3-none-any.whl`, installed it into a clean venv with `--no-deps`, and imported core, gateway app, and observability symbols successfully. The shared worktree's `dist/build` directories were not touched.
- **Debt D-02 (Unchanged by request):** GitHub Release creation and optional local artifact attachment remain manual, with no checksum/provenance/signing/SBOM baseline and no CI-enforced clean-commit/tag-target gate. Owner: project/release maintainer. Revisit when distribution broadens or the owner approves a supply-chain baseline.
- **Gaps / Assumptions:** GitHub Actions, Docker daemon build, deploy, release creation, rollback, vulnerability/license scanning, and backup/restore were not run.

## Independent verification

- **Status:** Reviewed.
- **Severity:** No Action for F-01 through F-06; D-01 and D-02 remain tracked debt.
- **Commands and results:**
  - Focused six-finding regression set: `272 passed`.
  - `conda run -n llm-rosetta make lint`: passed; Ruff check, format check, and ty check green for 274 files.
  - `conda run -n llm-rosetta make test`: `2438 passed, 4 skipped, 9 warnings` on Python 3.14.6.
  - `conda run -n llm-rosetta make check-codex-compat`: passed; no blocking contract changes at `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`.
  - Isolated current-tree wheel build, clean-venv install, and import smoke: passed (`wheel smoke OK`).
  - `git diff --check`: passed.
  - `codegraph sync`: passed; 9 changed source files synchronized.
- **Skipped:** Real provider/API integration, agentabi, browser visual/accessibility, Docker daemon, remote CI, load/capacity, backup/restore, dependency/license scanning, and release/deploy exercises.
- **Human review required:** Approve the Draft audit profile's security/privacy/SLO/supply-chain fields and decide release provenance requirements. D-01 and D-02 were intentionally not implemented in this repair.
