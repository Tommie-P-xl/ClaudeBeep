#!/usr/bin/env python3
"""ClaudeBeep Windows tray application — native Win32 menus for crisp DPI rendering."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import os
import ssl  # 提前导入，避免 PyInstaller --onefile 下 urllib 运行时从 base_library.zip 加载失败
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
import winreg
from pathlib import Path
from typing import Any

APP_NAME = "ClaudeBeep"
APP_VERSION = "1.0.5"
SCRIPT_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", SCRIPT_DIR))
CONFIG_FILE = SCRIPT_DIR / "config.json"
HEARTBEAT_FILE = SCRIPT_DIR / "tray_heartbeat.json"
ICON_FILE = RESOURCE_DIR / "assets" / "icon.ico"

CHANNEL_LABELS = {
    "windows_toast": "Windows 通知",
    "weixin": "WeChat ⚠️",
    "qq": "QQ Bot",
    "telegram": "Telegram",
    "feishu": "Feishu",
    "dingtalk": "DingTalk",
}

_mutex_handle = None
_ui_process: subprocess.Popen | None = None
_stop_event = threading.Event()

# ─── Win32 constants ─────────────────────────────────────────────────────────
WM_USER = 0x0400
WM_TRAYICON = WM_USER + 1
WM_COMMAND = 0x0111
WM_RBUTTONUP = 0x0205
WM_LBUTTONUP = 0x0202
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
MF_STRING = 0x0000
MF_SEPARATOR = 0x0800
MF_CHECKED = 0x0008
MF_GRAYED = 0x0001
MF_POPUP = 0x0010
TPM_RIGHTBUTTON = 0x0002
TPM_BOTTOMALIGN = 0x0020
WM_NULL = 0x0000
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
GCLP_HICON = -14
IDI_APPLICATION = ctypes.cast(32512, ctypes.c_wchar_p)

# Menu command IDs (must be > 0)
CMD_OPEN_UI = 1001
CMD_INSTALL_HOOKS = 1002
CMD_UNINSTALL_HOOKS = 1003
CMD_STARTUP = 1004
CMD_CHECK_UPDATE = 1005
CMD_QUIT = 1006
CMD_CHANNEL_BASE = 2000  # 2000+channel_index for toggles

# ─── Win32 structures ────────────────────────────────────────────────────────
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.DWORD),
        ("hWnd", ctypes.wintypes.HWND),
        ("uID", ctypes.wintypes.UINT),
        ("uFlags", ctypes.wintypes.UINT),
        ("uCallbackMessage", ctypes.wintypes.UINT),
        ("hIcon", ctypes.wintypes.HICON),
        ("szTip", ctypes.c_wchar * 128),
        ("dwState", ctypes.wintypes.DWORD),
        ("dwStateMask", ctypes.wintypes.DWORD),
        ("szInfo", ctypes.c_wchar * 256),
        ("uVersion", ctypes.wintypes.UINT),
        ("szInfoTitle", ctypes.c_wchar * 64),
        ("dwInfoFlags", ctypes.wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", ctypes.wintypes.HICON),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.wintypes.HWND, ctypes.wintypes.UINT,
                            ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.UINT),
        ("style", ctypes.wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", ctypes.wintypes.HINSTANCE),
        ("hIcon", ctypes.wintypes.HICON),
        ("hCursor", ctypes.wintypes.HANDLE),
        ("hbrBackground", ctypes.wintypes.HBRUSH),
        ("lpszMenuName", ctypes.c_wchar_p),
        ("lpszClassName", ctypes.c_wchar_p),
        ("hIconSm", ctypes.wintypes.HICON),
    ]


# ─── Win32 function signatures (required for string args) ───────────────────
UINT_PTR = ctypes.c_size_t  # platform-sized unsigned int, not in ctypes.wintypes
user32.AppendMenuW.argtypes = [ctypes.wintypes.HMENU, ctypes.wintypes.UINT, UINT_PTR, ctypes.wintypes.LPCWSTR]
user32.AppendMenuW.restype = ctypes.wintypes.BOOL

user32.InsertMenuItemW.argtypes = [ctypes.wintypes.HMENU, ctypes.wintypes.UINT, ctypes.wintypes.BOOL, ctypes.c_void_p]
user32.InsertMenuItemW.restype = ctypes.wintypes.BOOL

user32.CreatePopupMenu.argtypes = []
user32.CreatePopupMenu.restype = ctypes.wintypes.HMENU

user32.TrackPopupMenu.argtypes = [ctypes.wintypes.HMENU, ctypes.wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.wintypes.HWND, ctypes.c_void_p]
user32.TrackPopupMenu.restype = ctypes.wintypes.BOOL

user32.TrackPopupMenuEx.argtypes = [ctypes.wintypes.HMENU, ctypes.wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.wintypes.HWND, ctypes.c_void_p]
user32.TrackPopupMenuEx.restype = ctypes.wintypes.BOOL

user32.DestroyMenu.argtypes = [ctypes.wintypes.HMENU]
user32.DestroyMenu.restype = ctypes.wintypes.BOOL

user32.SetForegroundWindow.argtypes = [ctypes.wintypes.HWND]
user32.SetForegroundWindow.restype = ctypes.wintypes.BOOL

user32.PostMessageW.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.UINT, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM]
user32.PostMessageW.restype = ctypes.wintypes.BOOL

user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype = ctypes.wintypes.BOOL

user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.RegisterClassExW.restype = ctypes.wintypes.ATOM

user32.CreateWindowExW.argtypes = [ctypes.wintypes.DWORD, ctypes.wintypes.LPCWSTR, ctypes.wintypes.LPCWSTR, ctypes.wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.wintypes.HWND, ctypes.wintypes.HMENU, ctypes.wintypes.HINSTANCE, ctypes.c_void_p]
user32.CreateWindowExW.restype = ctypes.wintypes.HWND

user32.DefWindowProcW.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.UINT, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_long

user32.LoadImageW.argtypes = [ctypes.wintypes.HINSTANCE, ctypes.wintypes.LPCWSTR, ctypes.wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.wintypes.UINT]
user32.LoadImageW.restype = ctypes.wintypes.HANDLE


# ─── uxtheme dark mode APIs (Windows 10 1903+) ──────────────────────────────
_uxtheme = ctypes.windll.uxtheme
_SetPreferredAppMode = _uxtheme[135]
_FlushMenuThemes = _uxtheme[136]
DARK_MODE = 1


def _is_system_dark_mode() -> bool:
    """Check if Windows system is using dark mode for apps."""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return value == 0
    except Exception:
        return False


def _apply_dark_mode_to_hwnd(hwnd):
    """Apply immersive dark mode to a window via DWM API."""
    try:
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(ctypes.c_int(1)),
            ctypes.sizeof(ctypes.c_int),
        )
    except Exception:
        pass


def _enable_dark_mode():
    """Enable dark mode for the app — must be called before UI creation."""
    try:
        _SetPreferredAppMode(DARK_MODE)
    except Exception:
        pass


def _set_dpi_awareness() -> None:
    """Set process DPI awareness to fix blurry menus on high-DPI displays."""
    try:
        # Windows 10 1607+: Per-Monitor V2 DPI awareness (best for mixed-DPI setups)
        DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        ctypes.windll.user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
    except Exception:
        try:
            # Windows 8.1+: Per-Monitor DPI awareness
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                # Windows Vista+: System DPI awareness (fallback)
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


# ─── Native Win32 Tray Icon ──────────────────────────────────────────────────

_hwnd_tray = None
_hicon_tray = None
_nid = None
_channel_names = list(CHANNEL_LABELS.keys())
_wnd_proc_ref = None  # prevent GC of callback


def _load_icon() -> int:
    """Load the application icon at high resolution for crisp rendering."""
    if ICON_FILE.exists():
        # Load at 256x256 for high-DPI tray icons (system will scale down as needed)
        h = user32.LoadImageW(None, str(ICON_FILE), IMAGE_ICON, 256, 256, LR_LOADFROMFILE)
        if h:
            return h
    return user32.LoadIconW(None, IDI_APPLICATION)


def _create_tray_window() -> int:
    """Create a hidden message-only window for tray icon callbacks."""
    global _wnd_proc_ref

    hInstance = kernel32.GetModuleHandleW(None)
    className = "ClaudeBeepTrayWnd"

    # Define window procedure
    def wnd_proc(hwnd, msg, wparam, lparam):
        if msg == WM_TRAYICON:
            if lparam == WM_RBUTTONUP:
                _show_context_menu(hwnd)
            elif lparam == WM_LBUTTONUP:
                _open_ui()
            return 0
        elif msg == WM_COMMAND:
            _handle_command(hwnd, wparam)
            return 0
        elif msg == WM_DESTROY:
            _remove_tray_icon()
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    _wnd_proc_ref = WNDPROC(wnd_proc)  # prevent GC

    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
    wc.lpfnWndProc = _wnd_proc_ref
    wc.hInstance = hInstance
    wc.lpszClassName = className
    wc.hIcon = _load_icon()
    user32.RegisterClassExW(ctypes.byref(wc))

    hwnd = user32.CreateWindowExW(
        0, className, "ClaudeBeepTray", 0,
        0, 0, 0, 0,
        None, None, hInstance, None
    )
    return hwnd


def _add_tray_icon(hwnd: int) -> None:
    """Add the tray icon to the system notification area."""
    global _nid
    _nid = NOTIFYICONDATAW()
    _nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
    _nid.hWnd = hwnd
    _nid.uID = 1
    _nid.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP
    _nid.uCallbackMessage = WM_TRAYICON
    _nid.hIcon = _load_icon()
    _nid.szTip = f"{APP_NAME} v{APP_VERSION}"
    shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(_nid))


def _remove_tray_icon() -> None:
    """Remove the tray icon."""
    if _nid:
        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(_nid))


def _update_tray_tooltip(text: str) -> None:
    """Update the tray icon tooltip."""
    if _nid:
        _nid.szTip = text[:127]
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(_nid))


def _build_channel_submenu() -> int:
    """Build the notification source submenu with checkmarks."""
    hMenu = user32.CreatePopupMenu()
    cfg = _load_config()
    for i, (name, label) in enumerate(CHANNEL_LABELS.items()):
        flags = MF_STRING
        if cfg.get(name, {}).get("enabled"):
            flags |= MF_CHECKED
        if not _is_channel_configured(name):
            flags |= MF_GRAYED
        user32.AppendMenuW(hMenu, flags, CMD_CHANNEL_BASE + i, label)
    return hMenu


def _show_context_menu(hwnd: int) -> None:
    """Show the native right-click context menu."""
    hMenu = user32.CreatePopupMenu()

    # 打开主界面
    user32.AppendMenuW(hMenu, MF_STRING, CMD_OPEN_UI, "打开主界面")

    # 通知源管理 (submenu)
    hSubMenu = _build_channel_submenu()
    user32.AppendMenuW(hMenu, MF_STRING | MF_POPUP, hSubMenu, "通知源管理")

    user32.AppendMenuW(hMenu, MF_SEPARATOR, 0, None)

    # 安装/卸载所有 Hook
    user32.AppendMenuW(hMenu, MF_STRING, CMD_INSTALL_HOOKS, "安装所有 Hook")
    user32.AppendMenuW(hMenu, MF_STRING, CMD_UNINSTALL_HOOKS, "卸载所有 Hook")

    # 开机自启动 (checkbox)
    flags_startup = MF_STRING
    if _is_startup_enabled():
        flags_startup |= MF_CHECKED
    user32.AppendMenuW(hMenu, flags_startup, CMD_STARTUP, "开机自启动")

    # 检查更新
    user32.AppendMenuW(hMenu, MF_STRING, CMD_CHECK_UPDATE, "检查更新")

    user32.AppendMenuW(hMenu, MF_SEPARATOR, 0, None)

    # 退出
    user32.AppendMenuW(hMenu, MF_STRING, CMD_QUIT, f"退出 (v{APP_VERSION})")

    # Get cursor position and show menu
    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))

    # Required: SetForegroundWindow before TrackPopupMenu for proper dismiss behavior
    user32.SetForegroundWindow(hwnd)
    user32.TrackPopupMenu(
        hMenu,
        TPM_RIGHTBUTTON | TPM_BOTTOMALIGN,
        pt.x, pt.y, 0, hwnd, None
    )
    # Required: PostMessage(WM_NULL) after TrackPopupMenu per MSDN
    user32.PostMessageW(hwnd, WM_NULL, 0, 0)
    user32.DestroyMenu(hMenu)


def _handle_command(hwnd: int, wparam: int) -> None:
    """Handle menu command selection."""
    cmd = wparam & 0xFFFF

    if cmd == CMD_OPEN_UI:
        _open_ui()
    elif cmd == CMD_INSTALL_HOOKS:
        threading.Thread(target=_install_hooks, daemon=True).start()
    elif cmd == CMD_UNINSTALL_HOOKS:
        threading.Thread(target=_uninstall_hooks, daemon=True).start()
    elif cmd == CMD_STARTUP:
        _toggle_startup()
    elif cmd == CMD_CHECK_UPDATE:
        threading.Thread(target=_check_updates, daemon=True).start()
    elif cmd == CMD_QUIT:
        _quit_tray()
    elif CMD_CHANNEL_BASE <= cmd < CMD_CHANNEL_BASE + len(_channel_names):
        idx = cmd - CMD_CHANNEL_BASE
        name = _channel_names[idx]
        _toggle_channel(name)


def _run_message_loop() -> None:
    """Run the Win32 message pump."""
    msg = ctypes.wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


def _run_tray() -> None:
    """Main tray icon loop using native Win32 APIs for crisp DPI rendering."""
    global _hwnd_tray, _hicon_tray

    _enable_dark_mode()
    _hicon_tray = _load_icon()
    _hwnd_tray = _create_tray_window()

    if not _hwnd_tray:
        _message_box("无法创建托盘窗口。", APP_NAME, 0x10)
        return

    _add_tray_icon(_hwnd_tray)

    # Start menu refresh thread
    threading.Thread(target=_menu_refresh_loop, args=(_hwnd_tray,), name="menu-refresh", daemon=True).start()

    # Run message pump (blocks until WM_QUIT)
    _run_message_loop()


def _menu_refresh_loop(hwnd: int) -> None:
    """Periodically update tooltip to reflect state changes."""
    last_config_mtime = _mtime(CONFIG_FILE)
    while not _stop_event.is_set():
        _stop_event.wait(5)
        config_mtime = _mtime(CONFIG_FILE)
        if config_mtime != last_config_mtime:
            last_config_mtime = config_mtime
            cfg = _load_config()
            enabled = sum(1 for ch in CHANNEL_LABELS if cfg.get(ch, {}).get("enabled"))
            _update_tray_tooltip(f"{APP_NAME} v{APP_VERSION} ({enabled} 渠道)")


# ─── Utility & business logic (unchanged) ────────────────────────────────────

def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _load_config() -> dict[str, Any]:
    import notify
    return notify.load_config()


def _save_config(cfg: dict[str, Any]) -> None:
    import notify
    notify.save_config(cfg)


def _is_channel_enabled(name: str) -> bool:
    return bool(_load_config().get(name, {}).get("enabled"))


def _is_channel_configured(name: str) -> bool:
    cfg = _load_config()
    data = cfg.get(name, {})
    if name == "windows_toast":
        return True
    if name == "weixin":
        return bool(data.get("bot_token") and data.get("to_user_id"))
    if name == "qq":
        return bool(data.get("app_id") and data.get("app_secret") and data.get("target_id"))
    if name == "telegram":
        return bool(data.get("bot_token") and data.get("chat_id"))
    if name == "feishu":
        return bool(data.get("app_id") and data.get("app_secret") and data.get("receive_id"))
    if name == "dingtalk":
        return bool(data.get("client_id") and data.get("client_secret") and data.get("user_id"))
    return False


def _toggle_channel(name: str, icon: Any = None) -> None:
    cfg = _load_config()
    cfg.setdefault(name, {})["enabled"] = not bool(cfg.get(name, {}).get("enabled"))
    _save_config(cfg)
    if name == "weixin":
        try:
            from channels.weixin import start_keepalive, stop_keepalive
            if cfg[name]["enabled"]:
                start_keepalive()
            else:
                stop_keepalive()
        except Exception:
            pass


def main() -> None:
    _set_dpi_awareness()

    if _should_delegate_to_notify():
        import notify
        notify.main()
        return

    if not _acquire_single_instance():
        _message_box("ClaudeBeep 已在运行。", APP_NAME, 0x40)
        return

    _ensure_runtime_dirs()
    _start_background_services()
    _run_tray()


def _should_delegate_to_notify() -> bool:
    args = set(sys.argv[1:])
    return bool(args & {"--type", "--install", "--uninstall", "--test", "--ui", "--from-stdin"})


def _ensure_runtime_dirs() -> None:
    (SCRIPT_DIR / "pending").mkdir(exist_ok=True)
    (SCRIPT_DIR / "responses").mkdir(exist_ok=True)
    (SCRIPT_DIR / "send_queue").mkdir(exist_ok=True)


def _acquire_single_instance() -> bool:
    global _mutex_handle
    if sys.platform != "win32":
        return True
    kernel32 = ctypes.windll.kernel32
    _mutex_handle = kernel32.CreateMutexW(None, False, "Global\\ClaudeBeepTray")
    return kernel32.GetLastError() != 183


def _start_background_services() -> None:
    threading.Thread(target=_heartbeat_loop, name="tray-heartbeat", daemon=True).start()
    threading.Thread(target=_cleanup_loop, name="cleanup", daemon=True).start()
    try:
        from channels.weixin import start_keepalive
        cfg = _load_config()
        if cfg.get("weixin", {}).get("enabled") and cfg.get("weixin", {}).get("bot_token"):
            start_keepalive()
    except Exception:
        pass


def _install_hooks() -> None:
    try:
        import notify
        notify.install_hooks()
        _message_box("Claude Code hooks 已安装。", APP_NAME, 0x40)
    except Exception as exc:
        _message_box(f"安装 hooks 失败：\n{exc}", APP_NAME, 0x10)


def _uninstall_hooks() -> None:
    try:
        import notify
        notify.uninstall_hooks()
        _message_box("Claude Code hooks 已卸载。", APP_NAME, 0x40)
    except Exception as exc:
        _message_box(f"卸载 hooks 失败：\n{exc}", APP_NAME, 0x10)


def _open_ui() -> None:
    global _ui_process
    if _ui_process and _ui_process.poll() is None:
        webbrowser.open("http://localhost:5100")
        return
    if getattr(sys, "frozen", False):
        cmd = [str(Path(sys.executable).resolve()), "--ui"]
    else:
        cmd = [sys.executable, str(SCRIPT_DIR / "notify.py"), "--ui"]
    _ui_process = subprocess.Popen(cmd, cwd=str(SCRIPT_DIR), creationflags=_creationflags())


def _creationflags() -> int:
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0


def _is_startup_enabled() -> bool:
    if sys.platform != "win32":
        return False
    cfg = _load_config()
    if not cfg.get("app", {}).get("auto_start", False):
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            winreg.QueryValueEx(key, APP_NAME)
        return True
    except OSError:
        return False


def _toggle_startup(icon: Any = None) -> None:
    if sys.platform != "win32":
        return
    cfg = _load_config()
    app_cfg = cfg.setdefault("app", {})
    new_state = not _is_startup_enabled()
    app_cfg["auto_start"] = new_state
    _save_config(cfg)
    run_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    approved_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_path, 0, winreg.KEY_SET_VALUE) as key:
        if not new_state:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except OSError:
                pass
        else:
            raw = sys.executable if getattr(sys, "frozen", False) else str(SCRIPT_DIR / "ClaudeBeep.exe")
            target = os.path.normpath(raw)
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{target}"')
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, approved_path, 0, winreg.KEY_SET_VALUE) as key:
            if new_state:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_BINARY, b'\x02' + b'\x00' * 11)
            else:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_BINARY, b'\x01' + b'\x00' * 11)
    except OSError:
        pass


def _check_updates() -> None:
    import updater
    try:
        info = updater.check_for_update(APP_VERSION)
        if not info:
            _message_box("当前已是最新版本。", APP_NAME, 0x40)
            return
        if _message_box(f"检测到新版本 {info['version']}，是否现在安装？", APP_NAME, 0x24) != 6:
            return
        if info.get("url"):
            success = updater.perform_update(info["url"], info["version"])
            if success:
                _quit_tray()
            else:
                _message_box("自动更新失败，正在打开下载页面...", APP_NAME, 0x10)
                webbrowser.open(f"https://github.com/{updater.GITHUB_OWNER}/{updater.GITHUB_REPO}/releases/latest")
        else:
            webbrowser.open(f"https://github.com/{updater.GITHUB_OWNER}/{updater.GITHUB_REPO}/releases/latest")
    except Exception as exc:
        _message_box(f"检查更新失败：\n{exc}", APP_NAME, 0x10)


def _quit_tray() -> None:
    _stop_event.set()
    if _hwnd_tray:
        user32.PostMessageW(_hwnd_tray, WM_DESTROY, 0, 0)
    else:
        os._exit(0)


def _heartbeat_loop() -> None:
    while not _stop_event.is_set():
        try:
            from channels.weixin import get_keepalive_status
            status = get_keepalive_status()
            HEARTBEAT_FILE.write_text(json.dumps({
                "ts": time.time(),
                "pid": os.getpid(),
                "weixin_keepalive": bool(status.get("running")),
            }), encoding="utf-8")
        except Exception:
            pass
        _stop_event.wait(15)


def _cleanup_loop() -> None:
    while not _stop_event.is_set():
        try:
            _cleanup_runtime_files()
        except Exception:
            pass
        cfg = _load_config()
        hours = int(cfg.get("app", {}).get("cleanup_interval_hours", 12) or 12)
        _stop_event.wait(max(1, hours) * 3600)


def _cleanup_runtime_files() -> None:
    import interaction
    interaction.cleanup_stale()
    now = time.time()
    for folder, max_age in ((SCRIPT_DIR, 24 * 3600), (SCRIPT_DIR / "responses", 7 * 24 * 3600)):
        if not folder.exists():
            continue
        for path in folder.glob("*.tmp"):
            _safe_unlink(path, now, max_age)
        if folder.name == "responses":
            for path in folder.glob("*.json"):
                _safe_unlink(path, now, max_age)
    send_queue = SCRIPT_DIR / "send_queue"
    if send_queue.exists():
        for path in send_queue.glob("*"):
            _safe_unlink(path, now, 120)
        try:
            if not any(send_queue.iterdir()):
                send_queue.rmdir()
        except Exception:
            pass
    _trim_log(SCRIPT_DIR / "notify.log", max_lines=1200)


def _safe_unlink(path: Path, now: float, max_age: int) -> None:
    try:
        if now - path.stat().st_mtime < max_age:
            return
        with open(path, "a", encoding="utf-8"):
            pass
        path.unlink(missing_ok=True)
    except Exception:
        pass


def _trim_log(path: Path, max_lines: int) -> None:
    try:
        if not path.exists() or time.time() - path.stat().st_mtime < 60:
            return
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        if len(lines) <= max_lines:
            return
        path.write_text("\n".join(lines[-max_lines:]) + "\n", encoding="utf-8")
    except Exception:
        pass


def _message_box(text: str, title: str, flags: int) -> int:
    if sys.platform == "win32":
        return ctypes.windll.user32.MessageBoxW(None, text, title, flags)
    print(f"{title}: {text}")
    return 0


if __name__ == "__main__":
    main()
