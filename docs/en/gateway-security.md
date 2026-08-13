# Gateway Security and Authentication

## Remote compaction retention

Rosetta Remote Compaction V2 stores a plaintext handoff replacement in the
gateway SQLite database for seven days. The returned `encrypted_content` is an
opaque `rskc_v1_` handle, not ciphertext; only its SHA-256 is stored beside the
plaintext. Mappings are isolated by authenticated principal, expire on cleanup,
and are renewed when replayed. A missing, expired, or cross-principal handle is
silently discarded. This logical TTL does not erase rollout files, explicitly
enabled raw traces, test artifacts, backups, or already-freed SQLite pages.

On a same-format Responses route, `context_limit` and `user_requested`
compaction remains native and unchanged. Model-switch compaction, including
`comp_hash_changed` and `model_downshift`, instead uses Rosetta's no-tools
summary request against the previous model. Rosetta stores the plaintext
replacement for seven days and returns an opaque `rskc_v1_` handle so the next
Provider receives replayable plaintext rather than another Provider's encrypted
compaction payload. Routes that convert Responses to another protocol also use
the Rosetta coordinator.

An individual Responses Provider may set `force_rosetta_compaction: true` to
use the Rosetta coordinator for every valid compaction reason, including
`context_limit`, `user_requested`, model-switch reasons, and unknown reasons.
This does not alter ordinary requests or discard existing native compaction
history. If SQLite persistence is unavailable, Rosetta returns HTTP 503 before
calling the summary upstream and never falls back to native compaction. Because
the mapping contains summary plaintext for seven days, protect the Gateway data
directory, backups, and copied test artifacts accordingly.

## Late instruction cache compatibility

The Chat-only compatibility option is a request-local role conversion. It does
not retain model output, continue an abandoned upstream stream, or replay hidden
content. In a request with valid Codex turn metadata, Rosetta preserves the
contiguous leading system/developer prefix. Every system or developer message
after the first ordinary conversation item becomes a separate user-role message with its
content wrapped in `<system>...</system>`. The rule is positional and does not
inspect or special-case `<turn_aborted>` text. Ordinary user messages are
unchanged. The retired plaintext `soft_interrupt_handoffs`
table, if present from an earlier development build, is deleted with all of its
rows on startup. Because the conversion intentionally lowers role precedence,
enable it only when later instruction content is safe to deliver as user text.

Codex-Rosetta fails closed: every gateway configuration must contain a
non-empty Admin password and at least one gateway access key. The default bind
address is `127.0.0.1`, and API credential reveal is disabled by default.

## Initialize a local gateway

```bash
codex-rosetta-gateway init
codex-rosetta-gateway --host 127.0.0.1
```

`init` sets `server.admin_password` to the default password `columbina` and
generates one random `server.api_keys` entry in the config file. Change the
default Admin password before exposing the gateway beyond a trusted local
machine. The config, lock, and backup files
are written with owner-only permissions. Store the generated credentials in a
password manager before distributing them to clients. The `init` command also
prints the default Admin password to the terminal.

The first configured Gateway startup also creates `admin-session.key` beside
`config.jsonc` with owner-only permissions. This independent random secret is
used only to derive the browser Admin token: a normal Gateway restart preserves
the login, while changing the Admin password or deleting the secret invalidates
existing browser sessions. The internal bearer token used by Admin model tests
remains ephemeral and is rotated on every process start. Programmatic
`create_app()` calls without a config path intentionally use an ephemeral Admin
session secret and therefore do not promise login persistence across instances.

Every `/v1` request uses the gateway access key, not an upstream provider key.
Authentication runs before routing, so unknown, removed, and dynamically
registered `/v1` paths fail closed as well. Browser `OPTIONS` preflight remains
public and the subsequent request still requires authentication:

```http
Authorization: Bearer rsk-...
```

Inbound parsing also has fixed process-level resource limits. A request line
must complete within one 15-second monotonic deadline; each header or chunked
trailer section must complete within 30 seconds and may contain at most 100
fields or 64 KiB including framing; and the complete request body must arrive
within one 120-second monotonic deadline. At most 64 connections may occupy the
request parser at once. A 65th connection receives HTTP 503 immediately rather
than waiting for capacity.

