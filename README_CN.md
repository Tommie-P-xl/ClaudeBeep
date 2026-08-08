# ClaudeBeep v2.3.2

<p align="center">
  <img src="assets/icon.png" width="128" alt="ClaudeBeep Logo">
</p>

<p align="center">
  <strong>面向 Claude Code 与 Codex 的 Windows 系统托盘通知应用</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-v2.3.2-blue" alt="Version">
  <img src="https://img.shields.io/badge/python-3.10+-green" alt="Python">
  <img src="https://img.shields.io/badge/platform-Windows-lightgrey" alt="Platform">
  <img src="https://img.shields.io/badge/license-MIT-brightgreen" alt="License">
</p>

<p align="center">
  中文 | <a href="README.md">English</a>
</p>

---

ClaudeBeep 是一个将 Claude Code 和 Codex 作为对等集成的 Windows 系统托盘应用。两个平台分别拥有独立的平台开关、hook 事件和投递渠道选择，同时共用一套渠道凭证。只需安装实际使用的平台；未安装的集成不会增加 hook 或运行时开销。

## 功能

### 系统托盘

- **打开主界面** — 启动 Web UI，用于详细渠道配置、扫码登录和日志查看。
- **对等平台菜单** — Claude Code 与 Codex 在托盘中分别提供独立的平台和渠道控制；未配置的渠道会置灰。
- **开机自启动** — 通过 Windows 注册表（`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`）切换开机自启。
- **检查更新** — 查询 GitHub Releases 最新版本；如有新版，下载后先按 `latest.json` 发布的 SHA256 校验，通过后再应用。Setup 安装包静默安装；独立 exe 通过延迟替换脚本完成（无需卸载）。若自动更新失败，回退到打开下载页面。
- **系统深色模式** — 自动检测 Windows 系统主题，为托盘菜单应用深色模式样式。
- **Web UI 主题** — 支持明亮 / 暗夜 / 跟随系统三种主题模式，默认跟随系统。主题偏好自动保存。
- **高清托盘图标** — 256×256 高分辨率图标，在高 DPI 屏幕上清晰显示。
- **高 DPI 感知** — 通过应用清单（manifest）声明 Per-Monitor V2 DPI 感知，解决高分屏下托盘菜单文字模糊问题。
- **SVG 图标** — 仪表盘和各配置页面使用内联 SVG 矢量图标，清晰不失真。
- **退出** — 停止所有后台服务并退出。

### 对等集成

- **Claude Code** — 完成、权限和询问事件继续使用原有交互流程；审批选项和自由文本回复仍可来自终端或已配置的远程渠道。
- **Codex** — 完成及权限/需关注事件会发送通知，但审批和回答始终留在 Codex 内完成。安装 Codex hooks 后，请在 Codex 中运行 `/hooks`，检查并确认信任提示。
- **独立控制** — Web UI 和托盘均可分别设置 Claude Code 与 Codex 的平台开关、事件选择和投递渠道。
- **共享投递** — 渠道凭证只配置一次，由两个集成共同使用。任一已启用平台使用微信时，托盘只维护一个共享 keepalive，而不是每个平台各建一条连接。
- **未安装即无开销** — 未安装 hooks 的平台不会启动对应适配器，也不会为该平台增加处理工作。

### 通知渠道

| 渠道 | 协议 | 保活机制 | 回复监听 |
|------|------|----------|----------|
| Windows Toast | WinRT（带应用图标） | 无（发后即忘） | 不适用 |
| 微信 ⚠️ 不推荐 | iLink Bot API | 托盘进程管理的 `getupdates` 长轮询 | keepalive 循环中直接分发 |
| QQ Bot | QQ 开放平台（OAuth2 + c2c/群） | 托盘进程管理 WebSocket | `listeners/` WebSocket |
| Telegram | Telegram Bot API | 托盘进程管理长轮询 | `listeners/` 长轮询 |
| 飞书/Lark | 飞书开放平台（OAuth2） | 托盘进程管理 WebSocket | `lark_oapi` WebSocket |
| 钉钉 | 钉钉开放平台（OAuth2） | 托盘进程管理 Stream | `dingtalk_stream` |

### 交互式回复

当 Claude Code 提出问题（PermissionRequest / Elicitation）时，ClaudeBeep 向所有已启用渠道发送带编号选项的格式化通知。用户可从以下位置回复：
- 终端（直接键盘输入）
- 任意远程渠道（微信、QQ、Telegram、飞书、钉钉）

