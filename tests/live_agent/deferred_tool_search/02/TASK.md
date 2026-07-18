Use the standalone MCP capabilities installed in this isolated Codex home to
retrieve the immutable proof for archive record `ARCHIVE-20260716`.

Use the exposed deferred-discovery surface. If `tool_search`, `tool_read`, and
`invoke_deferred_tool` are available, call them in that order and invoke only
the exact name returned by discovery. Otherwise, in the JavaScript `exec`
runtime inspect `ALL_TOOLS` and dynamically invoke the matching read-only tool
as `tools[entry.name](args)`. Do not call `exec_command` and do not guess a
nested tool name.

Verify that the tool returned `ARCHIVE_PROOF_OK:ARCHIVE-20260716`, then reply
with exactly `RESULT:MCP_EXPLICIT_OK` and nothing else. If the required tool is
unavailable or fails, reply with exactly `RESULT:MCP_EXPLICIT_FAILED`.