For protected `/v1` and Admin API requests, credentials are checked after the
bounded headers but before body bytes are consumed. Invalid credentials are
therefore rejected without buffering a declared large body. Valid requests
default to a 128 MiB body limit. The Admin Server Settings page can change
`server.request_body_limit_mb` at runtime to `64`, `128`, `256`, `512`, `1024`,
or `"unlimited"`; a config reload applies the same setting without restarting
the gateway. Public Admin login/auth-check endpoints and browser `OPTIONS`
preflight remain intentionally unauthenticated; any body they carry is still
covered by the same body deadline, configured size limit, and parser capacity.
Authenticated `/v1` requests with `Content-Encoding: zstd` are decoded before
JSON parsing. The configured body limit is enforced independently on both the
compressed wire body and the decompressed body, using the same current WebUI
setting; requests without that encoding keep the existing uncompressed path.
The unlimited setting removes Rosetta's practical body-size ceiling but still
buffers each body in memory, so use it only on a trusted, memory-controlled
deployment.

Each access-key entry needs a stable, unique `id`. Rosetta uses that ID as the
authenticated principal for cross-turn state isolation; changing a label does
not change identity. The Admin UI rejects deletion of the final access key.

Gateway model identifiers are limited to 256 UTF-8 bytes. The Codex
`x-codex-window-id` header is limited to 128 UTF-8 bytes; current Codex window
IDs use `{UUID}:{window_number}` and are normally about 40 bytes. Requests over
either semantic limit receive a format-appropriate HTTP 400 before routing or
state allocation. These limits prevent request-error reflection and state-key
memory from bypassing the larger body/header and cache-value byte budgets.
External `x-request-id` values are correlation metadata only and must be 1–128
visible ASCII bytes (`!` through `~`). Missing IDs receive a Gateway-generated
UUID. Blank, control-containing, non-ASCII, or oversized IDs receive a
format-appropriate HTTP 400 before body parsing, logging, tracing, persistence,
state allocation, or upstream forwarding. This prevents terminal-control
injection and repeated trace metadata from amplifying diagnostic storage.

Cross-turn in-memory state has principal-fair hard limits. Provider continuation
metadata is limited to 1 MiB per entry, 8 MiB per scope, 1,024 entries and
16 MiB per principal, and 10,000 entries and 64 MiB for the app. Reaching a
principal limit rejects the new state. When the global entry map is full,
Rosetta may replace only the inserting principal's oldest entry; it never evicts
another principal's state. Capacity failures are returned as HTTP 413 before
partial cache mutation. Deferred Code Mode tool discovery does not add
cross-turn Gateway state: it searches Codex's request-local `ALL_TOOLS` runtime
catalog through `exec`. Fixed `tool_search` returns bounded names and summaries;
fixed `tool_read` retrieves one exact complete declaration. Only a paired read
call/result carried into the next request may authorize that exact Node REPL
name through `invoke_deferred_tool`, and Rosetta validates the declaration from
history without retaining a discovery cache. Reading `js` does not authorize
`js_reset` or `js_add_node_module_dir`. Search summaries are at most 240
characters and whole search results stay within 24,000 serialized characters;
exact reads also enforce a 24,000-character fail-closed budget. Discovered Node
tools are never added as top-level Chat Functions, so tool definitions remain
byte-stable across search, read, and invocation; both results remain in history.

## Environment-backed example config

The versioned example uses these required environment variables:

```bash
export CODEX_ROSETTA_ADMIN_PASSWORD='replace-with-a-strong-secret'
export CODEX_ROSETTA_API_KEY='rsk-replace-with-a-strong-secret'
```

Startup fails if either value is empty or unresolved. Provider API keys remain
separate and use their provider-specific environment variables.

