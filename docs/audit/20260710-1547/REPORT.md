# Codex-Rosetta 第 18 轮代码审计报告

审计与修复时间：2026-07-10 15:47–16:30 America/Edmonton  
审计画像：`.agent-work/audit/PROFILE.md`（`Draft`）  
完整台账：`.agent-work/audit/20260710-1547/FULL.md`

结论：**第 18 轮确认的 pre-auth 入站 DoS finding 已解决，本轮不再有未处理的运行时 finding。** HTTP parser 现在对 request line、headers/trailers、body 和并发 parser 都有明确上限；受保护的 `/v1` 与 Admin API 会在读取 body 前认证。修复落在 upstream owner 后通过正式 `zerodep --local update` 流程 re-vendor，没有直接手改 `_vendor/**`。

## 修复结果

- Upstream `httpserver 0.2.3` 分别执行 5 秒 request-line、10 秒 header/trailer、30 秒完整 body 的 monotonic deadline。
- Headers/trailers 继续执行 100 fields、64 KiB（包含 framing）的上限；有效 Gateway 请求 body 上限继续为 50,000,000 bytes。
- 每个 `App` 最多允许 64 个并发 request parser；第 65 个连接不等待，立即返回 HTTP 503。
- `App.before_body()` 在 bounded headers 后、body 前运行。Gateway 将同一个 auth hook 注册到 `before_body` 和 `before_request`：真实 socket 只认证一次，直接 `_dispatch` 测试仍有 fail-closed fallback。
- Early 401 会经过 after-request hooks，因此 `/v1` wildcard CORS 和 Admin allowlist CORS 保持原语义。Admin login/auth-check 与浏览器 `OPTIONS` 仍公开，但其 body 同样受 deadline、byte cap 和 parser capacity 保护。
- Parser slot 在正常、early response、parser error、disconnect 和 cancellation 路径均释放；连接关闭会等待 `wait_closed()`。

## Upstream 与 re-vendor 证据

- Upstream HEAD：`fb84dd10ca736129f937740e44a485034b51258b`。
- 修复前既有 dirty patch SHA-256：`ab6a13fbf883cce898ad34ccf10dd75c801740a0fa922ccc83acf17110da8639`。
- 修复后完整 dirty patch SHA-256：`0c31e3037b22b413b44ced49e17efb759cc498a2c4aa736d2363604d44b8c3fa`。
- 正式命令：`python zerodep.py --local update httpserver --no-deps --dir .../src/codex_rosetta/_vendor`。
- 仅规范化 CLI 管理的 note header 后，upstream/vendor 完全一致；双方 SHA-256 均为 `1489f17beb816ff72a353a4c5a16ddb0998da37c2673ca1b30b09af2da174d73`。
- Upstream Ruff、format、source-only `ty`、78 项 correctness、`dep-check httpserver`、`make lint`、`version-check` 均通过。
- Upstream pre-commit 的 Ruff/format/ty 通过；唯一失败是本轮开始前已存在的 dirty `httpclient/conftest.py::_HttpBinHandler::do_GET` complexipy finding，本轮未扩大范围处理。

## 主仓验证

- 新增真实 Gateway raw-socket 覆盖：invalid Bearer/Admin token + 声明 50 MB body 的 early 401、valid key body dispatch、public login body deadline、slow request line、64/65 capacity、`/v1`/Admin CORS preflight。
- 定向 raw-socket/auth/CORS：**51 passed**。
- `make lint`：通过（Ruff、294 files format、`ty`）。
- `make test`：收集 2,746 项，结果 **2,741 passed, 5 skipped, 9 warnings**。
- `make build`：成功生成 sdist 与 `codex_rosetta-0.144.0.post0-py3-none-any.whl`。
- Python 3.10.20 / 3.13.2 的 core 与 `[gateway]` 四组 clean-wheel smoke：全部通过；Gateway CLI 均报告 `0.144.0.r0`，runtime budgets 为 `5/10/30/64`。
- `make check-codex-compat`：通过，`Changed: None`；`make check-release-version RELEASE_TAG=v0.144.0.r0`：通过。
- 隔离 Compose 从当前 wheel 构建成功；`/health` 正常、容器内版本为 `0.144.0.r0`，invalid key + 50 MB 声明 body 在 0.004 秒返回 CORS-readable 401。临时容器与 network 已清理，其他 Docker 工作负载未触碰。
- `git diff --check`、normalized vendor equality 与 `codegraph sync`：通过。

## 文档与兼容性

- `docs/en/gateway-security.md` 与 `docs/zh-cn/gateway-security.md` 已同步记录固定 parser budgets、pre-body auth 顺序、public login/OPTIONS 例外及 50 MB 有效 body 上限。
- 本修复是通用 HTTP parser/auth resource envelope，不新增 Codex-specific header/item/event/tool adaptation，因此不新增 compatibility point；现有 Codex contract gate 已通过。

## 未运行与剩余风险

- 未运行 credentialed live Codex/provider/agentabi、真实外部 non-loopback 负载/容量、外部 GitHub Actions、漏洞/许可证/SBOM/签名、backup/restore、release、deploy 或 rollback。
- 64-parser 是固定安全预算，不是生产吞吐量测量结果。非回环部署仍必须使用 TLS、网络 ACL/防火墙和外层限流。
- Audit profile 的 owner、legal/privacy、ASVS、SLO/error budget、incident response、依赖治理、签名与 SBOM 仍为未批准治理项。
- Public health/readiness 的 token-only redaction 继续按前轮已接受合同保留，本轮没有重开。

维护性判断：修复集中在 upstream HTTP parser 的 request lifecycle owner，Gateway 只声明产品 budgets 并复用一个 auth hook；未引入第二套 parser、per-route semaphore 或等待队列。新增 upstream 与真实 socket regression 覆盖关键正常、早退、错误、取消和容量边界，无需额外清理重构。
