"""Auto-update via GitHub Releases with silent Setup installer.

Update flow:
1. Check for updates via latest.json or GitHub API
2. Download Setup.exe from the release assets
3. Verify SHA256 (when metadata provides it)
4. Launch Setup.exe silently (Inno Setup flags), or for standalone exe:
   schedule a delayed replacement script (running exe cannot rename itself)
"""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from version import APP_NAME, GITHUB_OWNER, GITHUB_REPO


UPDATE_CHECK_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
LATEST_JSON_URL = (
    f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
    f"/releases/latest/download/latest.json"
)


def _log(msg: str):
    try:
        from common.paths import RUNTIME_DIR
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        _log_file = RUNTIME_DIR / "updater.log"
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
                "sha256": str(data.get("sha256", "") or "").strip(),
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
            "sha256": "",
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


def _verify_sha256(path: Path, expected: str) -> bool:
    """校验下载文件哈希（S4）。expected 为空时跳过（元数据未提供）。"""
    expected = (expected or "").strip().lower()
    if not expected:
        _log("No SHA256 metadata provided, skipping verification")
        return True
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                digest.update(chunk)
        actual = digest.hexdigest()
        if actual != expected:
            _log(f"SHA256 mismatch: expected {expected}, got {actual}")
            return False
        _log("SHA256 verification passed")
        return True
    except Exception as e:
        _log(f"SHA256 verification failed: {e}")
        return False


def _is_installer(filename: str) -> bool:
    """Check if the filename looks like an Inno Setup installer."""
    return "setup" in filename.lower() or "installer" in filename.lower()


def _message_box(text: str, flags: int) -> int:
    """显示更新相关消息框，返回用户选择（如 IDYES=6）；失败返回 0。"""
    try:
        import ctypes
        return ctypes.windll.user32.MessageBoxW(None, text, "ClaudeBeep 更新", flags)
    except Exception:
        return 0


def perform_update(download_url: str, new_version: str, sha256: str = "") -> bool:
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

    # L15：元数据缺少 SHA256 时要求用户显式确认（防供应链篡改）
    if not (sha256 or "").strip():
        choice = _message_box(
            f"新版本 {new_version} 的更新元数据未提供 SHA256 校验值，\n"
            "无法验证安装包完整性。仍要继续下载并安装吗？",
            0x24,  # MB_ICONQUESTION | MB_YESNO
        )
        if choice != 6:  # IDYES
            _log("Update aborted: missing SHA256, user declined")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return False

    # Show info message
    _message_box(
        f"正在下载 ClaudeBeep {new_version}...\n下载完成后将自动安装并重启。",
        0x40,  # MB_ICONINFORMATION
    )

    # Download the file
    success = _download_file_with_progress(download_url, downloaded_file)
    if not success or not downloaded_file.exists():
        _log("Download failed or file is empty")
        _message_box("下载失败，请手动下载更新。", 0x10)
        shutil.rmtree(temp_dir, ignore_errors=True)
        return False

    _log(f"Downloaded {downloaded_file.stat().st_size} bytes")

    # 哈希校验（S4）：元数据提供 SHA256 时强制比对，失败即中止
    if not _verify_sha256(downloaded_file, sha256):
        _message_box("下载文件校验失败（SHA256 不匹配），为安全起见已取消更新。", 0x10)
        shutil.rmtree(temp_dir, ignore_errors=True)
        return False

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
            _message_box(f"启动安装程序失败: {e}\n请手动运行: {downloaded_file}", 0x10)
            shutil.rmtree(temp_dir, ignore_errors=True)
            return False

    # ── standalone exe：运行中的程序无法 rename 自身（S4）────
    # 生成延迟替换脚本，在进程退出后由独立 cmd 完成替换并重启
    try:
        current_exe = Path(sys.executable).resolve()
        backup_exe = current_exe.with_suffix(".exe.bak")
        script = temp_dir / "apply_update.bat"

        _log(f"Replacing standalone exe via delayed script: {current_exe}")

        # 延迟替换脚本：等待旧进程退出 → 备份/替换 → 延迟启动新 exe。
        # 竞态防护（修复 _MEI python311.dll 加载失败）：
        #   1) Web UI 子进程等仍持有 exe 句柄，rename/copy 会被锁 → 先循环等待全部退出（最长 20s），超时中止；
        #   2) 替换后立即启动时，Defender 实时扫描会锁定刚写入的 exe，引导器解压失败 → 延迟 3s 再启动。
        script_content = (
            "@echo off\r\n"
            "rem Wait for all old ClaudeBeep processes to exit (max 20s)\r\n"
            "set /a waited=0\r\n"
            ":wait_loop\r\n"
            'tasklist /fi "imagename eq ClaudeBeep.exe" 2>nul | find /i "ClaudeBeep.exe" >nul\r\n'
            "if errorlevel 1 goto proceed\r\n"
            "timeout /t 1 /nobreak >nul\r\n"
            "set /a waited+=1\r\n"
            "if %waited% lss 20 goto wait_loop\r\n"
            f'echo [ClaudeBeep] Timed out waiting for old processes, update aborted > "{temp_dir}\\update_aborted.txt"\r\n'
            "exit /b 1\r\n"
            ":proceed\r\n"
            "timeout /t 1 /nobreak >nul\r\n"
            f'if exist "{backup_exe}" del /q "{backup_exe}"\r\n'
            f'rename "{current_exe}" "{backup_exe.name}"\r\n'
            f'if exist "{current_exe}" del /q "{current_exe}"\r\n'
            f'copy /y "{downloaded_file}" "{current_exe}" >nul\r\n'
            f'if not exist "{current_exe}" (\r\n'
            f'  echo [ClaudeBeep] Replace failed, restoring backup > "{temp_dir}\\update_failed.txt"\r\n'
            f'  if exist "{backup_exe}" rename "{backup_exe}" "{current_exe.name}"\r\n'
            "  exit /b 1\r\n"
            ")\r\n"
            "rem Let antivirus finish scanning the new exe before launching\r\n"
            "timeout /t 3 /nobreak >nul\r\n"
            f'start "" "{current_exe}"\r\n'
            f'del /q "{downloaded_file}"\r\n'
            f'del /q "%~f0"\r\n'
            f'rmdir /q "{temp_dir}" 2>nul\r\n'
        )
        # M3 修复：脚本中含本机路径，用户名含非 ASCII 字符（如中文）时
        # ascii 编码必抛 UnicodeEncodeError。cmd.exe 按 ANSI 代码页解析 bat，
        # 故用 mbcs 写入；仍失败则回退提示手动更新。
        try:
            script.write_text(script_content, encoding="mbcs")
        except (UnicodeEncodeError, LookupError) as enc_err:
            _log(f"Batch script encoding failed (non-ASCII path): {enc_err}")
            _message_box(
                f"自动更新脚本无法处理当前路径（含特殊字符）。\n请手动运行: {downloaded_file}",
                0x10,
            )
            return False

        subprocess.Popen(
            ["cmd", "/c", str(script)],
            cwd=str(temp_dir),
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
        )
        return True
    except Exception as e:
        _log(f"Failed to schedule standalone replacement: {e}")
        _message_box(f"更新失败: {e}\n请手动替换: {downloaded_file}", 0x10)
        shutil.rmtree(temp_dir, ignore_errors=True)
        return False
