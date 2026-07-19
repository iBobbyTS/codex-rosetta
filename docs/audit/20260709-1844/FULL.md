# Codex-Rosetta Full-System Audit Ledger

Audit started: 2026-07-09 18:44 America/Edmonton
Audit remediation completed: 2026-07-09 20:40 America/Edmonton
Profile: `.agent-work/audit/PROFILE.md` (`Draft`)
Scope adjustment: the profile's Codex-compatibility coverage was treated as a minimum. This requested full-system pass also sampled generic converters, gateway/Admin security, persistence/privacy, release/build, supply chain, documentation, and agent-facing repository knowledge.

| Area | Status | Severity | Files | Notes |
| --- | --- | --- | --- | --- |
| Repository reality and final diff | Reviewed | No Action | `git status`; `git diff origin/master`; `_vendor/**` | 64 tracked and 12 untracked implementation/doc/test files remain uncommitted; final diff checks pass; `_vendor/**` is unchanged. |
| Public conversion API and routing | Reviewed | No Action | `src/codex_rosetta/{__init__,auto_detect,pipeline,routing}.py`; converter suites | Representative request/response/stream paths and the complete non-integration suite pass. |
| Gateway authentication and defaults | Reviewed | No Action | `gateway/{auth,config,cli,app}.py`; Docker/example config; security docs | Admin password and at least one access key are mandatory; loopback and hidden credentials are defaults; generated credentials are random. |
| Streaming, tools, and scoped state | Reviewed | No Action | `gateway/{state_scope,proxy,tool_adaptation,stream_phase_buffer}.py`; SQLite mapping | Cross-turn state is scoped by stable principal/provider/model/conversation; request-local state is not persisted; scoped clears preserve other principals. |
| Admin UI and bounded operations | Reviewed | No Action | `gateway/admin/**` | Dynamic handlers/attributes use context encoding; login/test-task state is bounded; last gateway key cannot be deleted. |
| Persistence, observability, and privacy | Reviewed | No Action | `gateway/config.py`; `observability/{persistence,error_dump,redaction}.py`; stream trace | Secure permissions, atomic config CAS/backup, token-only redaction, and the established 10,000-entry count retention are implemented and tested. |
| Python contract, CI, wheel, and release | Reviewed | No Action | `pyproject.toml`; `Makefile`; `.github/workflows/ci.yml`; release script/docs | ty is clean, CI covers Python 3.10/3.13 and full tests, wheel smoke passes on 3.10/3.14, automated publish entrypoints are disabled, and manual release validation is documented. |
| Test determinism | Reviewed | No Action | `tests/test_pipeline_profile.py`; `.agent-work/debug/resolved/20260709-pipeline-profile-rounding-flake.md` | Independently rounded 0.01 ms profile values now use a derived absolute assertion tolerance; focused, stress, and full-suite verification pass. |
| Codex compatibility and repository knowledge | Reviewed | No Action | `docs/dev/version-compatibility/**`; compatibility script; bilingual docs | No changed contract group; English/Chinese security docs and developer release guidance are synchronized. |
| External/live validation | Needs Follow-up | Track as Debt | real providers; agentabi; browser UI | Not run because it requires provider credentials/running services or interactive browser validation. |

## Framing and assumptions

- Quality priorities: correctness and reliability first; then security/privacy, modifiability, operability, performance, and cost.
- Crown jewels: upstream and gateway API keys, Admin password/token, prompts/tool traffic, persisted request/error/stream data, Codex session/window identifiers, and compatibility contracts.
- Trust boundaries: downstream clients -> gateway; gateway -> configured provider/API URL; Admin client -> Admin endpoints; gateway -> local SQLite/JSONL/config files; optional web-search tool -> Tavily.
- The implemented principal scope treats each configured gateway access-key ID as an independent owner for cross-request state.
- Draft-profile unknowns remain: legal/privacy controls, SLOs, production topology, and artifact signing/SBOM policy. Diagnostic retention is explicitly count-only at 10,000 error dumps, but the profile is still `Draft`.
- `_vendor/**` was excluded from implementation changes and remains untouched.

## Finding remediation ledger

## Finding F-01: Public-by-default Admin and optional gateway authentication

