# -*- coding: utf-8 -*-
"""listeners 消息分发单元测试。

覆盖使用路径：
- 临时模式（单请求上下文）：标签匹配 / 无标签默认 / 不匹配忽略 / 先到先生效
- 常驻模式（全局分发）：遍历 pending 匹配 label / 无匹配
- 回复确认与"已处理"反馈的触发

响应文件写入隔离到临时目录；网络发送全部 mock 为 no-op。
"""

import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import interaction
from listeners import base as listener_base


class ListenerTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp())
        # 目录隔离
        self.enterContext(mock.patch.object(interaction, "PENDING_DIR", self._tmp / "pending"))
        self.enterContext(mock.patch.object(interaction, "RESPONSE_DIR", self._tmp / "responses"))
        self.enterContext(mock.patch.object(listener_base, "RUNTIME_DIR", self._tmp))
        # 日志与网络发送隔离
        self.enterContext(mock.patch("common.log.LOG_FILE", self._tmp / "notify.log"))
        self.enterContext(mock.patch.object(listener_base, "_log", lambda msg: None))
        self.enterContext(mock.patch.object(listener_base, "_send_confirmation"))
        self.enterContext(mock.patch.object(listener_base, "_send_already_handled_feedback"))
        self.enterContext(mock.patch.object(listener_base, "_send_no_pending_feedback"))
        interaction.PENDING_DIR.mkdir(parents=True, exist_ok=True)
        interaction.RESPONSE_DIR.mkdir(parents=True, exist_ok=True)

    def _create_pending_file(self, rid="req1", label="A"):
        pending = {
            "id": rid, "label": label, "pid": os.getpid(),
            "hook_type": "ask", "option_type": "approve_deny", "options": [],
            "created_at": 0,
        }
        (interaction.PENDING_DIR / f"{rid}.json").write_text(
            json.dumps(pending), encoding="utf-8")
        return pending

    def _response(self, rid):
        path = interaction.RESPONSE_DIR / f"{rid}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


class TestProcessMessage(ListenerTestCase):
    """临时模式：单请求上下文。"""

    def test_label_match_writes_response(self):
        stop = threading.Event()
        ok = listener_base._process_message(
            "A 1", "telegram", "req1",
            {"id": "req1", "label": "A"}, stop)
        self.assertTrue(ok)
        self.assertTrue(stop.is_set())
        resp = self._response("req1")
        self.assertEqual(resp["reply"], "1")
        self.assertEqual(resp["channel"], "telegram")

    def test_no_label_defaults_to_current_request(self):
        stop = threading.Event()
        ok = listener_base._process_message(
            "1", "qq", "req1", {"id": "req1", "label": "A"}, stop)
        self.assertTrue(ok)
        self.assertEqual(self._response("req1")["reply"], "1")

    def test_label_mismatch_ignored(self):
        stop = threading.Event()
        ok = listener_base._process_message(
            "B 1", "qq", "req1", {"id": "req1", "label": "A"}, stop)
        self.assertFalse(ok)
        self.assertFalse(stop.is_set())
        self.assertIsNone(self._response("req1"))

    def test_empty_reply_ignored(self):
        stop = threading.Event()
        ok = listener_base._process_message(
            "", "qq", "req1", {"id": "req1", "label": "A"}, stop)
        self.assertFalse(ok)
        self.assertFalse(stop.is_set())

    def test_second_reply_loses_and_feedback_sent(self):
        """先到先生效：第二次回复不覆盖，且触发"已处理"反馈。"""
        stop = threading.Event()
        listener_base._process_message("A 1", "telegram", "req1", {"id": "req1", "label": "A"}, stop)
        ok2 = listener_base._process_message("A 2", "qq", "req1", {"id": "req1", "label": "A"}, stop)
        self.assertFalse(ok2)
        self.assertEqual(self._response("req1")["reply"], "1")
        listener_base._send_already_handled_feedback.assert_called_once()


class TestProcessMessageGlobal(ListenerTestCase):
    """常驻模式：托盘进程持有，遍历所有 pending。"""

    def test_global_match_writes_response(self):
        self._create_pending_file("req1", "A")
        listener_base._process_message_global("A 2", "qq")
        resp = self._response("req1")
        self.assertEqual(resp["reply"], "2")

    def test_global_no_match(self):
        self._create_pending_file("req1", "A")
        listener_base._process_message_global("Z 9", "qq")
        self.assertIsNone(self._response("req1"))

    def test_global_without_label_ignored(self):
        self._create_pending_file("req1", "A")
        listener_base._process_message_global("3", "qq")
        self.assertIsNone(self._response("req1"))

    def test_global_no_pending_sends_feedback(self):
        listener_base._process_message_global("A 1", "telegram")
        listener_base._send_no_pending_feedback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
