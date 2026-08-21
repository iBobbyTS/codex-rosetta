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

### Stable compatibility point registry

The following registry is the canonical point list. Point IDs are stable and
must be used in upgrade reports; names are descriptive and may be clarified
without changing the ID. Never reuse a retired ID. The compatibility overview
and test matrix below must each contain every registered name exactly once.

| ID | Compatibility point |
| --- | --- |
| `CP-01` | Agent-facing API |
| `CP-02` | Responses transparent handling |
| `CP-03` | Codex Search and Images endpoints |
| `CP-04` | Request and window identity |
| `CP-05` | Responses→Chat bridge |
| `CP-06` | Responses Lite / `additional_tools` |
| `CP-07` | Codex model catalog |
| `CP-08` | custom/freeform tool |
| `CP-09` | Code tool localization |
| `CP-10` | Tool history consistency |
| `CP-11` | Deferred tool discovery |
| `CP-12` | Codex tool usage tips |
| `CP-13` | Skill delivery surfaces |
| `CP-14` | Live-agent runtime authentication |
| `CP-15` | Web search bridge |
| `CP-16` | Self-hosted Bing search |
| `CP-17` | Stream lifecycle |
| `CP-18` | Message phase |
| `CP-19` | Reasoning |
| `CP-20` | Context compaction resilience |
| `CP-21` | GPT relay provider identity |
| `CP-22` | Model-group tool profiles |
| `CP-23` | Static tool catalog |
| `CP-24` | Late instruction message cache compatibility |
| `CP-25` | Window-scoped Chat tool surface stability |
| `CP-26` | Collaboration argument confidentiality and delivery mode |

## Current upgrade status

Codex `0.147.0` is under a full-inventory, source-first adaptation against
peeled commit `be6e8eac029b183056b7e4402879f15d2c85f61b`. The reviewed source
snapshot is bound to that commit so subsequent drift is detectable, but this
is not release approval: model/tool assets, Provider behavior, deterministic
integration gates, and the complete live-agent inventory remain later section
work, and the package version remains `0.144.0.r0`.

The 0.147 source introduces `encrypted_function_args` on Responses function
calls. Direct Responses preserves it as opaque wire data. Every converted Chat
route deliberately discards missing, null, empty, and non-empty forms before
the Chat request and tool-history canonical identity exist; all four forms must
therefore produce identical upstream request bytes and cache templates.
Converted output never synthesizes the marker, so Multi-Agent V2 uses the
pre-0.147 encrypted inter-agent delivery path on Chat routes.

The code-derived ledger has been rechecked against Codex `0.142.0`,
`0.144.6`, `0.145.0-alpha.23`, and the exact `0.145.0` source. The formal
adaptation, packaged model/tool assets, and deterministic tests have been
updated or run. The post-migration CLI and agentabi matrices now cover the
primary tool paths, while Images routing, sidecar search, exact-version GUI,
compaction switch/summary, orchestrator, and live audio/profile gates remain
blocked or unrun. Runtime compatibility remains **not approved** and the
package version therefore remains `0.144.0.r0`. See
[`reports/upgrade-review.md`](reports/upgrade-review.md) for
the exact pass/failure matrix and adoption decision, and see
[`reports/range-coverage-review.md`](reports/range-coverage-review.md) for
the historical range review for 0.142.0–0.144.6.

## Formal 0.145.0 source-first corrections

The overview table below contains historical implementation detail that remains
useful for the 0.144.x boundary. For the current formal 0.145.0 inspection, these
source facts supersede older wording:

- Codex ModelInfo uses `supports_reasoning_summary_parameter` with a serde
  default of true. The formal bundled JSON also carries the legacy
  `supports_reasoning_summaries: true` key, which is ignored because it is not a
  `ModelInfo` field. Rosetta local-mode catalogs continue to emit that alias for
  installed 0.144.x clients, deriving it from the current summary capability.
- Codex 0.145.0 adds `ContentItem::InputAudio`, `InputModality::Audio`, and
  Code Mode/MCP audio forwarding. Responses and Chat converters now preserve
  data-URL and provider-native audio forms through the IR; malformed or
  unsupported audio remains fail-open passthrough.
- ModelMessages now has optional permissions (danger_full_access,
  workspace_write, read_only), and AutoReviewMessages has policy_template.
- Response item IDs are typed ResponseItemId values with prefix validation; the
  client clears unprefixed IDs before sending request history.
- SearchResponse has optional opaque structured results. Rosetta's local
  /v1/alpha/search bridge now emits structured text results for real searches,
  preserves an explicit empty array, and omits the field for non-search calls;
  direct passthrough remains a separate boundary.
- Alpha.23 adds cache_write_tokens to completed usage and changes remote
  compaction fallback/response-id handling. Rosetta maps cache writes to the
  existing IR cache_creation_tokens owner on cross-provider paths.
- Code Mode deferred-only MCP type rendering, audio forwarding,
  apply_patch/exec descriptions,
  Realtime routing, host-skill world state, and platform-specific shell
  descriptions are changed source contracts and must not be classified as
  high-confidence unchanged.
- App-server protocol additions such as RawResponseCompleted, turn start/error
  metadata, environment connection events, Realtime V3/frameless Bidi, Sleep
  extension items, spend-control state, permission serialization, and subagent
  rollout ordinals have no Rosetta wire-converter owner. They remain explicit
  client-owned/live-gate obligations under the relevant CP rows, not evidence
  that the Responses bridge is unchanged.

The detailed CP-07 and CP-23 overview rows retain alpha.23 implementation
history. Their current formal binding is the packaged `0.145.0` catalog and
tool catalog metadata at source commit `25af12f7e61572b0bc18ddb1008be543b91519b0`.
The formal source adds audio to the client input/Code Mode surface; the current
owner is the Responses/Chat audio bridge and `code_mode_projection.py`, not a
new source-tool item. Catalog schema v7 contains 57 concrete items, 62 exact
source registrations, and five runtime-dynamic families. Rosetta-owned
injections remain explicitly separate from Codex source registrations.

## Current compatibility overview

The `Primary Locations` column names the shortest useful entry points. The
exhaustive code-derived owner and deterministic-test map is maintained in
[`rosetta-source-map.md`](rosetta-source-map.md); it takes precedence when this
summary omits a transitive owner.

