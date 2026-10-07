"""借用人档案：姓名 / 手机号 / 单位。

登录时采集一次，之后 `plan` / `borrow` 自动复用，避免每次手填。
保存在 ``~/.crb/profile.json``（可用环境变量 CRB_PROFILE_FILE 覆盖）。

文件里有**两层**，别混：

* **账号档案段**（``account`` / ``account_name`` / ``account_org``）——
  「这个账号本人是谁」，也就是**全局默认的借用人身份**。只有
  :func:`save_identity` 能写它：`crb login` 采集、`crb plan` 发现账号变了
  自动重采、`crb profile --name` 是显式改档。**通用写路径碰不到它。**
* **通用字段**（``JYRXM`` / ``JYDWDM`` / ``JYRDH`` / ``campus`` / 契约…）——
  手机号、默认校区，以及给旧档案/旧下游留的姓名/单位兼容写法。

为什么要分成两层（2026-10-07 服务器上的事故）：8787 申请口的 agent 把某位访客
点名的「卢佳铭」写进了 ``JYRXM``，把账号本人的姓名**从档案里抹掉**了 ——
账号又没换，于是「换账号就重学」那条自愈也不会触发，之后所有访客的申请
（包括别人借的）借用人都成了卢佳铭。现在的规矩：账号自带的姓名/单位有它
自己的家，**单次覆盖写不进那个家**；要「以某人名义借」就传 plan 的
``defaults``（单次，由调用方自己负责），或走 ``crb profile``（显式改档）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

#: 账号档案段的键。**只有 `save_identity()` 写它们**——通用 `save()` 会跳过。
ACCOUNT_KEYS = ("account", "account_name", "account_org")


def path() -> Path:
    env = os.environ.get("CRB_PROFILE_FILE")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".crb" / "profile.json"


def load(target: Path | None = None) -> dict[str, Any]:
    p = target if target is not None else path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save(data: dict[str, Any], target: Path | None = None) -> Path:
    """合并写入档案（**账号档案段不在此路径被改写**：``ACCOUNT_KEYS`` 一律忽略）。

    忽略而不是报错，是给「下游程序顺手把自己那份姓名也存进档案」留活口：
    以前这么做会顶掉账号本人（见模块 docstring 里那场事故），现在它只是个
    通用字段的写入，账号档案段照旧。真要以某人名义借，请把值放进 plan 的
    ``defaults``（单次），或显式跑 ``crb profile --name``。
    """
    p = target if target is not None else path()
    p.parent.mkdir(parents=True, exist_ok=True)
    cur = load(p)
    cur.update({k: v for k, v in data.items() if v not in (None, "") and k not in ACCOUNT_KEYS})
    return _write(p, cur)


def save_identity(
    *,
    account: str = "",
    name: str = "",
    org: str = "",
    target: Path | None = None,
) -> Path:
    """写**账号档案段**（姓名/单位来自学校账号）。空值不写 —— 别把已知的抹掉。"""
    p = target if target is not None else path()
    p.parent.mkdir(parents=True, exist_ok=True)
    cur = load(p)
    if account:
        cur["account"] = account
    if name:
        cur["account_name"] = name
    if org:
        cur["account_org"] = org
    return _write(p, cur)


def identity(prof: dict[str, Any] | None = None) -> dict[str, str]:
    """读账号档案段（缺的给空串，不猜）。"""
    data = load() if prof is None else prof
    return {
        "account": str(data.get("account") or ""),
        "name": str(data.get("account_name") or ""),
        "org": str(data.get("account_org") or ""),
    }


def defaults(prof: dict[str, Any] | None = None) -> dict[str, Any]:
    """`plan` 用的默认层：**账号档案段优先于通用字段**。

    账号本人的姓名/单位是「全局默认」——哪怕通用字段被谁写脏了（旧版下游、
    手工改档、上一场事故留下的尾巴），只要账号档案段在，默认就是账号本人。
    老档案（没有账号档案段）仍旧走 ``JYRXM`` / ``JYDWDM``，行为不变。
    """
    out = dict(load() if prof is None else prof)
    ident = identity(out)
    if ident["name"]:
        out["JYRXM"] = ident["name"]
    if ident["org"]:
        out["JYDWDM"] = ident["org"]
    return out


def _write(p: Path, data: dict[str, Any]) -> Path:
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        p.chmod(0o600)
    except OSError:
        pass
    return p
