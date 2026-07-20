# Persistent Audit Findings and Debt

Last updated: 2026-07-20
Repository base: `804efef03d91f72771f27228bde26003d6ba40fa`; targeted omission-remediation re-audit `20260720-1239` is in the working tree
Profile: `docs/audit-profile.md` (Approved)

## Conclusion ownership

This section separates the current conclusions by who may authorize the next
step. The baseline recorded `Authorized remediation: No`; the owner later
authorized the remediation wave documented in
`docs/audit/runs/20260719-1712/`.

### Logic/control issues I can repair directly

| ID | Conclusion | Direct repair boundary |
| --- | --- | --- |
| AUD-002 | Compaction replacement persistence has no aggregate row/byte quota | Add bounded, transactional persistence controls and regression tests; exact limits can be proposed within the approved local/LAN risk profile. |
| AUD-001 | Rosetta-version migration and legacy paths conflict with the no-migration boundary | Reject incompatible legacy config/state and remove the active migration/alias paths; current protocol compatibility remains explicit. |
| AUD-003 | Real-call runners lack a fail-closed developer-approval gate | Add an explicit opt-in gate and deterministic tests proving no external-call subprocess/client starts without it. |
| AUD-006 | Live-call approval gate omitted executable examples | Gate every REST/SDK example before dotenv/credentials and enforce directory-complete coverage. |
| AUD-007 | Admin tool-profile default still depends on stripped provider metadata | Derive the runtime profile from `api_type + base_url` using the same URL-authoritative preset rules, without persisting UI options. |
| AUD-008 | Audit coverage ledger contradicts current finding/closure status | Reconcile current coverage, control status, and rotation queue after reopening affected findings. |
| AUD-010 | SQLite index validation omitted uniqueness/origin/partial attributes | Validate the complete required index shape before startup. |
| AUD-012 | Upstream redirects could forward provider authorization to a second target | Reject every upstream redirect before a second request is sent. |

### Business/semantic decisions requiring owner authority

| ID | Decision / current state | Why it cannot be inferred safely |
| --- | --- | --- |
| AUD-005 | **Recorded:** provider vendor/variant is derived from URL; unmatched URLs use custom and remain allowed | URL-authoritative custom endpoint semantics are product policy; the implementation boundary must follow the owner decision. |
| AUD-004 | Whether to adopt stronger artifact-integrity controls such as digest pinning, SBOM, provenance, and signing before a public release or stronger security claim | Manual release and the current pre-release risk acceptance are explicit product policy; stronger guarantees require an owner decision. |
| AUD-009 | **Recorded:** missing `api_type` is inferred at runtime from exact preset URL support order; custom defaults to Responses; no write-back | Protocol selection changes routing behavior, so its fallback order requires owner authority. |
| AUD-011 | **Recorded:** arbitrary HTTP(S) custom URLs may receive upstream API keys within local/LAN scope; redirects are prohibited | The initial egress/key-disclosure boundary requires owner authority; redirect behavior is a repairable transport control. |

The remaining `No Action`, deterministic-only, and excluded-runtime statements
are evidence status or explicit scope limits, not additional remediation
findings. They must not be presented as live-production or provider-quality
claims.

## Findings Status

| ID | Severity | Decision class | Status | Root cause | Affected scenarios/areas | Owner/decision | Due/revisit trigger |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AUD-002 | Must Fix | Agent-Fixable | Closed | Transactional compaction replacement row/byte/replacement-size quotas now bound supported local/LAN persistence | SCN-06, SCN-07; persistence/observability | Project owner / Gateway persistence owner | Reopen if limits or storage path change |
| AUD-001 | Should Plan | Agent-Fixable | Closed | Rosetta-version config/state/API migration and legacy compatibility paths were rejected or removed under the prelaunch no-migration boundary | SCN-08, SCN-06, DATA-03; config/local mode/admin/persistence/core API | Project owner / core and gateway owners | Reopen if a migration path is added |
| AUD-003 | Should Plan | Agent-Fixable | Closed | Shared exact-marker gate now covers every enumerated real-call entry point | SCN-11; scripts/live-agent/integration/agent control plane | Project owner / test-harness owner | Reopen on any new ungated live entry point |
| AUD-005 | Should Plan | Decision Recorded | Closed | URL-authoritative runtime resolution and Admin profile derivation now agree without persisting options | SCN-09; provider/config/Admin UI | Project owner decision recorded in profile | Reopen if provider options become persisted or URL semantics change |
| AUD-006 | Should Plan | Agent-Fixable | Closed | Integration/agent launchers and all 24 executable examples fail closed before credentials/external work | SCN-11; integration, examples, and agent launch scripts | Project owner / test-harness owner | Reopen on any new real-call entry point |
| AUD-007 | Should Plan | Agent-Fixable | Closed | Admin profile is derived from runtime API fields and URL/protocol rules | SCN-09; Admin UI/config route | Gateway/Admin owner | Reopen if API response loses required derived fields |
| AUD-008 | Should Plan | Agent-Fixable | Closed | Findings, coverage, system map, run evidence, and rotation queue reconciled | audit control plane | Audit owner | Reopen when a remediation run leaves contradictory ledger state |
| AUD-010 | Should Plan | Agent-Fixable | Closed | SQLite validator checks columns, constraints, primary keys, required index columns, uniqueness, origin, and partial flag | DATA-01/DATA-03; persistence startup/write path | Persistence owner | Reopen on schema/table/index change without updated contract |
| AUD-012 | Must Fix | Agent-Fixable | Closed | HTTP client rejects all redirects before any credential-bearing follow-up request | PROVIDER-01/SCN-09; transport boundary | Gateway transport owner | Reopen if redirect behavior or HTTP client changes |
| AUD-009 | Should Plan | Decision Recorded | Closed | Missing `api_type` is inferred in memory using `responses`, `chat`, `anthropic`, `google` order; custom defaults to Responses; warning emitted | PROVIDER-01; config/Admin | Project owner decision recorded in profile | Reopen if fallback order or persistence semantics change |
| AUD-011 | Should Plan | Decision Recorded | Risk Accepted | Direct arbitrary HTTP(S) custom egress and key delivery are accepted within local/LAN scope; redirect expansion is prohibited | PROVIDER-01/SCN-09; transport boundary | Project owner | Reopen if deployment boundary or direct-egress policy changes |

