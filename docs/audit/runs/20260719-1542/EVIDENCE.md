# Audit Run Evidence

Run: 20260719-1542
Repository head/environment: `0caa7a1308452100e553c9e1e3411b9a9f0a0746`, `main`, macOS, Python 3.14.6, conda environment `llm-rosetta`
Audit constraint: no real Codex/provider/API calls; no production deployment or external runtime evidence

## Evidence Index

| Unit | Status | Severity | Coverage IDs | Finding IDs | Evidence summary | Gaps |
| --- | --- | --- | --- | --- | --- | --- |
| UNIT-001 repository/profile/map | Reviewed | No Action | GOV-01, MAP-01 | None | Current head, branch, tags, repository layout, old audit assets, and approved profile reconciled | Historical reports are not trusted as current coverage |
| UNIT-002 auth/admin/principal boundary | Reviewed | No Action | AUTH-01, AUTH-02, SCN-01, SCN-02, SCN-08 | None | AuthState, Admin session, CORS, key validation, principal scoping, and admin mutation tests passed | No deployed network probe; public exposure excluded |
| UNIT-003 Codex routing/conversion/stream/tool path | Reviewed | No Action | CODEX-01, CODEX-02, STREAM-01, TOOL-01, SCN-03, SCN-04, SCN-05, SCN-06 | None | Deterministic source/contract gates and focused/full tests passed | Real Codex/provider/tool trajectories prohibited |
| UNIT-004 persistence/redaction/retention | Reviewed | Must Fix / Should Plan | DATA-01, DATA-02, DATA-03, SCN-02, SCN-05, SCN-06, SCN-07 | AUD-001, AUD-002 | Principal-scoped encrypted mappings, file modes, token redaction, caps and TTL verified; internal migrations and compaction table lack approved boundary/cap | No restore/production storage exercise |
| UNIT-005 release/CI/Docker/supply chain | Reviewed | Should Plan / Debt | REL-01, REL-02, SCN-10 | AUD-004 | Lint/test/build/contract/tag gates pass; manual release is disabled for automated push; mutable action/base/dependency inputs remain | External GitHub settings, signatures, SBOM, provenance unavailable |
| UNIT-006 agent/live-test control plane | Partial | Should Plan | AGENT-01, SCN-11 | AUD-003 | Deterministic tests are separated from integration/live harnesses; live scripts can invoke Codex/provider flows without an in-harness approval gate | No live execution by policy; no trajectory evidence |
| UNIT-007 provider preset boundary and optional sidecars | Partial | Should Plan / Evidence Gap | PROVIDER-01, SIDE-01, SCN-09 | AUD-005 | Bundled provider/shim and optional sidecar surfaces mapped; generic custom/unknown provider fallback remains exposed | Provider endpoint behavior and sidecar runtime unavailable |

---

## UNIT-001 — Repository, profile, and baseline reconciliation

- Scope reason: `reset`; durable system map/coverage/findings ledgers were absent and the existing profile was Draft and compatibility-focused.
- Status: Reviewed
- Outcome: No Action for reconciliation; baseline reset recorded.
- Coverage IDs: GOV-01, MAP-01
- Finding IDs: None

### Scope and boundaries

- Current branch/head: `main` at `0caa7a1308452100e553c9e1e3411b9a9f0a0746`; `origin/main` at `81fc00a62c13b7e309289a5b355ae478495240ab`; local branch ahead by four commits.
- Worktree: clean outside ignored `.agent-work` audit artifacts; no user code changes were reset or overwritten.
- Tags: current package tag `v0.144.0.r0`; recent Codex alpha.23 compatibility commits are after the old audit snapshots.
- Existing audit assets: many historical `docs/audit/20260709-*` and `20260711-*` `FULL.md`/`REPORT.md` snapshots plus the former Draft profile; no trusted `SYSTEM-MAP.md`, `COVERAGE.md`, or `FINDINGS.md` before this run.
- Generated/vendor exclusions: `src/codex_rosetta/_vendor/**` and `gateway/resources/**` are excluded from type/complexity checks by project configuration; vendor files are not edited.

