Test `collaboration.followup_task` using only `collaboration` Namespace tools.

1. Call `collaboration.spawn_agent` with task name `followup_probe`,
   `fork_turns` set to `none`, and this exact child message:
   `Reply with only SUBAGENT:FOLLOWUP_READY without using tools.`
2. Use `collaboration.wait_agent` until the initial child turn completes with
   exact marker `SUBAGENT:FOLLOWUP_READY`.
3. Call `collaboration.followup_task` targeting `/root/followup_probe` with
   this exact message:
   `Reply with only SUBAGENT:FOLLOWUP_OK without using tools.`
4. Use `collaboration.wait_agent` until the same child completes the new turn
   with exact marker `SUBAGENT:FOLLOWUP_OK`.

Do not spawn a replacement child and do not replace `followup_task` with
`send_message`. If the same canonical child does not run both turns, reply with
only `RESULT:FOLLOWUP_TASK_FAILED`. Otherwise reply with only
`RESULT:FOLLOWUP_TASK_OK`.
