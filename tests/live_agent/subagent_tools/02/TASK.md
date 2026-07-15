Test `collaboration.wait_agent` using only `collaboration` Namespace tools.

1. Call `collaboration.spawn_agent` with task name `wait_probe`,
   `fork_turns` set to `none`, and this exact child message:
   `Reply with only SUBAGENT:WAIT_OK without using tools.`
2. Call `collaboration.wait_agent` with `timeout_ms` set to `30000`. Repeat the
   same wait only when it times out before the child's completion notification.
3. Require a non-timeout wait completion and the exact child marker
   `SUBAGENT:WAIT_OK`.

Do not use polling through another tool. If `wait_agent` is unavailable, never
called, returns an error, or never observes the child completion, reply with
only `RESULT:WAIT_AGENT_FAILED`. Otherwise reply with only
`RESULT:WAIT_AGENT_OK`.
