# Codex-Rosetta 第八轮审计修复完成报告

审计时间：2026-07-10（MDT）
审计画像：.agent-work/audit/PROFILE.md（Draft）
完整账本：.agent-work/audit/20260710-0736/FULL.md

本轮发现的 5 项问题已全部修复并通过当前仓库验证：F-01/F-02 的 Google URL-image 网络边界、F-03 的 profiling 下载路由、F-04 的 Admin 数字查询校验，以及 F-05 的 request-log retention 热更新事务。当前没有遗留的本轮 finding。

前轮已经接受的 public health token-only 正文语义、count-only 诊断保留、多副本连续性和 manual release provenance 没有被重新包装成新问题。本轮未提交、未推送、未发布、未部署，也没有重置或暂存用户原有工作。

## 审计验证

- 仓库状态已检查：是。master 的 HEAD 为 eb947426572a，比 origin/master ahead 1；当前工作树有 88 个 tracked change 和 23 个 untracked file，无 staged change。大型脏工作树被保留。
- 差异已审阅：是。重点复核 F-01 至 F-05 的源代码、测试和 CodeGraph 调用路径；没有把整棵用户工作树归因于本轮修复。
- 审计范围与抽样依据：覆盖 Responses→Google image、gateway egress policy、Admin route dispatch、Admin query validation、config hot reload→persistence owner 五条高风险路径；同时抽样复核 auth/CORS、state scope、encrypted mapping、stream terminal、CI/Docker/release。
- 关键质量属性：安全、正确性、可靠性、事务恢复、单一状态所有权、运维可解释性和可维护性。
- 已运行测试：
  - conda run -n llm-rosetta make lint：通过；Ruff check、283 个文件的 format check、ty check 全绿。
  - conda run -n llm-rosetta make test：2,581 passed, 4 skipped, 9 warnings；Python 3.14.6。
  - make check-codex-compat：通过；Codex source 2e8c3756f95789c215d9ea9a5ade6ec377934b3f，Changed: None。
  - make check-release-version RELEASE_TAG=v0.144.0.r0：通过。
  - git diff --check、git diff origin/master --check：通过。
  - codegraph sync：通过；同步 15 个 changed file。
- 环境调用说明：直接 make lint/test 曾因当前 shell 未激活 llm-rosetta 而退出 2，原始错误分别为 make: ruff: No such file or directory 和 make: pytest: No such file or directory；随后使用项目 conda 环境复验通过。
- 未运行测试：真实 provider/API/agentabi、native GPT、compact/resume/fork、浏览器 UI、WebSocket、GitHub Actions、负载/容量、依赖漏洞/许可证、生产备份恢复、release/deploy/rollback、Python 3.10/3.13 wheel smoke、Compose smoke。
- wheel/Compose 限制：F-01 至 F-05 未改依赖元数据、打包包含规则、Docker 或 Compose 配置，因此本轮未重复这些 smoke；仍应以 CI/release automation 作为外部确认。
- 已检查发布/回滚/观测/恢复路径：检查 Codex contract、release tag gate、config 文件恢复、runtime compensation、SQLite prune/rollback 和 restart convergence；没有执行外部变更。
- 假设：gateway access key 持有者可以调用模型，但不应自动获得读取 gateway 内网、loopback 或 cloud metadata 的能力。
- 需要人工复核：真实公网 image、显式 application proxy、真实 provider/agentabi、浏览器 UI 与多进程场景仍需外部环境验证。
- 已知过时上下文：修复前关于默认 urllib opener 和 retention hot reload 的完成声明已经由本轮实现与测试替代。

## 主要发现与修复结果

### F-01：Responses→Google image URL 的 SSRF、无界下载和 event-loop 阻塞

已解决。新增统一的安全 fetcher，仅允许 HTTP(S)，禁止 URL userinfo，拒绝 private、loopback、link-local、multicast、reserved、unspecified 和其他非公网地址；所有 DNS 结果必须为公网，直连时绑定已验证的数值 IP，redirect 每跳重新校验并限制次数。响应同时限制 MIME、Content-Length 和实际读取字节数，错误不回显 URL 或正文。Google 请求转换通过 asyncio.to_thread 移出 event loop。

测试覆盖 unsafe scheme/address、混合 DNS、redirect、DNS rebinding 防护、MIME/大小、错误脱敏、loopback pipeline rejection 和 off-loop scheduling。

### F-02：无显式 proxy 时 URL-image fetch 读取 process environment

已解决。fetcher 始终显式安装 ProxyHandler；proxy_url 为空时使用空代理映射，不再读取 HTTP_PROXY/HTTPS_PROXY；proxy_url 非空时只使用 app-owned proxy。回归测试同时验证 stale 环境代理隔离和显式代理路径。

### F-03：profiling ZIP download 路由被动态 index 截获

已解决。静态 download 路由现在先注册，动态路由改为 <int:index>。dispatch 级测试验证 HTTP 200、application/zip、archive 文件名和内容。

### F-04：Admin 数字 query 参数畸形值返回 500

已解决。统一的 bounded integer query helper 现在拒绝非整数、重复值、负数、禁止的零值和超大值，并返回结构化 400。metrics seconds、request-log limit/offset、error-dump limit/offset 都使用同一边界，另有有效默认值和分页回归。

### F-05：request-log retention config 与 live persistence state 分裂

已解决。persistence policy 使用 prepare/commit/rollback token，同时更新 redactor、success_max 和 error_max。降低 cap 会在同一 SQLite transaction 中立即 prune；prune/commit/config write 后续失败会恢复旧 cap、redactor 和被删 rows。启动时也立即按当前 cap 收敛。config candidate 在 runtime activation 前完成 directory fsync，失败时恢复原文件；zero-row provider backfill 不再留下未关闭 transaction。error-dump retention 仍保持独立，没有改变原合同。

测试覆盖立即 prune、增大 cap、partial prune failure、commit failure、post-activation rollback、restart convergence、app isolation、fsync ordering、文件恢复和 zero-row transaction。

## 整体健康状况

本轮最高风险的外部输入→内部网络→外部 provider 信任链已经改为 fail-closed；其余四项 integration/ownership 缺口也在现有模块边界内闭环。静态检查、全量测试、Codex contract、release tag 和 diff hygiene 全部通过。auth/CORS、principal/window isolation、encrypted mapping、stream terminal 与原子 config writer 的抽样结果仍然稳定。

当前仍是大型未提交工作树，因此“本轮 finding 全部解决”不等于“工作树 clean”或“已达到发布状态”。真实 provider、浏览器、多进程和 release/CI 环境仍是剩余外部验证边界。

## 风险排序依据

排序优先考虑未授权网络能力、跨信任域数据移动、内存/事件循环爆炸半径、持久化数据可逆性、发生概率和证据强度。F-01/F-02 的 egress boundary 优先级最高；F-05 涉及运行时与持久化状态一致性及 rollback；F-03/F-04 影响控制面可恢复性和错误语义。所有修复均有行为级回归，而不是仅靠 mock 执行或静态声明。

## 维护性判断

影响模块集中在 Google image conversion、Admin routes、config activation 和 persistence owner。新增复杂度主要来自必要的网络策略与事务补偿，并分别收敛在单一 safe fetcher、单一 query helper 和既有 activation transaction 中；没有引入平行配置服务或大范围重写。测试覆盖了安全负路径、路由 dispatch、事务失败与 restart。当前无需为本轮修复追加结构性重构；后续应继续用集成测试保护已经较大的 gateway/config 协调面。
