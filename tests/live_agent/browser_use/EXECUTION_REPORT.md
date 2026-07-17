# Browser Live Test Execution Report

This contract is for the GUI **test executor only**. It records Browser actions
and observable fixture outcomes without judging them.

The executor must not inspect Gateway Logs, Gateway traces/databases, Request
Log rows, session JSONL, rollout JSONL, or archived session metadata. It must
not read `EVALUATION.md`, assign capability statuses, or produce an overall
verdict.

Write `<run_root>/execution.json`, where `run_root` is the unique
`.agent-work/live-agent-test/{YYYYMMDD-HHMM}` directory created before Browser
setup. Never write to a shared result path or an existing timestamp directory.
Use this shape:

```json
{
  "schema_version": 2,
  "task_id": "01",
  "role": "executor",
  "run_root": "/absolute/workspace/.agent-work/live-agent-test/YYYYMMDD-HHMM",
  "run_stamp": "YYYYMMDD-HHMM",
  "host_surface": "codex_gui_app",
  "plugin": "Browser",
  "skill": "browser:control-in-app-browser",
  "browser": "iab",
  "backend": "iab",
  "fixture_url": "http://127.0.0.1:8876/",
  "fixture_server": {
    "host": "127.0.0.1",
    "port": 8876,
    "pid": 12345,
    "ready_marker_observed": true
  },
  "run_started_at": "ISO-8601 timestamp",
  "run_finished_at": "ISO-8601 timestamp",
  "execution_constraints_observed": {
    "main_task_only": true,
    "codex_cli_calls": 0,
    "subagent_calls": 0,
    "chrome_calls": 0,
    "substitute_browser_calls": 0
  },
  "forbidden_evidence_access": {
    "gateway_admin_logs_opened": false,
    "gateway_log_or_trace_read": false,
    "gateway_database_or_request_log_read": false,
    "session_or_rollout_jsonl_read": false,
    "archived_session_metadata_read": false
  },
  "matrix_completed": true,
  "expected_capability_count": 23,
  "recorded_capability_count": 23,
  "missing_capability_ids": [],
  "recovery_events": [
    {
      "after_capability": "capability id",
      "method": "reload_fixture | fresh_iab_tab",
      "ready_marker_observed": true,
      "note": "short observation"
    }
  ],
  "capability_observations": [
    {
      "id": "stable capability id",
      "browser_operations": ["short operation names"],
      "call_returned": true,
      "observed_postcondition": "exact short synthetic observation or null",
      "error": null,
      "note": null
    }
  ],
  "cleanup": {
    "viewport_reset": true,
    "test_tabs_finalized": true,
    "fixture_server_stopped": true
  },
  "judge_handoff_required": true
}
```

`fixture_server.pid` must be the positive integer PID returned by the shell
when this run starts the server, not a later name-based lookup. The executor
must preserve the original value after cleanup so the judge can check for a
surviving process and listener. The executor's final response must repeat this
exact PID and port.

Use `null` when no postcondition was observed; do not replace it with an
interpretive status. Keep observations short and synthetic. Do not include DOM
dumps, screenshots, Browser source, credentials, headers, clipboard contents,
data URLs, model payloads, raw logs, or raw JSONL records.
