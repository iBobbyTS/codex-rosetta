# 代码审计报告

## 执行摘要

- 审计模式：`Reset Baseline`
- 仓库范围与当前 head：`main@0caa7a1308452100e553c9e1e3411b9a9f0a0746`；相对 `origin/main` ahead 4；工作树在本轮审计文件外无用户代码改动。
- Audit Profile 状态：`Approved`，位于 `docs/audit-profile.md`。
- 系统整体健康状况：确定性开发控制和核心认证/主体验证较稳固；当前不能称为已完成生产审计，也不能称为 live compatibility 已闭合。
- 最稳固区域：`/v1`/Admin 鉴权分离、API-key principal 隔离、加密 tool mapping、请求/流生命周期测试、手工 release 禁止自动 push、当前 Codex source contract 的 blocking gate。
- 最高风险区域：Codex compaction 持久化缺少 aggregate quota；已批准的“无 Rosetta 迁移兼容层”与现有 legacy/migration 实现不一致；真实调用 runner 没有机械化 developer-approval gate；preset-only provider 边界尚未在代码/UI 中统一落实。
- 本轮未覆盖的重要风险：真实 Codex/provider/agentabi 行为、生产或内网部署、浏览器/反向代理、Docker runtime、backup/restore、HA/SLO/RTO/RPO、GitHub 远端权限、签名/SBOM/provenance。

## 结论归属

以下归属只说明下一步由谁负责决定或实施，不等于已经授权修复；本轮仍然是“未授权 remediation”。

### 我可以直接修复的逻辑/控制问题

- **AUD-002**：为 compaction replacement 持久化增加单条、每 principal 和全局 row/byte 上限，并补事务性超限与隔离测试。
- **AUD-001**：把 Codex/provider 协议兼容与 Rosetta 内部迁移分开盘点，删除或拒绝不再承诺的内部迁移路径，并补护栏测试。
- **AUD-003**：为所有真实调用 runner 增加 fail-closed 的显式 developer opt-in，并用确定性测试证明未 opt-in 时不会启动外部调用。

### 需要你决定的业务/策略语义

- **AUD-005**：preset provider 是否允许 custom endpoint，以及未知 provider identity 是否必须拒绝。这会改变支持面、凭据出站边界、Admin/config 语义和兼容性承诺。
- **AUD-004**：在首次公网 release 或更强安全声明前，是否采用 digest pinning、SBOM、provenance、signing 等更强 artifact-integrity 基线。当前“手动 release、暂不保证更强能力”是已接受的产品策略，不能由代码审计自行升级。

其余 `No Action`、确定性证据、以及明确排除的运行时项目属于证据状态或范围边界，不是额外待修复结论；不能把它们表述为 live production 或 provider quality 已被证明。

## 需要用户敲定的业务/风险语义

### AUD-005 — preset-only 上游边界是否允许 bundled provider 的 custom endpoint

- 需要决定：上游是否只能使用预设 provider identity，还是允许预设 provider 使用自定义 `base_url`；任意未知 provider identity 是否必须拒绝。
- 选项与后果：
  - 严格 preset identity：缩小 credential egress、测试和支持面，但会失去部分自定义兼容性。
  - 预设 identity + 明确 custom endpoint：保留灵活性，但必须定义 URL/凭据边界并增加一致的 config/UI/egress 测试。
- 建议及证据：当前 `build_provider_info` 对未知/custom 类型使用通用 Bearer 和 `{base_url}/` fallback，Admin UI 公开了 `Custom` vendor；这与已批准 profile 的“预设 provider”表述不完全一致。
- 阻塞的审计/修复范围：AUD-005 的 remediation，以及 provider boundary 的最终 `Fresh` 判定。

其他 profile 语义已由用户确认：仅本机/内网承诺；单 Admin、多 API key、Codex-only downstream、预设 provider upstream、手动 release；不承诺公网账户安全、可用性、数据恢复、HA、backup/restore、RTO/RPO；audit 不允许真实 API 调用；开发 live 测试需开发者逐次批准；当前未上线；不承诺 Rosetta 版本之间迁移兼容层。

## 主要发现

### AUD-002 — Compaction replacement 持久化缺少 aggregate quota

