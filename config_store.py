from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from common.paths import RUNTIME_DIR, SCRIPT_DIR as _PROGRAM_DIR
from version import APP_VERSION, GITHUB_OWNER, GITHUB_REPO

# ── platform-specific file locking ──────────────────────────────────────────
if sys.platform == "win32":
    import msvcrt

    def _lock_file(f) -> None:  # type: ignore[no-untyped-def]
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)

    def _unlock_file(f) -> None:  # type: ignore[no-untyped-def]
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
else:
    import fcntl

    def _lock_file(f) -> None:  # type: ignore[no-untyped-def]
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)

    def _unlock_file(f) -> None:  # type: ignore[no-untyped-def]
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


# ── load_config mtime cache ─────────────────────────────────────────────────
_config_cache: dict | None = None
_config_mtime: float = 0.0
_config_path_cached: Path | None = None


CONFIG_FILE = RUNTIME_DIR / "config.json"


def _migrate_legacy_runtime_files() -> None:
    """frozen 模式：把旧位置（程序目录）的 config.json 复制到 %APPDATA%\\ClaudeBeep。

    仅在新位置不存在且旧位置存在时执行一次，旧文件保留（不删除）。
    """
    if not getattr(sys, "frozen", False):
        return
    legacy = _PROGRAM_DIR / "config.json"
    if legacy.exists() and not CONFIG_FILE.exists():
        try:
            RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legacy, CONFIG_FILE)
        except Exception:
            pass


PLATFORMS = ("claude_code", "codex")
CHANNEL_NAMES = ("windows_toast", "weixin", "qq", "telegram", "feishu", "dingtalk")
CLAUDE_EVENTS = ("Stop", "Elicitation", "PermissionRequest")
CODEX_EVENTS = (
    "Stop", "PermissionRequest", "SessionStart", "SubagentStart",
    "SubagentStop", "PreCompact", "PostCompact", "PreToolUse",
    "PostToolUse", "UserPromptSubmit",
)


class ConfigFileError(RuntimeError):
    pass


CHANNEL_CREDENTIAL_FIELDS = {
    "windows_toast": (),
    "weixin": ("bot_token", "to_user_id"),
    "qq": ("app_id", "app_secret", "target_id"),
    "telegram": ("bot_token", "chat_id"),
    "feishu": ("app_id", "app_secret", "receive_id"),
    "dingtalk": ("client_id", "client_secret", "user_id"),
}
CHANNEL_SECRET_FIELDS = {
    "windows_toast": (),
    "weixin": ("bot_token", "context_token", "sync_buf"),
    "qq": ("app_secret",),
    "telegram": ("bot_token",),
    "feishu": ("app_secret",),
    "dingtalk": ("client_secret",),
}


DEFAULT_CONFIG = {
    "app": {
        "version": APP_VERSION,
        "auto_start": False,
        "auto_cleanup": True,
        "cleanup_interval_hours": 12,
        "update_repo": f"{GITHUB_OWNER}/{GITHUB_REPO}",
    },
    "channels": {
        "windows_toast": {"duration_ms": 5000, "sound": "reminder"},
        "weixin": {
            "bot_token": "",
            "baseurl": "https://ilinkai.weixin.qq.com",
            "ilink_bot_id": "",
            "ilink_user_id": "",
            "to_user_id": "",
            "context_token": "",
            "sync_buf": "",
            "session_expired": False,
        },
        "qq": {"app_id": "", "app_secret": "", "target_id": ""},
        "telegram": {"bot_token": "", "chat_id": ""},
        "feishu": {"app_id": "", "app_secret": "", "receive_id": ""},
        "dingtalk": {"client_id": "", "client_secret": "", "user_id": ""},
    },
    "integrations": {
        "claude_code": {
            "enabled": True,
            "events": {name: True for name in CLAUDE_EVENTS},
            "channels": {
                "windows_toast": True,
                "weixin": False,
                "qq": False,
                "telegram": False,
                "feishu": False,
                "dingtalk": False,
            },
            "interaction": {
                "enabled": True,
                "timeout_seconds": 0,
                "show_in_terminal": True,
            },
        },
        "codex": {
            "enabled": False,
            "events": {
                "Stop": True,
                "PermissionRequest": True,
                **{name: False for name in CODEX_EVENTS[2:]},
            },
            "channels": {
                "windows_toast": True,
                "weixin": False,
                "qq": False,
                "telegram": False,
                "feishu": False,
                "dingtalk": False,
            },
        },
    },
}


