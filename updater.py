"""Auto-update via GitHub Releases with visual progress.

Update flow:
1. Check for updates via latest.json or GitHub API
2. Show progress window during download
3. Replace exe via batch script
4. Update config.json version (preserve user settings)
5. Clean up temporary files
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk
import urllib.request
from pathlib import Path


APP_NAME = "ClaudeBeep"
GITHUB_OWNER = "Tommie-P-xl"
GITHUB_REPO = "ClaudeBeep"
UPDATE_CHECK_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
LATEST_JSON_URL = (
    f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
    f"/releases/latest/download/latest.json"
)


def _log(msg: str):
    try:
        _log_file = Path(sys.executable).resolve().parent / "updater.log" if getattr(sys, "frozen", False) else Path(__file__).resolve().parent / "updater.log"
        ts = time.strftime("%H:%M:%S")
        with open(_log_file, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def parse_version(v: str) -> tuple:
    v = v.lstrip("v")
    parts = v.split(".")
    return tuple(int(p) for p in parts[:3])


def _fetch_json(url: str, timeout: int = 15) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": APP_NAME})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        _log(f"Fetch failed for {url}: {e}")
        return None


def _find_exe_asset(release: dict) -> str | None:
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if name.endswith(".exe") and "setup" not in name.lower():
            url = asset.get("browser_download_url", "")
            if url:
                return url
    # Fallback: any .exe
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if name.endswith(".exe"):
            url = asset.get("browser_download_url", "")
            if url:
                return url
    return None


def check_for_update(current_version: str) -> dict | None:
    """Check for a newer release. Returns release info dict or None."""
    # Strategy 1: Try latest.json metadata endpoint
    data = _fetch_json(LATEST_JSON_URL)
    if data and "version" in data:
        remote_ver = parse_version(data["version"])
        local_ver = parse_version(current_version)
        if remote_ver > local_ver:
            exe_url = data.get("url") or data.get("download_url")
            if not exe_url:
                exe_url = _find_exe_asset(data)
            _log(f"Update available via latest.json: {data['version']}")
            return {
                "version": data["version"],
                "url": exe_url,
                "body": data.get("notes", data.get("body", "")),
            }

    # Strategy 2: Fall back to GitHub API
    data = _fetch_json(UPDATE_CHECK_URL)
    if not data:
        return None

    remote_tag = data.get("tag_name", "")
    if not remote_tag:
        return None

    remote_ver = parse_version(remote_tag)
    local_ver = parse_version(current_version)

    if remote_ver > local_ver:
        exe_url = _find_exe_asset(data)
        _log(f"Update available via API: {remote_tag}")
        return {
            "version": remote_tag,
            "url": exe_url,
            "body": data.get("body", ""),
        }

    _log(f"No update available (local={current_version}, remote={remote_tag})")
    return None


def _download_file_with_progress(url: str, dest: Path, progress_callback=None, timeout: int = 300) -> bool:
    """Download file with progress updates."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": APP_NAME})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total_size = int(resp.headers.get('Content-Length', 0))
            downloaded = 0
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total_size > 0:
                        progress_callback(downloaded, total_size)
        return dest.exists() and dest.stat().st_size > 0
    except Exception as e:
        _log(f"Download failed: {e}")
        return False


def _update_config_version(new_version: str) -> None:
    """Update version in config.json while preserving all user settings."""
    try:
        # Determine config path
        if getattr(sys, "frozen", False):
            config_path = Path(sys.executable).resolve().parent / "config.json"
        else:
            config_path = Path(__file__).resolve().parent / "config.json"

        if not config_path.exists():
            _log("Config file not found, skipping version update")
            return

        # Read existing config
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        # Update only the version field
        if "app" not in config:
            config["app"] = {}
        config["app"]["version"] = new_version.lstrip("v")

        # Write back preserving formatting
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        _log(f"Updated config.json version to {new_version}")

    except Exception as e:
        _log(f"Failed to update config version: {e}")


