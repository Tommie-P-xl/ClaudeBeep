# ClaudeBeep Bugfix, UI Refactor, and Packaging Audit Design

## Summary

Fix 8 code review findings from the Codex integration work, refactor the Web UI to
separate dashboard (channel toggles) from hooks page (event toggles + hook management),
replace native checkboxes with sliding toggle switches, and ensure the PyInstaller-built
exe runs independently on machines without a Python environment.

## Goals

- Fix all 8 confirmed code review findings ranked by severity.
- Dashboard page controls only notification channel toggles and interaction settings.
- Hooks page manages event toggles and hook install/uninstall for both platforms.
- All toggle controls use sliding toggle switches (toggle-track + toggle-thumb).
- Remove Python version references from UI and API.
- Verify and fix all code paths for PyInstaller frozen exe compatibility.
- Ensure the built exe works on machines without any Python installation.

## Non-goals

- Redesign the notification delivery pipeline.
- Change the configuration data model.
- Add new notification channels or events.
- Migrate away from PyInstaller.

---

## Part 1: Code Review Bug Fixes

### Fix 1 — WeChat keepalive thread permanently exits (HIGH)

**File:** `channels/weixin.py:531-532`

**Problem:** `_keepalive_loop` uses `return` when `should_run_weixin_keepalive` returns
False, permanently terminating the thread. If WeChat is later re-enabled, the thread
cannot restart because `_keepalive_stop` remains set.

**Fix:** Replace `return` with `continue` and add a sleep before retrying. The loop
already checks `_keepalive_stop.is_set()` in the `while` condition, so `stop_keepalive()`
can still terminate it cleanly.

```python
# Line 531-532: change return to continue
if not config_store.should_run_weixin_keepalive(cfg):
    time.sleep(10)
    continue
```

### Fix 2 — Codex hook missing PYTHONUTF8=1 (MEDIUM)

**File:** `hook_manager.py:126-132`

**Problem:** Claude hook sets `env: {"PYTHONUTF8": "1"}` but Codex hook does not. On
non-UTF-8 Windows systems (e.g., GBK locale), Codex stdin JSON with non-ASCII characters
may produce mojibake.

**Fix:** Add `env` field to the Codex hook command dict.

```python
return {
    "type": "command",
    "command": command,
    "commandWindows": command,
    "env": {"PYTHONUTF8": "1"},
    "timeout": 10,
    "statusMessage": "ClaudeBeep notification",
}
```

### Fix 3 — notify.py reads interaction from legacy path (MEDIUM)

**File:** `notify.py:372, 386-387`

**Problem:** Interaction settings are read from `config.get("interaction", {})` (legacy
mirror) instead of the canonical `config["integrations"]["claude_code"]["interaction"]`.
If the legacy mirror is stale, timeout and show_in_terminal values may be wrong.

**Fix:** Read from canonical path.

```python
interaction_cfg = config.get("integrations", {}).get("claude_code", {}).get("interaction", {})
timeout = interaction_cfg.get("timeout_seconds", 0)
show_terminal = interaction_cfg.get("show_in_terminal", True)
```

### Fix 4 — tray.py dead code functions (MEDIUM)

**File:** `tray.py:558-577`

**Problem:** `_is_channel_enabled` and `_is_channel_configured` read from old flat config
structure (`cfg.get(name, {}).get("enabled")`). They are never called and would return
wrong values if called.

**Fix:** Delete both functions.

### Fix 5 — collect_channels behavioral change (LOW)

**File:** `notify.py:112-114`

**Problem:** Old `collect_channels` returned all 6 channels; new version returns only
enabled channels. This is an intentional design change for the Codex integration.

**Fix:** No code change needed. Confirm test coverage matches new behavior.

### Fix 6 — notify.py dead code (LOW)

**File:** `notify.py:117-141`

**Problem:** `_clean_notify_hooks` and `_extract_commands` are no longer called after hook
management moved to `hook_manager.py`.

**Fix:** Delete both functions.

### Fix 7 — config_store overly complex reconciliation (LOW)

**File:** `config_store.py:178-247`

**Problem:** `_reconcile_legacy_changes` implements a 4-way merge (canonical, canonical
baseline, legacy, legacy baseline) that exceeds the design spec's "canonical wins"
requirement. The function is 70 lines of hard-to-verify logic.

**Fix:** Simplify to unidirectional mirror: `_refresh_legacy_mirrors` copies canonical
values to legacy fields. Remove the reverse propagation from legacy to canonical. The
`ConfigSnapshot._canonical_snapshot` and `_legacy_snapshot` fields and the
`_reconcile_legacy_changes` function can be removed, along with `_attach_snapshot`,
`_canonical_view`, `_legacy_view`, `_field`, `_reconcile_field`. `load_config` returns
plain dicts; `save_config` always migrates and refreshes mirrors.

### Fix 8 — runtime_channel_config redundant copy (LOW)

**File:** `config_store.py:307-314`

**Problem:** `runtime_channel_config` calls `migrate_config` then `copy.deepcopy`, then
overwrites each `result[name]` with another `deepcopy` of `migrated["channels"][name]`.
The second set of copies is redundant.

