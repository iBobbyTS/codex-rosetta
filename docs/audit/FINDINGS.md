# Persistent Audit Findings and Debt

Last updated: 2026-07-19
Repository head: `0caa7a1308452100e553c9e1e3411b9a9f0a0746`
Profile: `docs/audit-profile.md` (Approved)

## Conclusion ownership

This section separates the current conclusions by who may authorize the next
step. It does not authorize remediation; the current baseline explicitly
recorded `Authorized remediation: No`.

### Logic/control issues I can repair directly

| ID | Conclusion | Direct repair boundary |
| --- | --- | --- |
| AUD-002 | Compaction replacement persistence has no aggregate row/byte quota | Add bounded, transactional persistence controls and regression tests; exact limits can be proposed within the approved local/LAN risk profile. |
| AUD-001 | Rosetta-version migration and legacy paths conflict with the no-migration boundary | Inventory protocol compatibility separately, then remove or reject unsupported internal migration paths and add guard tests. |
| AUD-003 | Real-call runners lack a fail-closed developer-approval gate | Add an explicit opt-in gate and deterministic tests proving no external-call subprocess/client starts without it. |

### Business/semantic decisions you must make

| ID | Decision required | Why it cannot be inferred safely |
| --- | --- | --- |
| AUD-005 | Whether a preset provider may use a custom endpoint, and whether unknown provider identities are rejected | This changes the supported upstream surface, credential-egress policy, UI/config semantics, and compatibility promise. |
| AUD-004 | Whether to adopt stronger artifact-integrity controls such as digest pinning, SBOM, provenance, and signing before a public release or stronger security claim | Manual release and the current pre-release risk acceptance are explicit product policy; stronger guarantees require an owner decision. |

The remaining `No Action`, deterministic-only, and excluded-runtime statements
are evidence status or explicit scope limits, not additional remediation
findings. They must not be presented as live-production or provider-quality
claims.

## Open Findings

| ID | Severity | Decision class | Status | Root cause | Affected scenarios/areas | Owner/decision | Due/revisit trigger |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AUD-002 | Must Fix | Agent-Fixable | Open | Codex compaction replacement persistence has TTL but no aggregate row/byte/replacement-size quota | SCN-06, SCN-07; persistence/observability | Project owner / Gateway persistence owner | Before first supported internal deployment or any live compaction use |
| AUD-001 | Should Plan | Agent-Fixable | Open | Rosetta-version config/state/API migration and legacy compatibility paths remain after prelaunch no-migration decision | SCN-08, SCN-06, DATA-03; config/local mode/admin/persistence/core API | Project owner / core and gateway owners | Before claiming the no-migration boundary is implemented |
| AUD-003 | Should Plan | Agent-Fixable | Open | Real-call integration/live runners lack a fail-closed developer-approval gate | SCN-11; scripts/live-agent/agent control plane | Project owner / test-harness owner | Before agent-autonomous test execution or broader live-test use |
| AUD-005 | Should Plan | Needs Decision | Open | Runtime/Admin expose arbitrary custom/unknown provider fallback beyond approved preset-provider boundary | SCN-09; provider/config/Admin UI | Project owner must decide custom endpoint policy | Before first release/support claim for provider surface |

## Closed Findings

| ID | Closed in run/head | Closure evidence | Residual risk | Reopen trigger |
| --- | --- | --- | --- | --- |
| None | — | — | — | — |

## Accepted Debt and Risk

| ID | Owner | Why acceptable now | Safety ceiling | Mitigations/monitoring | Revisit trigger/date | Expected resolution |
| --- | --- | --- | --- | --- | --- | --- |
| AUD-004 | Project owner | Project is pre-release, manual-release-only, and makes no signing/SBOM/provenance guarantee yet | No public supply-chain/security claim; no automated package/image publication | manual tag/version gate; local build from current checkout; CI Docker secret checks; disabled push targets | Before first public release or stronger artifact-integrity claim | Pin/verify build inputs and define provenance/SBOM/signing policy |

## Golden-Principle Candidates

| GP ID | Recurring issue/invariant | Evidence occurrences | Proposed enforcement | False-positive/maintenance risk | Owner | Status |
| --- | --- | --- | --- | --- | --- | --- |
| GP-001 | Real provider/Codex calls require explicit human approval and are never part of audit/default deterministic checks | `Makefile` separates integration; live scripts invoke real calls without a gate; user policy requires approval | mandatory opt-in environment/CLI gate that fails closed, plus deterministic test asserting no opt-in means no network | Could make intentionally approved live runs more verbose; keep gate scoped to external-call runners | Project owner | Candidate |
| GP-002 | Every durable agent/gateway state store needs an explicit owner scope and aggregate byte/row/TTL bound | tool mappings have quotas; compaction mappings have TTL but no quota | shared persistence quota contract and tests for row/bytes/TTL/cleanup | Tuning limits across protocol scenarios; contract must be explicit | Gateway persistence owner | Candidate |

