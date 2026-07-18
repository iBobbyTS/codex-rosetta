# Codex Documentation Coverage Review
Date: 2026-07-18
Codex version: 0.144.0

## Decision

- Review mode: **full inventory review, documentation coverage only**.
- Documentation coverage: **complete after the corrections recorded below**.
- Codex `0.144.6` runtime compatibility: **not approved**.
- Runtime adaptation, package-version change, source-contract baseline refresh,
  and real Codex/API tests: **not performed in this review**.

The purpose of this review is to make the maintained documents sufficient for
a future developer-selected routine release review. It does not adopt
`0.144.6`.

## Inspection identities

| Identity | Value |
| --- | --- |
| Inspection date | `2026-07-18` |
| Local Codex CLI | `codex-cli 0.144.6` |
| Codex source before inspection | detached `rust-v0.145.0-alpha.18`, commit `f84f9a6406cc55b210395f71b4c6aed236fc7ebb`, `2026-07-16T09:58:29-07:00` |
| Target Codex source | detached `rust-v0.144.6`, commit `5d1fbf26c43abc65a203928b2e31561cb039e06d`, `2026-07-18T09:05:05-04:00` |
| Source update method | exact-tag detach after fetch; prior and target commits are divergent release snapshots, so no fast-forward claim is made |
| Codex-Rosetta package version | `0.144.0.r0` |
| Codex-Rosetta review commit | `d2770c7aefcabc191e4416fa6b4ea0128bea106a` plus this documentation-only worktree |

The source checkout was clean before and after the exact-tag switch. Patch tags
in this range can be backport snapshots rather than a single ancestor chain;
the review therefore compares release snapshots, not only commit ancestry.

## Release snapshot inventory

`0.142.0` is assessed against `rust-v0.141.0`
(`3fb81667d30d9d24297216ea61fbfcc4351b2aa9`). Later rows use the immediately
preceding release snapshot.

| Release | Peeled source commit | Changed `codex-rs` paths | Non-package paths |
| --- | --- | ---: | ---: |
| `0.142.0` | `3a76f3ac68c8949d1cac6ea769b6ec7b8953a415` | 882 | 867 |
| `0.142.1` | `95da8fd25193fd58d1c5984eee20d1ef7bd50e77` | 7 | 4 |
| `0.142.2` | `390b0d254d658148751d0cca50ca41832c7894a1` | 217 | 214 |
| `0.142.3` | `e2b60462a7321517895dd94920661599303a7539` | 4 | 3 |
| `0.142.4` | `d0fd96663e19a6cd5d6f315e3420c4d154562013` | 7 | 6 |
| `0.142.5` | `26de83050b20f7e0ee211b9739e52ae00ce8032a` | 2 | 1 |
| `0.143.0` | `c4d748f586a84a3ed5b6aceb82e9a1db4abb1cda` | 1,083 | 1,042 |
| `0.144.0` | `767822446c7a594caa19609ca435281a9ec67e0d` | 486 | 469 |
| `0.144.1` | `44918ea10c0f99151c6710411b4322c2f5c96bea` | 6 | 5 |
| `0.144.2` | `a6645b6b8a656360fa16fb7e1c6721d0697d3d6a` | 9 | 8 |
| `0.144.3` | `78ad6e6bfd1d3b6a209acd3ef82172a96b25179c` | 28 | 27 |
| `0.144.4` | `8c68d4c87dc54d38861f5114e920c3de2efa5876` | 10 | 9 |
| `0.144.5` | `87db9bc18ba5bc82c1cb4e4381b44f693ee35623` | 6 | 5 |
| `0.144.6` | `5d1fbf26c43abc65a203928b2e31561cb039e06d` | 2 | 1 |

The last column excludes Cargo and package manifests only. It is a diff-scope
sanity check, not a count of compatibility changes; every remaining path was
classified through the source anchors and Rosetta ownership boundaries.

## Method

1. Read the compatibility ledger, checklist, prior `0.144.0`, `0.144.1`, and
   `0.144.4` reports, and every version-specific document found outside the
   authoritative directory.
2. Used current Rosetta code and deterministic tests as implementation facts.
   CodeGraph supplied ownership/call-path entry points; a targeted signal scan
   then checked headers, Responses items/events, tools, catalog, compaction,
   reasoning, phase, authentication, search, Images, and live-agent fixtures.
3. Built the exhaustive owner index in `../rosetta-source-map.md` and reconciled
   it with the compatibility overview and test matrix.
4. Compared every release snapshot and release message from `0.142.0` through
   `0.144.6`, mapping Codex-facing changes to stable `CP-*` points.
5. Ran `make check-codex-compat` against exact `0.144.6` and separately compared
   complete bundled model values, because the current extractor does not cover
   them.

## Documentation defects found and corrected

### Ledger integrity

The former overview and test matrix were not the same list:

