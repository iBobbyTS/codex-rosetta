Test `collaboration.interrupt_agent` using only `collaboration` Namespace tools.

1. Call `collaboration.spawn_agent` with task name `interrupt_probe`,
   `fork_turns` set to `none`, and this exact child message:
   `Call collaboration.wait_agent with timeout_ms 120000 and remain active until interrupted. Do not send a completion marker.`
2. Call `collaboration.list_agents` with `path_prefix` set to
   `interrupt_probe` and require `/root/interrupt_probe` to be resident.
3. Call `collaboration.interrupt_agent` targeting `/root/interrupt_probe`.
   Require a successful result containing `previous_status`.
4. Call `collaboration.list_agents` again with the same prefix and require the
   same canonical child path to remain resident after interruption.

Do not close, replace, or respawn the child. If interruption fails or removes
the child, reply with only `RESULT:INTERRUPT_AGENT_FAILED`. Otherwise reply
with only `RESULT:INTERRUPT_AGENT_OK`.
