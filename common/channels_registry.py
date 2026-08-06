"""渠道注册表（M4/M8）：所有通知渠道的元数据与工厂函数。

新增渠道只需在此登记一份元数据（名称 / 标签 / 实现模块与类 / 是否远程渠道），
其余模块（tray 菜单、app 路由、listener 实例化）统一引用本注册表，
避免渠道名散落硬编码造成不同步。
"""

from __future__ import annotations

import importlib
from typing import Any, Dict


def _meta(name: str, label: str, module: str, cls: str, remote: bool) -> Dict[str, Any]:
    return {
        "name": name,
        "label": label,
        "module": module,
        "class": cls,
        "remote": remote,
    }


CHANNEL_META: Dict[str, Dict[str, Any]] = {
    "windows_toast": _meta("windows_toast", "Windows 通知", "channels.windows_toast", "WindowsToastChannel", remote=False),
    "weixin": _meta("weixin", "WeChat ⚠️", "channels.weixin", "WeixinChannel", remote=True),
    "qq": _meta("qq", "QQ Bot", "channels.qq", "QQBotChannel", remote=True),
    "telegram": _meta("telegram", "Telegram", "channels.telegram", "TelegramChannel", remote=True),
    "feishu": _meta("feishu", "Feishu", "channels.feishu", "FeishuChannel", remote=True),
    "dingtalk": _meta("dingtalk", "DingTalk", "channels.dingtalk", "DingTalkChannel", remote=True),
}

CHANNEL_NAMES = tuple(CHANNEL_META.keys())
REMOTE_CHANNELS = frozenset(name for name, meta in CHANNEL_META.items() if meta["remote"])
CHANNEL_LABELS = {name: meta["label"] for name, meta in CHANNEL_META.items()}


def create_channel(name: str, config: dict):
    """按注册表工厂实例化渠道对象。"""
    meta = CHANNEL_META[name]
    module = importlib.import_module(meta["module"])
    return getattr(module, meta["class"])(config)