## Candidate Disposition

| Candidate | Run/area | Disposition | Evidence/reason |
| --- | --- | --- | --- |
| Reuse old audit `FULL.md` status | UNIT-001 | Rejected | old head/profile and missing durable ledgers invalidate freshness |
| Treat no deployment as no security scope | UNIT-001/002 | Rejected | local/LAN auth, secrets, principal isolation and untrusted provider content remain in scope |
| Treat all `legacy` strings as one defect | UNIT-004 | Rejected | current Codex/provider protocol compatibility is distinct from Rosetta-version migration; inventory must separate them |

---

## AUD-002 — Compaction replacement persistence has no aggregate quota

- Severity: Must Fix
- Decision class: Agent-Fixable
- Status: Open
- Confidence: High
- First detected run: 20260719-1542
- Last updated run: 20260719-1542
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
- Architecture/history evidence: tool-mapping quota controls were added, while compaction mapping storage remains TTL-only.
- Contradicting evidence considered: seven-day expiry and request/upstream limits may bound individual summaries; they do not establish an aggregate row/byte ceiling for the table.
- Gaps/assumptions: exact upstream response size limit and operator filesystem capacity were not live-exercised.

### Recommended direction

- Smallest credible remediation/control: add explicit maximum replacement bytes and per-principal/global row/byte quotas using the same fail-closed pattern as encrypted tool mappings; ensure cleanup and quota accounting are transactional.
- Rollout/migration/rollback implications: no migration compatibility layer is promised; new limits can reject new mappings while allowing existing TTL cleanup. Add tests for per-principal/global overage and oversized one-row input.
- Suggested priority: Must Fix before first supported internal deployment/live compaction use.

### Frozen acceptance criteria

- [ ] A single compaction replacement has a hard, tested byte limit.
- [ ] Per-principal and global row/byte quotas are enforced transactionally.
- [ ] Existing TTL cleanup remains fail-closed and does not bypass quotas.
- [ ] Original compaction scenario succeeds below limits and returns a bounded error above limits.
- [ ] Different API-key principals cannot consume or read each other’s mappings.
- [ ] Focused persistence/compaction tests and full deterministic suite pass.
- [ ] Persistent coverage and retention policy document the new bounds.

### Human decision or risk acceptance

- Decision required: None for the control shape; exact limits can be selected by the persistence owner within the profile.
- Options/consequences: add quota controls now, or explicitly accept local/LAN disk-growth risk until before first internal deployment.
- Decision: Not yet authorized for remediation.
- Authority/date: —
- Residual-risk owner: Project owner

### Remediation history

| Wave/head | Changes | Verification | Result | Coverage invalidated |
| --- | --- | --- | --- | --- |
| None | No remediation authorized | — | Open | — |

### Closure/reopen

- Closure evidence: None.
- Residual risk: TTL-only aggregate bound remains.
- Reopen trigger: any attempted fix without transactional quota tests or any new durable compaction store.

---

## AUD-001 — Internal migration and legacy compatibility paths conflict with the prelaunch boundary

- Severity: Should Plan
- Decision class: Agent-Fixable
- Status: Open
- Confidence: High
- First detected run: 20260719-1542
- Last updated run: 20260719-1542
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

- [ ] Every active `legacy`/`migration` path is inventoried with owner and classification.
- [ ] Current Codex/provider protocol compatibility aliases have explicit source-map entries and tests.
- [ ] Rosetta-version config/persistence/internal-API migration paths are removed or fail closed.
- [ ] No new compatibility migration layer can be added without an explicit profile decision.
- [ ] Full deterministic suite and targeted compatibility checks pass after the inventory/removal wave.

### Human decision or risk acceptance

- Decision required: None for the approved boundary; protocol-vs-internal classification must be documented during remediation.
- Options/consequences: remove internal migration now, or accept growing prelaunch complexity and future removal cost.
- Decision: Not yet authorized for remediation.
- Authority/date: —
- Residual-risk owner: Project owner

### Remediation history

