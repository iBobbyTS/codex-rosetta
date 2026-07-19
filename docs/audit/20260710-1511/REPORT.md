# Codex-Rosetta 第 17 轮代码审计报告

审计时间：2026-07-10 15:11–15:42 America/Edmonton  
审计画像：`.agent-work/audit/PROFILE.md`（`Draft`）  
完整台账：`.agent-work/audit/20260710-1511/FULL.md`

结论：**本轮确认的 1 条“必须修复”和 1 条“需要规划”finding 均已在当前 worktree 修复并完成独立验证。** opt-in request/response body logging 现在复用当前 app/config token 脱敏边界；`log_bodies` 与 `verbose` 使用独立的 logger level 合同，正文日志可以单独开启，普通 DEBUG 也不会被连带开启。

## 审计验证

- **仓库状态已检查：是。** `master` HEAD 为 `eb94742`；最终有 98 个 tracked 修改文件、33 个非忽略 untracked 文件、无 staged diff。最终 tracked diff 为 9,287 行新增/1,787 行删除。两个 finding 的修复仅落在 logging、app/proxy state plumbing、Admin config activation、测试和中英文安全文档边界，未重置或覆盖其他用户改动。
- **差异已审阅：是。** 抽样覆盖 Gateway request/auth/state/stream、Admin/config、observability/persistence、HTTP/SSE、远程图片、CI/release/Docker；修复后又复核 `BodyLogState` 从 app 创建、请求入口、非流式/流式 proxy 到 Admin hot reload/rollback 的完整数据流。
- **审计范围与抽样依据：** 按 Draft profile 优先正确性、可靠性、安全和 Codex 协议兼容；在前轮 owner 基础上独立追踪 diagnostic sinks，并用真实 Compose cross-format 路径验证 effective logger level 和 token redaction，而不是只依赖配置布尔值。
- **关键质量属性：** 凭证安全、协议正确性、流式可靠性、跨 app/principal 隔离、持久化一致性、运维可观测性、发布完整性和可维护性。
- **已运行测试：** 首轮定向 **20 passed**；扩大定向（logging、redaction、hot reload/rollback、多 app isolation、passthrough、stream）**86 passed**；changed-files Ruff check/format-check 通过；`conda run -n llm-rosetta make lint` 通过（Ruff、293 files format、`ty`）；`conda run -n llm-rosetta make test` 收集 2,737 项，结果 **2,732 passed, 5 skipped, 9 warnings**；`conda run -n llm-rosetta make build` 成功生成 sdist 与 wheel；`make check-codex-compat`、`make check-release-version RELEASE_TAG=v0.144.0.r0`、`git diff --check`、`git diff --cached --check` 均通过；`codegraph sync` 报告 `Already up to date`。
- **运行态 Compose 验证：** 使用当前 checkout wheel、隔离端口/config/network 和 synthetic 501 upstream，发送 Responses→Chat cross-format 请求。四组合结果为：F/F 不出现正文或普通 DEBUG；F/T 出现 ORIGINAL/IR/CONVERTED body DEBUG，但不出现普通 `inject:` DEBUG；T/F 只出现普通 `DEBUG | inject: store has 0 entries: []`；T/T 两者同时出现。正文 marker 被保留，synthetic gateway/provider token 在所有正文层均变为 `[REDACTED]`。容器、network、临时 image/config/data 已清理。
- **未运行测试：** credentialed integration/agentabi/live Codex/provider、真实浏览器/Admin external-origin、外部 GitHub Actions、漏洞/许可证扫描、生产负载、backup/restore、真实 release/deploy/rollback。
- **已检查高风险流程：** `/v1` fail-closed auth、Admin token/CORS/config activation、body-log hot reload/rollback、多 app 隔离、request/window state cleanup、stream cancel/finalization、encrypted tool replay、token redaction、URL-image SSRF/DNS/worker、HTTP/SSE envelope。
- **已检查发布/回滚/观测/恢复路径：** 本地 release/Codex/build gates、Docker current-wheel 来源、config/SQLite rollback、request/error/stream/body observability 已抽样；外部 provenance、签名/SBOM 和恢复演练仍缺证据。
- **假设：** body logging 为 opt-in；一般 prompt/PII/password/secret 的保留是现有明确合同，本修复只保护已配置 token 与显式 token/Bearer/API-key 字段，不扩展为通用隐私 scrubber。
- **需要人工复核：** Audit profile owner、legal/privacy、ASVS、SLO/error budget、incident response、dependency/signing/SBOM；以及未运行的真实 provider/生产运维证据。
- **已知过时上下文或冲突证据：** 本报告替代 15:28 时“两个 finding 均未修复”的中间状态；最终代码、测试与 Compose 证据支持将两项标记为 resolved。

