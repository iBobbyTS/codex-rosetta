# Codex Version Compatibility Audit Ledger

| Area | Status | Severity | Files | Notes |
| --- | --- | --- | --- | --- |
| Baseline and source provenance | Reviewed | No Action | `../openai-codex-src`, `src/codex_rosetta/__init__.py` | Source commit and installed CLI version recorded separately |
| Responses request and metadata contract | Reviewed | Should Plan | Codex `core/src/client.rs`, `core/src/responses_metadata.rs`; Rosetta `gateway/app.py`, `gateway/headers.py`, `gateway/proxy.py` | Canonical client metadata is raw-preserved on direct routes; bridge consumes only window header |
| Direct Responses passthrough | Reviewed | No Action | `gateway/proxy.py`, `test_responses_passthrough.py` | Unknown request/response fields and raw SSE are deliberately preserved |
| Responses-to-Chat conversion | Reviewed | Should Plan | `converters/openai_responses/**`, related tests | High-value fields covered; new Codex item/event shapes require explicit review |
| Tool localization and history mapping | Reviewed | Should Plan | `gateway/tool_adaptation.py`, persistence, tests | Strong Codex coupling with broad tests; schema/name drift is high risk |
| Deferred tool discovery | Reviewed | Should Plan | `gateway/proxy.py`, `test_tool_adaptation.py` | Window-scoped `namespace` and `tool_search` compatibility |
| Stream phase and event reconstruction | Reviewed | Should Plan | `gateway/stream_phase_buffer.py`, Responses converter, tests | Current phase logic is covered for function calls; native tool-search/web-search signal coverage needs follow-up |
| Hosted web search bridge | Reviewed | Should Plan | `gateway/web_search.py`, `test_web_search_bridge.py` | Reconstructs Codex-native web search activity over Chat upstreams |
| Reasoning and encrypted state | Reviewed | Should Plan | Responses/Chat content and stream converters, tests | Summary/content/encrypted state preservation is version-sensitive |
| Compaction and replay resilience | Reviewed | Should Plan | orphan-tool helpers/tests, history mapping | Codex compaction and replay assumptions need live upgrade tests |
| Model catalog surface | Reviewed | Track as Debt | `gateway/app.py::handle_list_models` | Gateway returns a minimal OpenAI list, not Codex `ModelInfo` metadata |
| Upgrade verification workflow | Reviewed | Should Plan | tests, `agentabi`, live Codex | Repeatable commands written; live gates remain unexecuted |

## Scope and assumptions

- This is a targeted full-repository audit of Codex-specific compatibility, not a general security or architecture audit.
- Current local Codex CLI: `codex-cli 0.142.5`.
- Current source checkout: `../openai-codex-src` at `cca16a10878202cb2f6e9666b6b4330329ea7e65` (`2026-07-06`, `feat(core): emit canonical command execution items (#31297)`).
- The source checkout has no release tag/version mapping in its manifests; do not claim that the commit is exactly the `0.142.5` release solely from local evidence.
- Existing user changes in `src/codex_rosetta/__init__.py` and `docs/*/version-compatibility.md` are outside this audit change and remain untouched.

## Evidence gathered

- CodeGraph was used before text search in both indexed repositories.
- Codex request construction: `codex-rs/core/src/client.rs::build_responses_request`.
- Codex canonical metadata and compatibility headers: `codex-rs/core/src/responses_metadata.rs::CodexResponsesMetadata`.
- Codex wire request structs/events: `codex-rs/codex-api/src/common.rs`, `codex-rs/codex-api/src/sse/responses.rs::process_responses_event`.
- Codex response items and phase: `codex-rs/protocol/src/models.rs::{ResponseInputItem, ResponseItem, MessagePhase}`.
- Codex model/tool controls: `codex-rs/protocol/src/openai_models.rs::ModelInfo`, `codex-rs/models-manager/models.json`.
- Rosetta gateway entry and session keying: `src/codex_rosetta/gateway/app.py::_proxy_handler`.
- Rosetta direct/bridge routing, deferred tools, conversion, and stream output: `src/codex_rosetta/gateway/proxy.py`.
- Rosetta phase behavior: `src/codex_rosetta/gateway/stream_phase_buffer.py::ResponsesPhaseBuffer`.
- Rosetta tool localization: `src/codex_rosetta/gateway/tool_adaptation.py`.

## Findings requiring follow-up detail

### Native tool-search/web-search phase signal coverage

