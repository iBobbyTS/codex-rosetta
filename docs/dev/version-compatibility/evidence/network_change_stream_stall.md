# Network Change Stream Stall
Date: 2026-07-12
Codex version: 0.144.0

Historical compatibility evidence; use the maintained ledger and reports for
current conclusions.

## Confirmed observations

- Codex-to-Gateway localhost connections survive Wi-Fi and Tailscale route changes while the Gateway-to-provider TCP stream can become a black hole.
- Gateway model requests use streaming responses and wait up to 300 seconds for each upstream read before surfacing an error.
- Codex defaults to four request retries and five stream reconnect attempts, but those retries cannot start until Rosetta returns or drops the stalled stream.
- Streaming model connections are not returned to the vendored connection pool, so stale pooled connection reuse is not the primary cause.
- Vendored `wait_closed()` calls are not bounded, but project rules prohibit modifying vendored sources directly.

## Current hypothesis

The apparent global stall is delayed error propagation: Rosetta keeps the local SSE response open while its upstream socket is black-holed, so Codex sees no retryable failure.

## First repair attempt

- Bound upstream streaming response establishment to 30 seconds.
- Bound upstream parsed and raw SSE inactivity to 60 seconds.
- Bound transport-layer response cleanup to 2 seconds.
- Drop the downstream stream on timeout so Codex owns retry/reconnect behavior; do not replay partially delivered streams inside Rosetta.

## Manual result and second repair

- Manual network switching no longer leaves the Gateway permanently stuck.
- The first repair passed the 30-second stream-open timeout into the vendored response, unintentionally making body inactivity time out at 30 seconds instead of the intended 60 seconds.
- Use 30 seconds only for the outer response-open deadline and 60 seconds for established stream reads.
- Normalize vendored stream timeout/connection errors to a network-only domain exception.
- Record that expected exception as one traceback-free `ERROR` line and an incomplete 502 stream outcome so Codex can reconnect.

## Verification

- `tests/gateway/test_http_transport_limits.py`: 39 passed.
- Transport, Responses passthrough, telemetry, EOF, trace, and phase-buffer regression set: 83 passed.
- `conda run -n llm-rosetta make lint`: Ruff, format, ty, and complexity checks passed.
- Second-repair transport/stream regression set: 87 passed; full lint passed.
- Manual verification remains: switch Wi-Fi or enable Tailscale during a live Codex turn, then confirm a retry succeeds without restarting Rosetta.
