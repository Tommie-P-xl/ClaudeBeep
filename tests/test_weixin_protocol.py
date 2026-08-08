# -*- coding: utf-8 -*-
"""微信 iLink 协议决策与发送降级逻辑单元测试。

覆盖使用路径：
- ret=-2 / errcode=-14 的语义识别（_is_stale_context_error）
- _direct_send 的降级重试（剥离 context_token 重发）
- 会话过期标记、网络错误处理
- 发送队列处理（enqueue → process → done）

所有网络请求 mock，写盘调用 mock，不产生真实流量、不触碰真实配置。
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from channels import weixin
from channels.weixin import (
    _is_stale_context_error,
    _direct_send,
    _enqueue_message,
    _wait_for_send_result,
    _process_send_queue,
)


class _Resp:
    def __init__(self, body, status=200):
        self.status = status
        self._body = body.encode("utf-8") if isinstance(body, str) else body

    def read(self):
        return self._body


WX_CONFIG = {
    "bot_token": "token123",
    "baseurl": "https://ilinkai.weixin.qq.com",
    "to_user_id": "user_1",
    "context_token": "ctx_abc",
}


class TestIsStaleContextError(unittest.TestCase):
    def test_ret_minus2_empty_msg(self):
        self.assertTrue(_is_stale_context_error(-2, 0, ""))

    def test_ret_minus2_unknown_error(self):
        self.assertTrue(_is_stale_context_error(-2, 0, "unknown error"))

    def test_ret_minus2_invalid_token(self):
        self.assertTrue(_is_stale_context_error(-2, 0, "invalid context token"))

    def test_ret_minus2_other_msg_not_stale(self):
        self.assertFalse(_is_stale_context_error(-2, 0, "some real error"))

    def test_zero_not_stale(self):
        self.assertFalse(_is_stale_context_error(0, 0, ""))

    def test_minus14_not_stale(self):
        self.assertFalse(_is_stale_context_error(-14, 0, ""))

    def test_none_ret_falls_back_to_errcode(self):
        self.assertTrue(_is_stale_context_error(None, -2, ""))


class TestDirectSend(unittest.TestCase):
    def setUp(self):
        # 隔离日志写入，避免污染项目目录的 notify.log
        self.enterContext(mock.patch(
            "common.log.LOG_FILE", Path(tempfile.mkdtemp()) / "notify.log"))

    def _patch_urlopen(self, responses):
        return mock.patch.object(
            weixin.urllib.request, "urlopen",
            side_effect=[_Resp(r) for r in responses],
        )

    def test_success_no_retry(self):
        with self._patch_urlopen(['{"ret":0,"errcode":0}']) as urlopen, \
             mock.patch.object(weixin, "_update_config_field") as upd, \
             mock.patch.object(weixin, "_mark_session_timeout") as mark:
            ok = _direct_send(dict(WX_CONFIG), "T", "M")
        self.assertTrue(ok)
        self.assertEqual(urlopen.call_count, 1)
        upd.assert_not_called()
        mark.assert_not_called()

    def test_stale_context_retries_without_token(self):
        """ret=-2 且 errmsg 为空 → 清空 context_token 后无令牌降级重试。"""
        with self._patch_urlopen([
            '{"ret":-2,"errcode":0,"errmsg":""}',
            '{"ret":0,"errcode":0}',
        ]) as urlopen, \
             mock.patch.object(weixin, "_update_config_field") as upd, \
             mock.patch.object(weixin, "_mark_session_timeout") as mark:
            ok = _direct_send(dict(WX_CONFIG), "T", "M")
        self.assertTrue(ok)
        self.assertEqual(urlopen.call_count, 2)
        upd.assert_called_once_with("context_token", "")
        mark.assert_not_called()

    def test_session_expired_marks_timeout(self):
        with self._patch_urlopen(['{"ret":-14,"errcode":0}']) as urlopen, \
             mock.patch.object(weixin, "_update_config_field") as upd, \
             mock.patch.object(weixin, "_mark_session_timeout") as mark:
            ok = _direct_send(dict(WX_CONFIG), "T", "M")
        self.assertFalse(ok)
        self.assertEqual(urlopen.call_count, 1)
        mark.assert_called_once()

    def test_network_error_returns_false(self):
        # 注意：带 context_token 时网络错误也会做一次无 token 降级重试（容错设计）
        with mock.patch.object(
            weixin.urllib.request, "urlopen",
            side_effect=weixin.urllib.error.URLError("boom"),
        ) as urlopen, \
             mock.patch.object(weixin, "_update_config_field") as upd, \
             mock.patch.object(weixin, "_mark_session_timeout") as mark:
            ok = _direct_send(dict(WX_CONFIG), "T", "M")
        self.assertFalse(ok)
        self.assertEqual(urlopen.call_count, 2)
        upd.assert_not_called()

    def test_http_error_returns_false(self):
        with mock.patch.object(
            weixin.urllib.request, "urlopen",
            side_effect=weixin.urllib.error.HTTPError("http://x", 500, "err", None, None),
        ) as urlopen:
            ok = _direct_send(dict(WX_CONFIG), "T", "M")
        self.assertFalse(ok)
        self.assertEqual(urlopen.call_count, 2)  # 同网络错误：带 token 重试一次


class TestSendQueue(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp())
        self._old = weixin.SEND_QUEUE_DIR
        weixin.SEND_QUEUE_DIR = self._tmp
        # 隔离日志写入，避免污染项目目录的 notify.log
        self.enterContext(mock.patch(
            "common.log.LOG_FILE", self._tmp / "notify.log"))

    def tearDown(self):
        weixin.SEND_QUEUE_DIR = self._old

    def test_enqueue_process_roundtrip(self):
        msg_id = _enqueue_message("标题", "内容")
        self.assertTrue((self._tmp / f"{msg_id}.json").exists())

        sent = []

        def do_send(title, message):
            sent.append((title, message))
            return True

        _process_send_queue(do_send)
        data = json.loads((self._tmp / f"{msg_id}.json").read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "done")
        self.assertTrue(data["result"])
        self.assertEqual(sent, [("标题", "内容")])

    def test_expired_message_dropped(self):
        msg_id = _enqueue_message("旧", "消息")
        path = self._tmp / f"{msg_id}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["ts"] = time.time() - 120  # 超过 60 秒视为过期
        path.write_text(json.dumps(data), encoding="utf-8")

        sent = []
        _process_send_queue(lambda t, m: sent.append(t))
        self.assertFalse(path.exists())  # 过期消息被删除
        self.assertEqual(sent, [])

    def test_wait_for_send_result(self):
        msg_id = _enqueue_message("T", "M")
        path = self._tmp / f"{msg_id}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["status"] = "done"
        data["result"] = True
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertTrue(_wait_for_send_result(msg_id, timeout=5))
        self.assertFalse(path.exists())  # 成功后清理队列文件


if __name__ == "__main__":
    unittest.main()
