# -*- coding: utf-8 -*-
"""hook_flow 解析与过滤逻辑单元测试。

覆盖使用路径上的核心决策：
- parse_hook_stdin 的 JSON 解析 / 事件类型判定 / 静默跳过
- 权限模式（bypassPermissions / acceptEdits / auto_approved）过滤
- 上下文文本提取（Bash / Edit / cwd 前缀）
- _extract_options 的选项类型判定（AskUserQuestion / PermissionRequest）
"""

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hook_flow import (
    parse_hook_stdin,
    _extract_options,
    _extract_context_text,
    _is_auto_approved,
)


def _collector():
    """返回 (logs, log_fn)，log_fn 供 parse_hook_stdin 使用。"""
    logs = []

    def log_fn(msg):
        logs.append(str(msg))

    return logs, log_fn


class TestParseHookStdin(unittest.TestCase):
    def test_empty_input(self):
        _, log_fn = _collector()
        ctx, event, htype, text, skip = parse_hook_stdin("", log_fn)
        self.assertEqual(ctx, {})
        self.assertEqual(event, "")
        self.assertEqual(htype, "stop")
        self.assertEqual(text, "")
        self.assertEqual(skip, "")

    def test_stop_event_with_cwd(self):
        _, log_fn = _collector()
        raw = json.dumps({
            "hook_event_name": "Stop",
            "cwd": "C:\\work\\proj",
            "stop_reason": "finished",
        })
        ctx, event, htype, text, skip = parse_hook_stdin(raw, log_fn)
        self.assertEqual(event, "Stop")
        self.assertEqual(htype, "stop")
        self.assertEqual(skip, "")
        self.assertIn("C:\\work\\proj", text)
        self.assertIn("finished", text)

    def test_elicitation_is_ask(self):
        _, log_fn = _collector()
        raw = json.dumps({"hook_event_name": "Elicitation", "message": "请选择技术栈"})
        _, event, htype, text, skip = parse_hook_stdin(raw, log_fn)
        self.assertEqual(event, "Elicitation")
        self.assertEqual(htype, "ask")
        self.assertIn("请选择技术栈", text)

    def test_permission_request_is_ask(self):
        _, log_fn = _collector()
        raw = json.dumps({"hook_event_name": "PermissionRequest", "tool_name": "Bash"})
        _, event, htype, _, skip = parse_hook_stdin(raw, log_fn)
        self.assertEqual(event, "PermissionRequest")
        self.assertEqual(htype, "ask")
        self.assertEqual(skip, "")

    def test_auto_approved_skipped(self):
        _, log_fn = _collector()
        raw = json.dumps({
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "auto_approved": True,
        })
        _, event, htype, text, skip = parse_hook_stdin(raw, log_fn)
        self.assertNotEqual(skip, "")
        self.assertEqual(event, "")  # 跳过时不解析事件

    def test_bypass_permissions_stop_still_notifies(self):
        _, log_fn = _collector()
        raw = json.dumps({
            "hook_event_name": "Stop",
            "permission_mode": "bypassPermissions",
        })
        _, _, _, _, skip = parse_hook_stdin(raw, log_fn)
        self.assertEqual(skip, "")  # Stop 在 bypass 模式下仍通知

    def test_accept_edits_skips_edit(self):
        _, log_fn = _collector()
        raw = json.dumps({
            "hook_event_name": "PreToolUse",
            "permission_mode": "acceptEdits",
            "tool_name": "Edit",
        })
        _, _, _, _, skip = parse_hook_stdin(raw, log_fn)
        self.assertIn("acceptEdits", skip)

    def test_pretooluse_always_skipped(self):
        """非 PermissionRequest 的 PreToolUse 一律不通知（含 acceptEdits + Bash）。"""
        _, log_fn = _collector()
        raw = json.dumps({
            "hook_event_name": "PreToolUse",
            "permission_mode": "acceptEdits",
            "tool_name": "Bash",
        })
        _, _, _, _, skip = parse_hook_stdin(raw, log_fn)
        self.assertIn("仅 PermissionRequest", skip)

    def test_invalid_json_does_not_raise(self):
        _, log_fn = _collector()
        ctx, event, htype, text, skip = parse_hook_stdin("not-json{{{", log_fn)
        self.assertEqual(ctx, {})
        self.assertEqual(skip, "")

    def test_non_utf8_input_does_not_raise(self):
        _, log_fn = _collector()
        bad = "{\"hook_event_name\": \"\udcff\"}".encode("utf-8", errors="replace").decode("utf-8", errors="replace")
        parse_hook_stdin(bad, log_fn)  # 不应抛异常