- Original severity: Must Fix.
- Final status: Resolved.
- Implementation evidence:
  - `GatewayConfig` now requires a non-empty string `server.admin_password` and at least one validated `server.api_keys` entry. IDs and key values must be unique; unresolved environment placeholders and the reserved Admin principal are rejected.
  - Default host is `127.0.0.1`; `credential_visible` defaults to `False`.
  - CLI `init` creates random Admin and gateway credentials, writes owner-only config, and prints the generated secrets once.
  - Example config, Docker entrypoint/compose, README, and English/Chinese security documentation use the hardened contract.
  - The last gateway access key cannot be deleted.
  - Hot reload updates access-key principals/labels and rotates the Admin password-derived HMAC token; externally edited Admin credentials no longer remain stale until restart.
- Verification:
  - `tests/gateway/test_config.py`, `test_auth.py`, `test_admin_auth_routes.py`, `test_admin_key_routes.py`, and `test_admin_config_routes.py` pass.
  - CLI-init smoke confirmed loopback, hidden credentials, valid generated secrets, and mode `0600` before the final two local fixes; those paths were unchanged afterward.
- Remaining limitation: Admin uses one password-derived bearer token rather than role-separated read/write permissions. This is an accepted current architecture, not an open defect under the Draft profile.

## Finding F-02: Stored DOM XSS in Admin inline handlers

- Original severity: Must Fix.
- Final status: Resolved.
- Implementation evidence:
  - Dynamic text, HTML attributes, and JavaScript handler arguments use separate `esc()`, `escAttr()`, and `handlerArg()` contracts.
  - Handler arguments are JSON-string serialized and HTML-attribute encoded, preventing quotes, entities, and markup from crossing either parser boundary.
  - Dynamic handler construction was audited with a malicious provider/model/group/key payload.
- Verification: `tests/gateway/test_admin_page_routes.py::test_admin_dynamic_handlers_and_attributes_use_context_specific_encoding` and the full suite pass.
- Remaining limitation: the Admin remains a bundled HTML SPA with inline scripts, so a strict no-inline CSP would require a larger frontend extraction. The demonstrated stored-name injection path is closed.

## Finding F-03: Python 3.10 gateway import failure

- Original severity: Must Fix.
- Final status: Resolved.
- Implementation evidence:
  - Python 3.11-only `datetime.UTC` use was replaced with Python 3.10-compatible APIs.
  - CI matrices now exercise Python 3.10 and 3.13 for lint/tests and wheel smoke.
- Verification:
  - Final wheel `codex_rosetta-0.144.0.post0-py3-none-any.whl` built successfully.
  - Clean Python 3.10.20 and 3.14.6 virtual environments installed the wheel with declared dependencies, imported `codex_rosetta.gateway.app`, verified packaged `admin.html`, and returned `codex-rosetta-gateway 0.144.0.r0`.
  - An initial `--no-deps` smoke failed only because `typing_extensions` was intentionally not installed; the realistic dependency-resolving smoke then passed.

## Finding F-04: Cross-request state not isolated by authenticated principal

- Original severity: Must Fix.
- Final status: Resolved.
- Implementation evidence:
  - `GatewayStateScope` keys state by stable configured principal ID, provider, model, and conversation ID.
  - Requests with a client window ID receive persistent scoped state; requests without one receive a unique request-local, non-persistent scope.
  - Provider metadata, Codex tool localization, deferred tool search, and SQLite tool-call mappings use the same ownership boundary.
  - SQLite migrates legacy unscoped mappings by rebuilding the scoped table; unassignable legacy rows are not silently attributed to a principal.
  - Scoped `clear()` and `len()` operations affect only the current scope, while unscoped root cleanup remains available where intended.
- Verification:
  - Collision tests cover identical call/window IDs across principals in `test_provider_metadata_store.py`, `test_tool_adaptation.py`, `test_window_tool_search_store.py`, and `test_persistence_sqlite.py`.
  - Final focused security/state suite passed 139 tests; the full suite also passes.
- Remaining limitation: correct isolation depends on operators assigning stable unique IDs to access keys; config validation now enforces uniqueness.

## Finding F-05: Red type gate and incomplete CI behavior coverage

- Original severity: Must Fix.
- Final status: Resolved.
- Implementation evidence:
  - The 110 observed ty diagnostics were repaired without broad suppression.
  - `make lint` now runs Ruff check, Ruff format check, and `ty check`.
  - CI uses Python 3.10/3.13 and runs the complete non-integration suite rather than selected converter/type directories.
  - Wheel smoke installs and imports the packaged gateway/Admin resources.
- Verification:
  - Final `conda run -n llm-rosetta make lint`: all Ruff/format/ty checks pass; 272 files already formatted.
  - Final `conda run -n llm-rosetta make test`: 2,378 passed, 4 skipped, 28 warnings in 6.22 seconds on Python 3.14.6.