| Boundaries | Current Implementation | Primary Locations | Upgrade Risks |
| --- | --- | --- | --- |
| Agent-facing API | Expose `/v1/responses` to Codex; Chat/Anthropic/Google as upstream target formats; accept full-history image sessions under the configured inbound-body limit. Codex 0.145.0 authentication is owned only by the HTTP `Authorization` request header. Direct Responses removes that inbound header case-insensitively, retains other unknown end-to-end headers subject to hop-by-hop/framing/network-origin filtering, and overlays Provider auth last. Every Responses Provider explicitly selects `request_encoding`: `passthrough` preserves eligible unchanged attested raw wire, `identity` rebuilds plain JSON, and `zstd` rebuilds Zstd JSON. Rebuilt JSON removes `Content-Encoding` and `x-oai-attestation`; unchanged raw wire preserves them. Responses→Chat/Anthropic/Google retain the explicit minimal header set. Every `/v1` error-message leaf uses exactly one origin label: `Codex Rosetta: `, `Codex Rosetta blocked: `, or `Upstream: `; Provider envelopes, statuses, codes, and non-message fields remain owned by their source. Every Codex version review must diff source plus a real capture for any new authentication location or error/status mapping | `gateway/app.py`, `gateway/downstream_errors.py`, `gateway/headers.py`, `gateway/inbound_content_encoding.py`, `gateway/config.py`, Admin config/UI, `gateway/proxy.py` | Codex changes endpoint, authentication location, transport, request shape, request compression, attestation headers, end-to-end capability headers, error/status mapping, or retained image/history size |
| Responses transparent handling | Admin exposes one `responses` wire protocol. Every Responses→Responses route is direct regardless of Provider: the gateway applies the selected Tool Profile, retains other request fields, and returns successful model response JSON/SSE bytes unchanged subject only to transport size and framing limits. Error responses preserve the upstream envelope/code but prefix only documented message leaves; raw SSE preserves ordinary events byte-for-byte while `response.failed` is labeled and `response.incomplete` becomes a labeled `response.failed`. The direct header set is computed once from original ingress; only inbound `Authorization`, hop-by-hop/framing fields, `Connection`-declared fields, and network-origin identity are removed. Provider auth is applied last. Current OpenAI Responses, OpenAI Chat, Anthropic Messages, and Google GenAI response schemas declare no API-authentication body fields, and upstream HTTP response headers are not forwarded. Model output is therefore never searched for configured credential strings. The protocol path inventory is explicitly empty and must be updated only when a future protocol declares an exact response authentication field. Model-response logs, traces, and dumps redact explicit authentication/token fields only. Requests and credential-bearing auxiliary clients retain exact configured-token protection; their internal streaming guard uses bounded rolling windows for ordinary fields and full buffers only for unfinished embedded JSON, with no total fragment-count limit. Model-switch compaction and raw-wire attestation behavior remain unchanged. The response transport enforces 1 MiB per line and 8 MiB per event with no total successful-stream cap | `gateway/config.py`, `gateway/downstream_errors.py`, `gateway/headers.py`, `gateway/model_protocol_credentials.py`, `gateway/proxy.py`, `gateway/stream_trace.py`, `gateway/transport/http/transport.py`, `gateway/transport/credential_redaction.py`, `gateway/transport/credential_semantics.py`, `observability/redaction.py`, `observability/error_dump.py`, `test_downstream_errors.py`, `test_responses_passthrough.py`, `test_provider_return_redaction.py`, `test_stream_trace.py`, `test_transport_credential_redaction.py`, `test_http_transport_limits.py` | Codex changes its authentication location, HTTP error extraction, `response.failed`/`response.incomplete` parsing, or EOF retry behavior; an upstream protocol adds a response authentication field; a model route regains generic credential scanning; auxiliary protection is bypassed; attestation or stream framing changes |
| Codex Search and Images endpoints | Expose JSON `POST /v1/alpha/search`, `/v1/images/generations`, and `/v1/images/edits`. `image_gen.imagegen` Passthrough retains direct Tool Mapping only routing; Modified resolves its Profile Base URL/Token and forwards unchanged OpenAI Images generation/edit JSON with the configured model alias on Chat, Responses, Anthropic, and Google Profile protocols, while Disabled rejects the endpoint. Codex extension requests use the fixed `gpt-image-2` model without identifying the parent LLM route; when that model is not in the LLM catalog, Rosetta may use Profile routing only if every enabled Modified image mapping resolves to the same endpoint, credential set, and proxy, preserving `gpt-image-2` on the Images wire. Distinct mappings fail closed instead of depending on configuration order. Provider and authenticated `web-run` sidecar credentials are removed from successful payloads, HTTP errors, and transport exceptions before model, client, trace, metric, or persistence use; sensitive exception causes are not retained. No vendor-private image API translation is attempted. Codex separately gates model-facing image generation on image modality, the feature toggle, provider capability, and either OpenAI actor authorization or real Codex-backend auth. Rosetta projects only a live Codex declaration and deliberately does not invent a missing `image_gen.imagegen`. Web Search Provider code owns its sub-capabilities, command fields, validation, invocation, and projection policy; the Tool Catalog only identifies and binds the ordinary tool. All-GPT preserves the complete live alpha/search surface, while local/mixed chains expose only code-owned executable branches and mixed is single-query until a per-query GPT adapter exists. Search references are allocated atomically and cached for retry stability in an app-owned, bounded 24-hour store scoped by authenticated principal plus `SearchRequest.id`; model and `x-codex-window-id` are deliberately excluded so references survive model changes and compaction. Without the optional sidecar, local/mixed open uses the bounded static Python fetcher and the projected schema omits browser commands. With the authenticated `web-run` Docker sidecar, self-hosted Google uses short-lived bounded Patchright contexts, while open uses a session context and adds scoped `turnXfetchY` references, numbered-link `click`, text `find`, and PDF `turnXviewY` plus `screenshot`; PyMuPDF extracts/renders PDF pages and Tesseract provides OCR fallback. Alpha.23 SearchResponse has optional structured `results`; the local bridge emits normalized `text_result` objects for actual searches, preserves explicit empty results, and omits the field when no search ran. Public-address checks cover navigation/subresources/redirects/PDF downloads; unknown, expired, or cross-session references fail closed, and remaining unsupported commands/settings fail before partial execution. Gateway Logs record local request/result/error stages, executor choice, operation counts, and reference/cache counts without tokens | `gateway/codex_auxiliary.py`, `gateway/codex_images.py`, `gateway/codex_search.py`, `gateway/web_run_capabilities.py`, `gateway/web_run_sidecar.py`, `gateway/codex_search_references.py`, `gateway/codex_page.py`, `gateway/tool_profiles.py`, `gateway/app.py`, `gateway/transport/credential_redaction.py`, `routing.py`, `gateway/resources/web_run/app.py`, `gateway/resources/web_run/google_search.py`, `test_codex_search.py`, `test_web_run_sidecar.py`, `test_web_run_google_search.py`, `test_codex_search_references.py`, `test_codex_page.py`, `test_codex_auxiliary.py`, `test_provider_return_redaction.py`, `test_transport_credential_redaction.py`, `test_downstream_routes.py`, `../openai-codex-src/codex-rs/core/src/tools/spec_plan.rs`, `../openai-codex-src/codex-rs/codex-api/src/search.rs`, `../openai-codex-src/codex-rs/ext/image-generation/` | Codex changes endpoint paths, fixed image model or parent-route metadata, Images API body/response, SearchRequest commands/settings, required headers, SearchResponse shape, `SearchRequest.id` lifecycle, image-generation auth/feature/modality exposure gates, Patchright/browser behavior, Google result-page behavior, open/click/find/screenshot reference semantics, PDF screenshot result expectations, or no longer includes routing model/session identity |
| Request and window identity | Read `x-codex-window-id` as the authenticated session key for provider continuation metadata and phase behavior; tool-history object translations use only the authenticated principal and do not use the window. Enforce the documented 128-byte window and 256-byte model identity envelopes before routing/state allocation; keep external `x-request-id` correlation-only and require 1–128 visible ASCII bytes before body/log/trace/persistence/state/upstream use, generating a UUID when absent. Ordinary requests may forward that correlation header, but exact attested-wire requests must not acquire a Gateway-generated header absent from the inbound wire. Use a private nonce when no window exists, and clear request-local window state at normal/error/cancel completion | `gateway/app.py`, `gateway/proxy.py`, `gateway/state_scope.py`, `gateway/headers.py` | Codex changes to only send canonical `client_metadata`, changes window or request-ID semantics, or needs an identity above the safety envelope |
| Responses→Chat bridge | Convert Codex Responses requests to Chat via IR, expand Function Namespace children as the regex-safe canonical `namespace-function`, and rebuild Responses output. Namespace non-Function children reuse the same loss-minimizing degradation as top-level non-Function tools, so a custom child remains a callable raw child container without changing ordinary Function prefix/restoration semantics. Synthetic `response.reasoning_summary_text.delta` events carry `summary_index: 0`, matching the single synthetic reasoning summary consumed by Codex. Response restoration also accepts `namespace_function`, `namespace.function`, or a bare child name only when exactly one Namespace owns it and no top-level Function has that name; ambiguous names remain flat. Codex `agent_message` input becomes Chat-visible user content, including its inter-agent `content[].encrypted_content`, while ordinary message/reasoning encrypted content remains opaque | `converters/openai_responses/**`, `gateway/proxy.py` | High; new item/event/identity fields are not automatically transparent, Namespace child kinds or Function naming can become ambiguous, and inter-agent payload carriers can change independently |
| Responses Lite / `additional_tools` | Responses→Responses can be transmitted transparently as is; Responses→Chat merges the top-level tools with `input[].type=additional_tools`, retains the developer instructions, and removes duplication according to the final Chat name. Codex 0.149 groups ordinary and custom execution tools under the `functions` Namespace; Rosetta retains those custom children for Chat degradation and recursively infers only exact `type=custom` `exec`/`apply_patch` capability leaves without flattening or mutating the request | `converters/openai_responses/tool_ops.py`, `converter.py`, `gateway/tool_adaptation.py`, `gateway/proxy.py` | High; the location or kind of Lite tools, Namespace child encoding, and developer instructions may change |
| Codex model catalog | Treat the bundled catalog and local catalog overrides as Codex client capability declarations, while Rosetta model groups remain the routing source of truth for alias, upstream model, Provider Profile, protocol, and Tool Profile. The packaged Codex catalog remains version-bound. Model resolution prefers an exact upstream slug and falls back to the exposed slug, deep-copies the complete matched record, applies a recursive `model_info` override, then copies the selected provider runtime preset, matches its exact upstream-first/exposed-fallback model preset, and applies provider-declared `temperature`/`top_p` request overrides. The canonical deep diff against both matched bases is the only persisted override; the resulting `ResolvedModelProfile` is shared by local catalog generation and Gateway enforcement. Its `comp_hash` overlay remains selected only by upstream model name, so Provider identity cannot change compaction compatibility. Admin preserves hidden complete-record fields behind a visual model-information dialog and exposes auto-filled Provider limits in a separate dialog; it marks canonical differences yellow, and restore/clear returns to the matched preset. The Models page also manages confirmed-local-mode task models and the transactional local-mode catalog/Provider lifecycle described below. The configured-Responses Search Model allowlist is separately fixed to the reviewed Responses Lite slugs `gpt-5.6-sol`, `gpt-5.6-terra`, and `gpt-5.6-luna`; extractor drift forces an explicit search-routing review instead of silently adding or replacing a model | `gateway/codex_models.json`, `gateway/codex_models_version.md`, `gateway/codex_model_presets.json`, `gateway/model_presets.py`, `gateway/model_profiles.py`, `gateway/provider_profiles.py`, `gateway/local_mode.py`, `gateway/cli.py`, `gateway/config.py`, Admin config/UI, `test_model_profiles.py`, `test_model_presets.py`, `test_local_mode.py`, `test_cli_local_mode.py`, `test_admin_config_routes.py`, `test_codex_source_contract.py`, `../openai-codex-src/codex-rs/models-manager/models.json`, `../openai-codex-src/codex-rs/model-provider/src/provider.rs`, `../openai-codex-src/codex-rs/core/src/guardian/review.rs`, `../openai-codex-src/codex-rs/memories/write/src/phase1.rs`, `../openai-codex-src/codex-rs/memories/write/src/phase2.rs`, `docs/en/codex-model-catalog.md`, `docs/zh-cn/codex-model-catalog.md` | A Codex upgrade changes fields, nested types, enum values, serde defaults/skip behavior, fallback metadata, bundled model count/order/values, prompt precedence, catalog file loading, `model_catalog_json`, `model_provider`, configured Provider parsing, `is_openai()` semantics, task-model provider defaults, Guardian override lookup, memory model config fields, Responses Lite slugs, or the requests/tools selected by those values. Revalidate the complete-record merge/diff contract, provider and exact-model runtime presets, upstream-name preset/hash selection and Provider invariance, auto-review tool mode/override, memory model selection, managed Provider identity, and the fixed configured-search allowlist |
| custom/freeform tool | Identify `apply_patch` and Code Mode `exec` of Responses `type: custom`, including exact custom leaves nested by Responses Lite under a Namespace, convert them into Chat callable form, and restore Codex-native tool type, call/output in response return. Capability inference recursively reads Namespace child lists but grants custom execution only for exact custom type/name pairs. For Chat Default, treat the Disabled parent `exec` as a conversion container: retain it through Responses source filtering, parse selected nested declarations from its live description, project them as normal Chat Functions, and remove only the exact heading-through-declaration-fence spans whose replacements were actually emitted. Remove the parent only when every recognized section was consumed and no deferred guidance, unknown section, duplicate section, direct-name conflict, malformed known section, or unparsed source description remains; otherwise send the pruned raw `exec(input: string)` beside the ordinary Functions. On Tool Mapping only, a copied Profile with Modified `web.run` instead retains the parent `exec` and structurally rewrites only its live `### web__run` section in both ordinary `tools` and Lite `additional_tools`; Passthrough remains unchanged, missing declarations are never invented, and malformed Modified sections are removed fail-closed. Model calls are deterministically rebuilt as custom `exec` JavaScript without duplicating Codex schemas. JSON Schema constraints omitted by Codex's TypeScript renderer remain irrecoverable. The source contract hashes the current exec description builder, nested heading/declaration renderers, web description and command schema | `openai_responses/converter.py`, `openai_responses/tool_ops.py`, `gateway/tool_profiles.py`, `gateway/proxy.py`, `gateway/code_mode_projection.py`, `gateway/tool_adaptation.py`, `test_tool_profiles.py`, `test_code_mode_projection.py`, `test_tool_adaptation.py` | Codex changes the custom grammar, Namespace placement, TypeScript schema renderer, exec section/declaration syntax, normalized nested names, web description/schema, helper output contract, call/output/delta event, or internal-container lifecycle |
| Code tool localization | Catalog schema v6 owns the complete model-visible definitions for `Read`/`Edit`/`Write`/`Glob`/`Grep` and `send_line`; runtime adapters only translate validated calls back to Codex-native tools. `Edit` and `Write` explicitly require preference over Shell/Python for file mutation. Chat Default projects selected nested `exec_command`, `write_stdin`, `update_plan`, `view_image`, `web.run`, Goal, Clock, Memories, Skills, conditionally `image_gen`, and conditionally assembled deferred/environment/context/plugin/MCP-resource/Agent-Job tools from Code Mode `exec`, including when Codex 0.149 delivers that custom container under the Lite `functions` Namespace, while preserving same-named direct Functions. When effective native `write_stdin` and enabled `send_line` are both present, Rosetta exposes `send_line(session_id, line)` and reconstructs exactly one real newline; the `exec_command`/`write_stdin` hints are conditional catalog description fragments and disappear with the facade. `view_image` modality policy, unknown-modality fail-open behavior, eager-only delivery, and supported detail enum are catalog declarations. `web.run` identity/binding remains catalog data, but Provider command fields, sub-capabilities, validation, invocation, and cardinality projection are code-owned. A Feature- or runtime-gated declaration that Codex omitted is never otherwise synthesized. The parent `exec` remains an internal container as declared by catalog delivery metadata. Model-facing `apply_patch` remains disabled while its internal projection supports localized edits. `Bash` is not exposed and survives only as the historical alias of `exec_command`; the obsolete hosted `image_generation` suppression has been removed. Parse failures, missing projections, duplicate sections, and direct-name conflicts fail closed | `gateway/tool_catalog_contract.py`, `gateway/tool_runtime_plan.py`, `gateway/code_mode_projection.py`, `gateway/web_run_capabilities.py`, `gateway/tool_adaptation.py`, `gateway/proxy.py`, `gateway/tool_profiles.py`, `gateway/admin/tool_catalog.json`, `test_tool_runtime_plan.py`, `test_code_mode_projection.py`, `test_tool_adaptation.py`, `test_tool_profiles.py`, `test_admin_tools_catalog.py` | Tool name, catalog schema/adapter contract, exec declaration syntax or Namespace placement, helper output contract, direct-versus-nested availability, modality metadata, conditional assembly, capability IDs, or Profile state changes |
| Tool history consistency | Persist exact call and result object translations independently as principal-scoped, HMAC-addressed, authenticated encrypted SQLite state, including projected Chat Function to custom `exec` objects. Exclude only protocol top-level IDs from identity and inject the current ID on replay; retain nested IDs. Session, thread, window, fork, Provider, model, and call ID do not select entries. Use an absolute non-renewing 24-hour TTL, retranslate and rewrite after expiry, migrate encrypted-v1 calls atomically, and enforce 16 MiB per row, 8,192 rows/256 MiB per principal, and 32,768 rows/512 MiB globally | `gateway/tool_history_translation.py`, `gateway/proxy.py`, `gateway/tool_adaptation.py`, `observability/tool_history_store.py`, `observability/persistence.py`, `observability/tool_mapping_crypto.py`, `test_tool_history_translation.py`, `test_tool_history_store.py`, `test_tool_adaptation.py` | Codex history replay, compact, fork, call/result or output shape changes; custom `exec` call representation; database/key backup mismatch; content identity, principal ownership, migration, or capacity changes |
| Deferred tool discovery | Catalog schema v7 owns the fixed `tool_search`, `tool_read`, and `invoke_deferred_tool` definitions and adapters. `tool_read` returns a SHA-256 `definition_hash`; dispatch requires paired request-local search/read history, the exact name/hash/declaration, the same live runtime definition, and an enabled Profile capability. Strictly parsed MCP, plugin, app, connector, and other catalog/family-owned runtime names may use the current nested `exec` adapter. Section headings accept either backticked names or bounded bare `[A-Za-z0-9_.-]+` names; all other heading forms fail closed. Malformed, ambiguous, unsupported, stale, cross-request-only, or direct-name-conflicting evidence is rejected; a persistent surface snapshot never grants invocation authority | `gateway/tool_catalog_contract.py`, `gateway/tool_runtime_plan.py`, `gateway/tool_search_bridge.py`, `gateway/code_mode_projection.py`, `gateway/tool_adaptation.py`, `converters/openai_responses/tool_ops.py`, `test_tool_runtime_plan.py`, `test_code_mode_projection.py`, `test_tool_adaptation.py`, `tests/converters/openai_responses/test_tool_ops.py` | Native tool-search schema/history, deferred guidance, section-heading grammar, `ALL_TOOLS` format, hash/adapter contract, dynamic family registration, or direct-name precedence changes |
| Codex tool usage tips | Supplement the Chat model with `request_user_input`, `create_goal`, `update_goal`, localized file-mutation precedence, concise `exec_command` session guidance that assigns polling/raw or complex interaction to `write_stdin` and simple single-line input to `send_line`, and a minimal final `write_stdin.chars` sentence directing line-oriented input to `send_line`; their Admin card descriptions are shown only in Modified state | `converters/openai_chat/tool_ops.py`, `gateway/tool_adaptation.py`, `gateway/code_mode_projection.py`, tool catalog, related pipeline tests | schema, mode availability or Desktop/runtime tool contract changes |
| Skill delivery surfaces | Keep local filesystem Skills and orchestrator-owned Skills as two distinct Codex client contracts. Local `codex exec` discovers filesystem roots and injects the selected `SKILL.md` body without `skills.list`/`skills.read`; orchestrator-owned Skills require app-server, no attached local execution environment, `[orchestrator.skills]`, and exact opaque handles returned by `skills.list` then reused by `skills.read`. Rosetta does not convert either surface, but its isolated runtime fixtures must preserve the distinction | `tests/live_agent/local_skills/`, `tests/live_agent/orchestrator_skills/`, `test_live_agent_configuration_contract.py`, `docs/dev/agent-tool-testing.md`, `../openai-codex-src/codex-rs/core-skills/`, `../openai-codex-src/codex-rs/ext/skills/` | Skill root discovery, catalog metadata, selection/body injection, orchestrator availability gates, Namespace schemas, resource pagination, opaque-handle semantics, or runner/environment rules change |
| Live-agent runtime authentication | Every Gateway-backed live cell uses the production-intended identity/routing combination: ChatGPT OAuth copied into the ignored isolated Codex home plus the local-mode `codex_rosetta`/`OpenAI` Provider's `experimental_bearer_token`. OAuth owns Codex identity and capability gates; Provider auth precedence keeps model and auxiliary requests on the isolated Gateway. Gateway credentials come only from `~/.config/codex-rosetta-gateway`, OAuth only from `/Users/ibobby/.codex-multi-2/auth.json`, and neither source nor any secret value may enter Git history. The run records only credential-free runtime-auth evidence | `tests/live_agent/runtime-contract.json`, live-agent runner skill and documentation, `test_live_agent_configuration_contract.py` | Codex auth storage, auth-mode recognition, Provider auth precedence, `requires_openai_auth`, local-mode Provider generation, or auth-gated capability exposure changes |

