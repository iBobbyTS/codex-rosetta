# Codex 0.147.0 Upgrade Review

Date: 2026-08-17

## Analysis status

- Review mode: **full inventory, source-first**, explicitly selected by the
  developer.
- Target: annotated tag `rust-v0.147.0`, peeled commit
  `be6e8eac029b183056b7e4402879f15d2c85f61b`. The previous reviewed source is
  `rust-v0.145.0` at `25af12f7e61572b0bc18ddb1008be543b91519b0`.
- Point-in-time client: installed `codex-cli 0.145.0`. This records the client
  present during analysis; it is not the target source identity or proof that
  Codex 0.147.0 has been adopted.
- Codex-Rosetta evidence identities: feature base
  `345887ad933f8d302ebe75c63ec8bf0daae635bf`; pre-wave-2 final-reviewed head
  `880a0d78c353f331a1d523d19dce6d28bc502704`. The exact repair/final release
  head is intentionally left to subsequent bounded review and S04 evidence,
  avoiding an impossible self-reference inside its own commit.
- The bounded source range contains 565 commits and 2,025 changed paths.
- The source-contract extractor now follows the current ToolRegistry owners:
  core sources, MCP exposure, extension contributors, dynamic runtimes,
  deferred search, Code Mode registration, and final model-visible assembly.
  It no longer anchors the removed `add_dynamic_tools`, `add_extension_tools`,
  `add_tool_sources`, or `prepend_code_mode_executors` functions.
- The checked-in source snapshot is refreshed only to make later source drift
  detectable. It is **not** a compatibility or release approval.
- No live-agent test was run in this section. The package remains
  `0.144.0.r0`; the complete live inventory is mandatory and no failed or
  unverified mandatory cell may be waived. This analysis is neither release
  approval nor publication evidence.

## Full CP classification

Every current point is classified below. “Possibly unchanged” means the
source inventory found no implemented Rosetta delta but still requires the
listed real-client gate. Later implementation sections own catalog, Provider,
Images, compaction, and release changes; this section owns only the exact
source inventory and CP-26's already-existing conversion behavior.

| ID and compatibility point | Classification | 0.147 source finding and current disposition |
| --- | --- | --- |
| `CP-01 — Agent-facing API` | Possibly unchanged | Endpoint and core header constants remain stable; new image-turn identity and Provider capabilities are owned by CP-03/21. Live ingress/auth/error capture remains mandatory. |
| `CP-02 — Responses transparent handling` | Changed | Direct Responses must transparently retain new request metadata, usage fields, and `encrypted_function_args`; focused direct passthrough coverage includes the marker. |
| `CP-03 — Codex Search and Images endpoints` | Changed | Images request bodies already pass through the existing auxiliary route; `image_generation_call` is now retained by the Responses stream passthrough with `transparent_background`. S02.1 owns deterministic Images metadata, S03 owns only the managed local-mode standalone Search Provider opt-in, and S04 owns the live route matrix. |
| `CP-04 — Request and window identity` | Changed | `parent_turn_id` and Code Mode tool-name metadata join the turn metadata contract; converted ownership must remain explicit. |
| `CP-05 — Responses→Chat bridge` | Changed | The new collaboration marker is intentionally discarded on Chat conversion; new Responses-only metadata must not leak or be fabricated. |
| `CP-06 — Responses Lite / additional_tools` | Changed | Function/freeform/Namespace assembly moved under the centralized registry and Lite projection must be requalified. |
| `CP-07 — Codex model catalog` | Changed | S02 synchronized the packaged asset byte-for-byte to the reviewed 0.147 source (SHA-256 `384ff2e0…`), removed third-party `base_instructions` synthesis, added Apps/Plugin shared fields, and proved specialty plus nested collaboration/token-budget round-trip. Live client evidence remains S04-owned. |
| `CP-08 — custom/freeform tool` | Changed | Deferred custom/freeform assembly and Code Mode registration moved to ToolRegistry owners; S02 binds `exec`/`wait` to `register_code_mode_executors` through catalog data without hard-coded gateway definitions. |
| `CP-09 — Code tool localization` | Changed | Code Mode tool-name mappings are emitted in request metadata and registration/exposure semantics changed. |
| `CP-10 — Tool history consistency` | Changed | CP-26 requires marker variants to have one Chat object identity; focused canonical-template tests prove current behavior without changing persistence. |
| `CP-11 — Deferred tool discovery` | Changed | `CodeModeOnly` and `DeferredModelOnly`, default Function namespaces, collisions, and deferred runtime selection change the discovery surface. Existing schema-v7 conditional/surface/dynamic declarations express these states; runtime-plan tests retain deterministic declaration order, while live discovery remains mandatory. |
| `CP-12 — Codex tool usage tips` | Possibly unchanged | S02 synchronized catalog owner metadata without duplicating source tool schemas; static text hashes and runtime injection semantics still require full live tool use before compatibility can be claimed. |
| `CP-13 — Skill delivery surfaces` | Changed | Apps/Plugins instruction gating and extension contributor assembly changed. S02 keeps Apps/Plugin model metadata true while preserving Codex's Tool Suggest + Apps + Plugins AND-gate and binds dynamic extensions to `append_extension_tool_executors`; filesystem and orchestrator Skill paths still require complete live requalification. |
| `CP-14 — Live-agent runtime authentication` | Possibly unchanged | No new authentication owner was found; the exact 0.147 client and complete dual-auth inventory remain mandatory. |
| `CP-15 — Web search bridge` | Changed | Custom Providers may opt into standalone `/alpha/search`; S03 enables this only for the managed Rosetta local Provider. |
| `CP-16 — Self-hosted Bing search` | High-confidence unchanged | No source change alters Rosetta's self-hosted executor contract, but the standing real sidecar gates remain required. |
| `CP-17 — Stream lifecycle` | Changed | Completed usage gains optional `codex_rollout_budget_units`; Responses conversion copies it only when supplied, while converted routes never synthesize it. Deterministic converter and SSE regressions are owned by S02.1. |
| `CP-18 — Message phase` | Possibly unchanged | Phase enum and current bridge ownership show no mapped semantic delta; full UI/tool lifecycle evidence remains required. |
| `CP-19 — Reasoning` | Possibly unchanged | Reasoning field names remain stable; model-catalog and compaction changes still require the full reasoning/continuation matrix. |
| `CP-20 — Context compaction resilience` | Changed | Provider compaction capability becomes unsupported/V1/V2 and the fallback implementation changed; S02.1 owns deterministic runtime requalification and S04 owns live evidence. |
| `CP-21 — GPT relay provider identity` | Changed | Provider capabilities add standalone search/external web access and remote compaction selection; identity must not infer unsupported endpoints. |
| `CP-22 — Model-group tool profiles` | Changed | New catalog capability fields and ToolExposure variants affect the model-visible surface. S02 proved the existing Profile/compiler can express the reviewed direct/deferred/code-mode policies without a new engine owner; Tool Profile/catalog data remain the sole declaration owner. |
| `CP-23 — Static tool catalog` | Changed | S02 rebound schema-v7 metadata to exact 0.147 and maps MCP/Apps, thread function/namespace, extensions, and Code Mode generated tools to the current ToolRegistry owners exactly once. Rosetta injections remain separately documented and no gateway/converter tool definition was added. |
| `CP-24 — Late instruction message cache compatibility` | Possibly unchanged | No new late-message role transform was found; exact interrupt/steer/fork cache evidence remains mandatory. |
| `CP-25 — Window-scoped Chat tool surface stability` | Changed | New exposure states, namespaces, and Code Mode registration alter potential ordered tool surfaces. S02 locks catalog declaration order and existing runtime-plan projection deterministically; S04 must still prove live window stability. |
| `CP-26 — Collaboration argument confidentiality and delivery mode` | Changed | Direct Responses preserves the opaque marker. Converted Chat drops missing/null/empty/non-empty variants before request serialization and replay identity, never synthesizes it on return, and deliberately retains encrypted Multi-Agent V2 delivery. The source-contract group retains selected field/router/protocol/linkage anchors as partial evidence only; it does not prove transitive delivery coverage, so S04 real Codex/API gates remain mandatory. |

