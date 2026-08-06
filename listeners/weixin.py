"""微信临时轮询监听器（常驻轮询由 channels.weixin keepalive 持有）。"""

import json
import time
import threading
import random
import base64
import urllib.request
import urllib.error

from common.log import log as _log_impl
from .base import _handle_received, _update_config, _log


def _random_wechat_uin() -> str:
    """生成随机的 X-WECHAT-UIN 头"""
    uint32 = random.randint(0, 2**32 - 1)
    return base64.b64encode(str(uint32).encode("utf-8")).decode("utf-8")


def _weixin_listener(config: dict, stop_event: threading.Event, request_id: str = None, pending: dict = None):
    """微信临时 getupdates 轮询"""
    import urllib.request
    import urllib.error

    wx_cfg = config.get("weixin", {})
    token = wx_cfg.get("bot_token", "")
    baseurl = wx_cfg.get("baseurl", "https://ilinkai.weixin.qq.com").rstrip("/")

    if not token:
        return

    _log("[weixin] 临时轮询启动")

    sync_buf = ""
    consecutive_failures = 0

    while not stop_event.is_set():
        try:
            body = json.dumps({
                "get_updates_buf": sync_buf,
                "base_info": {"channel_version": "2.2.0"}
            }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

            headers = {
                "Content-Type": "application/json",
                "AuthorizationType": "ilink_bot_token",
                "Authorization": f"Bearer {token}",
                "X-WECHAT-UIN": _random_wechat_uin(),
                "iLink-App-Id": "bot",
                "iLink-App-ClientVersion": str((2 << 16) | (2 << 8) | 0),
                "Content-Length": str(len(body)),
            }

            url = f"{baseurl}/ilink/bot/getupdates"
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            resp = urllib.request.urlopen(req, timeout=40)
            data = json.loads(resp.read().decode("utf-8", errors="replace"))

            ret = data.get("ret", 0)
            errcode = data.get("errcode", 0)

            if ret == 0 and errcode == 0:
                consecutive_failures = 0
                new_buf = data.get("get_updates_buf", "")
                if new_buf:
                    sync_buf = new_buf

                for msg in data.get("msgs", []):
                    # 更新 context_token 和 to_user_id（如需要）
                    ctx = msg.get("context_token", "")
                    if ctx:
                        _update_config("weixin", "context_token", ctx)
                        config.setdefault("weixin", {})["context_token"] = ctx

                    from_user = msg.get("from_user_id", "")
                    if from_user and not wx_cfg.get("to_user_id"):
                        _update_config("weixin", "to_user_id", from_user)
                        config.setdefault("weixin", {})["to_user_id"] = from_user

                    # 处理消息内容
                    for item in msg.get("item_list", []):
                        if item.get("type") == 1:
                            text = item.get("text_item", {}).get("text", "").strip()
                            if text:
                                _log(f"[weixin] 收到消息: len={len(text)}")
                                _handle_received(text, "weixin", stop_event, request_id, pending)
                            break

            elif errcode == -14 or ret == -14:
                # bot session 过期，无法继续监听
                _log("[weixin] listener: session 过期，请在 Web UI 重新扫码登录")
                return

            elif ret == -2:
                # context_token 过期，清空 sync_buf 继续轮询（下次可能恢复）
                _log("[weixin] listener: ret=-2, context_token 可能过期，清空 sync_buf 继续")
                sync_buf = ""
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    return
                time.sleep(3)

            else:
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    _log("[weixin] 连续失败，退出监听")
                    return
                time.sleep(3)

        except urllib.error.URLError as e:
            if "timed out" not in str(getattr(e, 'reason', '')).lower():
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    return
                time.sleep(3)
        except Exception:
            consecutive_failures += 1
            if consecutive_failures >= 3:
                return
            time.sleep(3)

    _log("[weixin] 临时轮询退出")
