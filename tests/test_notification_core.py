# -*- coding: utf-8 -*-
"""notification_core 投递核心单元测试。

覆盖使用路径：单/多渠道投递、失败隔离（单渠道异常不影响其他渠道）、
禁用渠道跳过、observer 回调、自定义渠道工厂。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from notification_core import NotificationEvent, DeliveryResult, collect_channels, send_event


class FakeChannel:
    """可编程的假渠道：配置化启用状态、返回值与异常。"""

    def __init__(self, cfg, enabled=True, send_result=True, send_raises=None, name="fake"):
        self.config = cfg
        self.enabled_flag = enabled
        self.send_result = send_result
        self.send_raises = send_raises
        self.name = name
        self.platform = ""
        self.sent = []  # (title, message) 记录

    def set_platform(self, platform):
        self.platform = platform

    def is_enabled(self):
        return self.enabled_flag

    def send(self, title, message):
        self.sent.append((title, message))
        if self.send_raises:
            raise self.send_raises
        return self.send_result


EVENT = NotificationEvent(platform="claude_code", event_name="Stop", title="T", message="M")


class TestSendEvent(unittest.TestCase):
    def _cfg(self):
        return {"integrations": {"claude_code": {"channels": {}}}}

    def test_single_channel_success(self):
        ch = FakeChannel(self._cfg())
        results = send_event(EVENT, self._cfg(), channels=[ch])
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].success)
        self.assertEqual(results[0].channel, "fake")
        self.assertEqual(ch.sent, [("T", "M")])

    def test_channel_returns_false_is_failure(self):
        ch = FakeChannel(self._cfg(), send_result=False)
        results = send_event(EVENT, self._cfg(), channels=[ch])
        self.assertFalse(results[0].success)
        self.assertIn("failure", results[0].error)

    def test_exception_is_isolated(self):
        """一个渠道抛异常不能影响其他渠道送达。"""
        bad = FakeChannel(self._cfg(), name="bad", send_raises=RuntimeError("boom"))
        good = FakeChannel(self._cfg(), name="good")
        results = send_event(EVENT, self._cfg(), channels=[bad, good])
        by_name = {r.channel: r for r in results}
        self.assertFalse(by_name["bad"].success)
        self.assertIn("boom", by_name["bad"].error)
        self.assertTrue(by_name["good"].success)
        self.assertEqual(good.sent, [("T", "M")])

    def test_disabled_channel_skipped(self):
        ch = FakeChannel(self._cfg(), enabled=False)
        results = send_event(EVENT, self._cfg(), channels=[ch])
        self.assertEqual(results, [])
        self.assertEqual(ch.sent, [])

    def test_parallel_multi_channel_order_preserved(self):
        channels = [FakeChannel(self._cfg(), name=f"c{i}") for i in range(4)]
        results = send_event(EVENT, self._cfg(), channels=channels)
        self.assertEqual([r.channel for r in results], ["c0", "c1", "c2", "c3"])
        for ch in channels:
            self.assertEqual(ch.sent, [("T", "M")])

    def test_observer_callbacks(self):
        ch = FakeChannel(self._cfg())
        seen = []

        def observer(stage, channel, result):
            seen.append(stage)

        send_event(EVENT, self._cfg(), channels=[ch], observer=observer)
        self.assertIn("sending", seen)
        self.assertIn("result", seen)

    def test_disabled_observer_called(self):
        ch = FakeChannel(self._cfg(), enabled=False)
        seen = []
        send_event(EVENT, self._cfg(), channels=[ch], observer=lambda s, c, r: seen.append(s))
        self.assertIn("disabled", seen)


class TestCollectChannels(unittest.TestCase):
    def test_custom_factories(self):
        cfg = {"integrations": {"claude_code": {"channels": {"fake": True}}}}
        factories = {"fake": lambda cfg: FakeChannel(cfg, name="fake")}
        channels = collect_channels(cfg, "claude_code", factories=factories)
        self.assertEqual(len(channels), 1)
        self.assertEqual(channels[0].name, "fake")

    def test_unselected_channel_not_collected(self):
        """默认工厂路径：未启用的渠道不应被实例化（返回空列表）。"""
        # migrate_config 会补默认值，windows_toast 默认启用，需显式全部关闭
        cfg = {"integrations": {"claude_code": {"channels": {
            "windows_toast": False, "weixin": False, "qq": False,
            "telegram": False, "feishu": False, "dingtalk": False,
        }}}}
        self.assertEqual(collect_channels(cfg, "claude_code"), [])


if __name__ == "__main__":
    unittest.main()
