"""学校后端接口封装。

全部接口都通过 :class:`crb.session.Session` 携带登录态调用，
不依赖浏览器 UI（学校前端的下拉框有 bug，直连接口更稳）。

对应探测记录：docs/reference/nju-classroom-agent-findings.md
"""

from __future__ import annotations

import json
from datetime import date as _date
from typing import Any

from .config import (
    CAMPUSES,
    EP_BORROW_TYPE,
    EP_BUILDING,
    EP_CALENDAR,
    EP_CAMPUS,
    EP_DATE_TO_WEEK,
    EP_DELETE,
    EP_FREE_ROOMS,
    EP_LIST,
    EP_ORG,
    EP_ROOM_TYPE,
    EP_SAVE,
    EP_SYS_PARAMS,
    EP_TERM,
)
from .models import BorrowRecord, BorrowRequest, Building, Campus, FreeRoom, SaveResult
from .session import Session


# ---------------------------------------------------------------- 基础工具
def _datas(resp: Any) -> dict[str, Any]:
    if not isinstance(resp, dict):
        raise RuntimeError(f"接口返回异常：{resp!r}")
    return resp.get("datas") or {}


def _rows(resp: Any, key: str) -> list[dict[str, Any]]:
    return list(_datas(resp).get(key, {}).get("rows") or [])


def _query_setting(items: list[dict[str, Any]]) -> str:
    """构造 emapdatatable 的高级查询 JSON。"""
    return json.dumps(items, ensure_ascii=False, separators=(",", ":"))


def _cond(name: str, value: str, builder: str = "equal", link: str = "AND") -> dict[str, Any]:
    return {"name": name, "value": value, "builder": builder, "linkOpt": link}


# ---------------------------------------------------------------- 字典
def campuses(session: Session) -> list[Campus]:
    rows = _rows(session.post_form(EP_CAMPUS), "code")
    if rows:
        return [Campus(id=str(r["id"]), name=str(r["name"])) for r in rows]
    return [Campus(id=k, name=v) for k, v in CAMPUSES.items()]


def buildings(session: Session, campus_id: str) -> list[Building]:
    rows = _rows(session.post_form(EP_BUILDING, {"XXXQDM": campus_id}), "jxlcx")
    return [Building.model_validate(r) for r in rows]


def room_types(session: Session) -> list[dict[str, Any]]:
    resp = session.post_form(EP_ROOM_TYPE)
    rows = _rows(resp, "code") or _rows(resp, "rows")
    return rows


def system_params(session: Session) -> dict[str, Any]:
    """系统参数：当前学期、借用开关、可借日期范围等。"""
    rows = _rows(session.post_form(EP_SYS_PARAMS), "cxxtcs")
    if not rows:
        return {}
    return dict(rows[0])


def current_term(session: Session) -> str:
    """当前学年学期，例如 2026-2027-1。"""
    params = system_params(session)
    if params.get("DQXNXQDM"):
        return str(params["DQXNXQDM"])
    rows = _rows(session.post_form(EP_TERM), "cxdqxnxq")
    if rows:
        r = rows[0]
        return str(r.get("XNXQDM") or r.get("DQXNXQDM") or "")
    return ""


def my_org(session: Session) -> dict[str, Any]:
    rows = _rows(session.post_form(EP_ORG), "cxyhszdw")
    return dict(rows[0]) if rows else {}


def borrow_types(session: Session) -> list[dict[str, Any]]:
    return _rows(session.post_form(EP_BORROW_TYPE), "cxjsjylx")


# ---------------------------------------------------------------- 日期 / 校历
def term_parts(term: str) -> tuple[str, str]:
    """2026-2027-1 -> ("2026-2027", "1")。"""
    parts = term.split("-")
    if len(parts) >= 3:
        return f"{parts[0]}-{parts[1]}", parts[2]
    raise ValueError(f"无法解析学年学期：{term!r}")


