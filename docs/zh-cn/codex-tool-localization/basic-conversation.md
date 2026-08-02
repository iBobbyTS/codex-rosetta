# 基础对话

Codex 通过 OpenAI Responses API 接口与模型通信。许多第三方供应商只暴露 OpenAI Chat Completions 兼容的端点。Codex-Rosetta 根据路由不同，以不同方式填补这一差距：

- 管理界面只暴露一个 **OpenAI Responses** 协议。所有 Provider 都走直接 Responses 路径；Provider 选择只改变默认工具处理方式。
- Responses 到 Chat 的路由通过 Codex-Rosetta 的 IR 进行转换，然后再转换回 Responses 事件供 Codex 使用。

目标是保留 Codex 运行时的语义，而不仅仅是让上游请求在语法上有效。

## Provider Profile 与协议 fallback

Provider 配置必须显式声明。provider 主选项与 `api_type` 共同选择标准转换器和已适配的 provider 扩展；endpoint 子选项与 Base URL 只选择网络地址。Rosetta 不再根据 URL 推断 provider 或协议，模型名也不能选择请求字段。

Admin 协议选择器会先列出 Rosetta 已适配协议，再列出 provider 已知支持但 Rosetta 未适配的可选协议，最后列出 provider 可能不支持的其他可选协议。后两组均可保存并调用，但只使用所选官方标准：Chat Completions、Responses、Anthropic Messages 或 Google GenAI；UI、配置与 trace 会标记 warning，且不执行 provider 专属扩展。所选协议没有 endpoint preset 时会清空 URL，并要求填写明确地址。

内置推荐协议为：OpenAI 推荐 Responses，Anthropic 推荐 Messages，Google 推荐 GenAI，其余 provider 推荐 Chat Completions。

## 单一 Responses 协议与供应商感知默认值

Provider 配置会保存所选 `provider` 和 `api_type: "responses"`。供应商子选项不入库；管理界面只根据已保存的供应商和 Base URL 推导子选项。供应商选择只决定模型组默认工具处理方式，协议处理始终保持直接传输：

- OpenAI 官方选择 **透传**。这是模型组的特殊选项，不是 Tool Profile；Rosetta 不执行任何工具映射，请求、工具声明、响应 JSON 和 SSE 字节都走直接路径。
- OpenAI 自定义以及“自定义 + 自定义”选择 **web.run 注入（适用于尚未支持/alpha/search端点的中转站）**。原始工具形态全部保留，只有 `web.run` 设为 Modified 并由 Rosetta 处理。
- 列表内第三方供应商选择 Responses 时，自动使用 **工具映射（适用于第三方模型提供的Responses接口）**，同时保持 Responses 直接传输。
- 任何 Chat 协议选择 **Chat Default（适用于第三方仅提供chat api的模型）**。Anthropic 和 Google 协议没有内置默认 Profile，但可以使用显式兼容的用户 Profile。

现在只支持 `responses` 这一种 Responses 协议值；旧的 `responses_passthrough` 与 `responses_rosetta` 不再接受，加载配置前必须替换为 `responses`。

Responses Provider 还可以设置 `force_rosetta_compaction: true`。这个
Provider 级策略只影响合法的 Codex compaction trigger：无论 reason 是什么，都使用
Rosetta 的无工具提示词摘要，而不转发 native Remote Compaction V2。普通 Responses
请求仍走直接路径，历史中已有的上游 native `compaction` item 也保持不变。其他协议启用
该选项会被拒绝，而且该功能依赖 Gateway SQLite 持久化。

## Responses 直接传输

对于所有同协议 Responses 路由，网关不会通过 IR 解码和重新编码完整请求体。它会应用所选 Tool Profile；选择 **透传** 时则跳过工具映射。随后网关转发请求，并将上游原始 SSE 字节流式传输回 Codex。模型切换压缩，以及启用强制 Rosetta 压缩的 Provider 上的所有合法 trigger，是有意的语义例外：Rosetta 会让当前模型生成明文摘要，保存对应替换内容七天，并在下一个 Provider 请求前还原。传输层还有一个编码例外：经过认证且带有 `Content-Encoding: zstd` 的请求会先在配置的解压前、解压后大小限制内解码，并移除编码 header。

这一点很重要，因为 Codex 依赖的某些字段不属于最小跨供应商 IR 的一部分，包括：

- 消息输出项上的 `phase` 字段，Codex 用它来折叠工作流程输出。
- 推理项和加密的推理载荷。
- 原生的 Responses 工具项结构。
- 供应商特定的请求字段，如 `include`。

