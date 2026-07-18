# OpenAI Responses Passthrough Notes
Date: 2026-07-06
Codex version: 0.144.0

This note records Responses API fields and event details that codex-rosetta has
already had to preserve while converting through IR. It exists so future
cross-protocol conversions into Responses do not need to rediscover the same
Responses-specific behavior.

This supporting contract note is subordinate to the maintained compatibility
point list in [`../compatibility-points.md`](../compatibility-points.md).

## Scope

`openai_responses -> openai_responses` should be handled as direct passthrough
at the gateway boundary. It should not decode into IR and re-emit a newly built
Responses request or stream.

Other source protocols that target Responses still need to synthesize enough
Responses structure for Codex and OpenAI-compatible clients. The fields below
are the known important surface.

## Request Fields To Preserve Or Synthesize

- `model`: gateway aliases may replace this with the upstream model before
  forwarding.
- `input`: Responses flat input item list. It may contain messages,
  `function_call`, `function_call_output`, and other provider items.
- `instructions`: system/developer instruction field echoed by Responses.
- `tools`: may include ordinary `function` tools and non-function passthrough
  tool definitions such as web/search-style tools or Codex-specific tools.
- `tool_choice`: `auto`, `none`, `required`, or a specific tool choice. Do not
  emit it without `tools` unless the target accepts that combination.
- `parallel_tool_calls` and `max_tool_calls`: Responses top-level tool config.
- `reasoning`: object such as `{ "effort": "high" }`. Do not invent unsupported
  nested fields when targeting OpenAI-compatible Responses endpoints.
- `include`: used for fields such as `reasoning.encrypted_content`.
- `text`, `temperature`, `top_p`, `max_output_tokens`, `truncation`,
  `metadata`, `user`, `store`, `background`, `service_tier`,
  `previous_response_id`, `prompt_cache_key`, `prompt_cache_retention`,
  `safety_identifier`, `top_logprobs`, `frequency_penalty`, and
  `presence_penalty`: Responses request/resource fields that have been
  preserved by the converter in lossless mode.

## Response Resource Fields

When building a Responses object for a non-Responses upstream, keep the
Responses response envelope coherent:

- Core fields: `id`, `object`, `created_at`, `model`, `status`, `output`,
  `usage`.
- Lifecycle/config echo fields: `background`, `completed_at`, `error`,
  `incomplete_details`, `instructions`, `max_output_tokens`, `max_tool_calls`,
  `parallel_tool_calls`, `previous_response_id`, `reasoning`, `service_tier`,
  `store`, `temperature`, `text`, `tool_choice`, `tools`, `top_p`,
  `truncation`, and related penalty/cache/user fields.
- Usage mapping: Responses uses `input_tokens`, `output_tokens`, `total_tokens`,
  `input_tokens_details.cached_tokens`, and
  `output_tokens_details.reasoning_tokens`.

## Output Items

Known output item types with behavior relevant to Codex:

- `message`: assistant output item. Preserve item-level metadata including
  `id`, `status`, `role`, and `phase`.
- `message.content[].output_text`: normal visible assistant text. Preserve
  `annotations` and `logprobs` if present.
- `reasoning`: reasoning output item. Preserve `id`, `summary`,
  `encrypted_content`, and raw `content` if present. A reasoning item alone
  should not force a tool loop.
- `function_call`: tool call item. Preserve both `id` and `call_id`; `call_id`
  is the stable correlation key for follow-up `function_call_output`.
- `function_call_output`: tool result item paired by `call_id`.
- `custom_tool_call`: Codex/custom tool call item. Preserve `call_id`, `name`,
  `input`, and item metadata.
- `tool_search_call` and `tool_search_output`: provider/Codex passthrough items.
  They must remain in `response.completed.output`. `tool_search_call` keeps
  Codex in the tool loop even though it is not a standard function call.

## Streaming Events

For Responses streams, clients depend on the original event sequence and item
metadata. Direct passthrough should forward upstream SSE bytes as-is. Cross-
protocol conversion into Responses should synthesize these events carefully:

- `response.created`: starts the stream and carries the response resource echo.
- `response.output_item.added`: starts output items. For `message` items,
  preserve item metadata such as `id`, `role`, `status`, and `phase`.
- `response.content_part.added`: starts a content block. `output_text` maps to
  visible text; `summary_text` maps to thinking/reasoning presentation.
- `response.output_text.delta`: visible text delta.
- `response.output_text.done`: final visible text for a content part.
- `response.reasoning_summary_text.delta`: reasoning summary delta.
- `response.function_call_arguments.delta` and
  `response.function_call_arguments.done`: function call argument streaming.
  Some upstreams use `item_id`; resolve it back to `call_id` when converting.
- `response.custom_tool_call_input.delta` and
  `response.custom_tool_call_input.done`: custom tool input streaming.
- `response.content_part.done`: closes the content part.
- `response.output_item.done`: closes the output item. Preserve `phase` on
  message items and metadata on tool/search items.
- `response.completed`: terminal response resource. Include the final `output`
  array with message `phase`, reasoning items, tool calls, passthrough items,
  and usage.
- `response.failed`: terminal failure event.

## Codex UI And Loop Notes

- `phase` on message output items is used by Codex presentation. For example,
  `phase: "commentary"` marks work-process output that Codex can fold or hide
  when producing the final answer. Dropping `phase` changes UI behavior even if
  text content is otherwise preserved.
- Reasoning summary events and reasoning items affect thinking/work display.
  Preserve `summary_text`, `reasoning.summary`, and `encrypted_content` when
  the upstream provides them.
- Tool loop detection cannot only look for `function_call`; passthrough
  `tool_search_call` also indicates that Codex should continue the agent loop.
- Orphan repair logic was only needed because IR conversion could lose request
  structure. Responses direct passthrough should not inject synthetic
  `function_call_output` items or strip tool config fields.
