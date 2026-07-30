# Interrupt continuation

This protocol-level live suite compares Codex Responses → DeepSeek Chat Steer
and ESC hard-interrupt behavior in two independent app-server cells. The
fixture is deliberately tool/skill/plugin-neutral: it has no `.agents` tree,
MCP manifest, plugin, or skill. Its isolated Codex config disables configurable
skills, apps, plugin discovery, tool suggestions, web search, collaboration,
and shell tools. Any remaining app-server baseline tool declarations are
fingerprinted and must stay unchanged.

- `steer`: `turn/steer` keeps the active turn ID. It must complete without a
  `<turn_aborted>` marker or a user-role `<system>` wrapper.
- `interrupt`: `turn/interrupt` cancels the active upstream stream normally.
  The next turn must contain the canonical Codex marker as exactly one separate
  user-role `<system>` envelope, followed by the actual user continuation.
  Rosetta must not drain the cancelled stream, retain hidden output, replay an
  assistant response, synthesize a tool result, or issue an extra upstream
  request.

Run each real-provider cell only with the repository live-call gate enabled:

```bash
CODEX_ROSETTA_ALLOW_LIVE_CALLS=I_UNDERSTAND_REAL_API_CALLS \
  conda run -n llm-rosetta python tests/live_agent/interrupt_continuation/run_live.py \
  --mode steer

CODEX_ROSETTA_ALLOW_LIVE_CALLS=I_UNDERSTAND_REAL_API_CALLS \
  conda run -n llm-rosetta python tests/live_agent/interrupt_continuation/run_live.py \
  --mode interrupt
```

Each invocation uses a fresh ignored timestamp root under
`tmp/agent_testing_workspace/`, a matching trace directory under
`/Volumes/RAMDisk/`, a temporary non-8765 Gateway, and one fresh random
DeepSeek `user_id`. The same `user_id` is reused only inside that cell so its
requests can share cache state, while different cells cannot inherit a prior
experiment's cache. The identifier contains only non-PII ASCII letters,
digits, and hyphens.

Reports include request-level input/output/cached token counts when DeepSeek
returns usage. If the diagnostic trace reaches its chunk-retention bound, the
test-only localhost forwarder retains the final numeric usage fields instead;
it never retains response text. The interrupted request may have no final usage
because its stream is cancelled; the completed continuation must report
non-zero cached input tokens. The runner also records credential-free system/developer and
tool fingerprints, canonical-system-marker count, wrapped-user-notice count,
Provider request count, and app-server turn status. A Skill/Plugin marker, tool
surface change, or observed tool call makes the result `confounded` instead of
mixing another variable into the cache result.

Deterministic coverage lives in `tests/gateway/test_late_developer_message.py`,
`tests/gateway/test_persistence_sqlite.py`, and
`tests/live_agent/test_interrupt_continuation_runner.py`.

## Why later developer messages are rewritten

Codex's native hard-interrupt behavior adds this exact runtime marker to later
history:

```text
<turn_aborted>
The previous turn was interrupted on purpose. Any running unified exec processes may still be running in the background. If any tools/commands were aborted, they may have partially executed.
</turn_aborted>
```

Direct DeepSeek controls using the full Codex system prompt and a fresh random
`user_id` showed that changing this later item from system to user retained the
established 14,336-token cache block. The production rule is positional rather
than marker-specific: it preserves the leading system/developer prefix, then
changes every later developer message to a separate user message with the
original content inside a `<system>` envelope. The interrupt case therefore
arrives upstream as:

```text
<system>
<turn_aborted>
The previous turn was interrupted on purpose. Any running unified exec processes may still be running in the background. If any tools/commands were aborted, they may have partially executed.
</turn_aborted>
</system>
```

The implementation does not parse or special-case `<turn_aborted>`; fork,
plugin, skill, and other Codex runtime developer items follow the same rule.
This is a request-local role conversion, not a continuation cache or a
steer-like replay. Provider caching remains best-effort.