- `Skill delivery surfaces` existed only in the test matrix;
- `Self-hosted Bing search` existed only in the overview;
- the deferred-tool point used two different names.

The ledger now has 23 stable IDs (`CP-01` through `CP-23`), and both tables
contain the same canonical names exactly once. `CP-13` now records the distinct
filesystem and orchestrator Skill contracts; the missing Bing real-test row is
also present.

### Rosetta owner omissions

The prior overview described most behaviors correctly but did not provide a
reliable reverse index to all implementation owners. The new source map records
the missing or previously implicit owners, including:

- `gateway/codex_compact_prompt.md` and
  `gateway/codex_compact_summary_prefix.md`;
- `reasoning_mapping.py`, `pipeline.py`, and provider reasoning transforms;
- `capabilities.py` and preset-driven reasoning/vision enforcement;
- `gateway/auth.py`, `providers.py`, and principal/session identity owners;
- `web_run_health.py`, `web_run_supervisor.py`, and the readiness path that
  changes the model-visible `web.run` declaration;
- tool-history persistence/crypto and the corresponding deterministic tests;
- client-only Skill fixtures, which have no Rosetta runtime converter.

No additional top-level runtime compatibility point was required after these
owners were mapped. The missing Skill point and missing Bing test row were
documentation-structure gaps, not new runtime adaptations. Legacy launchers,
session-log diagnostics, and generic provider-SDK schema extractors were
classified explicitly as non-owners because they observe or start runs without
defining a Codex-facing runtime contract.

### Scattered version material

Version-specific research under `docs/dev/sdk_ir/`, Codex compatibility debug
records under `.agent-work/`, and the detailed version-bound real-agent result
formerly duplicated under `docs/en/` and `docs/zh-cn/` were moved to
`../evidence/`. A Python-version-specific Tavily cancellation note remains in
`.agent-work/` because it does not define a Codex contract. The two user pages
now contain only language-matched pointers, while
the live-agent suite definition links to the central evidence instead of owning
a second version baseline. Duplicate upgrade procedure text was removed from
the English and Chinese model-catalog field reference, and the repository agent
instructions now retain only centralized entry points and high-level mandatory
gates. The following remain outside this directory intentionally:

- English and Chinese user-facing model-catalog field references;
- English and Chinese user-facing tool-exposure references;
- the general live-agent/tool test method guide;
- the release manual.

Each now relies on or links to the authoritative compatibility workflow rather
than defining a second version-upgrade procedure.

## Per-release coverage validation

| Release | Codex-facing source changes relevant to Rosetta | Points triggered/reviewed | Coverage verdict |
| --- | --- | --- | --- |
| `0.142.0` | Broad API, Responses item/event, model/provider, tool/Code Mode, plugin/Skill, search/image, identity, reasoning, compaction, and session changes; includes UUIDv7 lineage, multi-agent modes, deferred discovery, indexed search, and Clock/Goal/request-user-input surfaces | `CP-01`–`CP-23` | Covered. The full review exposed and added the missing `CP-13` overview owner and `CP-16` real-test row |
| `0.142.1` | Windows system-proxy authentication behavior | `CP-14`, `CP-21` | Covered as an auth/provider-identity trigger; no Rosetta wire-shape change identified |
| `0.142.2` | Responses safety-buffering headers/events and provider error mapping; world-state and response-item `turn_id` history; compaction-trigger shape; MCP/tool-search exposure; Code Mode metadata warning; remote-image validation | `CP-01`–`CP-05`, `CP-07`, `CP-09`–`CP-13`, `CP-15`, `CP-17`, `CP-19`–`CP-23` | Covered by API/transport, identity/history, catalog/tool, search, reasoning, compaction, provider, and static-catalog points |
| `0.142.3` | Bedrock provider catalog adds GPT-5.6 Sol/Terra/Luna model IDs, context windows, and maximum reasoning support | `CP-07`, `CP-19`, `CP-21` | Covered by model catalog, reasoning, and provider-identity points |
| `0.142.4` | Multi-agent tool descriptions/delegation guidance, search-tool contract tests, and permission/auto-review prompt changes | `CP-09`, `CP-12`, `CP-15`, `CP-22`, `CP-23` | Covered by tool schema/guidance, search, profile, and static-catalog points |
| `0.142.5` | Responses WebSocket trace-payload redaction | `CP-17` | Covered by transport/limitation handling; Rosetta still does not claim Responses WebSocket support |
| `0.143.0` | Broad API/transport, Responses Lite `additional_tools`, Code Mode host/process, Namespace/custom tools, MCP/plugin/Skill world state, collaboration, `max` reasoning, image/search extensions, session/fork metadata, model catalog, and provider auth changes | `CP-01`–`CP-23` | Covered by the complete ledger |
| `0.144.0` | Broad API/transport, canonical command/dynamic/subagent/collaboration items, UUIDv7 IDs, extension-owned items, indexed-web/image behavior, runtime auth, Responses Lite/catalog, compact fallback, and Guardian/auto-review changes | `CP-01`–`CP-23` | Covered; earlier detailed evidence remains in the `0.144.0` report |
| `0.144.1` | Standalone Code Mode host availability and embedded fallback | `CP-08`, `CP-09`, `CP-23` | Covered; earlier scoped evidence remains in the `0.144.1` report |
| `0.144.2` | Guardian auto-review policy/request/tool rollback | `CP-07`, `CP-22`, `CP-23` | Covered |
| `0.144.3` | App-server thread-resume metadata, persisted model/provider/reasoning settings, and TUI reasoning selection behavior | `CP-04`, `CP-07`, `CP-19`–`CP-21` | Covered by identity, catalog, reasoning, compaction/resume, and provider-identity points |
| `0.144.4` | Guardian review/session behavior and `ModelMessages.auto_review` catalog support | `CP-07`, `CP-22`, `CP-23` | Covered; earlier detailed evidence remains in the `0.144.4` report, while this exact-tag range corrects its broader realtime-call attribution |
| `0.144.5` | Dangerous-command classification and clearer denial reasons | `CP-08`, `CP-09`, `CP-12`, `CP-17` | Covered as client-side tool-error/recovery behavior; no Rosetta request/tool wire-shape change identified |
| `0.144.6` | Sol/Terra/Luna bundled instructions and context windows | `CP-07`, `CP-11`–`CP-13`, `CP-19`, `CP-20`, `CP-22`, `CP-23` | Covered, but implementation and live-test gates remain open |

