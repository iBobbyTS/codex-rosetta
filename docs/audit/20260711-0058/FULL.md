# Audit Ledger — 2026-07-11 00:58

Audit profile: `.agent-work/audit/PROFILE.md` (Draft)

| Area | Status | Severity | Files | Notes |
| --- | --- | --- | --- | --- |
| Repository state and analyzer repair | Reviewed | No Action | `scripts/analyze_codex_jsonl_errors.py`, `tests/test_analyze_codex_jsonl_errors.py` | F-02 resolved in `2c29d36`; session and trace schemas now have separate evidence paths |
| Terminal stats logging | Reviewed | No Action | `gateway/logging.py`, `gateway/app.py`, logging tests | F-01 resolved in `a9823ea`; renderer failures are isolated from the data plane |
| Stats endpoint coverage | Reviewed | No Action | `gateway/app.py`, `gateway/embeddings.py`, docs | F-03 resolved in `3353a32`; embeddings use the existing model-stat path |
| Codex compatibility contracts | Reviewed | Track as Debt | `docs/dev/version-compatibility/**`, `../openai-codex-src/**` | Contract automation passes; live matrix and clean approval remain incomplete |
| Gateway ingress, auth, and body limits | Reviewed | No Action | `gateway/app.py`, `auth.py`, `config.py`, Admin config routes | Auth-before-body, bounded parser, reload/rollback paths sampled |
| Streaming, tools, and per-window state | Reviewed | No Action | `gateway/proxy.py`, `tool_adaptation.py`, `state_scope.py`, Responses converter | Lifecycle, cancellation, quotas, and state ownership sampled |
| Persistence, logging, and observability | Reviewed | No Action | `gateway/admin/**`, `gateway/logging.py`, `observability/**` | Existing ownership, retention, encryption, and redaction protections retained |
| Build, release, and CI | Reviewed | No Action | `Makefile`, `pyproject.toml`, `.github/workflows/**`, `docker/**` | F-04 resolved in `c8f295e` and `3d97198`; analyzer static checks and the complexity ratchet are enforced by `make lint` |
| Tests and independent verification | Reviewed | No Action | `tests/**`, project gates | Full test/lint/build/contract gates pass despite semantic findings |
| Simplification and stale-state pass | Reviewed | Track as Debt | gateway coordinators, compatibility docs | High-complexity hotspots and stale pending baseline remain visible debt |

## Audit framing

- Audit baseline: `e48f9b1 feat(gateway): add live model request stats`; repair closure HEAD: `2c29d3680745cf586bda3a5cddd671158cf18ae8` on `audit/20260711`.
- The committed F-02 tree was verified clean immediately after `2c29d36`. That commit contains only `scripts/analyze_codex_jsonl_errors.py` and `tests/test_analyze_codex_jsonl_errors.py`, with 643 insertions / 48 deletions relative to `3d97198`. After scratch cleanup, a new concurrent unstaged diff appeared in the same two files (128 insertions / 1 deletion, including `summarize_provider_like` and provider-status patterns). It was not staged, committed, reverted, or included in Round 21 verification.
- The analyzer changed concurrently during initial finding analysis. Its mtime moved through intermediate snapshots, briefly producing `2 failed, 2 passed`; the pre-repair evidence snapshot stabilized at `2026-07-11 01:04:42`, after which focused tests returned `4 passed`. F-02 was later repaired and verified on the committed `2c29d36` tree. The still-later dirty diff described above has no test claim in this ledger.
- Profile status: Draft. Unknown owner decisions include legal/privacy constraints, vulnerability response, SLOs, CI credential boundaries, release signing, and SBOM expectations.
- Quality priorities: correctness and reliability first, then security, modifiability/operability, and finally bounded performance/cost.
- Excluded by the profile: exhaustive generic converter, Admin UI, deployment, and dependency security review. These were sampled where they intersect Codex compatibility or credential/logging risk.

## F-01 — Stats output failure can fail otherwise valid proxy requests

- **Status:** Resolved in `a9823ea`.
- **Severity:** Must Fix.
- **Scope:** `src/codex_rosetta/gateway/logging.py:161-176`, `src/codex_rosetta/gateway/app.py:544-548`.
- **Trigger:** Run with `--log-level stats` and let `stderr`/its pipe fail on `write()` or `flush()` (closed consumer, logging driver failure, I/O error).
- **Evidence:** `StatsStreamHandler.record_request()` directly writes and flushes under only a `try/finally` lock release. Unlike `emit()`, it does not catch an output exception or call a safe failure path. `_proxy_handler()` calls `record_request_stat()` before its main `try/finally`. A `Broken.write()` reproduction raised `OSError: stderr closed` at line 172.
- **Impact:** A diagnostic output failure crosses into the data plane and turns valid model requests into HTTP 500 responses. It also bypasses the proxy's normal telemetry and state-finalization block because the call is before that block.
- **Resolution:** Stats rendering is now best-effort and non-throwing. Write, flush, and active-line close failure regressions pass without affecting proxy handling.

## F-02 — Analyzer trusts a trace schema that its default roots do not contain and misses real session errors

