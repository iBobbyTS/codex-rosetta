# Audit Coverage Ledger

Last updated: 2026-07-19
Repository head: `0caa7a1308452100e553c9e1e3411b9a9f0a0746`
Profile: `docs/audit-profile.md` (Approved)

## Status Definitions

- `Fresh`: required scope and evidence reviewed against the recorded state.
- `Stale`: confidence decayed without direct contradiction.
- `Invalidated`: a change/event directly breaks the previous proof assumptions.
- `Unknown`: no trustworthy evidence exists or evidence is intentionally unavailable.

## Area Coverage

| Coverage ID | Area/control | Criticality | Required depth/cadence | Last reviewed commit/date/environment | Scope reviewed | Evidence refs | Gaps | Dependencies | Invalidation triggers | Status | Next rotation reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GOV-01 | Profile, system boundary, owners, risk choices | Critical | baseline + material risk change | `0caa7a1` / 2026-07-19 / local | user decisions and repository boundary | UNIT-001, PROFILE | no legal/contract obligations supplied | all areas | profile/deployment/risk change | Fresh | first deployment or scope change |
| MAP-01 | Architecture, interfaces, trust/state/deployment/agent map | Critical | baseline + changed edges | `0caa7a1` / 2026-07-19 / local | core, gateway, persistence, release, agents | SYSTEM-MAP, UNIT-001 | runtime topology and external settings unavailable | all scenarios | architecture/runtime/agent change | Fresh | first internal deployment |
| AUTH-01 | `/v1` API-key auth and fail-closed path | Critical | always-on; every auth change | `0caa7a1` / 2026-07-19 / Python 3.14.6 | `create_app`, `AuthState`, auth hook, config validation | UNIT-002, auth tests | no reverse-proxy/live network probe | SCN-01/02/08 | auth/header/session/config change | Fresh | auth or deployment change |
| AUTH-02 | Single Admin session/CORS/config mutation | Critical | always-on; every Admin change | `0caa7a1` / 2026-07-19 / Python 3.14.6 | Admin auth/session, config/key/provider/model routes | UNIT-002, admin tests | browser/runtime deployment not exercised | SCN-08 | Admin/UI/CORS/config change | Fresh | first internal deployment |
| PROVIDER-01 | Preset provider/shim/model resolution | Critical | every provider/Codex update + rotation | `0caa7a1` / 2026-07-19 / local | registry, shims, config resolution, Admin UI | UNIT-003/007, provider/config tests | custom boundary decision pending; no external call | SCN-03/09 | provider/shim/config/UI change | Invalidated by AUD-005 | resolve provider identity/endpoint policy |
| CODEX-01 | Codex source contract extraction and catalog ownership | Critical | every supported Codex version | `0caa7a1` / 2026-07-19 / source checkout | source map, compatibility points, contract script, resources | UNIT-003, `make check-codex-compat` | 11 semantic rows are `Possibly unchanged`; no live gate | SCN-03/04/06 | Codex source/catalog/feature change | Fresh (partial semantic) | complete uncovered semantic extraction/manual review |
| CODEX-02 | Local-mode model/tool/compaction behavior | Critical | every Codex update; rotating | `0caa7a1` / 2026-07-19 / deterministic | `local_mode`, catalogs, compaction, auxiliary/tool projections | UNIT-003, local/compaction/tool tests | real Codex trajectory unavailable | SCN-04/05/06 | local-mode/catalog/compaction/tool change | Fresh (deterministic) | developer-approved live matrix outside audit |
| STREAM-01 | SSE conversion, phase buffer, cancellation/finalization | Critical | always-on; every stream change | `0caa7a1` / 2026-07-19 / deterministic | proxy generators, converter stream paths, telemetry cleanup | UNIT-003, stream tests | no real provider chunk timing | SCN-04 | converter/proxy/transport/stream change | Fresh (deterministic) | live provider stream evidence |
| TOOL-01 | Tool localization/deferred discovery and replay | Critical | every tool/Codex update | `0caa7a1` / 2026-07-19 / deterministic | tool adaptation, mappings, projection, replay | UNIT-003/004, tool tests | no live MCP/plugin trajectory | SCN-05 | tool schema/projection/persistence change | Fresh (deterministic) | live deferred-tool evidence |
| DATA-01 | SQLite file permissions, schema, request/error retention | High | baseline + persistence change | `0caa7a1` / 2026-07-19 / local | SQLite init, logs, error dumps, redaction, retention | UNIT-004, persistence/retention tests | no restore/production disk exercise | SCN-07 | schema/retention/logging change | Fresh (source/tests) | first deployment or retention change |
| DATA-02 | Encrypted tool mapping principal/AAD/quotas | Critical | always-on; every mapping/key change | `0caa7a1` / 2026-07-19 / local | crypto, SQL scopes, capacity and cleanup | UNIT-002/004, persistence tests | no long-run stress | SCN-02/05/07 | key/schema/scope/capacity change | Fresh (sampled) | targeted quota stress |
| DATA-03 | Codex compaction mapping retention/boundedness | Critical | every compaction change; pre-deploy gate | `0caa7a1` / 2026-07-19 / local | compaction table/store/TTL/replay | UNIT-004, AUD-002 | no aggregate quota; no live summary | SCN-06/07 | compaction/persistence change | Invalidated by AUD-002 | quota remediation/re-audit |
| REL-01 | Local lint/test/build/install smoke | High | every change/release | `0caa7a1` / 2026-07-19 / local | Makefile, pyproject, package build | UNIT-005 | Makefile clean scans historical tree; direct wheel build used | SCN-10 | build/toolchain change | Fresh (direct build) | improve cleanup path before release |
| REL-02 | Codex/release tag/manual publication gate | High | every supported Codex release | `0caa7a1` / 2026-07-19 / local | contract script, version script, disabled push targets | UNIT-003/005 | no GitHub publication/settings/provenance | SCN-10 | release/workflow/tag change | Fresh (local) | pre-release provenance decision |
| AGENT-01 | Deterministic-vs-live test separation and approval | High | every harness/agent change | `0caa7a1` / 2026-07-19 / local | Makefile, live scripts, runtime contract, docs | UNIT-006, AUD-003 | no live trajectory; no mechanical approval gate | SCN-11 | harness/credentials/agent permissions change | Invalidated by AUD-003 | add gate and re-audit |
| SUPPLY-01 | CI/action/base/dependency provenance | Medium | rotating; pre-public release | `0caa7a1` / 2026-07-19 / local | workflows, Dockerfile, pyproject, release docs | UNIT-005, AUD-004 | remote settings, pins, SBOM/signing absent | SCN-10 | dependency/workflow/release change | Stale/Unknown | before stronger release claim |
| SIDE-01 | web-run/search/image optional sidecars | Medium | rotating; feature change | `0caa7a1` / 2026-07-19 / source/tests | sidecar, URL/token config, health/supervisor, image fetch | UNIT-007 | no live endpoint/container smoke | SCN-07/09 | sidecar/URL/credential change | Unknown | first optional-sidecar deployment |
| GOV-02 | Legacy/migration path inventory and boundary | High | baseline then targeted remediation | `0caa7a1` / 2026-07-19 / source/tests | config/local/admin/persistence/core aliases | UNIT-004, AUD-001 | protocol-vs-internal classification incomplete | SCN-06/08 | any compatibility/migration change | Invalidated by AUD-001 | inventory/removal wave |

