# Codex-Rosetta 第 10 轮代码审计报告

审计时间：2026-07-10 09:27 America/Edmonton

审计画像：`.agent-work/audit/PROFILE.md`（Draft）。本轮按用户要求立即审计并修复；未确认的治理字段继续作为限制记录，不把它们表述为已批准的业务规则。

## 审计验证

- 仓库状态已检查：是。当前分支为 `master`，HEAD 为 `eb947426572ad7658c4b5ad19688fa68659a06b6`，`origin/master` 为 `d3e899aea478002d965b0a591fbedf803f80ddb1`。工作区包含大量既有 tracked/untracked 改动，均已保留，没有回退用户工作。
- 差异已审阅：是。覆盖当前 working tree、相对 `origin/master` 的差异、vendored upstream 变更、对应 tests/docs/build/release surface。最终 tracked diff 为 95 个文件、6,300 insertions、1,392 deletions，另有 untracked 源码、测试、脚本和文档；`git diff --check` 与 `git diff origin/master --check` 均 exit 0，`git status --short` 已留存，`codegraph sync` 成功同步 9 个 changed files。
- 审计范围与抽样依据：覆盖 `/v1` Auth/CORS/路由顺序、direct/converted 与 stream/non-stream proxy、HTTP chunked/SSE transport、raw Responses passthrough、Admin credential presentation、Google image egress、跨请求状态、SQLite persistence/redaction/encrypted mapping、CI/Docker/release、Codex compatibility ledger。优先抽样不可信网络输入、安全默认值、secret presentation、状态隔离和发布可追溯性。
- 关键质量属性：安全、正确性和可靠性最高；其次为运维性、可维护性和发布可追溯性；性能按资源耗尽与进程级 blast radius 排序。
- 已运行测试与检查：
  - 主仓库 `make lint`：通过。
  - 主仓库 `make test`：`2632 passed, 4 skipped, 9 warnings`。
  - Auth/application 定向测试：`42 passed`。
  - Transport/raw passthrough 定向测试：`19 passed`。
  - `make check-codex-compat`：通过，无 changed contract group。
  - `make check-release-version RELEASE_TAG=v0.144.0.r0`：通过。
  - Python 3.10.20/3.13.2 clean-wheel core 与 Gateway smoke：通过；四个环境均报告 `0.144.0.r0`。
  - 当前 wheel Compose image build 与隔离 runtime smoke：通过；`/health` 返回 `status: ok`，容器内 CLI 报告 `0.144.0.r0`。
  - Upstream `httpclient`：`155 passed`；upstream `sse`：`76 passed`；`zerodep version-check`、`zerodep dep-check httpclient sse`（`2 passed`）、lint、Ruff/format/ty/complexipy pre-commit：全部通过。
- Upstream 完整 diff SHA-256 与 vendor normalized-note/source equality：通过。
- 审计工件生命周期：最终 `FULL.md`/`REPORT.md` 已写入，`.agent-work/audit/CURRENT.md` 已删除。
- 未运行测试：`tests/integration/**`、真实 Codex/provider/agentabi matrix、远端 CI、backup/restore drill、多进程压力测试。真实 credential/外部 provider 与运维演练不在本轮本地闭环内；commit、push、PR、release、deploy 未获授权，均未执行。
- 上游验证缺口：upstream aggregate `make test` 因基线 Makefile 引用不存在的 `jsonc/test_jsonc_correctness.py` 无法完成；受影响模块的直接 tests、dependency/version checks 和所有质量门禁均通过。这是 upstream 基线 aggregate target 缺口，不是本轮修复失败。
- 已检查高风险流程：未知/动态/removed `/v1` 路由鉴权、peer-declared chunk、无换行 SSE line、无 delimiter SSE event、converted/raw passthrough overflow、stream cancel/close、Admin proxy userinfo、principal/window state、Google SSRF/worker、config activation rollback、encrypted mapping。
- 已检查发布/回滚/观测/恢复路径：release version gate、current-wheel Docker provenance、Compose runtime、config CAS/backup/rollback、request/error log、mapping DB/key 绑定均已抽样；真实 release/deploy、灾备恢复和远端 rollback 未执行。
- 假设：成功 SSE 可无限持续且总字节数不受限，但单 line/event 受当前 1 MiB/8 MiB 安全 envelope 约束；未来真实 Codex/provider 单 event 接近上限时必须触发 compatibility ledger 中的真实测试与限额复核。
- 需要人工复核：未来升级需执行已记录的真实 Codex/API matrix；proxy URL userinfo 仍对已认证 Admin 可见，应继续视为敏感配置并尽量避免在 URL 中存放密码。
- 已知过时上下文或冲突证据：初始审计报告中的 F-01/F-02/F-03 “Open” 状态已被当前代码、negative regressions、upstream provenance 和验证结果取代；F-04 经业务语义确认后归为 Accepted Semantics，而非待修 secret masking bug。

## 主要发现

本轮没有未关闭的“必须修复”或“需要规划”发现。四项初始问题已按当前证据收口：

### 1. 已解决：`/v1` namespace 默认 fail closed

