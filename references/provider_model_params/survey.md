# Provider Model Parameter Compatibility Survey

> Last updated: 2026-05-23
>
> This document catalogs parameter support differences across LLM providers
> relevant to llm-rosetta's translation pipeline. The goal is to inform the
> design of a lightweight capability/parameter schema that transforms can
> consult at runtime.

## Methodology

Parameters are compared against the **OpenAI Chat Completions** spec as the
baseline, since most providers expose OpenAI-compatible endpoints and
`openai_chat` is the dominant base converter in llm-rosetta.

Sources: official API documentation, SDK references, and empirical testing
via existing shim transforms.

---

## 1. Quick Reference — Parameter Support Matrix

Legend: ✅ supported | ❌ unsupported (will error) | ⚠️ silently ignored |
🔄 renamed/remapped | 📐 constrained (different range) | — not applicable

| Parameter | OpenAI | Anthropic | Google | DeepSeek | xAI | Qwen | Zhipu | MiniMax | Moonshot | Volcengine |
|-----------|--------|-----------|--------|----------|-----|------|-------|---------|---------|------------|
| **Sampling** | | | | | | | | | | |
| `temperature` | ✅ 0–2 | ✅ 0–1 | ✅ 0–2 | ✅ 0–2 | ✅ 0–2 | ✅ 0–2 | 📐 0–1 | ✅ (0,1] | ✅ 0–1 | ✅ 0–2 |
| `top_p` | ✅ 0–1 | ✅ 0–1 | ✅ 0–1 | ✅ 0–1 | ✅ 0–1 | ✅ 0–1 | 📐 0.01–1 | ✅ 0–1 | ✅ 0–1 | ✅ 0–1 |
| `top_k` | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |
| `seed` | ✅ | ❌ | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| `n` | ✅ | ❌ | ✅† | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ |
| **Output Control** | | | | | | | | | | |
| `max_tokens` | ✅‡ | ✅ (req) | 🔄§ | ✅ | ⚠️‡ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `max_completion_tokens` | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅‡‡‡ |
| `stop` | ✅ | 🔄¶ | 🔄§ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| `response_format` | ✅ | ❌ | 🔄§ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Penalties** | | | | | | | | | | |
| `frequency_penalty` | ✅ -2–2 | ❌ | ❌ | ⚠️∥ | ✅ | ❌ | ❌ | ⚠️ | ✅ | ⚠️‡‡‡ |
| `presence_penalty` | ✅ -2–2 | ❌ | ❌ | ⚠️∥ | ⚠️# | ❌ | ❌ | ⚠️ | ✅ | ⚠️‡‡‡ |
| `logit_bias` | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ⚠️ | ❌ | ⚠️‡‡‡ |
| **Logging** | | | | | | | | | | |
| `logprobs` | ✅ | ❌ | ❌ | ✅ | ⚠️** | ✅ | ❌ | ❌ | ❌ | ⚠️‡‡‡ |
| `top_logprobs` | ✅ | ❌ | ❌ | ✅ | ⚠️** | ✅ | ❌ | ❌ | ❌ | ⚠️‡‡‡ |
| **Thinking / Reasoning** | | | | | | | | | | |
| Reasoning mode | ✅†† | ✅‡‡ | ✅§§ | ✅¶¶ | ✅∥∥ | ✅## | ❌ | ❌ | ❌ | ✅*** |
| `reasoning_effort` | ✅ | — | — | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |

**Footnotes:**

- † Google uses `candidateCount` instead of `n`
- ‡ OpenAI: `max_tokens` deprecated for newer models → `max_completion_tokens`;
  xAI: same deprecation pattern
- § Google uses different field names under `generationConfig`
  (`maxOutputTokens`, `stopSequences`, `responseMimeType`)
