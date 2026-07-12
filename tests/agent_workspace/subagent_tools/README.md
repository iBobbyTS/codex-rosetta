# Subagent Tool Test

This suite verifies the six Codex `collaboration` Namespace Functions through
Codex-Rosetta. It tests tool exposure, selection, argument delivery, lifecycle
state, and result reconstruction. It does not measure delegation judgment,
subagent intelligence, coding quality, or prose.

## Scenarios

Each task has exactly one core Function. Supporting calls only establish or
observe the required lifecycle state:

- `01`: `spawn_agent` creates a named child and returns its canonical path.
- `02`: `wait_agent` observes a child completion notification.
- `03`: `list_agents` returns the named child and its completed state.
- `04`: `send_message` delivers a queued message to a running child.
- `05`: `followup_task` starts a new turn on an idle completed child.
- `06`: `interrupt_agent` interrupts a running child without removing it.

Run every task in a separate isolated runtime. Do not combine the scenarios:
child state from one scenario must not satisfy another scenario.

## Required Codex configuration

Run the exact case-sensitive provider identities `custom` and `OpenAI` while
keeping the isolated Rosetta localhost `base_url`. Define each identity as a
custom provider entry whose display name exactly matches its ID. Codex compares
the display name to `OpenAI` case-sensitively, so do not use `openai`, `OPENAI`,
or any other spelling for the OpenAI matrix column.

Use these two shapes in separate runs:

```toml
model_provider = "custom"

[model_providers.custom]
name = "custom"
```

```toml
model_provider = "OpenAI"

[model_providers.OpenAI]
name = "OpenAI"
```

Both entries also require the normal `wire_api`, authentication, and isolated
Rosetta `base_url` fields from the runner Skill.

Enable Multi-Agent V2 in the isolated `config.toml`:

```toml
[features]
multi_agent_v2 = true
```

Do not enable or test legacy `multi_agent_v1` in this suite.

## Provider matrix

Run every provider/model/task combination:

| Model | Gateway model group | Expected route |
|---|---|---|
| `gpt-5.6-terra` | `GPT中转站` | Responses Tool Mapping only |
| `deepseek-v4-flash` | `DeepSeek` | Responses-to-Chat conversion |

Every provider/model/task cell requires its own timestamp run root, Codex home,
copied Gateway configuration, port, and Gateway Logs trace. Confirm the actual
upstream model from Gateway Logs.

## Result interpretation

Follow [`EVALUATION.md`](EVALUATION.md) and write
`artifacts/evaluation.json`. A scenario succeeds only when the rollout shows a
successful native call to its core Function and the scenario-specific state or
marker. Supporting calls may fail the scenario when they are necessary to
prove the core Function worked, but they are not reported as extra core tools.

For Responses-to-Chat routes, the canonical logical names are:

```text
collaboration-spawn_agent
collaboration-wait_agent
collaboration-list_agents
collaboration-send_message
collaboration-followup_task
collaboration-interrupt_agent
```

Rosetta also accepts compatible underscore and dotted forms such as
`collaboration_wait_agent` and `collaboration.wait_agent`, plus bare child names
when they identify exactly one Namespace child and do not collide with a
top-level Function. It must restore the `collaboration` Namespace before Codex
executes the call. Ambiguous names remain flat and fail closed. Record the
observed wire name and review the compatibility ledger if this contract changes.
