# Open Model File Editing Tool Localization

This note records the research and design decision for exposing local file
editing tools to open or third-party coding models when adapting them to Codex.
It is intended to guide future implementation, not to describe current gateway
behavior.

## Decision Summary

Expose one model-facing tool surface that is Claude-Code-like:

- `Read`
- `Edit`
- `Write`
- `Glob`
- `Grep`
- `Bash`

Use the Anthropic API text editor tool as a semantic reference for the internal
editing IR, not as the default model-facing tool surface.

The target architecture should be:

```text
Model-facing tools
  -> FileEditIR
  -> Codex apply_patch, shell execution, or direct local file operations
```

The model should see only one coherent tool set. The gateway or adapter may
support multiple profiles later, but a single run should not expose both Claude
Code names and Anthropic text-editor command names for the same editing action.

## Why There Are Two Anthropic-Related Tool Surfaces

Public documentation shows two different Anthropic-related surfaces:

1. Claude Code product tools.
   Claude Code exposes product-level tools such as `Read`, `Edit`, `Write`,
   `Glob`, `Grep`, `Bash`, `LSP`, `NotebookEdit`, and other workflow tools to
   the model running inside Claude Code.

2. Anthropic Messages API text editor tool.
   API users can enable `str_replace_based_edit_tool`, whose commands include
   `view`, `create`, `str_replace`, and `insert`. This is a built-in API tool
   for developers building their own agent runtimes.

The API is not limited to the text editor tool. It also supports custom client
tools, so an application can define tools named `Read`, `Edit`, and `Write` if
it implements them. However, those names are not automatically provided by the
generic Messages API.

Do not describe this as definitively "two trained editing standards" unless
there is a source for that claim. The safe public claim is: Anthropic documents
two different tool surfaces for two different host contexts.

## Why Use The Claude-Code-Like Surface For Open Models

The goal is to adapt GLM, DeepSeek, MiniMax, Qwen, and similar models to Codex.
The strongest public ecosystem signal is that these models are commonly
documented or recommended with Claude Code, OpenCode, Cline, Kilo, Roo, Cursor,
or their own coding agents.

Reasons to make the default model-facing profile Claude-Code-like:

- It is closer to a complete coding-agent runtime than the API text editor
  tool. It includes file reads, exact edits, whole-file writes, search, shell
  commands, and optionally language-server or notebook operations.
- It matches the tools these models are likely to see when users connect them
  to Claude Code or Claude-Code-compatible workflows.
- Exact string replacement is easier to validate and repair than free-form
  patch output for models that were not trained for Codex `apply_patch`.
- `Read` / `Edit` / `Write` map cleanly to an internal editing IR and can be
  executed as Codex `apply_patch` when the Codex side requires patch execution.
- The Anthropic API text editor tool lacks several product-agent capabilities
  that matter for coding workflows, especially whole-file overwrite, grep/glob,
  shell execution, and diagnostics.

Use the Anthropic text editor commands to shape the internal semantics:

```text
view
create
replace
insert
write
patch
```

Do not use the API text editor command names as the default model-facing names
unless the adapter is explicitly trying to emulate Anthropic Messages API.

## Recommended Version 1 Tool Surface

Version 1 should be small, stable, and easy to translate to Codex.

```ts
Read({
  file_path: string,
  offset?: number,
  limit?: number,
})

Edit({
  file_path: string,
  old_string: string,
  new_string: string,
  replace_all?: boolean,
})

Write({
  file_path: string,
  content: string,
})

Glob({
  pattern: string,
  path?: string,
})

Grep({
  pattern: string,
  path?: string,
  glob?: string,
  type?: string,
  output_mode?: "content" | "files_with_matches" | "count",
  case_insensitive?: boolean,
  line_numbers?: boolean,
  before_context?: number,
  after_context?: number,
  context?: number,
  head_limit?: number,
  offset?: number,
  multiline?: boolean,
})

Bash({
  command: string,
  timeout?: number,
  description?: string,
  run_in_background?: boolean,
})
```

Implementation notes for version 1:

- Enforce read-before-edit for `Edit` and read-before-overwrite for existing
  files passed to `Write`.
- `Edit.old_string` must be exact raw file text, not line-numbered text copied
  from `Read` output.
- By default, require a unique `old_string` match. Allow `replace_all` only
  when the model explicitly asks for repeated identical replacements.
- On edit failure, return a precise error and enough nearby context for the
  model to retry after rereading the file.
- Prefer translating `Edit` and `Write` to `apply_patch` on the Codex side when
  Codex requires patch-based file edits.
- Also keep a generated diff or patch for auditability even if the local
  executor writes files directly.
- Do not expose sandbox-disabling flags such as `dangerouslyDisableSandbox` to
  the model-facing `Bash` schema in the first version.

## Recommended Version 2 Additions

Version 2 should add capability only after version 1 has stable validation,
patch translation, and retry behavior.

Candidate additions:

- `NotebookEdit` for `.ipynb` cell-level edits:

  ```ts
  NotebookEdit({
    notebook_path: string,
    cell_id?: string,
    new_source: string,
    cell_type?: "code" | "markdown",
    edit_mode?: "replace" | "insert" | "delete",
  })
  ```

