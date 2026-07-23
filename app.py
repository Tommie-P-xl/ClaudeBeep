"""Flask 后端 — ClaudeBeep Web UI。"""

import json
import sys
import time
import threading
import subprocess
import uuid
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory, Response, abort

SCRIPT_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", SCRIPT_DIR))
CONFIG_FILE = SCRIPT_DIR / "config.json"
LOG_FILE = SCRIPT_DIR / "notify.log"
CLAUDECODE_SETTINGS = Path.home() / ".claude" / "settings.json"

sys.path.insert(0, str(SCRIPT_DIR))

# SSE 连接跟踪：浏览器关闭后自动退出
_sse_connections = set()
_sse_lock = threading.Lock()
_SSE_SHUTDOWN_DELAY = 2  # 秒，所有连接断开后等待时间


_sse_shutdown_event = threading.Event()


def create_app() -> Flask:
    app = Flask(__name__, static_folder=str(RESOURCE_DIR / "static"))

    from config_store import (
        CHANNEL_NAMES, CLAUDE_EVENTS, CODEX_EVENTS, PLATFORMS,
        CHANNEL_SECRET_FIELDS, ConfigFileError, get_integration,
        is_channel_configured, load_config, save_config,
    )
    from hook_manager import HookFileError, inspect_hooks, sync_hooks, uninstall_hooks as remove_hooks
    import hook_manager
    import notification_core as notification_service
    from notification_core import NotificationEvent

    @app.errorhandler(ConfigFileError)
    def config_file_error(error):
        return jsonify({"ok": False, "error": "配置文件无法读取，请检查配置格式"}), 409

    @app.errorhandler(HookFileError)
    def hook_file_error(error):
        return jsonify({"ok": False, "error": "Hook 文件无法读取，请检查 Hook 配置格式"}), 409

    def require_platform(platform: str) -> str:
        if platform not in PLATFORMS:
            abort(404)
        return platform

    def require_channel(name: str) -> str:
        if name not in CHANNEL_NAMES:
            abort(404)
        return name

    def hook_status(platform: str, configured_events):
        return {
            "configured_events": list(configured_events),
            "trust_review_required": platform == "codex" and bool(configured_events),
            "trust_command": "/hooks",
        }

    def validate_channel_credentials(cfg: dict, name: str) -> str | None:
        if is_channel_configured(cfg, name):
            return None
        values = cfg.get("channels", {}).get(name, {})
        if name == "weixin" and (not values.get("bot_token") or not values.get("to_user_id")):
            return "请先完成微信扫码登录并配置接收用户 ID（to_user_id）"
        if name == "qq" and (not values.get("app_id") or not values.get("app_secret")):
            return "请先配置 QQ Bot AppID 和 AppSecret"
        if name == "qq" and not values.get("target_id"):
            return "请先配置 Target ID"
        if name == "telegram":
            return "请先配置 Telegram Bot Token 和 Chat ID"
        if name == "feishu":
            return "请先配置飞书 App ID / App Secret / Receive ID"
        if name == "dingtalk":
            return "请先配置钉钉 Client ID / Client Secret / User ID"
        return None

    def set_channel(platform: str, name: str, enabled: bool):
        cfg = load_config()
        if enabled:
            error = validate_channel_credentials(cfg, name)
            if error:
                return jsonify({"ok": False, "error": error}), 400
        cfg["integrations"][platform]["channels"][name] = enabled
        save_config(cfg)
        status = "启用" if enabled else "禁用"
        return jsonify({"ok": True, "message": f"{name} 通知已{status}"})

    def run_platform_test(platform: str):
        cfg = load_config()
        event = NotificationEvent(platform, "Test", f"{platform} 测试", "这是一条来自 Web UI 的测试通知")
        return notification_service.send_event(event, cfg)

    def integration_payload(cfg: dict):
        result = {}
        for platform in PLATFORMS:
            integration = get_integration(cfg, platform)
            configured = inspect_hooks(platform).configured_events
            result[platform] = {
                "enabled": bool(integration.get("enabled", False)),
                "events": dict(integration.get("events", {})),
                "channels": dict(integration.get("channels", {})),
                "hooks": hook_status(platform, configured),
            }
            if platform == "claude_code":
                result[platform]["interaction"] = dict(integration.get("interaction", {}))
        return result

    @app.route("/api/integrations", methods=["GET"])
    def integrations():
        return jsonify({"integrations": integration_payload(load_config())})

    @app.route("/api/integrations/<platform>", methods=["PUT"])
    def update_integration(platform: str):
        platform = require_platform(platform)
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"ok": False, "error": "请求体必须是 JSON 对象"}), 400
        # Parse before mutating config so malformed hook files cannot leave a
        # partially applied integration update.
        inspect_hooks(platform)
        allowed = {"enabled", "events"} | ({"interaction"} if platform == "claude_code" else set())
        if set(data) - allowed:
            return jsonify({"ok": False, "error": "不支持的集成字段"}), 400
        cfg = load_config()
        integration = cfg["integrations"][platform]
        if "events" in data:
            events = data["events"]
            if not isinstance(events, dict):
                return jsonify({"ok": False, "error": "events 必须是对象"}), 400
            allowed_events = set(CLAUDE_EVENTS if platform == "claude_code" else CODEX_EVENTS)
            if set(events) - allowed_events:
                return jsonify({"ok": False, "error": "不支持的事件名称"}), 400
            if any(not isinstance(value, bool) for value in events.values()):
                return jsonify({"ok": False, "error": "事件值必须是布尔值"}), 400
            integration["events"].update(events)
        if "interaction" in data:
            if not isinstance(data["interaction"], dict):
                return jsonify({"ok": False, "error": "interaction 必须是对象"}), 400
            allowed_interaction = {"enabled", "timeout_seconds", "show_in_terminal"}
            if set(data["interaction"]) - allowed_interaction:
                return jsonify({"ok": False, "error": "不支持的 interaction 字段"}), 400
            for key in ("enabled", "show_in_terminal"):
                if key in data["interaction"] and not isinstance(data["interaction"][key], bool):
                    return jsonify({"ok": False, "error": f"{key} 必须是布尔值"}), 400
            if "timeout_seconds" in data["interaction"] and (
                not isinstance(data["interaction"]["timeout_seconds"], int)
                or data["interaction"]["timeout_seconds"] < 0
            ):
                return jsonify({"ok": False, "error": "timeout_seconds 必须是非负整数"}), 400
            integration["interaction"].update(data["interaction"])
        if "enabled" in data:
            if not isinstance(data["enabled"], bool):
                return jsonify({"ok": False, "error": "enabled 必须是布尔值"}), 400
            integration["enabled"] = data["enabled"]
        hook_snapshot = hook_manager.snapshot_hooks(platform)
        configured_events = tuple(name for name, enabled in integration.get("events", {}).items() if enabled)
        try:
            if integration.get("enabled"):
                hook_result = sync_hooks(platform, configured_events)
            else:
                hook_result = remove_hooks(platform)
            save_config(cfg)
        except Exception:
            try:
                hook_manager.restore_hooks(hook_snapshot)
            except Exception:
                pass
            raise
        return jsonify({"ok": True, "integration": integration, "hooks": hook_status(platform, hook_result.configured_events)})

    @app.route("/api/integrations/<platform>/channels/<name>/toggle", methods=["POST"])
    def integration_channel_toggle(platform: str, name: str):
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get("enabled"), bool):
            return jsonify({"ok": False, "error": "enabled 必须是布尔值"}), 400
        return set_channel(require_platform(platform), require_channel(name), body["enabled"])

    @app.route("/api/integrations/<platform>/hooks/sync", methods=["POST"])
    def integration_hooks_sync(platform: str):
        platform = require_platform(platform)
        cfg = load_config()
        integration = get_integration(cfg, platform)
        configured = tuple(name for name, enabled in integration.get("events", {}).items() if enabled)
        status = sync_hooks(platform, configured) if integration.get("enabled") else remove_hooks(platform)
        return jsonify({"ok": True, "hooks": hook_status(platform, status.configured_events)})

    @app.route("/api/integrations/<platform>/hooks/uninstall", methods=["POST"])
    def integration_hooks_uninstall(platform: str):
        platform = require_platform(platform)
        status = remove_hooks(platform)
        return jsonify({"ok": True, "hooks": hook_status(platform, status.configured_events)})

    @app.route("/api/integrations/<platform>/test", methods=["POST"])
    def integration_test(platform: str):
        platform = require_platform(platform)
        results = run_platform_test(platform)
        return jsonify({"ok": True, "results": [{"channel": r.channel, "success": r.success, "error": r.error} for r in results]})

    # --- 静态文件 ---
    @app.route("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.route("/assets/<path:filename>")
    def serve_assets(filename):
        return send_from_directory(str(RESOURCE_DIR / "assets"), filename)

    # --- SSE 持久连接（标签页关闭检测） ---
    @app.route("/api/stream")
    def stream():
        conn_id = str(uuid.uuid4())
        with _sse_lock:
            _sse_connections.add(conn_id)

        def generate():
            try:
                while True:
                    yield f"data: {json.dumps({'ts': time.time()})}\n\n"
                    time.sleep(3)
            except GeneratorExit:
                pass
            finally:
                with _sse_lock:
                    _sse_connections.discard(conn_id)
                if len(_sse_connections) == 0:
                    _sse_shutdown_event.set()

        return Response(generate(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # --- 配置 API ---
    @app.route("/api/config", methods=["GET"])
    def get_config():
        cfg = load_config()
        safe = json.loads(json.dumps(cfg))
        for container_name in (None, "channels"):
            container = safe if container_name is None else safe.get(container_name, {})
            if not isinstance(container, dict):
                continue
            for channel, secret_fields in CHANNEL_SECRET_FIELDS.items():
                values = container.get(channel)
                if not isinstance(values, dict):
                    continue
                values["configured_secrets"] = {
                    key: bool(values.get(key)) for key in secret_fields
                }
                for key in secret_fields:
                    if key in values:
                        values[key] = ""
        return jsonify(safe)

    @app.route("/api/config", methods=["PUT"])
    def update_config():
        data = request.get_json(force=True)
        cfg = load_config()
        # 敏感字段：空值不覆盖已有值
        SENSITIVE_KEYS = {key for fields in CHANNEL_SECRET_FIELDS.values() for key in fields}
        ALLOWED_CHANNEL_KEYS = {"windows_toast", "weixin", "qq", "telegram", "feishu", "dingtalk"}
        for channel_name, channel_conf in data.items():
            if channel_name not in ALLOWED_CHANNEL_KEYS:
                continue
            if channel_name in cfg and isinstance(cfg[channel_name], dict):
                for k, v in channel_conf.items():
                    if k == "configured_secrets":
                        continue
                    if k in SENSITIVE_KEYS and (v is None or v == "" or v == "***"):
                        continue  # 跳过空值，保留已有配置
                    cfg[channel_name][k] = v
                    canonical = cfg.get("channels", {}).get(channel_name)
                    if isinstance(canonical, dict):
                        canonical[k] = v
            else:
                cfg[channel_name] = channel_conf
        save_config(cfg)
        return jsonify({"ok": True, "message": "配置已保存"})

    # --- 通知渠道开关 ---
    @app.route("/api/channel/<name>/toggle", methods=["POST"])
    def toggle_channel(name: str):
        if name not in CHANNEL_NAMES:
            return jsonify({"ok": False, "error": f"未知渠道: {name}"}), 400
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get("enabled"), bool):
            return jsonify({"ok": False, "error": "enabled 必须是布尔值"}), 400
        return set_channel("claude_code", name, body["enabled"])

    # --- 测试通知 ---
    @app.route("/api/test", methods=["POST"])
    def test_notification():
        results = run_platform_test("claude_code")
        return jsonify({"ok": True, "results": [{"channel": r.channel, "success": r.success} for r in results]})

    # --- 微信登录（直接 ilink API） ---
    @app.route("/api/weixin/qr", methods=["POST"])
    def weixin_qr_login():
        from channels.weixin import WeixinChannel
        result = WeixinChannel.start_qr_login()
        status = 200 if result.get("ok") else 400
        return jsonify(result), status

    @app.route("/api/weixin/qr/status", methods=["GET"])
    def weixin_qr_status():
        from channels.weixin import WeixinChannel
        status = WeixinChannel.get_qr_status()

        # 登录成功后自动更新 config.json
        if status.get("status") == "confirmed" and status.get("bot_token"):
            cfg = load_config()
            cfg["channels"]["weixin"]["bot_token"] = status["bot_token"]
            cfg["channels"]["weixin"]["baseurl"] = status.get("baseurl", "https://ilinkai.weixin.qq.com")
            cfg["channels"]["weixin"]["ilink_bot_id"] = status.get("ilink_bot_id", "")
            cfg["channels"]["weixin"]["ilink_user_id"] = status.get("ilink_user_id", "")
            cfg["channels"]["weixin"].setdefault("to_user_id", "")
            cfg["channels"]["weixin"]["session_expired"] = False
            save_config(cfg)

        return jsonify(status)

    @app.route("/api/weixin/status", methods=["GET"])
    def weixin_status():
        from channels.weixin import WeixinChannel
        cfg = load_config()
        return jsonify(WeixinChannel.get_login_status(cfg))

    @app.route("/api/weixin/logout", methods=["POST"])
    def weixin_logout():
        from channels.weixin import WeixinChannel
        WeixinChannel.clear_login()
        cfg = load_config()
        cfg["channels"]["weixin"]["bot_token"] = ""
        cfg["channels"]["weixin"]["baseurl"] = "https://ilinkai.weixin.qq.com"
        cfg["channels"]["weixin"]["ilink_bot_id"] = ""
        cfg["channels"]["weixin"]["ilink_user_id"] = ""
        cfg["channels"]["weixin"]["to_user_id"] = ""
        cfg["channels"]["weixin"]["enabled"] = False
        save_config(cfg)
        return jsonify({"ok": True, "message": "微信登录信息已清除"})

    # --- QQ 登录 ---
    @app.route("/api/qq/validate", methods=["POST"])
    def qq_validate():
        from channels.qq import QQBotChannel
        data = request.get_json(force=True)
        app_id = data.get("app_id", "").strip()
        app_secret = data.get("app_secret", "").strip()
        target_id = data.get("target_id", "").strip()

        if not app_id or not app_secret:
            return jsonify({"ok": False, "error": "AppID 和 AppSecret 不能为空"}), 400

        result = QQBotChannel.validate_credentials(app_id, app_secret)
        if result.get("ok"):
            cfg = load_config()
            cfg["channels"]["qq"]["app_id"] = app_id
            cfg["channels"]["qq"]["app_secret"] = app_secret
            if target_id:
                cfg["channels"]["qq"]["target_id"] = target_id
            save_config(cfg)
        return jsonify(result)

    @app.route("/api/qq/status", methods=["GET"])
    def qq_status():
        from channels.qq import QQBotChannel
        cfg = load_config()
        return jsonify(QQBotChannel.get_login_status(cfg))

    @app.route("/api/qq/save_target", methods=["POST"])
    def qq_save_target():
        data = request.get_json(force=True)
        target_id = data.get("target_id", "").strip()
        if not target_id:
            return jsonify({"ok": False, "error": "Target ID 不能为空"}), 400
        cfg = load_config()
        cfg["channels"]["qq"]["target_id"] = target_id
        save_config(cfg)
        return jsonify({"ok": True, "message": "Target ID 已保存"})

    @app.route("/api/qq/logout", methods=["POST"])
    def qq_logout():
        cfg = load_config()
        cfg["channels"]["qq"]["app_id"] = ""
        cfg["channels"]["qq"]["app_secret"] = ""
        cfg["channels"]["qq"]["target_id"] = ""
        cfg["channels"]["qq"]["enabled"] = False
        save_config(cfg)
        return jsonify({"ok": True, "message": "QQ Bot 信息已清除"})

    @app.route("/api/qq/capture_openid", methods=["POST"])
    def qq_capture_openid():
        from listener import start_qq_openid_capture
        cfg = load_config()
        app_id = cfg.get("qq", {}).get("app_id", "")
        app_secret = cfg.get("qq", {}).get("app_secret", "")
        if not app_id or not app_secret:
            return jsonify({"ok": False, "error": "请先配置并验证 AppID 和 AppSecret"}), 400
        start_qq_openid_capture(app_id, app_secret)
        return jsonify({"ok": True, "message": "正在监听，发送消息给 QQ Bot 即可自动捕获 OpenID"})

    @app.route("/api/qq/capture_status", methods=["GET"])
    def qq_capture_status():
        from listener import get_qq_capture_status
        return jsonify(get_qq_capture_status())

    # --- Telegram 配置 ---
    @app.route("/api/telegram/validate", methods=["POST"])
    def telegram_validate():
        from channels.telegram import TelegramChannel
        data = request.get_json(force=True)
        bot_token = data.get("bot_token", "").strip()
        if not bot_token:
            return jsonify({"ok": False, "error": "Bot Token 不能为空"}), 400

        result = TelegramChannel.validate_credentials(bot_token)
        if result.get("ok"):
            cfg = load_config()
            cfg["channels"]["telegram"]["bot_token"] = bot_token
            save_config(cfg)
        return jsonify(result)

    @app.route("/api/telegram/status", methods=["GET"])
    def telegram_status():
        from channels.telegram import TelegramChannel
        cfg = load_config()
        return jsonify(TelegramChannel.get_login_status(cfg))

    @app.route("/api/telegram/logout", methods=["POST"])
    def telegram_logout():
        cfg = load_config()
        cfg["channels"]["telegram"]["bot_token"] = ""
        cfg["channels"]["telegram"]["chat_id"] = ""
        cfg["channels"]["telegram"]["enabled"] = False
        save_config(cfg)
        return jsonify({"ok": True, "message": "Telegram 信息已清除"})

    @app.route("/api/telegram/capture_chatid", methods=["POST"])
    def telegram_capture_chatid():
        from listener import start_tg_chatid_capture
        cfg = load_config()
        bot_token = cfg.get("telegram", {}).get("bot_token", "")
        if not bot_token:
            return jsonify({"ok": False, "error": "请先配置 Bot Token"}), 400
        start_tg_chatid_capture(bot_token)
        return jsonify({"ok": True, "message": "正在监听，发送消息给 Telegram Bot 即可自动捕获 Chat ID"})

    @app.route("/api/telegram/capture_status", methods=["GET"])
    def telegram_capture_status():
        from listener import get_tg_capture_status
        return jsonify(get_tg_capture_status())

    # --- 飞书配置 ---
    @app.route("/api/feishu/validate", methods=["POST"])
    def feishu_validate():
        from channels.feishu import FeishuChannel
        data = request.get_json(force=True)
        app_id = data.get("app_id", "").strip()
        app_secret = data.get("app_secret", "").strip()
        if not app_id or not app_secret:
            return jsonify({"ok": False, "error": "App ID 和 App Secret 不能为空"}), 400

        result = FeishuChannel.validate_credentials(app_id, app_secret)
        if result.get("ok"):
            cfg = load_config()
            cfg["channels"]["feishu"]["app_id"] = app_id
            cfg["channels"]["feishu"]["app_secret"] = app_secret
            save_config(cfg)
        return jsonify(result)

    @app.route("/api/feishu/status", methods=["GET"])
    def feishu_status():
        from channels.feishu import FeishuChannel
        cfg = load_config()
        return jsonify(FeishuChannel.get_login_status(cfg))

    @app.route("/api/feishu/logout", methods=["POST"])
    def feishu_logout():
        cfg = load_config()
        cfg["channels"]["feishu"]["app_id"] = ""
        cfg["channels"]["feishu"]["app_secret"] = ""
        cfg["channels"]["feishu"]["receive_id"] = ""
        cfg["channels"]["feishu"]["enabled"] = False
        save_config(cfg)
        return jsonify({"ok": True, "message": "飞书信息已清除"})

    @app.route("/api/feishu/capture_openid", methods=["POST"])
    def feishu_capture_openid():
        from listener import start_fs_openid_capture
        cfg = load_config()
        app_id = cfg.get("feishu", {}).get("app_id", "")
        app_secret = cfg.get("feishu", {}).get("app_secret", "")
        if not app_id or not app_secret:
            return jsonify({"ok": False, "error": "请先配置 App ID 和 App Secret"}), 400
        start_fs_openid_capture(app_id, app_secret)
        return jsonify({"ok": True, "message": "正在监听，发送消息给飞书 Bot 即可自动捕获 Open ID"})

    @app.route("/api/feishu/capture_status", methods=["GET"])
    def feishu_capture_status():
        from listener import get_fs_capture_status
        return jsonify(get_fs_capture_status())

    # --- 钉钉配置 ---
    @app.route("/api/dingtalk/validate", methods=["POST"])
    def dingtalk_validate():
        from channels.dingtalk import DingTalkChannel
        data = request.get_json(force=True)
        client_id = data.get("client_id", "").strip()
        client_secret = data.get("client_secret", "").strip()
        if not client_id or not client_secret:
            return jsonify({"ok": False, "error": "Client ID 和 Client Secret 不能为空"}), 400

        result = DingTalkChannel.validate_credentials(client_id, client_secret)
        if result.get("ok"):
            cfg = load_config()
            cfg["channels"]["dingtalk"]["client_id"] = client_id
            cfg["channels"]["dingtalk"]["client_secret"] = client_secret
            save_config(cfg)
        return jsonify(result)

    @app.route("/api/dingtalk/status", methods=["GET"])
    def dingtalk_status():
        from channels.dingtalk import DingTalkChannel
        cfg = load_config()
        return jsonify(DingTalkChannel.get_login_status(cfg))

    @app.route("/api/dingtalk/logout", methods=["POST"])
    def dingtalk_logout():
        cfg = load_config()
        cfg["channels"]["dingtalk"]["client_id"] = ""
        cfg["channels"]["dingtalk"]["client_secret"] = ""
        cfg["channels"]["dingtalk"]["user_id"] = ""
        cfg["channels"]["dingtalk"]["enabled"] = False
        save_config(cfg)
        return jsonify({"ok": True, "message": "钉钉信息已清除"})

    @app.route("/api/dingtalk/capture_userid", methods=["POST"])
    def dingtalk_capture_userid():
        from listener import start_dt_userid_capture
        cfg = load_config()
        client_id = cfg.get("dingtalk", {}).get("client_id", "")
        client_secret = cfg.get("dingtalk", {}).get("client_secret", "")
        if not client_id or not client_secret:
            return jsonify({"ok": False, "error": "请先配置 Client ID 和 Client Secret"}), 400
        start_dt_userid_capture(client_id, client_secret)
        return jsonify({"ok": True, "message": "正在监听，发送消息给钉钉 Bot 即可自动捕获 User ID"})

    @app.route("/api/dingtalk/capture_status", methods=["GET"])
    def dingtalk_capture_status():
        from listener import get_dt_capture_status
        return jsonify(get_dt_capture_status())

    # --- Hooks 管理 ---
    @app.route("/api/hooks", methods=["GET"])
    def get_hooks():
        status = inspect_hooks("claude_code")
        events = {event: event in status.configured_events for event in CLAUDE_EVENTS}
        return jsonify({"installed": bool(status.configured_events), "events": events})

    @app.route("/api/hooks/install", methods=["POST"])
    def install_hooks():
        cfg = load_config()
        integration = get_integration(cfg, "claude_code")
        enabled_events = tuple(name for name, enabled in integration.get("events", {}).items() if enabled)
        status = sync_hooks("claude_code", enabled_events) if integration.get("enabled") else remove_hooks("claude_code")
        return jsonify({"ok": True, "message": "Hooks 已安装"})

    @app.route("/api/hooks/uninstall", methods=["POST"])
    def uninstall_hooks():
        remove_hooks("claude_code")
        return jsonify({"ok": True, "message": "Hooks 已卸载"})

    # --- 权限模式管理 ---
    @app.route("/api/permission-mode", methods=["GET"])
    def get_permission_mode():
        settings = {}
        try:
            if CLAUDECODE_SETTINGS.exists():
                with open(CLAUDECODE_SETTINGS, "r", encoding="utf-8") as f:
                    settings = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigFileError("Claude settings.json 无法读取") from exc
        if not isinstance(settings, dict) or ("permissions" in settings and not isinstance(settings["permissions"], dict)):
            raise ConfigFileError("Claude settings.json 结构无效")
        mode = settings.get("permissions", {}).get("defaultMode", "default")
        return jsonify({"mode": mode})

    @app.route("/api/permission-mode", methods=["PUT"])
    def set_permission_mode():
        data = request.get_json(force=True)
        mode = data.get("mode", "default")
        if mode not in ("default", "acceptEdits", "bypassPermissions"):
            return jsonify({"ok": False, "error": f"无效模式: {mode}"}), 400

        from config_store import atomic_write_json
        if CLAUDECODE_SETTINGS.exists():
            try:
                with open(CLAUDECODE_SETTINGS, "r", encoding="utf-8") as f:
                    settings = json.load(f)
            except (OSError, json.JSONDecodeError) as exc:
                raise ConfigFileError("Claude settings.json 无法读取") from exc
            if not isinstance(settings, dict) or ("permissions" in settings and not isinstance(settings["permissions"], dict)):
                raise ConfigFileError("Claude settings.json 结构无效")
        else:
            settings = {}

        permissions = settings.setdefault("permissions", {})
        if mode == "default":
            permissions.pop("defaultMode", None)
        else:
            permissions["defaultMode"] = mode

        try:
            atomic_write_json(CLAUDECODE_SETTINGS, settings)
            return jsonify({"ok": True, "message": f"权限模式已切换为 {mode}"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    # --- 交互功能配置 ---
    @app.route("/api/interaction", methods=["GET", "POST"])
    def api_interaction():
        """交互功能配置 API"""
        if request.method == "GET":
            cfg = load_config()
            interaction = cfg["integrations"]["claude_code"].get("interaction", {
                "enabled": True,
                "timeout_seconds": 0,
                "show_in_terminal": True,
            })
            return jsonify(interaction)

        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict) or set(data) - {"enabled", "timeout_seconds", "show_in_terminal"}:
            return jsonify({"ok": False, "error": "交互配置字段无效"}), 400
        cfg = load_config()
        interaction = cfg["integrations"]["claude_code"].get("interaction", {})
        if "enabled" in data:
            if not isinstance(data["enabled"], bool):
                return jsonify({"ok": False, "error": "enabled 必须是布尔值"}), 400
            interaction["enabled"] = data["enabled"]
        if "timeout_seconds" in data:
            if not isinstance(data["timeout_seconds"], int) or data["timeout_seconds"] < 0:
                return jsonify({"ok": False, "error": "timeout_seconds 必须是非负整数"}), 400
            interaction["timeout_seconds"] = data["timeout_seconds"]
        if "show_in_terminal" in data:
            if not isinstance(data["show_in_terminal"], bool):
                return jsonify({"ok": False, "error": "show_in_terminal 必须是布尔值"}), 400
            interaction["show_in_terminal"] = data["show_in_terminal"]
        cfg["integrations"]["claude_code"]["interaction"] = interaction
        save_config(cfg)
        return jsonify({"ok": True, "interaction": interaction})

    # --- 系统状态 ---
    @app.route("/api/status", methods=["GET"])
    def system_status():
        cfg = load_config()

        return jsonify({
            "config_exists": CONFIG_FILE.exists(),
            "hooks_installed": _check_hooks_installed(),
        })

    # --- 日志 ---
    @app.route("/api/logs", methods=["GET"])
    def get_logs():
        lines = int(request.args.get("lines", 50))
        if not LOG_FILE.exists():
            return jsonify({"lines": []})
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                all_lines = f.readlines()
            return jsonify({"lines": [l.rstrip() for l in all_lines[-lines:]]})
        except Exception:
            return jsonify({"lines": []})

    @app.route("/api/logs/clear", methods=["POST"])
    def clear_logs():
        try:
            if LOG_FILE.exists():
                LOG_FILE.write_text("", encoding="utf-8")
            return jsonify({"ok": True, "message": "日志已清除"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    # SSE shutdown watcher: waits for _sse_shutdown_event, then exits after delay
    def _watch_sse_shutdown():
        while True:
            _sse_shutdown_event.wait()
            time.sleep(_SSE_SHUTDOWN_DELAY)
            with _sse_lock:
                if len(_sse_connections) > 0:
                    _sse_shutdown_event.clear()
                    continue
            print(f"\n[INFO] 所有浏览器标签页已关闭，自动退出。")
            import os
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(0)

    threading.Thread(target=_watch_sse_shutdown, daemon=True).start()

    return app


def _extract_commands(entry: dict) -> list:
    if "hooks" in entry and isinstance(entry["hooks"], list):
        return [h.get("command", "") for h in entry["hooks"] if h.get("type") == "command"]
    if "command" in entry:
        return [entry["command"]]
    return []


def _check_hooks_installed() -> bool:
    if not CLAUDECODE_SETTINGS.exists():
        return False
    try:
        with open(CLAUDECODE_SETTINGS, "r", encoding="utf-8") as f:
            settings = json.load(f)
        hooks = settings.get("hooks", {})
        from config_store import CLAUDE_EVENTS as NOTIFY_HOOK_EVENTS
        for event in NOTIFY_HOOK_EVENTS:
            for entry in hooks.get(event, []):
                cmds = _extract_commands(entry)
                if any(("notify" in c.lower() or "claudebeep" in c.lower()) for c in cmds):
                    return True
    except Exception:
        pass
    return False


if __name__ == "__main__":
    import webbrowser
    app = create_app()
    webbrowser.open("http://localhost:5100")
    app.run(host="127.0.0.1", port=5100, debug=False)
