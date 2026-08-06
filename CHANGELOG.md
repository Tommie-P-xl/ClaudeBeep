# Changelog

All notable changes to ClaudeBeep are documented in this file.

## [v2.2.1] - 2026-08-06

### Fixed
- **Strict single-instance enforcement**: The tray process now takes a per-user file lock (`%APPDATA%\ClaudeBeep\tray.lock`) in addition to the Windows mutex, so multiple tray instances can no longer coexist even when the global-namespace mutex is unavailable (permissions / session isolation). The Web UI (`--ui`, tray menu, `app.py`) now probes `127.0.0.1:5100` before starting: if a ClaudeBeep UI service is already running, it reuses it and opens the browser instead of launching a duplicate Flask process; port-bind races fall back to reuse as well. Hook / install / test short-lived processes are intentionally exempt (they must run concurrently).
- **Auto-update replacement races** (fixes the "Failed to load Python DLL" popup after an update): the delayed replace script now waits for **all** old ClaudeBeep processes to exit (including the Web UI child process, which keeps the EXE handle open) before renaming/copying — it aborts safely after a 20s timeout and restores the backup on failure. It also pauses 3s after copying before launching the new EXE so antivirus real-time scanning no longer locks the freshly written binary and breaks the onefile bootloader extraction. The tray now terminates its own Web UI subprocess on quit so updates proceed even when the dashboard is open.

## [v2.2.0] - 2026-08-06

### Security
- **Log redaction**: All logs now go through a unified `common/log.py`; credentials (`bot_token`, `context_token`, `app_secret`, `user_id`, etc.) are masked before being written to `notify.log`. Hook contexts are logged by field name + value length only, never by value.
- **Web UI local access guard**: `/api/*` now rejects non-loopback `Host` headers (blocks DNS rebinding) and requires `X-Requested-With: XMLHttpRequest` on write methods (blocks cross-site requests). Frontend `api()` wrapper sends the header automatically.
- **Update integrity**: The updater now verifies the downloaded EXE against a SHA256 hash published in `latest.json`; mismatches abort the update. Standalone replacement uses a delayed apply-script instead of renaming the running EXE (which fails on Windows).
- **Config write hardening**: `update_config` no longer lets the "new channel" branch bypass sensitive-field protection or persist frontend meta fields like `configured_secrets`.

### Data & Paths
- **Runtime data moved to `%APPDATA%\ClaudeBeep`** (installed/frozen mode): `config.json`, `notify.log`, `pending/`, `responses/`, `send_queue/`, heartbeat and token caches no longer live under Program Files. Legacy config in the install dir is migrated automatically once. Uninstalling no longer deletes user configuration.

### Performance
- **Cross-process token cache**: QQ / Feishu / DingTalk access tokens are cached to a file with TTL, so hook cold starts reuse tokens instead of re-fetching on every event.
- **Tray-managed channel listeners**: The tray process now holds long-lived listeners for Telegram / QQ / Feishu / DingTalk (WeChat keepalive already worked this way), and hook processes skip temporary connections via the heartbeat's `managed_channels` list.

### Fixes
- `write_response` uses atomic hard-link creation so "first reply wins" holds across platforms (POSIX `rename` used to silently overwrite).
- QQ OpenID capture no longer dies silently on token/gateway fetch errors; the UI reports an error instead of spinning forever.
- Multi-question replies only split on `|` — Chinese/English periods no longer trigger false multi-question parsing.
- `/api/logs` clamps the requested line count (≤500) to prevent full-log exfiltration.
- Windows Toast now shows the correct app name per platform (Codex no longer shows "Claude Code").
- Removed dead code: `notify_state.py` module, `_process_message_global`, `_send_winotify`, `NOTIFY_HOOK_EVENTS`.

### Architecture & Maintenance
- New channel registry (`common/channels_registry.py`) is the single source for channel metadata and factories.
- `listener.py` (1072 lines) split into the `listeners/` package (coordinator, per-channel listeners, capture flows); `listener.py` remains a compatibility shim.
- `notify.main()` split into `notify_cli.py` (argument parsing) and `hook_flow.py` (hook context parsing/filtering).
- Single version source in `version.py`; `build.ps1` injects it into PyInstaller resources and the Inno Setup installer.
- 35 unit tests added (`tests/`) covering reply parsing, hook ownership, config migration, secret redaction, and tray menu decoding.

## [v2.1.0] - 2026-04

- **Bug fix**: All channel credential endpoints (QR login, validate, logout) now correctly persist to canonical config path — fixes silent data loss introduced in v2.0.0
- **Config caching**: `load_config()` now uses mtime-based caching to avoid redundant disk reads and deep copies on every API call
- **Concurrency**: Added file locking to `atomic_write_json()` to prevent concurrent writer data loss
- **Telegram default**: Telegram channel notifications are now disabled by default for new installations
- **SSE shutdown race**: Fixed race condition where rapid tab open/close could cause premature app exit
- **Codex adapter**: Fixed `str(None)` producing literal "None" in notifications when payload fields are null
- **TOML cleanup**: Fixed path separator mismatch on Windows that prevented Codex hook state cleanup
- **Atomic TOML write**: `~/.codex/config.toml` cleanup now uses atomic write to prevent corruption
- **Hook deduplication**: Improved shlex handling to prevent hook duplication on malformed commands
- **Code cleanup**: Removed dead wrapper functions in notify.py, unused imports, and redundant config indirection layers
- **Type safety**: Replaced `type(x) is not bool` with `isinstance()` throughout the codebase

## [v2.0.0] - 2026-01

- Codex peer integration with independent platform controls
- Centralized config management (config_store.py)
- Hook ownership tracking (hook_manager.py)
- Notification delivery boundary (notification_core.py)
- Native Win32 tray menus with dark mode support

[v2.2.1]: https://github.com/Tommie-P-xl/ClaudeBeep/releases/tag/v2.2.1
[v2.2.0]: https://github.com/Tommie-P-xl/ClaudeBeep/releases/tag/v2.2.0
[v2.1.0]: https://github.com/Tommie-P-xl/ClaudeBeep/releases/tag/v2.1.0
[v2.0.0]: https://github.com/Tommie-P-xl/ClaudeBeep/releases/tag/v2.0.0