| Web search bridge | Web Search Providers are independent code-owned contracts/adapters; the static Tool Catalog owns ordinary tool declarations only and must not duplicate provider sub-capabilities, request fields, validation, or invocation. Modified `web.run` resolves only the canonical `server.web_search.providers` list. One persisted sticky-current row starts each request; a Provider search failure makes one circular pass over eligible rows, and the first success becomes current. Unsupported sub-tools return currently unavailable without switching or cooldown. Ordinary failures create a one-hour process-local cooldown; a supported periodic-credit check persistently excludes only exact-zero credit and is retried on demand no more than hourly. Admin can select cooling but not exhausted rows through the existing status route, whose routing DTO exposes only row ID/status/current. An all-configured GPT chain forwards every non-empty `commands` request body unchanged to relative `alpha/search`, where GPT owns upstream validation and the complete body/result response; Tavily/self-hosted use code-owned local query adapters and normalized references. The DeepSeek official Responses row consumes only eligible configured names from `web_search_contract.deepseek_providers`, uses the official `https://api.deepseek.com` origin, fixed `deepseek-v4-flash`, and one `search_query.q` per request; domains, recency, location, multi-query, Pro, history, usage, and quota state are out of scope. A Provider-state change preserves an existing `x-codex-window-id` projection; stale commands return currently unavailable, and a new window receives current capabilities. | `gateway/search_provider_contract.py`, `gateway/search_provider_candidates.py`, `gateway/search_provider_chain.py`, `gateway/search_provider_chain_state.py`, `gateway/search_provider_executor.py`, `gateway/codex_search.py`, `gateway/codex_auxiliary.py`, `gateway/web_search.py`, `gateway/admin/routes/config.py`, `gateway/admin/routes/network_search.py`, `webui/src/admin/pages/NetworkSearchPage.svelte`, `test_search_provider_chain.py`, `test_search_provider_executor.py`, `test_codex_auxiliary.py`, `test_admin_config_routes.py`, `test_admin_network_search_routes.py` | Provider contract/adapter, canonical config, current/quota persistence, Admin routing DTO, upstream alpha/search validation, candidate chain/error/cooldown/budget semantics, window projection, or local normalized-reference behavior changes |
| Self-hosted Bing search | `server.web_search.provider = self_hosted_bing` retains the backward-compatible RSS executor, while `self_hosted_bing_browser` explicitly selects interactive HTML parsing. Both project the same reduced Codex `search_query` contract when the authenticated sidecar is browser-ready. The Gateway sends the selected provider to `/v1/search`; the sidecar uses an isolated Patchright context, extracts bounded results, unwraps `bing.com/ck/a` targets when present, reapplies domain filters, and fails closed on challenge or parser failure within the current self-hosted row without implicitly switching engines. That typed candidate-health failure may still advance to a later explicitly configured candidate without changing the Codex Search `output`/optional `results` response contract | `gateway/config.py`, `gateway/app.py`, `gateway/codex_search.py`, `gateway/web_run_sidecar.py`, `gateway/resources/web_run/app.py`, `gateway/resources/web_run/bing_search.py`, `test_web_run_bing_search.py`, `test_web_run_sidecar.py`, `test_codex_search.py` | Bing RSS or HTML markup, redirect encoding, challenge behavior, provider selection, sidecar request schema, or Codex Search response shape changes |
| Late instruction message cache compatibility | On an enabled Responses→Chat route with authenticated Codex turn metadata, preserve the contiguous leading system/developer prefix. After the first ordinary conversation item, convert every valid system or developer message to a separate user-role message with its original content wrapped in `<system>...</system>`. The rule is positional and content-agnostic: `<turn_aborted>`, fork, plugin, skill, and other runtime instruction text are not separately classified. Ordinary user messages, malformed items, direct Responses, and non-Chat protocols are unchanged. Stream cancellation remains ordinary cancellation: Rosetta does not drain it, retain hidden output, synthesize tool results, or replay content. Any retired plaintext handoff table is deleted on startup | `gateway/late_developer_message.py`, `gateway/app.py`, `gateway/provider_profiles.py`, `observability/persistence.py`, Admin Provider UI, `test_late_developer_message.py`, `tests/live_agent/interrupt_continuation/`, `test_persistence_sqlite.py` | Codex changes `client_metadata["x-codex-turn-metadata"]`, request-kind identity, leading instruction placement, instruction item shape, or ESC/fork/plugin/skill scheduling; a Chat Provider changes role support or prompt-cache segmentation |
| Stream lifecycle | Rebuild `response.created`, item added/delta/done, `response.completed`, etc. from Chat chunks Responses SSE; classify normal EOF, provider error, client cancellation, and bounded line/event overflow consistently in transport/telemetry/trace. After HTTP 200 begins, protocol/safety/network/local failures emit one source-protocol terminal error event with the correct origin label; cancellation emits none | `openai_responses/converter.py`, `gateway/app.py`, `gateway/downstream_errors.py`, `gateway/proxy.py`, `gateway/transport/http/transport.py` | Codex parser adds required events, sequences or termination conditions; `response.failed`/`response.incomplete` or downstream disconnect semantics change; maximum required event size changes |
| Message phase | Use tool calls and terminal events to infer `commentary`/`final_answer`, write phase back to message item; override native tool/web search signal | `gateway/stream_phase_buffer.py`, `test_stream_phase_buffer.py` | phase enumeration or Codex mailbox/final-answer semantic changes |
| Reasoning | Convert reasoning effort/summary, retain reasoning summary/content, `reasoning_content` and `encrypted_content`; Provider Profile plus protocol owns wire fields, while `ResolvedModelProfile` owns only the supported effort ladder | `capabilities.py`, `gateway/provider_profiles.py`, `gateway/model_profiles.py`, `pipeline.py`, `converters/base/helpers/reasoning.py`, Responses/Chat content, config and stream converters, provider-wide reasoning declarations, `test_model_profiles.py`, `test_provider_profiles.py`, `test_reasoning_mapping.py`, `test_pipeline.py` | New effort, summary delivery, reasoning event or encryption status change; provider/protocol support changes; any reintroduction of model-name wire branching |
| Context compaction resilience | Remove orphan `tool_choice/tool_config` that has no tools but remains after compact; keep tool history replayable | `converters/base/helpers/tool_orphan_fix.py`, `test_strip_orphaned_tool_config.py` | Codex compact output, window generation or historical clipping changes |
| GPT relay provider identity | Codex gates sequential-cutoff reasoning delivery and internal ChatGPT item metadata on the selected Provider's case-sensitive display name `OpenAI`, not its `model_provider` ID; request Zstd and current-model compact fallback additionally require Codex-backend auth. Local mode therefore uses ID `codex_rosetta` with `name = "OpenAI"`, plus an explicit bearer token that keeps the configured Provider on the custom-token auth path. The provider-neutral real-service A/B suite sends both identities through the same selected relay and labels synthetic backend-auth cells | `gateway/local_mode.py`, `tests/integration/gpt_relay/`, `../openai-codex-src/codex-rs/model-provider-info/src/lib.rs`, `../openai-codex-src/codex-rs/model-provider/src/provider.rs`, `../openai-codex-src/codex-rs/core/src/session/turn.rs`, Codex request client and history normalization | Codex changes `is_openai`, configured bearer-token precedence, auth classification, request compression, metadata clearing, reasoning-summary delivery, remote compact error classification, or fallback order; a relay accepts ordinary API-key requests but rejects an OpenAI-identity wire variant |
| Model-group tool profiles | Every bundled and user Profile declares a required non-empty `api_types` set. Catalog schema v6 additionally declares `state_api_types` per item, so Admin disables and the backend rejects states that cannot apply to every selected protocol. Chat Default is Chat-only; Responses Profiles remain Responses-only. The Admin catalog is presented as Exec Expansion, Function, Namespace, and Rosetta Injection. Chat Default injects catalog-owned file tools plus `send_line`, deferred read/dispatch tools when their dependencies are effective, and uses Modified Chat `tool_search`; the Responses built-in Profile explicitly keeps native `tool_search` Passthrough. Model modality, runtime capability, source-tool presence, and dependency predicates are compiled into `ToolRuntimePlan`. The special Responses Pass through option is not a Profile and bypasses the plan entirely, preserving strict zero tool mutation and raw-wire eligibility. Bundled Profile state is immutable; permitted input overrides remain separate | `gateway/tool_catalog_contract.py`, `gateway/tool_runtime_plan.py`, `gateway/tool_profiles.py`, `gateway/config.py`, `gateway/model_presets.py`, `gateway/code_mode_projection.py`, Admin tools/model-group UI, `gateway/proxy.py` | Codex tool IDs, modality metadata, Profile protocol ownership, state/API restrictions, input IDs, delivery declarations, adapter dependencies, or Responses bypass semantics change |
| Static tool catalog | Package schema v7 keeps 57 concrete items as the sole Profile/runtime declaration source and adds 62 exact source registrations plus five dynamic families. Every Codex static, generated, Hosted, or Hidden registration maps exactly once to an item; every dynamic entry maps exactly once to a family. Source binding, exposure, surface stability, initial delivery, adapter identity, wire identity, and the pinned source commit `25af12f7e61572b0bc18ddb1008be543b91519b0` fail closed at startup and in the source-contract extractor. Runtime names are validated by family rather than copied into static items; Rosetta injections remain explicitly marked | `src/codex_rosetta/gateway/admin/tool_catalog.json`, `gateway/tool_catalog_contract.py`, `gateway/admin/tool_catalog.py`, `scripts/check_codex_compatibility.py`, `test_tool_runtime_plan.py`, `test_admin_tools_catalog.py`, `test_codex_source_contract.py` | Codex adds or changes a registration form, ToolSpec/ToolExposure, contributor/runtime family, delivery/adapter identity, wire type, conditional exposure, or source binding |
| Window-scoped Chat tool surface stability | For authenticated Codex Responses/Responses Lite→Chat requests with a valid `x-codex-window-id` and selected Tool Profile, lock the first final ordered Chat tool array per principal/provider/model/window/API/contract generation. Strictly parsed live additions and same-name schema changes remain deferred behind request-local search/read/hash authorization; removed eager definitions remain visible but never recreate a missing executor. Opaque, ambiguous, unsupported, or explicitly selected changes atomically start a new epoch. AES-GCM snapshots use an independent HMAC/AAD domain, encrypted scope/tool/manifest payload, sliding 24-hour TTL, hard no-eviction quotas, transactional first-writer semantics, and fail-closed 503 before upstream on persistence/integrity failure. Direct Responses, native Chat, Anthropic, Google, and windowless requests are unchanged | `gateway/chat_tool_surface.py`, `gateway/tool_adaptation.py`, `gateway/code_mode_projection.py`, `gateway/proxy.py`, `gateway/app.py`, `observability/chat_tool_surface_store.py`, `observability/tool_mapping_crypto.py`, `observability/persistence.py`, `test_chat_tool_surface.py`, `test_code_mode_projection.py` | Window identity, Profile/catalog/adapter generation, tool ordering/schema, dynamic registration, Code Mode declaration, persistence key/schema/quota, or provider routing changes |
| Collaboration argument confidentiality and delivery mode | Preserve `encrypted_function_args` opaquely only on direct Responses transport. Responses→Chat ignores the field before Chat serialization and tool-history capture, treating absent, null, empty, and non-empty values identically. No converted response synthesizes it. This deliberately keeps collaboration v2 calls on the prior encrypted-content delivery path for Chat upstreams while native Responses may use Codex's structured-plaintext marker semantics | `gateway/proxy.py` direct Responses path, `converters/openai_responses/tool_ops.py` existing field selection, `gateway/tool_history_translation.py`, `test_pipeline.py`, `test_tool_history_translation.py`, `test_responses_passthrough.py` | Codex changes the marker type, its plaintext/encrypted interpretation, eligible collaboration tools, provider filtering, replay semantics, or logging/redaction boundary |

