# Codex-Rosetta 全系统审计修复报告

审计与修复日期：2026-07-09
审计基线：`.agent-work/audit/PROFILE.md`（`Draft`）
完整英文证据账本：`.agent-work/audit/20260709-1844/FULL.md`

## 结论

本轮审计报告中的 F-01 至 F-10 已全部修复或按明确的当前策略完成收口，没有保留已确认的业务问题。最终本地静态检查、2,378 个非 integration 测试、Codex compatibility、Python 3.10/3.14 wheel smoke 和 diff 检查全部通过。

尚不能宣称“生产与真实模型全链路已验证”：真实 provider/API、`agentabi`、Admin 浏览器视觉/无障碍和 GitHub Actions 实际运行没有执行。审计 Profile 仍是 `Draft`，生产隐私、SLO、部署拓扑和发布治理仍需 owner 定稿。

## 审计验证

- 仓库状态已检查：是。当前保留 64 个 tracked 修改和 12 个 untracked 源码/文档/测试文件；没有 commit、push 或 PR。
- 差异已审阅：是。覆盖 gateway/Admin 认证、跨轮状态、SQLite、配置写入、观测脱敏、流式缓冲、CI、release、Docker、双语文档和测试。
- `_vendor/**`：未修改。
- `.agent-work/audit/CURRENT.md`：不存在，审计临时指针已清理。
- `git diff --check origin/master` 与工作树 `git diff --check`：通过。
- `conda run -n llm-rosetta make lint`：通过；Ruff、format、ty 均为绿色，272 个文件格式一致。
- 定向 token 脱敏/retention/hot reload 回归：58 passed；此前更广的安全/config/state 组合为 139 passed。
- `conda run -n llm-rosetta make test`：2,378 passed，4 skipped，28 warnings，Python 3.14.6。
- `conda run -n llm-rosetta make check-codex-compat`：通过；Codex source commit 为 `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`，Changed: None。
- wheel：构建成功；在干净的 Python 3.10.20 和 3.14.6 环境中按声明依赖安装后，gateway import、Admin 资源和 CLI version smoke 全部通过。
- 未运行：真实 provider/API integration、`agentabi`、Admin 浏览器视觉/无障碍和真实 GitHub Actions。

## 已完成修复

### 1. 认证与安全默认

- 强制配置非空 Admin 密码和至少一个 gateway access key，校验 key ID/value 唯一性及保留 ID。
- 默认监听 `127.0.0.1`，凭证显示默认关闭。
- CLI init 生成随机 Admin 密码和 access key，配置文件权限为 `0600`。
- example、Docker、README 及英中文安全文档同步到新合同。
- 禁止删除最后一个 gateway access key。
- Admin 配置热重载现在同步 gateway key principal/label，也同步 Admin 密码并重建 HMAC token，外部改密后旧 token 不会持续到重启。

### 2. Admin XSS 与运行时滥用边界

- 动态文本、HTML 属性和 JavaScript handler 参数使用各自的上下文编码，恶意 provider/model/group/key 名称不能突破 handler 或 attribute 边界。
- 登录限流忽略不可信 `X-Forwarded-For`，使用直接 peer、`compare_digest`、10 分钟 TTL 和 4,096 条容量上限。
- Admin model test 限制为最多 4 个并发、128 个保留记录、120 秒执行超时和 300 秒记录年龄。

### 3. 多 principal 跨轮状态隔离

- 新增统一 `GatewayStateScope`，按稳定 principal ID、provider、model、conversation 组合隔离。
- 没有 window ID 的请求只使用 request-local state，不落入跨轮共享命名空间。
- provider metadata、Codex 工具本地化、tool search、SQLite mapping 全部使用同一 ownership boundary。
- legacy SQLite unscoped mapping 通过表迁移清理，不会错误归属给任一 principal。
- scoped store 的 `clear()` 和 `len()` 现在只作用于当前 scope，不能清除或统计其他 principal 数据；已有跨 principal 碰撞与清理回归。

### 4. 本地持久化、配置并发与诊断隐私

