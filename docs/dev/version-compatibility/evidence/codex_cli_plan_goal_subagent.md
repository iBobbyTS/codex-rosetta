# Codex CLI plan/goal/subagent Rosetta test
Date: 2026-07-07
Codex version: 0.144.0

Historical compatibility evidence; use the maintained ledger and reports for
current conclusions.

## Confirmed observations

- Test skill: `.agents/skills/rosetta-codex-readme-test/SKILL.md`.
- Test repo: `/Users/ibobby/Projects/AGENTS.md-test`, currently clean on branch `main`.
- Test Codex home: `/Users/ibobby/Projects/codex-rosetta/codex-test-home`.
- Test config currently points Rosetta base URL to `http://127.0.0.1:8772/v1`.
- An isolated Rosetta gateway was started from the current worktree on `127.0.0.1:8772` with config `/Users/ibobby/Projects/codex-rosetta/rosetta-test-config/codex-cli-tools-test-20260707-1422.jsonc`.
- Rosetta trace for the 2026-07-07 14:22 test run: `/Volumes/RAM Disk/codex-cli-tools-test-20260707-1422.jsonl`.
- `codex exec --help` does not expose an explicit `--mode plan` flag.
- OpenAI Codex source shows Plan Mode questions use the `request_user_input` tool, while the Proposed Plan card is parsed from `<proposed_plan>...</proposed_plan>` output into `item/plan/delta`.
- OpenAI Codex `exec/src/lib.rs` sends `TurnStartParams { collaboration_mode: None }` for `codex exec`; `core/src/session/mod.rs` initializes the session collaboration mode as `ModeKind::Default`. This is strong evidence that non-interactive `codex exec` cannot directly start a Plan Mode turn.
- Unit verification for the current namespace-tool fix passed: `PATH=/Users/ibobby/miniconda3/envs/llm-rosetta/bin:$PATH pytest tests/converters/openai_responses/test_tool_ops.py tests/test_pipeline.py -q` -> `101 passed`.

## Current code fix under test

- Responses namespace tools, such as Codex `multi_agent_v1`, are flattened to child Chat functions such as `spawn_agent`, `wait_agent`, and `close_agent` when converting Responses -> Chat.
- The request conversion stores child-tool -> namespace mappings in `ConversionContext`.
- Chat response and streaming tool calls restore the original Responses namespace before returning to Codex, so Codex sees `{"type":"function_call","name":"spawn_agent","namespace":"multi_agent_v1"}` instead of unsupported bare `multi_agent_v1` or missing namespace.

## 2026-07-07 14:22 CLI test evidence

### gpt-5.5 through Rosetta

- TODO/update_plan passed.
  - stdout: `/Volumes/RAM Disk/gpt55-todo-20260707-1422.jsonl`
  - rollout: `/Users/ibobby/Projects/codex-rosetta/codex-test-home/sessions/2026/07/07/rollout-2026-07-07T14-23-12-019f3e3f-bef6-7271-ba7b-83cae8eafecc.jsonl`
  - Evidence: rollout includes `function_call` named `update_plan`; final says all 8 repo skills were covered.
- Subagent passed.
  - stdout: `/Volumes/RAM Disk/gpt55-subagent-20260707-1422.jsonl`
  - rollout: `/Users/ibobby/Projects/codex-rosetta/codex-test-home/sessions/2026/07/07/rollout-2026-07-07T14-23-49-019f3e40-4cc1-7dd0-b928-f491ab228c11.jsonl`
  - Evidence: rollout includes `spawn_agent`, `wait_agent`, and `close_agent` with namespace `multi_agent_v1`; subagent model was `gpt-5.4-mini`.
- Goal complete passed.
  - stdout: `/Volumes/RAM Disk/gpt55-goal-complete-20260707-1422.jsonl`
  - rollout: `/Users/ibobby/Projects/codex-rosetta/codex-test-home/sessions/2026/07/07/rollout-2026-07-07T14-24-41-019f3e41-17d2-7b50-a421-7b768d3d5581.jsonl`
  - Evidence: `get_goal` -> no goal, then `create_goal`, then `update_goal {"status":"complete"}` returned goal status `complete`.
- Goal blocked passed.
  - stdout: `/Volumes/RAM Disk/gpt55-goal-blocked-20260707-1422.jsonl`
  - rollout: `/Users/ibobby/Projects/codex-rosetta/codex-test-home/sessions/2026/07/07/rollout-2026-07-07T14-24-41-019f3e41-17eb-7f31-9f83-eb303d72c347.jsonl`
  - Evidence: `get_goal` -> no goal, then `create_goal`, then `update_goal {"status":"blocked"}` returned goal status `blocked`.

### deepseek-v4-flash through Rosetta

