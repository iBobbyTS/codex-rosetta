# Codex Responses Context Observation
Date: 2026-07-06
Codex version: 0.144.0

Observed with Codex Desktop / CLI version `0.142.5` on 2026-07-06.

This is historical runtime evidence for the version-compatibility ledger. It is
not a current compatibility claim; current ownership, limitations, and upgrade
gates are recorded in [`../compatibility-points.md`](../compatibility-points.md).

## Summary

In the observed Codex sessions, Codex used the Responses API in a stateless
full-context mode:

- `previous_response_id` was always `null`.
- `store` was `false`.
- Each request sent the full conversation context again.
- `prompt_cache_key` was present and stable across related requests, so upstream
  prompt caching could reduce repeated processing cost, but it did not reduce
  request payload size or context-window usage.

This means Codex-Rosetta did not need to reconstruct conversation state for these
requests. For `openai_responses -> openai_responses`, it passed the request and
raw SSE stream through. For `openai_responses -> openai_chat`, it converted the
full current Responses `input` payload into Chat Completions `messages`.

## Evidence

The main local evidence came from:

- `/Users/ibobby/.config/codex-rosetta-gateway/log.jsonl`
- `/Users/ibobby/.config/codex-rosetta-gateway/chat-responses.jsonl`
- `/Users/ibobby/.config/codex-rosetta-gateway/responses-responses.jsonl`
- `/Users/ibobby/.codex/sessions/2026/07/06/rollout-2026-07-06T19-46-23-019f3a41-42ec-7301-95c0-5931e634b691.jsonl`
- `/Users/ibobby/.codex/sessions/2026/07/06/rollout-2026-07-06T19-48-45-019f3a43-6d55-74b1-a13b-6d5c1f430284.jsonl`

The relevant request metadata observed in `log.jsonl`:

| UTC time | Route | Model | Input tokens | Cached tokens | `previous_response_id` | `store` |
| --- | --- | --- | ---: | ---: | --- | --- |
| 2026-07-07 04:40:50 | `openai_responses -> openai_responses` | `gpt-5.5` | 40,722 | 4,992 | `null` | `false` |
| 2026-07-07 04:41:03 | `openai_responses -> openai_responses` | `gpt-5.5` | 139,419 | 4,992 | `null` | `false` |
| 2026-07-07 04:41:39 | `openai_responses -> openai_responses` | `gpt-5.5` | 149,150 | 139,136 | `null` | `false` |
| 2026-07-07 04:45:29 | `openai_responses -> openai_responses` | `gpt-5.5` | 149,340 | 139,136 | `null` | `false` |
| 2026-07-07 04:45:52 | `openai_responses -> openai_responses` | `gpt-5.5` | 150,850 | 148,864 | `null` | `false` |
| 2026-07-07 04:46:25 | `openai_responses -> openai_responses` | `gpt-5.5` | 153,893 | 150,400 | `null` | `false` |

The fixed response echo included a large `instructions` field and 18 tools. A
rough local estimate, without exact tokenizer support, put fixed
`instructions + tools` overhead around 10K tokens, leaving roughly 129K-144K
tokens of conversation and runtime context in the later requests.

The Codex session files also contained the local transcript items for the
conversation, including:

- user messages
- assistant messages
- reasoning items
- function calls
- function call outputs

That matches the observed token usage: later requests were not short deltas,
but full-context requests rebuilt from the local Codex transcript.

## Implications For Codex-Rosetta

Codex-Rosetta should not assume that Responses clients will use server-side
Responses state. A Responses request with `previous_response_id: null` and
`store: false` can still be a valid full-context request.

For same-protocol Responses passthrough:

- Preserve request body and raw SSE bytes.
- Do not attempt to interpret, inject, or synthesize `previous_response_id`.
- Treat state strategy as a client/upstream concern.

For Responses-to-Chat conversion:

- Conversion can only preserve conversation context that is already present in
  the current Responses request body.
- If a future client sends only incremental `input` plus
  `previous_response_id`, Codex-Rosetta cannot convert that to Chat Completions
  correctly unless it also maintains or can retrieve the missing conversation
  history.
- Supporting that mode would require an explicit conversation-state store keyed
  by response/conversation IDs, plus retention, invalidation, privacy, and
  replay semantics.

## Practical Interpretation

The observed behavior is not a protocol violation. It is a stateless use of the
Responses API. The cost tradeoff is:

- It keeps Codex in control of the complete transcript.
- It avoids reliance on upstream response retention.
- It enables prompt-cache reuse through `prompt_cache_key`.
- It does not reduce HTTP payload size.
- It does not reduce context-window usage.
- It can generate large gateway logs when raw Responses SSE is recorded.
