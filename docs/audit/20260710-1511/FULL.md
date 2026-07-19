# Codex-Rosetta Audit Ledger

| Area | Status | Severity | Files | Notes |
| --- | --- | --- | --- | --- |
| Repository reality and change scope | Reviewed | No Action | worktree, recent commits, audit profile | Final state verified after repairing both findings |
| Gateway request lifecycle | Reviewed | No Action | `gateway/app.py`, `gateway/proxy.py`, `gateway/state_scope.py` | Entry, cleanup, streaming, and state isolation sampled |
| Authentication and admin control plane | Reviewed | No Action | `gateway/auth.py`, `gateway/cors.py`, `gateway/admin/routes/*` | Fail-closed auth, Admin CORS, config CAS/activation, and credential reveal sampled |
| Persistence and observability | Reviewed | No Action | `gateway/logging.py`, `observability/*`, `gateway/stream_trace.py` | Body-log redaction and independent level contract repaired and verified |
| HTTP transport and vendored runtime | Reviewed | No Action | `gateway/transport/*`, `_vendor/*` | Limits, redirects, proxy behavior, upstream baseline, and resource cleanup sampled |
| Converter and image paths | Reviewed | No Action | `converters/google_genai/*`, `converters/openai_responses/*` | Remote-image SSRF/deadline/worker and protocol semantics sampled |
| Release, Docker, and CI | Reviewed | No Action | `.github/workflows/*`, `Makefile`, `docker/*`, release docs/scripts | Local wheel source, release version, workflow permissions, and runtime defaults sampled |
| Test portfolio and independent verification | Reviewed | No Action | `tests/*` | Full suite, body-log contracts, and isolated Compose matrix green |

## Repository reality and audit framing

- **Status:** Reviewed.
- **Severity:** No Action.
- **Scope:** Current `master` worktree at `eb94742`; `git status --short`; `git diff --stat`; `.agent-work/audit/PROFILE.md`; current AGENTS instructions.
- **Focus:** Current repository state, audit scope, high-risk change surfaces, project profile, and evidence boundaries.
- **Evidence:** The final `master` worktree remains at `eb94742`, with 98 modified tracked files, 33 non-ignored untracked files, no staged diff, and a final tracked diff of 9,287 insertions and 1,787 deletions. The repository has `.codegraph/`. The profile is `Draft` and explicitly excludes a full security/admin/deployment audit, but the present changes materially alter those surfaces; this audit therefore extended coverage where the diff created risk. The two findings were repaired only in their logging/config-activation/test/documentation boundary; unrelated user work was preserved.
- **Verification:** Final `git status --short`, `git diff --stat`, `git diff --check`, `git diff --cached --check`, and `codegraph sync` completed; CodeGraph reported `Already up to date`.
- **Gaps / Assumptions:** The intended final deployment model is not established. No credentialed live provider/API check is assumed; the Compose smoke used an isolated synthetic 501 upstream to exercise the real cross-format gateway path.

## Gateway request lifecycle

- **Status:** Reviewed.
- **Severity:** No Action.
- **Scope:** `gateway/app.py` request parsing, authenticated `GatewayStateScope`, non-streaming/streaming instrumentation and cleanup; `gateway/proxy.py` direct and converted paths, stream generators, web-search continuation, state stores, and shutdown cleanup.
- **Focus:** Authentication-before-routing, request/window ownership, state cleanup on success/error/cancel, stream telemetry finalization, active-stream accounting, upstream resource closure, and bounded stores.
- **Evidence:** `_proxy_handler()` rejects requests without an authenticated principal, creates principal/provider/model/window-scoped state, clears non-persistent stores in `finally`, and defers cleanup to `_InstrumentedStream` for open streams. Stream generators close upstream resources via async context managers and record terminal outcomes in `finally`. App shutdown closes image workers and transport, then clears root stores.
- **Verification:** Relevant lifecycle tests were inspected; the final 2,737-item non-integration suite passed with 2,732 passed and 5 skipped.
- **Gaps / Assumptions:** No real client-disconnect/provider stream was exercised in this round. Existing opt-in browser/live-provider tests were not run.

## Authentication and Admin control plane

