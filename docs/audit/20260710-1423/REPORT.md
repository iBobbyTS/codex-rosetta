# Codex-Rosetta 第 15 轮代码审计报告

审计时间：2026-07-10 14:23–14:49 America/Edmonton  
审计画像：`.agent-work/audit/PROFILE.md`（`Draft`）  
完整台账：`.agent-work/audit/20260710-1423/FULL.md`

结论：**第 15 轮发现的 1 条“必须修复”安全问题已经解决，本轮无未关闭 finding。** 修复保持在 Admin DOM 渲染与回归测试边界内；没有 stage、commit、push、PR、release 或 deploy。

## 审计验证

- **仓库状态已检查：是。** `master` 比 `origin/master` ahead 1，HEAD 为 `eb94742`；有 97 个 tracked 修改文件、31 个非忽略 untracked 文件，无 staged diff。tracked diff 为 9,091 行新增、1,610 行删除；`git diff --check` 最终通过，`codegraph sync` 成功同步本轮 7 个 changed files。
- **差异与当前源码已审阅：是。** 本轮从前序 quota/persistence 修复向外独立抽样 Admin browser trust boundary、模型测试 self-call、embedding raw passthrough、入站 HTTP/header envelope、request correlation header 和 Admin credential/CSP。
- **审计范围与抽样依据：** 按 Draft profile 将外部 provider 响应视为不可信输入，追踪其从 upstream transport 到 self-call task、Admin JSON、DOM sink 和 Admin token 的完整路径；用前 14 轮台账避免重复包装已修复或已接受问题，但结论以当前源码为准。
- **关键质量属性：** 安全、协议正确性、跨请求隔离、可靠性和可维护性。
- **已运行测试：** `make lint` 通过（Ruff、291 files format check、`ty`）；`make test` 收集 **2,723** 项，结果为 **2,718 passed, 5 skipped, 9 warnings**。新增 opt-in browser 模块相对修复前正好增加 1 个普通 pass 和 1 个默认 skip。
- **真实浏览器回归：** `RUN_ADMIN_BROWSER_TESTS=1 conda run -n llm-rosetta python -m pytest tests/gateway/test_admin_model_usage_browser.py -vv -s` 在 Chromium `149.0.7827.201` 下输出 `DOM_ASSERTIONS_OK`。HTML/SVG/closing-script、Unicode/control、对象、数组、自定义 coercion、`NaN`、Infinity、负数和 unsafe integer 均不能创建元素、执行事件、读取 Admin token、发起 stubbed exfil fetch 或触发 coercion；合法 safe integer 与五类 provider usage shape 精确显示。
- **构建与兼容门禁：** `make build`、`make check-codex-compat`、`make check-release-version RELEASE_TAG=v0.144.0.r0` 均通过。Codex source commit 为 `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`，Changed 为 None，12 组 Possibly unchanged 保留文档规定的真实 API 验证义务。
- **运行态验证：** headed Chromium 完成真实 Admin 登录并渲染 `/admin/providers`；隔离 Compose 用当前 wheel 启动，`/health` 与 `/admin` 均返回 200，且 `/admin` 保持 `Content-Security-Policy: frame-ancestors 'none'` 和 `X-Frame-Options: DENY`。容器内 `codex-rosetta-gateway --version` 返回 `0.144.0.r0`。浏览器、gateway、Compose project 和临时配置均已清理，用户原有的 8765 gateway 未被停止。
- **测试限制：** 未运行 credentialed external provider/agentabi matrix、外部 GitHub Actions、漏洞/许可证扫描、生产负载、备份恢复演练或真实 release/deploy/rollback。
- **已检查高风险流程：** Admin test task 的 self-call/result retention、embedding raw response passthrough、Responses/embedding 结果渲染、Admin token 存储/发送、CSP、request header/body 限制、window/principal state ownership 与 cleanup。
- **已检查发布/回滚/观测/恢复路径：** 本轮没有改变这些路径；本地 lint/test 通过。外部发布与恢复证据仍是既有人工缺口。
- **假设：** provider endpoint 和其返回 JSON 可能恶意或被攻陷；管理员会使用 Admin 的模型测试功能；Admin token 具备当前路由定义的完整控制面权限。
- **需要人工复核：** Draft audit profile 尚未敲定法律/隐私、ASVS、SLO、事件响应、签名/SBOM 与依赖治理标准；真实外部 provider/agentabi 和生产运维演练仍需其对应凭证与环境。
- **已知过时上下文或冲突证据：** 第 14 轮的 clean 结论未覆盖本轮新追出的 Admin upstream-to-DOM source/sink；其 state/persistence 与全量 gate 结论没有被推翻。

