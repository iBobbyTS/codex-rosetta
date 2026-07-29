# Code Editing

Codex exposes native editing capabilities such as `apply_patch`, `exec_command`, and `write_stdin`. Many open models have seen more Claude Code-style editing tools during training or product use, so they may choose shell commands or ad-hoc Python scripts instead of Codex's patch workflow.

Codex-Rosetta can localize the model-facing editing surface for Responses-to-Chat routes while still returning Codex-native tool calls downstream.

## Model Configuration

The gateway admin UI exposes a model-level section named `Tool Adaption for Codex`.

Current options:

- `Localize code editing tools`: replace Codex-native editing tools with localized Chat tools for the upstream model.
- Tool Profiles manage the current `image_gen__imagegen` Function nested in Code Mode `exec` (runtime identity `image_gen.imagegen`). The obsolete hosted `image_generation` tool is not part of the bundled Profile catalog.

Only the configured model route is affected.

## Model-Facing Tools

When `localize_code_editing_tools` is enabled for an OpenAI Responses to OpenAI Chat route, Rosetta removes native code editing tools from the upstream Chat request and exposes these Claude Code-like tools instead:

- `Read(file_path, offset?, limit?)`
- `Edit(file_path, old_string, new_string, replace_all?)`
- `Write(file_path, content)`
- `Glob(pattern, path?)`
- `Grep(pattern, path?, glob?, type?, output_mode?, case_insensitive?, line_numbers?, before_context?, after_context?, context?, head_limit?, offset?, multiline?)`
- `Bash(command, timeout?, description?, run_in_background?)`

The localized `Edit` description explicitly asks the model to replace complete lines or complete consecutive line blocks when possible. This improves conversion to Codex patches because `apply_patch` is much more reliable when the old text includes full line context.

## Native Translation

Localized tool calls are translated back before Codex receives the response:

- `Bash` becomes `exec_command`.
- `Read` becomes an `exec_command` that prints UTF-8 file contents, with optional offset and limit.
- `Glob` becomes an `exec_command` using Python `glob`.
- `Grep` becomes an `exec_command` using `rg`.
- `Write` normally becomes a custom `apply_patch` add-file call.
- `Edit` normally becomes a custom `apply_patch` call.
- `Edit(replace_all=true)` becomes an `exec_command` that performs a controlled replace-all operation.

If the original request does not expose custom `apply_patch`, `Edit` falls back to an `exec_command` or `shell_command` that invokes `apply_patch` through a heredoc when available, and `Write` falls back to an `exec_command` that writes UTF-8 content through a base64-safe Python helper.

## Read Output Expansion

Some models emit narrow substring edits even after reading the file. Rosetta maintains a session-local read-output cache while rebuilding the converted Chat request. When a later `Edit` targets a substring that can be expanded unambiguously to a full line from a prior `Read`, Rosetta expands `old_string` and `new_string` to full-line replacements before generating the patch.

The cache is invalidated for a file after successful mutating calls for that file, so stale reads are not reused across edits.

## Historical Tool-Object Translation

Codex stores assistant tool calls in its local session history and sends that history again on later turns. After localization, Codex sees native calls such as `apply_patch`, but the upstream Chat model originally saw localized calls such as `Edit`.

To keep provider-side prompt caching and model continuity intact, Rosetta stores
principal-owned translations of individual Chat tool objects. Calls and results
are independent entries. Only the protocol-level call identifier (`id` for a
call or `tool_call_id` for a result) is excluded from content identity; IDs
nested inside arguments or result content remain significant. A hit injects the
current request's protocol-level identifier.

The authenticated principal is the only ownership boundary. Session, thread,
window, fork, Provider, model, and call ID are deliberately not cache keys, so
an exact object translation can be reused after a window change, compaction,
resume, or fork without copying the surrounding conversation. A keyed HMAC,
domain-separated by principal and object kind, prevents SQLite lookup tokens
from becoming an enumeration surface. The exact source and translated template
are protected with AES-256-GCM at rest. Diagnostic redaction is deliberately
not applied to this executable payload, because a `[REDACTED]` object would no
longer describe the tool action Codex executed. See
[Gateway Security and Authentication](../gateway-security.md#executable-tool-history-storage)
for key lifecycle, backup, failure, and legacy-row behavior.

Rosetta replays exact hits before applying current request localization. A miss
is translated normally: request-history results are saved only after the
upstream accepts the request, while a newly returned model call must be durably
saved before Rosetta releases it to Codex. Result capacity or conflict failures
skip only that result record; a call persistence failure fails closed rather
than exposing history that cannot later be reconstructed.

Each entry has an absolute 24-hour TTL. Reads and duplicate writes do not renew
it. Expired entries are ordinary misses: Rosetta retranslates them and, after
the same acceptance rules, writes a fresh entry with a new 24-hour lifetime.
Entries are not deleted merely because one request did not use them, allowing
independent forks to reuse the same exact object.

This keeps Codex's downstream history native and prevents tool-object
retranslation from changing the upstream model's repeated context. It does not
guarantee a Provider prompt-cache hit: Codex may append other context when it
forks or resumes a thread, and the Provider may choose a new cache segment even
when the earlier Chat messages remain an exact prefix.

## Current Limits

The localization layer is intentionally conservative:

- It only runs for Responses-to-Chat routes.
- It only changes routes where the model config enables it.
- It does not attempt to parse arbitrary shell edits back into structured edits.
- It cannot hide reasoning that the model places in ordinary text.
