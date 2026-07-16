# Task: judge an in-app Browser live execution

You are the independent **judge agent**, not the Browser test executor. The
user must provide the executor's copied final response, the path to
`artifacts/browser_use/01/execution.json`, and the source test session/thread id.

Read:

- `tests/live_agent/browser_use/01/expected.json`
- `tests/live_agent/browser_use/EVALUATION.md`
- the supplied `execution.json`

Do not rerun Browser actions and do not modify the execution report. Inspect
only bounded, credential-free Gateway and source-session evidence needed by
`EVALUATION.md`. Classify every executor observation, perform the separate
Gateway/rollout correlation check, write
`artifacts/browser_use/01/evaluation.json`, and report the final verdict with
the evaluation artifact path.
