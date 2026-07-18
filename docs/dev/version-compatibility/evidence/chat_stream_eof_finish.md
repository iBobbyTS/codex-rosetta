# Chat stream EOF after finish fallback
Date: 2026-07-07
Codex version: 0.144.0

Historical compatibility evidence; use the maintained ledger and reports for
current conclusions.

## Evidence

- `openai_chat` stream converter currently emits `StreamEndEvent` on empty `choices: []` after start, or on `finish_reason` when usage is present in the same chunk.
- Simulated Chat stream with `finish_reason` followed by normal EOF but no usage/empty-choices chunk leaves Responses output without `response.completed`.
- Real DeepSeek v4 flash completed streams ended with `finish_reason + usage`; real GLM/gpt-5.3-codex normal completed streams ended with empty `choices: [] + usage`.
- A GLM timeout/interrupted stream ended without `finish_reason`, usage, or empty choices; that should not be treated as a completed response.

## Hypothesis

The minimal fix is a gateway/pipeline EOF finalize step only for `openai_chat` upstream streams: if a `finish` IR event was seen and the upstream stream context has not already ended, synthesize one IR `stream_end` at normal EOF.

## Verification Plan

- Add unit coverage for finish-only EOF producing `response.completed`.
- Lock existing successful shapes: `finish_reason + usage` and `finish_reason` followed by empty `choices: [] + usage` still produce exactly one `response.completed`.
- Verify no `response.completed` is synthesized when normal EOF occurs without `finish_reason`.

## Resolution

- Added `StreamProcessor.finalize_stream()` with an opt-in `finalize_on_finish_eof` flag.
- Gateway enables the flag only for `openai_responses/open_responses -> openai_chat` streaming conversion.
- The finalize path emits `stream_end` only when a `finish` IR event was seen and the upstream stream context did not already end.
- Tests verify finish-only EOF produces one `response.completed`, existing DeepSeek-style `finish_reason + usage` produces one completed with usage, existing GLM-style `finish_reason` then empty `choices: [] + usage` produces one completed with usage, and EOF without finish produces no completed.

## Verified

- `PATH=/Users/ibobby/miniconda3/envs/llm-rosetta/bin:$PATH PYTHONPATH=src pytest tests/gateway/test_chat_stream_eof_finalize.py tests/gateway/test_stream_trace.py tests/gateway/test_stream_phase_buffer.py tests/gateway/test_tool_adaptation.py tests/converters/openai_chat/test_stream.py tests/test_pipeline.py -q`
- `PATH=/Users/ibobby/miniconda3/envs/llm-rosetta/bin:$PATH ruff check src/llm_rosetta/pipeline.py src/llm_rosetta/gateway/proxy.py tests/gateway/test_chat_stream_eof_finalize.py`
- `PATH=/Users/ibobby/miniconda3/envs/llm-rosetta/bin:$PATH ruff format --check src/llm_rosetta/pipeline.py src/llm_rosetta/gateway/proxy.py tests/gateway/test_chat_stream_eof_finalize.py`
