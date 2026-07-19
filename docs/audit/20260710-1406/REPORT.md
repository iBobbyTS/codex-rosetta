# Codex-Rosetta 第 14 轮代码审计报告

审计时间：2026-07-10 14:06–14:17 America/Edmonton  
审计画像：`.agent-work/audit/PROFILE.md`（`Draft`）  
完整台账：`.agent-work/audit/20260710-1406/FULL.md`

结论：**本轮 clean，没有确认新的可操作 finding。** 未修改实现、测试或文档，没有 stage、commit、push、PR、release 或 deploy；仅写入被忽略的审计台账。

## 审计验证

- **仓库状态已检查：是。** `master` 比 `origin/master` ahead 1，HEAD 为 `eb94742`；当前有 97 个 tracked 修改文件、30 个非忽略 untracked 文件，无 staged diff。tracked diff 为 9,018 行新增、1,597 行删除。
- **差异已审阅：是。** 重点抽样 `gateway/proxy.py`、`app.py`、`auth.py`、`config.py`、Admin auth/config/key routes、HTTP transport、Google URL-image conversion、`observability/persistence.py`、tool-mapping crypto、CI/Makefile/package/release metadata 及其行为测试。
- **审计范围与抽样依据：** 按 Draft profile 将 Codex 协议正确性、gateway 状态 owner、principal 隔离、持久化事务/回放、认证/CORS、远程图像 SSRF 边界、流式/HTTP envelope 和 release gate 作为高风险路径；用前轮台账避免把已接受债务重新包装成新问题，但本轮结论以当前源码和新执行结果为准。
- **关键质量属性：** 正确性、可靠性、安全、资源隔离、持久化一致性、发布完整性和可维护性。
- **已运行测试：** `conda run -n llm-rosetta make lint` 通过（Ruff、format、`ty`）；`conda run -n llm-rosetta make test` 通过，**2717 passed, 4 skipped, 9 warnings**；`make check-codex-compat`、`make check-release-version RELEASE_TAG=v0.144.0.r0` 和 `git diff --check` 均通过。
- **兼容性证据：** Codex source commit `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`；静态 contract 为 Changed: None，但仍保留 12 组 `Possibly unchanged`，未把静态 gate 当作 live compatibility 证明。
- **未运行测试：** 需要真实凭证/外部状态的 integration、agentabi/live Codex/provider matrix、浏览器 Admin、外部 GitHub Actions；本轮也未重跑 Docker/Compose、Python 3.10/3.13 clean-wheel、生产规模负载/容量、漏洞/许可证扫描、backup/restore drill 和真实 release/deploy/rollback。
- **已检查高风险流程：** window/provider metadata quota 与 accounting、encrypted mapping row/session/principal/global budget、replacement/TTL/rollback/replay、请求与 stream cleanup、`/v1` fail-closed auth、Admin token/CORS、config CAS/activation、token redaction、URL-image DNS/redirect/proxy/MIME/size/deadline/cancellation、HTTP/SSE limits。
- **已检查发布/回滚/观测/恢复路径：** 本地静态 compatibility 和 release-version gate 通过；config/SQLite rollback 与诊断路径有自动化覆盖。外部发布 provenance、签名/SBOM 和恢复演练仍需人工证据。
- **假设：** 多个不互信 API-key principal 可能共享进程；provider/model 输出和 URL 属于不可信输入；当前接受的 public-health/token-only redaction 与单 Admin 角色合同不变。
- **需要人工复核：** 真实 Codex compact/resume/restart/plugin/MCP/web-search/multi-agent matrix，生产容量目标，外部 CI，release provenance/signing/SBOM 和恢复演练。
- **已知过时上下文或冲突证据：** 无新的冲突。当前 compatibility report 仍为 Pending，12 组静态合同仍明确为 `Possibly unchanged`。

## 主要发现

### 无需处理

- 本轮没有确认新的 `必须修复`、`需要规划` 或独立的 `记录为技术债` finding。
- 第 13 轮新增的 principal-fair quota 与 encrypted mapping 分层预算，在当前源码中仍保持单 owner、原子校验/回滚和负向/并发/迁移测试覆盖；本轮未发现回归。
- Google URL-image、Admin/auth/config、HTTP/SSE 与 release gate 的独立抽样未发现新的可复现缺陷。

### 既有技术债（不重复计为本轮 finding）

- Audit profile 仍为 Draft，缺 owner、legal/privacy、ASVS、SLO/error budget、incident response、CI 权限、signing/SBOM 和 dependency governance 基线。
- 真实 Codex/provider evidence、外部 CI、生产容量/费用标定、backup/restore 和 release provenance 仍依赖人工流程。
- 已记录的 successful SSE 总 duration/size、web-search 总调用/时间/费用预算、单 Admin 角色、inline SPA/CSP 和 token-only diagnostic retention 语义未在本轮重新分类。

## 整体健康状况

当前变化面很大，但高风险 owner 已较清晰：in-memory state 留在两个 store，exact replay 和 quota transaction 留在 `PersistenceManager`，auth/config/CORS/redaction 使用 app-owned prepare/commit 路径，URL-image 使用独立受限 egress policy。完整本地 lint/type/test 与静态 release/compatibility gate 均为绿。最高剩余风险来自未执行的真实 Codex/provider matrix、外部 CI 和生产治理证据，而不是本轮确认的实现缺陷。

## 风险排序依据

本报告按协议/数据正确性、安全与跨 principal blast radius、可用性、发生概率、可逆性、证据强度、系统性和修复成本排序。由于本轮没有形成同时具备当前代码证据与可复现失败路径的新问题，因此结论为 clean，不以文件大小、复杂度或未覆盖行本身制造 finding。

维护性判断：最新 quota/persistence 修复继续留在既有三个 owner 内，没有新增平行 cache/service；现有复杂度由真实失败、并发、迁移和回滚测试覆盖，本轮不建议额外结构性重构。
