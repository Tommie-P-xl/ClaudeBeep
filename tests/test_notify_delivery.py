import sys

import notify


class RecordingChannel:
    def __init__(self, name, events, succeeds=True, enabled=True):
        self._name = name
        self._events = events
        self._succeeds = succeeds
        self._enabled = enabled
        self.enabled_checks = 0
        self.send_calls = 0

    @property
    def name(self):
        return self._name

    def is_enabled(self):
        self.enabled_checks += 1
        self._events.append(f"state:{self.name}")
        return self._enabled

    def send(self, title, message):
        self.send_calls += 1
        self._events.append(f"send:{self.name}")
        if isinstance(self._succeeds, Exception):
            raise self._succeeds
        return self._succeeds


def test_noninteractive_main_preserves_per_channel_delivery_order(
    monkeypatch, legacy_config
):
    events = []
    failed = RecordingChannel("first", events, RuntimeError("offline"))
    passed = RecordingChannel("second", events)
    disabled = RecordingChannel("third", events, enabled=False)
    monkeypatch.setattr(notify, "load_config", lambda: legacy_config)
    monkeypatch.setattr(
        notify, "collect_channels", lambda config: [failed, passed, disabled]
    )

    def capture_channel_log(message):
        if message.startswith("["):
            events.append(f"log:{message}")

    monkeypatch.setattr(notify, "log", capture_channel_log)
    monkeypatch.setattr(
        sys, "argv", ["notify.py", "--type", "stop", "--message", "hello"]
    )

    notify.main()

    assert failed.enabled_checks == 1
    assert failed.send_calls == 1
    assert passed.enabled_checks == 1
    assert passed.send_calls == 1
    assert disabled.enabled_checks == 1
    assert disabled.send_calls == 0
    assert events == [
        "state:first",
        "log:[first] 发送通知: Claude Code - 完成 | hello",
        "send:first",
        "log:[first] 发送结果: 失败",
        "state:second",
        "log:[second] 发送通知: Claude Code - 完成 | hello",
        "send:second",
        "log:[second] 发送结果: 成功",
        "state:third",
        "log:[third] 已禁用，跳过",
    ]


def test_codex_platform_stdin_routes_without_marker(monkeypatch):
    called = []
    monkeypatch.setattr(notify, "_read_stdin_utf8", lambda: '{"hook_event_name":"Stop"}')
    monkeypatch.setattr("codex_adapter.run_codex_hook", lambda raw: called.append(raw) or 0)
    monkeypatch.setattr(sys, "argv", ["notify.py", "--platform", "codex", "--from-stdin"])
    notify.main()
    assert called == ['{"hook_event_name":"Stop"}']
