# Codex-Rosetta 第三轮独立代码审计报告

审计日期：2026-07-09（MDT）

修复验证日期：2026-07-09（MDT）

审计画像：`.agent-work/audit/PROFILE.md`，状态为 `Draft`。

## 审计验证

- 仓库状态已检查：是。基线仍为 `eb94742`；当前工作树有 74 个 tracked 修改和 14 个 untracked 实现、测试、脚本及文档文件，tracked diff 为 3,358 additions / 862 deletions；未修改 `_vendor/**`，未执行 commit、push 或 PR。
- 差异已审阅：是。重点复核了本轮修改的 state root 生命周期、公共请求入口、配置 prepare/commit、认证与脱敏状态、CORS、key label、stream terminal telemetry、request-log/SQLite final update 及对应测试；同时保留并复核前两轮的大型共享 dirty worktree。
- 审计范围与抽样依据：按 Draft profile 的正确性、可靠性、安全和高变更路径，端到端追踪 `/v1/responses`、`/v1/embeddings`、Admin 配置写入/热重载、gateway key 生命周期、跨请求工具状态、流式遥测、错误诊断和发布门禁。
- 关键质量属性：正确性与可靠性最高，安全、可运维性、可维护性其次；性能/容量和供应链按可触发风险抽样。
- 已运行测试与检查：
  - 六项发现综合定向回归：`272 passed`。
  - `conda run -n llm-rosetta make lint`：通过；Ruff、format、ty 全绿，274 个文件格式一致。
  - `conda run -n llm-rosetta make test`：`2438 passed, 4 skipped, 9 warnings`（Python 3.14.6）。
  - `conda run -n llm-rosetta make check-codex-compat`：通过；Codex source commit 为 `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`，无阻塞性合同变化。
  - 当前 dirty tree 的隔离副本成功构建 wheel，在干净 venv 中无依赖安装并导入 core、gateway、observability（`wheel smoke OK`）。
  - `git diff --check`：通过。
  - `codegraph sync`：通过，同步 9 个变更源码文件。
- 未运行测试：真实 provider/API、agentabi、Responses WebSocket/Lite、compact/resume/fork、多客户端并发、Admin 浏览器视觉/无障碍、Docker daemon、GitHub Actions、负载/容量、备份恢复、依赖漏洞/许可证和真实 release/deploy；这些需要外部凭证、运行环境或人工操作。
- 已检查高风险流程：认证 principal + provider/model/window state ownership、工具映射持久化/清理、配置 candidate validation/CAS/prepare/commit、Admin token rotation、CORS 热更新、诊断落盘、SSE terminal/cancel/disconnect、web-search 多轮循环。
- 已检查发布/回滚/观测/恢复路径：检查并测试了配置 `.bak` 与 preparation failure、SQLite terminal update、stream trace/request log、wheel 来源；未执行实际发布、部署或恢复演练。
- 假设：gateway 可能非回环部署；同一 Python 进程内嵌或重启 app 是 `close_resources()` 公共合同应支持的生命周期。
- 需要人工复核：确认 Draft profile 的 owner、privacy/legal、ASVS、SLO/error budget、CI secret、签名/SBOM、事故响应和发布 provenance。
- 已知过时上下文或冲突证据：第三轮初始报告中的六个 failure reproduction 均已由当前代码和回归测试取代；上一轮“磁盘 rollback 等于 runtime rollback”的结论不再作为证据，当前采用 prepare-before-write 合同。

## 主要发现

### 已修复

1. **F-01：shutdown 未清除 scoped 工具状态 — 已修复**

   app 现在显式持有 metadata、localization、window-tool 三个 root，并在非流式/流式请求中显式传递。三个 store 都有 root marker 和 root-only `clear_all()`，scoped view 无法清空共享 root；`close_resources()` 使用 `is not None`，并清理 discovered/deferred window tools。回归覆盖同进程 cleanup、重建 app 获得全新 roots、以及 scoped view 的权限边界。

2. **F-02：合法但非 object 的公共 API JSON 返回 500 — 已修复**

   `_proxy_handler` 与独立 embeddings 入口都在模型解析前要求顶层 JSON 为 dict。`/v1/responses` 与 `/v1/embeddings` 的 route-level 测试覆盖 list、null、string、integer、boolean、float，全部返回 source-compatible 400。