- ¶ Anthropic uses `stop_sequences` (list of strings)
- ∥ DeepSeek V4: `frequency_penalty` and `presence_penalty` deprecated
- \# xAI: `presence_penalty` not supported by Grok-3 and reasoning models
- \*\* xAI: `logprobs` silently ignored on Grok-4.20+
- †† OpenAI: reasoning via o-series models; `reasoning_effort` (low/medium/high);
  no `temperature`, `top_p` for reasoning models
- ‡‡ Anthropic: `thinking.type` = enabled/disabled/adaptive;
  `thinking.budget_tokens`; temperature/top_k **rejected** when thinking
  active; top_p restricted to [0.95, 1.0]
- §§ Google: `thinkingConfig.thinkingBudget`
- ¶¶ DeepSeek: thinking via model name suffix or parameter;
  `reasoning_effort` (high/max)
- ∥∥ xAI: `reasoning_effort` (low/high for chat completions)
- \#\# Qwen: thinking via `enable_thinking` parameter in some models
- ‡‡‡ Volcengine: model-generation-specific — `frequency_penalty`/`presence_penalty`
  unsupported on Seed 1.8/2.0; `logprobs`/`top_logprobs`/`logit_bias` unsupported
  on thinking models; `max_completion_tokens` mutually exclusive with `max_tokens`
- \*\*\* Volcengine: thinking support via Doubao-thinking models;
  `reasoning_effort` (minimal/low/medium/high)

---

## 2. Per-Provider Details

### 2.1 OpenAI

**Base:** Reference standard for `openai_chat` converter.

**Endpoint:** `POST /v1/chat/completions`

**Standard models (GPT-4o, GPT-4.1, etc.):**
- Full parameter support — temperature [0,2], top_p, seed, n, logprobs,
  top_logprobs, frequency_penalty [-2,2], presence_penalty [-2,2],
  logit_bias, stop, max_tokens, response_format, stream
- `max_completion_tokens` preferred over `max_tokens` for newer models

**Reasoning models (o-series: o1, o3, o4-mini, etc.):**
- 🚫 `temperature` — not supported (must be 1 or omitted)
- 🚫 `top_p` — not supported (must be 1 or omitted)
- 🚫 `presence_penalty` — not supported
- 🚫 `frequency_penalty` — not supported
- 🚫 `logprobs` / `top_logprobs` — not supported
- ✅ `reasoning_effort` — low / medium / high (controls thinking depth)
- ✅ `max_completion_tokens` — required (replaces `max_tokens`)
- Response includes `reasoning_content` in message output

**Key insight for llm-rosetta:** OpenAI itself has model-level parameter
incompatibilities within a single provider. The o-series models require
stripping sampling and penalty parameters that standard models accept.
This is a strong argument for model-level capability awareness.

**References:**
- https://platform.openai.com/docs/api-reference/chat/create
- https://platform.openai.com/docs/guides/reasoning

---

### 2.2 Anthropic

**Base:** Native `anthropic` converter.

**Endpoint:** `POST /v1/messages`

**All models (Claude Opus 4, Sonnet 4, Haiku 3.5, etc.):**
- `model` — **required**, enumerated model IDs
- `max_tokens` — **required** (set to 0 for cache pre-warming only)
- `messages` — **required**, alternating user/assistant turns (limit 100k)
- `temperature` — range [0, 1] (default 1.0)
- `top_p` — range [0, 1]
- `top_k` — ✅ (unique to Anthropic among major providers)
- `stop_sequences` — list of strings (not `stop`)
- `stream` — boolean
- `system` — separate top-level field (not in messages array)
- `tool_choice` — `auto` | `any` | `tool` (with `name`) | `none`;
  each variant has optional `disable_parallel_tool_use: boolean`
- `tools` — client tools + server tools (web_search, code_execution, etc.)
- `metadata` — contains `user_id` for abuse detection
- `output_config` — contains `effort` and `format` (JSON schema output)
- `cache_control` — ephemeral caching, TTL `"5m"` or `"1h"`
- `service_tier` — `"auto"` | `"standard_only"`

