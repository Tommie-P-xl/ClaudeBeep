# ClaudeBeep Codex Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Release ClaudeBeep `1.5.0` with independently managed Claude Code and Codex hooks, events, and notification channels while preserving all existing Claude Code notifications and interactive replies.

**Architecture:** Keep `notify.py` as the behavior-compatible Claude Code entry point, add a notification-only Codex adapter, and share only canonical configuration and channel delivery. Store Claude Code and Codex as peer integrations, manage their user-level hook files independently, and keep Web UI and Windows tray state derived from the same integration APIs.

This remains one implementation plan because configuration, hook ownership,
runtime selection, Web UI, and tray all share one compatibility contract and do
not produce independently shippable releases. Every task still ends in a
reviewable, passing intermediate state.

**Tech Stack:** Python 3.10+, Flask, pytest, Alpine.js, Tailwind CSS, native Win32 tray menus through `ctypes`, JSON user configuration, PyInstaller, Inno Setup.

## Global Constraints

- Preserve Claude Code v1.1.0 `Stop`, `Elicitation`, and `PermissionRequest` behavior, including remote replies and hook response JSON.
- Use `~/.claude/settings.json` only for Claude Code and `~/.codex/hooks.json` only for Codex.
- Install Codex hooks at user scope only; do not create project `.codex/` files.
- Claude Code and Codex are peers under `integrations`, with independent platform, event, and channel switches.
- Configure channel credentials once; canonical `channels` data generates legacy compatibility mirrors.
- Codex is notification-only. Approval, denial, and answers remain inside Codex.
- Disabled or uninstalled platform events must start no ClaudeBeep hook process.
- The Codex path must not import `interaction.py` or `listener.py`.
- Preserve third-party hooks, unknown JSON fields, channel login state, and downgrade compatibility.
- Use atomic JSON writes and never overwrite malformed existing JSON.
- Run at most one WeChat keepalive when either integration enables WeChat.
- Web UI and Windows tray must expose equivalent peer integration controls.
- Set every application release version to exactly `1.5.0` and update `README.md` and `README_CN.md`.
- Do not add a new persistent process or a second channel listener.

## File Structure

### New production files

- `config_store.py`: canonical defaults, legacy migration, atomic persistence, peer integration accessors, and effective legacy-shaped channel configuration.
- `notification_core.py`: normalized notification event, platform-aware channel collection, and isolated multi-channel delivery.
- `codex_adapter.py`: Codex stdin payload parsing, notification text mapping, and notification-only hook execution.
- `hook_manager.py`: ownership-safe Claude Code and Codex hook inspection, synchronization, and uninstall operations.
- `tray_menu.py`: platform/channel/event command IDs and pure menu-state calculations testable without Win32 UI calls.

### New test files

- `requirements-dev.txt`: pytest-only development dependencies.
- `tests/conftest.py`: isolated paths and reusable v1.1.0 fixtures.
- `tests/test_claude_regression.py`: characterization tests for current Claude parsing and response behavior.
- `tests/test_config_store.py`: migration, peer independence, mirrors, malformed JSON, and atomic writes.
- `tests/test_notification_core.py`: platform channel selection and failure isolation.
- `tests/test_codex_adapter.py`: Codex payload mapping and import isolation.
- `tests/test_hook_manager.py`: exact hook ownership, sync, uninstall, and third-party preservation.
- `tests/test_app_integrations.py`: new API routes and legacy compatibility routes.
- `tests/test_tray_menu.py`: menu command mapping, platform state, and WeChat keepalive policy.
- `tests/test_runtime_isolation.py`: end-to-end module/import/process-path isolation.

### Existing files to modify

- `notify.py`: delegate configuration and delivery to shared modules, retain Claude behavior, add marked CLI/platform routing, and expose compatibility wrappers.
- `app.py`: add peer integration APIs and preserve legacy API shims.
- `tray.py`: render nested platform menus, route commands, and use shared keepalive policy.
- `static/index.html`: replace global hooks/channels state with the approved peer panels and shared credentials section.
- `requirements.txt`: verify production dependencies remain unchanged; pytest belongs only in `requirements-dev.txt`.
- `build.ps1`: include new modules through normal PyInstaller discovery and keep the existing build command.
- `installer.iss`: set `MyAppVersion` to `1.5.0`.
- `README.md`: document Claude Code and Codex setup and behavior in English.
- `README_CN.md`: document the same behavior in Chinese.

---

### Task 1: Establish the Test Harness and Claude Code Regression Baseline

