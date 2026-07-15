import json
import copy
import sys
import threading
import time

import interaction
import hook_manager
import notify
from config_store import DEFAULT_CONFIG


def test_auto_approved_permission_is_filtered():
    approved, reason = notify._is_auto_approved({
        "hook_event_name": "PermissionRequest",
        "tool_name": "Bash",
        "tool_input": {"command": "git status"},
        "auto_approved": True,
        "permission_mode": "default",
    })
    assert approved is True
    assert reason


def test_permission_context_preserves_command():
    text = notify._extract_context_text({
        "hook_event_name": "PermissionRequest",
        "tool_name": "Bash",
        "tool_input": {"command": "git status"},
    })
    assert "git status" in text


def test_ask_user_question_options_are_preserved():
    result = notify._extract_options({
        "hook_event_name": "PermissionRequest",
        "tool_name": "AskUserQuestion",
        "tool_input": {
            "questions": [{
                "question": "Deploy now?",
                "options": [
                    {"label": "Yes", "description": "Deploy"},
                    {"label": "No", "description": "Wait"},
                ],
                "multiSelect": False,
            }]
        },
    })
    assert result["question"] == "Deploy now?"
    assert result["options"] == ["Yes", "No"]
    assert result["as_elicitation"] is True


def test_elicitation_response_wire_format_is_json():
    output = interaction.format_hook_response(
        "Yes", "Elicitation", "Deploy now?", {}
    )
    payload = json.loads(output)
    hook_output = payload["hookSpecificOutput"]
    assert hook_output["hookEventName"] == "PermissionRequest"
    assert hook_output["decision"]["behavior"] == "allow"
    assert hook_output["decision"]["updatedInput"]["answers"] == {
        "Deploy now?": "Yes"
    }


def test_claude_install_hooks_does_not_touch_codex_hooks(monkeypatch, tmp_path):
    claude_settings = tmp_path / "claude" / "settings.json"
    codex_hooks = tmp_path / "codex" / "hooks.json"
    codex_hooks.parent.mkdir(parents=True)
    codex_hooks.write_bytes(b'{"sentinel":"codex"}')
    before = codex_hooks.read_bytes()
    config = copy.deepcopy(DEFAULT_CONFIG)
    monkeypatch.setattr(hook_manager, "CLAUDE_SETTINGS", claude_settings)
    monkeypatch.setattr(hook_manager, "CODEX_HOOKS", codex_hooks)
    monkeypatch.setattr(notify, "load_config", lambda: config)

    assert notify.install_hooks() is True

    assert codex_hooks.read_bytes() == before
    saved = json.loads(claude_settings.read_text(encoding="utf-8"))
    commands = [
        handler["command"]
        for groups in saved["hooks"].values()
        for group in groups
        for handler in group["hooks"]
    ]
    assert commands
    assert all(
        "--claudebeep-hook" in command and "--platform claude_code" in command
        for command in commands
    )


def _interactive_config():
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["interaction"] = copy.deepcopy(config["integrations"]["claude_code"]["interaction"])
    return config


def _isolate_interaction(monkeypatch, tmp_path):
    monkeypatch.setattr(interaction, "PENDING_DIR", tmp_path / "pending")
    monkeypatch.setattr(interaction, "RESPONSE_DIR", tmp_path / "responses")
    monkeypatch.setattr(interaction, "_LABEL_SEQ_FILE", tmp_path / "label_seq")


def test_real_claude_permission_hook_terminal_reply_emits_exact_json_and_cleans_up(monkeypatch, tmp_path, capsys):
    _isolate_interaction(monkeypatch, tmp_path)
    payload = {"hook_event_name": "PermissionRequest", "tool_name": "Bash", "tool_input": {"command": "git status"}}
    monkeypatch.setattr(notify, "load_config", _interactive_config)
    monkeypatch.setattr(notify, "collect_channels", lambda config: [])
    monkeypatch.setattr(notify, "_read_stdin_utf8", lambda: json.dumps(payload))
    console_input = tmp_path / "console-input.txt"
    console_input.write_text("Yes\n", encoding="utf-8")
    monkeypatch.setattr(interaction, "_get_console_path", lambda: str(console_input))
    monkeypatch.setattr(interaction, "write_to_console", lambda text: None)
    monkeypatch.setattr(sys, "argv", ["notify.py", "--type", "ask", "--from-stdin"])
    notify.main()
    output = json.loads(capsys.readouterr().out.strip())
    assert output == {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}
    assert not list((tmp_path / "pending").glob("*.json"))
    assert len(list((tmp_path / "responses").glob("*.json"))) == 1