**透传**选项会完全绕过 Tool Profile 解析，因此 Rosetta 既不映射原生工具，也不注入合成工具。打包的 **web.run 注入** Profile 会保留原始 Responses 工具形态，只有 `web.run` 为 Modified。Rosetta 只改写 custom `exec` 描述中实时提供的 `web__run` Section；其他 Responses 字段和上游响应字节仍走直接路径。**工具映射** 则继承已验证的 Chat Default 映射策略，供列表内第三方 Responses 实现使用。

Codex 的独立 Search 和 Images 客户端还会使用三个 JSON 端点：

- `POST /v1/alpha/search`
- `POST /v1/images/generations`
- `POST /v1/images/edits`

Images 端点按照所选 Profile 中 `image_gen.imagegen` 的状态处理：

- **Passthrough**：只有请求模型解析到直接 OpenAI Responses 供应商时才透传。
- **Modified**：把生成和编辑请求发送到 Function 卡片中配置的 OpenAI
  Images API Base URL，并使用 Token 作为 Bearer 凭据。Responses、Chat、
  Anthropic 和 Google 模型组均可使用此路径。
- **Disabled**：拒绝 Images 端点请求。

请求中的模型必须能够解析到选择该 Profile 的模型组。网关会应用配置的上游模型
别名，其余 OpenAI Images 请求和 JSON 响应不经过 IR 转换。Modified 当前仅支持
OpenAI `images/generations` 和 `images/edits` 线协议；Rosetta 不转换供应商私有的
生图 API。

独立 Search 还提供本地 bridge。当所选 Profile 把 `web.run` 设为 Modified
时，`/v1/alpha/search` 会在本地执行可靠子集：`search_query` 使用 Admin
**联网搜索**页面中的全局 Provider（`server.web_search`）。Tavily 使用所配置的
API Key；**Self-hosted (Google)**、**Self-hosted (Bing RSS)** 和
**Self-hosted (Bing Browser)** 则在现有 `web-run` 容器中运行，因此要求
sidecar 健康。Bing RSS 读取 XML 结果表示，Bing Browser 加载并解析交互式
HTML 结果页。**从已配置的 Provider 中选择**则要求再选择一个已启用且 API 类型为
`responses` 的 Provider。由此产生的每个 `web.run` 请求都会原样转发到该 Provider
的相对 `alpha/search` 端点，并使用其凭据和传输设置；当前模型路由及其 upstream
model alias 不会覆盖这条显式搜索路由。所有本地搜索 Provider 都会被规范化为相同的 Codex 可见来源格式。
直接 URL 的 `open` 获取公开静态 HTML 或纯文本，`time` 使用 Python 的固定
UTC offset 计算。Open 会逐跳校验重定向目标，拒绝凭据和非公开地址，最多
允许五次重定向，并限制为 15 秒和 2 MiB；返回规范化、带行号的正文并支持
`lineno`；已保存的 `turnXsearchY` 引用会在对应作用域内解析为搜索结果 URL。

可选、独立构建的 `web-run` Docker sidecar 会提供自托管 Google 或 Bing 基础搜索，并增加
支持 JavaScript 渲染的 `open`、session 级 `turnXfetchY` 页面引用、带编号链接的 `click`、不区分大小写
的 `find`，以及 PDF `turnXviewY` 引用。PDF 的 `open` 和 `find` 使用 PyMuPDF
提取内嵌文本；PDF `screenshot` 使用 PyMuPDF 渲染指定页面，并在页面没有内嵌
文本时使用 Tesseract。Codex Search 端点返回的是文本，而不是多模态图片项，
因此 screenshot 结果包含渲染尺寸和提取/OCR 文本，不会把 PDF 像素注入模型
对话。未启用 sidecar 时，Modified 模式发给模型的 schema 会移除 `click`、
`find` 和 `screenshot`，`open` 继续使用受限的 Python 静态实现。仅配置 sidecar
还不足以向模型声明浏览器命令；有界健康状态必须同时报告服务在线且
`browser_ready=true`。

