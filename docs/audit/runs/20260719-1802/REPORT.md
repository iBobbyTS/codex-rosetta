# 报告 — 遗漏审计

## 结论

独立 subagent 发现 6 项遗漏：4 项可直接修复的逻辑/审计控制问题，2 项需要项目负责人冻结/明确语义后才能修复。上一轮 AUD-003 与 PROVIDER-01 不能继续保持“完全关闭”表述，应分别重开或降级为部分关闭。

## 可直接修复的逻辑/控制问题

### AUD-006：真实调用门禁没有覆盖全部 integration/live 入口

- 严重性：Should Plan；在首次允许开发 live run 前建议 Must Fix。
- 可达路径：`tests/integration/test_*_e2e.py` 直接读取 provider API key 并构造 SDK/REST client；`test_gateway_agentabi.py` 调用 `agentabi.run_sync`；`tests/integration/gpt_relay/run.py` 启动 capture proxy/Codex harness。这些路径没有调用 `require_live_call_approval()`。
- 违反约束：用户要求开发者批准 agent 执行产生真实 API 调用，audit 不产生真实调用。
- 最小建议：把共享 exact-marker gate 放到每个真实调用入口的最早位置，在读取凭据、创建 run root、启动子进程之前执行；覆盖 SDK/REST、agentabi、gpt-relay，以及 `scripts/rosetta-test-claude-code.sh`、`rosetta-test-opencode.sh`、`rosetta-test-kilo.sh` 等 agent 启动脚本；为每类入口加 fail-closed contract test。更新 AUD-003 为 Reopened/Partially closed。

### AUD-007：Admin 新建/切换 model group 时仍可能错误选择 Responses tool profile

- 严重性：Should Plan。
- 可达路径：API 返回配置时去掉 `provider`；Admin `_defaultToolProfileForProvider()` 仍读取 `provider.provider`。官方 OpenAI Responses provider 从 API 加载后会走 `responses-tool-mapping`，而不是 `openai-responses-tool-mapping-only`；自定义 Responses URL 在当前分支也会落到 `responses-tool-mapping`，而不是后端 URL 规则要求的 `web-run-injection`。
- 最小建议：在浏览器端按 `api_type + base_url` 的同一 URL 规范化/精确 preset 规则推导 profile，或由 API 返回明确的运行时派生 profile（不写回 config）；增加 UI/contract test 覆盖官方 URL、已知 preset、custom URL 和切换 provider。

### AUD-008：审计 coverage ledger 与已关闭结论自相矛盾

- 严重性：Should Plan。
- 可达路径：`docs/audit/COVERAGE.md` 顶部和 `FINDINGS.md`/run report 说 AUD-001/002/003 已关闭，但 `CTRL-06` 仍为 `Unknown / gap`，Due Rotation 仍把 AUD-001/002/003 当作待处理 P0。这会让后续审计无法判断当前有效状态。
- 最小建议：重开 AUD-003 后同步更新 coverage/control/rotation；删除已完成事项的旧待办，或显式标记为历史快照并加日期/适用范围。

### AUD-010：SQLite schema 校验只检查列名，不检查约束与索引

- 严重性：Should Plan。
- 可达路径：`PersistenceManager._init_tables()` 使用 `CREATE TABLE IF NOT EXISTS`，`_validate_schema()` 只比较 `PRAGMA table_info()` 的列名集合；一个拥有相同列名但缺少复合主键/唯一约束或索引的旧数据库会通过启动校验，随后 `ON CONFLICT(principal_id, token_hash)` 可能在第一次 compaction 写入时失败。
- 最小建议：为每张关键表建立 schema fingerprint/约束索引 contract test，至少验证主键、NOT NULL、列类型和必要索引；不兼容时在启动阶段拒绝。若项目负责人有意只保证列集，则必须把该限制写入 profile 并接受运行时失败风险。

## 需要负责人决定的业务语义

### AUD-009：缺少 `api_type` 时是否允许按 provider 名称回退

- 严重性：Needs Decision / Should Plan。
- 事实：`resolve_provider_config_type_and_shim()` 仍允许已知 provider 名称在缺少 `api_type` 时决定协议；示例配置也存在不写 `api_type` 的 provider。
- 冲突：当前约定是 URL 作为 provider 选项权威，`api_type` 是必要的传输协议字段；名称回退会形成第二权威，且 Admin 已剥离名称字段后可能把旧配置渲染成 Chat。
- 需要决定：
  1. 要求所有 provider 显式写 `api_type`，拒绝名称回退并更新 examples/测试；或
  2. 明确名称回退是当前协议兼容例外，保留它并补充 API/UI 显示、保存和审计文档。

### AUD-011：允许任意 custom URL 时的出站/SSRF 风险边界未写清

- 严重性：Needs Decision / Should Plan。
- 事实：当前语义允许未命中 preset 的 HTTP(S) URL 作为 custom 放行；Gateway 会向该 URL 发起上游请求并携带 provider API key。这个行为符合目前“custom 允许放行”的决定，但会把内网地址、云元数据地址或其他非预期 HTTP(S) 端点纳入出站范围。
- 需要明确：接受“任意 HTTP(S) custom、由本机/内网部署边界自行承担 SSRF 风险”，或增加 host/网段 allowlist 与私网/元数据地址阻断。若继续允许任意 custom，应在 profile 中把该风险写成明确的 owner acceptance，而不是暗示上游仅限 preset provider。

## 未审计/证据缺口

- 本轮没有真实 provider/Codex/agentabi 调用，因此不判断上游质量、出网行为、可用性或数据恢复。
- 没有浏览器、内网部署、Docker/Compose、备份恢复或 GitHub 远端设置证据。
