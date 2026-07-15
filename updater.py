"""Auto-update via GitHub Releases with silent Setup installer.

Update flow:
1. Check for updates via latest.json or GitHub API
2. Download Setup.exe from the release assets
3. Launch Setup.exe silently (Inno Setup flags)
"""
import json
import subprocess
import sys
import tempfile
import time
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


def _find_setup_asset(release: dict) -> str | None:
    """Find the Setup exe asset in a GitHub release."""
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if "setup" in name.lower() and name.endswith(".exe"):
            url = asset.get("browser_download_url", "")
            if url:
                return url
    # Fallback: any .exe that looks like an installer
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if name.endswith(".exe") and "ClaudeBeep" in name:
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
                exe_url = _find_setup_asset(data)
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
        exe_url = _find_setup_asset(data)
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


def perform_update(download_url: str, new_version: str) -> bool:
    """Download Setup.exe and run it silently to update."""
    if not download_url:
        _log("No download URL provided")
        return False

    temp_dir = Path(tempfile.mkdtemp(prefix="claudebeep_update_"))
    setup_exe = temp_dir / f"ClaudeBeep-Setup-{new_version.lstrip('v')}.exe"

    _log(f"Downloading update from: {download_url}")

    # Show info message
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None,
            f"正在下载 ClaudeBeep {new_version}...\n下载完成后将自动安装并重启。",
            "ClaudeBeep 更新",
            0x40  # MB_ICONINFORMATION
        )
    except Exception:
        pass

    # Download the Setup.exe
    success = _download_file_with_progress(download_url, setup_exe)
    if not success or not setup_exe.exists():
        _log("Download failed or file is empty")
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None,
                "下载失败，请手动下载更新。",
                "ClaudeBeep 更新",
                0x10  # MB_ICONERROR
            )
        except Exception:
            pass
        return False

    _log(f"Downloaded {setup_exe.stat().st_size} bytes")

    # Launch the Setup.exe silently, install to current directory
    install_dir = str(Path(sys.executable).resolve().parent)
    try:
        _log(f"Launching Setup.exe silently (install to {install_dir})...")
        subprocess.Popen(
            [
                str(setup_exe),
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/CLOSEAPPLICATIONS",
                "/RESTARTAPPLICATIONS",
                f"/DIR={install_dir}",
            ],
            cwd=str(temp_dir),
            creationflags=subprocess.DETACHED_PROCESS,
        )
        return True
    except Exception as e:
        _log(f"Failed to launch Setup.exe: {e}")
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None,
                f"启动安装程序失败: {e}\n请手动运行: {setup_exe}",
                "ClaudeBeep 更新",
                0x10
            )
        except Exception:
            pass
        return False