- TODO/update_plan passed.
  - stdout: `/Volumes/RAM Disk/ds-todo-20260707-1422.jsonl`
  - rollout: `/Users/ibobby/Projects/codex-rosetta/codex-test-home/sessions/2026/07/07/rollout-2026-07-07T14-26-06-019f3e42-6437-7d21-a8b7-9a7f8d33385f.jsonl`
  - Evidence: rollout includes `function_call` named `update_plan`; final `todo_list` contains all 8 repo skills.
- Subagent passed with the namespace fix.
  - stdout: `/Volumes/RAM Disk/ds-subagent-20260707-1422.jsonl`
  - rollout: `/Users/ibobby/Projects/codex-rosetta/codex-test-home/sessions/2026/07/07/rollout-2026-07-07T14-26-27-019f3e42-b7e9-7e63-804f-e45a2971970f.jsonl`
  - Evidence: rollout includes `spawn_agent`, `wait_agent`, and `close_agent` with namespace `multi_agent_v1`; no `unsupported call: multi_agent_v1`; subagent model was `gpt-5.4-mini`.
- Goal complete partially failed.
  - stdout: `/Volumes/RAM Disk/ds-goal-complete-20260707-1422.jsonl`
  - rollout: `/Users/ibobby/Projects/codex-rosetta/codex-test-home/sessions/2026/07/07/rollout-2026-07-07T14-27-03-019f3e43-44ca-74f1-947b-d6f998cb3caf.jsonl`
  - Evidence: model called `update_goal {"status":"complete"}` directly; Codex returned `cannot update goal because this thread has no goal`; model did not recover by calling `create_goal`.
- Goal blocked partially failed.
  - stdout: `/Volumes/RAM Disk/ds-goal-blocked-20260707-1422.jsonl`
  - rollout: `/Users/ibobby/Projects/codex-rosetta/codex-test-home/sessions/2026/07/07/rollout-2026-07-07T14-27-03-019f3e43-44ed-78e1-ab43-9bd25b2d6bfc.jsonl`
  - Evidence: model called `get_goal`, then `create_goal` with `token_budget: 100`, then `update_goal {"status":"blocked"}`. The update result became `budgetLimited` because the artificial budget was exceeded, not `blocked`.

## Current hypothesis

- Plan Mode cannot be proven through plain non-interactive `codex exec` because that path has no plan-mode entrypoint and starts turns with `collaboration_mode: None`.
- Responses namespace tool adaptation is now sufficient for DeepSeek subagent use: upstream Chat sees child tools, while Codex receives native namespaced Responses calls.
- DeepSeek Goal failures are tool-use policy/semantics failures, not protocol conversion failures. The model needs clearer guidance to create a goal first when none exists and not invent a token budget unless the user asks.

## Next diagnostics

- Decide whether to implement small Chat-target tool-description adaptation for `get_goal`/`create_goal`/`update_goal` to steer non-OpenAI models:
  - For `update_goal`, explain that if it returns no-goal / thread has no goal, the agent should call `create_goal` with no `token_budget` unless explicitly requested, then retry `update_goal`.
  - For `create_goal`, emphasize not to set `token_budget` unless the user explicitly asked for a budget.
  - Avoid changing Responses passthrough semantics for OpenAI models.
- If adapting descriptions, add focused tests over Responses -> Chat target tool definitions and rerun DeepSeek Goal complete/blocked probes.

## 2026-07-07 14:37 DeepSeek Goal retarget verification

After adding Chat-target goal tool description guidance, DeepSeek was retested through the isolated Rosetta gateway on `127.0.0.1:8772`.

- Gateway process: PID 88452, config `/Users/ibobby/Projects/codex-rosetta/rosetta-test-config/codex-cli-goal-retarget-20260707-1432.jsonc`.
- Rosetta trace: `/Volumes/RAM Disk/codex-cli-goal-retarget-20260707-1432.jsonl`.
- Complete stdout: `/Volumes/RAM Disk/ds-goal-complete-retarget-20260707-143746.jsonl`.
- Complete rollout: `/Users/ibobby/Projects/codex-rosetta/codex-test-home/sessions/2026/07/07/rollout-2026-07-07T14-37-47-019f3e4d-158e-7863-b0c6-8e59637b7896.jsonl`.
- Blocked stdout: `/Volumes/RAM Disk/ds-goal-blocked-retarget-20260707-143746.jsonl`.
- Blocked rollout: `/Users/ibobby/Projects/codex-rosetta/codex-test-home/sessions/2026/07/07/rollout-2026-07-07T14-37-54-019f3e4d-3279-7063-ad26-e6996fb38076.jsonl`.

Results:

