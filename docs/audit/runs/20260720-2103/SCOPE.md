# Audit Run Scope

Run: `20260720-2103`
Mode: `Periodic`
Repository range/head: `origin/main@da6d108..99218427824047a416030675c19c9ba4908925ac`; current worktree clean on `main`, which is eight commits ahead of `origin/main`
Profile and status: `docs/audit-profile.md`, `Approved`
Resource/budget constraints: deterministic local evidence only; no real Codex/provider API calls, deployment, GitHub-setting inspection, or production evidence
Authorized remediation: No during independent discovery; the owner later authorized separate remediation commits for AUD-019 and the AUD-020 decision contract

## 1. Scope Selection Summary

| Scope item | Reason | Criticality | Quality attributes | Scenarios | Expected evidence | Planned depth |
| --- | --- | --- | --- | --- | --- | --- |
| Configured-credential return boundary across primary proxy, Admin model discovery/test, Codex auxiliary endpoints, web-run/search, transport exceptions, logs, and traces | `changed/high-churn`, `invalidated`, `always-on critical` | Critical | Security, correctness, reliability | A configured credential is reflected in JSON, text, bytes, SSE, headers, exception text, or a cleanup/fallback path | Current call graph, source traces, adversarial deterministic tests, relevant existing tests | Deep end-to-end slice |
| Exact-token collision handling and response-protocol integrity | `changed/high-churn`, `always-on critical` | Critical | Security, correctness | Short, overlapping, escaped, split-chunk, status/header, or structurally significant credential values are reflected upstream | Boundary tests with meaningful JSON/SSE/error oracles; source inspection of collision/fail-closed behavior | Deep |
| Outbound-network and return-path completeness | `rotating`, `profile gap`, `finding/debt follow-up` | High | Security, maintainability | A network call or response-return site bypasses the central credential-return policy | Repository-wide inventory of HTTP/provider clients and downstream/Admin response constructors, cross-checked against the central policy | Broad discovery plus targeted deep checks |
| Live-call approval boundary across repository-local runners | `always-on critical`, `agent/harness/tooling`, `changed/high-churn` | High | Cost, security, evidence integrity | A test, script, CLI helper, or agent harness can make a real provider call without the exact approval marker | Entrypoint inventory, static trace, deterministic subprocess/contract checks only | Representative full entrypoint inventory |
| One rotating non-Codex conversion edge | `rotating` | Medium | Correctness, interoperability | Provider-specific content or tool data crosses a non-Codex converter edge with silent corruption | One representative converter/shim path and its tests | Targeted sample |

## 2. Changed and Invalidated Surface

| Change/component | Semantic class | Dependent coverage/scenarios | Invalidation result | Rationale |
| --- | --- | --- | --- | --- |
| `gateway/transport/credential_redaction.py`, `observability/redaction.py` | Security boundary, shared policy | Credential confidentiality, JSON/SSE correctness, logs/traces | Invalidated until re-evidenced | New cross-cutting redaction and collision behavior affects nearly every upstream return path |
| `gateway/proxy.py`, Admin config/model discovery, auxiliary/search/sidecar paths | Routing, transport, Admin operations | Primary request path, operator test/discovery, auxiliary tools | Invalidated until traced | Callers now own fail-closed handling and downstream error mapping |
| HTTP redirect and provider metadata/config changes | Configuration and trust boundary | Provider egress, credential destination, model discovery | Targeted confirmation required | Redirect and URL semantics determine where credentials may travel and return |
| Live runner guard changes | Agent/harness/tooling | No accidental live calls during audit/test | Targeted confirmation required | A missed entrypoint weakens the audit evidence boundary and may incur real cost |

## 3. Always-On Critical Scenarios

| Scenario | Why required now | Evidence target |
| --- | --- | --- |
| Authenticated `/v1/responses` request returns provider output without configured credentials and without silently corrupting SSE/JSON | Highest-profile security/correctness path and directly changed | Proxy/transport call trace plus deterministic response fixtures |
| Admin model discovery/test cannot return or persist provider credentials | Privileged operator surface with provider network access | Route/task cleanup trace and tests |
| Logs, stream traces, error dumps, and metrics do not retain configured credentials | Crown-jewel confidentiality requirement | Exact-value redactor call graph and persistence/log tests |
| No audit/test runner performs a real call without exact developer approval marker | Approved profile hard control | Entrypoint inventory and local contract checks |

## 4. Rotating Deep Slices

| Area | Last reviewed | Why selected | Planned boundary |
| --- | --- | --- | --- |
| Outbound HTTP/provider call inventory | Not accepted from prior summaries; current evidence required | Cross-cutting credential policy is only as strong as its least-covered caller | All repository-owned network clients and return constructors, excluding vendored code |
| Representative non-Codex converter | Current evidence required | Profile requires one non-Codex conversion edge per audit | Select one tool/content path after current map inspection |

## 5. Incident, Finding, and Debt Follow-up

Prior reviewer findings are deliberately not used as discovery hypotheses. After independent discovery, candidate root causes will be deduplicated against the persistent ledger only to preserve stable IDs.

## 6. Exclusions

| Area | Reason excluded | Residual risk | Next review trigger |
| --- | --- | --- | --- |
| Real provider/Codex calls and provider quality | Explicitly prohibited by approved audit profile | Live response variants and external behavior remain Unknown | Developer-authorized development validation |
| Public-internet deployment, production operations, HA, backup/restore, DR, RTO/RPO | Outside approved supported boundary | No claim beyond local/trusted-LAN behavior | Profile or deployment-boundary change |
| GitHub branch protection, release environment, and external registry settings | Not locally authoritative/available | Supply-chain controls remain Partial | External settings access or release review |
| `_vendor/**` internals | Managed externally and must not be edited; audit only repository-owned wrappers | Vendored implementation defects are not exhaustively reviewed | Dependency update, advisory, or wrapper failure |
| Full converter matrix | Periodic risk sampling | Unselected converter edges remain at prior/Unknown freshness | Next rotation or converter change |

## 7. Material Assumptions and Decisions Needed

- The approved local/trusted-LAN profile, arbitrary configured HTTP(S) provider URLs, token-only redaction semantics, and no minimum credential length are treated as authoritative requirements for this run.
- No implementation semantics will be chosen by the auditor. Any newly discovered ambiguity that affects remediation will be classified `Needs Decision`.

## 8. Stop Criteria for This Run

- [x] Every scoped item has evidence and outcome.
- [x] Required scenarios are exercised or explicitly blocked.
- [x] Candidate findings are deduplicated against the persistent ledger without relying on prior rationalizations.
- [x] Persistent ledgers are updated.
- [x] Report states gaps and next priorities.
