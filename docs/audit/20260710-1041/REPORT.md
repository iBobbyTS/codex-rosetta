# Codex-Rosetta 第 11 轮代码审计修复报告

审计时间：2026-07-10 10:41 America/Edmonton

本轮发现的 4 项问题均已修复并完成回归，没有 commit、push、PR、release 或 deploy。此前已接受的 public-health token-only 内容合同、count-only 诊断保留、manual release provenance 和 web-search 总调用/时间/费用预算债务没有被重新包装成新问题。

## 审计验证

- 仓库状态与大型未提交差异已检查，用户工作均已保留。
- `make lint` 通过：Ruff check、format check、ty check 全绿。
- `make test` 通过：`2677 passed, 4 skipped, 9 warnings`（Python 3.14.6）。
- 新增专项回归先后通过 `196 passed`；最后的原子预算调整后相关子集为 `186 passed`。
- `make check-codex-compat` 通过：Codex source `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`，Changed: None。
- `make check-release-version RELEASE_TAG=v0.144.0.r0` 通过。
- Compose smoke 使用当前 checkout wheel 构建 `codex-rosetta-gateway-local:0.144.0.r0`，隔离容器内 `/health` 返回 `status: ok`，CLI 报告 `0.144.0.r0`；未占用或停止宿主现有 8765 gateway。
- 未运行真实 provider/API/agentabi、远端 GitHub Actions、backup/restore、漏洞/许可证和 release/deploy/rollback；本轮修复不据此扩大兼容性声明。
- 未触发 Py3.10/3.13 wheel 条件：没有修改 package metadata、public typing 或 Python 版本合同；Compose wheel build 已通过。

## 已解决发现

### F-01：`x-request-id` 与 request-local state identity 已分离

无 window 请求现在由 `GatewayStateScope.for_request()` 生成不可复用私有 nonce；外部 `x-request-id` 只用于 trace、upstream allowlist 和 response。非流式 normal/error 与流式 normal/error/close/cancel 终态都会清理 request-local provider metadata、tool localization 和 deferred-tool state；真实 `x-codex-window-id` scope 保持跨请求连续性。

回归覆盖同 principal/provider/model 复用 request ID 的顺序/并发双请求隔离、真实 window 连续性及所有 stream cleanup 终态。

### F-02：`WindowToolSearchStore` 已增加原子资源预算

现有 store owner 统一维护共享锁、per-scope tool count/bytes 和 global bytes：每 scope 最多 1,024 个嵌套工具、16 MiB canonical UTF-8 JSON，全 app 最多 64 MiB。deferred 与 discovered batches 会联合预检，候选 payload 在任何 TTL/scope eviction/replacement 前完成 bounded materialization；超限不修改旧状态、不截断历史，稳定返回 413 capacity error。

回归覆盖跨请求累计、same-name replace、Unicode bytes、多 scope/global、并发写入、TTL、既有 scope-count eviction、clear 和 combined-batch 原子拒绝。

### F-03：辅助 outbound HTTP 已复用主 response safety envelope

新增的 Gateway bounded auxiliary helper 直接复用主 transport success/error limits 与 incremental reader，强制 identity encoding，并在 overflow/cancel 时关闭连接。Tavily、Admin network diagnostics、provider model discovery 和 model testing 均已接入；检索确认没有剩余的 Gateway 非流式 `AsyncClient` 聚合绕过点。

真实 loopback 覆盖正常 JSON、Content-Length、chunked、EOF、compressed response、timeout 和 cancel；错误正文只保留 bounded/truncated 诊断。

### F-04：tool mapping TTL 已由共享 validator 严格验证

默认 24h 不变；统一要求 finite、非 bool 且 `0 < ttl <= 720h`。raw/env config 在 `GatewayConfig` startup fail-fast，Admin 非法值返回 400 且不写文件，runtime helper 不再二次宽松解析；`NaN`/Infinity 无法进入非标准 JSON 或延迟到 `timedelta` 才失败。

回归覆盖 env/string/bool、NaN、Infinity、`1e999`、超大有限值、720 边界及 Admin no-write 行为。

## 整体判断

第 11 轮四项 runtime finding 已有可见修复和回归证据，当前归类为“无需处理”。实现均扩展现有 state scope、`WindowToolSearchStore`、HTTP transport reader 和 config validator owner，没有新增平行服务或大范围重写 coordinator。兼容性 ledger/checklist 已同步新增的 identity、budget、bounded HTTP 和 TTL 自动化合同。

维护性判断：模块 ownership 仍清晰；主要新增复杂度集中在 `WindowToolSearchStore` 的共享预算账本，但以单 owner、原子 mutation 和并发/生命周期测试约束，不建议另做拆分。
