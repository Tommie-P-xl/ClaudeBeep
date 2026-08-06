"""Telegram 临时/常驻长轮询监听器。"""

import json
import time
import threading
import urllib.request

from common.log import log as _log_impl
from .base import _handle_received, _update_config, _log


def _get_telegram_latest_offset(base_url: str) -> int:
    """获取 Telegram 最新 update_id，避免重复处理历史消息"""
    import urllib.request
    try:
        url = f"{base_url}/getUpdates?limit=1&offset=-1"
        req = urllib.request.Request(url, method="GET")
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode("utf-8"))
        results = data.get("result", [])
        if results:
            return results[-1]["update_id"] + 1
    except Exception:
        pass
    return 0


def _telegram_listener(config: dict, stop_event: threading.Event, request_id: str = None, pending: dict = None):
    """Telegram 临时长轮询监听"""
    import urllib.request

    bot_token = config["telegram"]["bot_token"]
    base_url = f"https://api.telegram.org/bot{bot_token}"

    # 获取当前 offset（从最新消息开始，不重复处理历史消息）
    offset = _get_telegram_latest_offset(base_url)
    _log(f"[telegram] 临时监听启动, offset={offset}")

    while not stop_event.is_set():
        try:
            url = f"{base_url}/getUpdates?timeout=20&offset={offset}&allowed_updates=[\"message\"]"
            req = urllib.request.Request(url, method="GET")
            resp = urllib.request.urlopen(req, timeout=25)
            data = json.loads(resp.read().decode("utf-8"))

            if data.get("ok"):
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    text = update.get("message", {}).get("text", "").strip()
                    chat_id = str(update.get("message", {}).get("chat", {}).get("id", ""))

                    # 自动更新 chat_id（如果尚未配置）
                    if chat_id and not config.get("telegram", {}).get("chat_id"):
                        _update_config("telegram", "chat_id", chat_id)
                        config["telegram"]["chat_id"] = chat_id

                    if text:
                        _log(f"[telegram] 收到消息: len={len(text)}")
                        _handle_received(text, "telegram", stop_event, request_id, pending)
                        if stop_event.is_set():
                            return
            else:
                time.sleep(2)
        except Exception:
            if not stop_event.is_set():
                time.sleep(2)

    _log("[telegram] 临时监听退出")

