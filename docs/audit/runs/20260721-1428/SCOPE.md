# 定向复审范围

## 模式

Targeted Re-audit，针对独立遗漏审计发现 `AUD-025`、`AUD-026`、`AUD-027`。
本轮仅覆盖其修复影响锥，不重扫无关子系统。

## 固定范围

| Finding | 边界 | 验收 |
| --- | --- | --- |
| AUD-025 | `credential_semantics.py` 与 raw/parsed SSE 包装器；Responses、Chat、Anthropic、Google stream 字段 | 分片凭据在每种 provider 的 raw/parsed 路径均阻断，并保留有界身份/片段限制 |
| AUD-026 | Responses `response.completed` output item 扫描与 unsupported computer item 拒绝 | `function_call` 后跟 `computer_call` 仍明确抛出，不静默发 finish |
| AUD-027 | Responses 非流式 `response_from_provider` 到 IR/下游 finish reason | completed tool-call 输出为 `tool_calls`，普通 assistant message 仍为 `stop` |

## 排除

- 不执行真实 provider、Codex、Tavily、MCP 或部署调用。
- 不扩大 generic computer-control 支持。
- 不重新评估已记录的业务语义决定或公网安全承诺。
