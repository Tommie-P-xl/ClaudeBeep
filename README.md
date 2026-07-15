# ClaudeBeep v1.5.0

<p align="center">
  <img src="assets/icon.png" width="128" alt="ClaudeBeep Logo">
</p>

<p align="center">
  <strong>Windows system tray notifications for Claude Code and Codex</strong>
</p>

<p align="center">
  <a href="README_CN.md">中文</a> | English
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-v1.5.0-blue" alt="Version">
  <img src="https://img.shields.io/badge/python-3.10+-green" alt="Python">
  <img src="https://img.shields.io/badge/platform-Windows-lightgrey" alt="Platform">
  <img src="https://img.shields.io/badge/license-MIT-brightgreen" alt="License">
</p>

---

ClaudeBeep is a Windows system tray application that treats Claude Code and Codex as peer integrations. Each platform has its own enable switch, hook events, and delivery-channel selections, while both reuse one set of channel credentials. Install only the platform you use: an uninstalled integration adds no hook or runtime overhead.

## Features

### System Tray

- **Open Dashboard** — launches the Web UI for detailed channel configuration, QR login, and log viewing.
- **Peer platform menus** — Claude Code and Codex each expose independent platform and channel controls in the tray. Unconfigured channels are greyed out.
- **Start with Windows** — toggles per-user auto-start via the Windows registry (`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`).
- **Check for Updates** — queries GitHub Releases for the latest version; if newer, downloads and replaces the exe in-place via a batch script with retry logic (no uninstall required). Falls back to opening the download page if auto-update fails.
- **System Dark Mode** — automatically detects the Windows system theme and applies dark mode styling to the tray menu.
- **Web UI Themes** — supports Light / Dark / Follow System theme modes, with Follow System as default. Theme preference is persisted automatically.
- **High-Res Tray Icon** — 256×256 high-resolution icon for crisp display on high-DPI screens.
- **High-DPI Awareness** — Application manifest declares Per-Monitor V2 DPI awareness, fixing blurry tray menu text on high-DPI screens.
- **SVG Icons** — Dashboard and configuration pages use inline SVG vector icons for crisp rendering at any scale.
- **Quit** — stops all background services and exits.

### Peer Integrations

- **Claude Code** — completion, permission, and elicitation events keep the existing interactive workflow. Approval choices and free-form answers can still arrive from the terminal or a configured remote channel.
- **Codex** — completion and permission/attention events produce outbound notifications, but approvals and answers remain inside Codex. After installing Codex hooks, run `/hooks` in Codex and review the trust prompt before accepting the configuration.
- **Independent controls** — the Web UI and tray expose separate platform enable switches, event selections, and delivery-channel selections for Claude Code and Codex.
- **Shared delivery** — channel credentials are configured once and reused by both integrations. When either enabled platform uses WeChat, the tray maintains one shared keepalive rather than one connection per platform.
- **Zero unused-platform overhead** — a platform whose hooks are not installed does not start an adapter or add work to that platform.

### Notification Channels

| Channel | Protocol | Keepalive | Reply Listening |
|---------|----------|-----------|-----------------|
| Windows Toast | WinRT / `winotify` (with app icon) | None (fire-and-forget) | N/A |
| WeChat ⚠️ Not Recommended | iLink Bot API | Tray-managed `getupdates` long-poll | Direct dispatch in keepalive loop |
| QQ Bot | QQ Open API (OAuth2 + c2c/group) | None (token cached) | WebSocket via `listener.py` |
| Telegram | Telegram Bot API | None | Long-polling via `listener.py` |
| Feishu/Lark | Feishu Open API (OAuth2) | None (token cached) | WebSocket via `lark_oapi` |
| DingTalk | DingTalk Open API (OAuth2) | None (token cached) | Stream via `dingtalk_stream` |

### Interactive Replies

When Claude Code asks a question (PermissionRequest / Elicitation), ClaudeBeep sends a formatted notification with numbered options to all enabled channels. The user can reply from:
- The terminal (direct keyboard input)
- Any remote channel (WeChat, QQ, Telegram, Feishu, DingTalk)

The first reply wins. Responses are written atomically via temp-file rename to prevent race conditions. Codex permission notifications are informational: approval and answer input stays in Codex.

### Safety & Reliability

- **Multi-instance protection** — a Windows global mutex (`Global\ClaudeBeepTray`) prevents duplicate tray processes.
- **Automatic cleanup** — a background loop runs every 12 hours (configurable) to trim logs, remove stale pending/response files, and clean up queue artifacts. Files are checked for active handles before deletion.
- **Heartbeat monitoring** — `tray_heartbeat.json` is written every 15 seconds with PID and channel status, enabling cross-process coordination.
- **Graceful degradation** — if the keepalive process is not running, WeChat falls back to direct HTTP sending; if a channel fails, other channels still deliver.

