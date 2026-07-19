# Codex-Rosetta 第七轮独立代码审计修复报告

审计时间：2026-07-10（MDT）  
审计画像：`.agent-work/audit/PROFILE.md`（`Draft`）  
完整账本：`.agent-work/audit/20260710-0048/FULL.md`

本轮发现的 1 条“必须修复”、2 条“需要规划”和 1 条“记录为技术债”问题均已修复。用户选择的业务语义是 **B：精确历史重放**——跨请求和 Gateway 重启的 tool mapping 以 SQLite 为权威状态，不依赖内存；数据库中的可执行 mapping 使用可逆认证加密，诊断界面仍只脱敏 token。没有 commit、push、PR、release 或 deploy。

## 审计验证

- 仓库状态已检查：是。当前位于 `master`，HEAD 为 `eb947426572ad7658c4b5ad19688fa68659a06b6`，比 `origin/master` ahead 1。最终工作树有 86 个 tracked diff 文件、20 个 untracked 文件；tracked diff 为 4,757 additions / 1,175 deletions，无 staged diff。
- 差异已审阅：是。重点复核加密 key 生命周期、SQLite mapping schema/migration、persistent-scope DB authority、proxy option threading、三条 stream terminal path、Compose 本地 wheel 构建合同及配套测试/文档。
- 审计范围与抽样依据：沿四条 finding 的端到端路径复核，从 tool call 写库到同进程/重启恢复，从热重载 provider config 到 Google URL image fetch，从 client early close 到 trace terminal record，从 fresh checkout wheel 到 Compose container health。
- 关键质量属性：正确性、安全、跨重启可靠性、状态单一所有权、观测一致性、构建可复现性和可维护性。
- 已运行测试：
  - `conda run -n llm-rosetta make lint`：通过；Ruff、format、`ty check` 全绿。
  - 修复期定向测试：`232 passed, 2 warnings`；后续精简回归：`203 passed`。
  - `conda run -n llm-rosetta make test`：`2533 passed, 4 skipped, 9 warnings`，Python 3.14.6。
  - `conda run -n llm-rosetta make check-codex-compat`：通过；14 组 High-confidence unchanged、12 组 Possibly unchanged、Changed: None；Codex source commit `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`。
  - `conda run -n llm-rosetta make check-release-version RELEASE_TAG=v0.144.0.r0`：通过。
  - Python 3.10/3.13 clean wheel：core install/import 通过且不会安装 `cryptography`；`[gateway]` install、CLI version、AES-GCM mapping round-trip 通过。
  - Colima/Compose：本地 current-wheel build、容器启动、`/health/live`、CLI version、容器内 encrypted persistence 均通过；修正 `.dockerignore` 后 build context 约从 21.7 MB 降到 1.48 MB，且不再归档 `.codegraph/daemon.sock`。Colima 已恢复为停止状态。
  - `git diff --check` 与 `codegraph sync`：通过。
- 未运行测试：完整真实 provider/API 与 agentabi matrix、native GPT、compact/resume/fork、plugin/MCP/deferred tool、WebSocket、浏览器 UI phase、GitHub Actions、负载/容量、依赖漏洞/许可证、生产备份恢复、release/deploy/rollback。
- 已检查高风险流程：exact mapping 写入、认证解密、key 丢失/错误/篡改、legacy migration、并发 key 创建、principal 隔离、同进程与重启恢复、proxy 热重载、stream cancel、Compose provenance。
- 已检查发布/回滚/观测/恢复路径：DB+key 成对备份合同、external secret-manager key、legacy row 清理、stream trace、current-wheel Compose 和 manual GitHub release 文档均已检查；没有执行真实 release/deploy。
- 假设：持久化 tool mapping 是 Gateway 的可执行兼容状态；诊断 redaction 不能作为历史恢复来源。该假设已由用户明确选择 B 确认。
- 需要人工复核：key rotation 尚未实现；部署方必须成对备份/恢复 `gateway.db` 与 `tool-mapping.key`，或确保 external secret manager 能恢复同一个 env key。真实 Codex/provider 兼容结论仍需按 live matrix 验证。
- 已知过时上下文或冲突证据：本机 `codex-cli 0.144.1`，而 package/compatibility target 是 `0.144.0.r0`；二者不能混作同一个兼容性证据。版本兼容报告继续保持 **Pending / not approved**。

