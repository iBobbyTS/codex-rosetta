# Codex File Editing Toolset Research - 2026-07-06

This note records the Codex file-editing tool surface observed while designing
open-model tool localization for Codex. It complements
`open_model_file_editing_tool_localization.md`.

## Snapshot

Sources checked:

- Codex manual fetched through the OpenAI docs helper.
- OpenAI Codex source cloned from `https://github.com/openai/codex`.
- Source snapshot: `cca16a10878202cb2f6e9666b6b4330329ea7e65`
  (`2026-07-06T21:22:51-07:00`,
  `feat(core): emit canonical command execution items (#31297)`).
- OpenAI Apply Patch API guide:
  `https://developers.openai.com/api/docs/guides/tools-apply-patch`.

## Main Finding

Codex's current local file-editing path is centered on `apply_patch`, not on a
Claude-Code-style `Read` / `Edit` / `Write` tool family.

There are several related but distinct surfaces:

1. Codex CLI direct tool mode:
   - `apply_patch` as a Responses `custom` freeform tool with a Lark grammar.
   - shell execution through either `exec_command` + `write_stdin`, or legacy
     `shell_command`.

2. Codex code mode:
   - model sees `exec` and `wait`.
   - `exec` runs raw JavaScript in a V8 isolate and exposes nested tools on a
     global `tools` object.
   - nested tools can include `apply_patch`, shell tools, MCP tools, and other
     registered tools.

3. OpenAI public Apply Patch API guide:
   - documents a hosted Responses tool shape using `{"type": "apply_patch"}`.
   - wire events include `apply_patch_call` and `apply_patch_call_output`.
   - this is not the same wire shape as the open-source Codex CLI freeform
     `custom` tool named `apply_patch`.

4. Legacy shell compatibility:
   - Codex can intercept shell commands such as
     `apply_patch <<'EOF' ... EOF`.
   - This is compatibility behavior. Newer prompts tell the model to use the
     `apply_patch` tool directly rather than wrapping it in shell JSON.

## Direct Mode Tool Surface

### `apply_patch`

Source:

- `codex-rs/core/src/tools/handlers/apply_patch_spec.rs`
- `codex-rs/core/src/tools/handlers/apply_patch.lark`
- `codex-rs/core/src/tools/handlers/apply_patch.rs`
- `codex-rs/apply-patch/src/parser.rs`
- `codex-rs/apply-patch/src/lib.rs`

Model-visible Responses tool shape:

```json
{
  "type": "custom",
  "name": "apply_patch",
  "description": "Use the `apply_patch` tool to edit files. This is a FREEFORM tool, so do not wrap the patch in JSON.",
  "format": {
    "type": "grammar",
    "syntax": "lark",
    "definition": "..."
  }
}
```

Core grammar:

```text
start: begin_patch hunk+ end_patch
begin_patch: "*** Begin Patch" LF
end_patch: "*** End Patch" LF?

hunk: add_hunk | delete_hunk | update_hunk
add_hunk: "*** Add File: " filename LF add_line+
delete_hunk: "*** Delete File: " filename LF
update_hunk: "*** Update File: " filename LF change_move? change?

filename: /(.+)/
add_line: "+" /(.*)/ LF -> line

change_move: "*** Move to: " filename LF
change: (change_context | change_line)+ eof_line?
change_context: ("@@" | "@@ " /(.+)/) LF
change_line: ("+" | "-" | " ") /(.*)/ LF
eof_line: "*** End of File" LF
```

When multiple execution environments are attached, Codex extends the grammar
with:

```text
environment_id: "*** Environment ID: " filename LF
```

Semantic behavior:

- Supports add, delete, update, and move.
- Patch paths are resolved relative to the selected environment cwd.
- Parser is lenient around some legacy heredoc forms.
- Verification reads the target files before applying update/delete hunks.
- Runtime evaluates sandbox and approval policy before applying changes.
- Actual application is Codex's own patch engine, not plain `git apply`.
- Applied deltas are tracked for UI, telemetry, rollback/audit, and failure
  reporting.
