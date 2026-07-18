# Responses Reasoning Passthrough
Date: 2026-07-06
Codex version: 0.144.0

Historical compatibility evidence; use the maintained ledger and reports for
current conclusions.

## Symptom

Direct Codex Responses sessions contained `reasoning` response items, while llm-rosetta same-format gateway sessions contained none. The llm-rosetta sessions also showed worse model self-knowledge and one spurious `create_goal({"objective":"dummy"})` call.

## Evidence

- Direct sessions had encrypted `reasoning` items:
  - `/Users/ibobby/.codex/sessions/2026/07/06/rollout-2026-07-06T12-27-47-019f38af-b841-7e22-aac9-b5f4ffc086fb.jsonl`
  - `/Users/ibobby/.codex/sessions/2026/07/06/rollout-2026-07-06T13-43-34-019f38f5-1a07-7e70-935a-4a8fb58c2c31.jsonl`
- llm-rosetta sessions had zero `reasoning` payload items:
  - `/Users/ibobby/.codex/sessions/2026/07/06/rollout-2026-07-06T13-38-54-019f38f0-d3b9-7f52-993e-77bd2ed483ba.jsonl`
  - `/Users/ibobby/.codex/sessions/2026/07/06/rollout-2026-07-06T13-41-36-019f38f3-4c0a-7923-86e7-e6d9d797278e.jsonl`

## Root Cause

OpenAI Responses streaming passthrough only preserved `tool_search_call` and `tool_search_output`. Opaque provider-native `reasoning` output items were ignored at `response.output_item.added`, `response.output_item.done`, and `response.completed`.

## Fix

Add `reasoning` to the general Responses passthrough output item set, but keep a separate tool-loop passthrough set so `reasoning` does not change the finish reason to `tool_calls`.

## Verification

- `python -m pytest tests/converters/openai_responses -q`
- `ruff check src/llm_rosetta/converters/openai_responses/converter.py tests/converters/openai_responses/test_stream.py`
- `ruff format --check src/llm_rosetta/converters/openai_responses/converter.py tests/converters/openai_responses/test_stream.py`
- Synthetic `ConversionPipeline("openai_responses", "openai_responses")` stream probe preserved `reasoning` in `output_item.added`, `output_item.done`, and `response.completed.output`.
