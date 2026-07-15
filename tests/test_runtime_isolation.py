import copy
import json
import os
from pathlib import Path
import subprocess
import sys

from config_store import DEFAULT_CONFIG


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_notify(args, payload="", env=None):
    return subprocess.run(
        [sys.executable, "notify.py", *args],
        input=payload,
        text=True,
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=env or os.environ.copy(),
        timeout=10,
        check=False,
    )


def _isolated_env(home):
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    return env


def test_codex_unknown_event_exits_cleanly_without_hook_output(tmp_path):
    result = run_notify(
        ["--platform", "codex", "--claudebeep-hook", "--from-stdin"],
        json.dumps({"hook_event_name": "Unknown", "session_id": "s1"}),
        env=_isolated_env(tmp_path),
    )

    assert result.returncode == 0
    assert result.stdout == ""


def test_codex_disabled_event_exits_cleanly_without_hook_output(tmp_path):
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["integrations"]["codex"]["enabled"] = True
    config["integrations"]["codex"]["events"]["Stop"] = False
    code = (
        "import json, sys, codex_adapter; "
        "raise SystemExit(codex_adapter.run_codex_hook(sys.stdin.read(), "
        "json.loads(sys.argv[1])))"
    )

    result = subprocess.run(
        [sys.executable, "-c", code, json.dumps(config)],
        input=json.dumps({"hook_event_name": "Stop", "session_id": "s1"}),
        text=True,
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=_isolated_env(tmp_path),
        timeout=10,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == ""


def test_importing_codex_adapter_does_not_import_interaction_or_listener():
    code = (
        "import sys, codex_adapter; "
        "assert 'interaction' not in sys.modules; "
        "assert 'listener' not in sys.modules"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_collect_channels_does_not_import_unselected_implementations():
    code = r'''import copy, sys
import config_store, notification_core
cfg = copy.deepcopy(config_store.DEFAULT_CONFIG)
cfg["integrations"]["claude_code"]["channels"] = {name: name == "windows_toast" for name in config_store.CHANNEL_NAMES}
notification_core.collect_channels(cfg, "claude_code")
assert "channels.telegram" not in sys.modules
assert "channels.weixin" not in sys.modules
assert "channels.qq" not in sys.modules
assert "channels.feishu" not in sys.modules
assert "channels.dingtalk" not in sys.modules
'''
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def _snapshot_files(directory):
    if not directory.exists():
        return {}
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file()
    }


def test_codex_permission_blocks_claude_imports_and_creates_no_interaction_files(tmp_path):
    pending_dir = PROJECT_ROOT / "pending"
    responses_dir = PROJECT_ROOT / "responses"
    before_pending = _snapshot_files(pending_dir)
    before_responses = _snapshot_files(responses_dir)
    delivery_record = tmp_path / "deliveries.json"
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["integrations"]["codex"]["enabled"] = True
    config["integrations"]["codex"]["events"]["PermissionRequest"] = True
    for channel_name in config["integrations"]["codex"]["channels"]:
        config["integrations"]["codex"]["channels"][channel_name] = (
            channel_name == "windows_toast"
        )
    code = """
import importlib.abc
import json
import sys
from pathlib import Path

blocked = []

class ClaudeImportBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {"interaction", "listener"}:
            blocked.append(fullname)
            raise AssertionError(f"Codex imported Claude runtime module: {fullname}")
        return None

sys.meta_path.insert(0, ClaudeImportBlocker())
import codex_adapter
import notification_core

delivery_record = Path(sys.argv[2])

class RecordingWindowsChannel:
    name = "windows_toast"

    def __init__(self, config):
        self.config = config

    def is_enabled(self):
        return self.config["windows_toast"]["enabled"]

    def send(self, title, message):
        deliveries = json.loads(delivery_record.read_text(encoding="utf-8"))
        deliveries.append({"title": title, "message": message})
        delivery_record.write_text(json.dumps(deliveries), encoding="utf-8")
        return True

notification_core._default_factories = lambda: {
    "windows_toast": RecordingWindowsChannel,
}
result = codex_adapter.run_codex_hook(sys.stdin.read(), json.loads(sys.argv[1]))
assert blocked == []
raise SystemExit(result)
"""
    payload = json.dumps({
        "hook_event_name": "PermissionRequest",
        "tool_name": "Bash",
        "tool_input": {"command": "git push"},
    })

    delivery_record.write_text("[]", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-c", code, json.dumps(config), str(delivery_record)],
        input=payload,
        text=True,
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=_isolated_env(tmp_path),
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    deliveries = json.loads(delivery_record.read_text(encoding="utf-8"))
    assert len(deliveries) == 1
    assert deliveries[0]["title"] == "Codex - 需要处理"
    assert _snapshot_files(pending_dir) == before_pending
    assert _snapshot_files(responses_dir) == before_responses


def test_release_version_is_consistent():
    assert '"version": "1.5.0"' in Path("config_store.py").read_text(encoding="utf-8")
    assert 'APP_VERSION = "1.5.0"' in Path("tray.py").read_text(encoding="utf-8")
    assert '#define MyAppVersion "1.5.0"' in Path("installer.iss").read_text(encoding="utf-8")
    assert 'assemblyIdentity version="1.5.0.0"' in Path("ClaudeBeep.manifest").read_text(encoding="utf-8")
    assert "# ClaudeBeep v1.5.0" in Path("README.md").read_text(encoding="utf-8")
    assert "# ClaudeBeep v1.5.0" in Path("README_CN.md").read_text(encoding="utf-8")


def test_windows_build_embeds_release_version_resource():
    build_script = Path("build.ps1").read_text(encoding="utf-8")
    version_path = Path("version_info.txt")

    assert '--version-file version_info.txt' in build_script
    assert version_path.is_file()
    version_resource = version_path.read_text(encoding="utf-8")
    assert "filevers=(1, 5, 0, 0)" in version_resource
    assert "prodvers=(1, 5, 0, 0)" in version_resource
    assert "FileVersion', '1.5.0.0" in version_resource
    assert "ProductVersion', '1.5.0.0" in version_resource
    assert "ProductName', 'ClaudeBeep" in version_resource
    assert "FileDescription', 'ClaudeBeep" in version_resource
