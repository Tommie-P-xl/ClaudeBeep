# 更新日志

本文件记录 ClaudeBeep 的历次版本更新内容。

## [v2.3.0] - 2026-08-07

### 修复
- **渠道 ID 自动捕获不再静默丢失**（严重）：监听器自动捕获的字段（QQ `target_id`、Telegram `chat_id`、飞书 `receive_id`、钉钉 `user_id`、微信 `context_token`/`to_user_id`）此前写入 `config.json` 顶层遗留镜像，而镜像会在下次加载时被 canonical `channels.*` 重建覆盖——捕获的值在下一次读取时即消失。所有捕获路径统一改用新的事务式 `config_store.update_channel_fields()`，在文件锁内写入 canonical 存储。
- **微信扫码登录不再永久悬挂**：状态轮询循环增加每张二维码 3 分钟的总时限；此前若用户始终不扫码，登录线程会无限轮询，且后续所有登录请求都被"登录流程已在进行中"拒绝。
- **微信 keepalive 热循环**：持续返回 `ret=-2`（context_token 过期）时现在计入失败退避，不再全速空转请求 iLink API。
- **非 ASCII 用户目录下自动更新失败**：延迟替换批处理脚本改用系统 ANSI 代码页（`mbcs`）写入（此前固定 ASCII，中文用户名路径必抛 `UnicodeEncodeError`）；仍无法编码时回退提示手动更新。
- **单实例误报**：托盘互斥体检查改用 `WinDLL(use_last_error=True)` 语义，文件锁为唯一权威判定——被覆盖的 `GetLastError()` 不再错误阻止启动。
- **交互健壮性**：请求标签分配改为文件锁保护（并发 hook 此前可能拿到重复标签导致回复串号）；渠道回复监听先于通知发送启动，慢发送不再压缩可回复窗口；超过 24 小时的残留 pending 请求一律清理（Windows PID 复用此前会导致永不清理）；响应轮询间隔 2s → 0.5s。
- **Hook 同步加固**：`settings.json` 中非 list 的畸形 `hooks.<event>` 条目改为重置而非 `AttributeError` 崩溃；Codex `config.toml` 清理不再因空行提前结束跳过段（残留键会挂靠到前一个段），并在写入前保留 `.bak` 备份。
- **其他小修复**：QQ 监听器在握手非 `READY` 时中止；token 缓存临时文件改唯一名（并发刷新会互相截断）；`/api/config` PUT 对非对象 JSON 返回 400 而非 500；`/api/weixin/qr/status` 仅在 token 变化时写盘（此前每 2 秒轮询都全量重写配置）；Flask `secret_key` 跨重启持久化；多问题回复分隔符的过期注释更正。

### 安全
- **Toast 脚本注入面闭合**：`windows_toast.duration_ms` 拼入 PowerShell 脚本前强制转为受限整数。
- **更新完整性**：更新元数据缺少 SHA256 时，更新器要求用户显式确认后才下载/安装。
- **日志卫生**：渠道 HTTP 响应体写日志前剔除 token；过短 ID（≤5 字符）不再全文替换（避免误伤错误信息）。
- 请求 ID 改用 `secrets` 替代 `random`。

### 性能
- **多渠道并行投递**：`notification_core.send_event` 并发分发各启用渠道——慢渠道（网络超时、PowerShell 冷启动）不再拖累其他渠道。
- **日志内置轮转**：`notify.log` 超过约 1MB 时自动保留尾部约 512KB（在 `common.log` 内完成，不再依赖托盘定期清理）；`/api/logs` 改为从文件尾部读取，不再全量加载。
- 微信 `sync_buf` 仅在变化时持久化；`should_run_weixin_keepalive` 与遗留迁移检查在配置已迁移时跳过冗余深拷贝。

### 维护
- 新事务式配置 API：`config_store.update_config(mutator)` 与 `update_channel_fields()` 在文件锁内完成完整的读-改-写（此前只有写入瞬间持锁）。
- 清理死代码：`notify.py` 中 7 个未使用的 `hook_flow` 导入、`_load_permissions_allow` / `_load_project_settings` / `_find_claude_dir` 调用链；`requirements.txt` 移除未使用依赖（`winotify`、`pystray`、`pillow`）。
- 新增 4 个单元测试（共 44 个），覆盖 canonical 写入持久化（H1 回归）与并发写不丢更新（M4 回归）。

## [v2.2.1] - 2026-08-06

### 修复
- **严格单实例**：托盘进程在原有 Windows 互斥体之外，新增按用户目录的文件独占锁（`%APPDATA%\ClaudeBeep\tray.lock`），即使全局互斥体因权限/会话隔离失效，多个托盘实例也无法并存。Web UI（`--ui`、托盘菜单、`app.py`）启动前先探测 `127.0.0.1:5100`：已有本应用 UI 服务则直接复用并打开浏览器，不再重复启动 Flask 进程；端口绑定竞态时同样回退复用。hook / install / test 短生命周期进程有意豁免（必须允许并发）。
- **自动更新替换竞态**（修复更新后偶发的 "Failed to load Python DLL" 弹窗）：延迟替换脚本现在会先等待**所有**旧 ClaudeBeep 进程退出（包括持有 exe 句柄的 Web UI 子进程），再进行重命名/复制——等待超 20 秒则安全中止并保留现场，替换失败时自动从备份恢复；复制完成后额外等待 3 秒再启动新 exe，避免杀软实时扫描锁定刚写入的二进制导致 onefile 引导器解压失败（`_MEI\python311.dll`）。托盘退出时也会主动终止自己启动的 Web UI 子进程，确保开着管理面板也能正常更新。

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

[v2.3.0]: https://github.com/Tommie-P-xl/ClaudeBeep/releases/tag/v2.3.0
[v2.2.1]: https://github.com/Tommie-P-xl/ClaudeBeep/releases/tag/v2.2.1
[v2.2.0]: https://github.com/Tommie-P-xl/ClaudeBeep/releases/tag/v2.2.0
[v2.1.0]: https://github.com/Tommie-P-xl/ClaudeBeep/releases/tag/v2.1.0
[v2.0.0]: https://github.com/Tommie-P-xl/ClaudeBeep/releases/tag/v2.0.0
