# Codex 版本兼容性定向审计报告

## 审计验证

- 仓库状态已检查：是。用户已有 `src/codex_rosetta/__init__.py` 修改和
  `docs/*/version-compatibility.md` 未跟踪文件；本任务没有修改这些文件。
- 差异已审阅：是。任务改动仅为 `AGENTS.md` 和根目录
  `version-compatibility/` 文档。
- 审计范围与抽样依据：覆盖 Codex request/metadata、Responses direct/bridge、
  tool localization、namespace/tool_search、web search、SSE/phase、reasoning、
  compaction/history、model catalog 和升级测试路径。
- 关键质量属性：正确性、可靠性、可修改性和可运维性优先；安全仅检查了 header
  forwarding 和日志/状态边界，不是完整安全审计。
- 已运行测试：专项兼容测试 `383 passed`；`make lint` 通过；最终完整测试
  `2288 passed, 4 skipped`。
- 测试稳定性：第一次完整测试有一个 profiling 测试临时失败，单测复跑和第二次
  全量复跑均通过。
- 未运行测试：agentabi、真实 provider、WebSocket、Responses Lite、remote compact
  和 Codex UI 人工验收；缺少本次任务所需的外部运行条件，且不是纯文档变更的安全
  本地验证步骤。
- 已检查高风险流程：window/session 隔离、工具历史重放、stream phase、custom
  `apply_patch`、deferred tools 和 compact orphan 修复。
- 已检查发布/回滚/观测/恢复路径：检查了版本门禁、stream trace/request log 和
  persistence/TTL；未进行实际发布或回滚。
- 假设：当前 custom provider 仍使用 HTTP `/v1/responses` + SSE，并继续发送兼容
  `x-codex-window-id` header。
- 需要人工复核：真实 Codex request capture、agentabi 多轮工具矩阵和 UI phase 行为。
- 已知过时上下文或冲突证据：AGENTS.md 写的是 `codex-rosetta` conda 环境，但当前
  本机实际可用的是历史环境 `llm-rosetta`；升级清单允许环境变量覆盖。

## 主要发现

### 需要规划

1. Canonical `client_metadata` 已成为 Codex 元数据真相来源，而 bridge 的 window
   状态仍依赖兼容 HTTP header。header 停发或语义变化会破坏状态隔离。
2. `tool_search_call`/`web_search_call` 没有进入 phase buffer 的工具信号集合，且没有
   文本后接 native search tool 的专项回归。
3. Responses WebSocket、Responses Lite、`/responses/compact`、code-mode `exec/wait`
   和增量 `previous_response_id` 都没有实现或验证；不能随 Codex model catalog 静默启用。
4. `multi_agent_v2`/`collaboration` 没有完整的 namespace discovery/call/output 回归。

### 记录为技术债

1. Gateway `/v1/models` 是通用 OpenAI list，不是 Codex `ModelInfo` catalog；如果 Codex
   开始从 custom provider 动态读取 catalog，会影响 apply_patch、reasoning、context
   和 tool mode。
2. `create_goal`/`update_goal` 等 Desktop/runtime-only tool 契约无法完全从相邻开源
   源码验证，需要保留真实 payload fixture。

### 无需处理

1. Responses→Responses direct path 原样保留未知请求字段、响应 JSON 和原始 SSE，
   是当前最稳固的前向兼容边界。
2. 现有 custom `apply_patch`、tool localization、history mapping、reasoning、phase 和
   web search 的主路径有较强的专项测试覆盖。

整体健康状况：当前 HTTP/SSE + full-history 的 Codex 主路径有扎实的实现和测试基础，
但 Codex 正在扩展 metadata、transport、tool mode 和 multi-agent wire shape。最高风险
不是普通 converter，而是 window 身份、phase/tool 事件语义和未启用的新 transport/
catalog 能力。下一轮应优先补真实 request fixture、native search phase 测试和 v2
namespace/code-mode 回归。

## 风险排序依据

本报告按是否会破坏 agent loop、影响多个 provider、造成跨会话状态串扰、是否静默
退化、是否能用配置关闭、证据强度和修复成本排序。单纯文件大小或代码复杂度不作为
优先级依据。
