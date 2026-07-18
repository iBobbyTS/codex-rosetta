# Responses Namespaced Function Calls
Date: 2026-07-06
Codex version: 0.144.0

Historical compatibility evidence; use the maintained ledger and reports for
current conclusions.

## Symptom

Codex through llm-rosetta could continue the agent loop, but subagent calls failed with `unsupported call: spawn_agent`.

## Evidence

- Failing session: `/Users/ibobby/.codex/sessions/2026/07/06/rollout-2026-07-06T13-19-40-019f38df-38a2-7582-a5e7-fa0faa3e5a1f.jsonl`.
- Working direct session: `/Users/ibobby/.codex/sessions/2026/07/06/rollout-2026-07-06T12-27-47-019f38af-b841-7e22-aac9-b5f4ffc086fb.jsonl`.
- Both sessions exposed `multi_agent_v1.spawn_agent` in `tool_search_output`.
- The failing session emitted `function_call` items with `name="spawn_agent"` but no `namespace`; Codex returned `unsupported call: spawn_agent`.
- The working direct session emitted `function_call` items with `namespace="multi_agent_v1"` and original `fc_...` item ids.

## Root Cause

The OpenAI Responses streaming provider-to-IR-to-provider path preserved portable tool call fields but dropped Responses-native metadata needed by Codex routing: `namespace` and the provider response item id.

## Fix

Store Responses tool call provider metadata on `ToolCallStartEvent` and in `OpenAIResponsesStreamContext`, then restore it when converting tool call start, done, and completed events back to provider format.

## Verification

- `ruff check src/llm_rosetta/converters/openai_responses/converter.py src/llm_rosetta/converters/openai_responses/stream_context.py tests/converters/openai_responses/test_stream.py`
- `ruff format --check src/llm_rosetta/converters/openai_responses/converter.py src/llm_rosetta/converters/openai_responses/stream_context.py tests/converters/openai_responses/test_stream.py`
- `python -m pytest tests/converters/openai_responses -q`
