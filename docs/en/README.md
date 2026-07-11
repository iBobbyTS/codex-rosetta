# Codex-Rosetta User Documentation

## Compatibility

- [Codex version compatibility](version-compatibility.md)

## Gateway operations

- [Security and authentication](gateway-security.md)

The terminal supports four logging levels:

```bash
codex-rosetta-gateway --log-level info
codex-rosetta-gateway --log-level stats
codex-rosetta-gateway --log-level warning
codex-rosetta-gateway --log-level error
```

`warning` is the default and suppresses normal per-request output while
retaining warnings and errors. `stats` maintains per-model request counts on a
single refreshed line, keyed by each provider's original upstream model name
rather than its exposed alias, for example `model-1: 12, model-2: 7`. A warning
or error starts on a new line, and the counters resume on the next request.
`info` prints request summaries; `error` prints errors only. For complete
request history, use **Request Log** in the WebUI. For streaming trace
diagnostics, use **Gateway Logs** in the WebUI.

## Codex tool localization

- [Basic conversation](codex-tool-localization/basic-conversation.md)
- [Code editing](codex-tool-localization/code-edit.md)
- [Other tools](codex-tool-localization/other-tools.md)

For architecture notes, source contracts, and maintenance procedures, see the
[developer documentation](../dev/README.md).
