# Task: execute the in-app Browser live capability matrix

You are the **test executor**, not the judge. Run the Browser actions, record
bounded observable results, clean up, and report the execution artifact. Do not
assign per-capability statuses or an overall success/failure classification.

Run this test entirely inside the current Codex GUI app main task.

Hard requirements:

1. Use the explicitly attached `@Browser` plugin and
   `$browser:control-in-app-browser` skill.
2. Select and keep the in-app Browser (`iab`) binding required by that skill.
3. Do not use any Codex CLI command or `codex exec`.
4. Do not spawn or delegate to a subagent for execution, monitoring, or
   evaluation.
5. Do not use Chrome or the Chrome extension backend, even as a fallback.
6. Do not use standalone Playwright, Selenium, Computer Use, `web.run`, another
   browser MCP, or raw HTTP to perform or prove browser interactions.

## Executor-only evidence boundary

Do not open, search, tail, query, or otherwise inspect any of the following:

- Rosetta Gateway Logs in the Admin UI;
- Gateway log files, stream traces, request-log databases, or Request Log rows;
- this task's session JSONL or any other Codex session/rollout JSONL;
- archived sessions, rollout metadata, or raw model request/response traces.

Do not read `tests/live_agent/browser_use/EVALUATION.md` or perform the judge's
work. Log correlation, execution-provenance verification, capability status
classification, and the overall verdict belong exclusively to a separate judge
agent after the user hands off your report.

## Execution

Read and follow:

- `tests/live_agent/browser_use/01/expected.json`
- `tests/live_agent/browser_use/EXECUTION_REPORT.md`

Before starting the fixture or Browser, create this run's unique workspace:

```text
.agent-work/live-agent-test/{YYYYMMDD-HHMM}
```

Compute the timestamp once from the host's local time. Create the exact
directory without `-p` or any overwrite behavior. If it already exists, stop
before Browser setup and tell the user to start a new test in a new minute. Do
not reuse, delete, rename, or clear an earlier run directory, and do not add a
model name, counter, seconds, or another suffix. Retain the exact absolute
`run_root` path for the entire executor/judge handoff.

Through the main GUI task's ordinary shell tool, start
`python3 tests/live_agent/browser_use/serve_fixture.py --port 8876`, retain its
process handle, and write bounded server output to `<run_root>/fixture-server.log`.
Verify only that the server reports its ready marker. Open
`http://127.0.0.1:8876/` in the selected in-app Browser.

Exercise each executor capability group in `expected.json` in order. Before
every action, resolve a unique semantic locator or obtain fresh screenshot/DOM
coordinates as applicable. After each group, record the Browser operation,
whether the call returned, the exact bounded page-level postcondition, and any
error or limitation in `<run_root>/execution.json`. Do not convert
those observations into `pass`, `partial`, `fail`, or an overall classification.

Do not stop the matrix when an individual operation errors or its expected
postcondition is absent. Record the raw bounded outcome and recover:

1. Reload the fixture entry URL for ordinary state contamination.
2. Re-observe the expected title and `ready` marker.
3. If the tab is stale, blocked, or unusable, discard only that tab binding and
   create a fresh fixture tab from the existing IAB binding.
4. Do not reinitialize the Browser runtime, reselect a browser, switch backend,
   or use a prohibited fallback during recovery.
5. Continue until every executor capability group has one observation row,
   including cleanup.

Only an invalid execution gate or an unavailable/disconnected IAB binding that
prevents further Browser calls may end execution early. Record the stopping
condition without judging it.

Dialog actions require special care: never race the user. If the user handles a
dialog in the GUI, stop automated dialog handling and re-observe the page. Keep
fixture data synthetic. Do not inspect browser history, cookies, local storage,
profiles, passwords, session stores, or the pre-existing system clipboard.
Clipboard coverage may write, read back, and clear only a synthetic marker
created by this task.

At the end, reset any viewport override, close/finalize all test tabs, stop the
exact fixture server process, and finish `execution.json` according to
`EXECUTION_REPORT.md` inside the same run root. Never copy or move it to a
shared result path.

## Required final response and handoff

Report only:

- whether the execution matrix was completed;
- the number of recorded capability observations and any missing ids;
- a concise list of observed errors or missing postconditions, without judging
  them;
- cleanup state;
- the exact absolute run-root path;
- the clickable path to `execution.json`.

Do not state `success`, `success_with_limitations`, `partial`, `failure`,
`invalid_environment`, or `invalid_execution` as a verdict.

End by telling the user exactly this:

> 请把本回复完整复制到一个新的 judge agent session，并同时提供
> 本次 `.agent-work/live-agent-test/{YYYYMMDD-HHMM}` 运行目录、其中
> `execution.json` 的路径和本测试 session/thread id。
> 由 judge agent 按 `tests/live_agent/browser_use/JUDGE_TASK.md` 独立检查日志并
> 给出最终分类；当前测试 agent 不负责判定结果。
