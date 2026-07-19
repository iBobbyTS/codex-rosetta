# Codex-Rosetta 第 23 轮代码审计报告

结论：本轮确认的 **2 个必须修复、1 个需要规划** finding 与 1 个低风险 portability debt 已全部修复。不存在需要业务方重新敲定的语义：修复沿用既定合同——Gateway 输入必须受资源预算约束；诊断只脱敏 token/API key/Bearer/Authorization，普通 password、secret、prompt 和正文保留；持久历史以加密 SQLite 为权威。

## 审计验证

- 仓库状态已检查：是。分支为 `audit/20260711`，审计基线为 `18eb24350f6c2079272340c90e2dc76d7fbf2659`。修复后 index 为空；工作树只剩审计前已有的 `scripts/analyze_codex_jsonl_errors.py` 与 `tests/test_analyze_codex_jsonl_errors.py` 两份 unstaged `provider_like` WIP。本轮没有 push、PR、release 或 deploy。
- 差异已审阅：是。覆盖 `origin/master..18eb243` 的七个 audit commit、当前两份 analyzer WIP，以及其与 committed analyzer 的边界。
- 审计范围与抽样依据：按 `.agent-work/audit/PROFILE.md`（Draft）把正确性、可靠性和安全排在最前；覆盖 Gateway 入站认证、model 路由、principal state、加密 SQLite tool-history replay、Responses↔Chat conversion、SSE/transport、Admin/observability、analyzer、CI/build/release/Docker 和恢复/清理路径。
- 关键质量属性：正确性、可靠性、安全、运维性、可修改性；性能与成本主要按可触发的内存/响应放大评估。
- 已运行测试：`conda run -n llm-rosetta make test` 收集 2,869 项，结果 **2,864 passed, 5 skipped, 9 warnings**。跳过项为 1 个 opt-in Chromium 回归和 4 个无适用 public-API item 的参数实例。
- 已运行静态门禁：`conda run -n llm-rosetta make lint` 通过 Ruff、299 文件 format、ty 与 Complexipy ratchet；`git diff --check` 通过。
- 已运行构建/合同门禁：sdist 与 wheel build 成功；`make check-codex-compat` 在 source commit `2e8c3756f95789c215d9ea9a5ade6ec377934b3f` 上通过且 `Changed: None`；`make check-release-version RELEASE_TAG=v0.144.0.r0` 通过。因工作树有已知 analyzer WIP，本轮 build 仅为验证，不是 clean release evidence。
- 未运行测试：带凭据的真实 provider/Codex/agentabi、真实浏览器、Docker、外部 GitHub Actions、生产 deploy/rollback、backup/restore drill、负载、漏洞/许可证/SBOM/签名。
- 已检查高风险流程：强制 Admin/API key 鉴权、API-key principal 隔离、model/window identity、SQLite mapping 认证读写与重启、stream cancellation/finalization、raw/converted SSE、token redaction、Admin self-test、手工 release/current-wheel 来源。
- 已检查发布/回滚/观测/恢复路径：本地 build/contract/tag gate、request/error/stream/body diagnostics、mapping backup/key pairing 与 cleanup；未执行外部发布或生产恢复演练。
- 假设：沿用已确认的 token-only redaction 与 database-authoritative replay 语义。Codex window ID 当前合同为 `{UUID}:{window_number}`，因此可以设置远高于当前真实值但远低于 64 KiB header budget 的固定上限。
- 需要人工复核：真实 Codex live matrix；audit profile 的 owner、法律/隐私、SLO/error budget、漏洞响应、Actions pinning、SBOM/signing 和生产恢复要求。
- 已知过时上下文或冲突证据：本机 CLI 为 `codex-cli 0.144.1`，包合同仍为 `0.144.0.r0`；兼容性文档明确标记 pending/not approved，本轮自动 contract pass 不等于 live compatibility approval。

## 主要发现

### 已修复 F-01：`model` 与 `x-codex-window-id` 资源预算绕过

- 位置：`src/codex_rosetta/gateway/proxy.py::extract_model`、`gateway/app.py::_proxy_handler`、`gateway/state_scope.py::GatewayStateScope.for_request`、`gateway/proxy.py::ProviderMetadataStore` / `WindowToolSearchStore`。
- 触发 A：已认证请求提交超长但非空的 `model`。路由失败时 `/v1/responses` 和 `/v1/embeddings` 会把整个值插入 404。
- 实测：1 MiB `model` 分别产生 **1,048,695 bytes** 与 **1,048,675 bytes** 的 404，并完整包含输入。正常 body 上限是 50 MB，且配置允许 unlimited。
- 触发 B：近 64 KiB 的唯一 `x-codex-window-id` 被复制进每个 `GatewayStateScope` key；现有 byte quota 只统计 value，不统计 scope/key 字符串。
- 实测：同一 principal 下 1,024 个 tiny metadata entry + 60,000-character window IDs，`tracemalloc` 保留 **61,956,140 bytes**，store 自报 quota usage 仅 **7,168 bytes**。
- 影响：一个已认证 API key 可制造大响应和持续的未计费内存放大；并发时可导致高延迟或 OOM。
- 修复：`f8b60e2` 在共享 ingress 把 model 限制为 256 UTF-8 bytes、window ID 限制为 128 UTF-8 bytes；超限在 routing/state 前返回 source-shaped 400。exact/+1、多字节、responses/embeddings/Chat/Anthropic/Google 与 pre-routing 回归均通过；`10fe69e` 完成这些测试的静态类型收口。

