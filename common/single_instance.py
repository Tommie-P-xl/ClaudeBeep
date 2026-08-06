"""跨进程单实例与 UI 复用探测（根治多实例）。

1. 文件锁单实例：不依赖 Global 互斥体的会话/权限问题——进程持有锁文件句柄期间，
   其他实例无法获取锁；进程异常退出时 OS 自动释放句柄，不会死锁。
2. UI 服务探测：任何入口想打开 Web UI 前先探测 127.0.0.1:5100，
   已有本应用服务则直接复用，杜绝重复启动 Flask 进程。
"""

from __future__ import annotations

import json
import socket
import sys
import urllib.request

from common.paths import RUNTIME_DIR

UI_PORT = 5100
UI_STATUS_PATH = "/api/status"


def acquire_file_lock(name: str):
    """对 RUNTIME_DIR/<name>.lock 加非阻塞独占锁（Windows）。

    成功返回打开的文件对象（调用方须持有到进程结束，句柄关闭即释放锁）；
    失败（已有实例持有）返回 None。
    """
    if sys.platform != "win32":
        return None  # 项目主要面向 Windows；非 Windows 环境不强制单实例
    try:
        import msvcrt
    except ImportError:
        return None
    try:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        lock_file = open(RUNTIME_DIR / f"{name}.lock", "a+", encoding="utf-8")
        try:
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            lock_file.close()
            return None
        return lock_file
    except Exception:
        return None


def is_ui_running(timeout: float = 0.8, port: int = UI_PORT) -> bool:
    """探测本机是否已有 ClaudeBeep Web UI 服务。

    用 /api/status 响应中的专有字段（hooks_installed）区分，
    避免其他程序占用端口时误判。
    """
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}{UI_STATUS_PATH}")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return isinstance(data, dict) and "hooks_installed" in data
    except Exception:
        return False


def port_in_use(port: int = UI_PORT, timeout: float = 0.3) -> bool:
    """TCP 探测端口是否被占用（用于绑定前的快速检查）。"""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False
