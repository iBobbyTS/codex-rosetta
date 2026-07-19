# Codex-Rosetta Audit Ledger

Audit started: 2026-07-10 09:14 MDT
Repair closure: complete on 2026-07-10 MDT
Profile: `.agent-work/audit/PROFILE.md` (Draft)

| Finding | Status | Severity | Primary owner | Resolution |
| --- | --- | --- | --- | --- |
| F-01 upstream error logs accepted raw secrets and forged lines | Resolved | Must Fix | `gateway/logging.py` live per-app state | Token-only redaction, single-line escaping, 4,096-character cap, hot reload and rollback |
| F-02 Google URL-image timeout/concurrency was not a total bounded Gateway resource | Resolved | Must Fix | `google_genai/image_fetch.py`, `gateway/image_workers.py` | Monotonic fetch deadline, cooperative close, app-owned bounded workers, permit held until raw future exits |
| F-03 request-log retention accepted unsafe values and negative SQLite limits | Resolved | Must Fix | `observability/retention.py` | One startup/reload/direct validator, 0..1,000,000 contract, immediate zero convergence |
| F-04 upstream response bodies were fully aggregated without transport caps | Resolved | Must Fix | `gateway/transport/http/transport.py` | Identity-only upstream responses and incremental success/error byte limits |

## Repository reality

- The repair continues on the existing large dirty `master` worktree. No reset,
  revert, staging, commit, push, release, or deployment was performed.
- No file under `src/codex_rosetta/_vendor/**` was modified.
- CodeGraph was used before direct source searches to confirm the four owner and
  caller paths.

## F-01: live upstream-error log boundary

- **Status:** Resolved.
- **Resolution:** `UpstreamErrorLogState` is owned by each app and uses the live
  config plus internal-token set. Admin config activation prepares, commits, and
  compensates the redactor together with auth, trace, metrics, and persistence.
  Upstream error JSON and explicit authorization/token/API-key assignments are
  redacted without hiding prompt, PII, ordinary password/secret/client-secret
  content. C0/C1 controls, CR/LF, and Unicode line separators are escaped; the
  final line is capped at exactly 4,096 characters. The no-state fallback also
  sanitizes and never logs the original raw value.
- **Call paths:** Both direct and converted non-streaming errors, and both direct
  and converted streaming errors, pass the current app state. The policy is
  independent of request-body logging.
- **Evidence:** `tests/gateway/test_upstream_error_logging.py` covers targeted
  fields, Unicode/control characters, exact truncation, stream/non-stream
  fallback, hot reload, rollback, and multi-app isolation.

## F-02: one image-fetch deadline and app-owned worker capacity

- **Status:** Resolved.
- **Resolution:** One monotonic deadline now covers validation/DNS, connect,
  redirects, headers, and each incremental body read. Direct connections retain
  public-address validation and numeric pinning; every redirect is revalidated.
  Active connections and responses register cooperative closers. The Gateway
  runs Google request conversion in a per-app four-worker owner. Queue timeout,
  task timeout, cancellation, and shutdown signal the fetch token; a permit is
  returned only by the raw `Future` done callback, so stuck DNS cannot create
  unbounded threads or false capacity.
- **Error semantics:** Worker capacity maps to 503 and conversion/fetch deadline
  expiry maps to 504 rather than a client conversion 400. Direct synchronous
  conversion still checks the same fetch deadline and rejects results that
  arrive after it.
- **Evidence:** Image tests cover slow-drip bodies and DNS completion after the
  deadline. Worker tests cover queue saturation, timeout without early permit
  release, recovery after raw exit, cancellation token signaling, event-loop
  responsiveness, and isolation between two owners.

## F-03: strict request-log retention contract

- **Status:** Resolved.
- **Resolution:** `observability/retention.py` is the single validation source.
  `success_max`, `error_max`, legacy `max_entries`, and both environment
  overrides must be non-boolean integers from 0 through 1,000,000. Validation
  occurs while constructing `GatewayConfig`, so startup and Admin candidate
  commits return stable configuration errors before persistence mutation.
  `PersistenceManager` reuses the same validator for direct construction and
  prepared policy updates. A zero cap immediately deletes all rows of that
  request class inside the existing activation transaction, and compensation
  restores pruned rows after a later failure.
- **Independent contract:** Error-dump retention remains the established fixed
  10,000-entry count-only policy.
