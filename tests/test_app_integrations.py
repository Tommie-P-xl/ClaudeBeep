import json

import pytest

import app as app_module
import config_store
import hook_manager
import notification_core


@pytest.fixture
def isolated_config_path(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    monkeypatch.setattr(config_store, "CONFIG_FILE", path)
    monkeypatch.setattr(app_module, "CONFIG_FILE", path)
    monkeypatch.setattr(hook_manager, "CLAUDE_SETTINGS", tmp_path / ".claude" / "settings.json")
    monkeypatch.setattr(hook_manager, "CODEX_HOOKS", tmp_path / ".codex" / "hooks.json")
    return path


@pytest.fixture
def client(isolated_config_path):
    application = app_module.create_app()
    application.config.update(TESTING=True)
    with application.test_client() as test_client:
        yield test_client


def test_integrations_are_returned_as_peers(client):
    response = client.get("/api/integrations")
    assert response.status_code == 200
    data = response.get_json()
    assert set(data["integrations"]) == {"claude_code", "codex"}


def test_index_contains_peer_integration_controls(client):
    html = client.get("/").get_data(as_text=True)
    assert 'data-integration="claude_code"' in html
    assert 'data-integration="codex"' in html
    assert "共享通知渠道凭证" in html
    assert "批准和回答仍在 Codex 中完成" in html
    assert "/api/integrations" in html


def test_index_peer_ui_uses_safe_responsive_platform_contracts(client):
    html = client.get("/").get_data(as_text=True)
    assert "(hookStatus[platform]?.configured_events || []).length" in html
    assert 'class="w-full overflow-x-auto"' in html
    assert 'class="tab-bar" style="width:max-content"' in html
    assert "async testIntegration(platform)" in html
    assert "`/api/integrations/${platform}/test`" in html
    assert "@click=\"toggleChannel('weixin'" not in html
    assert "@click=\"toggleChannel('qq'" not in html
    assert html.count("共享通知渠道凭证") >= 5
    assert "hookStatus.claude_code?.configured_events || []" in html


def test_codex_channel_toggle_does_not_change_claude(client):
    client.put("/api/config", json={"telegram": {"bot_token": "test-token", "chat_id": "42"}})
    claude_response = client.post(
        "/api/integrations/claude_code/channels/telegram/toggle",
        json={"enabled": False},
    )
    assert claude_response.status_code == 200
    response = client.post(
        "/api/integrations/codex/channels/telegram/toggle",
        json={"enabled": True},
    )
    assert response.status_code == 200
    data = client.get("/api/integrations").get_json()
    assert data["integrations"]["codex"]["channels"]["telegram"] is True
    assert data["integrations"]["claude_code"]["channels"]["telegram"] is False


def test_unknown_platform_and_channel_are_rejected(client):
    assert client.put("/api/integrations/other", json={}).status_code == 404
    assert client.post(
        "/api/integrations/codex/channels/other/toggle", json={"enabled": True}
    ).status_code == 404


def test_legacy_channel_route_targets_claude(client):
    response = client.post("/api/channel/telegram/toggle", json={"enabled": False})
    assert response.status_code == 200
    data = client.get("/api/integrations").get_json()
    assert data["integrations"]["claude_code"]["channels"]["telegram"] is False


def test_malformed_config_returns_conflict_without_overwrite(client, isolated_config_path):
    isolated_config_path.write_text("{broken", encoding="utf-8")
    response = client.get("/api/integrations")
    assert response.status_code == 409
    assert "配置" in response.get_json()["error"]
    assert isolated_config_path.read_text(encoding="utf-8") == "{broken"


def test_malformed_hook_put_does_not_change_config(client, isolated_config_path):
    client.get("/api/integrations")
    before = isolated_config_path.read_bytes()
    hook_manager.CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    hook_manager.CLAUDE_SETTINGS.write_text("{broken", encoding="utf-8")
    response = client.put(
        "/api/integrations/claude_code",
        json={"events": {"Stop": False}},
    )
    assert response.status_code == 409
    assert isolated_config_path.read_bytes() == before
    assert hook_manager.CLAUDE_SETTINGS.read_text(encoding="utf-8") == "{broken"


def test_structurally_malformed_hook_put_does_not_change_config(client, isolated_config_path):
    client.get("/api/integrations")
    before = isolated_config_path.read_bytes()
    hook_manager.CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    hook_manager.CLAUDE_SETTINGS.write_text(json.dumps({"hooks": []}), encoding="utf-8")
    hook_before = hook_manager.CLAUDE_SETTINGS.read_bytes()
    response = client.put(
        "/api/integrations/claude_code",
        json={"events": {"Stop": False}},
    )
    assert response.status_code == 409
    assert isolated_config_path.read_bytes() == before
    assert hook_manager.CLAUDE_SETTINGS.read_bytes() == hook_before


def test_legacy_qq_toggle_requires_target_id(client, isolated_config_path):
    client.get("/api/integrations")
    config = json.loads(isolated_config_path.read_text(encoding="utf-8"))
    config["channels"]["qq"].update({"app_id": "app", "app_secret": "secret"})
    isolated_config_path.write_text(json.dumps(config), encoding="utf-8")
    response = client.post("/api/channel/qq/toggle", json={"enabled": True})
    assert response.status_code == 400
    assert "Target ID" in response.get_json()["error"]


def test_legacy_test_route_uses_canonical_test_service(client, monkeypatch):
    calls = []

    def fake_send_event(event, config):
        calls.append((event.platform, event.event_name))
        return [notification_core.DeliveryResult("telegram", False, "failed")]

    monkeypatch.setattr(notification_core, "send_event", fake_send_event)
    response = client.post("/api/test")
    assert response.status_code == 200
    assert calls == [("claude_code", "Test")]
    assert response.get_json() == {
        "ok": True,
        "results": [{"channel": "telegram", "success": False}],
    }


@pytest.mark.parametrize("payload", [[], "bad", None])
def test_integration_put_requires_object(client, payload):
    response = client.put("/api/integrations/codex", json=payload)
    assert response.status_code == 400


def test_permission_mode_rejects_malformed_settings_without_overwrite(client, monkeypatch, tmp_path):
    path = tmp_path / "settings.json"
    path.write_bytes(b"{broken")
    monkeypatch.setattr(app_module, "CLAUDECODE_SETTINGS", path)
    response = client.put("/api/permission-mode", json={"mode": "acceptEdits"})
    assert response.status_code == 409
    assert path.read_bytes() == b"{broken"


def test_permission_mode_rejects_invalid_structure_without_overwrite(client, monkeypatch, tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"permissions": []}), encoding="utf-8")
    before = path.read_bytes()
    monkeypatch.setattr(app_module, "CLAUDECODE_SETTINGS", path)
    response = client.put("/api/permission-mode", json={"mode": "acceptEdits"})
    assert response.status_code == 409
    assert path.read_bytes() == before


