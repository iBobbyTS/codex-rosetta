# Codex-Rosetta 第 12 轮代码审计修复报告

审计开始：2026-07-10 11:28 America/Edmonton  
审计完成：2026-07-10 12:45 America/Edmonton  
审计画像：`.agent-work/audit/PROFILE.md`（`Draft`）  
完整台账：`.agent-work/audit/20260710-1128/FULL.md`

本轮发现的 2 项“必须修复”和 3 项“需要规划”已全部修复并验证。未 commit、push、PR、release、deploy，也未重置、回退或覆盖现有大型 dirty worktree。

## 审计验证

- **仓库状态已检查：是。** 当前 `master` 为 `eb947426572ad7658c4b5ad19688fa68659a06b6`，`origin/master` 为 `d3e899aea478002d965b0a591fbedf803f80ddb1`。最终 `git status --porcelain=v1` 有 127 项；tracked diff 涉及 97 个文件、8,010 行新增和 1,568 行删除；无 staged diff。
- **差异已审阅：是。** 覆盖当前 gateway、HTTP transport/vendor、state store、observability、Admin/config、converter、CI/Docker/release、文档与测试改动；对 5 项 finding 的真实入口、状态所有权、失败映射和回归证据均已复核。
- **审计范围与抽样依据：** 按 Draft profile 从 Codex-facing Responses 入口、认证前请求解析、上游响应解析、跨请求状态、stream/tool lifecycle、持久化、观测和发布路径追踪；HTTP/vendor 是本轮高 churn 安全边界，因此继续覆盖 generic transport。
- **关键质量属性：** 正确性、可用性/安全、兼容可靠性、运维性和可维护性优先，其次为性能/成本与供应链来源完整性。
- **已运行测试与检查：**
  - `conda run -n llm-rosetta make lint`：通过；Ruff check、Ruff format check、`ty check` 全绿。
  - `conda run -n llm-rosetta make test`：通过；**2694 passed, 4 skipped, 9 warnings**。
  - 5 项修复跨模块组合回归：**117 passed**。
  - 定向主仓回归：metadata/state **29 passed**；metrics/health **30 passed**；worker/subprocess **7 passed**；HTTP transport **23 passed**。
  - upstream `httpclient`：header 定向 **13 passed**；完整 correctness **165 passed**；后加的 CONNECT **2 passed**。
  - upstream `httpserver`：入站定向 **7 passed**；`test_httpserver_correctness.py` **65 passed**。
  - upstream manifest/version/diff、lint 与 re-vendor 一致性：通过；`make dep-check` 通过并报告 `all modules up-to-date, nothing to check`。
  - `conda run -n llm-rosetta make check-codex-compat`：通过；source commit `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`，Changed: None；仍有 12 组 Possibly unchanged。
  - `conda run -n llm-rosetta make check-release-version RELEASE_TAG=v0.144.0.r0`：通过。
  - `git diff --check`：通过。
  - Python wheel smoke：同一个当前 checkout wheel 在 Python **3.10.20** 和 **3.13.2** 的 clean venv 中通过 core import、Google converter import、gateway import 和 CLI `--version`；版本均为 `0.144.0.r0`。
  - Compose smoke：版本化 Compose 配置与当前 wheel build 通过；因本机 8765 已有用户进程，隔离运行在 18765，`/health` 返回 `status: ok`，容器版本为 `0.144.0.r0`；测试容器和网络已清理。
  - `codegraph sync`：通过；同步 14 个 changed files、872 个 nodes。
- **未运行测试：** `tests/integration/**`、真实 provider/API/agentabi/live Codex、浏览器 Admin、负载/容量、外部 GitHub Actions、依赖漏洞/许可证、备份恢复、真实 release/deploy/rollback。
- **已检查高风险流程：** auth 前 request headers/trailers、provider/proxy response headers/interim/redirect/CONNECT/trailers、provider metadata 跨请求状态、stream terminal cleanup、deferred-tool budget、encrypted mapping、config activation/rollback、diagnostic redaction。
- **已检查发布/回滚/观测/恢复路径：** 本地 compatibility/tag gate、3.10/3.13 wheel、current-checkout Docker provenance、Compose runtime、config `.bak`/activation compensation、SQLite/key 配对恢复和 health/stream/request log 已检查；外部发布和恢复演练未执行。
- **假设：** gateway 可能对外绑定；provider/proxy/工具端点属于可故障或被攻陷的外部信任边界；持有 gateway API key 的多个 principal 可能共享一个进程。
- **需要人工复核：** compatibility checklist 触发的真实 Codex/API 测试、外部 CI、发布 revision、供应链签名/SBOM、容量基线和恢复演练仍需由发布负责人确认。
- **已知过时上下文或冲突证据：** 修复前报告中的 Open 状态和 `2677 passed` 已被当前实现与 **2694 passed** 的最终主仓结果取代。兼容性报告仍为 Pending/not approved；静态 contract gate 不能替代 live matrix。