## 主要发现

### 已解决：opt-in body logging 会把配置凭证原样写入日志

- **原风险：** 原始 request、IR、转换后 request 或 upstream response 中的 Gateway/Provider token、Authorization、Bearer 或 API-key 字段可能进入 stderr、容器日志或集中式日志系统。
- **修复：** 新增每 app 独立的 `BodyLogState`，复用 `SecretRedactor` 和当前配置 token 集合；先对完整结构脱敏，再 JSON 序列化、单行化并限制为 20,000 字符。redaction/serialization 失败只输出固定占位符，不回退到原对象或异常文本。非流式、流式、Admin hot reload/rollback 与多 app 隔离均接入同一 state owner。
- **证据：** 单元测试覆盖 exact configured token、Bearer/Authorization/API-key、JSON-encoded `function.arguments`、安全 fallback、hot reload、rollback 和多 app 隔离；Compose cross-format 日志保留普通正文，同时两个 synthetic 配置 token 在 ORIGINAL/IR/CONVERTED 三层均为 `[REDACTED]`。

### 已解决：`log_bodies=true` 可以“显示已启用、实际零输出”

- **原风险：** 只设置 `log_bodies=true`、未设置 verbose 时，CLI 声称启用正文日志，但 INFO handler 会丢弃所有 DEBUG body record。
- **修复：** 正文记录改用专用 `codex-rosetta-gateway.body` DEBUG logger；console/file handler 接受 DEBUG，普通 Gateway logger level 仍由 `verbose` 独立控制。`log_bodies` 不会开启普通 DEBUG，`verbose` 也不会自动开启正文。CLI banner 和中英文安全文档已同步此合同。
- **证据：** console 与 `FileHandler` 的四组合行为测试通过；Compose F/T 实际输出三层正文且抑制 `inject:`，T/F 实际输出 `inject:` 且不输出正文，T/T 同时输出两类记录。

### 记录为技术债

- Audit profile 仍为 Draft，owner、legal/privacy、ASVS、SLO/error budget、incident response、依赖治理、签名/SBOM 未批准。
- 真实 Codex/provider matrix、外部 CI、生产容量/成本、backup/restore 和 release provenance 仍依赖人工证据。
- `getaddrinfo()` 本身不可中断，极端 DNS 阻塞会长期占用 image worker permit；当前文档与测试明确接受“raw worker 退出前不释放 capacity”，本轮未把它重新包装成新 finding。

### 无需处理

- 当前抽样下，Gateway auth/state/stream cleanup、Admin CORS/config transaction、encrypted mapping quota/integrity、HTTP/SSE limits、Google image SSRF 边界、Docker current-wheel 与 CI 权限没有确认新的独立缺陷。
- Vendored HTTP/SSE 文件与已保存的 zerodep upstream 工作树一致，只有安装 note 拼写不同；本轮没有证据支持“直接手改 vendor”的结论。

## 整体健康状况

核心 request/state/persistence/transport owner 和 2,737 项本地门禁保持稳固。本轮最高风险的 opt-in diagnostic sink 已收敛到 app-owned、可热更新、可回滚的 token-redaction owner，并以 unit、full suite、build、compat 和真实 Compose level matrix 闭环。下一轮建议优先补真实 Codex/provider matrix 和 Draft audit profile 的人工治理决策，而不是继续扩展 logging abstraction。

## 风险排序依据

本报告按凭证可复用性、用户/业务影响、触发概率、blast radius、可逆性、证据强度、系统性和修复成本排序。F-01 原有明确 source-to-sink 与运行态泄漏证据，故优先修复；F-02 影响证据采集可信度，并与 F-01 共享 handler/state 边界，因此同轮收口。两项只有在实现、行为测试、全量 gate 和 Compose runtime 证据全部可见后才标记为 resolved。

维护性判断：修复集中在 logging state owner、现有 proxy call sites 与 config activation 边界，复用 `SecretRedactor`，未新增 module-global mutable redactor 或第二套 sanitizer；复杂度增量由定向行为测试和全量门禁覆盖，无需后续结构性清理。