For `CP-07`, Admin upstream model discovery accepts only an object root with
the provider's expected array, object members, and string model identifiers.
Syntactically valid wrong-shape JSON returns a stable controlled error and must
not enter model sorting or Admin rendering. This boundary is owned by
`gateway/admin/routes/config.py` and
`tests/gateway/test_admin_model_discovery_cleanup.py`.

### Alpha.23 Chat Default profile refinement

The Chat Default Modified profile owns descriptive guidance for interactive
`exec_command`/`write_stdin` continuation and line termination. It tells the
model to reuse a returned `session_id`, use `write_stdin` for polling, raw
character input, or complex multi-step interaction, and use `send_line` for
simple single-line input. The current guidance contains no command, newline-
escaping, or model-specific example. The profile does not normalize or rewrite
the resulting model arguments; OpenAI Responses passthrough remains unchanged.
Covered by `gateway/admin/tool_catalog.json`,
`test_code_mode_projection.py`, `test_admin_tools_catalog.py`, and the
credential-free live evidence in `reports/live-evidence.md`.

The current CP-02 boundary is location-based. Codex 0.145.0 authentication is
present only in the inbound HTTP `Authorization` header, which direct Responses
removes before Provider authentication is overlaid last. Model request bodies
and model output are not searched for configured credentials.

The current OpenAI Responses, OpenAI Chat, Anthropic Messages, and Google GenAI
response contracts declare no API-authentication body fields. Their registered
response authentication path inventory is therefore empty, and upstream HTTP
response headers are not forwarded. Converted and direct model documents and
streams pass ordinary text unchanged. Deferred stream diagnostics use a
request-owned anonymous disk spool until terminal safety classification. Safe
completed batches are retained in full without an aggregate byte or
record-count limit; individual diagnostic strings retain their configured cap.
Failed, cancelled, or unsafe batches are discarded. Trace I/O failure disables
that request's diagnostics and never changes or terminates the model stream.
Model-response diagnostics redact explicit authentication/token fields only;
request diagnostics and auxiliary clients keep exact configured-token
redaction and collision protection.

For CP-05/CP-17, `computer_call` is the canonical public Responses wire item.
The non-streaming Responses IR round trip preserves its native structure.
Chat, Anthropic, and Google targets, plus the generic streaming bridge, reject
`computer_use` explicitly; Rosetta does not invent a function representation or
silently discard the call item. Direct Responses transport remains byte-transparent
under the ordinary transport safety envelope. The 20260721-1148 omission audit
found that `computer_call_output` is not yet owned by the IR/result dispatcher and
is currently silently discarded; this is an open Must-Fix decision point. The
owner must either authorize an explicit unsupported-item rejection (the current
scope recommendation) or a complete native output/screenshot round trip before
claiming the computer-call history contract is complete.

## Compatibility point test matrix

