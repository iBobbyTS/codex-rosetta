Use the standalone MCP server installed in this isolated Codex home.

1. In the JavaScript `exec` runtime, filter the global `ALL_TOOLS` array for the
   read-only deterministic marker tool and emit the matching metadata with
   `text(...)`. `ALL_TOOLS` is not a shell variable: do not call
   `exec_command`, and do not guess a nested tool name.
2. Invoke the matching nested MCP tool with `value` set to exactly
   `ROSETTA_DEFERRED_20260716`. Use the discovered entry dynamically as
   `tools[entry.name](args)` inside `exec`.
3. Verify that its result contains exactly
   `PLUGIN_TOOL_OK:ROSETTA_DEFERRED_20260716`.
4. Reply with exactly `RESULT:MCP_DISCOVERY_OK` and nothing else.

Do not use shell, browser, network, or file tools as substitutes. If the MCP
tool is unavailable or fails, reply with exactly `RESULT:MCP_DISCOVERY_FAILED`.
