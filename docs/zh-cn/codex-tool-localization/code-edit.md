# 代码编辑

Codex 提供了原生编辑能力，例如 `apply_patch`、`exec_command` 和 `write_stdin`。许多开源模型在训练或产品使用中接触更多的是 Claude Code 风格的编辑工具，因此它们可能会选择 shell 命令或临时 Python 脚本，而不是 Codex 的 patch 工作流。

Codex-Rosetta 可以在 Responses 到 Chat 的路由上本地化模型端编辑界面，同时仍然在返回端向 Codex 提供原生工具调用。

## 模型配置

网关管理 UI 提供了一个名为 `Tool Adaption for Codex`（Codex 工具适配）的模型级配置区域。

当前选项：

- `Localize code editing tools`（本地化代码编辑工具）：将 Codex 原生编辑工具替换为面向上游模型的本地化 Chat 工具。
- Tool Profile 管理当前嵌套在 Code Mode `exec` 中的 `image_gen__imagegen` Function（运行时身份为 `image_gen.imagegen`）。已废弃的 Hosted `image_generation` 工具不再属于打包的 Profile 目录。

只有配置了该选项的模型路由会受到影响。

## 模型端工具

当为 OpenAI Responses 到 OpenAI Chat 的路由启用 `localize_code_editing_tools` 时，Rosetta 会从上游 Chat 请求中移除原生代码编辑工具，并暴露以下 Claude Code 风格的工具：

- `Read(file_path, offset?, limit?)`
- `Edit(file_path, old_string, new_string, replace_all?)`
- `Write(file_path, content)`
- `Glob(pattern, path?)`
- `Grep(pattern, path?, glob?, type?, output_mode?, case_insensitive?, line_numbers?, before_context?, after_context?, context?, head_limit?, offset?, multiline?)`
- `Bash(command, timeout?, description?, run_in_background?)`

本地化的 `Edit` 描述明确要求模型尽可能替换完整的行或连续的代码块。这有助于提升转换到 Codex patch 的质量，因为当 `old_string` 包含完整的行上下文时，`apply_patch` 的可靠性要高得多。

## 原生翻译

在 Codex 收到响应之前，本地化的工具调用会被转换回来：

- `Bash` 变为 `exec_command`。
- `Read` 变为一个 `exec_command`，打印 UTF-8 文件内容，支持可选的 offset 和 limit。
- `Glob` 变为一个通过 Python `glob` 实现的 `exec_command`。
- `Grep` 变为一个通过 `rg` 实现的 `exec_command`。
- `Write` 通常变为自定义的 `apply_patch` 新增文件调用。
- `Edit` 通常变为自定义的 `apply_patch` 调用。
- `Edit(replace_all=true)` 变为一个执行受控全局替换操作的 `exec_command`。

如果原始请求没有暴露自定义的 `apply_patch`，`Edit` 会回退到 `exec_command` 或 `shell_command`，在可用时通过 heredoc 调用 `apply_patch`；`Write` 会回退到一个通过 base64 安全 Python 辅助函数写入 UTF-8 内容的 `exec_command`。

## Read 输出扩展

某些模型在读取文件后仍然发出狭窄的子字符串编辑。Rosetta 在重建转换后的 Chat 请求时维护了一个会话级别的读取输出缓存。当后续的 `Edit` 针对一个可以从先前 `Read` 中无歧义扩展为完整行的子字符串时，Rosetta 会将 `old_string` 和 `new_string` 扩展为完整行替换，然后再生成 patch。

在成功对该文件执行修改操作后，该文件的缓存会被失效，因此过期的读取结果不会在后续编辑中被重用。

## 历史工具对象翻译

Codex 在本地会话历史中存储助手工具调用，并在后续轮次中重新发送该历史。本地化之后，Codex 看到的是 `apply_patch` 这样的原生调用，但上游 Chat 模型最初看到的是 `Edit` 这样的本地化调用。

为了保持供应商端提示缓存和模型连续性，Rosetta 会按 principal 归属，分别保存单个
Chat 工具对象的翻译。Call 与 Result 是彼此独立的记录。内容身份只排除协议顶层的调用
标识符（Call 的 `id` 或 Result 的 `tool_call_id`）；参数或结果内容内部的 `id` 仍参与
匹配。命中时会注入当前请求的协议顶层标识符。

已认证 principal 是唯一的所有权边界。Session、thread、window、fork、Provider、model
和 call ID 都不是缓存键，因此 window 变化、compact、resume 或 fork 后仍可复用完全一致
的单对象翻译，而无需复制外围会话。按 principal 和对象类型做域隔离的 keyed HMAC
可防止 SQLite lookup token 成为枚举界面；精确 source 与翻译后的 template 使用
AES-256-GCM 进行 at-rest 保护。诊断脱敏不会应用到这份可执行 payload，因为
`[REDACTED]` 对象已无法描述 Codex 真实执行的工具动作。Key lifecycle、备份、失败和
legacy row 语义见
[网关安全与认证](../gateway-security.md#可执行工具历史存储)。

Rosetta 会先重放精确命中，再执行当前请求的本地化。Miss 会正常重新翻译：请求历史中的
Result 只会在上游接受本次请求后写入；模型新返回的 Call 则必须先安全持久化，Rosetta
才会把它发给 Codex。Result 的容量或冲突错误只跳过该条 Result 记录；Call 无法持久化
时会 fail closed，避免向 Codex 暴露后续无法恢复的历史。

每条记录使用绝对 24 小时 TTL；读取和重复写入都不会续期。过期记录按普通 miss 处理：
Rosetta 重新翻译，并在满足相同接受规则后写入新的 24 小时记录。某次请求没有使用一条
记录不会导致其删除，因此多个独立 fork 可以复用同一个精确对象。

这样既保持了 Codex 下游历史的原生性，又避免工具对象重新翻译改变上游模型的重复上下文。
但它不保证供应商提示缓存一定命中：Codex 在 fork 或 resume 时可能追加其他上下文；即使
先前 Chat messages 仍是逐项精确前缀，供应商也可能选择新的缓存分段。

## 当前限制

本地化层有意保持保守：

- 它仅在 Responses 到 Chat 的路由上运行。
- 它只更改模型配置中启用了该功能的路由。
- 它不会尝试将任意的 shell 编辑解析回结构化编辑。
- 它无法隐藏模型放在普通文本中的推理内容。
