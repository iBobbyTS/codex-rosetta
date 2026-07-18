# Summary-Quality Evaluation Guide

The test executor may be a coding agent or developer. The tested model only
returns recalled facts and must never assess whether its own summary was good.

Write `RUN_ROOT/artifacts/evaluation.json` with this bounded schema:

```json
{
  "suite": "context_compaction_summary_quality",
  "task_id": "01",
  "classification": "completed",
  "protocol_preconditions_satisfied": true,
  "phase1_exit_status": 0,
  "resume_exit_status": 0,
  "phase1_marker_observed": true,
  "same_thread_resume": true,
  "compaction_reason": "context_limit",
  "request_kind": "remote_v2_in_band",
  "request_http_path": "/v1/responses | /v1/responses/compact | unknown",
  "gateway_compaction_mode": "native",
  "compaction_count": 1,
  "resume_compaction_count": 0,
  "command_starts": 1,
  "resume_command_starts": 0,
  "baseline_tokens": 14500,
  "post_compaction_tokens": 10000,
  "command_output_chars": 128000,
  "final_response_after_compaction": true,
  "model": "observed Codex-facing model alias",
  "gateway_provider": "Pixel (K12)",
  "thread_id": "<thread-id>",
  "summary_reviewer": "coding_agent_or_developer",
  "summary_review": "effective",
  "summary_review_note": "All eleven values match.",
  "summary_fact_checks": {
    "project": "preserved",
    "completed_stage": "preserved",
    "immutable_file": "preserved",
    "timezone": "preserved",
    "active_endpoint": "preserved",
    "superseded_endpoint": "preserved",
    "predeploy_gate": "preserved",
    "reference_code": "preserved",
    "rollout_strategy": "preserved",
    "strategy_reason": "preserved",
    "deployment_owner": "preserved"
  },
  "final_response_json": {
    "project": "Orchid",
    "completed_stage": "phase 2 completed",
    "immutable_file": "never modify ledger.csv",
    "timezone": "UTC only",
    "active_endpoint": "/v3/checkpoint",
    "superseded_endpoint": "/v2/checkpoint",
    "predeploy_gate": "run verify_delta immediately before production and require exit 0",
    "reference_code": "A7-KAPPA",
    "rollout_strategy": "two-phase rollout",
    "strategy_reason": "checkpoint writes are idempotent",
    "deployment_owner": null
  },
  "error": null
}
```

For each key:

- `preserved`: the fixed field rule below is satisfied;
- `missing`: the key/value or a required atomic qualifier is absent;
- `contradicted`: the value asserts a conflicting project state.

Use these field rules only for this one scenario:

- `project`, both endpoints, and `reference_code` match exactly;
- `completed_stage` says phase 2 is completed, case-insensitively;
- `immutable_file` contains `ledger.csv` and an explicit never/do-not-modify
  constraint;
- `timezone` contains both `UTC` and `only`;
- `predeploy_gate` contains `verify_delta`, immediately-before-production
  ordering, and required exit code 0;
- `rollout_strategy` conveys a two-phase rollout and `strategy_reason` conveys
  idempotent checkpoint writes;
- `deployment_owner` is JSON null.

Set `summary_review` to `effective` only when all eleven checks are preserved.
Set it to `ineffective` when protocol preconditions pass but at least one fact
is missing or contradicted. Set it to `not_scored` when a protocol precondition
fails, and explain that failure without converting it into a quality judgment.

Do not include credentials, full prompts, summary plaintext, opaque compaction
content, or unbounded logs in the artifact.