Each configured upstream Provider uses exactly one API key. To use multiple
upstream accounts, create a separate named Provider for each account instead of
putting comma-separated keys in one Provider. Legacy comma-separated Provider
values are accepted during migration: after environment substitution, the
Gateway uses the first non-empty trimmed key and ignores the rest. Loading or
viewing the configuration does not rewrite the file; the next successful Admin
save for that Provider persists only the selected first key. This Provider rule
does not change `server.api_keys`, which remains the multi-principal list used
to authenticate Gateway clients.

## Docker and remote access

The container listens on `0.0.0.0` so Docker can publish the gateway. This does
not relax authentication: keep the generated Admin password and gateway access
key, restrict the published port with host/network firewall rules, and place
TLS in front of any non-loopback deployment. `server.credential_visible`
controls raw Gateway/provider API credential reveal in the Admin UI and API;
do not enable it unless that reveal is explicitly needed in a trusted Admin
session. It does not mask userinfo embedded in `server.proxy` or a provider
`proxy` URL. Those connection URLs remain visible to an authenticated Admin,
so keep proxy passwords out of URLs when possible and protect Admin access.

The repository does not publish a Docker image. From the repository root, use
`make compose-up`; it rebuilds the current checkout's wheel and passes that
exact wheel into the versioned Compose build. A plain Compose invocation must
also provide `LOCAL_WHEEL` and must not rely on the old registry image name.

For a gateway running directly on the host, the simplest way to enable the
browser-backed `web.run` service is:

```bash
codex-rosetta-gateway --with-web-run
```

This explicit option requires both Docker and `docker-compose`. The CLI builds
the packaged sidecar context, creates an isolated Compose project, and binds
only to `127.0.0.1`. It starts with candidate port `8766`; occupied ports and
port-allocation races advance to the next port automatically. The generated
bearer token and selected URL override `server.web_run` only for the running
process, continue to apply after Admin config reloads, and are restored on
shutdown. Gateway startup fails closed if the service or Chromium does not
become ready. Normal exit and `Ctrl-C` remove only that invocation's managed
Compose project.

For a gateway that also runs inside Compose, browser-backed `web.run` remains
an optional profile. Start it together with the gateway by supplying a dedicated
random bearer token of at least 24 characters:

```bash
CODEX_ROSETTA_WEB_RUN_TOKEN='<random-sidecar-token>' make compose-up-web-run
```

The Make target is only a convenience wrapper. To use Docker Compose directly,
build the current checkout's wheel, export the values consumed by the Compose
file, and enable the `web-run` profile:

```bash
python -m build --wheel
export LOCAL_WHEEL="$(basename "$(ls -t dist/*.whl | head -n 1)")"
export CODEX_ROSETTA_WEB_RUN_URL='http://web-run:8080'
export CODEX_ROSETTA_WEB_RUN_TOKEN='<random-sidecar-token>'

docker-compose -f docker/docker-compose.yaml \
  --profile web-run up --build -d
```

`LOCAL_WHEEL` must be the filename of a wheel under the repository's `dist/`
directory. The Gateway Dockerfile deliberately installs that wheel so the
container runs the exact local checkout. The token must be the same for the
gateway and sidecar; the Compose network URL must remain
`http://web-run:8080`.

Use the Compose service name for routine inspection, restart, and sidecar-only
stop. Reuse the same environment variables and profile from startup:

```bash
docker-compose -f docker/docker-compose.yaml --profile web-run logs -f web-run
docker-compose -f docker/docker-compose.yaml --profile web-run restart web-run
docker-compose -f docker/docker-compose.yaml --profile web-run stop web-run
```

To stop and remove the complete Compose stack, reuse the exported variables and
profile:

```bash
docker-compose -f docker/docker-compose.yaml \
  --profile web-run down
```

This builds a separate `web-run` service. Compose assigns the project-scoped
container name and does not publish its port to the host; the gateway reaches
it over the private Compose network and receives
`CODEX_ROSETTA_WEB_RUN_URL=http://web-run:8080`. The sidecar receives no gateway
configuration directory or provider credentials. Its bearer token is masked by
the Admin configuration API and Gateway Logs. Outside Compose or the managed
CLI option, configure matching `server.web_run.base_url` and
`server.web_run.token` values (or the corresponding URL/Token environment
variables) explicitly. Sidecar operations default to a 300-second timeout;
`server.web_run.timeout_seconds` accepts values from 1 through 600 seconds.

