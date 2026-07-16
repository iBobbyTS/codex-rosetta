Use [@deferred-marker](plugin://deferred-marker@rosetta-live-fixtures) exactly
as follows:

1. In the JavaScript `exec` runtime, filter the global `ALL_TOOLS` array for the
   deterministic marker plugin tool and emit the matching metadata with
   `text(...)`. `ALL_TOOLS` is not a shell variable: do not call
   `exec_command`, and do not guess a nested tool name.
2. Invoke the matching nested MCP tool with
   `value` set to exactly `ROSETTA_DEFERRED_20260716`. Use the discovered
   entry dynamically as `tools[entry.name](args)` inside `exec`.
3. Verify that the tool result is exactly
   `PLUGIN_TOOL_OK:ROSETTA_DEFERRED_20260716`.
4. Reply with exactly this one line and nothing else:

`RESULT:PLUGIN_DISCOVERY_OK`

Do not use shell commands, browser tools, network tools, file tools, or another
plugin. If a required tool is unavailable or errors, do not substitute another
mechanism; reply with exactly `RESULT:PLUGIN_DISCOVERY_FAILED`.
