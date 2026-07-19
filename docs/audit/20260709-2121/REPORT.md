# Codex-Rosetta 代码审计报告

审计与修复日期：2026-07-09（MDT）

审计画像：`.agent-work/audit/PROFILE.md`，状态为 `Draft`。

## 审计验证

- 仓库状态已检查：是。当前位于 `master`，HEAD 为 `eb94742 feat(admin): add read-only tool catalog`，`origin/master` 为 `d3e899a release: v0.144.0.r0`。最终检查时工作树包含 72 个 tracked 文件变更（2,347 additions / 792 deletions）和 12 个 untracked 实现、测试及文档文件；无 staged diff，未执行 commit、push 或 PR 操作。
- 差异已审阅：是。重点覆盖 `gateway/app.py`、`auth.py`、`config.py`、`proxy.py`、Admin routes/UI、state scope、tool adaptation、stream phase、observability/persistence/redaction、Responses converter、CI/Makefile/Docker/发布脚本及相关测试；同时抽查公共入口、Codex 兼容性台账和仓库规则。
- 审计范围与抽样依据：围绕 `/v1/responses`、SSE、跨轮工具状态、Admin 登录与配置写入、API key 生命周期、SQLite/JSONL 诊断、Codex 升级契约和发布路径展开；按 Draft profile 的高变更、高影响路径抽样，并检查当前大规模未提交改动。
- 关键质量属性：正确性、可靠性与安全优先，其次为可运维性、可维护性、性能/容量和发布可追溯性。
- 已运行测试与检查：
  - 修复定向回归：`144 passed`。
  - 格式化后的 affected suites：`121 passed`。
  - `conda run -n llm-rosetta make lint`：通过；Ruff check、format check、`ty check` 均通过。
  - `conda run -n llm-rosetta make test`：`2390 passed, 4 skipped, 9 warnings`（Python 3.14.6）。4 个 skip 是空 public-API module case；与 F-08 相关的 SQLite fixture warning 已消除。
  - `conda run -n llm-rosetta make check-codex-compat`：通过；基线 commit 为 `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`，无阻塞性合同变化。
  - `make check-release-version RELEASE_TAG=v0.144.0.r0`：通过。
  - `make build-package`：成功生成 `codex_rosetta-0.144.0.post0-py3-none-any.whl` 和 source tarball。
  - release/Docker 静态合同测试通过；`make -n build-docker V=0.144.0.r0` 确认先构建当前 checkout wheel，再仅通过 `LOCAL_WHEEL` 交给 Docker build。
  - `git diff --check`：通过。
- 未运行测试：`tests/integration`、agentabi/真实 Provider、真实 compact/resume/fork 多客户端并发、Admin 浏览器手测、实际 Docker daemon build/deploy、负载/容量测试、备份恢复演练、依赖漏洞/许可证扫描和 GitHub Actions。原因分别是需要外部凭证、运行中的代理、浏览器交互、Docker daemon、部署环境或远端 CI。
- 已检查高风险流程：认证主体与 window scope、缺失 window 的隔离降级、API key CRUD、配置 candidate validation/CAS/backup/activation rollback、工具映射持久化、Responses Lite/custom tool、phase buffering、stream/error diagnostics。
- 已检查发布/回滚/观测/恢复路径：检查了 CI、Makefile、GitHub Web UI 手动 release 合同、tag validator、本地 package build、Docker 本地 wheel 合同、SQLite/JSONL 保留策略和 config `.bak`/activation rollback；未实际发布、部署或执行恢复演练。
- 假设：Gateway 可能部署到非回环地址；Admin token、Provider 输出和客户端输入属于不可信或可被窃取输入；配置文件和诊断数据可能包含真实代码或凭证。
- 需要人工复核：Draft profile 尚未确认 owner、privacy/legal、ASVS、SLO/error budget、发布签名、CI secret、SBOM、依赖治理和 incident-response 基线。`v`-prefixed GitHub tag、仅 GitHub Web UI 手动 release、不发布 PyPI/Docker，以及 F-06 的 count-only retention 已获确认，不再属于待确认项。
- 已知过时上下文或冲突证据：发现阶段识别出的 compatibility ledger、release、Docker 和 `AGENTS.md` 冲突已在本轮修复并由合同检查覆盖；当前审阅范围内没有已知仍未处理的同类冲突。

## 主要发现

### 必须修复

1. **F-01 已解决：Admin 配置响应泄漏 `admin_password`**

   `_mask_server_config()` 现在从响应中彻底删除 `admin_password`。GET config 与 server-settings mutation 的 route 测试覆盖 literal/env placeholder、两种 credential visibility，并验证 stored/resolved password 均不会出现在响应中。

