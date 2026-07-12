# Command Execution Suite

This suite isolates command start and continuation behavior. It intentionally
avoids file-editing tasks and broad repository questions so that failures can
be attributed to tool selection, argument construction, or process-session
handling.

## Task matrix

| Task | Behavior under test | Expected native pattern |
|---|---|---|
| `01` | One short foreground command | One command start; no continuation |
| `02` | A command that outlives the initial yield | One command start; one or more empty-input polls on the returned session |
| `03` | One interactive prompt | One command start; one non-empty write to the returned session |
| `04` | Two interactive stages | One command start; two ordered non-empty writes to the same session |

Use task `01` as the default command smoke test. In a real-provider matrix,
run tasks `02` through `04` only after that model completes task `01`.

Each numbered directory contains:

- `TASK.md`: the prompt passed verbatim to `codex exec`;
- `scenario.py`: the deterministic local process;
- `expected.json`: machine-readable expectations for evidence review.

`common/AGENTS.md` is copied into every runtime workspace. The prompts specify
the required wait/interaction pattern directly so the test does not depend on
planning skill or repository knowledge.

## Result interpretation

A task passes only when both conditions hold:

1. the final assistant message contains exactly the expected `RESULT:` marker;
2. the Codex rollout shows the interaction pattern in `expected.json`.

Do not treat a correct final marker as sufficient if the agent restarted a
process instead of continuing its session. Do not score wording, explanation,
or efficiency beyond the explicit call-count constraints.

Interpret the `expected.json` interaction fields as follows:

- `command_starts` counts new process starts;
- `continuations_min` and `continuations_max` count later operations on a
  returned process session;
- `non_empty_writes` counts continuation operations that send input;
- when `same_session_required` is true, every continuation must reuse the
  session returned by the single initial command.

For Responses-to-Chat routes, record three layers separately: the localized
command call visible to the upstream model, the native Codex command-start call
reconstructed by Rosetta, and every later native continuation. This distinction
detects routes that start a process correctly but lose polling or stdin
intervention.
