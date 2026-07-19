# Codex-Rosetta 第四轮独立代码审计报告

审计日期：2026-07-09（MDT）

审计画像：`.agent-work/audit/PROFILE.md`，状态为 `Draft`。

修复状态：F-01～F-03 均已按本轮发现完成最小修复；Codex `0.144.0` 兼容性结论已纠正为 `Pending / not approved`，仍不能发布为“已验证兼容”。

## 审计验证

- 仓库状态已检查：是。分支为 `master`，相对 `origin/master` ahead 1；HEAD 为 `eb947426572ad7658c4b5ad19688fa68659a06b6`。发现形成时的快照为 74 个 tracked 修改、14 个 untracked 文件、tracked diff 3,358 additions / 862 deletions；修复后为 74 个 tracked 修改、16 个 untracked 文件、tracked diff 3,413 additions / 920 deletions。新增的两个 untracked 文件是 F-01/F-02 回归测试。未执行 commit、push、PR、release 或 deploy。
- 差异已审阅：是。重点覆盖认证/Admin mutation、配置 CAS/activation、跨请求状态、proxy/stream lifecycle、工具本地化、SQLite/脱敏、Responses converter、Codex compatibility ledger、CI/release/Docker 和对应测试。
- 审计范围与抽样依据：沿 `/v1/responses`、embeddings、model list、Admin 配置/测试/模型发现、SSE、跨轮工具映射、错误诊断、兼容性升级与发布路径端到端抽样；按 Draft profile 的正确性、可靠性、安全和发布可追溯性排序风险。
- 关键质量属性：正确性与可靠性最高，安全与发布可追溯性次之；随后是可维护性、可运维性、性能/容量和供应链。
- 已运行测试：
  - F-01/F-02 定向集：`48 passed`。
  - `conda run -n llm-rosetta make lint`：通过；Ruff check、276-file format check、`ty check` 全绿。
  - `conda run -n llm-rosetta make test`：`2444 passed, 4 skipped, 9 warnings`，共收集 2,448 项，Python 3.14.6。
  - `conda run -n llm-rosetta make check-codex-compat`：通过；Codex source 为 `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`，12 个 contract groups 仍明确为 `Possibly unchanged`。
  - `conda run -n llm-rosetta make check-release-version RELEASE_TAG=v0.144.0.r0`：通过；这只验证版本/tag 形状，不构成 release 批准。
  - 当前 checkout wheel 在干净 Python 3.10 和 3.13 环境安装通过；core、Google converter、gateway import 和 `codex-rosetta-gateway --version` 均通过。
  - `git diff --check`：通过；`codegraph sync`：通过。
- 未运行测试：`tests/integration`、agentabi、完整 triggered live Codex matrix、native GPT route、compact/resume/fork/restart、multi-agent/plugin/MCP/web-search/UI phase、Admin 浏览器、Docker daemon、GitHub Actions、真实 release/deploy、负载/容量、备份恢复和依赖漏洞/许可证扫描。原因是需要外部凭证、真实客户端/模型、浏览器、Docker/远端环境或 owner 基线。
- 已检查高风险流程：认证 principal + provider/model/window scope、缺失 window 的 request-local 降级、配置 candidate validation/CAS/rollback、API key 生命周期、工具映射持久化、stream 正常/异常/cancel 终态、phase buffer 上限、诊断落盘、多 app config owner 和 Admin outbound client cleanup。
- 已检查发布/回滚/观测/恢复路径：检查了 manual tag validator、GitHub Web UI release runbook、本地 wheel-to-Docker 来源合同、config `.bak`/activation rollback、SQLite/trace/request log；未实际发布、部署或演练恢复。
- 假设：生产通常每个进程只运行一个 gateway app，但 `create_app()` 的工厂合同仍必须保证实例隔离；Docker/远程部署意味着不能把 loopback 当作唯一运行边界。
- 需要人工复核：Draft profile 的 owner、legal/privacy、ASVS/threat model、SLO/error budget、CI secret、incident response、签名/SBOM 和依赖治理；以及兼容性报告引用的外部 trace/session。
- 已知过时上下文或冲突证据：原升级报告曾绑定 `419e6f9` 并写成 approved。现已记录真实 audit-time dirty snapshot 并降为 pending；未来仍需绑定一个 exact clean Rosetta commit 才能批准。

## 主要发现

### 已修复

