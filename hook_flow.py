"""Hook 上下文处理（M3）：从 notify.main() 拆出的纯逻辑。

包括：hook stdin JSON 解析、自动批准过滤、选项提取、上下文文本构建、
Claude settings 读取等。notify.main() 只负责流程编排。
"""

import json
import sys
from pathlib import Path

from channels.text import sanitize_data

CLAUDECODE_SETTINGS = Path.home() / ".claude" / "settings.json"


def _read_stdin_utf8() -> str:
    """Read hook JSON as UTF-8 bytes to avoid Windows codepage mojibake."""
    try:
        data = sys.stdin.buffer.read()
        return data.decode("utf-8", errors="replace")
    except Exception:
        return sys.stdin.read()


def _is_interaction_enabled(config: dict) -> bool:
    """检查交互功能是否启用"""
    return config.get("interaction", {}).get("enabled", False) is True


def _extract_options(ctx: dict, log=None) -> dict:
    """从 hook 上下文中提取选项信息。log 为可选日志回调（避免循环依赖）。"""
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
        if log is not None:
            log(f"permission_suggestions: count={len(suggestions)}")
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


def parse_hook_stdin(raw: str, log) -> tuple[dict, str, str, str, str]:
    """
    解析 hook stdin JSON（S1：日志只记录字段名与长度，不记录值）。

    返回 (ctx, hook_event, hook_type, context_text, skip_reason)：
    - skip_reason 非空表示应静默跳过（不发通知）；
    - hook_type 为 "stop" / "ask"。
    """
    ctx = {}
    hook_type = "stop"
    hook_event = ""
    context_text = ""
    try:
        if not raw or not raw.strip():
            return (ctx, hook_event, hook_type, context_text, "")
        ctx = sanitize_data(json.loads(raw))
        log(f"hook ctx keys={list(ctx.keys())} tool={ctx.get('tool_name','?')} "
            f"event={ctx.get('hook_event_name', ctx.get('hookEvent', '?'))} "
            f"auto_approved={ctx.get('auto_approved', 'NOT_PRESENT')}")
        # 只记录字段名与值长度，避免敏感信息落盘
        debug_summary = ", ".join(
            f"{k}={len(str(v))}" for k, v in ctx.items() if k != "transcript_path"
        )
        log(f"hook ctx fields: {debug_summary[:400]}")

        # 核心过滤：已自动放行的权限不通知
        approved, reason = _is_auto_approved(ctx)
        if approved:
            log(f"过滤跳过: {reason}")
            return (ctx, hook_event, hook_type, context_text, reason)

        # 记录未被过滤的命令（仅长度，不记录内容）
        cmd_preview = ""
        if isinstance(ctx.get("tool_input"), dict):
            cmd_preview = ctx["tool_input"].get("command", "")[:40]
        log(f"发送通知: tool={ctx.get('tool_name','?')} cmd_len={len(cmd_preview)}")

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
    return (ctx, hook_event, hook_type, context_text, "")
