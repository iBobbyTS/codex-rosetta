# Network Search Evaluation

This file guides the outer evaluating agent. Do not include it in the tested
model's prompt.

## Required evidence

Use all three bounded sources, but assign them different roles:

1. `artifacts/codex.jsonl` proves the process result, thread id, visible search
   activity, and final marker.
2. The matching rollout under `codex_home/sessions` proves the native Codex
   call/result sequence and absence of prohibited command or browser fallbacks.
3. Rosetta **Gateway Logs** at the path recorded in
   `artifacts/gateway-log-root.txt` are authoritative for `search_surface`, the
   actual upstream model, conversion path, and terminal stream state.

Do not classify the surface from a Codex item whose type is `web_search`.
Codex uses that presentation type for both standalone `web.run` and hosted
`web_search`.

## Search-surface classification

Set `search_surface` using the Gateway Logs:

### `web.run`

Require an executed namespace/nested call, not instructional prose. Accepted
evidence includes a model output call to `web.run`, or an `exec` custom-tool
call whose executable input invokes `tools.web__run`. When route telemetry is
available, also record the subsequent `POST /v1/alpha/search` request.

The string `web.run` inside instructions, descriptions, input history, or an
error message is not sufficient by itself.

### `web_search`

Require a structured hosted tool definition or call. Accepted evidence
includes:

- a Responses request tool with `type: "web_search"` or
  `type: "web_search_preview"`, followed by a `web_search_call`; or
- a Responses-to-Chat trace where `source_request` contains the hosted search
  tool, `target_request` contains Rosetta's localized `web_search` function,
  and the trace contains `web_search_request`/`web_search_response` stages.

If Rosetta executes the localized call through Tavily, set
`search_executor` to `tavily` but keep `search_surface` as `web_search`.

### `none` and `ambiguous`

Use `none` when the Gateway Logs are present and prove that no model-facing
search call occurred. Use `ambiguous` when the trace is absent, truncated, has
the wrong model/request filter, or contains only textual mentions. An
`ambiguous` run cannot pass this suite.

## Success decision

The run passes only when all of the following are true:

- the exact success marker is present;
- `search_surface` is `web.run` or `web_search`;
- at least one corresponding model-facing call is proven by Gateway Logs;
- the search result is non-error and contains a `docs.python.org` URL;
- no command or browser fallback was used;
- the Rosetta stream completed successfully.

Small unrelated model deviations do not fail the run when these core
conditions hold. A correctly selected search tool whose backend fails is still
an end-to-end test failure, while its `search_surface` classification remains
valid.

## Required result file

Write `artifacts/evaluation.json` with this shape:

```json
{
  "classification": "success | success with deviations | failure",
  "model": "model alias used by Codex",
  "upstream_model": "model proven by Gateway Logs",
  "thread_id": "Codex thread id",
  "process_exit_code": 0,
  "success_marker_observed": true,
  "search_surface": "web.run | web_search | none | ambiguous",
  "search_executor": "alpha_search | upstream_responses | tavily | none | unknown",
  "network_search_calls": 1,
  "successful_search_result": true,
  "command_calls": 0,
  "browser_calls": 0,
  "gateway_log_evidence": [
    {
      "stage": "bounded Gateway Logs stage",
      "request_id": "request id when available",
      "observation": "short credential-free structural observation"
    }
  ],
  "stream_completed": true,
  "warning": null
}
```

Keep evidence structural and bounded. Do not copy full prompts, response
bodies, API keys, authorization headers, or an entire trace into the result.