## CP-26 deterministic evidence

- Four marker variants produce byte-identical Chat request bodies.
- The same variants produce one canonical tool-history source template.
- A Chat tool call reconstructed as Responses does not gain the marker.
- Direct Responses retains `encrypted_function_args: []` without entering IR.
- No production converter or persistence mechanism was added: the existing
  field selection already implements the approved stable-discard policy.
- The extracted CP-26 source group is intentionally partial evidence, not a
  high-confidence compatibility closure; its selected anchors cannot replace
  the required S04 live delivery/confidentiality gates.

## Deferred mandatory evidence

S01 performs no live testing. Before approval, later sections must run the
complete live-agent inventory, including native and converted Multi-Agent V2,
standalone `web.run`, Apps/Plugins, Images, streaming usage, tool discovery,
interrupt/fork, compaction, model switching, and original-model cells. A
fallback pass never replaces an original-model failure.

---

# Codex 0.145.0 Upgrade Review (historical)

> Daily-development addendum (2026-08-01): catalog schema v7 inventories exact
> Codex source registrations and dynamic families. CP-11 now uses exact
> `definition_hash` authorization, CP-23 owns the registration inventory, and
> CP-25 owns encrypted window-scoped Chat tool-surface locking. See
> `../evidence/window_chat_tool_surface_stability.md`. This does not approve
> 0.145.0 or advance the package version.
Date: 2026-07-25
Codex version: 0.145.0

## Formal-release status

- Review mode: **full inventory, source-first**. The formal source is detached
  at `rust-v0.145.0`, commit
  `25af12f7e61572b0bc18ddb1008be543b91519b0`.
- The installed CLI used by the formal live cells reports `codex-cli 0.145.0`;
  the source checkout and installed CLI remain separate compatibility
  identifiers. The manual Browser GUI was already
  `0.146.0-alpha.3.1` on 2026-07-24 and cannot provide exact `0.145.0` GUI
  evidence. Rosetta remains `0.144.0.r0`.
- The formal source adds `InputAudio`/`Audio` protocol variants, audio in the
  Code Mode MCP forwarding helper, `never`/`unless_trusted` approval fields,
  and a changed Code Mode description builder. The bundled catalog also changes
  context limits, prompt/skills values, and carries the legacy
  `supports_reasoning_summaries` key while Rust `ModelInfo` continues to read
  `supports_reasoning_summary_parameter` with default `true`.
- Rosetta now bridges audio data URLs and Chat `input_audio` through the IR,
  preserves valid audio on Responses and Chat paths, and fail-open passes
  malformed or unsupported audio blocks. The packaged model and tool catalogs
  are bound to the formal source commit.
- The full non-integration suite passes (`3784 passed, 4 skipped`), and
  `make check-codex-compat` passes
  against the refreshed formal baseline. The post-migration agentabi matrix
  passes 3/3, and the CLI live rerun covers command execution, built-in tools,
  deferred discovery, namespace/local Skills, collaboration, network search,
  compaction, and Images. Original-model failures and permitted fallback
  outcomes remain recorded separately. No inspected post-migration trace shows
  Rosetta dropping or corrupting model-visible tool data. Both post-migration
  model-switch directions and orchestrator paths are now covered. Exact
  0.145.0 GUI, sidecar search, a scoreable summary-quality cell, and live
  audio/profile evidence remain unavailable; the Images route also lacks
  `gpt-image-2`. Therefore 0.145.0 remains **not approved** and the package
  version must not advance.

## Formal Live Progress And Remaining Gates

Completed formal live cells are retained in
[`live-evidence.md`](live-evidence.md):

