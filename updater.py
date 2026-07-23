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


def _is_installer(filename: str) -> bool:
    """Check if the filename looks like an Inno Setup installer."""
    return "setup" in filename.lower() or "installer" in filename.lower()


def perform_update(download_url: str, new_version: str) -> bool:
    """Download and apply update. Handles both Setup installer and standalone exe."""
    if not download_url:
        _log("No download URL provided")
        return False

    temp_dir = Path(tempfile.mkdtemp(prefix="claudebeep_update_"))
    filename = download_url.split("/")[-1].split("?")[0]  # Get filename from URL
    if not filename.endswith(".exe"):
        filename = f"ClaudeBeep-Setup-{new_version.lstrip('v')}.exe"
    downloaded_file = temp_dir / filename

    _log(f"Downloading update from: {download_url}")
    _log(f"File type: {'installer' if _is_installer(filename) else 'standalone exe'}")

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

    # Download the file
    success = _download_file_with_progress(download_url, downloaded_file)
    if not success or not downloaded_file.exists():
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

    _log(f"Downloaded {downloaded_file.stat().st_size} bytes")

    install_dir = Path(sys.executable).resolve().parent

    if _is_installer(filename):
        # It's an Inno Setup installer - launch silently
        try:
            _log(f"Launching Setup.exe silently (install to {install_dir})...")
            subprocess.Popen(
                [
                    str(downloaded_file),
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
                    f"启动安装程序失败: {e}\n请手动运行: {downloaded_file}",
                    "ClaudeBeep 更新",
                    0x10
                )
            except Exception:
                pass
            return False
    else:
        # It's a standalone exe - copy to replace current exe
        try:
            current_exe = Path(sys.executable).resolve()
            backup_exe = current_exe.with_suffix(".exe.bak")

            _log(f"Replacing standalone exe: {current_exe}")

            # Create backup of current exe
            if backup_exe.exists():
                backup_exe.unlink()
            current_exe.rename(backup_exe)

            # Copy new exe to install location
            import shutil
            shutil.copy2(str(downloaded_file), str(current_exe))

            _log(f"Successfully replaced exe. Restarting...")

            # Launch new version
            subprocess.Popen(
                [str(current_exe)],
                cwd=str(install_dir),
                creationflags=subprocess.DETACHED_PROCESS,
            )
            return True
        except Exception as e:
            _log(f"Failed to replace exe: {e}")
            # Try to restore backup
            try:
                if backup_exe.exists() and not current_exe.exists():
                    backup_exe.rename(current_exe)
            except Exception:
                pass
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(
                    None,
                    f"更新失败: {e}\n请手动替换: {downloaded_file}",
                    "ClaudeBeep 更新",
                    0x10
                )
            except Exception:
                pass
            return False
