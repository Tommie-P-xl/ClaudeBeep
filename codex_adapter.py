from __future__ import annotations

import json
import sys
import logging

from config_store import CODEX_EVENTS, get_integration, load_config, migrate_config
from notification_core import NotificationEvent, log_failure, send_event


SUPPORTED_EVENTS = frozenset(CODEX_EVENTS)
logger = logging.getLogger("claudebeep.codex")


def parse_codex_event(payload: dict) -> NotificationEvent | None:
    event_name = str(payload.get("hook_event_name", ""))
    if event_name not in SUPPORTED_EVENTS:
        return None
    cwd = str(payload.get("cwd", "")) if payload.get("cwd") is not None else ""
    tool_name = str(payload.get("tool_name", "")) if payload.get("tool_name") is not None else ""
    raw_tool_input = payload.get("tool_input")
    tool_input = raw_tool_input if isinstance(raw_tool_input, dict) else {}
    command = str(tool_input.get("command", ""))[:500] if tool_input.get("command") is not None else ""
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
        session_id=str(payload.get("session_id", "")) if payload.get("session_id") is not None else "",
    )


def run_codex_hook(raw: str, config: dict | None = None) -> int:
    if not raw or not raw.strip():
        return 0
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        print("Codex hook payload could not be parsed", file=sys.stderr)
        return 0
    if not isinstance(payload, dict):
        return 0

    event = parse_codex_event(payload)
    if event is None:
        return 0
    try:
        effective_config = migrate_config(config if config is not None else load_config())
        integration = get_integration(effective_config, "codex")
        if not integration.get("enabled", False):
            return 0
        if not integration.get("events", {}).get(event.event_name, False):
            return 0
        results = send_event(event, effective_config)
        for result in results:
            if not result.success:
                log_failure(event, result.channel, result.error or "failed", effective_config)
    except Exception as exc:
        log_failure(event, "unknown", exc, effective_config if "effective_config" in locals() else (config or {}))
    return 0
