"""监听协调层（M2）：临时/常驻监听启动、消息分发、反馈发送。

渠道监听器实现位于 listeners/telegram.py 等子模块；
各渠道的 OpenID/ChatID 捕获位于 listeners/capture.py。
本模块不依赖具体渠道实现，避免循环导入。
"""

import json
import os
import threading
import time

from common.log import log, redact_key_value
from common.paths import RUNTIME_DIR
from interaction import _extract_reply_parts  # 与 interaction 共用唯一实现（Q2）


def _log(msg: str):
    log("listener", msg)


# ── 配置辅助 ──────────────────────────────────────────────

def _update_config(channel: str, key: str, value: str):
    """原子更新 config.json 中指定渠道的字段"""
    config_file = RUNTIME_DIR / "config.json"
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if channel not in cfg:
            cfg[channel] = {}
        if cfg[channel].get(key) == value:
            return
        cfg[channel][key] = value
        import tempfile
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(RUNTIME_DIR), suffix=".tmp")
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, str(config_file))
        _log(f"[{channel}] 自动更新 {key}={redact_key_value(key, value)}")
    except Exception as e:
        _log(f"[{channel}] 更新配置失败: {e}")


# ── 消息处理 ──────────────────────────────────────────────

def _process_message(text: str, channel: str, request_id: str, pending: dict, stop_event: threading.Event) -> bool:
    """
    解析收到的消息，判断是否匹配当前请求。
    匹配成功则写入 response 文件并 set stop_event。
    返回 True 表示成功处理。
    """
    # 1. 解析标签和回复内容
    label, reply = _extract_reply_parts(text)

    # 2. 省略标签时，默认回复当前请求
    if not label:
        reply = text.strip()
        label = pending.get("label", "")

    # 3. 标签不匹配，忽略
    if label.upper() != pending.get("label", "").upper():
        return False

    if not reply:
        return False

    _log(f"[{channel}] 匹配请求: label={label}, reply_len={len(reply)}")

    # 4. 写入 response 文件（原子操作）
    from interaction import write_response
    success = write_response(request_id, reply, channel, label=label)

    if success:
        stop_event.set()
        # 向回复渠道发送确认反馈（在独立线程中发，不阻塞主流程）
        threading.Thread(
            target=_send_confirmation,
            args=(channel, label, reply),
            daemon=True
        ).start()
        return True
    else:
        # 已被其他渠道抢先处理
        _send_already_handled_feedback(channel, label)
        return False


def _process_message_global(text: str, channel: str):
    """
    托盘常驻监听的全局消息处理（P1）：遍历所有 pending 文件，找到 label 匹配的请求。
    与临时模式不同，这里不依赖单请求上下文，也不停止监听线程（常驻）。
    """
    label, reply = _extract_reply_parts(text)
    if not reply or not label:
        return

    from interaction import list_requests, write_response
    if not (RUNTIME_DIR / "pending").exists():
        return

    for req in list_requests():
        req_label = req.get("label", "").upper()
        if req_label == label.upper():
            success = write_response(req["id"], reply, channel, label=label)
            if success:
                _log(f"[{channel}] 全局分发: label={label}, reply_len={len(reply)}")
                threading.Thread(
                    target=_send_confirmation,
                    args=(channel, label, reply),
                    daemon=True
                ).start()
            else:
                _send_already_handled_feedback(channel, label)
            return

    # 未找到匹配请求
    _send_no_pending_feedback(channel, label)


def _handle_received(text: str, channel: str, stop_event: threading.Event,
                     request_id: str = None, pending: dict = None):
    """双模式消息分发（P1）：
    - 临时模式（hook 进程，request_id 非空）：按单请求处理并停止监听；
    - 常驻模式（托盘进程，request_id 为空）：走全局分发，监听持续运行。
    """
    if request_id is not None and pending is not None:
        _process_message(text, channel, request_id, pending, stop_event)
    else:
        _process_message_global(text, channel)


# ── 反馈发送 ──────────────────────────────────────────────

def _send_confirmation(channel: str, label: str, reply: str):
    """向回复渠道发送确认反馈"""
    try:
        from notify import load_config
        cfg = load_config()
        ch = _create_channel(channel, cfg)
        if ch:
            ch.send("Claude Code - 回复确认", f"已收到回复: {reply}")
            _log(f"[{channel}] 确认反馈已发送")
    except Exception as e:
        _log(f"[{channel}] 发送确认反馈失败: {e}")


def _send_already_handled_feedback(channel: str, label: str):
    """向渠道发送'已处理'反馈"""
    try:
        from notify import load_config
        cfg = load_config()
        ch = _create_channel(channel, cfg)
        if ch:
            ch.send("Claude Code - 已处理", f"#{label} 已被其他渠道处理，您的回复已忽略")
            _log(f"[{channel}] 已处理反馈已发送")
    except Exception as e:
        _log(f"[{channel}] 发送已处理反馈失败: {e}")


def _send_no_pending_feedback(channel: str, label: str = ""):
    """向渠道发送'无待处理请求'反馈"""
    try:
        from notify import load_config
        cfg = load_config()
        ch = _create_channel(channel, cfg)
        if ch:
            msg = f"当前无等待回复的请求（#{label} 可能已被其他渠道处理）" if label else "当前无等待回复的请求"
            ch.send("Claude Code - 提示", msg)
    except Exception:
        pass


