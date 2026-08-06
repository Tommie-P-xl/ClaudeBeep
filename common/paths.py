"""统一路径（S3）：frozen（打包安装）模式下运行时数据写入 %APPDATA%\\ClaudeBeep，
避免写入 Program Files 无权限；开发模式使用项目目录（本身可写）。

程序资源（static/assets/hook bat）仍在 SCRIPT_DIR（frozen 时为 exe 所在目录）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def script_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


SCRIPT_DIR = script_dir()


def runtime_dir() -> Path:
    """运行时数据目录：frozen 模式 %APPDATA%\\ClaudeBeep，开发模式项目目录。"""
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
        return base / "ClaudeBeep"
    return SCRIPT_DIR


RUNTIME_DIR = runtime_dir()
