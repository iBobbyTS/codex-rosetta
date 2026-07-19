# Codex-Rosetta 第 21 轮代码审计报告

结论：本轮确认的 **2 个必须修复、2 个需要规划** finding 均已完成修复并分别提交。`2c29d36` committed tree 的 `make lint` 与 `make test` 全部通过。该提交完成并核验后，同两份 analyzer 文件又出现新的并发 unstaged diff；它未纳入第 21 轮提交或验证，并已原样保留。既有 Codex live matrix 与 Draft audit profile 治理缺口仍需跟踪。

## 审计验证

- 仓库状态已检查：是。审计基线为 `e48f9b1`，修复收口 HEAD 为 `2c29d3680745cf586bda3a5cddd671158cf18ae8`。提交后最初核验为 clean；scratch 清理后的最终复核检测到 `scripts/analyze_codex_jsonl_errors.py` 与 `tests/test_analyze_codex_jsonl_errors.py` 新增并发 unstaged diff（128 insertions / 1 deletion），未 stage、commit 或 revert。
- 差异已审阅：是。初始 finding 分析期间这两个文件发生并发漂移，中间态曾出现 `2 failed, 2 passed`；修复证据与最终门禁以 committed `2c29d36` tree 为准。随后新出现的 dirty diff 未纳入这些测试结论。
- 审计范围与抽样依据：覆盖最新 body-limit/log-level/stats 提交、当前未提交 analyzer 差异、Gateway auth/request/provider/stream/state 路径、持久化与日志边界、Codex 官方 session/rollout-trace 合同、CI/build/release 和复杂度门禁。
- 关键质量属性：正确性与可靠性最高，其次是安全、可维护性、运维性，再其次是性能和成本。
- 已运行测试：最终 `make test` 为 **2822 passed, 5 skipped, 9 warnings**；F-02 analyzer 定向测试 **10 passed**；此前最新提交相关定向组 **181 passed**。
- 已运行静态/构建门禁：`make lint` 的 Ruff、299 文件 format、ty 与 Complexipy ratchet 全部通过；`make check-codex-compat` 通过且 `Changed: None`；release-version check 通过；wheel build 通过；diff check 通过。
- 复杂度回归验证：临时 complexity 26 探针会被 ratchet 拒绝，探针随后已删除。
- 已检查高风险流程：auth-before-body、body size hot reload/rollback、request/window state、stream cancel/finalize、tool/deferred state、加密持久化、日志脱敏、终端 stats、Codex 两类 JSONL schema。
- 已检查发布/回滚/观测/恢复路径：本地合同、release version、wheel、config rollback、stream/request/error observability 已抽样；未执行生产 deploy/rollback、backup/restore 或外部 CI。
- 假设：Draft profile 中的 owner、privacy/legal、ASVS、SLO、incident response、SBOM/signing 与最终部署模型仍未定义。
- 需要人工复核：真实 provider/Codex/agentabi、生产备份恢复、负载、外部 CI 与供应链证据。
- 已知过时上下文：兼容性文档保留了一个明确标注日期的旧 dirty snapshot；它不代表当前 `e48f9b1` 树，也未宣称兼容审批完成。

## 主要发现

### 已解决 F-01：stats 输出失败会让正常代理请求失败

`StatsStreamHandler.record_request()` 直接写入并 flush `stderr`，只用 `finally` 释放锁，没有像普通 logging `emit()` 一样吞掉输出故障。`_proxy_handler()` 又在主 `try/finally` 之前调用它。已用 broken stream 复现 `OSError: stderr closed`。

触发后，单纯的终端/pipe/logging driver 故障原本会让正常模型请求返回 500，并绕过代理自己的 telemetry/state-finalization 区间。`a9823ea` 已把 stats 渲染改为严格 best-effort，并覆盖 write、flush 与 active-line close 失败。

### 已解决 F-02：analyzer 的可信 schema 与默认扫描输入不一致，真实 session 错误会漏报

新 analyzer 把 `schema_version=1`、`payload.type=inference_failed` 等 raw rollout-trace 事件作为“结构化 provider 证据”。这个 schema 本身与 Codex 源码一致，但它只有设置 `CODEX_ROLLOUT_TRACE_ROOT` 才会写到任意指定目录；analyzer 默认仍只扫描普通 `~/.codex/sessions`、`archived_sessions` 和 session backup。

普通 session 的真实合同是 `{type:'event_msg', payload:{type:'error'|'stream_error', ...}}`。当前实现没有显式解析这两种事件，也忽略 `stream_error.additional_details`。最终树直接验证中，`event_msg/error` 的 generic connection message、`event_msg/stream_error` 的 connection reset，以及 `additional_details='HTTP 503 service unavailable'` 全部返回空候选。

