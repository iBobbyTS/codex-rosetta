# Deferred Plugin Tool Search Workspace

This workspace tests isolated discovery of a plugin, standalone MCP server, or
standalone skill.

- Follow `TASK.md` exactly and perform the operations in its stated order.
- For MCP tasks, `ALL_TOOLS` is a JavaScript global array inside the `exec`
  runtime. It is not a shell environment variable and must not be inspected by
  calling `exec_command`. Filter that array inside `exec`, then invoke the
  discovered entry through `tools[entry.name](args)`.
- For the skill task, use the explicitly named skill and follow its complete
  injected body.
- Do not use shell commands, browser tools, network tools, file tools, or other
  plugins as substitutes.
- Do not modify files.
- Keep the final response to the exact result line requested by the task.