## Architecture

```
┌────────────────────────┐     ┌────────────────────────┐
│ Claude Code            │     │ Codex                  │
│ ~/.claude/settings.json│     │ ~/.codex/hooks.json    │
└───────────┬────────────┘     └───────────┬────────────┘
            ▼                              ▼
┌────────────────────────┐     ┌────────────────────────┐
│ Claude adapter         │     │ Codex adapter          │
│ interactive replies    │     │ notify only            │
└───────────┬────────────┘     └───────────┬────────────┘
            └──────────────┬───────────────┘
                           ▼
                ┌─────────────────────┐
                │ notification_core   │
                │ delivery boundary   │
                └──────────┬──────────┘
                           ▼
      Windows Toast / WeChat / QQ / Telegram / Feishu / DingTalk

The adapters are isolated and converge only at delivery. Channel credentials,
the tray-owned WeChat keepalive, and delivery implementations are shared.
```

### WeChat iLink Protocol — Deep Dive

The iLink Bot API uses a **dual-layer token architecture**:

| Layer | Token | Scope | Lifetime | Transport |
|-------|-------|-------|----------|-----------|
| Identity | `bot_token` | Global device-level auth | Long-lived (until QR re-scan) | HTTP Header |
| Routing | `context_token` | Per-conversation message routing | Short-lived (expires on inactivity) | HTTP Body |

**Key protocol behaviors:**

1. **Session binding** — the iLink server binds `bot_token` to the TCP connection that maintains `getupdates`. Send requests from a different process/connection are silently rejected with `ret=-2`.

2. **`ret=-2` ambiguity** — this error code is overloaded: it can mean stale `context_token`, parameter error, OR cross-process session mismatch. The `errmsg` field is unreliable (sometimes `"unknown error"`, sometimes empty).

3. **Tokenless fallback** — when `context_token` has expired, stripping it from the request body and retrying can succeed. This is a protocol-level "degraded send" mechanism.

4. **`errcode=-14`** — the only true session expiry signal. Requires re-scanning the QR code.

**ClaudeBeep's WeChat strategy:**

- The tray process owns the `getupdates` long-poll loop, maintaining the active TCP session.
- When `send()` is called from the hook process, the message is enqueued to `send_queue/` as a JSON file.
- The keepalive loop drains the queue and sends messages through its own HTTP connection (same process, same session binding).
- On `ret=-2`: clears cached `context_token`, retries without it (tokenless fallback).
- On `errcode=-14`: disables the channel, marks session expired, prompts for re-login.
- `context_token` and `to_user_id` are dynamically updated from inbound messages — no static config dependency.

## Installation

Download the latest `ClaudeBeep-Setup-x.x.x.exe` from [GitHub Releases](https://github.com/Tommie-P-xl/ClaudeBeep/releases) and run it. Choose the installation directory — all runtime files (`config.json`, `notify.log`, `pending/`, `responses/`, `send_queue/`) are stored there.

The installer:
- Registers the application in Add/Remove Programs
- Creates Start Menu and optional Desktop shortcuts
- Detects a running instance via mutex and warns before overwriting
- Supports silent install: `ClaudeBeep-Setup.exe /SILENT /DIR="C:\MyPath"`

## Development

```powershell
# Install runtime and development dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Run the complete test suite
python -m pytest -v

# Run the tray application
python tray.py

# Or run individual commands
python notify.py --ui          # Web UI only
python notify.py --install     # Install hooks only
python notify.py --uninstall   # Uninstall hooks only
python notify.py --test        # Test all enabled channels
```

## Build

```powershell
# Build the standalone executable
./build.ps1
```

This creates `dist/ClaudeBeep.exe` (single-file, windowed, UPX-compressed).

### CI/CD

Pushing a version tag triggers the GitHub Actions workflow:

```
git tag v1.5.0
git push origin v1.5.0
```

The workflow:
1. Sets up Python 3.11
2. Runs `build.ps1` to produce the EXE
3. Installs Inno Setup and builds the installer
4. Uploads both as GitHub Release assets

## Configuration

`config.json` is created automatically on first run. All fields have sensible defaults:

```json
{
  "app": {
    "version": "1.5.0",
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

The shortened example omits unchanged channel fields. Sensitive fields (`bot_token`, `app_secret`, etc.) are masked in API responses.

## Privacy

The following files contain sensitive or runtime data and are excluded from version control:

- `config.json` — channel credentials and tokens
- `notify.log` — operational log
- `notify_state.json` — cross-process dedup state
- `tray_heartbeat.json` — process heartbeat
- `send_queue/` — transient message queue
- `pending/` / `responses/` — interactive reply lifecycle files
- `dist/` / `build/` — build artifacts

Never commit local tokens or generated runtime state.

## License

MIT