def date_to_week(session: Session, term: str, day: str) -> dict[str, Any]:
    """日期 -> {ZC: 周次, XQJ: 星期}。参数是 XN/XQ/RQ（不是 XNXQDM）。"""
    xn, xq = term_parts(term)
    rows = _rows(session.post_form(EP_DATE_TO_WEEK, {"XN": xn, "XQ": xq, "RQ": day}), "cxrqdydzcxq")
    return dict(rows[0]) if rows else {}


def calendar(session: Session, term: str) -> dict[str, Any]:
    """校历：学期开始日期、总周次等。"""
    xn, xq = term_parts(term)
    rows = _rows(session.post_form(EP_CALENDAR, {"XN": xn, "XQ": xq}), "cxxljxjszc")
    return dict(rows[0]) if rows else {}


# ---------------------------------------------------------------- 空闲教室
def free_rooms(
    session: Session,
    *,
    campus_id: str,
    day: str,
    term: str,
    building_id: str | None = None,
    room_type: str | None = None,
    week: str | None = None,
    weekday: str | None = None,
    page_size: int = 200,
) -> list[FreeRoom]:
    """查询某天某校区的空闲教室。

    week/weekday 不传时自动用 date_to_week 换算（需校历已配置）。
    """
    if week is None or weekday is None:
        info = date_to_week(session, term, day)
        week = week or str(info.get("ZC", ""))
        weekday = weekday or str(info.get("XQJ", ""))

    conds = [_cond("XXXQDM", campus_id)]
    if building_id:
        conds.append(_cond("JXLDM", building_id, builder="include"))
    if room_type:
        conds.append(_cond("JASLXDM", room_type))

    resp = session.post_form(
        EP_FREE_ROOMS,
        {
            "pageSize": page_size,
            "pageNumber": 1,
            "XNXQDM": term,
            "ZC": week,
            "XQ": weekday,
            "RQ": day,
            "querySetting": _query_setting(conds),
            "*order": "+LC,+JASMC",
        },
    )
    rooms: list[FreeRoom] = []
    for r in _rows(resp, "cxjsqk"):
        periods = {k: v for k, v in r.items() if k.startswith("JC")}
        room = FreeRoom.model_validate(r)
        room.periods = periods
        rooms.append(room)
    return rooms


# ---------------------------------------------------------------- 申请
def save_borrow(session: Session, req: BorrowRequest, submit: bool = False) -> SaveResult:
    """保存草稿或正式提交。

    默认只保存草稿（TYPE='save'）；submit=True 才是 TYPE='TJ'。
    """
    req.TYPE = "TJ" if submit else "save"
    resp = session.post_form(EP_SAVE, {"param": json.dumps([req.as_payload()], ensure_ascii=False)})
    ext = _datas(resp).get("xzjasjysq", {}).get("extParams", {}) or {}
    code = ext.get("code")
    return SaveResult(
        ok=(code == 1),
        code=code,
        msg=str(ext.get("msg", "")),
        raw=resp if isinstance(resp, dict) else None,
    )


def list_borrows(session: Session, term: str, page_size: int = 100) -> list[BorrowRecord]:
    resp = session.post_form(
        EP_LIST,
        {
            "pageSize": page_size,
            "pageNumber": 1,
            "XNXQDM": term,
            "*order": "-SQRQ",
            "querySetting": "[]",
        },
    )
    return [BorrowRecord.model_validate(r) for r in _rows(resp, "cxjsjysq")]


def delete_borrow(session: Session, sqbh: str) -> SaveResult:
    """删除申请/草稿（scjssq.do）。实测对草稿也生效。"""
    resp = session.post_form(EP_DELETE, {"param": json.dumps([{"SQBH": sqbh}], ensure_ascii=False)})
    ext = _datas(resp).get("scjssq", {}).get("extParams", {}) or {}
    code = ext.get("code")
    return SaveResult(ok=(code == 1), code=code, msg=str(ext.get("msg", "")), raw=resp)


# ---------------------------------------------------------------- 便捷函数
def today() -> str:
    return _date.today().isoformat()
