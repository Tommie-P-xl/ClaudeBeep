"""统一日志模块：追加写 notify.log + 敏感信息脱敏工具。

所有模块通过 common.log.log() 写入日志，避免各文件重复实现 _log()，
并在写入前对含敏感字段名的值统一打码（S1 / Q2）。

M11：日志文件内置基于大小的滚动（超过 1MB 时保留尾部约 512KB），
不再依赖托盘进程的定期清理，Web UI / hook 独立运行时日志也不会无限增长。
"""

from __future__ import annotations

import os
import re
import threading
from datetime import datetime
from pathlib import Path

from common.paths import RUNTIME_DIR

LOG_FILE = RUNTIME_DIR / "notify.log"

_lock = threading.Lock()

_MAX_LOG_BYTES = 1_000_000
_KEEP_TAIL_BYTES = 512_000


def _roll_log_if_needed(path: Path) -> None:
    """日志超过 _MAX_LOG_BYTES 时截断为尾部 _KEEP_TAIL_BYTES（调用方须已持有 _lock）。"""
    try:
        if path.stat().st_size <= _MAX_LOG_BYTES:
            return
        with open(path, "rb") as f:
            f.seek(-_KEEP_TAIL_BYTES, os.SEEK_END)
            tail = f.read().decode("utf-8", errors="replace")
        # 丢弃可能残缺的首行
        tail = tail.split("\n", 1)[-1]
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(tail, encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        pass


def log(component: str, msg: str) -> None:
    """追加写一行日志，component 标识来源模块。"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with _lock:
            _roll_log_if_needed(LOG_FILE)
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
