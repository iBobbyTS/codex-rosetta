# Codex-Rosetta 代码库审计报告

审计时间：2026-07-09  
修复完成：2026-07-10  
审计画像：`.agent-work/audit/PROFILE.md`（`Draft`）  
完整账本：`.agent-work/audit/20260709-2336/FULL.md`

## 审计验证

- 仓库状态已检查：是。`master` 相对 `origin/master` ahead 1，当前 HEAD 为 `eb94742`；无 staged diff。
- 差异已审阅：是。修复完成后，当前 unstaged tracked diff 涉及 76 个文件、3,819 行新增、952 行删除，另有 17 个 untracked 文件；也检查了 ahead commit 的范围和工具目录实现。当前仍是大幅 dirty snapshot，不能据此声称 release-ready。
- 审计范围与抽样依据：按 Draft profile 重点覆盖 Codex-facing Responses 入口、认证/CORS、Admin、配置持久化与热更新、跨请求 state scope、tool localization、stream 生命周期、redaction/SQLite、CI/Docker、版本兼容与发布路径；未审阅 `_vendor/**`，遵守仓库禁止直接修改 vendored code 的规则。
- 关键质量属性：正确性与可靠性最高，其次是凭据/诊断数据安全、可运维性、兼容性与可维护性。
- 已运行测试：
  - `conda run -n llm-rosetta make lint`：通过，Ruff lint/format 与 `ty check` 均通过。
  - `conda run -n llm-rosetta make test`：通过，`2451 passed, 4 skipped, 9 warnings`，本机 Python 3.14.6。
  - health/config 定向测试：`52 passed`。
  - redaction/persistence/tool-adaptation 定向测试：`93 passed`；最终的 restart/proxy replay 两条回归也通过。
  - `make check-codex-compat`：通过，sibling source commit `2e8c3756f95789c215d9ea9a5ade6ec377934b3f` 未出现阻塞 contract 变化。
  - `conda run -n llm-rosetta make check-release-version RELEASE_TAG=v0.144.0.r0`：通过。
  - `git diff --check`：通过。
  - `codegraph sync`：通过，同步 1 个变更文件、38 个节点。
- 未运行测试：需要 API key 的 integration/agentabi/live Codex matrix、Docker build/image scan、Python 3.10/3.13 本地 clean-wheel smoke、SBOM/签名、真实 release/rollback 演练。
- 已检查高风险流程：gateway access key、Admin token/login rate limit、CORS、upstream header allowlist、配置 CAS/rollback、principal/window state isolation、持久化 tool mapping、stream EOF/error/cancel finalization、错误诊断与 trace redaction。
- 已检查发布/回滚/观测/恢复路径：本地 version/contract gate 和手工 release 文档已检查；当前发布仍依赖人工执行，未验证 GitHub branch protection、artifact provenance 或恢复演练。
- 假设：health route 在 gateway 对外绑定或经反向代理暴露时可被未认证调用；`gateway.db` 通常为 owner-only，但共享 volume、备份和多用户主机会提高其敏感数据风险。
- 需要人工复核：确认正式 threat model、数据目录备份策略、SLO、漏洞响应、签名/SBOM 和 manual release 接受标准。health 与 mapping 的 token-only 合同已按本轮明确语义实现，不再等待业务选择。
- 已知过时上下文或冲突证据：本机 `codex-cli 0.144.1`，而 package/report 目标为 `0.144.0.r0`；二者不能混作同一个兼容性证据。仓库 upgrade report 已明确标记 `Pending / not approved`，本审计不改变该结论。

## 主要发现

### 已解决：公开 health endpoint 的 token 泄露

原缺陷是 `MetricsCollector.record_request()` 将完整 `error_detail` 写入 provider `last_error`，免鉴权的 `/health` 与 critical 状态的 `/health/ready` 会原样返回 token。修复后：

- `MetricsCollector` 在 ingestion 时按 token-only 规则脱敏，避免新的 raw token 进入内存。
- 新增 `src/codex_rosetta/gateway/health.py`，集中构造 public health/readiness payload，并在 presentation 时再次使用当前运行时 redactor，防护热更新前或旧内存值。
- 配置热更新会与 auth、stream trace、persistence、CORS 一起 prepare/commit metrics redactor，避免部分激活。

路由级回归向 `/health` 和 `/health/ready` 注入原泄露形状，确认 Bearer 值与配置 token 均替换为 `[REDACTED]`。provider 名、email/PII、prompt、普通 `password`/`secret`/`client_secret`/proxy password 与其他错误正文保持原样，这是本轮明确接受的公开信息合同。

该项已有 ingestion、presentation、config hot reload 三层行为测试，最终 lint/type 与全量测试通过，当前状态为 resolved。

### 已解决：持久化 tool-call mapping 的 token 明文