- **Status:** Resolved in `2c29d36`.
- **Severity:** Must Fix.
- **Scope:** `scripts/analyze_codex_jsonl_errors.py:448-541`, default roots near the top of that file, and `tests/test_analyze_codex_jsonl_errors.py`.
- **Trigger:** Run the analyzer with no positional roots (the documented/default path), or pass ordinary Codex rollout session JSONL containing `event_msg` `error` / `stream_error` events.
- **Evidence from current Codex source:**
  - Ordinary persisted sessions use `RolloutItem` with `{type, payload}` and `EventMsg` variants (`../openai-codex-src/codex-rs/protocol/src/protocol.rs:1279`, `:1414`, `:1891`, `:3132`, `:3580`). Error events are `payload.type=error` or `stream_error`, with `message`, optional `additional_details`, and structured `codex_error_info`.
  - The new analyzer's trusted provider path accepts only optional raw rollout-trace envelopes with top-level `schema_version=1` and payload types such as `inference_failed`.
  - Raw rollout trace is opt-in via `CODEX_ROLLOUT_TRACE_ROOT` and is written under an arbitrary configured root (`../openai-codex-src/codex-rs/rollout-trace/src/thread.rs:41-44`, `:101-117`, `:420-443`). The analyzer's default roots remain `~/.codex/sessions`, `~/.codex/archived_sessions`, and a session backup path; they do not include that env root.
  - A real current session summary contained `response_item`, `event_msg`, `session_meta`, etc., not raw trace envelopes.
  - Direct final-tree reproductions returned no candidates for all of: an `event_msg/error` with `message='upstream closed the connection'`; an `event_msg/stream_error` with `message='connection reset by peer'`; and a `stream_error` whose `additional_details='HTTP 503 service unavailable'`.
  - `_dict_signals_failure()` also marks a failed container but still requires an error keyword in child text. Thus `{status:'failed', message:'Provider disconnected before producing a response'}` collapses to the generic status and `{exit_code:2, stderr:'bad invocation'}` can be omitted.
- **Impact:** The default scanner can report zero structured upstream failures even when its primary session inputs contain provider errors. Consequently `structured_provider_failover_candidates` is not reliable enough to drive Rosetta failover or retry policy. Synthetic tests pass because they replaced ordinary session fixtures with opt-in trace fixtures.
- **Resolution:** Ordinary session and raw rollout-trace inputs now use separate roots, parsers, and deduplication domains. Session `error` / `stream_error` events collect `message`, `additional_details`, and stable structured error metadata. `CODEX_ROLLOUT_TRACE_ROOT` and `--trace-root` opt in the trace parser. Transient `stream_error` evidence remains ineligible for failover, terminal session errors are evaluated conservatively, structured failed containers no longer require error keywords, and token-only redaction is unchanged.
- **Verification:** Analyzer-focused tests returned **10 passed**. The committed blobs (`03c8e7a5...` and `127574341...`) exactly match the independently prepared scratch commit `6f00214`.

## F-03 — Documented per-model stats omit the embeddings route

- **Status:** Resolved in `3353a32`.
- **Severity:** Should Plan.
- **Scope:** `src/codex_rosetta/gateway/app.py`, `src/codex_rosetta/gateway/embeddings.py`, English/Chinese README stats text.
- **Evidence:** `record_request_stat()` has one runtime call in `_proxy_handler()`. `/v1/embeddings` bypasses `_proxy_handler()` and uses the dedicated embeddings handler. The documentation describes generic per-model request counts and does not declare embeddings out of scope.
- **Impact:** Counts are incomplete for gateways serving embeddings, so the new terminal view disagrees with its documented meaning and with request metrics.
- **Resolution:** The embeddings handler records the resolved `upstream_model` through the existing per-model stats entry point, with endpoint-level regression coverage.

## F-04 — Configured maintainability checks are not release gates

- **Status:** Resolved in `c8f295e` and `3d97198`.
- **Severity:** Should Plan.
- **Scope:** `pyproject.toml`, `Makefile`, `.github/workflows/ci.yml`, high-complexity converter/gateway functions.
- **Evidence:** `pyproject.toml` configures Complexipy with a limit of 25, but `make lint` and CI never run it. Manual `complexipy` fails; non-vendored hotspots include `_web_search_stream_event_generator` (86), `OpenAIResponsesToolOps.p_tool_definition_to_ir` (64), `_stream_event_generator` (40), and several Responses conversion helpers above 25. `PY_CHECK_PATHS` also excludes the newly added analyzer script, so normal CI Ruff/format/ty coverage does not include it; manual Ruff and format checks passed this audit.
- **Impact:** The repository advertises a complexity budget that cannot currently gate regressions, while its highest-risk compatibility coordinators continue accumulating branches. New standalone scripts can bypass the normal static surface.
- **Resolution:** The maintained analyzer is included in Ruff, format, and ty checks. The official Complexipy snapshot ratchet records 25 non-vendored historical hotspots and rejects new or worsened complexity without forcing an unsafe broad refactor.

## Reviewed areas with no new runtime finding

