import json
from pathlib import Path

import pytest

import hook_manager


@pytest.fixture
def codex_hooks_path(tmp_path):
    return tmp_path / "codex" / "hooks.json"


@pytest.fixture
def claude_settings_path(tmp_path):
    return tmp_path / "claude" / "settings.json"


def test_codex_sync_preserves_third_party_hook(codex_hooks_path):
    codex_hooks_path.parent.mkdir(parents=True)
    codex_hooks_path.write_text(json.dumps({
        "future": {"preserve": True},
        "hooks": {"Stop": [{
            "hooks": [{"type": "command", "command": "third-party.exe"}]
        }]},
    }), encoding="utf-8")
    status = hook_manager.sync_hooks("codex", {"Stop"}, codex_hooks_path)
    saved = json.loads(codex_hooks_path.read_text(encoding="utf-8"))
    commands = [h["command"] for group in saved["hooks"]["Stop"] for h in group["hooks"]]
    assert "third-party.exe" in commands
    assert any("--platform codex" in command for command in commands)
    assert saved["future"] == {"preserve": True}
    assert status.configured_events == ("Stop",)


def test_codex_uninstall_does_not_change_claude_file(codex_hooks_path, claude_settings_path):
    hook_manager.sync_hooks("codex", {"Stop"}, codex_hooks_path)
    claude_settings_path.parent.mkdir(parents=True)
    claude_settings_path.write_text('{"hooks":{"Stop":[]}}', encoding="utf-8")
    before = claude_settings_path.read_bytes()
    hook_manager.uninstall_hooks("codex", codex_hooks_path)
    assert claude_settings_path.read_bytes() == before


def test_claude_sync_does_not_change_codex_file(codex_hooks_path, claude_settings_path):
    codex_hooks_path.parent.mkdir(parents=True)
    codex_hooks_path.write_text('{"hooks":{"Stop":[]}}', encoding="utf-8")
    before = codex_hooks_path.read_bytes()

    hook_manager.sync_hooks("claude_code", {"Stop"}, claude_settings_path)

    assert codex_hooks_path.read_bytes() == before


def test_default_hook_paths_are_isolated_between_platforms(
    monkeypatch, codex_hooks_path, claude_settings_path
):
    monkeypatch.setattr(hook_manager, "CODEX_HOOKS", codex_hooks_path)
    monkeypatch.setattr(hook_manager, "CLAUDE_SETTINGS", claude_settings_path)
    codex_hooks_path.parent.mkdir(parents=True)
    codex_hooks_path.write_text('{"sentinel":"codex"}', encoding="utf-8")
    codex_before = codex_hooks_path.read_bytes()

    hook_manager.sync_hooks("claude_code", {"Stop"})

    assert codex_hooks_path.read_bytes() == codex_before
    hook_manager.sync_hooks("codex", {"Stop"})
    claude_before_uninstall = claude_settings_path.read_bytes()

    hook_manager.uninstall_hooks("codex")

    assert claude_settings_path.read_bytes() == claude_before_uninstall


def test_claude_sync_replaces_only_known_legacy_claudebeep_entry(claude_settings_path):
    claude_settings_path.parent.mkdir(parents=True)
    claude_settings_path.write_text(json.dumps({"hooks": {
        "Stop": [
            {"hooks": [{"type": "command", "command": '"C:/ClaudeBeep/notify_hook.bat" --type stop --from-stdin'}]},
            {"hooks": [{"type": "command", "command": "notify-company.exe"}]},
        ]
    }}), encoding="utf-8")
    hook_manager.sync_hooks("claude_code", {"Stop"}, claude_settings_path)
    saved = json.loads(claude_settings_path.read_text(encoding="utf-8"))
    commands = [h["command"] for group in saved["hooks"]["Stop"] for h in group["hooks"]]
    assert "notify-company.exe" in commands
    assert sum("--platform claude_code" in command for command in commands) == 1


def test_malformed_hook_file_is_unchanged(codex_hooks_path):
    codex_hooks_path.parent.mkdir(parents=True)
    codex_hooks_path.write_text("{broken", encoding="utf-8")
    with pytest.raises(hook_manager.HookFileError):
        hook_manager.sync_hooks("codex", {"Stop"}, codex_hooks_path)
    assert codex_hooks_path.read_text(encoding="utf-8") == "{broken"


def test_build_hook_command_rejects_unknown_event():
    with pytest.raises(ValueError):
        hook_manager.build_hook_command("codex", "Unknown")
    with pytest.raises(ValueError):
        hook_manager.build_hook_command("claude_code", "Unknown")


