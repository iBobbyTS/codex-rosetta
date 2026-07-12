# Namespace Tool Test

This suite verifies direct use of three Codex Namespace surfaces through
Codex-Rosetta: `clock`, `memories`, and `skills`. It does not measure planning,
research, coding, prose, or general agent quality.

## Scenario

- `01`: call one deterministic read-only operation from `clock`, `memories`,
  and `skills`.

All three Namespace checks live in one short task so a normal two-model matrix
needs only one isolated run for `gpt-5.6-terra` and one for
`deepseek-v4-flash`. Evaluation remains per Namespace: one missing or failed
Namespace does not erase evidence collected for the others.

Subagent lifecycle behavior is intentionally isolated in the
[`subagent_tools`](../subagent_tools/README.md) suite so each `collaboration`
Function can be evaluated independently.

## Required Codex configuration

Use the custom provider ID `namespace-test` with provider display name `openai`
for both models while keeping the isolated Rosetta localhost `base_url`. Codex
reserves the built-in `openai` ID and rejects attempts to override its URL, but
the exact display name supplies the OpenAI Namespace capability to the custom
test provider. Record this test-only identity override in the evaluation.

Add these feature flags to the isolated `config.toml`:

```toml
[features]
current_time_reminder = true
memories = true

[memories]
generate_memories = false
use_memories = true
dedicated_tools = true
```

After copying the suite task, prepare the isolated memory store without reading
or modifying the user's real memories:

```bash
mkdir -p "$RUN_ROOT/codex_home/memories"
cp "$RUN_ROOT/worktree/memory_fixture.md" \
  "$RUN_ROOT/codex_home/memories/memory_summary.md"
```

The `skills` Namespace is contributed only when the Codex runtime has an
app-server orchestrator skill provider. Do not replace it with ordinary local
Skill discovery. If `skills.list` is absent, the test must record
`skills.status = "not_exposed"` and the overall run fails even if the other
three Namespaces work.

## Provider matrix

Run task `01` once with each model:

| Model | Gateway model group | Expected route |
|---|---|---|
| `gpt-5.6-terra` | `GPT中转站` | Responses Tool Mapping only |
| `deepseek-v4-flash` | `DeepSeek` | Responses-to-Chat conversion |

Use a separate timestamp run root, Codex home, copied Gateway config, port, and
Gateway Logs trace for each row. Confirm the actual upstream model from Gateway
Logs rather than trusting the Codex-facing alias.

## Result interpretation

Follow [`EVALUATION.md`](EVALUATION.md) and write
`artifacts/evaluation.json`. A Namespace succeeds only when the rollout shows
the native call and a non-error result. Gateway Logs must additionally prove
the model-facing call name and conversion route.

For the Chat route, expected model-facing names are the unique flattened forms
`clock.curr_time`, `memories.list`, and `skills.list`; Rosetta must restore
their native Namespace metadata before Codex executes them. The exact name may
differ only if the current Codex/Rosetta contract deliberately changes the
stable flattening scheme, in which case record the observed name and review the
compatibility ledger.
