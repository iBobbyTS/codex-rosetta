# Codex-Rosetta 第 16 轮代码审计报告

审计与修复时间：2026-07-10 14:53–15:08 America/Edmonton  
审计画像：`.agent-work/audit/PROFILE.md`（`Draft`）  
完整台账：`.agent-work/audit/20260710-1453/FULL.md`

结论：**本轮确认的 1 条“需要规划”finding 已修复并验证，当前无未关闭 finding。** SDK 兼容性定时监控现在只在 schedule/manual job 上获得创建 issue 所需的最小权限，并由结构化 workflow contract tests 固定 fork/untrusted PR 安全边界。Gateway 运行时、Admin 动态渲染和完整本地测试门禁没有发现新的未关闭缺陷。

## 审计验证

- **仓库状态已检查：是。** `master` 比 `origin/master` ahead 1，HEAD 为 `eb94742`；最终有 98 个 tracked 修改文件、32 个 untracked 文件，无 staged diff。第 16 轮修复只新增/修改 `.github/workflows/sdk-compatibility.yml`、`tests/test_workflow_contracts.py` 和被忽略的审计台账；没有 commit、push、PR、release、deploy 或远端 issue/workflow 操作。
- **差异已审阅：是。** 审阅当前 9,097 行新增/1,613 行删除的 tracked diff 概况，并独立抽样 Admin HTML/JSON/profiling source-to-sink、日志/诊断/下载路径、CI、SDK monitor、Dependabot、依赖元数据、Docker/Makefile 与最近提交；修复 diff 另行逐行复核，未把前轮摘要当作当前证据。
- **审计范围与抽样依据：** Draft profile 将 Codex/gateway 正确性与可靠性置于最高优先级；前 15 轮已深入覆盖转换、状态、持久化、HTTP/SSE、Admin/config 和 release，本轮继续追踪上一轮 DOM-XSS 邻近 sink，并轮换到未形成实际运行证据的 SDK 兼容监控与 CI 权限边界。
- **关键质量属性：** 安全、可靠性、运维可观测性、协议正确性、发布完整性和可维护性。
- **已运行测试：** workflow contract 定向测试 **2 passed**；`conda run -n llm-rosetta make lint` 通过（Ruff、292 files format check、`ty`）；`conda run -n llm-rosetta make test` 收集 2,725 项，结果为 **2,720 passed, 5 skipped, 9 warnings**；`make check-codex-compat`、`make check-release-version RELEASE_TAG=v0.144.0.r0`、`git diff --check`、`git diff --cached --check` 与 `codegraph sync` 均通过。
- **远端只读验证：** GitHub API 确认 `SDK Compatibility Monitor` 为 active，但仓库 `default_workflow_permissions` 为 `read`，且该 workflow 尚无历史 run；仓库标签列表中也没有 `sdk-compatibility` 与 `automated`。
- **未运行测试：** `actionlint` 未安装；未触发远端 `workflow_dispatch`，因为这会改变外部 Actions 状态；未运行 credentialed integration/agentabi/live provider、漏洞/许可证扫描、生产负载、备份恢复、真实 release/deploy/rollback。opt-in 浏览器测试本轮未重跑。
- **已检查高风险流程：** provider/config/log/test/diagnostic 值到 Admin DOM 的编码边界；profiling HTML/ZIP 生成与查看；SDK type-test 失败到 issue 告警；CI Python matrix、clean-wheel 和 Docker 本地 wheel 来源。
- **已检查发布/回滚/观测/恢复路径：** 自动发布保持禁用，Docker 使用当前 checkout wheel；SDK drift 告警权限缺口已局部修复并由静态 contract 固定。签名/SBOM、外部 CI、恢复演练和真实发布证据仍缺失。
- **假设：** `pyinstrument.output_html()` 属于受信任的已安装代码；GitHub 当前返回的 repository workflow permission 是实际执行时 `GITHUB_TOKEN` 的默认权限；用户要求立即审计，因此在 Draft profile 上继续而未等待 owner 补齐治理字段。
- **需要人工复核：** audit profile 的 owner、legal/privacy、ASVS、SLO/error budget、incident response、CI 权限、signing/SBOM 和 dependency governance；条件允许时仍应进行一次受控的失败分支 workflow dispatch。
- **已知过时上下文或冲突证据：** 第 15 轮 clean 结论聚焦 Admin source-to-sink，没有覆盖本轮的 SDK monitor 权限边界；其运行时与 DOM-XSS 修复结论未被推翻。

