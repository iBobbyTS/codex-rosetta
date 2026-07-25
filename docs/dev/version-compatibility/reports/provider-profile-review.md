# Provider Profile Responsibility Full-Inventory Review

Date: 2026-07-25

Codex version: 0.145.0 source baseline (no version adoption in this review)

## Scope and decision

This full-inventory review covers the refactor that makes `provider + api_type`
the sole owner of wire request construction. It is not a Codex version upgrade
or a broad compatibility approval. The model name now participates only in
preset matching, catalog/capability metadata, the upstream `model` value, and
logs. Tool Profile/catalog data remains the sole owner of model-visible tool
exposure and schema changes.

The review repeated the CodeGraph owner scan, a bounded text scan for model-name
wire branches, the stable CP-01..CP-23 ledger mapping, and the user/developer
documentation scan required by the full-inventory workflow.

## New owners and pipeline

The route resolves these immutable/effective objects before conversion:

1. standard source protocol;
2. immutable `ProviderProfile` selected by explicit provider main identity plus
   `api_type`;
3. one `ResolvedModelProfile`, produced by preset copy plus recursive config
   overlay and provider runtime-preset copy plus recursive runtime overlay;
4. Tool Profile selected independently from model identity.

The request path is source protocol to IR, resolved capability enforcement,
target standard converter, provider-wide extension, then transport. Response
processing reverses that order. Unadapted provider/protocol combinations use
only the selected official standard and emit a warning; they do not receive
provider extensions.

## Removed model-specific adaptations

The following combinations are intentionally no longer claimed as adapted:

| Former special case | Removed behavior | Current disposition |
| --- | --- | --- |
| Anthropic `claude-haiku-4-5-20251001` | enabled thinking with derived budget; no effort field | Uses the selected Anthropic Provider Profile standard without a model-specific exception |
| Anthropic `claude-opus-4-7` / `claude-opus-4-8` | forced adaptive thinking | Uses the provider-wide Anthropic declaration |
| Argo Anthropic `claudehaiku45` / `claudesonnet4` | enabled thinking with derived budget | Uses the provider-wide Argo Anthropic declaration |
| Argo Anthropic `claudeopus47` / `claudeopus48` | forced adaptive thinking | Uses the provider-wide Argo Anthropic declaration |
| Argo Chat `claudeopus47*` | stripped `temperature` | No model-specific temperature mutation |
| Argo Chat `gpt*` / `o*` | truncated image count to 50 | No model-specific image-count mutation |
| Argo Chat `gemini*` | unwound parallel tool calls | No model-pattern parallel-tool mutation |
| DeepSeek V4, GLM 5.2, Qwen 3.7, Kimi K2.7 Code, MiniMax M3, MiMo V2.5 name patterns | selected raw reasoning/thinking fields and budgets by model name | Removed mapper APIs now raise a migration error; provider/protocol standard owns fields |

Provider-wide transforms remain valid. Model-pattern arguments to image
truncation and parallel-tool unwind are removed. Legacy
`reasoning.model_overrides`, `reasoning_mapping`, and raw mapper entry points
return actionable migration errors instead of silently changing request shape.

## Stable compatibility ledger classification

`Changed` below means this refactor changed a Rosetta owner or configuration
contract. The limited live checks validate only basic routing and do not close
the existing real-agent gates.