**Not supported (no OpenAI equivalent):**
- ❌ `n` — single completion only
- ❌ `seed` — no deterministic generation
- ❌ `logprobs` / `top_logprobs`
- ❌ `logit_bias`
- ❌ `frequency_penalty` / `presence_penalty`
- ❌ `response_format` (uses `output_config.format` for structured output)
- ❌ `max_completion_tokens` (uses `max_tokens`)

**Extended thinking — three mode variants:**

| Mode | Config | Description |
|------|--------|-------------|
| `"enabled"` | `{type: "enabled", budget_tokens: N}` | Always think; `budget_tokens` ≥ 1024 and < `max_tokens` |
| `"adaptive"` | `{type: "adaptive"}` | Model decides when/how much to think |
| `"disabled"` | `{type: "disabled"}` | Explicitly no thinking |

Both `"enabled"` and `"adaptive"` accept optional `display`:
`"summarized"` | `"omitted"` (default varies by model).

**Sampling constraints when thinking is active (enabled or adaptive):**
- `temperature` — ❌ **rejected** if set to non-default (not "locked to 1.0"
  — the request fails entirely)
- `top_k` — ❌ **rejected** if set
- `top_p` — ⚠️ restricted to [0.95, 1.0] only
- `tool_choice` — only `"auto"` or `"none"` allowed; `"any"` and
  `{"type": "tool"}` are rejected
- Response pre-fill — ❌ cannot pre-fill assistant messages

**`output_config.effort` levels (used with adaptive thinking):**

| Level | Availability |
|-------|-------------|
| `"low"` | Opus 4.5+, Sonnet 4.6+, Mythos |
| `"medium"` | Opus 4.5+, Sonnet 4.6+, Mythos |
| `"high"` (default) | Opus 4.5+, Sonnet 4.6+, Mythos |
| `"xhigh"` | **Opus 4.7 only** |
| `"max"` | Mythos, Opus 4.7, Opus 4.6, Sonnet 4.6 |

**Model-specific thinking support:**

| Model | `enabled` | `adaptive` | `disabled` | Default `display` |
|-------|-----------|------------|------------|-------------------|
| Opus 4.7 | ❌ rejected | ✅ only mode | ✅ (off by default) | `"omitted"` |
| Mythos Preview | ✅ | ✅ default | ❌ not supported | `"omitted"` |
| Opus 4.6 | ⚠️ deprecated | ✅ recommended | ✅ | `"summarized"` |
| Sonnet 4.6 | ⚠️ deprecated | ✅ recommended | ✅ | `"summarized"` |
| Opus 4.5 | ✅ required | ❌ | ✅ | `"summarized"` |
| Sonnet 4.5 | ✅ required | ❌ | ✅ | `"summarized"` |
| Haiku 4.5 | ✅ | ❌ | ✅ | `"summarized"` |

