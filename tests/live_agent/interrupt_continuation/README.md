# Interrupt continuation

This suite is a protocol-level live test for the Codex Responses → Provider
Chat soft-interrupt path. It drives one app-server thread in two independent
cells. The fixture is deliberately tool/skill/plugin-neutral: it contains no
`.agents` tree, MCP manifest, plugin, or skill, and the isolated Codex config
disables the configurable bundled/orchestrator skills, apps, plugin discovery,
tool suggestions, web search, and collaboration modes. Any app-server baseline
tool declarations that remain are fingerprinted and must stay unchanged.

- `steer`: `turn/steer` must keep the active turn id and complete without a
  `<turn_aborted>` marker or a new turn.
- `interrupt`: a hard stop followed by a new turn containing the canonical
  `<turn_aborted>` marker must drain the predecessor, persist its completed
  output, and send the next Chat request in a steer-like form: replayed output
  and the continuation are retained, but the control marker is omitted.

Run the real-provider cell only with the repository live-call gate enabled:

```bash
CODEX_ROSETTA_ALLOW_LIVE_CALLS=I_UNDERSTAND_REAL_API_CALLS \
  conda run -n llm-rosetta python tests/live_agent/interrupt_continuation/run_live.py \
  --mode steer
```

Use `--mode interrupt` for the hard-stop cell. Each invocation creates a fresh
ignored timestamp root under `tmp/agent_testing_workspace/` and a matching
trace directory under `/Volumes/RAMDisk/`. Reports contain request-level input,
output, and cached token counts when the upstream returns usage; they do not
derive or publish cache hit rates. Every request is also summarized with
credential-free fingerprints of its system/developer context and tool surface.
A Skill/Plugin marker, a tool surface change, or an observed tool call changes
the result to `confounded` and invalidates the cache comparison instead of
mixing that variable into the cache result.

The deterministic unit coverage for the replay boundary is in
`tests/gateway/test_soft_interrupt.py` and
`tests/gateway/test_soft_interrupt_proxy.py`.
