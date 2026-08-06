"""飞书临时/常驻 WebSocket 监听器。"""

import json
import threading

from common.log import log as _log_impl
from .base import _handle_received, _update_config, _log


def _feishu_listener(config: dict, stop_event: threading.Event, request_id: str = None, pending: dict = None):
    """飞书临时 WebSocket 监听"""
    try:
        import lark_oapi as lark
        from lark_oapi.ws import Client as WsClient
    except ImportError:
        _log("[feishu] lark-oapi 未安装，跳过")
        return

    fs_cfg = config.get("feishu", {})
    app_id = fs_cfg.get("app_id", "")
    app_secret = fs_cfg.get("app_secret", "")

    _log("[feishu] 临时 WebSocket 连接中...")

    def on_message(data):
        try:
            msg = data.event.message
            sender = data.event.sender
            open_id = sender.sender_id.open_id if sender and sender.sender_id else ""

            # 自动更新 receive_id
            if open_id and not config.get("feishu", {}).get("receive_id"):
                _update_config("feishu", "receive_id", open_id)
                config["feishu"]["receive_id"] = open_id

            content = ""
            if msg.content:
                try:
                    content = json.loads(msg.content).get("text", "").strip()
                except Exception:
                    pass

            if content:
                _log(f"[feishu] 收到消息: len={len(content)}")
                _handle_received(content, "feishu", stop_event, request_id, pending)
        except Exception as e:
            _log(f"[feishu] 处理消息异常: {e}")

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

    # 看门狗线程：stop_event 被 set 后强制停止 client
    def _watchdog():
        stop_event.wait()  # 阻塞直到 stop_event 被 set
        try:
            # 尝试关闭 SDK 内部 websocket
            if hasattr(client, '_Client__ws_client') and client._Client__ws_client:
                client._Client__ws_client.close()
        except Exception:
            pass

    threading.Thread(target=_watchdog, daemon=True).start()

    try:
        client.start()
    except Exception:
        pass
    _log("[feishu] 临时监听退出")

