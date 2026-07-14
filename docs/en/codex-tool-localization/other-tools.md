# Other Codex Tools

Codex has several agent/runtime tools whose behavior depends on more than a simple function call schema. Codex-Rosetta keeps those tools usable for Chat-only upstream models by preserving Responses-specific structure where needed. Targeted model guidance is a Profile-owned Function field rather than a hard-coded converter rule.

## Plan Mode

Plan mode uses `request_user_input` when the model needs a real user decision before producing or revising a plan. Chat models can confuse that with the final approval step and ask the user whether to proceed after they already emitted a proposed plan.

The bundled **Chat Default** Profile marks `request_user_input` as Modified and supplies this editable Tool Guidance field:

- Use it only for preferences or decisions that materially change the plan.
- Do not use it to ask whether to approve, proceed with, or implement a proposed plan.
- After the final `<proposed_plan>` block, let the Codex UI handle approval and implementation.
- Keep option labels short and natural, without `A:`, `B:`, or `C:` prefixes.

This is a prompt-level/tool-description adaptation. It does not change the tool schema.

## TODO / update_plan

When Codex exposes `update_plan` only as a nested Code Mode tool, the bundled **Chat Default** Profile projects it into an ordinary Chat function. Rosetta derives the current parameter schema and description from Codex's `exec` declaration instead of maintaining a duplicate schema. A model call is rebuilt as a deterministic custom `exec` script for Codex. If Codex already exposes a direct `update_plan` Function, that direct definition is preserved.

## Goal Tools

Goal state is managed through `get_goal`, `create_goal`, and `update_goal`. Chat models may not infer the right sequence from the terse native tool descriptions.

The bundled **Chat Default** Profile marks these Functions as Modified and supplies editable Tool Guidance fields for:

- `create_goal`: call it when the user explicitly asks to mark a goal complete or blocked but no active goal exists, or when `update_goal` reports that the thread has no goal. Do not set `token_budget` unless the user explicitly provided a numeric token budget.
- `update_goal`: when goal state is uncertain, call `get_goal` first. If there is no active goal, call `create_goal` with a concise objective and no token budget unless explicitly requested, then retry `update_goal`.

All three Goal tools are marked Modified so they can be projected from Code Mode `exec`. `get_goal` has no additional guidance text; `create_goal` and `update_goal` retain the Profile-owned guidance above.

## Code Mode Nested Tools

Recent Codex Code Mode surfaces keep several runtime tools inside the custom `exec` description instead of exposing every tool as a top-level Function. For Responses-to-Chat routes, **Chat Default** projects the following nested declarations into ordinary Chat functions when those declarations are present:

- `exec_command`, `write_stdin`, `update_plan`, `apply_patch`, and `view_image`
- `web.run`, exposed to Chat as `web-run`
- `get_goal`, `create_goal`, and `update_goal`
- `clock.curr_time` and `clock.sleep`, exposed as `clock-curr_time` and `clock-sleep`

Rosetta reads each schema and description from the actual Codex `exec` declaration. Its reverse parser covers the TypeScript grammar emitted by Codex, including literals, unions, intersections, arrays, tuples, and object index signatures. Constraints that Codex itself omits while rendering JSON Schema to TypeScript cannot be reconstructed. Rosetta does not invent a Function when a declaration cannot be parsed. A same-named direct Function wins, and projection fails closed for that name.

Calls to projected Functions are rebuilt as deterministic JavaScript calls on the nested `tools` object and returned to Codex as `custom_tool_call` calls to `exec`. The exact Chat-to-Codex call mapping is stored in the existing encrypted tool-history cache, so a subsequent request within its 24-hour TTL restores the original Chat Function and arguments before it is sent upstream. `view_image` forwards its result through the `image(...)` exec helper; the other projected tools use `text(...)`.

The top-level `wait` and `request_user_input` Functions are not projected through `exec`. They remain direct Functions in both directions.

## Subagents And Namespace Tools

Codex exposes subagent capabilities through Responses namespace tools such as `collaboration` and legacy `multi_agent_v1`. Chat Completions does not have the same nested namespace tool shape.

