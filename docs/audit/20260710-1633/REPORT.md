# Codex-Rosetta 第 19 轮代码审计报告

结论：**第 19 轮 Must Fix 已解决并验证，当前没有未关闭的本轮 finding。** 转换型 upstream 的 malformed SSE `data` 不再进入 warning/body log，也不会被静默丢弃后继续成功；transport 会只关闭一次 upstream，并抛出正文无关的 typed protocol error。converted、web-search、outer telemetry 统一产生一次稳定的 502 类失败终态；direct Responses raw passthrough 按既有架构继续逐字节转发，只执行 wire-size envelope。

## 修复结果

- 新增并导出 `UpstreamProtocolError`，固定消息为 `Upstream SSE data is not valid JSON`，不包含 raw `event.data`、JSON parser repr 或 exception chain 中的正文。
- `HttpUpstreamStream` 保留 SSE comment/keepalive、空 `data:`、`[DONE]` 和合法 JSON 的现有语义；其他非空 data 会立即 fail closed，后续 event 不再 yield。
- stream close 改为幂等；正常完成、malformed protocol error、HTTP error body 预读、重复显式 close、parsed/raw cancellation、limit error 与 outer context cleanup 都只关闭一次底层 response。
- outer `_InstrumentedStream` 只写一次 metrics/request-log 502；第二次读取不会把 EOF 再标成成功。converted 与 web-search stream trace 也各自只写一个 `stream_outcome=error` terminal record。
- direct OpenAI Responses streaming 仍走 raw passthrough，不解析 event JSON；malformed JSON bytes 原样转发且仍受 line/event wire budget 限制。
- 复核全部 runtime `JSONDecodeError`/malformed SSE/event data sink，没有发现第二个会记录 rejected SSE 正文的生产路径。
- 中英文 `gateway-security.md` 已同步记录 converted fail-closed 与 direct raw passthrough 边界。

## 安全与正确性回归

- configured token、Bearer token、prompt text、plain password 四类 malformed payload 均不出现在普通或 body logger capture 中。
- client/exception 可见内容只有稳定错误，不含 upstream event 正文；后续合法 event 不会被消费或下发。
- request log、metrics、stream profile、stream trace 都只有一次失败终态，不会在后续 EOF 重复记成功。
- normal JSON、SSE comment、empty data、`[DONE]` 和 direct raw passthrough 语义均有回归覆盖。

## 验证结果

- 扩展定向：**55 passed**，包含 close-on-cancel 强化覆盖。
- `make lint`：通过，包含 Ruff check/format（294 files）和 `ty check`。
- `make test`：**2,752 passed, 5 skipped, 9 warnings**。
- `make build`：成功生成 sdist 与 wheel。
- `make check-codex-compat`：通过，Codex source `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`，`Changed: None`。
- `make check-release-version RELEASE_TAG=v0.144.0.r0`：通过。
- 隔离 Compose malformed-SSE smoke：当前 wheel 构建的 Gateway 报告 `0.144.0.r0`；client 在 HTTP 200 stream header 后收到连接终止且没有下游正文（stream header 已先提交，无法改写 HTTP status），container 普通/body logs 中没有 configured token、Bearer、prompt、password 或后续 event；SQLite 只有一条 status 502，`stream_complete=false`、`stream_outcome=error`、stable error。临时 container/network/image/fake upstream 已清理，其他 Docker workload 未触碰。
- 最终 repository reality check：`git diff --check` 通过；`master` 仍领先 `origin/master` 1 个 commit，保留原有 unstaged/untracked 审计工作树，无 staged diff；`.agent-work/audit/CURRENT.md` 不存在。
- `codegraph sync`：通过（`Already up to date`）。

## 未运行与剩余边界

- 未运行带凭证的真实 provider/Codex/agentabi、外部 GitHub Actions、生产 deploy/rollback、backup/restore、漏洞/许可证/SBOM/签名。
- audit profile 的 owner、privacy/legal、ASVS、SLO/error budget、incident response 与 supply-chain governance 仍未批准。
- 本轮没有 commit、push、PR、release 或 deploy。

维护性判断：修复集中在现有 HTTP/SSE transport protocol owner，复用现有 outer telemetry；没有新增第二套 parser、跨层 redactor 或平行状态机。typed error、幂等 close 与 direct/raw 边界均有回归，无需后续清理重构。