class UpdateProgressWindow:
    """Visual progress window for update download."""

    def __init__(self, version: str):
        self.version = version
        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} - 更新")
        self.root.geometry("400x180")
        self.root.resizable(False, False)

        # Center window
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - 400) // 2
        y = (self.root.winfo_screenheight() - 180) // 2
        self.root.geometry(f"+{x}+{y}")

        # Make window stay on top
        self.root.attributes('-topmost', True)

        self._create_widgets()
        self.cancelled = False
        self.download_complete = False
        self.download_success = False

    def _create_widgets(self):
        # Title
        title_label = tk.Label(
            self.root,
            text=f"正在更新到 {self.version}",
            font=("Microsoft YaHei UI", 12, "bold")
        )
        title_label.pack(pady=(15, 5))

        # Status label
        self.status_label = tk.Label(
            self.root,
            text="准备下载...",
            font=("Microsoft YaHei UI", 9)
        )
        self.status_label.pack(pady=(0, 10))

        # Progress bar
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(
            self.root,
            variable=self.progress_var,
            maximum=100,
            length=350,
            mode='determinate'
        )
        self.progress_bar.pack(pady=(0, 5))

        # Percentage label
        self.percent_label = tk.Label(
            self.root,
            text="0%",
            font=("Microsoft YaHei UI", 9)
        )
        self.percent_label.pack(pady=(0, 10))

        # Cancel button
        self.cancel_button = tk.Button(
            self.root,
            text="取消",
            command=self._on_cancel,
            width=10
        )
        self.cancel_button.pack()

    def _on_cancel(self):
        self.cancelled = True
        self.root.quit()

    def update_progress(self, downloaded: int, total: int):
        """Update progress bar (called from download thread)."""
        if self.cancelled:
            return
        percent = (downloaded / total) * 100
        downloaded_mb = downloaded / (1024 * 1024)
        total_mb = total / (1024 * 1024)

        self.root.after(0, self._update_ui, percent, downloaded_mb, total_mb)

    def _update_ui(self, percent, downloaded_mb, total_mb):
        """Update UI elements (must be called from main thread)."""
        self.progress_var.set(percent)
        self.percent_label.config(text=f"{percent:.1f}%")
        self.status_label.config(text=f"已下载 {downloaded_mb:.1f} MB / {total_mb:.1f} MB")

    def set_status(self, text: str):
        """Update status text."""
        self.root.after(0, lambda: self.status_label.config(text=text))

    def set_complete(self, success: bool):
        """Mark download as complete."""
        self.download_complete = True
        self.download_success = success
        if success:
            self.root.after(0, self._show_complete)
        else:
            self.root.after(0, self._show_error)

    def _show_complete(self):
        self.status_label.config(text="下载完成！正在安装...")
        self.cancel_button.config(state='disabled')
        # Auto close after 1 second
        self.root.after(1000, self.root.quit)

    def _show_error(self):
        self.status_label.config(text="下载失败，请重试")
        self.cancel_button.config(text="关闭")

    def run(self):
        """Start the progress window main loop."""
        self.root.mainloop()

    def destroy(self):
        """Destroy the window."""
        try:
            self.root.destroy()
        except Exception:
            pass