## Closed Findings

| ID | Closed in run/head | Closure evidence | Residual risk | Reopen trigger |
| --- | --- | --- | --- | --- |
| AUD-001 | 20260719-1712 / working tree | Legacy config/state/API migration and deprecated retention aliases rejected or removed; deterministic suite green | Current Codex/provider protocol compatibility remains explicit; old user data is not migrated | Reopen if any Rosetta-version migration path is added |
| AUD-002 | 20260719-1712 / working tree | Single-row, per-principal and global compaction row/byte quotas enforced transactionally with focused tests | Chosen limits are local/LAN operational limits; no disk-recovery guarantee | Reopen if compaction storage semantics change |
| AUD-003 | 20260720-1107 / `e7f72bf` | Exact opt-in gate tested fail-closed for enumerated live/integration runners | Approved development live runs remain outside audit evidence | Reopen if a runner bypasses the shared gate |
| AUD-005 | 20260720-1107 / `e7f72bf` | URL-authoritative preset/custom resolution, runtime profile derivation, and no-option persistence tests | Custom egress remains owner-accepted local/LAN risk; no public claim | Reopen if provider options become persisted or matching diverges |
| AUD-006 | 20260720-1239 / `35521ab` | All 24 REST/SDK examples gate before dotenv; directory-discovered contract tests pass | No real-call trajectory was run | Reopen on new runner/example |
| AUD-007 | 20260720-1107 / `e7f72bf` | Admin provider/model-group profile and validation rendering use runtime-derived fields | No browser deployment evidence | Reopen if Admin API/UI contract changes |
| AUD-008 | 20260720-1239 / working tree | Profile, findings, coverage, system map, README, and immutable run evidence reconciled to `804efef` | Ledger validity is repository-local | Reopen on contradictory status |
| AUD-009 | 20260720-1239 / `804efef` | Runtime inference, one warning per active provider load, Admin rendering, and no-write-back tests pass | A wrong custom URL can still select Responses until operator corrects it | Reopen if fallback order or persistence changes |
| AUD-010 | 20260720-1239 / `ec8419b` | SQLite schema fingerprint includes index uniqueness/origin/partial attributes with focused tests | No restore/long-run stress claim | Reopen on schema change |
| AUD-011 | 20260720-1239 / `477fa00`, `804efef` | Profile retains accepted direct custom egress while transport rejects redirects | Direct custom URL SSRF/account-security risk remains accepted within local/LAN boundary | Reopen if scope or policy changes |
| AUD-012 | 20260720-1239 / `477fa00` | Loopback regression proves a redirect response does not reach its target | DNS/proxy behavior was not live-tested | Reopen if redirect/client behavior changes |

## Omission-remediation re-audit — `20260720-1239`

The second omission pass reopened incomplete controls, identified redirect credential exposure, and replaced the earlier AUD-009 decision. Details and current evidence are in [`docs/audit/runs/20260720-1239/REPORT.md`](runs/20260720-1239/REPORT.md) and [`EVIDENCE.md`](runs/20260720-1239/EVIDENCE.md). Prior runs remain historical evidence only.

### Current classification

- Agent-fixable and closed: AUD-003, AUD-006 (including executable examples), AUD-007, AUD-008, AUD-010 (complete index attributes), AUD-012 (redirect prohibition).
- Business semantics recorded: AUD-005 (URL-authoritative custom behavior), AUD-009 (runtime protocol inference and warning), AUD-011 (direct arbitrary custom HTTP(S) egress accepted within local/LAN scope).
- No live/provider/deployment claim: this run remains static/deterministic only.

## Accepted Debt and Risk

| ID | Owner | Why acceptable now | Safety ceiling | Mitigations/monitoring | Revisit trigger/date | Expected resolution |
| --- | --- | --- | --- | --- | --- | --- |
| AUD-004 | Project owner | Project is permanently scoped to local/trusted-LAN deployment and makes no public or artifact-integrity guarantee | No public deployment/security claim; no automated package/image publication | manual tag/version gate; local build from current checkout; CI Docker secret checks; disabled push targets | If the deployment boundary or release claim changes | Pin/verify build inputs and define provenance/SBOM/signing only if the owner later expands the boundary |

## Golden-Principle Candidates

| GP ID | Recurring issue/invariant | Evidence occurrences | Proposed enforcement | False-positive/maintenance risk | Owner | Status |
| --- | --- | --- | --- | --- | --- | --- |
| GP-001 | Real provider/Codex calls require explicit human approval and are never part of audit/default deterministic checks | live runners now share a fail-closed exact-marker gate; deterministic suite excludes real calls | keep the shared gate mandatory for every new runner | Approved live runs remain explicit and out of audit evidence | Project owner | Enforced |
| GP-002 | Every durable agent/gateway state store needs an explicit owner scope and aggregate byte/row/TTL bound | tool mappings and compaction mappings now have scope, TTL and transactional row/byte limits | require quota contract tests for each new durable store | Limits are local/LAN policy values and may need owner tuning | Gateway persistence owner | Enforced |

