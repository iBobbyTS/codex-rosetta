# AUD-025 定向修复复审报告

## 结论

`AUD-025` 已关闭。修复提交 `51f3b2d` 让 credential semantic gate 使用 Codex
实际消费的身份，而不是上游可选 wire metadata：

- output text 只按当前 active item 分流；
- reasoning summary 按 active item 和 `summary_index` 分流；
- reasoning text 按 active item 和 `content_index` 分流；
- Codex 丢弃的 `item_id/output_index/content_index` 不再创建新 buffer；
- item 边界和所有终止路径都会清理有界状态。

没有新增业务决策。现有 profile 对“当前 provider 凭据不得穿过返回边界”的
要求已经决定了修复方向。

## 验收证据

| 检查 | 结果 |
| --- | --- |
| 三类 changing-ignored-ID raw/parsed 反例 | 均在完成凭据前拒绝 |
| active item / retained index 隔离与容量 | 通过 |
| EOF、完成、失败、取消、generator/explicit close 清理 | 通过 |
| transport/Responses focused suite | `296 passed` |
| 提交后的独立 adversarial selection | `8 passed` |
| 完整确定性 suite | `3676 passed, 5 skipped, 11 warnings` |
| lint / Codex compatibility / CodeGraph | 通过 |
| 真实 provider/API/Codex 调用 | 未执行 |

因此 `PROVIDER-01`、`STREAM-01`、`SCN-03`、`SCN-04` 和 `CTRL-03`
恢复为 `Fresh (deterministic)`。

## 剩余边界

本轮不证明真实 provider/Codex 时序、外部 sink、隐蔽编码、公网部署、可用性
或恢复能力。Codex 的 Responses 消费语义、text event 集合或 active-item 生命周期
发生变化时，必须重新打开对应 coverage。

## 维护性判断

修改集中在 transport credential gate 及其 Codex 兼容性单一事实源，没有新增
平行协议层。消费者身份规则按事件集中声明，生命周期清理由 stream wrapper
统一承担；精确回归覆盖了安全边界、隔离、容量和清理。当前无需后续重构。
