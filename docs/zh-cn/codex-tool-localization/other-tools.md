# 其他 Codex 工具

Codex 有几个 agent/运行时工具，其行为不仅仅依赖于简单的函数调用架构。Codex-Rosetta 会在需要时保留 Responses 特有结构。定向的模型使用指导属于 Profile 的 Function field，而不是 Converter 中按工具名称写死的规则。

## 计划模式

计划模式使用 `request_user_input`，当模型需要在生成或修改计划之前获得真实的用户决策时。Chat 模型可能会将其与最终的审批步骤混淆，并在已经发出提议计划后询问用户是否继续。

内置 **Chat Default** Profile 会将 `request_user_input` 设为 Modified，并提供以下可编辑的工具使用指导字段：

- 仅在需要做出实质性改变计划的偏好或决策时使用。
- 不要用它来询问是否批准、继续或执行提议的计划。
- 在最终的 `<proposed_plan>` 块之后，让 Codex UI 处理审批和实施。
- 保持选项标签简短自然，不要使用 `A:`、`B:` 或 `C:` 前缀。

这是一种提示级别/工具描述的适配，不会改变工具架构。

## TODO / update_plan

当 Codex 只把 `update_plan` 作为 Code Mode 的嵌套工具暴露时，内置 **Chat Default** Profile 会将其投影为普通 Chat Function。Rosetta 从 Codex 当前的 `exec` 声明中提取参数 schema 和 description，不在本地维护重复 schema。模型调用会被重组为确定性的 custom `exec` 脚本交还 Codex。如果 Codex 已直接暴露 `update_plan` Function，则保留直接定义。

## 目标工具

目标状态通过 `get_goal`、`create_goal` 和 `update_goal` 管理。Chat 模型可能无法从简洁的原生工具描述中推断出正确的顺序。

内置 **Chat Default** Profile 会将以下 Function 设为 Modified，并提供可编辑的工具使用指导字段：

- `create_goal`：当用户明确要求标记目标完成或受阻但不存在活跃目标时调用，或者当 `update_goal` 报告线程没有目标时。除非用户明确提供了数字令牌预算，否则不要设置 `token_budget`。
- `update_goal`：当目标状态不确定时，先调用 `get_goal`。如果没有活跃目标，使用简洁的目标调用 `create_goal`，除非明确要求否则不设置令牌预算，然后重试 `update_goal`。

三个 Goal 工具都会标记为 Modified，以便从 Code Mode `exec` 投影。`get_goal` 不追加额外指导文本；`create_goal` 和 `update_goal` 继续使用上述由 Profile 管理的指导。

## Code Mode 嵌套工具

新版 Codex Code Mode 会把部分运行时工具放在 custom `exec` 的 description 中，而不再把每项工具都作为顶层 Function 暴露。对于 Responses 到 Chat 的路由，**Chat Default** 会在声明实际存在时，把以下嵌套工具投影为普通 Chat Function：

- `exec_command`、`write_stdin`、`update_plan`、`apply_patch` 和 `view_image`
- `web.run`，在 Chat 中显示为 `web-run`
- `get_goal`、`create_goal` 和 `update_goal`
- `clock.curr_time` 和 `clock.sleep`，在 Chat 中显示为 `clock-curr_time` 和 `clock-sleep`

Rosetta 从实际 Codex `exec` 声明中读取每项工具的 schema 和 description。反向解析器覆盖 Codex 会输出的 TypeScript 语法，包括 literal、union、intersection、array、tuple 和对象 index signature；Codex 在把 JSON Schema 渲染成 TypeScript 时已经省略的约束无法恢复。声明无法解析时不会凭空生成 Function。同名的直接 Function 优先，该名称的投影会 fail-closed。

投影 Function 的调用会被重组为调用嵌套 `tools` 对象的确定性 JavaScript，并作为调用 `exec` 的 `custom_tool_call` 返回 Codex。精确的 Chat 到 Codex 调用映射会写入现有的加密工具历史缓存，因此后续请求在其 24 小时 TTL 内可先恢复原始 Chat Function 和参数，再发送给上游。`view_image` 通过 exec 的 `image(...)` helper 转发结果，其他投影工具使用 `text(...)`。

顶层 `wait` 和 `request_user_input` Function 不会投影到 `exec`，在两个方向都保持直接 Function。

## 子工具与命名空间工具

Codex 通过 Responses 命名空间工具（如 `collaboration` 和旧版 `multi_agent_v1`）暴露子工具能力。Chat Completions 没有相同的嵌套命名空间工具结构。

对于 Responses 到 Chat 的路由，Rosetta 将命名空间子工具扁平化为普通的 Chat 函数工具。例如：

```text
multi_agent_v1-spawn_agent
```

