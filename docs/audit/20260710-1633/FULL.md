# Codex-Rosetta Audit Round 19 — Full Ledger

| Area | Status | Severity | Files | Notes |
| --- | --- | --- | --- | --- |
| Repository state and current diff | Reviewed | No Action | `git status`, `git diff --stat`, audit ledger | Large pre-existing dirty worktree preserved; no staged diff |
| Converted upstream SSE transport | Reviewed | No Action | `gateway/transport/_base.py`, `gateway/transport/http/transport.py` | F-01 fixed with a typed, body-free fail-closed protocol error |
| Converted and web-search stream lifecycle | Reviewed | No Action | `gateway/proxy.py`, `gateway/app.py` | Stable 502-class terminal state exactly once |
| Direct Responses raw passthrough | Reviewed | No Action | `_raw_stream_event_generator`, `HttpUpstreamStream.aiter_raw_bytes()` | Remains byte-preserving and wire-size bounded; JSON is intentionally not parsed |
| Diagnostic confidentiality | Reviewed | No Action | transport, body log, request log, stream trace | Malformed event content does not enter ordinary/body logs or terminal diagnostics |
| Documentation and tests | Reviewed | No Action | bilingual security docs; transport/telemetry/trace tests | Runtime contract and regression coverage updated together |

## Audit framing

- Profile: `.agent-work/audit/PROFILE.md` (`Draft`).
- Highest-priority attributes: compatibility correctness, reliability, security/privacy, operability, then modifiability.
- Sampling focus: high-churn Gateway transport, stream lifecycle, logging/redaction, state isolation, persistence encryption, Admin auth/CORS, release/CI and Docker paths. Previous round reports were checked to avoid re-reporting resolved findings.
- Repository reality at audit start: `master` at `eb94742`, ahead of `origin/master` by one commit, with a large pre-existing unstaged/untracked worktree. No user work was reset, removed, staged or committed.

## F-01 — Malformed upstream SSE bypassed diagnostic redaction and was silently dropped

- Status: **Resolved**.
- Original severity: **Must Fix**.
- Scope:
  - `src/codex_rosetta/gateway/transport/_base.py`
  - `src/codex_rosetta/gateway/transport/__init__.py`
  - `src/codex_rosetta/gateway/transport/http/transport.py`
  - `tests/gateway/test_http_transport_limits.py`
  - `tests/gateway/test_stream_telemetry_lifecycle.py`
  - `tests/gateway/test_stream_trace.py`
  - `docs/en/gateway-security.md`
  - `docs/zh-cn/gateway-security.md`
- Original evidence: `HttpUpstreamStream.__aiter__()` caught `JSONDecodeError`, wrote `event.data[:200]` directly to the ordinary warning logger, silently skipped the event, and could subsequently end as a successful stream. A minimal reproduction logged `secret-token=sk-live-should-not-log` verbatim while yielding a later JSON event.

### Resolution

- Added exported `UpstreamProtocolError`, a typed `UpstreamConnectionError` with the stable message `Upstream SSE data is not valid JSON`.
- Converted SSE parsing now preserves comments/keepalives, empty `data:`, `[DONE]`, and valid JSON. Any other non-empty `data:` event closes the upstream and raises the stable typed error with `from None`; raw data and the JSON parser exception never enter the message, ordinary logs, or body logs.
- `HttpUpstreamStream.close()` is idempotent. Normal completion, malformed protocol failure, HTTP error pre-read, explicit repeated close, parsed-stream cancellation, raw-stream cancellation, line/event overflow and outer async-context cleanup call the underlying response close at most once.
- Converted and web-search generators propagate the typed failure. Their stream profile/trace writes one terminal `error` record; the outer `_InstrumentedStream` writes one request-log/metrics outcome with status 502 and cannot later reinterpret EOF as success.
- Same-protocol Responses direct streaming remains byte-preserving. It applies wire-size envelopes but intentionally does not parse provider JSON, so malformed JSON bytes pass through unchanged rather than being reclassified by the converted-stream contract.
- English and Chinese Gateway security docs now describe the converted fail-closed and direct raw-passthrough distinction.

### Regression evidence

- Sensitive malformed payload cases: configured token, Bearer token, prompt text and plain password. None appears in ordinary or body logger capture; the stable exception is body-independent.
- Malformed input consumes no later event, closes once, and raises `UpstreamProtocolError`.
- Comments, empty data, JSON and `[DONE]` preserve their previous behavior.
- HTTP streaming error pre-read plus repeated outer cleanup closes once.
- Parsed and raw cancellation close once.
- Outer metrics/request log records exactly one 502 with `stream_complete=false`; a second iterator read produces `StopAsyncIteration` without double finalization.
- Converted and web-search stream traces contain exactly one safe terminal failure and no untrusted body.
- Direct Responses raw-passthrough test preserves malformed bytes without invoking the JSON parser.

## Verification

- Expanded targeted suite: `55 passed` across HTTP limits, telemetry lifecycle, stream trace, direct Responses passthrough and web-search bridge, including close-on-cancel assertions.
- `make lint`: passed (`ruff check`, `ruff format --check` for 294 files, `ty check`).
- `make test`: **2,752 passed, 5 skipped, 9 warnings**.
- `make build`: produced `codex_rosetta-0.144.0.post0.tar.gz` and `codex_rosetta-0.144.0.post0-py3-none-any.whl`.
- `make check-codex-compat`: passed, source `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`, `Changed: None`.
- `make check-release-version RELEASE_TAG=v0.144.0.r0`: passed.
- Isolated Compose smoke built the current wheel, ran Gateway `0.144.0.r0`, and used a loopback fake Chat SSE upstream. The client received HTTP 200 streaming headers followed by a connection failure before any downstream event (stream status was already committed); container logs contained only `Upstream SSE data is not valid JSON`, never the configured-token/Bearer/prompt/password malformed body. Persisted request telemetry was exactly one row with status 502, the stable error, `stream_complete=false`, and `stream_outcome=error`. The isolated container, network, local image and fake upstream were stopped/removed; unrelated Docker workloads were untouched.
- Final repository reality check: `git diff --check` passed; `master` remained one commit ahead of `origin/master` with the pre-existing unstaged/untracked audit worktree and no staged diff; `.agent-work/audit/CURRENT.md` was absent.
- `codegraph sync`: passed (`Already up to date`).

## Source review for related sinks

Repository-wide review of `except JSONDecodeError`, malformed-SSE messages, `event.data`, and response logging found no second runtime malformed-SSE body warning sink. Other JSON decode fallbacks operate on tool arguments or local diagnostic JSONL and do not log the rejected input. Integration-test helper parsers that skip malformed data are not shipped runtime sinks.

## Simplification pass

The repair deletes the data-bearing permissive fallback and extends the existing transport error hierarchy. It does not add a transport redactor, second SSE parser, provider-specific state machine, or duplicate telemetry owner. Direct raw passthrough remains separate by design.

## Gaps and assumptions

- The audit profile remains `Draft`; owner, privacy/legal baseline, ASVS target, SLO/error budget, incident response and supply-chain/signing requirements remain governance inputs.
- No credentialed external provider/Codex/agentabi test, external GitHub Actions run, production deployment, backup/restore exercise, vulnerability/license/SBOM scan or artifact signing was performed.
- No commit, push, PR, release or deployment was created.
