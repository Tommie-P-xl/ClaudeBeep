"""跨进程 access_token 文件缓存（P1）。

QQ / 飞书 / 钉钉每次 hook 都是新进程，实例内 token 缓存跨进程失效，
导致每次发送都重复请求换取 token。此处把 token 持久化到运行时目录文件，
带过期时间，命中即复用，减少冷启动开销。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from common.paths import RUNTIME_DIR


def _cache_file(name: str) -> Path:
    return RUNTIME_DIR / f"token_cache_{name}.json"


def get_cached_token(name: str, ttl: float = 6600.0) -> str:
    """读取缓存 token；不存在或已过期返回空串。"""
    path = _cache_file(name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - float(data.get("ts", 0)) < ttl:
            return str(data.get("token", ""))
    except Exception:
        pass
    return ""


def set_cached_token(name: str, token: str) -> None:
    """写入缓存 token（原子替换，失败静默）。"""
    if not token:
        return
    try:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        path = _cache_file(name)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(
            json.dumps({"ts": time.time(), "token": token}, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except Exception:
        pass
