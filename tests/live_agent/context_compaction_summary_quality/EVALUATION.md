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
  "compaction_reason": "context_limit",
  "gateway_compaction_mode": "native",
  "compaction_count": 1,
  "command_starts": 1,
  "baseline_tokens": 14500,
  "post_compaction_tokens": 10000,
  "command_output_chars": 128000,
  "final_response_after_compaction": true,
  "model": "gpt-5.6-terra",
  "gateway_provider": "Pixel (K12)",
  "thread_id": "<thread-id>",
  "summary_reviewer": "coding_agent_or_developer",
  "summary_review": "effective",
  "summary_review_note": "All seven values match.",
  "summary_fact_checks": {
    "project": "preserved",
    "stage": "preserved",
    "ledger_policy": "preserved",
    "timezone": "preserved",
    "endpoint": "preserved",
    "predeploy_check": "preserved",
    "reference_code": "preserved"
  },
  "final_response_json": {
    "project": "Orchid",
    "stage": "2 completed",
    "ledger_policy": "do not modify ledger.csv",
    "timezone": "UTC only",
    "endpoint": "/v2/checkpoint",
    "predeploy_check": "verify_delta",
    "reference_code": "A7-KAPPA"
  },
  "error": null
}
```

For each key:

- `preserved`: exact value match;
- `missing`: key absent or empty;
- `contradicted`: key present with a different non-empty value.

Set `summary_review` to `effective` only when all seven checks are preserved.
Set it to `ineffective` when protocol preconditions pass but at least one fact
is missing or contradicted. Set it to `not_scored` when a protocol precondition
fails, and explain that failure without converting it into a quality judgment.

Do not include credentials, full prompts, summary plaintext, opaque compaction
content, or unbounded logs in the artifact.