此前接受的 public health token-only 合同保持不变：公开 provider 名、prompt/PII、普通 password/secret/client-secret/proxy password 和错误正文属于已接受残余内容；只脱敏 configured token/API key/Bearer/Authorization。本轮没有重新打开该业务语义。

## 主要发现

### 必须修复

本轮无未解决的“必须修复”项。原 F-01、F-02 已解决：

1. **F-01 入站 HTTP header section 缺少 aggregate envelope：已解决。**

   upstream `httpserver` 从 `0.2.1` 更新到 `0.2.2`。请求 headers 与 chunked trailers 统一限制为 100 个字段、64 KiB（包含 framing/结束空行）和不可被逐行续期的 10 秒 monotonic deadline。超限稳定返回 431 并关闭连接。vendored 文件与 normalized upstream 完全一致。

2. **F-02 上游 response headers 绕过 body/SSE envelope：已解决。**

   upstream `httpclient` 从 `0.4.5` 更新到 `0.4.6`。同步/异步 reader 对最终 headers、`100 Continue`、redirect、proxy `CONNECT` 和 trailers 统一执行 100 headers、64 KiB、10 秒总 deadline。gateway 将 header/trailer overflow 稳定映射为 `UpstreamSafetyError`，不回显敌意内容。vendored 文件与 normalized upstream 完全一致。

### 需要规划

本轮无未解决的“需要规划”项。原 F-03、F-04、F-05 已解决：

3. **F-03 `ProviderMetadataStore` byte 无界且缺少 principal fairness：已解决。**

   metadata 以 canonical UTF-8 JSON bytes 计费，默认预算为 1 MiB/entry、8 MiB/scope、16 MiB/principal、64 MiB/application，并保留 10,000 entry cap。batch/replacement 在 mutation 前完成原子预检，失败保留旧状态；count eviction 只淘汰同一 principal，不能跨 principal 驱逐。容量错误稳定映射为 413。

4. **F-04 `errors_last_hour` 实际只有五分钟：已解决。**

   新增独立、紧凑、只记录 error seconds 的 3,600 秒 `_ErrorCountWindow`；原五分钟 latency/request metrics 不变。字段名与实际保留范围一致，且无需每次构造 3,600 个空 datapoints。

5. **F-05 image worker close 无法保证及时退出：已解决。**

   移除 `ThreadPoolExecutor`，改为固定数量 daemon threads 与 bounded queue。`close()` 会关闭 owner、取消 tokens、唤醒等待提交者、drain/cancel queued work、为每个 worker 放入 sentinel，且不会 join 卡死 worker。subprocess 回归证明 30 秒卡死任务不会阻塞解释器退出。

### 记录为技术债

- Audit profile 仍为 Draft，缺 owner、legal/privacy、ASVS、SLO/error budget、incident response、signing/SBOM 和依赖治理基线。
- Release provenance、真实 Codex/provider evidence、外部 CI 与 rollback 仍依赖人工流程。
- Count-only error diagnostics、web-search 总调用/时间/费用预算和 multi-replica continuity 继续按前轮接受语义保留；本轮未重新包装为新 finding。

### 无需处理

- 当前 `/v1` fail-closed auth、Admin token/origin gate、JSON object boundary、parse-first env substitution 和 config CAS/atomic write/activation compensation 未发现新问题。
- Request-local nonce/cleanup、persistent principal/provider/model/window scope、deferred-tool 原子 byte budget、stream complete/error/cancelled 终态与 AES-GCM exact mapping replay 具有较强自动化覆盖。
- 5 项修复均放在既有所有权边界内：HTTP parser 修在 upstream 后 re-vendor；metadata 扩展现有 store；hour metric 使用独立紧凑窗口；worker lifecycle 由一个固定有界 owner 管理。未引入平行 parser/cache/service。

## 整体健康状况

本轮确认的 5 项风险已全部关闭。当前最稳固的部分是 HTTP envelope、state scope/config transaction、stream terminal lifecycle、deferred-tool budget、encrypted mapping，以及覆盖 3.10/3.13 wheel 和 current-wheel Compose 的本地发布前门禁。当前最高剩余不确定性来自未执行的真实 Codex/provider live matrix、外部 CI、容量测试和人工发布/恢复流程，而不是本轮 5 个实现缺口。

下一轮建议只在准备兼容性确认或发布时执行 checklist-triggered live tests、外部 CI 与容量/恢复验证；不要重复已经全绿的第 12 轮定向集合。

## 风险排序依据

本报告按未认证可达性、外部信任边界、内存/连接/进程级 blast radius、发生概率、可逆性、证据强度和系统性排序。F-01/F-02 原先优先级最高，因为分别位于 auth 前和外部 response parser；F-03 涉及长期累计内存与跨 principal 连续性；F-04 影响运维判断；F-05 影响 shutdown/rollout。当前这些失败路径都已有直接实现修复和针对性验证，因此不再保留 Open finding。

维护性判断：本轮修复保持了 parser、state store、metrics 和 worker 的所有权边界，新增复杂度集中且有 117 项组合回归与完整主仓测试保护；无需后续清理性重构。`.agent-work/audit/CURRENT.md` 已不存在，审计已收口。
