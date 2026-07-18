# Responses Full-Turn Phase Buffer
Date: 2026-07-07
Codex version: 0.144.0

Historical compatibility evidence; use the maintained ledger and reports for
current conclusions.

## Symptom

When a Chat upstream emits ordinary assistant text before tool calls, the
Responses downstream stream exposes that text without `phase: "commentary"`.
Codex then displays intermediate work text like final-answer text instead of
folding it during the active tool loop.

## Evidence

- Current `_stream_event_generator` formats every source event immediately after
  `processor.process_chunk(...)`.
- OpenAI Chat to Responses conversion emits normal message/text events before
  later tool-call events, so phase cannot be decided at the first text delta.
- The desired boundary is structural, not textual: a later tool-call event means
  buffered text is commentary; terminal `response.completed` without tool calls
  means final answer.

## Hypothesis

The minimal fix is a gateway-local Responses event buffer placed after provider
conversion and before SSE formatting. It can hold message/text events until a
tool or completion signal, then inject `phase: "commentary"` only when the
stream proves the buffered text belongs to a tool-use turn.

## Verification Plan

- Unit-test the buffer helper directly for tool, final, pure-tool, completed-only
  tool, and EOF paths.
- Test `_stream_event_generator` output order and trace order with the buffer.
- Run targeted gateway tests and ruff checks.
