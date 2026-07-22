# 补充遗漏审计报告

## 结论

本轮在当前 `c2db61e` 上确认一个可达遗漏，并重新打开 `AUD-025`：

- 级别：`Must Fix`
- 决策类别：`Agent-Fixable`
- 根因：credential gate 用下游 Codex 会丢弃的可选 wire 字段划分
  delta buffer，导致同一条实际消费流被拆成多个安全检查流。
- 影响事件：`response.output_text.delta`、
  `response.reasoning_summary_text.delta`、`response.reasoning_text.delta`。
- 影响范围：`PROVIDER-01`、`STREAM-01`、`SCN-03`、`SCN-04`、`CTRL-03`。

不需要新的业务决定。现有 profile 已明确要求当前 provider 的凭据不能
穿过返回边界；这里只需要让安全 gate 与唯一支持的下游 Codex 消费语义一致。

## 可达证据

Codex 对三类事件分别保留：仅 `delta`、`delta + summary_index`、
`delta + content_index`，并把它们绑定到当前 active item。当前 gate 却把
`item_id/output_index/content_index` 中下游并不消费的值加入 identity。

纯内存 fake transport 反例把虚拟凭据 `secret-token` 拆为两段，并在两段间
改变这些被忽略的 wire ID。三种事件的 parsed 和 raw SSE 路径均释放两个
事件和完整 frame，Codex 侧会重建出完整凭据。

## 验证

| 检查 | 结果 |
| --- | --- |
| 三类 raw/parsed SSE 反例 | 均复现，完整虚拟凭据被重建 |
| 相关 transport/Responses suite | `290 passed` |
| 真实 provider/API/Codex 调用 | 未执行 |
| 产品代码、提交、部署 | 未修改、未执行 |

现有测试全绿不构成关闭证据，因为缺少“同一消费流中，可选 wire identity 值
发生变化”的失败 oracle。

## 修复建议

在既有 `ProviderCredentialSemanticGate` 所有权边界内修复，不新增通用协议层：

1. 以 Codex 实际保留的 event 字段和 active-item 生命周期作为唯一分流依据。
2. 下游忽略的可选字段不得创建新 buffer；矛盾元数据可忽略或 fail closed，
   但不能拆散同一消费流。
3. 为三类事件增加 raw/parsed 回归，同时覆盖不同 active item、
   `summary_index`、`content_index` 的隔离、容量上限和清理。
4. 完成后对 `AUD-025` 做定向复审，再恢复受影响 coverage 的 Fresh 状态。

## 审计边界

本轮是风险抽样，不表示整个仓库没有其他问题。没有验证真实 provider 时序、
外部 sink、公网安全、可用性或数据恢复；这些仍按批准的本机/内网 profile
保持排除或 Unknown。

## 维护性判断

问题集中在 transport credential gate 与 Codex Responses 消费契约之间的
高风险语义边界。建议修复时收敛已有 identity 规则并增加精确回归，不再叠加
另一套平行映射；无需扩大 converter、持久化或 computer-control 范围。
