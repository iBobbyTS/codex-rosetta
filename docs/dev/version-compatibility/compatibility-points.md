# Codex-Specific Compatibility Points

## Judgment criteria

This document only includes behaviors that meet any of the following conditions:

- Rely on Codex-specific header, request item, tool schema, SSE event or model metadata;
- Exists to maintain Codex agent loop, history replay, tool execution or UI phase semantics;
- Behavior regression may occur after a Codex upgrade even if the OpenAI Responses API is still "well-formed".

Common provider conversion capabilities are not separately listed as Codex compatibility points.

## Daily maintenance requirements

This document is the only list of Codex-specific compatibility points. As long as a Codex-specific behavior is added, modified or discovered during daily development, it must be updated in the same task:

1. Current implementation, main code locations and upgrade risks;
2. **Can automatically complete** static, fixture, component or local integration checks;
3. Real Codex/API scenarios that **must be actually tested**.

Even if a certain automation has not yet been implemented, write out the necessary automated checks and mark the backlog. Even if a certain upgrade is judged to have no change with high confidence, its real test definition cannot be deleted; whether the real test is triggered in this upgrade is determined by the upgrade classification.

## Current compatibility overview

| Boundaries | Current Implementation | Primary Locations | Upgrade Risks |
| --- | --- | --- | --- |
| Agent-facing API | Expose `/v1/responses` to Codex; Chat/Anthropic/Google as upstream target format | `gateway/app.py`, `gateway/proxy.py` | Codex change endpoint, transport or request shape |
| Responses pass through as is | Responses→Responses retain unknown body fields, original response JSON and original SSE bytes | `gateway/proxy.py`, `test_responses_passthrough.py` | Low; only explicit tool adaptation will change the body |
| Request and window identity | Read `x-codex-window-id` as session key for tool mapping, deferred tools and phase behavior; do not transparently transmit to upstream | `gateway/app.py`, `gateway/headers.py` | Codex changes to only send canonical `client_metadata` or change window semantics |
| Responses→Chat bridge | Convert Codex Responses request to Chat via IR, and then rebuild Responses output | `converters/openai_responses/**`, `gateway/proxy.py` | High; new item/event/ fields will not be automatically transparently transmitted |
| Responses Lite / `additional_tools` | Responses→Responses can be transmitted transparently as is; Responses→Chat merges the top-level tools with `input[].type=additional_tools`, retains the developer instructions, and removes duplication according to the final Chat name | `converters/openai_responses/message_ops.py`, `converter.py`, `gateway/proxy.py` | High; 0.144.0 model catalog Responses Lite has been enabled for some models, the location of tools and developer instructions will change |
| custom/freeform tool | Identify `apply_patch` and Code Mode `exec` of Responses `type: custom`, convert into Chat callable form, and restore Codex-native tool type, call/output in response return | `openai_responses/converter.py`, `openai_responses/tool_ops.py`, `gateway/tool_adaptation.py` | Codex change custom grammar, call/output/delta event, or third-party models misinterpret freeform `exec` as JSON shell function |
| Code tool localization | Replace `apply_patch`/`exec_command`/`write_stdin` with the familiar `Read`/`Edit`/`Write`/`Glob`/`Grep`/`Bash`, and the response is translated back to Codex-native call | `gateway/tool_adaptation.py`, `test_tool_adaptation.py` | Tool name, parameter schema, call id or execution result format change |
| Tool history consistency | Memorize native/localized mapping by call id, rewrite subsequent history, and enable persistence and TTL cleanup | `gateway/proxy.py`, persistence/observability modules | Codex history replay, compact or output shape changes |
| Deferred tool discovery | Temporary `namespace` tools by Codex window, inject/process `tool_search`, restore `tool_search_call/output` to native Responses items | `gateway/proxy.py::WindowToolSearchStore`, Responses converter | namespace/tool_search schema, execution or compact behavior changes |
| Codex tool usage tips | Supplement the Chat model with `request_user_input`, `create_goal`, `update_goal` and other Codex tool calling constraints | `converters/openai_chat/tool_ops.py`, related pipeline tests | schema, mode availability or Desktop/runtime tool contract changes |
| Web search bridge | Codex `web_search` can be exposed to the Chat model, and the `web_search_call` event can be reconstructed and continued after Tavily execution | `gateway/web_search.py`, `test_web_search_bridge.py` | native web-search item/event or tool configuration changes |
| Stream lifecycle | Rebuild `response.created`, item added/delta/done, `response.completed`, etc. from Chat chunks Responses SSE | `openai_responses/converter.py`, `gateway/proxy.py` | Codex parser adds required events, sequences or termination conditions |
| Message phase | Use tool calls and terminal events to infer `commentary`/`final_answer`, write phase back to message item; override native tool/web search signal | `gateway/stream_phase_buffer.py`, `test_stream_phase_buffer.py` | phase enumeration or Codex mailbox/final-answer semantic changes |
| Reasoning | Convert reasoning effort/summary, retain reasoning summary/content, `reasoning_content` and `encrypted_content` | Responses/Chat content, config, stream converters | New effort, summary delivery, reasoning event or encryption status change |
| Context compaction resilience | Remove orphan `tool_choice/tool_config` that has no tools but remains after compact; keep tool history replayable | `converters/base/helpers/tool_orphan_fix.py`, `test_strip_orphaned_tool_config.py` | Codex compact output, window generation or historical clipping changes |
| Model-level switches | Configure code tool localization, `apply_patch` fallback, remove `image_generation`, tool description optimization and phase detection | `gateway/config.py`, admin config/UI | Codex model catalog control field or default value changes |
| Static tool catalog | Package a read-only catalog of fixed built-in and bundled tools, bound to Codex CLI `0.144.0` and source commit `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`; exclude `tool_search` and runtime-dynamic MCP/plugin/app/connector tools | `src/codex_rosetta/gateway/admin/tool_catalog.json` | Fixed tool sets, namespace members, wire types, aliases, or model-controlled availability change |

