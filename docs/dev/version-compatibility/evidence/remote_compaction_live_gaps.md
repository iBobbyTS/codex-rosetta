# Remote compaction real-provider gaps
Date: 2026-07-15
Codex version: 0.144.0

Historical unresolved compatibility evidence; use the maintained ledger and
reports for current conclusions.

## Current evidence

- DeepSeek context-limit run `202607151343` completes canonical compaction and
  plaintext replay, but its three summaries omit all seven injected facts and
  cause the one-shot fixture command to run three times under the 1000-token
  diagnostic threshold. Protocol result: success. Test-executor summary review:
  ineffective.
- Terra-to-DeepSeek run `202607151346` triggers `comp_hash_changed` and Rosetta
  mode, but three internal `yieryier` responses contain no non-empty assistant
  text. Rosetta correctly returns 502 and creates no mapping.
- DeepSeek-to-Terra run `202607151349` succeeds with one mapping, all seven facts
  preserved, and the expected target marker.
- GPT native context-limit run `202607151328` succeeds through `yieryier` with
  one native compaction item and zero Rosetta mappings.

## Boundary

Do not weaken the protocol by accepting empty summaries or tool calls. Future
investigation should compare the model-facing no-tools summary request and the
bounded upstream response shape for the ineffective/empty cases without
persisting prompt or summary bodies in gateway logs.
