# -*- coding: utf-8 -*-
"""config_store 迁移 / 脱敏 / tray_menu 解码单元测试。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config_store
from notification_core import _safe_error
from tray_menu import decode_command, channel_command_id, hook_command_id


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