## Compatibility point test matrix

| Compatibility points | Can be automated | Must be actually tested |
| --- | --- | --- |
| Agent-facing API | Routing, method, content type, SSE terminal/error fixture; fake upstream single-round and multi-round playback | Real Codex completes single/multi-round via gateway, the session ends normally and errors are visible |
| Responses are transparently transmitted as is | Unknown request fields, original JSON, original SSE bytes and terminal events are not rewritten | True same-format Responses routing retains the actual Codex request/response fields and can be continued |
| Request and window identity | header/body metadata extraction, fallback, concurrent window isolation and cache key testing | Capture header/body/window changes of real turn, compact, resume, fork, subagent |
| Responses→Chat bridge | request/response/stream/history four-way fixture; fake Chat upstream multi-round tool playback | Use `deepseek-v4-flash` to complete text, multi-round tools, error recovery and final answer |
| Responses Lite / `additional_tools` | Accurate replay of Lite requests; extract embedded tools and developer instructions; override top/embedded tool mixing, deduplication, `reasoning.context=all_turns`, `parallel_tool_calls=false` and embedded image-generation removal | Enable Lite for `deepseek-v4-flash` using controlled catalog override, complete real multiple rounds of tool calls and confirm that the second round can consume the results |
| custom/freeform tool | `apply_patch` schema/grammar/delta/call-output round-trip; Code Mode `exec` in Responses→Chat→Responses, non-streaming, added/delta/done/completed return trips are restored to `custom_tool_call`; non-compliant third-party parameters are retained, and no guessing is rewritten to JavaScript | Real Codex execution success patch, failed patch Post-fix correction; execute `exec/wait` and nested tool call for catalog with code mode enabled, confirm that tool failure is visible and fatal incompatible-payload will not appear |
| Code tool localization | native/localized schema mapping, parameter conversion, call id, result recovery and history replay | Really execute read/edit/write/search/shell, and the tool history can still be correctly consumed in the next round |
| Tool history consistency | TTL, persistence, failure results, post-compact history, concurrent session isolation | compact/resume/restart after multiple rounds of tools, confirm that there are no repeated calls or orphaned output |
| Deferred tool discovery | namespace defer, search matching, multiple searches, call/output and two-way window isolation | Real plugin/MCP namespace search, call, consume results, and verify that the two sessions do not cross talk |
| Codex tool usage tips | tool description/schema injection and mode availability fixture | Real calls to `request_user_input`, Goal/Plan and available Desktop runtime tools |
| Web search bridge | Configure, disabled/missing keys, search results, event reconstruction and continuation fixtures | Real search, read results and continue to generate final answers; verify that error paths are recoverable |
| Stream lifecycle | created, item/delta/done, completed/failed/incomplete sequence and exception EOF | Real streaming turn without duplication/truncation/stuck, terminal and errors are presented correctly |
| Message phase | All tool signals, completed-only, added/done/completed phase consistency | Commentary/final in Codex UI is displayed correctly, mailbox/steering can work |
| Reasoning | effort/summary/content/encrypted state Cross-format round-trip and tool continuation round fixture | `deepseek-v4-flash` reasoning can be continued before, after, and in the next round of the tool without repeated thinking |
| Context compaction resilience | orphan tool config, history trimming, compact fixture and window generation | Continue tool tasks after long session triggers compact and verify resume/restart |
| Model-level switches | Configure defaults, save/load, runtime validation, and ModelInfo contract fixtures | Verify tool mode, apply_patch/search/reasoning/multi-agent switch behavior with target model |
| Static tool catalog | Validate unique IDs, references, policy defaults, excluded dynamic tools, and exact CLI/source binding | Compare the catalog against tool definitions exposed by a real Codex session for the target version; record conditionally available tools separately |

