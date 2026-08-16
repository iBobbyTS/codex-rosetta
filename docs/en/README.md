# Codex-Rosetta User Documentation

## Compatibility

- [Codex version compatibility](version-compatibility.md)
- [Codex model catalog field reference](codex-model-catalog.md)

## Current Protocol Support

The currently developed and supported gateway paths are:

- OpenAI Responses to OpenAI Chat Completions conversion;
- Direct OpenAI Responses transport for every Provider, with model-group Tool Profile changes plus Rosetta-managed plaintext handoff for model-switch compaction.

Anthropic and Google conversion remain internal options and are not currently guaranteed. Tool Profiles may declare Chat, Responses, Anthropic Messages, and Google GenAI applicability; the Admin UI filters model-group choices by that protocol. Chat and Responses Providers retain their bundled defaults, while Anthropic and Google Providers use no Profile unless one is selected explicitly. Provider selection never changes same-format Responses protocol handling.

## Gateway operations

- [Security and authentication](gateway-security.md)
- [Web Admin and desktop app](desktop.md)

The terminal supports four logging levels:

```bash
codex-rosetta-gateway --log-level info
codex-rosetta-gateway --log-level stats
codex-rosetta-gateway --log-level warning
codex-rosetta-gateway --log-level error
```

Use `codex-rosetta-gateway --with-web-run` to start the optional browser/PDF
sidecar together with a host-run gateway. The CLI selects the first available
loopback port from `8766`, waits for Chromium readiness, and manages cleanup.

`warning` is the default and suppresses normal per-request output while
retaining warnings and errors. `stats` maintains per-model request counts on a
single refreshed line, keyed by each provider's original upstream model name
rather than its exposed alias, for example `model-1: 12, model-2: 7`. A warning
or error starts on a new line, and the counters resume on the next request.
`info` prints request summaries; `error` prints errors only. For complete
request history, use **Request Log** in the WebUI. For streaming trace
diagnostics, use **Gateway Logs** in the WebUI.

### Provider Base URLs and Credentials

A Provider stores an ordered, non-empty `base_urls` list and one member as
`current_base_url`. The existing **Providers** page edits that order and shows
each URL as available, cooling, or current. Selecting a cooling URL makes it
current immediately and clears only that URL's cooldown.

Before any client-visible output, a literal upstream HTTP 502 is retried on the
same URL after 1, 2, 4, 8, and 16 seconds. Only six consecutive 502 responses
cool that URL and silently try the next non-cooling URL, which receives the same
retry budget. A narrowly recognized CDN 502 page still rotates immediately and
is not retried. Failed URLs cool for one hour in process memory, while the
current URL is persisted. Streaming requests with failover disabled are not
retried. Search Provider passthrough requests use the same retry-before-rotation
behavior and retain one logical Search Provider request-budget charge.

Each Provider also stores an ordered, non-empty `api_keys` list of stable IDs
and masked credentials, plus a member `current_api_key`. A literal upstream HTTP
503 is retried on the current credential after 1, 2, 4, 8, and 16 seconds. Only
six consecutive 503 responses cool that credential and rotate to the next
non-cooling credential, which receives a fresh retry budget. This applies to
normal, streaming, passthrough, and Search Provider requests; internal Search
retries retain one logical request-budget charge. Streaming requests with
failover disabled remain single-attempt. Only 503 rotates the credential ring;
502 rotates only the URL ring, and either ring can advance without resetting
the other. A failed credential cools for one hour, and exhausting the finite
ring reports only its size. Manual selection may restore a cooling entry and
clears only that entry's cooldown. Successful request counts never rotate
credentials.

## Codex tool localization

- [Basic conversation](codex-tool-localization/basic-conversation.md)
- [Code editing](codex-tool-localization/code-edit.md)
- [Other tools](codex-tool-localization/other-tools.md)
- [Real-agent tool test results](tools/real-agent-test-results.md)

For architecture notes, source contracts, and maintenance procedures, see the
[developer documentation](../dev/README.md).