- Status: Needs Follow-up
- Severity: Should Plan
- Evidence: `_TOOL_ITEM_TYPES` in `gateway/stream_phase_buffer.py` includes `function_call`, `custom_tool_call`, `mcp_call`, `shell_call`, and `computer_call`, but not `tool_search_call` or `web_search_call`. `tests/gateway/test_stream_phase_buffer.py` exercises function-call signals only.
- Trigger: A converted stream emits pre-tool assistant text followed by a native `tool_search_call` or `web_search_call` and relies on phase buffering to mark the text as commentary.
- Impact: The buffered text can be classified at completion as `final_answer` instead of `commentary`, depending on the reconstructed event sequence.
- Recommended priority: Add regression coverage and then decide whether both native call types belong in `_TOOL_ITEM_TYPES`.
- Scope boundary: Not fixed in this documentation task.

### Codex metadata transport drift

- Status: Needs Follow-up
- Severity: Should Plan
- Evidence: Current Codex source declares `client_metadata["x-codex-turn-metadata"]` canonical and direct headers compatibility projections. Rosetta consumes `x-codex-window-id` from the HTTP header and forwards only `x-request-id`, `User-Agent`, and `OpenResponses-Version`. Direct Responses routes preserve the request body; bridged routes do not use the canonical metadata object.
- Trigger: Codex stops emitting the compatibility `x-codex-window-id` header or changes the window key format/semantics.
- Impact: Window-scoped phase and deferred-tool stores fall back or stop activating.
- Recommended priority: On every Codex update, verify both header and `client_metadata` behavior with `responses_headers` source tests and a live request capture.

### Minimal gateway model list

- Status: Reviewed
- Severity: Track as Debt
- Evidence: `gateway/app.py::handle_list_models` returns id/display/capabilities fields only. Codex model behavior is controlled by `ModelInfo` fields such as `apply_patch_tool_type`, `supports_reasoning_summaries`, `supports_parallel_tool_calls`, and context-window settings.
- Trigger: Codex starts relying on the configured provider's `/v1/models` response for these fields instead of bundled/configured model metadata.
- Impact: Codex may expose a different tool surface or reasoning behavior than Rosetta expects.
- Recommended priority: Keep as a watched contract; add a Codex-facing catalog only when source/runtime evidence shows it is consumed.

### Unsupported or unverified Codex transports and modes

- Status: Needs Follow-up
- Severity: Should Plan
- Evidence: The gateway registers HTTP `/v1/responses` but no Responses WebSocket or `/responses/compact`; no Rosetta fixture was found for Responses Lite `AdditionalTools`, code-mode `exec/wait`, or incremental `previous_response_id` history.
- Trigger: A Codex model/provider begins enabling WebSocket, Responses Lite, remote compact, code mode, or incremental response state by default.
- Impact: Requests can fail at routing or reach the Chat bridge without enough tools/history.
- Recommended priority: Treat each feature as unsupported until a real request fixture and multi-turn acceptance test pass.

### New multi-agent namespace coverage

- Status: Needs Follow-up
- Severity: Should Plan
- Evidence: Rosetta's direct namespace whitelist names `codex_app` and `multi_agent_v1`; current Codex source contains `multi_agent_v2`/`collaboration` planning, while Rosetta has no dedicated end-to-end regression for it.
- Trigger: Codex emits the newer namespace/tool-search shapes.
- Impact: Generic deferral may work, but discovery, call, and output restoration are not proven.
- Recommended priority: Add a captured fixture and an end-to-end namespace search/call/output test before claiming support.

### Desktop/runtime-only tool contracts

- Status: Needs Follow-up
- Severity: Track as Debt
- Evidence: Rosetta adds model-facing guidance for `request_user_input`, `create_goal`, and `update_goal`; only part of this surface is visible in the adjacent open-source tree.
- Trigger: Desktop/runtime changes these schemas or availability rules without an equivalent open-source change.
- Impact: Chat models can emit invalid calls despite source review appearing clean.
- Recommended priority: Retain real session/tool fixtures in the upgrade gate.

## Verification

- `conda run -n llm-rosetta python -m pytest ...` targeted compatibility suite: `383 passed`.
- `conda run -n llm-rosetta make lint`: passed; ruff check and format check clean.
- First `conda run -n llm-rosetta make test`: `2287 passed, 4 skipped`, with one transient failure in `TestPipelineProfile::test_profile_populated_after_convert_request`.
- Isolated rerun of that profiling test: passed.
- Second full `conda run -n llm-rosetta make test`: `2288 passed, 4 skipped`.
- `git diff --check`: passed before final documentation refinements; rerun required in final verification.
- Agentabi, real upstream, WebSocket/Lite/remote compact, and live Codex UI acceptance were not run; these remain mandatory before a release-level compatibility claim.
