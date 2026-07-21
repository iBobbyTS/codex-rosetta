# 定向修复复审报告

## 结论

`AUD-025`、`AUD-026`、`AUD-027` 均为 `Must Fix / Agent-Fixable`，本轮已闭合。

- `AUD-025`：四种已支持 provider 的 raw/parsed stream 现在累计并检查分片文本、推理、拒绝、MCP 和 provider-specific 字段。
- `AUD-026`：Responses completion output 现在完整扫描，前一个 function/tool item 不再隐藏后续 unsupported `computer_call`。
- `AUD-027`：非流式 Responses tool-call 与流式路径统一报告 `finish_reason=tool_calls`。

## 验证

| 检查 | 结果 |
| --- | --- |
| 受影响 focused suite | `185 passed` |
| 完整 deterministic suite | `3629 passed, 5 skipped, 11 warnings` |
| ruff / format / ty | 通过 |
| CodeGraph / diff 检查 | 通过 |
| 真实 provider/API/Codex 调用 | 未执行 |
| 部署、公网和可用性承诺 | 未执行且不作承诺 |

## 残余风险

关闭仅表示当前源码、测试和本机 deterministic 证据满足冻结的验收标准；不覆盖真实 provider 时序、未知未来 stream consumer、外部 sink、恢复能力或公网账户安全。`computer_call_output` 仍按 owner 决定明确拒绝，不扩展 generic computer-control 范围。

## 维护性判断

修复保持在 transport credential gate 与 Responses converter 的既有所有权边界内，使用已有有界累计和类型契约；新增的 provider 分支与回归矩阵对应当前四个 converter，没有引入持久化层或通用 computer-control 抽象。后续仅在新增 provider stream 字段或扩大工具协议时重新审计。
