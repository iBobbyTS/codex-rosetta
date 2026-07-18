# Codex Tool Localization - Resolved Debug Notes
Date: 2026-07-07
Codex version: 0.144.0

Historical compatibility evidence; use the maintained ledger and reports for
current conclusions.

## Confirmed Observations

- Current worktree started clean on `master`, ahead of `origin/master` by 5 commits.
- Admin/config already stores `tool_adaptation.localize_code_editing_tools`.
- `proxy._apply_tool_adaptation()` currently only removes `image_generation`.
- Responses -> Chat conversion currently exposes Codex native tools to Chat upstream, including `exec_command`, `write_stdin`, and `apply_patch`.
- Chat streaming tool calls arrive as `tool_call_start` plus argument deltas; there is no separate Chat args-done IR event before `finish`.

## Current Hypothesis

The least invasive implementation is gateway-only:

- After Responses -> Chat request conversion, replace native Codex edit/shell tools with Claude-Code-like `Read`, `Edit`, `Write`, `Glob`, `Grep`, `Bash`.
- Before Chat -> Responses response conversion reaches Codex, map localized tool calls back to native Codex tools:
  - `Bash`, `Read`, `Glob`, `Grep` -> `exec_command`
  - `Edit`, `Write` -> custom freeform `apply_patch`
- For streaming, buffer localized tool call IR events until `finish`, then emit translated native tool call start/delta events before the finish event.

## Verification Targets

- Unit tests for tool definition localization.
- Unit tests for non-streaming localized tool call translation.
- Unit tests for streaming localized tool call translation.
- Safe test executor verifies generated edit/write patches and bash command mapping.
- Real `deepseek-v4-flash` request count capped at 100.

## Verified Result

- Added gateway-only Codex tool localization for Responses -> Chat routes with
  `tool_adaptation.localize_code_editing_tools`.
- Localized model-facing tools are `Read`, `Edit`, `Write`, `Glob`, `Grep`,
  and `Bash`.
- Localized tool calls are translated back to native Codex `exec_command` or
  custom `apply_patch` before returning to Codex.
- Streaming localized tool calls are buffered until complete, then emitted as
  native Codex tool call events before finish.
- Relevant checks passed:
  - `ruff check src/llm_rosetta/gateway/tool_adaptation.py src/llm_rosetta/gateway/proxy.py src/llm_rosetta/pipeline.py tests/gateway/test_tool_adaptation.py`
  - `pytest tests/gateway/test_tool_adaptation.py tests/gateway/test_responses_passthrough.py tests/test_pipeline.py -q`
  - Real `deepseek-v4-flash` tool-selection test sent 3 requests and verified
    Bash success, Edit success, and Edit failure with useful context.
