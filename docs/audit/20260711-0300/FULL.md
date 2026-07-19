# Codex-Rosetta Round 24 Full Audit Ledger

Audit started: 2026-07-11 03:00 MDT  
Baseline: `audit/20260711` at `b6f37e4`  
Profile: `.agent-work/audit/PROFILE.md` (`Draft`)

| Area | Status | Severity | Files | Notes |
| --- | --- | --- | --- | --- |
| Repository reality and recent changes | Reviewed | No Action | git history; working tree; `origin/master..b6f37e4` | Thirteen audit commits reviewed separately from two unstaged analyzer WIP files |
| Gateway ingress, auth, and routing | Reviewed | No Action | `app.py`, `auth.py`, `headers.py`, `embeddings.py`, `proxy.py` | F-01 fixed by `5e9e4e4`: external request IDs are validated before any consumer |
| Principal-scoped state and persistence | Reviewed | No Action | `state_scope.py`, `proxy.py`, `tool_adaptation.py`, `observability/persistence.py`, crypto | API-key isolation and encrypted SQLite-authoritative replay sampled end to end |
| Streaming and converters | Reviewed | No Action | `gateway/proxy.py`, `stream_trace.py`, transport, converters | Stream lifecycle remains bounded; F-01's external metadata bypass is fixed and covered |
| Admin and observability | Reviewed | No Action | `gateway/admin/**`, `observability/**`, `stream_trace.py` | Auth/persistence/redaction sampled; F-01's trace amplification path is fixed |
| Analyzer and agent tooling | Reviewed | Needs Follow-up | analyzer script/tests; compatibility tooling | F-02 fixed and verified in isolated child `0723f4f`, but intentionally not integrated over the user's unstaged WIP |
| Build, release, Docker, and CI | Reviewed | Track as Debt | `Makefile`, `.github/**`, `docker/**`, `pyproject.toml` | Local release gates pass; external governance remains undefined in Draft profile |
| Independent verification | Reviewed | No Action | tests/lint/build/compatibility gates | 113 targeted and 2,864 full tests pass; lint/build/compat/tag gates pass |

## Audit framing

- Highest priorities: correctness and reliability, then security, operability, and modifiability.
- Critical scenarios: authenticated routing, per-principal isolation, encrypted SQLite replay after restart, bounded streaming and diagnostics, and manual release from the reviewed checkout.
- Profile limitations: owner, legal/privacy baseline, SLO/error budget, vulnerability response, signing/SBOM, and production recovery expectations remain undefined.
- Working-tree constraint: `scripts/analyze_codex_jsonl_errors.py` and `tests/test_analyze_codex_jsonl_errors.py` contain pre-existing unstaged WIP and remain untouched in the main worktree. F-02 was repaired on synthetic base `24c9a368c256ea54fc63b61e0e6a86cf86b47fbd` in `/tmp/codex-rosetta-audit24-f02`, producing isolated child `0723f4f75e331024f0e70408641d525af8208019`.

## Repository reality and recent changes

- **Evidence:** main `HEAD=5e9e4e408e26921dcb0928df0bafa192b1bde7a8`, `origin/master=e48f9b1b37ce921583a372faae01f86f367afa03`. F-01's main commit and F-02's isolated child each contain exactly one standalone `Maintenance-Audit: true` trailer.
- **Diff scope:** committed changes affect stats output isolation, embeddings stats, lint/complexity gates, analyzer session/trace parsing and redaction/bounds, and model/window identity validation. The only unstaged tracked files are `scripts/analyze_codex_jsonl_errors.py` and `tests/test_analyze_codex_jsonl_errors.py`, adding `provider_like` reporting.
- **Verification:** `git diff --check` passes; index is empty. Audit artifacts are ignored/local.

## Finding F-01 — externally supplied request IDs amplify stream-trace storage