Changes such as TUI rendering, installer packaging, platform shell behavior, and
system-proxy implementation remain outside Rosetta's conversion contract unless
they alter one of the mapped auth, transport, tool-error, or capability gates.
The report records those boundary decisions instead of silently ignoring the
release notes.

Release-note labels such as "maintenance-only", "version-only", or "no
user-facing changes" were not treated as source evidence. Exact stable-tag
diffs exposed mapped compatibility changes in `0.142.3`, `0.142.4`, `0.144.3`,
and `0.144.4`; future routine reviews must perform the same source comparison.

## `0.144.6` implementation gap found by documentation validation

The target `codex-rs/models-manager/models.json` differs from Rosetta's packaged
`gateway/codex_models_0_144_4.json` in exactly three model entries and four
top-level fields per entry:

| Models | Changed fields | Packaged Rosetta value | Codex `0.144.6` value |
| --- | --- | --- | --- |
| `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna` | `context_window`, `max_context_window` | `372000` | `272000` |
| same three | `base_instructions`, `model_messages` | `0.144.4` instruction/message payloads | refreshed `0.144.6` payloads |

This is an implementation asset gap under `CP-07` and changes compaction timing
under `CP-20`. `CP-23` also remains bound to Codex CLI/source `0.144.4`. Per the
scope of this review, none of those runtime assets or bindings were changed.

The comparison also exposes an automation blind spot: full bundled model values
are still on the extractor backlog. A source-commit-only contract failure must
therefore never be interpreted as proof that the catalog values are unchanged.

## Contract-group output against exact `0.144.6`

`make check-codex-compat` failed as expected because the reviewed baseline is
still bound to the `0.144.4` source commit.

High-confidence unchanged extracted groups:

`apply_patch`, `approval_messages_fields`, `code_mode_exec_shape`,
`codex_header_constants`, `endpoints`, `model_messages_fields`,
`remote_compaction_v2`, `response_item_additional_tools_fields`,
`responses_lite_model_fields`, `responses_metadata_keys`, `sse_event_names`,
`tool_spec_web_search_fields`, `tool_spec_wire_types`, `transport_constants`,
and `websocket_client_metadata_keys`.

Possibly unchanged extracted groups:

`compaction_input_fields`, `content_item_variants`, `message_phase_variants`,
`model_enum_variants`, `model_info_fields`, `reasoning_fields`,
`response_create_ws_request_fields`, `response_event_variants`,
`response_input_item_variants`, `response_item_variants`,
`responses_api_request_fields`, and `stream_options_fields`.

Changed extracted groups:

- `codex_source_commit`: `8c68d4c87dc54d38861f5114e920c3de2efa5876`
  → `5d1fbf26c43abc65a203928b2e31561cb039e06d`.

The missing model-value signal was found only by the separate complete JSON
comparison required by the updated checklist.

## Itemized point disposition for `0.144.4` → `0.144.6`

Every point has range documentation coverage. The classification below is
source-review input for a future adoption task, not a compatibility decision.