The Admin **Web Search** page stores the canonical
`server.web_search.providers` list of at most 32 basic-search Providers. The
retired single-Provider object is rejected. It can use Tavily credentials,
**Self-hosted (Google)**, **Self-hosted (Bing RSS)**, or
**Self-hosted (Bing Browser)** in the existing sidecar. It can also select an
enabled configured Responses Provider and one of the existing reviewed Search
Models; in that mode the Gateway sends the
unchanged Codex Search body to the Provider's `alpha/search` endpoint with that
Provider's existing credential, proxy, and redirect policy. Disabled and
non-Responses Providers are rejected during configuration. The page can also
select an already configured DeepSeek Provider only when it is enabled, uses
the `deepseek` identity and Responses protocol, has exactly one credential, and
resolves to the official `https://api.deepseek.com` origin. This row stores only
the configured Provider name and calls the official Responses `web_search` tool
with fixed `deepseek-v4-flash`; it accepts only `search_query.q`, one query per
request. Domains, recency, location, multiple queries, server history,
`deepseek-v4-pro`, usage, and credit/quota display are not supported. The
self-contained Admin view derives, rather than saves, each row's provider
family, execution mode, and capability summary from Rosetta's Web Search
Provider contract. GPT rows display only their Responses Provider and Search
Model and preserve the complete configured Responses `/alpha/search`
passthrough only when the entire ordered chain is GPT. Tavily rows display only
their Tavily key and existing quota view; DeepSeek rows display the configured
Provider selector and read-only `deepseek-v4-flash` model with an empty quota
cell; self-hosted rows display no GPT- or Tavily-specific fields. Local-only chains expose the local query-adapter
capabilities, while mixed GPT/local chains display and enforce the safe
single-`search_query` intersection. These derived summaries never include
credentials, fingerprints, sidecar connection values, or upstream-private
data, and do not alter the persisted Provider-row wire format. DeepSeek uses
its own native Responses family and adapter rather than GPT's `alpha/search`
passthrough or the Tool Catalog.

One row is the sticky current Provider. A Provider search failure starts one
circular pass over the other eligible rows, with each row attempted at most
once; the first successful row is persisted as current for subsequent requests.
An unsupported search sub-tool is returned as unavailable for the current
Provider and does not trigger failover or cooldown. The self-contained
**Search Test** card sends the fixed query
`latest python release version` through the same Gateway auxiliary handler as a
real `POST /v1/alpha/search` request and displays normalized result cards; it does not call
Tavily, the sidecar, or a Provider-specific search client directly. The
self-contained Admin boundary never displays a Provider's raw failure body:
authorization, timeout, rate-limit, unavailable, and rejected outcomes are
mapped to controlled error categories. Self-hosted providers send no search API
credential and never substitute another engine within one row. The read-only
advanced section reports sidecar service
availability and browser readiness independently. The status endpoint uses a
five-second bounded request to the sidecar's public `/health` route and never
returns the sidecar URL, bearer token, or upstream error text. The page checks
immediately, refreshes every five seconds while active, and stops when another
Admin page is selected. Model requests share the same five-second health cache;
Modified `web.run` advertises browser commands only while the cached status is
online with `browser_ready=true`. Concurrent refreshes are coalesced, and config
hot reload invalidates the cached status.

Provider runtime and Admin editing both use exactly one API Key per Provider.
Legacy comma-separated Provider keys are accepted only at the read boundary:
the first non-empty value becomes active, discarded values remain redaction
inputs, and the next Admin save converges the field to that one key. Configure
multiple accounts as separate Providers; do not put multiple keys in one field.
Configured Responses search rows never rotate or fall back to another
credential. DeepSeek search rows use the selected Provider's single credential
without copying it into the row. Self-hosted rows have neither quota configuration nor automatic
credential fallback.

