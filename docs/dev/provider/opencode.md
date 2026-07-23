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
