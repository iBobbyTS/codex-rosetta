# 补充遗漏审计报告

## 结论

本轮在产品代码基线 `51f3b2d` 上独立复现了一个可达的 credential-return
遗漏，并重新打开 `AUD-025`：

- 级别：`Must Fix`
- 决策类别：`Agent-Fixable`
- 结论置信度：High
- 新业务决定：不需要

问题发生在跨格式流：Chat、Anthropic 和 Google 的 semantic gate 分别按
choice、block、candidate/part 身份分 buffer，但 target -> IR -> Responses
转换会丢弃或合并这些身份；Codex 最终只把输出文本 delta 追加到当前 active
item。于是同一个下游消费流可以被 gate 拆成多个缓冲区，配置的 canary 能在
gate 之后重新拼回。

这是原 `AUD-025`“下游消费身份与 gate 身份不一致”根因的再次出现，不是
独立 finding，也不分配新 ID。`20260721-2035` 的原生 Responses 关闭证据仍
保留为历史；本轮只说明跨格式桥接边界尚未被那次修复覆盖。

## 证据

网关路径已逐段取证：streaming handler 包装 redacting transport，建立
`ConversionPipeline`，经过 target -> IR -> source 转换，再由 SSE generator
释放事件。Codex 源码保留 `response.output_text.delta` 的 `delta`，并在
当前 active item 上消费它；不会使用上游转换中可选的 output/choice identity。

使用中性 `CANARY-ALPHA-BETA` 的离线 fake transport 和真实本地转换管线，三
个目标 provider 都允许两段片段，并在 source-side reconstruction 得到完整
canary：

| target provider | gate 结果 | downstream reconstruction |
| --- | --- | --- |
| OpenAI Chat | allowed | `CANARY-ALPHA-BETA` |
| Anthropic | allowed | `CANARY-ALPHA-BETA` |
| Google | allowed | `CANARY-ALPHA-BETA` |

既有 focused checks 为 `153 passed`，但测试固定了 Chat choice、Anthropic
block、Google candidate/part identity，没有跨格式“身份变化后仍被下游合并”
的失败 oracle。因此绿套件不能关闭本 finding。

## 修复验收方向

修复应收敛在现有 credential gate/转换边界，结果导向如下：

1. Chat、Anthropic、Google 转换流的 gate 分区必须等于 source consumer 实际
   保留的 active-item/retained-index 身份。
2. 不会被下游消费的 upstream choice/block/part 字段不得创建新 buffer；矛盾
   元数据应 fail closed 或保持身份无关，不能释放完成 canary。
3. 用 fake transport 加真实 `ConversionPipeline` 覆盖 parsed/raw SSE、三种
   provider、跨片段 canary、不同 active item/index 的隔离、容量和所有终止
   清理路径。
4. 保持 direct Responses、工具参数、碰撞 fail-closed、active-provider-only
   范围和协议合法性。

修复完成后，应对本次失效 coverage 做 targeted/fresh adversarial re-audit；
本轮没有授权实施修复。

## 验证边界

没有执行真实 provider/API/Codex 调用、部署或网络访问，也没有修改产品代码、
测试或配置。真实 provider 时序、外部 sink、隐蔽编码、公网部署、可用性和
恢复能力仍按 profile 保持排除或 `Unknown`。

## 维护性判断

问题集中在 transport credential gate 与 Codex Responses 消费契约这一条高风险
语义边界。建议修复时复用既有 identity/state 所有权并补精确跨格式回归，不
新增平行协议层；当前无需扩大到持久化、Admin 或其他 converter 重构。
