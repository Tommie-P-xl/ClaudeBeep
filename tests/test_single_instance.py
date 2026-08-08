# -*- coding: utf-8 -*-
"""common/single_instance 单实例与 UI 探测单元测试。"""

import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.single_instance import acquire_file_lock, is_ui_running, port_in_use
from common import single_instance as si_module


class _MockHandler(BaseHTTPRequestHandler):
    """本地 mock 服务：按路径返回 ClaudeBeep 专有字段或其他内容。"""
    payload = {"foo": "bar"}

    def do_GET(self):
        body = json.dumps(self.payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class _MockServer:
    def __init__(self, payload):
        _MockHandler.payload = payload
        self.httpd = HTTPServer(("127.0.0.1", 0), _MockHandler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


class TestFileLock(unittest.TestCase):
    def setUp(self):
        # 隔离锁文件目录，避免在项目目录留下 test_instance.lock
        self._tmp = Path(tempfile.mkdtemp())
        self.enterContext(mock.patch.object(si_module, "RUNTIME_DIR", self._tmp))

    def tearDown(self):
        (self._tmp / "test_instance.lock").unlink(missing_ok=True)

    def test_second_acquire_fails(self):
        """第一个持有者存在时，第二次获取必须失败（多实例被拒绝）。"""
        first = acquire_file_lock("test_instance")
        self.assertIsNotNone(first, "首次获取锁应成功")
        try:
            second = acquire_file_lock("test_instance")
            self.assertIsNone(second, "已有持有者时第二次获取必须失败")
        finally:
            first.close()

    def test_acquire_after_release_succeeds(self):
        """释放（关闭句柄）后应能重新获取——模拟进程退出后锁自动释放。"""
        first = acquire_file_lock("test_instance")
        self.assertIsNotNone(first)
        first.close()
        second = acquire_file_lock("test_instance")
        self.assertIsNotNone(second, "释放后应可重新获取")
        second.close()


class TestUIProbe(unittest.TestCase):
    def test_port_probe_no_service(self):
        """探测未监听端口应返回 False。"""
        self.assertFalse(port_in_use(5199, timeout=0.3))

    def test_ui_detected_with_owned_field(self):
        """响应含 ClaudeBeep 专有字段（hooks_installed）→ 判定为已有 UI。"""
        with _MockServer({"hooks_installed": True}) as srv:
            self.assertTrue(is_ui_running(timeout=0.5, port=srv.port))

    def test_ui_not_detected_for_foreign_service(self):
        """其他程序占用端口（无专有字段）→ 不应误判为 ClaudeBeep UI。"""
        with _MockServer({"foo": "bar"}) as srv:
            self.assertFalse(is_ui_running(timeout=0.5, port=srv.port))


if __name__ == "__main__":
    unittest.main()
