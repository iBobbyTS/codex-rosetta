# Audit Scope

Run: `20260721-2248`
Mode: AUD-025 targeted remediation and phase-separated adversarial verification
Repository baseline: working tree after `0f26285`
Real API/provider/Codex calls: prohibited; none executed

## Scope

- Final source-consumer credential identity after Chat, Anthropic, or Google to
  IR to Responses stream conversion.
- Ordering relative to phase buffering, web-search control, trace, and SSE
  serialization.
- Text and reasoning reconstruction, direct Responses regressions, state bounds,
  and normal/failure/cancellation/early-close lifecycle cleanup.
- Compatibility ledgers for CP-02 and CP-17.

## Exclusions

No live provider, Codex, Tavily, deployment, external sink, public-network,
availability, recovery, or covert-encoding evidence was collected.