def test_real_claude_ask_user_question_remote_reply_uses_elicitation_wire_format(monkeypatch, tmp_path, capsys):
    _isolate_interaction(monkeypatch, tmp_path)
    payload = {"hook_event_name": "PermissionRequest", "tool_name": "AskUserQuestion", "tool_input": {"questions": [{"question": "Deploy now?", "options": [{"label": "Yes"}, {"label": "No"}], "multiSelect": False}]}}
    monkeypatch.setattr(notify, "load_config", _interactive_config)
    monkeypatch.setattr(notify, "collect_channels", lambda config: [])
    monkeypatch.setattr(notify, "_read_stdin_utf8", lambda: json.dumps(payload))
    config = _interactive_config()
    config["interaction"]["show_in_terminal"] = False
    config["integrations"]["claude_code"]["interaction"]["show_in_terminal"] = False
    monkeypatch.setattr(notify, "load_config", lambda: config)
    writes = []
    def remote_reply():
        deadline = time.time() + 3
        while time.time() < deadline:
            pending_files = list((tmp_path / "pending").glob("*.json"))
            if pending_files:
                request_id = json.loads(pending_files[0].read_text(encoding="utf-8"))["id"]
                writes.append(interaction.write_response(request_id, "1", "weixin"))
                writes.append(interaction.write_response(request_id, "2", "telegram"))
                return
            time.sleep(0.01)
        raise AssertionError("pending request was not created")
    writer = threading.Thread(target=remote_reply)
    writer.start()
    monkeypatch.setattr(sys, "argv", ["notify.py", "--type", "ask", "--from-stdin"])
    notify.main()
    writer.join(timeout=3)
    decision = json.loads(capsys.readouterr().out.strip())["hookSpecificOutput"]["decision"]
    assert decision == {"behavior": "allow", "updatedInput": {"questions": payload["tool_input"]["questions"], "answers": {"Deploy now?": "Yes"}}}
    assert writes == [True, False]
    assert not list((tmp_path / "pending").glob("*.json"))


def test_real_claude_interactive_timeout_cleans_pending_and_response(monkeypatch, tmp_path, capsys):
    _isolate_interaction(monkeypatch, tmp_path)
    payload = {"hook_event_name": "PermissionRequest", "tool_name": "Bash", "tool_input": {"command": "git status"}}
    config = _interactive_config()
    config["interaction"]["timeout_seconds"] = 1
    config["integrations"]["claude_code"]["interaction"]["timeout_seconds"] = 1
    monkeypatch.setattr(notify, "load_config", lambda: config)
    monkeypatch.setattr(notify, "collect_channels", lambda config: [])
    monkeypatch.setattr(notify, "_read_stdin_utf8", lambda: json.dumps(payload))
    config["interaction"]["show_in_terminal"] = False
    config["integrations"]["claude_code"]["interaction"]["show_in_terminal"] = False
    monkeypatch.setattr(sys, "argv", ["notify.py", "--type", "ask", "--from-stdin"])
    notify.main()
    assert capsys.readouterr().out == ""
    assert not list((tmp_path / "pending").glob("*.json"))
    assert not list((tmp_path / "responses").glob("*.json"))


def test_first_interaction_reply_wins(monkeypatch, tmp_path):
    _isolate_interaction(monkeypatch, tmp_path)
    assert interaction.write_response("request", "yes", "terminal") is True
    assert interaction.write_response("request", "no", "weixin") is False
    assert interaction.read_response("request")["reply"] == "yes"