For each Tavily row, Admin usage shows only Tavily's
`account.plan_usage` and `account.plan_limit`. Results are cached server-side
for five minutes by credential and concurrent misses are coalesced. The reset
date is shown only as the first day of the next month; Tavily does not provide
an exact reset time or authoritative time zone for this value.

An ordinary Provider search failure puts that row identity into a one-hour,
process-local cooldown. A Provider with a supported periodic-credit check is
instead persistently marked exhausted only when its available credit is exactly
zero. Exhausted credit is rechecked on demand no more than once per hour until
it recovers; refreshing Admin usage applies the same state transition. Admin
shows available, cooling, and exhausted rows with green, yellow, and red
backgrounds. A cooling row remains manually selectable and selection clears
its cooldown; an exhausted row is disabled and rejected. Manual selection and
successful automatic failover persist the current row, while Gateway restart
clears only the process-local cooldowns.

For authenticated Codex requests with `x-codex-window-id`, Provider changes do
not add to or trim that window's first projected `web.run` surface. A stale
invocation returns that the command is currently unavailable for the current
Provider. New windows receive the current Provider capabilities.

Tavily credentials are sent only in the Bearer authorization header. Before a
Tavily success or error response can reach a model, Search client, or diagnostic
boundary, the gateway removes any reflected occurrence of the configured token,
including occurrences inside documented `answer` and `results` fields.

Self-hosted Bing RSS reads Bing's XML result representation. Self-hosted Bing
Browser instead loads the interactive HTML result page in the sidecar's
Patchright browser. They are separately selectable and never replace each other
inside a row; an explicit later candidate remains eligible under the documented
chain failover rules. Both retain the same result and domain bounds. Operators remain
responsible for using each search engine in accordance with its applicable
terms.

Self-hosted searches use short-lived isolated browser contexts with at most two
concurrent searches. Search result URLs, titles, and snippets are bounded and
normalized before returning to the gateway; domain filters are applied both to
the Google query and to returned hostnames.

The container pins Patchright and its Chromium build instead of installing the
Playwright runtime or using the Playwright base image. Chromium runs headful
inside a private Xvfb display, and browser contexts do not override the browser
user agent. Patchright remains Chromium-only here; Google can still reject a
data-center exit IP, which is surfaced as a bounded error rather than bypassed.

The sidecar runs Chromium as the image's unprivileged `pwuser`, uses the pinned
Chromium seccomp profile required by its user-namespace sandbox, keeps
a read-only root filesystem, and stores only bounded temporary browser/PDF
state. Each Codex Search request ID is mapped to an isolated browser context;
contexts expire after 15 minutes and retain at most 16 page/PDF references and
40 MiB of PDF data. The container also has explicit memory and process limits.
Navigation, subresources, redirects, and PDF downloads are restricted to public
HTTP(S) addresses. This is a defense boundary, not a guarantee that arbitrary
web content is trustworthy: keep the sidecar unexposed, use a unique token, and
apply outbound network controls when deployment policy requires stricter site
allowlisting.

The Admin login limiter keys attempts by the direct peer address. Forwarded
client-IP headers are ignored because the gateway does not yet expose a
trusted-proxy allowlist. A reverse proxy therefore shares one limiter bucket;
configure its own rate limiting as an additional control. Request-log client
attribution follows the same rule and records only the direct TCP peer; it does
not treat `X-Forwarded-For` or `X-Real-IP` as authoritative.

Every `create_app()` instance owns its Admin login limiter and model-test task
registry. Login failures, task IDs, capacity, cancellation, expiry cleanup, and
shutdown therefore affect only that app. Polling or cancelling an ID through a
different app returns the same HTTP 404 as an unknown ID and does not reveal
whether the other app owns it.

