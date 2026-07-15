"""Pure command mapping and state helpers for the Windows tray menu."""

from __future__ import annotations

import config_store


CHANNEL_BASE = {"claude_code": 2000, "codex": 2100}
HOOK_BASE = {"claude_code": 3000, "codex": 3200}
UNINSTALL_ALL = {"claude_code": 3500, "codex": 3501}
SYNC_ALL = {"claude_code": 3502, "codex": 3503}
PLATFORM_BASE = {"claude_code": 3600, "codex": 3601}
PLATFORM_LABELS = {"claude_code": "Claude Code", "codex": "Codex"}

_CHANNEL_CREDENTIALS = {
    "windows_toast": (),
    "weixin": ("bot_token", "to_user_id"),
    "qq": ("app_id", "app_secret", "target_id"),
    "telegram": ("bot_token", "chat_id"),
    "feishu": ("app_id", "app_secret", "receive_id"),
    "dingtalk": ("client_id", "client_secret", "user_id"),
}


def _events_for(platform: str) -> tuple[str, ...]:
    if platform == "claude_code":
        return config_store.CLAUDE_EVENTS
    if platform == "codex":
        return config_store.CODEX_EVENTS
    raise ValueError(f"Unsupported platform: {platform}")


def channel_command_id(platform: str, channel: str) -> int:
    try:
        return CHANNEL_BASE[platform] + config_store.CHANNEL_NAMES.index(channel)
    except KeyError as exc:
        raise ValueError(f"Unsupported platform: {platform}") from exc
    except ValueError as exc:
        raise ValueError(f"Unsupported channel: {channel}") from exc


def hook_command_id(platform: str, event: str) -> int:
    try:
        return HOOK_BASE[platform] + _events_for(platform).index(event)
    except KeyError as exc:
        raise ValueError(f"Unsupported platform: {platform}") from exc
    except ValueError as exc:
        raise ValueError(f"Unsupported event for {platform}: {event}") from exc


def platform_command_id(platform: str) -> int:
    try:
        return PLATFORM_BASE[platform]
    except KeyError as exc:
        raise ValueError(f"Unsupported platform: {platform}") from exc


def decode_command(command_id: int):
    for platform, platform_id in PLATFORM_BASE.items():
        if command_id == platform_id:
            return "platform", platform, None
    for platform, base in CHANNEL_BASE.items():
        offset = command_id - base
        if 0 <= offset < len(config_store.CHANNEL_NAMES):
            return "channel", platform, config_store.CHANNEL_NAMES[offset]
    for platform, base in HOOK_BASE.items():
        events = _events_for(platform)
        offset = command_id - base
        if 0 <= offset < len(events):
            return "hook", platform, events[offset]
    for platform, uninstall_id in UNINSTALL_ALL.items():
        if command_id == uninstall_id:
            return "uninstall", platform, None
    for platform, sync_id in SYNC_ALL.items():
        if command_id == sync_id:
            return "sync", platform, None
    return None


def channel_menu_state(config: dict, platform: str) -> dict[str, dict[str, bool]]:
    migrated = config_store.migrate_config(config)
    switches = config_store.get_integration(migrated, platform)["channels"]
    state = {}
    for channel in config_store.CHANNEL_NAMES:
        credentials = migrated["channels"][channel]
        required = _CHANNEL_CREDENTIALS[channel]
        state[channel] = {
            "checked": bool(switches.get(channel, False)),
            "configured": config_store.is_channel_configured(migrated, channel),
        }
    return state