| ID and compatibility point | Classification | Evidence and disposition | Real API result |
| --- | --- | --- | --- |
| `CP-01 — Agent-facing API` | Changed | Explicit provider identity and protocol now fail closed; `ResolvedRoute` carries actual Provider and Model Profiles | Four minimal route cells completed as recorded below |
| `CP-02 — Responses transparent handling` | Changed | Unadapted Responses still uses the one direct standard; selection no longer depends on URL/model | Terra direct Responses cell passed; no raw-wire/attestation rerun |
| `CP-03 — Codex Search and Images endpoints` | High-confidence unchanged | No endpoint, credential, or Tool Profile declaration owner changed | Not triggered |
| `CP-04 — Request and window identity` | High-confidence unchanged | No identity/state owner changed | Not triggered |
| `CP-05 — Responses→Chat bridge` | Changed | Target shape is selected by Provider Profile; model name cannot mutate raw fields | DeepSeek, GLM, and Kimi minimal bridge cells passed; no tools/history |
| `CP-06 — Responses Lite / additional_tools` | High-confidence unchanged | Tool/Profile path unchanged | Not triggered |
| `CP-07 — Codex model catalog` | Changed | Complete-record preset copy, recursive merge/diff, provider runtime preset, and one shared `ResolvedModelProfile` | Basic route cells only; no Codex catalog/UI live rerun |
| `CP-08 — custom/freeform tool` | High-confidence unchanged | Tool converter and Tool Profile ownership unchanged | Not triggered |
| `CP-09 — Code tool localization` | High-confidence unchanged | No model-visible tool declaration changed | Not triggered |
| `CP-10 — Tool history consistency` | High-confidence unchanged | Persistence/replay owner unchanged | Not triggered |
| `CP-11 — Deferred tool discovery` | High-confidence unchanged | Catalog/runtime discovery owner unchanged | Not triggered |
| `CP-12 — Codex tool usage tips` | High-confidence unchanged | Tool descriptions remain catalog-owned | Not triggered |
| `CP-13 — Skill delivery surfaces` | High-confidence unchanged | No Skill surface changed | Not triggered |
| `CP-14 — Live-agent runtime authentication` | Changed | Provider config now requires recognized explicit main identity and protocol; generated local Provider remains explicit OpenAI Responses | No live-agent run; isolated gateway used existing bearer configuration |
| `CP-15 — Web search bridge` | High-confidence unchanged | Search execution path unchanged | Not triggered |
| `CP-16 — Self-hosted Bing search` | High-confidence unchanged | No search-provider owner changed | Not triggered |
| `CP-17 — Stream lifecycle` | Changed | Provider Profile now selects response extension/usage parsing, including OpenCode Chat semantics | Non-streaming only; streaming remains unverified |
| `CP-18 — Message phase` | High-confidence unchanged | Phase buffer unchanged | Not triggered |
| `CP-19 — Reasoning` | Changed | Model-name mapper deleted; provider/profile controls wire fields; model capability only clamps supported effort | Deterministic reasoning/content/usage tests; basic live requests only |
| `CP-20 — Context compaction resilience` | High-confidence unchanged | Compaction identity/hash selection remains upstream-model capability metadata, not request-field construction | Not triggered |
| `CP-21 — GPT relay provider identity` | Changed | Provider identity is explicit and URL inference is rejected | Terra route passed; relay C0-C5 not rerun |
| `CP-22 — Model-group tool profiles` | Changed | Provider catalog dynamically supplies protocol groups and recommendations; Tool Profile ownership itself is unchanged | No tool live rerun |
| `CP-23 — Static tool catalog` | High-confidence unchanged | Catalog entries and model-visible tool schemas unchanged | Not triggered |

## Deterministic evidence

- Architecture regression: two model names under the same OpenCode Go Chat
  Profile produce byte-equivalent request structure except for `model`.
- Provider recommendations, adapted/known/other protocol grouping data,
  unadapted standard fallback, recursive catalog immutability, and fail-closed
  unknown identity are covered by provider-profile tests.
- Complete preset matching, recursive merge/diff, array replacement, explicit
  null, unknown-preset validation, legacy eight-field reading, runtime fields,
  and canonical minimal persistence are covered by model-profile/Admin tests.
- OpenCode Go deterministic coverage includes Chat `reasoning_effort`, response
  `reasoning_content`, and cached-token usage normalization.

Final deterministic results from the current worktree:

- `make lint`: passed Ruff, formatting, `ty`, and the complexity ratchet.
- `make test`: 3,688 passed, 4 skipped, 11 warnings.
- WebUI `npm run check`: 0 errors and 0 warnings.
- WebUI `npm test`: 59 passed.
- WebUI `npm run build`: Admin and bootstrap production builds passed.
- `make check-codex-compat`: passed against Codex source commit
  `25af12f7e61572b0bc18ddb1008be543b91519b0`; no contract changes detected.

## Limited live route verification

Time: 2026-07-25 14:27:29 MDT (UTC-06:00)

Each cell sent a non-streaming Responses request containing `input: "hi"` to an
isolated current-worktree Gateway. No live agent, tools, images, streaming,
reasoning assertion, or long conversation was run.

| Model | Provider Profile | Target protocol | Result |
| --- | --- | --- | --- |
| `gpt-5.6-terra` | `openai:responses` | OpenAI Responses | HTTP 200 |
| `deepseek-v4-flash` | `deepseek:chat` | OpenAI Chat Completions | HTTP 200 |
| `glm-5.2` | `opencode_go:chat` | OpenAI Chat Completions | HTTP 200 |
| `kimi-k3` | `opencode_go:chat` | OpenAI Chat Completions | HTTP 200 |

OpenCode Go returned Cloudflare error 1010 for Python's default
`Python-urllib` User-Agent. Direct controls and the Gateway route succeeded
with `codex_cli_rs/0.145.0`; this is an upstream edge-policy observation, not a
request-body conversion defect. The temporary gateway used port 18765, was
stopped after the checks, and its isolated Codex Home was moved to Trash.

## Compatibility decision

The responsibility boundary and the four basic routes are accepted for this
implementation. Complete tools, images, streaming, reasoning continuity,
compaction, and long-session compatibility are explicitly not claimed from
these live checks. The existing 0.145.0 adoption status and package version do
not change as a result of this report.
