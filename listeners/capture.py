"""各渠道 OpenID / ChatID / UserID 捕获（Web UI 设置用）。

统一模式：后台线程建立长连接监听，捕获第一条消息的身份 ID 后写回配置。
超时由看门狗线程兜底，异常时状态置 error（R2）。
"""

import json
import threading
import time

from common.log import log as _log_impl
from .base import _update_config, _log
from .qq import _qq_get_access_token, _qq_get_gateway
from .telegram import _get_telegram_latest_offset


_qq_capture_result = {"status": "idle", "open_id": None, "error": None}
_qq_capture_lock = threading.Lock()


def start_qq_openid_capture(app_id: str, app_secret: str):
    """启动后台 WebSocket 监听，捕获第一条消息的 OpenID。"""
    global _qq_capture_result
    with _qq_capture_lock:
        _qq_capture_result = {"status": "waiting", "open_id": None, "error": None}

    def _capture_thread():
        import asyncio
        global _qq_capture_result
        try:
            import websockets
        except ImportError:
            with _qq_capture_lock:
                _qq_capture_result = {"status": "error", "open_id": None, "error": "websockets 未安装"}
            return

        async def _async_capture():
            try:
                token = _qq_get_access_token(app_id, app_secret)
            except Exception as e:
                _log(f"[qq-capture] 获取 access_token 异常: {e}")
                with _qq_capture_lock:
                    _qq_capture_result = {"status": "error", "open_id": None, "error": f"获取 access_token 失败: {e}"}
                return
            if not token:
                with _qq_capture_lock:
                    _qq_capture_result = {"status": "error", "open_id": None, "error": "获取 access_token 失败"}
                return

            try:
                gateway = _qq_get_gateway(token)
            except Exception as e:
                _log(f"[qq-capture] 获取 gateway 异常: {e}")
                with _qq_capture_lock:
                    _qq_capture_result = {"status": "error", "open_id": None, "error": f"获取 gateway 失败: {e}"}
                return
            if not gateway:
                with _qq_capture_lock:
                    _qq_capture_result = {"status": "error", "open_id": None, "error": "获取 gateway 失败"}
                return

            _log("[qq-capture] WebSocket 连接中...")
            try:
                async with websockets.connect(gateway, ping_interval=None) as ws:
                    hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                    heartbeat_interval = hello.get("d", {}).get("heartbeat_interval", 40000) / 1000

                    await ws.send(json.dumps({
                        "op": 2,
                        "d": {
                            "token": f"QQBot {token}",
                            "intents": (1 << 25) | (1 << 12),
                            "shard": [0, 1],
                            "properties": {"$os": "windows", "$browser": "claudebeep", "$device": "claudebeep"},
                        }
                    }))

                    ready = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                    if ready.get("t") != "READY":
                        with _qq_capture_lock:
                            _qq_capture_result = {"status": "error", "open_id": None, "error": f"WebSocket 握手失败: {ready}"}
                        return

                    _log("[qq-capture] 已连接，等待用户发消息...")
                    last_heartbeat = time.time()
                    deadline = time.time() + 150  # 2.5 分钟超时

                    while time.time() < deadline:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=2)
                            msg = json.loads(raw)
                            op = msg.get("op")
                            event_type = msg.get("t")
                            _log(f"[qq-capture] 收到事件 op={op} t={event_type}")

                            # 心跳
                            if op == 1:
                                await ws.send(json.dumps({"op": 1, "d": None}))
                                last_heartbeat = time.time()
                                continue

                            # 处理所有消息事件
                            if op == 0 and event_type:
                                d = msg.get("d", {})
                                author = d.get("author", {})
                                user_openid = author.get("user_openid", "")

                                # 也检查其他可能的字段
                                if not user_openid:
                                    user_openid = author.get("id", "")
                                if not user_openid:
                                    user_openid = d.get("user_openid", "")

                                if user_openid:
                                    target_id = f"qqbot:c2c:{user_openid}"
                                    _update_config("qq", "target_id", target_id)
                                    _log(f"[qq-capture] 捕获 OpenID: {user_openid} (event={event_type})")
                                    with _qq_capture_lock:
                                        _qq_capture_result = {"status": "done", "open_id": target_id, "error": None}
                                    return

                        except asyncio.TimeoutError:
                            if time.time() - last_heartbeat >= heartbeat_interval:
                                await ws.send(json.dumps({"op": 1, "d": None}))
                                last_heartbeat = time.time()

                    with _qq_capture_lock:
                        _qq_capture_result = {"status": "timeout", "open_id": None, "error": "等待超时"}

            except Exception as e:
                _log(f"[qq-capture] WebSocket 异常: {e}")
                with _qq_capture_lock:
                    _qq_capture_result = {"status": "error", "open_id": None, "error": str(e)}

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_async_capture())
        finally:
            loop.close()

    threading.Thread(target=_capture_thread, daemon=True).start()


