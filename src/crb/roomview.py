"""教室视角：回答「**这一间教室**在某天哪些节空闲」。

为什么单开一层
--------------
学校只给了一个权威口径：「某天某节次区间 → 空闲教室列表」（``cxkxjs.do``，
见 :func:`crb.api.free_rooms`）。要反过来问「这间教室这天怎么样」，只能围着它做。

实测（2026-09-28，教师号只读探针）：

* **区间语义是「整个区间都空闲」**：`1-2` 的结果 = `1` 与 `2` 的交集
  （逐节对拍验证过）。所以单节状态要用**单节查询**来问；
* 占用网格 ``cxjsqk.do``（JC1..JC20）与单教室详情 ``cxkxjsxq.do`` 都不可靠
  （列语义混乱、只回一部分占用），**不用**——宁可多打几发权威请求。

请求数：先按整段问一次（命中即「整天全空」，1 发）；没命中再逐节问，
最多 1 + 节次个数（默认 12）发。
"""

from __future__ import annotations

import re
from datetime import date as _date

from . import api
from .config import PERIOD_COUNT, PERIOD_TIMES
from .models import FreeRoomSlot, PeriodSlot, PeriodSpan, RoomInfo, RoomView
from .session import Session
from .utils import room_key, room_key_loose, slot_time, span_label, span_time

#: 候选最多给这么多间 —— 再多就不是「让用户挑一个」，是把列表倒给他。
CANDIDATE_LIMIT = 20

_WEEKDAYS = "一二三四五六日"

_DIGITS = re.compile(r"\d+")


def weekday_label(day: str) -> str:
    """``2026-09-30`` -> ``周三``；解析不了就回空串。"""
    try:
        return f"周{_WEEKDAYS[_date.fromisoformat(day).weekday()]}"
    except ValueError:
        return ""


def _dedupe(rooms: list[FreeRoomSlot]) -> list[FreeRoomSlot]:
    """同名同楼只留一条 —— 学校数据里「专用教室」这种名字会重复出现。"""
    seen: set[tuple[str, str]] = set()
    out: list[FreeRoomSlot] = []
    for room in rooms:
        key = (room_key(room.room_name), str(room.building_id or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(room)
    return out


def _by_loose_key(rooms: list[FreeRoomSlot], key: str) -> list[FreeRoomSlot]:
    return [r for r in rooms if room_key_loose(r.room_name) == key]


def match_room(
    rooms: list[FreeRoomSlot], query: str
) -> tuple[FreeRoomSlot | None, list[FreeRoomSlot]]:
    """把用户嘴里的教室名对到真实教室。

    返回 ``(命中的那一间, 候选)``：命中时候选为空；对不上或对上一堆时候选非空
    （调用方**不要**自己挑一个 —— 这是这一个项目里最贵的错：教室猜错会借到别的房间）。

    匹配顺序：

    1. 严格同名（``仙Ⅰ-501`` = ``仙I-501``）；
    2. 宽松同名（``仙一`` = ``仙Ⅰ`` = ``仙I``）；
    3. 包含（用户只说「501」）；
    4. 按号码兜底（用户说「新教501」——楼名对不上，但号码能对上几间）。

    **1~3 对上一间才敢说「就是它」**；第 4 条一律只给候选：前缀都没对上，
    再唯一也只是「像」，不该替用户拍板。
    """
    strict = room_key(query)
    loose = room_key_loose(query)
    if not strict:
        return None, []

    hits = _dedupe(
        [
            r
            for r in rooms
            if room_key(r.room_name) == strict or room_key_loose(r.room_name) == loose
        ]
    )
    if not hits:
        hits = _dedupe(
            [
                r
                for r in rooms
                if strict in room_key(r.room_name) or loose in room_key_loose(r.room_name)
            ]
        )
    if hits:
        if len(hits) == 1:
            return hits[0], []
        return None, _candidates(hits)

    numbers = _DIGITS.findall(loose)
    if not numbers:
        return None, []
    wanted = _room_number(loose)
    if not wanted:
        return None, []
    near = _dedupe([r for r in rooms if _room_number(room_key_loose(r.room_name)) == wanted])
    return None, _candidates(near)


def _room_number(text: str) -> str:
    """从名字里取「房号」：最后一段数字的末三位。

    楼号会和房号粘在一起（``仙Ⅰ-501`` 的宽松键是 ``仙1501``，``仙Ⅱ-501`` 是
    ``仙2501``），所以只能拿末三位比 —— 这也是号码兜底只用**相等**、
    不搞相似度的原因：这里已经够糊了，宁可多给候选、让人来挑。
    """
    groups = _DIGITS.findall(text)
    tail = groups[-1][-3:] if groups else ""
    return tail if len(tail) == 3 else ""


def _candidates(hits: list[FreeRoomSlot]) -> list[FreeRoomSlot]:
    hits.sort(key=lambda r: (str(r.building_id or ""), room_key(r.room_name)))
    return hits[:CANDIDATE_LIMIT]


def _spans(periods: list[int]) -> list[PeriodSpan]:
    """把一串节次压成连续段：``[1, 2, 5, 6, 7]`` -> ``1-2``、``5-7``。"""
    out: list[PeriodSpan] = []
    start: int | None = None
    prev: int | None = None
    for p in sorted(periods):
        if start is None:
            start = prev = p
        elif p == (prev or 0) + 1:
            prev = p
        else:
            out.append(_span(start, prev or start))
            start = prev = p
    if start is not None:
        out.append(_span(start, prev or start))
    return out


def _span(a1: int, a2: int) -> PeriodSpan:
    return PeriodSpan(label=span_label(a1, a2), start=a1, end=a2, time=span_time(a1, a2))


def room_day(
    session: Session,
    *,
    campus_id: str,
    day: str,
    room: str,
    building_id: str | None = None,
    start_period: int = 1,
    end_period: int = PERIOD_COUNT,
) -> RoomView:
    """「这一间教室这天各节空闲吗」——学校权威口径。"""
    view = RoomView(campus=campus_id, date=day, weekday=weekday_label(day))
    rooms = api.all_rooms(session, campus_id=campus_id, building_id=building_id, day=day)
    matched, candidates = match_room(rooms, room)
    if matched is None:
        view.status = "ambiguous" if candidates else "not_found"
        view.candidates = [RoomInfo.of(r) for r in candidates]
        return view

    view.room = RoomInfo.of(matched)
    bid = matched.building_id or building_id
    wanted = room_key(matched.room_name)

    def is_free(p1: int, p2: int) -> bool:
        rows = api.free_rooms(
            session,
            campus_id=campus_id,
            day=day,
            start_period=p1,
            end_period=p2,
            building_id=bid,
        )
        return any(room_key(r.room_name) == wanted for r in rows)

    # 先整段问一次：命中 = 这个区间每一节都空闲（区间语义是「全空」）。
    free_periods: set[int] = set()
    if is_free(start_period, end_period):
        free_periods = set(range(start_period, end_period + 1))
    else:
        for p in range(start_period, end_period + 1):
            if p in PERIOD_TIMES and is_free(p, p):
                free_periods.add(p)

    all_periods = [p for p in range(start_period, end_period + 1) if p in PERIOD_TIMES]
    view.periods = [
        PeriodSlot(period=p, time=slot_time(p), free=p in free_periods) for p in all_periods
    ]
    view.free_spans = _spans(sorted(free_periods))
    view.occupied_spans = _spans([p for p in all_periods if p not in free_periods])
    return view
