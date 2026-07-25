# OpenCode Go Protocol Probe

> Last tested: 2026-07-23 17:16:15 MDT (UTC-06:00)

## Scope

This record covers a live probe of every model returned by the authenticated
OpenCode Go `GET /zen/go/v1/models` endpoint at the recorded time. Each model
received one non-streaming `hi` request with `max_tokens: 16` through both:

- OpenAI Chat Completions: `POST /zen/go/v1/chat/completions`
- Anthropic Messages: `POST /zen/go/v1/messages`

A result is successful only when the endpoint returned HTTP 2xx without an
error object. The probe sent 46 requests: 30 succeeded and 16 failed.

## Results

| Model | Chat Completions | Anthropic Messages |
| --- | --- | --- |
| `deepseek-v4-flash` | 200 | 400, upstream rejected |
| `deepseek-v4-pro` | 200 | 400, upstream rejected |
| `glm-5` | 200 | 200 |
| `glm-5.1` | 200 | 200 |
| `glm-5.2` | 200 | 200 |
| `grok-4.5` | 200 | 401, unsupported Anthropic format |
| `hy3` | 200 | 400, upstream rejected |
| `hy3-preview` | 400, absent from the lite model list | 400, absent from the lite model list |
| `kimi-k2.5` | 200 | 400, upstream rejected |
| `kimi-k2.6` | 200 | 400, upstream rejected |
| `kimi-k2.7-code` | 200 | 400, upstream rejected |
| `kimi-k3` | 200 | 400, upstream rejected |
| `mimo-v2-omni` | 400, upstream rejected | 400, upstream rejected |
| `mimo-v2-pro` | 400, upstream rejected | 400, upstream rejected |
| `mimo-v2.5` | 200 | 400, upstream rejected |
| `mimo-v2.5-pro` | 200 | 400, upstream rejected |
| `minimax-m2.5` | 200 | 200 |
| `minimax-m2.7` | 200 | 200 |
| `minimax-m3` | 200 | 200 |
| `qwen3.5-plus` | 200 | 200 |
| `qwen3.6-plus` | 200 | 200 |
| `qwen3.7-max` | 200 | 200 |
| `qwen3.7-plus` | 200 | 200 |

## Project Decision

Based on the test results, this project will use the OpenAI Chat Completions
API for all OpenCode Go models.

This is a protocol-selection decision, not a claim that every model currently
listed by `GET /models` is callable. `hy3-preview`, `mimo-v2-omni`, and
`mimo-v2-pro` failed on both probed endpoints and must remain unavailable until
OpenCode Go exposes a working route for them.

## Rosetta Provider Profile Verification

> Last tested: 2026-07-25 14:27:29 MDT (UTC-06:00)

OpenCode Go is now one adapted Provider Profile using the OpenAI Chat
Completions standard. The Profile constructs `reasoning_effort`, parses
`reasoning_content`, and normalizes
`usage.prompt_tokens_details.cached_tokens` using OpenAI Chat semantics. Model
names do not select any of these fields.

The Provider catalog also exposes optional `temperature` and `top_p` request
overrides for OpenCode Go. Admin edits them in a separate Provider-limits
dialog. A numeric value replaces the corresponding request-IR sampling value,
an explicit `null` removes it, and an absent field preserves the client value.
No other Provider Profile currently declares these overrides. These are local
Rosetta routing controls, not a claim that OpenCode Go publishes proprietary
wire parameters beyond the OpenAI Chat standard.

Rosetta stores the OpenCode defaults as exact model-name presets derived from
the local OpenCode source checkout's `ProviderTransform.temperature()` and
`ProviderTransform.topP()` behavior. Resolution prefers `upstream_model` and
falls back to the exposed alias. The currently bound Go models are:

| Models | `temperature` | `top_p` |
| --- | ---: | ---: |
| `qwen3.5-plus`, `qwen3.6-plus`, `qwen3.7-max`, `qwen3.7-plus` | 0.55 | 1.0 |
| `minimax-m2.5`, `minimax-m2.7` | 1.0 | 0.95 |
| `kimi-k2.5` | 1.0 | 0.95 |
| `kimi-k2.6`, `kimi-k2.7-code` | 1.0 | inherited |

This is catalog data rather than a model-name conditional in the converter.
Admin auto-fills the matched values, and config persists only differences from
the matched Provider preset.

The following minimal checks sent an OpenAI Responses request containing only
`input: "hi"` through an isolated current-worktree Gateway. The Gateway then
used each resolved Provider Profile and target protocol. No tools, images,
multi-turn history, or live agent were exercised.

| Model | Provider Profile | Target protocol | Result |
| --- | --- | --- | --- |
| `gpt-5.6-terra` | `openai:responses` | OpenAI Responses | HTTP 200 |
| `deepseek-v4-flash` | `deepseek:chat` | OpenAI Chat Completions | HTTP 200 |
| `glm-5.2` | `opencode_go:chat` | OpenAI Chat Completions | HTTP 200 |
| `kimi-k3` | `opencode_go:chat` | OpenAI Chat Completions | HTTP 200 |

The OpenCode edge returned Cloudflare error 1010 when the diagnostic client
used Python's default `Python-urllib` User-Agent. Direct control requests and
the Gateway route both succeeded with the Codex `codex_cli_rs/0.145.0`
User-Agent. This is recorded as an edge policy observation, not a request-body
conversion failure and not a reason to override the client User-Agent in the
Provider Profile.

These checks verify only basic routing and response reconstruction. They do not
claim complete reasoning, cached usage, tools, image, streaming, or long-session
compatibility; those semantics remain covered by deterministic tests or
separate live-agent gates as applicable.
