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
import argparse
from pathlib import Path

SCRIPT_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from channels.text import sanitize_data, sanitize_text
from config_store import DEFAULT_CONFIG, CONFIG_FILE, migrate_config
from config_store import load_config as _load_config
from config_store import save_config as _save_config
from notification_core import NotificationEvent, collect_channels as _collect_channels
from notification_core import send_event
import hook_manager

# Channel imports are deferred to collect_channels() to speed up hook cold-start.
# Only the text utilities are needed at module level for sanitize_text/sanitize_data.

CLAUDECODE_SETTINGS = Path.home() / ".claude" / "settings.json"
LOG_FILE = SCRIPT_DIR / "notify.log"
PYTHON_EXE = str(sys.executable).replace(chr(92), "/")

# 需要通知的 hook 事件
# 只在 PermissionRequest 触发时通知（用户需要手动批准的场景）
# PreToolUse 不再发送通知，因为自动批准的工具也会触发 PreToolUse，无法区分
NOTIFY_HOOK_EVENTS = [
    "Stop",              # Claude 完成输出
    "Elicitation",       # MCP 服务器请求用户输入
    "PermissionRequest", # 权限弹窗出现时（用户需手动批准的场景）
]


def log(msg: str) -> None:
    """记录日志到文件"""
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = sanitize_text(msg)
    try:
        lines = []
        if LOG_FILE.exists():
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
        lines.append(f"[{timestamp}] {msg}\n")
        if len(lines) > 500:
            lines = lines[-500:]
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except Exception:
        pass


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


def _read_stdin_utf8() -> str:
    """Read hook JSON as UTF-8 bytes to avoid Windows codepage mojibake."""
    try:
        data = sys.stdin.buffer.read()
        return data.decode("utf-8", errors="replace")
    except Exception:
        return sys.stdin.read()


def _is_interaction_enabled(config: dict) -> bool:
    """检查交互功能是否启用（避免在 main 中直接 import interaction）"""
    return config.get("interaction", {}).get("enabled", False) is True


def _extract_options(ctx: dict) -> dict:
    """从 hook 上下文中提取选项信息"""
    tool_name = ctx.get("tool_name", "")
    tool_input = ctx.get("tool_input", {})
    hook_event = ctx.get("hook_event_name", ctx.get("hookEvent", ""))
    if not isinstance(tool_input, dict):
        tool_input = {}

    # AskUserQuestion（可能触发 PermissionRequest 或 Elicitation）→ 提取问题选项
    if tool_name == "AskUserQuestion":
        questions = tool_input.get("questions", [])
        if questions:
            q = questions[0]
            options = []
            for o in q.get("options", []):
                label = o.get("label", "")
                desc = o.get("description", "")
                options.append(label if label else desc)
            is_multi = q.get("multiSelect", False)
            return {
                "options": options,
                "option_type": "multi_select" if is_multi else "single_select",
                "multi_select": is_multi,
                "allow_custom": True,
                "question": q.get("question", ""),
                "as_elicitation": True,  # 标记为 Elicitation 格式输出
            }

    # PermissionRequest（真正的权限请求）→ 标准 3 选项
    if hook_event == "PermissionRequest":
        suggestions = ctx.get("permission_suggestions", [])
        log(f"permission_suggestions: {json.dumps(suggestions, ensure_ascii=False)[:300]}")
        return {
            "options": [
                "Yes",
                "Yes, allow all edits during this session",
                "No",
            ],
            "option_type": "permission_select",
            "multi_select": False,
            "allow_custom": False,
            "question": "",
            "as_elicitation": False,
        }

    return {
        "options": [],
        "option_type": "approve_deny",
        "multi_select": False,
        "allow_custom": False,
        "question": "",
        "as_elicitation": False,
    }