1. **F-01：模块全局 `_config` 使多个 `create_app()` 实例串用配置**

   已删除 `gateway.app._config`。`create_app()` 创建 `App` 后立即设置 `app.gateway_config`；proxy、embeddings、OpenAI/Google model list、web-search、Admin config/testing helper 都从 `request.app.gateway_config` 读取；hot reload 只更新请求所属 app。

   新增双 app 回归：创建 app A 后再创建 app B，验证 A 仍使用自己的 model/provider、base URL、auth header、web-search config、两类 model catalog、embeddings config 和 Admin helper；更新 A 后 B 保持不变。原先 app A 返回 `Configured models: model-b` 的复现已被该测试锁住。

2. **F-03：Codex 兼容性批准结论违反 mandatory live-test 与 revision 绑定规则**

   `docs/dev/version-compatibility/reports/20260709-codex-v0.144.0.md`、`README.md` 和 `compatibility-points.md` 已统一为 `Pending / not approved`。报告逐项区分 `tested`、`unverified / not triggered` 和 `unsupported`，保留受控 `deepseek-v4-flash` Lite/code-mode/`exec` 证据，但明确它不是 native GPT 证据。

   报告记录本轮发现时的 dirty snapshot：HEAD `eb947426…`、74 tracked、14 untracked、3,358 additions / 862 deletions，并明确这不是可重现 clean release revision。只有未来在 exact clean commit 上完成全部 triggered live matrix 后，才能重新批准。未修改手工 `v0.144.0.r0` tag 形状，也未启用 PyPI/Docker 发布。

3. **F-02：上游模型发现失败时未关闭专用 `AsyncClient`**

   `fetch_upstream_models()` 已改为 `async with AsyncClient(...)`，并显式透传 `asyncio.CancelledError`。回归测试覆盖成功、连接异常、JSON 解析异常和取消；四条路径都验证 context `enter_count == 1`、`exit_count == 1`，且取消继续向上传播，没有 double close。

### 记录为技术债

1. **D-01：hosted web-search 只有 round limit，没有总调用/总时间/费用预算。** 沿用上一轮记录；触发条件是面向不可信/高流量客户端广泛启用，或出现 quota/cost/长连接事故。
2. **D-02：release provenance 仍完全手工。** 当前没有 checksum、签名、SBOM、clean-commit/tag-target 强制门禁；在扩大分发或 owner 批准更强供应链基线时重新评估。

### 无需处理

- `GatewayStateScope` 对 principal/provider/model/window 的请求级隔离、缺失 window 时 request-local/non-persistent 降级，以及 SQLite compound key 设计合理。
- Config writer 的 digest CAS、stable lock、0600 atomic replace/backup、fsync、prepare-before-write 和 assignment-only activation 路径有清晰 ownership 与负向测试。
- Token-only redaction 与中英文安全文档一致；普通 prompt/password/secret/personal data 的保留属于已明确的当前策略，而非隐式遗漏。
- Stream telemetry 的 exactly-once terminal owner、phase buffer 的 event/byte 上限、Responses direct passthrough 和 namespace/custom/freeform converter 路径有较强自动化覆盖。

总体健康状况：F-01～F-03 已收口，运行时配置现在只有 app owner，Admin outbound client cleanup 有全路径回归，兼容性 ledger 不再越过自身 release gate。当前完整本地自动化和 wheel smoke 为绿，但 Codex `0.144.0` 兼容性仍是 pending；最高剩余风险是未执行的真实 native GPT、compact/resume/fork、plugin/MCP/web-search/UI phase 和 multi-agent 矩阵，而不是本轮新增的运行时代码。

## 风险排序依据

本报告按用户/业务影响、凭证与数据隔离、发生概率、爆炸半径、可逆性、证据强度、系统性程度和修复成本排序。F-01 曾有可执行复现并可能错发上游；F-03 直接违反现有 release gate；F-02 影响 Admin 失败路径资源可靠性。三项均已用最小、可逆改动修复并补真实行为断言，没有按文件大小、覆盖率百分比或主观代码味道排序。

## 维护性判断

本轮没有新增共享服务或平行状态层：F-01 删除 module-global owner，收敛到已有 `app.gateway_config`；F-02 复用既有 async context-manager 生命周期；F-03 只纠正唯一兼容性 ledger 的证据状态。影响模块边界清晰，新增测试覆盖真实多实例与异常/取消行为。暂不建议后续结构性清理；D-01/D-02 继续按既有触发条件跟踪。
