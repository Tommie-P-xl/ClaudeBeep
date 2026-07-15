from importlib import import_module

from .base import NotificationChannel

__all__ = [
    "NotificationChannel",
    "WindowsToastChannel",
    "WeixinChannel",
    "QQBotChannel",
    "TelegramChannel",
    "FeishuChannel",
    "DingTalkChannel",
]

_CHANNEL_TYPES = {
    "WindowsToastChannel": ("windows_toast", "WindowsToastChannel"),
    "WeixinChannel": ("weixin", "WeixinChannel"),
    "QQBotChannel": ("qq", "QQBotChannel"),
    "TelegramChannel": ("telegram", "TelegramChannel"),
    "FeishuChannel": ("feishu", "FeishuChannel"),
    "DingTalkChannel": ("dingtalk", "DingTalkChannel"),
}


def __getattr__(name):
    if name not in _CHANNEL_TYPES:
        raise AttributeError(name)
    module, class_name = _CHANNEL_TYPES[name]
    value = getattr(import_module(f"{__name__}.{module}"), class_name)
    globals()[name] = value
    return value