## Candidate Disposition

| Candidate | Run/area | Disposition | Evidence/reason |
| --- | --- | --- | --- |
| Reuse old audit `FULL.md` status | UNIT-001 | Rejected | old head/profile and missing durable ledgers invalidate freshness |
| Treat no deployment as no security scope | UNIT-001/002 | Rejected | local/LAN auth, secrets, principal isolation and untrusted provider content remain in scope |
| Treat all `legacy` strings as one defect | UNIT-004 | Rejected | current Codex/provider protocol compatibility is distinct from Rosetta-version migration; inventory must separate them |
| AUD-013: reject model groups that reference missing/disabled providers | 20260720-1239 / config routing | Rejected by owner | Current silent-skip behavior is proportionate to this Gateway's scale; no new validation/error-propagation state machine is introduced. Revisit only if routing scale or operability requirements change. |

---

## AUD-002 — Compaction replacement persistence has no aggregate quota

- Severity: Must Fix
- Decision class: Agent-Fixable
- Status: Closed in remediation wave `20260719-1712`; confirmed in targeted re-audit `20260720-1107`
- Current state: `store_codex_compaction_mapping` now enforces replacement-size, per-principal and global row/byte quotas transactionally; the original failure description is retained as historical baseline evidence.
- Confidence: High
- First detected run: 20260719-1542
- Last updated run: 20260720-1107
- Owner: Gateway persistence owner / project owner

### Quality attributes and profile requirements

- Affected attributes: Security, reliability, privacy, cost, operability.
- Profile/control requirement: Durable state must be bounded for supported local/LAN use; do not tolerate unbounded supported-path state growth. Prompt/summary content may be retained only within explicit current policy bounds.
- Violated invariant/outcome: A valid authenticated client can cause multiple Rosetta compaction summaries to be retained for the rolling seven-day TTL without a configured aggregate row/byte ceiling.

### Failure, abuse, or structural path

```text
Stimulus/trigger: Repeated valid Codex Remote Compaction V2 triggers routed through Rosetta mode.
Environment/preconditions: Supported local/LAN Gateway; valid API key; compaction summary succeeds.
Path/components: codex_compaction.create_compaction_mapping -> PersistenceManager.store_codex_compaction_mapping -> codex_compaction_mappings.
Expected response: Persist only within an explicit per-principal/global row and byte budget, or fail closed with a bounded error.
Observed or supported failure: The storage method accepts arbitrary replacement_text, computes replacement_bytes, inserts and commits; only a rolling seven-day TTL is applied. No aggregate quota or max replacement length is enforced in this path.
```

### Impact and risk basis

- User/business/mission impact: local/LAN Gateway disk and database growth can degrade or stop the only supported service; compaction may retain large prompt-derived summaries.
- Security/privacy/data/reliability impact: prompt/source-sensitive plaintext is retained; a valid key or buggy loop can create repeated state and denial-of-wallet/storage pressure.
- Likelihood/exploitability: Medium; reachable only through valid routed compaction flow, but repeated loops are plausible.
- Blast radius: one principal can affect the shared SQLite data directory; aggregate impact persists until TTL cleanup or manual deletion.
- Reversibility/recovery: manual deletion is possible, but no backup/restore guarantee exists and disk exhaustion can impair normal cleanup.
- Systemic reach: persistence owner and all compaction routes; distinct from already-bounded encrypted tool mappings.

### Scope and occurrences

| Component/path/symbol/workflow | Evidence | Why affected |
| --- | --- | --- |
| `src/codex_rosetta/gateway/codex_compaction.py:create_compaction_mapping` | lines 304-326 | stores full summary replacement and uses only seven-day TTL |
| `src/codex_rosetta/observability/persistence.py:store_codex_compaction_mapping` | lines 1271-1303 | accepts arbitrary text and commits without quota validation |
| `src/codex_rosetta/observability/persistence.py:codex_compaction_mappings` | schema lines 401-414 | has expiry index but no row/byte budget columns/limits |
| `src/codex_rosetta/observability/persistence.py:tool_call_mappings` | schema/capacity methods lines 326-419, 1000-1259 | sibling store demonstrates stronger boundedness controls, making the gap concrete |

### Evidence

- Code/configuration evidence: `EVIDENCE.md` UNIT-004; current source lines above.
- Test/scanner evidence: `tests/gateway/test_codex_compaction.py` and `tests/gateway/test_persistence_sqlite.py` pass, but no aggregate compaction-cap test exists in the reviewed scope.
- Runtime/operations/incident evidence: no deployed environment or production data; no live API call made.
- Architecture/history evidence: the remediation wave aligned compaction mapping storage with the bounded encrypted tool-mapping pattern while preserving TTL cleanup.
- Contradicting evidence considered: seven-day expiry and request/upstream limits may bound individual summaries; they do not establish an aggregate row/byte ceiling for the table.
- Gaps/assumptions: exact upstream response size limit and operator filesystem capacity were not live-exercised.

### Recommended direction

- Smallest credible remediation/control: add explicit maximum replacement bytes and per-principal/global row/byte quotas using the same fail-closed pattern as encrypted tool mappings; ensure cleanup and quota accounting are transactional.
- Rollout/migration/rollback implications: no migration compatibility layer is promised; new limits can reject new mappings while allowing existing TTL cleanup. Add tests for per-principal/global overage and oversized one-row input.
- Suggested priority: Must Fix before first supported internal deployment/live compaction use.

### Frozen acceptance criteria

