"""借用人档案：姓名 / 手机号 / 单位。

登录时采集一次，之后 `plan` / `borrow` 自动复用，避免每次手填。
保存在 ``~/.crb/profile.json``（可用环境变量 CRB_PROFILE_FILE 覆盖）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def path() -> Path:
    env = os.environ.get("CRB_PROFILE_FILE")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".crb" / "profile.json"


def load() -> dict[str, Any]:
    p = path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save(data: dict[str, Any]) -> Path:
    """合并写入档案。"""
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    cur = load()
    cur.update({k: v for k, v in data.items() if v not in (None, "")})
    p.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        p.chmod(0o600)
    except OSError:
        pass
    return p
