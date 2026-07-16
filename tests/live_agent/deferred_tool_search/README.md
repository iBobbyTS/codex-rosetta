# Isolated Plugin, MCP, And Skill Discovery Test

This suite verifies three independently provisioned Codex capabilities in a
fresh isolated home: a local plugin, a standalone MCP server, and a standalone
skill. It uses the discovery surface selected by the Codex 0.144.4 model
catalog.

It intentionally does not use Browser, an app connector, user authentication,
or the user's normal `CODEX_HOME`.

## Scenario

- `01`: install and mention the local `deferred-marker` plugin, discover its
  deferred MCP tool through code mode `ALL_TOOLS`, and invoke it.
- `02`: install the same deterministic server with `codex mcp add`, without a
  plugin, then discover and invoke it through code mode `ALL_TOOLS`.
- `03`: copy a standalone skill into the isolated Codex home, explicitly invoke
  it, and prove that its complete body was injected.

Task `01` contains the structured plugin mention
`plugin://deferred-marker@rosetta-live-fixtures`. Installation alone does not
activate a plugin's MCP bundle for a turn; the mention is part of the real
Codex plugin contract and must remain in the exact prompt.

The MCP server is deterministic and read-only. Its only successful tool result
is `PLUGIN_TOOL_OK:ROSETTA_DEFERRED_20260716`.

## Isolated provisioning

Copy `common/` and exactly one selected task into the run worktree as required
by the live-agent runner. The copied local marketplace root is `marketplace`.

After copying the user's gateway configuration, prepare only the isolated copy
and Codex home:

```bash
conda run -n llm-rosetta python "$SUITE/prepare_run.py" \
  --run-root "$RUN_ROOT" \
  --gateway-log-root "$GATEWAY_LOG_ROOT" \
  --port 18765 \
  --model gpt-5.6-terra \
  --task-id 01
```

`prepare_run.py` provisions exactly the selected task after writing the
isolated config. Start a new `codex exec` only after it succeeds. Preserve its
installation/list outputs under `artifacts/`; they are evidence, not a runtime
success signal. For third-party aliases it also writes the copied gateway's
Terra-derived `model_catalog.json`; an unknown-model fallback is a setup
failure, not valid Responses-to-Chat/code-mode evidence.


## Required Codex configuration

Use a custom provider ID such as `deferred-tool-test` with provider display
name `openai` and the isolated Rosetta localhost `base_url`. The display name
enables Codex Namespace tool support for the custom provider.

Explicitly enable plugins:

```toml
[features]
plugins = true
```

## Model order and stop gate

Run `01`, `02`, and `03` with `gpt-5.6-terra` first, using a separate timestamp
root and gateway for every task. Do not start any `deepseek-v4-flash` cell
until all three Terra cells pass.

| Model | Gateway model group | Expected route |
|---|---|---|
| `gpt-5.6-terra` | `GPT中转站` | direct OpenAI Responses Lite/code-mode baseline |
| `deepseek-v4-flash` | `DeepSeek` | Responses-to-Chat with Tool Profile |

## Result interpretation

Follow [`EVALUATION.md`](EVALUATION.md). For the 0.144.4 Terra catalog, a success
uses `exec`, discovers the deferred nested MCP tool from `ALL_TOOLS`, and calls
it in the same or a later code cell. A top-level `tool_search` call is not
required for a `code_mode_only` model. The standalone skill task instead
requires the full skill-body marker in the isolated rollout.
