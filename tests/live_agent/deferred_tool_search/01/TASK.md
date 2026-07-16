Use [@deferred-marker](plugin://deferred-marker@rosetta-live-fixtures) to
retrieve the immutable proof for archive record `ARCHIVE-20260716`.

In the JavaScript `exec` runtime, inspect the global `ALL_TOOLS` array and
dynamically invoke the matching read-only tool as `tools[entry.name](args)`.
Do not call `exec_command` and do not guess a nested tool name.

Verify that the tool returned `ARCHIVE_PROOF_OK:ARCHIVE-20260716`, then reply
with exactly `RESULT:PLUGIN_EXPLICIT_OK` and nothing else. If the required tool
is unavailable or fails, reply with exactly `RESULT:PLUGIN_EXPLICIT_FAILED`.
