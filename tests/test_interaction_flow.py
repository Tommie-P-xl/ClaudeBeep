# -*- coding: utf-8 -*-
"""interaction 请求生命周期与响应解析单元测试。

覆盖使用路径：
- pending/response 文件生命周期（创建、原子响应、先到先生效）
- 标签分配与重置（并发场景的锁语义）
- 残留请求清理（PID 失效 / 超龄）
- 回复解析与 hook 输出格式化（PermissionRequest / Elicitation）

所有目录均隔离到临时目录，绝不触碰项目真实 pending/responses 数据。
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import interaction


class InteractionTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp())
        self._old = {
            "pending": interaction.PENDING_DIR,
            "responses": interaction.RESPONSE_DIR,
            "label_seq": interaction._LABEL_SEQ_FILE,
        }
        interaction.PENDING_DIR = self._tmp / "pending"
        interaction.RESPONSE_DIR = self._tmp / "responses"
        interaction._LABEL_SEQ_FILE = interaction.PENDING_DIR / ".label_seq"

    def tearDown(self):
        interaction.PENDING_DIR = self._old["pending"]
        interaction.RESPONSE_DIR = self._old["responses"]
        interaction._LABEL_SEQ_FILE = self._old["label_seq"]

    def _create(self, **overrides):
        kwargs = dict(
            hook_event="Elicitation",
            context_text="ctx",
            tool_name="AskUserQuestion",
            tool_input={"questions": []},
            options=["甲", "乙"],
            option_type="single_select",
            multi_select=False,
            allow_custom=True,
            timeout=0,
        )
        kwargs.update(overrides)
        return interaction.create_request(**kwargs)


class TestRequestLifecycle(InteractionTestCase):
    def test_create_request_writes_file(self):
        pending = self._create()
        self.assertTrue(pending["id"].startswith("req_"))
        self.assertTrue((interaction.PENDING_DIR / f"{pending['id']}.json").exists())
        self.assertEqual(pending["label"], "A")

    def test_label_increments(self):
        a = self._create()
        b = self._create()
        self.assertEqual(a["label"], "A")
        self.assertEqual(b["label"], "B")

    def test_label_resets_when_no_pending(self):
        self._create()
        interaction.cleanup_all()
        c = self._create()
        self.assertEqual(c["label"], "A")

    def test_write_response_first_wins(self):
        """核心契约：硬链接 O_EXCL 语义，后到者不能覆盖先到者。"""
        pending = self._create()
        rid = pending["id"]
        self.assertTrue(interaction.write_response(rid, "甲", "weixin"))
        self.assertFalse(interaction.write_response(rid, "乙", "telegram"))
        response = interaction.read_response(rid)
        self.assertEqual(response["reply"], "甲")
        self.assertEqual(response["channel"], "weixin")

    def test_cleanup_request_removes_both(self):
        pending = self._create()
        rid = pending["id"]
        interaction.write_response(rid, "x", "qq")
        interaction.cleanup_request(rid)
        self.assertFalse((interaction.PENDING_DIR / f"{rid}.json").exists())
        self.assertFalse((interaction.RESPONSE_DIR / f"{rid}.json").exists())

    def test_cleanup_stale_removes_dead_pid(self):
        rid = "req_dead"
        interaction.PENDING_DIR.mkdir(parents=True, exist_ok=True)
        stale = {
            "id": rid, "label": "A", "pid": 99999999, "created_at": time.time(),
            "hook_type": "ask", "option_type": "approve_deny", "options": [],
        }
        (interaction.PENDING_DIR / f"{rid}.json").write_text(
            json.dumps(stale), encoding="utf-8")
        interaction.cleanup_stale()
        self.assertFalse((interaction.PENDING_DIR / f"{rid}.json").exists())

    def test_cleanup_stale_keeps_live_pid(self):
        pending = self._create()
        rid = pending["id"]
        interaction.cleanup_stale()
        self.assertTrue((interaction.PENDING_DIR / f"{rid}.json").exists())


class TestParseReply(InteractionTestCase):
    def test_approve_deny_keywords(self):
        p = {"option_type": "approve_deny", "options": []}
        self.assertEqual(interaction.parse_reply("y", p), "approve")
        self.assertEqual(interaction.parse_reply("否", p), "deny")
        self.assertEqual(interaction.parse_reply("自定义内容", p), "自定义内容")

    def test_permission_select_digits(self):
        p = {"option_type": "permission_select", "options": []}
        self.assertEqual(interaction.parse_reply("1", p), "approve")
        self.assertEqual(interaction.parse_reply("2", p), "approve_all")
        self.assertEqual(interaction.parse_reply("3", p), "deny")

    def test_single_select(self):
        p = {"option_type": "single_select", "options": ["甲", "乙", "丙"], "allow_custom": False}
        self.assertEqual(interaction.parse_reply("2", p), "乙")
        self.assertEqual(interaction.parse_reply("9", p), "9")  # 越界透传

    def test_multi_select(self):
        p = {"option_type": "multi_select", "options": ["甲", "乙", "丙"]}
        self.assertEqual(interaction.parse_reply("1,3", p), "甲,丙")

    def test_multi_question(self):
        p = {
            "option_type": "single_select",
            "options": [],
            "tool_input": {
                "questions": [
                    {"field": "q1", "options": [{"label": "甲"}, {"label": "乙"}]},
                    {"field": "q2", "options": [{"label": "丙"}, {"label": "丁"}]},
                ]
            },
        }
        data = json.loads(interaction.parse_reply("1|2", p))
        self.assertEqual(data, {"q1": "甲", "q2": "丁"})


class TestFormatHookResponse(InteractionTestCase):
    def test_permission_approve(self):
        out = interaction.format_hook_response("approve", "PermissionRequest")
        data = json.loads(out)
        self.assertEqual(data["hookSpecificOutput"]["decision"]["behavior"], "allow")

    def test_permission_approve_all(self):
        out = interaction.format_hook_response("approve_all", "PermissionRequest")
        data = json.loads(out)
        decision = data["hookSpecificOutput"]["decision"]
        self.assertEqual(decision["behavior"], "allow")
        self.assertEqual(decision["updatedPermissions"][0]["mode"], "acceptEdits")

    def test_permission_deny(self):
        out = interaction.format_hook_response("deny", "PermissionRequest")
        data = json.loads(out)
        self.assertEqual(data["hookSpecificOutput"]["decision"]["behavior"], "deny")

    def test_elicitation_echoes_questions(self):
        tool_input = {"questions": [{"field": "q1", "question": "Q?"}]}
        out = interaction.format_hook_response("甲", "Elicitation", question="Q?", tool_input=tool_input)
        data = json.loads(out)
        answers = data["hookSpecificOutput"]["decision"]["updatedInput"]["answers"]
        self.assertEqual(answers["Q?"], "甲")
        self.assertIn("questions", data["hookSpecificOutput"]["decision"]["updatedInput"])

    def test_plain_text_fallback(self):
        out = interaction.format_hook_response("hello", "", tool_input={})
        self.assertEqual(out, "hello")


class TestExtractReplyParts(InteractionTestCase):
    def test_label_with_space(self):
        self.assertEqual(interaction._extract_reply_parts("A 1"), ("A", "1"))

    def test_number_only(self):
        self.assertEqual(interaction._extract_reply_parts("1"), ("", "1"))

    def test_label_concatenated(self):
        self.assertEqual(interaction._extract_reply_parts("a1"), ("A", "1"))

    def test_empty(self):
        self.assertEqual(interaction._extract_reply_parts("  "), ("", ""))


class TestFormatNotificationMessage(InteractionTestCase):
    def test_approve_deny_message(self):
        pending = self._create(option_type="approve_deny", options=[])
        msg = interaction.format_notification_message(pending)
        self.assertIn("#A", msg)
        self.assertIn("1 - 批准", msg)
        self.assertIn("2 - 拒绝", msg)


if __name__ == "__main__":
    unittest.main()
