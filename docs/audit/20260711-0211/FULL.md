# Codex-Rosetta Round 23 Full Audit Ledger

Audit started: 2026-07-11 02:11 MDT  
Baseline: `audit/20260711` at `18eb243`  
Profile: `.agent-work/audit/PROFILE.md` (`Draft`)

| Area | Status | Severity | Files | Notes |
| --- | --- | --- | --- | --- |
| Repository reality and recent changes | Reviewed | No Action | git history; working tree; `origin/master..18eb243` | Seven audit commits reviewed; two pre-existing analyzer WIP files remain unstaged |
| Gateway ingress, auth, and model routing | Reviewed | Must Fix | `src/codex_rosetta/gateway/app.py:480-555`, `auth.py`, `proxy.py:203-211`, `embeddings.py:67-103` | F-01 resolved by `f8b60e2`; model/window IDs now have UTF-8 byte limits |
| Principal-scoped state and persisted replay | Reviewed | Must Fix | `state_scope.py`, `proxy.py:606-735,810-1115`, `tool_adaptation.py`, observability persistence | SQLite replay remains authoritative; F-01 accounting bypass is closed at ingress |
| Streaming and transport lifecycle | Reviewed | No Action | `gateway/proxy.py`, `transport/http/transport.py`, converters | SSE/error/close/bounds and terminal telemetry sampled |
| Admin and observability control plane | Reviewed | No Action | `gateway/admin/**`, `observability/**` | Auth, persistence, redaction, runtime ownership, bounded self-test sampled |
| Analyzer and agent tooling | Reviewed | Must Fix | `scripts/analyze_codex_jsonl_errors.py`, analyzer tests | F-02/F-03 and portability debt resolved by `f3ca68a`, `9f7dd0c`, and `dee82c0` |
| Converter and IR contracts | Reviewed | No Action | `converters/**`, `types/ir/**`, `shims/**` | Responses↔Chat/IR, tools, reasoning, stream ordering and provider sampling complete |
| Build, release, Docker, and CI | Reviewed | Track as Debt | `Makefile`, `.github/**`, `docker/**`, `pyproject.toml` | Manual release/current-wheel contract holds; external supply-chain governance remains undefined |
| Tests and independent verification | Reviewed | No Action | `tests/**`, compatibility scripts | Lint/test/build/compat/release gates pass; live/external evidence remains unavailable |

## Audit framing

- Highest priorities: correctness and reliability, then security, operability, and modifiability.
- Critical scenarios: authenticated request routing; per-principal cache isolation; encrypted SQLite tool-history replay across restart; streaming termination/cancellation; diagnostics without token leakage; manual release from reviewed checkout.
- Known baseline limitation: profile owner, privacy/legal baseline, SLO/error budget, vulnerability response, SBOM/signing, and production recovery requirements remain undefined.
- Working-tree constraint: `scripts/analyze_codex_jsonl_errors.py` and `tests/test_analyze_codex_jsonl_errors.py` contain pre-existing unstaged WIP and must not be attributed to committed `18eb243`.

## Repository reality and recent changes

- **Scope:** `git status --short --branch`, `git log`, `git diff origin/master..HEAD`, each of the seven commits after `e48f9b1`, and the two unstaged analyzer files.
- **Evidence:** baseline is `18eb243`; committed changes are limited to stats failure isolation, embedding stats, static/complexity gates, evidence-aware analyzer parsing, token-only redaction, and model type/non-empty validation. The worktree had only the two known unstaged analyzer files before this audit's local artifacts were created.
- **Verification:** `git diff --check` passes. No staged diff was present.
- **Gaps:** local `.agent-work/audit/**` evidence is intentionally untracked and not part of runtime/release artifacts.

## Finding F-01 — unbounded request identity fields bypass intended resource budgets