### Hypotheses and disposition

| Candidate | Evidence sought | Disposition | Evidence/reason |
| --- | --- | --- | --- |
| Prior report can be reused as current baseline | current head, ledger presence, changed contract surface | Falsified | old reports predate current alpha.23/compaction/deferred-tool/auth changes and no durable freshness graph exists |
| Repository is currently deployed | local deployment/config/runtime evidence | Falsified for supplied scope | user confirmed not yet online; only local/LAN commitment |
| Profile choices materially changed prioritization | user decisions | Confirmed | public exposure, one Admin, multi-key, Codex-only downstream, preset upstream, manual release, no HA/DR guarantee, no audit live calls |

### Evidence inspected

- Code/configuration: repository tree, `AGENTS.md`, `pyproject.toml`, `Makefile`, `docker/`, `src/`, `tests/`.
- Tests/scanners: full non-integration suite, lint/type/complexity, focused critical suites.
- Build/release/provenance: local workflows, manual-release Makefile targets, Dockerfile, version script, Codex contract script.
- Docs/profile/history: existing profile, architecture docs, version-compatibility docs, recent git history.

### Commands and results

| Command/check | Result | Environment/head | Limitation |
| --- | --- | --- | --- |
| `git status --short --branch` | `main...origin/main [ahead 4]`; no non-audit worktree changes | current head | ignored audit files are local |
| `git log -20` / tags | current alpha.23/compaction/live-agent changes present; `v0.144.0.r0` tag | current checkout | history is not runtime proof |
| `codegraph explore ...` | current gateway/auth/persistence/routing symbols and call paths mapped | `.codegraph` current index | dynamic provider/runtime behavior still needs execution |
| `find .agent-work/audit ...` | historical snapshot reports only; durable ledgers absent before this run | current checkout | old reports not inherited |

### Findings or No Action rationale

- No finding is assigned merely because the project is pre-release or not deployed. Those facts change evidence status and scope, not code correctness.

### Coverage update

- Previous status: Unknown / not trustworthy.
- New status: Fresh for repository/profile/map reconciliation at current head.
- Evidence refs: this unit, `PROFILE.md`, `SYSTEM-MAP.md`, `SCOPE.md`.
- Dependencies/invalidation triggers: any profile decision, deployment, Codex contract, auth/state architecture, or ledger corruption resets broad conclusions.
- Next rotation reason: re-run reconciliation after first internal deployment or material Codex/runtime transition.

---

## UNIT-002 — Gateway authentication, Admin, and principal isolation

- Scope reason: `always-on critical`; supported system has one Admin and multiple API-key principals.
- Status: Reviewed
- Outcome: No Action under available evidence.
- Coverage IDs: AUTH-01, AUTH-02, SCN-01, SCN-02, SCN-08
- Finding IDs: None

### Scope and boundaries

- `create_app` registers `/v1/responses`, `/v1/models`, `/health*`, and Admin routes; auth hooks run before body/request processing.
- `/health` is public; the full `/v1` namespace is protected by API-key auth; Admin API uses separate Admin token/session checks.
- `AuthState` stores raw-key lookup only in memory, maps each key to a stable configured principal ID, and reserves `__admin_internal__`.
- Admin session secret is durable beside configured `config.jsonc` or ephemeral for programmatic app creation; files are opened/created owner-only.
- Config validation requires non-empty Admin password, at least one API key, unique IDs and keys, and rejects unresolved secret placeholders.

### Hypotheses and disposition

| Candidate | Evidence sought | Disposition | Evidence/reason |
| --- | --- | --- | --- |
| Missing/unknown `/v1` route bypasses auth | auth path predicate and route hook ordering | Falsified | `create_auth_hook` protects `/v1` and `/v1/`; hook runs before body decode/JSON parsing |
| API-key labels are used as state ownership | context vars, state scope, SQL predicates | Falsified | state uses stable configured `id`, not label/raw key; persistence tests cover principal scope |
| Admin and API-key auth are conflated | separate auth branches/session handling | Falsified | Admin paths use `x-admin-token`/session; `/v1` uses Bearer key; internal token is reserved |
| Multiple keys can share persistent mapping state | mapping primary key/AAD and tests | Not reproduced | mapping key and AAD include `principal_id`; focused persistence/auth suites pass |