## 1. Request, header and session identity

The current Codex source code is clarified in `codex-rs/core/src/responses_metadata.rs`: the canonical carrier of the complete turn metadata is the `client_metadata["x-codex-turn-metadata"]` of the request body, and the HTTP `x-codex-*` headers are compatible projections.

Rosetta's current behavior:

- `gateway/app.py::_proxy_handler` reads `x-codex-window-id` from HTTP header;
- window id serves as the key for both tool history mapping and window-scoped `tool_search`/phase status;
- `gateway/headers.py` only forwards `x-request-id`, `User-Agent` and `OpenResponses-Version` upstream;
- Responses→Responses direct path leaves body intact, so canonical `client_metadata` will not be lost by IR;
- Responses→Chat path does not send Codex metadata to Chat upstream, local status still relies on HTTP `x-codex-window-id`.

The upgrade review must capture and compare both:

```text
HTTP x-codex-window-id
HTTP x-codex-turn-metadata
client_metadata["x-codex-window-id"]
client_metadata["x-codex-turn-metadata"]
session-id / thread-id / turn-id / parent-thread-id / subagent metadata
```

The window id in the current source code is in the form of `{thread_id}:{auto_compact_window_number}`. compact, resume, fork and subagent will affect its life cycle; it cannot be treated as a thread UUID that never changes.

## 2. Responses request and direct transparent transmission

The current Codex `ResponsesApiRequest` contains `instructions`, `input`, `tools`, `tool_choice`, `parallel_tool_calls`, `reasoning`, `store`, `stream`, `stream_options`, `include`, `service_tier`, `prompt_cache_key`, `text` and `client_metadata`.

Using direct passthrough for same-format routing is an important forward compatibility strategy: unknown fields will not be compressed into the IR first, and the response will not be reserialized. This boundary must be preserved when upgrading to avoid changing the direct path to decode/re-encode in order to reuse the converter.

Responses→Chat is an explicit compatibility layer. After adding request item, tool type, reasoning field or SSE event to Codex, you must confirm that the converter has a clear downgrade/recovery strategy, and "request successful" cannot be regarded as agent loop compatibility.

### Responses Lite and `additional_tools`

The bundled model catalog of Codex 0.144.0 has `use_responses_lite=true` enabled for some models. In this mode, Codex no longer puts tools at the top level `tools`: it inserts a `type: "additional_tools"` item at the beginning of `input` and uses a developer message to carry the original instructions; reasoning may also use `context: "all_turns"`.

