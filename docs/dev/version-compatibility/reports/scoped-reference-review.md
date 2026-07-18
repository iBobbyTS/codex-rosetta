# Codex Scoped Reference Review
Date: 2026-07-12
Codex version: 0.144.0

Status: **Pending / not approved**. This report records the exact 0.144.1
release source used as the current reference and the Namespace compatibility
repair. It does not advance the Codex-Rosetta package version or close the full
upgrade matrix.

## Identifiers

| Item | Value |
| --- | --- |
| Installed Codex CLI | `codex-cli 0.144.1` |
| Previous reviewed source reference | `2e8c3756f95789c215d9ea9a5ade6ec377934b3f` |
| Target release tag | `rust-v0.144.1` |
| Target release commit | `44918ea10c0f99151c6710411b4322c2f5c96bea` |
| Codex-Rosetta package version | `0.144.0.r0` (unchanged) |

The sibling source checkout is detached at the exact release tag and is clean.
The source commit, installed CLI, Rosetta package version and eventual clean
Rosetta release commit remain independent identifiers.

## Scoped source-contract review

The reviewed range changes only these relevant tool-planning files:

- `codex-rs/core/src/tools/code_mode/execute_spec.rs`;
- `codex-rs/core/src/tools/code_mode/mod.rs`;
- `codex-rs/core/src/tools/spec_plan.rs`.

Those changes replace the explicit deferred code-mode tool list with an
availability flag and add an in-process fallback when the code-mode host cannot
start. They do not change the Responses `FunctionCall.namespace` field or the
six `multi_agent_v2`/`collaboration` Function contracts. This is a scoped
source review, not a complete per-point 0.144.1 upgrade classification.

## Rosetta repair in this worktree

Responses-to-Chat Namespace expansion now uses the regex-safe canonical
`namespace-function` name. Return conversion also accepts unique
`namespace_function` and `namespace.function` forms, and a bare child name only when exactly one
Namespace owns it and no ordinary top-level Function has the same name.
Ordinary Function conflicts, shared child names and alias collisions remain
flat so Codex fails closed rather than executing the wrong Namespace Function.

The live failures also exposed a separate request-side contract. Codex sends a
spawned child's task in an `agent_message` item whose visible `input_text`
contains the routing envelope while the actual payload is carried in that
item's `encrypted_content`. Rosetta now converts `agent_message` to a Chat user
message and exposes that payload only for this item type. Ordinary encrypted
message/reasoning content remains opaque. Chat descriptions additionally give
bounded guidance for `spawn_agent`, `wait_agent`, `list_agents`, and
`send_message`.

Automated coverage includes streaming and non-streaming restoration plus all
three ambiguity classes. Real validation is limited to the requested
`provider=OpenAI`, `deepseek-v4-flash` six-scenario collaboration suite and
is recorded below. Native GPT and the complete 0.144.1
upgrade matrix are intentionally not claimed by this report.

## Real collaboration results

All runs used installed Codex `0.144.1`, `provider=OpenAI`, model alias and
confirmed upstream model `deepseek-v4-flash`, and the Responses-to-Chat route.
Gateway Logs showed the canonical model-facing names
`collaboration-spawn_agent`, `collaboration-wait_agent`,
`collaboration-list_agents`, `collaboration-send_message`,
`collaboration-followup_task`, and `collaboration-interrupt_agent`; successful
calls were restored to native `namespace="collaboration"` calls.

| Scenario | Controlled rounds before repair | Repair/prompt retest | Conclusion |
| --- | --- | --- | --- |
| `spawn_agent` | Two failures: child payload was absent and the child recursively reconstructed the parent task | `202607121315` succeeded after `agent_message` repair; `202607121333` succeeded with only extra final prose after Chat guidance | Core tool and child payload delivery verified |
| `wait_agent` | One success followed by failures; the accumulated error threshold was reached | `202607121317` and post-guidance `202607121325` both failed because the child completion had already entered the current parent input before the explicit wait | Namespace mapping and arguments are correct; Codex future-mailbox timing remains a scenario limitation |
| `list_agents` | One failed result and one timeout reached the error threshold | `202607121318` succeeded after payload repair; `202607121334` succeeded with only extra final prose after guidance | Core listing and completed child state verified |
| `send_message` | One failed result and one timeout reached the error threshold | `202607121319` succeeded after payload repair; `202607121335` proved message delivery and marker, with one harmless extra `exec_command` after the core behavior | Core message delivery verified with a recorded model deviation |
| `followup_task` | First round failed/timed out | Four later rounds (`202607121320`–`202607121323`) succeeded; stopped at the five-round cap | Core idle-child follow-up verified |
| `interrupt_agent` | Three consecutive successful rounds (`202607121308`, `202607121310`, `202607121311`) | No further round required | Core interruption and resident-child state verified |

The `wait_agent` failures are not malformed DeepSeek calls and cannot be fixed
by restoring another Namespace alias. In the failing runs the native call used
`{"timeout_ms":30000}`, but Codex had already delivered the child's
`FINAL_ANSWER` as an `agent_message`; `wait_agent` waits only for a future
mailbox update and does not replay that consumed notification. The prompt now
states that behavior, and the repeated post-guidance failure is retained as a
known test-timing gap rather than hidden by another fallback.

Automated verification on the final worktree: focused converter/gateway suite
`287 passed`; full non-integration suite `3084 passed, 5 skipped`; `make lint`
passed. Each formal live run has a repository-local `artifacts/evaluation.json`
and a RAM-Disk Gateway trace.

## Remaining gates

- Run the complete compatibility contract check and classify every changed or
  possibly unchanged point.
- Run all other triggered real Codex/API scenarios before advancing the
  package version or declaring 0.144.1 compatibility.
