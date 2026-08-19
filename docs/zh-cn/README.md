# Codex-Rosetta 用户文档

## 兼容性

- [Codex 版本兼容性](version-compatibility.md)
- [Codex 模型目录字段参考](codex-model-catalog.md)

## 当前协议支持状态

目前已重点开发并保证的网关路径仅有：

- OpenAI Responses 到 OpenAI Chat Completions 的协议转换；
- 所有 Provider 都直接传输 OpenAI Responses；除模型组 Tool Profile 外，仅模型切换压缩使用 Rosetta 管理的明文交接。

Anthropic 和 Google 转换仍是内部选项，目前不作保证。Tool Profile 可以声明适用于 Chat、Responses、Anthropic Messages 和 Google GenAI；管理界面会按该协议过滤模型组选项。Chat 和 Responses Provider 保留内置默认值，Anthropic 和 Google Provider 只有在显式选择时才使用 Profile。Provider 类别不会改变同协议 Responses 的处理路径。

## 网关运维

- [安全与认证](gateway-security.md)
- [Web 管理界面与桌面应用](desktop.md)

终端支持四个日志级别：

```bash
codex-rosetta-gateway --log-level info
codex-rosetta-gateway --log-level stats
codex-rosetta-gateway --log-level warning
codex-rosetta-gateway --log-level error
```

运行 `codex-rosetta-gateway --with-web-run` 可以在宿主机 Gateway 启动时一并拉起
可选的浏览器/PDF sidecar。CLI 会从回环端口 `8766` 开始选择第一个空闲端口，等待
Chromium 就绪，并在退出时清理托管 service。

`warning` 是默认档位，不打印每个正常请求，但保留 warning 和 error；`info` 还会打印
请求摘要；`stats` 在同一行持续刷新各模型的请求数，例如
`model-1: 12, model-2: 7`。计数键使用 provider 的原始 upstream 模型名，不使用对外
暴露的模型别名。遇到 warning 或 error 时会先换行打印，下一次请求再继续刷新统计行；
`error` 只打印错误。完整请求历史请在 WebUI 的 **请求日志（Request Log）** 中查看；
流式 trace 诊断请使用 WebUI 的 **网关日志（Gateway Logs）**。

### Provider Base URL 与凭据

每个 Provider 保存一个有序、非空的 `base_urls` 列表，并将其中一个成员保存为
`current_base_url`。现有的**服务方**页面可编辑顺序，并显示每个 URL 是可用、冷却中
还是当前 URL。手动选择冷却中的 URL 会立即将其设为当前 URL，并且只清除该 URL 的
冷却状态。

在向客户端输出任何内容之前，字面意义的上游 HTTP 502 会在同一个 URL 上分别等待
1、2、4、8、16 秒后重试。只有连续六次 502 才会让该 URL 进入冷却，并静默尝试下一个
未冷却 URL；每个后续 URL 都有同样的重试预算。被窄范围识别的 CDN 502 页面仍会立即
轮换且不会重试。失败 URL 在进程内冷却一小时，当前 URL 则持久化保存。禁用故障转移的
流式请求不会重试。
Search Provider 透传请求同样使用此“轮换前重试”行为，并且仍只占用一次逻辑上的
Search Provider 请求预算。

每个 Provider 还保存一个有序、非空的 `api_keys` 列表。每个条目包含稳定 UUID、可编辑
ID 和掩码凭据；`current_api_key` 通过可编辑 ID 选中一个条目。Admin UI 使用 UUID，因而
修改 ID 时仍能保留原有凭据。字面意义的上游 HTTP 503 会在当前凭据上分别等待
1、2、4、8、16 秒后重试。只有连续六次 503 才会让该凭据进入冷却并轮换到下一个未冷却
凭据；每个后续凭据都有完整的新重试预算。普通、流式、透传及 Search Provider 请求均
遵循此行为，Search 内部重试仍只占用一次逻辑请求预算。禁用故障转移的流式请求仍只尝试
一次。只有 503 会轮换凭据环；502 只轮换 URL 环，两个环可以各自推进且互不重置。失败
凭据在进程内冷却一小时；有限环全部耗尽时只报告凭据数量。手动选择允许恢复冷却中的
条目，并且只清除该条目的冷却状态。成功请求不会按请求次数轮换凭据。

每个 Provider 都必须显式设置布尔字段 `auto_rotate_credentials`。值为 `true` 时，
Provider 保留上述内部 503 重试与凭据轮换行为，模型组以名称保存该 Provider。值为
`false` 时，Provider 内部绝不选择其他凭据；模型组改为保存有序的
`{provider, credential_uuid}` 候选项。凭据的可编辑 ID 改名后，UUID 仍保持候选项身份
不变。Admin UI 要求每个关闭自动轮换的 Provider 行选择凭据，允许同一个 Provider
使用不同凭据，并拒绝完全重复的 pair。一个模型组内的所有候选项仍必须使用相同的
`api_type`；不支持异构 Provider 模型组。

模型组候选项的顺序和当前选择会分别保存。有序 `provider` 列表始终保留用户在 Admin
UI 中调整的顺序；可选 `current_provider` 使用相同的 Provider 名称或
`{provider, credential_uuid}` 结构标识当前行，并且可以指向列表中的任意成员。未配置
`current_provider` 时使用第一个符合条件的有序候选项；已保存的当前候选项不可用时，也
会回退到第一个符合条件的候选项，但不会改写列表顺序。

从自动轮换切换为模型组管理时，现有模型组行会绑定到该 Provider 当时的当前凭据
UUID；重新开启自动轮换时，会在该 Provider 首次出现的位置合并其所有 pair。移除被
引用的凭据时，界面会先列出所有受影响模型组并要求确认；确认后会移除所有匹配 pair，
若没有候选项则保留一个空的、不可用的模型组。

## Codex 工具本地化

- [基础对话](codex-tool-localization/basic-conversation.md)
- [代码编辑](codex-tool-localization/code-edit.md)
- [其他工具](codex-tool-localization/other-tools.md)
- [Agent 实机工具测试结果](tools/real-agent-test-results.md)

架构说明、源码契约和维护流程请参阅[开发者文档（英文）](../dev/README.md)。
