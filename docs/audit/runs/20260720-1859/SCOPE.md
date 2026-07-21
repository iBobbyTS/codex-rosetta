# Audit Run Scope

Run: `20260720-1859`
Mode: Periodic / fifth independent omission audit
Repository range/head: current `6d1bc7affdb02c3c928c84ee49b321011363aea4`
Profile and status: `docs/audit-profile.md` (Approved)
Resource/budget constraints: deterministic local source, fake-response, and focused-test evidence only
Authorized remediation: No

## 1. Scope Selection Summary

| Scope item | Reason | Criticality | Quality attributes | Scenarios | Expected evidence | Planned depth |
| --- | --- | --- | --- | --- | --- | --- |
| Exact configured-credential return redaction | changed/high-churn, invalidated, finding follow-up | Critical | correctness, security, interoperability | SCN-03, SCN-04 | accepted credential domain, raw SSE behavior, parsed/raw redaction code, existing tests | source trace plus deterministic probe |
| Admin upstream model discovery response validation | rotating, trust-boundary follow-up | High | reliability, security, operability | SCN-08, SCN-09 | JSON root/member validation and controlled error behavior | source trace plus fake-response probe |
| Durable audit conclusions after `6d1bc7a` | profile gap, invalidated | Critical | audit integrity, maintainability | all affected coverage | current HEAD reconciliation | ledger update only |

## 2. Changed and Invalidated Surface

| Change/component | Semantic class | Dependent coverage/scenarios | Invalidation result | Rationale |
| --- | --- | --- | --- | --- |
| `SecretRedactor` exact string/byte replacement used by `CredentialRedactingTransport` | credential-return security control | PROVIDER-01, SIDE-01, SCN-03, SCN-04, CTRL-03 | Invalidated | current accepted credential domain includes short/common strings that can overlap protocol syntax and legitimate payload content |
| Admin `fetch_upstream_models` redacts parsed JSON before normalizing it | untrusted upstream schema boundary | AUTH-02, SCN-08, SCN-09 | Invalidated/Partial | syntactically valid non-object JSON or non-object list members escape the route's controlled error handling |

## 3. Always-On Critical Scenarios

| Scenario | Why required now | Evidence target |
| --- | --- | --- |
| SCN-03 / SCN-04 provider response and SSE preservation | the new return redactor sits directly on the critical downstream protocol path | prove configured credentials cannot silently corrupt framing or JSON semantics |
| SCN-08 Admin provider/model operation | model discovery consumes untrusted provider data under Admin authority | prove malformed upstream shapes produce a bounded Admin response rather than an uncaught exception |

## 4. Rotating Deep Slices

| Area | Last reviewed | Why selected | Planned boundary |
| --- | --- | --- | --- |
| Return redaction semantics, not only secret absence | `20260720-1606` | prior verification asserted non-secret preservation but sampled only long unique tokens | credential validation through parsed/raw/SSE output |
| Admin model-discovery schema normalization | `20260720-1606` | prior pass checked credential reflection but not adversarial JSON shapes | HTTP JSON parse through normalized model list/error response |

## 5. Incident, Finding, and Debt Follow-up

| Item | Trigger/evidence | Planned verification |
| --- | --- | --- |
| AUD-015 closure assumptions | current exact-value implementation can change unrelated protocol bytes | open a separate finding rather than altering historical closure evidence |
| GP-003 | enforcement proposal treats all exact matches as safely replaceable | mark for recalibration pending AUD-017 decision |

## 6. Exclusions

| Area | Reason excluded | Residual risk | Next review trigger |
| --- | --- | --- | --- |
| Real provider, Codex, sidecar, or Tavily calls | prohibited in audit; no developer approval supplied | live encodings and provider-specific behavior remain unknown | separately approved development evidence |
| Remediation implementation | not authorized | findings remain Open | owner decision for AUD-017 and explicit remediation authorization |
| Unchanged converter, persistence, release, and live-runner surfaces | no dependent invalidation found in this pass | retained prior sampling limits | corresponding code/profile change |

## 7. Material Assumptions and Decisions Needed

- AUD-017 requires the owner to choose the supported credential domain or relax the absolute exact-reflection/no-content-change combination. The current code cannot distinguish a short secret occurrence from identical legitimate protocol/content bytes.
- AUD-018 does not require new product semantics: untrusted upstream JSON should fail as a controlled Admin error.

## 8. Stop Criteria for This Run

- [x] Every scoped item has evidence and outcome.
- [x] Required scenarios are exercised or explicitly blocked.
- [x] Persistent ledgers are updated.
- [x] Report states gaps and next priorities.