## Scenario Coverage

| Scenario ID | Scenario | Required response/measure | Last exercised | Evidence/result | Gaps | Dependencies | Invalidation triggers | Status | Next action |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SCN-01 | Invalid/missing API key to `/v1/responses` | fail closed; no upstream/state identity | 2026-07-19 | auth tests; satisfied deterministically | no live reverse proxy | AUTH-01 | auth/header/config change | Fresh | repeat after auth change |
| SCN-02 | Two API keys share window/tool IDs | no cross-principal state read/write | 2026-07-19 | persistence/auth tests; satisfied for sampled mappings | no deployment stress | AUTH-01, DATA-02 | scope/key/schema change | Fresh | quota/isolation targeted re-audit |
| SCN-03 | Codex Responses route to configured provider | preserve required request/response semantics | 2026-07-19 | converters/proxy + source contract; deterministic satisfied | real upstream/model unknown | PROVIDER-01, CODEX-01 | route/converter/Codex change | Fresh (deterministic) | live approved development run |
| SCN-04 | Provider SSE deltas/tool/usage/EOF/cancel | order, terminal event, cleanup | 2026-07-19 | stream/lifecycle tests; deterministic satisfied | real timing/provider unknown | STREAM-01, CODEX-02 | stream/proxy/transport change | Fresh (deterministic) | live approved stream run |
| SCN-05 | Tool localization/deferred discovery/replay | exact owner-scoped tool identity/args | 2026-07-19 | tool/mapping tests; deterministic satisfied | no real MCP/plugin trajectory | TOOL-01, DATA-02, AGENT-01 | tool schema/projection/change | Fresh (deterministic) | live deferred-tool run outside audit |
| SCN-06 | Compaction trigger/resume/fork | valid mode, owned token rehydration, bounded state | 2026-07-19 | compaction tests; input validation satisfied; persistence bound not satisfied | no live summary; no aggregate cap | CODEX-02, DATA-03 | compaction/persistence/Codex change | Invalidated | fix AUD-002 then re-audit |
| SCN-07 | Repeated large diagnostic/compaction/tool payloads | caps/TTL/cleanup prevent uncontrolled growth | 2026-07-19 | tool/log caps evidenced; compaction cap gap found | no long-run disk/stress | DATA-01/02/03 | retention/persistence change | Invalidated | quota and stress evidence |
| SCN-08 | Admin login/reload/key/provider/model mutation | one Admin only; invalid config no partial state | 2026-07-19 | admin/config/session tests; deterministic satisfied | no browser/LAN deployment | AUTH-02, GOV-02 | Admin/config/session change | Fresh | browser/local deployment smoke |
| SCN-09 | Unsupported custom/unknown provider config | reject or explicitly support one policy | 2026-07-19 | source/UI shows broader behavior than profile | decision pending; no egress test | PROVIDER-01, SIDE-01 | provider/UI/config change | Unknown | owner decision and boundary test |
| SCN-10 | Build wheel/Docker/manual release | current source, tag/version gate, no automated publish | 2026-07-19 | lint/test/build/contract/tag passed; manual publish path | no GitHub/provenance/signing | REL-01/02, SUPPLY-01 | release/workflow/dependency change | Fresh (local) | release-integrity plan |
| SCN-11 | Agent/live runner external call | no audit calls; development call requires explicit approval | 2026-07-19 | deterministic separation verified; gate missing | no live trajectory; no enforced opt-in | AGENT-01 | harness/agent permission change | Invalidated | implement AUD-003 control |

