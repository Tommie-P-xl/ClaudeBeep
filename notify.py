#!/usr/bin/env python3
"""
Claude Code 通知管理器。
当 Claude Code 完成响应、弹出询问或执行工具时，自动发送通知到 Windows Toast、微信和/或 QQ。
通过 Claude Code hooks 机制自动触发，支持多渠道扩展。

用法:
  python notify.py --type stop [--message "可选消息"]
  python notify.py --type ask  [--message "可选消息"]
  python notify.py --install   安装 Claude Code hooks 配置
  python notify.py --uninstall 卸载 Claude Code hooks 配置
  python notify.py --test      测试所有已启用渠道
  python notify.py --ui        启动 Web 管理界面
"""

import sys
import os
import json
from pathlib import Path

SCRIPT_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from channels.text import sanitize_text
from config_store import DEFAULT_CONFIG, CONFIG_FILE, migrate_config
from config_store import load_config as _load_config
from config_store import save_config as _save_config
from notification_core import NotificationEvent, collect_channels as _collect_channels
from notification_core import send_event
from common.log import log as _log_impl
from notify_cli import build_parser
from hook_flow import (
    parse_hook_stdin,
    _read_stdin_utf8,
    _is_interaction_enabled,
    _extract_options,
    _load_claude_settings,
    _find_claude_dir,
    _load_project_settings,
    _load_permissions_allow,
    _get_permission_mode,
    _is_auto_approved,
    _extract_context_text,
)
import hook_manager

# Channel imports are deferred to collect_channels() to speed up hook cold-start.
# Only the text utilities are needed at module level for sanitize_text/sanitize_data.

CLAUDECODE_SETTINGS = Path.home() / ".claude" / "settings.json"
PYTHON_EXE = str(sys.executable).replace(chr(92), "/")


def log(msg: str) -> None:
    """记录日志到文件（统一走 common.log，追加写 + 模块标识）"""
    _log_impl("notify", sanitize_text(msg))


def load_config() -> dict:
    return _load_config()


def save_config(config: dict) -> None:
    _save_config(config)


def collect_channels(config: dict):
    """收集 Claude Code 通知渠道。"""
    return _collect_channels(config, "claude_code")


def install_hooks() -> bool:
    """Install Claude Code hooks through the ownership-safe manager."""
    config = load_config()

    integration = config.get("integrations", {}).get("claude_code", {})
    events = [name for name, enabled in integration.get("events", {}).items() if enabled]
    if integration.get("enabled"):
        hook_manager.sync_hooks("claude_code", events)
    else:
        hook_manager.uninstall_hooks("claude_code")
    return True


def uninstall_hooks() -> bool:
    hook_manager.uninstall_hooks("claude_code")
    return True


def test_channels(config: dict) -> None:
    """测试所有已启用的渠道"""
    channels = collect_channels(config)
    tested = 0
    for ch in channels:
        if ch.is_enabled():
            print(f"测试渠道: {ch.name} ... ", end="", flush=True)
            ok = ch.send("Claude Code 测试通知", "如果你看到这条消息，说明通知功能配置成功！")
            print("成功" if ok else "失败")
            tested += 1
        else:
            print(f"渠道 {ch.name}: 已禁用，跳过")
    if tested == 0:
        print("没有启用任何通知渠道。")


