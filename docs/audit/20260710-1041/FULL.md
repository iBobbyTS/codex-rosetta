# Codex-Rosetta Full Audit Ledger

Audit started: 2026-07-10 10:41 America/Edmonton

| Area | Status | Severity | Files | Notes |
| --- | --- | --- | --- | --- |
| Repository state and diff | Reviewed | No Action | 95 modified/new paths | Large uncommitted gateway hardening diff preserved and reviewed as-is |
| Request identity and cross-request state | Reviewed | No Action | `gateway/app.py`, `gateway/state_scope.py`, `gateway/proxy.py`, `gateway/tool_adaptation.py` | F-01 resolved: private request nonce plus terminal cleanup; persistent windows preserved |
| Deferred tool-search state | Reviewed | No Action | `gateway/proxy.py::WindowToolSearchStore` | F-02 resolved: atomic per-scope/global count and canonical-byte budgets |
| Auxiliary outbound HTTP | Reviewed | No Action | `gateway/web_search.py`, Admin outbound clients, HTTP transport | F-03 resolved: all auxiliary clients use the primary bounded streaming reader |
| Tool-mapping TTL configuration | Reviewed | No Action | `gateway/admin/routes/config.py`, `gateway/tool_adaptation.py`, `gateway/config.py` | F-04 resolved: shared finite `(0, 720]` validator at config/Admin/runtime boundaries |
| Auth, CORS, and Admin control plane | Reviewed | No Action | `gateway/auth.py`, `gateway/cors.py`, `gateway/admin/routes/**` | Fail-closed `/v1`, strict Admin origin handling, bounded login/task state sampled |
| Persistence and observability | Reviewed | No Action | `observability/**`, `gateway/health.py`, `gateway/stream_trace.py` | Existing accepted privacy/retention contracts retained; encrypted tool mappings sampled |
| Primary upstream transport and image fetch | Reviewed | No Action | `gateway/transport/**`, `google_genai/image_fetch.py`, `gateway/image_workers.py`, `_vendor/**` | Main provider bodies/SSE and URL-image egress have explicit limits and tests |
| Converter and stream compatibility | Partial | No Action | Responses/Google changed files, phase buffer, tool adaptation | Changed paths sampled; full automated suite and Codex contract gate passed |
| Release/build/container | Reviewed | No Action | CI, Makefile, Docker, release/version compatibility docs | Local source/tag/contract gates passed; no external release or deployment run |
| Tests and independent verification | Reviewed | No Action | `tests/**` and project gates | `make lint`, full non-integration test suite, compatibility and release-version gates passed |

## Repository state and diff

- **Status:** Reviewed.
- **Severity:** No Action for repository hygiene; findings below remain open.
- **Scope:** `git status --short --branch`, `git log -5 --oneline`, `git diff --stat`, `git diff --numstat`, `git diff --check`, `git diff origin/master --check`.
- **Focus:** Current repository reality, audit target, scope size, conflict/stale-state detection.
- **Evidence:** `master` is one commit ahead of `origin/master`; the working tree contains 95 changed/new paths and approximately 6,300 additions / 1,392 deletions. Both diff checks exited successfully. The vendored `httpclient`/`sse` changes have prior repo-local provenance evidence in the immediately preceding audit; this pass did not repeat the upstream checkout verification.
- **Verification:** Current status and diff statistics inspected directly on 2026-07-10.
- **Gaps / Assumptions:** The working tree is user-owned and reviewed as-is. This audit does not infer which prior agent created each change and did not modify runtime code.

## F-01: client `x-request-id` aliases independent request-local state

