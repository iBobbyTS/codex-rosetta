# Audit Evidence

Run: `20260721-2137`
Repository head: `0f262852c0de91d2ec4eadd56e3894fced8c18f0`
Product-code baseline: `51f3b2d`
Mode: periodic supplementary omission audit
Real API calls: none

## UNIT-001 - Repository and path reconciliation

The worktree was clean on `main`; the current head is audit documentation after
the product-code remediation at `51f3b2d`. The current local Codex source
checkout is `655224ffae098a85efeddf8289171ff3bd2624d1`.

The reachable streaming path is:

1. `src/codex_rosetta/gateway/proxy.py:2471` wraps the transport with
   `CredentialRedactingTransport`.
2. `src/codex_rosetta/gateway/proxy.py:2548-2559` constructs a
   `ConversionPipeline(route.source_provider, route.target_provider)`.
3. `src/codex_rosetta/gateway/proxy.py:2605-2611` sends the converted request through the wrapped
   streaming transport.
4. `src/codex_rosetta/gateway/transport/credential_redaction.py:329-358` returns a
   `CredentialRedactingStream`; parsed events invoke the semantic gate at
   `:226-244` before yielding.
5. `src/codex_rosetta/pipeline.py:578-581` converts target-provider chunks to IR and
   `:626-632` serializes IR events to the source provider.
6. `src/codex_rosetta/gateway/proxy.py:1705-1747` processes the converted events and emits source
   SSE to the caller.

The gate therefore runs before the target -> IR -> source conversion has
established the source consumer's final identity.

## UNIT-002 - Provider identity versus source Responses identity

| Upstream target | Semantic-gate partition | Converter evidence | Source Responses behavior | Observed consequence |
| --- | --- | --- | --- | --- |
| OpenAI Chat | `choice_index` for `content`, `reasoning_content`, and `refusal` (`src/codex_rosetta/gateway/transport/credential_semantics.py:588-612`) | Chat emits `TextDeltaEvent` with `choice_index` (`src/codex_rosetta/converters/openai_chat/converter.py:618-637`) | Responses emits an optional `output_index` but accumulates text in one `context.accumulated_text` (`src/codex_rosetta/converters/openai_responses/converter.py:1609-1636`); Codex does not retain that output index | A choice identity can split the gate while the downstream active-item consumer concatenates the text |
| Anthropic Messages | `block_index` for text/thinking/signature/JSON fragments (`src/codex_rosetta/gateway/transport/credential_semantics.py:614-635`) | Anthropic preserves `block_index` on IR text/reasoning events (`src/codex_rosetta/converters/anthropic/converter.py:671-723`) | Responses text handling accumulates the event text in the active context and has no block-index partition (`src/codex_rosetta/converters/openai_responses/converter.py:1609-1636`) | Distinct upstream blocks can be merged into one source active-item stream |
| Google GenAI | candidate `choice_index` plus enumerated `part_index` (`src/codex_rosetta/gateway/transport/credential_semantics.py:637-653`) | Google emits text/reasoning deltas with candidate `choice_index`; parts are iterated in `src/codex_rosetta/converters/google_genai/converter.py:798-898` | Responses uses the choice as `output_index`, fixes `content_index` to `0`, and appends every text delta to `context.accumulated_text` (`src/codex_rosetta/converters/openai_responses/converter.py:1609-1636`) | A part identity can split the gate even though the source stream has one active text accumulator |

The source bridge is not merely a formatting pass: it discards or collapses
upstream identity fields while creating the exact stream consumed by Codex.
The gate's upstream-provider keys therefore do not prove a no-reconstruction
property for converted routes.

## UNIT-003 - Codex consumer source contract

The local Codex parser handles `response.output_text.delta` by retaining only
`delta` (`../openai-codex-src/codex-rs/codex-api/src/sse/responses.rs:339-342`).
The turn consumer then attaches each `OutputTextDelta` to the current active
item and emits the delta without consulting `item_id`, `output_index`, or
`content_index` (`../openai-codex-src/codex-rs/core/src/session/turn.rs:2323-2353`).
This is the downstream identity that the converted Responses stream must
protect.

## UNIT-004 - Neutral offline canary reproduction

An in-process `llm-rosetta` probe configured only the neutral canary
`CANARY-ALPHA-BETA`. For each target provider it sent `CANARY-ALPHA-` and
`BETA` as separate upstream text fragments while changing the provider-specific
partition identity between fragments, then ran the target -> IR -> Responses
conversion. The semantic gate allowed the fragments and the source-side
consumer reconstruction equaled the canary in every case:

```text
openai_chat allowed True [(0, 0), (1, 0)]
anthropic allowed True [(0, 0), (0, 0)]
google allowed True [(0, 0), (0, 0)]
```

This is a deterministic local reproduction, not a provider-quality or live
network claim. It demonstrates that the configured value can be reconstructed
after the gate for Chat, Anthropic, and Google converted streams.

## UNIT-005 - Existing test oracle gap

The focused existing checks were run as:

```text
conda run -n llm-rosetta pytest -q \
  tests/gateway/test_transport_credential_redaction.py \
  tests/test_pipeline.py
```

Result: `153 passed`.

`tests/gateway/test_transport_credential_redaction.py:957-1034` tests split
text for each provider, but holds the partition identity fixed: Chat choice
`0`, Anthropic block `0`, and Google candidate/part `0`. The direct Responses
ignored-ID regressions beginning at `:1037` do not exercise a target-provider
conversion into source Responses. Converter tests likewise verify individual
identity preservation, not gate-to-source consumer reconstruction. The green
suite is therefore evidence of a missing cross-format failure oracle, not
closure evidence.

## UNIT-006 - Finding disposition and deduplication

- Severity: `Must Fix`.
- Decision class: `Agent-Fixable`.
- Confidence: High.
- Business decision required: No; the approved active-provider no-return
  invariant already determines the intended outcome.
- Root cause: the semantic gate partitions fragments by an identity that the
  downstream consumer does not retain after conversion, allowing one
  consumer-visible stream to be split across gate buffers.
- Deduplication: this is the same invariant as `AUD-025`, not an independent
  root cause. `AUD-025` is reopened; no new finding ID is allocated.

## Frozen Repair Evidence Requirements

The repair must show all of the following before this run can be closed:

1. The gate or an equivalent post-conversion boundary owns the final source
   consumer identity for Chat, Anthropic, and Google converted text/reasoning.
2. A changed upstream choice/block/part identity cannot release the completing
   fragment when the source consumer would concatenate it into the same active
   stream.
3. Fake transport and real pipeline regressions cover parsed and raw SSE paths,
   including canary reconstruction, separate active-item/index isolation,
   bounds, and every terminal cleanup path.
4. Existing direct Responses, argument, tool, collision, protocol, and
   active-provider-only tests remain green.

## Remaining Gaps

No real provider/Codex trajectory, timing, external sink, public deployment,
availability, recovery, or covert-encoding evidence was collected. Those remain
excluded or `Unknown` under the approved profile.
