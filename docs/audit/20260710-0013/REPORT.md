# Codex-Rosetta 第六轮独立代码审计报告

审计时间：2026-07-10（MDT）  
审计画像：`.agent-work/audit/PROFILE.md`（`Draft`）  
完整账本：`.agent-work/audit/20260710-0013/FULL.md`

本轮确认的 4 个问题均已在当前工作树修复并补充回归。没有 commit、push、PR、release 或 deploy，也没有改变上一轮已接受的 public health token-only 正文语义。

## 审计验证

- 仓库状态已检查：是。当前位于 `master`，HEAD 为 `eb94742`，`origin/master` 为 `d3e899a`。收口时工作树有 77 个 tracked status entries、19 个 untracked 文件；tracked diff 为 4,041 additions / 1,035 deletions，无 staged diff。
- 差异已审阅：是。重点复核本轮 CORS/auth、Admin HTML headers、Admin JSON routes、JSONC env substitution 及对应测试；同时保留对 gateway state、stream、observability、config persistence、CI/Docker/release 和近期 HEAD 的既有审计覆盖。
- 审计范围与抽样依据：按 Draft profile 的高风险入口和高 churn 文件抽样；从浏览器 preflight/auth error、Admin 控制面、请求 JSON root、配置文件到运行时激活追踪关键边界。
- 关键质量属性：正确性、可靠性、安全、可运维性和可维护性优先；性能/容量、供应链和成本作为次级检查。
- 已运行测试：
  - `conda run -n llm-rosetta make lint`：通过，Ruff、format、`ty check` 全绿。
  - `conda run -n llm-rosetta make test`：`2519 passed, 4 skipped, 9 warnings`，Python 3.14.6。
  - `conda run -n llm-rosetta make check-codex-compat`：通过；Codex source commit `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`，Changed: None；仍有 12 组 Possibly unchanged。
  - `conda run -n llm-rosetta make check-release-version RELEASE_TAG=v0.144.0.r0`：通过。
  - `git diff --check`、staged diff check：通过。
  - `codegraph sync`：通过，索引已经是最新状态。
- 未运行测试：真实 provider/API、agentabi/live Codex、compact/resume/fork/WebSocket、Admin 实际浏览器、Docker daemon/image scan、GitHub Actions、Python 3.10/3.13 本地矩阵、负载/容量、依赖漏洞/许可证、备份恢复和 release/rollback 演练。
- 已检查高风险流程：gateway access-key principal、Admin token/login rate limit、CORS/auth 顺序、Admin anti-framing、Admin JSON 输入边界、config env/CAS/backup/activation rollback、跨轮 mapping、stream normal/error/cancel/disconnect 终态、诊断落盘与 release gate。
- 已检查发布/回滚/观测/恢复路径：检查了本地 compatibility/tag gate、manual release runbook、当前 checkout wheel-to-Docker 合同、config `.bak`/activation rollback、SQLite/trace/request log；没有执行真实外部流程。
- 假设：跨源浏览器支持由代码中明确的 `/v1/*` wildcard CORS 和 Admin origin allowlist 表达；Admin 可能被远程部署或经反向代理访问。
- 需要人工复核：Draft profile 仍未定义 owner、legal/privacy、ASVS/threat model、SLO、incident response、签名/SBOM 和依赖治理；应确认上一轮 public health 普通 PII/error 正文的接受决定是否需要写入 versioned 安全文档。
- 已知过时上下文或冲突证据：Codex compatibility report 仍是 `Pending / not approved`；本轮通过的静态 contract gate 不能替代真实 Codex/API matrix。当前大幅 dirty snapshot 也不是可发布 revision。

## 主要发现

### 必须修复

当前没有未解决的“必须修复”项。

1. **F-02 已解决：Admin 控制面 anti-framing**

   `src/codex_rosetta/gateway/admin/routes/auth.py:18-32` 现在为 Admin HTML 同时设置 `Content-Security-Policy: frame-ancestors 'none'` 与 `X-Frame-Options: DENY`。`tests/gateway/test_admin_page_routes.py:65-84` 对每个 Admin HTML alias 验证这两个 header。修复没有改变现有 inline script/style 合同。

