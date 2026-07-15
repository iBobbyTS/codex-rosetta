Test `collaboration.list_agents` using only `collaboration` Namespace tools.

1. Call `collaboration.spawn_agent` with task name `list_probe`,
   `fork_turns` set to `none`, and this exact child message:
   `Reply with only SUBAGENT:LIST_OK without using tools.`
2. Use `collaboration.wait_agent` until the child completes with exact marker
   `SUBAGENT:LIST_OK`.
3. Call `collaboration.list_agents` with `path_prefix` set to `list_probe`.
4. Require its result to contain canonical path `/root/list_probe` with a
   completed status that includes `SUBAGENT:LIST_OK`.

Do not infer the list result from the earlier spawn output. If `list_agents`
does not return the required resident child and completed state, reply with
only `RESULT:LIST_AGENTS_FAILED`. Otherwise reply with only
`RESULT:LIST_AGENTS_OK`.
