# Codex-Rosetta 第 24 轮代码审计报告

结论：本轮确认的 **1 个必须修复**问题已在主分支修复；**1 个需要规划**问题已在隔离 scratch 修复并验证，但因它完整叠加在用户原有未提交 WIP 上，尚未集成到主工作树。没有需要用户重新敲定的业务语义。

## 审计验证

- 仓库状态已检查：是。分支为 `audit/20260711`，主工作树 `HEAD=5e9e4e408e26921dcb0928df0bafa192b1bde7a8`，`origin/master=e48f9b1b37ce921583a372faae01f86f367afa03`。index 为空；工作树仍仅有审计前已存在的 `scripts/analyze_codex_jsonl_errors.py` 与 `tests/test_analyze_codex_jsonl_errors.py` 两份 unstaged `provider_like` WIP。
- 差异已审阅：是。F-01 主 commit `5e9e4e4` 与 F-02 隔离 child `0723f4f` 均有且仅有一行 `Maintenance-Audit: true` trailer。F-02 的 synthetic base `24c9a36` 精确包含两份用户 WIP；未 cherry-pick、未覆盖主工作树。
- 审计范围与抽样依据：按 `.agent-work/audit/PROFILE.md`（Draft）优先检查正确性、可靠性、安全、运维性与可修改性；覆盖 Gateway 入站认证与身份字段、路由、API-key principal 隔离、加密 SQLite tool-history replay、Responses/Chat/Anthropic/Google conversion、SSE/transport、Admin/observability、analyzer、CI/build/release/Docker。
- 已运行测试：F-01 变更与高风险定向套件 **192 passed**；主工作树全量 **2,915 passed, 5 skipped, 9 warnings**。F-02 scratch analyzer **18 passed**，scratch 全量 **2,916 passed, 5 skipped, 9 warnings**。
- 已运行静态门禁：`conda run -n llm-rosetta make lint` 通过 Ruff、299 文件 format、ty 与 Complexipy ratchet；`git diff --check` 通过。
- 已运行构建与合同门禁：sdist/wheel build 成功；`make check-codex-compat` 在 Codex source `2e8c3756f95789c215d9ea9a5ade6ec377934b3f` 上通过，`Changed: None`；`make check-release-version RELEASE_TAG=v0.144.0.r0` 通过。由于 analyzer WIP 未提交，本轮 build 仅是验证，不构成 clean release evidence。
- 未运行测试：带凭据的真实 provider/Codex/agentabi、浏览器、Docker、外部 GitHub Actions、生产 deploy/rollback、backup/restore drill、负载、漏洞/许可证/SBOM/签名。
- 已检查高风险流程：强制 Admin/API key 鉴权、principal ownership、model/window/request identity、SQLite 精确映射的认证加密读写与重启恢复、stream cancellation/finalization、raw/converted SSE、token-only redaction、Admin hot reload、手工 release/current-wheel 来源。
- 已检查发布/回滚/观测/恢复路径：本地 build/contract/tag gate、request/error/stream trace、mapping backup/key pairing 与 TTL/容量清理；未执行外部发布、生产回滚或恢复演练。
- 假设：沿用已确认合同——Admin 密码与 Gateway API key 必填；不同 API key 隔离；历史重放以加密 SQLite 为权威；仅脱敏 token/API key；仅手工 GitHub Release。
- 需要人工复核：真实 Codex live matrix；audit profile 的 owner、隐私/法律、SLO/error budget、漏洞响应、Actions/digest pinning、SBOM/signing 与生产恢复要求。
- 已知过时上下文或冲突证据：本机 CLI 为 `codex-cli 0.144.1`，包合同仍为 `0.144.0.r0`；自动 contract pass 不能替代兼容性文档中仍标为 pending 的 live evidence。

## 主要发现

### 已修复 F-01：`x-request-id` 可注入终端控制字符并放大 stream trace

- 位置：`src/codex_rosetta/gateway/app.py::_proxy_handler`、`gateway/headers.py::build_upstream_extra_headers`、`gateway/proxy.py` 的 streaming trace 创建路径、`gateway/stream_trace.py::StreamTraceLogger.log`。
- 触发：已认证调用方提交长 `x-request-id`。Gateway 没有语义长度/字符集校验，HTTP parser 的总 header 上限约 64 KiB；stream trace 会在每个 upstream chunk、IR/source event、downstream SSE 和 terminal record 中原样重复该 ID，而且它位于 `_truncate(data, max_string_chars)` 之外。
- 实测：60,000 字符 request ID、`max_string_chars=100`、100 条 tiny trace record 生成 **6,029,990 bytes**，首行 60,298 bytes。另一个 parser 复现证明 `x-request-id: req-\x1b[2J` 会保留 literal ESC；该值随后直接进入普通 Gateway 日志。
- 影响：即使 stream record 的 data 有上限，单个已认证客户端仍可按事件数放大 trace 磁盘/I/O；无论 tracing 是否开启，都可向终端日志注入控制序列。该值还会进入 profiler metadata、响应 header 和 upstream request。
- 修复：主 commit `5e9e4e4` 在共享 ingress 只接受 1–128 bytes 的 visible ASCII（`!`–`~`）；header 缺失时才生成 Gateway UUID。blank、C0/C1/DEL、非 ASCII 和超限值会在 body parsing、日志、trace、persistence、state 和 upstream forwarding 前被拒绝。Proxy 各 source envelope 与 embeddings 返回对应格式的 400，拒绝的外部值不会回显。
- 验证：定向 **192 passed**；主工作树全量 **2,915 passed, 5 skipped, 9 warnings**；`make lint` 全绿。