- Streaming patch input can emit `PatchApplyUpdated` progress events when the
  `ApplyPatchStreamingEvents` feature is enabled.

### `exec_command`

Source:

- `codex-rs/core/src/tools/handlers/shell_spec.rs`
- `codex-rs/core/src/tools/handlers/unified_exec/exec_command.rs`
- `codex-rs/core/src/tools/handlers/unified_exec/write_stdin.rs`

Model-visible function tool name: `exec_command`.

Main input schema:

```text
cmd: string
workdir?: string
tty?: boolean
yield_time_ms?: number
max_output_tokens?: number
shell?: string
login?: boolean
environment_id?: string
sandbox_permissions?: "use_default" | "with_additional_permissions" | "require_escalated"
additional_permissions?: { file_system?: { read?: string[], write?: string[] }, network?: { enabled?: boolean } }
justification?: string
prefix_rule?: string[]
```

Notes:

- `cmd` is the command string.
- `shell` may be omitted in zsh-fork mode unless a remote environment is
  attached.
- Long-running commands return a `session_id` that can be continued with
  `write_stdin`.
- Hooks see this as canonical `Bash` through `HookToolName::bash()`.
- `exec_command` still intercepts legacy apply-patch shell invocations and
  routes them through the apply-patch handler.

### `write_stdin`

Model-visible function tool name: `write_stdin`.

Main input schema:

```text
session_id: number
chars?: string
yield_time_ms?: number
max_output_tokens?: number
```

Notes:

- Continues or polls a running unified exec session.
- Empty `chars` is treated as a background poll.
- Non-empty `chars` is a terminal interaction event.

### `shell_command`

Source:

- `codex-rs/core/src/tools/handlers/shell_spec.rs`
- `codex-rs/core/src/tools/handlers/shell/shell_command.rs`

Model-visible function tool name: `shell_command`.

Main input schema:

```text
command: string
workdir?: string
timeout_ms?: number
login?: boolean
sandbox_permissions?: "use_default" | "with_additional_permissions" | "require_escalated"
additional_permissions?: { file_system?: { read?: string[], write?: string[] }, network?: { enabled?: boolean } }
justification?: string
prefix_rule?: string[]
```

Notes:

- This is the older shell tool surface.
- When unified exec is model-visible, `shell_command` may remain registered as
  hidden dispatch-only compatibility.
- Hooks also see shell-like commands as canonical `Bash`.

## Model Metadata Controls

Source:

- `codex-rs/protocol/src/openai_models.rs`
- `codex-rs/core/src/tools/spec_plan.rs`
- `codex-rs/tools/src/tool_config.rs`

Relevant model metadata:

```text
shell_type:
  default | local | unified_exec | disabled | shell_command

apply_patch_tool_type:
  freeform

tool_mode:
  direct | code_mode | code_mode_only
```

Important behavior:

- `apply_patch` is only added when an environment exists and
  `model_info.apply_patch_tool_type` is set.
- The only currently defined `ApplyPatchToolType` in the source snapshot is
  `Freeform`.
- Shell tool visibility is controlled by model `shell_type` plus feature flags.
- With unified exec enabled and supported, Codex exposes
  `exec_command` + `write_stdin` and keeps `shell_command` hidden.
- With shell command mode, Codex exposes `shell_command`.
- With code mode enabled, Codex may expose `exec` and `wait` instead of the
  ordinary nested tools, depending on `tool_mode`.

## Code Mode

Source:

- `codex-rs/core/src/tools/code_mode/execute_spec.rs`
- `codex-rs/core/src/tools/code_mode/execute_handler.rs`
- `codex-rs/code-mode-protocol/src/description.rs`

Model-visible tools:

- `exec`: freeform raw JavaScript source, not JSON.
- `wait`: JSON function tool for resuming a yielded `exec` cell.