- Goal complete now passes. Evidence: `get_goal {}` returned `goal:null`, then `create_goal {"objective":"Test goal tool — mark as completed immediately"}`, then `update_goal {"status":"complete"}` returned `goal.status:"complete"`; final answer was exactly `goal completed test done`.
- Goal blocked now passes. Evidence: `create_goal {"objective":"Goal tool test"}` omitted `token_budget`, then `update_goal {"status":"blocked"}` returned `goal.status:"blocked"`; final answer was exactly `goal blocked test done`.
- Test repo `/Users/ibobby/Projects/AGENTS.md-test` remained clean.

Updated hypothesis:

- DeepSeek Goal failures were steerability/description issues on the Chat-target tool surface, not protocol conversion failures. The current minimal description guidance appears sufficient for this probe.
- DeepSeek stable tool coverage through Rosetta is now: TODO/update_plan pass, subagent pass with namespace flatten/restore, goal complete/block pass with goal description guidance.

## 2026-07-07 Plan Mode CLI boundary

Confirmed by Codex CLI help and source inspection:

- `codex exec --help` exposes no `--mode`, `--plan`, or `collaboration_mode` option.
- `codex-rs/exec/src/lib.rs` constructs `TurnStartParams` with `collaboration_mode: None` for non-interactive exec turns.
- The same file explicitly rejects `ServerRequest::ToolRequestUserInput` in exec mode with `request_user_input is not supported in exec mode`.
- The interactive TUI cycle path is Shift+Tab (`KeyCode::BackTab`) -> `cycle_collaboration_mode()` -> `set_collaboration_mask_from_user_action()`, and then the active mode is attached to submissions as `collaboration_mode: Some(...)`.
- Plan content is not a tool. In Plan mode the stream parser splits `<proposed_plan>...</proposed_plan>` into `PlanDelta` and `TurnItem::Plan`.

Conclusion for this objective:

- `codex exec` cannot stably trigger the real Plan mode `request_user_input` / proposed-plan approval flow. This is a Codex CLI surface limitation, not a Rosetta conversion issue.
- To test Plan mode through Rosetta, use interactive TUI automation or app-server/SDK calls that can set `TurnStartParams.collaborationMode`. The bundled `app-server-test-client send-message-v2` currently does not expose a collaboration-mode flag; it would need a small test-client change or a direct SDK/json-rpc harness.



## 2026-07-07 post-compaction verification

Current-state verification after context compaction:

- Worktree still contains the intended Rosetta code changes only in converter/context/pipeline and focused tests. `.agent-work/` remains untracked and should not be committed.
- Focused tests passed again: `PATH=/Users/ibobby/miniconda3/envs/llm-rosetta/bin:$PATH pytest tests/converters/openai_chat/test_tool_ops.py tests/converters/openai_responses/test_tool_ops.py tests/test_pipeline.py -q` -> `128 passed`.
- Formatting and lint checks passed again on all changed files: `ruff format --check ...` -> `8 files already formatted`; `ruff check ...` -> `All checks passed!`.
- Evidence rescan of rollout JSONLs confirmed the expected tool calls:
  - gpt-5.5 TODO: `update_plan`.
  - gpt-5.5 subagent: `spawn_agent`, `wait_agent`, `close_agent`; `gpt-5.4-mini` appears in the session.
  - gpt-5.5 goal complete/blocked: `get_goal`, `create_goal`, `update_goal`.
  - deepseek-v4-flash TODO: `update_plan`.
  - deepseek-v4-flash subagent: `spawn_agent`, `wait_agent`, `close_agent`; `gpt-5.4-mini` appears in the session.
  - deepseek-v4-flash fixed goal complete: `get_goal`, `create_goal`, `update_goal`.
  - deepseek-v4-flash fixed goal blocked: `create_goal`, `update_goal`.
- `codex exec --help` still has no plan/collaboration-mode flag.
- Source evidence remains decisive: `codex-rs/exec/src/lib.rs` builds `TurnStartParams` with `collaboration_mode: None` and rejects `ServerRequest::ToolRequestUserInput` with `request_user_input is not supported in exec mode`.
- The generated TypeScript `TurnStartParams` schema in this source checkout does not expose `collaborationMode`; the Rust exec code has a field, but hard-codes it to `None`.
- The isolated Rosetta test service on `127.0.0.1:8772` was stopped. The user main gateway on `127.0.0.1:8765` was left running.

Current status:

- Stable via `codex exec` and verified through Rosetta/current code: TODO, subagent, goal complete, goal blocked.
- Not available through plain `codex exec`: true Plan mode `request_user_input` and proposed-plan approval flow. The remaining way to test it is interactive TUI automation or a direct app-server/SDK harness capable of setting Plan collaboration mode.
