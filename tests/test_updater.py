# -*- coding: utf-8 -*-
"""updater 版本解析与更新判断逻辑单元测试。

覆盖使用路径：检查更新（版本比较、latest.json 优先、GitHub API 兜底）、SHA256 校验。
网络请求全部 mock，不产生真实流量。
"""

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import updater
from updater import (
    parse_version,
    check_for_update,
    _verify_sha256,
    _find_setup_asset,
    _build_replace_script,
)


class TestParseVersion(unittest.TestCase):
    def test_standard(self):
        self.assertEqual(parse_version("2.3.0"), (2, 3, 0))

    def test_leading_v(self):
        self.assertEqual(parse_version("v2.3.0"), (2, 3, 0))

    def test_two_parts(self):
        self.assertEqual(parse_version("2.3"), (2, 3, 0))

    def test_four_parts_truncated(self):
        self.assertEqual(parse_version("2.3.0.1"), (2, 3, 0))

    def test_prerelease_suffix_no_crash(self):
        """B3 回归：预发布版本不能抛异常，应提取数字段。"""
        self.assertEqual(parse_version("2.3.0-rc1"), (2, 3, 0))
        self.assertEqual(parse_version("v2.4.0-beta.2"), (2, 4, 0))

    def test_garbage_returns_zeros(self):
        self.assertEqual(parse_version("not-a-version"), (0, 0, 0))
        self.assertEqual(parse_version(""), (0, 0, 0))

    def test_comparison(self):
        self.assertGreater(parse_version("2.4.0"), parse_version("2.3.9"))
        self.assertEqual(parse_version("2.3.0"), parse_version("v2.3.0"))


class TestCheckForUpdate(unittest.TestCase):
    def setUp(self):
        # 隔离 updater.log 写入（updater._log 运行时读取 common.paths.RUNTIME_DIR）
        self.enterContext(mock.patch(
            "common.paths.RUNTIME_DIR", Path(tempfile.mkdtemp())))

    def test_newer_via_latest_json(self):
        with mock.patch.object(updater, "_fetch_json", return_value={
            "version": "2.4.0",
            "url": "https://example.com/ClaudeBeep-Setup-2.4.0.exe",
            "sha256": "abc123",
        }) as fetch:
            info = check_for_update("2.3.0")
        self.assertIsNotNone(info)
        self.assertEqual(info["version"], "2.4.0")
        self.assertEqual(info["url"], "https://example.com/ClaudeBeep-Setup-2.4.0.exe")
        self.assertEqual(info["sha256"], "abc123")
        fetch.assert_called_once_with(updater.LATEST_JSON_URL)

    def test_no_update_when_older(self):
        with mock.patch.object(updater, "_fetch_json", return_value={"version": "2.2.0"}):
            info = check_for_update("2.3.0")
        self.assertIsNone(info)

    def test_same_version_no_update(self):
        with mock.patch.object(updater, "_fetch_json", return_value={"version": "2.3.0"}):
            info = check_for_update("2.3.0")
        self.assertIsNone(info)

    def test_fallback_to_github_api(self):
        release = {
            "tag_name": "v2.5.0",
            "assets": [{
                "name": "ClaudeBeep-Setup-2.5.0.exe",
                "browser_download_url": "https://example.com/setup.exe",
            }],
        }
        # 第一次（latest.json）返回 None 触发兜底；第二次返回 release
        with mock.patch.object(updater, "_fetch_json", side_effect=[None, release]) as fetch:
            info = check_for_update("2.3.0")
        self.assertIsNotNone(info)
        self.assertEqual(info["version"], "v2.5.0")
        self.assertEqual(info["url"], "https://example.com/setup.exe")
        self.assertEqual(fetch.call_count, 2)


class TestFindSetupAsset(unittest.TestCase):
    def test_prefers_setup_exe(self):
        release = {"assets": [
            {"name": "ClaudeBeep.exe", "browser_download_url": "u1"},
            {"name": "ClaudeBeep-Setup-2.3.0.exe", "browser_download_url": "u2"},
        ]}
        self.assertEqual(_find_setup_asset(release), "u2")

    def test_fallback_by_name(self):
        release = {"assets": [{"name": "ClaudeBeep-portable.exe", "browser_download_url": "u1"}]}
        self.assertEqual(_find_setup_asset(release), "u1")

    def test_no_match(self):
        self.assertIsNone(_find_setup_asset({"assets": [{"name": "readme.md", "browser_download_url": "u"}]}))