def get_qq_capture_status() -> dict:
    with _qq_capture_lock:
        return dict(_qq_capture_result)




_tg_capture_result = {"status": "idle", "chat_id": None, "error": None}
_tg_capture_lock = threading.Lock()


def start_tg_chatid_capture(bot_token: str):
    """启动后台 Telegram 长轮询，捕获第一条消息的 Chat ID。"""
    global _tg_capture_result
    with _tg_capture_lock:
        _tg_capture_result = {"status": "waiting", "chat_id": None, "error": None}

    def _capture_thread():
        global _tg_capture_result
        import urllib.request
        base_url = f"https://api.telegram.org/bot{bot_token}"
        _log("[tg-capture] 长轮询启动")

        try:
            # 先跳过历史消息
            offset = _get_telegram_latest_offset(base_url)
            deadline = time.time() + 150

            while time.time() < deadline:
                try:
                    url = f"{base_url}/getUpdates?timeout=10&offset={offset}&allowed_updates=[\"message\"]"
                    req = urllib.request.Request(url, method="GET")
                    resp = urllib.request.urlopen(req, timeout=15)
                    data = json.loads(resp.read().decode("utf-8"))

                    if data.get("ok"):
                        for update in data.get("result", []):
                            offset = update["update_id"] + 1
                            chat_id = str(update.get("message", {}).get("chat", {}).get("id", ""))
                            if chat_id:
                                _update_config("telegram", "chat_id", chat_id)
                                _log(f"[tg-capture] 捕获 Chat ID: {chat_id}")
                                with _tg_capture_lock:
                                    _tg_capture_result = {"status": "done", "chat_id": chat_id, "error": None}
                                return
                    else:
                        time.sleep(2)
                except Exception:
                    if time.time() < deadline:
                        time.sleep(2)

            with _tg_capture_lock:
                _tg_capture_result = {"status": "timeout", "chat_id": None, "error": "等待超时"}

        except Exception as e:
            _log(f"[tg-capture] 异常: {e}")
            with _tg_capture_lock:
                _tg_capture_result = {"status": "error", "chat_id": None, "error": str(e)}

    threading.Thread(target=_capture_thread, daemon=True).start()


def get_tg_capture_status() -> dict:
    with _tg_capture_lock:
        return dict(_tg_capture_result)




_fs_capture_result = {"status": "idle", "receive_id": None, "error": None}
_fs_capture_lock = threading.Lock()


