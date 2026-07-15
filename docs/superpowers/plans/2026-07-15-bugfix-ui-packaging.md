# ClaudeBeep Bugfix, UI Refactor, and Packaging Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Release ClaudeBeep 1.5.0 with all code review findings fixed, a cleaner dashboard/hooks UI split, sliding toggle switches, and full Python-independence for the built exe.

**Architecture:** Fix 8 bugs across `channels/weixin.py`, `hook_manager.py`, `notify.py`, `tray.py`, and `config_store.py`. Refactor `static/index.html` to move event toggles and hook management to the Hooks page, replace all native checkboxes with sliding toggles, and remove Python/System Info sections. Simplify `hook_manager._get_hook_base_cmd` for frozen exe and verify PyInstaller packaging completeness.

**Tech Stack:** Python 3.10+, Flask, pytest, Alpine.js, Tailwind CSS, native Win32 tray menus through `ctypes`, PyInstaller.

## Global Constraints

- Preserve Claude Code v1.1.0 `Stop`, `Elicitation`, and `PermissionRequest` behavior.
- Preserve Codex notification behavior.
- All existing tests must pass after each task.
- Do not run `git add` or `git commit`; keep changes unstaged until user requests.
- Every toggle in the UI must use the sliding toggle switch pattern (`.toggle-track` / `.toggle-thumb`).

## File Structure

### Files to modify

- `channels/weixin.py` — Fix 1: keepalive loop
- `hook_manager.py` — Fix 2: PYTHONUTF8 env; Fix packaging: simplify `_get_hook_base_cmd`
- `notify.py` — Fix 3: interaction config path; Fix 6: remove dead code
- `tray.py` — Fix 4: remove dead functions; update `_coerce_config` for simplified config_store
- `config_store.py` — Fix 7: simplify reconciliation; Fix 8: remove redundant copy
- `static/index.html` — UI refactor: dashboard, hooks page, toggle switches, remove Python info
- `app.py` — Remove `python_version` from `/api/status`
- `build.ps1` — Verify/add hidden imports

### Test files to modify

- `tests/test_config_store.py` — Update reconciliation tests for simplified model
- `tests/test_hook_manager.py` — Add test for PYTHONUTF8 in Codex hooks

---

### Task 1: Fix WeChat keepalive thread permanently exiting

**Files:**
- Modify: `channels/weixin.py:528-532`

**Interfaces:**
- Consumes: `config_store.should_run_weixin_keepalive`
- Produces: keepalive thread stays alive when WeChat is disabled, allowing restart

- [ ] **Step 1: Read the current keepalive loop**

Read `channels/weixin.py` lines 520-550 to confirm the exact `return` statement at line 532.

- [ ] **Step 2: Apply the fix**

In `channels/weixin.py`, replace lines 531-532:

```python
            if not config_store.should_run_weixin_keepalive(cfg):
                return
```

with:

```python
            if not config_store.should_run_weixin_keepalive(cfg):
                time.sleep(10)
                continue
```

- [ ] **Step 3: Verify the fix with existing tests**

Run:

```powershell
python -m pytest tests/test_weixin_keepalive.py -v
```

Expected: all tests pass.

- [ ] **Step 4: Verify full test suite**

Run:

```powershell
python -m pytest -v
```

Expected: all tests pass.

---

### Task 2: Add PYTHONUTF8=1 to Codex hook commands

**Files:**
- Modify: `hook_manager.py:126-132`
- Modify: `tests/test_hook_manager.py`