def test_inspect_hooks_ignores_malformed_entries(codex_hooks_path):
    codex_hooks_path.parent.mkdir(parents=True)
    codex_hooks_path.write_text(json.dumps({"hooks": {
        "Stop": [None, {"hooks": None}, {"hooks": [None, {"command": None}, {"command": "third-party"}]}]
    }}), encoding="utf-8")
    status = hook_manager.inspect_hooks("codex", codex_hooks_path)
    assert status.configured_events == ()


def test_inspect_hooks_rejects_non_object_hooks(codex_hooks_path):
    codex_hooks_path.parent.mkdir(parents=True)
    codex_hooks_path.write_text(json.dumps({"hooks": []}), encoding="utf-8")
    with pytest.raises(hook_manager.HookFileError):
        hook_manager.inspect_hooks("codex", codex_hooks_path)


def test_uninstall_reports_only_owned_remaining_events(codex_hooks_path):
    codex_hooks_path.parent.mkdir(parents=True)
    hook_manager.sync_hooks("codex", {"Stop", "PermissionRequest"}, codex_hooks_path)
    data = json.loads(codex_hooks_path.read_text(encoding="utf-8"))
    data["hooks"]["PermissionRequest"].append({"hooks": [{"type": "command", "command": "third-party"}]})
    codex_hooks_path.write_text(json.dumps(data), encoding="utf-8")
    status = hook_manager.uninstall_hooks("codex", codex_hooks_path)
    assert status.configured_events == ()


def test_owned_markers_on_other_entry_path_are_preserved(codex_hooks_path):
    codex_hooks_path.parent.mkdir(parents=True)
    command = '"C:/ThirdParty/notify.py" --claudebeep-hook --platform codex --from-stdin'
    codex_hooks_path.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": command}]}]}}), encoding="utf-8")
    hook_manager.uninstall_hooks("codex", codex_hooks_path)
    assert json.loads(codex_hooks_path.read_text(encoding="utf-8"))["hooks"]["Stop"][0]["hooks"][0]["command"] == command


@pytest.mark.parametrize("platform,event", [("claude_code", "Stop"), ("codex", "Stop")])
def test_generated_commands_are_owned_and_sync_is_idempotent(platform, event, tmp_path):
    path = tmp_path / f"{platform}.json"
    command = hook_manager.build_hook_command(platform, event)["command"]
    assert hook_manager._is_owned(command, platform)
    hook_manager.sync_hooks(platform, {event}, path)
    hook_manager.sync_hooks(platform, {event}, path)
    data = json.loads(path.read_text(encoding="utf-8"))
    owned = [h for group in data["hooks"][event] for h in group["hooks"] if hook_manager._is_owned(h["command"], platform)]
    assert len(owned) == 1
    hook_manager.uninstall_hooks(platform, path)
    assert hook_manager.inspect_hooks(platform, path).configured_events == ()


def test_source_and_frozen_entry_variants_are_owned(monkeypatch):
    root = Path(hook_manager.__file__).resolve().parent
    marker = "--claudebeep-hook --platform codex --from-stdin"
    source = f'"C:/Python/python.exe" "{root / "notify.py"}" {marker}'
    frozen = f'"{root / "ClaudeBeep.exe"}" {marker}'
    assert hook_manager._is_owned(source, "codex")
    assert hook_manager._is_owned(frozen, "codex")


def test_legacy_hook_at_third_party_path_is_preserved(tmp_path):
    path = tmp_path / "settings.json"
    command = '"C:/ThirdParty/notify_hook.bat" --type stop --from-stdin'
    path.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": command}]}]}}), encoding="utf-8")
    hook_manager.uninstall_hooks("claude_code", path)
    assert json.loads(path.read_text(encoding="utf-8"))["hooks"]["Stop"][0]["hooks"][0]["command"] == command


def test_codex_hook_command_includes_pythonutf8_env():
    cmd = hook_manager.build_hook_command("codex", "Stop")
    assert cmd["env"] == {"PYTHONUTF8": "1"}


def test_restore_snapshot_recreates_exact_bytes_and_missing_state(tmp_path):
    path = tmp_path / "hooks.json"
    original = b'{"hooks":{},"format":"exact"}'
    path.write_bytes(original)
    present = hook_manager.snapshot_hooks("codex", path)
    path.write_text('{"changed":true}\n', encoding="utf-8")
    hook_manager.restore_hooks(present)
    assert path.read_bytes() == original

    path.unlink()
    missing = hook_manager.snapshot_hooks("codex", path)
    path.write_text('{"created":true}', encoding="utf-8")
    hook_manager.restore_hooks(missing)
    assert not path.exists()