先到先得。响应通过硬链接原子创建（`O_EXCL` 语义）写入，跨平台保证“先到先生效”。渠道监听由托盘进程常驻持有（`listeners/` 包），hook 进程直接复用，不再每次临时建连。Codex 的权限通知只用于提醒；审批和回答输入仍在 Codex 内完成。

### 安全与可靠性

- **Web UI 本地防护** — 管理界面绑定 `127.0.0.1`，拒绝非回环 Host 请求（阻断 DNS Rebinding）；写接口要求 `X-Requested-With` 头，阻断跨站请求。
- **日志脱敏** — 凭据与 hook 载荷值在 `notify.log` 中自动打码，只记录字段名与长度。
- **更新完整性校验** — 下载的安装包先按 SHA256 校验再安装。
- **多实例防护** — Windows 全局互斥体（`Global\ClaudeBeepTray`）防止重复启动托盘进程。
- **自动清理** — 后台循环每 12 小时（可配置）运行一次，清理日志、过期的 pending/response 文件和队列残留。删除前检查文件是否仍被使用。
- **心跳监控** — 每 15 秒写入 `tray_heartbeat.json`，包含 PID 和渠道状态，支持跨进程协调。
- **优雅降级** — 如果 keepalive 进程未运行，微信回退到直接 HTTP 发送；如果某个渠道失败，其他渠道仍可送达。

## 架构

```
┌────────────────────────┐     ┌────────────────────────┐
│ Claude Code            │     │ Codex                  │
│ ~/.claude/settings.json│     │ ~/.codex/hooks.json    │
└───────────┬────────────┘     └───────────┬────────────┘
            ▼                              ▼
┌────────────────────────┐     ┌────────────────────────┐
│ Claude 适配器          │     │ Codex 适配器           │
│ 支持交互式回复         │     │ 仅发送通知             │
└───────────┬────────────┘     └───────────┬────────────┘
            └──────────────┬───────────────┘
                           ▼
                ┌─────────────────────┐
                │ notification_core   │
                │ 投递边界            │
                └──────────┬──────────┘
                           ▼
       Windows Toast / 微信 / QQ / Telegram / 飞书 / 钉钉

两个适配器彼此隔离，仅在投递层汇合；渠道凭证、托盘管理的微信
keepalive 和各渠道投递实现由它们共享。
```

### 微信 iLink 协议深度解析

iLink Bot API 采用**双层令牌架构**：

| 层级 | 令牌 | 作用域 | 生命周期 | 传输位置 |
|------|------|--------|----------|----------|
| 身份层 | `bot_token` | 全局设备级认证 | 长效（直到重新扫码） | HTTP Header |
| 路由层 | `context_token` | 单次对话消息路由 | 短效（不活跃时过期） | HTTP Body |

**关键协议行为：**

1. **会话绑定** — iLink 服务器将 `bot_token` 绑定到维护 `getupdates` 的 TCP 连接。来自不同进程/连接的发送请求会被静默拒绝，返回 `ret=-2`。

2. **`ret=-2` 语义歧义** — 此错误码被重载：可能表示 `context_token` 过期、参数错误，或跨进程会话不匹配。`errmsg` 字段不可靠（有时为 `"unknown error"`，有时为空）。

3. **无令牌降级重试** — 当 `context_token` 过期时，从请求体中剥离它并重试可能成功。这是协议级别的"降级发送"机制。

4. **`errcode=-14`** — 唯一真正的会话过期信号。需要重新扫描二维码。

**ClaudeBeep 的微信策略：**

- 托盘进程拥有 `getupdates` 长轮询循环，维护活跃的 TCP 会话。
- 当 hook 进程调用 `send()` 时，消息被写入 `send_queue/` 作为 JSON 文件入队。
- keepalive 循环消费队列，通过自身的 HTTP 连接发送消息（同进程、同会话绑定）。
- 遇到 `ret=-2`：清除缓存的 `context_token`，不带 token 重试（无令牌降级）。
- 遇到 `errcode=-14`：禁用渠道，标记会话过期，提示重新登录。
- `context_token` 和 `to_user_id` 从入站消息动态更新 — 不依赖静态配置。

## 安装