- 分类：必须修复
- 状态：Open；本轮未授权修复
- 影响的质量属性/关键流程：Security、Privacy、Reliability、Cost；SCN-06/SCN-07。
- 触发路径：`codex_compaction.create_compaction_mapping` 将完整 summary 写入 `PersistenceManager.store_codex_compaction_mapping`；表有 rolling 7-day TTL，但没有单行、每 principal 或全局 row/byte quota。
- 影响与风险排序依据：有效 API key 可重复触发；summary 是 prompt/source 相关 plaintext；共享 SQLite 可持续增长；没有 backup/restore 承诺，磁盘耗尽后的恢复边界更弱。相邻 tool mapping 已有严格 quota，因此该差异是具体结构性缺口，不是推测性优化。
- 证据：`docs/audit/runs/20260719-1542/EVIDENCE.md` UNIT-004；`codex_compaction.py:304-326`；`observability/persistence.py:1271-1303`。
- 建议方向：为 compaction replacement 增加 hard max bytes、per-principal/global row/byte quotas，并采用事务性、fail-closed 的 quota accounting；添加超限和跨 principal 测试。
- 修复与验证状态：未修复；未运行真实 compaction summary；当前 focused/full deterministic tests 通过。
- 证据缺口/置信度：High；缺少真实 upstream response size 和长时间磁盘实验，但不影响“缺少 aggregate bound”的源码结论。

### AUD-001 — 内部 migration/legacy 路径与已批准的 no-migration 边界冲突

- 分类：需要规划
- 状态：Open；本轮未授权修复
- 影响的质量属性/关键流程：Modifiability、Correctness、Security、Operability；SCN-06/SCN-08。
- 触发路径：`GatewayConfig` 的 legacy `server.api_key` synthetic entry；local mode 单 key 迁移；Admin key route 迁移；SQLite legacy JSON/schema/mapping migration；pipeline/converter deprecated aliases。
- 影响与风险排序依据：项目尚未上线，没有旧数据迁移义务；保留多套 state/config/API 语义会增加 agent/human 认知负担，并让 secret/history 迁移边界长期存在。当前 Codex/provider wire compatibility 不能与 Rosetta-version migration 混为一谈。
- 证据：`gateway/config.py:756-767`；`gateway/local_mode.py:789-812`；`gateway/admin/routes/keys.py:34-43,81-86`；`observability/persistence.py` 的 `_migrate_*`；`pipeline.py` deprecated aliases；全量 `rg` inventory。
- 建议方向：建立一次性分类表：保留的 Codex/provider protocol compatibility、当前 config、应删除/拒绝的 Rosetta-version migration；移除最后一类，并增加禁止新增未登记 migration path 的护栏。
- 修复与验证状态：未修复；legacy tests 通过只证明当前实现，不证明 profile 一致。
- 证据缺口/置信度：High；完整 protocol-vs-internal 分类表尚未建立。

### AUD-003 — 真实调用 runner 缺少 fail-closed developer-approval gate

- 分类：需要规划
- 状态：Open；本轮未授权修复
- 影响的质量属性/关键流程：Security、Cost、Operability、Verification Integrity；SCN-11。
- 触发路径：`scripts/run_gateway_integration.sh` 或 `tests/live_agent/*/run_live.py` 被 agent/开发者直接调用；live harness 可读取 credentials 并启动真实 Codex/provider 流程；其中一个 isolated config 使用 `approval_policy="never"` 和 `sandbox_mode="danger-full-access"`。
- 影响与风险排序依据：可能产生真实 API 费用、transcript/tool side effects 和 credential exposure；当前 audit 通过 `make test` 排除 integration，因此本轮没有真实调用，但直接 runner invocation 仍是 procedural-only gate。
- 证据：`scripts/run_gateway_integration.sh:21-40,70-82`；`tests/live_agent/context_compaction/run_live.py:23-30,72-90`；`tests/live_agent/deferred_tool_search/prepare_run.py:36-59`；`EVIDENCE.md` UNIT-006。
- 建议方向：所有 real-call runner 增加一次性、明确、无 secret 的显式 opt-in；无 opt-in 时 fail closed；用 deterministic test 证明不会启动 external-call subprocess/client。
- 修复与验证状态：未修复；本轮严格未运行 live/integration。
- 证据缺口/置信度：High；未检查任何真实 credential，也未执行 live trajectory。

