# Live-agent failure reanalysis
Date: 2026-07-18
Codex version: 0.144.0

Historical compatibility evidence; use the maintained ledger and reports for
current conclusions.

## Confirmed observations

- Terra namespace run `202607172323` called `clock.curr_time` and
  `memories.list` successfully through top-level `exec`; only `skills.list`
  was unavailable.
- Current Codex source suppresses orchestrator skills when a local execution
  environment is attached. It also requires `[orchestrator.skills] enabled =
  true` before contributing the `skills` Namespace.
- Codex image generation is filtered unless the provider uses OpenAI actor
  authorization or `requires_openai_auth` is backed by Codex-backend auth.
  An isolated provider using only `experimental_bearer_token` does not satisfy
  that gate.
- Terra context-limit run `202607172322` retained only a 1,000-token bounded
  command result. Its second request used 15,723 input tokens, below the
  configured 17,000-token auto-compaction limit.
- Terra-to-DeepSeek run `202607172344` did compact. Gateway persistence records
  `compaction_mode=rosetta`, reason `comp_hash_changed`, and one mapping. The
  Remote V2 early response is not represented in the stream trace.
- DeepSeek namespace rerun `202607171613` recursively scanned JSON Schema tool
  definitions. Five schema `properties` maps contain a property named `type`
  whose value is a dict, causing `_has_reasoning_history()` to hash a dict in a
  set-membership expression.

## Root cause and fix

The reasoning-history crash treated every nested `type` value as a scalar
Responses item discriminator. Tuple membership now compares candidates without
hashing, so JSON Schema objects are ignored while real `reasoning` and
`thinking` history remains detectable.

The live fixtures now separate runner/auth prerequisites from model behavior,
retain enough command output to trigger context compaction, use Gateway
request-log profiles and mapping evidence for early compaction responses, and
test file outcomes separately from Chat and Responses editing-tool selection.

## Verified result

- `pytest tests/test_reasoning_mapping.py tests/test_pipeline.py -q`:
  168 passed.
- `pytest tests/test_reasoning_mapping.py tests/live_agent/test_live_agent_configuration_contract.py tests/live_agent/test_deferred_tool_search_fixture.py -q`:
  116 passed.
- `make lint`: passed.
- Full non-integration suite: 3401 passed, 5 skipped, with three pre-existing
  model-preset snapshot failures (`service_tiers`, `additional_speed_tiers`,
  and missing `supports_parallel_tool_calls`).