| Compatibility points | Can be automated | Must be actually tested |
| --- | --- | --- |
| Agent-facing API | Routing, method, content type, SSE terminal/error fixture; fixed-tier body-limit validation before and after Zstd decoding, malformed/trailing Zstd rejection, authenticated decode ordering, and real App-dispatch retention of request-local attested wire state across middleware; Admin persistence/hot reload, default and unlimited runtime mapping; fake upstream single-round and multi-round playback | Real Codex completes single/multi-round via gateway, including an OpenAI-identity Zstd request and an image-heavy request above the old 50 MB ceiling; the session ends normally and errors are visible |
| Responses transparent handling | Admin exposes one `responses` protocol, and all Provider selections use the same direct Responses transport. Only selected Profile tool changes and model-switch plaintext compaction may alter an ordinary request. Successful direct JSON and ordinary SSE events are preserved subject to transport limits; upstream HTTP/SSE error envelopes and codes are retained while the exact documented message leaf receives the `Upstream:` label. Configured credential strings in ordinary model content are not scanned. Current response-authentication field paths are empty for Responses, Chat, Anthropic, and Google. Exact attested streaming requests preserve their original wire body; changed requests use rebuilt JSON without the original attestation | Verify Provider selection and Tool Profile behavior, byte-identical raw-wire eligibility, rebuilt JSON fallback after mutation, Provider auth precedence, model token text passing through direct and converted successful responses, exact error-message origin labels without ordinary-string scanning, more than 4096 model fragments completing, response diagnostics redacting only explicit auth/token fields, and auxiliary-client exact protection remaining green. For the internal auxiliary streaming guard, verify more than 4096 ordinary and structured fragments complete below the structured byte bound, cross-fragment decoded/wire/JSON-escaped credentials fail closed, completed safe SSE events release immediately, and termination/EOF/cancel/close release all state |
| Codex Search and Images endpoints | Verify all three POST routes, model validation/aliasing, native pass-through path/body/status/header/error behavior, Profile-selected OpenAI Images Base URL/Bearer token forwarding for generation and edits on Chat, Responses, Anthropic, and Google Profile protocols, fixed `gpt-image-2` fallback through one unique Modified mapping, ambiguity rejection for distinct Modified mappings, missing/invalid image configuration, Disabled handling, secret-free Gateway Logs, configured local Tavily and self-hosted Google search, bounded static direct-URL and stored-reference open, authenticated principal/`SearchRequest.id` isolation, retry-stable and concurrent reference allocation, TTL/capacity cleanup, Python time behavior, public-address/redirect/content-type/size/line handling, domain/context/length mapping, atomic mixed-command rejection, and stable unsupported-feature errors. Modified `web.run` projection fixtures must cover the persisted current row across top-level Functions, ordinary nested `exec`, Lite `additional_tools`, and Responses→Chat: every new-window surface retains `open`/`time`/`response_length`; an unready self-hosted current row omits `search_query` even when a later configured Responses or Tavily row is eligible; a configured Responses current row, a Tavily current row with a valid Key, or a self-hosted current row whose sidecar reports `browser_ready=true` exposes its supported `search_query` schema. Later fallback rows do not widen the new-window surface. Existing windows retain their locked projection across Provider-state changes, and stale invocations fail as currently unavailable. Browser-ready health exposes `click` (`ref_id`, `id`), `find` (`ref_id`, `pattern`), and `screenshot` (`ref_id`, `pageno`). Unsupported guidance must be removed, Passthrough must retain every live schema branch and the original description text, malformed Modified nested sections must be removed without changing sibling exec sections, and missing declarations must not be invented. Validate the shared five-second health TTL, concurrent refresh coalescing, hot-reload invalidation, sidecar bearer authentication, bounded HTTP responses, self-hosted Google query/result bounds and domain filtering, session/reference isolation and expiry, public-address enforcement, JavaScript-rendered open, numbered-link click, find, PDF embedded-text extraction, page rendering, OCR fallback, and behavior when the sidecar is unavailable. Projection fixtures must also cover both a supplied live `image_gen` declaration and the fail-closed case where Codex omits it | Invoke standalone `web.run` through Tool Mapping only with a copied Profile set to Passthrough and confirm upstream forwarding and the complete live declaration; repeat with `web.run` Modified and inspect the upstream `exec.description`: a new window whose current row is unready self-hosted must omit `search_query` even when a later row is eligible; a new window whose current row is configured Responses, Tavily with a valid Key, or Self-hosted (Google) plus a ready sidecar must include that row's supported query schema; browser commands must appear only after sidecar health reports `browser_ready=true`. Confirm that an existing window retains its locked surface after the current Provider changes and that a stale command fails as currently unavailable. Complete successful configured Responses, Tavily, and self-hosted Google local searches, `turnXsearchY` static open and time calls. Enable the isolated `web-run` container, then run JavaScript `open`, `click`, `find`, a PDF open, and PDF `screenshot`; inspect Gateway Logs for sidecar executor and operation counts. Confirm Google challenge/rate-limit failures surface without an implicit engine substitution within the current self-hosted row; when an explicit later candidate exists, the typed candidate-health failure may advance to it. Confirm expired/cross-session/unknown references fail closed, and remaining unsupported commands return fatal 501. Test a converted third-party model with Chat Default separately. Invoke `image_gen.imagegen` generation and edit through a Modified Profile and confirm the selected OpenAI Images endpoint, fixed image model or configured alias as applicable, response, and saved artifact. Run `tests/live_agent/image_generation/01` only after `view_image` and visual recognition pass; seed the isolated home from the authorized ChatGPT OAuth source while retaining the Gateway bearer Provider, prove both model and Images requests reach the isolated Gateway, and classify an absent declaration as an auth/exposure failure before attributing anything to the upstream model |
| Request and window identity | header/body metadata extraction; exact/+1 model, window, and request-ID budgets; request-ID validation/generation; correlation/state-key separation; no-window isolation; persistent-window continuity; provider-metadata quotas; terminal cleanup; and direct-Responses filtering that removes only inbound `Authorization` plus framing, hop-by-hop, `Connection`-declared, and network-origin identity fields | Capture header/body/window/request-ID changes and maximum observed lengths; verify Provider auth replaces every case variant of inbound `Authorization`, other unknown end-to-end headers survive direct routing, and conversion routes retain their explicit minimal header set |
| Responses→Chat bridge | request/response/stream/history four-way fixture; fake Chat upstream multi-round tool playback; hyphenated Function Namespace expansion plus hyphen, dotted, underscore and uniquely unqualified child restoration in streaming/non-streaming responses; generic Namespace custom-child degradation; top-level Function, multi-Namespace child and alias-collision cases must remain fail-closed; `agent_message` exposes only its own encrypted payload while unrelated encrypted content remains opaque | Use `deepseek-v4-flash` to complete text, multi-round tools, error recovery and final answer; for collaboration, verify all six native calls, inter-agent payload delivery, and the model-facing name against the restored Namespace |
| Responses Lite / `additional_tools` | Accurate replay of Lite requests; extract embedded tools and developer instructions; preserve 0.149-shaped Namespace custom children; recursively detect exact custom `exec`/`apply_patch` while ignoring malformed/unknown leaves and retaining legacy top-level forms; verify allowed command projections, override top/embedded tool mixing, deduplication, `reasoning.context=all_turns`, `parallel_tool_calls=false` and embedded image-generation removal | Use exact Codex 0.149 with local `ox-alpha`; complete real read, edit/write, and shell calls through the nested `functions` Namespace, then confirm the next round consumes their results |
| Codex model catalog | Diff the complete bundled JSON key set and per-model values; verify the packaged upstream asset byte-for-byte; validate exact upstream-first/exposed-fallback preset matching, complete hidden `model_info` preservation through the visual editor, recursive merge/diff, whole-array replacement, explicit null, unknown-preset validation, provider and exact-model runtime-preset inheritance, Provider-declared `temperature`/`top_p` overrides, rejection by undeclared providers, model-bound Admin auto-fill, yellow modified state, named restore, separate Provider-limits UI, and identical Codex/Gateway `ResolvedModelProfile` use. Test local-mode defaults, custom Codex Home, CLI/WebUI lifecycle, stable alias generation, TOML preservation, managed cleanup, mutation synchronization, key non-rotation, Provider replacement, rollback, package resources, and exact set equality between extracted Responses Lite slugs and the fixed configured-search model allowlist | Start Codex against generated automatic and manually edited catalogs; confirm the selected alias, complete display metadata, Provider identity and bearer key. Restart after a WebUI model/runtime mutation and confirm the canonical minimal config diff and matching Gateway sampling override. For every preset selector, run the actual third-party upstream and inspect Gateway Logs for command/code mode, Responses Lite, reasoning, context/compact, image input, search, collaboration v2, and OpenAI-identity compact behavior. If Responses Lite slugs drift, resolve the current official latest model and explicitly retain, add, replace, or retire each configured-search option before accepting the compatibility baseline |
| custom/freeform tool | `apply_patch` schema/grammar/delta/call-output round-trip; top-level and Namespace-nested custom degradation; strict recursive capability inference; Code Mode `exec` in Responses→Chat→Responses, non-streaming, added/delta/done/completed return trips are restored to `custom_tool_call`; non-compliant third-party parameters are retained, and no guessing is rewritten to JavaScript | Real Codex execution success patch, failed patch Post-fix correction; with exact 0.149, execute `exec/wait` and nested tool calls from the Lite `functions` Namespace, confirm that tool failure is visible and fatal incompatible-payload will not appear |
| Code tool localization | native/localized schema mapping, parameter conversion, call id, result recovery and history replay; a 0.149-shaped Lite `functions` Namespace must project existing command tools and route localized Write/Edit through native `exec`/`apply_patch` without the unsupported-support error | Really execute read/edit/write/search/shell with exact Codex 0.149 and local `ox-alpha`, and confirm that tool history can still be correctly consumed in the next round |
| Tool history consistency | Exact encrypted at-rest payload, authenticated restart replay, missing/wrong key and tamper fail-closed, plaintext and encrypted-v1 schema migration, row/session/principal/global row+byte budgets, replacement accounting, TTL release, transactional write rollback, abnormal replay bounds, and concurrent principal/session isolation | compact/resume/restart after multiple rounds of tools, confirm that there are no repeated calls or orphaned output; restore a matched database/key backup; exercise a session near the documented replay envelope |
| Deferred tool discovery | Fixed synthetic `tool_search`, `tool_read`, and `invoke_deferred_tool` exposure only with live deferred guidance; byte-identical top-level Chat `tools` across search/read/call; exact schemas; natural-language and regex search; bounded whole summary matches; bounded exact declaration read; paired-read allowlist authorization; direct-name conflicts; custom `exec` round trip; raw `exec` retention; no Gateway window/cache state; ordered skill/plugin contextual metadata, explicit skill/plugin injection, implicit selected-skill read, and plugin provenance | Run `tests/live_agent/deferred_tool_search/01` through `07`. Require `tool_search` and `tool_read` to translate to custom `exec`, request-local ordered candidates, selected declaration provenance, only the selected archive body/tool through raw `exec`, a consumed result, and no implicit-prompt identifier leakage. Separately require Browser Node matches to follow `tool_search → tool_read → invoke_deferred_tool`, while Gateway emits the Node custom `exec` wrapper and model-facing top-level tool bytes remain unchanged. Repeat with regex and verify that search alone or a fresh request cannot authorize dispatcher use |
| Skill delivery surfaces | Validate filesystem Skill root discovery, catalog rendering, explicit `$skill` selection, full body injection, and the separate orchestrator `skills.list`/`skills.read` schemas and opaque-handle validation against the pinned Codex source | Run `tests/live_agent/local_skills/01` through ordinary local `codex exec` and require catalog plus explicit body injection with zero Skills Namespace calls. Run `tests/live_agent/orchestrator_skills/01` only through app-server with no local execution environment, `[orchestrator.skills]`, and a provisioned `codex_apps` MCP resource backend; require `skills.list → skills.read` to reuse the returned package/main-resource handles exactly |
| Live-agent runtime authentication | Validate the shared runtime contract, fixed credential-source paths, local-mode Provider identity, dual-auth requirement, ignored secret destinations, credential-free evidence schema, and browser-only exception | For every Gateway-backed CLI and app-server cell, copy Gateway credentials only from `~/.config/codex-rosetta-gateway` and ChatGPT OAuth only from `/Users/ibobby/.codex-multi-2/auth.json`; prove `codex login status` is ChatGPT, the bearer is present without recording it, and actual model requests reach the isolated localhost Gateway. Reject OAuth-only, bearer-only, bypassed-Gateway, or secret-bearing artifacts as invalid runner configurations |
| Codex tool usage tips | tool description/schema injection and mode availability fixture | Under local mode with Provider ID `codex_rosetta`, display name exactly `OpenAI`, and its generated catalog, use `gpt-5.6-terra` as the default GPT cell with one permitted Sol fallback and execute `builtin_tools/01` through `06` for Code Mode `wait`, Plan, protocol-neutral file modification, image viewing, Goal lifecycle, and upstream visual recognition. On Chat record natural use of `Glob`/`Grep`/`Read`/`Edit`/`Write`; on direct GPT record native `apply_patch`. Before image tasks, require the selected model catalog entry to include image input and verify that `view_image` is actually exposed; text-only models are unsupported rather than failed image cells. Accept an omitted `detail` or any value in the visible schema instead of requiring `original`. Use `qwen3.7-plus` by default for task 06. `request_user_input` requires an app-server JSON-RPC runner because `codex exec` explicitly rejects it; do not count an exec-mode rejection as model evidence |
| Web search bridge | Validate zero through 32 canonical rows and rejection of the retired single-row object; strict row/provider/model/key validation; candidate identity and duplicate/credential-overlap rejection; persisted sticky-current selection; circular complete-request replay with one attempt per eligible candidate; success persistence; unsupported-sub-tool no-switch behavior; one-hour process-local cooldown; exact-zero persistent quota exclusion and hourly on-demand recovery checks; reorder/identity-change/restart behavior; manual cooling selection and exhausted rejection; and bounded state/concurrency/budget behavior. Provider sub-capabilities, fields, validation, invocation, and projection are code-owned; the static Tool Catalog only declares/binds the ordinary tool. All-GPT preserves the complete live alpha/search wire, while mixed chains are single-query until a per-query GPT adapter exists and reject larger requests before external work or cooldown. Verify the unchanged Passthrough/Disabled semantics, exact three-option Responses model allowlist, final upstream-model override, single Provider/single Key convergence, configured Responses and self-hosted boundaries, five-minute Tavily usage cache/coalescing exposing only plan usage/limit plus month-start reset date, bounded Admin current/status/usage/Search Test DTOs, and `x-codex-window-id` projection locking with stale-command rejection | Exercise a multiple-row chain through real Codex and verify current-first circular full-request replay, one attempt per eligible candidate, successful current persistence, selected Responses model and Provider credential, visible recovery after an eligible failure, no switch for an unsupported sub-tool, and no raw Provider error disclosure. Verify that an existing window retains its projected surface while a new window receives current capabilities. Test all three reviewed Responses models separately. Record that live Provider/sidecar/network evidence is required; deterministic tests alone do not approve compatibility |
| Self-hosted Bing search | Validate RSS and browser provider selection, authenticated sidecar request shape, bounded result parsing, Bing redirect unwrapping, domain filtering, challenge detection, current-row fail-closed behavior without implicit engine switching, typed candidate-health advancement to a later explicitly configured candidate, reduced `search_query` projection, and text-only Codex output | Run Self-hosted (Bing RSS) and Self-hosted (Bing Browser) separately through a real Codex turn. Confirm the selected executor and counts in Gateway Logs, successful search/result continuation, redirect targets and domain filters, and a visible fail-closed error on challenge or parser failure within the current row without an implicit engine switch. In a separate explicit multi-row chain, confirm the same eligible typed candidate-health failure can advance to the configured later Google or Tavily candidate |
| Late instruction message cache compatibility | Validate DeepSeek/default/explicit Provider configuration, Codex metadata gating, leading-prefix preservation, positional copy-on-write conversion of all later system/developer messages, string and multipart `<system>` wrapping, malformed/user skips, non-Chat/direct-Responses exclusion, old-table deletion, and unchanged ordinary stream cancellation | Through a temporary non-8765 Gateway, run `tests/live_agent/interrupt_continuation/run_live.py --mode interrupt`, `--mode steer`, and `--mode fork` against DeepSeek Chat with one fresh random `user_id` per cell. Record per-request input/output/cached tokens when usage is present, target role/marker counts, Provider request count, and terminal events. Confirm ESC cancels the predecessor, the next request contains exactly one user-role `<system>` envelope and no canonical middle system notice, its completed usage reports a non-zero cache hit, Steer contains neither notice form, and Rosetta sends no extra upstream request. The fork cell must use real `thread/fork`, create a different thread/session ID, preserve the parent target messages as an exact prefix, keep tool definitions unchanged, convert its injected late instruction item to one user-role `<system>` envelope, and complete with non-zero cached input tokens; record `prompt_cache_key` change as an observation rather than a pass condition. Exercise system, developer, plugin, and skill late-instruction shapes deterministically because the production rule does not inspect their text |
| Stream lifecycle | created, item/delta/done, completed/failed/incomplete sequence; exact error-origin labeling; incomplete-to-failed mapping; protocol-valid late terminal errors; huge declared HTTP chunks; no-newline/no-delimiter SSE; converted/raw/web-search overflow and early-close classification; complete anonymous-spool release for safe deferred response diagnostics beyond 1 MiB/4096 records; discard and cleanup on failure, cancellation, and `aclose()`; protocol-field-only response diagnostics with ordinary-error retention | Real streaming turn, upstream interruption, and client disconnect without duplication/truncation/stuck; Codex must receive the labeled failure instead of synthesizing unlabeled EOF; more than 4096 ordinary deltas must still complete, and an enabled trace must retain the complete safely finished response diagnostics and terminal usage regardless of stream length |
| Message phase | All tool signals, completed-only, added/done/completed phase consistency | Commentary/final in Codex UI is displayed correctly, mailbox/steering can work |
| Reasoning | effort/summary/content/encrypted state cross-format round-trip, required summary-delta identity, and tool continuation round fixture | `deepseek-v4-flash` reasoning can be continued before, after, and in the next round of the tool without repeated thinking; every reconstructed `response.reasoning_summary_text.delta` has the Codex-required `summary_index` and passes the final-source semantic gate |
| Context compaction resilience | orphan tool config, history trimming, compact fixture and window generation; protocol fixtures are separated from one byte-identical deterministic fact-retention scenario; unchanged attested Remote V2 requests retain their exact compressed wire body, encoding, attestation, and allowed client headers only when the selected Provider uses `request_encoding: passthrough` and no Tool Profile or web-search mutation occurs. `identity` and `zstd` always rebuild the final body. Rebuilt requests conservatively omit the opaque attestation and original content encoding while retaining other allowed direct headers, including `x-codex-beta-features`; this is a provenance policy with unknown upstream effect, not a claim that the token is body-bound. The Responses-only Provider policy `force_rosetta_compaction` forces every valid trigger through the existing no-tools coordinator, requires SQLite before any summary call, preserves ordinary direct traffic and existing native compaction items, and records `compaction_forced_rosetta`. The native smoke runner can request a real Desktop DeviceCheck attestation through app-server without persisting it | Run the isolated Pixel/Cockpit four-cell matrix with one `gpt-5.6-terra` alias and Provider-only hot switching: Pixel native success; Cockpit native exact `400 invalid_request/model is required` baseline with the model still present; Cockpit forced Rosetta followed by Pixel native; and Pixel native followed by Cockpit forced Rosetta. Run both baselines, classify a mismatch as `blocked`, execute cell 4 even if cell 3 fails, and require both switch cells for `success`. Record thread/window, effective Provider/model, request IDs, compaction mode, install/replay correlation, mapping count, and token/cache deltas without summary plaintext, handles, or opaque payloads. Also run `tests/live_agent/context_compaction/run_live.py --model gpt-5.6-terra` for the isolated real manual-compact smoke cell. Context-limit commands must retain at least 20,000 output tokens and 60,000 characters so the fixture actually crosses its threshold. Classify `/responses/compact` as legacy remote, `/responses` plus a final `compaction_trigger` as Remote V2, a later installed `compaction` as follow-up, and rollout-only compact events as local/internal. For native Remote V2, require byte-identical upstream request body and matching attestation plus end-to-end capability headers with both the Pass through option and a Profile that would modify Responses Lite `additional_tools` on ordinary traffic. When Rosetta returns Remote V2 before stream tracing, require request-log `compaction_mode`/`compaction_reason`/forced policy plus mapping/install evidence. Quality scenario completed separately: GPT native and DeepSeek Rosetta each installed exactly one compaction, resumed the same thread without another command/compaction, and preserved 8/11 fixed checks; both executor reviews are `ineffective` and non-gating |
| GPT relay provider identity | Unit-test prompt-free capture/redaction, attested-wire passthrough, and C0-C5 evaluation contracts; compile the path-pinned Codex harness | Against the same real relay/model, run C0-C5 separately and compare non-OpenAI versus `OpenAI`. Require real SSE completion and actual forwarded-model evidence; additionally require original Zstd bytes plus attestation for C3, old/current compact order plus follow-up for C4, and negative controls for C5. Confirm the Provider credential, never the gateway client credential, reaches the relay. Never count harness mocks as relay evidence |
| Model-group tool profiles | Validate required `chat`/`responses`/`anthropic`/`google` Profile protocol sets, bundled protocol assignments and immutability, the Responses-only Pass through option and its reserved non-Profile ID, Admin CRUD/reference guards, backend mismatch rejection, model-group candidate filtering including user Profiles, no bundled default plus explicit compatible user Profiles on Anthropic/Google groups, bundled input-only override validation, all four Admin categories, per-tool filtering, text/password/select persistence, UI-hidden inputs, input/description state visibility, namespace pass-through/expansion, Disabled Namespace child-state coercion and selector locking, injected-tool selection, absence of hosted `image_generation`, and `web.run`/`image_gen.imagegen` endpoint selection | Use real Codex sessions on a Chat Provider with Chat Default and a Responses Provider with Pass through, web.run-mapping, and restrictive Profiles; verify Pass through performs no tool mapping, cross-protocol selection is unavailable and rejected, bundled visible fields survive explicit save/reset while protocol and delivery states reject edits, Chat Default disables `multi_agent_v1` and upstream-visible `apply_patch`, injects exactly three read plus two write tools, keeps Function guidance text hidden behind localized summaries, preserves namespace expansion/restoration, and uses the selected search/image credentials without leaking tokens |
| Static tool catalog | Validate unique item/registration/family IDs, exact source binding, ToolSpec/ToolExposure, wire identities, surface policies, dynamic-family matchers/adapters, Profile definitions, and exact CLI/source commit binding. The extractor must reject an unrecognized registration form | Compare schema v7 against every Codex static/generated/Hosted/Hidden registration and every MCP/plugin/app/connector/thread/extension dynamic entry point; verify runtime names are family-validated and absent declarations are never synthesized |
| Window-scoped Chat tool surface stability | Fixture-test first-writer concurrency, principal/provider/model/window/generation isolation, exact ordered hashes, reliable add/schema-change deferral, search/read/hash TOCTOU, stale executor behavior, explicit choice and opaque rollover, encrypted restart recovery, 24-hour sliding TTL, quotas, wrong key/tamper/rollback, 503 before upstream, streaming/non-streaming final transport equality, and unaffected routes | Replay the recorded 29→30 plugin transition with three isolated Flash IDs and the same sequence on Pro after Flash passes. Require the final top-level tool bytes to stay at the first baseline, the live plugin schemas to remain discoverable/invocable only after model search/read, cache loss within the identical-request tolerance, matching Gateway/DeepSeek usage, no extra upstream request, and no mapping/conversion warning. Count opaque rollover as an expected cache reset |
| Collaboration argument confidentiality and delivery mode | Parametrize missing, null, empty-array, and non-empty-array markers and require byte-identical converted Chat bodies plus identical canonical tool-history templates. Require direct Responses to retain the marker and converted Responses output never to add it | Run the complete Multi-Agent V2 matrix. Native Responses with `[]` must exercise structured plaintext; native missing/null must exercise encrypted delivery. Every converted Chat variant must complete through encrypted delivery with no request/cache drift, marker leakage to a non-OpenAI upstream, or plaintext argument logging |