### AUD-005 — Preset-only provider 边界未统一落实

- 分类：需要规划
- 状态：Open；等待 profile 细化决定
- 影响的质量属性/关键流程：Security、Modifiability、Operability、Correctness；SCN-09。
- 触发路径：Admin `Custom` vendor / custom variants → config provider resolution → unknown provider fallback → generic URL/auth egress。
- 影响与风险排序依据：Admin 或配置错误可将 provider credential 和 prompt traffic 发往未明确支持的 endpoint；当前不是匿名 SSRF，因为路径受 Admin/config 控制，但支持面与 profile 不一致会造成错误的安全和兼容性承诺。
- 证据：`gateway/providers.py:130-144`；`gateway/admin/admin.html:1310-1323`；`gateway/config.py:402-419`；`EVIDENCE.md` UNIT-007。
- 建议方向：先决定 bundled provider custom endpoint 是否支持；随后在一个 canonical config boundary 统一 reject/allow，并同步 UI、docs、tests。
- 修复与验证状态：未修复；无外部 egress 测试。
- 证据缺口/置信度：High；缺少 owner 对 custom endpoint 语义的最终决定。

### AUD-004 — mutable build inputs / 缺少 artifact provenance（已接受技术债）

- 分类：记录为技术债
- 状态：Risk Accepted；不是本轮修复项
- 影响的质量属性/关键流程：Supply Chain、Security、Operability；SCN-10。
- 触发路径：CI action major tags、Docker `python:3.14.6-alpine` tag、未锁定的 optional dependency/latest SDK resolution、无 signing/SBOM/provenance。
- 影响与风险排序依据：手工 release 与 disabled push 降低当前自动化爆炸半径，但未来外部 tag/index 变化仍可能改变 artifact。
- 证据：`.github/workflows/ci.yml:15-18,52-55`；`.github/workflows/sdk-compatibility.yml:18-31,42`；`docker/Dockerfile:3-5,29-39`；`pyproject.toml`；`EVIDENCE.md` UNIT-005。
- 建议方向：在首次 public release 或更强 security claim 前定义 digest pinning、dependency constraints/lock、SBOM、provenance/signing 和 owner。
- 修复与验证状态：当前 risk accepted；本地 lint/test/build/contract/tag gates 通过。
- 证据缺口/置信度：High；GitHub 远端 settings、签名服务和 registry 状态不可用。

## 本轮已修复

无。本轮明确未授权 remediation；没有 finding 被标记为 resolved/closed。

## 审计范围与抽样依据

- Always-on critical：Gateway auth/Admin/principal scope；Codex Responses routing；SSE/tool/compaction；persistent state/redaction/retention；manual release/Codex gate；agent live-call boundary。
- Changed/high-churn：Codex alpha.23 contract/catalog、compaction、deferred MCP/tool dispatch、live-agent contracts、auth/headers、model/provider config。
- Invalidated dependency cones：旧 20260709–20260711 快照因 current head、profile、Codex contract 和缺少 durable ledgers 而不继承；相关 coverage 重新从 Unknown/Invalidated 建立。
- Rotating deep slices：non-Codex converter/provider breadth、optional web/search/image sidecars、CI/Docker supply chain。
- Incident/finding/debt follow-up：无用户提供的 incidents；本轮发现 AUD-001/002/003/005，记录 AUD-004 accepted debt。
- 排除范围及原因：真实 API、生产/内网部署、公网账户安全、backup/restore/HA/SLO/RTO/RPO、外部 GitHub settings、完整 provider matrix；原因均已写入 `SCOPE.md`。

## 场景与质量属性验证