- **Evidence:** Tests cover config and environment invalid values, bool, zero,
  maximum, legacy precedence, direct persistence calls, immediate zero prune,
  hot reload, rollback, restart behavior, and app isolation.

## F-04: bounded upstream transport bodies

- **Status:** Resolved.
- **Resolution:** Non-streaming HTTP calls now request `stream=True` and collect
  incrementally in the gateway transport instead of using the vendored client's
  unbounded aggregate path. All upstream requests force
  `Accept-Encoding: identity`; a non-identity response is closed before body
  iteration. Therefore observable wire payload bytes and decoded payload bytes
  are identical; chunk framing is excluded. Non-streaming success bodies are
  capped at 50,000,000 bytes. Non-streaming errors and streaming HTTP errors are
  capped at 1,000,000 bytes. Content-Length is rejected before reading and
  chunked/unknown-length bodies are counted per chunk. Successful SSE remains
  incremental without a whole-stream cap.
- **Error semantics and cleanup:** Safety violations subclass
  `UpstreamConnectionError`, so direct/converted non-stream and stream setup
  paths return stable 502 errors. Responses close on success, exception,
  oversize, unsupported encoding, and cancellation. Large bodies are never
  passed to error logging or dump persistence.
- **Evidence:** Transport tests cover normal JSON, forced identity headers,
  oversized Content-Length, incremental unknown/chunked overflow, gzip-bomb
  rejection, bounded streaming errors, normal SSE, and cancellation cleanup.
  Real loopback fixtures exercise success overflow, non-streaming error
  overflow, and streaming error overflow through the vendored streaming client
  without public network access. The existing local embeddings HTTP fixture
  also exercises the real vendored streaming client.

## Documentation and compatibility

- `docs/en/gateway-security.md` was updated first and mirrored at the same path
  under `docs/zh-cn/` with the deadline, worker, identity, body-cap, logging, and
  retention contracts.
- These repairs change generic Gateway safety boundaries, not a Codex-specific
  request, response, stream event, tool, session, or model-catalog contract. No
  new compatibility-ledger point was triggered.

## Verification

- First F-01/F-03 focused run: 61 passed.
- F-02 focused image/worker/lifecycle run: 29 passed.
- F-04 transport/embeddings/Responses run: 13 passed.
- Broader converter/Gateway/observability run: 527 passed, 2 existing warnings.
- Final `conda run -n llm-rosetta make test`: 2,622 passed, 4 skipped, 9
  warnings. This includes the three real loopback F-04 transport fixtures.
- Final `conda run -n llm-rosetta make lint`: Ruff passed, all 288 checked files
  were formatted, and `ty check` passed.
- `conda run -n llm-rosetta make check-codex-compat`: passed against source
  commit `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`; `Changed: None`.
- `conda run -n llm-rosetta make check-release-version
  RELEASE_TAG=v0.144.0.r0`: passed with source version `0.144.0.r0`.
- `git diff --check` and `git diff origin/master --check`: passed with no
  whitespace errors. `git status --short -- src/codex_rosetta/_vendor` was
  empty.
- A wheel was rebuilt from the current source, installed with `--no-deps` into
  an isolated Python 3.14 virtual environment, and all F-01 through F-04 owner
  modules imported from `site-packages`; runtime version was `0.144.0.r0`.
- Final `codegraph sync`: passed and synchronized the one remaining changed
  file since the previous graph update.

## Verification limitations

- `tests/integration/**` was not run because it requires live provider API keys
  and upstream network access; `make test` excludes this directory by design.
- Docker Compose was not run. This round did not change the Dockerfile, Compose
  configuration, or entrypoint, and the current-source wheel build plus
  isolated install/import smoke verifies that the new modules are packaged.
  A Compose smoke remains appropriate before an actual container release.
- The project audit profile remains Draft with owner, legal/privacy,
  vulnerability-response, SLO, build-provenance, and CI-secret-policy fields
  still requiring maintainer decisions. Those profile gaps did not block the
  four concrete safety repairs in this round.

## Maintainability judgment

Each high-risk semantic boundary has one owner: log sanitization, image worker
capacity, retention validation, and HTTP response-body limits. The existing
large `proxy.py` only receives narrow state/worker parameters and stable error
mapping; network loops and validation rules are not duplicated there. Behavior
and failure-path tests cover the new ownership boundaries. No enabling
structural refactor remains necessary before closure.