**Fix:** Remove the per-channel `deepcopy` loop. The `result` already contains deep copies
from the initial `copy.deepcopy(migrated)`. Just set `enabled` on the existing entries.

```python
def runtime_channel_config(config: dict, platform: str) -> dict:
    migrated = migrate_config(config)
    result = copy.deepcopy(migrated)
    selected = get_integration(migrated, platform)["channels"]
    for name in CHANNEL_NAMES:
        result["channels"][name]["enabled"] = bool(selected.get(name, False))
    return result
```

---

## Part 2: UI Refactor

### 2.1 Dashboard Page

**Retain:**
- Platform enable toggles (Claude Code / Codex) — sliding toggle
- Notification channel toggles per platform (6 channels × 2 platforms) — sliding toggle
- Claude Code interaction mode settings
- Test notification buttons

**Remove:**
- Event notification checkboxes (move to Hooks page)
- Hook install/uninstall buttons (move to Hooks page)
- Quick Actions section
- System Info section (Python version, Hooks status, enabled channel count)

**Layout:** Two-column grid on desktop (one card per platform), stacked on mobile. Each
card contains: platform toggle → channel toggles (2×3 grid) → interaction settings
(Claude only) → test button.

### 2.2 Hooks Page

**Retain:**
- Claude Code hook status display and install/uninstall buttons
- settings.json path display

**Add:**
- Codex hook management section:
  - Event toggles (sliding toggle switches, one per supported event)
  - Install / Uninstall buttons
  - hooks.json path display
  - Trust review reminder for Codex
- Each platform in its own card

### 2.3 Toggle Switch Style

All checkboxes replaced with sliding toggle switches using existing `.toggle-track` /
`.toggle-thumb` CSS classes. Size variants:

```css
.toggle-sm { width: 36px; height: 20px; }
.toggle-sm .toggle-thumb { width: 14px; height: 14px; top: 3px; left: 3px; }
.toggle-sm.is-on .toggle-thumb { transform: translateX(16px); }
```

Standard size (48×26px) for platform toggles. Small size (36×20px) for channel and event
toggles.

### 2.4 Remove Python References

- Remove `python_version` from `/api/status` response in `app.py`
- Remove Python row from System Info card in `index.html`
- Remove hooks installed badge from top status bar (redundant with Hooks page)
- Remove the entire System Info card from dashboard

---

## Part 3: Packaging Compatibility Audit

### 3.1 Simplify `_get_hook_base_cmd` for frozen exe

**File:** `hook_manager.py:39-53`

**Problem:** Current code tries `shutil.which("python")` in frozen mode, which is
unnecessary and confusing.

**Fix:** Frozen exe always uses its own path.

```python
def _get_hook_base_cmd() -> str:
    script_dir = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent
    )
    if sys.platform == "win32":
        if getattr(sys, "frozen", False):
            return f'"{Path(sys.executable).resolve()}"'
        bat = script_dir / "notify_hook.bat"
        if bat.exists():
            return f'"{str(bat).replace("/", chr(92))}"'
        py = shutil.which("python") or shutil.which("python3")
        return f'"{py}" "{script_dir / "notify.py"}"' if py else f'"{script_dir / "notify.py"}"'
    return f'"{sys.executable}" "{script_dir / "notify.py"}"'
```

### 3.2 Verify PyInstaller hidden imports

Current `build.ps1` includes `--hidden-import` for:
- `websockets`
- `lark_oapi`, `lark_oapi.ws`
- `dingtalk_stream`

**Additional hidden imports to verify:**
- `channels.windows_toast` — uses `win10toast_click` or `winotify`
- `channels.telegram` — uses `urllib.request` (stdlib, auto-included)
- `channels.qq` — uses `urllib.request` (stdlib, auto-included)
- `channels.feishu` — uses `urllib.request` (stdlib, auto-included)

Add any missing hidden imports to `build.ps1`.

### 3.3 Verify tray.py `_open_ui` in frozen mode

**File:** `tray.py:798-802`

Current code correctly handles frozen mode by using `sys.executable --ui`. The `--ui` flag
triggers `notify.main()` → Flask app. No change needed.

### 3.4 Verify channels/weixin.py in frozen mode

**File:** `channels/weixin.py:168-170`

`_load_config_file` imports `config_store` inside the function. This is correct for lazy
loading. `config_store` will be bundled by PyInstaller. No change needed.

---

## Testing

- Run full pytest suite after each fix.
- Verify WeChat keepalive restarts after disable/re-enable cycle.
- Verify Codex hook commands include `PYTHONUTF8=1`.
- Verify UI dashboard shows only channel toggles with sliding switches.
- Verify Hooks page shows event toggles for both platforms.
- Build exe and test on a clean Windows machine without Python.

## Acceptance Criteria

1. All 8 code review findings are fixed.
2. Dashboard shows platform toggles, channel toggles, interaction settings, and test buttons only.
3. Hooks page shows event toggles and hook install/uninstall for both platforms.
4. All toggles use sliding switch style (no native checkboxes).
5. No Python version references in UI or API.
6. Built exe runs on a clean Windows machine without Python.
7. All existing tests pass.
