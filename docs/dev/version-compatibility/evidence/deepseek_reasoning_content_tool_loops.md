# DeepSeek Reasoning Content Tool Loops
Date: 2026-07-07
Codex version: 0.144.0

Historical compatibility evidence; use the maintained ledger and reports for
current conclusions.

## Symptom

DeepSeek thinking-mode requests with tool calls could fail on the follow-up turn
with:

```text
The `reasoning_content` in the thinking mode must be passed back to the API.
```

The captured stream trace showed upstream Chat chunks carrying
`delta.reasoning_content`, Rosetta converting them into IR reasoning deltas and
Responses `response.reasoning_summary_text.delta` events, but the final
`response.completed.response.output` did not contain a durable `reasoning` item.
The next converted Chat request therefore replayed assistant tool calls without
`reasoning_content`.

## External Contract

DeepSeek's official Thinking Mode guide says that tool-call turns in thinking
mode must pass `reasoning_content` back in all subsequent requests, otherwise the
API returns a 400 error.

Source: https://api-docs.deepseek.com/guides/thinking_mode

## Root Cause

The Chat streaming converter already produced `ReasoningDeltaEvent` from
`delta.reasoning_content`, and the Responses streaming converter already emitted
UI-facing `response.reasoning_summary_text.delta` events. However, the Responses
stream context only accumulated final assistant text and tool calls. Reasoning
deltas were not accumulated into the final `response.completed.output`, so the
Responses history lost the data needed to reconstruct Chat `reasoning_content`.

There was also a smaller Chat parsing edge case: non-streaming Chat assistant
messages used truthiness to detect `reasoning_content`, so an explicit empty
string was dropped. DeepSeek examples and field reports show empty
`reasoning_content` may still need to be passed back.

## Fix

- Add `reasoning_seen` and `accumulated_reasoning` to
  `OpenAIResponsesStreamContext`.
- Accumulate `ReasoningDeltaEvent` in the Responses stream converter while
  preserving existing `response.reasoning_summary_text.delta` output.
- Synthesize a Responses `reasoning` output item in `response.completed.output`
  when reasoning deltas were observed and no native passthrough reasoning item
  already exists.
- Also synthesize `response.output_item.added` and `response.output_item.done`
  events for that reasoning item. Codex appears to rebuild its next full-context
  request from streamed output items, not by reparsing the terminal
  `response.completed.output` array.
- Preserve explicit empty Chat `reasoning_content` values by checking
  `is not None` instead of truthiness.

## Verification

- `PATH=/Users/ibobby/miniconda3/envs/llm-rosetta/bin:$PATH PYTHONPATH=src pytest tests/converters/openai_responses/test_stream.py tests/converters/openai_responses/test_message_ops.py tests/converters/openai_chat/test_message_ops.py tests/converters/openai_chat/test_stream.py -q`
- `PATH=/Users/ibobby/miniconda3/envs/llm-rosetta/bin:$PATH ruff check src/llm_rosetta/converters/openai_responses/converter.py src/llm_rosetta/converters/openai_responses/stream_context.py src/llm_rosetta/converters/openai_chat/message_ops.py tests/converters/openai_responses/test_stream.py tests/converters/openai_chat/test_message_ops.py`
- `PATH=/Users/ibobby/miniconda3/envs/llm-rosetta/bin:$PATH ruff format --check src/llm_rosetta/converters/openai_responses/converter.py src/llm_rosetta/converters/openai_responses/stream_context.py src/llm_rosetta/converters/openai_chat/message_ops.py tests/converters/openai_responses/test_stream.py tests/converters/openai_chat/test_message_ops.py`

Added a regression that converts Chat streaming `reasoning_content` plus a tool
call into Responses output history using `response.output_item.added/done`
events, then converts that history back into the next Chat request and asserts
the assistant message carries `reasoning_content`.

## Follow-up Evidence

After the first fix, session `019f3ce1-5109-70b1-ae01-1e68618b90e6` still
failed. `/Volumes/RAM Disk/log.jsonl` showed:

- Gateway startup was `2026-07-07 07:44:23 -0600`; the prior source edits were
  earlier (`07:38` to `07:41`), so this was not stale code.
- The gateway did include synthetic `reasoning` items in
  `response.completed.output`.
- The next Codex source request did not include those reasoning items, and the
  converted Chat request therefore had assistant `tool_calls` without
  `reasoning_content`.

That narrowed the missing behavior to streamed output item persistence, so the
fix was extended to emit synthetic reasoning output-item lifecycle events.