- [x] A single compaction replacement has a hard, tested byte limit.
- [x] Per-principal and global row/byte quotas are enforced transactionally.
- [x] Existing TTL cleanup remains fail-closed and does not bypass quotas.
- [x] Original compaction scenario succeeds below limits and returns a bounded error above limits.
- [x] Different API-key principals cannot consume or read each other’s mappings.
- [x] Focused persistence/compaction tests and full deterministic suite pass.
- [x] Persistent coverage and retention policy document the new bounds.

### Human decision or risk acceptance

- Decision required: None for the control shape; exact limits can be selected by the persistence owner within the profile.
- Options/consequences: add quota controls now, or explicitly accept local/LAN disk-growth risk until before first internal deployment.
- Decision: Owner authorized remediation after the baseline.
- Authority/date: 2026-07-19
- Residual-risk owner: Project owner

### Remediation history

| Wave/head | Changes | Verification | Result | Coverage invalidated |
| --- | --- | --- | --- | --- |
| 20260719-1712 | Added transactional single-row, per-principal and global row/byte quotas with deterministic regression tests | `make test`; focused persistence tests | Closed | No baseline rows/data migration is promised |

### Closure/reopen

- Closure evidence: `docs/audit/runs/20260719-1712/EVIDENCE.md`; persistence/compaction tests; full deterministic suite.
- Residual risk: limits are local/LAN policy limits; no backup/restore or long-run disk guarantee is claimed.
- Reopen trigger: any change that bypasses transactional quota accounting or introduces another durable compaction store.

---

## AUD-001 — Internal migration and legacy compatibility paths conflict with the prelaunch boundary

- Severity: Should Plan
- Decision class: Agent-Fixable
- Status: Closed in targeted re-audit `20260720-1107` (original gate added in `20260719-1712`)
- Current state: Rosetta-version config/state/internal API migration and deprecated retention aliases now fail closed or are removed; current protocol compatibility remains explicit.
- Confidence: High
- First detected run: 20260719-1542
- Last updated run: 20260720-1107
- Owner: Project owner with core/gateway owners

### Quality attributes and profile requirements

- Affected attributes: Modifiability, correctness, security, operability.
- Profile/control requirement: No project-version migration layer for old Rosetta config, persistence, or internal APIs is promised; current Codex/provider wire compatibility remains in scope.
- Violated invariant/outcome: The implementation still contains active Rosetta-version migration/legacy paths that preserve old config/state/API behavior without an approved supported boundary.

### Failure, abuse, or structural path

```text
Stimulus/trigger: New prelaunch code/config/schema is changed while legacy input/state remains accepted.
Environment/preconditions: Old config key, legacy JSONL/JSON data, old mapping schema, or deprecated Python alias is present.
Path/components: GatewayConfig/local_mode/Admin key routes/PersistenceManager/pipeline/converter aliases.
Expected response: Unsupported old Rosetta-version state/config/API is rejected or removed, while explicit Codex/provider protocol compatibility remains tested and documented.
Observed or supported failure: Multiple paths synthesize, migrate, backfill, or alias legacy behavior; scope and removal trigger are not centralized.
```

### Impact and risk basis

- User/business/mission impact: prelaunch changes carry avoidable compatibility branches and state transitions; future Codex/provider fixes can touch more paths.
- Security/privacy/data/reliability impact: migration code handles secrets, logs, and executable tool history; hidden fallback semantics can preserve stale or lossy state.
- Likelihood/exploitability: High for maintainers/agents encountering old artifacts; not an anonymous attack path under the supported boundary.
- Blast radius: config startup/admin mutation, persistence initialization, local mode, core public API and converters.
- Reversibility/recovery: removal is easier before first supported deployment/data set; after deployment, migration semantics become harder to change.
- Systemic reach: broad recurring pattern, not one local branch.

### Scope and occurrences

| Component/path/symbol/workflow | Evidence | Why affected |
| --- | --- | --- |
| `gateway/config.py` | lines 756-767 | accepts legacy `server.api_key` by synthesizing `api_keys` |
| `gateway/local_mode.py:ensure_codex_api_key` | lines 789-812 | migrates legacy single key into array |
| `gateway/admin/routes/keys.py` | lines 34-43 and 81-86 | exposes and migrates legacy key entries |
| `observability/persistence.py` | `_migrate_legacy`, column/schema migration, legacy mapping migration | imports old files/schema and discards/rewrites old mapping state |
| `pipeline.py` and converter modules | deprecated aliases and old API compatibility methods | keeps old internal/public call shapes alive |
| `gateway/admin`/catalog/docs | legacy field/type fallbacks | preserves old config and target-client shapes; some may be Codex protocol compatibility and require classification |

### Evidence

- Code/configuration evidence: `EVIDENCE.md` UNIT-004 and `rg -n -i 'legacy|migration|backward compat'` inventory.
- Test/scanner evidence: full deterministic suite passes, including legacy migration tests; passing tests prove current behavior, not that the behavior is still approved.
- Runtime/operations/incident evidence: no deployed data set exists.
- Architecture/history evidence: current project has an IR/provider compatibility mission, while the user explicitly removed Rosetta-version migration obligations.
- Contradicting evidence considered: some legacy fields are required to preserve current Codex 0.144.x/alpha.23 protocol behavior; those must not be removed without classification.
- Gaps/assumptions: exact complete inventory and canonical allowlist of protocol compatibility aliases are not yet finalized.

### Recommended direction

- Smallest credible remediation/control: build a one-time inventory and classification table: `current Codex/provider protocol compatibility`, `required current config`, or `Rosetta-version migration/legacy`. Remove or reject only the last class; add a test/CI guard against new unapproved internal migration paths.
- Rollout/migration/rollback implications: prelaunch/no deployed data makes removal low-risk; preserve no old-data migration guarantee as profile states.
- Suggested priority: schedule before first supported internal deployment.