Responses→Responses direct path can naturally retain this body. Responses→Chat currently ignores `additional_tools` items that are unknown and do not have an extended namespace, and the top-level `tools` is empty. The result is that the Chat upstream does not receive any tool definitions. `remove_image_generation` currently only checks the top-level tools and cannot handle the `image_gen` namespace/function in Lite item. This is a confirmed compatibility gap for the 0.144.0 upgrade, and support for the Responses Lite-enabled model catalog cannot be declared until fixes and multiple rounds of real tool testing are completed.

## 3. Codex-native tools and history replay

The current Codex source code exposes `apply_patch` as a freeform grammar tool with Responses `type: "custom"`; the call uses `custom_tool_call`, the parameter is a string, and the result uses `custom_tool_call_output`. Catalogs with code mode enabled also expose `exec` on the same wire type, whose `input` must be a raw JavaScript source, not a shell parameter object. Rosetta maintains two layers simultaneously and is compatible with:

1. The Responses converter safely downgrades a native custom tool into an IR/Chat representation, then restores the native Responses item from preserved metadata;
2. Optional tool localization replaces Codex editing tools with tools more familiar to Chat models, then translates model calls back to `apply_patch`, `exec_command`, or a controlled fallback.

When Chat upstream downgrades the custom/freeform tool to a normal function call, the Responses return must restore `custom_tool_call` according to the `metadata.provider_type="custom"` recorded during the request period; this applies to both non-streaming responses and streaming added/delta/done/completed. The `{"cmd": "..."}` returned by a third-party model cannot be synthesized into JavaScript without authorization: it is evidence that the model does not adhere to freeform semantics, and should be handled by Codex as a visible tool error and let the model retry, rather than letting Rosetta guess the execution intention.

Because Codex will resend history on subsequent requests, this project saves the native/localized mapping by `call_id` and restores the tool call originally seen by the model before sending it upstream. This is a critical path for prompt cache consistency with multi-round tools and must be tested with compact, resume, failed tool results, and TTL/persistence.

`namespace` and `tool_search` are another Codex-specific path. Rosetta will hide namespaces that are not suitable for one-time expansion to Chat, save them by window, inject the synthesized `tool_search`, and restore the matching tool with a subsequent `tool_search_output`.

Currently the direct namespace whitelist only contains `codex_app` and `multi_agent_v1`. Codex source code already has tool planning in the direction of `multi_agent_v2`/`collaboration`; although the general defer path may take over the new namespace, there is currently no dedicated end-to-end regression, and compatibility cannot be declared based on this.

The OpenAI Chat tool converter also adds model-visible usage hints for `request_user_input`, `create_goal`, and `update_goal`. `request_user_input` can be checked against the adjacent source checkout; some Goal tools come from real Desktop/runtime payloads and do not have matching definitions there. Retain real session/tool fixtures during upgrades instead of relying only on source searches.

### Static tool catalog version binding

`src/codex_rosetta/gateway/admin/tool_catalog.json` is a read-only conceptual snapshot of fixed Codex tools. Its metadata is bound to Codex CLI `0.144.0` and source commit `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`. It intentionally excludes `tool_search` and runtime-dynamic MCP, plugin, app, and connector tools, and it does not describe the exact tools available to any individual request.

Every Codex upgrade must review the built-in tool specifications and bundled extension registrations, refresh the catalog contents and version metadata when needed, and run the catalog contract tests. Even when the tool set is unchanged, the source binding may be advanced only after that review is recorded in the upgrade report.

## 4. SSE, phase and termination semantics

Codex first registers an item through `response.output_item.added`, then consumes text/tool deltas, and finally processes item-done and `response.completed`. Rosetta's rebuilt stream must preserve at least this order:

```text
response.created
response.output_item.added
response.output_text.delta / tool input delta
response.output_item.done
response.completed
```

`phase` is inside the message item, not a separate event. `commentary` is not just a UI label: the current Codex checks the mailbox after the commentary item is completed, and may change subsequent sampling behavior. Therefore the phase in added, done and completed output must be consistent.

Currently `ResponsesPhaseBuffer` treats function/custom/MCP/shell/computer/tool_search/ web_search calls as tool signals. Automated regression covers "text followed by native search tool" and the scenario where there is only native search call in `response.completed.output`, ensuring that the previous text is marked as `commentary` instead of erroneously marked as `final_answer`. When adding a new Codex output item type, you still need to clearly determine whether it will continue the agent loop, and expand this set and the tests of the two event paths accordingly.

