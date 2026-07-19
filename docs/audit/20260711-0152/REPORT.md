# 第 22 轮代码审计报告

## 审计验证

- 仓库状态已检查：是。分支为 `audit/20260711`，审计起始 HEAD 为 `2c29d36`，修复结束 HEAD 为 `18eb243`；index 为空，工作树只有既有的 `scripts/analyze_codex_jsonl_errors.py` 和 `tests/test_analyze_codex_jsonl_errors.py` 两份 unstaged 修改。
- 差异已审阅：是。分别审阅了第 21 轮修复、两项第 22 轮修复，以及 analyzer/test unstaged `provider_like` 汇总修改；没有把既有 WIP 混入修复提交。
- 审计范围与抽样依据：依据 `.agent-work/audit/PROFILE.md`（Draft），覆盖 Gateway 入口、认证、model 路由、API key 状态隔离、SQLite tool-history 重放、observability/redaction、Responses SSE/phase/tool 流、analyzer、CI、手工 release、Docker 本地 wheel 和恢复/清理路径。通用 converter、Admin UI 与依赖面按高风险交点抽样。
- 关键质量属性：正确性、可靠性优先，其次为安全、运维性与可修改性，再考虑性能和成本。
- 已运行测试：修复前定向组 **38 passed**；修复后定向组 **68 passed**；完整非 integration 测试 **2842 passed, 5 skipped, 9 warnings**（Python 3.14.6，14.49s）。
- 已运行门禁：`make lint` 通过 Ruff、299 文件 format、ty 和 Complexipy ratchet；`make check-codex-compat` 在 source commit `2e8c3756f95789c215d9ea9a5ade6ec377934b3f` 上通过且 `Changed: None`；release tag 检查、wheel build、`git diff --check` 均通过。
- 未运行测试：带凭据的真实 provider/Codex/agentabi、外部 GitHub Actions、Admin 浏览器 smoke、Docker daemon build/smoke、漏洞/许可证/SBOM/签名扫描、生产 deploy/rollback、备份恢复演练、敌意 proxy/DNS 和负载测试。
- 已检查高风险流程：强制 Admin 密码与 Gateway API key；不同 API key 的 principal scope；Responses→Chat 历史重写；加密 SQLite mapping 的读取、写入、重启、key 错配、篡改和容量边界；stream cancellation/finalization；stats/embeddings；JSONL session/trace 解析。
- 已检查发布/回滚/观测/恢复路径：仓库没有自动发布 workflow；`push-package`、`push-docker`、`push` 均禁用；GitHub Release 手工 tag 为 `v{codex_version}.rN`；Docker/Compose 只接收当前 checkout wheel；tool mapping 数据和密钥可成对备份恢复。
- 假设：本轮沿用已敲定语义——只脱敏 token/API key/Bearer/Authorization，普通 `password`、`proxy_password`、`secret`、`client_secret`、prompt 和正文保留；persistent tool history 以加密 SQLite 为权威，不以内存替代。
- 需要人工复核：audit profile 的 owner、法律/隐私要求、SLO、漏洞响应、CI credential、Actions pinning/signing 和 SBOM 仍未定义；Codex 真实 live matrix 仍未完成。
- 已知过时上下文或冲突证据：本机 `codex-cli 0.144.1`，包和当前 release contract 仍为 `0.144.0.r0`；兼容性报告明确标为 pending，不能把本轮自动 contract pass 当作 live compatibility approval。

## 主要发现

### 已解决（原需要规划）：analyzer 对普通 `secret=` 做了超出既定边界的脱敏

- 位置：`scripts/analyze_codex_jsonl_errors.py:54-59`，`redact_text()`。
- 触发：可报告错误中出现 `secret=ordinary-secret` 或 `client_secret=ordinary-client-secret`。
- 修复前证据：`SENSITIVE_ASSIGNMENT_RE` 含无条件的 `secret` alternative；Gateway persistence 的回归测试则明确保留普通 `secret`/`client_secret`，只脱敏 token/API key/Bearer/Authorization。`9e61807` 之前 analyzer 只有 Bearer 测试，没有普通 secret 保留测试。
- 影响：历史诊断会静默丢掉用户要求保留的非 token 数据，降低取证完整性，并与 Gateway 持久化规则不一致。
- 修复方向：删除通用 `secret` alternative，保持 authorization、API key、`*token`、Bearer 与已知 key shape 脱敏；补“普通 secret/client_secret 保留”和“token 仍脱敏”的回归。不要借此改变用于聚合的 path/UUID/数字归一化。
- 修复：`9e61807` 删除通用 `secret` alternative，新增行为测试证明普通 `secret`/`client_secret` 保留，同时 token/API key/Authorization/Bearer 仍被脱敏。该提交没有包含任何既有 provider-like WIP。