### Frozen acceptance criteria

- [x] Every active `legacy`/`migration` path in the affected slices is inventoried with owner and classification.
- [x] Current Codex/provider protocol compatibility remains explicit and tested.
- [x] Rosetta-version config/persistence/internal-API migration paths are removed or fail closed.
- [x] No new compatibility migration layer can be added without an explicit profile decision.
- [x] Full deterministic suite and targeted compatibility checks pass after the inventory/removal wave.

### Human decision or risk acceptance

- Decision required: None for the approved boundary; protocol-vs-internal classification must be documented during remediation.
- Options/consequences: remove internal migration now, or accept growing prelaunch complexity and future removal cost.
- Decision: Owner authorized removal/rejection of Rosetta-version migration paths; current protocol compatibility remains in scope.
- Authority/date: 2026-07-19
- Residual-risk owner: Project owner

### Remediation history

| Wave/head | Changes | Verification | Result | Coverage invalidated |
| --- | --- | --- | --- | --- |
| 20260719-1712 | Rejected legacy single-key/config/type/schema/file paths, removed deprecated pipeline aliases and request-log retention alias, and updated tests | `make test`; config/persistence/profiling tests | Closed | Existing old state is rejected, not migrated |

### Closure/reopen

- Closure evidence: `docs/audit/runs/20260719-1712/EVIDENCE.md`; config/local-mode/admin/persistence/core changes; full deterministic suite.
- Residual risk: protocol compatibility remains intentionally supported; old Rosetta state/config is not recoverable by migration. A pair of private, unreachable historical mapping-migration definitions remains as cleanup debt and is not invoked by startup or runtime paths.
- Reopen trigger: any new Rosetta-version migration/compatibility path without an explicit profile decision.

---

## AUD-003 — Real-call runners lack a fail-closed developer-approval gate

- Severity: Should Plan
- Decision class: Agent-Fixable
- Status: Closed in targeted re-audit `20260720-1107` (original gate added in `20260719-1712`)
- Current state: every enumerated integration, relay, agentabi, and repository live-agent runner requires the shared exact approval marker before external work starts.
- Confidence: High
- First detected run: 20260719-1542
- Last updated run: 20260720-1107
- Owner: Project owner / live-test harness owner

### Quality attributes and profile requirements

- Affected attributes: Security, cost, operability, verification integrity.
- Profile/control requirement: Real Provider/Codex API calls are normal development behavior only after explicit developer approval; audit runs must never make real calls.
- Violated invariant/outcome: historical omission was that several live runners bypassed the approval boundary; the current entry-point inventory now fails closed before credentials and external endpoints.

### Failure, abuse, or structural path

```text
Stimulus/trigger: Agent or developer invokes a live/integration runner.
Environment/preconditions: Credentials/configuration are present; runner is reachable.
Path/components: scripts/run_gateway_integration.sh or tests/live_agent/*/run_live.py -> Codex/provider process/API.
Expected response: runner refuses unless an explicit one-shot opt-in/approval marker is present; deterministic tests remain network-free.
Observed or supported failure: scripts are directly executable; one live config sets approval_policy="never" and sandbox_mode="danger-full-access" for the isolated run; no in-harness human confirmation or fail-closed external-call gate exists.
```

### Impact and risk basis

- User/business/mission impact: accidental or autonomous runs can consume paid provider quota and produce unapproved real transcripts/tool side effects.
- Security/privacy/data/reliability impact: credentials and prompt/tool data cross the local harness boundary; evaluator evidence can be contaminated by unintended live state.
- Likelihood/exploitability: Medium; requires a runner invocation and credentials, but agent autonomy makes accidental invocation plausible.
- Blast radius: selected provider/Codex account and local run artifacts; no release secret path observed.
- Reversibility/recovery: API spend/transcript exposure cannot be fully undone.
- Systemic reach: all live/integration runners, not just one scenario.

### Scope and occurrences

| Component/path/symbol/workflow | Evidence | Why affected |
| --- | --- | --- |
| `scripts/run_gateway_integration.sh` | lines 21-40, 70-82 | default matrix and child scripts can invoke a running Gateway/upstream |
| `tests/live_agent/context_compaction/run_live.py` | lines 23-30, 72-90 | reads configured sources and builds a real Codex config |
| `tests/live_agent/deferred_tool_search/prepare_run.py` | lines 36-59, 68-96 | invokes `codex` in isolated run root and writes credentials/config |
| `Makefile` | `test` excludes integration but `test-integration`/`test-gateway` are callable | separation exists but approval is procedural, not mechanical |

### Evidence

- Code/configuration evidence: current scripts and `docs/dev/agent-tool-testing.md`.
- Test/scanner evidence: deterministic live configuration/fixture tests passed; no live run executed.
- Runtime/operations/incident evidence: explicitly unavailable by user policy.
- Contradicting evidence considered: `make test` excludes integration and current audit used only deterministic tests; this prevents accidental calls in this run but does not protect direct runner invocation.
- Gaps/assumptions: exact credential availability and developer workflow are intentionally not inspected/used.

### Recommended direction

- Smallest credible remediation/control: add a mandatory explicit opt-in variable/CLI flag with a clear approval value and fail closed in every runner; add deterministic tests that absent opt-in cannot spawn Codex/provider subprocesses or network clients. Keep audit profile commands on the no-live path.
- Rollout/migration/rollback implications: no impact to deterministic tests; developers must opt in per run/provider.
- Suggested priority: before autonomous agent execution or adding more live suites.

### Frozen acceptance criteria

