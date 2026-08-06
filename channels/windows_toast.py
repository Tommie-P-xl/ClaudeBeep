"""Windows 原生 Toast 通知渠道。使用 PowerShell + WinRT（支持自定义图标）。"""

import subprocess
import sys
from pathlib import Path
from typing import Dict, Any
from .base import NotificationChannel
from common.log import log as _log

# 图标路径：优先使用 PNG，ICO 作为回退
_SCRIPT_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
_RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", _SCRIPT_DIR))
_ICON_PNG = _RESOURCE_DIR / "assets" / "icon.png"
_ICON_ICO = _RESOURCE_DIR / "assets" / "icon.ico"
_ICON_PATH = str(_ICON_PNG if _ICON_PNG.exists() else _ICON_ICO)

# 可用的提示音映射
_SOUND_MAP = {
    "default": "Default",
    "reminder": "Reminder",
    "alarm": "LoopingAlarm",
    "call": "LoopingCall",
    "mail": "Mail",
    "im": "IM",
    "sms": "SMS",
    "silent": "Silent",
}

# 按来源平台选择 Toast 应用名（Q5：Codex 通知不再显示 "Claude Code"）
_APP_ID_BY_PLATFORM = {
    "claude_code": "Claude Code",
    "codex": "Codex",
}


class WindowsToastChannel(NotificationChannel):
    """发送 Windows Toast 通知"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._toast_config = config.get("windows_toast", {})

    @property
    def name(self) -> str:
        return "windows_toast"

    def is_enabled(self) -> bool:
        return self._toast_config.get("enabled", True)

    def _resolve_app_id(self) -> str:
        """按平台选择通知 App ID，未知平台回退到 Claude Code。"""
        return _APP_ID_BY_PLATFORM.get(self.platform, "Claude Code")

    def send(self, title: str, message: str) -> bool:
        """发送 Windows Toast 通知

        使用 PowerShell + WinRT（支持 placement="appLogoOverride" 显示自定义图标），
        使用 CREATE_NO_WINDOW 隐藏 PowerShell 窗口。
        """
        return self._send_powershell(title, message)

    def _send_powershell(self, title: str, message: str) -> bool:
        """PowerShell + WinRT 发送"""
        duration_ms = self._toast_config.get("duration_ms", 5000)
        sound_name = self._toast_config.get("sound", "reminder").lower()
        sound_attr = _SOUND_MAP.get(sound_name, "Reminder")
        audio_src = f"ms-winsoundevent:Notification.{sound_attr}"
        app_id = self._resolve_app_id()
        toast_xml = f"""<toast duration="short">
  <visual>
    <binding template="ToastImageAndText02">
      <image id="1" src="{_ICON_PATH}" placement="appLogoOverride" hint-crop="circle"/>
      <text id="1">{self._escape_xml(title)}</text>
      <text id="2">{self._escape_xml(message)}</text>
    </binding>
  </visual>
  <audio src="{audio_src}" />
</toast>"""
        ps_script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml('{toast_xml}')
$toast = New-Object Windows.UI.Notifications.ToastNotification($xml)
$toast.ExpirationTime = [DateTimeOffset]::Now.AddMilliseconds({duration_ms})
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("{app_id}").Show($toast)
"""
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                capture_output=True, text=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if result.returncode != 0:
                _log(f"[windows_toast] PowerShell 发送失败: {(result.stderr or '').strip()[:200]}")
                return False
            return True
        except subprocess.TimeoutExpired:
            _log("[windows_toast] PowerShell 发送超时")
            return False
        except FileNotFoundError:
            _log("[windows_toast] 系统未找到 PowerShell")
            return False

    @staticmethod
    def _escape_xml(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;")
