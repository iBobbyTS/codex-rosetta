# Codex-Rosetta 第 20 轮代码审计报告

结论：**本轮原有 2 个“必须修复” finding 已全部解决，没有剩余开放 finding。** 修复集中在 Admin control-plane 的 app ownership 与 model-test retained-memory boundary，没有扩散到主 proxy/converter，也没有提交、推送、发 PR、release 或 deploy。

## 审计验证

- 仓库状态已检查：是。当前仍为含大量用户工作的大型 uncommitted working tree；本轮保留了所有既有改动，没有 reset、revert、stage、commit、push、release 或 deploy。
- 差异已审阅：是。重点回看 `gateway/admin/runtime.py`、Admin auth/testing route、`setup_admin()`、Gateway shutdown、bounded auxiliary transport、两 app/hot-reload/lifecycle tests 和双语安全文档；同时复核原审计覆盖的 ingress、proxy/stream、persistence、observability、converter、Docker/release 路径。
- 审计范围与抽样依据：按 Draft profile 将正确性、可靠性和安全排在最前；对两个 finding 从 route 入口追到 owner、锁、byte/count accounting、cancel/TTL/shutdown 和 HTTP reader，再以 unit、route、full-suite、wheel 与 Compose 分层验证。
- 已运行定向测试：最小 repair group **57 passed**；扩展 Admin/transport/app/lifecycle group **243 passed, 1 skipped**。
- 已运行完整测试：`make test` 为 **2765 passed, 5 skipped, 9 warnings**。
- 已运行静态门禁：`make lint` 通过 Ruff、296 files format check 与 `ty check`；`git diff --check`、`git diff --cached --check` 通过。
- 已运行构建/合同门禁：`make build` 通过；`make check-codex-compat` 通过，source commit `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`、`Changed: None`；`make check-release-version RELEASE_TAG=v0.144.0.r0` 通过。
- 已运行版本 smoke：Python 3.10.20 与 3.13.2 均从生成的 `0.144.0.post0` wheel 成功 import/运行新的 Admin runtime，输出 `admin-runtime-wheel-smoke-ok`。
- 已运行 Compose smoke：隔离 project 中两个 Gateway 与一个 >4 MiB upstream 均来自当前本地 wheel image。超限 task 返回稳定 502 且没有 partial body；同 task ID 从另一 Gateway poll 为 404；app A 锁定后返回 429，app B 正确密码仍返回 200。创建的 container、network、image、config 和 database 已全部清理。
- CodeGraph：`codegraph sync` 成功，报告 index 已是最新。
- 高风险流程：已检查 auth-before-body、Admin login/task、跨 app ownership、request/window cleanup、stream cancellation/finalization、encrypted mapping AAD/quota、redaction/retention、URL-image SSRF/DNS/worker、HTTP body/SSE limits。
- 发布/回滚/观测/恢复：本地 release/Codex gates、config/persistence compensation、request/error/stream/body observability 已抽样；未执行外部发布、生产 deploy/rollback 或 backup/restore drill。
- 未运行：带凭证的 provider/Codex/agentabi、真实浏览器 Admin、外部 GitHub Actions、漏洞/许可证/SBOM/签名、生产负载、真实恶意 DNS/proxy。
- 假设与人工复核：Draft profile 的 owner、privacy/legal、ASVS、SLO/error budget、incident response、dependency/signing/SBOM，以及最终生产部署模型仍需项目负责人定义。

## 主要发现

### 已解决 F-01：Admin mutable state 跨越 app 鉴权边界

`AdminRuntimeState` 现在由每次 `create_app()` 独立创建，统一持有 `AdminLoginLimiter` 与 `AdminTestTaskStore`。Admin login、task start/poll/cancel/cleanup 全部从 `request.app` 取得 owner；config hot reload 不会替换 owner；shutdown 只取消、等待和清空当前 app 的任务。原来的 `_login_failures` / `_test_tasks` module-global mutable request state 已删除。

回归证据覆盖：app A 连续失败不会锁 app B；跨 app GET/cancel 一律 404；cleanup、capacity、TTL 与 shutdown 不会影响另一 app；两个 `create_app()` 的 runtime/limiter/store identity 均不同；hot reload 保留原 owner；threaded limiter 的 200 次更新保持原子。

### 已解决 F-02：Admin model-test 只有 count bound、没有 memory bound

Admin self-call 的成功与错误 response 都显式使用 **4 MiB** 增量读取上限，在完整 `json.loads` 前拒绝超限内容。长期保存的是 bounded JSON bytes，而不是展开后的 Python object；GET 只临时 decode。每条 retained record（含 metadata）上限 **4 MiB**，每个 app 的 completed payload 总预算 **32 MiB**，record count 仍为 **128**；running task 计入 count、不计入 completed bytes。锁内原子收敛只驱逐本 app 最旧的 completed task，绝不驱逐 active task。

边界验证覆盖 exact 4 MiB 成功与 4 MiB+1 失败、稳定 502/no partial body、单 task 507、32 MiB oldest eviction、active preservation、128 active/no completed、normal/error/cancel/TTL/eviction byte accounting，以及 aggregate 小到连 compact diagnostic 都放不下时仍不会出现负记账。

### 记录为技术债：外部发布与治理证据仍不完整

本地 lint/test/build/contract/wheel/Compose 路径健康，但 audit profile 仍为 Draft，真实 provider/Codex/agentabi、生产 backup/restore、外部 CI、漏洞/许可证/SBOM/签名和生产负载证据仍缺失。版本兼容报告的外部/manual 项仍应按其原状态处理，本轮没有扩大兼容结论。

### 无需处理：vendored HTTP/SSE provenance 已复核

本轮没有修改 `_vendor/**`。第 10/12/18 轮已记录 zerodep upstream baseline、dirty-patch hash、patch tests/version bump、官方 re-vendor 与 normalized source equality；第 20 轮再次确认 `httpclient`、`httpserver`、`sse` normalized SHA-256 匹配，因此没有 vendor provenance finding。

## 整体健康状况

主 Gateway 的 request/state/persistence/transport owner 继续稳定，Admin control plane 现在也具备与其一致的 app ownership 和明确内存预算。两个 finding 都用一个 app-owned runtime boundary 收敛，没有引入第二套 cache 或把 app ID 散布到 route 字典中。下一轮建议把注意力放在真实 provider/agentabi、生产备份恢复、外部 CI/supply-chain 与容量证据，而不是继续扩展本次已闭合的局部 owner。

## 风险排序依据

F-01 原按跨鉴权边界的数据/控制面影响、可重复性和系统性列为必须修复；F-02 原按 OOM 爆炸半径、坏 upstream 的可触发性和明确容量算术列为必须修复。两项现均有代码、边界测试、两 app lifecycle test、wheel 与 Compose 证据支持，因此降为“无需处理”。剩余 governance/release gaps 没有新的运行时缺陷证据，继续记录为技术债。

维护性判断：修复边界清晰，新增复杂度集中在一个 app-owned Admin runtime；auth/testing route 退化为薄 HTTP adapter，预算与状态机由单一 owner 管理，测试覆盖完整，当前不建议追加清理重构。
