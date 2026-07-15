Continue from the existing compacted task without running commands or reading
files. Return only one compact JSON object with exactly these keys:
`project`, `completed_stage`, `immutable_file`, `timezone`, `active_endpoint`,
`superseded_endpoint`, `predeploy_gate`, `reference_code`, `rollout_strategy`,
`strategy_reason`, `deployment_owner`. Use the latest effective state. Preserve
exact paths, filenames, codes, and qualifiers. Set `deployment_owner` to JSON
null if no owner was assigned. Do not add Markdown or an evaluation.