**Interfaces:**
- Consumes: `build_hook_command(platform, event)`
- Produces: Codex hook dict includes `env: {"PYTHONUTF8": "1"}`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_hook_manager.py`:

```python
def test_codex_hook_command_includes_pythonutf8_env():
    cmd = hook_manager.build_hook_command("codex", "Stop")
    assert cmd["env"] == {"PYTHONUTF8": "1"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
python -m pytest tests/test_hook_manager.py::test_codex_hook_command_includes_pythonutf8_env -v
```

Expected: FAIL — `KeyError: 'env'`.

- [ ] **Step 3: Apply the fix**

In `hook_manager.py`, replace lines 126-132:

```python
    return {
        "type": "command",
        "command": command,
        "commandWindows": command,
        "timeout": 10,
        "statusMessage": "ClaudeBeep notification",
    }
```

with:

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

- [ ] **Step 4: Run the test to verify it passes**

Run:

```powershell
python -m pytest tests/test_hook_manager.py::test_codex_hook_command_includes_pythonutf8_env -v
```

Expected: PASS.

- [ ] **Step 5: Run full test suite**

Run:

```powershell
python -m pytest -v
```

Expected: all tests pass.

---

### Task 3: Fix notify.py reading interaction config from legacy path

**Files:**
- Modify: `notify.py:372, 386-387`

**Interfaces:**
- Consumes: `config` dict from `load_config()`
- Produces: interaction settings read from canonical `integrations.claude_code.interaction`

- [ ] **Step 1: Read the current code**

Read `notify.py` lines 370-390 to confirm the exact legacy path references.

- [ ] **Step 2: Apply the fix**

In `notify.py`, replace line 372:

```python
            timeout=config.get("interaction", {}).get("timeout_seconds", 0),
```

with:

```python
            timeout=config.get("integrations", {}).get("claude_code", {}).get("interaction", {}).get("timeout_seconds", 0),
```

Replace lines 386-387:

```python
        timeout = config.get("interaction", {}).get("timeout_seconds", 0)
        show_terminal = config.get("interaction", {}).get("show_in_terminal", True)
```

with:

```python
        interaction_cfg = config.get("integrations", {}).get("claude_code", {}).get("interaction", {})
        timeout = interaction_cfg.get("timeout_seconds", 0)
        show_terminal = interaction_cfg.get("show_in_terminal", True)
```

- [ ] **Step 3: Run regression tests**

Run:

```powershell
python -m pytest tests/test_claude_regression.py -v
```

Expected: all tests pass.

- [ ] **Step 4: Run full test suite**

Run:

```powershell
python -m pytest -v
```

Expected: all tests pass.

---

### Task 4: Remove dead code from tray.py and notify.py

**Files:**
- Modify: `tray.py:558-577` — delete `_is_channel_enabled` and `_is_channel_configured`
- Modify: `notify.py:117-141` — delete `_clean_notify_hooks` and `_extract_commands`

**Interfaces:**
- No consumers of these functions exist.

- [ ] **Step 1: Verify no callers exist**

Run:

```powershell
cd D:\edge_load\ClaudeBeep
Select-String -Path "tray.py" -Pattern "_is_channel_enabled|_is_channel_configured" | Where-Object { $_.LineNumber -ge 558 }
```

Expected: only the function definitions, no callers.

Run:

```powershell
Select-String -Path "notify.py" -Pattern "_clean_notify_hooks|_extract_commands" | Where-Object { $_.LineNumber -ge 117 }
```

Expected: only the function definitions (and `_clean_notify_hooks` calling `_extract_commands`), no external callers.

- [ ] **Step 2: Delete `_is_channel_enabled` and `_is_channel_configured` from tray.py**

Delete lines 558-577 (the two functions).

- [ ] **Step 3: Delete `_clean_notify_hooks` and `_extract_commands` from notify.py**

Delete lines 117-141 (the two functions).

- [ ] **Step 4: Run full test suite**

Run:

```powershell
python -m pytest -v
```

Expected: all tests pass.

---

### Task 5: Simplify config_store reconciliation logic

**Files:**
- Modify: `config_store.py` — remove `ConfigSnapshot`, `_canonical_view`, `_legacy_view`, `_attach_snapshot`, `_field`, `_reconcile_field`, `_reconcile_legacy_changes`, `_MISSING`; simplify `load_config`, `save_config`, `migrate_config`
- Modify: `tray.py` — simplify `_coerce_config`
- Modify: `tests/test_config_store.py` — update reconciliation tests

**Interfaces:**
- Consumes: `migrate_config`, `load_config`, `save_config`
- Produces: `load_config` returns plain `dict`; `save_config` always migrates and mirrors

- [ ] **Step 1: Read the current config_store.py**

Read the full file to understand all functions to be removed/modified.

- [ ] **Step 2: Remove the reconciliation infrastructure**

In `config_store.py`:

Delete the following (lines 31-36):
```python
class ConfigSnapshot(dict):
    """Dict-compatible config carrying an in-memory baseline for compatibility saves."""

    _canonical_snapshot: dict | None = None
    _legacy_snapshot: dict | None = None
```

Delete `_MISSING` constant (line 38).

Delete `_canonical_view` (lines 129-133).

Delete `_legacy_view` (lines 136-141).

Delete `_attach_snapshot` (lines 144-148).

Delete `_field` (lines 151-152).

Delete `_reconcile_field` (lines 155-175).

Delete `_reconcile_legacy_changes` (lines 178-246).

- [ ] **Step 3: Simplify `migrate_config`**

In `config_store.py`, replace `migrate_config` (lines 249-290):

```python
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
```

- [ ] **Step 4: Simplify `load_config`**

In `config_store.py`, replace `load_config` (lines 368-379):

```python
def load_config(path: Path | None = None) -> dict:
    config_path = Path(path) if path is not None else CONFIG_FILE
    if not config_path.exists():
        config = copy.deepcopy(DEFAULT_CONFIG)
        save_config(config, config_path)
        return _refresh_legacy_mirrors(config)
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (json.JSONDecodeError, OSError) as exc:
        raise ConfigFileError(f"Unable to read configuration: {config_path}") from exc
    return _refresh_legacy_mirrors(migrate_config(raw))
```

- [ ] **Step 5: Simplify `save_config`**

In `config_store.py`, replace `save_config` (lines 382-393):

```python
def save_config(config: dict, path: Path | None = None) -> None:
    config_path = Path(path) if path is not None else CONFIG_FILE
    migrated = migrate_config(config)
    persisted = _refresh_legacy_mirrors(migrated)
    atomic_write_json(config_path, persisted)
```

- [ ] **Step 6: Simplify `_coerce_config` in tray.py**

In `tray.py`, replace `_coerce_config` (lines 592-599):

```python
def _coerce_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Migrate legacy dictionaries."""
    return config_store.migrate_config(raw)
```

- [ ] **Step 7: Update tests**

In `tests/test_config_store.py`, remove or update these tests that depend on reconciliation:

- `test_save_reconciles_legacy_mutations` — update to test that canonical values are preserved (legacy mutations on top-level keys are no longer propagated to canonical).
- `test_canonical_changes_win_over_legacy_mutations` — this test should still pass as-is.
- `test_legacy_credential_change_survives_unrelated_codex_change` — update: legacy top-level credential changes are no longer automatically propagated; the test should verify that canonical `channels` values are preserved.
- `test_legacy_interaction_change_survives_unrelated_canonical_channel_change` — update: legacy `interaction` changes are no longer propagated.
- `test_repeated_save_refreshes_snapshot_after_legacy_reconciliation` — update or remove.

Replace the reconciliation tests with:

```python
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
    assert not isinstance(config, config_store.ConfigSnapshot)
```

- [ ] **Step 8: Run full test suite**

Run:

```powershell
python -m pytest -v
```

Expected: all tests pass.

---

### Task 6: Fix runtime_channel_config redundant copy

**Files:**
- Modify: `config_store.py:307-314`

**Interfaces:**
- Consumes: `migrate_config`, `get_integration`
- Produces: same return shape, fewer allocations

- [ ] **Step 1: Apply the fix**

In `config_store.py`, replace `runtime_channel_config` (lines 307-314):

```python
def runtime_channel_config(config: dict, platform: str) -> dict:
    migrated = migrate_config(config)
    result = copy.deepcopy(migrated)
    selected = get_integration(migrated, platform)["channels"]
    for name in CHANNEL_NAMES:
        result[name] = copy.deepcopy(migrated["channels"][name])
        result[name]["enabled"] = bool(selected.get(name, False))
    return result
```

with:

```python
def runtime_channel_config(config: dict, platform: str) -> dict:
    migrated = migrate_config(config)
    result = copy.deepcopy(migrated)
    selected = get_integration(migrated, platform)["channels"]
    for name in CHANNEL_NAMES:
        result["channels"][name]["enabled"] = bool(selected.get(name, False))
    return result
```

- [ ] **Step 2: Run the runtime config test**

Run:

```powershell
python -m pytest tests/test_config_store.py::test_runtime_config_combines_shared_credentials_and_platform_switch -v
```

Expected: PASS.

- [ ] **Step 3: Run full test suite**

Run:

```powershell
python -m pytest -v
```

Expected: all tests pass.

---

### Task 7: Simplify `_get_hook_base_cmd` for frozen exe

**Files:**
- Modify: `hook_manager.py:38-53`

**Interfaces:**
- Consumes: `sys.frozen`, `sys.platform`
- Produces: frozen exe always uses its own path; no `shutil.which("python")` in frozen mode

- [ ] **Step 1: Apply the fix**

In `hook_manager.py`, replace `_get_hook_base_cmd` (lines 38-53):

```python
def _get_hook_base_cmd() -> str:
    script_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    if sys.platform == "win32":
        if getattr(sys, "frozen", False):
            py = shutil.which("python") or shutil.which("python3")
            script = script_dir / "notify.py"
            if py and script.exists():
                return f'"{py}" "{script}"'
            return f'"{Path(sys.executable).resolve()}"'
        bat = script_dir / "notify_hook.bat"
        if bat.exists():
            bat_path = str(bat).replace("/", chr(92))
            return f'"{bat_path}"'
        py = shutil.which("python") or shutil.which("python3")
        return f'"{py}" "{script_dir / "notify.py"}"' if py else f'"{script_dir / "notify.py"}"'
    return f'"{sys.executable}" "{script_dir / "notify.py"}"'
```

with:

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

- [ ] **Step 2: Run hook manager tests**

Run:

```powershell
python -m pytest tests/test_hook_manager.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Run full test suite**

Run:

```powershell
python -m pytest -v
```

Expected: all tests pass.

---

### Task 8: Remove Python references from UI and API

**Files:**
- Modify: `app.py:686-700` — remove `python_version` from `/api/status`
- Modify: `static/index.html:661-678` — remove System Info card
- Modify: `static/index.html:376-382` — remove hooks installed badge from status bar

**Interfaces:**
- Consumes: `/api/status` response
- Produces: no Python version or system info in UI

- [ ] **Step 1: Remove `python_version` from `/api/status`**

In `app.py`, replace lines 691-700:

```python
        return jsonify({
            "python_version": sys.version,
            "config_exists": CONFIG_FILE.exists(),
            "hooks_installed": _check_hooks_installed(),
            "channels": {
                "windows_toast": cfg.get("windows_toast", {}).get("enabled", False),
                "weixin": cfg.get("weixin", {}).get("enabled", False),
                "qq": cfg.get("qq", {}).get("enabled", False),
            },
        })
```

with:

```python
        return jsonify({
            "config_exists": CONFIG_FILE.exists(),
            "hooks_installed": _check_hooks_installed(),
        })
```

- [ ] **Step 2: Remove System Info card from dashboard**

In `static/index.html`, delete lines 661-678 (the entire `<!-- System Info -->` card):

```html
    <!-- System Info -->
    <div class="card p-6">
      ...
    </div>
```

- [ ] **Step 3: Remove hooks installed badge from top status bar**

In `static/index.html`, delete lines 376-382 (the hooks status badge):

```html
      <span class="status-badge"
            :style="status.hooks_installed ? 'background:var(--success-light);color:var(--success)' : 'background:var(--warning-light);color:var(--warning)'">
        <span class="w-2 h-2 rounded-full breathe-dot relative" :style="status.hooks_installed ? 'background:var(--success)' : 'background:var(--warning)'"></span>
        Hooks <span x-text="status.hooks_installed ? '已安装' : '未安装'"></span>
      </span>
```

- [ ] **Step 4: Verify no remaining Python references**

Run:

```powershell
Select-String -Path "static/index.html" -Pattern "python|Python"
```

Expected: no matches.

Run:

```powershell
Select-String -Path "app.py" -Pattern "python_version"
```

Expected: no matches.

---

### Task 9: Refactor dashboard to show only channel toggles

**Files:**
- Modify: `static/index.html:596-659` — refactor dashboard peer integrations section

**Interfaces:**
- Consumes: `integrations`, `channelOptions`, `toggleIntegrationChannel`, `saveIntegration`, `testIntegration`
- Produces: dashboard with platform toggles, channel toggles, interaction settings, test buttons

- [ ] **Step 1: Read the current dashboard section**

Read `static/index.html` lines 596-659 to understand the current structure.

- [ ] **Step 2: Replace the peer integrations section**

Replace lines 596-647 (the `<!-- Peer integrations -->` section) with:

```html
    <!-- Peer integrations -->
    <section class="mb-8">
      <div class="section-label mb-3 px-1">编程助手集成</div>
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <template x-for="platform in ['claude_code', 'codex']" :key="platform">
          <article class="card p-6" :data-integration="platform">
            <!-- Platform header with toggle -->
            <div class="flex items-start justify-between gap-4 mb-5">
              <div>
                <h3 class="font-bold text-base" style="color:var(--text-ink)" x-text="platform === 'claude_code' ? 'Claude Code' : 'Codex'"></h3>
                <p class="text-xs mt-1" style="color:var(--text-muted)" x-text="platform === 'claude_code' ? '本地 Hooks 与通知交互' : 'Codex 事件提醒集成'"></p>
              </div>
              <button @click="integrations[platform].enabled = !integrations[platform].enabled; saveIntegration(platform)" class="toggle-track" :aria-label="platform + ' enabled'"
                      :style="integrations[platform]?.enabled ? 'background:var(--accent)' : 'background:var(--toggle-off)'">
                <span class="toggle-thumb" :style="integrations[platform]?.enabled ? 'transform:translateX(22px)' : 'transform:translateX(0)'"></span>
              </button>
            </div>
            <!-- Channel toggles -->
            <div class="text-xs font-semibold mb-3" style="color:var(--text-body)">通知渠道</div>
            <div class="grid grid-cols-2 gap-2 mb-4">
              <template x-for="channel in channelOptions" :key="channel.id">
                <div class="flex items-center justify-between gap-2 rounded-xl px-3 py-2" style="background:var(--bg-surface-alt)">
                  <span class="text-xs truncate" style="color:var(--text-body)" x-text="channel.label"></span>
                  <button @click="toggleIntegrationChannel(platform, channel.id, !integrations[platform]?.channels?.[channel.id])" class="toggle-track toggle-sm"
                          :style="(integrations[platform]?.channels?.[channel.id]) ? 'background:var(--accent)' : 'background:var(--toggle-off)'">
                    <span class="toggle-thumb toggle-sm-thumb" :style="(integrations[platform]?.channels?.[channel.id]) ? 'transform:translateX(16px)' : 'transform:translateX(0)'"></span>
                  </button>
                </div>
              </template>
            </div>
            <!-- Claude Code interaction settings -->
            <div x-show="platform === 'claude_code'" class="mt-4 pt-4 space-y-3" style="border-top:1px solid var(--border-primary)">
              <div class="flex items-center justify-between">
                <span class="text-xs font-semibold" style="color:var(--text-body)">交互模式</span>
                <button @click="integrations.claude_code.interaction.enabled = !integrations.claude_code.interaction.enabled; saveIntegration('claude_code')" class="toggle-track toggle-sm"
                        :style="integrations.claude_code?.interaction?.enabled ? 'background:var(--accent)' : 'background:var(--toggle-off)'">
                  <span class="toggle-thumb toggle-sm-thumb" :style="integrations.claude_code?.interaction?.enabled ? 'transform:translateX(16px)' : 'transform:translateX(0)'"></span>
                </button>
              </div>
              <div class="flex items-center justify-between">
                <span class="text-xs" style="color:var(--text-muted)">超时（秒，0=无限）</span>
                <input type="number" min="0" class="w-20 px-2 py-1 text-xs rounded-lg" style="background:var(--input-bg);border:1px solid var(--input-border);color:var(--text-ink)" x-model.number="integrations.claude_code.interaction.timeout_seconds" @change="saveIntegration('claude_code')">
              </div>
            </div>
            <!-- Codex info -->
            <p x-show="platform === 'codex'" class="callout callout-info mt-4">远程渠道仅发送提醒，批准和回答仍在 Codex 中完成。</p>
            <!-- Test button -->
            <div class="mt-4 pt-3" style="border-top:1px solid var(--border-primary)">
              <button @click="testIntegration(platform)" class="btn-pill btn-ghost px-4 py-2 text-xs w-full">测试通知</button>
            </div>
          </article>
        </template>
      </div>
    </section>
```

- [ ] **Step 3: Remove the Quick Actions section**

Delete lines 649-659 (the `<!-- Quick Actions -->` section):

```html
    <!-- Quick Actions -->
    <div class="card p-6 mb-6">
      ...
    </div>
```

- [ ] **Step 4: Add the toggle-sm CSS**

In the `<style>` section of `static/index.html`, after the existing `.toggle-thumb` rule (line 219), add:

```css
  .toggle-sm {
    width: 36px; height: 20px;
  }
  .toggle-sm-thumb {
    width: 14px; height: 14px; top: 3px; left: 3px;
  }
```

- [ ] **Step 5: Verify no native checkboxes remain in dashboard**

Run:

```powershell
Select-String -Path "static/index.html" -Pattern "type=.checkbox." | Select-Object -First 20
```

Expected: no matches in the dashboard section (lines 596-660).

---

### Task 10: Refactor Hooks page with event toggles and Codex section

**Files:**
- Modify: `static/index.html:1074-1118` — rewrite Hooks page

**Interfaces:**
- Consumes: `integrations`, `hookStatus`, `syncIntegrationHooks`, `uninstallIntegrationHooks`, `hookDescriptions`
- Produces: Hooks page with event toggles (sliding switches), install/uninstall, both platforms

- [ ] **Step 1: Read the current Hooks page**

Read `static/index.html` lines 1074-1118 to understand the current structure.

- [ ] **Step 2: Replace the Hooks page**

Replace lines 1074-1118 (the `<!-- ==================== Hooks Tab ==================== -->` section) with:

```html
  <!-- ==================== Hooks Tab ==================== -->
  <div x-show="currentTab === 'hooks'" x-cloak>
    <!-- Claude Code Hooks -->
    <div class="card p-6 mb-6">
      <h3 class="font-bold text-base mb-2" style="color:var(--text-ink)">Claude Code Hooks</h3>
      <p class="text-xs mb-5" style="color:var(--text-muted)">
        Claude Code 通过 hooks 机制在特定事件触发时调用通知脚本。安装后，Claude 的各种操作（完成、询问、编辑文件、执行命令等）都会自动发送通知。
      </p>
      <div class="space-y-2 mb-5">
        <template x-for="(enabled, event) in integrations.claude_code.events" :key="event">
          <div class="flex items-center justify-between gap-3 rounded-xl px-3 py-2" style="background:var(--bg-surface-alt)">
            <div class="flex items-center gap-2 min-w-0">
              <span class="w-2 h-2 rounded-full flex-shrink-0" :style="(hookStatus.claude_code?.configured_events || []).includes(event) ? 'background:var(--success)' : 'background:var(--text-faint)'"></span>
              <div class="min-w-0">
                <div class="text-xs font-semibold truncate" style="color:var(--text-body)" x-text="event"></div>
                <div class="text-xs truncate" style="color:var(--text-muted)" x-text="hookDescriptions[event] || ''"></div>
              </div>
            </div>
            <button @click="integrations.claude_code.events[event] = !enabled; saveIntegration('claude_code')" class="toggle-track toggle-sm"
                    :style="enabled ? 'background:var(--accent)' : 'background:var(--toggle-off)'">
              <span class="toggle-thumb toggle-sm-thumb" :style="enabled ? 'transform:translateX(16px)' : 'transform:translateX(0)'"></span>
            </button>
          </div>
        </template>
      </div>
      <div class="flex gap-3 mb-4">
        <button @click="syncIntegrationHooks('claude_code')" class="btn-pill btn-primary px-6 py-2.5 text-sm">安装 Hooks</button>
        <button @click="uninstallIntegrationHooks('claude_code')" class="btn-pill btn-danger px-6 py-2.5 text-sm">卸载</button>
      </div>
      <div>
        <span class="text-xs" style="color:var(--text-muted)">配置文件：</span>
        <code class="text-xs px-3 py-1 rounded-lg inline-block font-bold" style="background:var(--accent-light);color:var(--accent)">~/.claude/settings.json</code>
      </div>
    </div>

    <!-- Codex Hooks -->
    <div class="card p-6">
      <h3 class="font-bold text-base mb-2" style="color:var(--text-ink)">Codex Hooks</h3>
      <p class="text-xs mb-5" style="color:var(--text-muted)">
        Codex 通过 hooks 机制在事件触发时调用通知脚本。安装后请在 Codex 中运行 <code>/hooks</code> 确认信任状态。
      </p>
      <div class="space-y-2 mb-5">
        <template x-for="(enabled, event) in integrations.codex.events" :key="event">
          <div class="flex items-center justify-between gap-3 rounded-xl px-3 py-2" style="background:var(--bg-surface-alt)">
            <div class="flex items-center gap-2 min-w-0">
              <span class="w-2 h-2 rounded-full flex-shrink-0" :style="(hookStatus.codex?.configured_events || []).includes(event) ? 'background:var(--success)' : 'background:var(--text-faint)'"></span>
              <span class="text-xs font-semibold truncate" style="color:var(--text-body)" x-text="event"></span>
            </div>
            <button @click="integrations.codex.events[event] = !enabled; saveIntegration('codex')" class="toggle-track toggle-sm"
                    :style="enabled ? 'background:var(--accent)' : 'background:var(--toggle-off)'">
              <span class="toggle-thumb toggle-sm-thumb" :style="enabled ? 'transform:translateX(16px)' : 'transform:translateX(0)'"></span>
            </button>
          </div>
        </template>
      </div>
      <div class="flex gap-3 mb-4">
        <button @click="syncIntegrationHooks('codex')" class="btn-pill btn-primary px-6 py-2.5 text-sm">安装 Hooks</button>
        <button @click="uninstallIntegrationHooks('codex')" class="btn-pill btn-danger px-6 py-2.5 text-sm">卸载</button>
      </div>
      <p x-show="hookStatus.codex?.trust_review_required" class="text-xs mb-3" style="color:var(--warning)">请在 Codex 中运行 /hooks 查看并确认信任状态。</p>
      <div>
        <span class="text-xs" style="color:var(--text-muted)">配置文件：</span>
        <code class="text-xs px-3 py-1 rounded-lg inline-block font-bold" style="background:var(--accent-light);color:var(--accent)">~/.codex/hooks.json</code>
      </div>
    </div>
  </div>
```

- [ ] **Step 3: Verify no native checkboxes remain in Hooks page**

Run:

```powershell
Select-String -Path "static/index.html" -Pattern "type=.checkbox."
```

Expected: no matches anywhere in the file.

- [ ] **Step 4: Verify the HTML structure**

Open the Web UI in a browser and verify:
- Dashboard shows platform toggles, channel toggles (sliding switches), interaction settings
- Hooks page shows event toggles (sliding switches) for both Claude Code and Codex
- No native checkboxes visible anywhere
- No Python version or system info displayed

---

### Task 11: Verify PyInstaller hidden imports and build

**Files:**
- Modify: `build.ps1` — add any missing hidden imports

**Interfaces:**
- Consumes: `build.ps1`
- Produces: `dist/ClaudeBeep.exe` that works without Python

- [ ] **Step 1: Check channel module imports**

Read `channels/__init__.py` to verify all channel modules are discoverable.

Read `channels/windows_toast.py` to check what it imports (win10toast_click / winotify).

- [ ] **Step 2: Add missing hidden imports if needed**

If `channels/windows_toast` uses `win10toast_click` or `winotify`, add to `build.ps1`:

```powershell
--hidden-import win10toast_click `
```

or

```powershell
--hidden-import winotify `
```

- [ ] **Step 3: Build the exe**

Run:

```powershell
cd D:\edge_load\ClaudeBeep
.\build.ps1
```

Expected: `dist\ClaudeBeep.exe` is created.

- [ ] **Step 4: Verify the exe runs**

Run:

```powershell
.\dist\ClaudeBeep.exe --test
```

Expected: test notifications are sent without errors.

- [ ] **Step 5: Run full test suite**

Run:

```powershell
python -m pytest -v
```

Expected: all tests pass.