2. **F-02 已解决：Admin mutation 可先持久化无效配置**

   provider/model/model-group/server/key mutation 已统一到 `_commit_gateway_config()`：先对完整 raw candidate 做环境变量解析与 `GatewayConfig` 校验，再执行 digest-CAS 写盘和 live activation；activation 失败时恢复原始文件字节。duplicate key 返回 409，non-string/unresolved placeholder 返回 400，负面测试验证磁盘不变。

3. **F-03 已解决：诊断数据写入边界脱敏不完整**

   `PersistenceManager` 现在在 request-log、initial/update profile、`stream_error`、error-dump metadata 和 `upstream_url` 的持久化边界执行 token-only redaction。SQLite 回读测试验证 configured/Bearer token 不存在，同时普通 password、secret、client-secret、proxy-password、prompt 和 URL 正文保持原样。

### 需要规划

4. **F-04 已解决：Admin CORS preflight 被 token auth 提前拦截**

   Admin API OPTIONS 只绕过 token hook 进入严格 origin 检查；allowed origin 返回 204 与 CORS headers，denied origin 返回 403，实际 Admin 请求仍要求有效 token。允许、拒绝和实际请求均有 route-level 测试。

5. **F-05 已解决：兼容性、release、Docker 和 agent 规则冲突**

   当前合同统一为 source `0.144.0.r0` 对应 tag `v0.144.0.r0`，只通过 GitHub Web UI 手动创建 Release，不发布 PyPI/Docker。`build-docker` 必须先构建当前 checkout wheel，Dockerfile 不再回退安装 PyPI package。compatibility ledger/report、`AGENTS.md`、Make help、release/dev 文档已同步，version/package/Docker 合同检查通过。

### 记录为技术债

6. **F-06 已明确接受：诊断存储没有总大小、年龄或轮转预算**

   保留 token-only redaction 和 10,000 条 count-only error-dump retention，不实现 age/size pruning 或更广泛的正文脱敏。Owner 为 Gateway maintainers/operators。仅在持续 remote/multi-user 使用、广泛且长期启用 stream trace、出现磁盘告警/事故，或运营方提出硬存储预算时重新评估。

7. **F-07 已解决：request log 信任可伪造的 forwarded client IP**

   request log 现在只使用 direct TCP peer，与登录限流的信任边界一致；在引入显式 trusted-proxy allowlist 前忽略 forwarded headers。测试及中英文安全文档均覆盖该行为。

8. **F-08 已解决：测试 fixture 未关闭 SQLite connection**

   相关 `PersistenceManager` fixtures 和 direct retention tests 已显式关闭 SQLite。focused observability suites 在 `PytestUnraisableExceptionWarning` 提升为 error 时通过；最终全量 suite 中已无该类 fixture warning。

### 无需处理

- `GatewayStateScope` 将跨请求状态隔离到 authenticated principal + provider + exposed model + window；缺失 window 时使用 request-local、non-persistent scope。SQLite tool mapping 使用匹配 compound key，相关隔离测试通过。
- Phase buffer 按 event count/UTF-8 bytes 限界，超限时降级为不标 phase 的 passthrough；正常 EOF/terminal 流程和 Responses 生命周期测试通过。
- Responses converter 的 `additional_tools`、namespace regroup、custom/freeform call restoration、reasoning/stream 路径有当前实现与自动化测试覆盖；Codex contract gate 通过。
- Config durability primitives 使用稳定 sidecar lock、source digest CAS、fsync、0600 原子替换/backup；Admin mutation 现已在该边界前完成完整 candidate validation，并能在 activation failure 时恢复原始字节。
- CI 定义在 Python 3.10/3.13 运行完整非集成 suite、lint/type 和 clean-wheel smoke；本地 Python 3.14.6 检查通过，但远端 GitHub Actions 仍属于未验证项。

## 风险排序依据

本报告按业务/用户影响、秘密与数据风险、发生概率、爆炸半径、可逆性、证据强度、系统性程度和修复成本排序，而不是按文件大小或代码风格排序。F-01/F-03 涉及认证秘密或持久化诊断，F-02 可由正常 Admin API 触发并破坏下一次启动，因此原列为必须修复；F-04/F-05 影响部署和发布契约，原列为需要规划。F-06 的风险取决于运行规模与 stream-trace 使用方式，现有访问控制、token-only redaction 和 count limit 提供部分缓解，且 owner 已接受剩余容量风险。F-07/F-08 的影响较窄，修复已通过定向与全量回归。

## 总体判断

审计发现的 8 项问题中，F-01～F-05、F-07、F-08 已修复并通过自动化验证；F-06 已记录 owner 和明确触发条件后接受。转换器、Codex contract gate、状态隔离、phase buffer、配置事务、诊断脱敏和 release/package 合同整体健康。当前剩余风险主要是未执行的真实 Provider/多客户端/browser/Docker/恢复/负载/供应链/CI 验证，以及 Draft audit profile 尚未确认的运维与治理基线；下一轮应优先补这些系统级证据，而不是继续扩展本轮已完成的局部修复。
