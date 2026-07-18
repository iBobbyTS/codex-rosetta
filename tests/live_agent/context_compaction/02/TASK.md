Run `python3 scenario.py` exactly once. Do not read the script to infer its
output and do not run any other command. Configure the command tool to retain
at least 20,000 output tokens (`max_output_tokens=20000` when that argument is
available); a 1,000-token result is invalid because it cannot cross the
compaction threshold. After it finishes, reply with only
`RESULT:COMPACTION_PROTOCOL_OK`.