`src/codex_rosetta/gateway/auth.py::_is_protected_api_path()` 现在覆盖 `/v1` 及所有 `/v1/*`。认证先于 router，因此动态注册、未知和已移除路径无 key 均返回 401；有效 key 后再由 router 决定结果。当前 wildcard `OPTIONS` route 会让 authenticated unknown non-OPTIONS path 返回 405，测试已显式记录。浏览器 `OPTIONS`、Admin 与 health 行为保持原有边界。

### 2. 已解决：chunked body 不再按 peer 声明大小整体物化

修复落在 upstream `zerodep`：`httpclient 0.4.4 → 0.4.5`。Async chunk decoder 按调用方 `chunk_size` 分段读取；Gateway 每次最多读取 64 KiB，小 budget 使用 `max_bytes + 1`，外层总量限制能在 bounded read 后及时拒绝。真实 loopback regression 覆盖 huge declared chunk、正常 multi-chunk、overflow、cancel 和 close。

Upstream 基线为 `fb84dd10ca736129f937740e44a485034b51258b`，六文件完整 diff SHA-256 为 `62b4be2a13f3b347af40aba37c47fdaf96e60b0bd86fddbaa14d8a13d2d838e0`。官方 re-vendor 命令为：

```bash
python zerodep.py --local update httpclient sse --no-deps \
  --dir /Users/ibobby/Projects/codex-rosetta/codex-rosetta/src/codex_rosetta/_vendor
```

只规范化 CLI 管理的 note header 后，upstream 与 vendor 逐字一致；`httpclient` normalized SHA-256 为 `d1a678cdf403ceae61b7b890aa952178d8bd34014c3c2b94717fba43f40cfedb`。

### 3. 已解决：成功 SSE 具有 per-line/per-event 安全上限

Upstream `sse 0.3.2 → 0.3.3`，同步/异步 HTTP line 默认上限 1 MiB，SSE event 累积 `data:` payload 上限 8 MiB，每个 delimiter 后重置。Gateway 用稳定的 `UpstreamStreamLimitError` 表达 overflow；converted SSE 与 raw Responses passthrough 执行同一限制，raw 合法字节不被重写，成功 stream 的总时长和总大小仍无限。

Loopback 与 Gateway regressions 覆盖 no-newline line、no-delimiter event、converted/raw overflow、合法多行事件、byte-identical raw passthrough、cancel/close。Normalized `sse` upstream/vendor SHA-256 为 `88e25785784c90df278a04d0afeefe0df909a9ac92bf8f8b9bc55aa09c9f526e`。

### 4. 已接受语义，无需代码修改：`credential_visible` 不遮盖 proxy URL userinfo

`server.credential_visible` 的产品合同只控制 Admin UI/API 中 Gateway/provider API credential 的原文显示，不处理 `server.proxy` 或 provider `proxy` URL 中的 userinfo。中英文 `gateway-security.md` 已同步明确：这类连接 URL 对已认证 Admin 仍可见，应尽量避免把 proxy password 写入 URL，并严格保护 Admin access。该残余风险已被明确记录，不再作为与产品合同冲突的 bug。

### 记录为技术债

`gateway/app.py` 仍有未使用的 legacy generation handler，`app.py`、`proxy.py` 和 Admin config coordination 规模较大。当前 ownership、测试和文档足以支撑本轮局部修复；没有证据支持借本轮安全闭环做大范围 coordinator rewrite。建议只在后续明确的删除/边界重构任务中处理。

## 风险排序依据

F-01 原本是系统性 authorization default；F-02/F-03 可由单个不可信 upstream 连接触发进程级可用性故障；F-04 是 authenticated Admin trust-boundary 的展示语义。排序依据是安全/业务影响、发生可能性、blast radius、可逆性、证据强度和修复边界，而非文件大小。前三项均已在单一 owner 边界内修复并有 negative regression；F-04 经语义确认和双语文档澄清后降为已记录 residual risk。

## 整体判断

第 10 轮审计的四项初始问题均已闭环：F-01/F-02/F-03 有代码、upstream provenance、negative regressions 和多层验证；F-04 有明确的 accepted semantics 与双语 operator guidance。当前最稳固的部分包括 Auth fail-closed default、HTTP/SSE resource boundary、raw byte-preserving passthrough、config transaction、encrypted mapping、Google URL validation 和 current-wheel Docker provenance。

剩余限制主要是外部真实性验证，而非已知本地缺陷：真实 Codex/provider/agentabi matrix、远端 CI、灾备/多进程演练仍未运行。Compose smoke 使用独立 18765 端口并仅清理本轮容器/network，用户原有的 `127.0.0.1:8765` 进程未被操作。

维护性判断：修复保持在 Auth policy、upstream transport/SSE、Gateway safety translation 和文档合同各自的 ownership boundary；没有把逻辑继续堆入大型 coordinator。测试覆盖了真实 socket、overflow、cancel/close、raw byte preservation 和动态 route 默认值。除单独处理 legacy handler/大文件债务外，不建议追加清理重构。
