# Codex-Rosetta 第 13 轮代码审计报告

审计与修复时间：2026-07-10 12:48–14:02 America/Edmonton  
审计画像：`.agent-work/audit/PROFILE.md`（`Draft`）  
完整台账：`.agent-work/audit/20260710-1248/FULL.md`

本轮确认的 3 项容量/隔离问题均已在原有 owner 内修复并完成回归验证；没有 stage、commit、push、PR、release 或 deploy，也没有改动或回退无关用户工作。

## 审计验证

- **仓库状态已检查：是。** 当前分支 `master` 位于 `eb947426572ad7658c4b5ad19688fa68659a06b6`。最终有 97 个 tracked 修改文件和 30 个非忽略 untracked 文件；tracked diff 为 9,018 行新增、1,597 行删除；无 staged diff。
- **差异已审阅：是。** 重点覆盖 `gateway/proxy.py` 两个跨轮 store、`observability/persistence.py` 的 encrypted mapping schema/transaction/query、相关 route 生命周期、测试、双语 security 文档与 Codex compatibility ledger。
- **审计范围与抽样依据：** 依据 Draft profile，以 Codex Responses 入口、跨轮工具/metadata 状态、认证 principal 隔离、持久化、迁移、并发、失败回滚和发布门禁为主；既有完整审计对 stream、HTTP、Admin/config、image、release 路径的结论继续保留。
- **关键质量属性：** 正确性与兼容可靠性最高，其次为安全/跨 principal 隔离、资源可用性、持久化一致性、运维性和可维护性。
- **已运行测试：** quota/fairness 专项 **117 passed**；扩展 state/persistence/config 专项 **293 passed**；`make lint` 通过（Ruff、format、`ty`）；`make test` 通过，**2717 passed, 4 skipped, 9 warnings**；`make build`、`make check-codex-compat`、`make check-release-version RELEASE_TAG=v0.144.0.r0` 全部通过。
- **构建与运行验证：** Python 3.10/3.13 clean-wheel 的 core/gateway smoke 全部通过；Compose 从当前 checkout wheel 构建并启动 `0.144.0.r0`，`/health` 返回 HTTP 200，之后已停止并删除 smoke stack 和本轮生成的 `docker/config/`。
- **兼容性证据：** Codex source commit `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`；静态 gate 为 Changed: None，仍明确保留 12 组 `Possibly unchanged`。
- **其他检查：** `git diff --check` 通过；`codegraph sync` 通过。
- **未运行测试：** `tests/integration/**`、真实 provider/API/agentabi/live Codex、浏览器 Admin、外部 GitHub Actions、生产规模负载/容量、漏洞/许可证扫描、恢复演练、真实 release/deploy/rollback。
- **已检查高风险流程：** principal/window ownership、loaded/deferred 双 map 计数、provider metadata batch/replacement、encrypted mapping startup/migration/upsert/query、TTL、并发、SQLite 写失败回滚、413 route 映射、真实 window 连续性。
- **已检查发布/回滚/观测/恢复路径：** 本地 wheel/Compose/version/compatibility gate 通过；SQLite transaction rollback 和 matched key/DB fail-closed 路径有自动化证据；外部发布与恢复演练未授权也未执行。
- **假设：** 多个 gateway API key principal 可能共享同一进程；持有合法 key 的客户端仍是不可信资源消费者；provider/model 输出属于外部不可信输入。
- **需要人工复核：** compatibility checklist 要求的真实 Codex/API 测试、外部 CI、生产容量目标、发布 provenance/signing/SBOM 和恢复演练。
- **已知过时上下文或冲突证据：** 第 12 轮的 provider metadata fairness 只证明不跨 principal 驱逐，未覆盖单 principal 占满全局 count；第 13 轮修复已补上 per-principal count quota 和对应回归。

## 主要发现

### 无需处理（本轮已解决并验证）

1. **`WindowToolSearchStore` 不再跨 principal 驱逐。**

   - 每个 principal 默认最多 256 个唯一 scope；同一 scope 同时存在于 loaded/deferred map 时只计一次。
   - 达到 principal cap 时硬拒绝；每张 map 的全局 count 满时，只能替换当前 principal 自己最旧的 scope，没有候选则拒绝。
   - TTL、replacement、eviction、clear 和 accounting rebuild 会归还预算；并发测试证明不会超卖。

2. **`ProviderMetadataStore` 不再允许单 principal 独占全部小 entry。**

   - 每个 principal 默认最多 1,024 entries；batch/replacement 在同一锁内计算 projected count，replacement 不双计。
   - 全局 count overflow 只允许当前 principal 的 oldest candidate；其他 principal 的状态不会被驱逐。
   - 覆盖另一 principal 仍可写入、atomic batch rejection、TTL/clear 和并发饱和。

3. **encrypted tool mapping 已有完整分层硬预算和事务边界。**

   - 默认上限：每行 16 MiB；每 session 2,048 行/64 MiB；每 principal 8,192 行/256 MiB；全局 32,768 行/512 MiB。
   - encrypted-v1 表无损增加并回填 `mapping_bytes`；plaintext/lossy legacy row 继续执行原有不可恢复清理合同。
   - startup 在解密前校验 accounting/capacity；query 在加载 ciphertext 前校验 session；upsert 用 `BEGIN IMMEDIATE` 原子执行 expiry、replacement-aware accounting、校验和写入，失败会 rollback 并保留旧 row。
   - 回归覆盖 rows/bytes、replacement、expiry、raw SQLite accounting、restart/migration、异常 replay、并发不超卖和模拟 SQLite 写失败。

### 记录为技术债

- Audit profile 仍为 Draft，缺 owner、legal/privacy、ASVS、SLO/error budget、incident response、CI 权限、signing/SBOM 和 dependency governance 基线。
- 真实 Codex/provider evidence、外部 CI、live rollback/restore 与发布 provenance 仍依赖人工流程。
- 已文档化的 successful SSE 无总 size/duration 上限、count-only error dump、token-only diagnostic redaction 继续作为既有接受语义，本轮不重复包装为新 finding。

## 整体健康状况

系统在协议转换、HTTP envelope、配置事务、流式终态、加密恢复和自动化测试方面整体稳固。本轮最高风险的 principal resource-ownership 缺口已经统一落到现有 store/persistence owner：数据隔离与资源配额现在采用同一 authenticated principal 边界，超限显式失败，不会静默破坏其他 principal 的跨轮状态。剩余主要风险不在本轮实现，而在真实 Codex/API matrix、外部 CI、生产容量标定和发布/恢复治理证据。

## 风险排序依据

本报告按用户/业务影响、跨 principal blast radius、触发成本、可持续性、可逆性、证据强度、系统性和修复成本排序。F-01 原本会静默改变他人 agent tool 行为，F-02 会持续阻断 continuation，F-03 的磁盘/内存 blast radius 最大；三项均有代码修复、负向/并发/迁移/回滚测试和完整 gate 支持，因此可从“需要规划”降为“无需处理”。

维护性判断：修复分别留在现有 `WindowToolSearchStore`、`ProviderMetadataStore` 和 `PersistenceManager`，没有新增平行 cache/service；新增复杂度集中在明确的 accounting 与 transaction 边界，并由 23 个新增测试和双语/兼容性文档覆盖，无需后续结构性清理。
