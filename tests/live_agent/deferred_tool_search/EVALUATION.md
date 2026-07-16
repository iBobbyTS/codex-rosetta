# Isolated Capability Discovery Evaluation

This file guides the outer evaluating agent. Do not include it in the tested
model's prompt.

## Required evidence

Use all three bounded evidence sources:

1. `artifacts/codex.jsonl` for process exit, thread id, visible tool activity,
   and the exact final marker.
2. The matching isolated rollout under `codex_home/sessions` for plugin
   guidance or skill injection, `exec` code cells, nested MCP calls, and results.
3. Gateway Logs for the actual upstream model, conversion route, request order,
   model-facing loaded tool name, and terminal stream state.

Installation output proves only that the plugin was provisioned. It does not
prove deferred discovery or execution. Tool descriptions and prompt text do
not count as tool calls.

## Decision rules

- Task `01` succeeds when the plugin is installed and mentioned, plugin guidance
  names its MCP server, `ALL_TOOLS` discovers the nested marker tool, and that
  tool is called successfully.
- Task `02` succeeds when the standalone MCP server is installed, `ALL_TOOLS`
  discovers its nested marker tool, and that tool is called successfully.
- Task `03` succeeds when the standalone skill is present in the available
  skills list, its complete body is injected, and the exact final marker is
  returned without a file/shell fallback.
- For MCP tasks, the tool must be called with value
  `ROSETTA_DEFERRED_20260716`; its result contained the exact marker; the final
  response must be exact and the stream must complete.
- `success with deviations`: all required behavior succeeded, with harmless
  extra tool calls or prose before the exact final line.
- `failure`: any required stage is missing, errors, uses a shell/network/browser
  fallback, or cannot be proven by the three evidence sources.

When a stage fails, distinguish `not_listed`, `not_injected`, `not_exposed`,
`not_called`, and `failed`.

## Required result file

Write `artifacts/evaluation.json` with this shape:

```json
{
  "classification": "success | success with deviations | failure",
  "model": "model alias used by Codex",
  "provider_identity": "deferred-tool-test (display name: openai)",
  "upstream_model": "model proven by Gateway Logs",
  "thread_id": "Codex thread id",
  "rollout_path": "isolated rollout path",
  "process_exit_code": 0,
  "capability_kind": "plugin | mcp | skill",
  "installation": "success | failed",
  "discovery": {
    "surface": "exec.ALL_TOOLS | skills metadata and injection",
    "status": "success | not_listed | not_injected | not_exposed | failed",
    "observed": true
  },
  "marker_tool": {
    "status": "success | not_exposed | not_called | failed",
    "native_name": "mcp__deferred-marker__return_marker",
    "model_facing_names": ["observed name"],
    "input_value_observed": true,
    "marker_result_observed": true
  },
  "prohibited_fallback_calls": 0,
  "success_marker_observed": true,
  "stream_completed": true,
  "gateway_log_evidence": [],
  "warning": null
}
```

Keep evidence structural and credential-free. Never copy authorization headers,
tokens, full prompts, or whole trace records into the result.