- Language-server helpers. Prefer explicit, narrow tools instead of one opaque
  `LSP` tool if the upstream schema is not stable:

  ```text
  Diagnostics(path?)
  GoToDefinition(path, line, column)
  FindReferences(path, line, column)
  ```

- `PowerShell` for Windows environments, with the same approval and sandbox
  policy as `Bash`.
- Optional `Insert` as a model-facing tool only if exact replacement proves too
  verbose for common append/insert tasks. Internally, keep `insert` available in
  FileEditIR from the beginning.
- Optional `ApplyPatch` for models or profiles that are known to be strong at
  patch generation. This should be a profile choice, not the default for all
  open models.
- Batch-edit support as a host-level optimization. Do not model it after
  unstable or undocumented `MultiEdit` behavior unless current docs later make
  that tool stable.

Do not add `undo_edit` as a model-facing tool initially. Prefer host-managed
rollback through generated diffs, git, or per-operation snapshots.

## Model And Agent Evidence

The following public sources informed the decision:

- Claude Code Tools Reference:
  `https://code.claude.com/docs/en/tools-reference`
  Documents Claude Code product tools such as `Read`, `Edit`, `Write`,
  `Glob`, `Grep`, `Bash`, `LSP`, and `NotebookEdit`.
- Claude Agent SDK TypeScript tool input types:
  `https://code.claude.com/docs/en/agent-sdk/typescript`
  Documents typed inputs for core tools such as `Read`, `Edit`, `Write`,
  `Glob`, `Grep`, `Bash`, and `NotebookEdit`.
- Anthropic Tool Use Overview:
  `https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview`
  Confirms that API developers can define client tools and execute tool results
  in their own runtimes.
- Anthropic Text Editor Tool:
  `https://platform.claude.com/docs/en/agents-and-tools/tool-use/text-editor-tool`
  Documents the API-level `str_replace_based_edit_tool` commands:
  `view`, `create`, `str_replace`, and `insert`.
- Z.AI GLM Coding Plan Quick Start:
  `https://docs.z.ai/devpack/quick-start`
  Lists Claude Code, Roo Code, Kilo Code, Cline, OpenCode, OpenClaw, and Cursor
  as integration targets.
- Z.AI Tool Integration:
  `https://docs.z.ai/devpack/tool/others`
  Lists Claude Code, OpenCode, Cursor, Cline, Qoder, Kilo, Roo, and related
  coding tools.
- GLM-5 model guide:
  `https://docs.z.ai/guides/llm/glm-5`
  Describes GLM-5 coding and agentic capabilities.
- Cline GLM-4.6 report:
  `https://cline.ghost.io/open-source-progress-continues-with-the-release-of-glm-4-6-in-cline/`
  Reports high diff-edit success for GLM-4.6 in Cline telemetry.
- DeepSeek AI Tools:
  `https://api-docs.deepseek.com/guides/coding_agents`
  Lists Claude Code, OpenCode, and OpenClaw integration paths.
- DeepSeek V4 release:
  `https://api-docs.deepseek.com/news/news260424`
  Describes DeepSeek-V4 agent and coding improvements and tool integrations.
- MiniMax M3 quick start:
  `https://platform.minimax.io/docs/token-plan/quickstart`
  Lists Claude Code, Cursor, Trae, OpenCode, Kilo Code, Grok CLI, Codex CLI,
  and Droid as coding tool integrations.
- MiniMax other tools:
  `https://platform.minimax.io/docs/token-plan/other-tools`
  Recommends Anthropic-compatible paths for Claude-Code-style tools and
  distinguishes OpenAI-compatible usage for tools such as Cursor and Aider.
- MiniMax M3 model page:
  `https://www.minimax.io/models/text/m3`
  Describes M3 as a coding and agentic model.
- Qwen3-Coder blog:
  `https://qwenlm.github.io/blog/qwen3-coder/`
  Lists Qwen Code, Claude Code, and Cline as agentic coding workflows.
- Qoder Agent Mode:
  `https://docs.qoder.com/user-guide/chat/agent`
  Describes Qoder's agent workflow and its generation/application stages for
  code changes.
- OpenCode tools:
  `https://opencode.ai/docs/tools/`
  Documents an agent tool surface that includes read, edit, write, and patch
  style operations.
- Cline tools:
  `https://docs.cline.bot/tools-reference/all-cline-tools`
  Documents Cline's file editing tools and tool-call style.
- Aider edit formats:
  `https://aider.chat/docs/more/edit-formats.html`
  Shows that coding agents often choose edit formats per model rather than
  relying on one universal patch format.
- Aider leaderboard:
  `https://aider.chat/docs/leaderboards/`
  Provides evidence that some open models can generate well-formed diffs, but
  performance depends heavily on the chosen edit format and harness.

## Practical Guidance For Implementation

- The default open-model profile should be Claude-Code-like.
- A Codex-native profile may still expose `apply_patch` directly for models
  known to work well with Codex.
- If the adapter receives a model-generated `Edit`, validate it against the
  current file and only then generate a patch or write operation.
- Preserve user work by checking file freshness between `Read` and `Edit`.
- Return tool errors that are useful to the model, not just generic failures.
- Keep the model-facing schema stable. Make profile changes explicit and
  model-specific.
- Treat API text editor commands as a clean internal vocabulary, not as the
  only or preferred model-facing interface.