### Evidence inspected

- Code/configuration: `gateway/app.py`, `gateway/auth.py`, `gateway/admin_session.py`, `gateway/config.py`, `gateway/state_scope.py`, `observability/persistence.py`, Admin auth/config/key routes.
- Tests/scanners: `tests/gateway/test_auth.py`, `test_admin_auth_routes.py`, `test_admin_session.py`, `test_admin_config_routes.py`, `test_persistence_sqlite.py`, `test_request_state_lifecycle.py`, `test_app_config_isolation.py`.
- Runtime evidence: no external runtime; deterministic in-process HTTP/test fixtures only.

### Commands and results

| Command/check | Result | Environment/head | Limitation |
| --- | --- | --- | --- |
| `conda run -n llm-rosetta pytest -q ...critical gateway suites...` | `533 passed` | Python 3.14.6/current head | fixture/local transport only |
| `conda run -n llm-rosetta make test` | full non-integration suite `3425 passed, 5 skipped, 11 warnings` | Python 3.14.6/current head | excludes real integration/live suites |
| source trace of `create_app`/`create_auth_hook`/`GatewayStateScope` | auth and principal path coherent | current source | no deployed reverse-proxy behavior |

### Findings or No Action rationale

- Current auth/principal design satisfies the approved local/LAN invariant based on source and deterministic tests. No claim is made about public deployment account security or reverse-proxy/TLS configuration.

### Coverage update

- Previous status: Unknown.
- New status: Fresh for source + deterministic auth/admin/principal evidence; live/network exposure remains Unknown.
- Evidence refs: UNIT-002; `tests/gateway/test_auth.py`, `test_admin_auth_routes.py`, `test_admin_session.py`, `test_persistence_sqlite.py`.
- Dependencies/invalidation triggers: auth/config/session/state-scope/persistence key changes; first deployment; public exposure claim.
- Next rotation reason: first internal deployment and after any auth/key/session/schema change.

---

## UNIT-003 — Codex routing, conversion, streaming, tool adaptation, and compaction

- Scope reason: `always-on critical` and `changed/high-churn`; this is the supported downstream workflow.
- Status: Reviewed
- Outcome: No Action for deterministic contract paths; live evidence gap recorded.
- Coverage IDs: CODEX-01, CODEX-02, STREAM-01, TOOL-01, SCN-03, SCN-04, SCN-05, SCN-06
- Finding IDs: None

### Scope and boundaries

- The public Gateway route exposes Codex Responses and model/auxiliary routes; Chat/Anthropic/Google are upstream target formats, not supported downstream client surfaces.
- `GatewayConfig.resolve` binds source API type, provider shim, upstream model, input modalities, tool profile, and runtime capabilities.
- `proxy.py` owns request conversion, model/window validation, tool profile/localization, persistent mapping injection, non-streaming response conversion, stream event generation, terminal telemetry and cleanup.
- `ConversionPipeline` owns source→IR, IR transforms, IR→target and response/stream conversion; transport remains caller/Gateway-owned.
- Codex compaction selects native passthrough or Rosetta summary mode, rehydrates owned tokens, and stores replacements under principal scope.

### Hypotheses and disposition

| Candidate | Evidence sought | Disposition | Evidence/reason |
| --- | --- | --- | --- |
| Codex route can silently resolve an unknown model/provider | model extraction, config resolve, error path | Not reproduced | focused proxy/config/downstream suites pass; no live provider evidence |
| Stream cancellation/EOF leaves resources or terminal state inconsistent | stream generators, instrumented wrapper, lifecycle tests | Not reproduced | stream EOF/finalization/telemetry suites pass |
| Tool localization loses exact call identity | tool adaptation, mapping persistence, replay tests | Not reproduced | code path and persistence tests pass; live tool trajectory unavailable |
| Compaction accepts invalid trigger or tool response | trigger/summary validators and tests | Not reproduced | compaction tests cover final trigger, empty/tool summary rejection |
| Current Codex contract changed from baseline | source contract check | Falsified for blocking changes | `make check-codex-compat` reports no changed blocking points; 11 points remain `Possibly unchanged` because extractor does not prove all types/defaults/serde behavior |

