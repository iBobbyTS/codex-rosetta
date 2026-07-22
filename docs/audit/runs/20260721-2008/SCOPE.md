# Audit Scope

Run: `20260721-2008`
Mode: Periodic supplementary omission audit
Repository head: `c2db61e434c59bacc0f57d2e8c1286f16658d1d4`
Starting worktree: clean; `main` four commits ahead of `origin/main`
Authorized remediation: No
Real API calls: prohibited; none executed

## Scope selection

| Slice | Selection reason | Review depth |
| --- | --- | --- |
| Responses credential stream semantics | Always-on critical return boundary changed in four commits after the last recorded re-audit | source trace plus adversarial raw/parsed fake-transport probes |
| Codex Responses event consumers | The safety gate must use the identity that the only supported downstream actually consumes | exact local Codex source trace for parsing and active-item dispatch |
| Regression oracle quality | Existing tests remained green after the counterexample was found | focused transport/Responses suite plus missing-oracle analysis |
| Persistent audit state | Current findings and coverage still referred to the prior remediation head | reconcile `FINDINGS.md`, `COVERAGE.md`, and `SYSTEM-MAP.md` |

The same independent subagent from the interrupted supplementary run performed
the discovery pass. Its reporting turn stalled after it sent the root-cause
evidence, so the primary agent stopped it without file changes and independently
reproduced the finding before recording this run.

## Scenarios and expected controls

| Scenario | Expected response |
| --- | --- |
| SCN-03 | No active-provider credential crosses the Responses return boundary through fields that Codex reconstructs. |
| SCN-04 | Raw and parsed SSE paths use the same downstream-consumer identity, retain bounded state, and block a credential before its completing fragment is released. |
| CTRL-03 | The active-client credential gate preserves credential-free protocol data while failing closed on a reachable credential reconstruction. |

## Exclusions

- No provider, Codex, Tavily, MCP, live-agent, integration-live, or deployment call.
- No product-code remediation, commit, release, browser/LAN, or public-deployment verification.
- No availability, recovery, provider-quality, external-sink, or covert-encoding claim.
- Unchanged persistence, Admin, release, and non-Responses converter surfaces were not rescanned.

## Evidence required for completion

- A current source path proving which event fields Codex retains and concatenates.
- A deterministic raw and parsed SSE counterexample using only fake transports and a dummy credential.
- Stable finding deduplication, classification, acceptance criteria, and bounded coverage invalidation.
- An explicit statement of whether an owner business decision is required.
