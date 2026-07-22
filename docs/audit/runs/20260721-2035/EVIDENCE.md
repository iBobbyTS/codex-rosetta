# Audit Evidence

Run: `20260721-2035`
Repository head: `51f3b2d569f722f7f8c039a451b898ec65231b7f`
Mode: targeted remediation re-audit
Real API calls: none

## UNIT-001 - consumer-aligned identity implementation

The repair remains inside `ProviderCredentialSemanticGate` and separates the
Codex text-delta contract from provider-wire consumers:

| Event | Gate identity after repair | Ignored wire metadata |
| --- | --- | --- |
| `response.output_text.delta` | local active-item generation | `item_id`, `output_index`, `content_index` |
| `response.reasoning_summary_text.delta` | active-item generation + `summary_index` | `item_id`, `output_index`, `content_index` |
| `response.reasoning_text.delta` | active-item generation + `content_index` | `item_id`, `output_index` |

`response.output_item.added` and `response.output_item.done` advance the bounded
local active-item lifecycle and clear its text buffers. Refusal and code-
interpreter streams retain their existing wire-consumer identities.

The parsed stream wrapper clears gate state from iterator `finally`, context
manager exit, and explicit close paths. The raw wrapper shares the same semantic
gate, so both paths use one consumer contract.

## UNIT-002 - frozen counterexamples and negative oracles

Before the repair, the five newly added regression groups failed as expected.
After the repair, raw and parsed fake transports reject split `secret-` / `token`
for all three event types even when ignored wire IDs change. The completing
fragment is not released.

Additional regressions prove:

- separate active items, summary indices, and content indices do not collide;
- ignored delta IDs do not allocate identity state or change identity mode;
- the identity count remains bounded;
- item boundaries, response completion, EOF, failure, cancellation, generator
  close, and explicit close clear semantic state;
- refusal and code-interpreter identities retain their existing behavior.

## UNIT-003 - verification record

Focused transport and Responses suite:

```text
296 passed
```

Phase-separated adversarial re-audit selection, run after the repair commit:

```text
8 passed
```

Full deterministic suite:

```text
3676 passed, 5 skipped, 11 warnings
```

Static checks:

```text
make lint: passed (ruff check, format check, ty, complexipy)
check_codex_compatibility.py: no compatibility-blocking changes
reviewed Codex source: 655224ffae098a85efeddf8289171ff3bd2624d1
git diff --check: passed
git show --check 51f3b2d: passed
codegraph sync: passed
```

All commands ran through the local `llm-rosetta` environment where applicable.
No live or integration-live target was invoked.

## Acceptance disposition

All five frozen acceptance criteria are satisfied deterministically. `AUD-025`
can be closed and the affected coverage rows restored to `Fresh
(deterministic)`.

## Residual risk

Real provider/Codex timing, external sinks, unsupported or covert encodings,
public deployment, availability, and recovery remain excluded or Unknown under
the approved profile. A Codex consumer change or a new Responses text event
invalidates this evidence.
