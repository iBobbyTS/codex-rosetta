# Context Compaction Summary Quality Test

This suite runs one controlled coding-handoff scenario through two provider
cells. It is intentionally a small regression test, not a benchmark. Protocol
validity is a prerequisite; the test executor—not the tested model—scores only
the fixed post-compaction facts.

## Provider cells

| Task | Default model | Copied-config provider | Expected gateway mode |
|---|---|---|---|
| `01` | `gpt-5.6-sol` | `Pixel (K12)` | native |
| `02` | `deepseek-v4-flash` | existing sole provider | Rosetta |

The two tasks must keep byte-identical `TASK.md`, `scenario.py`, and `QUERY.md`
files. Phase 1 contains one naturalistic coding handoff with an obsolete value,
its later replacement, exact operational constraints, one decision and reason,
one unassigned field, and irrelevant project noise. Deterministic high-entropy
filler only forces compaction. The canonical expected values live once in
[`expected_facts.json`](expected_facts.json) and are read only by the test
executor.

In the copied Gateway config only, route `gpt-5.6-sol` to the provider named
exactly `Pixel (K12)`. Do not modify the user's main config. Keep
`deepseek-v4-flash` on its existing sole provider. Confirm the observed provider
and upstream model from Gateway Logs.

## Two-phase run

Use local-mode Provider ID `codex_rosetta`, require display name `OpenAI`,
retain its generated catalog, and set:

```toml
model_auto_compact_token_limit = 15000
```

Run `TASK.md` first and retain its thread id. Phase 1 must execute
`scenario.py` once, compact after the command result, and return exactly
`PHASE1:QUALITY_CONTEXT_READY`. Only after that compaction, resume the same
thread and model with the previously unseen query:

```bash
QUERY=$(<"$RUN_ROOT/worktree/QUERY.md")
CODEX_HOME="$RUN_ROOT/codex_home" codex exec resume --json \
  -c model_auto_compact_token_limit=1000000 \
  -m "$MODEL" "$THREAD_ID" "$QUERY"
```

Capture phase 1 and resume output separately as
`artifacts/codex-phase1.jsonl` and `artifacts/codex-resume.jsonl`. The resume
phase must not run a command or trigger another compaction.
The resume-only threshold override prevents a second compaction from changing
the first installed summary before it is evaluated.

The run is scoreable only when all protocol preconditions hold:

1. `scenario.py` executes exactly once.
2. Exactly one `context_limit` compaction occurs after the command result.
3. The compact response is accepted and installed.
4. The phase-1 marker is produced after the installed compaction.
5. `QUERY.md` is submitted only during a same-thread, same-model resume.
6. Resume produces one JSON object with exactly the requested keys, without
   another command or compaction.
7. Baseline and post-compaction Codex token counts are below 15,000 and the
   command emits at least 100,000 characters.

Classify the compact request using the path/body/event method in
[`context_compaction/EVALUATION.md`](../context_compaction/EVALUATION.md); a
rollout-only local/internal compact event does not satisfy these preconditions.

Zero or multiple phase-1 compactions, a repeated command, an early query, a
different resume thread, or another resume compaction makes the quality result
`not_scored`; it is not an ineffective-summary result.

## Scoring

Follow [`EVALUATION.md`](EVALUATION.md). Compare only the resume JSON values
with `expected_facts.json`. Exact paths, filenames, codes, negation, ordering,
and null must match. Do not use Rosetta's plaintext mapping as the primary
score, because native GPT compaction is opaque; the mapping is diagnostic
evidence for the DeepSeek cell only.
