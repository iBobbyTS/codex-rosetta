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
mixing that variable into the cache result. The exact canonical
`<turn_aborted>` system item is an expected hard-interrupt event: the runner
normalizes it out of the system-context fingerprint while retaining its raw
count in the evidence. A marker with extra text is not normalized.

The deterministic unit coverage for the replay boundary is in
`tests/gateway/test_soft_interrupt.py` and
`tests/gateway/test_soft_interrupt_proxy.py`.

## DeepSeek cache isolation

Each provider experiment creates one fresh random `user_id` and sends that same
value on every request in that experiment. Changing it between requests would
disable the cache continuity being measured; reusing it between experiments can
reuse a prior DeepSeek KV-cache entry. The value must contain only ASCII
letters, digits, `-`, or `_`, and must not contain PII. The live runner uses a
test-only localhost forwarder to inject the field after Rosetta's Responses →
Chat conversion, so production conversion behavior is unchanged.

## Direct DeepSeek cache control

A fresh direct `https://api.deepseek.com/chat/completions` control run used the
Codex system/developer prompt captured from the first target request in the
hard-interrupt cell (`4` system parts, `20,572` characters) and the
`deepseek-v4-flash` model. It used one new random `user_id` for both requests;
the identifier is not a cache metric. The first request was `system1 + user1`;
the second added the returned assistant message, the canonical
`<turn_aborted>` system item, and a new user message. The provider reported:

| Request | Input tokens | Cache hits | Cache misses |
| --- | ---: | ---: | ---: |
| `system1 + user1` | 4,284 | 0 | 4,284 |
| `system1 + user1 + assistant1 + system2 + user2` | 4,427 | 4,224 | 203 |

The fresh `user_id` made the first request cold, while the second request hit
the newly established 4,224-token prefix. This confirms that the earlier
4,224-token hit was not simply inherited from a previous experiment. The
middle `<turn_aborted>` item did not reduce that established Codex system-prefix
cache block. It does not prove that the marker is free: the second request also
adds assistant and user content, and a no-marker control branch is required to
isolate the marker's own tail.

The same isolation was used for the app-server cells. The current soft-
interrupt implementation produced these usage observations:

| Cell | First request | Continuation request | Proxy requests |
| --- | ---: | ---: | ---: |
| hard interrupt | `0 / 14,366` cached/input | `14,336 / 15,409` cached/input | 3 |
| steer | `0 / 14,366` cached/input | `14,336 / 15,408` cached/input | 3 |

The temporary baseline (implementation stashed, same fresh-ID proxy) was cold
on its first request (`0 / 14,387` cached/input) and remained cold after the
hard interrupt (`0 / 14,475` cached/input). Its resumed target had 11 messages
and retained the canonical `<turn_aborted>` system item. The implementation run
had 12 messages, removed that marker from the replayed target, and reported the
14,336-token hit. The baseline response exceeded the normal deferred trace
capacity, so the evidence run temporarily retained only the final numeric usage
summary; that temporary recording change was removed immediately after the
successful run. These traces are retained at
`/Volumes/RAMDisk/202607260022/rosetta-trace.jsonl`,
`/Volumes/RAMDisk/202607260023/rosetta-trace.jsonl`, and
`/Volumes/RAMDisk/20260726004403-a8f5b8/rosetta-trace.jsonl`.