## Control Baseline Coverage

| Control ID | Control/outcome | Source/profile requirement | Implementation scope | Verification evidence | Exceptions | Owner | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CTRL-01 | mandatory Admin password and Gateway API key | PROFILE security baseline | `GatewayConfig._validate`, auth state | auth/config tests | public deployment excluded | Gateway | Fresh |
| CTRL-02 | stable API-key principal isolation | PROFILE security baseline | context vars, state scope, SQL AAD | auth/persistence tests | no live multi-client run | Gateway/observability | Fresh |
| CTRL-03 | token-only redaction with non-token retention | PROFILE privacy policy | `SecretRedactor`, logs/persistence | redaction/persistence tests | no external log sink | Observability | Fresh |
| CTRL-04 | bounded durable state | PROFILE security/reliability baseline | log/tool caps, TTL, cleanup | persistence tests | compaction quota missing | Observability | Invalidated |
| CTRL-05 | audit no real API calls | user decision/profile | audit scope and executed commands | command record; no live call | live runners remain callable | Project owner | Fresh for this run / control gap |
| CTRL-06 | developer approval before real API tests | user decision/profile | current docs/procedural workflow only | source review shows no gate | AUD-003 | Test harness owner | Unknown / gap |
| CTRL-07 | manual release only | user decision/profile | disabled push targets, manual docs | Makefile/source review | external GitHub settings unknown | Project owner | Fresh (local) |
| CTRL-08 | no Rosetta migration layer | user decision/profile | current code still has legacy/migration paths | inventory/AUD-001 | protocol compatibility aliases need classification | Core/Gateway | Invalidated |

