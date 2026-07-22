# Audit Scope

Run: `20260721-2035`
Mode: Targeted remediation re-audit
Repository head: `51f3b2d569f722f7f8c039a451b898ec65231b7f`
Authorized remediation: Yes, limited to reopened `AUD-025`
Real API calls: prohibited; none executed

## Scope selection

| Slice | Selection reason | Review depth |
| --- | --- | --- |
| Responses text-delta identity | `20260721-2008` proved that optional wire IDs discarded by Codex split one consumer-visible stream across gate buffers | exact implementation trace against the current local Codex consumer |
| Raw and parsed credential gates | Both paths released the frozen counterexamples | adversarial fake-transport regressions for all three affected events |
| State lifecycle and bounds | The repair introduces active-item generation and consumer-specific identities | isolation, capacity, completion, failure, cancellation, EOF, and explicit-close tests |
| Compatibility ownership | The repair changes a Codex-facing semantic boundary | CP-02/source-map reconciliation and compatibility script |

## Affected coverage

`PROVIDER-01`, `STREAM-01`, `SCN-03`, `SCN-04`, and `CTRL-03`.

## Frozen acceptance criteria

1. Each supported Responses text delta is partitioned by the identity Codex
   actually retains and concatenates: active item, plus `summary_index` or
   `content_index` where applicable.
2. Wire fields ignored by that consumer cannot allocate a new identity buffer.
3. Raw and parsed paths reject all three changing-ignored-ID counterexamples
   before releasing the completing fragment.
4. Separate active items and retained indices remain isolated; state is bounded
   and cleared on completion, failure, cancellation, EOF, and explicit close.
5. Focused and full deterministic checks pass without a real API call.

## Exclusions

- No provider, Codex, Tavily, MCP, live-agent, integration-live, deployment, or
  public-network call.
- No availability, recovery, external-sink, provider-quality, timing, or covert-
  encoding claim.
- No rescan of unchanged persistence, Admin, release, or non-Responses converter
  surfaces.
