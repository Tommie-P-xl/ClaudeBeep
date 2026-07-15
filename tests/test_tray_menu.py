import copy
import json

import config_store
import tray_menu


def test_channel_command_round_trip():
    command = tray_menu.channel_command_id("codex", "telegram")
    assert tray_menu.decode_command(command) == ("channel", "codex", "telegram")


def test_hook_command_round_trip():
    command = tray_menu.hook_command_id("claude_code", "PermissionRequest")
    assert tray_menu.decode_command(command) == (
        "hook", "claude_code", "PermissionRequest"
    )


def test_platform_command_round_trip():
    command = tray_menu.platform_command_id("codex")
    assert tray_menu.decode_command(command) == ("platform", "codex", None)


def test_platform_channel_menu_states_are_independent(legacy_config):
    config = config_store.migrate_config(copy.deepcopy(legacy_config))
    config["integrations"]["codex"]["enabled"] = True
    config_store.set_channel_enabled(config, "codex", "telegram", False)
    claude = tray_menu.channel_menu_state(config, "claude_code")
    codex = tray_menu.channel_menu_state(config, "codex")
    assert claude["telegram"]["checked"] is True
    assert codex["telegram"]["checked"] is False


def test_tray_channel_toggle_changes_only_selected_platform(monkeypatch, legacy_config):
    import tray

    config = config_store.migrate_config(copy.deepcopy(legacy_config))
    saved = []
    monkeypatch.setattr(tray, "_load_config", lambda: config)
    monkeypatch.setattr(tray, "_save_config", lambda value: saved.append(copy.deepcopy(value)))

    tray._toggle_channel("codex", "telegram")

    assert config["integrations"]["claude_code"]["channels"]["telegram"] is True
    assert config["integrations"]["codex"]["channels"]["telegram"] is True
    assert len(saved) == 1


def test_weixin_keepalive_changes_only_when_aggregate_policy_changes(
    monkeypatch, legacy_config
):
    import tray
    from channels import weixin

    config = config_store.migrate_config(copy.deepcopy(legacy_config))
    config["channels"]["weixin"]["bot_token"] = "token"
    config["integrations"]["codex"]["enabled"] = True
    calls = []
    monkeypatch.setattr(tray, "_load_config", lambda: config)
    monkeypatch.setattr(tray, "_save_config", lambda value: None)
    monkeypatch.setattr(weixin, "start_keepalive", lambda: calls.append("start"))
    monkeypatch.setattr(weixin, "stop_keepalive", lambda: calls.append("stop"))

    tray._toggle_channel("codex", "weixin")
    tray._toggle_channel("claude_code", "weixin")
    tray._toggle_channel("codex", "weixin")
    tray._toggle_channel("claude_code", "weixin")

    assert calls == ["start", "stop"]


def test_hook_command_saves_switch_and_synchronizes_platform(
    monkeypatch, legacy_config
):
    import hook_manager
    import tray

    config = config_store.migrate_config(copy.deepcopy(legacy_config))
    config["integrations"]["codex"]["enabled"] = True
    saved = []
    synchronized = []
    monkeypatch.setattr(tray, "_load_config", lambda: config)
    monkeypatch.setattr(tray, "_save_config", lambda value: saved.append(copy.deepcopy(value)))
    monkeypatch.setattr(
        hook_manager,
        "sync_hooks",
        lambda platform, events: synchronized.append((platform, tuple(events))),
    )

    tray._handle_command(
        0, tray_menu.hook_command_id("codex", "PermissionRequest")
    )

    assert saved[-1]["integrations"]["codex"]["events"]["PermissionRequest"] is False
    assert synchronized == [("codex", ("Stop",))]


def test_uninstall_command_disables_events_after_hook_write(
    monkeypatch, legacy_config
):
    import hook_manager
    import tray

    config = config_store.migrate_config(copy.deepcopy(legacy_config))
    order = []
    monkeypatch.setattr(tray, "_load_config", lambda: config)
    monkeypatch.setattr(tray, "_save_config", lambda value: order.append("config"))
    monkeypatch.setattr(
        hook_manager,
        "uninstall_hooks",
        lambda platform: order.append(("hooks", platform)),
    )

    tray._handle_command(0, tray_menu.UNINSTALL_ALL["claude_code"])

    assert order == [("hooks", "claude_code"), "config"]
    assert not any(config["integrations"]["claude_code"]["events"].values())


