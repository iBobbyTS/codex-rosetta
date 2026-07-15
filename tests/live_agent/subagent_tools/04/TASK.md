Test `collaboration.send_message` using only `collaboration` Namespace tools.

1. Call `collaboration.spawn_agent` with task name `message_probe`,
   `fork_turns` set to `none`, and this exact child message:
   `Call collaboration.wait_agent with timeout_ms 30000 until you receive the message PING:SEND_MESSAGE. Then reply with only SUBAGENT:SEND_MESSAGE_OK.`
2. Call `collaboration.send_message` targeting `/root/message_probe` with the
   exact message `PING:SEND_MESSAGE`.
3. Use `collaboration.wait_agent` until the child finishes. Require evidence
   that the child received `PING:SEND_MESSAGE` and the exact child marker
   `SUBAGENT:SEND_MESSAGE_OK`.

Do not replace `send_message` with `followup_task`. If message delivery or the
child marker is missing, reply with only `RESULT:SEND_MESSAGE_FAILED`.
Otherwise reply with only `RESULT:SEND_MESSAGE_OK`.