**Key insight for llm-rosetta:** Anthropic's thinking mode is the most
complex among all providers. The fact that Opus 4.7 **rejects** `enabled`
mode (only accepts `adaptive`) while older models **require** `enabled`
(don't support `adaptive`) makes this a critical model-level capability
that transforms must handle. The ARGO shim's `_ADAPTIVE_THINKING_MODELS`
frozenset is a direct response to this.

**References:**
- https://docs.anthropic.com/en/api/messages
- https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking

---

### 2.3 Google Gemini

**Base:** Native `google` converter (Google GenAI SDK).

**Endpoint:** `POST /v1/models/{model}:generateContent`

**Parameter mapping (completely different schema):**

| OpenAI Field | Google Equivalent |
|-------------|-------------------|
| `temperature` | `generationConfig.temperature` (0–2) |
| `top_p` | `generationConfig.topP` |
| `top_k` | `generationConfig.topK` (✅ supported) |
| `max_tokens` | `generationConfig.maxOutputTokens` |
| `n` | `generationConfig.candidateCount` |
| `stop` | `generationConfig.stopSequences` |
| `response_format` | `generationConfig.responseMimeType` + `responseSchema` |
| `seed` | `generationConfig.seed` |

**Not supported:**
- ❌ `frequency_penalty` / `presence_penalty`
- ❌ `logit_bias`
- ❌ `logprobs` / `top_logprobs`

**Thinking support:**
- `generationConfig.thinkingConfig.thinkingBudget` — token budget for reasoning
- Available on Gemini 2.5 Flash/Pro models

**References:**
- https://ai.google.dev/api/generate-content
- https://ai.google.dev/gemini-api/docs/thinking

---

### 2.4 DeepSeek

**Base:** `openai_chat` (OpenAI-compatible).

**Current shim strips:** `n`, `logit_bias`, `seed`

**DeepSeek V4 models (deepseek-v4-flash, deepseek-v4-pro):**
- `temperature` — [0, 2] (default 1.0)
- `top_p` — [0, 1] (default 1.0)
- ❌ `n` — not supported (always 1)
- ❌ `logit_bias` — not supported
- ❌ `seed` — not supported
- ✅ `logprobs` / `top_logprobs` — supported (up to 20)
- ✅ `stop` — supported (up to 16 strings)
- ✅ `response_format` — json_object supported
- ⚠️ `frequency_penalty` — **deprecated in V4**, defaults to 0
- ⚠️ `presence_penalty` — **deprecated in V4**, defaults to 0

**Thinking mode:**
- Enabled via model name (e.g., `deepseek-reasoner`) or parameter
- `reasoning_effort` — `"high"` | `"max"`
- Response includes `reasoning_content` field

**Key insight:** The `frequency_penalty` / `presence_penalty` deprecation
in V4 means our shim may need updating — currently we strip `n`,
`logit_bias`, `seed` but not the penalties. For V4 models specifically,
stripping or warning about penalties would be appropriate.

**References:**
- https://api-docs.deepseek.com/api/create-chat-completion

---

### 2.5 xAI (Grok)

**Base:** `openai_chat` (OpenAI-compatible).

**Current shim strips:** `logit_bias`

**All Grok models:**
- `temperature` — [0, 2] (default 0)
- `top_p` — [0, 1] (default 1)
- ✅ `seed` — supported
- ✅ `n` — supported
- ✅ `stop` — supported
- ✅ `response_format` — json supported
- ❌ `logit_bias` — explicitly unsupported

**Model-specific quirks:**
- `logprobs` / `top_logprobs` — silently ignored on Grok-4.20+
- `presence_penalty` — **not supported** by Grok-3 and reasoning models
- `max_tokens` — **deprecated** in favor of `max_completion_tokens`

**Reasoning:**
- `reasoning_effort` — `"low"` | `"high"` (for chat completions)
- Response includes `reasoning_content` in message

**Key insight:** xAI has model-generation-specific differences —
Grok-4.20+ silently drops logprobs, Grok-3 doesn't support
presence_penalty. A per-model capability table would help here.

**References:**
- https://docs.x.ai/docs/api-reference#chat-completions

---

### 2.6 Qwen (DashScope)

**Base:** `openai_chat` (OpenAI-compatible via DashScope).

**Current shim strips:** `frequency_penalty`, `logit_bias`

**Qwen models (qwen-plus, qwen-max, qwen-turbo, etc.):**
- `temperature` — [0, 2]
- `top_p` — [0, 1]
- `top_k` — ✅ supported (unique among OpenAI-compatible providers)
- ✅ `seed` — supported
- ✅ `n` — supported
- ✅ `logprobs` / `top_logprobs` — supported
- ✅ `stop` — supported
- ❌ `frequency_penalty` — not supported (use `repetition_penalty` via
  `extra_body`)
- ❌ `logit_bias` — not supported
- `presence_penalty` — ❌ not supported (same as frequency_penalty)
- ✅ `response_format` — json_object supported

**Thinking:**
- `enable_thinking` parameter for QwQ and Qwen3 series
- Thinking content returned in response

**References:**
- https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope

---

### 2.7 Zhipu (GLM)

**Base:** `openai_chat` (OpenAI-compatible).

**Current shim strips:** `n`, `presence_penalty`, `frequency_penalty`,
`logprobs`, `top_logprobs`, `logit_bias`, `seed`

**GLM models (glm-4-plus, glm-4-flash, etc.):**
- `temperature` — 📐 range [0, **1**] (not [0, 2] like OpenAI!)
- `top_p` — 📐 range [**0.01**, 1] (minimum is 0.01, not 0)
- ❌ `n` — not supported
- ❌ `presence_penalty` — not supported
- ❌ `frequency_penalty` — not supported
- ❌ `logprobs` / `top_logprobs` — not supported
- ❌ `logit_bias` — not supported
- ❌ `seed` — not supported
- ✅ `stop` — supported
- ✅ `max_tokens` — supported
- ✅ `response_format` — supported

**⚠️ Value clamping needed:** The temperature and top_p ranges are
narrower than OpenAI's. A request with `temperature: 1.5` would need
clamping to 1.0 for Zhipu. This is NOT handled by the current shim
(noted as a TODO in the transforms.py docstring).

**References:**
- https://docs.bigmodel.cn
- https://docs.z.ai/api-reference/llm/chat-completion

---

### 2.8 MiniMax

**Base:** `openai_chat` (OpenAI-compatible).

**Current shim strips:** `logprobs`, `top_logprobs`, `seed`, `stop`

**MiniMax models (MiniMax-Text-01, abab-series):**
- `temperature` — range (0, 1] (default 0.1)
- `top_p` — [0, 1] (default 0.95)
- ✅ `n` — supported
- ❌ `logprobs` / `top_logprobs` — not supported
- ❌ `seed` — not supported
- ❌ `stop` — not supported
- ⚠️ `frequency_penalty` — silently ignored (no error)
- ⚠️ `presence_penalty` — silently ignored (no error)
- ⚠️ `logit_bias` — silently ignored (no error)
- ✅ `max_tokens` — supported
- ✅ `response_format` — supported

**⚠️ Temperature range:** MiniMax's temperature range (0, 1] is narrower
than OpenAI's [0, 2]. Similar to Zhipu, value clamping may be needed.

**References:**
- https://platform.minimaxi.com/document/ChatCompletion%20v2

---

### 2.9 Moonshot (Kimi)

**Base:** `openai_chat` (OpenAI-compatible).

**Current shim strips:** `logprobs`, `top_logprobs`, `logit_bias`, `seed`

**Moonshot models (moonshot-v1-8k, moonshot-v1-32k, moonshot-v1-128k):**
- `temperature` — [0, 1] (default 0.3)
- `top_p` — [0, 1] (default 1.0)
- ✅ `n` — supported
- ✅ `stop` — supported
- ✅ `max_tokens` — supported
- ✅ `frequency_penalty` — supported
- ✅ `presence_penalty` — supported
- ❌ `logprobs` / `top_logprobs` — not supported
- ❌ `logit_bias` — not supported
- ❌ `seed` — not supported
- ✅ `response_format` — supported

**References:**
- https://platform.moonshot.cn/docs/api/chat

---

### 2.10 Volcengine (Doubao)

**Base:** `openai_chat` (OpenAI-compatible via ARK platform).

**Endpoint:** `POST https://ark.cn-beijing.volces.com/api/v3/chat/completions`

**Current shim strips:** `logprobs`, `top_logprobs`

**⚠️ Shim accuracy concern:** The current shim globally strips
`logprobs`/`top_logprobs`, but these are only unsupported on **thinking
models** — standard models (doubao-1.5-pro etc.) do support them. This
is a model-level distinction, not a provider-level one.

**Globally supported parameters:**
- `temperature` — [0, 2] (default 1.0)
- `top_p` — [0, 1] (**default 0.7**, unlike OpenAI's 1.0)
- `max_tokens` — supported (range varies by model)
- `max_completion_tokens` — [0, 65536], includes thinking tokens;
  **mutually exclusive** with `max_tokens`
- `stop` — up to 4 strings
- `response_format` — `text`, `json_object`, `json_schema` (beta)
- `tools` — function calling
- `stream` / `stream_options` — supported
- `service_tier` — `"auto"` | `"default"` (TPM guarantee tier)

**Globally unsupported:**
- ❌ `n` — single completion only
- ❌ `seed` — no deterministic generation
- ❌ `user` — not supported
- ❌ `top_k` — not supported

**Model-generation-specific differences (critical):**

| Parameter | doubao-1.5 (pro/lite) | Seed 1.6 | Seed 1.8 | Seed 2.0 | Thinking models |
|-----------|----------------------|----------|----------|----------|-----------------|
| `frequency_penalty` | ✅ | ✅ | ❌ | ❌ | ❌ |
| `presence_penalty` | ✅ | ✅ | ❌ | ❌ | ❌ |
| `logprobs` | ✅ | ✅ | ✅ | ✅ | ❌ |
| `top_logprobs` | ✅ | ✅ | ✅ | ✅ | ❌ |
| `logit_bias` | ✅ | ✅ | ✅ | ✅ | ❌ |
| `stop` | ✅ | ✅ | ✅ | ✅ | ❌ |
| `tool_choice` | ❌ | ✅ | ✅ | ✅ | — |
| `parallel_tool_calls` | ❌ | ✅ | ✅ | ✅ | — |

**Thinking models (doubao-1.5-thinking-pro, doubao-seed-1.6-thinking, etc.):**
- `thinking` — `{type: "enabled"}` | `{type: "disabled"}` | `{type: "auto"}`
- `reasoning_effort` — `"minimal"` | `"low"` | `"medium"` (default) | `"high"`
- Response: `reasoning_content` field + optional `encrypted_content`
  (seed-2.0-lite+, for compressed reasoning round-trip)
- Thinking models strip: `logprobs`, `top_logprobs`, `logit_bias`, `stop`

**Key insight for llm-rosetta:** Volcengine is the strongest example of
**intra-provider model-level differences** beyond just thinking mode. The
penalty parameters (`frequency_penalty`, `presence_penalty`) are supported
by older models but rejected by newer Seed 1.8/2.0 models. The `top_p`
default difference (0.7 vs 1.0) means parameter passthrough may produce
different behavior than expected. The current shim's global stripping
of `logprobs`/`top_logprobs` is inaccurate — it should be model-level.

**References:**
- https://www.volcengine.com/docs/82379/1494384 (Chat API reference)
- https://docs.byteplus.com/en/docs/ModelArk/1494384 (English API ref)
- https://www.volcengine.com/docs/82379/1449737 (Deep thinking guide)
- https://www.volcengine.com/docs/82379/1536428 (Thinking model details)

---

### 2.11 OpenRouter

**Base:** `openai_chat` (OpenAI-compatible).

**Current shim:** No transforms (pass-through).

OpenRouter is a **meta-router** that forwards requests to downstream
providers. It accepts a **superset** of OpenAI Chat Completions parameters
and handles per-model compatibility internally.

**Accepted parameters (superset of OpenAI):**

All standard OpenAI Chat Completions parameters, PLUS:
- `top_k` — integer ≥ 0 (not available for OpenAI models)
- `repetition_penalty` — float 0–2 (non-OpenAI parameter)
- `min_p` — float 0–1 (non-OpenAI parameter)
- `top_a` — float 0–1 (non-OpenAI parameter)
- `verbosity` — enum (maps to `output_config.effort` for Anthropic)

**Unsupported parameter handling:**

> *"If the chosen model doesn't support a request parameter (such as
> `logit_bias` in non-OpenAI models, or `top_k` for OpenAI), then the
> parameter is ignored."*

Default behavior = **silent stripping**. The `require_parameters: true`
flag in the `provider` object forces strict validation (only route to
providers supporting all requested parameters).

**Per-model capabilities metadata:**

The `/api/v1/models` endpoint returns `supported_parameters` per model:
- `openai/gpt-4o`: `["frequency_penalty", "logit_bias", "logprobs", ...]`
- `anthropic/claude-sonnet-4`: `["max_tokens", "reasoning", "stop",
  "temperature", "tool_choice", "tools", "top_k", "top_p"]`
- `google/gemini-2.5-flash`: `["include_reasoning", "max_tokens",
  "reasoning", "response_format", "seed", "stop", ...]`

Models can also declare `default_parameters` with explicit `null` values
to override OpenRouter's defaults (e.g., Anthropic models set
`temperature: null` so OpenRouter doesn't inject `temperature=1.0`).

**Routing control (`provider` object):**
- `order` — prioritize specific provider slugs
- `allow_fallbacks` — disable fallback routing
- `require_parameters` — strict parameter validation
- `sort` — by `"price"`, `"throughput"`, or `"latency"`
- `only` / `ignore` — provider whitelist/blacklist

**Our approach:** Since OpenRouter handles parameter compatibility itself,
the llm-rosetta shim should remain a no-op pass-through. The rich
`supported_parameters` metadata from the models endpoint could be useful
for future capability-aware routing.

**References:**
- https://openrouter.ai/docs/api-reference/chat-completions
- https://openrouter.ai/docs/features/provider-routing

---

### 2.12 ARGO (Argonne)

**Base:** Both `anthropic` and `openai_chat` (two separate shims).

**Current shim: argo_anthropic:**
- `to_transforms`: `_normalize_thinking()` — converts `thinking.type`
  between `"adaptive"` and `"enabled"` based on model
- `from_transforms`: `_normalize_openai_response()` — fixes response
  format inconsistency (some models return OpenAI format on Anthropic
  endpoint)

**Current shim: argo_openai_chat:**
- No transforms

**Model-specific logic:**
- `_ADAPTIVE_THINKING_MODELS` frozenset tracks which internal model IDs
  support `thinking.type = "adaptive"` (currently only `claudeopus47`)
- All other models get `"adaptive"` → `"enabled"` conversion with
  auto-calculated `budget_tokens`

**Key insight:** ARGO is the strongest existing example of model-level
parameter differences within a single provider shim. The hardcoded
frozenset is a prototype for what a capability table would formalize.

---

## 3. Cross-Cutting Observations

### 3.1 Parameters that need stripping (current shim coverage)

| Parameter | Stripped by providers |
|-----------|---------------------|
| `logit_bias` | deepseek, moonshot, xai, qwen, zhipu |
| `seed` | deepseek, minimax, moonshot, zhipu |
| `logprobs` | minimax, moonshot, volcengine (thinking models only), zhipu |
| `top_logprobs` | minimax, moonshot, volcengine (thinking models only), zhipu |
| `n` | deepseek, zhipu |
| `frequency_penalty` | qwen, zhipu |
| `presence_penalty` | zhipu |
| `stop` | minimax |

### 3.2 Parameters that need value clamping (NOT currently handled)

| Parameter | Provider | OpenAI Range | Provider Range | Action Needed |
|-----------|----------|-------------|----------------|---------------|
| `temperature` | Zhipu | [0, 2] | [0, 1] | Clamp to 1.0 |
| `temperature` | MiniMax | [0, 2] | (0, 1] | Clamp to 1.0, floor to 0.01 |
| `temperature` | Moonshot | [0, 2] | [0, 1] | Clamp to 1.0 |
| `temperature` | Anthropic | [0, 2] | [0, 1] | Clamp to 1.0 |
| `top_p` | Zhipu | [0, 1] | [0.01, 1] | Floor to 0.01 |

### 3.3 Parameters that need conditional handling (model-level)

| Scenario | Provider | Details |
|----------|----------|---------|
| Reasoning models strip sampling | OpenAI | o-series: no temperature, top_p, penalties |
| Thinking rejects sampling params | Anthropic | temperature/top_k rejected; top_p restricted to [0.95,1.0] |
| Thinking mode varies by model | Anthropic | Opus 4.7: adaptive only; Opus 4.5: enabled only; Mythos: can't disable |
| Adaptive vs enabled thinking | ARGO | Per-model frozenset (mirrors Anthropic model-level differences) |
| logprobs silently ignored | xAI | Grok-4.20+ |
| presence_penalty unsupported | xAI | Grok-3 + reasoning models |
| Deprecated penalties | DeepSeek | V4 models |
| max_tokens → max_completion_tokens | OpenAI, xAI | Newer model generations |
| Penalties unsupported on newer models | Volcengine | Seed 1.8/2.0: no frequency/presence_penalty |
| Logging params stripped by thinking | Volcengine | Thinking models: no logprobs/logit_bias/stop |
| top_p default difference | Volcengine | Default 0.7 vs OpenAI 1.0 — passthrough may surprise |

### 3.4 Gap analysis — what the current shims DON'T handle

1. **Value clamping** — temperature/top_p range differences (Zhipu, MiniMax,
   Moonshot, Anthropic) are documented but not enforced
2. **Model-level parameter differences** — only ARGO has model-level logic;
   OpenAI (o-series), xAI (Grok generations), DeepSeek (V4) all have
   model-specific quirks that are not handled
3. **Deprecation warnings** — no mechanism to warn about deprecated params
   (DeepSeek penalties, OpenAI max_tokens, xAI max_tokens)
4. **Reasoning/thinking normalization** — each provider has a different
   thinking API; cross-provider thinking translation is not yet implemented
   (only ARGO's internal normalization exists)
5. **Inaccurate stripping** — Volcengine shim globally strips `logprobs` /
   `top_logprobs`, but these are only unsupported on **thinking models** —
   standard models support them. Additionally, Seed 1.8/2.0 models don't
   support `frequency_penalty`/`presence_penalty` but the shim doesn't
   strip those. Also missing: `n`, `seed` (globally unsupported)

---

## 4. Implications for llm-rosetta Capability System

### 4.1 What belongs in a capability table

Based on this survey, the capability table should track:

**Binary decisions (strip/keep):**
- `unsupported_params`: list of parameter names to strip per-model
  (generalizes the current `strip_fields` approach)

**Value constraints (clamp/adjust):**
- `temperature_range`: `[min, max]` — clamp incoming values
- `top_p_range`: `[min, max]` — clamp incoming values

**Thinking/reasoning mode:**
- `thinking_type`: which thinking API variant this model uses
  (none / openai_reasoning / anthropic_thinking / deepseek_thinking / ...)
- `thinking_params`: model-specific thinking parameter support

**Deprecation/migration:**
- `max_tokens_field`: `"max_tokens"` | `"max_completion_tokens"` — which
  field name the provider expects

### 4.2 What should NOT be in the capability table

- **Feature capabilities** (vision, embedding, audio) — let upstream errors
  propagate; the translation SDK doesn't need to pre-validate these
- **Context window sizes** — informational, doesn't affect translation
- **Pricing** — not relevant to format translation
- **Rate limits** — handled at gateway level, not converter level

### 4.3 Proposed hierarchy

```
providers/{name}/
├── provider.yaml          # identity card (existing)
├── transforms.py          # transform functions (existing)
└── capabilities.yaml      # NEW: per-model parameter constraints
```

The `capabilities.yaml` is optional — providers without it get permissive
defaults (all parameters accepted, no clamping). Transforms consult the
capability table at runtime via a helper function.

### 4.4 Transform primitives needed

Beyond the existing `strip_fields`, `rename_field`, `set_defaults`:

- **`clamp_field(name, min, max)`** — clamp numeric values to a range
- **`strip_for_model(capabilities)`** — model-aware field stripping
  (consults capability table using the `model` field from the request body)

These can be implemented as new transform factory functions in
`shims/transforms.py`.