| 场景 | 属性 | 预期响应 | 证据/结果 | 缺口 |
| --- | --- | --- | --- | --- |
| SCN-01 invalid `/v1` key | Security | fail closed，不解析/转发 | AuthState/source + focused/full tests；Satisfied (deterministic) | 无 live reverse-proxy probe |
| SCN-02 two-key state isolation | Security/Privacy | 不跨 principal replay | state scope/AAD/SQL + persistence tests；Satisfied (sampled) | 无部署压力测试 |
| SCN-03 Codex route/conversion | Correctness | preserve request/response contract | converter/proxy tests + source contract；Satisfied (deterministic) | live provider/model behavior |
| SCN-04 stream EOF/tool/usage | Reliability/Correctness | ordered terminal stream and cleanup | stream/lifecycle tests；Satisfied (deterministic) | real provider timing |
| SCN-05 tool localization/replay | Correctness/Security | exact owner-scoped tool identity | tool/persistence tests；Satisfied (deterministic) | live MCP/plugin trajectory |
| SCN-06 compaction/resume | Correctness/Reliability | valid mode, owned token, bounded store | trigger/summary tests pass; quota invariant Not Satisfied | live summary and aggregate quota |
| SCN-07 repeated large state | Reliability/Cost | bounded retention/cleanup | logs/tool mappings bounded; compaction bound gap confirmed | long-run disk test |
| SCN-08 Admin mutation | Security/Operability | single Admin, atomic invalid-config behavior | Admin/config/session tests；Satisfied (deterministic) | browser/LAN deployment |
| SCN-09 provider boundary | Security/Modifiability | explicit reject/allow policy | code/UI shows policy gap；Unknown | owner decision and egress tests |
| SCN-10 release | Supply Chain/Operability | manual current-source release gate | lint/test/direct wheel/contract/tag pass | remote settings/provenance/signing |
| SCN-11 agent external call | Security/Cost | audit no calls; dev call needs approval | deterministic separation pass; gate Not Satisfied | no live trajectory |

## 仓库、运行和发布证据

### 已检查

- 仓库状态和差异：`main@0caa7a1`，ahead 4，审计文件外无用户工作树改动。
- 数据/迁移/恢复：SQLite schema、WAL/permission、redaction、request/error retention、encrypted mappings、compaction mappings、legacy migration paths。
- 权限和信任边界：`/v1` API key、single Admin、Admin session/CORS、internal token、provider credential egress、principal scope、untrusted tool/provider content。
- 发布/回滚/配置：JSONC/env substitution、atomic write、manual tag gate、disabled push targets、Docker/Compose current-wheel build。
- 可观测性和事故恢复：request/error/stream traces、metrics、health/readiness、Admin diagnostics；没有 production alert/restore drill。
- 依赖/构建/供应链：pyproject optional deps、CI action tags、Docker base tag、Docker secret check、manual wheel build、SDK monitor。
- Agent/harness/tooling：CodeGraph、deterministic live contract fixtures、integration/live runners、isolated credential paths、approval-policy configuration。

### 已运行检查

| 命令/流程 | 结果 | 限制 |
| --- | --- | --- |
| `conda run -n llm-rosetta make lint` | 通过 Ruff、format、ty、complexipy | local only |
| `conda run -n llm-rosetta make test` | `3425 passed, 5 skipped, 11 warnings` | excludes `tests/integration`; no real API |
| focused critical pytest set | `533 passed` | deterministic/fake/local only |
| `conda run -n llm-rosetta make check-codex-compat` | 通过；source commit `655224ffae098a85efeddf8289171ff3bd2624d1`；无 blocking changes | 11 semantic rows remain `Possibly unchanged` |
| `conda run -n llm-rosetta python scripts/check_release_version.py --tag v0.144.0.r0` | 通过 | no GitHub publication |
| `conda run -n llm-rosetta python -m build --wheel` | 通过，生成 `codex_rosetta-0.144.0.post0-py3-none-any.whl` | direct build used because Makefile clean scans historical audit tree and did not complete |
| `git diff --check` | 通过 | ignored audit files not in diff |
| `codegraph explore` | current gateway/auth/persistence/route/control paths mapped | dynamic runtime behavior remains separate |

### 未运行或不可获得

| 证据 | 原因 | 剩余风险 | 所需负责人/动作 |
| --- | --- | --- | --- |
| 真实 Codex/provider/agentabi | 用户禁止 audit 真实 API 调用 | live model/tool/stream behavior unknown | developer-approved development run outside audit |
| 生产/内网 deployment | 当前尚未上线 | effective exposure, logs, metrics, rollback unknown | first internal deployment owner |
| Docker/Compose runtime | 本轮未启动 daemon/sidecar | runtime user/network/health behavior unknown | local/LAN deployment smoke |
| backup/restore/HA/SLO/RTO/RPO | 明确不承诺 | recovery behavior unknown | only when profile changes |
| GitHub remote permissions/settings | local checkout unavailable | action pinning/branch protection may differ | owner-authorized GitHub inspection |
| SBOM/signing/provenance | current profile has no guarantee | artifact integrity debt | before public/stronger release claim |

