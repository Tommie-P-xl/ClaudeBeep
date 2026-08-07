from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from dataclasses import dataclass
import tempfile
from pathlib import Path

from config_store import CLAUDE_EVENTS, CODEX_EVENTS, atomic_write_json

CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"
CODEX_HOOKS = Path.home() / ".codex" / "hooks.json"
OWNER_FLAG = "--claudebeep-hook"


@dataclass(frozen=True)
class HookStatus:
    platform: str
    configured_events: tuple[str, ...]
    removed_count: int = 0


@dataclass(frozen=True)
class HookFileSnapshot:
    path: Path
    existed: bool
    content: bytes = b""


class HookFileError(RuntimeError):
    pass


def _get_hook_base_cmd() -> str:
    script_dir = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent
    )
    if sys.platform == "win32":
        if getattr(sys, "frozen", False):
            bat = script_dir / "claudebeep_hook.bat"
            if bat.exists():
                return str(bat).replace("\\", "/")
            return str(Path(sys.executable).resolve()).replace("\\", "/")
        bat = script_dir / "notify_hook.bat"
        if bat.exists():
            return str(bat).replace("\\", "/")
        py = shutil.which("python") or shutil.which("python3")
        return f'"{py}" "{script_dir / "notify.py"}"' if py else f'"{script_dir / "notify.py"}"'
    return f'"{sys.executable}" "{script_dir / "notify.py"}"'


def _is_owned(command: str, platform: str) -> bool:
    argv = _command_argv(command)
    return bool(
        _is_known_entry(argv)
        and argv.count(OWNER_FLAG) == 1
        and argv.count("--from-stdin") == 1
        and argv.count("--platform") == 1
        and argv[argv.index("--platform") + 1:argv.index("--platform") + 2] == [platform]
    )


def _is_legacy_claude_owned(command: str) -> bool:
    argv = _command_argv(command)
    return bool(
        _is_known_entry(argv)
        and OWNER_FLAG not in argv
        and argv.count("--from-stdin") == 1
        and argv.count("--type") == 1
        and argv[argv.index("--type") + 1:argv.index("--type") + 2] in (["stop"], ["ask"])
    )


def _command_argv(command: str) -> list[str]:
    if not isinstance(command, str):
        return []
    try:
        lexer = shlex.shlex(command, posix=False)
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return []
    return [token[1:-1] if len(token) >= 2 and token[0] == token[-1] == '"' else token for token in tokens]


def _normalized_path(value: str) -> str:
    return str(Path(value).resolve()).replace("\\", "/").casefold()


def _known_roots() -> set[str]:
    roots = {_normalized_path(str(Path(__file__).resolve().parent))}
    if getattr(sys, "frozen", False):
        roots.add(_normalized_path(str(Path(sys.executable).resolve().parent)))
    return roots


def _is_known_entry(argv: list[str]) -> bool:
    if not argv:
        return False
    roots = _known_roots()
    first = Path(argv[0])
    first_root = _normalized_path(str(first.parent))
    first_name = first.name.casefold()
    if first_root in roots and first_name in {"notify_hook.bat", "claudebeep_hook.bat", "claudebeep.exe"}:
        return True
    if len(argv) >= 2:
        script = Path(argv[1])
        return script.name.casefold() == "notify.py" and _normalized_path(str(script.parent)) in roots
    return False


def build_hook_command(platform: str, event: str) -> dict:
    if platform not in ("claude_code", "codex"):
        raise ValueError(f"Unsupported platform: {platform}")
    allowed = CLAUDE_EVENTS if platform == "claude_code" else CODEX_EVENTS
    if event not in allowed:
        raise ValueError(f"Unsupported event for {platform}: {event}")
    command = f"{_get_hook_base_cmd()} {OWNER_FLAG} --platform {platform} --from-stdin"
    if platform == "claude_code":
        command += f" --type {'stop' if event == 'Stop' else 'ask'}"
        return {"type": "command", "command": command, "env": {"PYTHONUTF8": "1"}}
    return {
        "type": "command",
        "command": command,
        "commandWindows": command,
        "env": {"PYTHONUTF8": "1"},
        "timeout": 10,
        "statusMessage": "ClaudeBeep notification",
    }


def _path_for(platform: str, path: Path | None) -> Path:
    if platform == "claude_code":
        return Path(path) if path is not None else CLAUDE_SETTINGS
    if platform == "codex":
        return Path(path) if path is not None else CODEX_HOOKS
    raise ValueError(f"Unsupported platform: {platform}")


def snapshot_hooks(platform: str, path: Path | None = None) -> HookFileSnapshot:
    target = _path_for(platform, path)
    if not target.exists():
        return HookFileSnapshot(target, False)
    try:
        return HookFileSnapshot(target, True, target.read_bytes())
    except OSError as exc:
        raise HookFileError(f"Unable to snapshot hook file: {target}") from exc


