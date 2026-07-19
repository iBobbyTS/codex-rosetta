# Audit Run Scope

Run: 20260719-1542
Mode: Reset Baseline
Repository range/head: `origin/main..0caa7a1308452100e553c9e1e3411b9a9f0a0746`; current branch `main`, worktree clean outside audit artifacts
Profile and status: `docs/audit-profile.md`, Approved
Resource/budget constraints: local repository and deterministic runtime evidence only; no real Codex/provider API calls; no production deployment/logs/metrics; no remediation authorized
Authorized remediation: No

## 1. Scope Selection Summary

| Scope item | Reason | Criticality | Quality attributes | Scenarios | Expected evidence | Planned depth |
| --- | --- | --- | --- | --- | --- | --- |
| Repository/profile/map reconciliation | reset; durable ledgers absent and old reports use a different protocol | Critical | operability, modifiability | all | git state, file/symbol inventory, profile decisions | broad map, not deep every file |
| Gateway auth, Admin session, CORS and config mutation | always-on critical; privileged boundary | Critical | security, privacy, correctness, operability | SCN-01, SCN-02, SCN-08 | current source, auth/admin/config tests, local probes if needed | deep slice |
| Provider/model/shim routing and downstream surface | always-on critical; Codex-only supported client and preset upstreams | Critical | correctness, security, modifiability | SCN-03, SCN-09 | route/config/shim source, tests, docs comparison | deep slice |
| Conversion pipeline, Responses/SSE/tool/compaction paths | always-on critical and high churn; core product invariant | Critical | correctness, reliability, privacy | SCN-03, SCN-04, SCN-05, SCN-06 | converter/proxy/stream/compaction source, focused/full deterministic tests | deep representative slice |
| Persistence, principal state, redaction, retention, cleanup | always-on critical; crown-jewel prompts/tool history and key isolation | Critical | security, privacy, reliability, cost | SCN-02, SCN-05, SCN-06, SCN-07 | SQLite schema/source/tests, boundedness experiments | deep slice |
| Release, CI, Docker and build provenance | always-on release control; manual release only | High | security, operability, modifiability, cost | SCN-10 | Makefile, workflows, Docker, build/lint/version gates | source/control review + local gates |
| Agent/live-test control plane | profile-mandated; developer approval and audit no-live-call rule | High | security, operability, correctness | SCN-11 | repo instructions, harness configs, test collection, artifact policy | control-plane review |
| Non-Codex converter/shim breadth | rotating deep slice; baseline representative coverage | Medium | correctness, modifiability | SCN-03 | one or more per-format source/test slices | representative only |
| Optional web/search/image sidecars | rotating; external trust boundary and optional feature | Medium | security, reliability, cost | SCN-07, SCN-09 | config/sidecar/source/test review | map + gap inventory |

## 2. Changed and Invalidated Surface

| Change/component | Semantic class | Dependent coverage/scenarios | Invalidation result | Rationale |
| --- | --- | --- | --- | --- |
| Current head includes Codex alpha.23 compatibility and model/catalog updates | behavior/contract/agent | SCN-03/04/06/11 | old 20260709-20260711 snapshots invalidated for current compatibility claims | source contract and catalog semantics changed after old audit snapshots |
| Current head includes compaction, deferred MCP, live-agent contract and auth/header changes | behavior/state/agent/security | SCN-01/02/04/05/06/11 | broad prior conclusions not trusted | multiple cross-cutting boundaries changed |
| Persistent `SYSTEM-MAP.md`, `COVERAGE.md`, `FINDINGS.md` absent | governance/evidence | all | reset baseline | no bounded freshness/invalidation graph existed |
| Existing audit profile was Draft and compatibility-focused | governance/risk | all | replaced for current approved scope | user changed supported deployment/risk boundary |

## 3. Always-On Critical Scenarios