## 1. Request, header and session identity

The current Codex source code is clarified in `codex-rs/core/src/responses_metadata.rs`: the canonical carrier of the complete turn metadata is the `client_metadata["x-codex-turn-metadata"]` of the request body, and the HTTP `x-codex-*` headers are compatible projections.

Rosetta's current behavior:

- `gateway/app.py::_proxy_handler` reads `x-codex-window-id` from HTTP header;
- model IDs are limited to 256 UTF-8 bytes and window IDs to 128 UTF-8 bytes before routing/state allocation;
- window id serves as the key for provider continuation metadata and phase
  status; principal-scoped tool-history object translations and request-local
  `ALL_TOOLS` search deliberately do not use it;
- provider continuation metadata uses the same authenticated principal/window scope; it enforces 1 MiB per entry, 8 MiB per scope, 1,024 entries/16 MiB per principal, and 10,000 entries/64 MiB globally, and global count replacement never evicts another principal;
- `x-request-id` remains a trace/response correlation value and never becomes a state key; without a window header, each inbound request receives a private non-reusable scope that is cleared when non-streaming or streaming delivery ends normally, fails, or is cancelled;
- `gateway/headers.py` forwards `x-request-id`, `User-Agent` and `OpenResponses-Version` on ordinary requests; exact attested-wire forwarding drops the Gateway-owned `x-request-id` while preserving supported client metadata;
- Responses→Responses always leaves non-tool body fields intact, so canonical `client_metadata` never passes through IR; only cross-protocol routes require explicit metadata coverage;
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

Direct same-format Responses routing is an important forward compatibility strategy: after the selected Profile is applied, or with tool mapping skipped for the special Pass through option, unknown non-tool fields are not compressed into the IR first, and the response is not reserialized. This invariant applies to every Provider. The Provider selection still chooses the default tool handling—official OpenAI uses Pass through, OpenAI/custom relays use `web.run` injection, and listed third-party providers use Tool Mapping—but never selects a different protocol-processing path. Model-switch compaction is deliberately handled before this direct path so an old Provider's opaque encrypted item is replaced by Rosetta-managed plaintext. These branches and the compaction exception must remain separately testable during upgrades.

`x-oai-attestation` remains an opaque compatibility boundary. Codex requests it
just in time from an attestation-capable app-server connection, but the public
provider interface receives only the thread ID and does not reveal what the
returned token authenticates. Rosetta therefore preserves it only with the
unchanged captured wire and omits it after request reconstruction as a
conservative provenance policy. Whether an upstream accepts, ignores, changes
behavior for, or rejects a reconstructed request carrying the original token
is unverified. Treat any exact-wire versus rebuilt-request discrepancy as an
attestation/header-coupling diagnostic priority, and do not describe the token
as body-bound until source, protocol documentation, or a controlled replay
proves that property.

Responses→Chat is an explicit compatibility layer. After adding request item, tool type, reasoning field or SSE event to Codex, you must confirm that the converter has a clear downgrade/recovery strategy, and "request successful" cannot be regarded as agent loop compatibility.

### Responses Lite and `additional_tools`

The bundled model catalog of Codex 0.144.0 has `use_responses_lite=true` enabled for some models. In this mode, Codex no longer puts tools at the top level `tools`: it inserts a `type: "additional_tools"` item at the beginning of `input` and uses a developer message to carry the original instructions; reasoning may also use `context: "all_turns"`.

Direct Responses retains this body except for selected Profile tool changes and model-switch compaction rehydration, regardless of Provider.
Responses→Chat depends on explicit IR coverage and now merges
top-level tools with `input[].type=additional_tools`, preserves the embedded
developer instructions, deduplicates by the final Chat tool name, and applies
image-generation filtering to both locations. Converter and gateway regression
tests cover these paths, and the 0.144.0 upgrade report records a controlled
multi-turn Lite/code-mode run through `deepseek-v4-flash`. Native GPT routing
and untriggered catalog combinations remain real-test gaps, not an
`additional_tools` implementation gap.

Codex returns freeform Code Mode results as `custom_tool_call_output`, including
multi-part `input_text` output from `exec`. Responses→Chat converts those items
to the same IR tool-result path as `function_call_output` so the paired Chat
tool message contains the actual script/search result instead of an orphan-call
placeholder. A real `gpt-5.6-sol` alias backed by `deepseek-v4-flash` consumed
that output and completed `web.run` through local Tavily in the controlled
network-search test.

### Model catalog metadata and third-party aliases

The catalog is an input to Codex client behavior, not a Rosetta routing table.
`slug` must match the alias exposed by Rosetta, while the model group remains
responsible for selecting the upstream model, provider, protocol, and Tool
Profile. Capability fields then determine which request dialect, prompts,
reasoning options, context budgets, and tools Codex attempts to use.