- **Severity:** Must Fix.
- **Scope:** `gateway/proxy.py::extract_model`, `gateway/app.py::_proxy_handler`, `gateway/state_scope.py::GatewayStateScope.for_request`, `gateway/proxy.py::ProviderMetadataStore`, and `WindowToolSearchStore`.
- **Trigger A (model reflection):** an authenticated caller sends a valid JSON object whose `model` is a very long non-empty string. `extract_model()` accepts it, `GatewayConfig.resolve()` fails, and both `/v1/responses` and `/v1/embeddings` interpolate the entire attacker-controlled model into the 404 body.
- **Observed evidence:** a 1 MiB model produced 404 bodies of **1,048,695 bytes** (`/v1/responses`) and **1,048,675 bytes** (`/v1/embeddings`), both containing the full input. The configured request-body limit is 50 MB and can explicitly be set to unlimited, so the current model fix validates type/emptiness but not a semantic size budget.
- **Trigger B (state-key accounting bypass):** `x-codex-window-id` is copied verbatim into `GatewayStateScope.conversation_id`. Provider metadata and deferred-tool byte quotas count serialized values but not the scope strings held in dict keys/accounting maps. The HTTP parser permits close to its aggregate 64 KiB header budget.
- **Observed evidence:** inserting 1,024 tiny provider-metadata entries under one principal with distinct 60,000-character window IDs retained **61,956,140 bytes** by `tracemalloc`, while `ProviderMetadataStore._state.global_bytes` reported only **7,168 bytes**. This is within the store's existing per-principal entry limit, so the byte quota does not prevent the amplification.
- **Impact:** one authenticated API key can amplify bounded request input into large response allocation/writes, and can retain tens of MiB of unaccounted state per principal. Concurrent use raises Gateway OOM/latency risk and undermines the resource-envelope claims used by prior audits.
- **Suggested fix direction:** enforce small, documented UTF-8 byte limits at the shared ingress boundary for model names and `x-codex-window-id` before routing/state construction; return stable source-shaped 400 responses. Current Codex IDs are `{UUID}:{window_number}`, so a conservative fixed ceiling can retain forward compatibility. Regression tests should prove exact-bound acceptance, over-bound rejection on responses/embeddings, and that oversized window IDs never reach proxy/state stores.
- **Simplification check:** an ingress limit is smaller and easier to reason about than teaching three independent in-memory stores to account every repeated scope-key/object byte.
- **Resolution:** `f8b60e2` enforces 256 UTF-8 bytes for model IDs and 128 UTF-8 bytes for `x-codex-window-id` before routing/state allocation. Exact/+1 and multibyte regressions cover Responses, embeddings, Chat, Anthropic, Google, and pre-routing rejection. `10fe69e` narrows the new test response types for the repository's full `ty` gate.

## Principal isolation and durable replay

- **Focus:** API-key principal ownership, provider/model/window scoping, encrypted SQLite lookup/write, restart, key mismatch/tamper, quotas, cleanup, and volatile fallback behavior.
- **Evidence:** `api_key_principal_var` derives from the configured unique `server.api_keys[].id`; `GatewayStateScope` includes principal/provider/model/conversation. Persistent localization loads only through `query_tool_call_mappings()` and persistent writes pass only through encrypted `upsert_tool_call_mapping()`. Persistent scopes pass `store=None`; missing/unreadable persistence raises and refuses lossy replay instead of using the in-memory `CodexToolLocalizationStore`.
- **Verification:** full persistence/state tests passed within the 2,842-test suite. Source paths for restart/backup/key mismatch/tamper and row/session/principal/global quotas were inspected.
- **Conclusion:** the user's database-authoritative replay and per-API-key isolation semantics hold, apart from F-01's unaccounted identifier-memory cost.

## Gateway streaming, admin, observability, and release boundaries

- **Streaming/transport:** inspected success/error size envelopes, identity encoding, SSE line/event limits, malformed JSON fail-closed behavior, cancellation/close, raw Responses passthrough, stream terminal telemetry, and request-local cleanup. No new independent defect confirmed.
- **Admin/observability:** inspected separate Admin authentication, app-owned login/task state, bounded model-test self-call, request/error/profile access, redaction, encrypted mapping persistence, and shutdown. No new independent defect confirmed.
- **Release/build:** no automated PyPI/Docker publication workflow exists. `push-package`, `push-docker`, and `push` are disabled; Docker and Compose require the current checkout wheel; manual release docs/tag contract remain `v{codex_version}.rN`.
- **Debt:** GitHub Actions tag pinning, SBOM/signing, vulnerability response, SLO/recovery ownership, and production backup/restore remain profile-level decisions without approved baselines.

## Converter, IR, and shim contracts

- **Scope:** OpenAI Responses request items, additional/deferred tools, custom/function tool calls, reasoning history, tool results/order, Responses phase buffering, Chat bridge response reconstruction, stream event completion, Anthropic/Google message/content/tool boundaries, shared IR validation, shim transforms, and provider YAML discovery.
- **Evidence:** current source keeps source/target converters behind `ConversionPipeline`, records provider-specific metadata in `ConversionContext`, preserves native custom tool types, applies tool-history localization only on the Responses→Chat bridge, and uses the persisted mapping before upstream history replay. Phase buffering and stream completion have dedicated tests, as do malformed request/response and tool ordering paths.
- **Verification:** converter and type suites are included in the full **2,842 passed** result; the aggregate source coverage report was 79%, with core converter modules generally in the mid-80s to high-90s. The Codex source-contract gate reported `Changed: None` against `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`.
- **Gaps:** contract extraction still labels several Rust member/type/default/serde groups as “possibly unchanged”; live native GPT, compact/resume/fork, plugin/MCP/deferred-tool, web-search/UI phase/error, Desktop tool, and multi-agent evidence remain pending exactly as documented. No new source-level mismatch was confirmed.

