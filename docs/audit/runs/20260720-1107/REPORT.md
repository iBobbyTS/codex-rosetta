# 修复复审报告

## 结论

本轮针对遗漏审计发现的 AUD-003、AUD-005、AUD-006、AUD-007、AUD-008、AUD-009、AUD-010、AUD-011 已完成修复或语义冻结。确定性测试和 lint 通过，审计 ledger 已按本轮证据统一。

## 可以直接修复的逻辑/控制问题

- **AUD-003 / AUD-006：真实调用入口门禁**。已覆盖 SDK/REST、agentabi、relay 和 Codex/Claude/OpenCode 启动路径；所有入口在凭据、进程和网络工作前共享 exact-marker fail-closed gate。新增 contract tests 验证入口清单和拒绝路径。
- **AUD-007：Admin profile 派生**。UI 使用 API 返回的运行时派生 profile，不再读取已剥离的 provider 元数据；URL/protocol 规则与后端一致，且选项不写回 config。
- **AUD-008：审计 ledger 不一致**。本轮同步 findings、coverage、system map、run evidence 和 rotation queue，移除已关闭 finding 的待办状态。
- **AUD-010：SQLite schema 形状校验**。启动时同时校验列名、类型、NOT NULL、主键位置和必要索引列顺序；不兼容数据库 fail closed，并有回归测试。

## 已冻结的业务语义

- **AUD-005**：URL 是 provider 选项的权威；精确匹配 preset 时渲染 preset，未匹配时渲染协议对应的 `custom`，允许保存。provider 选项不持久化，config 只保存 URL 等权威字段。
- **AUD-009**：缺少 `api_type` 是无效配置，不按 provider 名称回退。Gateway 拒绝激活该 provider；Admin provider 卡片和所有引用它的 model group 显示 `validation_error`。
- **AUD-011**：接受任意 HTTP(S) custom URL 的出站和 API-key 传递风险，边界限定为本机/内网部署；不作公网 SSRF、账户安全或 provider 质量承诺。

## 未验证与后续触发

本轮没有真实调用、部署、浏览器/LAN、Docker、恢复、可用性或公网验证。后续若新增 live 入口、改变 provider URL 语义、改变 `api_type` 契约、扩展部署边界或引入迁移层，应重新打开相应 finding 并触发 targeted audit。