| Scenario | Why required now | Evidence target |
| --- | --- | --- |
| SCN-01 invalid API key fails closed | all `/v1` trust starts at this gate | auth source + deterministic tests |
| SCN-02 principal isolation | multiple API keys are supported and state is persistent | scope construction, SQL predicates, tests |
| SCN-03 Codex request/response route | only downstream client is Codex | current route, pipeline, catalog, local fake upstream |
| SCN-04 stream lifecycle | Codex tool/reasoning behavior depends on ordered SSE | stream converter/proxy tests and cleanup paths |
| SCN-05 tool localization/replay | high-impact tool semantics and persisted history | mapping crypto/persistence/proxy tests |
| SCN-06 compaction/resume/fork | current compatibility work and durable state | compaction source/tests; live summary blocked |
| SCN-08 single Admin mutation | only privileged control plane | admin auth/config/session tests |

## 4. Rotating Deep Slices

| Area | Last reviewed | Why selected | Planned boundary |
| --- | --- | --- | --- |
| Auth/config/provider boundary | None trusted | critical and current profile change | `app.py`, `auth.py`, `config.py`, `providers.py`, admin config/key routes |
| Persistent state and retention | None trusted | crown-jewel data and local disk growth | `observability/persistence.py`, crypto, retention, compaction persistence |
| Codex compatibility/control plane | None trusted for current head | high churn and source-contract drift | `local_mode.py`, `codex_compaction.py`, catalog/docs/check script |
| Release/supply chain | None trusted | manual release and mutable CI/build inputs | Makefile, workflows, Docker, pyproject, version scripts |

## 5. Incident, Finding, and Debt Follow-up

| Item | Trigger/evidence | Planned verification |
| --- | --- | --- |
| Legacy/migration compatibility paths | user approved no Rosetta-version migration layer; current source contains config/persistence/API legacy paths | inventory and classify protocol compatibility vs internal migration; record finding, no repair |
| Unbounded/partially bounded durable state | tool mappings are quota-bounded; compaction mappings use TTL without obvious byte/row cap | source trace and local boundedness experiment |
| Real API/live evidence | user explicitly prohibits audit real calls; project is not deployed | record Unknown/external blocker, inspect harness approval boundary |
| Prior audit reports | historical snapshots on old heads and no durable ledgers | reconcile but do not inherit findings/coverage |

## 6. Exclusions

| Area | Reason excluded | Residual risk | Next review trigger |
| --- | --- | --- | --- |
| Real Codex/provider/agentabi execution | user policy prohibits real API calls during audit | model/tool/stream behavior under live providers unknown | developer-approved development live run outside audit |
| Production/shared deployment | none exists | effective network exposure, telemetry, rollback unknown | first internal deployment |
| Public-internet account security | outside supported commitment | unsafe public exposure remains possible | any public deployment claim |
| Backup/restore/DR/HA/SLO | explicitly not promised | recovery behavior unknown | introduction of operational guarantee |
| External GitHub settings and Actions branch protections | not available through local checkout evidence | remote permissions/pinning may differ | owner-authorized GitHub inspection |
| Full converter/provider matrix | baseline is risk-sampled, not exhaustive | unreviewed format/provider edges remain Unknown | rotating audit or changed converter/shim |
| `_vendor/` internals | vendored and excluded by project rules | upstream vendored behavior not independently audited | re-vendoring or vendor change |

## 7. Material Assumptions and Decisions Needed

- The user-approved boundary treats local/LAN use as supported and public deployment as unsupported.
- No legal/privacy/contract requirements are currently known.
- Only token values/token-shaped fields require redaction; non-token diagnostic content may be retained within current caps/TTL.
- Provider selection for any future development live test is chosen and approved per test; audit will not perform such calls.
- “No compatibility migration layer” means no Rosetta-version config/persistence/internal-API migration promise; current Codex/provider wire compatibility remains product scope.
- No material decision currently blocks this baseline discovery; unknown runtime evidence is recorded as a gap.

## 8. Stop Criteria for This Run

- [x] Every scoped item has evidence and outcome.
- [x] Required scenarios are traced or explicitly blocked.
- [x] Persistent ledgers are updated.
- [x] No remediation is performed without separate authorization.
- [x] Report states sampling limits, Unknown areas, findings, and next rotation.
