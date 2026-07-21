# 复审证据

## 代码修复

- `credential_semantics.py` 为 Responses/Chat/Anthropic/Google 的可拼接文本、推理、拒绝和工具参数建立有界身份累计；Responses 新增 MCP 参数事件类型。
- Responses completion handler 移除首个 tool-loop item 后的提前 `break`，完整扫描后再决定 finish reason。
- 非流式 Responses 在 IR 内容归一化后，检测 tool-call part 并将 `stop` 修正为 `tool_calls`。

## 回归验证

- 定向 suite：`185 passed`，覆盖四种 provider 的 raw/parsed 分片凭据、混合 completed output，以及非流式 tool-call finish reason。
- 完整 deterministic suite：`3629 passed, 5 skipped, 11 warnings`。
- 等价 lint：ruff check 通过，ruff format check 通过，ty check 通过。
- `git diff --check` 通过；CodeGraph 已同步。

## 安全边界

未进行真实上游调用、live agent、部署或公网验证；结果只证明当前源码和 deterministic 测试边界。真实 provider 时序、外部 sink、可用性、数据恢复和公网账户安全仍不作承诺。
