# Audit Evidence

Run: `20260721-2008`
Repository head: `c2db61e434c59bacc0f57d2e8c1286f16658d1d4`
Mode: periodic supplementary omission audit
Real API calls: none

## Repository reconciliation

- Start state: clean `main`, four commits ahead of `origin/main`.
- Changes after the last recorded targeted re-audit were limited to credential
  stream semantics and Responses embedded-JSON consumers:
  `15c6e94`, `c51c454`, `69a11a0`, and `c2db61e`.
- The durable ledgers still described the `20260721-1428` remediation state and
  therefore required current-head reconciliation.

## UNIT-001 - downstream consumer identity trace

The local Codex source is the authoritative downstream contract for this
local/LAN, Codex-only Gateway profile.

| Event | Codex parser retains | Turn consumer identity | Gate identity at current HEAD |
| --- | --- | --- | --- |
| `response.output_text.delta` | `delta` only | current active item | optional `item_id`, `output_index`, and `content_index` values |
| `response.reasoning_summary_text.delta` | `delta` and `summary_index` | current active item plus `summary_index` | optional `item_id`, `output_index`, and `content_index`; `summary_index` is not part of the key |
| `response.reasoning_text.delta` | `delta` and `content_index` | current active item plus `content_index` | `content_index` plus optional `item_id` and `output_index` values |

Source evidence:

- `src/codex_rosetta/gateway/transport/credential_semantics.py:21-42`
  defines the Responses text inventory.
- `credential_semantics.py:321-431` builds buffer identities from the configured
  required and optional wire fields.
- `credential_semantics.py:468-524` dispatches the three affected event types.
- `../openai-codex-src/codex-rs/codex-api/src/sse/responses.rs:339-380`
  discards the optional wire identifiers listed above while retaining only the
  event-specific delta/index fields.
- `../openai-codex-src/codex-rs/core/src/session/turn.rs:2323-2392` and
  `:2449-2464` bind those deltas to the current active item.

Changing a field that Codex discards therefore creates a new gate buffer without
creating a new downstream semantic stream. Conversely, summary deltas for
different `summary_index` values can share a gate key when the optional fields
remain unchanged. The former is a credential bypass; the latter also shows that
the gate does not own the consumer's true partitioning contract.

## UNIT-002 - deterministic counterexample

An in-process probe loaded the repository test fake stream and transport classes,
configured only the dummy credential `secret-token`, and sent two delta events
per affected type. The first event contained `secret-`; the second contained
`token`. Both events belonged to the same Codex-consumed stream, while ignored
optional wire identifiers changed between the two events.

Result:

```text
output_text: parsed_released=2 raw_released=True reconstructed=secret-token
reasoning_summary: parsed_released=2 raw_released=True reconstructed=secret-token
reasoning_text: parsed_released=2 raw_released=True reconstructed=secret-token
```

Both transport paths released the completing fragment and all frames. No
`UpstreamCredentialCollisionError` occurred.

## UNIT-003 - existing oracle portfolio

```text
conda run -n llm-rosetta pytest -q \
  tests/gateway/test_transport_credential_redaction.py \
  tests/converters/openai_responses/test_converter.py \
  tests/converters/openai_responses/test_stream.py \
  tests/converters/openai_responses/test_tool_ops.py
```

Result: `290 passed`.

The green suite covers fixed identities and optional-field presence/shape changes,
but not two credential fragments whose ignored optional identity values differ.
It is therefore evidence of a missing failure oracle, not closure evidence.

## Finding disposition

The subagent proposed the next unused run-local candidate ID, but the failure was
deduplicated into reopened `AUD-025`: its root cause remains a split credential
stream partitioned by an identity that does not match the supported consumer.

- Severity: `Must Fix`
- Decision class: `Agent-Fixable`
- Confidence: High
- Affected coverage: `PROVIDER-01`, `STREAM-01`, `SCN-03`, `SCN-04`, `CTRL-03`
- Business decision required: No

## Frozen acceptance criteria

1. For every supported Responses text delta, the gate partitions fragments by
   the identity Codex actually retains and concatenates, including active-item
   lifecycle and the event-specific retained index.
2. `item_id`, `output_index`, or `content_index` values ignored by a given Codex
   event consumer cannot create a fresh buffer for that consumer; contradictory
   metadata either remains irrelevant to identity or fails closed.
3. Raw and parsed SSE regressions block all three two-fragment counterexamples
   before the completing fragment is released.
4. Separate active items, summary indices, and content indices do not create
   false cross-stream credential collisions; all state remains bounded and is
   cleared on completion, failure, cancellation, and end-of-stream.
5. Focused and full deterministic checks pass without any real API call.

## Gaps

No real provider timing, Codex trajectory, external sink, public deployment,
availability, or recovery evidence was collected. Those remain excluded or
Unknown under the approved profile.