Admin model tests allow at most four running tasks and retain at most 128 task
records per app. Their self-call response body has a dedicated 4 MiB incremental
read limit for both success and error responses; overflow is rejected before
full-body JSON decoding and is recorded as a stable 502-class diagnostic with
no partial body. Completed results remain compact JSON bytes until polling.
Each retained record, including its metadata, is limited to 4 MiB, and all
completed records in one app share a 32 MiB budget. Capacity enforcement evicts
only that app's oldest completed results, never active work. Running tasks count
toward the 128-record limit but not the completed-byte budget. App shutdown
cancels and awaits its own active tests and clears its own completed results.
Each active model test has a matching 15-minute frontend and backend deadline.

## Outbound network and response limits

When a request is converted to Google GenAI, public HTTP(S) image URLs are
downloaded under one 120-second monotonic deadline covering DNS, connect,
redirects, response headers, and body reads. Redirect targets and every direct
DNS answer are revalidated, private/non-routable addresses are rejected, at
most three redirects are followed, and each image body is limited to 10 MiB.
The gateway runs this blocking work in a four-worker pool owned by each app;
queue waits, request cancellation, and shutdown do not release capacity until
the underlying worker has actually exited.

Gateway upstream HTTP requests force `Accept-Encoding: identity`. A response
that still declares gzip, deflate, Brotli, or another content encoding is
closed and rejected instead of being decompressed. This makes observable wire
payload bytes and decoded payload bytes identical; HTTP chunk framing is not
counted as payload. Non-streaming success bodies are limited to 50,000,000
bytes, and non-streaming error bodies plus streaming HTTP error bodies are
limited to 1,000,000 bytes. `Content-Length` is checked before reading, while
chunked and unknown-length bodies are counted incrementally. A peer-declared
HTTP chunk is consumed in fixed bounded payload subchunks (at most 64 KiB in
Gateway body reads), so the peer's declared chunk size is never materialized
before the Gateway budget is checked. Oversized or non-identity responses are
closed and surfaced as a stable gateway upstream error.

Successful SSE streams remain incremental and do not acquire a total
stream-size or duration cap. Each SSE line is limited to 1 MiB and each event's
accumulated `data:` payload is limited to 8 MiB; the event counter resets after
every delimiter. The same limits apply to converted SSE and byte-preserving
Responses passthrough. Overflow closes the upstream and surfaces a stable
Gateway safety error.

Ordinary upstream HTTP requests have a 10-minute timeout. Streaming requests
allow 10 minutes for the upstream response to open, five minutes between
subsequent upstream bytes, and five seconds for connection cleanup. Static page
opens allow 60 seconds; Tavily, browser navigation/search, PDF downloads, and
Google image downloads allow 120 seconds.

Converted provider streams accept JSON `data:` events, the explicit `[DONE]`
marker, empty `data:` keepalives, and normal SSE comments. A non-empty event
that is neither JSON nor `[DONE]` is an upstream protocol failure: Rosetta
closes it once and terminates the converted stream with a stable 502-class
error. The malformed event body is never included in the client-visible error
or ordinary/body logs. Same-protocol Responses streaming remains a
byte-preserving passthrough; it enforces the wire-size limits above without
parsing ordinary provider event JSON. Complete `response.failed` and
`response.incomplete` events are the narrow exception described below.

## Codex-facing error origins

Every error message returned through the `/v1` agent surface has one stable
owner prefix:

- `Codex Rosetta: ` for request, routing, conversion, configuration, and other
  Gateway failures;
- `Codex Rosetta blocked: ` for authentication, SSRF, credential-return,
  parser/resource-limit, and other intentional safety-policy rejections;
- `Upstream: ` for provider HTTP errors, connection failures, protocol errors,
  and upstream stream interruptions.

Rosetta preserves the provider-specific HTTP/SSE envelope, status, error code,
and non-message fields. It changes only documented error-message locations; a
non-JSON upstream error is wrapped in the source-compatible JSON error
envelope. Successful response bodies and ordinary model strings are unchanged.
For SSE, upstream `response.failed` messages are labeled, an upstream
`response.incomplete` is emitted downstream as `response.failed` with the
original reason, and a failure after HTTP 200 has started produces one
protocol-valid terminal error event instead of an unlabeled EOF. Client
cancellation does not synthesize an error event.