### Evidence inspected

- Code/configuration: `gateway/app.py`, `gateway/proxy.py`, `pipeline.py`, all four converters, `tool_adaptation.py`, `stream_phase_buffer.py`, `codex_compaction.py`, `local_mode.py`, catalog resources.
- Tests/scanners: converter request/response/stream suites; gateway proxy/stream/tool/local-mode/compaction/passthrough suites; `tests/live_agent/test_*configuration_contract.py` deterministic checks.
- Docs/contract: `docs/dev/version-compatibility/{README.md,rosetta-source-map.md,compatibility-points.md,upgrade-checklist.md}`, current Codex source contract JSON.

### Commands and results

| Command/check | Result | Environment/head | Limitation |
| --- | --- | --- | --- |
| `conda run -n llm-rosetta make check-codex-compat` | exit 0; source commit `655224ffae098a85efeddf8289171ff3bd2624d1`; no blocking changes | sibling source/current head | extractor marks several semantic rows `Possibly unchanged` |
| focused gateway/converter suites | included in `533 passed` | Python 3.14.6/current head | deterministic/fake upstream only |
| `conda run -n llm-rosetta make test` | `3425 passed, 5 skipped, 11 warnings` | Python 3.14.6/current head | no real Codex/provider calls |

### Findings or No Action rationale

- Deterministic current-source and test evidence supports the core route/conversion/stream invariants sampled. It does not establish model quality, real provider behavior, or live Codex trajectory success; those are explicitly Unknown.

### Coverage update

- Previous status: Unknown / invalidated old compatibility snapshots.
- New status: Fresh for sampled source/fixture contract paths; live model/provider behavior and uncovered semantic contract rows remain Unknown.
- Evidence refs: UNIT-003; command results; version-compatibility docs.
- Dependencies/invalidation triggers: Codex source/catalog/feature changes, proxy/converter/stream/tool/compaction changes, model preset changes.
- Next rotation reason: current source alpha.23 semantic rows marked `Possibly unchanged`, then developer-approved live matrix outside audit.

---

## UNIT-004 — Persistence, redaction, retention, and compaction state

- Scope reason: `always-on critical`; persisted prompt/tool state is crown-jewel data and state growth affects local/LAN reliability.
- Status: Reviewed
- Outcome: Must Fix / Should Plan.
- Coverage IDs: DATA-01, DATA-02, DATA-03, SCN-02, SCN-05, SCN-06, SCN-07
- Finding IDs: AUD-001, AUD-002

### Scope and boundaries

- SQLite database and sidecars are created with owner-only permissions and WAL mode; request logs and error dumps use retention caps.
- API-token values, Bearer values, and token-shaped JSON fields are redacted; non-token diagnostic content is retained by design.
- Tool-call mappings are AES-256-GCM protected, principal/provider/model/session/call-id scoped, AAD-bound, TTL-controlled, and row/session/principal/global byte/row quota-bounded.
- Codex compaction mappings store plaintext replacement summaries under principal+token hash and roll for seven days, but the storage method has no row/byte quota or max replacement length.
- Current source contains schema/file migrations for legacy JSONL/JSON, old request-log columns, plaintext/lossy mapping rows, and deprecated retention arguments.

### Hypotheses and disposition

