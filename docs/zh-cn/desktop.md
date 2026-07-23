# Web 管理界面与桌面应用

Codex-Rosetta 在浏览器和 Tauri 2 桌面壳中使用同一套 Svelte 5 管理界面。
Python 仍是鉴权、配置、Provider 凭据、模型路由和上游请求的唯一所有者。

## Web 与内网使用

按现有方式启动 Gateway 后打开 `/admin`。`/admin/providers`、`/admin/logs`
等深链接可以直接刷新。内网部署继续使用 Gateway 配置的监听地址，以及现有的
Admin 密码和 Gateway API key 控制。

支持边界仍然只有本机和可信内网。不承诺公网账户安全、可用性或数据恢复。
产品只有一个 Admin，可以配置多个 Gateway API key，但不是多用户系统。

## 桌面端首次启动

桌面应用只管理它自己启动的回环 Gateway sidecar。首次启动时先要求输入非空
Admin 密码，然后单独询问是否启用 Codex local mode。启用后会修改本机 Codex
配置和模型目录；拒绝则不修改 Codex Home。

sidecar 在 `127.0.0.1` 完成监听并通过 `/health/live` 后，应用才打开与 Web
部署相同的 `/admin` 页面。Admin 窗口没有 Tauri IPC capability。桌面应用不能
连接已有或远程 Gateway，也不会把它管理的 Gateway 暴露到内网。

## 排障

- 端口冲突表示配置的稳定桌面端口已被占用。应用会 fail closed，不会打开该端口
  上身份不明的服务。
- 配置错误需要在桌面应用自己的配置目录修复；应用不会静默覆盖已有配置。
- 关闭应用时只请求优雅停止它自己持有的 sidecar，不会按进程名、PID 文件或端口
  扫描并终止其他进程。
- 桌面 release 只能手动执行，没有自动更新或后台自启动服务。

当前仓库只验证了 macOS arm64 开发构建。缺少平台签名和公证的产物只能称为开发
构建，不能称为正式 release。