- **Status:** Reviewed.
- **Severity:** No Action.
- **Scope:** `gateway/auth.py`, `gateway/cors.py`, `gateway/config.py`, `gateway/admin/routes/auth.py`, `keys.py`, `_shared.py`, config/observability/testing routes, and Admin route registration.
- **Focus:** `/v1` fail-closed behavior, constant-time credential checks, principal identity, direct-peer rate limiting, Admin token/CORS boundaries, JSON validation, config compare-and-swap, runtime activation rollback, key deletion/reveal controls, and untrusted provider-to-DOM flow.
- **Evidence:** All `/v1` paths require an access key or private internal token; keys map to stable configured IDs. Admin API requires the derived token except login/auth-check/preflight; CORS allowlists are canonicalized and applied live. Config writes lock, digest-check, atomically replace, activate under the lock, and compensate runtime/file state on failure. Credential reveal remains feature-gated.
- **Verification:** Full auth/Admin/config tests passed, including the prior browser test's default skip contract.
- **Gaps / Assumptions:** No reverse-proxy deployment, real browser login, or external-origin request was run this round.

## Persistence and observability

- **Status:** Reviewed.
- **Severity:** No Action after repair.
- **Scope:** `observability/redaction.py`, `error_dump.py`, `metrics.py`, `persistence.py`, `retention.py`, `tool_mapping_crypto.py`; `gateway/stream_trace.py`, `gateway/logging.py`, and logging call sites in `gateway/proxy.py`.
- **Focus:** Token confidentiality, diagnostic retention, tool-history encryption/integrity, quotas, migrations, rollback, public health payloads, and console logging.
- **Evidence:** Persistence, metrics, upstream-error logs, stream traces, and body logs now use the current configured-token set. `BodyLogState` is app-owned, redacts the complete structure before JSON serialization, escapes it to one line, bounds output at 20,000 characters, and uses constant fallbacks for redaction/serialization failures. Proxy paths pass the same state through ORIGINAL REQUEST, IR REQUEST, CONVERTED REQUEST, and UPSTREAM RESPONSE logging. Admin activation prepares the replacement redactor before commit and rolls back enabled/redactor state on activation failure; separate app instances retain separate policies. The dedicated `codex-rosetta-gateway.body` DEBUG child logger allows body records through DEBUG-capable console/file handlers while the parent logger's INFO/DEBUG level independently gates ordinary gateway DEBUG noise.
- **Verification:** Initial targeted tests returned 20 passed; expanded logging/redaction/reload/isolation/passthrough/stream tests returned 86 passed. Final full suite returned 2,732 passed, 5 skipped, 9 warnings. Isolated Compose runtime tests exercised all four `(verbose, log_bodies)` combinations on a real Responses-to-Chat cross-format path: body records appeared only when requested; the normal `inject: store has 0 entries: []` DEBUG record appeared only with verbose; both could appear together; and configured gateway/provider token values were replaced with `[REDACTED]` in ORIGINAL/IR/CONVERTED records while ordinary prompt text remained.
- **Gaps / Assumptions:** Body logging remains opt-in and intentionally preserves prompt/PII plus ordinary `password`, `secret`, `client_secret`, and proxy-password data. This repair protects configured tokens and explicit token/Bearer/API-key fields; it is not a general privacy scrubber. The Compose smoke used a synthetic upstream and did not receive a successful upstream response body, while unit tests cover UPSTREAM RESPONSE logging.

### Finding F-01: Opt-in body logging writes configured credentials verbatim

- **Resolution:** Resolved in the current worktree.
- **Trigger:** Enable body logging and a DEBUG-capable handler (`debug.log_bodies=true` plus verbose/DEBUG), then process a request, converted request, or upstream response containing a configured gateway/provider token or an explicit token/Bearer field.
- **Impact:** Credentials can enter stderr, container logs, terminal scrollback, or a centralized log collector. Anyone with log access can reuse them against the gateway or upstream provider. This contradicts the profile's credential-not-logged baseline and is not covered by current token-redaction tests.
- **Recommended priority:** Must Fix before treating the diagnostic hardening as complete.
- **Implemented repair:** Added app-owned `BodyLogState` using `SecretRedactor`; redaction occurs before serialization/truncation with no raw-object fallback. App creation, request handlers, non-streaming/streaming proxy paths, and Admin config activation/rollback now carry the state and current token set. Tests cover exact configured tokens, Bearer/Authorization/API-key fields, JSON-encoded function arguments, retained non-token content, constant failure fallbacks, hot reload, rollback, and multi-app isolation.
- **Resolution evidence:** The final full suite and Compose cross-format smoke passed; neither synthetic configured token appeared in runtime logs, while the ordinary body marker did appear when body logging was enabled.

### Finding F-02: `log_bodies=true` reports enabled while an INFO handler drops every body record