- [x] Every audited real-call runner fails closed without explicit opt-in.
- [x] Approval marker is scoped to one run and does not expose secret values.
- [x] Deterministic tests prove the no-opt-in path performs no external call.
- [x] Live artifacts remain credential-free and ignored by Git.

### Human decision or risk acceptance

- Decision required: None; the user already approved the gate requirement.
- Options/consequences: enforce in runner code, or retain a procedural-only gate with residual spend/privacy risk.
- Decision: Owner authorized a mandatory fail-closed developer approval marker for live tests.
- Authority/date: 2026-07-19
- Residual-risk owner: Project owner

### Remediation history

| Wave/head | Changes | Verification | Result | Coverage invalidated |
| --- | --- | --- | --- | --- |
| 20260719-1712 | Added shared exact-marker gate before credentials/run roots/subprocesses and deterministic fail-closed tests | live configuration contract tests; `make test` | Closed | No real-call trajectory was run |
| 20260720-1107 | Extended the gate to every integration, relay, agentabi, and agent-launch entry point and re-audited ordering | full deterministic suite; live-call contract tests | Closed | No real-call trajectory was run |

### Closure/reopen

- Closure evidence: `docs/audit/runs/20260719-1712/EVIDENCE.md`; `gateway/live_gate.py`; live runner contract tests.
- Residual risk: approved development runs can still incur real API cost or side effects; audit continues to exclude them.
- Reopen trigger: any new external-call runner without the shared gate.

---

## AUD-005 — URL-authoritative provider option semantics were not enforced

- Severity: Should Plan
- Decision class: Needs Decision (decision now recorded)
- Status: Closed in targeted re-audit `20260720-1107` (original URL semantics fixed in `20260719-1712`)
- Current state: Admin saves only URL/protocol/key data; runtime derives the preset/custom presentation and shim from the URL, with unmatched URLs allowed as `custom`.
- Confidence: High
- First detected run: 20260719-1542
- Last updated run: 20260720-1107
- Owner: Project owner / Gateway product owner

### Quality attributes and profile requirements

- Affected attributes: Security, modifiability, operability, correctness.
- Profile/control requirement: provider vendor/variant is presentation-only; exact preset URL matches render the preset, unmatched URLs render `custom` and remain allowed within the local/LAN operator boundary.
- Decision boundary: resolved by owner on 2026-07-19; `api_type` remains the persisted transport protocol while URL is the provider-option authority.

### Failure, abuse, or structural path

```text
Stimulus/trigger: Admin/config supplies a custom or unknown provider entry/base URL.
Environment/preconditions: Admin-authenticated mutation or local config file.
Path/components: Admin provider UI -> GatewayConfig provider resolution -> build_provider_info unknown fallback -> ProviderInfo URL/auth.
Expected response: behavior matches an explicit preset-only policy: reject unsupported provider identity/endpoint, or document and test the override as supported.
Observed or supported failure: UI exposes `Custom`; config accepts unknown types; provider factory falls back to Bearer auth and generic `{base_url}/` URL template.
```

### Impact and risk basis

- User/business/mission impact: supported surface is broader than profile, making compatibility/test and support claims ambiguous.
- Security/privacy/data/reliability impact: arbitrary endpoint selection can send configured provider credentials and prompt traffic directly to the selected URL; automatic HTTP redirects are now prohibited. This is an Admin/misconfiguration path, not anonymous SSRF under the current boundary.
- Likelihood/exploitability: Medium for operator error or compromised Admin; low for unauthenticated clients.
- Blast radius: provider credential and prompt traffic for the configured route.
- Reversibility/recovery: config can be changed, but accidental egress may already expose data/credentials.
- Systemic reach: registry, config parser, Admin UI, docs, and tests.

### Scope and occurrences

| Component/path/symbol/workflow | Evidence | Why affected |
| --- | --- | --- |
| `gateway/providers.py:build_provider_info` | lines 130-144 | unknown/custom provider gets generic Bearer/URL fallback |
| `gateway/admin/admin.html` | lines 1310-1323 | explicit Custom vendor and custom variants are user-visible |
| `gateway/config.py` | lines 402-419 | provider/API type/shim fallback resolution accepts name/type forms |

### Evidence

- Code/configuration evidence: current provider factory/config/admin UI.
- Test/scanner evidence: provider/config/admin tests pass and therefore confirm the behavior is intentional/current.
- Runtime/operations/incident evidence: no external call was made; no deployment exists.
- Contradicting evidence considered: the old baseline exposed a broader Custom surface without a documented source of truth; the remediation now documents and tests that custom URLs are intentionally allowed.
- Gaps/assumptions: no external egress/provider-quality test was run; those remain outside audit scope.

### Recommended direction

- Smallest credible remediation/control: use URL/protocol matching as the single runtime source of truth, keep exact preset matches selectable, and render unmatched URLs as `custom` without persisting vendor/variant metadata.
- Rollout/migration/rollback implications: prelaunch/no deployed data makes boundary tightening low-risk; no old config migration promise.
- Suggested priority: reopen only if the owner changes the custom endpoint policy or provider metadata becomes persisted.

### Frozen acceptance criteria

- [x] Product decision records that exact preset URL matches render preset options and unmatched URLs render allowed `custom`.
- [x] Provider `type`/`shim` metadata is not persisted as the source of routing truth; URL/protocol resolution is canonical.
- [x] Admin UI, docs, config handling, and tests use the same URL-authoritative semantics.
- [x] No external egress claim is made by this deterministic audit.

### Human decision or risk acceptance

- Decision required: No further decision for the approved semantics.
- Options/consequences: exact preset URLs render preset options; unmatched URLs render `custom` and remain allowed. This preserves operator flexibility while keeping URL authoritative.
- Decision: URL is authoritative; `api_type` remains the transport protocol field because one URL may serve Chat or Responses.
- Authority/date: 2026-07-19
- Residual-risk owner: Project owner