Every upgrade must compare the full bundled `models.json` key/value set with
`ModelInfo`, its nested structs and enums, serde rename/default/skip behavior,
the unknown-model fallback initializer, and the runtime consumers of each
field. This includes catalog keys ignored by the current client and valid
defaulted fields absent from the bundled JSON. The maintained field inventory
and third-party decisions are documented in
[`docs/en/codex-model-catalog.md`](../../en/codex-model-catalog.md) and its Chinese
counterpart.

For new third-party aliases, the target design should prefer the current Codex
surface: `web.run` over legacy hosted `web_search`, and collaboration v2 over
legacy `multi_agent_v1`. This is a preference after capability verification,
not permission to copy a built-in model's catalog wholesale. Until the actual
model completes the newer search/open or subagent lifecycle through Rosetta,
the corresponding field/tool should remain disabled or use the proven older
surface.

Rosetta local mode is the sole owner of `<codex-home>/model_catalog.json`. With
no configured models it starts from the eight bound Codex 0.145.0
entries; otherwise it writes only configured aliases in stable name order. In
both paths it applies the runtime `comp_hash` overlay and emits the legacy
`supports_reasoning_summaries` alias for 0.144.x clients; the formal Rust
loader ignores that
extra key, so the packaged asset remains byte-identical while the generated
local catalog is intentionally not. Exact aliases found in
`codex_model_presets.json` receive their declared Terra-derived preset,
including prompt identity substitution; other aliases use the generic Terra
copy with only `slug`, `display_name`, and `description` replaced. The runtime
shared preset fields start from the target Terra catalog, currently the 24
client-consumed identity-independent fields reviewed from official
`0.145.0`. The catalog targets current flagship third-party models and
keeps Responses Lite, Code Mode only, collaboration v2, and the Terra search
metadata as fixed shared behavior; only Rosetta's verified protocol semantics
or model-specific facts justify a different value.
Every shared key may be overridden by a model entry. Known fields are
materialized from model-specific values, dedicated prompt/reasoning logic, or
this shared snapshot; `template_slug` copies only unknown future fields as a
forward-compatible fallback and cannot resurrect a known removed field or the
client-ignored `available_in_plans`, `minimal_client_version`,
`prefer_websockets`, and `reasoning_summary_format` keys. This catalog-only
review is not a full `0.145` compatibility classification. The runtime
`comp_hash` overlay uses the configured upstream model name to select a preset,
falling back to the exposed alias when no mapping exists. A preset's explicit
non-empty hash takes precedence; otherwise the name selects a reviewed group or
the deterministic custom hash. Provider identity is deliberately excluded,
aliases mapped to one upstream model share a hash, and changing the upstream
model or its selected preset can change the hash. Automated coverage must hold
alias and Provider inputs independently while varying the upstream name and
must verify explicit preset-hash inheritance. A real Codex test must
switch Providers for one unchanged upstream model without triggering
model-switch compaction, then switch the upstream name and confirm the normal
non-empty/unequal-hash compaction path. The gateway removes every active `model_catalog_json`
assignment from Codex `config.toml` before writing one root absolute path, but
preserves unrelated TOML text and never deletes a file referenced by an old
assignment. On each confirmed startup or Admin synchronization it also ensures
one gateway key with ID/label `codex`; an existing key is reused without
rotation. It replaces root `model_provider` with `codex_rosetta`, removes the
buggy root-level reasoning setting written by older Rosetta builds, and updates
`[desktop].enabled-reasoning-efforts` when it does not already contain all six
values (`low`, `medium`, `high`, `xhigh`, `max`, and `ultra`). It replaces
the managed `[model_providers.codex_rosetta]` table with an OpenAI-named
Responses provider using the resolved bearer key and effective loopback port.
Other Provider tables and their parameters remain unchanged. Disabling local
mode removes the managed catalog, selection, and Provider table but retains the
gateway key for later reuse. Synchronization compares the complete generated
catalog and TOML bytes with their snapshots and skips byte-identical writes; a
Provider-only model-group edit therefore hot-reloads gateway routing without a
Codex-file write or restart notice. Replacing managed `[memories]` assignments
reuses any retained blank-line separator before the next table, so repeated
synchronization is byte-idempotent instead of accumulating whitespace. Gateway
config, catalog, TOML, and hot activation use compensating rollback. An upgrade
must rebind the packaged asset and retest this ownership, idempotence,
compaction-hash, and Provider-identity contract before changing the declared
Codex version.

Admin exact-slug detection prefers `upstream_model` and falls back to the
exposed alias. It resolves the complete current Codex `ModelInfo` record by
deep-copying the matched preset and applying recursive config overrides; the
selected Provider Profile contributes a separately copied runtime preset.
Objects merge recursively, arrays replace, scalars replace, and null is an
explicit override. Save computes a canonical deep diff against both bases and
omits empty override objects. Unknown presets require a complete valid
`model_info`. Runtime override fields and exact model-name presets are declared
by the Provider Profile; currently only OpenCode Go exposes `temperature` and
`top_p`. Provider preset matching prefers `upstream_model` and falls back to the
exposed alias. Values replace or, when explicitly null, remove the corresponding
request-IR sampling value.
Admin preserves hidden complete-record fields behind a visual model editor and
opens Provider limits in a separate dialog. It marks any canonical diff in
yellow, while restore or clear removes it. The resulting single
`ResolvedModelProfile` supplies both local Codex catalog generation and Gateway
enforcement. Upgrade checks must compare the complete catalog record, both
sampling override fields, exact model bindings, and upstream-first matching,
not a fixed eight-field subset.

The Models page exposes task-model routing only while local mode is both enabled
and confirmed. It stores the source selections under gateway `codex`, copies
`auto_review_model_override` onto every generated catalog entry because
Guardian reads the current turn model's metadata, and manages only
`extract_model` plus `consolidation_model` inside Codex `[memories]`. Editable
unset or stale values are yellow and configured values are green. Inactive
local mode locks the selectors to `codex-auto-review`, `gpt-5.4`, and
`gpt-5.4-mini`, reporting each configured default in green and each missing
route in red. Clear removes the managed TOML memory assignments while retaining
the gateway selections for a later local-mode activation.

The hidden `codex-auto-review` alias is selected by model mapping rather than
provider heuristics. An absent/empty upstream model or the same
`codex-auto-review` upstream keeps the official entry byte-equivalent at the
parsed JSON level, including its null `tool_mode`; this supports native
Responses passthrough to OpenAI and GPT relay services. An explicitly different
upstream model forces only `tool_mode` to `code_mode_only`. That mapping acts as
the user's non-OpenAI-service signal and intentionally narrows Rosetta's review
path to the newer Code Mode instead of requiring support for every legacy and
mixed Guardian tool surface. Tests must cover object and shorthand-string model
configuration for both branches.

## 3. Codex-native tools and history replay

The current Codex source code exposes `apply_patch` as a freeform grammar tool with Responses `type: "custom"`; the call uses `custom_tool_call`, the parameter is a string, and the result uses `custom_tool_call_output`. Catalogs with code mode enabled also expose `exec` on the same wire type, whose `input` must be a raw JavaScript source, not a shell parameter object. Rosetta maintains two layers simultaneously and is compatible with:

1. The Responses converter safely downgrades a native custom tool into an IR/Chat representation, then restores the native Responses item from preserved metadata;
2. Every Responses→Chat route localizes Codex editing tools into forms more familiar to Chat models, then translates model calls back to `apply_patch`, `exec_command`, or a controlled fallback. This is protocol policy, not model configuration. Direct Responses→Responses routes bypass this adaptation and preserve the upstream body.

When Chat upstream downgrades the custom/freeform tool to a normal function call, the Responses return must restore `custom_tool_call` according to the `metadata.provider_type="custom"` recorded during the request period; this applies to both non-streaming responses and streaming added/delta/done/completed. The `{"cmd": "..."}` returned by a third-party model cannot be synthesized into JavaScript without authorization: it is evidence that the model does not adhere to freeform semantics, and should be handled by Codex as a visible tool error and let the model retry, rather than letting Rosetta guess the execution intention.

Because Codex resends history on subsequent requests, this project stores each
native/model-facing call and result translation independently. The authenticated
principal is the sole ownership key. A principal- and object-kind-separated HMAC
addresses the exact source template; AES-256-GCM authenticates and encrypts both
source and target. Only the protocol top-level call ID is removed from identity
and the current ID is injected on replay; nested IDs remain exact. Consequently
Provider, model, session, thread, window, fork, and call ID changes cannot select
or block an otherwise exact translation. Diagnostic redaction never substitutes
`[REDACTED]` into executable replay data. Missing, mismatched, damaged,
over-budget, conflicting, or inconsistently-accounted key/ciphertext state for
model calls fails closed. Ciphertext plus ownership metadata is capped at 16 MiB
per row, 8,192 rows/256 MiB per principal, and 32,768 rows/512 MiB globally.
Each entry expires after an absolute non-renewing 24 hours; an expired miss is
retranslated and, after upstream acceptance, stored with a fresh TTL. This is a
critical prompt-cache path and must be tested with fork/window changes, compact,
resume, parallel calls, reversed and failed results, expiry rewrite,
restart/backup, migration, quota, and rollback failure.

Deferred Code Mode tools use the live `ALL_TOOLS` runtime catalog instead of a
Gateway namespace map. When the source `exec.description` contains Codex's
deferred-tool guidance, Rosetta exposes fixed ordinary Chat `tool_search`,
`tool_read`, and `invoke_deferred_tool` Functions beside raw `exec`. Their
complete top-level definitions and order do not change across search, read, or
invocation turns.

`tool_search` validates its `query`, optional `limit`, and optional
natural-language/regex mode before Rosetta builds deterministic custom `exec`
JavaScript. The script searches only the current runtime Array and returns
versioned, bounded `{name, summary}` entries through `text(...)`. Summaries are
derived from the declaration introduction, whitespace-normalized, and limited
to 240 characters. The serialized result has a 24,000-character budget, admits
only whole candidates, and reports `returned_matches`, `total_matches`, and
`truncated`. Invalid regex is a structured zero-match result.

`tool_read` takes one exact name and generates a second custom `exec` script
that retrieves the complete declaration. Its versioned result also has a
24,000-character serialized budget and fails closed with `result_too_large`
instead of slicing the declaration. For an unblocked `mcp__` tool, the read
result appends the exact `invoke_deferred_tool` instruction. Non-MCP
declarations use raw `exec` with `tools[entry.name](...)`.

On the next Responses-to-Chat request, Rosetta recovers exactly paired
`tool_read` call/output items from request history. It accepts an exact searched
`mcp__` name only when the paired read description contains a parseable
declaration for that same tool. The three Browser Node tools retain their
existing static projections; other MCP names receive request-local generic
projections. The model supplies the fixed dispatcher name, exact deferred name,
and structured JSON arguments; Rosetta generates the outer custom `exec` call
with JSON-safe bracket access for unknown names. Discovered MCP tools never
become independent top-level Chat Functions. `CallToolResult.content` text and
image blocks are forwarded with `text(...)` and `image(...)`; other blocks are
serialized as text and `isError` remains model-visible. A result containing
only `js` never exposes either helper. Direct same-named Functions still win.
The paired search summary and complete read result remain in their original
history positions.
Malformed, oversized, unpaired, mismatched, unauthorized, and non-object calls
fail closed without invoking a dynamic tool. A direct dispatcher conflict
disables synthetic dispatcher guidance and leaves all deferred calls on raw
`exec`; a direct same-named Node Function prevents authorization for that name.
Direct Node Function calls are not accepted as a compatibility alias; Browser
runtime execution must use the fixed dispatcher after a valid paired read.

There is no discovered/deferred store, authenticated-window ownership, TTL,
quota, namespace hiding, or later IR injection. Native `tool_search_call/output`
is synthesized only by the catalog-declared Chat passthrough bridge for an
actually present client-executed native declaration; it is not used as a
discovery cache. The next request must carry the paired read history; compaction
or a fresh request without it requires another search and read. The generic
localized-call mapping may restore the model-facing names, but activation also
recognizes Rosetta's marked raw read `exec` history and therefore does not
depend on that mapping cache. Tool Profiles still own static namespace expansion
and filtering; runtime plugin/MCP availability is owned by Codex's `ALL_TOOLS`.
The generic Responses converter continues to parse native
`tool_search_call/output` for protocol compatibility, but that path does not
load tools into a Rosetta discovery cache.