## 主要发现

### 已修复

1. **F-01：重启后 token redaction 静默改写真实工具历史**

   已按 B 方案拆开“诊断脱敏”和“可执行历史”。SQLite mapping 保存 AES-256-GCM 认证密文，AAD 绑定 principal/provider/model/session/call ID；默认 key 原子创建为 `data/tool-mapping.key`（`0600`），也可使用 `CODEX_ROSETTA_TOOL_MAPPING_KEY`。persistent scope 的同进程续轮和重启续轮都从 DB 恢复 exact payload，内存 store 不再充当跨轮 authority。missing/wrong/malformed key、ciphertext tamper 和 mapping 写入失败均 fail closed；legacy plaintext/`[REDACTED]` rows 在事务中仅清理 mapping table，不影响 request log/metrics。

   回归覆盖原始 SQLite/WAL/SHM 不含 token 明文、decrypt exact equality、重启 exact replay、DB+key 配对恢复、并发 key 创建、TTL/prune、多 principal 隔离和权限。普通字段保留原值；诊断输出继续只脱敏 token。

2. **F-02：`server.proxy` 热重载后的 outbound proxy split-brain**

   `create_app()` 已停止修改 process-global `HTTP_PROXY`/`HTTPS_PROXY`。`ProviderInfo.proxy_url` 通过 conversion options 显式传到 Google converter/message/content ops，URL image fetch 与 provider transport 共享同一个 app-owned proxy source。热重载和多 app instance 不再依赖陈旧环境变量。

3. **F-03：client disconnect 被 stream trace 误记为成功**

   converted、raw passthrough、web-search 三条 generator 现在显式区分 `completed`、`error`、`cancelled`。`GeneratorExit` 与 `CancelledError` 不再落入成功路径；`stream_outcome`、`stream_complete`、`stream_error` 与外层 499 语义一致。三条 early-close 回归均通过。

4. **F-04：Compose 引用仓库不发布的 registry image**

   Compose 已改成从当前 checkout 的 `dist/*.whl` 本地构建；`make compose-up` 先重建 wheel，再传入 `LOCAL_WHEEL` 并执行 `docker-compose ... up --build -d`。新增 `CODEX_ROSETTA_CONFIG_DIR` 用于隔离 config mount；`.dockerignore` 排除 `.codegraph/`、`.agent-work/` 和 `.agents/`，避免 socket、审计材料和 agent 配置进入 build context。

### 当前无未解决的必须修复/需要规划项

- 本轮四项 finding 均已有代码、测试和文档证据支持“已修复”。
- 兼容性报告中的 live matrix、key rotation、Draft audit profile 治理字段仍是明确的人工/后续边界，不伪装成本轮已完成事项。

## 整体健康状况

本轮把三个分裂的所有权边界收敛了：tool history 由 SQLite 唯一承载，proxy 由 app config 唯一承载，stream terminal 由明确 outcome 唯一描述；Compose 也复用了当前 wheel 的既有 provenance 合同。全量测试、静态检查、双 Python wheel smoke 和容器 smoke 均通过。最高剩余风险不在本轮实现，而在尚未执行的真实 Codex/provider live matrix、key rotation/灾备演练和 Draft profile 中尚未确认的治理基线。

## 维护性判断

影响模块集中在 persistence/crypto、gateway proxy、Google conversion、stream trace 和 Docker 入口，责任边界比修复前更清晰。新增复杂度主要是必要的 authenticated-encryption/key lifecycle；它被隔离在单独模块，并由 migration、tamper、concurrency 和 restart tests 保护。`cryptography` 只进入 gateway extra，core 零必需依赖边界未被扩大。当前不建议额外重构；后续若实现 key rotation，应单独设计版本化 re-encryption 流程和中断恢复测试。

## 风险排序依据

排序综合核心 Codex workflow 影响、静默数据/语义破坏、秘密暴露风险、爆炸半径、可逆性、证据强度、系统性程度和修复成本。F-01 同时涉及 exact replay 与 secret-at-rest，优先级最高；F-02 是 egress source-of-truth；F-03 是诊断一致性；F-04 是本地部署 provenance。修复后的结论来自当前代码、回归和真实本地容器/多 Python smoke，而不是仅依赖实现摘要。
