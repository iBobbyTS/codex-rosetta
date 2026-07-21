# 第五轮独立遗漏审计报告

## 执行摘要

- 审计模式：`Periodic`
- 审计基线：`6d1bc7affdb02c3c928c84ee49b321011363aea4`；修复证据来自其后的未提交工作树。
- Audit Profile：`Approved`。
- 最终结论：AUD-017 与 AUD-018 已在获得授权后修复，并通过与发现阶段分离的确定性复核关闭。
- AUD-017：不限制凭据长度；Rosetta 仍强制配置 Gateway API key，不提供无鉴权模式。成功返回不再做语义改写；发现任一实际配置凭据的精确碰撞时受控失败。raw SSE 只按完整事件释放安全内容，因此不会先泄漏或输出碰撞事件的部分字节。
- AUD-018：Admin 模型发现现在先验证 provider 对应的 root、集合、成员和模型 ID schema，再做 normalization；错误形状统一返回稳定且不含敏感内容的错误。
- 本轮没有真实 provider、Codex、Tavily 或 sidecar API 调用。

## 发现阶段快照

修复前的独立探针确认：

- `api_key="data"` 会使旧 exact replacement 把合法 SSE `data:` 字段改成 `[REDACTED]:`，证明旧实现会静默破坏协议。
- Admin fake response 返回 list root 时，旧 model discovery 会在 `body.get()` 抛出 `AttributeError`，证明 JSON 语法有效不足以构成可信边界。

这些证据保留在 `EVIDENCE.md`，用于说明根因与关闭前状态；它们不代表当前工作树状态。

## 授权修复

### AUD-017 — 凭据碰撞安全边界

- `SecretRedactor` 增加统一的精确碰撞检测；诊断日志仍可脱敏，但成功的非可信返回内容不再被任意替换。
- provider non-stream JSON/raw、parsed stream、raw SSE、Codex auxiliary、Tavily、web-run sidecar 和 Admin model discovery 共用 fail-closed 语义。
- raw SSE 使用有界的完整事件 gate：任意 chunk 拆分下只释放完整且无碰撞的事件；发生碰撞时从合法事件边界返回与源协议兼容的终止错误。
- 轮换 key、短/常见/纯数字 key、JSON key/value、SSE `data`/`event`/引号、HTTP error 和 transport exception 均有回归覆盖。
- 状态：`Closed / Agent-Fixable`。

### AUD-018 — Admin 模型列表 schema 边界

- 新 normalization 边界要求 root 为 object、目标 collection 为 list、成员为 object、provider/shim 指定的模型 ID 为 string。
- list/scalar/null root、缺失或错误 collection、错误成员与错误 ID 类型均返回统一受控错误。
- OpenAI、Anthropic、Google 和 custom `model_id_field` 的成功 normalization 保持覆盖。
- 状态：`Closed / Agent-Fixable`。

## 场景与控制结果

| 场景/控制 | 最终结果 | 确定性证据 | 剩余未知 |
| --- | --- | --- | --- |
| SCN-03 / PROVIDER-01 | Satisfied | credential-free JSON/SSE 保持不变；碰撞 fail closed | 真实 provider 编码与外部 sink |
| SCN-04 / CTRL-03 | Satisfied | 完整 SSE event gate、任意 chunk 拆分、source-compatible terminal error | 真实网络 timing |
| SIDE-01 | Satisfied at deterministic boundary | auxiliary/Tavily/sidecar success/error/exception 碰撞矩阵 | sidecar container/live endpoint |
| SCN-08/09 / AUTH-02 | Satisfied | provider schema 负面矩阵与四类成功 normalization | 浏览器/LAN UX、真实 pagination |
| GP-003 | Enforced | 统一 collision detection、完整事件 gate、client inventory tests | encoded/hashed/covert exfiltration 不在 exact-match 保证内 |

## 验证证据

| 检查 | 结果 | 限制 |
| --- | --- | --- |
| 相关 focused pytest | `187 passed` | 仅确定性 fake/in-process 边界 |
| 完整非 integration 测试 | `3576 passed, 5 skipped, 11 warnings` | 不执行真实 API |
| `make lint` | 通过 | 静态质量门禁 |
| `make check-codex-compat` | 通过 | 无触发的 Codex compatibility group；不替代 live gate |

## 覆盖新鲜度

- `PROVIDER-01`、`SIDE-01`、`SCN-03`、`SCN-04`、`CTRL-03`：`Invalidated → Fresh (deterministic)`。
- `AUTH-02`、`SCN-08`、`SCN-09`：`Invalidated/Partial → Fresh (deterministic)`。
- 真实 provider/Codex/sidecar/Tavily、浏览器/LAN、部署、恢复和外部日志 sink 仍为 `Unknown`；项目 profile 本来也不承诺公网账户安全、可用性或数据丢失恢复。

## 维护性判断

修复把安全语义集中在 transport collision boundary 和一个 Admin model-list normalizer，没有把 provider-specific 判断散落到各 route。raw SSE gate 引入一事件有界缓冲，但避免了跨模块重复状态机；测试覆盖其 framing、分片和终止语义。当前不建议再做额外抽象。
