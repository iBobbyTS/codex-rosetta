# Audit Scope

Run: `20260721-2137`
Mode: Periodic supplementary omission audit
Repository head: `0f262852c0de91d2ec4eadd56e3894fced8c18f0`
Product-code baseline: `51f3b2d569f722f7f8c039a451b898ec65231b7f`
Working tree: clean at reconciliation
Branch: `main` (six commits ahead of `origin/main`)
Authorized remediation: No
Real API/provider/Codex calls: prohibited; none executed

The current repository head contains audit-ledger updates after the last
product-code remediation. The product behavior under review is therefore the
`51f3b2d` implementation, while this run records a fresh cross-format
consistency check against the current source and local Codex checkout.

## Scope Selection

| Slice | Selection reason | Review depth |
| --- | --- | --- |
| Cross-format credential semantic gate | The gate is a critical return boundary, and the prior `AUD-025` closure proved only native Responses event identities | Trace provider-wire identity through IR, source Responses serialization, and the Codex consumer |
| Gateway streaming reachability | A finding is actionable only if the wrapped gate is on the actual streaming proxy path | Follow `handle_streaming` through transport, pipeline, processor, and SSE emission |
| Chat, Anthropic, and Google siblings | Each provider has a distinct upstream text partition key that can be changed without changing the downstream active item | Compare gate keys, converter fields, source Responses accumulation, and consumer-visible identity |
| Offline failure oracle and test portfolio | Existing green tests may hold identities fixed and miss a cross-format collapse | Run a neutral canary probe and inspect provider redaction tests for the missing oracle |
| Durable ledgers and deduplication | The candidate may be a recurrence of the existing split-stream invariant | Reconcile to `AUD-025`; do not allocate a new ID unless the root cause is independent |

## Affected Coverage

`PROVIDER-01`, `STREAM-01`, `SCN-03`, `SCN-04`, and `CTRL-03`.

## Frozen Acceptance Criteria For Any Repair

1. For every converted text and reasoning field, the credential gate partitions
   fragments by the identity retained by the downstream source consumer after
   target -> IR -> source conversion.
2. Chat choice, Anthropic block, and Google candidate/part changes that do not
   create distinct downstream active streams cannot split one credential buffer;
   ambiguous metadata conflicts fail closed rather than release an unsafe
   fragment.
3. Fake-transport plus real `ConversionPipeline` regressions for all three
   provider families block the completing canary before formatted Responses SSE
   reaches the caller, in both parsed and raw paths where supported.
4. Distinct actual active items and retained reasoning indices remain isolated;
   all identity state is bounded and cleared on completion, EOF, failure,
   cancellation, iterator close, context-manager exit, and explicit close.
5. Direct Responses controls, tool-argument controls, collision-safe byte
   preservation, active-provider-only credential scope, and protocol-valid SSE
   behavior remain unchanged.
6. Focused and full deterministic tests, lint, and the Codex compatibility gate
   pass without a live provider, Codex, deployment, or external sink.

## Exclusions

- No product-code, test, configuration, generated asset, or `_vendor` changes.
- No provider, Codex, Tavily, MCP, live-agent, integration-live, deployment, or
  public-network call.
- No claim about real-provider timing, external sinks, covert encodings,
  availability, recovery, or public deployment.
- No rescan of unrelated persistence, Admin, release, or migration surfaces.
