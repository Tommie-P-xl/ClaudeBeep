import copy
import json
import subprocess
import sys

import codex_adapter
import notification_core
from config_store import CODEX_EVENTS, DEFAULT_CONFIG


def _enabled_codex_config():
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["integrations"]["codex"]["enabled"] = True
    return config


def test_stop_payload_maps_to_completion():
    event = codex_adapter.parse_codex_event({
        "session_id": "s1",
        "turn_id": "t1",
        "cwd": "C:/repo",
        "hook_event_name": "Stop",
        "model": "gpt-5",
    })

    assert event.platform == "codex"
    assert event.event_name == "Stop"
    assert event.title == "Codex - 完成"
    assert "C:/repo" in event.message


def test_permission_payload_tells_user_to_return_to_codex():
    event = codex_adapter.parse_codex_event({
        "session_id": "s1",
        "turn_id": "t1",
        "cwd": "C:/repo",
        "hook_event_name": "PermissionRequest",
        "tool_name": "Bash",
        "tool_input": {"command": "git push"},
    })

    assert "Codex" in event.message
    assert "处理" in event.message
    assert "git push" in event.message


def test_unknown_payload_is_ignored():
    assert codex_adapter.parse_codex_event({"hook_event_name": "Unknown"}) is None


def test_supported_events_share_config_store_definition():
    assert codex_adapter.SUPPORTED_EVENTS == frozenset(CODEX_EVENTS)
    assert isinstance(codex_adapter.SUPPORTED_EVENTS, frozenset)


def test_codex_module_does_not_import_claude_interaction_modules():
    script = (
        "import sys; import codex_adapter; "
        "raise SystemExit(1 if {'interaction', 'listener'} & sys.modules.keys() else 0)"
    )

    result = subprocess.run([sys.executable, "-c", script], check=False)

    assert result.returncode == 0


def test_run_codex_hook_delivers_enabled_event(monkeypatch):
    delivered = []
    monkeypatch.setattr(codex_adapter, "send_event", lambda event, config: delivered.append(event))

    result = codex_adapter.run_codex_hook(
        json.dumps({"hook_event_name": "Stop", "cwd": "C:/repo"}),
        _enabled_codex_config(),
    )

    assert result == 0
    assert [event.event_name for event in delivered] == ["Stop"]


def test_run_codex_hook_ignores_disabled_platform(monkeypatch, capsys):
    delivered = []
    monkeypatch.setattr(codex_adapter, "send_event", lambda event, config: delivered.append(event))

    assert codex_adapter.run_codex_hook('{"hook_event_name":"Stop"}', copy.deepcopy(DEFAULT_CONFIG)) == 0
    assert delivered == []
    assert capsys.readouterr().out == ""


def test_run_codex_hook_ignores_disabled_event(monkeypatch, capsys):
    delivered = []
    config = _enabled_codex_config()
    config["integrations"]["codex"]["events"]["Stop"] = False
    monkeypatch.setattr(codex_adapter, "send_event", lambda event, config: delivered.append(event))

    assert codex_adapter.run_codex_hook('{"hook_event_name":"Stop"}', config) == 0
    assert delivered == []
    assert capsys.readouterr().out == ""


def test_run_codex_hook_ignores_unknown_event_without_decision_output(capsys):
    assert codex_adapter.run_codex_hook(
        '{"hook_event_name":"Unknown"}', _enabled_codex_config()
    ) == 0
    assert capsys.readouterr().out == ""


def test_run_codex_hook_malformed_input_has_sanitized_error(capsys):
    secret = "super-secret-token"

    assert codex_adapter.run_codex_hook("{" + secret, _enabled_codex_config()) == 0

    captured = capsys.readouterr()
    assert secret not in captured.err
    assert captured.out == ""


def test_run_codex_hook_swallows_delivery_failure(monkeypatch, capsys):
    def fail_delivery(event, config):
        raise RuntimeError("offline")

    monkeypatch.setattr(codex_adapter, "send_event", fail_delivery)

    result = codex_adapter.run_codex_hook(
        '{"hook_event_name":"Stop"}', _enabled_codex_config()
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out == ""


def test_top_level_codex_failure_is_sanitized_to_durable_log(monkeypatch, tmp_path):
    config = _enabled_codex_config()
    secret = "credential-secret-value"
    config["channels"]["telegram"]["bot_token"] = secret
    log_path = tmp_path / "notify.log"
    monkeypatch.setattr(notification_core, "LOG_FILE", log_path)
    monkeypatch.setattr(codex_adapter, "log_failure", notification_core.log_failure)
    monkeypatch.setattr(codex_adapter, "send_event", lambda event, cfg: (_ for _ in ()).throw(RuntimeError(f"failed {secret}")))
    assert codex_adapter.run_codex_hook('{"hook_event_name":"Stop"}', config) == 0
    logged = log_path.read_text(encoding="utf-8")
    assert secret not in logged
    assert "platform=codex" in logged and "event=Stop" in logged and "channel=unknown" in logged
