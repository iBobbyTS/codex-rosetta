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
`EVALUATION.md`. In addition, perform its fixture process/listener cleanup
verification using the exact PID and port reported in `execution.json`.
Classify every executor observation, perform the separate Gateway/rollout
correlation check, write `<run_root>/evaluation.json`, and report the final
verdict with the run root and evaluation artifact path. Use only the exact run
root supplied by the user. Do not select the newest timestamp directory, reuse
another run, or write to a shared artifact path.

Never terminate a process merely because its name resembles the fixture or
because the port is open. Termination is allowed only when the reported PID
exists, the reported port is listening, the bounded localhost response is the
expected fixture, and the unique listener PID equals the reported PID. Record
all mismatches and leave the process untouched.