原缺陷是 `_persist_tool_mapping()` 将 localized/native tool call 直接写入 SQLite，绕过 `PersistenceManager.redact_sensitive()`。修复后：

- `PersistenceManager.upsert_tool_call_mapping()` 在序列化前同时脱敏 `original_tool_call` 与 `codex_tool_call`。
- `SecretRedactor` 会识别 encoded `function.arguments` JSON 内的 token/API-key/Authorization 字段；不含 token 的 encoded arguments 保持字节一致。
- 当前 raw Codex history 只在“匹配副本”上应用同一 redactor，再与 persisted mapping 比较；原 history 不被改写。
- 命中后的 localized replay 在原 token 位置使用 `[REDACTED]`，其他命令、文件内容、参数、email/PII、prompt、普通 password/secret/client_secret/proxy password 全部保留。

SQLite 原文测试确认 configured token、Bearer 值和 encoded API-key 字段不再出现，同时 email 与普通 password/secret 仍在。restart 测试关闭并重开 `PersistenceManager` 后，已脱敏 mapping 仍能匹配 raw history；gateway 非流式完整路径也验证了 cache/history continuity。

该项当前状态为 resolved。完整 replay payload 仍按用户确认的合同保留；本轮没有扩大为全字段 secret scrub、加密、持久化 opt-in 或新的清理策略。

### 接受的技术债：gateway 核心协调器继续跨职责膨胀

当前 `gateway/app.py` 约 983 行、`gateway/proxy.py` 约 2,655 行、`gateway/tool_adaptation.py` 约 1,524 行、`observability/persistence.py` 约 1,118 行。风险不只来自行数：

- `app.py` 仍拥有 telemetry、stream wrapper、request routing、后台清理、auth、CORS 和 lifecycle，但 public health/readiness presentation 已拆到 `gateway/health.py`。
- `proxy.py` 同时拥有 conversion orchestration、错误翻译、mapping persistence、metadata/deferred-tool cache、search bridge、SSE/trace 和 transport 流程。
- mapping 修复复用了既有 `PersistenceManager` redactor，没有再引入平行安全抽象。

本轮接受剩余结构债，不做大重写。后续触发条件是 stream telemetry、tool-mapping repository 或 deferred-tool search 再增加非局部行为，开始支持多进程部署，或同一职责出现第三个实现；届时再在现有 regression tests 下小步拆分。

### 记录为技术债

- Provider metadata 与 deferred tool catalog 仍是单进程内存状态；gateway restart 或多 replica/load-balanced request 可能丢失 thought signature 或 deferred discovery continuity。是否需要共享/持久化取决于正式 deployment topology。
- Error diagnostics 仅按条数限制，没有按年龄或总字节数清理；英文/中文 security guide 已明确披露，需由 owner 确认是否满足数据治理要求。
- Manual GitHub Release 没有 repository-enforced promotion/signing gate；当前由人工执行本地 lint/test/contract/tag 检查。Draft profile 尚未定义 provenance、signing 与 SBOM 基线。

### 无需处理

- 当前 access-key principal isolation、Admin token、bounded login limiter、same-origin/exact-origin CORS、upstream header allowlist 的实现和测试与现有风险画像一致。
- 配置写入具备 private mode、CAS lost-update detection、backup、atomic replace、activation rollback 和 app-scoped hot reload；未发现新的阻塞性正确性问题。
- Responses namespace/custom tool typing、stream telemetry lifecycle、bounded phase buffering 与 state-root cleanup 的自动测试均通过；但这不替代 upgrade report 中仍缺失的 live Codex/API matrix。

## 整体健康度

系统当前自动化测试和静态验证较强，配置安全默认值、原子持久化、principal/window 隔离、stream 终态处理，以及新补齐的 health/mapping token 边界是最稳固的部分。本轮确认的两个安全问题均已修复，没有剩余“必须修复”项。主要剩余风险是结构与部署技术债：大型协调器、多 replica 状态连续性、count-only error retention，以及人工 release provenance。下一轮建议优先补真实 Codex/API matrix，并在明确部署拓扑后复核 multi-process continuity。

## 风险排序依据

排序先看未认证可达性、API token 影响、爆炸半径和证据强度，再看发生概率、可逆性、系统性与修复成本。health finding 可被直接复现且无需认证，因此最先修复；tool mapping 需要 data-dir/backup 访问，但存在明确明文 token 证据，因此同轮修复并增加 restart continuity 测试。协调器膨胀主要影响未来变更安全和审查成本，不是当前运行时故障，故按明确触发条件接受为技术债。

本轮已完成审计、两项安全修复、定向与全量验证、CodeGraph 同步和账本更新。未 commit、push、创建 PR、release 或 deploy；upgrade report 仍为 `Pending / not approved`。