### 已隔离修复、待集成 F-02：WIP `provider_like` 汇总在 group 上限触发时漏计

- 位置：`scripts/analyze_codex_jsonl_errors.py::summarize_provider_like`。
- 触发：`max_error_groups` 先被非 provider signature 填满，随后出现 provider-like error。全局 `categories` 和 `error_group_overflow_by_category` 会正确计数，但新 summary 只遍历已保留的 `error_groups`。
- 实测：`max_error_groups=1` 时，先输入 generic error、再输入 `Error [OpenAI]: HTTP 401`；主报告得到 `upstream_auth=1` 且 overflow `upstream_auth=1`，但 `provider_like.candidate_count=0`、各 bucket 为空。
- 影响：JSON consumer 可能在真实 provider error 存在时得到“0 个候选”。顶层 `retention.truncated=true` 已披露全局截断，所以风险低于运行时问题，但新字段本身仍会给出错误零值。
- 修复：隔离 child `0723f4f` 在 group retention 前单遍维护 `ProviderLikeAggregate`。只累计固定 category/evidence、有限 provider×三位 HTTP status 与固定 HTTP status/category bucket；不保留第二份 signature/sample map。named group 仍只来自受限 `error_groups`，并新增 file-limit 与 retained-group truncation 披露。
- 验证：`max_error_groups=1` 丢弃 OpenAI 401 group 后，`candidate_count`、category/evidence 与 `openai:HTTP 401` 仍正确为 1；named groups 为空且明确标记 truncated。Analyzer **18 passed**，scratch 全量 **2,916 passed, 5 skipped, 9 warnings**，lint 全绿。
- 集成边界：synthetic base `24c9a368c256ea54fc63b61e0e6a86cf86b47fbd` 精确承载用户两份 WIP，child 为 `0723f4f75e331024f0e70408641d525af8208019`。为保护用户未提交工作，本轮未把它 cherry-pick 到主工作树。

### 记录为技术债：live acceptance 与治理证据仍未闭合

- native GPT、compact/resume/fork、plugin/MCP/deferred-tool、真实 web search/UI phase/error、Desktop/multi-agent 仍缺 live evidence。
- Draft profile 仍未定义 SLO、恢复、漏洞响应、SBOM/signing 等 owner 与验收线；Actions/base image 仍使用版本 tag 而非 immutable digest。在基线未获批准前，本轮只记录治理债，不将其扩大成未经证实的运行时 finding。

### 无需处理：认证隔离、数据库权威重放与发布来源

- `/v1/**` API-key auth fail closed，Admin auth 独立；stable API-key ID 进入 principal scope。
- persistent tool mapping 仅通过按 principal/provider/model/session/call-id 精确作用域的加密 SQLite 读写；missing persistence、wrong key、tamper 或容量失败均 fail closed，不以内存 store 代替跨请求权威。
- model/window identity 已在 routing/state 前受 UTF-8 byte 上限约束；stream transport 的 line/event、cancel/close、terminal telemetry 与 request-local cleanup 未发现新的独立缺陷。
- 仅保留 GitHub 手工 Release，tag 为 `v{codex_version}.rN`；PyPI/Docker publish targets 禁用，Docker/Compose 从当前 checkout wheel 构建。

## 整体健康状况

Gateway 的认证、principal ownership、加密 SQLite replay、stream lifecycle 和手工 release/current-wheel 来源仍是最稳固部分。外部 correlation header 风险已在主工作树闭合；Analyzer WIP 的有界聚合顺序错误也已有通过全量验证的隔离修复，只剩用户 WIP 的集成边界待决定。本轮不是 clean round，下一轮应从实际集成后的树重新独立审计。

## 风险排序依据

F-01 可由任一已认证 key 直接触发终端控制注入，并在 tracing 开启时按 stream event 数放大磁盘写入，证据直接、爆炸半径可累积且修复成本低，因此列为必须修复。F-02 只影响新的未提交离线汇总字段，且顶层已有 truncation signal，可逆性高、运行时影响低，因此列为需要规划。治理/live gaps 缺少已批准基线或外部凭据，只记录为技术债。

维护性判断：两项最小修复都留在现有 owner——共享 ingress identity validator 与 analyzer scan-time aggregate；没有新增服务、converter 重写或持久化架构调整。F-02 仍需在用户决定 WIP 记录方式后集成。