def start_fs_openid_capture(app_id: str, app_secret: str):
    """启动后台飞书 WebSocket，捕获第一条消息的 Open ID。"""
    global _fs_capture_result
    with _fs_capture_lock:
        _fs_capture_result = {"status": "waiting", "receive_id": None, "error": None}

    def _capture_thread():
        global _fs_capture_result
        try:
            import lark_oapi as lark
            from lark_oapi.ws import Client as WsClient
        except ImportError:
            with _fs_capture_lock:
                _fs_capture_result = {"status": "error", "receive_id": None, "error": "lark-oapi 未安装"}
            return

        captured = threading.Event()

        def on_message(data):
            try:
                sender = data.event.sender
                open_id = sender.sender_id.open_id if sender and sender.sender_id else ""
                if open_id:
                    _update_config("feishu", "receive_id", open_id)
                    _log(f"[fs-capture] 捕获 Open ID: {open_id}")
                    with _fs_capture_lock:
                        _fs_capture_result = {"status": "done", "receive_id": open_id, "error": None}
                    captured.set()
            except Exception as e:
                _log(f"[fs-capture] 处理消息异常: {e}")

        event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(on_message)
            .build()
        )

        client = WsClient(
            app_id=app_id,
            app_secret=app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.WARNING,
        )

        # 超时看门狗
        def _timeout_watchdog():
            if not captured.wait(timeout=150):
                with _fs_capture_lock:
                    if _fs_capture_result["status"] == "waiting":
                        _fs_capture_result = {"status": "timeout", "receive_id": None, "error": "等待超时"}
                try:
                    if hasattr(client, '_Client__ws_client') and client._Client__ws_client:
                        client._Client__ws_client.close()
                except Exception:
                    pass

        threading.Thread(target=_timeout_watchdog, daemon=True).start()

        try:
            _log("[fs-capture] WebSocket 连接中...")
            client.start()
        except Exception as e:
            if not captured.is_set():
                _log(f"[fs-capture] 异常: {e}")
                with _fs_capture_lock:
                    _fs_capture_result = {"status": "error", "receive_id": None, "error": str(e)}

    threading.Thread(target=_capture_thread, daemon=True).start()


def get_fs_capture_status() -> dict:
    with _fs_capture_lock:
        return dict(_fs_capture_result)




_dt_capture_result = {"status": "idle", "user_id": None, "error": None}
_dt_capture_lock = threading.Lock()


def start_dt_userid_capture(client_id: str, client_secret: str):
    """启动后台钉钉 Stream，捕获第一条消息的 User ID。"""
    global _dt_capture_result
    with _dt_capture_lock:
        _dt_capture_result = {"status": "waiting", "user_id": None, "error": None}

    def _capture_thread():
        global _dt_capture_result
        try:
            import dingtalk_stream
            from dingtalk_stream import ChatbotHandler, Credential
        except ImportError:
            with _dt_capture_lock:
                _dt_capture_result = {"status": "error", "user_id": None, "error": "dingtalk-stream 未安装"}
            return

        captured = threading.Event()
        credential = Credential(client_id, client_secret)
        stream_client = dingtalk_stream.DingTalkStreamClient(credential)

        class CaptureHandler(ChatbotHandler):
            def process(self, callback_message):
                try:
                    message = dingtalk_stream.ChatbotMessage.from_dict(callback_message.data)
                    sender_id = message.sender_staff_id or message.sender_id or ""
                    if sender_id:
                        _update_config("dingtalk", "user_id", sender_id)
                        _log(f"[dt-capture] 捕获 User ID: {sender_id}")
                        with _dt_capture_lock:
                            _dt_capture_result = {"status": "done", "user_id": sender_id, "error": None}
                        captured.set()
                except Exception as e:
                    _log(f"[dt-capture] 处理消息异常: {e}")

        stream_client.register_callback_handler(dingtalk_stream.ChatbotMessage.TOPIC, CaptureHandler())

        # 超时看门狗
        def _timeout_watchdog():
            if not captured.wait(timeout=150):
                with _dt_capture_lock:
                    if _dt_capture_result["status"] == "waiting":
                        _dt_capture_result = {"status": "timeout", "user_id": None, "error": "等待超时"}
                try:
                    stream_client.stop()
                except Exception:
                    pass

        threading.Thread(target=_timeout_watchdog, daemon=True).start()

        try:
            _log("[dt-capture] Stream 连接中...")
            stream_client.start_forever()
        except Exception as e:
            if not captured.is_set():
                _log(f"[dt-capture] 异常: {e}")
                with _dt_capture_lock:
                    _dt_capture_result = {"status": "error", "user_id": None, "error": str(e)}

    threading.Thread(target=_capture_thread, daemon=True).start()


def get_dt_capture_status() -> dict:
    with _dt_capture_lock:
        return dict(_dt_capture_result)