因此修复前的默认运行可能在真实 provider error 存在时仍报告“结构化上游失败 0”。`2c29d36` 已为普通 session 与 raw rollout trace 建立独立 root、parser 和去重域；支持 `CODEX_ROLLOUT_TRACE_ROOT` / `--trace-root`，采集真实 `error` / `stream_error` 字段，同时只允许保守判定后的 terminal error 授权 failover。`stream_error` 只记录为 transient evidence，structured failed container 也不会因关键词缺失而漏报。定向测试为 **10 passed**，且脱敏规则仍只处理 token。

### 已解决 F-03：per-model stats 漏掉 `/v1/embeddings`

计数入口原本只在 `_proxy_handler()`，而 embeddings 使用独立 handler。`3353a32` 已让 embeddings 在模型解析后通过既有入口按 `upstream_model` 计数，并加入 endpoint 级回归测试。

### 已解决 F-04：复杂度与 standalone script 静态检查没有进入 CI

项目配置了 Complexipy max 25，但 `make lint`/CI 不运行它；当前手动执行会失败，热点包括 `_web_search_stream_event_generator` 86、`OpenAIResponsesToolOps.p_tool_definition_to_ir` 64 和 `_stream_event_generator` 40。与此同时，`PY_CHECK_PATHS` 没有包含新 analyzer，日常 Ruff/format/ty 门禁不会检查该 700+ 行脚本。

`c8f295e` 已把 maintained analyzer 纳入 Ruff、format 与 ty；`3d97198` 已加入官方 Complexipy snapshot ratchet，记录 25 个非 vendored 历史热点并阻止新增或恶化。该方案没有为通过门禁而一次性大改 stream/converter。

### 记录为技术债：兼容性 live matrix 与治理证据仍未闭合

Codex source contract 当前匹配 `2e8c3756...`，本地 lint/test/build/release-version 均健康；但 native GPT、compact/resume/fork、plugin/MCP/deferred tool、真实 web search/UI phase/error path/multi-agent 等 live evidence 仍未闭合。Draft audit profile 的安全、SLO、供应链与恢复基线也仍需 owner 决策。

### 无需处理：本轮抽样的 Gateway 核心边界

auth-before-body、固定 parser deadlines/capacity、body-size tier 与 hot reload rollback、请求 header allowlist、request/window state ownership、stream cancellation cleanup、加密 tool mapping、quota/retention/redaction、bounded Admin runtime 和本地 wheel/Docker source boundary 均保留了现有保护；本轮没有确认新的独立运行时缺陷。

## 整体健康状况

Gateway 的认证、状态 ownership、持久化和流生命周期仍是最稳固区域；本轮发现的 stats 故障隔离、analyzer 输入合同、embeddings 统计与复杂度门禁均已用局部修复和回归测试闭合。下一轮重点应回到仍未闭合的 Codex live matrix、audit profile owner 决策和生产恢复证据，而不是继续扩展本轮修复范围。

## 风险排序依据

F-01 可由常见 I/O 故障直接触发正常请求 500，爆炸半径覆盖 stats 模式全部请求且证据可复现，因此列为必须修复。F-02 会让用于 provider retry/failover 判断的数据源系统性漏报，且测试与真实默认输入合同不一致，因此同样列为必须修复。F-03 影响统计完整性但不影响代理正确性；F-04 是系统性可维护性风险但没有当前数据损坏或安全后果，故列为需要规划。上述优先级是修复前判断，不因现已解决而回写降低。

维护性判断：核心 Gateway 边界总体健康；当前新增复杂度集中在 stats side channel 和双 JSONL schema 识别，应以局部故障隔离与 schema-specific parser 修复，不建议扩展为新的共享框架。

## 修复跟进

经主线程批准，本轮已完成以下独立修复：

- F-01 已由 `a9823ea` 修复：stats 的 write、flush、active-line close 故障均为 best-effort，不再影响数据面。
- F-03 已由 `3353a32` 修复：`/v1/embeddings` 在模型解析后纳入既有 per-model stats，并按 `upstream_model` 计数。
- F-04a 已由 `c8f295e` 修复：maintained analyzer 已进入 Ruff、format 与 ty 门禁，未修改或提交 analyzer 当前工作树。
- F-04b 已由 `3d97198` 修复：官方 Complexipy snapshot watermark 记录 25 个非 vendored 历史热点，并由 `make lint` 阻止新增或恶化；临时 complexity 26 探针已验证会失败并已删除。

修复后的完整验证为 **2822 passed, 5 skipped, 9 warnings**；`make lint` 的 Ruff、299 文件 format、ty 与 complexity ratchet 全部通过。五个 commit 均准确包含一次 `Maintenance-Audit: true`。

- F-02 已由 `2c29d36` 修复：普通 session 与 raw rollout trace 使用独立证据路径，failover eligibility 仅来自保守判定的终态错误；提交只包含 analyzer 与对应测试两文件。

最终 HEAD 为 `2c29d36`。其 committed tree 与 scratch child 的两个目标 blob 完全一致；当前工作树另有随后出现并保留的 analyzer/test unstaged 修改，不属于第 21 轮提交，且没有用当前 dirty tree 重新声明测试结果。本轮没有 push、PR、release 或 deploy。