## 主要发现

### 已解决，无需处理：Admin 模型测试的 provider usage DOM XSS

- **修复前证据链：**
  - `src/codex_rosetta/gateway/admin/admin.html:4358` 把 `body.usage.prompt_tokens` 直接拼进 `meta.innerHTML`。
  - `src/codex_rosetta/gateway/admin/admin.html:4365-4367` 同样直接拼接 `input_tokens`、`output_tokens`、`completion_tokens`。
  - `src/codex_rosetta/gateway/embeddings.py:108-129` 对成功 embedding 响应做 raw passthrough；`src/codex_rosetta/gateway/admin/routes/testing.py:113-127` 解析后原样返回 body，没有把 usage 强制为数字。
  - `src/codex_rosetta/gateway/admin/admin.html:1933-1967,2223` 把 `admin_token` 放在 `localStorage` 并用于 `X-Admin-Token`；`src/codex_rosetta/gateway/admin/routes/auth.py:27-31` 的 CSP 只有 `frame-ancestors 'none'`，不会阻止 inline event handler。
- **原触发路径：** provider 对成功 embedding 或 Responses 测试返回类似 `{"usage":{"prompt_tokens":"<img src=x onerror=...>"}}` 的 JSON，管理员点击对应模型的 Test。修复前该字符串会进入 `innerHTML` 并在 Admin origin 执行；当前 sink 已不存在。
- **原影响：** 同源脚本原可读取 Admin token，并调用 config、API key reveal/rotate、internal token、日志/错误转储等控制面 API。当前局部 DOM 修复已切断 provider response 到可执行 HTML 的路径。
- **修复：** `src/codex_rosetta/gateway/admin/admin.html:4118-4165` 使用 `createElement`、`textContent`、`createTextNode` 和 `replaceChildren` 构造 test meta；`runTest()` 不再写 `meta.innerHTML`。token count 仅接受非负 `Number.isSafeInteger()`，primary 字段存在但非法时不会 fallback。
- **验证：** `tests/gateway/test_admin_page_routes.py:112` 固化安全 sink 契约，`tests/gateway/test_admin_model_usage_browser.py:47` 用真实 Chromium 覆盖 embedding、Responses、OpenAI Chat fallback、Anthropic 和 Google usage shape 及恶意值。事件执行、token 读取、fetch 与 coercion 计数均为 0。
- **残余说明：** 当前 CSP 仍主要提供 anti-framing。nonce/hash CSP 可作为后续纵深防御，但原始可利用 sink 已移除，因此不再保留为开放 finding。

### 无需处理

- `x-request-id` 未单独规范化，但入站 header 已有 64 KiB aggregate envelope，LF 不能作为同一 header value 穿过解析边界；本轮没有确认高影响 response-splitting 或资源爆炸路径，因此不把它升级为新 finding。
- 前轮 window/provider metadata/encrypted mapping 的 principal quota、transaction、TTL 和 cleanup owner 在当前源码与全量测试中仍成立；未发现新的独立回归。

## 整体健康状况

Gateway 的状态 owner、持久化预算、HTTP/SSE envelope 和完整本地测试门禁仍然稳固；本轮最高风险的 Admin source-to-sink 漏洞已用局部 DOM 修复和真实 Chromium 回归关闭。第 15 轮当前无未关闭 finding；下一轮建议继续抽样 Admin 其他动态渲染边界与外部 provider/agentabi 真实契约，而不是扩张本次局部修复。

## 风险排序依据

本报告按凭证/配置安全、用户触发概率、外部信任边界、blast radius、可逆性、证据强度、系统性和修复成本排序。F-01 原本具备直接 source-to-sink 与完整 Admin 能力，故优先修复；当前源码、真实 Chromium 与运行态证据共同支持将其改为“已解决/无需处理”。低证据 header hardening 和既有治理缺口没有被包装成同级新问题。

维护性判断：F-01 沿用现有 DOM/text rendering owner 做局部修复，未引入新前端框架、依赖、服务端 schema 或平行状态 owner；源级与真实浏览器回归覆盖了高风险边界，无需后续结构性清理。