## 主要发现

### 已解决，无需处理：SDK compatibility failure 无法创建告警 issue

- **修复前证据：** type-test 使用 `continue-on-error` 进入 failure issue step，脚本调用 `github.rest.issues.listForRepo()` 与 `github.rest.issues.create()`，但 workflow/job 没有 `permissions` 声明；GitHub 实仓 API 返回 `default_workflow_permissions: read`。当前修复位于 `.github/workflows/sdk-compatibility.yml:13-15,33-42,51-66`。
- **触发路径：** 周日 schedule 或手动 dispatch 的 type compatibility tests 失败；由于 `continue-on-error: true`，流程进入 `actions/github-script@v9`，随后 Issues API 因 `GITHUB_TOKEN` 无 `issues: write` 被拒绝。
- **影响：** SDK 漂移虽然会让 Actions job 失败，但不会生成设计中的可去重、可跟踪 issue；维护者只能主动发现失败 run。它不影响 Gateway 请求处理，因此不升级为“必须修复”。
- **修复：** 仅在 `sdk-compatibility` job 声明精确的 `contents: read` 与 `issues: write`；trigger 仍严格是 `schedule` / `workflow_dispatch`，没有 fork/untrusted PR、push 或 workflow chaining 入口。移除远端不存在的 `sdk-compatibility` / `automated` label 依赖，保留按标题去重。
- **回归保护：** `tests/test_workflow_contracts.py` 结构化解析 workflow，验证 trigger 集合、无 workflow-wide write、精确 job permissions、type-test 命令与真实失败传播、issue step condition/action/API 调用及无 label 依赖。
- **验证：** 定向 2 tests、lint/type、2,725 项完整非集成 suite、Codex compatibility、release-version、diff 与 CodeGraph gates 全部通过；按要求没有真实触发或创建 issue。

### 记录为技术债

- Actions 使用可移动 major tag，optional dependencies 多数无上界；是否要求 immutable SHA、lock、漏洞/许可证策略、签名与 SBOM 仍缺 owner 基线。
- Audit profile 仍为 Draft，外部 GitHub Actions、真实 Codex/provider matrix、生产容量和恢复/发布演练仍没有本轮证据。

### 无需处理

- Admin provider/model/key/log/test/diagnostic 动态值使用 `esc()`、`escAttr()`、`handlerArg()`、`textContent` 或 DOM 构造；本轮未确认第二条可利用 DOM-XSS 链。
- Main CI 覆盖 Python 3.10/3.13 的 lint/type/full non-integration suite 和 clean-wheel smoke；Docker 构建只安装当前 checkout wheel并以非 root 应用用户运行。

## 整体健康状况

运行时与 Admin 输入输出边界在当前抽样和 2,725 项本地门禁下保持稳固；本轮运维告警权限缺口已用最小 job 权限和结构化 contract tests 关闭。剩余最高风险来自尚未执行的真实 Codex/provider matrix、外部 Actions 失败分支和治理证据，而不是新的本地实现缺陷。下一轮应在获准时验证真实失败分支，再轮换到真实 Codex/provider matrix。

## 风险排序依据

本报告按用户/业务影响、发生概率、blast radius、可逆性、证据强度、系统性和修复成本排序。F-01 有当前 workflow 源码与 live repository 权限双重证据，原本会系统性丢失每次 SDK failure 的 issue 告警；当前局部修复和静态 contract 已覆盖代码侧失败条件，因此降为“无需处理”。未执行的远端失败分支仍明确保留为人工验证缺口，未定稿的供应链治理项也没有被包装成同级实现缺陷。

维护性判断：修复只涉及现有 workflow 的最小 job 权限、移除不存在的 label 依赖和一个结构化 contract test，没有新增运行时模块、服务或依赖；无需后续结构性清理。