- Remaining limitation: GitHub Actions itself was not triggered in this local task; current workflow YAML and commands were locally validated.

## Finding F-06: Insecure local artifact permissions and token exposure in diagnostics

- Original severity: Must Fix.
- Final status: Resolved.
- Implementation evidence:
  - Config, lock, backup, SQLite database, WAL, and SHM are forced to mode `0600`; gateway-created data directories are mode `0700`.
  - `SecretRedactor` removes only configured Gateway/provider API token values, Bearer/Authorization tokens, explicit token/API-key fields, and the ephemeral internal Admin API token from error dumps and stream traces.
  - Ordinary request bodies, converted bodies, response text, prompts, passwords, secrets, client secrets, proxy passwords, and personal data are retained unless a concrete value also matches a configured API token.
  - Error dumps retain the established count-only policy of at most 10,000 records. No age or total-byte pruning was added; count pruning and manual clearing remove orphaned body blobs.
  - Runtime token sets are refreshed during config hot reload without collecting Admin passwords, client secrets, or proxy passwords.
- Verification: config-persistence, SQLite-permission/count-retention, error-dump, stream-trace, hot-reload, and redaction tests pass. Negative assertions confirm non-token password/secret/client-secret/proxy-password data remains unchanged.
- Remaining limitation: preserving non-token diagnostic data is the explicit product contract. File/directory permissions and Admin access control therefore remain the privacy boundary for that content.

## Finding F-07: Non-atomic, lost-update-prone config writes

- Original severity: Should Plan.
- Final status: Resolved.
- Implementation evidence:
  - A stable companion lock serializes writers.
  - `ConfigDocument` carries the loaded byte digest; stale writes fail with `ConfigConflictError` rather than overwriting another process's update.
  - Writes use owner-only temporary files, `fsync`, atomic `os.replace`, directory `fsync`, and a private `.bak` copy.
  - Admin and CLI mutation routes load with `load_config_raw()` and retain the digest through mutation.
- Verification: `tests/gateway/test_config_persistence.py` covers private files/directories, backup, stale-write rejection, and tightening existing permissions.
- Remaining limitation: a successful save followed by runtime reload failure still returns explicit `saved: true, reloaded: false`; recovery uses the persisted config/backup and a later reload/restart.

## Finding F-08: Undocumented manual production release after workflow removal

- Original severity: Should Plan.
- Final status: Resolved for the chosen manual-release policy.
- Implementation evidence:
  - Automated PyPI and Docker publish entrypoints remain disabled intentionally.
  - `scripts/check_release_version.py` enforces the `{codex_version}.rN` release contract.
  - `docs/dev/releasing.md` documents creation of a GitHub Release through the GitHub web UI, required gates, version validation, and optional attachment of locally verified artifacts. It explicitly states that PyPI and Docker registries are not published.
  - Make release targets use the version validator; developer docs link the runbook.
- Verification: release-version tests pass and `0.144.0.r0` validates.
- Remaining limitation: no GitHub Release was created in this task; this was not required for the code/audit remediation.

## Finding F-09: Unbounded runtime state and unsafe development version restoration

- Original severity: Track as Debt.
- Final status: Resolved.
- Implementation evidence:
  - Login rate limiting ignores untrusted `X-Forwarded-For`, uses the direct peer, constant-time comparison, 10-minute inactive TTL, and a 4,096-entry cap.
  - When full, the oldest inactive/least-recent record is evicted. This is an accepted best-effort in-process limiter; the secure default exposes a single loopback peer unless operators deliberately proxy it.
  - `ResponsesPhaseBuffer` caps at 256 events and 1 MiB, then flushes and switches to unannotated pass-through rather than accumulating indefinitely.
  - Admin model tests cap active tasks at 4, retained task records at 128, individual execution at 120 seconds, and record age at 300 seconds.
  - `deploy-dev` uses a shell trap to restore the temporary source version after success or failure.
  - Markdown trailing whitespace in `origin/master..HEAD` was repaired.
- Verification: Admin auth/testing and phase-buffer limit tests pass; final diff checks pass.

## Finding F-10: Pipeline profile timing assertion was nondeterministic at sub-0.1 ms durations

- Original severity: Must Fix for reliable CI.
- Final status: Resolved.
- Evidence:
  - Main-thread final verification produced `1 failed, 2377 passed, 4 skipped` at `TestPipelineProfile::test_profile_populated_after_convert_request`, while the isolated test and a later full run passed.
  - A 20,000-iteration in-process repro failed at iteration 13,010: the four independently rounded parts summed to `0.05 ms`, while the independently rounded total was `0.04 ms`.
