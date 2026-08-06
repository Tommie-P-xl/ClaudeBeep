# 更新日志

本文件记录 ClaudeBeep 的历次版本更新内容。

## [Unreleased]

### 修复
- **严格单实例**：托盘进程在原有 Windows 互斥体之外，新增按用户目录的文件独占锁（`%APPDATA%\ClaudeBeep\tray.lock`），即使全局互斥体因权限/会话隔离失效，多个托盘实例也无法并存。Web UI（`--ui`、托盘菜单、`app.py`）启动前先探测 `127.0.0.1:5100`：已有本应用 UI 服务则直接复用并打开浏览器，不再重复启动 Flask 进程；端口绑定竞态时同样回退复用。hook / install / test 短生命周期进程有意豁免（必须允许并发）。

## [v2.2.0] - 2026-08-06

### 安全
- **日志脱敏**：所有日志统一走 `common/log.py`，`bot_token`/`context_token`/`app_secret`/`user_id` 等凭据写入 `notify.log` 前自动打码；hook 上下文只记录字段名与值长度，不再记录明文值。
- **Web UI 本地访问防护**：`/api/*` 拒绝非回环 Host 请求（阻断 DNS Rebinding），写方法要求携带 `X-Requested-With: XMLHttpRequest` 头（阻断跨站请求）；前端 `api()` 封装已自动附带。
- **更新完整性校验**：更新器下载 EXE 后按 `latest.json` 发布的 SHA256 校验，不匹配即中止；standalone 替换改为"延迟替换脚本"（运行中的 exe 在 Windows 上无法 rename 自身）。
- **配置写入加固**：`update_config` 新渠道分支不再绕过敏感字段保护，前端元字段（如 `configured_secrets`）不再被持久化。

### 数据与路径
- **运行时数据迁移到 `%APPDATA%\ClaudeBeep`**（安装/frozen 模式）：`config.json`、`notify.log`、`pending/`、`responses/`、`send_queue/`、心跳与 token 缓存不再位于 Program Files；安装目录中的旧配置会自动迁移一次；卸载不再删除用户配置。

### 性能
- **跨进程 token 缓存**：QQ / 飞书 / 钉钉的 access_token 落盘缓存（带过期时间），hook 冷启动直接复用，不再每次事件都重复换取。
- **托盘统一持有渠道连接**：托盘进程常驻持有 Telegram / QQ / 飞书 / 钉钉的长连接（微信 keepalive 原本如此），hook 进程通过心跳中的 `managed_channels` 检测后跳过临时建连。

### 修复
- `write_response` 改用硬链接原子创建，"先到先生效"跨平台成立（POSIX 下 `rename` 会静默覆盖）。
- QQ OpenID 捕获在 token/gateway 获取失败时不再静默崩溃，界面会明确报错而不是一直转圈。
- 多问题回复仅以 `|` 分隔，中文/英文句号不再误触发多问题解析。
- `/api/logs` 限制返回行数（≤500），防止全量日志被拉取。
- Windows Toast 通知按平台显示正确应用名（Codex 不再显示 "Claude Code"）。
- 清理死代码：`notify_state.py` 模块、`_process_message_global`、`_send_winotify`、`NOTIFY_HOOK_EVENTS`。

### 架构与维护
- 新增渠道注册表 `common/channels_registry.py`，作为渠道元数据与工厂的唯一来源。
- `listener.py`（1072 行）拆分为 `listeners/` 包（协调层、各渠道监听器、捕获流程）；`listener.py` 保留为兼容转发层。
- `notify.main()` 拆分出 `notify_cli.py`（参数解析）与 `hook_flow.py`（hook 上下文解析/过滤）。
- 版本号单一来源 `version.py`；`build.ps1` 注入 PyInstaller 资源与 Inno Setup 安装包。
- 新增 35 个单元测试（`tests/`），覆盖回复解析、hook 所有权判定、配置迁移、凭据脱敏、托盘菜单解码。

## [v2.1.0] - 2026-04

- **修复**：所有渠道凭证端点（扫码登录、验证、登出）现在正确持久化到规范配置路径 — 修复了 v2.0.0 引入的静默数据丢失问题
- **配置缓存**：`load_config()` 采用 mtime 缓存，减少每次 API 调用的重复磁盘读取与深拷贝
- **并发**：`atomic_write_json()` 增加文件锁，防止并发写入导致数据丢失
- **Telegram 默认关闭**：新安装默认不再启用 Telegram 通知
- **SSE 退出竞态**：修复标签页快速开关导致应用提前退出的竞态
- **Codex 适配器**：修复 payload 字段为 null 时 `str(None)` 产生字面 "None" 的问题
- **TOML 清理**：修复 Windows 路径分隔符不匹配导致 Codex hook 状态清理失败
- **TOML 原子写**：`~/.codex/config.toml` 清理改用原子写防损坏
- **Hook 去重**：改进 shlex 解析，防止畸形命令导致 hook 重复
- **代码清理**：移除 notify.py 中废弃包装函数、未用导入与冗余配置间接层
- **类型安全**：全库以 `isinstance()` 取代 `type(x) is not bool`

## [v2.0.0] - 2026-01

- Codex 对等集成，独立平台控制
- 集中配置管理（config_store.py）
- Hook 所有权跟踪（hook_manager.py）
- 通知投递边界（notification_core.py）
- 原生 Win32 托盘菜单，支持深色模式

[Unreleased]: #
[v2.2.0]: https://github.com/Tommie-P-xl/ClaudeBeep/releases/tag/v2.2.0
[v2.1.0]: https://github.com/Tommie-P-xl/ClaudeBeep/releases/tag/v2.1.0
[v2.0.0]: https://github.com/Tommie-P-xl/ClaudeBeep/releases/tag/v2.0.0