从 [Releases](https://github.com/Tommie-P-xl/ClaudeBeep/releases/tag/v2.3.2) 下载最新的 `ClaudeBeep-Setup-*.exe` 并运行安装程序。

安装程序包含：
- `ClaudeBeep.exe` — 主程序
- `claudebeep_hook.bat` — Codex 集成的 hook 包装器

首次启动时，ClaudeBeep 会在 `%APPDATA%\ClaudeBeep` 下创建 `config.json`（以及其他运行时数据：`notify.log`、`pending/`、`responses/`、`send_queue/`）——安装版不会写入 Program Files。开发模式数据仍留在项目目录。安装目录中的旧配置会在首次启动时自动迁移。

### 卸载

通过 Windows 设置 > 应用 卸载。安装目录下的所有文件将被自动清除。

## Codex 集成说明

从 Web UI 安装 Codex hooks 后，需要在 Codex 中信任它们：

1. 打开 Codex 终端
2. 输入 `/hooks`
3. 审核并信任 ClaudeBeep hooks

如果重新安装或更新 ClaudeBeep，hooks 的哈希值会变化，Codex 会再次标记为"需要审核"。运行 `/hooks` 重新信任即可。

**已知问题：** Codex 在 Windows 上无法直接执行 `.exe` 文件作为 hook。ClaudeBeep 使用 `.bat` 包装器（`claudebeep_hook.bat`）来解决此问题。包装器已包含在安装程序中。

## 开发

```powershell
# 安装运行时和开发依赖
pip install -r requirements.txt
pip install -r requirements-dev.txt

# 运行完整测试套件
python -m unittest discover tests -v

# 运行托盘应用
python tray.py

# 或运行单个命令
python notify.py --ui          # 仅 Web UI
python notify.py --install     # 仅安装 hooks
python notify.py --uninstall   # 仅卸载 hooks
python notify.py --test        # 测试所有已启用渠道
```

## 构建

```powershell
# 构建独立可执行文件
./build.ps1
```

生成 `dist/ClaudeBeep.exe`（单文件、窗口模式、UPX 压缩）。

### CI/CD

推送版本标签触发 GitHub Actions 工作流：

```
git tag v2.3.2
git push origin v2.3.2
```

工作流步骤：
1. 设置 Python 3.11
2. 运行 `build.ps1` 生成 EXE
3. 安装 Inno Setup 并构建安装程序
4. 将两者上传为 GitHub Release 资产

## 配置

`config.json` 在首次运行时自动创建，所有字段都有合理默认值：

```json
{
  "app": {
    "version": "2.3.2",
    "auto_cleanup": true,
    "cleanup_interval_hours": 12,
    "update_repo": "Tommie-P-xl/ClaudeBeep"
  },
  "channels": {
    "windows_toast": { "duration_ms": 5000, "sound": "reminder" },
    "weixin": { "bot_token": "", "baseurl": "https://ilinkai.weixin.qq.com" },
    "telegram": { "bot_token": "", "chat_id": "" }
  },
  "integrations": {
    "claude_code": {
      "enabled": true,
      "events": { "Stop": true, "Elicitation": true, "PermissionRequest": true },
      "channels": { "windows_toast": true, "weixin": false, "telegram": true },
      "interaction": { "enabled": true, "timeout_seconds": 0, "show_in_terminal": true }
    },
    "codex": {
      "enabled": false,
      "events": { "Stop": true, "PermissionRequest": true },
      "channels": { "windows_toast": true, "weixin": false, "telegram": false }
    }
  }
}
```

以上为省略未变渠道字段的简化示例。敏感字段（`bot_token`、`app_secret` 等）在 API 响应中会被脱敏。

## 更新日志

完整版本历史见 [CHANGELOG_CN.md](CHANGELOG_CN.md)（中文）或 [CHANGELOG.md](CHANGELOG.md)（English）。

## 隐私

以下文件包含敏感或运行时数据，已从版本控制中排除：

- `config.json` — 渠道凭证和令牌
- `notify.log` — 运行日志
- `notify_state.json` — 跨进程去重状态
- `tray_heartbeat.json` — 进程心跳
- `send_queue/` — 瞬态消息队列
- `pending/` / `responses/` — 交互式回复生命周期文件
- `dist/` / `build/` — 构建产物

请勿提交本地令牌或生成的运行时状态。

## 许可证

MIT
