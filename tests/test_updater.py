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
from updater import parse_version, check_for_update, _verify_sha256, _find_setup_asset


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


if __name__ == "__main__":
    unittest.main()