- config、lock、backup、SQLite DB/WAL/SHM 强制 `0600`，gateway 创建的数据目录为 `0700`。
- 配置写入采用稳定 lock、加载 digest CAS、私有临时文件、`fsync`、atomic replace、目录 `fsync` 和 `.bak`。
- error dump 与 stream trace 使用共享 `SecretRedactor`，只脱敏已配置的 Gateway/Provider API token、Bearer/Authorization token、明确的 token/API key 字段、匹配已配置 API token 的值，以及内部 Admin API token。
- 普通 request body、converted body、response、prompt、password、secret、client secret、proxy password 和个人数据继续保留；只有其具体值同时匹配已配置 API token 时才会被替换。
- error dump 只沿用原有的 10,000 条数量上限，不按天数或总大小自动删除；数量清理与手动清空仍会清理 orphan body。
- 配置热重载会刷新 API token 集合，不会把 Admin password、client secret 或 proxy password 误加入脱敏集合。

### 5. 流式与开发工具的容量/失败恢复

- `ResponsesPhaseBuffer` 限制为 256 events 和 1 MiB；超限后先 flush，再切换为未标注 pass-through，避免无限占用内存。
- `deploy-dev` 使用 trap，无论成功或失败都会恢复临时改写的版本。
- Markdown 尾随空格已清理，最终 diff check 通过。

### 6. Python、CI 与发布合同

- 修复 Python 3.10 gateway import 合同，wheel 已在 3.10.20 实机验证。
- ty diagnostics 清零；`make lint` 包含 Ruff、format 和 ty。
- CI 改为 Python 3.10/3.13，运行完整非 integration suite 与 wheel smoke。
- 自动 PyPI/Docker 发布入口保持禁用；新增仅通过 GitHub Web UI 创建 Release 的 runbook 和 `{codex_version}.rN` 校验脚本，`0.144.0.r0` 校验通过。

### 7. 修复 pipeline profile 计时测试的非确定性

- 主线程最终重跑曾出现 `1 failed, 2377 passed, 4 skipped`；失败来自多个已分别取整到 0.01 ms 的阶段之和偶尔大于独立取整的总耗时。
- 20,000 次同进程诊断稳定捕获 `parts=0.05 ms`、`total=0.04 ms` 的量化误差样本，证明不是运行时漏记阶段。
- 请求/响应断言改用按阶段数推导的 0.03 ms/0.02 ms 绝对量化容差。
- focused 5 tests、50,000 次压力检查和最终全量 `2,378 passed, 4 skipped` 均通过。

## 仍需人工/真实环境验证

以下不是已确认缺陷，而是本地审计无法替代的验证层：

1. 使用真实 provider credentials 运行 same-format、cross-format、streaming 与错误路径。
2. 按 `AGENTS.md` 运行 `agentabi` 矩阵，尤其是 Responses -> Chat、多轮工具调用与 reasoning/thinking 保留。
3. 在浏览器中检查 Admin 的布局、交互、视觉回归与无障碍状态。
4. 实际运行 GitHub Actions；正式 Release 按现有 runbook 仅通过 GitHub Web UI 手动创建，不涉及 PyPI 或 Docker registry 发布。
5. Owner 审批或完善 `.agent-work/audit/PROFILE.md`，明确生产隐私、SLO、部署拓扑和 SBOM/签名策略。错误诊断的 10,000 条 count-only retention 已按用户口径确定，不再作为待确认项。

## 维护性判断

本轮修改跨 gateway auth、state、persistence、Admin、CI/release 和双语文档，属于高风险多模块修复。新增复杂度集中在三个有明确 ownership 的边界：`GatewayStateScope`、`SecretRedactor` 和安全原子 config writer；它们替代了分散的 partial-key、脱敏和写盘逻辑，没有形成新的平行实现。关键安全/并发/迁移路径均有回归覆盖，完整门禁为绿。当前不建议继续做结构性重写；后续只需在真实 provider、agentabi、浏览器和生产发布环境补齐系统验证。

## 风险排序依据

本轮先处理可远程触发的凭证/配置接管、XSS、跨 principal 数据污染和落盘 API token，再处理配置 crash/lost-update、Python/CI 合同、容量边界与发布可追溯性。排序综合用户影响、可利用性、发生概率、爆炸半径、可逆性、证据强度、系统性程度和修复成本，而不是按文件大小或代码行数判断。
