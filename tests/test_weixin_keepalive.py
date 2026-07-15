import copy
import json

import config_store
from channels import weixin


def _canonical_weixin_config(legacy_config):
    config = config_store.migrate_config(copy.deepcopy(legacy_config))
    config["channels"]["weixin"]["bot_token"] = "token"
    config["channels"]["weixin"]["to_user_id"] = "user"
    return config


def test_codex_only_policy_runs_one_keepalive_iteration(
    monkeypatch, tmp_path, legacy_config
):
    config = _canonical_weixin_config(legacy_config)
    config["integrations"]["claude_code"]["enabled"] = False
    config["integrations"]["codex"]["enabled"] = True
    config["integrations"]["codex"]["channels"]["weixin"] = True
    config_store.save_config(config, tmp_path / "config.json")
    monkeypatch.setattr(weixin, "SCRIPT_DIR", tmp_path)
    queue_calls = []
    monkeypatch.setattr(weixin, "_process_send_queue", lambda sender: queue_calls.append(sender))
    monkeypatch.setattr(weixin.time, "sleep", lambda seconds: weixin._keepalive_stop.set())

    class Response:
        def read(self):
            weixin._keepalive_stop.set()
            return json.dumps({"ret": 0, "get_updates_buf": "next"}).encode()

    monkeypatch.setattr(weixin.urllib.request, "urlopen", lambda request, timeout: Response())
    weixin._keepalive_stop.clear()
    try:
        weixin._keepalive_loop()
    finally:
        weixin._keepalive_stop.clear()

    assert len(queue_calls) == 1
    saved = config_store.load_config(tmp_path / "config.json")
    assert saved["channels"]["weixin"]["sync_buf"] == "next"


def test_disabled_platforms_stop_without_polling(monkeypatch, tmp_path, legacy_config):
    config = _canonical_weixin_config(legacy_config)
    config["integrations"]["claude_code"]["enabled"] = False
    config["integrations"]["codex"]["enabled"] = False
    config_store.save_config(config, tmp_path / "config.json")
    monkeypatch.setattr(weixin, "SCRIPT_DIR", tmp_path)
    monkeypatch.setattr(
        weixin, "_process_send_queue", lambda sender: (_ for _ in ()).throw(AssertionError("polled"))
    )
    monkeypatch.setattr(weixin.time, "sleep", lambda seconds: weixin._keepalive_stop.set())

    weixin._keepalive_stop.clear()
    weixin._keepalive_loop()

    assert weixin.get_keepalive_status()["running"] is False


def test_legacy_session_field_helper_updates_canonical_config(
    monkeypatch, tmp_path, legacy_config
):
    config_store.save_config(config_store.migrate_config(legacy_config), tmp_path / "config.json")
    monkeypatch.setattr(weixin, "SCRIPT_DIR", tmp_path)

    weixin._update_config_field("context_token", "fresh-context")

    saved = config_store.load_config(tmp_path / "config.json")
    assert saved["channels"]["weixin"]["context_token"] == "fresh-context"


def test_session_timeout_disables_both_platform_selections(
    monkeypatch, tmp_path, legacy_config
):
    config = _canonical_weixin_config(legacy_config)
    for platform in config_store.PLATFORMS:
        config["integrations"][platform]["enabled"] = True
        config["integrations"][platform]["channels"]["weixin"] = True
    config["channels"]["weixin"]["context_token"] = "expired"
    config_store.save_config(config, tmp_path / "config.json")
    monkeypatch.setattr(weixin, "SCRIPT_DIR", tmp_path)

    weixin._mark_session_timeout()

    saved = config_store.load_config(tmp_path / "config.json")
    assert saved["channels"]["weixin"]["context_token"] == ""
    assert saved["channels"]["weixin"]["session_expired"] is True
    assert all(
        not saved["integrations"][platform]["channels"]["weixin"]
        for platform in config_store.PLATFORMS
    )


def test_codex_only_inbound_text_does_not_import_claude_interaction(monkeypatch, legacy_config):
    import builtins
    config = config_store.migrate_config(legacy_config)
    config["integrations"]["claude_code"]["enabled"] = False
    config["integrations"]["claude_code"]["channels"]["weixin"] = False
    config["integrations"]["codex"]["enabled"] = True
    config["integrations"]["codex"]["channels"]["weixin"] = True
    monkeypatch.setattr(weixin, "_load_config_file", lambda: config)
    real_import = builtins.__import__
    def blocked(name, *args, **kwargs):
        if name in {"interaction", "listener"}:
            raise AssertionError(f"unexpected import: {name}")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", blocked)
    weixin._dispatch_interaction_reply("#1 yes")