def test_hook_sync_failure_leaves_event_unchanged(monkeypatch, legacy_config):
    import hook_manager
    import tray

    config = config_store.migrate_config(copy.deepcopy(legacy_config))
    config["integrations"]["codex"]["enabled"] = True
    saved = []
    errors = []
    original = config["integrations"]["codex"]["events"]["PermissionRequest"]
    monkeypatch.setattr(tray, "_load_config", lambda: config)
    monkeypatch.setattr(tray, "_save_config", lambda value: saved.append(copy.deepcopy(value)))
    monkeypatch.setattr(tray, "_message_box", lambda message, title, flags: errors.append(message))

    def fail_sync(platform, events):
        raise RuntimeError("hook file unavailable")

    monkeypatch.setattr(hook_manager, "sync_hooks", fail_sync)

    tray._handle_command(0, tray_menu.hook_command_id("codex", "PermissionRequest"))

    assert config["integrations"]["codex"]["events"]["PermissionRequest"] is original
    assert saved == []
    assert errors and "hook file unavailable" in errors[0]


def test_disabled_tray_event_toggle_persists_preference_without_hooks(monkeypatch, tmp_path, legacy_config):
    import hook_manager
    import tray

    config = config_store.migrate_config(copy.deepcopy(legacy_config))
    config["integrations"]["codex"]["enabled"] = False
    path = tmp_path / "hooks.json"
    monkeypatch.setattr(hook_manager, "CODEX_HOOKS", path)
    hook_manager.sync_hooks("codex", {"Stop"})
    saved = []
    monkeypatch.setattr(tray, "_load_config", lambda: config)
    monkeypatch.setattr(tray, "_save_config", lambda value: saved.append(copy.deepcopy(value)))

    tray._handle_command(0, tray_menu.hook_command_id("codex", "SessionStart"))

    assert saved[-1]["integrations"]["codex"]["events"]["SessionStart"] is True
    assert hook_manager.inspect_hooks("codex").configured_events == ()


def test_all_tray_command_ids_are_unique_and_decode_correctly():
    import tray

    commands = {}
    for platform in config_store.PLATFORMS:
        command = tray_menu.platform_command_id(platform)
        commands[command] = ("platform", platform, None)
        for channel in config_store.CHANNEL_NAMES:
            command = tray_menu.channel_command_id(platform, channel)
            commands[command] = ("channel", platform, channel)
        events = (
            config_store.CLAUDE_EVENTS
            if platform == "claude_code"
            else config_store.CODEX_EVENTS
        )
        for event in events:
            command = tray_menu.hook_command_id(platform, event)
            commands[command] = ("hook", platform, event)
        commands[tray_menu.UNINSTALL_ALL[platform]] = ("uninstall", platform, None)

    assert len(commands) == (2 + 2 * len(config_store.CHANNEL_NAMES)
                             + len(config_store.CLAUDE_EVENTS)
                             + len(config_store.CODEX_EVENTS) + 2)
    for command, expected in commands.items():
        assert tray_menu.decode_command(command) == expected

    legacy = {
        tray.CMD_OPEN_UI,
        tray.CMD_STARTUP,
        tray.CMD_CHECK_UPDATE,
        tray.CMD_QUIT,
    }
    assert not legacy & commands.keys()


def test_platform_toggles_are_independent(monkeypatch, legacy_config):
    import hook_manager
    import tray

    config = config_store.migrate_config(copy.deepcopy(legacy_config))
    config["integrations"]["codex"]["enabled"] = False
    saved = []
    sync_calls = []
    uninstall_calls = []
    monkeypatch.setattr(tray, "_load_config", lambda: config)
    monkeypatch.setattr(tray, "_save_config", lambda value: saved.append(copy.deepcopy(value)))
    monkeypatch.setattr(
        hook_manager,
        "sync_hooks",
        lambda platform, events: sync_calls.append((platform, tuple(events))),
    )
    monkeypatch.setattr(hook_manager, "uninstall_hooks", lambda platform: uninstall_calls.append(platform))

    tray._handle_command(0, tray_menu.platform_command_id("codex"))
    tray._handle_command(0, tray_menu.platform_command_id("claude_code"))

    assert config["integrations"]["codex"]["enabled"] is True
    assert config["integrations"]["claude_code"]["enabled"] is False
    assert sync_calls == [("codex", ("Stop", "PermissionRequest"))]
    assert uninstall_calls == ["claude_code"]
    assert len(saved) == 2