def main():
    log(f"notify.py invoked: args={sys.argv[1:]}")
    parser = argparse.ArgumentParser(
        description="Claude Code 通知管理器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--type", choices=["stop", "ask"], default="stop",
        help="通知类型: stop (执行完毕) / ask (询问问题)"
    )
    parser.add_argument("--message", default="", help="自定义通知消息")
    parser.add_argument("--from-stdin", action="store_true", help="从 stdin 读取 hook 上下文")
    parser.add_argument("--platform", choices=["claude_code", "codex"], default="claude_code")
    parser.add_argument("--claudebeep-hook", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--install", action="store_true", help="安装 Claude Code hooks")
    parser.add_argument("--uninstall", action="store_true", help="卸载 Claude Code hooks")
    parser.add_argument("--test", action="store_true", help="测试所有通知渠道")
    parser.add_argument("--ui", action="store_true", help="启动 Web 管理界面")

    args = parser.parse_args()

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
        from app import create_app
        app = create_app()
        import webbrowser
        webbrowser.open("http://localhost:5100")
        app.run(host="127.0.0.1", port=5100, debug=False)
        return

    # --- 正常通知流程 ---
    context_text = ""
    hook_type = args.type
    ctx = {}
    hook_event = ""

    if args.from_stdin:
        try:
            if not sys.stdin.isatty():
                raw = _read_stdin_utf8()
                if raw.strip():
                    ctx = sanitize_data(json.loads(raw))
                    log(f"hook ctx keys={list(ctx.keys())} tool={ctx.get('tool_name','?')} event={ctx.get('hook_event_name', ctx.get('hookEvent', '?'))} auto_approved={ctx.get('auto_approved', 'NOT_PRESENT')}")
                    # 调试：记录完整上下文（排除大字段）
                    debug_ctx = {k: v for k, v in ctx.items() if k not in ('transcript_path',)}
                    log(f"hook ctx detail: {json.dumps(debug_ctx, ensure_ascii=False, default=str)[:500]}")

                    # 核心过滤：已自动放行的权限不通知
                    approved, reason = _is_auto_approved(ctx)
                    if approved:
                        log(f"过滤跳过: {reason}")
                        return  # 静默退出，不发通知

                    # 记录未被过滤的命令，方便排查
                    cmd_preview = ""
                    if isinstance(ctx.get("tool_input"), dict):
                        cmd_preview = ctx["tool_input"].get("command", "")[:80]
                    log(f"发送通知: tool={ctx.get('tool_name','?')} cmd={cmd_preview!r}")

                    context_text = _extract_context_text(ctx)
                    # 在通知消息前加上工作目录
                    cwd = ctx.get("cwd", "")
                    if cwd:
                        context_text = f"[{cwd}] {context_text}" if context_text else cwd
                    hook_event = ctx.get("hook_event_name", ctx.get("hookEvent", ""))
                    if hook_event in ("Elicitation", "PermissionRequest", "Notification"):
                        hook_type = "ask"
        except (json.JSONDecodeError, IOError):
            pass

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

        options_info = _extract_options(ctx)
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
            log(f"交互响应: channel={response.get('channel','?')} reply={response['reply']!r} → parsed={reply_text!r} → stdout={hook_output!r}")
            print(hook_output, flush=True)

            # 向其他远程渠道主动推送"已处理"通知
            # 注意：回复渠道的确认反馈已由 listener.py 的 _send_confirmation 处理，此处不再重复发送
            resp_channel = response.get("channel", "")
            _REMOTE_CHANNEL_NAMES = {"weixin", "qq", "telegram", "feishu", "dingtalk"}
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


def _load_claude_settings() -> dict:
    """读取 ~/.claude/settings.json，失败返回空 dict"""
    try:
        if CLAUDECODE_SETTINGS.exists():
            with open(CLAUDECODE_SETTINGS, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _find_claude_dir(start: Path) -> Path | None:
    """从 start 向上查找包含 .claude/ 的目录（类似 git 查找 .git/）"""
    current = start.resolve()
    for _ in range(20):
        claude_dir = current / ".claude"
        if claude_dir.is_dir():
            return claude_dir
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def _load_project_settings(cwd: str = "") -> dict:
    """读取项目级 .claude/settings.local.json 和 .claude/settings.json
    从 cwd 向上查找 .claude/ 目录（类似 git 查找 .git/）。"""
    if not cwd:
        return {}
    merged = {}
    claude_dir = _find_claude_dir(Path(cwd))
    if not claude_dir:
        return merged
    for name in ("settings.json", "settings.local.json"):
        path = claude_dir / name
        try:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for k, v in data.items():
                    if k == "permissions" and isinstance(v, dict) and k in merged:
                        for pk, pv in v.items():
                            if pk == "allow" and isinstance(pv, list):
                                merged[k].setdefault("allow", []).extend(pv)
                            else:
                                merged[k][pk] = pv
                    else:
                        merged[k] = v
        except Exception:
            pass
    return merged


def _load_permissions_allow(cwd: str = "") -> list:
    """读取 permissions.allow 列表（合并用户级 + 项目级设置）"""
    allow = _load_claude_settings().get("permissions", {}).get("allow", [])
    project_allow = _load_project_settings(cwd).get("permissions", {}).get("allow", [])
    if project_allow:
        allow = list(set(allow + project_allow))
    return allow


def _get_permission_mode() -> str:
    """
    从 ~/.claude/settings.json 读取 permissions.defaultMode（兜底方案）。
    优先应从 hook ctx.get("permission_mode") 读取，此函数仅作为 fallback。
    """
    settings = _load_claude_settings()
    return settings.get("permissions", {}).get("defaultMode", "")


def _is_auto_approved(ctx: dict) -> tuple[bool, str]:
    """
    判断此次工具调用是否跳过通知。
    返回 (是否跳过, 原因说明)

    只有 PermissionRequest 事件会触发通知（用户需要手动批准时）。
    PreToolUse 不再发送通知，因为自动批准的工具也会触发 PreToolUse，无法区分。
    """
    tool_name = ctx.get("tool_name", "")
    hook_event = ctx.get("hook_event_name", ctx.get("hookEvent", ""))

    # ── 层0：权限模式 ────────────────────────────────────────────
    permission_mode = ctx.get("permission_mode", "") or _get_permission_mode()

    if permission_mode == "bypassPermissions":
        # bypassPermissions 下 PermissionRequest/Stop/Elicitation 仍需通知用户
        if hook_event in ("PermissionRequest", "Stop", "Elicitation"):
            return False, ""
        return True, f"bypassPermissions 模式，跳过 {tool_name}"

    if permission_mode == "acceptEdits":
        if tool_name in ("Edit", "Write", "Read", "MultiEdit"):
            return True, f"acceptEdits 模式，跳过 {tool_name}"

    # ── 层1：auto_approved 标记 ───────────────────────────────────
    if ctx.get("auto_approved") is True:
        return True, "auto_approved=true"

    # ── 层2：Stop / Elicitation 直接放行 ─────────────────────────
    if hook_event in ("Stop", "Elicitation") or not tool_name:
        return False, ""

    # ── 层3：PermissionRequest 事件 ──────────────────────────────
    # PermissionRequest 只在需要用户批准时触发，自动批准的工具不触发
    if hook_event == "PermissionRequest":
        return False, ""

    # 其他事件（如 PreToolUse）不再发送通知
    return True, f"跳过 {hook_event} 事件（仅 PermissionRequest 发送通知）"


def _extract_context_text(ctx: dict) -> str:
    """从 hook 上下文中提取有意义的文本描述"""
    # 优先使用 message / text / content 字段
    msg = ctx.get("message", "") or ctx.get("text", "") or ctx.get("content", "")
    if msg:
        return msg

    # PermissionRequest / PreToolUse 场景：从 tool_name + tool_input 构建描述
    tool_name = ctx.get("tool_name", "")
    tool_input = ctx.get("tool_input", {})
    if not isinstance(tool_input, dict):
        tool_input = {}

    if tool_name:
        if tool_name == "Bash":
            cmd = tool_input.get("command", "")
            desc = tool_input.get("description", "")
            if desc:
                return f"执行: {desc}"
            if cmd:
                return f"执行命令: {cmd[:120]}"
            return "执行 Bash 命令"
        elif tool_name == "Edit":
            fp = tool_input.get("file_path", "")
            old = tool_input.get("old_string", "")[:60]
            return f"编辑文件: {fp}" + (f"\n{old}..." if old else "")
        elif tool_name == "Write":
            fp = tool_input.get("file_path", "")
            return f"写入文件: {fp}" if fp else "写入文件"
        elif tool_name == "AskUserQuestion":
            questions = tool_input.get("questions", [])
            if questions:
                texts = [q.get("question", "") for q in questions if q.get("question")]
                return "\n".join(texts[:3]) if texts else "Claude 正在询问您的意见"
            return tool_input.get("question", "") or "Claude 正在询问您的意见"
        elif tool_name == "Agent":
            desc = tool_input.get("description", "")
            return f"启动子代理: {desc}" if desc else "启动子代理"
        elif tool_name.startswith("mcp__"):
            return f"MCP 工具: {tool_name}"
        else:
            return f"工具调用: {tool_name}"

    # Stop 事件：尝试提取 stop_reason
    stop_reason = ctx.get("stop_reason", "")
    if stop_reason:
        return f"完成原因: {stop_reason}"

    return ""


if __name__ == "__main__":
    main()