### 需要规划

当前没有由本轮 4 项发现遗留的未解决“需要规划”项。

2. **F-01 已解决：auth/CORS 顺序与 auth-error headers**

   新增 `src/codex_rosetta/gateway/cors.py` 作为 route-specific CORS 单一入口。受保护 `/v1` OPTIONS 可进入 preflight，但真实请求仍需 API key；API 401 使用 wildcard CORS，Admin 401 仅在 exact allowlist origin 下返回 CORS grant。route-level 回归覆盖三个受保护 `/v1` endpoint、Admin allowed/denied origin、auth failure 和热更新 allowlist。

3. **F-03 已解决：Admin JSON root-object 合同**

   `admin/routes/_shared.py:46-54` 的 `_parse_json_object()` 现在是 Admin routes 唯一的 `request.json()` 调用点。login、provider、model、model-group、server、bulk-model、keys、testing 与 profiling 对 scalar/list/null 统一返回 400；profiling 的非整数 `requests` 也返回 400。测试矩阵覆盖 6 类非对象值、10 条 route 与非法整数。

4. **F-04 已解决：JSONC 环境变量结构注入/特殊字符破坏**

   `gateway/config.py:199-226` 现在先解析 JSONC，再递归替换 dict/list 中的字符串值。quote、backslash、newline 与 JSON-looking 环境值均保持为字符串数据，不能新增 sibling 字段；startup `load_config()` 与 Admin candidate `GatewayConfig.from_raw_with_env()` 均有回归。未设置变量继续保留原 placeholder 并记录 warning，旧合同不变。

### 记录为技术债

- Public `/health` 和 critical `/health/ready` 仍会公开 provider 名称及普通 email/PII/password/secret 型 `last_error`，只脱敏 configured/Bearer/token 字段。`.agent-work/audit/20260709-2336/REPORT.md` 已把它记录为接受的 public contract，本轮未扩大或改变该语义。建议 owner 决定是否把这一公开信息合同写进 versioned security guide。
- Provider metadata/deferred tool catalog 仍是单进程内存状态；多 replica/restart 连续性取决于尚未确定的部署拓扑。
- Release provenance、clean revision、compatibility live evidence、签名和 SBOM 仍依赖人工；upgrade report 继续保持 `Pending / not approved`。

### 无需处理

- `GatewayStateScope` 对 principal/provider/model/window 的隔离、缺失 window 的 request-local/non-persistent 降级，以及 SQLite compound key 在当前审阅范围内合理。
- Config writer 的稳定 lock、digest CAS、0600 atomic replace/backup、fsync、prepare-before-write 和 assignment-only activation/rollback 有清晰 ownership 与负向测试。
- Stream terminal wrapper、phase buffer 上限、Responses direct passthrough、namespace/custom/freeform 工具路径及 token-only persistence redaction 有较强自动化覆盖。
- 本轮共享 CORS policy、Admin JSON parser 与 parse-first env substitution 都留在既有 ownership 边界内，没有引入新的 service、依赖或并行状态源。

## 整体健康状况

本轮 4 个可复现问题已全部解决，核心转换、state scope、config durability、stream lifecycle 和本地自动化仍是最稳固部分。修复把重复的 CORS/JSON 输入规则收敛到小型共享入口，并保持配置替换在现有 loader 边界内；没有扩大 public health 内容合同。剩余最高风险不在本轮代码缺陷，而在 Draft audit profile、真实 Codex/provider/browser/Docker 验证，以及 release provenance/多副本部署假设。

## 风险排序依据

排序综合未认证/跨站可达性、控制面权限、用户影响、发生概率、爆炸半径、可逆性、证据强度、系统性程度和修复成本。Clickjacking 原先影响完整 Admin 权限；CORS 是可复现的受支持路径故障；JSON/env 问题分别位于输入与配置来源边界。它们只有在代码可见且回归、全量 gate 均通过后才标记为已解决。