def test_platform_toggle_save_failure_restores_state_and_hooks(monkeypatch, legacy_config):
    import hook_manager
    import tray

    config = config_store.migrate_config(copy.deepcopy(legacy_config))
    original = config["integrations"]["codex"]["enabled"]
    calls = []
    restored = []
    errors = []
    monkeypatch.setattr(tray, "_load_config", lambda: config)
    monkeypatch.setattr(tray, "_save_config", lambda value: (_ for _ in ()).throw(OSError("disk")))
    monkeypatch.setattr(tray, "_message_box", lambda message, title, flags: errors.append(message))
    monkeypatch.setattr(
        hook_manager,
        "sync_hooks",
        lambda platform, events: calls.append(("sync", platform, tuple(events))),
    )
    monkeypatch.setattr(hook_manager, "uninstall_hooks", lambda platform: calls.append(("uninstall", platform)))
    monkeypatch.setattr(hook_manager, "snapshot_hooks", lambda platform: "exact-before")
    monkeypatch.setattr(hook_manager, "restore_hooks", lambda snapshot: restored.append(snapshot))

    tray._handle_command(0, tray_menu.platform_command_id("codex"))

    assert config["integrations"]["codex"]["enabled"] is original
    assert calls == [("sync", "codex", ("Stop", "PermissionRequest"))]
    assert restored == ["exact-before"]
    assert errors and "保存配置失败" in errors[0]


def test_platform_toggle_sync_failure_preserves_state(monkeypatch, legacy_config):
    import hook_manager
    import tray

    config = config_store.migrate_config(copy.deepcopy(legacy_config))
    config["integrations"]["codex"]["enabled"] = True
    config["integrations"]["codex"]["enabled"] = False
    saved = []
    errors = []
    monkeypatch.setattr(tray, "_load_config", lambda: config)
    monkeypatch.setattr(tray, "_save_config", lambda value: saved.append(value))
    monkeypatch.setattr(tray, "_message_box", lambda message, title, flags: errors.append(message))
    monkeypatch.setattr(
        hook_manager, "sync_hooks", lambda platform, events: (_ for _ in ()).throw(OSError("hook"))
    )

    tray._handle_command(0, tray_menu.platform_command_id("codex"))

    assert config["integrations"]["codex"]["enabled"] is False
    assert saved == []
    assert errors and "同步" in errors[0]


def test_platform_toggle_updates_aggregate_keepalive(monkeypatch, legacy_config):
    import hook_manager
    import tray
    from channels import weixin

    config = config_store.migrate_config(copy.deepcopy(legacy_config))
    config["channels"]["weixin"]["bot_token"] = "token"
    config["integrations"]["codex"]["enabled"] = False
    config["integrations"]["codex"]["channels"]["weixin"] = True
    calls = []
    monkeypatch.setattr(tray, "_load_config", lambda: config)
    monkeypatch.setattr(tray, "_save_config", lambda value: None)
    monkeypatch.setattr(hook_manager, "sync_hooks", lambda platform, events: None)
    monkeypatch.setattr(hook_manager, "uninstall_hooks", lambda platform: None)
    monkeypatch.setattr(weixin, "start_keepalive", lambda: calls.append("start"))
    monkeypatch.setattr(weixin, "stop_keepalive", lambda: calls.append("stop"))

    tray._handle_command(0, tray_menu.platform_command_id("codex"))
    tray._handle_command(0, tray_menu.platform_command_id("codex"))

    assert calls == ["start", "stop"]


def test_menu_refresh_applies_external_keepalive_transition(monkeypatch, legacy_config):
    import tray

    before = config_store.migrate_config(copy.deepcopy(legacy_config))
    before["channels"]["weixin"]["bot_token"] = "token"
    before["integrations"]["claude_code"]["channels"]["weixin"] = False
    after = config_store.migrate_config(copy.deepcopy(before))
    after["integrations"]["codex"]["enabled"] = True
    after["integrations"]["codex"]["channels"]["weixin"] = True
    configs = iter((before, after))
    mtimes = iter((1.0, 2.0))
    transitions = []

    class OneIterationStop:
        waited = False

        def is_set(self):
            return self.waited

        def wait(self, timeout):
            self.waited = True

    monkeypatch.setattr(tray, "_stop_event", OneIterationStop())
    monkeypatch.setattr(tray, "_load_config", lambda: next(configs))
    monkeypatch.setattr(tray, "_mtime", lambda path: next(mtimes))
    monkeypatch.setattr(tray, "_update_tray_tooltip", lambda text: None)
    monkeypatch.setattr(
        tray, "_sync_weixin_keepalive", lambda old, new: transitions.append((old, new))
    )

    tray._menu_refresh_loop(0)

    assert transitions == [(False, True)]


