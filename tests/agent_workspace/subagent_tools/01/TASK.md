Test `collaboration.spawn_agent` using only `collaboration` Namespace tools.

1. Call `collaboration.spawn_agent` with task name `spawn_probe`,
   `fork_turns` set to `none`, and this exact child message:
   `Reply with only SUBAGENT:SPAWN_OK without using tools.`
2. Require the spawn result to contain canonical task path
   `/root/spawn_probe`.
3. Use `collaboration.wait_agent` only as cleanup and confirmation until the
   child finishes. Require the exact child marker `SUBAGENT:SPAWN_OK`.

Do not use another tool or infer success from the prompt. If the spawn call,
canonical path, or child marker is missing, reply with only
`RESULT:SPAWN_AGENT_FAILED`. Otherwise reply with only
`RESULT:SPAWN_AGENT_OK`.
