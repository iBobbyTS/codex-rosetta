# Trace QA

## Where do unexplained `gpt-5.4` or `gpt-5.4-mini` calls come from?

When a stream trace used for DeepSeek/Codex tool tests contains `gpt-5.4` or `gpt-5.4-mini` requests, first investigate whether the same gateway recorded unrelated Codex traffic at the same time. Do not immediately conclude that the DeepSeek route used the wrong model.

Common indicators:

- Unexplained `gpt-5.4` calls most likely come from memory creation or consolidation tasks. Typical indicators are a `cwd` under `/Users/ibobby/.codex/memories`, user input containing `Memory Writing Agent`, `Phase 2`, or consolidation-related text, and stages such as `raw_passthrough_request` / `raw_passthrough_chunk`.
- Unexplained `gpt-5.4-mini` calls most likely come from Codex generating a thread title or doing lightweight background organization. They typically use same-format OpenAI Responses passthrough and are usually unrelated to the DeepSeek Responses-to-Chat conversion path.

Investigation sequence:

1. Group records by `request_id`, then inspect `source_provider`, `target_provider`, `provider_name`, and the stage.
2. If the path is `openai_responses -> openai_responses` and the stage is `raw_passthrough_*`, treat it first as unrelated passthrough traffic on the same gateway.
3. Extract the request's `cwd` and a summary of its final user input to confirm whether it belongs to the current test directory.
4. Investigate the route configuration only if the `deepseek-v4-flash` request itself contains an unexpected upstream model.