- **Status:** Reviewed; resolved.
- **Severity:** No Action (originally Must Fix).
- **Scope:** `src/codex_rosetta/gateway/app.py::_proxy_handler` around lines 431-495; `src/codex_rosetta/gateway/state_scope.py::GatewayStateScope.for_request` lines 23-48; `ProviderMetadataStore` lines 800-916; `CodexToolLocalizationStore` lines 192-244.
- **Focus:** Authenticated ownership, request isolation, cross-request compatibility metadata, correlation versus identity.
- **Finding:** When `x-codex-window-id` is absent, `GatewayStateScope.for_request()` is intended to create an isolated, non-persistent request scope. The supplied `request_id` is nevertheless the client-provided `x-request-id` whenever that header exists. Two independent requests with the same principal/provider/model and reused correlation ID therefore receive equal state scopes. App-owned stores retain those scopes until TTL/eviction or shutdown; they are not cleared in the request `finally` path.
- **Trigger / failure path:** A client or reverse proxy reuses `x-request-id`; a first request caches provider metadata or a localized tool mapping for a call ID; a later request under the same principal/provider/model and call ID receives the first request's state despite having no window ID.
- **Observed reproduction:** Two calls to `GatewayStateScope.for_request(... request_id='reused', window_id=None)` compared equal. Caching `provider_metadata={'signature':'from-first-request'}` through the first scoped `ProviderMetadataStore`, then injecting through the second, added that signature to the second request.
- **Impact:** Wrong provider signatures or code-tool mappings can be injected into an unrelated request. A shared gateway access-key principal can make this cross-client within that principal; accidental proxy correlation-ID reuse is also enough. The failure violates the source contract that a missing window is request-local.
- **Recommended priority:** Must Fix before treating principal/window isolation as complete.
- **Suggested fix direction:** Keep the external request ID only for tracing/forwarding. Generate a private per-dispatch nonce for non-window `conversation_id`, or clear every non-persistent scoped store deterministically after response/stream completion. Add a two-request regression that reuses `x-request-id` and proves no metadata or tool mapping crosses requests.
- **Verification:** Source trace plus executable minimal reproduction.
- **Gaps / Assumptions:** Persistent window scope intentionally remains client-selected and is not part of this finding.
- **Resolution:** `GatewayStateScope.for_request()` now generates a private UUID nonce when no window exists; `x-request-id` remains trace-only. `_proxy_handler()` clears provider metadata, localization and deferred-tool state after non-streaming completion/error, and the instrumented stream finalizer performs the same cleanup after normal EOF, provider failure, early close or cancellation. Persistent window scopes are never cleared by this request-local path.
- **Regression verification:** Sequential and concurrent requests with the same principal/provider/model and reused `x-request-id` remain isolated; persistent window continuity and all stream terminal cleanup paths are covered by `test_request_state_lifecycle.py` and `test_stream_telemetry_lifecycle.py`.

## F-02: deferred tool-search cache is count-bounded but byte-unbounded

- **Status:** Reviewed; resolved.
- **Severity:** No Action (originally Must Fix).
- **Scope:** `src/codex_rosetta/gateway/app.py:create_app` (`max_body_size=50_000_000`); `gateway/proxy.py::_defer_responses_namespace_tools_for_chat` lines 403-443; `WindowToolSearchStore` lines 919-1438, especially `_remember_tools` and `_merge_loadable_tool` lines 1204-1254.
- **Focus:** Authenticated-client denial of service, cumulative memory growth, TTL/eviction semantics, deep-copy amplification.
- **Finding:** `WindowToolSearchStore.max_size` limits only the number of scope keys in each dictionary. A single scope entry is a dictionary that can grow without a tool-count or byte limit across requests. Every unique namespace/tool is deep-copied into the entry; updating a namespace deep-copies the existing entry again. The 50 MB request limit bounds one request but not cumulative retained state.
- **Trigger / failure path:** An authenticated caller sends Responses-to-Chat requests with one `x-codex-window-id` and repeatedly supplies unique deferred namespace tools or `tool_search_output.tools`. Each request refreshes the scope timestamp and adds more retained definitions, so the TTL does not converge while the caller remains active.
- **Observed reproduction:** With `WindowToolSearchStore(max_size=1)`, 200 sequential tools with 10,000-character descriptions under one scope produced one retained scope containing 200 tools and approximately 2,018,380 serialized bytes. The `max_size=1` cap never applied to the contents of that scope.
- **Impact:** One valid gateway credential can grow process memory until OOM. The same count-only pattern also merits review in provider metadata/localized-call caches, but the deferred tool store is directly controllable by the downstream request and is the confirmed path.
- **Recommended priority:** Must Fix because availability is a highest-priority profile attribute and the trigger is an ordinary authenticated API request.
- **Suggested fix direction:** Enforce per-scope and global serialized-byte budgets plus tool/count limits at the single store owner. Define deterministic behavior on overflow (reject the request or evict the oldest tool/scope without corrupting current history), and add repeated-request tests that prove retained bytes converge. Avoid adding a parallel cache layer.
- **Verification:** Source inspection plus executable bounded-store reproduction.
- **Gaps / Assumptions:** No production load test was run; the reproduction used small payloads to demonstrate unbounded growth without stressing the workstation.
- **Resolution:** The existing `WindowToolSearchStore` now owns a lock-protected shared accounting state across scoped views. It enforces 1,024 nested tools and 16 MiB canonical UTF-8 JSON per scope plus 64 MiB per app. Deferred and discovered batches are jointly preflighted; candidate payloads are materialized before TTL eviction, scope-count eviction or replacement, so capacity failures return a stable `ToolSearchCapacityError` without partial state mutation. Existing scope-count eviction remains and all removal paths return cached budgets.
- **Regression verification:** Cross-request accumulation, same-name replacement, Unicode bytes, per-scope/global limits, concurrent writers, TTL, scope-count eviction, clear, combined-batch atomicity and stable HTTP 413 mapping are covered by `test_window_tool_search_store.py` and `test_request_state_lifecycle.py`.

