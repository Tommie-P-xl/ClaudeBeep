from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
import importlib
from datetime import datetime
from pathlib import Path
import sys

from config_store import runtime_channel_config

SCRIPT_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
LOG_FILE = SCRIPT_DIR / "notify.log"


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


def _default_factories() -> dict[str, Callable[[dict], object]]:
    return {
        name: (lambda cfg, module=module, cls=cls: getattr(importlib.import_module(module), cls)(cfg))
        for name, module, cls in (
            ("windows_toast", "channels.windows_toast", "WindowsToastChannel"),
            ("weixin", "channels.weixin", "WeixinChannel"),
            ("qq", "channels.qq", "QQBotChannel"),
            ("telegram", "channels.telegram", "TelegramChannel"),
            ("feishu", "channels.feishu", "FeishuChannel"),
            ("dingtalk", "channels.dingtalk", "DingTalkChannel"),
        )
    }


def collect_channels(
    config: dict,
    platform: str,
    factories: dict[str, Callable[[dict], object]] | None = None,
) -> list[object]:
    runtime_config = runtime_channel_config(config, platform)
    if factories is None:
        selected = runtime_config.get("integrations", {}).get(platform, {}).get("channels", {})
        selected_factories = {name: factory for name, factory in _default_factories().items() if selected.get(name, False)}
    else:
        selected_factories = factories
    return [factory(runtime_config) for factory in selected_factories.values()]


def _credential_values(value: object, key: str = "") -> set[str]:
    credentials = set()
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            credentials.update(_credential_values(child_value, str(child_key).lower()))
    elif isinstance(value, (list, tuple)):
        for item in value:
            credentials.update(_credential_values(item, key))
    elif (
        value is not None
        and isinstance(value, (str, int, float, bool))
        and (
            key.endswith("_id")
            or key == "sync_buf"
            or any(marker in key for marker in ("token", "secret", "password"))
        )
    ):
        credential = str(value)
        if credential:
            credentials.add(credential)
    return credentials


def _safe_error(error: Exception, config: dict) -> str:
    message = str(error)
    for credential in sorted(_credential_values(config), key=len, reverse=True):
        message = message.replace(credential, "[redacted]")
    return message or type(error).__name__


def sanitize_error(error: Exception, config: dict) -> str:
    return _safe_error(error, config)


def log_failure(event: NotificationEvent, channel: str, error: Exception | str, config: dict) -> None:
    exc = error if isinstance(error, Exception) else RuntimeError(str(error))
    message = sanitize_error(exc, config)
    line = (
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
        f"delivery failure platform={event.platform} event={event.event_name} "
        f"channel={channel or 'unknown'} result={message}\n"
    )
    try:
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass


def send_event(
    event: NotificationEvent,
    config: dict,
    channels: list[object] | None = None,
    observer: Callable[[str, object, DeliveryResult | None], None] | None = None,
) -> list[DeliveryResult]:
    selected_channels = channels
    if selected_channels is None:
        selected_channels = collect_channels(config, event.platform)

    results = []
    for channel in selected_channels:
        try:
            enabled = channel.is_enabled()
        except Exception as exc:
            result = DeliveryResult(channel.name, False, _safe_error(exc, config))
            results.append(result)
            if observer is not None:
                observer("result", channel, result)
            continue

        if not enabled:
            if observer is not None:
                observer("disabled", channel, None)
            continue

        if observer is not None:
            observer("sending", channel, None)
        try:
            success = bool(channel.send(event.title, event.message))
            error = "" if success else "Channel returned failure"
        except Exception as exc:
            success = False
            error = _safe_error(exc, config)
        result = DeliveryResult(channel.name, success, error)
        results.append(result)
        if observer is not None:
            observer("result", channel, result)
    return results