- **Resolution:** Resolved in the current worktree.
- **Trigger:** Configure `debug.log_bodies=true` or `CODEX_ROSETTA_LOG_BODIES=true` without also enabling verbose logging.
- **Impact:** `cli.py:373-375,391-392` reports body logging enabled, but `setup_logging()` sets `_log_bodies=True` while leaving the handler at INFO (`logging.py:257-282`); every body is emitted with `_logger.debug()` and discarded. Operators can believe evidence was captured when it was not, making debugging and incident reconstruction unreliable.
- **Recommended priority:** Should Plan together with F-01 because changing levels affects the security exposure of body data.
- **Implemented repair:** Body records now use the dedicated `codex-rosetta-gateway.body` DEBUG logger. Configured handlers accept DEBUG records, while the parent gateway logger remains INFO unless verbose is enabled. Body logging therefore works without enabling unrelated DEBUG output, and verbose alone does not enable body records. CLI text and English/Chinese security docs state the contract.
- **Resolution evidence:** Unit tests cover console and `FileHandler` output for all four combinations. The Compose matrix independently showed F/F = neither, F/T = body only, T/F = ordinary DEBUG only, and T/T = both.

## HTTP transport, vendored runtime, and image conversion

- **Status:** Reviewed.
- **Severity:** No Action.
- **Scope:** `gateway/transport/http/transport.py`, `_vendor/httpclient.py`, `_vendor/httpserver.py`, `_vendor/sse.py`, `converters/google_genai/image_fetch.py`, and `gateway/image_workers.py`.
- **Focus:** Header/body/SSE limits, content encoding, chunk handling, SSRF, DNS rebinding, redirect validation, proxy ownership, cancellation, queue bounds, and shutdown.
- **Evidence:** Direct image fetches reject non-public/mixed DNS answers, pin validated numeric destinations, revalidate redirects, disable environment proxies, and bound body/MIME/deadline behavior. Blocking conversion runs in a fixed app-owned daemon pool whose permit remains held until raw work exits. The vendored files match the captured upstream zerodep working tree except for the install-note spelling; upstream provenance is recorded under `.agent-work/upstream/` and the prior audit baseline.
- **Verification:** Focused transport/image tests and the full suite passed.
- **Gaps / Assumptions:** `getaddrinfo()` itself cannot be interrupted; four indefinitely stuck resolver calls can exhaust image workers. Current docs and tests explicitly preserve the rule that capacity is not released until raw work exits, so this was not reclassified as a new finding. No hostile live DNS/proxy server was used.

## Release, Docker, CI, and test portfolio

- **Status:** Reviewed.
- **Severity:** No Action for current implementation; governance gaps remain Track as Debt.
- **Scope:** `.github/workflows/ci.yml`, `sdk-compatibility.yml`, `Makefile`, `pyproject.toml`, Docker files, release script/docs, current tests, and Codex compatibility ledger/checker.
- **Focus:** Required CI gates, Python versions, write permissions, wheel provenance, disabled publishing, non-root runtime, version/tag matching, Codex source drift, and missing integration evidence.
- **Evidence:** CI runs lint/type/full non-integration tests on Python 3.10 and 3.13; the schedule/manual SDK monitor has narrow issue-write permission. Docker builds require a current-checkout wheel and run the app as a non-root user. Publishing targets fail closed. The local version/tag and Codex static-contract gates pass.
- **Verification:** `conda run -n llm-rosetta make lint` passed Ruff check, a 293-file format check, and `ty`; `conda run -n llm-rosetta make test` collected 2,737 and returned 2,732 passed/5 skipped/9 warnings; `conda run -n llm-rosetta make build` produced the sdist and wheel; `make check-codex-compat` reported Changed: None with 12 Possibly unchanged groups; `make check-release-version RELEASE_TAG=v0.144.0.r0`, `git diff --check`, and `git diff --cached --check` passed. The local wheel also built and ran in the isolated Compose body-log matrix.
- **Gaps / Assumptions:** No credentialed integration/agentabi/live Codex/provider matrix, external Actions run, vulnerability/license scan, load/cost test, backup/restore drill, or real release/deploy/rollback. The audit profile still lacks owner-approved ASVS/SLO/signing/SBOM/dependency policy.

## Simplification pass

- The repair reuses `SecretRedactor` and the app-owned configuration activation lifecycle; no second field-by-field sanitizer or module-global mutable redactor was introduced.
- Do not broaden token-only diagnostics into a general PII scrubber without an owner decision; the current security documentation deliberately preserves other body content.
- The proxy changes remain state plumbing at existing logging call sites; no structural rewrite or parallel logging pipeline was introduced. No follow-up cleanup is required for these two findings.