| ID and compatibility point | Classification | Evidence and future adoption gate |
| --- | --- | --- |
| `CP-01 — Agent-facing API` | High-confidence unchanged | Patch source changes are confined to command policy and bundled model values; endpoint/request ingress anchors are unchanged |
| `CP-02 — Responses transparent handling` | High-confidence unchanged | Direct Responses and compaction transport owners are unchanged; retain passthrough fixtures when adopting |
| `CP-03 — Codex Search and Images endpoints` | High-confidence unchanged | Search, Images, and extension source anchors are unchanged |
| `CP-04 — Request and window identity` | High-confidence unchanged | Header, item-ID, session/window/turn owners are unchanged |
| `CP-05 — Responses→Chat bridge` | High-confidence unchanged | Response/Input item and converter-relevant source shapes are unchanged |
| `CP-06 — Responses Lite / additional_tools` | High-confidence unchanged | Lite capability fields and `additional_tools` extracted shape are unchanged |
| `CP-07 — Codex model catalog` | Changed | Three bundled models changed instructions/messages and both context-window values; compare and intentionally refresh packaged assets before adoption |
| `CP-08 — custom/freeform tool` | Possibly unchanged | `0.144.5` changed command-policy behavior without changing the custom tool schema; run a real rejected-command/error-recovery loop |
| `CP-09 — Code tool localization` | Possibly unchanged | Localized call wire shapes are unchanged, but clearer dangerous-command denial can change the visible recovery loop; run failed-command continuation |
| `CP-10 — Tool history consistency` | High-confidence unchanged | Item/call/output and persistence owners are unchanged |
| `CP-11 — Deferred tool discovery` | Possibly unchanged | Tool declarations are unchanged, but refreshed base instructions can alter discovery behavior; rerun the controlled deferred suite if adopting |
| `CP-12 — Codex tool usage tips` | Possibly unchanged | Refreshed base instructions and command denials can interact with Rosetta's supplemental guidance; rerun builtin tool/error cells |
| `CP-13 — Skill delivery surfaces` | Possibly unchanged | Skill code/schema owners are unchanged, but refreshed instructions can affect selection; rerun local and orchestrator Skill cells |
| `CP-14 — Live-agent runtime authentication` | High-confidence unchanged | Auth storage, provider bearer precedence, and capability-gate source anchors are unchanged |
| `CP-15 — Web search bridge` | High-confidence unchanged | Hosted/standalone search wire and executor source anchors are unchanged |
| `CP-16 — Self-hosted Bing search` | High-confidence unchanged | Codex Search shape and Rosetta Bing owners are unchanged |
| `CP-17 — Stream lifecycle` | Possibly unchanged | SSE event sets are unchanged; `0.144.5` changes a client-side rejection/error path that requires visible-error confirmation |
| `CP-18 — Message phase` | High-confidence unchanged | MessagePhase and response-event extracted sets are unchanged |
| `CP-19 — Reasoning` | Possibly unchanged | Reasoning fields are structurally unchanged, but refreshed instructions can change model behavior; run the relevant real reasoning continuation cell |
| `CP-20 — Context compaction resilience` | Changed | Context windows changed from 372k to 272k, altering threshold behavior; rerun protocol compaction cells after asset adaptation |
| `CP-21 — GPT relay provider identity` | High-confidence unchanged | Provider identity/auth and request transport anchors are unchanged |
| `CP-22 — Model-group tool profiles` | Possibly unchanged | Profile code and tool specs are unchanged, but refreshed instructions can change how the selected surface is used; rerun affected Profile cells |
| `CP-23 — Static tool catalog` | Changed | Tool inventory is source-unchanged, but the packaged catalog's exact CLI/source binding remains `0.144.4`; review and advance it only in an adoption task |

Possibly unchanged and changed rows have no real API result in this review.
That is an explicit blocker to adoption, not a waived gate.

## Checks performed

| Check | Result |
| --- | --- |
| Exact target source status | Clean detached `rust-v0.144.6` at `5d1fbf26…` |
| `make check-codex-compat` | Expected non-zero result: source commit drift only in extracted groups; full model-value gap found separately |
| `pytest tests/test_codex_source_contract.py -q` | 10 passed |
| Complete `models.json` comparison | Exactly three models/four fields differ as recorded above |
| Compatibility overview/test-matrix parity | 23 names in each, no set difference |
| Runtime unit/integration suite | Not run; no runtime code changed |
| Real Codex/API tests | Not run; documentation-coverage-only scope |

## Final disposition

The optimized documentation covers the Codex-facing changes observed from
`0.142.0` through `0.144.6` and now records the Rosetta code/test owners needed
for a routine release review. A future developer-selected routine review may
start from these documents without repeating the full repository inventory.

That workflow must still escalate for a review-mode decision when a source diff
or Rosetta owner is unmapped. Codex `0.144.6` remains unapproved until the
catalog/context/binding changes are intentionally adapted and every triggered
automated and real-client gate passes.
