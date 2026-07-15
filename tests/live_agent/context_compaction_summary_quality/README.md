# Context Compaction Summary Quality Test

This suite compares end-to-end fact retention after context compaction. It is
separate from the protocol suite: protocol validity is a prerequisite, while
the score comes only from the tested model's post-compaction factual output.
The test executor—not the tested model—assigns the quality result.

## Controlled matrix

| Task | Model | Copied-config provider | Expected gateway mode |
|---|---|---|---|
| `01` | `gpt-5.6-terra` | `Pixel (K12)` | native |
| `02` | `deepseek-v4-flash` | existing sole provider | Rosetta |

The two tasks must keep byte-identical `TASK.md` and `scenario.py` files. The
facts appear only in `scenario.py` output, never in the prompt. The fixed
expected values live once in [`expected_facts.json`](expected_facts.json) and
are read only by the test executor.

In the copied Gateway config only, route `gpt-5.6-terra` to the provider named
exactly `Pixel (K12)`. Do not modify the user's main config. Keep
`deepseek-v4-flash` on its existing sole provider. Confirm the observed provider
and upstream model from Gateway Logs.

## Runtime

Use the built-in `openai` Codex provider and set:

```toml
model_auto_compact_token_limit = 17000
```

The run is scoreable only when all protocol preconditions hold:

1. `scenario.py` executes exactly once.
2. Exactly one `context_limit` compaction occurs after the command result.
3. The compact response is accepted and installed.
4. The final model response occurs after that installed compaction input.
5. The final response is one JSON object with exactly the requested keys.
6. The baseline and post-compaction Codex token counts are both below 17,000,
   the command emits at least 100,000 characters, and the genuine
   `context_limit` compaction occurs after the command result.

Zero or multiple compactions, a repeated command, or a response produced before
compaction makes the quality result `not_scored`; it is not an ineffective
summary result.

## Scoring

Follow [`EVALUATION.md`](EVALUATION.md). Compare only the final JSON values with
`expected_facts.json`. Do not use Rosetta's plaintext mapping as the primary
score, because native GPT compaction is opaque; the mapping may be inspected as
diagnostic evidence for the DeepSeek cell only.
