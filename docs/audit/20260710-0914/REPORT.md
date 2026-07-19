# Codex-Rosetta 第九轮审计修复报告

审计时间：2026-07-10（MDT）

完整账本：`.agent-work/audit/20260710-0914/FULL.md`

本轮 4 项必须修复 finding 已全部解决，最终验证门禁全部通过。本轮没有新增仍待处理的
代码 finding。

## 审计验证

- 仓库状态已检查：是。当前仍是 `master` 上的大型未提交工作树；本轮未 reset、revert、
  stage、commit、push、release 或 deploy，`src/codex_rosetta/_vendor/**` 无改动。
- 差异已审阅：是。本轮复核 F-01 至 F-04 的 owner、caller、错误映射、资源释放、配置
  热更新/回滚路径，以及对应正向、边界和失败路径测试；详细证据见 `FULL.md`。
- 审计范围与抽样依据：聚焦 Gateway 高风险安全边界，包括 upstream error logging、
  Google URL-image 网络获取与 worker 容量、request-log retention、HTTP upstream body
  聚合；覆盖配置启动/热更新、Admin activation、app lifecycle、persistence compensation、
  direct/converted 与 stream/non-stream 路径。
- 关键质量属性：按安全、可靠性、正确性、资源上限、可运维性和可维护性排序。
- 已运行测试：`conda run -n llm-rosetta make test`，结果为 `2622 passed, 4 skipped,
  9 warnings`；其中包含 3 个通过真实 loopback HTTP server 和 vendored streaming client
  执行的 F-04 overflow fixture。前序定向回归还包括 61、29、13 和 527 项测试组。
- 已运行静态与合同检查：`make lint` 全绿（Ruff、288 files format check、`ty check`）；
  `make check-codex-compat` 通过，Codex source commit 为
  `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`，`Changed: None`；
  `make check-release-version RELEASE_TAG=v0.144.0.r0` 通过。
- 已运行构建检查：从当前源码重新构建 wheel，在隔离 Python 3.14 venv 中以 `--no-deps`
  安装，并从 `site-packages` 成功导入 F-01 至 F-04 owner 模块；运行时版本为
  `0.144.0.r0`。
- 已运行仓库检查：`git diff --check`、`git diff origin/master --check` 均通过；最终
  `codegraph sync` 通过。
- 未运行测试：`tests/integration/**` 需要真实 provider API key 与 upstream 网络，且
  `make test` 按项目合同默认排除。Docker Compose 未运行，因为本轮未改 Dockerfile、
  Compose 或 entrypoint；当前源码 wheel 的构建、隔离安装和 import smoke 已覆盖新增
  模块的打包。实际容器发布前仍应执行 Compose smoke。
- 已检查高风险流程：token redaction 与日志单行/长度约束；DNS 到 body 的单一 deadline；
  worker timeout/cancel/shutdown 与 permit 生命周期；retention startup/reload/direct
  validation、零值 prune 与 compensation；body Content-Length/unknown-length/encoding
  上限、SSE 增量读取和 response close。
- 已检查发布/回滚/观测/恢复路径：Admin config prepare/commit/compensate、app close、
  persistence rollback、错误日志/错误 dump 边界和 release/compat gate 均有代码或测试
  证据。
- 假设：本轮是 generic Gateway safety repair，不改变 Codex-specific request、response、
  stream event、tool、session 或 model-catalog contract，因此未新增 compatibility ledger
  point。
- 需要人工复核：真实 provider integration、实际 Docker Compose 容器启动，以及 Draft
  audit profile 中尚未确定的 owner、legal/privacy、vulnerability response、SLO、build
  provenance 与 CI secret policy。
- 已知过时上下文或冲突证据：未发现。本报告已按当前工作树、当前测试输出和当前
  CodeGraph 状态更新，不以先前完成声明作为最终证据。

## 主要发现

- `必须修复（已解决）` F-01：upstream error log 原先可接收未脱敏 token 并允许控制字符
  伪造日志行。现由每个 app 的 `UpstreamErrorLogState` 统一执行 live token redaction、
  单行转义和精确 4,096 字符上限，并覆盖热更新、补偿回滚和多 app 隔离。
- `必须修复（已解决）` F-02：Google URL-image timeout 与并发容量原先不是 Gateway 的
  总量有界资源。现由单一 monotonic deadline 覆盖 DNS、连接、重定向、header 和 body，
  app-owned 四 worker 池在 raw future 真正结束前保持 permit，并支持 cooperative close。
- `必须修复（已解决）` F-03：request-log retention 原先可接受不安全值并把负值传给
  SQLite limit。现统一验证为非 bool 整数 `0..1_000_000`，`0` 在 activation transaction
  中立即 prune，失败后可 compensation；error dump 的固定 10,000 条合同保持独立。
- `必须修复（已解决）` F-04：upstream response body 原先可能无上限聚合。现强制
  `Accept-Encoding: identity`，非流式成功 body 上限 50,000,000 bytes，非流式错误和
  streaming HTTP error 上限 1,000,000 bytes；未知长度响应逐 chunk 计数，正常 SSE 保持
  增量传输。

系统整体健康状况：本轮发现的四个安全/可靠性缺口均已在清晰 owner 边界内修复，并由
失败路径、并发、回滚、真实 loopback transport 和全量测试共同验证。当前最稳固的部分
是新增边界的单一 owner 与可执行合同测试；剩余最高风险来自未执行的真实 provider/
container integration，以及仍为 Draft 的项目审计 profile。下一轮建议优先完成 profile
决策，并在发布候选上补真实 upstream 与 Compose smoke。

## 风险排序依据

本轮按凭证泄漏与日志注入、远程输入导致的线程/内存耗尽、持久化保留策略失控、影响
路径数量和爆炸半径、故障可逆性、证据强度及修复成本排序。四项 finding 均可由不可信
upstream 或运行时配置触发，影响跨 direct/converted、stream/non-stream 或多 app 路径，
因此列为必须修复，而不是仅按文件大小或代码复杂度排序。

## 维护性判断

日志脱敏、image worker 容量、retention validation 和 HTTP body limits 各有单一 owner；
`proxy.py` 只接收窄状态/worker 参数和稳定错误映射，没有复制网络循环或验证规则。测试
覆盖正常、边界、取消、回滚与隔离路径；本轮无需额外结构重构，后续只需完成上述真实
integration 与审计 profile 决策。