`exec` behavior:

- Runs raw JavaScript in a fresh V8 isolate.
- No Node, filesystem, network, or console access inside the isolate.
- Nested tools are exposed as async functions on global `tools`, for example
  `await tools.exec_command(...)`.
- `exec` input may start with a first-line pragma:

```text
// @exec: {"yield_time_ms": 10000, "max_output_tokens": 1000}
```

Code mode is a tool-composition runtime, not a simpler file editing API. For
Codex localization, direct mode and code mode need separate handling.

## Hook Names And Compatibility Aliases

Source:

- `codex-rs/core/src/tools/hook_names.rs`
- Codex manual hook matcher table.

Hook-facing names:

- File edits serialize as canonical `apply_patch`.
- Hook matchers may also use `Edit` or `Write` as aliases for `apply_patch`.
- Shell-like tools serialize as canonical `Bash`.

Important implication:

`Edit` and `Write` are not Codex model-visible file editing tools in this source
snapshot. They are hook matcher compatibility aliases, mainly useful for
configurations that describe file edits using Claude-Code-style names.

## Prompt Guidance

Sources:

- `codex-rs/core/gpt_5_1_prompt.md`
- `codex-rs/core/gpt_5_2_prompt.md`
- `codex-rs/core/gpt-5.2-codex_prompt.md`
- `codex-rs/core/prompt_with_apply_patch_instructions.md`

Observed guidance:

- Newer prompts tell the model to use `apply_patch` as a tool and not wrap the
  patch in JSON.
- The standalone Codex prompt says to try `apply_patch` for single-file edits,
  but allows other methods when patching is not efficient, such as generated
  files, formatter output, or broad mechanical replacement.
- Older prompt text still described `apply_patch` as a shell command. The
  runtime keeps shell interception compatibility for that legacy path.

## OpenAI API Apply Patch Guide Difference

The OpenAI API guide documents:

```json
{
  "tools": [{ "type": "apply_patch" }]
}
```

That hosted tool produces response items such as:

```text
apply_patch_call
apply_patch_call_output
```

Do not assume this is the same wire shape as the open-source Codex CLI's
freeform `custom` tool named `apply_patch`. A gateway that wants to support both
should model them as separate variants:

```text
CodexCustomApplyPatch
OpenAIHostedApplyPatch
```

They can share the same internal FileEditIR after parsing, but their model
request and response item shapes differ.

## Localization Implications

For adapting open models to Codex:

- Codex's native endpoint is still `apply_patch`, so a Claude-Code-like
  `Edit` / `Write` model-facing profile must translate into Codex
  `apply_patch` or direct filesystem writes before returning the equivalent
  Codex result.
- If the gateway simply exposes Codex native tools to open models, the model
  must produce freeform Lark-constrained patch text.
- If the gateway exposes Claude-Code-like tools to the model, it should own:
  exact-match validation, patch generation, and Codex response synthesis.
- `Edit` and `Write` should not be treated as Codex-native tools merely because
  hooks accept those matcher names.
- Code mode is a separate future target. It requires translating or generating
  JavaScript that calls `tools.apply_patch(...)` or `tools.exec_command(...)`.
- The adapter should preserve apply-patch progress and final delta semantics
  when possible, because Codex UI and logs distinguish patch apply events from
  ordinary shell output.

Recommended first Codex-localization target:

```text
Claude-Code-like Read/Edit/Write/Glob/Grep/Bash
  -> FileEditIR and shell IR
  -> Codex direct-mode apply_patch + exec_command/write_stdin
```

Recommended second target:

```text
Claude-Code-like or OpenCode-like tools
  -> FileEditIR and shell IR
  -> Codex code-mode exec/wait with nested tools
```

Keep hosted OpenAI `apply_patch` support separate unless the upstream actually
advertises the hosted `type: "apply_patch"` tool and returns
`apply_patch_call` items.