Codex may still map particular HTTP statuses to its own UI errors: current
Codex treats HTTP 400 as an invalid request using the complete body, maps 429
to its rate-limit flow, and may replace HTTP 500 text with a generic internal
message. The Gateway wire message remains labeled; exact final UI wording for
those status-specific client branches is owned by Codex.

## Model authentication boundary

Codex 0.145.0 sends the Gateway credential only in the HTTP `Authorization`
request header. On direct Responses routes, Rosetta removes that inbound header
case-insensitively and then overlays the selected Provider authentication last.
Other unknown end-to-end headers pass through on direct routes unless they are
hop-by-hop, framing, or client network-identity fields. Converted routes retain
their explicit minimal header set.

The supported OpenAI Responses, OpenAI Chat, Anthropic Messages, and Google
GenAI response protocols currently define no API-authentication fields. Rosetta
also does not forward upstream HTTP response headers. Model response JSON and
SSE bytes are therefore not scanned for configured credential strings.
Successful content remains unchanged; error-message fields may receive only
the origin label described above. If a future protocol declares an authentication
field in a response body, that exact field path must be registered and tested;
ordinary model text must not be scanned. Search, Images, web-run, model
discovery, and other credential-bearing auxiliary clients retain their exact
credential-return protection.

Those auxiliary clients currently use non-streaming passthrough in production.
Their internal streaming guard keeps only a per-consumer overlap tail for
ordinary decoded fields and raw SSE wire bytes. Complete tool-argument JSON is
retained only until its top-level value closes, then duplicate-preserving JSON
inspection runs and the buffer is released. There is no total fragment-count
limit: only unfinished structured arguments remain subject to the aggregate
1 MiB and identity limits, while rolling text windows have their own identity
limit. Each complete safe SSE event is released immediately. These controls do
not apply to model-generation routes.

## Diagnostic data retention

Error diagnostics may contain prompts, source code, and tool payloads. Request,
converted-body, configuration, and auxiliary-client diagnostics redact
configured Gateway/provider API tokens, Bearer/Authorization tokens, explicit
token/API-key fields, and exact configured-token values. Model-response
diagnostics redact only explicit authentication/token fields; ordinary response
strings, including strings equal to a configured token, are retained. Restrict
access to the data directory accordingly.

Live upstream-error log lines escape control characters and line separators
onto one line and cap the final value at 4,096 characters. For model responses,
parsed JSON redacts only explicit authentication/token fields, while non-JSON
text redacts explicit assignments such as `Authorization: ...` or
`api_key=...`; ordinary configured-token strings remain. Auxiliary-client
errors continue to use exact configured-token redaction. This is not a
general-purpose privacy scrubber.

Request/response body logging is a separate opt-in controlled by
`debug.log_bodies` or `CODEX_ROSETTA_LOG_BODIES`. It uses the dedicated
`codex-rosetta-gateway.body` logger at DEBUG: enabling it does not enable other
Gateway DEBUG noise. Each app keeps its own live body-log policy and token set,
including after Admin config reloads. Original, intermediate, and converted
request bodies use exact configured-token redaction. Upstream model response
bodies redact only explicit authentication/token fields. Records are then
JSON-serialized, escaped onto one line, and capped at 20,000 characters.
Serialization failures emit only a constant placeholder; they never fall back
to the raw object or exception text.

Body logs preserve prompts, source code, personal data, and ordinary
`password`, `secret`, `client_secret`, and proxy-password values. Treat them as
sensitive diagnostics and restrict console/file log access. Configured exact
Gateway/provider tokens remain visible in ordinary model response strings,
while explicit response authentication/token fields are redacted. Request
bodies retain the stronger exact-value, Bearer/Authorization, and explicit-field
redaction policy.