| Wave/head | Changes | Verification | Result | Coverage invalidated |
| --- | --- | --- | --- | --- |
| None | No remediation authorized | — | Open | — |

### Closure/reopen

- Closure evidence: None.
- Residual risk: current compatibility aliases and migration paths remain.
- Reopen trigger: any new legacy path without ledger classification.

---

## AUD-003 — Real-call runners lack a fail-closed developer-approval gate

- Severity: Should Plan
- Decision class: Agent-Fixable
- Status: Open
- Confidence: High
- First detected run: 20260719-1542
- Last updated run: 20260719-1542
- Owner: Project owner / live-test harness owner

### Quality attributes and profile requirements

- Affected attributes: Security, cost, operability, verification integrity.
- Profile/control requirement: Real Provider/Codex API calls are normal development behavior only after explicit developer approval; audit runs must never make real calls.
- Violated invariant/outcome: The repository does not mechanically require the approval before a live runner can use credentials and external endpoints.

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

- [ ] Every real-call runner fails closed without explicit opt-in.
- [ ] Approval marker is scoped to one run and does not expose secret values.
- [ ] Provider/model selection is printed and requires developer confirmation where configured dynamically.
- [ ] Deterministic tests prove the no-opt-in path performs no external call.
- [ ] Live artifacts remain credential-free and ignored by Git.

### Human decision or risk acceptance

- Decision required: None; the user already approved the gate requirement.
- Options/consequences: enforce in runner code, or retain a procedural-only gate with residual spend/privacy risk.
- Decision: Not yet authorized for remediation.
- Authority/date: —
- Residual-risk owner: Project owner

### Remediation history

| Wave/head | Changes | Verification | Result | Coverage invalidated |
| --- | --- | --- | --- | --- |
| None | No remediation authorized | — | Open | — |

### Closure/reopen

- Closure evidence: None.
- Residual risk: direct live runner invocation can still make calls without a code-enforced approval marker.
- Reopen trigger: any new external-call runner without the shared gate.

---

## AUD-005 — Preset-only upstream boundary is not enforced or explicit

- Severity: Should Plan
- Decision class: Needs Decision
- Status: Open
- Confidence: High
- First detected run: 20260719-1542
- Last updated run: 20260719-1542
- Owner: Project owner / Gateway product owner

### Quality attributes and profile requirements

- Affected attributes: Security, modifiability, operability, correctness.
- Profile/control requirement: supported upstreams are providers from the bundled preset list; arbitrary custom/unknown upstreams are outside the supported commitment.
- Decision boundary: whether a custom base URL for a bundled provider is allowed as an operator override, versus whether all custom/unknown provider entries must be rejected.

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
- Security/privacy/data/reliability impact: arbitrary endpoint selection can redirect configured provider credentials and prompt traffic; this is an Admin/misconfiguration path, not anonymous SSRF under the current boundary.
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
- Contradicting evidence considered: custom variants may be intended for a bundled provider’s alternate endpoint; profile does not yet state this distinction.
- Gaps/assumptions: exact product meaning of “preset provider” for custom base URLs needs owner decision.

### Recommended direction

- Smallest credible remediation/control: decide and document one boundary; then either reject unknown/custom provider identities and add config/UI tests, or explicitly classify bundled-provider custom endpoints as supported and constrain/validate them.
- Rollout/migration/rollback implications: prelaunch/no deployed data makes boundary tightening low-risk; no old config migration promise.
- Suggested priority: before first release/support statement.

### Frozen acceptance criteria

- [ ] Product decision records whether bundled-provider custom base URLs are supported.
- [ ] Unsupported provider identities fail closed at one canonical config boundary.
- [ ] Credential egress tests cover approved and rejected endpoint classes.
- [ ] Admin UI, docs, config schema, and tests use the same provider source of truth.

### Human decision or risk acceptance

- Decision required: choose `preset identities only` or `preset identities plus explicitly supported custom endpoints`.
- Options/consequences: strict rejection reduces egress/support surface; allowing custom endpoints preserves flexibility but requires URL/credential policy and tests.
- Decision: Pending; no remediation performed.
- Authority/date: —
- Residual-risk owner: Project owner

### Remediation history

| Wave/head | Changes | Verification | Result | Coverage invalidated |
| --- | --- | --- | --- | --- |
| None | No remediation authorized | — | Open | — |

### Closure/reopen

- Closure evidence: None.
- Residual risk: runtime supports more provider shapes than approved profile explicitly promises.
- Reopen trigger: new provider/custom path without the canonical boundary decision.

---

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
