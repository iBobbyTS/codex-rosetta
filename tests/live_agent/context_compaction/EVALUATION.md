# Context-Compaction Protocol Evaluation

This guide is for the test executor, including a coding agent or developer.
The tested model must not classify its own compaction. This suite evaluates
only the Codex/Rosetta protocol and routing contract; summary quality belongs
to the separate `context_compaction_summary_quality` suite.

## Required output

Write a bounded object to `RUN_ROOT/artifacts/evaluation.json`:

```json
{
  "suite": "context_compaction",
  "task_id": "01",
  "classification": "completed",
  "compaction_triggered": true,
  "remote_compaction_trigger_observed": true,
  "compaction_success": true,
  "compaction_method": "remote_v2_responses",
  "request_kind": "remote_v2_in_band",
  "request_http_path": "/v1/responses | /v1/responses/compact | unknown",
  "request_evidence_source": "gateway_request_profile | wire_body | access_log",
  "trigger_is_final_input_item": true,
  "compaction_reason": "context_limit",
  "gateway_compaction_mode": "rosetta",
  "wire_compaction_item_type": "compaction",
  "accepted_compaction_item_count": 1,
  "followup_compaction_input_observed": true,
  "error": null,
  "model": "observed Codex-facing model alias",
  "gateway_provider": "Deepseek (Official)",
  "codex_model_provider": "codex_rosetta",
  "thread_id": "<thread-id>",
  "command_starts": 1,
  "baseline_tokens": 14500,
  "post_compaction_tokens": 10000,
  "command_output_chars": 128000,
  "command_max_output_tokens": 20000,
  "rosetta_mapping_rows": 1
}
```

Do not include credentials, prompts, compaction payloads, summary plaintext,
or unbounded error bodies.

## Success decision

For Remote Compaction V2, require all of these:

1. A genuine outgoing item has `type: "compaction_trigger"`, or the Gateway
   request-log profile proves it recognized an in-band trigger by recording a
   non-empty `compaction_mode` and `compaction_reason` on `/v1/responses`.
2. The metadata reason and gateway mode match `expected.json`.
3. The compact response contains exactly one completed `compaction` item (or
   the accepted `compaction_summary` compatibility alias).
4. A later request carries the installed `type: "compaction"` item.
5. Codex reaches the task marker without a compact-task error.
6. The one-shot fixture command runs exactly once when the task has one.
7. `baseline_tokens` and `post_compaction_tokens` are both below
   `model_auto_compact_token_limit`, the command call retains at least 20,000
   output tokens and 60,000 output characters, and the genuine `context_limit`
   compaction occurs after that command result and before the final model
   response.

Set `request_kind` from the path/body/profile/event classification in the suite
README. A rollout-only `compacted` or `context_compacted` event is
`local_internal`; it cannot satisfy Remote V2. A request-log compaction profile
plus a mapping or native compaction item and installed follow-up is request
evidence, even when the early response bypasses stream tracing.

For Rosetta mode, also verify the expected mapping count. For native mode,
verify the mapping table remains unchanged. For model-switch tasks, verify the
first model initiates compaction and the target model produces the resume
marker.

## Classification

- `completed`: every protocol condition is satisfied.
- `remote_compaction_error_reproduced`: a genuine trigger is followed by the
  bounded compact-task error recorded in the artifact.
- `not_triggered`: the scenario ran but no genuine trigger was sent.
- `infrastructure_failure`: the tested provider was never reached.

Never use summary wording or fact retention to change this suite's protocol
classification.