支持的搜索选项包括查询/domain 过滤、搜索上下文大小、响应长度和保守输出预算。
请求中只要包含 `image_query`、finance、weather、sports、recency、
blocked-domain、location 或非 live 访问语义，就会在任何部分操作执行前返回
HTTP `501` 和 `code: "not_implemented"`。这些辅助端点的所有 `501` 文案还会
以 `Consider "Browser Use" skill` 结尾，提示 Codex 改用浏览器回退。把
`web.run` 设为 Passthrough 时，即使配置了 Tavily 或 sidecar，`/v1/alpha/search`
也会继续原生透传给上游。**从已配置的 Provider 中选择**是明确例外：Modified
和 Passthrough Profile 产生的每个 `web.run` 端点请求都使用这里选定的 Provider；
Disabled 仍会阻止该端点。其他 Modified 模式的受支持命令走本地 Rosetta 搜索服务。
模型可见定义始终保留直接 URL 的 `open`、固定时区 `time`
和 `response_length`；配置全局 Tavily API Key，或选择任一 self-hosted Provider 且
sidecar 报告就绪后，才增加 `search_query`；
只有可选 sidecar 报告 `browser_ready=true` 时才增加 `click`、`find` 和
`screenshot`。Hosted
`web_search` 保持独立，其 Provider、Token 和 guidance 仍属于所选 Profile。

这里的 `/v1/alpha/search` 是 Codex 调用 Gateway 的入口。Passthrough 不会假设
用户漏填了 `/v1`，而是把相对路径 `alpha/search` 接到配置的上游 Base URL：
Base URL 以 `/v1` 结尾时，上游收到 `/v1/alpha/search`；不带版本路径时，上游
收到 `/alpha/search`。

## Responses 转 Chat 转换

对于仅支持 Chat 的供应商，Codex-Rosetta 将传入的 Responses 请求转换为 IR，再转换为 Chat Completions 请求。转换后的 Chat 请求会在目标 API 允许的范围内，保留对话、工具、工具选择、推理配置和流配置。

当 Chat 响应返回时，Rosetta 将其转换回 Responses 兼容的输出，以便 Codex 继续驱动 agent 循环。

Chat Provider 还可以启用**后置指令缓存兼容**。DeepSeek 默认开启，其他 Chat
Provider 默认关闭；Responses、Anthropic 和 Google 协议不适用。Codex 可能在开头的
指令前缀之后追加 system 或 developer 项，用于 ESC 打断、fork、插件、Skill 或其他
运行时上下文。
部分 Chat Provider 会把这些中途指令项转换为 system 消息，导致前文输入缓存失效。

对于带有效 Codex turn metadata 的请求，Rosetta 会保留开头连续的 system/developer
前缀。从第一条普通对话项开始，之后每条 system 或 developer 消息都改为独立的
user-role 消息，
原内容按下列形式包裹：

```text
<system>
原指令内容
...
</system>
```

Rosetta 不检查或单独识别 `<turn_aborted>`；内部文本本身会继续说明其含义。普通 user
消息保持独立且不变。这项转换不会改变 stream 取消行为、保存隐藏
输出、合成工具结果或在另一请求中回放内容。缓存行为仍由 Provider 控制，只能视为
best-effort。由于转换会主动降低 role 优先级，仅应在后置指令内容可以安全地作为 user
文本传递时启用。

网关还会在请求和响应阶段之间保留选定的运行时状态：

- Responses 命名空间工具映射存储在转换上下文中。
- 供应商元数据（如推理或工具调用元数据）可以按工具调用 ID 缓存，并重新注入到后续请求中。
- User-Agent 和 OpenResponses-Version 头通过显式的头部允许列表转发。

## 流式形态

对于转换后的流式响应，Rosetta 从上游 Chat 块中重建 Responses SSE 事件。它发出 Codex 期望的相同大类事件：

- `response.output_item.added`
- 文本增量和文本完成事件
- 工具调用开始、参数增量和完成事件
- 推理事件（可用时）
- `response.completed`

转换器会在消息项的添加和完成事件上保留消息 `phase` 元数据，以便 Codex 在生成最终答案时折叠评论/工作输出。

## 推理

对于在供应商特定字段中输出推理的 Chat 供应商，当上游单独提供推理内容时，Rosetta 会将其与普通助手输出分开保存。DeepSeek 风格的 `reasoning_content` 会在工具循环中保留，以便后续请求能够满足那些要求回显推理内容的供应商。

如果模型在普通文本中输出推理，例如 `<think>...</think>`，Rosetta 会将其视为普通输出，因为供应商没有从语义上将其分离。

## 上下文处理

Codex 当前在重复请求中发送完整的对话上下文，而不是仅依赖 `previous_response_id`。因此，Rosetta 将传入的请求体视为当前轮次的真实来源。它不实现服务端的 Responses 对话存储。

这对 Chat 转换很重要：如果 Codex 重新发送历史助手工具调用或结果，Rosetta 必须使每个
历史对象与上游模型最初看到的内容保持一致。因此，工具本地化使用按 principal 隔离、
加密且按内容寻址的单对象缓存。Call 与 Result 独立匹配，不把 session、thread、window、
fork、Provider、model 或协议顶层 call ID 当作内容身份。
