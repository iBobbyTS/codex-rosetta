# Window-scoped Chat tool-surface evidence

Codex source: `25af12f7e61572b0bc18ddb1008be543b91519b0`

This evidence supports CP-11, CP-23, and CP-25. It contains no prompt body,
credential, window ID, or complete tool definition.

## Recorded 29→30 incident

| Request ID | Final tools | Tool hash prefix | Input | Cached | Adjacent delta |
|---|---:|---|---:|---:|---:|
| `e47b3e69-5d31-4b1b-aa8f-b8342ae907cb` | 29 | `7eef7c24a1114e38` | 422,237 | 421,376 | n/a |
| `68362bee-06c7-40fd-97d6-9a1626ea2d33` | 30 | `e539e7418a97fd84` | 418,336 | 1,152 | -421,578 |
| `9b9ab846-d466-4930-85f9-9c2d135d412a` | 29 | `7eef7c24a1114e38` | 418,443 | 401,408 | -17,087 |
| `c170caec-a3ef-4bbd-9cbb-3495f4c40a9b` | 29 | `7eef7c24a1114e38` | 419,291 | 418,432 | -271 |

The changed request added `list_available_plugins_to_install` and changed the
`request_plugin_install` schema. The fixed discovery trio did not change. This
is direct evidence that a temporary eager-tool change can invalidate almost the
complete DeepSeek prompt prefix.

## Active history-overlay experiment

Run directory: `/Volumes/4T/temp/DeepseekCacheDebug/20260802T002656Z/`.
The captured 30-tool Chat fixture was sent directly to DeepSeek with three
unique Flash `user_id` values per cell and one stable ID inside each warm/probe
pair. No Gateway or port was used.

| Cell | Result | Cache observation |
|---|---|---|
| No discovery control | 3/3 HTTP 200 | Every probe hit 396,800 tokens; prefix loss 5 |
| Isolated unpaired `role: tool` result | 3/3 probe HTTP 400 | Rejected before measurable probe usage |
| Gateway-forged paired `tool_search` history | 3/3 HTTP 200, but only 1/3 normal stop; 2/3 reached the output bound | Every probe hit 396,800; prefix loss 5 |
| Model-originated `tool_search → tool_read` | 2/2 evaluable repetitions completed the exact sequence; one warm response reached the output bound | Both probes hit 396,800; prefix loss 14 |

The forged-pair cell did not satisfy the 3/3 correct-consumption gate, so Pro
confirmation was skipped. Production therefore continues to require
model-originated request-local search/read evidence and never synthesizes tool
history.

## Window-lock live replay

Run directory:
`/Volumes/4T/temp/DeepseekCacheDebug/20260802T002656Z/window-surface-live/`.
The replay retained the exact `additional_tools` declarations from the recorded
29/30 requests and replaced the unrelated 775-message historical conversation
with one fresh user message. The full historical replay was intentionally
merged into this minimal form after two discarded Flash repetitions both
reached DeepSeek's historical `reasoning_content` validation error before the
surface behavior could be measured.

The first minimal replay exposed an `opaque_rollover`: Rosetta had not attributed
the top-level `exec.description` change to its strictly parsed nested plugin
sections. The second exposed that these Codex plugin sections used bounded bare
`### name` headings rather than backticked headings. Both integration gaps were
repaired with fail-closed coverage before the successful matrix below. Failed
repetitions use separate `user_id` values and remain preserved in the run
directory.

| Model | Repetitions | Final A/B tools | B cached/input | Prefix loss | Result |
|---|---:|---:|---:|---:|---|
| DeepSeek V4 Flash | 3 | 29 / 29 | 9,728 / 9,774 | 46 | 3/3 identical final body and tool hash |
| DeepSeek V4 Pro | 3 | 29 / 29 | 9,216 / 9,332 | 116 | 3/3 identical final body and tool hash |

Every repetition used a unique `user_id`, reused it only for its A/B pair, and
used a fresh window and Gateway data directory. The 12 successful upstream
requests produced no extra request, conversion warning, mapping error, or
surface rollover. Each upstream DeepSeek Chat usage tuple exactly matched the
corresponding Gateway Responses usage tuple. Both losses are below the fixed
256-token tolerance.

## Implementation consequence

Catalog schema v7 records all concrete source registrations and dynamic
families. CP-25 locks the final eager array only after Tool Profile conversion.
Reliable live additions and schema changes can be invoked only through the
current runtime after paired search/read and exact `definition_hash`
authorization. Opaque changes roll to a new epoch. A snapshot never recreates
a missing executor or authorizes a tool call.