| Candidate | Evidence sought | Disposition | Evidence/reason |
| --- | --- | --- | --- |
| Tool mappings can cross API-key principals | primary key/AAD/query predicates | Falsified for sampled path | principal is part of key/AAD and tests cover wrong-principal/key/tamper behavior |
| Token redaction is absent or broad enough to hide non-token data | redaction implementation/tests | Falsified for approved policy | exact token/Bearer/field redaction is implemented; non-token data deliberately preserved |
| Request/error/stream diagnostics are entirely unbounded | retention constants and prune paths | Partially falsified | request logs/error dumps/tool mappings have caps; stream trace has per-value truncation but no global file cap observed |
| Compaction mapping storage is quota-bounded | method/schema/capacity controls | Confirmed finding | `store_codex_compaction_mapping` accepts arbitrary `replacement_text` and only stores `replacement_bytes`; TTL is the only aggregate bound |
| Legacy migration layers are absent as approved | config/local/admin/persistence/pipeline inventory | Confirmed finding | multiple explicit legacy/backward-compat paths remain despite no Rosetta-version migration commitment |

### Evidence inspected

- Code/configuration: `observability/persistence.py`, `tool_mapping_crypto.py`, `redaction.py`, `retention.py`, `gateway/codex_compaction.py`, `gateway/config.py`, `gateway/local_mode.py`, Admin key routes, `pipeline.py`, converter compatibility aliases.
- Tests/scanners: `tests/gateway/test_persistence_sqlite.py`, `test_codex_compaction.py`, `tests/observability/test_retention.py`, `test_auth.py`, `test_request_state_lifecycle.py`.
- Runtime evidence: local SQLite/test fixtures only; no production DB, backup, restore, or external filesystem exercise.

### Commands and results

| Command/check | Result | Environment/head | Limitation |
| --- | --- | --- | --- |
| focused persistence/compaction/auth suites | pass within `533 passed` | Python 3.14.6/current head | no long-duration disk-growth run |
| source trace of `store_codex_compaction_mapping` | no row/byte quota or replacement-size validation; rolling TTL only | current source | exact provider summary size not live-tested |
| `rg -n -i 'legacy|migration|backward compat'` | explicit internal migration/alias inventory found | current source/tests/docs | protocol-level legacy compatibility must be separated from Rosetta-version migration |

### Findings or No Action rationale

- Encrypted tool-call mappings, principal isolation and token redaction are reasonable under the approved current policy.
- `AUD-002` is evidence-backed because the supported compaction path retains plaintext summary material with a seven-day rolling TTL but no quota boundary comparable to other durable stores.
- `AUD-001` is evidence-backed because internal config/state/API migration paths remain and are explicitly called out as legacy/backward-compatible, conflicting with the approved prelaunch policy.

### Coverage update

- Previous status: Unknown.
- New status: Fresh for sampled SQLite/crypto/redaction/capacity paths; restore and long-duration disk behavior Unknown; legacy-removal scope remains Open.
- Evidence refs: UNIT-004, AUD-001, AUD-002.
- Dependencies/invalidation triggers: schema/key/retention/compaction changes; new deployment/data; any remediation of either finding.
- Next rotation reason: targeted re-audit after accepted removal/quota control; backup/restore only if promised later.

---

## UNIT-005 — Release, CI, Docker, and build provenance

- Scope reason: `always-on release control`; project promises manual release only and is pre-release.
- Status: Reviewed
- Outcome: Should Plan / Track as Debt.
- Coverage IDs: REL-01, REL-02, SCN-10
- Finding IDs: AUD-004

### Scope and boundaries

- `make push-package` and `push-docker` are deliberately disabled; manual GitHub UI release is the intended publication path.
- `make check-release-version --tag v0.144.0.r0` passed and the current package source version is `0.144.0.r0` (wheel metadata normalizes to `0.144.0.post0`).
- CI runs lint/test and wheel install smoke on Python 3.14.6; Docker safety checks `.dockerignore` secret patterns.
- SDK compatibility monitor is scheduled/manual and has `contents: read`, `issues: write`; it installs latest SDKs rather than a lockfile.
- Workflows use mutable major action tags; Docker uses `python:3.14.6-alpine` tag; project has no lockfile, signing, SBOM, or provenance attestation control.

### Hypotheses and disposition