| Suite/task | Model and route | Outcome |
| --- | --- | --- |
| `command_execution/01` | `gpt-5.6-terra`; `晚照 (Plus)` Responses→Responses | Passed one command start and terminal marker. |
| `command_execution/01` | `deepseek-v4-flash`; `Deepseek (Official)` Responses→Chat | Passed one reconstructed command start and terminal marker. |
| `command_execution/03` | `kimi-k3`; `Opencode Go` Responses→Chat | Passed one start plus one same-session newline write. This was a targeted rerun; task 01 was not repeated. |
| `command_execution/02` | `gpt-5.6-terra`; `晚照 (Plus)` Responses→Responses | Passed one start, one wait, and one same-session empty continuation. |
| `command_execution/02` | `kimi-k3`; `Opencode Go` Responses→Chat | Passed the permitted DeepSeek fallback with one start and one same-session empty continuation. |
| `command_execution/04` | `kimi-k3`; `Opencode Go` Responses→Chat | Passed the permitted DeepSeek fallback with one start and two ordered same-session writes. |
| `builtin_tools/01` | Terra direct and DeepSeek converted | Both passed Code Mode `exec` yield followed by top-level `wait`. |
| `builtin_tools/02` | Terra direct and DeepSeek converted | Both passed the two-call `update_plan` lifecycle. |
| `builtin_tools/03` | `gpt-5.6-terra`; `晚照 (Plus)` Responses→Responses | Core workspace outcome passed with deviations: native patching was correct but fixture reads were skipped. |
| `builtin_tools/03` | `qwen3.7-plus`; `Opencode Go` Responses→Chat | Passed all workspace assertions and selected all five localized file tools; three extra verification reads are recorded as deviations. |
| `builtin_tools/04` | `gpt-5.6-terra`; `晚照 (Plus)` Responses→Responses | Passed one `view_image` with exact `detail: "original"`. |
| `builtin_tools/05` | Terra direct and DeepSeek converted | Both passed ordered Goal lifecycle calls on one fresh thread. |
| `builtin_tools/06` | `qwen3.7-plus`; `Opencode Go` Responses→Chat | Passed one projected `view_image` call with the schema-default detail and correctly recognized all four quadrants. |
| `context_compaction/03`, `04` | Terra↔DeepSeek across Pixel Plus and Deepseek Official | Both post-migration model-switch directions passed with one `comp_hash_changed` Rosetta compaction, one mapping, same-thread replay, and exact marker. |
| `context_compaction_summary_quality/01`, `02` | Terra on Pixel Plus/Pro; DeepSeek and Kimi converted | Execution completed but no cell is scoreable. Historical Pixel Plus/Pro runs returned native-compaction 502; after the direct-header fix, `202607250101` completed the Pixel Plus native chain and same-thread resume, but its 15,863-token baseline exceeded the strict below-15,000 precondition. DeepSeek completed a valid Rosetta V2 chain but missed token/output-size preconditions; Kimi did not compact. |
| `orchestrator_skills/01` | Terra direct; DeepSeek and Kimi converted | Terra passed after recovering a native typed-output evaluator false negative. DeepSeek completed list/read but failed exact final formatting; Kimi fallback passed the exact contract. |
| `browser_use/01` | `deepseek-v4-pro`; `Deepseek (Official)` Responses→Chat from Codex GUI `0.146.0-alpha.3.1` | Rosetta capability path succeeded with limitations: all 49 streams completed, the ordered 28-tool target surface stayed stable, and deferred Browser calls round-tripped through `tool_search`, `tool_read`, `invoke_deferred_tool`, and source custom `exec`. This is current-GUI Rosetta evidence, not exact `0.145.0` GUI evidence. |
| `browser_use/01` | `gpt-5.6-sol`; `晚照 (Plus)` native Responses from Codex GUI `0.146.0-alpha.3.1` | The 23-row matrix completed but the independent judge classified it `failure` (`17 pass / 3 partial / 3 fail`). The matched wire evidence retained `exec` with `namespace: null` and showed no `namespace:exec`/`execexec`; the Browser failures therefore do not establish Rosetta namespace loss. This is current-GUI evidence, not exact `0.145.0` GUI evidence. |

