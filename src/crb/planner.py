"""批量规划：多活动 → 查空闲教室 → 分配 → 冲突检测 → 生成/保存申请。

设计原则
--------
* 纯本地编排，不额外调 LLM：输入已经是结构化活动列表；
* 冲突检测同时考虑「容量」和「本批次内同教室同时段重复占用」；
* 默认只出方案（dry-run），加 ``--save`` 才写入草稿。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import api
from .models import Activity, Applicant, Assignment, BorrowRequest, FreeRoomSlot
from .session import Session
from .utils import parse_period, periods_overlap


# ---------------------------------------------------------------- 输入
def load_plan(path: Path) -> tuple[Applicant, list[Activity]]:
    """读取 plan 文件。支持两种格式：

    1. 活动数组 ``[{...}, {...}]``
    2. ``{"defaults": {...}, "activities": [{...}]}``
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        defaults: dict[str, Any] = {}
        items = raw
    elif isinstance(raw, dict):
        defaults = raw.get("defaults") or {}
        items = raw.get("activities") or raw.get("items") or []
    else:
        raise ValueError("plan 文件必须是数组，或含 activities 的对象")
    return Applicant.model_validate(defaults), [Activity.model_validate(x) for x in items]


def _capacity(room: FreeRoomSlot) -> int:
    return int(room.seat_class or room.seat_exam or 0)


def _is_conflict(
    room: FreeRoomSlot,
    day: str,
    a1: int,
    a2: int,
    used: dict[tuple[str, str], list[tuple[int, int]]],
) -> bool:
    key = (room.room_name, day)
    return any(periods_overlap(a1, a2, p1, p2) for p1, p2 in used.get(key, []))


# ---------------------------------------------------------------- 规划
def build_plan(
    session: Session,
    activities: list[Activity],
    applicant: Applicant,
) -> list[Assignment]:
    """为每条活动分配一间空闲教室，并做批次内冲突检测。"""
    used: dict[tuple[str, str], list[tuple[int, int]]] = {}
    results: list[Assignment] = []

    for act in activities:
        campus = act.campus or applicant.campus
        building = act.building or applicant.building
        room_type = act.room_type or applicant.room_type
        try:
            a1, a2 = parse_period(act.period)
        except ValueError:
            results.append(
                Assignment(activity=act, status="error", note=f"节次格式错误：{act.period}")
            )
            continue

        try:
            rooms = api.free_rooms(
                session,
                campus_id=campus,
                day=act.date,
                start_period=a1,
                end_period=a2,
                building_id=building,
                room_type=room_type,
            )
        except Exception as exc:  # noqa: BLE001
            results.append(Assignment(activity=act, status="error", note=f"查询失败：{exc}"))
            continue

        if not rooms:
            results.append(Assignment(activity=act, status="no_room", note="该时段无空闲教室"))
            continue

        big = [r for r in rooms if _capacity(r) >= act.people]
        if not big:
            results.append(
                Assignment(
                    activity=act,
                    status="too_small",
                    note=f"有 {len(rooms)} 间空闲教室，但容量均 < {act.people} 人",
                )
            )
            continue

        avail = [r for r in big if not _is_conflict(r, act.date, a1, a2, used)]
        if not avail:
            results.append(
                Assignment(activity=act, status="no_room", note="候选教室已被本批次其它活动占用")
            )
            continue

        chosen: FreeRoomSlot | None = None
        pref_missed = False
        if act.preferred_room:
            chosen = next((r for r in avail if r.room_name == act.preferred_room), None)
            pref_missed = chosen is None
        if chosen is None:
            # 容量刚好够用的优先，避免占用大教室
            chosen = sorted(avail, key=lambda r: (_capacity(r), r.room_name))[0]

        used.setdefault((chosen.room_name, act.date), []).append((a1, a2))
        note = f"意向教室 {act.preferred_room} 不可用，已改选" if pref_missed else ""
        results.append(Assignment(activity=act, room=chosen, status="ok", note=note))

    return results


# ---------------------------------------------------------------- 转成申请
def to_request(
    session: Session,
    assignment: Assignment,
    applicant: Applicant,
    term: str,
    week_cache: dict[str, dict[str, Any]] | None = None,
    room_in_purpose: bool = True,
) -> BorrowRequest:
    """把一条分配结果转成学校接口需要的申请对象。"""
    act = assignment.activity
    room = assignment.room
    a1, a2 = parse_period(act.period)

    week_cache = week_cache if week_cache is not None else {}
    if act.date not in week_cache:
        week_cache[act.date] = api.date_to_week(session, term, act.date)
    info = week_cache[act.date]
    if not info.get("ZC") or not info.get("XQJ"):
        raise RuntimeError(f"无法把 {act.date} 换算成周次/星期（校历可能未配置）")

    title = act.title
    if room_in_purpose and room:
        title = f"{title}（意向：{room.room_name}）"

    return BorrowRequest(
        JYDWDM=act.JYDWDM or applicant.JYDWDM,
        JYRXM=act.JYRXM or applicant.JYRXM,
        JYRDH=act.JYRDH or applicant.JYRDH,
        JYYTMS=title,
        JSJYLXDM=act.JSJYLXDM or applicant.JSJYLXDM,
        XXXQDM=act.campus or applicant.campus,
        JSRL=str(_capacity(room) if room else ""),
        XNXQDM=term,
        KSRQ=act.date,
        JSRQ=act.date,
        XQ=str(info["XQJ"]),
        ZC=str(info["ZC"]),
        KSJC=str(a1),
        JSJC=str(a2),
        ZRS=str(act.people),
        FJ=(room.room_name if room else ""),
    )


def save_plan(
    session: Session,
    assignments: list[Assignment],
    applicant: Applicant,
    room_in_purpose: bool = True,
) -> list[dict[str, Any]]:
    """把方案批量保存为草稿，返回逐条结果。"""
    term = api.current_term(session)
    week_cache: dict[str, dict[str, Any]] = {}
    out: list[dict[str, Any]] = []

    for a in assignments:
        if a.status != "ok":
            out.append({"title": a.activity.title, "ok": False, "msg": a.note or a.status})
            continue
        try:
            req = to_request(session, a, applicant, term, week_cache, room_in_purpose)
        except Exception as exc:  # noqa: BLE001
            out.append({"title": a.activity.title, "ok": False, "msg": f"生成申请失败：{exc}"})
            continue
        a.request = req.as_payload()
        res = api.save_borrow(session, req)
        out.append({"title": a.activity.title, "ok": res.ok, "msg": res.msg or str(res.code)})

    return out