**Files:**
- Create: `requirements-dev.txt`
- Create: `tests/conftest.py`
- Create: `tests/test_claude_regression.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: existing `notify._is_auto_approved`, `notify._extract_context_text`, `notify._extract_options`, and `interaction.format_hook_response` behavior.
- Produces: reusable `legacy_config`, `claude_settings_path`, and `codex_hooks_path` pytest fixtures; a regression gate for all later tasks.

- [ ] **Step 1: Add the development dependency and unignore committed plans/specs while ignoring local tool state**

Create `requirements-dev.txt`:

```text
-r requirements.txt
pytest>=8.0,<9
```

Replace the current `docs/` rule with these exact rules, then append the two
local-tool rules:

```gitignore
docs/*
!docs/superpowers/
docs/superpowers/*
!docs/superpowers/specs/
!docs/superpowers/specs/*.md
!docs/superpowers/plans/
!docs/superpowers/plans/*.md
.codegraph/
.superpowers/
```

- [ ] **Step 2: Create isolated path fixtures**

Create `tests/conftest.py` with fixtures that never touch real user settings:

```python
import copy
import json
from pathlib import Path

import pytest


@pytest.fixture
def legacy_config() -> dict:
    return {
        "app": {"version": "1.1.0", "auto_cleanup": True},
        "windows_toast": {"enabled": True, "duration_ms": 5000},
        "telegram": {
            "enabled": True,
            "bot_token": "test-token",
            "chat_id": "42",
        },
        "weixin": {"enabled": False, "bot_token": "", "to_user_id": ""},
        "qq": {"enabled": False, "app_id": "", "app_secret": "", "target_id": ""},
        "feishu": {"enabled": False, "app_id": "", "app_secret": "", "receive_id": ""},
        "dingtalk": {"enabled": False, "client_id": "", "client_secret": "", "user_id": ""},
        "interaction": {"enabled": True, "timeout_seconds": 0, "show_in_terminal": True},
        "future_field": {"preserve": True},
    }


@pytest.fixture
def config_file(tmp_path: Path, legacy_config: dict) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(copy.deepcopy(legacy_config)), encoding="utf-8")
    return path


@pytest.fixture
def claude_settings_path(tmp_path: Path) -> Path:
    return tmp_path / ".claude" / "settings.json"


@pytest.fixture
def codex_hooks_path(tmp_path: Path) -> Path:
    return tmp_path / ".codex" / "hooks.json"
```

- [ ] **Step 3: Write characterization tests before changing production code**

Create `tests/test_claude_regression.py` covering these exact payloads:

```python
import json

import interaction
import notify


def test_auto_approved_permission_is_filtered():
    approved, reason = notify._is_auto_approved({
        "hook_event_name": "PermissionRequest",
        "tool_name": "Bash",
        "tool_input": {"command": "git status"},
        "auto_approved": True,
        "permission_mode": "default",
    })
    assert approved is True
    assert reason


def test_permission_context_preserves_command():
    text = notify._extract_context_text({
        "hook_event_name": "PermissionRequest",
        "tool_name": "Bash",
        "tool_input": {"command": "git status"},
    })
    assert "git status" in text


def test_ask_user_question_options_are_preserved():
    result = notify._extract_options({
        "hook_event_name": "PermissionRequest",
        "tool_name": "AskUserQuestion",
        "tool_input": {
            "questions": [{
                "question": "Deploy now?",
                "options": [
                    {"label": "Yes", "description": "Deploy"},
                    {"label": "No", "description": "Wait"},
                ],
                "multiSelect": False,
            }]
        },
    })
    assert result["question"] == "Deploy now?"
    assert result["options"] == ["Yes", "No"]
    assert result["as_elicitation"] is True


def test_elicitation_response_wire_format_is_json():
    output = interaction.format_hook_response(
        "Yes", "Elicitation", "Deploy now?", {}
    )
    payload = json.loads(output)
    hook_output = payload["hookSpecificOutput"]
    assert hook_output["hookEventName"] == "PermissionRequest"
    assert hook_output["decision"]["behavior"] == "allow"
    assert hook_output["decision"]["updatedInput"]["answers"] == {
        "Deploy now?": "Yes"
    }
```

- [ ] **Step 4: Run the baseline tests and record the current behavior**

Run:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest tests/test_claude_regression.py -v
```

Expected: all four characterization tests pass against v1.1.0 code without changing production code.

- [ ] **Step 5: Commit the baseline**

```powershell
git add .gitignore requirements-dev.txt tests/conftest.py tests/test_claude_regression.py
git commit -m "test: capture Claude Code notification behavior"
```

---

### Task 2: Add Canonical Peer Configuration and Legacy Migration

**Files:**
- Create: `config_store.py`
- Create: `tests/test_config_store.py`
- Modify: `notify.py:30-84,180-203`

**Interfaces:**
- Consumes: `legacy_config` fixture from Task 1.
- Produces: `load_config(path: Path | None = None) -> dict`, `save_config(config: dict, path: Path | None = None) -> None`, `migrate_config(raw: dict) -> dict`, `get_integration(config: dict, platform: str) -> dict`, `runtime_channel_config(config: dict, platform: str) -> dict`, `set_channel_enabled(config: dict, platform: str, channel: str, enabled: bool) -> None`, and `should_run_weixin_keepalive(config: dict) -> bool`.

- [ ] **Step 1: Write failing migration and independence tests**

Create `tests/test_config_store.py`:

```python
import copy
import json

import pytest

import config_store


def test_legacy_config_migrates_to_peer_integrations(legacy_config):
    migrated = config_store.migrate_config(copy.deepcopy(legacy_config))
    assert migrated["integrations"]["claude_code"]["channels"]["telegram"] is True
    assert migrated["integrations"]["codex"]["enabled"] is False
    assert migrated["channels"]["telegram"]["bot_token"] == "test-token"
    assert migrated["future_field"] == {"preserve": True}


def test_platform_channel_switches_are_independent(legacy_config):
    config = config_store.migrate_config(copy.deepcopy(legacy_config))
    config_store.set_channel_enabled(config, "codex", "telegram", False)
    assert config["integrations"]["claude_code"]["channels"]["telegram"] is True
    assert config["integrations"]["codex"]["channels"]["telegram"] is False


def test_runtime_config_combines_shared_credentials_and_platform_switch(legacy_config):
    config = config_store.migrate_config(copy.deepcopy(legacy_config))
    config_store.set_channel_enabled(config, "codex", "telegram", True)
    runtime = config_store.runtime_channel_config(config, "codex")
    assert runtime["telegram"]["enabled"] is True
    assert runtime["telegram"]["bot_token"] == "test-token"


def test_save_refreshes_legacy_mirrors(config_file):
    config = config_store.load_config(config_file)
    config_store.set_channel_enabled(config, "claude_code", "telegram", False)
    config_store.save_config(config, config_file)
    saved = json.loads(config_file.read_text(encoding="utf-8"))
    assert saved["telegram"]["enabled"] is False
    assert saved["interaction"] == saved["integrations"]["claude_code"]["interaction"]


def test_malformed_json_is_never_overwritten(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(config_store.ConfigFileError):
        config_store.load_config(path)
    assert path.read_text(encoding="utf-8") == "{broken"


def test_missing_config_is_created_atomically(tmp_path):
    path = tmp_path / "config.json"
    config = config_store.load_config(path)
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["app"]["version"] == "1.5.0"
    assert config["integrations"]["codex"]["enabled"] is False


@pytest.mark.parametrize("claude,codex,expected", [
    (False, False, False),
    (True, False, True),
    (False, True, True),
    (True, True, True),
])
def test_weixin_keepalive_uses_either_platform(legacy_config, claude, codex, expected):
    config = config_store.migrate_config(copy.deepcopy(legacy_config))
    config["channels"]["weixin"].update({"bot_token": "token", "to_user_id": "user"})
    config_store.set_channel_enabled(config, "claude_code", "weixin", claude)
    config_store.set_channel_enabled(config, "codex", "weixin", codex)
    assert config_store.should_run_weixin_keepalive(config) is expected
```

- [ ] **Step 2: Run the tests to verify the module is missing**

Run: `python -m pytest tests/test_config_store.py -v`

Expected: collection fails with `ModuleNotFoundError: No module named 'config_store'`.

- [ ] **Step 3: Implement canonical defaults, deep merge, migration, and atomic writes**

Create `config_store.py` with these public constants and functions:

```python
from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "config.json"
PLATFORMS = ("claude_code", "codex")
CHANNEL_NAMES = ("windows_toast", "weixin", "qq", "telegram", "feishu", "dingtalk")
CLAUDE_EVENTS = ("Stop", "Elicitation", "PermissionRequest")
CODEX_EVENTS = (
    "Stop", "PermissionRequest", "SessionStart", "SubagentStart",
    "SubagentStop", "PreCompact", "PostCompact", "PreToolUse",
    "PostToolUse", "UserPromptSubmit",
)


class ConfigFileError(RuntimeError):
    pass


def atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
```

Implement `DEFAULT_CONFIG` with version `1.5.0`, shared `channels`, and the exact peer defaults from the design spec. `migrate_config` must deep-copy input, deep-fill missing defaults, copy legacy top-level channel blocks into `channels` only when canonical blocks are absent, populate Claude channel switches from legacy `enabled`, copy legacy `interaction`, and never discard unknown keys.

Implement the public accessors exactly as:

```python
def get_integration(config: dict, platform: str) -> dict:
    if platform not in PLATFORMS:
        raise ValueError(f"Unsupported platform: {platform}")
    return config["integrations"][platform]


def set_channel_enabled(
    config: dict, platform: str, channel: str, enabled: bool
) -> None:
    if channel not in CHANNEL_NAMES:
        raise ValueError(f"Unsupported channel: {channel}")
    get_integration(config, platform)["channels"][channel] = bool(enabled)


def runtime_channel_config(config: dict, platform: str) -> dict:
    migrated = migrate_config(config)
    result = copy.deepcopy(migrated)
    selected = get_integration(migrated, platform)["channels"]
    for name in CHANNEL_NAMES:
        result[name] = copy.deepcopy(migrated["channels"][name])
        result[name]["enabled"] = bool(selected.get(name, False))
    return result


def should_run_weixin_keepalive(config: dict) -> bool:
    migrated = migrate_config(config)
    credentials = migrated["channels"]["weixin"]
    # Preserve v1.1.0 behavior: login keepalive starts as soon as a bot token exists.
    configured = bool(credentials.get("bot_token"))
    selected = any(
        get_integration(migrated, platform)["enabled"]
        and get_integration(migrated, platform)["channels"].get("weixin", False)
        for platform in PLATFORMS
    )
    return configured and selected
```

Implement mirror refresh exactly as:

```python
def _refresh_legacy_mirrors(config: dict) -> dict:
    result = copy.deepcopy(config)
    claude = result["integrations"]["claude_code"]
    for name in CHANNEL_NAMES:
        shared = copy.deepcopy(result["channels"].get(name, {}))
        shared["enabled"] = bool(claude["channels"].get(name, False))
        result[name] = shared
    result["interaction"] = copy.deepcopy(claude["interaction"])
    return result
```

`load_config` must raise `ConfigFileError` for malformed existing JSON. When the
file is absent, it must create canonical defaults through `save_config` before
returning them, preserving the v1.1.0 first-run behavior. `save_config` must
migrate, refresh mirrors, and call `atomic_write_json`.

- [ ] **Step 4: Preserve existing imports through `notify.py` wrappers**

Replace the local config implementation in `notify.py` with:

```python
from config_store import DEFAULT_CONFIG, CONFIG_FILE
from config_store import load_config as _load_config
from config_store import save_config as _save_config


def load_config() -> dict:
    return _load_config()


def save_config(config: dict) -> None:
    _save_config(config)
```

Do not change callers in `app.py`, `listener.py`, or `channels/weixin.py` in this task.

- [ ] **Step 5: Run migration and Claude regression tests**

Run:

```powershell
python -m pytest tests/test_config_store.py tests/test_claude_regression.py -v
```

Expected: all tests pass; no real `config.json` is modified.

- [ ] **Step 6: Commit peer configuration**

```powershell
git add config_store.py notify.py tests/test_config_store.py
git commit -m "feat: add peer integration configuration"
```

---

### Task 3: Add Platform-aware Notification Delivery and the Codex Adapter

**Files:**
- Create: `notification_core.py`
- Create: `codex_adapter.py`
- Create: `tests/test_notification_core.py`
- Create: `tests/test_codex_adapter.py`
- Modify: `notify.py:206-219,429-570`

**Interfaces:**
- Consumes: `config_store.runtime_channel_config` and `config_store.get_integration` from Task 2.
- Produces: `NotificationEvent`, `DeliveryResult`, `collect_channels(config, platform)`, `send_event(event, config)`, `parse_codex_event(payload)`, and `run_codex_hook(raw, config=None) -> int`.

- [ ] **Step 1: Write failing delivery-selection tests**

Create `tests/test_notification_core.py` with fake channels injected through a factory map:

```python
from notification_core import NotificationEvent, send_event


class FakeChannel:
    def __init__(self, name, enabled=True, succeeds=True):
        self._name = name
        self._enabled = enabled
        self._succeeds = succeeds
        self.messages = []

    @property
    def name(self):
        return self._name

    def is_enabled(self):
        return self._enabled

    def send(self, title, message):
        self.messages.append((title, message))
        if isinstance(self._succeeds, Exception):
            raise self._succeeds
        return self._succeeds


def test_send_event_isolates_channel_failure(legacy_config):
    event = NotificationEvent("codex", "Stop", "Codex - 完成", "Done", "C:/repo", "s1")
    failed = FakeChannel("telegram", succeeds=RuntimeError("offline"))
    passed = FakeChannel("windows_toast", succeeds=True)
    results = send_event(event, legacy_config, channels=[failed, passed])
    assert [result.success for result in results] == [False, True]
    assert passed.messages == [("Codex - 完成", "Done")]
```

- [ ] **Step 2: Write failing Codex mapping and import-isolation tests**

Create `tests/test_codex_adapter.py`:

```python
import json
import sys

import codex_adapter


def test_stop_payload_maps_to_completion():
    event = codex_adapter.parse_codex_event({
        "session_id": "s1",
        "turn_id": "t1",
        "cwd": "C:/repo",
        "hook_event_name": "Stop",
        "model": "gpt-5",
    })
    assert event.platform == "codex"
    assert event.event_name == "Stop"
    assert event.title == "Codex - 完成"
    assert "C:/repo" in event.message


def test_permission_payload_tells_user_to_return_to_codex():
    event = codex_adapter.parse_codex_event({
        "session_id": "s1",
        "turn_id": "t1",
        "cwd": "C:/repo",
        "hook_event_name": "PermissionRequest",
        "tool_name": "Bash",
        "tool_input": {"command": "git push"},
    })
    assert "Codex" in event.message
    assert "处理" in event.message
    assert "git push" in event.message


def test_codex_module_does_not_import_claude_interaction_modules():
    assert "interaction" not in sys.modules
    assert "listener" not in sys.modules
```

- [ ] **Step 3: Run focused tests and verify missing interfaces**

Run: `python -m pytest tests/test_notification_core.py tests/test_codex_adapter.py -v`

Expected: collection fails because the new modules do not exist.

- [ ] **Step 4: Implement normalized delivery**

Create `notification_core.py` with immutable dataclasses:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class NotificationEvent:
    platform: str
    event_name: str
    title: str
    message: str
    cwd: str = ""
    session_id: str = ""


@dataclass(frozen=True)
class DeliveryResult:
    channel: str
    success: bool
    error: str = ""
```

Implement `collect_channels(config, platform)` using lazy imports and the output
of `runtime_channel_config(config, platform)`. Implement
`send_event(event, config, channels=None)` so each enabled channel is called in
its own `try/except`, credentials never appear in errors, and one failure cannot
stop the next channel.

Keep `notify.collect_channels(config)` as a compatibility wrapper calling
`notification_core.collect_channels(config, "claude_code")`. Replace only the
non-interactive send loop with `send_event`; leave the Claude interaction branch
and its output formatting intact.

- [ ] **Step 5: Implement the notification-only Codex adapter**

Create `codex_adapter.py` with:

```python
SUPPORTED_EVENTS = {
    "Stop", "PermissionRequest", "SessionStart", "SubagentStart",
    "SubagentStop", "PreCompact", "PostCompact", "PreToolUse",
    "PostToolUse", "UserPromptSubmit",
}


def parse_codex_event(payload: dict) -> NotificationEvent | None:
    event_name = str(payload.get("hook_event_name", ""))
    if event_name not in SUPPORTED_EVENTS:
        return None
    cwd = str(payload.get("cwd", ""))
    tool_name = str(payload.get("tool_name", ""))
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    command = str(tool_input.get("command", ""))[:500]
    if event_name == "Stop":
        title = "Codex - 完成"
        detail = "Codex 已完成当前任务。"
    elif event_name == "PermissionRequest":
        title = "Codex - 需要处理"
        detail = "Codex 正在等待权限或输入，请返回 Codex 处理。"
    else:
        title = f"Codex - {event_name}"
        detail = f"Codex 触发事件：{event_name}。"
    parts = [part for part in (cwd, tool_name, command, detail) if part]
    return NotificationEvent(
        platform="codex",
        event_name=event_name,
        title=title,
        message="\n".join(parts),
        cwd=cwd,
        session_id=str(payload.get("session_id", "")),
    )
```

`run_codex_hook(raw, config=None)` must parse JSON, return `0` for empty,
unknown, malformed, disabled-platform, or disabled-event input, log a sanitized
error for malformed input, call `send_event` for enabled events, print no hook
decision JSON, and always return `0`.

- [ ] **Step 6: Run new and regression tests**

Run:

```powershell
python -m pytest tests/test_notification_core.py tests/test_codex_adapter.py tests/test_claude_regression.py -v
```

Expected: all tests pass and the Claude characterization tests remain green.

- [ ] **Step 7: Commit the adapters**

```powershell
git add notification_core.py codex_adapter.py notify.py tests/test_notification_core.py tests/test_codex_adapter.py
git commit -m "feat: add isolated Codex notification adapter"
```

---

### Task 4: Implement Ownership-safe Dual Hook Management and CLI Routing

**Files:**
- Create: `hook_manager.py`
- Create: `tests/test_hook_manager.py`
- Modify: `notify.py:85-159,224-340,429-470`
- Modify: `tray.py:521-534`

**Interfaces:**
- Consumes: `config_store.CLAUDE_EVENTS`, `config_store.CODEX_EVENTS`, and `config_store.atomic_write_json`.
- Produces: `build_hook_command(platform, event) -> dict`, `sync_hooks(platform, enabled_events, path=None) -> HookStatus`, `uninstall_hooks(platform, path=None) -> HookStatus`, `inspect_hooks(platform, path=None) -> HookStatus`, and a CLI contract accepting `--platform`, `--claudebeep-hook`, `--install`, `--uninstall`, and `--from-stdin`.

- [ ] **Step 1: Write failing hook ownership tests**

Create `tests/test_hook_manager.py` with these core cases:

```python
import json

import hook_manager


def test_codex_sync_preserves_third_party_hook(codex_hooks_path):
    codex_hooks_path.parent.mkdir(parents=True)
    codex_hooks_path.write_text(json.dumps({
        "future": {"preserve": True},
        "hooks": {"Stop": [{
            "hooks": [{"type": "command", "command": "third-party.exe"}]
        }]},
    }), encoding="utf-8")
    status = hook_manager.sync_hooks("codex", {"Stop"}, codex_hooks_path)
    saved = json.loads(codex_hooks_path.read_text(encoding="utf-8"))
    commands = [h["command"] for group in saved["hooks"]["Stop"] for h in group["hooks"]]
    assert "third-party.exe" in commands
    assert any("--platform codex" in command for command in commands)
    assert saved["future"] == {"preserve": True}
    assert status.configured_events == ("Stop",)


def test_codex_uninstall_does_not_change_claude_file(codex_hooks_path, claude_settings_path):
    hook_manager.sync_hooks("codex", {"Stop"}, codex_hooks_path)
    claude_settings_path.parent.mkdir(parents=True)
    claude_settings_path.write_text('{"hooks":{"Stop":[]}}', encoding="utf-8")
    before = claude_settings_path.read_bytes()
    hook_manager.uninstall_hooks("codex", codex_hooks_path)
    assert claude_settings_path.read_bytes() == before


def test_claude_sync_replaces_only_known_legacy_claudebeep_entry(claude_settings_path):
    claude_settings_path.parent.mkdir(parents=True)
    claude_settings_path.write_text(json.dumps({"hooks": {
        "Stop": [
            {"hooks": [{"type": "command", "command": '"C:/ClaudeBeep/notify_hook.bat" --type stop --from-stdin'}]},
            {"hooks": [{"type": "command", "command": "notify-company.exe"}]},
        ]
    }}), encoding="utf-8")
    hook_manager.sync_hooks("claude_code", {"Stop"}, claude_settings_path)
    saved = json.loads(claude_settings_path.read_text(encoding="utf-8"))
    commands = [h["command"] for group in saved["hooks"]["Stop"] for h in group["hooks"]]
    assert "notify-company.exe" in commands
    assert sum("--platform claude_code" in command for command in commands) == 1


def test_malformed_hook_file_is_unchanged(codex_hooks_path):
    codex_hooks_path.parent.mkdir(parents=True)
    codex_hooks_path.write_text("{broken", encoding="utf-8")
    try:
        hook_manager.sync_hooks("codex", {"Stop"}, codex_hooks_path)
    except hook_manager.HookFileError:
        pass
    else:
        raise AssertionError("HookFileError not raised")
    assert codex_hooks_path.read_text(encoding="utf-8") == "{broken"
```

- [ ] **Step 2: Run tests and verify the hook manager is absent**

Run: `python -m pytest tests/test_hook_manager.py -v`

Expected: collection fails with `ModuleNotFoundError`.

- [ ] **Step 3: Implement exact ownership and hook synchronization**

Create `hook_manager.py` with:

```python
from dataclasses import dataclass
from pathlib import Path


CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"
CODEX_HOOKS = Path.home() / ".codex" / "hooks.json"
OWNER_FLAG = "--claudebeep-hook"


@dataclass(frozen=True)
class HookStatus:
    platform: str
    configured_events: tuple[str, ...]
    removed_count: int = 0


class HookFileError(RuntimeError):
    pass
```

Ownership rules must be exact:

```python
def _is_owned(command: str, platform: str) -> bool:
    return OWNER_FLAG in command and f"--platform {platform}" in command


def _is_legacy_claude_owned(command: str) -> bool:
    normalized = command.replace("\\", "/").lower()
    has_entry = normalized.endswith("notify.py --type stop --from-stdin") or \
        "notify_hook.bat\" --type " in normalized or \
        "claudebeep.exe\" --type " in normalized
    return has_entry and "--from-stdin" in normalized
```

Do not remove commands merely because they contain `notify` or `claudebeep`.
Read the entire JSON object, preserve unknown keys, filter only owned handlers,
delete empty matcher groups/events, append one owned group per enabled event,
and atomically write the result. Codex handlers use documented `type`,
`command`, `commandWindows`, `timeout`, and `statusMessage` fields; Claude
handlers preserve their current `env` and event-specific `--type` arguments.

Move the current executable/Python discovery from `notify._get_hook_base_cmd`
into `hook_manager._get_hook_base_cmd`. `build_hook_command` appends
`--claudebeep-hook --platform <platform> --from-stdin`; for Claude it also
appends `--type stop` for `Stop` and `--type ask` for `Elicitation` and
`PermissionRequest`. This keeps command generation usable from CLI, Flask, and
tray without importing `notify.py` back into `hook_manager.py`.

- [ ] **Step 4: Route the CLI without changing Claude output**

Add to `notify.main()`:

```python
parser.add_argument("--platform", choices=["claude_code", "codex"], default="claude_code")
parser.add_argument("--claudebeep-hook", action="store_true", help=argparse.SUPPRESS)
```

Use `hook_manager.sync_hooks` and `hook_manager.uninstall_hooks` for CLI install
operations. For normal Codex invocation, read stdin once and immediately return
`codex_adapter.run_codex_hook(raw)`. The Claude branch must continue through the
existing code unchanged after argument parsing.

Update `tray._should_delegate_to_notify()` so `--platform` and
`--claudebeep-hook` are recognized when the frozen executable is invoked by a
Codex hook.

- [ ] **Step 5: Run hook, Codex, and Claude regression tests**

Run:

```powershell
python -m pytest tests/test_hook_manager.py tests/test_codex_adapter.py tests/test_claude_regression.py -v
```

Expected: all tests pass; fixture files are the only settings files changed.

- [ ] **Step 6: Commit hook management**

```powershell
git add hook_manager.py notify.py tray.py tests/test_hook_manager.py
git commit -m "feat: manage Claude and Codex hooks independently"
```

---

### Task 5: Add Integration-aware Flask APIs with Legacy Shims

**Files:**
- Create: `tests/test_app_integrations.py`
- Modify: `app.py:1-17,77-157,435-575,595-610`

**Interfaces:**
- Consumes: config accessors from Task 2, `send_event` from Task 3, and hook operations from Task 4.
- Produces: `GET /api/integrations`, `PUT /api/integrations/<platform>`, `POST /api/integrations/<platform>/channels/<name>/toggle`, `POST /api/integrations/<platform>/hooks/sync`, `POST /api/integrations/<platform>/hooks/uninstall`, and `POST /api/integrations/<platform>/test`.

- [ ] **Step 1: Write failing API tests with isolated config and hook paths**

Create `tests/test_app_integrations.py` using `monkeypatch` before creating the
Flask app:

```python
def test_integrations_are_returned_as_peers(client):
    response = client.get("/api/integrations")
    assert response.status_code == 200
    data = response.get_json()
    assert set(data["integrations"]) == {"claude_code", "codex"}


def test_codex_channel_toggle_does_not_change_claude(client):
    response = client.post(
        "/api/integrations/codex/channels/telegram/toggle",
        json={"enabled": True},
    )
    assert response.status_code == 200
    data = client.get("/api/integrations").get_json()
    assert data["integrations"]["codex"]["channels"]["telegram"] is True
    assert data["integrations"]["claude_code"]["channels"]["telegram"] is True


def test_unknown_platform_and_channel_are_rejected(client):
    assert client.put("/api/integrations/other", json={}).status_code == 404
    assert client.post(
        "/api/integrations/codex/channels/other/toggle", json={"enabled": True}
    ).status_code == 404


def test_legacy_channel_route_targets_claude(client):
    response = client.post("/api/channel/telegram/toggle", json={"enabled": False})
    assert response.status_code == 200
    data = client.get("/api/integrations").get_json()
    assert data["integrations"]["claude_code"]["channels"]["telegram"] is False


def test_malformed_config_returns_conflict_without_overwrite(client, isolated_config_path):
    isolated_config_path.write_text("{broken", encoding="utf-8")
    response = client.get("/api/integrations")
    assert response.status_code == 409
    assert "配置" in response.get_json()["error"]
    assert isolated_config_path.read_text(encoding="utf-8") == "{broken"
```

Define the fixtures exactly as:

```python
@pytest.fixture
def isolated_config_path(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    monkeypatch.setattr(config_store, "CONFIG_FILE", path)
    monkeypatch.setattr(app_module, "CONFIG_FILE", path)
    monkeypatch.setattr(hook_manager, "CLAUDE_SETTINGS", tmp_path / ".claude" / "settings.json")
    monkeypatch.setattr(hook_manager, "CODEX_HOOKS", tmp_path / ".codex" / "hooks.json")
    return path


@pytest.fixture
def client(isolated_config_path):
    application = app_module.create_app()
    application.config.update(TESTING=True)
    with application.test_client() as test_client:
        yield test_client
```

The `app_module` import is `import app as app_module`; import `config_store` and
`hook_manager` in the test module before defining these fixtures.

- [ ] **Step 2: Run API tests and verify 404 failures**

Run: `python -m pytest tests/test_app_integrations.py -v`

Expected: new routes return 404 and tests fail.

- [ ] **Step 3: Implement platform validation and peer routes**

Add helpers in `create_app()`:

```python
def require_platform(platform: str) -> str:
    if platform not in ("claude_code", "codex"):
        abort(404)
    return platform


def require_channel(name: str) -> str:
    if name not in CHANNEL_NAMES:
        abort(404)
    return name
```

Implement the exact routes in the Interfaces section. `PUT` accepts only
`enabled`, `events`, and Claude-only `interaction`; reject unsupported event
names with HTTP 400. Disabling a platform uninstalls its owned hooks. Enabling
or changing events calls `sync_hooks` with the enabled event set. Channel
toggle validates credentials using the existing per-channel rules before
enabling it. The test route constructs a platform-specific `NotificationEvent`
and returns one result per attempted channel.

Return hook status as:

```json
{
  "configured_events": ["Stop"],
  "trust_review_required": true,
  "trust_command": "/hooks"
}
```

Set `trust_review_required` only for configured Codex hooks; do not claim that
ClaudeBeep can observe trusted/active state.

Register handlers for `ConfigFileError` and `HookFileError` that return HTTP 409
with `{"ok": false, "error": <sanitized Chinese message>}`. Do not include file
contents, commands from unrelated hooks, credentials, or tracebacks in the
response.

- [ ] **Step 4: Keep existing routes as Claude Code compatibility shims**

Make `/api/channel/<name>/toggle`, `/api/test`, `/api/hooks`,
`/api/hooks/install`, `/api/hooks/uninstall`, and `/api/interaction` call the
same service functions with `platform="claude_code"`. Preserve their existing
response keys so the v1.1.0 page remains functional during this task.

- [ ] **Step 5: Run API and full Python tests**

Run:

```powershell
python -m pytest tests/test_app_integrations.py -v
python -m pytest -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit the API**

```powershell
git add app.py tests/test_app_integrations.py
git commit -m "feat: expose peer integration APIs"
```

---

### Task 6: Build the Approved Peer Web UI

**Files:**
- Modify: `static/index.html:371-720,1094-1145,1170-1410,1860-1895`
- Modify: `tests/test_app_integrations.py`

**Interfaces:**
- Consumes: Task 5 integration APIs.
- Produces: side-by-side Claude Code and Codex panels, shared credential cards, platform event/channel toggles, hook actions, and Codex trust/interaction copy.

- [ ] **Step 1: Add failing HTML contract tests**

Add to `tests/test_app_integrations.py`:

```python
def test_index_contains_peer_integration_controls(client):
    html = client.get("/").get_data(as_text=True)
    assert 'data-integration="claude_code"' in html
    assert 'data-integration="codex"' in html
    assert "共享通知渠道凭证" in html
    assert "批准和回答仍在 Codex 中完成" in html
    assert "/api/integrations" in html
```

- [ ] **Step 2: Run the HTML contract test**

Run: `python -m pytest tests/test_app_integrations.py::test_index_contains_peer_integration_controls -v`

Expected: FAIL because the peer markup is absent.

- [ ] **Step 3: Replace global state with peer integration state**

In the Alpine component, replace `hooksInfo`, `interactionEnabled`, and global
channel enable assumptions with:

```javascript
integrations: {
  claude_code: { enabled: true, events: {}, channels: {}, interaction: {} },
  codex: { enabled: false, events: {}, channels: {} },
},
hookStatus: { claude_code: {}, codex: {} },
```

Add exact methods:

```javascript
async loadIntegrations() {
  const data = await this.api('GET', '/api/integrations');
  this.integrations = data.integrations;
  this.hookStatus = data.hooks;
},
async toggleIntegrationChannel(platform, channel, enabled) {
  await this.api('POST', `/api/integrations/${platform}/channels/${channel}/toggle`, { enabled });
  this.integrations[platform].channels[channel] = enabled;
},
async saveIntegration(platform) {
  await this.api('PUT', `/api/integrations/${platform}`, this.integrations[platform]);
  await this.loadIntegrations();
},
async syncIntegrationHooks(platform) {
  await this.api('POST', `/api/integrations/${platform}/hooks/sync`);
  await this.loadIntegrations();
},
async uninstallIntegrationHooks(platform) {
  await this.api('POST', `/api/integrations/${platform}/hooks/uninstall`);
  await this.loadIntegrations();
}
```

- [ ] **Step 4: Implement the approved responsive layout**

Create one unframed integration section containing a two-column desktop grid
that stacks on mobile. Each panel must include:

- `data-integration="claude_code"` or `data-integration="codex"`.
- Platform enable switch.
- Configured hook events and install/uninstall actions.
- Event switches generated from the API event object.
- Six platform-specific channel switches.
- Claude interaction controls in the Claude panel only.
- Codex text: `远程渠道仅发送提醒，批准和回答仍在 Codex 中完成。`
- Codex configured-hook text: `请在 Codex 中运行 /hooks 查看并确认信任状态。`

Move channel credentials/login forms into a separate full-width section titled
`共享通知渠道凭证`. Do not duplicate credential inputs inside platform panels.
Keep the existing theme behavior, login flows, log viewer, responsive
constraints, and channel icons.

- [ ] **Step 5: Run API tests and perform browser visual QA**

Run:

```powershell
python -m pytest tests/test_app_integrations.py -v
python notify.py --ui
```

With Playwright, inspect `http://127.0.0.1:5100` at `1440x900` and `390x844`.
Verify both platform panels are visible, mobile panels stack without horizontal
overflow, the longest event label fits, no controls overlap, and browser console
contains no errors. Exercise one event toggle and one channel toggle for each
platform, then restore fixture/default state.

- [ ] **Step 6: Commit the Web UI**

```powershell
git add static/index.html tests/test_app_integrations.py
git commit -m "feat: add peer Claude and Codex dashboard"
```

---

### Task 7: Add Peer Platform Controls to the Windows Tray

**Files:**
- Create: `tray_menu.py`
- Create: `tests/test_tray_menu.py`
- Modify: `tray.py:72-78,239,322-402,436-444,466-497,540-567`

**Interfaces:**
- Consumes: peer config from Task 2 and hook operations from Task 4.
- Produces: `channel_command_id(platform, channel)`, `hook_command_id(platform, event)`, `decode_command(command_id)`, `channel_menu_state(config, platform)`, and nested Win32 submenus.

- [ ] **Step 1: Write failing pure menu and keepalive tests**

Create `tests/test_tray_menu.py`:

```python
import copy

import config_store
import tray_menu


def test_channel_command_round_trip():
    command = tray_menu.channel_command_id("codex", "telegram")
    assert tray_menu.decode_command(command) == ("channel", "codex", "telegram")


def test_hook_command_round_trip():
    command = tray_menu.hook_command_id("claude_code", "PermissionRequest")
    assert tray_menu.decode_command(command) == (
        "hook", "claude_code", "PermissionRequest"
    )


def test_platform_channel_menu_states_are_independent(legacy_config):
    config = config_store.migrate_config(copy.deepcopy(legacy_config))
    config_store.set_channel_enabled(config, "codex", "telegram", False)
    claude = tray_menu.channel_menu_state(config, "claude_code")
    codex = tray_menu.channel_menu_state(config, "codex")
    assert claude["telegram"]["checked"] is True
    assert codex["telegram"]["checked"] is False
```

- [ ] **Step 2: Run tests and verify the pure menu module is absent**

Run: `python -m pytest tests/test_tray_menu.py -v`

Expected: collection fails with `ModuleNotFoundError`.

- [ ] **Step 3: Implement collision-free command ranges and pure state**

Create `tray_menu.py` with fixed ranges:

```python
CHANNEL_BASE = {"claude_code": 2000, "codex": 2100}
HOOK_BASE = {"claude_code": 3000, "codex": 3200}
UNINSTALL_ALL = {"claude_code": 3500, "codex": 3501}
PLATFORM_LABELS = {"claude_code": "Claude Code", "codex": "Codex"}
```

Map channel indices using `config_store.CHANNEL_NAMES` and event indices using
the appropriate event tuple. `decode_command` returns exactly one of:
`("channel", platform, channel)`, `("hook", platform, event)`,
`("uninstall", platform, None)`, or `None`. `channel_menu_state` returns
`checked` from the platform matrix and `configured` from shared credentials,
using the existing credential rules.

- [ ] **Step 4: Render nested notification and hook submenus**

Replace `_build_channel_submenu` with a root submenu that contains `Claude Code`
and `Codex` submenus. Add `_build_hooks_submenu` with one event item per platform
and `卸载全部` at the bottom of each platform submenu. Preserve checkmarks,
gray unconfigured channels, existing menu ordering, dark mode, and Win32 menu
cleanup.

Change `_handle_command` to call `tray_menu.decode_command`. A channel command
updates only the selected platform. A hook command toggles the event in config,
saves atomically, and synchronizes that platform's hooks. Uninstall removes all
owned hooks for that platform and disables its event switches only after a
successful write.

- [ ] **Step 5: Use the shared WeChat keepalive policy**

Replace all direct checks of `cfg["weixin"]["enabled"]` in tray startup and
toggle paths with `config_store.should_run_weixin_keepalive(cfg)`. Start or stop
the existing singleton keepalive only when the aggregate result changes.

Update the tooltip to show peer counts without expanding its fixed 128-character
buffer, for example: `ClaudeBeep v1.5.0 (Claude 2 / Codex 1)`.

- [ ] **Step 6: Run menu tests and manually inspect Win32 behavior**

Run:

```powershell
python -m pytest tests/test_tray_menu.py tests/test_config_store.py tests/test_hook_manager.py -v
python tray.py
```

Expected automated result: all tests pass. Manual result: notification and hook
menus contain separate Claude Code and Codex submenus; toggling one platform
does not change the other's checkmarks; menu dismissal and dark mode still work.

- [ ] **Step 7: Commit tray management**

```powershell
git add tray_menu.py tray.py tests/test_tray_menu.py
git commit -m "feat: manage peer integrations from the tray"
```

---

### Task 8: Prove Runtime Isolation and Complete Regression Coverage

**Files:**
- Create: `tests/test_runtime_isolation.py`
- Modify: `tests/test_claude_regression.py`
- Modify: `tests/test_codex_adapter.py`
- Modify: `tests/test_hook_manager.py`

**Interfaces:**
- Consumes: all runtime and hook interfaces from Tasks 2-7.
- Produces: release-blocking proof that one integration does not import, execute, or configure the other integration's runtime path.

- [ ] **Step 1: Add failing subprocess and import-isolation tests**

Create `tests/test_runtime_isolation.py`:

```python
import json
import os
import subprocess
import sys


def run_notify(args, payload="", env=None):
    return subprocess.run(
        [sys.executable, "notify.py", *args],
        input=payload,
        text=True,
        capture_output=True,
        env=env or os.environ.copy(),
        timeout=10,
        check=False,
    )


def test_codex_unknown_event_exits_cleanly_without_hook_output():
    result = run_notify(
        ["--platform", "codex", "--claudebeep-hook", "--from-stdin"],
        json.dumps({"hook_event_name": "Unknown", "session_id": "s1"}),
    )
    assert result.returncode == 0
    assert result.stdout == ""


def test_importing_codex_adapter_does_not_import_interaction_or_listener():
    code = (
        "import sys, codex_adapter; "
        "assert 'interaction' not in sys.modules; "
        "assert 'listener' not in sys.modules"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
```

Add a test that monkeypatches the channel factory and confirms a Codex
`PermissionRequest` sends once and returns without creating files under
`pending/` or `responses/`. Add a complementary Claude test that runs the
existing response formatter and asserts no Codex hook file is touched.

- [ ] **Step 2: Run the full suite and observe any isolation failures**

Run: `python -m pytest -v`

Expected: tests pass if Tasks 2-7 already maintain the required boundaries;
otherwise the failing assertion identifies the remaining coupled import or
filesystem path to correct in Step 3.

- [ ] **Step 3: Make only the minimal isolation corrections**

Move imports inside platform branches, remove any module-level Codex import from
the Claude path, and ensure all path dependencies accept injectable test paths.
Do not change Claude payload parsing or hook response formatting. Add explicit
platform/event/channel fields to sanitized log messages without recording bot
tokens, secrets, or full transcript data.

- [ ] **Step 4: Run the complete test suite twice**

Run:

```powershell
python -m pytest -v
python -m pytest -v
```

Expected: both runs pass, demonstrating tests do not leak global module or file
state between runs.

- [ ] **Step 5: Commit isolation coverage**

```powershell
git add tests/test_runtime_isolation.py tests/test_claude_regression.py tests/test_codex_adapter.py tests/test_hook_manager.py notify.py codex_adapter.py notification_core.py
git commit -m "test: verify integration runtime isolation"
```

---

### Task 9: Release Version 1.5.0, Documentation, Build, and Final Verification

**Files:**
- Modify: `tray.py:23`
- Modify: `installer.iss:2`
- Modify: `README.md`
- Modify: `README_CN.md`
- Verify: `build.ps1`
- Verify: `.github/workflows/build-windows.yml`

**Interfaces:**
- Consumes: completed peer integrations and full test suite.
- Produces: consistently versioned `1.5.0` application, current bilingual documentation, executable, and installer.

- [ ] **Step 1: Add a failing version consistency test**

Add to `tests/test_runtime_isolation.py`:

```python
from pathlib import Path


def test_release_version_is_consistent():
    assert '"version": "1.5.0"' in Path("config_store.py").read_text(encoding="utf-8")
    assert 'APP_VERSION = "1.5.0"' in Path("tray.py").read_text(encoding="utf-8")
    assert '#define MyAppVersion "1.5.0"' in Path("installer.iss").read_text(encoding="utf-8")
    assert "# ClaudeBeep v1.5.0" in Path("README.md").read_text(encoding="utf-8")
    assert "# ClaudeBeep v1.5.0" in Path("README_CN.md").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the version test and verify it fails**

Run: `python -m pytest tests/test_runtime_isolation.py::test_release_version_is_consistent -v`

Expected: FAIL on one or more remaining `1.1.0` values.

- [ ] **Step 3: Set all application release versions to 1.5.0**

Set canonical default version, tray version, installer version, badges, headings,
tag examples, and sample configuration to `1.5.0`. Do not change protocol
version constants such as channel SDK or WeChat `channel_version` fields.

- [ ] **Step 4: Rewrite both README architecture and usage sections**

In both languages, document:

- Claude Code and Codex as peer integrations.
- User-level paths `~/.claude/settings.json` and `~/.codex/hooks.json`.
- Independent platform, event, and channel controls in Web UI and tray.
- Shared channel credentials.
- Claude remote interactive replies unchanged.
- Codex completion and permission/attention notifications.
- Codex approval and answers remaining inside Codex.
- Codex `/hooks` trust review after installation.
- No overhead from an uninstalled platform and one shared WeChat keepalive.
- Updated development commands including `pip install -r requirements-dev.txt`
  and `python -m pytest -v`.
- Updated architecture diagram showing two adapters converging only at delivery.

- [ ] **Step 5: Run static version and documentation checks**

Run:

```powershell
python -m pytest tests/test_runtime_isolation.py::test_release_version_is_consistent -v
rg -n "v1\.1\.0|version.*1\.0\.3|MyAppVersion.*1\.1\.0|APP_VERSION.*1\.1\.0" README.md README_CN.md notify.py config_store.py tray.py installer.iss
```

Expected: version test passes and `rg` returns no stale application-version
matches. Channel protocol versions outside this file list are intentionally not
part of the check.

- [ ] **Step 6: Run the complete verification suite**

Run:

```powershell
python -m pytest -v
python -m compileall -q app.py notify.py config_store.py notification_core.py codex_adapter.py hook_manager.py tray.py tray_menu.py channels
git diff --check
```

Expected: pytest exits 0, compileall exits 0 with no output, and
`git diff --check` exits 0.

- [ ] **Step 7: Build the executable and installer**

Run:

```powershell
./build.ps1
& "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe" installer.iss
```

Expected artifacts:

- `dist/ClaudeBeep.exe`
- `Output/ClaudeBeep-Setup-1.5.0.exe`

Launch the built executable in a disposable Windows test account, inspect both
tray platform menus, open the Web UI, install one Claude event and one Codex
event, verify Codex displays the `/hooks` trust prompt,
then uninstall both and confirm unrelated fixture hooks remain.

- [ ] **Step 8: Commit the release update**

```powershell
git add config_store.py notify.py tray.py installer.iss README.md README_CN.md tests/test_runtime_isolation.py
git commit -m "release: prepare ClaudeBeep 1.5.0"
```

- [ ] **Step 9: Perform final repository review**

Run:

```powershell
git status --short
git log -10 --oneline
python -m pytest -q
```

Expected: only intentionally untracked build outputs ignored by `.gitignore`,
the nine task commits appear in order, and the final test summary reports all
tests passed.