- Root cause: the test used relative-only tolerance after every duration had already been rounded to a 0.01 ms reporting quantum. At very small durations, accumulated quantization exceeded the 10% allowance even though runtime phase accounting was correct.
- Implementation evidence: request and response assertions now use tight 0.03 ms and 0.02 ms absolute tolerances derived from the maximum independent rounding error for four and two parts respectively.
- Verification:
  - `tests/test_pipeline_profile.py`: 5 passed.
  - 50,000-iteration request-profile stress: pass; smallest observed margin was approximately 0.02 ms.
  - Final `make lint`, `make test` (`2,378 passed, 4 skipped`), and Codex compatibility (`Changed: None`) pass.

## Reviewed areas with no action

### Public API, converters, shims, and routing

- Scope: auto-detection, `ConversionPipeline`, request/response/stream converters, shim transforms, reasoning mappings.
- Evidence: CodeGraph call-path inspection and 2,378 passing non-integration tests.
- Gap: no real provider/API/agentabi matrix was run.

### Explicit upstream header allowlist

- Scope: `src/codex_rosetta/gateway/headers.py` and HTTP transport header assembly.
- Evidence: downstream Authorization/cookies are not forwarded; only explicitly allowed protocol/request headers are copied. `tests/gateway/test_app_headers.py` passes.

### Admin tool catalog package/read-only contract

- Scope: bundled tool catalog, GET-only route, Admin view, package data.
- Evidence: catalog tests validate IDs/defaults/source commit, and final wheel smoke verifies packaged Admin resources.
- Gap: browser visual/accessibility testing was not run.

### Codex source compatibility contract

- Scope: `docs/dev/version-compatibility/**`, `scripts/check_codex_compatibility.py`, sibling `../openai-codex-src`.
- Verification: final `make check-codex-compat` passes at source commit `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`; Changed: None.
- Gap: twelve groups remain `Possibly unchanged` by design and retain their documented real Codex/API checks when triggered.

## Independent verification

- Repository/diff:
  - 64 tracked modifications and 12 untracked source/doc/test files remain; no commit, push, or PR was made.
  - `git diff --check origin/master` and `git diff --check` pass.
  - `.agent-work/audit/CURRENT.md` is absent.
  - `_vendor/**` has no modifications.
- Static/unit/compatibility:
  - `conda run -n llm-rosetta make lint`: pass (Ruff, format, ty).
  - Focused token-redaction/retention/hot-reload suite: 58 passed; the earlier broader security/config/state suite passed 139 tests.
  - `conda run -n llm-rosetta make test`: 2,378 passed, 4 skipped, 28 warnings.
  - `conda run -n llm-rosetta make check-codex-compat`: pass; Changed: None.
  - Pipeline profile quantization regression: focused 5 passed and 50,000-iteration stress passed.
- Packaging:
  - Wheel build: pass.
  - Fresh Python 3.10.20 and 3.14.6 dependency-resolving installs: gateway import, packaged Admin resource, and CLI version smoke all pass.
- Earlier focused validation retained as evidence because the relevant code was unchanged afterward:
  - Gateway suite: 330 passed.
  - High-risk regression combination: 580 passed.
  - CLI init security/permissions smoke and release-version `0.144.0.r0` validation passed.
- Not run:
  - Real provider/API integration tests.
  - `agentabi` same-format/cross-format/stream/tool-use matrix.
  - Interactive Admin browser visual/accessibility test.
  - Actual GitHub Actions run or manual GitHub UI Release creation.

## Simplification and maintainability pass

- One `GatewayStateScope` now owns the principal/provider/model/conversation boundary across memory and SQLite rather than duplicating partial keys.
- One token-scoped `SecretRedactor` serves error dumps, stream traces, configuration-derived API tokens, and hot reload rather than bespoke field stripping at each sink.
- One secure atomic config writer serves Admin and CLI mutations and centralizes permission, conflict, backup, and durability behavior.
- `make lint` now matches the required static policy, reducing local/CI drift.
- No broad converter rewrite or new dependency was introduced. Existing converter boundaries remain appropriate.

## Remaining human-review and follow-up decisions

1. Approve or refine `.agent-work/audit/PROFILE.md`; it remains `Draft`.
2. Decide whether a role-separated Admin permission model and strict CSP are required for the intended deployment topology.
3. Run real provider and `agentabi` validation before claiming live cross-provider/Codex agent-loop compatibility for a release.
4. Perform browser visual/accessibility smoke for the Admin UI before a user-facing UI release.