### 已修复 F-02：analyzer 裸 Gateway/Google API key 泄漏

- 位置：`scripts/analyze_codex_jsonl_errors.py::redact_text`、`OPENAI_KEY_RE`。
- 触发：历史 error 文本包含没有 `api_key=` 前缀、也不在 Bearer header 中的裸 key。
- 实测：项目自己生成的 `rsk-<48 hex>`、`rsk-internal-<32 hex>`，以及文档支持的 Google `AIza...` 均被原样保留；它们会进入 console Markdown 和可保存的 JSON signature。
- 影响：违反“仅脱敏 token/API key”的已确认合同，历史诊断报告可能直接泄露有效访问凭据。
- 修复：`f3ca68a` 只增加三种高置信 token shape；回归证明 key 被脱敏，而 ordinary password、secret、client_secret、prompt 和正文继续保留。

### 已修复 F-03：analyzer 全局 cardinality 上限

- 位置：`discover_jsonl_files()` 与 `analyze_paths()` 的 candidate list / `groups` dict。
- 触发：大量文件或大量互不相同的 normalized error signature。单行、单 record 字段和每组 sample 虽有上限，但总文件数和总 group 数没有上限。
- 实测：50,000 条不同的短 tool error 形成 50,000 groups；即使 `sample_limit=0`，仍保留 **29,360,829 bytes**、peak **53,823,456 bytes**。
- 影响：默认会扫描 active、archived 和 backup roots；大历史或 provider-controlled 唯一错误文本可让离线工具耗尽内存，与 docstring 的 bounded-memory 承诺不符。
- 修复：`9f7dd0c` 以确定性 iterator 扫描文件，最多保留 20,000 个 candidate 和 10,000 个真实 ErrorGroup；溢出按 category 显式计数并在 JSON/Markdown 披露，不伪造 signature，也不丢总 category/provider-actionable count。exact/+1、500 distinct、`sample_limit=0` 和确定性回归均通过；`b6f37e4` 完成测试类型收口。

### 已修复技术债：analyzer 默认 home path 可移植性

`dee82c0` 已把 active/archived 默认路径改为 `Path.home() / ".codex"` 推导；backup volume 仍是显式第三 root，`CODEX_ROLLOUT_TRACE_ROOT` 行为不变。

### 记录为技术债：live acceptance 与治理证据仍未闭合

自动 contract、converter、stream、persistence、lint/test/build/tag gate 均健康，但 native GPT、compact/resume/fork、plugin/MCP/deferred-tool、真实 web search/UI phase/error/Desktop/multi-agent 仍缺 live evidence。Draft profile 的安全、SLO、供应链与恢复 owner 决策也未完成；完成前不得宣称 0.144.x 全面兼容。

### 无需处理：数据库权威重放、认证隔离与发布来源

- persistent tool mapping 只通过加密 SQLite 读取/写入；missing persistence、key mismatch、认证失败或写入失败都会 fail closed，不以内存 store 代替跨请求权威。
- API key 映射到唯一配置 principal，state scope 包含 principal/provider/model/window；不同 API key 的状态保持隔离。
- Admin 密码、Admin 登录与 Gateway API key 仍强制配置。
- 仅有 GitHub 手工 Release，tag 为 `v{codex_version}.rN`；PyPI/Docker publish targets 禁用，Docker/Compose 必须使用当前 checkout wheel。
- generic 500 的 `str(exc)` 反射已复核：未发现跨 principal 或匿名披露路径；在既定“非 token 诊断保留”语义下，本轮不列 finding。
- dirty `provider_like` 目前只写 machine-readable JSON、不显示在 Markdown。仓库没有声明它必须进入 CLI，因此不把未完成意图猜成 defect；若目标是 CLI 可见，应补 rendering contract/test。

## 整体健康状况

Gateway 的认证、principal ownership、加密 SQLite replay、stream lifecycle 与手工 release/current-wheel 来源仍是最稳固区域。本轮输入 byte budget、analyzer token shape、全局 memory envelope 与默认路径问题均已在既有 owner 内局部修复，没有新增状态服务或大规模 converter 重构。下一轮必须重新独立审计修复后的树；本轮修复不能自动算作 clean round。

## 风险排序依据

F-01 可由单个已认证 key 稳定触发，爆炸半径覆盖响应分配与持久内存，且量化证据直接，因此列为必须修复。F-02 会把访问凭据复制到人读/机读报告，违反明确安全合同，修复成本低，列为必须修复。F-03 属离线工具，但默认扫描多处大历史，内存随不可信 signature 数线性增长；发生概率和影响低于数据面，故列为需要规划。portability 与治理/live gaps 当前不造成已证实运行时错误，记录为技术债。

维护性判断：修复集中在既有 ingress validator 与 analyzer aggregation/redaction owner；未修改三套 store accounting，也未新建通用框架。F-01、F-02、F-03 与 portability 均保持独立提交并覆盖真实边界；无后续结构清理要求。

## 修复提交

- `f8b60e2`：限制 request identity 字段。
- `f3ca68a`：脱敏裸 provider key。
- `9f7dd0c`：限制 analyzer retained state。
- `dee82c0`：默认 session roots 改用 `Path.home()`。
- `10fe69e`、`b6f37e4`：让新增回归满足完整 `ty` 门禁。

每个提交均有且仅有一行独立 `Maintenance-Audit: true` trailer；均未纳入 `provider_like` WIP。
