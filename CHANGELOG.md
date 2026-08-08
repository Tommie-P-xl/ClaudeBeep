# Changelog

All notable changes to ClaudeBeep are documented in this file.

## [v2.3.1] - 2026-08-08

### Fixed
- **Web UI operations hanging**: `app.run()` used Flask's default single-threaded model, so the SSE long-lived connection from `/api/stream` monopolized the only worker thread and every other API request stalled once the dashboard was open. The server now explicitly runs with `threaded=True`.
- **Channels kept sending after logout**: the WeChat / QQ / Telegram / Feishu / DingTalk logout endpoints only cleared credentials and the canonical switch, not the per-integration channel toggle under `integrations.*.channels` — after logging out, every event still attempted to send with empty credentials and spammed error logs. Logout now disables the channel on all enabled platforms.
- **"Check for updates" crashed on prerelease versions**: `updater.parse_version` now extracts numeric segments with a regex, so tags like `2.3.0-rc1` no longer raise `ValueError`.
- **WeChat QR polling CPU spin**: the login status poll loop now backs off 1s on fast-failing paths instead of spinning hot for up to 180 seconds.
- **DingTalk sent-success false positives**: sending now validates the response business `code == 0`, so an HTTP 200 with an expired token / invalid args is no longer reported as success (aligned with QQ / Feishu / Telegram).

### Tests
- Added 7 unit-test files / 117 cases (161 total), covering: hook parsing and permission filtering, update checks and SHA256 verification, parallel multi-channel delivery with failure isolation, interaction request lifecycle and first-write-wins semantics, WeChat `ret=-2` fallback retry and the send queue, listener message dispatch (temporary / managed), and the Web API (config redaction, local-access guards, logout-toggle regression).
- All tests isolate temporary directories and mock network calls — they never write into the project directory or produce real traffic.

## [v2.3.0] - 2026-08-07

### Fixed
- **Captured channel IDs no longer silently lost** (critical): listener auto-capture (QQ `target_id`, Telegram `chat_id`, Feishu `receive_id`, DingTalk `user_id`, WeChat `context_token`/`to_user_id`) previously wrote to the legacy top-level mirror of `config.json`, which was rebuilt from canonical `channels.*` on the next load — the captured values vanished on the next read. All capture paths now go through the new transactional `config_store.update_channel_fields()` writing to canonical storage under a file lock.
- **WeChat QR login no longer hangs forever**: the status polling loop now has a 3-minute overall deadline per QR code; previously, if the user never scanned, the login thread spun indefinitely and every subsequent login attempt was rejected with "login already in progress".
- **WeChat keepalive hot loop**: a persistent `ret=-2` (stale context token) response now counts toward the failure backoff instead of looping at full speed against the iLink API.
- **Auto-update on non-ASCII Windows profiles**: the delayed replace batch script is written in the system ANSI code page (`mbcs`) instead of ASCII, which used to raise `UnicodeEncodeError` for users whose profile path contains e.g. Chinese characters; unencodable paths now fall back to a manual-update prompt.
- **Single-instance false positives**: the tray's mutex check now uses `WinDLL(use_last_error=True)` semantics and the file lock is the sole authoritative gate — a clobbered `GetLastError()` can no longer block startup.
- **Interaction robustness**: request labels are now allocated under a file lock (concurrent hooks could get duplicate labels and cross-deliver replies); channel reply listeners start *before* notifications are sent so slow sends no longer shrink the reply window; stale pending requests are also reaped after 24h (Windows PID reuse could previously keep them forever); response polling interval lowered 2s → 0.5s.
- **Hook sync hardening**: malformed non-list `hooks.<event>` entries in `settings.json` are reset instead of crashing with `AttributeError`; Codex `config.toml` cleanup no longer ends a skipped section at blank lines (stray keys could attach to the previous section) and now leaves a `.bak` backup.
- **Smaller fixes**: QQ listener aborts when the gateway handshake isn't `READY`; token-cache temp files use unique names (concurrent refreshes could truncate each other); `/api/config` PUT rejects non-object JSON with 400 instead of 500; `/api/weixin/qr/status` only persists when the token actually changed (was rewriting the whole config on every 2s poll); Flask `secret_key` persists across restarts; stale/outdated docstring for multi-question reply separators corrected.

### Security
- **Toast script injection surface closed**: `windows_toast.duration_ms` is coerced to a clamped integer before interpolation into the PowerShell script.
- **Update integrity**: when release metadata lacks a SHA256 hash, the updater now requires explicit user confirmation before downloading/installing.
- **Log hygiene**: channel HTTP response bodies are redacted for tokens before being written to the log; short IDs (≤5 chars) are no longer blanket-replaced in error messages (avoided mangling).
- Request IDs now use `secrets` instead of `random`.

### Performance
- **Parallel multi-channel delivery**: `notification_core.send_event` now dispatches enabled channels concurrently — a slow channel (network timeout, PowerShell cold start) no longer delays the others.
- **Log rotation built in**: `notify.log` self-rolls at ~1MB (keeping the last ~512KB) inside `common.log`, independent of the tray's periodic cleanup; `/api/logs` reads from the file tail instead of loading the whole file.
- WeChat `sync_buf` persists only when changed; `should_run_weixin_keepalive` and legacy-migration checks skip redundant deep copies when the config is already migrated.

### Maintenance
- New transactional config APIs: `config_store.update_config(mutator)` and `update_channel_fields()` hold the file lock across the whole read-modify-write cycle (previously only the write itself was locked).
- Removed dead code: seven unused `hook_flow` imports in `notify.py`, the `_load_permissions_allow` / `_load_project_settings` / `_find_claude_dir` chain, and unused dependencies (`winotify`, `pystray`, `pillow`) dropped from `requirements.txt`.
- 4 new unit tests (44 total) covering canonical-write persistence (H1 regression) and concurrent-writer lost-update (M4 regression).

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

[v2.3.1]: https://github.com/Tommie-P-xl/ClaudeBeep/releases/tag/v2.3.1
[v2.3.0]: https://github.com/Tommie-P-xl/ClaudeBeep/releases/tag/v2.3.0
[v2.2.1]: https://github.com/Tommie-P-xl/ClaudeBeep/releases/tag/v2.2.1
[v2.2.0]: https://github.com/Tommie-P-xl/ClaudeBeep/releases/tag/v2.2.0
[v2.1.0]: https://github.com/Tommie-P-xl/ClaudeBeep/releases/tag/v2.1.0
[v2.0.0]: https://github.com/Tommie-P-xl/ClaudeBeep/releases/tag/v2.0.0
