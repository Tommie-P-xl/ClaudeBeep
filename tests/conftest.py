import copy
import json
from pathlib import Path

import pytest


@pytest.fixture
def legacy_config() -> dict:
    return {
        "app": {"version": "1.1.0", "auto_cleanup": True},
        "windows_toast": {"enabled": True, "duration_ms": 5000},
        "telegram": {
            "enabled": True,
            "bot_token": "test-token",
            "chat_id": "42",
        },
        "weixin": {"enabled": False, "bot_token": "", "to_user_id": ""},
        "qq": {"enabled": False, "app_id": "", "app_secret": "", "target_id": ""},
        "feishu": {"enabled": False, "app_id": "", "app_secret": "", "receive_id": ""},
        "dingtalk": {"enabled": False, "client_id": "", "client_secret": "", "user_id": ""},
        "interaction": {"enabled": True, "timeout_seconds": 0, "show_in_terminal": True},
        "future_field": {"preserve": True},
    }


@pytest.fixture
def config_file(tmp_path: Path, legacy_config: dict) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(copy.deepcopy(legacy_config)), encoding="utf-8")
    return path


@pytest.fixture
def claude_settings_path(tmp_path: Path) -> Path:
    return tmp_path / ".claude" / "settings.json"


@pytest.fixture
def codex_hooks_path(tmp_path: Path) -> Path:
    return tmp_path / ".codex" / "hooks.json"