## Coverage Change Log

| Date/run | Coverage ID | Previous status | New status | Reason/change | Evidence |
| --- | --- | --- | --- | --- | --- |
| 2026-07-19 / 20260719-1542 | GOV-01/MAP-01 | Unknown | Fresh | reset baseline profile and map reconciled to `0caa7a1` | UNIT-001 |
| 2026-07-19 / 20260719-1542 | AUTH-01/AUTH-02 | Unknown | Fresh | current source + focused/full deterministic tests | UNIT-002 |
| 2026-07-19 / 20260719-1542 | CODEX-01/CODEX-02/STREAM-01/TOOL-01 | Invalidated/Unknown | Fresh (deterministic) | current Codex source contract + focused/full tests | UNIT-003 |
| 2026-07-19 / 20260719-1542 | DATA-01/DATA-02 | Unknown | Fresh | persistence/crypto/redaction/capacity source + tests | UNIT-004 |
| 2026-07-19 / 20260719-1542 | DATA-03 | Unknown | Invalidated | compaction mapping lacks aggregate bound | AUD-002 |
| 2026-07-19 / 20260719-1542 | GOV-02 | Unknown | Invalidated | approved no-migration boundary conflicts with current paths | AUD-001 |
| 2026-07-19 / 20260719-1542 | REL-01/REL-02 | Unknown | Fresh (local) | lint/test/direct wheel/contract/tag checks | UNIT-005 |
| 2026-07-19 / 20260719-1542 | SUPPLY-01 | Unknown | Stale/Unknown | mutable remote inputs and missing provenance | AUD-004 |
| 2026-07-19 / 20260719-1542 | AGENT-01 | Unknown | Invalidated | no mechanical developer-approval gate | AUD-003 |
| 2026-07-19 / 20260719-1542 | PROVIDER-01 | Unknown | Invalidated | current registry/UI/config contradicts the approved preset-only boundary until custom endpoint semantics are decided | AUD-005 |
| 2026-07-19 / 20260719-1542 | SIDE-01 | Unknown | Unknown | no live sidecar/provider runtime evidence | UNIT-007 |

## Due Rotation Queue

| Priority | Coverage/scenario | Reason due | Criticality | Evidence needed | Suggested next run |
| --- | --- | --- | --- | --- | --- |
| P0 | AUD-002 / DATA-03 / SCN-06/07 | aggregate compaction bound missing | Critical | quota design, focused tests, targeted re-audit | immediately before internal deployment |
| P0 | AUD-001 / GOV-02 | internal migration inventory conflicts with profile | High | classification table, removal/rejection tests | next remediation-enabled run |
| P0 | AUD-003 / AGENT-01 / SCN-11 | developer approval is procedural only | High | fail-closed opt-in and no-network test | before autonomous/live harness use |
| P1 | AUD-005 / PROVIDER-01 / SCN-09 | preset/custom boundary decision pending | High | owner decision, config/UI/egress tests | before provider support claim |
| P1 | CODEX-01/SCN-03/04/06 | extractor leaves semantic rows possibly unchanged | Critical | source/manual/default/serde review and approved live gate | next Codex compatibility cycle |
| P1 | SUPPLY-01/REL-02 | no immutable provenance/signing/SBOM | Medium | release-integrity design and remote settings | before first public release |
| P2 | SIDE-01 | optional sidecar/provider runtime unknown | Medium | local Compose/sidecar smoke without real provider, then approved live test | feature activation/deployment |
| P2 | SCN-08 | no browser/LAN deployment smoke | Critical | local/LAN browser and reverse-proxy evidence | first internal deployment |
