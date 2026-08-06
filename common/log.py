"""统一日志模块：追加写 notify.log + 敏感信息脱敏工具。

所有模块通过 common.log.log() 写入日志，避免各文件重复实现 _log()，
并在写入前对含敏感字段名的值统一打码（S1 / Q2）。
"""

from __future__ import annotations

import re
import threading
from datetime import datetime
from pathlib import Path

from common.paths import RUNTIME_DIR

LOG_FILE = RUNTIME_DIR / "notify.log"

_lock = threading.Lock()


def log(component: str, msg: str) -> None:
    """追加写一行日志，component 标识来源模块。"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with _lock:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] [{component}] {msg}\n")
    except Exception:
        pass


# 字段名含以下关键词时，其值视为敏感信息，记录前自动打码
_SENSITIVE_KEY_PATTERN = re.compile(
    r"(token|secret|password|credential|openid|context|sync_buf|user_id)", re.IGNORECASE
)


def is_sensitive_key(key: str) -> bool:
    """判断字段名是否指向敏感信息。"""
    return bool(_SENSITIVE_KEY_PATTERN.search(key))


def redact(value) -> str:
    """把敏感值打码为 a***b 形式，避免明文落盘。"""
    s = str(value)
    if not s:
        return ""
    if len(s) <= 6:
        return "*" * len(s)
    return s[:2] + "*" * (len(s) - 4) + s[-2:]


def redact_key_value(key: str, value) -> str:
    """按字段名决定是否打码：敏感字段只输出打码值。"""
    if is_sensitive_key(key):
        return redact(value)
    return str(value)