def test_config_get_redacts_all_canonical_credentials(client, isolated_config_path):
    cfg = config_store.load_config(isolated_config_path)
    for channel, values in cfg["channels"].items():
        for key in list(values):
            if key in config_store.CHANNEL_SECRET_FIELDS[channel]:
                values[key] = f"SENTINEL-{channel}-{key}"
    config_store.save_config(cfg, isolated_config_path)
    raw = client.get("/api/config").get_data(as_text=True)
    assert "SENTINEL-" not in raw


@pytest.mark.parametrize("channel", ["weixin", "qq", "telegram", "feishu", "dingtalk"])
def test_config_refresh_then_save_preserves_secrets_and_identifiers(client, isolated_config_path, channel):
    cfg = config_store.load_config(isolated_config_path)
    values = cfg["channels"][channel]
    for key in config_store.CHANNEL_SECRET_FIELDS[channel]:
        values[key] = f"secret-{channel}-{key}"
    for key in config_store.CHANNEL_CREDENTIAL_FIELDS[channel]:
        if key not in config_store.CHANNEL_SECRET_FIELDS[channel]:
            values[key] = f"identifier-{channel}-{key}"
    config_store.save_config(cfg, isolated_config_path)

    response = client.get("/api/config").get_json()[channel]
    assert all(response[key] == "" for key in config_store.CHANNEL_SECRET_FIELDS[channel])
    assert all(response["configured_secrets"][key] for key in config_store.CHANNEL_SECRET_FIELDS[channel])
    client.put("/api/config", json={channel: response})

    saved = config_store.load_config(isolated_config_path)["channels"][channel]
    for key in config_store.CHANNEL_SECRET_FIELDS[channel]:
        assert saved[key] == f"secret-{channel}-{key}"
    for key in config_store.CHANNEL_CREDENTIAL_FIELDS[channel]:
        if key not in config_store.CHANNEL_SECRET_FIELDS[channel]:
            assert saved[key] == f"identifier-{channel}-{key}"


@pytest.mark.parametrize("value", ["false", 0, 1, None])
def test_integration_boolean_fields_require_json_booleans(client, value):
    response = client.put("/api/integrations/codex", json={"enabled": value})
    assert response.status_code == 400


def test_disabled_platform_hook_sync_uninstalls(client):
    hook_manager.sync_hooks("codex", {"Stop"})
    response = client.post("/api/integrations/codex/hooks/sync")
    assert response.status_code == 200
    assert hook_manager.inspect_hooks("codex").configured_events == ()


def test_legacy_claude_install_respects_disabled_platform(client, isolated_config_path):
    cfg = config_store.load_config(isolated_config_path)
    cfg["integrations"]["claude_code"]["enabled"] = False
    config_store.save_config(cfg, isolated_config_path)
    hook_manager.sync_hooks("claude_code", {"Stop"})
    response = client.post("/api/hooks/install")
    assert response.status_code == 200
    assert hook_manager.inspect_hooks("claude_code").configured_events == ()


def test_integration_config_save_failure_restores_exact_hook_bytes(monkeypatch, isolated_config_path):
    cfg = config_store.load_config(isolated_config_path)
    cfg["integrations"]["codex"]["enabled"] = True
    cfg["integrations"]["codex"]["events"]["Stop"] = True
    cfg["integrations"]["codex"]["events"]["PermissionRequest"] = True
    config_store.save_config(cfg, isolated_config_path)
    hook_manager.sync_hooks("codex", {"SessionStart"})
    data = json.loads(hook_manager.CODEX_HOOKS.read_text(encoding="utf-8"))
    data["custom"] = {"spacing": "must survive"}
    hook_manager.CODEX_HOOKS.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    before = hook_manager.CODEX_HOOKS.read_bytes()

    real_save = config_store.save_config
    monkeypatch.setattr(config_store, "save_config", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")))
    application = app_module.create_app()
    application.config.update(TESTING=False)
    with application.test_client() as test_client:
        response = test_client.put("/api/integrations/codex", json={"events": {"Stop": False}})
    monkeypatch.setattr(config_store, "save_config", real_save)

    assert response.status_code == 500
    assert hook_manager.CODEX_HOOKS.read_bytes() == before