- **Status:** Fixed in main commit `5e9e4e408e26921dcb0928df0bafa192b1bde7a8`; original severity `Must Fix`.
- **Scope:** `gateway/app.py::_proxy_handler` reads `x-request-id` without a semantic byte limit; `gateway/headers.py::build_upstream_extra_headers` forwards it; `gateway/proxy.py::_handle_direct_responses_streaming` / `handle_streaming` recover it from `extra_headers`; `gateway/stream_trace.py::StreamTraceLogger.log` stores it in every trace JSONL record outside `_truncate(..., max_string_chars)`.
- **Trigger:** an authenticated caller supplies a long request ID (the HTTP server allows an aggregate 64 KiB header block) and opens a successful traced stream. Every upstream chunk, IR event, source event, downstream SSE event, and terminal trace record repeats the full ID. The vendored parser also accepts embedded Latin-1 control bytes other than CR/LF, and `request_id` is interpolated into ordinary terminal logs before any validation.
- **Observed evidence:** a direct `StreamTraceLogger` reproduction with a 60,000-character request ID, `max_string_chars=100`, and 100 tiny records produced 100 records, a 60,298-byte first line, and **6,029,990 bytes** total. Thus the configured record-data budget does not bound the attacker-controlled metadata cost. A direct `_read_header_section` reproduction accepted `x-request-id: req-\x1b[2J` and returned the literal ESC sequence, proving terminal-control injection reaches application code.
- **Impact:** when optional stream tracing is enabled, one authenticated client can multiply one bounded request header by stream event cardinality and consume diagnostic disk/I/O. Independently of tracing, an accepted request ID can inject terminal control sequences into Gateway logs; the same unvalidated value is also copied into profiler metadata, response headers, and the upstream request.
- **Implemented resolution:** shared ingress validation accepts only 1–128 bytes of visible ASCII (`!` through `~`), generates a Gateway UUID only when the header is absent, and rejects blank, control, DEL/C1, non-ASCII, and oversized external IDs before body parsing, logging, trace creation, persistence, state allocation, or upstream forwarding. Proxy source envelopes and embeddings return their native 400 shapes; rejected external values are never reflected, and proxy errors carry a newly generated safe UUID.
- **Verification:** 192 request-ID/high-risk regression tests passed; the final main-tree full run passed **2,915 tests, 5 skipped, 9 warnings**. `make lint` passed Ruff, format, ty, and Complexipy.

## Finding F-02 — WIP provider-like totals omit bounded-group overflow

- **Status:** Fixed and verified in isolated child `0723f4f75e331024f0e70408641d525af8208019`; not integrated into the main worktree because the affected implementation and tests belong to the user's unstaged WIP. Original severity `Should Plan`.
- **Scope:** `scripts/analyze_codex_jsonl_errors.py::summarize_provider_like` derives every count only from retained `report["error_groups"]`, after `analyze_paths()` has discarded new signatures beyond `max_error_groups`.
- **Trigger:** retained groups fill with a non-provider category before a provider-like signature arrives. The global category counters and `error_group_overflow_by_category` count that provider error, while `provider_like.candidate_count`, `by_category`, and evidence buckets report zero.
- **Observed evidence:** with `max_error_groups=1`, one retained generic error followed by `Error [OpenAI]: HTTP 401` produced global `upstream_auth=1` and overflow `upstream_auth=1`, but `provider_like.candidate_count=0` and empty provider-like buckets.
- **Impact:** a JSON consumer using the new summary can conclude that no provider-like errors occurred precisely when high-cardinality history activates the safety bound. The global `retention.truncated=true` prevents this from being wholly undisclosed, but the new summary does not state that its counts are retained-only.
- **Implemented resolution in scratch:** `ProviderLikeAggregate` counts provider-like category/evidence and bounded provider/status buckets once, before group retention. It retains no second signature/sample map; detailed named groups still come only from capped `error_groups`. The report now separates complete scanned totals from retained named groups and exposes `counts_truncated_by_file_limit`, `retained_groups_truncated`, `retained_group_occurrences_dropped`, and `retained_group_overflow_by_category`.
- **Verification:** with `max_error_groups=1`, an overflowed OpenAI 401 still reports `candidate_count=1`, the correct category/evidence and `openai:HTTP 401=1`, while retained named groups stay empty and explicitly truncated. Analyzer tests passed **18/18**; scratch `make lint` passed; scratch full tests passed **2,916, 5 skipped, 9 warnings**.
- **Integration boundary:** synthetic base `24c9a368c256ea54fc63b61e0e6a86cf86b47fbd` exactly captures the two unstaged WIP files on top of main `5e9e4e4`. The child must not be cherry-picked directly without first deciding how the user's WIP should be recorded.