| Candidate | Evidence sought | Disposition | Evidence/reason |
| --- | --- | --- | --- |
| Automated workflow can publish package/image | Makefile/workflow permissions | Falsified for checked-in targets | publish targets explicitly fail; no publish workflow found |
| Release tag/version mismatch bypasses manual gate | version script and command | Not reproduced | `check_release_version.py --tag v0.144.0.r0` passed |
| Artifact provenance is immutable and reproducible | action/base/dependency pins, signing/SBOM | Confirmed debt | mutable tags/latest dependency resolution and no attestation/signature controls |

### Evidence inspected

- Code/configuration: `pyproject.toml`, `Makefile`, `.github/workflows/ci.yml`, `docker-safety.yml`, `sdk-compatibility.yml`, `docker/Dockerfile`, `docker/docker-compose.yaml`, version/release scripts.
- Tests/scanners: lint, type, complexity, full test, build, release-tag check, `git diff --check`.

### Commands and results

| Command/check | Result | Environment/head | Limitation |
| --- | --- | --- | --- |
| `conda run -n llm-rosetta make lint` | pass: Ruff, format, ty, complexipy | Python 3.14.6/current head | no external CI runner |
| `conda run -n llm-rosetta make test` | pass: `3425 passed, 5 skipped, 11 warnings` | Python 3.14.6/current head | non-integration only |
| `conda run -n llm-rosetta python -m build --wheel` | pass: `codex_rosetta-0.144.0.post0-py3-none-any.whl` | local build/current head | used direct build because Makefile cleanup scans the entire historical audit tree and did not complete |
| `conda run -n llm-rosetta python scripts/check_release_version.py --tag v0.144.0.r0` | pass | current head | no GitHub publication |
| `git diff --check` | pass | current worktree | ignored audit artifacts not in diff |

### Findings or No Action rationale

- Manual release-only behavior is coherent and no automated push was attempted.
- `AUD-004` is retained as bounded supply-chain/release debt: mutable action/base/dependency inputs and absent provenance/signing are not a current release automation bypass, but they weaken artifact integrity before any broader release/security claim.

### Coverage update

- Previous status: Unknown.
- New status: Fresh for local deterministic release gates; Stale/Unknown for remote GitHub permissions, immutable pinning, signing/SBOM/provenance and registry state.
- Evidence refs: UNIT-005, AUD-004.
- Dependencies/invalidation triggers: workflow/Docker/dependency/release changes; any public release or production deployment.
- Next rotation reason: before first public/internal release with stronger supply-chain claim.

---

## UNIT-006 — Agent and live-test control plane

- Scope reason: `profile gap` and `always-on agent control`; development live tests require developer approval and audit must not make real calls.
- Status: Partial
- Outcome: Should Plan.
- Coverage IDs: AGENT-01, SCN-11
- Finding IDs: AUD-003

### Scope and boundaries

- `make test` excludes `tests/integration`; deterministic `tests/live_agent/test_*` contract/fixture tests run without real provider calls.
- Real live scripts explicitly read configured credentials, start local Gateway/Codex processes, and can call provider/model endpoints.
- `tests/live_agent/context_compaction/run_live.py` builds isolated config with `sandbox_mode = "danger-full-access"` and `approval_policy = "never"`; this is intended for an explicitly invoked isolated live run, but the script itself has no developer confirmation gate.
- `scripts/run_gateway_integration.sh` defaults to a localhost Gateway, `API_KEY=test`, and a model/SDK matrix; it does not require an explicit opt-in flag before invoking the child scripts.

### Hypotheses and disposition

| Candidate | Evidence sought | Disposition | Evidence/reason |
| --- | --- | --- | --- |
| Ordinary audit/test command invokes real provider calls | Makefile/test collection | Falsified for executed commands | `make test` excludes integration; only deterministic suites were run |
| Live harness requires explicit developer approval inside the harness | scripts/flags/confirmation | Confirmed finding | direct scripts can run real Codex/provider flows; no approval/opt-in gate is enforced by code |
| Live credentials are copied into repository artifacts | live README/prepare scripts | Partially falsified | scripts use isolated ignored run roots and document credential-free artifacts; no live run performed to verify all paths |

### Evidence inspected

