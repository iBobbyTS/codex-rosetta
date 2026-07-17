# Context Compaction Protocol Test

This suite verifies Codex Remote Compaction V2 routing, wire shape, persistence,
and replay through Codex-Rosetta. It does not score summary quality; use
`context_compaction_summary_quality` for the controlled fact-retention matrix.

## Scenarios

- `01`: `deepseek-v4-flash` context-limit compaction through Rosetta mode.
- `02`: `gpt-5.6-sol` context-limit native passthrough through
  `Pixel (K12)`.
- `03`: `gpt-5.6-sol` through `Pixel (K12)` to
  `deepseek-v4-flash`; require `comp_hash_changed` and Rosetta mode.
- `04`: reverse `03`; require `comp_hash_changed` and Rosetta mode.

Every cell uses a separate timestamped run root, Codex Home, copied gateway
configuration, port, gateway process, and Gateway Logs trace.

## Provider routing

In the copied config only, route every `gpt-5.6-sol` cell to the existing
provider named exactly `Pixel (K12)`. Keep `deepseek-v4-flash` on its existing
sole provider. Verify both provider names and actual upstream models from the
trace; model aliases alone are not evidence.

For context-limit tasks `01` and `02`, set:

```toml
model_provider = "openai"
model_auto_compact_token_limit = 17000
```

The deterministic command emits more than 100,000 characters of neutral filler
so the 17,000-token diagnostic limit sits above both the baseline and
post-compaction turns, while the pending command result forces one compaction
before the next model call. Record the baseline and post-compaction Codex token
counts plus the command-output character count. Require both token counts below
17,000, at least 100,000 command-output characters, and exactly one genuine
`context_limit` compaction after the command. A run without that measured shape
is invalid and must be reported rather than silently accepted.

For model-switch tasks `03` and `04`, use the normal token limit. Retain the
first execution's thread id and run:

```bash
codex exec resume -m TARGET <thread-id> \
  "Proceed with the resume phase of the existing task."
```

This explicit target selection is limited to the model-switch protocol cells;
ordinary cells use the isolated config default without `-m`. Non-interactive
resume requires the new prompt. The first phase's fixed code is
not repeated in that prompt, so the target marker proves context continuation.

## Result interpretation

Follow [`EVALUATION.md`](EVALUATION.md). Require a genuine trigger item, exact
reason/mode, one canonical compaction output, installed follow-up input, the
expected mapping count, and the final marker. Do not count strings that merely
appear inside prompts, source listings, tool output, or errors.