For Namespace children expanded onto a flat Chat tool surface, Rosetta uses
`namespace-function` as the canonical Chat-visible name. The return path also
recognizes `namespace_function`, `namespace.function`, and a bare child name.
The bare form is
restored only when exactly one Namespace owns that child and no ordinary
top-level Function uses the same name. The underscore form is likewise restored
only when it maps uniquely and does not collide with a top-level Function.
Ambiguity is never guessed: the call remains flat and Codex rejects an
unsupported call instead of Rosetta routing it to the wrong Namespace.

Codex collaboration messages are carried as Responses `agent_message` items.
For the Responses→Chat bridge, Rosetta converts these to user messages and
includes both ordinary `input_text` and the inter-agent task payload stored in
that item's `encrypted_content` part. This exception is scoped to
`agent_message`: ordinary message and reasoning encrypted content is not
exposed as model-visible text. Without this conversion a `fork_turns="none"`
child receives an empty `Payload:` and may reconstruct the wrong task from the
workspace.

The deferred Namespace whitelist remains separate from this one-time expansion
rule. The Codex `0.144.4` source still carries an optional Namespace on
`ResponseItem::FunctionCall`, and the reviewed release diff did not change the
`multi_agent_v2`/`collaboration` tool contract. Dedicated six-scenario real
coverage is nevertheless required before this route is considered verified.

The OpenAI Chat tool converter also adds model-visible usage hints for `request_user_input`, `create_goal`, `update_goal`, and selected collaboration lifecycle Functions. Collaboration guidance clarifies complete child messages, future-only waits, canonical path filtering, and canonical message targets. `request_user_input` can be checked against the adjacent source checkout; some Goal tools come from real Desktop/runtime payloads and do not have matching definitions there. Retain real session/tool fixtures during upgrades instead of relying only on source searches.

### Static tool catalog version binding

`src/codex_rosetta/gateway/admin/tool_catalog.json` is the schema-v6 source of truth for model-visible tool ownership. Its metadata is bound to Codex CLI `0.145.0` and source commit `25af12f7e61572b0bc18ddb1008be543b91519b0`. It contains 57 entries: the 53 reviewed source concepts plus explicit contracts for native/modified `tool_search`, `send_line`, `tool_read`, and `invoke_deferred_tool`. The latter remain request-conditional; catalog ownership does not mean they are synthesized without their declared source/dependency predicates. The obsolete hosted `image_generation` tool and runtime-dynamic MCP, plugin, app, and connector tools, including GitHub, remain excluded. Under Code Mode, Codex flattens namespaced tools nested in `exec` to `namespace__function` properties, so the catalog directly lists `clock__*`, `web__run`, `image_gen__imagegen`, `memories__*`, and `skills__*` without synthetic parent Namespace items. Only directly model-visible Responses Namespaces such as `collaboration` and legacy `multi_agent_v1` retain Namespace parents. Startup compilation produces an immutable contract and fails closed on an unknown field or adapter, invalid dependency/state/API combination, duplicate identity, or cycle. The per-request `ToolRuntimePlan` then evaluates actual declarations, route, modalities, and runtime capabilities; therefore the catalog still does not claim that every item is available in every request.

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

Gateway transport keeps the total successful HTTP/SSE stream size and duration
unlimited, but it applies a 1 MiB per-line and 8 MiB per-event `data:` limit to
both converted parsing and byte-preserving Responses passthrough. Chunked HTTP
payloads are read in fixed bounded subchunks instead of materializing the
peer-declared chunk size. Overflows close the upstream and become a stable
`UpstreamStreamLimitError`; credential-free raw passthrough bytes below the
limits are byte-identical. Exact-wire and one-layer parsed JSON collisions
across arbitrary HTTP chunk boundaries block the complete risk event and
terminate from a valid SSE boundary. The auxiliary consumer-semantic gate
preserves duplicate object members and parses only documented Responses/Chat
function and tool argument JSON strings. Ordinary decoded fields use bounded
per-consumer rolling overlap windows; only unfinished embedded-JSON arguments
are accumulated under the same call/item/index identities as their consumers.
The top-level JSON close is tracked incrementally, inspected immediately, and
then released. There is no total fragment-count limit. Unfinished structured
state is bounded to 1 MiB and 4096 identities, while ordinary rolling windows
have a separate 4096-identity limit; exceeding a live-state bound fails closed.
Complete safe SSE events are released immediately. Unknown ordinary strings
are not recursively parsed, and credential-free safe duplicate/BOM frames
remain byte-identical. Every new provider argument schema or consumer identity
rule must be registered and regression-tested explicitly.
A Codex upgrade that introduces larger required single events must be measured
and reviewed rather than disabling the limits.

The Gateway also bounds streaming connection establishment to 10 minutes,
upstream SSE inactivity to 5 minutes, and connection cleanup to 5 seconds.
This prevents a route change from leaving Codex attached to a black-holed
upstream socket: after HTTP 200 has begun, Rosetta emits one source-protocol
terminal error event labeled `Upstream: ` instead of leaving Codex to infer an
unlabeled premature EOF. Rosetta does not replay a stream after any upstream
bytes have been delivered. Automated coverage must retain stalled
open, stalled parsed/raw body, bounded cleanup, and normal long-stream framing;
real Codex testing must switch Wi-Fi or enable a route-changing VPN during a
turn and confirm that a later retry completes without restarting the Gateway.
Expected upstream stream timeouts and disconnects are normalized to one
traceback-free `ERROR` line and a labeled 502 stream outcome. Protocol failures
use `Upstream: `, safety-policy failures use `Codex Rosetta blocked: `, and
Gateway failures use `Codex Rosetta: `; client cancellation emits no error event.

`phase` is inside the message item, not a separate event. `commentary` is not just a UI label: the current Codex checks the mailbox after the commentary item is completed, and may change subsequent sampling behavior. Therefore the phase in added, done and completed output must be consistent.

Currently `ResponsesPhaseBuffer` treats function/custom/MCP/shell/computer/tool_search/ web_search calls as tool signals. Automated regression covers "text followed by native search tool" and the scenario where there is only native search call in `response.completed.output`, ensuring that the previous text is marked as `commentary` instead of erroneously marked as `final_answer`. When adding a new Codex output item type, you still need to clearly determine whether it will continue the agent loop, and expand this set and the tests of the two event paths accordingly.

## 5. Reasoning state

Codex will request `reasoning.encrypted_content` when reasoning is turned on, and consume summary part, summary text delta/done and raw reasoning delta. Rosetta currently retains Responses summary/content/encrypted state through IR metadata, and uses provider extension fields such as `reasoning_content` in Chat upstream to maintain tool continuation. When a Chat reasoning delta is rebuilt as `response.reasoning_summary_text.delta`, Rosetta emits `summary_index: 0` for its single synthetic summary. Missing or conflicting consumer-visible stream identity is a response-contract failure; only an actual configured-token match is a credential collision. Codex's inbound `light` display value is normalized immediately to the backend value `low`; no provider request or mapping metadata should contain `light`. OpenAI Responses and Chat preserve `max`.

Reasoning wire controls are selected only by the immutable Provider Profile and
its standard converter. Model identity contributes only the resolved supported
reasoning ladder. An unsupported effort is clamped to the nearest declared
level with a warning, but it cannot select a different raw field. The former
model-name mapper, enabled-budget/adaptive switches, per-model temperature,
image-count truncation, and model-pattern parallel-tool rules are rejected or
removed. Provider-wide OpenAI Chat profiles may emit `reasoning_effort` and
parse `reasoning_content`; Anthropic and Google use their standard converter
semantics. OpenCode Go is one OpenAI Chat profile with OpenAI Chat cached-token
usage normalization. Unadapted provider/protocol pairs use only the selected
official standard and no provider-specific reasoning extension.

Must check when upgrading:

- New value and degradation rules for reasoning effort;
- summary `auto/concise/detailed/none` and delivery order;
- required summary-delta identity fields such as `summary_index` on every
  reconstructed Responses event;
- `include: ["reasoning.encrypted_content"]`;
- Empty string `reasoning_content` coexists with tool calls;
- Renewability of reasoning items after history replay, compaction and cross-format conversion.

## 6. Current clear limitations and observations

### Canonical metadata is only naturally retained in the direct path

Bridge phase and provider-continuation state still rely on the compatibility
header. If Codex stops sending `x-codex-window-id` and only retains body
`client_metadata`, those two state families will no longer be windowed
correctly. Principal-scoped tool-history object translations and deferred
`ALL_TOOLS` search deliberately do not use this header. Every upgrade must be
confirmed with real request capture.

When the header is missing, `GatewayStateScope` creates a request-local,
non-persistent conversation ID for window-owned state. An authenticated
principal may still reuse exact tool-history object translations; an unauthenticated
direct library call without an explicit state scope remains in memory only.

### Gateway `/v1/models` is not a Codex dynamic catalog

`gateway/app.py::handle_list_models` returns the OpenAI SDK style `{"object":"list","data":[...]}`. The current dynamic catalog request of Codex source code is `GET models?client_version=...`, and the response is `{"models":[ModelInfo...]}`, among which `apply_patch_tool_type`, reasoning, parallel tools, context window, Responses Lite, tool mode and multi-agent version will change the requests and tools issued by Codex.

Therefore currently `/v1/models` cannot be considered a Codex catalog implementation. Only after it is confirmed that Codex will use the endpoint from the custom provider, it should be implemented and tested separately according to the Codex `ModelInfo` contract, and the two response formats cannot be mixed into one ambiguous endpoint.

### Responses WebSocket and `/responses/compact` are not implemented yet

The current gateway's Codex surface is HTTP `/v1/responses` + SSE. Responses WebSocket `response.create`, incremental `previous_response_id` and remote `/responses/compact` in the source code are not verified capabilities. Responses Lite is supported on both the direct and Responses→Chat paths described above; that support does not imply WebSocket, incremental-history, or remote-compact support.

Codex model/provider configurations must not declare these capabilities without testing; each upgrade must confirm that Codex still uses HTTP/SSE for custom providers, or has reliable fallback.

Currently Responses→Chat also relies on Codex to resend the complete input/history. Even if `additional_tools` is added, if Codex starts to use WebSocket/HTTP incremental requests and `previous_response_id` by default, Rosetta still does not have a corresponding server-side Responses session storage, and the bridge will lack history. This item must be determined through real request capture, and it cannot be inferred that it is enabled just from the presence of `previous_response_id` in the request type.

### Remaining code-mode and multi-agent verification gaps

The generic custom/freeform path preserves code-mode `exec` as
`custom_tool_call` with raw JavaScript input across non-streaming and streaming
added/delta/done/completed events; ordinary function tools such as `wait`
continue through the function-tool path. Automated fixtures cover the `exec`
wire round-trip, and the upgrade report records one controlled live `exec`
run. Nested call/wait continuation, malformed third-party recovery, and
`multi_agent_v2`/`collaboration` namespace discovery + call + output use the
hyphenated canonical expansion and fail-closed compatible-name restoration described above.
Automated streaming/non-streaming collision fixtures exist; dedicated real
six-scenario coverage is still required before the live gap is closed.

### Phase's native search signal has been incorporated into automated regression

`tool_search_call`/`web_search_call` has been incorporated into the phase tool signal collection and overrides the streaming item event and completed-only fallback. This fix only changes the phase classification, not the search bridge or tool execution; the real Codex UI/mailbox behavior is still a gatekeeper that must be actually tested.

### Existing real integration baselines are insufficient to prove tool compatibility

The recorded controlled 0.144.0 run covers Lite/code-mode short answers,
file-read, multi-turn read/write/diff, `ultra`, and one `exec` path through
`deepseek-v4-flash`. It does not validate native GPT routing, Goal/Plan,
request_user_input, plugin/tool_search, web search, compact/resume, nested wait,
or subagent behavior. Future upgrades must run the remaining matrix in the
upgrade checklist instead of treating the controlled alias as complete model
coverage.