class TestExtractOptions(unittest.TestCase):
    def test_ask_user_question_single(self):
        ctx = {
            "tool_name": "AskUserQuestion",
            "tool_input": {
                "questions": [{
                    "question": "Q",
                    "options": [{"label": "甲"}, {"description": "乙"}],
                    "multiSelect": False,
                }]
            },
        }
        info = _extract_options(ctx)
        self.assertEqual(info["option_type"], "single_select")
        self.assertEqual(info["options"], ["甲", "乙"])
        self.assertTrue(info["as_elicitation"])

    def test_ask_user_question_multi(self):
        ctx = {
            "tool_name": "AskUserQuestion",
            "tool_input": {"questions": [{"options": [{"label": "A"}], "multiSelect": True}]},
        }
        info = _extract_options(ctx)
        self.assertEqual(info["option_type"], "multi_select")
        self.assertTrue(info["multi_select"])

    def test_permission_request_three_options(self):
        ctx = {"hook_event_name": "PermissionRequest", "tool_name": "WebFetch"}
        info = _extract_options(ctx)
        self.assertEqual(info["option_type"], "permission_select")
        self.assertEqual(len(info["options"]), 3)

    def test_unknown_falls_back_to_approve_deny(self):
        info = _extract_options({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        self.assertEqual(info["option_type"], "approve_deny")

    def test_tool_input_not_dict(self):
        info = _extract_options({"tool_name": "AskUserQuestion", "tool_input": None})
        self.assertEqual(info["option_type"], "approve_deny")


class TestExtractContextText(unittest.TestCase):
    def test_bash_with_description(self):
        self.assertEqual(
            _extract_context_text({"tool_name": "Bash", "tool_input": {"description": "构建项目"}}),
            "执行: 构建项目",
        )

    def test_bash_with_command_truncated(self):
        text = _extract_context_text({"tool_name": "Bash", "tool_input": {"command": "x" * 300}})
        self.assertTrue(text.startswith("执行命令: "))
        self.assertLessEqual(len(text), len("执行命令: ") + 120)

    def test_edit_file(self):
        text = _extract_context_text({"tool_name": "Edit", "tool_input": {"file_path": "src/a.py"}})
        self.assertIn("src/a.py", text)

    def test_mcp_tool(self):
        text = _extract_context_text({"tool_name": "mcp__github__search", "tool_input": {}})
        self.assertIn("MCP 工具", text)

    def test_stop_reason(self):
        text = _extract_context_text({"stop_reason": "end_turn"})
        self.assertIn("end_turn", text)


class TestIsAutoApproved(unittest.TestCase):
    def test_bypass_skips_bash(self):
        ok, reason = _is_auto_approved({
            "hook_event_name": "PreToolUse",
            "permission_mode": "bypassPermissions",
            "tool_name": "Bash",
        })
        self.assertTrue(ok)
        self.assertIn("bypassPermissions", reason)

    def test_bypass_keeps_permission_request(self):
        ok, _ = _is_auto_approved({
            "hook_event_name": "PermissionRequest",
            "permission_mode": "bypassPermissions",
            "tool_name": "Bash",
        })
        self.assertFalse(ok)  # 权限请求必须通知

    def test_auto_approved_flag(self):
        # 不传 permission_mode 时会回退读取真实 ~/.claude/settings.json，
        # 测试必须隔离环境依赖（用户机器上可能配置了 bypassPermissions）。
        with mock.patch("hook_flow._load_claude_settings", return_value={}):
            ok, reason = _is_auto_approved({"tool_name": "Bash", "auto_approved": True})
        self.assertTrue(ok)
        self.assertIn("auto_approved", reason)

    def test_stop_never_skipped(self):
        ok, _ = _is_auto_approved({"hook_event_name": "Stop", "permission_mode": "bypassPermissions"})
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
