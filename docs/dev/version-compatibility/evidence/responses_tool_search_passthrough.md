# Responses tool_search passthrough
Date: 2026-07-06
Codex version: 0.144.0

Historical compatibility evidence; use the maintained ledger and reports for
current conclusions.

## Symptom

Codex requests through LLM-Rosetta returned one assistant message and then `task_complete`, without entering the agent loop. Direct calls to the same upstream did enter the loop.

## Evidence

- Failed sessions only contained `response_item` payloads with `message` item types.
- The successful direct session contained `reasoning`, `tool_search_call`, `tool_search_output`, `function_call`, and `function_call_output` items.
- LLM-Rosetta 0.7.0a2 had no `tool_search` handling in the OpenAI Responses stream or message converters.
- A converter probe showed `response.output_item.added` with `item.type == "tool_search_call"` produced no useful source event before this fix. `response.completed` therefore became a normal stop instead of a tool loop continuation.

## Root cause

Codex deferred tools use OpenAI Responses-native client-executed items, especially `tool_search_call` and `tool_search_output`. LLM-Rosetta's Responses converter only modeled portable IR tool calls. It dropped these Responses-native items on the stream path and on the next request's input-item path.

## Fix

- Added an opaque `provider_passthrough` stream event for provider-native chunks with no portable IR representation.
- OpenAI Responses now preserves `tool_search_call` and `tool_search_output` on same-format stream conversion.
- `response.completed` with these passthrough output items now maps to IR finish reason `tool_calls`.
- The target-side Responses stream context records passthrough output items so deferred `response.completed.response.output` remains complete.
- OpenAI Responses message conversion preserves `tool_search_call` and `tool_search_output` as assistant metadata passthrough items for request round trips.

## Verification

- `PATH=/Users/ibobby/miniconda3/envs/llm-rosetta/bin:$PATH make lint` passed.
- `/Users/ibobby/miniconda3/envs/llm-rosetta/bin/python -m pytest tests/converters/openai_responses/test_stream.py tests/converters/openai_responses/test_message_ops.py tests/converters/base/test_conversion_context.py -q` passed with 149 tests.
- `/Users/ibobby/miniconda3/envs/llm-rosetta/bin/python -m pytest tests/converters/openai_responses -q` passed with 332 tests.
- A local `ConversionPipeline("openai_responses", "openai_responses")` stream probe preserved `response.output_item.added/tool_search_call` and kept it in `response.completed.response.output`.

## Remaining unrelated issue

Full `make test` under `/Users/ibobby/miniconda3/envs/llm-rosetta/bin/python` failed only in `tests/gateway/test_auth.py`. The failure is `RuntimeError: There is no current event loop in thread 'MainThread'` from the test helper using `asyncio.get_event_loop()` on Python 3.14. This is unrelated to the Responses passthrough change.
