# Gateway stream trace logging
Date: 2026-07-07
Codex version: 0.144.0

Historical compatibility evidence; use the maintained ledger and reports for
current conclusions.

Confirmed evidence:
- Direct openai_responses -> openai_responses streaming raw passthrough currently logs each chunk twice: upstream_raw_chunk and downstream_raw_sse, but payload bytes are identical.
- Converted streaming path openai_responses -> openai_chat currently logs upstream_chunk, ir_event, source_event, downstream_sse only when StreamTraceConfig.enabled matches.

User request:
- Responses passthrough should not record duplicate raw chunks.
- For responses -> chat and received chat -> responses streaming conversion, both sides must be logged and not as an optional toggle.

Working hypothesis:
- Add mandatory trace creation for openai_responses <-> openai_chat conversion paths, while preserving optional stream_trace for other paths.
- For raw passthrough, log one raw_passthrough_chunk per chunk instead of two equivalent records.