When `server.stream_trace.enabled` is enabled, the stream trace writes an
`original_request` record before compaction, Tool Profile filtering, or protocol
conversion. The record is recursively token-redacted but is intentionally not
limited by `stream_trace.max_string_chars`. Disable stream tracing after the
investigation and restrict the trace file because prompts, source code, and
personal data remain present. It captures the request body received by the
proxy handler, not authentication headers. Deferred model-response trace
records use protocol-field-only redaction. While the response is pending its
terminal safety classification, every record is written to a request-owned
anonymous spool in the configured trace directory. A safely completed response
is appended to the trace in full, with no deferred-batch stream-length,
aggregate-byte, or record-count truncation. Individual diagnostic strings still
honor `stream_trace.max_string_chars`. Failed, cancelled, or otherwise unsafe
response batches are still discarded. Trace-directory, spool, or final-file
write failures disable tracing for that request without interrupting or
changing the model stream.

Request-log success and error caps are validated during both startup and Admin
hot reload. `server.request_log.success_max`, `error_max`, legacy
`max_entries`, and the `REQUEST_LOG_SUCCESS_MAX` / `REQUEST_LOG_ERROR_MAX`
environment overrides must be integers from 0 through 1,000,000; booleans,
negative values, and larger values are rejected. A cap of `0` retains no rows
of that request class and converges immediately when activated. These request
log caps do not change the independent 10,000-entry error-dump contract.

Each request or converted body is limited to 10 MiB before storage. Retained
error diagnostics are pruned only by the established 10,000-entry count limit;
there is no automatic age or total-size deletion policy. Count pruning and
manual clearing also delete unreferenced body blobs.

## Executable tool-history storage

When tool localization is enabled, native/model-facing object translations are
executable replay state rather than diagnostic data. Calls and results are
stored independently under the authenticated principal. Session, thread,
window, fork, Provider, model, and protocol-level call ID are not ownership or
lookup dimensions. Rosetta derives a principal- and object-kind-separated keyed
HMAC lookup token from the exact source template, then encrypts both the source
and target templates with AES-256-GCM using a unique nonce and authenticated
scope for every row. The SQLite columns therefore contain neither a plain hash
nor a redacted `[REDACTED]` projection. Request logs, traces, error dumps, APIs,
and the Admin UI remain separate diagnostic surfaces and continue to apply the
token-only redaction policy above.

By default the first persisted mapping atomically creates
`data/tool-mapping.key` next to `gateway.db`. The data directory is mode `0700`
and the key is mode `0600`; concurrent gateway starts converge on the same
fully-written key. A deployment-managed durable secret may instead set
`CODEX_ROSETTA_TOOL_MAPPING_KEY` to one base64-encoded 32-byte key. The
environment value is not copied into SQLite or included in errors.

Treat the database and key as one backup unit. Stop writes or use a consistent
SQLite backup, and back up `gateway.db` together with `tool-mapping.key`; when
using the environment override, back up the external secret through its secret
manager. Restore both from the same backup generation. Key rotation is not
implemented: do not replace either key source while encrypted rows remain.

If encrypted rows exist and the key is missing, malformed, mismatched, or a row
fails authentication, gateway startup fails closed instead of regenerating a
key or replaying lossy history. Legacy plaintext or `[REDACTED]` mapping rows
cannot be recovered; migration emits a warning and removes only that legacy
table. Encrypted-v1 call mappings are decrypted and migrated atomically into
single-object entries. Exact duplicates merge, while one source with conflicting
targets is not migrated. Any integrity, capacity, or SQLite failure rolls the
whole migration back and retains the legacy table.

Each object entry has an absolute 24-hour TTL. Lookup and duplicate insertion do
not renew it; expiry produces a normal miss, and a successfully accepted request
may create a new entry with a fresh absolute TTL. Unused entries are not deleted
early. Expired rows are removed at startup, during reads/writes, and by periodic
cleanup.

Encrypted object storage also has fixed hard budgets. Ciphertext plus ownership
metadata is limited to 16 MiB per row; each principal is limited to 8,192 rows
or 256 MiB, and the database to 32,768 rows or 512 MiB. Expiry cleanup,
row/byte accounting, validation, conflict detection, and the final insert run
inside transactions. Startup validates accounting and all budgets before
decrypting rows. Capacity, conflict, or inconsistent-accounting failures for
model call objects fail closed; accepted request-result records may be skipped
without changing the request already sent upstream.