## Analyzer and agent-tooling review

- **Committed behavior:** ordinary Codex sessions and opt-in raw rollout traces are parsed as separate schemas; token/API-key/Bearer/Authorization masking preserves ordinary password/secret/prompt data as required.
- **Unstaged WIP:** `provider_like` separates structured provider evidence, explicit named provider text, unattributed HTTP text, and weak/contextless text in the JSON report. `render_markdown()` does not display that new summary. This is **not yet classified as a defect** because no documented CLI contract says the WIP field must be rendered; it is an integration/test gap if the intended user-facing outcome is CLI visibility.
- **F-02 resolved:** `f3ca68a` narrowly masks `rsk-<48 hex>`, `rsk-internal-<32 hex>`, and `AIza<35 supported chars>` while regressions prove ordinary password/secret/client_secret/prompt data remains intact.
- **F-03 resolved:** `9f7dd0c` streams deterministic file discovery into a 20,000-candidate retained cap and limits real retained `ErrorGroup` objects to 10,000. Total category/provider-actionable counts continue across overflow; bounded per-category drop counters and JSON/Markdown truncation disclosures replace any temptation to invent an overflow signature. Tests cover exact/+1, 500 distinct errors, `sample_limit=0`, category totals, and deterministic output. `b6f37e4` supplies the explicit fixture type needed by the full `ty` gate.
- **Portability debt resolved:** `dee82c0` derives archived/session defaults from `Path.home() / ".codex"` while preserving the explicit backup volume and `CODEX_ROLLOUT_TRACE_ROOT` behavior.
- **500 reflection review:** the generic proxy catch reflects `str(exc)` in a 500, while upstream/conversion errors also intentionally return source-shaped diagnostic text. Concrete converter exceptions can contain client-supplied values, but the response goes to the same authenticated caller that supplied them, and the accepted product rule is to preserve non-token diagnostic data. No cross-principal or unauthenticated disclosure path was found, so this is not currently a finding. Token-bearing observability paths continue to use redactors; raw upstream protocol errors have stable body-free messages.

## Independent verification to date

- `conda run -n llm-rosetta make lint`: passed Ruff, format (299 files), ty, and Complexipy ratchet.
- `conda run -n llm-rosetta make test`: **2,864 passed, 5 skipped, 9 warnings** in 14.52 seconds (2,869 collected, Python 3.14.6).
- Initial bare `make lint`/`make test` attempts failed immediately because this shell did not have the environment's executables on `PATH`; rerunning through the documented `llm-rosetta` environment passed and is the authoritative result.
- `conda run -n llm-rosetta python -m build`: succeeded; produced `codex_rosetta-0.144.0.post0.tar.gz` and `codex_rosetta-0.144.0.post0-py3-none-any.whl`. Because the worktree contains known analyzer/test WIP, these local artifacts are verification-only and are not clean release evidence.
- `conda run -n llm-rosetta make check-codex-compat`: passed against source commit `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`; `Changed: None`, with the listed “possibly unchanged” groups still requiring their documented live evidence.
- `conda run -n llm-rosetta make check-release-version RELEASE_TAG=v0.144.0.r0`: passed.
- Skip reasons: one real Chromium Admin model-usage regression is opt-in; four parametrized public-API cases had no applicable module items. None was silently disabled by this audit.
- Not run in this round: live credentialed provider/Codex/agentabi, real browser, Docker, external CI, production deploy/rollback, production backup/restore, load, vulnerability/license/SBOM/signing.

## Repair closure

- Repair commits: `f8b60e2` (F-01), `f3ca68a` (F-02), `9f7dd0c` (F-03), `dee82c0` (portability), plus `10fe69e` and `b6f37e4` for full static-type conformance of the new regressions.
- Every repair commit contains exactly one standalone `Maintenance-Audit: true` trailer. No commit includes the pre-existing `provider_like` WIP.
- Final tracked dirty state is limited to `scripts/analyze_codex_jsonl_errors.py` and `tests/test_analyze_codex_jsonl_errors.py`, matching the preserved pre-existing WIP. The index is empty and `.agent-work/audit/CURRENT.md` is absent.
- This repaired round is not counted as a clean audit round; a subsequent independent audit must evaluate the repaired tree.