在请求转换过程中，Rosetta 记录展开后的工具名称到 Responses 命名空间的映射。连字符形式 `multi_agent_v1-spawn_agent` 是正式名称，也符合 Chat API 通常只允许字母、数字、下划线和连字符的限制。返回时 Rosetta 还接受 `multi_agent_v1_spawn_agent`、`multi_agent_v1.spawn_agent`；当裸 `spawn_agent` 只属于一个 Namespace 且不与普通 Function 重名时，也会恢复该裸名称。任一名称存在普通 Function 或其他 Namespace 冲突时都保持 fail-closed。随后 Rosetta 在将事件返回给 Codex 之前恢复 Responses 命名空间元数据：

```json
{
  "type": "function_call",
  "name": "spawn_agent",
  "namespace": "multi_agent_v1"
}
```

对于 Responses 到 Responses 的路由，命名空间工具保持原生的 Responses 形态。

## 插件与延迟加载工具

插件和延迟加载工具发现使用相同的通用工具转换路径。Rosetta 当前没有为每个插件工具添加专门的本地化规则。

重要的行为是工具调用必须能完成往返：

- 工具定义在发送给 Chat 供应商时被转换为 Chat 兼容的函数形态。
- 工具调用被转换回 Responses 事件供 Codex 使用。
- 当工具来自 Responses 命名空间时，命名空间元数据被恢复。
- 消息 `phase` 元数据被保留，以便工作流程输出在 Codex 中保持可折叠状态。

## Tool Profile 作用范围

**OpenAI Responses (Tool Mapping only)** 支持 Tool Profile，同时让 Responses 请求和响应的其余部分继续走直接路径。内置的 **Responses pass through** Profile 保持传入工具不变；**Responses web.run mapping** 只修改 `web.run`，让 `/v1/alpha/search` 使用 Rosetta 的本地映射。Responses Rosetta、Chat、Anthropic 和 Google 模型组仍支持 Profile 选择与处理。

打包的 Profile 通过 `image_gen.imagegen` 管理当前 Codex 图片生成工具，不再包含已废弃的 Hosted `image_generation` 工具。

### Function 卡片输入项

Function、Hosted 或 Namespace 目录项可以声明多组 `profile_inputs`。每组包含稳定 ID、本地化小标题、默认值，以及 `text`、`password` 或 `select` 输入类型。Select 使用有序的 `{value, label}` 选项：工具页面显示 label，并将 value 保存进 Profile。工具页面会按照目录中的声明顺序，在工具状态选择器下方渲染这些输入项。`web_search` 和 `web.run` 卡片分别保存自己的搜索 Provider 与 Token；目前 Provider 只支持 Tavily。原先独立的 Web Search 设置页签已移除。

输入项可以通过 `visible_when` 声明需要显示的工具状态，例如 `["modified"]`。输入项隐藏后，其已保存的 Profile 值不会被清除。卡片 description 默认在该工具支持的所有状态下显示；条目可以使用相同状态列表格式的 `description_visible_when` 自定义显示条件。目录项还可声明 `profile_mutations`：通用 Profile 处理只在 Modified 状态下执行其中配置的 description 或 parameter description 追加操作。Chat Default 中 `request_user_input`、Goal 工具、部分 `collaboration` Function 和 GitHub MCP Namespace 的工具使用指导都使用此机制；Converter 不再按 Function 名称写死指导文本。Hosted `web_search` 无论状态都会进行协议转换，但只有 Modified 会追加其 Profile guidance。

工具页面首次加载时会默认展开所有 Namespace 行。该展示状态与 Namespace 在 Profile 中的状态无关，用户仍可在当前页面手动折叠。

内置的 **Chat Default** Profile 会禁用旧版 `multi_agent_v1` Namespace，同时保持 `collaboration` 启用。Collaboration 子工具会为 Chat 展开，并恢复为原生 Responses Namespace 调用；它们不会通过 Code Mode `exec` 转译。任何 Namespace 设为 Disabled 时，其所有子 Function 都会被强制设为 Disabled，并锁定状态选择器，直到重新启用该 Namespace。

用户填写的值随用户 Profile 保存到 `inputs.<function-item-id>.<input-id>`。从当前 Profile 创建副本时会复制当前值；切换或重置 Profile 时会恢复已保存的值。所有打包的内置 Profile 也允许编辑并显式保存这些 field；保存值写入 `tool_profile_input_overrides.<profile-id>`，不会改写打包 JSON。内置 Profile 的工具传递状态仍保持只读。输入项只有被对应运行时功能读取后才会生效；当前 Modified Function 会读取 `guidance`，`image_gen.imagegen` 会读取其 Base URL 和 Token。
