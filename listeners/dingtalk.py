"""钉钉临时/常驻 Stream 监听器。"""

import threading

from common.log import log as _log_impl
from .base import _handle_received, _update_config, _log


def _dingtalk_listener(config: dict, stop_event: threading.Event, request_id: str = None, pending: dict = None):
    """钉钉临时 Stream 监听"""
    try:
        import dingtalk_stream
        from dingtalk_stream import ChatbotHandler, Credential
    except ImportError:
        _log("[dingtalk] dingtalk-stream 未安装，跳过")
        return

    dt_cfg = config.get("dingtalk", {})
    client_id = dt_cfg.get("client_id", "")
    client_secret = dt_cfg.get("client_secret", "")

    _log("[dingtalk] 临时 Stream 连接中...")

    credential = Credential(client_id, client_secret)
    client = dingtalk_stream.DingTalkStreamClient(credential)

    class BotHandler(ChatbotHandler):
        def process(self, callback_message):
            try:
                message = dingtalk_stream.ChatbotMessage.from_dict(callback_message.data)
                content = ""
                if message.text and hasattr(message.text, 'content'):
                    content = message.text.content.strip()

                sender_id = message.sender_staff_id or message.sender_id or ""
                if sender_id and not config.get("dingtalk", {}).get("user_id"):
                    _update_config("dingtalk", "user_id", sender_id)
                    config["dingtalk"]["user_id"] = sender_id

                if content:
                    _log(f"[dingtalk] 收到消息: len={len(content)}")
                    _handle_received(content, "dingtalk", stop_event, request_id, pending)
            except Exception as e:
                _log(f"[dingtalk] 处理消息异常: {e}")

    client.register_callback_handler(dingtalk_stream.ChatbotMessage.TOPIC, BotHandler())

    # 看门狗：收到回复后停止 client
    def _watchdog():
        stop_event.wait()
        try:
            client.stop()
        except Exception:
            pass

    threading.Thread(target=_watchdog, daemon=True).start()

    try:
        client.start_forever()
    except Exception:
        pass
    _log("[dingtalk] 临时监听退出")

