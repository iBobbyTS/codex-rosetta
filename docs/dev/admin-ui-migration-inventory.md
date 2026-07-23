# Admin UI Migration Inventory

This inventory freezes the behavior that the Svelte Admin must preserve from the
former single-file SPA. Python remains the owner of every API contract and side
effect. Frontend tests use mocked Admin responses and never contact a provider.

| Capability | Authoritative Admin API or config fields | Svelte owner | Required regression evidence |
| --- | --- | --- | --- |
| Authentication and expiry | `login`, `auth-check`; every protected route may return 401/403 | `App.svelte`, `lib/api.ts` | 401 and 403 clear the token and replace the entire authenticated shell with login |
| Provider configuration | `config`, provider PUT/DELETE/toggle, `/key`, `/models`; `registered_shims`, `known_api_types` | `ProvidersPage.svelte` | URL-derived presets, backend-only API types, redirects, proxy, credential reveal and model discovery |
| Model groups and metadata | model-group PUT/DELETE; `model_presets`; `model_info` eight-field contract | `ModelsPage.svelte` | structured edit, preset detected/modified/restore, modalities/reasoning, exact round trip |
| Model discovery | provider `/models` | `ModelsPage.svelte` | filter, select all, prefix, duplicate-safe bulk insertion |
| Model tests | test POST, poll GET/POST, DELETE | `ModelTestPanel.svelte`, `lib/model-test.ts` | pending/done/error/cancel/timeout, safe usage rendering, no request until user action |
| Tool catalog | `/tools/catalog`; policies, placement, projection, visibility and localized descriptions | `ToolsPage.svelte` | real catalog types/groups, detail rendering and hidden-item behavior |
| Tool profiles | profile GET/PUT/DELETE; typed `profile_inputs` | `ToolsPage.svelte` | readonly state controls, editable inputs, namespace effective disable, exact payload |
| Request details | `/requests`, `/requests/key-labels` | `RequestLogsPage.svelte` | filters, pagination, full expanded entry rendered as text, clear confirmation |
| Error dumps | `/error-dumps`, detail, body download, DELETE | `ErrorDumpsPanel.svelte` | list/detail/body download/clear with text-only rendering |
| Metrics and profiling | `/metrics`; profiling status/enable/disable/results/index/download/DELETE | `DashboardPage.svelte` | persistence state, bounded request count, artifact detail/download/clear |
| Server and Codex settings | config server/codex/reload; restart-required response header | `SettingsPage.svelte`, `lib/api.ts` | explicit local-mode confirmation, task-model state, persistent restart notice |
| Host and internal token | diagnostics host IP, internal-token | `SettingsPage.svelte` | explicit reveal actions, no automatic token fetch or logging |
| Gateway API keys | keys CRUD/reveal/rotate | `KeysPage.svelte` | create-once display, reveal/rotate/delete confirmation |
| Theme and language | browser-local preference, existing `admin_i18n.json` | `App.svelte`, `lib/i18n.svelte.ts` | preference persistence and visible runtime switch |
| Network search and traces | network-search/status, server web-search and stream-trace settings | existing pages | masked Tavily key preservation, bounded serial polling and exact writes |

Deleted Python assertions that inspected legacy HTML source are replaced by
component or browser behavior tests. Backend route tests remain the API contract
layer. The deleted model-usage browser suite is replaced with a real-DOM test
that accepts only non-negative safe integers and never coerces hostile values.