## High-risk workflow review

- **Auth and ownership:** `/v1/**` fails closed under gateway API-key auth; Admin authentication is separate; configured stable key IDs populate `GatewayStateScope.principal_id`. Model and window identities are bounded before route/state allocation.
- **Durable replay:** persistent tool localization reads and writes exact mappings through authenticated, encrypted SQLite rows scoped by principal/provider/model/session/call ID. Missing/unreadable persistence and crypto/tamper/capacity failures fail closed; persistent scopes do not use the volatile `CodexToolLocalizationStore` as replay authority.
- **Streams:** upstream line/event limits, cancellation/close, raw Responses byte passthrough, converted completion/error events, request-local cleanup, and terminal telemetry were sampled. No independent stream lifecycle defect was confirmed apart from trace metadata amplification.
- **Converters:** Responses↔Chat request/history/tool/reasoning paths and Anthropic/Google converter suites are covered by the full test pass. The current Codex source contract reports no extracted drift; groups labelled "Possibly unchanged" still require their documented live evidence.
- **Admin/observability:** mandatory credentials, hot-reload preparation/commit, body/error token redaction, request/error persistence, profiling bounds, and mapping backup/key behavior were sampled. Profile-level SLO, recovery, signing/SBOM, and vulnerability-response ownership remain undefined.

## Independent verification

- Final F-01 changed/high-risk tests on main: `192 passed`.
- F-02 scratch analyzer tests: `18 passed`.
- `conda run -n llm-rosetta make lint`: passed Ruff, format (299 files), ty, and Complexipy ratchet.
- Final main `conda run -n llm-rosetta make test`: **2,915 passed, 5 skipped, 9 warnings**.
- F-02 scratch `conda run -n llm-rosetta make test`: **2,916 passed, 5 skipped, 9 warnings**.
- `conda run -n llm-rosetta python -m build`: succeeded; built `codex_rosetta-0.144.0.post0` sdist and wheel. Because two analyzer files are dirty, these are verification-only artifacts, not clean release evidence.
- `conda run -n llm-rosetta make check-codex-compat`: passed against source `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`; `Changed: None`, with twelve groups still explicitly "Possibly unchanged".
- `conda run -n llm-rosetta make check-release-version RELEASE_TAG=v0.144.0.r0`: passed.
- Not run: credentialed live provider/Codex/agentabi, browser, Docker, external CI, deploy/rollback, production backup/restore drill, load, vulnerability/license/SBOM/signing.

## Simplification and risk-ranking pass

- F-01 was fixed once at the shared external request-ID boundary; no separate logger/trace/profiler sanitizers were added.
- F-02 reuses scan-time bounded counters and retained samples; it neither removes the cardinality cap nor introduces an unbounded second group map.
- No converter, persistence service, or state-store rewrite is warranted. Existing ownership boundaries remain usable.
- F-01 ranks first because an authenticated request reliably reaches an unsanitized log before upstream success and can conditionally multiply disk writes by stream event count. Evidence is direct and the fix is small/reversible.
- F-02 ranks below runtime findings because it affects a new unstaged offline-report field and the enclosing report already exposes truncation, but it can still produce a materially wrong zero and should be corrected before the WIP is committed.

## Final limitations and human review

- The Draft audit profile still lacks an owner and approved privacy/legal, SLO/error-budget, incident response, supply-chain signing/SBOM, and recovery baselines.
- Live Codex/provider scenarios remain incomplete: native GPT, compact/resume/fork, plugin/MCP/deferred tools, web search/UI phase/errors, Desktop tools, and multi-agent behavior.
- GitHub Actions and base images are version-tagged rather than immutable-digest pinned; without an approved supply-chain baseline this remains tracked governance debt, not a newly asserted runtime defect.
- No production deployment, rollback, restore, load, or vulnerability scan was performed.
