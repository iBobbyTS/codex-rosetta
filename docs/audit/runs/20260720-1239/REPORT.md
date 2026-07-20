# 遗漏修复复审报告

## 结论

本轮发现的四个逻辑/控制缺口均已修复并独立提交；AUD-009 与 AUD-011 的业务语义已按项目所有者决定重新冻结。完整 lint 与非集成测试通过，没有执行真实 API 调用。当前未发现还需要所有者决定的新增事项。

## 已修复的逻辑问题

- **AUD-012：禁止上游重定向。** HTTP 客户端可自动跟随的重定向状态在第二次请求前失败，避免 provider Authorization 被带到重定向目标；独立 loopback target 验证未收到请求。
- **AUD-006：示例真实调用门禁。** 24 个 REST/SDK 示例都在 `load_dotenv()` 前要求开发者显式批准；测试自动扫描目录，新增示例不会因静态名单遗漏。
- **AUD-010：SQLite 索引形状。** 除列顺序外，启动校验现覆盖 `unique`、`origin`、`partial`，不兼容数据库 fail closed。
- **AUD-008：审计账本。** 唯一 profile、findings、coverage、system map、README 和本轮证据已对齐代码基线 `804efef`。

## 已冻结的业务语义

- **AUD-009：缺少 `api_type`。** 运行时按精确 preset URL 支持情况和 `responses -> chat -> anthropic -> google` 顺序选择；custom URL 默认 Responses。每次加载对每个启用 provider 打一条 WARNING。推断值只进入运行时副本和 Admin 响应，不写回 config。
- **AUD-011：custom URL。** 任意 HTTP(S) custom URL 的直接出站与 API-key 交付风险仍在本机/内网边界内接受；重定向不在接受范围内，始终禁止。
- **AUD-013：不立项。** 缺少或禁用 provider 的 model group 继续静默跳过；当前规模下不增加新的校验和错误传播状态机。

## 未验证

真实 provider/Codex 行为、浏览器与 LAN 部署、Docker、恢复、长期容量、DNS/proxy 对抗和公网安全均未验证，也不在本轮承诺内。
