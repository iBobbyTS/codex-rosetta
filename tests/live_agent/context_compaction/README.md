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
model_provider = "codex_rosetta"
model_auto_compact_token_limit = 17000
```

The deterministic command emits more than 100,000 characters of neutral filler.
The tested model must configure its command call to retain at least 20,000
output tokens; otherwise Code Mode may select a 1,000-token result cap and keep
the next request below the 17,000-token diagnostic limit. Record the baseline
and post-compaction Codex token counts, selected command output-token cap, and
retained command-output character count. Require both token counts below
17,000, a cap of at least 20,000 tokens, at least 60,000 retained characters,
and exactly one genuine `context_limit` compaction after the command. A run
without that measured shape is invalid and must be reported rather than
silently accepted.

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

Classify each compact-related request from the strongest bounded evidence
available. Prefer the Gateway request-log profile plus the HTTP path; use the
wire body when the request reaches stream tracing. Rosetta may answer a Remote
V2 trigger early, before creating a normal stream-trace request record, so an
absent `raw_passthrough_request` is not evidence that compaction did not occur:

- `legacy_remote_compact`: `POST /v1/responses/compact`;
- `remote_v2_in_band`: `POST /v1/responses` whose final input item is the sole
  `compaction_trigger`;
- `post_compaction_followup`: `POST /v1/responses` carrying an installed
  `compaction` or accepted `compaction_summary` item without a new trigger;
- `local_internal`: a rollout `compacted`/`context_compacted` event with none
  of the wire shapes above;
- `ordinary_response`: none of the compact request/event evidence above.

Also record the `x-codex-turn-metadata` reason, model, route, prompt-cache key,
response item type, and the next request's installed item. This combination
distinguishes Remote V2 and proves the full trigger/result/replay chain even
when the current stream trace does not record the early-response request. A
Gateway request-log profile with `compaction_mode` and `compaction_reason` is
created only after a valid in-band trigger is recognized; combine it with the
registered `/v1/responses` route and mapping/install evidence. Do not classify
a legacy compact request unless a bounded access log or capture proves
`/v1/responses/compact`.