3. **F-03：配置激活失败只回滚磁盘、不回滚 runtime — 已修复**

   auth principals/labels/Admin token、stream-trace config/redactor、persistence redactor 和规范化 CORS 都在写盘前完成构造；activation callback 只做普通属性赋值，并最后交换 app/module config。auth、trace、persistence、CORS 四个 prepare 阶段分别注入失败时，磁盘字节、module `_config`、app config、auth、trace、persistence、CORS 均保持旧值。

4. **F-04：非字符串 key label 让 telemetry 成为请求失败点 — 已修复**

   `validate_api_key_label()` 是单一合同：必须为 string、最长 128 字符、允许空字符串。`GatewayConfig` 与 Admin create/update 双边调用；dict/list/oversize 均 400 且不改文件，duplicate 仍为 409。metrics/request-log/persistence 异常降级为 warning，强制 SQLite/request-log 失败时代理成功响应仍为 200。

5. **F-05：Admin CORS allowlist 类型不安全且不会热更新 — 已修复**

   CORS 现在必须是 `list[str]`，只接受不带 credentials/path/query/fragment 的 HTTP(S) origin，统一大小写、尾斜杠和默认端口后去重并保存规范值。请求时读取 live `app.admin_cors_origins`，activation 同步替换；substring origin 被拒绝，old→new reload 后 old=403、new=204。

6. **F-06：stream telemetry 在 response 构造时提前结束 — 已修复**

   初始 request-log 在 `StreamingResponse` 构造后安全写入，但 `active_streams` 和完成指标保持打开。`_InstrumentedStream` 统一拥有终态：正常完成记录 200（或原 response status），generator 异常记录 502，cancel/提前 `aclose()` 记录 499；source close 和 finalize exactly-once。最终写入完整 duration/status/error/profile，更新 gauge、metrics、provider health 与同一 request-log/SQLite 记录。回归覆盖 stream 打开时 gauge=1、正常完成、异常、重复 `aclose()`、显式 task cancellation 和 SQLite final update。

### 记录为技术债（按要求未处理）

1. **D-01：hosted web-search 只有 round limit，没有总调用/时间/费用预算。** Owner：gateway/web-search maintainers。触发条件：面向不可信/高流量客户端广泛启用，或出现 quota/cost/长连接事故。建议增加 per-round、total-call 和 wall-time budget，并返回确定性的 failed-tool result。

2. **D-02：release provenance 仍完全手工。** 当前无 checksum、签名、SBOM、clean-commit/tag-target 强制门禁；Draft profile 也未定义供应链标准。Owner：project/release maintainer。触发条件：扩大分发或 owner 批准供应链基线。

### 无需处理

- 当前 principal + provider + exposed model + window/request 的请求期隔离设计合理；本轮问题集中在 root lifecycle，修复后 cleanup/restart 回归已通过。
- token-only redaction、owner-only SQLite/trace permissions、10,000 条 count-only error-dump retention 与已确认策略一致；本轮未改变这些边界。
- Responses phase buffer、direct passthrough、namespace/custom tool、reasoning/opaque item 和 Codex contract gate 在本轮范围内没有新的 confirmed mismatch。
- CI/Makefile/Docker/release 的既有变更通过完整本地 lint/test/compatibility 与隔离 wheel smoke；未执行真实 Docker/CI/release。

## 总体判断

第三轮确认的六项问题已全部修复，并有真实 failure-path、route-level、lifecycle 与 persistence 回归支撑。修复复用了既有三个 ownership boundary：app-owned state roots、config prepare/assignment-only commit、stream generator terminal owner；没有引入平行 service。当前剩余风险主要是明确保留的 D-01 web-search 总预算和 D-02 release provenance，以及 Draft profile 尚未批准的治理基线，而不是这六项运行时缺陷。

## 维护性判断

受影响模块集中在 gateway state/config/telemetry 与 observability persistence；所有跨模块状态都有单一 owner。新增复杂度主要是 prepared state value 与 exactly-once stream wrapper，并由 failure-stage、normal/error/cancel/disconnect、SQLite 回归覆盖。当前不建议追加结构性重构；后续只需在接入新的配置依赖或 stream terminal 类型时扩展现有 prepare/finalize 入口。

## 风险排序依据

本报告按 agent loop/认证/请求可用性影响、跨实例或跨 principal 爆炸半径、触发概率、可逆性、证据强度、系统性程度和修复成本排序。F-01 至 F-06 现有代码与回归证据支持标记为已修复；D-01/D-02 因用户明确排除且当前有配置/流程缓解，继续作为有 owner 与触发条件的技术债。