def test_hook_save_failure_restores_event_and_rolls_back_hooks(
    monkeypatch, legacy_config
):
    import hook_manager
    import tray

    config = config_store.migrate_config(copy.deepcopy(legacy_config))
    config["integrations"]["codex"]["enabled"] = True
    original_events = copy.deepcopy(config["integrations"]["codex"]["events"])
    synchronized = []
    restored = []
    errors = []
    monkeypatch.setattr(tray, "_load_config", lambda: config)
    monkeypatch.setattr(
        tray, "_save_config", lambda value: (_ for _ in ()).throw(OSError("disk full"))
    )
    monkeypatch.setattr(hook_manager, "snapshot_hooks", lambda platform: "exact-before")
    monkeypatch.setattr(hook_manager, "restore_hooks", lambda snapshot: restored.append(snapshot))
    monkeypatch.setattr(tray, "_message_box", lambda message, title, flags: errors.append(message))
    monkeypatch.setattr(
        hook_manager,
        "sync_hooks",
        lambda platform, events: synchronized.append((platform, tuple(events))),
    )

    tray._handle_command(0, tray_menu.hook_command_id("codex", "PermissionRequest"))

    assert synchronized == [("codex", ("Stop",))]
    assert restored == ["exact-before"]
    assert config["integrations"]["codex"]["events"] == original_events
    assert errors and "保存配置失败" in errors[0]


def test_hook_rollback_failure_is_contained_and_reported(monkeypatch, legacy_config):
    import hook_manager
    import tray

    config = config_store.migrate_config(copy.deepcopy(legacy_config))
    config["integrations"]["codex"]["enabled"] = True
    original_events = copy.deepcopy(config["integrations"]["codex"]["events"])
    sync_calls = []
    errors = []
    monkeypatch.setattr(tray, "_load_config", lambda: config)
    monkeypatch.setattr(
        tray, "_save_config", lambda value: (_ for _ in ()).throw(OSError("secret path"))
    )
    monkeypatch.setattr(tray, "_message_box", lambda message, title, flags: errors.append(message))

    def sync_then_fail(platform, events):
        sync_calls.append((platform, tuple(events)))

    monkeypatch.setattr(hook_manager, "sync_hooks", sync_then_fail)
    monkeypatch.setattr(hook_manager, "snapshot_hooks", lambda platform: "exact-before")
    monkeypatch.setattr(hook_manager, "restore_hooks", lambda snapshot: (_ for _ in ()).throw(RuntimeError("secret command")))

    tray._handle_command(0, tray_menu.hook_command_id("codex", "PermissionRequest"))

    assert len(sync_calls) == 1
    assert config["integrations"]["codex"]["events"] == original_events
    assert errors and "保存配置失败" in errors[0] and "回滚 hooks 失败" in errors[0]
    assert "secret path" not in errors[0]
    assert "secret command" not in errors[0]


def test_tray_config_save_failure_restores_exact_hook_bytes(monkeypatch, tmp_path, legacy_config):
    import hook_manager
    import tray

    config = config_store.migrate_config(copy.deepcopy(legacy_config))
    config["integrations"]["codex"]["enabled"] = True
    path = tmp_path / "hooks.json"
    monkeypatch.setattr(hook_manager, "CODEX_HOOKS", path)
    hook_manager.sync_hooks("codex", {"SessionStart"})
    data = json.loads(path.read_text(encoding="utf-8"))
    data["third_party"] = [1, 2, 3]
    path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    before = path.read_bytes()
    monkeypatch.setattr(tray, "_load_config", lambda: config)
    monkeypatch.setattr(tray, "_save_config", lambda value: (_ for _ in ()).throw(OSError("disk full")))
    monkeypatch.setattr(tray, "_message_box", lambda *args: None)

    tray._handle_command(0, tray_menu.hook_command_id("codex", "PermissionRequest"))

    assert path.read_bytes() == before