## F-03: auxiliary outbound HTTP bypasses Gateway response limits

- **Status:** Reviewed; resolved.
- **Severity:** No Action (originally Must Fix).
- **Scope:** `src/codex_rosetta/gateway/web_search.py::TavilyHTTPClient.search` lines 61-107; `gateway/admin/routes/observability.py::network_diagnostics`; `gateway/admin/routes/config.py` provider model discovery; vendored `httpclient.py::_async_read_body` lines 2023-2065 and `_async_request` lines 2366-2491; compare `gateway/transport/http/transport.py::_read_bounded_body`.
- **Focus:** External-response memory bounds, compressed responses, shared transport policy, client-triggerable optional integrations.
- **Finding:** Main provider traffic correctly requests a streaming response and passes it through the Gateway's bounded reader. Auxiliary clients call `AsyncClient.get/post()` without `stream=True`. The vendored non-stream path trusts `Content-Length` for `readexactly(length)`, accumulates all chunked parts, or reads until EOF, then decompresses the complete body. It has no total wire or decoded byte limit.
- **Trigger / failure path:** A Tavily endpoint, configured proxy, DNS/transport compromise, or auxiliary provider endpoint returns a very large or compressed-bomb response. Web search is reachable from ordinary authenticated generation requests when configured, so Admin access is not required for the primary path.
- **Impact:** A single external response can allocate unbounded memory and terminate the Gateway process. This bypasses the safety envelope recently added to the primary upstream transport.
- **Recommended priority:** Must Fix before describing outbound response aggregation as system-wide bounded.
- **Suggested fix direction:** Reuse one bounded auxiliary HTTP response helper that requests `stream=True`, forces or validates identity encoding, caps wire/decoded bytes, always closes on overflow/cancellation, and returns a stable domain error. Add real loopback tests for oversized `Content-Length`, chunked/EOF bodies, and compressed responses on the Tavily path. Do not manually patch vendored code for a Gateway-only policy.
- **Verification:** Direct source trace. Existing web-search tests inject a fake client and do not exercise the real reader or overflow behavior.
- **Gaps / Assumptions:** No malicious live Tavily/proxy endpoint was contacted.
- **Resolution:** `request_bounded_response()` reuses the primary transport's success/error byte constants and incremental reader, forces `Accept-Encoding: identity`, rejects unsupported encoding, and closes on overflow or cancellation. Tavily, Admin network diagnostics, provider model discovery and model-test self-calls all use this helper; no Gateway auxiliary `AsyncClient` response aggregation bypass remains.
- **Regression verification:** Real loopback coverage verifies normal JSON, Content-Length, chunked and EOF overflow, compressed-response rejection, timeout and cancellation on the Tavily path. Admin call-site tests verify model discovery, diagnostics and model-test routing through the helper.

## F-04: tool-mapping TTL accepts non-finite and overflowing values