## 覆盖新鲜度更新

详见 `docs/audit/COVERAGE.md`。本轮主要变化：

- `AUTH-01/AUTH-02`、`DATA-01/DATA-02`、本地 `REL-01/REL-02`：`Unknown → Fresh`（当前 source + deterministic evidence）。
- `CODEX-01/CODEX-02/STREAM-01/TOOL-01`：对确定性路径为 `Fresh`，live/semantic uncovered rows 保持 Unknown/partial。
- `DATA-03`、`AGENT-01`、`GOV-02`：`Unknown → Invalidated`，分别对应 AUD-002、AUD-003、AUD-001。
- `SUPPLY-01`：`Unknown → Stale/Unknown`，由 AUD-004 accepted debt 和远端证据缺口导致。
- `PROVIDER-01`：`Unknown → Invalidated`；源码/UI 已确认当前 surface 超出 profile 的 preset-only 表述，AUD-005 决策未闭合。

## 技术债和持久护栏

- 到期/触发的技术债：AUD-004 在首次 public release、production deployment 或更强 artifact-integrity claim 前必须重新审视。
- 新的 golden principle candidate：
  - `GP-001`：real-call runners must fail closed without one-shot developer-approved opt-in。
  - `GP-002`：every durable state store must define owner scope plus aggregate byte/row/TTL bounds。
- 建议新增的 lint/test/generator/CI/doc control：
  - live/integration runner 的 no-opt-in no-network test；
  - durable-store quota contract tests；
  - legacy/migration inventory check against approved compatibility ledger；
  - provider preset/custom source-of-truth validation；
  - release provenance/SBOM/signing gate（在 profile 提高承诺后）。
- 可安全删除/收缩的复杂度：优先清理 AUD-001 中未批准的 Rosetta-version migration/legacy paths；不要为了减少代码量删除 Codex/provider protocol compatibility、security controls、retention、migration safeguards 或 meaningful tests。

## 假设、人工复核与下一轮重点

- 假设：用户的“不保留兼容迁移层”指 Rosetta 版本之间的 config/persistence/internal API，不等于删除当前 Codex/provider wire compatibility。
- 需要人工复核：AUD-005 custom endpoint 语义；首次内网部署的反向代理/浏览器/日志/权限；未来是否升级 release provenance、SBOM、signing 承诺。
- 下一轮优先范围：AUD-002 quota remediation targeted re-audit；AUD-001 migration inventory/removal；AUD-003 fail-closed live-call gate；AUD-005 provider boundary decision。
- Full-baseline reset 是否触发：本轮已经是 `Reset Baseline`；下一次只有在运行时/部署、身份/数据模型、Agent platform 或风险承诺再次发生重大变化时重置。

## 风险排序依据

AUD-002 排在最高：当前支持的 compaction 路径可写入 prompt-derived plaintext，存在明确的 aggregate bound 缺口，且共享本地/LAN SQLite 无恢复承诺。AUD-001 次之：用户已明确取消 Rosetta-version migration 义务，但实现仍保留多处 active fallback，系统性影响维护和安全边界。AUD-003 影响真实调用费用、凭据和验证完整性，但 audit 本轮已避免实际调用。AUD-005 目前受 Admin/config 控制，主要是支持边界和 credential-egress policy 不一致。AUD-004 因手工发布和 disabled push 降低当前爆炸半径，按已接受的供应链技术债记录。

维护性判断：本轮只新增审计控制面和证据账本，未改变生产代码；系统仍由 core/IR、gateway/proxy、observability/persistence、compatibility 和 release/agent 各自负责。主要结构性维护风险是 legacy/migration 分支与大型 gateway coordinators 的认知负担；下一轮应先做 AUD-001 的边界分类和 AUD-002/AUD-003 的最小控制，而不进行无边界重构。