def _deep_fill(target: dict, defaults: dict) -> None:
    for key, default in defaults.items():
        if key not in target:
            target[key] = copy.deepcopy(default)
        elif isinstance(default, dict) and isinstance(target[key], dict):
            _deep_fill(target[key], default)


def migrate_config(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ConfigFileError("Configuration root must be a JSON object")

    result = copy.deepcopy(raw)
    canonical_channels = result.get("channels")
    if not isinstance(canonical_channels, dict):
        canonical_channels = {}
        result["channels"] = canonical_channels

    integrations = result.get("integrations")
    if not isinstance(integrations, dict):
        integrations = {}
        result["integrations"] = integrations
    claude = integrations.get("claude_code")
    if not isinstance(claude, dict):
        claude = {}
        integrations["claude_code"] = claude
    claude_channels = claude.get("channels")
    if not isinstance(claude_channels, dict):
        claude_channels = {}
        claude["channels"] = claude_channels

    for name in CHANNEL_NAMES:
        legacy = result.get(name)
        if name not in canonical_channels and isinstance(legacy, dict):
            canonical_channels[name] = {
                key: copy.deepcopy(value)
                for key, value in legacy.items()
                if key != "enabled"
            }
        if name not in claude_channels and isinstance(legacy, dict) and "enabled" in legacy:
            claude_channels[name] = bool(legacy["enabled"])

    if "interaction" not in claude and isinstance(result.get("interaction"), dict):
        claude["interaction"] = copy.deepcopy(result["interaction"])

    _deep_fill(result, DEFAULT_CONFIG)
    return result


def get_integration(config: dict, platform: str) -> dict:
    if platform not in PLATFORMS:
        raise ValueError(f"Unsupported platform: {platform}")
    return config["integrations"][platform]


def set_channel_enabled(
    config: dict, platform: str, channel: str, enabled: bool
) -> None:
    if channel not in CHANNEL_NAMES:
        raise ValueError(f"Unsupported channel: {channel}")
    get_integration(config, platform)["channels"][channel] = bool(enabled)


def runtime_channel_config(config: dict, platform: str) -> dict:
    # Skip redundant migration if config already has canonical structure
    # (i.e. it came from load_config or was already migrated)
    if isinstance(config.get("integrations"), dict) and isinstance(
        config.get("channels"), dict
    ):
        migrated = config
    else:
        migrated = migrate_config(config)
    result = copy.deepcopy(migrated)
    selected = get_integration(migrated, platform)["channels"]
    for name in CHANNEL_NAMES:
        result[name] = result["channels"][name]
        result[name]["enabled"] = bool(selected.get(name, False))
    return result


def is_channel_configured(config: dict, channel: str) -> bool:
    """Return the single effective credential predicate used by API and tray."""
    if channel not in CHANNEL_NAMES:
        raise ValueError(f"Unsupported channel: {channel}")
    # Use already-migrated config if available, avoiding redundant deepcopy
    if isinstance(config.get("integrations"), dict) and isinstance(
        config.get("channels"), dict
    ):
        migrated = config
    else:
        migrated = migrate_config(config)
    credentials = migrated["channels"].get(channel, {})
    return all(bool(credentials.get(field)) for field in CHANNEL_CREDENTIAL_FIELDS[channel])


def should_run_weixin_keepalive(config: dict) -> bool:
    # Use already-migrated config if available, avoiding redundant deepcopy
    if isinstance(config.get("integrations"), dict) and isinstance(
        config.get("channels"), dict
    ):
        migrated = config
    else:
        migrated = migrate_config(config)
    credentials = migrated["channels"]["weixin"]
    # Preserve legacy behavior: login keepalive starts as soon as a bot token exists.
    configured = bool(credentials.get("bot_token"))
    selected = any(
        get_integration(migrated, platform)["enabled"]
        and get_integration(migrated, platform)["channels"].get("weixin", False)
        for platform in PLATFORMS
    )
    return configured and selected


def _refresh_legacy_mirrors(config: dict) -> dict:
    result = copy.deepcopy(config)
    claude = result["integrations"]["claude_code"]
    for name in CHANNEL_NAMES:
        shared = copy.deepcopy(result["channels"].get(name, {}))
        shared["enabled"] = bool(claude["channels"].get(name, False))
        result[name] = shared
    result["interaction"] = copy.deepcopy(claude["interaction"])
    return result


def _atomic_write_json_unlocked(path: Path, data: dict) -> None:
    """原子写 JSON（不加锁）。调用方必须已持有对应锁文件，或确保无并发写。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.parent / f".{path.name}.lock"
    lock_path.touch(exist_ok=True)
    with lock_path.open("r+") as lock_f:
        _lock_file(lock_f)
        try:
            _atomic_write_json_unlocked(path, data)
        finally:
            _unlock_file(lock_f)


def load_config(path: Path | None = None) -> dict:
    global _config_cache, _config_mtime, _config_path_cached

    config_path = Path(path) if path is not None else CONFIG_FILE

    # Return cached copy if file unchanged (mtime-based)
    if (
        _config_cache is not None
        and _config_path_cached == config_path
        and config_path.exists()
    ):
        try:
            current_mtime = config_path.stat().st_mtime
        except OSError:
            current_mtime = 0.0
        if current_mtime == _config_mtime:
            return copy.deepcopy(_config_cache)

    # frozen 模式下首次启动把旧位置配置迁移到 %APPDATA%\ClaudeBeep
    # （仅在缓存未命中后执行，避免每次 load 都多付两次 stat）
    if path is None:
        _migrate_legacy_runtime_files()

    if not config_path.exists():
        config = copy.deepcopy(DEFAULT_CONFIG)
        save_config(config, config_path)
        # save_config already updates cache
        return copy.deepcopy(_config_cache) if _config_cache is not None else _refresh_legacy_mirrors(config)

    try:
        with config_path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (json.JSONDecodeError, OSError) as exc:
        raise ConfigFileError(f"Unable to read configuration: {config_path}") from exc

    result = _refresh_legacy_mirrors(migrate_config(raw))

    # Update cache
    try:
        _config_mtime = config_path.stat().st_mtime
    except OSError:
        _config_mtime = 0.0
    _config_cache = result
    _config_path_cached = config_path

    return copy.deepcopy(result)


def save_config(config: dict, path: Path | None = None) -> None:
    global _config_cache, _config_mtime, _config_path_cached

    config_path = Path(path) if path is not None else CONFIG_FILE
    migrated = migrate_config(config)
    persisted = _refresh_legacy_mirrors(migrated)
    atomic_write_json(config_path, persisted)

    # Update cache to reflect newly written data
    try:
        _config_mtime = config_path.stat().st_mtime
    except OSError:
        _config_mtime = 0.0
    _config_cache = persisted
    _config_path_cached = config_path


def _read_config_no_cache(config_path: Path) -> dict:
    """绕过 mtime 缓存直接从磁盘读取并迁移配置（供带锁事务使用）。"""
    if not config_path.exists():
        return _refresh_legacy_mirrors(copy.deepcopy(DEFAULT_CONFIG))
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (json.JSONDecodeError, OSError) as exc:
        raise ConfigFileError(f"Unable to read configuration: {config_path}") from exc
    return _refresh_legacy_mirrors(migrate_config(raw))


def update_config(mutator, path: Path | None = None):
    """在文件锁保护下完成"读-改-写"全过程，避免跨进程丢失更新（M4）。

    mutator 接收迁移后的完整配置 dict，原地修改即可；
    其返回值作为 update_config 的返回值。mutator 抛异常时不写盘。
    """
    global _config_cache, _config_mtime, _config_path_cached

    config_path = Path(path) if path is not None else CONFIG_FILE
    if path is None:
        _migrate_legacy_runtime_files()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = config_path.parent / f".{config_path.name}.lock"
    lock_path.touch(exist_ok=True)
    with lock_path.open("r+") as lock_f:
        _lock_file(lock_f)
        try:
            cfg = _read_config_no_cache(config_path)
            result = mutator(cfg)
            persisted = _refresh_legacy_mirrors(migrate_config(cfg))
            _atomic_write_json_unlocked(config_path, persisted)
        finally:
            _unlock_file(lock_f)

    # Update cache to reflect newly written data
    try:
        _config_mtime = config_path.stat().st_mtime
    except OSError:
        _config_mtime = 0.0
    _config_cache = persisted
    _config_path_cached = config_path
    return result


def update_channel_fields(channel: str, fields: dict, path: Path | None = None) -> bool:
    """带锁更新 canonical ``channels.<channel>`` 下的字段（H1 修复后的统一写入入口）。

    所有"自动捕获/自动更新"型写入（listeners、keepalive 等）必须走这里，
    严禁直接写 config.json 顶层镜像——镜像会在下次 load 时被 canonical 重建覆盖。
    """
    if channel not in CHANNEL_NAMES:
        raise ValueError(f"Unsupported channel: {channel}")

    def _apply(cfg: dict) -> bool:
        canonical = cfg.setdefault("channels", {}).setdefault(channel, {})
        changed = False
        for key, value in fields.items():
            if canonical.get(key) != value:
                canonical[key] = value
                changed = True
        return changed

    changed = update_config(_apply, path)
    return bool(changed)
