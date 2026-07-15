import copy
import json

import pytest

import config_store


def test_legacy_config_migrates_to_peer_integrations(legacy_config):
    migrated = config_store.migrate_config(copy.deepcopy(legacy_config))
    assert migrated["integrations"]["claude_code"]["channels"]["telegram"] is True
    assert migrated["integrations"]["codex"]["enabled"] is False
    assert migrated["channels"]["telegram"]["bot_token"] == "test-token"
    assert migrated["future_field"] == {"preserve": True}


def test_platform_channel_switches_are_independent(legacy_config):
    config = config_store.migrate_config(copy.deepcopy(legacy_config))
    config_store.set_channel_enabled(config, "codex", "telegram", False)
    assert config["integrations"]["claude_code"]["channels"]["telegram"] is True
    assert config["integrations"]["codex"]["channels"]["telegram"] is False


def test_runtime_config_combines_shared_credentials_and_platform_switch(legacy_config):
    config = config_store.migrate_config(copy.deepcopy(legacy_config))
    config_store.set_channel_enabled(config, "codex", "telegram", True)
    runtime = config_store.runtime_channel_config(config, "codex")
    assert runtime["telegram"]["enabled"] is True
    assert runtime["telegram"]["bot_token"] == "test-token"


def test_malformed_json_is_never_overwritten(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(config_store.ConfigFileError):
        config_store.load_config(path)
    assert path.read_text(encoding="utf-8") == "{broken"


def test_missing_config_is_created_atomically(tmp_path):
    path = tmp_path / "config.json"
    config = config_store.load_config(path)
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["app"]["version"] == "1.5.0"
    assert config["integrations"]["codex"]["enabled"] is False


@pytest.mark.parametrize("claude,codex,expected", [
    (False, False, False),
    (True, False, True),
    (False, True, True),
    (True, True, True),
])
def test_weixin_keepalive_uses_either_platform(legacy_config, claude, codex, expected):
    config = config_store.migrate_config(copy.deepcopy(legacy_config))
    config["channels"]["weixin"].update({"bot_token": "token", "to_user_id": "user"})
    config_store.set_channel_enabled(config, "claude_code", "weixin", claude)
    config_store.set_channel_enabled(config, "codex", "weixin", codex)
    config["integrations"]["claude_code"]["enabled"] = claude
    config["integrations"]["codex"]["enabled"] = codex
    assert config_store.should_run_weixin_keepalive(config) is expected


def test_weixin_keepalive_requires_enabled_integration(legacy_config):
    config = config_store.migrate_config(copy.deepcopy(legacy_config))
    config["channels"]["weixin"]["bot_token"] = "token"
    config_store.set_channel_enabled(config, "claude_code", "weixin", True)
    config_store.set_channel_enabled(config, "codex", "weixin", True)
    config["integrations"]["claude_code"]["enabled"] = False
    config["integrations"]["codex"]["enabled"] = False
    assert config_store.should_run_weixin_keepalive(config) is False
    config["integrations"]["codex"]["enabled"] = True
    assert config_store.should_run_weixin_keepalive(config) is True


def test_save_preserves_canonical_values(config_file):
    config = config_store.load_config(config_file)
    config["integrations"]["claude_code"]["channels"]["telegram"] = False
    config["channels"]["telegram"]["bot_token"] = "canonical-token"
    config_store.save_config(config, config_file)
    saved = json.loads(config_file.read_text(encoding="utf-8"))
    assert saved["channels"]["telegram"]["bot_token"] == "canonical-token"
    assert saved["integrations"]["claude_code"]["channels"]["telegram"] is False


def test_save_refreshes_legacy_mirrors(config_file):
    config = config_store.load_config(config_file)
    config_store.set_channel_enabled(config, "claude_code", "telegram", False)
    config_store.save_config(config, config_file)
    saved = json.loads(config_file.read_text(encoding="utf-8"))
    assert saved["telegram"]["enabled"] is False
    assert saved["interaction"] == saved["integrations"]["claude_code"]["interaction"]


def test_load_returns_plain_dict(config_file):
    config = config_store.load_config(config_file)
    assert type(config) is dict