### 已解决（原需要规划）：非字符串 `model` 可越过客户端错误边界成为 500

- 位置：`src/codex_rosetta/gateway/proxy.py:204-206`、`src/codex_rosetta/gateway/app.py:495-519`、`src/codex_rosetta/gateway/embeddings.py:66-91`。
- 触发：例如向 `/v1/embeddings` 发送 `{"model":["x"],"input":"hello"}`；其他代理入口也通过 `extract_model()` 进入同一 lookup。
- 修复前证据：`extract_model()` 声明返回 `str | None`，实际原样返回任意 JSON 值；两个入口只判断 truthiness 后调用 `GatewayConfig.resolve()`。修复前复现得到 `TypeError: cannot use 'list' as a dict key (unhashable type: 'list')`，而不是 API-shaped 400。
- 影响：外部无效输入制造内部 500 和噪声告警，并绕过正常的 pre-resolution telemetry；未发现数据泄漏或进程崩溃。
- 修复方向：在共享 model 提取边界要求非空字符串，embeddings 复用相同校验；使用既有 provider-specific 400 error shape，并补通用 proxy 和 embeddings 回归。
- 修复：`18eb243` 在共享 `extract_model()` 边界拒绝非字符串和空白值；`/v1/responses` 与 `/v1/embeddings` 对 list、dict、number、bool、empty 和 whitespace-only model 均返回 400 `invalid_request_error`，缺失 model 和正常 alias 行为保持不变。

### 记录为技术债：Codex live acceptance 和 audit profile 决策仍未闭合

- 自动 contract、SSE ordering、phase、custom tool 和持久化回归均通过，但 compact/resume、collaboration、tool_search、真实 provider matrix 和完整 agentabi 仍缺 live 证据。
- 兼容性文档已经诚实标记 pending，因此这不是新运行时缺陷；完成 live matrix 前不得声称 0.144.x 全面兼容。
- audit profile 的安全/供应链/运维 owner 决策仍需人工补齐。

### 无需处理：已审阅的既定安全与发布语义

- Admin 密码、登录与 Gateway API key 仍为强制配置。
- 不同 API key 的 cache/state 继续由 principal scope 隔离。
- persistent localized tool history 先从加密 SQLite 读取，写入失败或认证失败会 fail closed；持久路径不会以 `CodexToolLocalizationStore` 内存状态替代。
- 仅保留 GitHub 手工 Release，tag 使用 `v{codex_version}.rN`；没有 PyPI/Docker 自动发布，Docker 使用当前 checkout wheel。
- stats I/O、embeddings 计数、analyzer session/trace schema 分离和 complexity ratchet 的第 21 轮修复在当前代码中可见且门禁通过。

## 整体健康状况

系统整体健康，认证、principal 隔离、SQLite 历史重放、stream 生命周期和发布来源边界仍是最稳固区域。本轮两个边界一致性缺口均已用局部修复和真实 endpoint 行为回归闭合，没有新增状态所有者或通用框架。下一轮应重新独立审计当前修复后的树，而不是把本轮修复结果直接视为 clean round。

## 风险排序依据

两项发现均可由确定输入稳定复现，证据强，但未造成凭据泄漏、持久化损坏、权限绕过或服务进程崩溃，因此原归类为“需要规划”而非“必须修复”。F-02 位于所有代理入口的公共信任边界，爆炸半径更广；F-01 直接违反已敲定数据语义，但只影响离线诊断保真度。两项现已修复；live matrix 与 profile gap 仍属于已显式记录、当前可接受的技术债。

维护性判断：F-01 保持为一个 regex/test 小修；F-02 复用现有共享 `extract_model()`，没有平行复制路由规则或重写 Gateway coordinator。两个提交均恰好包含一次 `Maintenance-Audit: true`，未 push、PR、release 或 deploy。
