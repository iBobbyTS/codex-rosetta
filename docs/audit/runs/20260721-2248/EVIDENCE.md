# Audit Evidence

Run: `20260721-2248`
Finding: `AUD-025`
Real API calls: none

## UNIT-001 - Pre-fix failure oracle

The new fake-transport regression passed real events through the gateway's real
`ConversionPipeline`. Before the repair, OpenAI Chat, Anthropic, and Google each
reconstructed `CANARY-ALPHA-BETA` in final Responses output. The exact targeted
command failed all three cases, proving the oracle was meaningful.

## UNIT-002 - Final consumer boundary

`ProviderCredentialOutputGate` reuses `ProviderCredentialSemanticGate` with the
source provider. `handle_streaming` creates it from only the active
`ProviderInfo` credentials. Every converted event is inspected after conversion,
web-search control, and phase buffering, but before final source-event trace and
SSE formatting. The original target-provider transport gate remains intact.

The final Responses gate therefore uses Codex active-item and retained-index
identity. Upstream Chat choice, Anthropic block, and Google candidate/part
changes cannot split one final text or reasoning consumer stream.

## UNIT-003 - Regression and lifecycle evidence

The provider-return suite reported `19 passed`. It covers cross-format text and
reasoning reconstruction for all three target providers and stable collision
errors without releasing the completing credential fragment. A recording final
gate proves cleanup on normal completion, inspection failure, and `aclose()`.
Existing semantic-gate tests retain the bounded identity, active-item isolation,
completion, failure, cancellation, EOF, context-exit, and explicit-close cases.

The affected focused cone reported `136 passed`. A separate post-implementation
adversarial selection reported `14 passed, 87 deselected` for cross-format,
final-output-gate, Codex identity, bounds, and isolation cases.

## UNIT-004 - Repository gates

- `make lint`: passed, including ruff, format, ty, and complexity ratchet.
- `make check-codex-compat`: passed against Codex source commit
  `655224ffae098a85efeddf8289171ff3bd2624d1`; no blocking change.
- `make test`: `3685 passed, 5 skipped, 11 warnings`.
- `git diff --check`: passed.

No integration/live suite ran, so no real API call or cost was generated.

## Disposition

All frozen AUD-025 acceptance criteria are satisfied at deterministic evidence
depth. `AUD-025` is closed. `PROVIDER-01`, `STREAM-01`, `SCN-03`, `SCN-04`, and
`CTRL-03` return to `Fresh (deterministic)`. Real provider/Codex timing, external
sinks, covert encodings, public deployment, availability, and recovery remain
excluded or `Unknown`.