The Browser partial-row analysis confirms zero Rosetta defects in that run.
Prompt handling and coordinate drag are Codex/IAB limitations; download-body
verification is blocked by a model-visible Browser API documentation/test
contract mismatch; visibility, page-assets, and filtered CDP-event gaps are
DeepSeek execution coverage or reporting problems. The default screenshot and
successful viewport `set()`/`reset()` calls already establish their supported
Rosetta paths, so missing optional screenshot variants and the nonexistent
viewport `get()` method must not be treated as product failures. Detailed
per-capability evidence and disposition are recorded in
[`live-evidence.md`](live-evidence.md#deepseek-v4-pro-browser-limitation-attribution).

Failed behavior cells remain failures even where Kimi proves the same bridge:
Terra tasks 03 and 04 never sent the required input; DeepSeek task 02 restarted
instead of polling, task 03 sent literal `rosetta\\n`, and task 04 ran a
forbidden inspection command before the correct two-write sequence. Do not
substitute Kimi success for Terra or DeepSeek model-quality passes, but use the
paired results as Rosetta bridge evidence. The detailed attribution in
[`live-evidence.md`](live-evidence.md) also distinguishes model behavior from
the two image-cell applicability/expectation mismatches: DeepSeek is text-only,
and Kimi cannot request `detail: "original"` under its advertised model
metadata. The corrected tests now derive `detail` from the visible schema, and
Rosetta suppresses `view_image` for explicitly text-only routed presets.
`gpt-5.6-sol` fallback reruns did not clear Terra's stdin failures: task `03`
omitted interactive TTY setup, while task `04` completed both same-session
writes but ran a forbidden inspection command and timed out before the final
assistant marker.

The following remains before a formal release decision. Every cell uses the
shared Conda 3.14.6 standard-GIL, local-mode, dual-auth runtime contract.

| Priority | Remaining formal gate | Minimum evidence to record |
| --- | --- | --- |
| 1 | Images route | Configure a reachable `gpt-image-2` route or an explicitly approved compatible mapping, then rerun the Qwen image cell through artifact generation and `view_image`. The current post-migration call reached the Images endpoint and returned `404 model_not_found`. |
| 1 | Post-migration context coverage | Model-switch tasks 03/04 passed. The `202607250101` Terra rerun cleared the prior Pixel Plus native-compaction 502 after the direct-header fix: one trigger, one installed follow-up, and same-thread resume all completed. Summary quality is still not scoreable because its 15,863-token baseline exceeded the strict below-15,000 precondition; DeepSeek and Kimi also missed strict token/output or compaction preconditions. Adjust the suite precondition separately before making a quality claim. |
| 1 | Sidecar search | Supply the existing test contract with an authenticated web-run sidecar URL/token, then run network tasks 03/04. Do not synthesize configuration in the test runner. |
| 2 | Audio and model profiles | Real Responses and Chat `InputAudio`/`Audio` calls; third-party Chat and Responses profile cells that exercise Code Mode audio exposure. |
| 2 | Provider identity | GPT relay C0/C1/C2/C3/C5 passed before the ownership refactor; C4 still has a 0.145 harness trigger mismatch. Record a post-migration relay sample if this surface is required for release approval. |
| Version-bound manual | Browser | Rosetta's deferred Browser path passed with limitations in the 2026-07-24 GUI run. The GUI had already updated to `0.146.0-alpha.3.1`, so exact `0.145.0` GUI behavior cannot be tested in the current installation and remains explicitly unverified. Do not discard the current-GUI Rosetta evidence or relabel it as `0.145.0` client evidence. |

## Formal CP Classification

| ID and compatibility point | Classification | Source/automation evidence | Formal live result |
| --- | --- | --- | --- |
| `CP-01 — Agent-facing API` | Changed | Codex 0.145.0 auth is confirmed at inbound `Authorization` only. Direct Responses removes that header, preserves other unknown end-to-end headers subject to transport/network filters, and overlays Provider auth last; conversion routes retain their explicit minimal set. Every `/v1` error message now has exactly one `Codex Rosetta: `, `Codex Rosetta blocked: `, or `Upstream: ` owner label without changing source status/code ownership | The earlier `202607250101` run remains valid evidence for direct-header/native-compaction behavior. New parser/auth/ingress/error-origin coverage is deterministic; no new real call was authorized |
| `CP-02 — Responses transparent handling` | Changed | Generic configured-token scanning and `ProviderCredentialOutputGate` remain absent from model documents and streams. Current Responses/Chat/Anthropic/Google response-auth field inventory is empty; ordinary successful response token strings pass unchanged. Upstream HTTP and SSE error envelopes retain codes/non-message fields while exact message leaves receive `Upstream: `; raw safe SSE remains byte-identical | The new error-origin and passthrough coverage is deterministic; no new live external run was performed |
| `CP-03 — Codex Search and Images endpoints` | Changed | `web.run` command/field/description projection is catalog-owned; obsolete `image_generation` suppression removed; `image_gen.imagegen` contract unchanged. Auxiliary credential streaming uses bounded decoded/wire rolling windows for ordinary fields and full retention only for unfinished embedded JSON; no fragment-count capacity remains. Auxiliary Provider errors are labeled `Upstream: `, while credential-return and SSRF policy failures are labeled `Codex Rosetta blocked: ` | Post-migration search passed for DeepSeek 3/3 and Terra 2/3 with Sol fallback for task 01. Qwen selected the exact image tool, but the configured Images route returned `404 model_not_found` for `gpt-image-2`. Current Search/Images production routes are non-streaming, so the new error-origin behavior has deterministic coverage only and no new real call was authorized |
| `CP-04 — Request and window identity` | Possibly unchanged | Metadata keys unchanged | Pending multi-turn wire capture |
| `CP-05 — Responses→Chat bridge` | Changed | `InputAudio` bridge and reasoning-summary `summary_index` reconstruction remain; obsolete cross-gate credential assertions were replaced by ordinary-text passthrough coverage across Chat/Anthropic/Google | Prior live bridge evidence remains unchanged; audio is pending |
| `CP-06 — Responses Lite / additional_tools` | Possibly unchanged | Field set unchanged | Pending Lite/deferred cell |
| `CP-07 — Codex model catalog` | Changed | Formal asset synchronized; catalog tests pass | Local-mode smoke passed |
| `CP-08 — custom/freeform tool` | Changed | Code Mode audio/description change; projection tests pass | Terra/DeepSeek `exec` yield and top-level wait passed; direct image and Goal paths exercised; current GUI Browser custom-`exec` reconstruction passed; MiMo recognition failed |
| `CP-09 — Code tool localization` | Changed | Schema-v6 catalog now owns localized definitions, `send_line`, modality/detail policy, description variants, and adapter bindings; focused and full Gateway suites pass | Post-migration command and built-in cells exercised direct and converted adapters. Strict model failures remain separate; no trace showed session or argument corruption by Rosetta |
| `CP-10 — Tool history consistency` | Possibly unchanged | Item names unchanged; full suite pass | Pending replay cell |
| `CP-11 — Deferred tool discovery` | Changed | Added catalog-owned dependency graph and native `tool_search` Chat projection with non-streaming, streaming, history, conflict, malformed, and converter restoration tests | Post-migration CLI deferred suite passed 14/14 core cells. Converted requests retained one stable 29-tool surface and restored discovered calls through the paired search/read/invoke path |
| `CP-12 — Codex tool usage tips` | Changed | Static guidance now includes `audio()` | Pending |
| `CP-13 — Skill delivery surfaces` | Possibly unchanged | Fixture contracts pass | Local/namespace suites passed. Post-migration Terra completed the exact orchestrator contract; DeepSeek completed exact list/read but failed exact final formatting, while Kimi fallback passed the converted path |
| `CP-14 — Live-agent runtime authentication` | Possibly unchanged | Contract tests pass | Twenty-eight valid formal command/builtin cells used Conda/local-mode dual auth; the new Qwen and Sol cells reached the configured isolated Gateway |
| `CP-15 — Web search bridge` | Possibly unchanged | Search fields unchanged | Pending sidecar matrix |
| `CP-16 — Self-hosted Bing search` | Possibly unchanged | No relevant formal diff | Pending sidecar gate |
| `CP-17 — Stream lifecycle` | Changed | Model stream lifecycle no longer owns credential fragment/identity state. Deferred trace capacity remains diagnostic-only. Raw and converted upstream `response.failed` messages are labeled; `response.incomplete` becomes a labeled failed event; protocol, network, safety, and local failures after HTTP 200 emit one source-protocol terminal error event instead of leaving Codex an unlabeled EOF. Client cancellation emits none | Deterministic raw/converted SSE, arbitrary chunking, terminal classification, and telemetry coverage pass. More than 4096 ordinary model and auxiliary deltas still complete. No new live interruption run was authorized |
| `CP-18 — Message phase` | Possibly unchanged | Phase variants unchanged | Kimi polling and stdin continuations plus builtin wait/plan/Goal paths reached terminal answers; broader tool/terminal cells pending |
| `CP-19 — Reasoning` | Changed | Reconstructed summary deltas now include Codex-required `summary_index`; saved-response replay and cross-module gate tests pass | DeepSeek reasoning/tool round completed; broader summary/audio capture pending |
| `CP-20 — Context compaction resilience` | Changed | Remote V2 body contract is unchanged, but direct header transport now preserves `x-codex-beta-features` across rebuilt/tool-adapted CLI requests while retaining raw-wire attestation behavior. Focused compaction/header suite passes | Post-migration protocol, exactly-once, attested manual, both model-switch directions, and the fresh Terra native trigger/install/replay path passed. Summary quality remains `not_scored` only because baseline tokens exceeded the suite threshold |
| `CP-21 — GPT relay provider identity` | Changed | Direct Responses removes inbound `Authorization` only and overlays Provider auth last with case-insensitive replacement. Other credential-shaped end-to-end headers are outside the confirmed Codex auth location; conversion routes remain explicit/minimal | GPT relay C0/C1/C2/C3/C5 and the Pixel Plus Terra run remain prior evidence. C4 remains a separate harness mismatch |
| `CP-22 — Model-group tool profiles` | Changed | Added `state_api_types`, immutable schema-v6 compilation, and per-request `ToolRuntimePlan`; strict Responses Pass through bypass remains covered | Post-migration direct and converted CLI cells exercised the compiled profiles. Exact 0.145.0 GUI evidence remains unavailable |
| `CP-23 — Static tool catalog` | Changed | Formal catalog upgraded from 53 conceptual rows to 57 schema-v6 owned entries, including native `tool_search` and three Rosetta injections; startup and ownership tests pass | Post-migration deferred 14/14, command/built-in, namespace, collaboration, search, and compaction cells exercised the catalog. Exact `0.145.0` GUI Browser behavior remains unverified because the installed GUI is `0.146.0-alpha.3.1` |

## Tool ownership migration implementation evidence

On 2026-07-24 the 0.145.0 adaptation moved model-visible tool ownership into
Catalog schema v6 and introduced immutable per-request `ToolRuntimePlan`
evaluation. `proxy.py`, Code Mode projection, localization, and `web.run`
capability code now consume catalog adapter/delivery data instead of owning
definitions or tool-name suppression. Native `tool_search` Passthrough can be
projected onto Chat only from an actually present client-executed declaration
and restored to `tool_search_call`/`tool_search_output`; malformed or orphaned
history fails closed. The special Responses Pass through option still bypasses
the plan completely.

Focused contract/bridge/trace coverage passed `81/81`; dedicated streaming and
non-streaming `tool_search` restoration tests passed `2/2`; the current
Gateway suite passed `1496/1496` with two pre-existing SQLite ResourceWarnings.
The current non-integration suite passed `3784 passed, 4 skipped`; `make lint`,
`make build`, `make check-codex-compat`, WebUI checks/build, and the focused
post-migration runner contracts also passed. Post-migration agentabi passed
3/3 and the live CLI evidence is recorded in `live-evidence.md`. Package
version remains `0.144.0.r0` until the remaining mandatory live gates finish.

The remainder of this file is the retained alpha.23 live inventory and is
historical evidence for the predecessor review. Its identities and results do
not constitute formal 0.145.0 live evidence; formal reruns must be appended to
`reports/live-evidence.md` under a separate 0.145.0 heading.

# Codex 0.145.0-alpha.23 Upgrade Review (historical)

## Decision

- Review mode: **full inventory review, source-first**.
- Rosetta's source adaptation and deterministic checks are complete.
- Codex 0.145.0-alpha.23 compatibility is **not approved**: two runnable
  live-agent cells failed, one compaction cell failed, and several mandatory
  gates could not run with the supplied configuration/environment.
- The package remains `0.144.0.r0`. No release, commit, or source-compatibility
  claim was made.
- `codex-source-contract.json` is refreshed to the reviewed target source so
  future drift is detectable. This records the implemented source contract; it
  is not an adoption approval.

The prior `0.142.0` through `0.144.6` report was documentation-only. This work
repeated the complete inventory, compared Codex and Rosetta source directly,
implemented the gaps, and then exercised the exact target binary. Developer
documentation was used as an index, not as proof.

## Inspection identities

| Identity | Value |
| --- | --- |
| Inspection date | 2026-07-18 |
| Installed Codex CLI (not used as target evidence) | `codex-cli 0.144.6` |
| Target source tag | `rust-v0.145.0-alpha.23` |
| Target source commit | `655224ffae098a85efeddf8289171ff3bd2624d1` |
| Target debug binary | `../openai-codex-src/codex-rs/target/debug/codex`, reporting `codex-cli 0.145.0-alpha.23` |
| Range baseline | `rust-v0.142.0`, `3a76f3ac68c8949d1cac6ea769b6ec7b8953a415` |
| Previous source | `rust-v0.144.6`, `5d1fbf26c43abc65a203928b2e31561cb039e06d` |
| Rosetta starting commit | `5dd45e7e60f8b5dacea321002b0a55a85b01bf17` plus the uncommitted adaptation |
| Latest catalog compatibility repair | `4ff126e8a1717d0ce4c49f02c53d59c71d34c733` |
| Rosetta package version | `0.144.0.r0` |

The target checkout was clean and detached at the exact tag. The source
manifest, target binary, installed CLI, and Rosetta package version were kept as
separate identities.

## Inventory and reverse-map method

1. Read the centralized ledger, source map, upgrade checklist, prior reports,
   and paired English/Chinese references.
2. Used CodeGraph before local source inspection, then followed Rosetta request,
   response, stream, tool, search, catalog, and session owners.
3. Compared the complete Codex source ranges. The `0.142.0..0.144.6` range
   contains 1,420 changed files; `0.144.6..0.145.0-alpha.23` contains 1,204.
   These are scope checks, not compatibility-point counts.
4. Compared the target `models-manager/models.json`, protocol structs, API
   endpoints, Code Mode descriptions, tool specs, SSE usage, compaction, skills,
   and runtime/auth paths against their Rosetta owners.
5. Scanned outside `docs/dev/version-compatibility/`. No second authoritative
   upgrade procedure or compatibility ledger remains. Outside pages are
   user-facing references, module READMEs, or historical work records.

## Implemented adaptation

| Boundary | Source-derived change |
| --- | --- |
| Model contracts | Adopted default-true `supports_reasoning_summary_parameter`, added permissions and auto-review contract extraction, and refreshed eight-entry official catalog values. Local-mode output also retains the legacy `supports_reasoning_summaries` alias so installed 0.144.x clients can parse the catalog. |
| Response IDs | Prevented empty `msg_`/`fc_` identifiers and kept one valid stable ID across streaming events and replay. |
| Usage | Preserved alpha.23 `cache_write_input_tokens` through non-streaming and streaming IR conversion as cache-creation usage, including reverse conversion. |
| Search | Preserved omitted versus explicit-empty `results` and supported structured `text_result` payloads without narrowing unknown JSON. |
| Code Mode | Accounted for deferred-only MCP declarations when rendering Shared MCP Types; refreshed the reviewed 53-item static tool catalog binding to the exact target commit. |
| Tool localization | Corrected model-facing deferred names to hyphenated names while retaining native dotted names. |
| Documentation | Centralized alpha.23 ownership/evidence, fixed the Kimi K3 preset gap, and updated matching English/Chinese model and compatibility references. |
| Release validation | Added prerelease-plus-`rN` validation, including the PEP 440 normalization `0.145.0a23.post0`. |

## Deterministic gates

| Check | Result |
| --- | --- |
| Targeted converter/gateway/source-contract tests | 246 passed; the subsequent stream/tool-focused rerun passed 165 tests |
| `conda run -n llm-rosetta make test` | **3422 passed, 5 skipped**, 11 warnings |
| `conda run -n llm-rosetta make lint` | Passed Ruff check/format, ty, and complexipy |
| `python -m build` in `llm-rosetta` | Passed; built `codex_rosetta-0.144.0.post0` wheel and sdist |
| `make build` wrapper | Interrupted during its broad pre-clean because preserved live-run roots made `find .` traverse for minutes; the actual build command passed |
| `make check-codex-compat` | Passed against the exact target: 22 high-confidence unchanged, 11 possibly unchanged, 0 changed |
| `make check-release-version RELEASE_TAG=v0.144.0.r0` | Passed for the unchanged package version; prerelease target syntax is covered by unit tests |
| Official model catalog comparison | Byte-identical to target `models-manager/models.json` |
| Static tool catalog checks | 53 reviewed items, exact alpha.23 tag/commit binding, tests passed |
| EN/ZH relative-path parity | Passed: 0 English-only and 0 Chinese-only paths |
| Markdown/link and whitespace checks | Passed; the literal `tools[entry.name](...)` prose is not a Markdown link |

The direct `make test` attempt outside the configured Conda environment could
not find `pytest`; the required environment run above is the authoritative
result.

## Live-agent execution

All runnable cells used the exact alpha.23 binary, local Gateway mode, an
isolated copy of `~/.config/codex-rosetta-gateway` with only the port changed,
its configured keys, and `/Users/ibobby/.codex-multi-2/auth.json`. GPT cells used
`gpt-5.6-terra`, non-multimodal third-party cells used
`deepseek-v4-flash`, and multimodal cells used `mimo-v2.5`.

The per-attempt route, thread, marker, evaluation, and per-request cache usage
are in [live-evidence.md](live-evidence.md).

The 2026-07-19 new-key retest is recorded in the appendix. DeepSeek task 03
failed again, while Terra task 03 passed. The raw Chat arguments show that
DeepSeek generated a literal backslash-plus-`n` and restarted the process;
Rosetta preserved that value. Terra generated a JavaScript newline escape and
continued the original session successfully. This is a model-facing
tool-argument reliability failure, not a Rosetta serialization failure.

The first additional `deepseek-v4-pro` retest failed: it received
`INPUT:VALUE` but restarted the command three times without any `write_stdin`
call. A later retest after the Chat Default continuation example succeeded: it
issued one `exec_command`, reused the same session with one `write_stdin`, and
sent the required newline, returning `RESULT:INPUT_OK`. This confirms the
original issue was model-facing prompt/tool-use behavior rather than a
Rosetta session or converter defect. A fresh `202607241636` strict rerun after
the appended `write_stdin.chars` guidance was reduced to one final `send_line`
sentence also succeeded. DeepSeek Pro used one command start and one same-session
raw `write_stdin` with a real newline; it did not select the synthetic facade.
The result therefore proves that removing the redundant examples did not
regress task 03, while the earlier focused Flash run remains the live evidence
for `send_line` reconstruction itself. The additional MiMo
retest reached the Images endpoint with the refreshed key, but the endpoint
still did not expose `gpt-image-2`.

The `glm-5.2` control was rerun after adding Chat default profile guidance to
both `exec_command` and `write_stdin`. The upstream request still exposed both
as independent Chat functions. GLM kept one process session and called
`write_stdin`, but its raw function arguments contained an over-escaped
`chars: "rosetta\\\\n"`; Rosetta preserved that exact value, so the process
remained blocked waiting for a newline. This confirms that `write_stdin` is
expanded outside `exec` for Chat upstreams and that the remaining failure is
model-side JSON escaping rather than Rosetta session or serialization loss.
Adding an explicit `exec_command` → `write_stdin` example to the profile was
also tested; it improved the documented sequence but did not change GLM's
over-escaping behavior.

### Ordinary suites

| Suite | Result |
| --- | --- |
| Command execution | 7/8 original final cells passed. Terra task 03 passed in the 2026-07-19 new-key retest. DeepSeek-v4-pro first failed but passed after the Chat Default continuation example; GLM task 03 still fails on over-escaped newline arguments. The remaining GLM failure is model-facing, not a Rosetta conversion failure. |
| Deferred discovery | 14/14 passed across Terra and DeepSeek. |
| Built-in tools | 11/11 passed: Terra 5, DeepSeek 4, MiMo view transport and visual recognition 2. |
| Local skills and namespace tools | 4/4 passed; native dotted and model-facing hyphenated names were both observed. |
| Subagent tools | 12/12 passed across Terra and DeepSeek. |
| Runnable network search | 6/6 final cells passed for tasks 01, 02, and 05 across both text models. Terra task 01 needed one retry after an upstream 429. |
| Image generation | Failed. MiMo discovered the correct image tool and reached the Images endpoint with both tested keys; the endpoint returned `404 model_not_found` for Codex's alpha.23 `gpt-image-2`, and the new-key retest made no capability difference. |

This is 54 passing and 2 failing final cells among 56 runnable ordinary cells.
Network tasks 03/04 were not runnable because the supplied configuration has no
`server.web_run.base_url`/token sidecar. The configuration was not expanded
beyond the user's boundary.

Browser/Computer Use was not executed in the historical alpha.23 matrix: its
maintained suite required a fresh GUI main-executor task plus a separate judge,
which could not be validly created inside that task. The later 2026-07-24 GUI
run recorded above supplies successful Rosetta-path evidence with limitations,
but its GUI reports `0.146.0-alpha.3.1` and therefore does not retroactively
prove alpha.23 or formal `0.145.0` GUI behavior. Orchestrator-skill cells were
`runner_not_supported` because that runner did not create a no-local-executor
app-server thread or supply the required `codex_apps` MCP resource backend.
In that historical alpha.23 matrix, formal `agentabi` was not run because no
`agentabi` Conda environment or importable package existed. This limitation no
longer applies to the formal post-migration run: an isolated Conda 3.14.6
environment ran the 3/3 matrix recorded above.

### Compaction suites

| Cell | Result |
| --- | --- |
| DeepSeek protocol-only context-limit task 01 | `completed_with_deviations`: three complete Remote V2 chains passed; the model also started the command three times, which is recorded outside the protocol score. |
| DeepSeek exactly-once context-limit task 05 | Completed with one command start, one Remote V2 compaction, one installed follow-up, and one Rosetta mapping. |
| Terra official context-limit task 02 | Failed official evaluation: compact/resume markers passed, but raw-wire passthrough was false. |
| Terra manual app-server task 02 | Completed with one user-requested compaction, raw-wire passthrough, installed follow-up, and one native profile mapping. |
| Terra manual task 02 after catalog repair | `202607191446` passed with installed `codex-cli 0.144.6`; `202607191451` passed with target `codex-cli 0.145.0-alpha.23`; both used `Pixel (Plus)` and `wire_passthrough=true`. |
| Terra→DeepSeek task 03 | Completed; one changed compaction hash and one mapping on the same thread. |
| DeepSeek→Terra task 04 | Completed with the same invariants. |
| Terra and DeepSeek summary-quality cells | `not_scored`: their baseline contexts (15,270 and 17,423 tokens) exceeded the suite's 15,000-token precondition. Diagnostic output is retained but is not a pass/fail quality claim. |

Thus the scored/executable compaction evidence is five completed (including
one protocol result with model deviations) and one failed cell, plus two
explicitly unscored quality cells.

### Cache-continuation evidence

The original matrix appendix records 227 upstream requests and 154 adjacent
non-first deltas; the three follow-up cells add 18 source requests without
being folded into a new combined cache aggregate. No aggregate hit rate is claimed.
Sixty-one original deltas were within ±200 tokens.
Larger deltas were inspected and attributed to uncached conversation suffixes,
backend block alignment, subagent instruction changes, deliberate model/profile
switches, or three backend misses. Eight requests omitted usage: one 429, four
failed/timeout command requests, and three completed Terra subagent requests.
They remain missing rather than being synthesized as zero.

## Compatibility-point disposition

| ID and compatibility point | Classification | Source code/contract evidence and implemented disposition | Automation results | Real API results |
| --- | --- | --- | --- | --- |
| `CP-01 — Agent-facing API` | Changed | Audited alpha routes and kept Realtime explicitly outside Rosetta; refreshed endpoint/private-struct extraction. | Contract and full suite passed. | Direct and cross-format routes passed; Realtime remains unsupported. |
| `CP-02 — Responses transparent handling` | Changed | Audited include/session/reasoning and preserved new opaque fields on transparent paths. | Passthrough/contract tests passed. | Ordinary Responses passed; official compaction raw-wire cell failed, manual raw-wire cell passed. |
| `CP-03 — Codex Search and Images endpoints` | Changed | Added optional opaque `results`/`text_result` handling and reviewed image tool contract. | Search and image exposure tests passed. | Search runnable cells passed; Images endpoint rejected `gpt-image-2`; sidecar tasks unavailable. |
| `CP-04 — Request and window identity` | Changed | Extracted prompt-cache/session ownership and retained runtime identity headers. | Identity and full tests passed. | Isolated auth/session traces passed across runnable suites. |
| `CP-05 — Responses→Chat bridge` | Changed | Added valid stable message/function IDs and cache-write mapping. | Converter/stream tests passed. | DeepSeek bridge broadly passed; Flash task 03 failed in the original matrix and follow-up, and Pro failed the additional control retest. |
| `CP-06 — Responses Lite / additional_tools` | Changed | Extractor now understands renamed capability and typed item IDs; multi-round Lite bridge retained. | Source-contract and deferred tests passed. | Deferred discovery passed 14/14. |
| `CP-07 — Codex model catalog` | Changed | Official alpha.23 fields use `supports_reasoning_summary_parameter`; local-mode projection adds legacy `supports_reasoning_summaries` for 0.144.x parser compatibility and derives it from the current capability. | Catalog/preset/local-mode tests passed, including the legacy alias regression. | `202607191446` (0.144.6) and `202607191451` (alpha.23) both resolved Terra through `Pixel (Plus)` and completed native compaction. |
| `CP-08 — custom/freeform tool` | Changed | Rebased exec/apply-patch/freeform and image constraints on target source. | Tool projection and converter tests passed. | Command/builtin/deferred suites passed except DeepSeek stdin task. |
| `CP-09 — Code tool localization` | Changed | Corrected model-facing hyphenated names and native dotted names. | Catalog/namespace tests passed. | Namespace cells observed both forms and passed. |
| `CP-10 — Tool history consistency` | Changed | Valid/stable response IDs and replay paths tested. | ID/history/stream tests passed. | Multi-round ordinary history passed; the split DeepSeek protocol task records three model repeats as deviations while the exactly-once control passed. |
| `CP-11 — Deferred tool discovery` | Changed | Shared MCP Types now include deferred-only MCP declarations with exact authorization. | Projection tests passed. | 14/14 deferred cells passed. |
| `CP-12 — Codex tool usage tips` | Changed | Refreshed reviewed static descriptions and target binding. | 53-item catalog tests passed. | Built-in tool suites passed. |
| `CP-13 — Skill delivery surfaces` | Changed | Local skill boundary retained; orchestrator remains provider-owned. | Fixture/full tests passed. | Local skill 2/2 passed; formal orchestrator runs for DeepSeek and Sol completed the native `skills.list → skills.read` sequence with exact resource handles. |
| `CP-14 — Live-agent runtime authentication` | Possibly unchanged | Kept OAuth and Gateway-key responsibilities separate. | Runtime-auth artifact validation passed for executed cells. | Runnable cells used both required auth sources; no auth mismatch found. |
| `CP-15 — Web search bridge` | Changed | Preserved opaque search results and reviewed native header forwarding. | Search tests passed. | Tasks 01/02/05 passed for both text models; tasks 03/04 lacked the configured sidecar. |
| `CP-16 — Self-hosted Bing search` | Possibly unchanged | Local executor remains separate, but its alpha result envelope is covered. | Bing/search unit coverage passed in full suite. | No sidecar/Bing live backend in supplied config; unresolved. |
| `CP-17 — Stream lifecycle` | Changed | Added cache-write usage in streaming and stable IDs across events. | Stream-focused rerun and full suite passed. | Runnable streaming cells terminated correctly; eight upstream events omitted usage as documented. |
| `CP-18 — Message phase` | Possibly unchanged | Phase ownership remains client-side; new protocol fields were inventoried. | Phase/tool tests passed. | Subagent and ordinary phase behavior passed; fresh GUI Browser phase was not validly runnable. |
| `CP-19 — Reasoning` | Changed | Adopted default-true summary parameter and preserved reasoning/include behavior. | Contract, preset, converter tests passed. | Reasoning-capable ordinary continuations passed; no separate formal C-matrix was run. |
| `CP-20 — Context compaction resilience` | Changed | Extracted retry/output-ID/cache-write changes and added stream/nonstream mappings. | Compaction contracts and full suite passed. | Five completed, one failed, two not scored; split DeepSeek protocol and exactly-once cells passed, while Terra raw-wire remains a CLI-attestation test-design mismatch. |
| `CP-21 — GPT relay provider identity` | Changed | Audited provider/session/route identity and retained explicit profile selection. | Identity/profile tests passed. | Formal C0/C1/C2/C3/C5 relay cells passed. C4 failed before Gateway invocation because the 0.145 harness sent `messages` instead of `compaction_trigger`; no Rosetta relay defect was observed. |
| `CP-22 — Model-group tool profiles` | Changed | Added permissions/auto-review fields and reviewed third-party profile differences. | Preset/local-mode/tool tests passed. | Terra, DeepSeek, and MiMo selected expected routes/tools; image profile backend failed. |
| `CP-23 — Static tool catalog` | Changed | Refreshed 53 entries and metadata to the formal `rust-v0.145.0` tag/commit. | Catalog equality, local-mode projection, and compatibility tests passed. | Deferred discovery passed 14/14; built-in, namespace, local-skill, subagent, and orchestrator surfaces were exercised. Only exact `0.145.0` GUI Browser behavior remains unverified; the available GUI is `0.146.0-alpha.3.1`. |

## Rosetta Improvements From Model-Facing Failures

These changes improve model-facing usability; they do not reclassify the
underlying model-tool-use failures as confirmed converter defects. Explicit
facades must remain separate from raw native tools and must never silently
rewrite a model-generated call.

1. **Structured presentation of `exec` session handles.** DeepSeek task 02
   received a valid `exec_command` result but failed to find the nested session
   identifier in the ordinary `input_text[]` wrapper and started a second
   command. Rosetta could offer an opt-in Chat result shape with a concise,
   machine-readable leading summary such as `session_id` and `is_running`,
   while retaining the original result text unchanged for history and replay.
   This improves result discoverability without changing the native Codex
   result contract by default.

2. **Implemented: explicit `send_line` facade.** DeepSeek/GLM task 03 failures
   involved model-generated literal `rosetta\\n` or a missing newline, while
   Rosetta faithfully preserved the received `write_stdin.chars`. Rosetta now
   exposes `send_line(session_id, line)` whenever native `write_stdin` is
   available and reconstructs the native call with exactly one real newline;
   raw `write_stdin` remains unchanged. Unit coverage verifies both top-level
   Chat localization and nested Code Mode projection. In focused DeepSeek run
   `202607241615`, the model eventually selected the facade and received
   `RESULT:INPUT_OK`; trace evidence shows the generated native call contained
   `chars: "rosetta\n"`. The strict task remains failed because the model had
   already restarted the scenario multiple times. After that run, the appended
   `write_stdin.chars` guidance was reduced to one final sentence directing
   line-oriented input to `send_line`; the redundant newline and escaping
   examples were removed. Strict DeepSeek Pro control run `202607241636` then
   passed with exactly one start and one same-session write. It chose raw
   `write_stdin`, so this control verifies the simplified description does not
   regress the native continuation path but does not add facade coverage. The
   appended `exec_command` guidance was subsequently reduced to parameter and
   responsibility rules only: reuse `session_id`, use `write_stdin` for
   polling/raw or complex interaction, use `send_line` for simple single-line
   input, and keep boolean parameters unquoted. Command and newline-escaping
   examples were removed. This final wording has deterministic projection
   coverage; run `202607241636` predates that last description-only revision.

3. **Implemented: focused precedence guidance for file mutation.** DeepSeek
   and Kimi selected Shell/Python through `exec_command` even though localized
   file tools were exposed. Only the `Edit` and `Write` descriptions now state
   that modifying or creating files must prefer those tools over Shell or
   Python. `Glob`, `Grep`, and `Read` descriptions are unchanged, and Shell is
   not hidden from the default profile.

4. **Implemented: `view_image` is eager-only.** MiMo received image data but
   discarded the first `view_image` result, converted a later result to JSON
   text, and then attempted unsupported byte parsing. Rosetta now excludes
   `view_image` from deferred `ALL_TOOLS` search/read discovery while retaining
   the eager, route-capability-gated image tool. Other deferred MCP tools remain
   available. Unit coverage verifies that search omits the duplicate and an
   attempted deferred read fails closed with `eager_only_tool`.

Focused validation passes `121/121` tests across `test_tool_adaptation.py` and
`test_code_mode_projection.py`; repository lint, format, type, and complexity
gates pass. The broader Gateway suite reached `1482 passed / 3 failed`; all
three failures are older stream-trace assertions that still expect
`stream_start` to precede the newly automatic `original_request` record, not
failures in the tool changes above.

## Adoption blockers

1. DeepSeek-v4-flash and the first DeepSeek-v4-pro cells failed the stdin/session
   continuation contract; the latest DeepSeek-v4-pro cell passed after the
   Chat Default prompt/example revision. Keep the successful replay as the
   current compatibility evidence and continue monitoring model variance.
2. The Images endpoint must expose Codex alpha.23's `gpt-image-2`, or the
   deployment must provide an explicitly compatible image-model mapping.
3. Terra's official raw-wire result is a CLI-runner/attestation gate mismatch.
   The DeepSeek protocol and exactly-once scopes are now split and both passed;
   run the Terra raw-wire gate via app-server or condition it on attestation
   before treating the remaining result as a Rosetta defect.
4. Summary-quality fixtures need a valid below-15k baseline before they can be
   scored.
5. In the historical alpha.23 environment, network sidecar/Bing and agentabi
   were unavailable. Formal 0.145.0 agentabi has since passed 3/3. Browser plus
   judge has completed for the Rosetta path on GUI `0.146.0-alpha.3.1`, and the
   formal orchestrator Skill and CP-21 C0/C1/C2/C3/C5 gates completed before
   the ownership refactor; exact `0.145.0` GUI Browser behavior remains
   unverified.
6. After those gates pass, update the package to the approved alpha.23 `r0`
   version and rerun release validation. Until then, `0.144.0.r0` remains the
   only package claim.