def perform_update(download_url: str, new_version: str) -> bool:
    """Download new version with visual progress and replace current exe."""
    if not download_url:
        _log("No download URL provided")
        return False
    if not getattr(sys, "frozen", False):
        _log("Not a packaged exe, cannot self-update")
        return False

    current_exe = Path(sys.executable)
    backup_exe = current_exe.with_suffix(".exe.bak")
    temp_dir = Path(tempfile.mkdtemp(prefix="claudebeep_update_"))
    new_exe = temp_dir / "ClaudeBeep_new.exe"
    log_file = current_exe.parent / "updater.log"

    # Create progress window
    progress_window = UpdateProgressWindow(new_version)

    def download_thread():
        """Download in background thread."""
        try:
            _log(f"Downloading update from: {download_url}")
            progress_window.set_status("正在下载...")

            success = _download_file_with_progress(
                download_url,
                new_exe,
                progress_callback=progress_window.update_progress
            )

            if not success or not new_exe.exists():
                _log("Download failed or file is empty")
                progress_window.set_complete(False)
                return

            _log(f"Downloaded {new_exe.stat().st_size} bytes")
            progress_window.set_complete(True)

        except Exception as e:
            _log(f"Download error: {e}")
            progress_window.set_complete(False)

    # Start download thread
    download_task = threading.Thread(target=download_thread, daemon=True)
    download_task.start()

    # Show progress window (blocks until closed)
    progress_window.run()
    progress_window.destroy()

    if progress_window.cancelled:
        _log("Update cancelled by user")
        try:
            new_exe.unlink(missing_ok=True)
            temp_dir.rmdir()
        except Exception:
            pass
        return False

    if not progress_window.download_success or not new_exe.exists():
        _log("Download was not successful")
        return False

    # Remove backup if exists
    if backup_exe.exists():
        try:
            backup_exe.unlink()
        except Exception:
            pass

    pid = os.getpid()
    config_path = current_exe.parent / "config.json"
    new_ver_clean = new_version.lstrip("v")

    # .ps1 核心逻辑 — 由 .bat 包装启动（.bat 能自删除，.ps1 不行）
    ps_script = f'''try {{
    $logFile = '{log_file}'
    function Log($msg) {{
        $ts = Get-Date -Format 'HH:mm:ss'
        Add-Content -Path $logFile -Value "[$ts] $msg" -Encoding UTF8
    }}
    Log 'PS1 update script started'
    Log "PID={pid} Current={current_exe} New={new_exe}"

    Start-Sleep -Seconds 3

    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Process -Id {pid} -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) {{
        Start-Sleep -Seconds 1
    }}
    $proc = Get-Process -Id {pid} -ErrorAction SilentlyContinue
    if ($proc) {{
        Log "Force killing PID {pid}"
        Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }}

    Log 'Replacing exe'
    $copied = $false
    for ($i = 1; $i -le 5; $i++) {{
        try {{
            Copy-Item -Path '{new_exe}' -Destination '{current_exe}' -Force -ErrorAction Stop
            $copied = $true
            Log "Copy succeeded on attempt $i"
            break
        }} catch {{
            Log "Copy attempt $i failed: $_"
            Start-Sleep -Seconds 2
        }}
    }}

    if (-not $copied) {{
        Log 'ALL copy attempts FAILED'
        Add-Type -AssemblyName PresentationFramework
        [System.Windows.MessageBox]::Show('Update failed! Could not replace exe.', 'ClaudeBeep Update', 'OK', 'Error')
        exit 1
    }}

    try {{
        $cfg = Get-Content '{config_path}' -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not $cfg.app) {{ $cfg | Add-Member -NotePropertyName app -NotePropertyValue (@{{}}) -Force }}
        $cfg.app.version = '{new_ver_clean}'
        $cfg | ConvertTo-Json -Depth 10 | Set-Content '{config_path}' -Encoding UTF8
        Log 'Config updated'
    }} catch {{
        Log "Config update failed: $_"
    }}

    Remove-Item -Path '{new_exe}' -Force -ErrorAction SilentlyContinue
    Log 'Update complete, restarting'
    Start-Process '{current_exe}'
    Log 'Restart initiated'
}} catch {{
    $errLogFile = '{log_file}'
    $ts = Get-Date -Format 'HH:mm:ss'
    Add-Content -Path $errLogFile -Value "[$ts] FATAL: $_" -Encoding UTF8
}}
'''

    ps_path = temp_dir / "update.ps1"
    with open(ps_path, "w", encoding="utf-8-sig") as f:
        f.write(ps_script)

    # .bat 包装器 — 能自删除，解决 .ps1 被锁问题
    bat_content = f"""@echo off
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{ps_path}"
ping -n 2 127.0.0.1 >nul
del /F "{ps_path}" >nul 2>&1
del /F "%~f0" >nul 2>&1
"""
    bat_path = temp_dir / "update.bat"
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(bat_content)

    _log("Launching update script...")
    subprocess.Popen(
        ["cmd", "/c", str(bat_path)],
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return True