- **Status:** Reviewed; resolved.
- **Severity:** No Action (originally Must Fix).
- **Scope:** `src/codex_rosetta/gateway/admin/routes/config.py::_clean_tool_adaptation` lines 119-161; `gateway/tool_adaptation.py::tool_call_cache_ttl_hours` lines 1329-1342; `gateway/proxy.py::_persist_tool_mapping` lines 665-695; `gateway/config.py::GatewayConfig` model adaptation parsing.
- **Focus:** Configuration validation, persistence expiry arithmetic, JSON interoperability, failure timing.
- **Finding:** Both TTL normalizers convert arbitrary values with `float()` and reject only `ttl <= 0`. `NaN`, positive infinity, and extremely large finite values all pass. The Admin normalizer may then write `NaN`/`Infinity` using Python's non-standard JSON encoding. The invalid value is not rejected by `GatewayConfig`; failure occurs later when a persistent localized tool call computes `timedelta(hours=ttl_hours)`.
- **Trigger / failure path:** Admin submits a string such as `"nan"`, `"inf"`, `"1e999"`, or a huge numeric value, or the raw config contains one; code-tool localization is enabled; a window-scoped response emits a mapping.
- **Observed reproduction:** Every listed value was accepted by `_clean_tool_adaptation()`/`tool_call_cache_ttl_hours()`. `_persist_tool_mapping()` then raised the stable outer `RuntimeError('Tool history could not be durably protected; refusing volatile mapping')`, caused by `ValueError`/`OverflowError` in `timedelta`.
- **Impact:** A config accepted at startup/Admin save can break otherwise valid tool-call responses at runtime; `NaN`/`Infinity` can also produce config/API JSON that standards-compliant clients cannot parse.
- **Recommended priority:** Must Fix at the configuration boundary; the fix is small and high-confidence.
- **Suggested fix direction:** Define one strict TTL validator used by raw config, Admin writes, and runtime access. Require a finite numeric value within an explicit maximum that `timedelta` and operational retention support; reject invalid candidates with a 400/startup `ValueError` rather than silently defaulting after persistence.
- **Verification:** Source inspection and executable failure reproduction.
- **Gaps / Assumptions:** The product owner still needs to choose the maximum supported TTL; finiteness and `timedelta` safety are not ambiguous.
- **Resolution:** One validator in `gateway/tool_adaptation.py` requires a non-boolean finite numeric value with `0 < ttl <= 720` hours. `GatewayConfig` validates raw/env-substituted values at startup, Admin returns 400 without writing, and runtime access no longer performs permissive fallback parsing. The 24-hour default is unchanged.
- **Regression verification:** Tests cover numeric/env strings, booleans, NaN, infinity, numeric overflow, the inclusive 720-hour boundary, Admin no-write rejection and runtime helper behavior.

## Auth, CORS, Admin, persistence, transport, and compatibility sampling

- **Status:** Reviewed/Partial as shown in the index.
- **Severity:** No additional finding.
- **Scope and evidence:**
  - `/v1` auth fails closed by namespace; Admin API requires its derived token; Admin preflight checks the live normalized origin allowlist; public health behavior matches the previously accepted token-only contract.
  - Config writes use a digest CAS, lock, atomic replace/backup, prepared runtime activation, persistence compensation, and file restoration on activation failure.
  - SQLite/data/key paths are owner-only; executable tool mappings use AES-GCM with scope-bound AAD and fail startup on key/integrity mismatch. Existing count-only diagnostic retention is documented and previously accepted.
  - Main provider HTTP bodies and SSE line/events have explicit limits. Google URL-image conversion rejects non-public destinations, revalidates redirects, limits MIME/bytes/deadline, and uses an app-owned worker pool.
  - Changed Responses/Google converter paths and stream-phase/tool-adaptation paths were sampled. No new protocol mismatch was found.
  - Prior repo-local decisions explicitly accept the public-health token-only body contract, count-only diagnostic retention, manual release provenance, and the recorded web-search total call/time/cost debt. They are not repackaged as new findings in this round.
- **Verification:** Static/source trace, current full test suite, lint/type checks, Codex contract gate, release version gate, and prior artifact consistency check.
- **Gaps / Assumptions:** Real provider/API/agentabi, browser Admin UI, GitHub Actions, multi-process/restart pressure, backup/restore, Docker/Compose, vulnerability/license scanning, and remote release/deploy were not run in this pass.

## Independent verification

- `conda run -n llm-rosetta make lint`: passed (`ruff check`, 288-file format check, `ty check`).
- `conda run -n llm-rosetta make test`: passed, `2677 passed, 4 skipped, 9 warnings` on Python 3.14.6.
- `conda run -n llm-rosetta make check-codex-compat`: passed against Codex source `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`; no changed contract group.
- `conda run -n llm-rosetta make check-release-version RELEASE_TAG=v0.144.0.r0`: passed.
- `git diff --check` and `git diff origin/master --check`: passed.
- Focused post-repair regression: `196 passed`; final atomic-budget/lifecycle/HTTP/config subset: `186 passed`.
- Compose smoke built the current checkout wheel into `codex-rosetta-gateway-local:0.144.0.r0`, started the real entrypoint in an isolated no-host-port container, returned `status: ok` from container-local `/health`, and reported `codex-rosetta-gateway 0.144.0.r0`.

## Simplification pass

- F-01 should separate correlation identity from state identity instead of adding another compatibility fallback.
- F-02 should extend the existing store with resource accounting, not create a second cache/service.
- F-03 should centralize bounded auxiliary reads and remove direct unbounded `AsyncClient` aggregation from network integrations.
- F-04 should use one validator shared by config/Admin/runtime; the duplicate permissive float conversions should be deleted.
- Unused legacy generation handlers in `gateway/app.py` and large `app.py`/`proxy.py` coordinators remain existing technical debt. No broad rewrite is justified by these four repairs.