### Remediation history

| Wave/head | Changes | Verification | Result | Coverage invalidated |
| --- | --- | --- | --- | --- |
| 20260719-1712 | Removed persisted vendor/variant writes, derived shims from exact URL/protocol matches, and added custom URL tests | config/Admin tests; full deterministic suite | Closed | No external egress or provider-quality claim |
| 20260720-1107 | Aligned Admin profile derivation and recorded the custom HTTP(S) egress decision in the profile | full deterministic suite; provider/Admin contract tests | Closed | Custom egress remains owner-accepted local/LAN risk |

### Closure/reopen

- Closure evidence: `docs/audit/runs/20260719-1712/EVIDENCE.md`; `gateway/config.py`; Admin config route/UI tests.
- Residual risk: custom URLs are intentionally allowed within local/LAN operator scope; no public SSRF/account-security claim is made.
- Reopen trigger: owner changes custom endpoint policy or any code persists provider option metadata.

---

## AUD-006 — Live-call approval gate did not cover every real-call entry point

- Severity: Should Plan
- Decision class: Agent-Fixable
- Status: Closed in omission-remediation re-audit `20260720-1239`
- First detected run: `20260719-1802`
- Last updated run: `20260720-1239`
- Owner: Project owner / live-test harness owner

### Failure and closure

The omission audits found SDK/REST E2E, agentabi, relay, agent-launch paths, and later all 24 executable examples could reach credentials, subprocesses, or network clients without the shared gate. The remediation added the exact-marker fail-closed gate to every entry point before sensitive work. Example coverage is directory-discovered so a newly added script cannot silently fall outside a static list.

- Closure evidence: `35521ab`; `scripts/require_live_call_approval.sh`; `src/codex_rosetta/gateway/live_gate.py`; all live/integration/example entry points; `tests/live_agent/test_live_agent_configuration_contract.py`.
- Residual risk: an approved development run can still incur real API cost or side effects; audit runs remain deterministic-only.
- Reopen trigger: any new real-call runner without the shared gate.

## AUD-007 — Admin profile derivation depended on stripped provider metadata

- Severity: Should Plan
- Decision class: Agent-Fixable
- Status: Closed in targeted re-audit `20260720-1107`
- First detected run: `20260719-1802`
- Last updated run: `20260720-1107`
- Owner: Gateway/Admin owner

### Failure and closure

The Admin API strips presentation-only provider metadata, while the UI still attempted to read it when selecting a tool profile. The API now returns runtime-derived `default_tool_profile` and validation state; the UI renders those fields and uses URL/protocol semantics without writing provider options back to config.

- Closure evidence: `gateway/admin/routes/config.py`, `gateway/admin/admin.html`, i18n labels, and Admin/config contract tests.
- Residual risk: browser and deployed LAN behavior remain unexercised in this audit.
- Reopen trigger: changing the Admin response contract or persisting provider presentation options.

## AUD-008 — Audit ledgers contained contradictory closure and rotation state

- Severity: Should Plan
- Decision class: Agent-Fixable
- Status: Closed in omission-remediation re-audit `20260720-1239`
- First detected run: `20260719-1802`
- Last updated run: `20260720-1239`
- Owner: Audit owner

### Failure and closure

`FINDINGS.md`, `COVERAGE.md`, the approved profile, README, and prior run text disagreed with current code and owner decisions. This run reconciles status tables, evidence links, coverage freshness, control baseline, system-map notes, and the rotation queue against exact code head `804efef`.

- Closure evidence: this ledger set and `docs/audit/runs/20260720-1239/`.
- Residual risk: ledger correctness is repository-local and depends on future runs preserving the same reconciliation step.
- Reopen trigger: a future remediation run leaves contradictory persistent statuses.

## AUD-009 — Missing `api_type` runtime fallback semantics

- Severity: Should Plan
- Decision class: Decision Recorded
- Status: Closed in omission-remediation re-audit `20260720-1239`
- First detected run: `20260719-1802`
- Last updated run: `20260720-1239`
- Owner: Project owner / Gateway config owner

### Decision and closure

Owner decision superseding the `20260720-1107` conclusion: missing `api_type` is not invalid. Runtime compares the authoritative URL against preset protocol URLs and selects the first supported protocol in `responses`, `chat`, `anthropic`, `google` order. An unmatched custom URL defaults to `responses`. Each active provider emits a terminal warning once per config load; Admin renders the inferred value. Neither the input dictionary nor the config file is written back.

- Closure evidence: `804efef`; `gateway/config.py`; Admin config route; config/Admin tests covering preset/custom selection, warning count, Tool Profile derivation, and no write-back.
- Residual risk: an unmatched or mistyped custom URL defaults to Responses until the operator corrects the URL or declares `api_type`; no compatibility migration layer is introduced.
- Reopen trigger: changing protocol order, URL-authority, warning behavior, or inferred-value persistence.

## AUD-010 — SQLite schema validation omitted complete index attributes

- Severity: Should Plan
- Decision class: Agent-Fixable
- Status: Closed in omission-remediation re-audit `20260720-1239`
- First detected run: `20260719-1802`
- Last updated run: `20260720-1239`
- Owner: Persistence owner

### Failure and closure

Startup validation checks expected column names/types, NOT NULL flags, primary-key positions, and required index names, column order, uniqueness, SQLite origin, and partial-index flag. Incompatible existing schemas fail closed before runtime writes; focused tests cover missing primary key, wrong columns, unique indexes, and partial indexes.