def restore_hooks(snapshot: HookFileSnapshot) -> None:
    target = snapshot.path
    if not snapshot.existed:
        try:
            target.unlink(missing_ok=True)
        except OSError as exc:
            raise HookFileError(f"Unable to restore missing hook file: {target}") from exc
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(snapshot.content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    except Exception as exc:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise HookFileError(f"Unable to restore hook file: {target}") from exc


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise HookFileError(f"Unable to read hook file: {path}") from exc
    if not isinstance(value, dict):
        raise HookFileError(f"Hook file root must be an object: {path}")
    return value


def _filter_event(entries: list, platform: str, event: str) -> tuple[list, int]:
    result, removed = [], 0
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
            result.append(entry)
            continue
        handlers = []
        for handler in entry["hooks"]:
            command = handler.get("command", "") if isinstance(handler, dict) else ""
            owned = isinstance(command, str) and (_is_owned(command, platform) or (platform == "claude_code" and _is_legacy_claude_owned(command)))
            if owned:
                removed += 1
            else:
                handlers.append(handler)
        if handlers:
            updated = dict(entry)
            updated["hooks"] = handlers
            result.append(updated)
    return result, removed


def sync_hooks(platform: str, enabled_events, path: Path | None = None) -> HookStatus:
    target = _path_for(platform, path)
    data = _read(target)
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise HookFileError("hooks must be an object")
    allowed = CLAUDE_EVENTS if platform == "claude_code" else CODEX_EVENTS
    enabled = {event for event in enabled_events if event in allowed}
    removed = 0
    for event in list(hooks):
        entries = hooks.get(event)
        if not isinstance(entries, list):
            continue
        filtered, count = _filter_event(entries, platform, event)
        removed += count
        if filtered:
            hooks[event] = filtered
        else:
            hooks.pop(event, None)
    for event in allowed:
        if event in enabled:
            entries = hooks.setdefault(event, [])
            if not isinstance(entries, list):
                # M8 修复：手工编辑过的畸形条目（非 list）直接重置，避免 append 崩溃
                entries = []
                hooks[event] = entries
            # Check if an owned hook already exists for this event
            already_owned = False
            for entry in entries:
                if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
                    continue
                for handler in entry["hooks"]:
                    command = handler.get("command", "") if isinstance(handler, dict) else ""
                    if isinstance(command, str) and _is_owned(command, platform):
                        already_owned = True
                        break
                if already_owned:
                    break
            if not already_owned:
                entries.append({"matcher": "", "hooks": [build_hook_command(platform, event)]})
    data["hooks"] = hooks
    atomic_write_json(target, data)
    return HookStatus(platform, tuple(event for event in allowed if event in enabled), removed)


def _cleanup_codex_config_toml() -> None:
    """Remove [hooks.state] entries from ~/.codex/config.toml that reference hooks.json."""
    config_toml = Path.home() / ".codex" / "config.toml"
    if not config_toml.exists():
        return
    try:
        lines = config_toml.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError:
        return

    hooks_json_path = str(CODEX_HOOKS).replace("\\", "/")
    new_lines = []
    skip_next_values = False
    for line in lines:
        stripped = line.strip()
        # Detect [hooks.state.'...hooks.json...'] section headers
        normalized_stripped = stripped.replace("\\", "/")
        if normalized_stripped.startswith("[hooks.state.'") and hooks_json_path in normalized_stripped:
            skip_next_values = True
            continue
        # Skip key-value lines belonging to a skipped section
        if skip_next_values:
            # M10 修复：仅在遇到下一个段头时结束跳过；
            # TOML 段内允许空行，空行不再提前结束跳过（否则残留键会挂靠到前一个段）
            if stripped.startswith("["):
                skip_next_values = False
            else:
                continue
        new_lines.append(line)

    # 写前备份，行级处理出错时可人工恢复
    try:
        shutil.copy2(config_toml, config_toml.with_suffix(".toml.bak"))
    except OSError:
        pass

    fd, tmp = tempfile.mkstemp(prefix=".config.toml.", suffix=".tmp", dir=config_toml.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("".join(new_lines))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, config_toml)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def uninstall_hooks(platform: str, path: Path | None = None) -> HookStatus:
    target = _path_for(platform, path)
    data = _read(target)
    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        raise HookFileError("hooks must be an object")
    removed = 0
    configured = []
    for event, entries in list(hooks.items()):
        if not isinstance(entries, list):
            continue
        filtered, count = _filter_event(entries, platform, event)
        removed += count
        if filtered:
            hooks[event] = filtered
        else:
            hooks.pop(event, None)
    data["hooks"] = hooks
    if target.exists() and removed:
        atomic_write_json(target, data)
    # Clean up Codex config.toml hooks.state when uninstalling Codex hooks
    if platform == "codex" and removed:
        _cleanup_codex_config_toml()
    remaining = inspect_hooks(platform, target).configured_events if target.exists() else ()
    return HookStatus(platform, remaining, removed)


def inspect_hooks(platform: str, path: Path | None = None) -> HookStatus:
    target = _path_for(platform, path)
    data = _read(target)
    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        raise HookFileError("hooks must be an object")
    configured = []
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            continue
        found = False
        for group in entries:
            handlers = group.get("hooks") if isinstance(group, dict) else None
            if not isinstance(handlers, list):
                continue
            for handler in handlers:
                if not isinstance(handler, dict) or not isinstance(handler.get("command"), str):
                    continue
                if _is_owned(handler["command"], platform) or (platform == "claude_code" and _is_legacy_claude_owned(handler["command"])):
                    found = True
                    break
            if found:
                break
        if found:
            configured.append(event)
    allowed = CLAUDE_EVENTS if platform == "claude_code" else CODEX_EVENTS
    return HookStatus(platform, tuple(event for event in allowed if event in configured))