def _create_channel(channel: str, cfg: dict):
    """根据渠道名创建渠道实例（复用渠道注册表工厂，M8）"""
    from common.channels_registry import create_channel
    try:
        return create_channel(channel, cfg)
    except KeyError:
        return None


def _tray_manages_channel(channel: str) -> bool:
    """托盘进程活跃且声明管理该渠道时，hook 进程不再重复启动临时监听（P1）。"""
    try:
        heartbeat = RUNTIME_DIR / "tray_heartbeat.json"
        if not heartbeat.exists():
            return False
        data = json.loads(heartbeat.read_text(encoding="utf-8"))
        if time.time() - float(data.get("ts", 0)) >= 90:
            return False
        if channel in data.get("managed_channels", []):
            return True
        # 兼容旧字段：微信 keepalive
        if channel == "weixin" and data.get("weixin_keepalive") is True:
            return True
    except Exception:
        pass
    return False


def _tray_is_managing_weixin() -> bool:
    """兼容别名：微信长轮询是否由托盘统一持有。"""
    return _tray_manages_channel("weixin")


# ── 对外接口 ──────────────────────────────────────────────

def start_listeners(config: dict, request_id: str, pending: dict, stop_event: threading.Event):
    """
    根据 config 中已启用的渠道，启动对应的临时监听线程。
    所有线程共享同一个 stop_event，任一渠道收到回复后 set stop_event。
    若托盘进程已在托管某渠道（heartbeat），则跳过该渠道避免重复监听。

    参数：
      config      - 完整配置 dict
      request_id  - 当前 pending 请求 ID
      pending     - pending dict（含 label 等信息）
      stop_event  - threading.Event，set 后所有线程退出
    """
    from .telegram import _telegram_listener
    from .qq import _qq_listener
    from .feishu import _feishu_listener
    from .dingtalk import _dingtalk_listener
    from .weixin import _weixin_listener

    threads = []

    if (config.get("telegram", {}).get("enabled") and config.get("telegram", {}).get("bot_token")
            and not _tray_manages_channel("telegram")):
        t = threading.Thread(
            target=_telegram_listener,
            args=(config, stop_event, request_id, pending),
            daemon=True,
            name="listener-telegram"
        )
        threads.append(t)

    if (config.get("qq", {}).get("enabled") and config.get("qq", {}).get("app_id")
            and not _tray_manages_channel("qq")):
        t = threading.Thread(
            target=_qq_listener,
            args=(config, stop_event, request_id, pending),
            daemon=True,
            name="listener-qq"
        )
        threads.append(t)

    if (config.get("feishu", {}).get("enabled") and config.get("feishu", {}).get("app_id")
            and not _tray_manages_channel("feishu")):
        t = threading.Thread(
            target=_feishu_listener,
            args=(config, stop_event, request_id, pending),
            daemon=True,
            name="listener-feishu"
        )
        threads.append(t)

    if (config.get("dingtalk", {}).get("enabled") and config.get("dingtalk", {}).get("client_id")
            and not _tray_manages_channel("dingtalk")):
        t = threading.Thread(
            target=_dingtalk_listener,
            args=(config, stop_event, request_id, pending),
            daemon=True,
            name="listener-dingtalk"
        )
        threads.append(t)

    if (config.get("weixin", {}).get("enabled") and config.get("weixin", {}).get("bot_token")
            and not _tray_is_managing_weixin()):
        t = threading.Thread(
            target=_weixin_listener,
            args=(config, stop_event, request_id, pending),
            daemon=True,
            name="listener-weixin"
        )
        threads.append(t)

    for t in threads:
        t.start()

    if threads:
        _log(f"启动 {len(threads)} 个临时监听线程: {', '.join(t.name for t in threads)}")

    return threads


def managed_channel_names(config: dict) -> list:
    """返回托盘进程应统一托管的远程渠道列表（P1）。"""
    names = []
    try:
        from common.channels_registry import REMOTE_CHANNELS
        for platform in ("claude_code", "codex"):
            integration = config.get("integrations", {}).get(platform, {})
            if not integration.get("enabled"):
                continue
            for ch, enabled in integration.get("channels", {}).items():
                if enabled and ch in REMOTE_CHANNELS:
                    names.append(ch)
    except Exception:
        pass
    return sorted(set(names))


def start_managed_listeners(config: dict, stop_event: threading.Event):
    """
    托盘常驻监听（P1）：托盘进程统一持有各远程渠道的长连接（微信由 keepalive 持有），
    收到消息走全局分发（匹配 pending 目录中的请求）。hook 进程检测到托盘托管后不再重复监听。
    """
    from .telegram import _telegram_listener
    from .qq import _qq_listener
    from .feishu import _feishu_listener
    from .dingtalk import _dingtalk_listener

    threads = []
    for channel in managed_channel_names(config):
        target = {
            "telegram": _telegram_listener,
            "qq": _qq_listener,
            "feishu": _feishu_listener,
            "dingtalk": _dingtalk_listener,
        }.get(channel)
        if target is None:
            continue  # weixin 由 keepalive 单独持有
        t = threading.Thread(
            target=target,
            args=(config, stop_event),
            daemon=True,
            name=f"managed-{channel}"
        )
        threads.append(t)

    for t in threads:
        t.start()

    if threads:
        _log(f"托盘托管 {len(threads)} 个渠道监听: {', '.join(t.name for t in threads)}")
    return threads