class TestVerifySha256(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch(
            "common.paths.RUNTIME_DIR", Path(tempfile.mkdtemp())))

    def _make_file(self, content: bytes) -> Path:
        fd, path = tempfile.mkstemp()
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        return Path(path)

    def test_match(self):
        p = self._make_file(b"hello")
        digest = hashlib.sha256(b"hello").hexdigest()
        try:
            self.assertTrue(_verify_sha256(p, digest))
        finally:
            p.unlink(missing_ok=True)

    def test_mismatch(self):
        p = self._make_file(b"hello")
        try:
            self.assertFalse(_verify_sha256(p, "0" * 64))
        finally:
            p.unlink(missing_ok=True)

    def test_empty_expected_skips(self):
        p = self._make_file(b"hello")
        try:
            self.assertTrue(_verify_sha256(p, ""))
            self.assertTrue(_verify_sha256(p, "  "))
        finally:
            p.unlink(missing_ok=True)


class TestReplaceScript(unittest.TestCase):
    """U5 回归：standalone 替换脚本（PowerShell）必须包含关键可靠逻辑。"""

    def _script(self):
        return _build_replace_script(
            Path(r"D:\ClaudeBeep\ClaudeBeep.exe"),
            Path(r"C:\Temp\x\ClaudeBeep.exe"),
            Path(r"C:\Users\测试\AppData\Roaming\ClaudeBeep\update_result.json"),
            "2.3.1",
        )

    def test_wait_for_process_exit(self):
        s = self._script()
        self.assertIn("Get-Process -Name ClaudeBeep", s)
        self.assertIn("AddSeconds(30)", s)

    def test_uses_start_sleep_not_timeout(self):
        """U5 核心：弃用 cmd timeout（无控制台环境失效），改用 Start-Sleep。"""
        s = self._script()
        self.assertNotIn("timeout /t", s)
        self.assertIn("Start-Sleep -Milliseconds 500", s)

    def test_retry_and_restore(self):
        s = self._script()
        self.assertIn("Rename-Item $target $backup", s)
        self.assertIn("Copy-Item $new $target", s)
        self.assertIn("Move-Item $backup $target", s)  # 失败时恢复备份
        self.assertIn("-lt 20", s)  # 重试上限

    def test_result_reporting(self):
        """替换结果必须写入 update_result.json，便于下次启动提示。"""
        s = self._script()
        self.assertIn("update_result.json", s)
        self.assertIn("ConvertTo-Json", s)
        self.assertIn("Write-Result $false", s)
        self.assertIn("Write-Result $true", s)

    def test_launches_new_version_after_delay(self):
        """U7：新 exe 启动前必须等待文件解锁（杀软扫描完成），并带验证。"""
        s = self._script()
        self.assertIn("Wait-FileUnlocked", s)
        self.assertIn("[System.IO.File]::Open($path, 'Open', 'Read', 'None')", s)
        self.assertIn("Start-Process $target", s)

    def test_launch_retries_on_error_dialog(self):
        """U7：引导器弹出 Error 对话框（Failed to load Python DLL）时应关闭并重试。"""
        s = self._script()
        self.assertIn("-lt 3", s)  # 最多 3 次启动尝试
        self.assertIn("MainWindowTitle -eq 'Error'", s)
        self.assertIn("CloseMainWindow", s)
        self.assertIn("$_.Kill()", s)

    def test_launch_failure_reports_manual_run(self):
        """U7：启动彻底失败时结果文件必须提示手动运行。"""
        s = self._script()
        self.assertIn("请手动运行: $target", s)
        self.assertIn("新版本启动失败（引导器解压异常）", s)

    def test_paths_interpolated_and_quoted(self):
        s = self._script()
        self.assertIn(r"D:\ClaudeBeep\ClaudeBeep.exe", s)
        self.assertIn(r"C:\Temp\x\ClaudeBeep.exe", s)
        self.assertIn(r"C:\Users\测试\AppData\Roaming\ClaudeBeep\update_result.json", s)

    def test_window_style_hidden(self):
        """U5：替换脚本必须以隐藏窗口方式运行，消除黑框闪现。"""
        s = self._script()
        # 启动参数在 perform_update 的 Popen 中，这里验证模板不含交互性命令
        self.assertNotIn("Read-Host", s)
        self.assertNotIn("pause", s)


if __name__ == "__main__":
    unittest.main()