For Responses-to-Chat routes, Rosetta flattens namespace child tools into ordinary Chat function tools. For example:

```text
multi_agent_v1-spawn_agent
```

During request conversion, Rosetta records the mapping from the flattened tool name to its Responses namespace. The hyphenated `multi_agent_v1-spawn_agent` form is canonical and valid on Chat APIs that restrict Function names to letters, digits, underscores, and hyphens. On return Rosetta also accepts `multi_agent_v1_spawn_agent`, `multi_agent_v1.spawn_agent`, and a bare `spawn_agent` when the selected name belongs to exactly one namespace and does not collide with an ordinary Function. Ambiguous names fail closed. Rosetta then restores the Responses namespace metadata before returning the event to Codex:

```json
{
  "type": "function_call",
  "name": "spawn_agent",
  "namespace": "multi_agent_v1"
}
```

For Responses-to-Responses routes, namespace tools stay in their native Responses shape.

## Plugin And Deferred Tools

Plugin and deferred tool discovery use the same general tool conversion path. Rosetta does not currently add a dedicated localization rule for every plugin tool.

The important behavior is that tool calls must survive the round trip:

- Tool definitions are converted into a Chat-compatible function shape when sent to Chat providers.
- Tool calls are converted back into Responses events for Codex.
- Namespace metadata is restored when the tool came from a Responses namespace.
- Message `phase` metadata is preserved so work-process output remains foldable in Codex.

## Tool Profile Scope

**OpenAI Responses (Tool Mapping only)** supports Tool Profiles while keeping the rest of the Responses request and response on the direct path. The bundled **Responses pass through** Profile preserves incoming tools; **Responses web.run mapping** changes only `web.run` so `/v1/alpha/search` uses Rosetta's local mapping. Responses Rosetta, Chat, Anthropic, and Google model groups continue to support Profile selection and processing.

The bundled Profiles manage current Codex image generation through `image_gen.imagegen`. They do not contain the obsolete hosted `image_generation` tool.

### Function Card Inputs

A Function, Hosted, or Namespace catalog item may declare multiple `profile_inputs`. Each entry has a stable ID, a localized subtitle, a default value, and a `text`, `password`, or `select` input type. A select declares ordered `{value, label}` options: the Tools page displays each label and persists its value. The Tools page renders the entries in catalog order beneath the tool status selector. The `web_search` and `web.run` cards each own their search Provider and Token; Tavily is currently the only provider. The former standalone Web Search settings tab has been removed.

An input may declare `visible_when` with a list of tool states, for example `["modified"]`. Hidden inputs retain their saved Profile values. Card descriptions appear in every supported state by default; an item may restrict them with `description_visible_when` using the same state-list format. A catalog item may also declare `profile_mutations`: generic Profile processing applies their configured description or parameter-description append operations only in the Modified state. The Chat Default Tool Guidance fields for `request_user_input`, the Goal tools, selected `collaboration` Functions, and the GitHub MCP Namespace use this mechanism; the converter contains no Function-name-specific guidance. Hosted `web_search` remains protocol-converted in either state, but only Modified can append its Profile guidance.

All Namespace rows start expanded on the Tools page. This display default is independent of each Namespace Profile state, and users can still collapse rows locally.

The bundled **Chat Default** Profile disables the legacy `multi_agent_v1` Namespace while leaving `collaboration` enabled. Collaboration children are flattened for Chat and restored to native Responses namespace calls; they are not translated through Code Mode `exec`. Whenever any Namespace is Disabled, every child Function is forced to Disabled and its state selector is locked until the Namespace is enabled again.

User-entered values are saved with a user Profile under `inputs.<function-item-id>.<input-id>`. Creating a Profile copy carries the current values into the new Profile; switching or resetting a Profile restores its saved values. Every bundled Profile also allows these fields to be edited and explicitly saved; those values are stored in `tool_profile_input_overrides.<profile-id>` without changing the bundled JSON. A bundled Profile's tool delivery states remain read-only. Inputs have no effect unless their runtime feature consumes them; currently Modified Functions consume `guidance`, and `image_gen.imagegen` consumes its Base URL and Token.
