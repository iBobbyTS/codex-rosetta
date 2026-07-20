# 本轮修复审计报告

## 结论

本轮授权的四个可修复问题均已完成代码修复并通过当前确定性测试：AUD-001、AUD-002、AUD-003、AUD-005 可关闭。AUD-004 继续作为项目所有者接受的供应链技术债，不在本轮修复。

AUD-001 的运行时迁移/回填入口已关闭；`persistence.py` 中仍有两组私有、不可达的历史 mapping-migration 定义，属于可单独删除的维护性清理，不参与启动或运行时路径。

这里的“通过”仅表示源码、单元测试和本机确定性检查通过；不表示真实 Codex/provider 行为、内网部署、可用性、数据恢复或公网安全得到承诺。

## 按责任归属

### 我可以直接修复的逻辑/控制问题

- AUD-001：启动时拒绝旧 Rosetta 配置/状态/内部别名，不保留迁移层；保留显式的当前协议 `api_type`。
- AUD-002：compaction replacement 增加单条、principal、全局 row/byte 限制，并在同一事务中清理、核算、写入。
- AUD-003：live/integration runner 在读取凭据、创建运行目录或启动进程前必须通过精确的开发者批准标记。

### 需要业务语义决定的问题

- AUD-005 的决定已由本轮 owner 输入冻结：URL 是 provider 选项的唯一权威；精确命中预设 URL 时渲染预设，未命中时渲染 `custom` 并允许保存。`api_type` 仅保留为传输协议选择，因为同一 URL 可能承载 Chat 或 Responses。
- AUD-004 仍由 owner 决定是否在未来扩展为公网/更强发布承诺后引入 digest pinning、SBOM、provenance、signing。

## 未验证项

真实上游调用、agentabi、部署运行时、浏览器反代、Docker/Compose、备份恢复、HA/SLO/RTO/RPO、GitHub 远端权限和供应链证明均未运行或承诺。
