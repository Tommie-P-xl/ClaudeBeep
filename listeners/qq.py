"""QQ Bot 临时/常驻 WebSocket 监听器。"""

import json
import time
import threading

from common.log import log as _log_impl
from .base import _handle_received, _update_config, _log


def _qq_get_access_token(app_id: str, app_secret: str) -> str:
    """获取 QQ Bot access_token"""
    import urllib.request
    body = json.dumps({"appId": app_id, "clientSecret": app_secret}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request("https://bots.qq.com/app/getAppAccessToken", data=body, headers=headers, method="POST")
    resp = urllib.request.urlopen(req, timeout=15)
    data = json.loads(resp.read().decode("utf-8"))
    return data.get("access_token", "")


def _qq_get_gateway(access_token: str) -> str:
    """获取 QQ WebSocket 网关地址"""
    import urllib.request
    headers = {"Authorization": f"QQBot {access_token}"}
    req = urllib.request.Request("https://api.sgroup.qq.com/gateway", method="GET")
    for k, v in headers.items():
        req.add_header(k, v)
    resp = urllib.request.urlopen(req, timeout=15)
    data = json.loads(resp.read().decode("utf-8"))
    return data.get("url", "")


def _qq_listener(config: dict, stop_event: threading.Event, request_id: str = None, pending: dict = None):
    """QQ WebSocket 临时监听"""
    import asyncio

    async def _async_qq():
        try:
            import websockets
        except ImportError:
            _log("[qq] websockets 未安装，跳过")
            return

        qq_cfg = config.get("qq", {})
        app_id = qq_cfg.get("app_id", "")
        app_secret = qq_cfg.get("app_secret", "")

        # 1. 获取 access_token 和 gateway
        try:
            token = _qq_get_access_token(app_id, app_secret)
        except Exception as e:
            _log(f"[qq] 获取 access_token 失败: {e}")
            return
        if not token:
            _log("[qq] access_token 为空")
            return
        try:
            gateway = _qq_get_gateway(token)
        except Exception as e:
            _log(f"[qq] 获取 gateway 失败: {e}")
            return
        if not gateway:
            _log("[qq] gateway 为空")
            return

        _log(f"[qq] 临时 WebSocket 连接中...")

        # 2. 建立 WebSocket 连接
        try:
            async with websockets.connect(gateway, ping_interval=None) as ws:
                # Hello → Identify → READY
                hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                heartbeat_interval = hello.get("d", {}).get("heartbeat_interval", 40000) / 1000

                await ws.send(json.dumps({
                    "op": 2,
                    "d": {
                        "token": f"QQBot {token}",
                        "intents": 1 << 25,  # C2C + GROUP
                        "shard": [0, 1],
                        "properties": {
                            "$os": "windows",
                            "$browser": "claude-notify",
                            "$device": "claude-notify",
                        },
                    }
                }))

                # 等待 READY
                ready_raw = await asyncio.wait_for(ws.recv(), timeout=10)
                ready = json.loads(ready_raw)
                if ready.get("t") == "READY":
                    _log("[qq] WebSocket 已连接，监听消息...")

                # 心跳 + 事件循环
                last_heartbeat = time.time()
                while not stop_event.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=2)
                        msg = json.loads(raw)
                        op = msg.get("op")
                        event_type = msg.get("t")

                        # 心跳响应
                        if op == 1:
                            await ws.send(json.dumps({"op": 1, "d": None}))
                            last_heartbeat = time.time()
                            continue

                        if op == 0 and event_type:
                            d = msg.get("d", {})
                            author = d.get("author", {})
                            user_openid = author.get("user_openid", "")
                            if not user_openid:
                                user_openid = author.get("id", "")
                            content = d.get("content", "").strip()

                            # 自动更新 target_id
                            if user_openid and not config.get("qq", {}).get("target_id"):
                                _update_config("qq", "target_id", f"qqbot:c2c:{user_openid}")
                                config["qq"]["target_id"] = f"qqbot:c2c:{user_openid}"

                            if content:
                                _log(f"[qq] 收到消息: len={len(content)} (event={event_type})")
                                _handle_received(content, "qq", stop_event, request_id, pending)

                    except asyncio.TimeoutError:
                        if time.time() - last_heartbeat >= heartbeat_interval:
                            await ws.send(json.dumps({"op": 1, "d": None}))
                            last_heartbeat = time.time()
        except Exception as e:
            if not stop_event.is_set():
                _log(f"[qq] WebSocket 异常: {e}")

    # 在独立 event loop 中运行（避免与主线程冲突）
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_async_qq())
    finally:
        loop.close()
    _log("[qq] 临时监听退出")

