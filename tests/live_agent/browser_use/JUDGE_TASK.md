# Task: judge an in-app Browser live execution

You are the independent **judge agent**, not the Browser test executor. The
user must provide the executor's copied final response, the path to
the exact `.agent-work/live-agent-test/{YYYYMMDD-HHMM}` run root, that root's
`execution.json`, and the source test session/thread id.

Read:

- `tests/live_agent/browser_use/01/expected.json`
- `tests/live_agent/browser_use/EVALUATION.md`
- the supplied `execution.json`

Do not rerun Browser actions and do not modify the execution report. Inspect
only bounded, credential-free Gateway and source-session evidence needed by
`EVALUATION.md`. Classify every executor observation, perform the separate
Gateway/rollout correlation check, write `<run_root>/evaluation.json`, and
report the final verdict with the run root and evaluation artifact path. Use
only the exact run root supplied by the user. Do not select the newest
timestamp directory, reuse another run, or write to a shared artifact path.