## 5. Reasoning state

Codex will request `reasoning.encrypted_content` when reasoning is turned on, and consume summary part, summary text delta/done and raw reasoning delta. Rosetta currently retains Responses summary/content/encrypted state through IR metadata, and uses provider extension fields such as `reasoning_content` in Chat upstream to maintain tool continuation.

Must check when upgrading:

- New value and degradation rules for reasoning effort;
- summary `auto/concise/detailed/none` and delivery order;
- `include: ["reasoning.encrypted_content"]`;
- Empty string `reasoning_content` coexists with tool calls;
- Renewability of reasoning items after history replay, compaction and cross-format conversion.

## 6. Current clear limitations and observations

### Canonical metadata is only naturally retained in the direct path

Bridge's window-scoped logic still relies on the compatibility header. If Codex stops sending the `x-codex-window-id` header in the future and only retains the body `client_metadata`, the phase and deferred tool status will no longer be windowed correctly. Every upgrade must be confirmed with real request capture.

When the header is missing, the tool mapping cache will degenerate to `model:{model}`. This will cause multiple Codex sessions of the same model to share a mapping domain, so it can only be used as a compatible fallback and cannot be regarded as equivalent session isolation.

### Gateway `/v1/models` is not a Codex dynamic catalog

`gateway/app.py::handle_list_models` returns the OpenAI SDK style `{"object":"list","data":[...]}`. The current dynamic catalog request of Codex source code is `GET models?client_version=...`, and the response is `{"models":[ModelInfo...]}`, among which `apply_patch_tool_type`, reasoning, parallel tools, context window, Responses Lite, tool mode and multi-agent version will change the requests and tools issued by Codex.

Therefore currently `/v1/models` cannot be considered a Codex catalog implementation. Only after it is confirmed that Codex will use the endpoint from the custom provider, it should be implemented and tested separately according to the Codex `ModelInfo` contract, and the two response formats cannot be mixed into one ambiguous endpoint.

### Responses WebSocket and `/responses/compact` are not implemented yet

The current gateway's Codex surface is HTTP `/v1/responses` + SSE. Responses WebSocket `response.create`, increment `previous_response_id` and remote `/responses/compact` in the source code are not verified capabilities. The current status of Responses Lite is documented separately above: direct path can be retained naturally, but bridge has a confirmed compatibility gap.

Codex model/provider configurations must not declare these capabilities without testing; each upgrade must confirm that Codex still uses HTTP/SSE for custom providers, or has reliable fallback.

Currently Responses→Chat also relies on Codex to resend the complete input/history. Even if `additional_tools` is added, if Codex starts to use WebSocket/HTTP incremental requests and `previous_response_id` by default, Rosetta still does not have a corresponding server-side Responses session storage, and the bridge will lack history. This item must be determined through real request capture, and it cannot be inferred that it is enabled just from the presence of `previous_response_id` in the request type.

### Code mode and new version of multi-agent tools lack special verification

Generic custom-tool converter is not compatible with code-mode `exec/wait`. There is currently no Rosetta fixture covering JavaScript/code-mode payloads, nested tool call or wait continuation rounds; `multi_agent_v2`/`collaboration` also lacks the full namespace discovery + call + output regression.

When these capabilities appear in the Codex model catalog or real requests, fixtures and end-to-end tests must be added first, and then the support statement must be updated.

### Phase's native search signal has been incorporated into automated regression

`tool_search_call`/`web_search_call` has been incorporated into the phase tool signal collection and overrides the streaming item event and completed-only fallback. This fix only changes the phase classification, not the search bridge or tool execution; the real Codex UI/mailbox behavior is still a gatekeeper that must be actually tested.

### Existing real integration baselines are insufficient to prove tool compatibility

The existing agentabi coverage in the warehouse mainly focuses on single-round arithmetic, and the startup script is only responsible for opening the Codex. They do not validate `apply_patch`, Goal/Plan, request_user_input, plugin/tool_search, web search, phase, compact/resume or subagent. Upgrading access control must run the multi-wheel tool matrix in the upgrade checklist.
