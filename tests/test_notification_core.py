from notification_core import NotificationEvent, collect_channels, send_event


class FakeChannel:
    def __init__(self, name, enabled=True, succeeds=True):
        self._name = name
        self._enabled = enabled
        self._succeeds = succeeds
        self.messages = []

    @property
    def name(self):
        return self._name

    def is_enabled(self):
        if isinstance(self._enabled, Exception):
            raise self._enabled
        return self._enabled

    def send(self, title, message):
        self.messages.append((title, message))
        if isinstance(self._succeeds, Exception):
            raise self._succeeds
        return self._succeeds


def test_send_event_isolates_channel_failure(legacy_config):
    event = NotificationEvent("codex", "Stop", "Codex - 完成", "Done", "C:/repo", "s1")
    failed = FakeChannel("telegram", succeeds=RuntimeError("offline"))
    passed = FakeChannel("windows_toast", succeeds=True)

    results = send_event(event, legacy_config, channels=[failed, passed])

    assert [result.success for result in results] == [False, True]
    assert results[0].error == "offline"
    assert passed.messages == [("Codex - 完成", "Done")]


def test_send_event_skips_disabled_channels(legacy_config):
    event = NotificationEvent("codex", "Stop", "title", "message")
    disabled = FakeChannel("telegram", enabled=False)

    assert send_event(event, legacy_config, channels=[disabled]) == []
    assert disabled.messages == []


def test_send_event_isolates_enabled_check_failure(legacy_config):
    failed = FakeChannel("telegram", enabled=RuntimeError("state unavailable"))
    passed = FakeChannel("windows_toast")

    results = send_event(
        NotificationEvent("codex", "Stop", "title", "message"),
        legacy_config,
        channels=[failed, passed],
    )

    assert [result.success for result in results] == [False, True]
    assert passed.messages == [("title", "message")]


def test_send_event_redacts_credentials_from_channel_errors(legacy_config):
    legacy_config["telegram"]["chat_id"] = 42
    token = legacy_config["telegram"]["bot_token"]
    chat_id = legacy_config["telegram"]["chat_id"]
    failed = FakeChannel(
        "telegram",
        succeeds=RuntimeError(f"request failed for {token} in chat {chat_id}"),
    )

    result = send_event(
        NotificationEvent("codex", "Stop", "title", "message"),
        legacy_config,
        channels=[failed],
    )[0]

    assert token not in result.error
    assert str(chat_id) not in result.error


def test_collect_channels_uses_platform_specific_runtime_config(legacy_config):
    seen = []

    def factory(config):
        seen.append(config)
        return FakeChannel("telegram", enabled=config["telegram"]["enabled"])

    channels = collect_channels(legacy_config, "codex", factories={"telegram": factory})

    assert [channel.name for channel in channels] == ["telegram"]
    assert seen[0]["telegram"]["bot_token"] == "test-token"
    assert seen[0]["telegram"]["enabled"] is False