- Code/configuration: `scripts/run_gateway_integration.sh`, `tests/live_agent/*/run_live.py`, `prepare_run.py`, `tests/integration/*`, `docs/dev/agent-tool-testing.md`, `tests/live_agent/runtime-contract.json`, repository instructions.
- Tests/scanners: deterministic live-agent configuration/fixture tests included in the full suite.
- Runtime evidence: deliberately none; real calls prohibited by profile.

### Commands and results

| Command/check | Result | Environment/head | Limitation |
| --- | --- | --- | --- |
| `make test` collection/execution | deterministic suite pass; integration excluded | Python 3.14.6/current head | no live trajectory |
| source trace of live scripts | credentials/network paths and no in-harness confirmation identified | current source | no actual credential use |

### Findings or No Action rationale

- The current audit complied with the no-live-call policy. The control gap is not that live tests exist; it is that the approved developer-approval rule is not mechanically fail-closed in the live runners.

### Coverage update

- Previous status: Unknown.
- New status: Fresh for deterministic separation and harness source review; live trajectories, provider choice, costs, and transcript behavior remain Unknown.
- Evidence refs: UNIT-006, AUD-003.
- Dependencies/invalidation triggers: harness, credentials, approval policy, model/provider defaults, agent permissions, or live artifact changes.
- Next rotation reason: before any live test expansion or autonomous agent execution.

---

## UNIT-007 — Provider preset boundary and optional sidecars

- Scope reason: `always-on route boundary` plus rotating optional feature slice.
- Status: Partial
- Outcome: Should Plan / Evidence Gap.
- Coverage IDs: PROVIDER-01, SIDE-01, SCN-09
- Finding IDs: AUD-005

### Scope and boundaries

- Bundled registry/shims cover known API standards and multiple provider identities; `GatewayConfig` resolves configured provider/shim/API type.
- `build_provider_info` intentionally falls back for unknown/custom provider types to Bearer auth and a generic `{base_url}/` URL template.
- Admin UI exposes a `Custom` vendor and custom variants for bundled providers.
- User-approved scope says supported upstreams are providers from the preset list; arbitrary custom/unknown upstreams are not part of the supported commitment.
- Optional web-run/search/image surfaces have separate local/LAN and external endpoint boundaries; no live sidecar/provider call was made.

### Hypotheses and disposition

| Candidate | Evidence sought | Disposition | Evidence/reason |
| --- | --- | --- | --- |
| Unknown provider types are rejected | provider factory/config validation | Falsified | unknown types intentionally use generic Bearer/URL fallback |
| Admin UI only exposes preset providers | UI registry/vendor list | Falsified | explicit `Custom` vendor and custom variants exist |
| Optional sidecars are covered by normal unit tests | test/source inventory | Evidence gap | source and deterministic tests exist, but no live sidecar/network behavior |

### Evidence inspected

- Code/configuration: `gateway/providers.py`, `gateway/config.py`, shim registry/YAML, `gateway/admin/admin.html`, web-run/search/image modules and Compose profile.
- Tests/scanners: provider/config/admin tests included in full and focused suites.

### Commands and results

| Command/check | Result | Environment/head | Limitation |
| --- | --- | --- | --- |
| `rg` provider/custom inventory | custom/unknown fallback and UI surface confirmed | current source | product intent does not prove runtime use |
| focused provider/config/admin suites | pass within `533 passed` | Python 3.14.6/current head | no external endpoint call |

### Findings or No Action rationale

- `AUD-005` records a supported-boundary mismatch, not an SSRF claim: the trusted Admin can configure arbitrary/custom endpoints even though the approved product profile promises only preset upstream providers. The exact treatment of custom base URLs for a preset provider should be made explicit before release.

### Coverage update

- Previous status: Unknown.
- New status: Fresh for local provider/config source and deterministic validation; external provider/sidecar behavior remains Unknown.
- Evidence refs: UNIT-007, AUD-005.
- Dependencies/invalidation triggers: provider/shim registry, Admin UI/config schema, provider URL validation, sidecar changes, first deployment.
- Next rotation reason: decide/encode preset-only boundary; then run focused re-audit.
