# Subagent Tool Evaluation

This file guides the outer evaluating agent. Do not include it in the tested
model's prompt.

## Required evidence

Use all three bounded evidence sources:

1. `artifacts/codex.jsonl` for process exit, thread id, visible tool activity,
   and the final marker.
2. The matching rollout under `codex_home/sessions` for native
   `collaboration` calls, results, canonical task paths, lifecycle changes, and
   child messages.
3. Gateway Logs for the actual upstream model, model-facing tool names,
   conversion route, and terminal stream state.

Do not count tool descriptions, prompt text, or the presence of a child in a
later request as a call. Shell commands, local files, browser tools, and
non-`collaboration` fallbacks do not satisfy any scenario.

## Per-scenario decisions

- `01` / `spawn_agent`: require a successful native `spawn_agent`, canonical
  path `/root/spawn_probe`, and the spawned child's exact
  `SUBAGENT:SPAWN_OK` completion marker.
- `02` / `wait_agent`: require a successful native `wait_agent` after the
  child is spawned, a non-timeout completion wake-up, and exact child marker
  `SUBAGENT:WAIT_OK`.
- `03` / `list_agents`: require a successful native `list_agents` result that
  includes `/root/list_probe` with completed state and marker
  `SUBAGENT:LIST_OK`.
- `04` / `send_message`: require a successful native `send_message` targeting
  `/root/message_probe`, evidence that the child received
  `PING:SEND_MESSAGE`, and exact child marker `SUBAGENT:SEND_MESSAGE_OK`.
- `05` / `followup_task`: require the child to complete its initial turn with
  `SUBAGENT:FOLLOWUP_READY`, a successful native `followup_task` targeting the
  same canonical path, and a later exact marker `SUBAGENT:FOLLOWUP_OK`.
- `06` / `interrupt_agent`: require a successful native `interrupt_agent`
  targeting `/root/interrupt_probe`, a returned `previous_status`, and a later
  `list_agents` result proving the same canonical child remains resident.

Set `target_status` to `success`, `not_exposed`, `not_called`, or `failed`.
The overall run succeeds only when the target status is `success`, the exact
parent marker is present, no prohibited fallback occurred, and the stream
completed. A target tool present in the request but not selected is
`not_called`; do not report it as model quality or tool absence.

Small extra waits, status checks, or prose are deviations rather than failures
when the core lifecycle behavior is proven. Calling a different Function as a
substitute, restarting the scenario, or obtaining the marker without the
required target call is a failure.

## Required result file

Write `artifacts/evaluation.json` with this shape:

```json
{
  "classification": "success | success with deviations | failure",
  "task_id": "01 through 06",
  "target_tool": "collaboration Function named by expected.json",
  "target_status": "success | not_exposed | not_called | failed",
  "model": "model alias used by Codex",
  "provider_identity": "codex_rosetta",
  "provider_display_name": "OpenAI",
  "upstream_model": "model proven by Gateway Logs",
  "thread_id": "Codex thread id",
  "rollout_path": "isolated rollout path",
  "process_exit_code": 0,
  "success_marker_observed": true,
  "native_calls": ["observed collaboration calls in order"],
  "model_facing_calls": ["observed names in order"],
  "successful_target_result": true,
  "child_task_paths": ["observed canonical paths"],
  "child_markers": ["observed exact child markers"],
  "state_observations": ["bounded lifecycle evidence"],
  "prohibited_fallback_calls": 0,
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

Keep evidence structural and credential-free. Never copy full prompts,
authorization headers, tokens, or entire trace records into this file.
