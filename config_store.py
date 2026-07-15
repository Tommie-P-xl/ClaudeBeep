from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
from pathlib import Path


SCRIPT_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
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


CHANNEL_CREDENTIAL_FIELDS = {
    "windows_toast": (),
    "weixin": ("bot_token", "to_user_id"),
    "qq": ("app_id", "app_secret", "target_id"),
    "telegram": ("bot_token", "chat_id"),
    "feishu": ("app_id", "app_secret", "receive_id"),
    "dingtalk": ("client_id", "client_secret", "user_id"),
}
CHANNEL_SECRET_FIELDS = {
    "windows_toast": (),
    "weixin": ("bot_token", "context_token", "sync_buf"),
    "qq": ("app_secret",),
    "telegram": ("bot_token",),
    "feishu": ("app_secret",),
    "dingtalk": ("client_secret",),
}


DEFAULT_CONFIG = {
    "app": {
        "version": "2.0.0",
        "auto_start": False,
        "auto_cleanup": True,
        "cleanup_interval_hours": 12,
        "update_repo": "Tommie-P-xl/ClaudeBeep",
    },
    "channels": {
        "windows_toast": {"duration_ms": 5000, "sound": "reminder"},
        "weixin": {
            "bot_token": "",
            "baseurl": "https://ilinkai.weixin.qq.com",
            "ilink_bot_id": "",
            "ilink_user_id": "",
            "to_user_id": "",
            "context_token": "",
            "sync_buf": "",
            "session_expired": False,
        },
        "qq": {"app_id": "", "app_secret": "", "target_id": ""},
        "telegram": {"bot_token": "", "chat_id": ""},
        "feishu": {"app_id": "", "app_secret": "", "receive_id": ""},
        "dingtalk": {"client_id": "", "client_secret": "", "user_id": ""},
    },
    "integrations": {
        "claude_code": {
            "enabled": True,
            "events": {name: True for name in CLAUDE_EVENTS},
            "channels": {
                "windows_toast": True,
                "weixin": False,
                "qq": False,
                "telegram": True,
                "feishu": False,
                "dingtalk": False,
            },
            "interaction": {
                "enabled": True,
                "timeout_seconds": 0,
                "show_in_terminal": True,
            },
        },
        "codex": {
            "enabled": False,
            "events": {
                "Stop": True,
                "PermissionRequest": True,
                **{name: False for name in CODEX_EVENTS[2:]},
            },
            "channels": {
                "windows_toast": True,
                "weixin": False,
                "qq": False,
                "telegram": False,
                "feishu": False,
                "dingtalk": False,
            },
        },
    },
}


def _deep_fill(target: dict, defaults: dict) -> None:
    for key, default in defaults.items():
        if key not in target:
            target[key] = copy.deepcopy(default)
        elif isinstance(default, dict) and isinstance(target[key], dict):
            _deep_fill(target[key], default)


def migrate_config(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ConfigFileError("Configuration root must be a JSON object")

    result = copy.deepcopy(raw)
    canonical_channels = result.get("channels")
    if not isinstance(canonical_channels, dict):
        canonical_channels = {}
        result["channels"] = canonical_channels

    integrations = result.get("integrations")
    if not isinstance(integrations, dict):
        integrations = {}
        result["integrations"] = integrations
    claude = integrations.get("claude_code")
    if not isinstance(claude, dict):
        claude = {}
        integrations["claude_code"] = claude
    claude_channels = claude.get("channels")
    if not isinstance(claude_channels, dict):
        claude_channels = {}
        claude["channels"] = claude_channels

    for name in CHANNEL_NAMES:
        legacy = result.get(name)
        if name not in canonical_channels and isinstance(legacy, dict):
            canonical_channels[name] = {
                key: copy.deepcopy(value)
                for key, value in legacy.items()
                if key != "enabled"
            }
        if name not in claude_channels and isinstance(legacy, dict) and "enabled" in legacy:
            claude_channels[name] = bool(legacy["enabled"])

    if "interaction" not in claude and isinstance(result.get("interaction"), dict):
        claude["interaction"] = copy.deepcopy(result["interaction"])

    _deep_fill(result, DEFAULT_CONFIG)
    return result


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
        result[name] = result["channels"][name]
        result[name]["enabled"] = bool(selected.get(name, False))
    return result


def is_channel_configured(config: dict, channel: str) -> bool:
    """Return the single effective credential predicate used by API and tray."""
    if channel not in CHANNEL_NAMES:
        raise ValueError(f"Unsupported channel: {channel}")
    migrated = migrate_config(config)
    credentials = migrated["channels"].get(channel, {})
    return all(bool(credentials.get(field)) for field in CHANNEL_CREDENTIAL_FIELDS[channel])


def should_run_weixin_keepalive(config: dict) -> bool:
    migrated = migrate_config(config)
    credentials = migrated["channels"]["weixin"]
    # Preserve legacy behavior: login keepalive starts as soon as a bot token exists.
    configured = bool(credentials.get("bot_token"))
    selected = any(
        get_integration(migrated, platform)["enabled"]
        and get_integration(migrated, platform)["channels"].get("weixin", False)
        for platform in PLATFORMS
    )
    return configured and selected


def _refresh_legacy_mirrors(config: dict) -> dict:
    result = copy.deepcopy(config)
    claude = result["integrations"]["claude_code"]
    for name in CHANNEL_NAMES:
        shared = copy.deepcopy(result["channels"].get(name, {}))
        shared["enabled"] = bool(claude["channels"].get(name, False))
        result[name] = shared
    result["interaction"] = copy.deepcopy(claude["interaction"])
    return result


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


def load_config(path: Path | None = None) -> dict:
    config_path = Path(path) if path is not None else CONFIG_FILE
    if not config_path.exists():
        config = copy.deepcopy(DEFAULT_CONFIG)
        save_config(config, config_path)
        return _refresh_legacy_mirrors(config)
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (json.JSONDecodeError, OSError) as exc:
        raise ConfigFileError(f"Unable to read configuration: {config_path}") from exc
    return _refresh_legacy_mirrors(migrate_config(raw))


def save_config(config: dict, path: Path | None = None) -> None:
    config_path = Path(path) if path is not None else CONFIG_FILE
    migrated = migrate_config(config)
    persisted = _refresh_legacy_mirrors(migrated)
    atomic_write_json(config_path, persisted)