- Closure evidence: `ec8419b`; `observability/persistence.py`; `tests/gateway/test_persistence_sqlite.py`.
- Residual risk: no restore, deployment, or long-run disk stress evidence.
- Reopen trigger: schema/table/index changes without updated validation and tests.

## AUD-011 — Arbitrary HTTP(S) custom URL egress requires an owner boundary decision

- Severity: Should Plan
- Decision class: Decision Recorded
- Status: Direct-egress risk accepted; redirect scope narrowed in `20260720-1239`
- First detected run: `20260719-1802`
- Last updated run: `20260720-1239`
- Owner: Project owner

### Decision and residual risk

Owner decision: arbitrary unmatched HTTP(S) custom URLs are allowed and may receive configured upstream API keys. This is accepted only for the declared local/trusted-LAN deployment boundary. Redirects are not part of that acceptance and are always prohibited. The profile and system map state the remaining direct SSRF/egress and key-disclosure risk; no public deployment, account-security, or preset-only egress guarantee is claimed.

- Decision evidence: `docs/audit-profile.md`, `docs/audit/SYSTEM-MAP.md`, and `docs/audit/runs/20260720-1239/REPORT.md`.
- Reopen trigger: any public deployment/security claim or change to custom URL policy.

## AUD-012 — Upstream redirects could expand credential egress

- Severity: Must Fix
- Decision class: Agent-Fixable
- Status: Closed in omission-remediation re-audit `20260720-1239`
- First detected run: `20260720-1239`
- Last updated run: `20260720-1239`
- Owner: Gateway transport owner

### Failure and closure

The shared upstream client allowed redirects, so a configured endpoint could respond with a redirect and cause a second request carrying provider authorization outside the configured URL boundary. The client now sets `max_redirects=0`; every 301/302/303/307/308 fails before a target request is sent. A two-server loopback test verifies the redirect target receives no request.

- Closure evidence: `477fa00`; `gateway/transport/http/client_pool.py`; `tests/gateway/test_http_transport_limits.py`.
- Residual risk: the operator-approved direct custom URL and configured proxy still receive the credential; DNS rebinding and proxy behavior were not live-tested.
- Reopen trigger: any client/transport change that permits automatic redirect following.

## AUD-004 — Mutable build inputs and missing artifact provenance are accepted release debt

- Severity: Track as Debt
- Decision class: Needs Decision
- Status: Risk Accepted
- Confidence: High
- First detected run: 20260719-1542
- Last updated run: 20260719-1542
- Owner: Project owner

### Quality attributes and profile requirements

- Affected attributes: Security, operability, supply chain, modifiability.
- Profile/control requirement: manual GitHub Release only; no current signing/SBOM/provenance guarantee; revisit before any stronger public release/security claim.
- Violated invariant/outcome: none under the current explicitly limited pre-release commitment; artifact integrity is weaker than a mature release baseline.

### Failure, abuse, or structural path

```text
Stimulus/trigger: Build or manual release resolves mutable external action/base/dependency inputs.
Environment/preconditions: CI or local release build.
Path/components: Actions major tags, pip latest/unlocked optional dependencies, Docker base tag, manual artifact handling.
Expected response: future stronger release baseline pins/verifies inputs and records provenance.
Observed or supported failure: current controls do not provide immutable digest pinning, lockfile, SBOM, signature, or attestation.
```

### Impact and risk basis

- User/business/mission impact: a compromised/mutated build input could alter a manually released artifact.
- Security/privacy/data/reliability impact: supply-chain compromise can affect credentials and all gateway users; no automated publish path reduces immediate blast radius.
- Likelihood/exploitability: Low-to-medium; depends on external tag/index compromise.
- Blast radius: CI artifacts/manual release output.
- Reversibility/recovery: manual release withdrawal/rebuild; no signing claim.
- Systemic reach: CI, Docker, pyproject optional dependencies and release process.

### Evidence

- `.github/workflows/ci.yml` uses `actions/checkout@v6` and `actions/setup-python@v6`; SDK monitor upgrades SDKs to latest and uses `actions/github-script@v9` with `issues: write`.
- `docker/Dockerfile` uses `python:3.14.6-alpine` tag and resolves gateway/profiling dependencies at build time.
- `pyproject.toml` has no lockfile/provenance/signing/SBOM control; Makefile disables automated package/Docker push.
- Local lint/test/build/contract/release checks pass.

### Recommended direction

- Smallest credible remediation/control: define a release integrity baseline (digest-pinned Actions/base, dependency lock or verified constraints, SBOM, provenance/signing and review ownership) before claiming it.
- Rollout/migration/rollback implications: changes release process only; no runtime migration.
- Suggested priority: before first public release or external security claim.

### Frozen acceptance criteria

- [ ] Manual release remains the only publication path unless explicitly changed.
- [ ] External build inputs have an owner and immutable verification policy.
- [ ] Artifact provenance/signing/SBOM requirement is either implemented or explicitly risk-accepted with a review trigger.

### Human decision or risk acceptance

- Decision required: none for current pre-release operation; stronger release controls are deferred by profile.
- Decision: Risk accepted until first public/stronger release claim.
- Authority/date: Project owner / 2026-07-19
- Residual-risk owner: Project owner

### Remediation history

| Wave/head | Changes | Verification | Result | Coverage invalidated |
| --- | --- | --- | --- | --- |
| None | No remediation authorized | local deterministic gates pass | Risk Accepted | — |

### Closure/reopen

- Closure evidence: not applicable; this is accepted debt, not a resolved finding.
- Residual risk: mutable supply-chain inputs and absent provenance remain.
- Reopen trigger: public release, production deployment, signing/SBOM promise, or CI permission expansion.