def main():
    log(f"notify.py invoked: args={sys.argv[1:]}")
    args = build_parser().parse_args()

    if args.install:
        config = load_config()
        integration = config.get("integrations", {}).get(args.platform, {})
        events = [name for name, enabled in integration.get("events", {}).items() if enabled]
        if integration.get("enabled"):
            hook_manager.sync_hooks(args.platform, events)
        else:
            hook_manager.uninstall_hooks(args.platform)
        return
    if args.uninstall:
        hook_manager.uninstall_hooks(args.platform)
        return

    if args.platform == "codex" and (args.claudebeep_hook or args.from_stdin):
        from codex_adapter import run_codex_hook
        return run_codex_hook(_read_stdin_utf8())

    config = load_config()

    if args.test:
        test_channels(config)
        return

    if args.ui:
        import webbrowser
        from common.single_instance import is_ui_running
        # 已有本应用 UI 服务（其他实例/托盘启动的）→ 直接复用，不重复启动
        if is_ui_running():
            webbrowser.open("http://localhost:5100")
            return
        from app import create_app
        app = create_app()
        webbrowser.open("http://localhost:5100")
        try:
            app.run(host="127.0.0.1", port=5100, debug=False)
        except OSError:
            # 端口被占用（启动竞态）：说明已有实例在服务，直接复用
            webbrowser.open("http://localhost:5100")
        return

    # --- 正常通知流程 ---
    context_text = ""
    hook_type = args.type
    ctx = {}
    hook_event = ""

    if args.from_stdin:
        if not sys.stdin.isatty():
            raw = _read_stdin_utf8()
            ctx, hook_event, hook_type, context_text, skip_reason = parse_hook_stdin(raw, log)
            if skip_reason:
                return  # 静默退出，不发通知

    integration = migrate_config(config).get("integrations", {}).get("claude_code", {})
    requested_event = hook_event or ("Stop" if hook_type == "stop" else "PermissionRequest")
    if not integration.get("enabled", False) or not integration.get("events", {}).get(requested_event, False):
        return

    final_message = sanitize_text(args.message or context_text)

    if hook_type == "ask":
        title = "Claude Code - 询问"
        default_msg = "Claude 正在等待您的回复..."
    else:
        title = "Claude Code - 完成"
        default_msg = "Claude 已执行完毕，请查看结果。"

    message = sanitize_text(final_message if final_message else default_msg)

    channels = collect_channels(config)

    # ── 交互模式分支 ──
    if hook_type == "ask" and _is_interaction_enabled(config):
        import interaction

        options_info = _extract_options(ctx, log)
        interaction.cleanup_stale()  # 清理已退出进程的残留请求
        pending = interaction.create_request(
            hook_event=hook_event,
            context_text=context_text,
            tool_name=ctx.get("tool_name", ""),
            tool_input=ctx.get("tool_input", {}),
            options=options_info["options"],
            option_type=options_info["option_type"],
            multi_select=options_info["multi_select"],
            allow_custom=options_info["allow_custom"],
            timeout=config.get("integrations", {}).get("claude_code", {}).get("interaction", {}).get("timeout_seconds", 0),
            question=options_info.get("question", ""),
            as_elicitation=options_info.get("as_elicitation", False),
        )

        # 发送带选项的通知
        interactive_message = sanitize_text(interaction.format_notification_message(pending))
        for ch in channels:
            if ch.is_enabled():
                log(f"[{ch.name}] 发送交互通知: {interactive_message[:80]}")
                ok = ch.send(title, interactive_message)
                log(f"[{ch.name}] 发送结果: {'成功' if ok else '失败'}")

        # 等待响应（终端 + 文件轮询竞争）
        interaction_cfg = config.get("integrations", {}).get("claude_code", {}).get("interaction", {})
        timeout = interaction_cfg.get("timeout_seconds", 0)
        show_terminal = interaction_cfg.get("show_in_terminal", True)
        response = interaction.wait_for_response(
            pending["id"], timeout, show_terminal, config, pending
        )

        # 清理：只删 pending 文件，保留 response 文件供其他渠道检测"已处理"
        try:
            (interaction.PENDING_DIR / f"{pending['id']}.json").unlink(missing_ok=True)
        except Exception:
            pass

        # 输出响应给 Claude Code
        if response:
            reply_text = interaction.parse_reply(response["reply"], pending)
            # AskUserQuestion 触发的是 PermissionRequest 事件，但需要按 Elicitation 格式输出
            output_event = "Elicitation" if pending.get("as_elicitation") else hook_event
            hook_output = interaction.format_hook_response(reply_text, output_event, pending.get("question", ""), pending.get("tool_input", {}))
            log(f"交互响应: channel={response.get('channel','?')} reply_len={len(response['reply'])} parsed_len={len(reply_text)} stdout_len={len(hook_output)}")
            print(hook_output, flush=True)

            # 向其他远程渠道主动推送"已处理"通知
            # 注意：回复渠道的确认反馈已由 listener.py 的 _send_confirmation 处理，此处不再重复发送
            from common.channels_registry import REMOTE_CHANNELS as _REMOTE_CHANNEL_NAMES
            resp_channel = response.get("channel", "")
            label = pending.get("label", "?")
            # resp_channel 为空时说明是终端回复
            handled_by = resp_channel if resp_channel else "终端"
            done_msg = f"#{label} 已由【{handled_by}】处理，无需再次回复"
            for ch in channels:
                if (ch.is_enabled()
                        and ch.name in _REMOTE_CHANNEL_NAMES
                        and ch.name != resp_channel):
                    ok = ch.send("Claude Code - 已处理", done_msg)
                    log(f"[{ch.name}] 已处理通知: {'成功' if ok else '失败'}")
        else:
            log("等待用户响应超时")
            # 超时：清理 pending 和 response 文件
            interaction.cleanup_request(pending["id"])

    else:
        # ── 现有行为（完全不变）──
        event = NotificationEvent(
            platform="claude_code",
            event_name=hook_event,
            title=title,
            message=message,
            cwd=str(ctx.get("cwd", "")),
            session_id=str(ctx.get("session_id", "")),
        )

        def log_delivery(stage, channel, result):
            if stage == "sending":
                log(f"[{channel.name}] 发送通知: {title} | {message[:80]}")
            elif stage == "disabled":
                log(f"[{channel.name}] 已禁用，跳过")
            else:
                log(f"[{result.channel}] 发送结果: {'成功' if result.success else '失败'}")

        send_event(event, config, channels=channels, observer=log_delivery)