### Gateway ingress, auth, configuration, and state

- Protected `/v1` requests authenticate before body consumption. Request-line/header/body deadlines and parser capacity are bounded.
- The new body-size tiers validate fixed MiB choices, support explicit documented unlimited mode, and participate in Admin hot-reload activation/rollback.
- Only allowlisted request headers are forwarded upstream. Per-request state uses authenticated principal/provider/model/window ownership, and request-local state is cleared on normal, error, and cancellation paths.
- Streaming generators, phase buffering, tool localization, deferred tool search, metadata quotas, and image workers were sampled against their lifecycle tests. No additional concrete mismatch was found.

### Persistence and security controls

- Existing app-owned Admin runtime, bounded model-test retention, encrypted tool mapping persistence, hierarchical quotas, request/error retention, secret redaction, and stream-trace permissions remain in place.
- Docker uses a locally built wheel, drops to an app user after configuration setup, and avoids broad source-tree copying. No current `_vendor/**` edit was made.
- Remaining threat-model, dependency-signing/SBOM, production backup/restore, and CI identity decisions are profile gaps rather than newly demonstrated runtime defects.

### Compatibility and stale-state review

- `make check-codex-compat` matched source commit `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`; no extracted contract group changed.
- Installed CLI is `0.144.1`; package target remains `0.144.0.r0`. Compatibility docs explicitly keep approval pending and retain incomplete live-test gaps.
- The compatibility README's dirty Rosetta snapshot (`eb947...`, many modified/untracked files) is stale relative to current HEAD `e48f9b1`, but it is clearly described as a dated pending snapshot and the broader live matrix remains unresolved. Track this with the next compatibility report rather than treating it as proof of current approval.

## Independent verification

- Focused changed-area group before final analyzer stabilization: **181 passed**.
- Final analyzer focused test after F-02 repair: **10 passed**.
- Final full suite: `make test` — **2822 passed, 5 skipped, 9 warnings**.
- Static gate: `make lint` passed Ruff, format check for 299 files, `ty check`, and the Complexipy snapshot ratchet.
- Codex source contract: `make check-codex-compat` passed, `Changed: None`.
- Release version: `make check-release-version RELEASE_TAG=v0.144.0.r0` passed.
- Wheel build: `python -m build --wheel` passed and produced `codex_rosetta-0.144.0.post0-py3-none-any.whl`.
- Diff hygiene: `git diff --check` and `git diff --cached --check` passed.
- Complexity gate: the baseline-aware ratchet passed; an isolated temporary complexity-26 probe was independently confirmed to fail and was removed.
- Commit integrity: each of `a9823ea`, `3353a32`, `c8f295e`, `3d97198`, and `2c29d36` contains exactly one `Maintenance-Audit: true` trailer.
- Diff hygiene for the committed F-02 tree: the post-commit `git status --short`, `git diff --check`, and `git diff --cached --name-only` initially produced no output. A later final-state check found a new concurrent unstaged analyzer/test diff; no test result in this report is attributed to that later dirty tree.
- Not run: credentialed live providers/Codex/agentabi, browser Admin smoke, external GitHub Actions, vulnerability/license/SBOM/signing checks, production deploy/rollback, backup/restore, hostile DNS/proxy, and production load.

## Simplification pass

- F-01 was repaired inside the existing stats handler without adding a second request wrapper.
- F-02 uses schema-specific parsers for the two official JSONL formats; generic structured-failure collection is bounded and has no provider failover authority.
- F-03 shares the existing request-stat entry point instead of adding endpoint-specific counters.
- F-04 uses a regression ratchet rather than a broad rewrite. Future hotspot cleanup should begin with protected stream-generator and Responses converter behavior.

## Repair follow-up

All four findings were repaired in five atomic commits. F-02 was integrated only
after its independently prepared blobs matched the audited analyzer working tree.

| Finding | Status | Commit | Verification |
| --- | --- | --- | --- |
| F-01 stats I/O isolation | Resolved | `a9823ea` | Write, flush, and active-line close failures are non-throwing; focused logging tests passed |
| F-03 embeddings stats | Resolved | `3353a32` | Endpoint regression confirms resolved upstream model counting |
| F-04a analyzer static checks | Resolved | `c8f295e` | `make lint` now includes the maintained analyzer in Ruff, format, and ty |
| F-04b complexity gate | Resolved | `3d97198` | Official Complexipy snapshot watermark covers 25 non-vendored hotspots; a temporary new complexity-26 function failed the gate |
| F-02 session/trace schemas | Resolved | `2c29d36` | Separate session/trace evidence paths; terminal-only conservative failover eligibility; 10 focused tests passed |

Final post-repair verification: `make test` returned **2822 passed, 5 skipped,
9 warnings**; `make lint` passed Ruff, formatting for 299 files, ty, and the
Complexipy ratchet. Each repair commit contains exactly one
`Maintenance-Audit: true` trailer. HEAD is `2c29d36`; its committed tree and
scratch-child blobs were verified identical. The final observed working tree has
new, preserved unstaged modifications in the analyzer and its test that are not
part of Round 21.
