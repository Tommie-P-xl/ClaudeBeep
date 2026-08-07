# -*- coding: utf-8 -*-
"""config_store 迁移 / 脱敏 / tray_menu 解码单元测试。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config_store
from notification_core import _safe_error
from tray_menu import decode_command, channel_command_id, hook_command_id


class TestUpdateChannelFields(unittest.TestCase):
    """H1 回归：update_channel_fields 写入 canonical 后，重新加载必须仍能读到。

    旧实现（listeners/base._update_config）直接写顶层遗留镜像，
    下一次 load_config 时镜像被 canonical 重建覆盖，写入静默丢失。
    """

    def setUp(self):
        import tempfile
        from pathlib import Path
        self._tmp = Path(tempfile.mkdtemp())
        self._path = self._tmp / "config.json"

    def test_write_survives_reload(self):
        changed = config_store.update_channel_fields(
            "telegram", {"chat_id": "12345_CAPTURED"}, path=self._path
        )
        self.assertTrue(changed)
        # 绕过进程内缓存，模拟另一进程重新加载
        reloaded = config_store.load_config(self._path)
        self.assertEqual(reloaded["channels"]["telegram"]["chat_id"], "12345_CAPTURED")
        # 镜像同步刷新
        self.assertEqual(reloaded["telegram"]["chat_id"], "12345_CAPTURED")

    def test_unchanged_value_skips_write(self):
        config_store.update_channel_fields("qq", {"target_id": "t1"}, path=self._path)
        changed = config_store.update_channel_fields("qq", {"target_id": "t1"}, path=self._path)
        self.assertFalse(changed)

    def test_unknown_channel_raises(self):
        with self.assertRaises(ValueError):
            config_store.update_channel_fields("nope", {"a": 1}, path=self._path)

    def test_concurrent_writers_no_lost_update(self):
        """M4 回归：update_config 的读-改-写全程持锁，并发写不丢更新。"""
        import threading

        config_store.update_channel_fields("qq", {"target_id": "base"}, path=self._path)
        barrier = threading.Barrier(8)

        def writer(i):
            barrier.wait()
            config_store.update_config(
                lambda cfg: cfg["channels"]["qq"].update({f"k{i}": i}), path=self._path
            )

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        final = config_store.load_config(self._path)
        for i in range(8):
            self.assertEqual(final["channels"]["qq"].get(f"k{i}"), i)


class TestMigrateConfig(unittest.TestCase):
    def test_legacy_channels_promoted(self):
        raw = {
            "weixin": {"enabled": True, "bot_token": "x"},
            "qq": {"enabled": False},
        }
        migrated = config_store.migrate_config(raw)
        self.assertIn("channels", migrated)
        self.assertEqual(migrated["channels"]["weixin"]["bot_token"], "x")
        self.assertTrue(migrated["integrations"]["claude_code"]["channels"]["weixin"])
        self.assertFalse(migrated["integrations"]["claude_code"]["channels"]["qq"])

    def test_deep_fill_defaults(self):
        raw = {"integrations": {}}
        migrated = config_store.migrate_config(raw)
        self.assertIn("claude_code", migrated["integrations"])
        self.assertIn("codex", migrated["integrations"])
        # 渠道默认值补齐
        self.assertIn("windows_toast", migrated["channels"])

    def test_non_dict_root_raises(self):
        with self.assertRaises(config_store.ConfigFileError):
            config_store.migrate_config([])

    def test_runtime_channel_config(self):
        cfg = config_store.migrate_config({})
        runtime = config_store.runtime_channel_config(cfg, "claude_code")
        self.assertIn("windows_toast", runtime)
        self.assertTrue(runtime["windows_toast"]["enabled"])  # 默认启用


class TestSafeErrorRedaction(unittest.TestCase):
    def test_secret_redacted(self):
        cfg = {"channels": {"qq": {"app_secret": "SUPERSECRET-123"}}}
        msg = _safe_error(RuntimeError("auth failed with SUPERSECRET-123"), cfg)
        self.assertNotIn("SUPERSECRET-123", msg)
        self.assertIn("[redacted]", msg)

    def test_token_redacted(self):
        cfg = {"channels": {"telegram": {"bot_token": "123456:ABC"}}}
        msg = _safe_error(RuntimeError("HTTP 401 for 123456:ABC"), cfg)
        self.assertNotIn("123456:ABC", msg)


class TestTrayMenuDecode(unittest.TestCase):
    def test_channel_roundtrip(self):
        for channel in config_store.CHANNEL_NAMES:
            cid = channel_command_id("claude_code", channel)
            kind, platform, value = decode_command(cid)
            self.assertEqual((kind, platform, value), ("channel", "claude_code", channel))

    def test_hook_roundtrip(self):
        for event in config_store.CLAUDE_EVENTS:
            hid = hook_command_id("claude_code", event)
            kind, platform, value = decode_command(hid)
            self.assertEqual((kind, platform, value), ("hook", "claude_code", event))

    def test_unknown_returns_none(self):
        self.assertIsNone(decode_command(0))
        self.assertIsNone(decode_command(999999))


if __name__ == "__main__":
    unittest.main()
