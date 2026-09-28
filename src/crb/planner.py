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
from .models import (
    Activity,
    Applicant,
    Assignment,
    BorrowRequest,
    ExistingBooking,
    FreeRoomSlot,
)
from .session import Session
from .utils import parse_period, periods_overlap, room_key


# ---------------------------------------------------------------- 档案
def apply_profile(applicant: Applicant, prof: dict[str, Any]) -> Applicant:
    """用本地档案补齐申请人的缺失字段（登录时采集）。"""
    for key in ("JYDWDM", "JYRXM", "JYRDH", "JSJYLXDM", "campus"):
        if not getattr(applicant, key, None) and prof.get(key):
            setattr(applicant, key, prof[key])
    return applicant


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


def _room_occupied(
    room: FreeRoomSlot,
    campus: str,
    day: str,
    a1: int,
    a2: int,
    used: dict[tuple[str, str, str], list[tuple[int, int]]],
) -> bool:
    """该教室在同校区同一天是否已被本批次或已有申请占用。"""
    key = (str(campus), room_key(room.room_name), day)
    return any(periods_overlap(a1, a2, p1, p2) for p1, p2 in used.get(key, []))


def _match_existing(
    campus: str,
    day: str,
    a1: int,
    a2: int,
    room_name: str,
    existing: list[ExistingBooking],
) -> tuple[ExistingBooking, bool] | None:
    """四项防重：日期 + 校区 + 节次 + 教室；返回 (命中记录, 节次是否完全一致)。"""
    wanted = room_key(room_name)
    if not wanted:
        return None
    exact: ExistingBooking | None = None
    overlap: ExistingBooking | None = None
    for b in existing:
        if b.date != day or b.campus != str(campus) or not b.room_key:
            continue
        if wanted not in b.room_key and b.room_key not in wanted:
            continue
        if b.start_period == a1 and b.end_period == a2:
            exact = exact or b
        elif periods_overlap(a1, a2, b.start_period, b.end_period):
            overlap = overlap or b
    if exact is not None:
        return exact, True
    if overlap is not None:
        return overlap, False
    return None


def _duplicate_assignment(act: Activity, hit: tuple[ExistingBooking, bool]) -> Assignment:
    booking, exact = hit
    note = (
        f"与已有申请重复：{booking.label}"
        if exact
        else f"与已有申请时段重叠且教室相同：{booking.label}"
    )
    return Assignment(activity=act, status="duplicate", note=note)


# ---------------------------------------------------------------- 已有申请
def existing_usage(session: Session, term: str) -> list[ExistingBooking]:
    """读「我的申请」，按「日期 + 校区 + 节次 + 教室」提取防重证据。

    教室证据：优先备注 `FJ`（本工具写入的意向教室），否则 `JASMC`（学校分配后的教室），
    并拼上用途描述 `JYYTMS` 兜底——与教师侧脚本的比对口径一致。
    """
    out: list[ExistingBooking] = []
    for r in api.list_borrows(session, term, page_size=999):
        day = r.get("KSRQ")
        ks, js = r.get("KSJC"), r.get("JSJC")
        if not day or ks in (None, "") or js in (None, ""):
            continue
        try:
            a1, a2 = int(ks), int(js)
        except (TypeError, ValueError):
            continue
        room = str(r.get("FJ") or "").strip() or str(r.get("JASMC") or "").strip()
        out.append(
            ExistingBooking(
                date=str(day),
                campus=str(r.get("XXXQDM") or ""),
                start_period=a1,
                end_period=a2,
                room=room,
                room_key=room_key(f"{room}{r.get('JYYTMS') or ''}"),
                label=f"{r.get('SQBH')}({r.get('SHZT_DISPLAY') or r.get('SHZT')})",
            )
        )
    return out


# ---------------------------------------------------------------- 规划
def build_plan(
    session: Session,
    activities: list[Activity],
    applicant: Applicant,
    *,
    existing: list[ExistingBooking] | None = None,
    allow_overlap: bool = False,
) -> list[Assignment]:
    """为每条活动分配一间空闲教室，并做批次内 + 跨批次防重。

    去重口径与教师侧脚本对齐：**日期 + 校区 + 节次 + 教室** 四项才算重复
    （节次区间有重叠、其余三项一致也算）；只是时段重叠、教室不同**不算**重复
    ——并行活动（同时间不同教室/校区）是正常需求。
    """
    existing = existing or []
    used: dict[tuple[str, str, str], list[tuple[int, int]]] = {}
    for b in existing:
        if b.room:
            used.setdefault((b.campus, room_key(b.room), b.date), []).append(
                (b.start_period, b.end_period)
            )
    results: list[Assignment] = []

    for act in activities:
        campus = act.campus or applicant.campus or "3"
        building = act.building or applicant.building
        room_type = act.room_type or applicant.room_type
        try:
            a1, a2 = parse_period(act.period)
        except ValueError:
            results.append(
                Assignment(activity=act, status="error", note=f"节次格式错误：{act.period}")
            )
            continue

        # 跨批次：意向教室若与已有申请四项一致，直接判重（不必再查空闲）
        if act.preferred_room and not allow_overlap:
            hit = _match_existing(campus, act.date, a1, a2, act.preferred_room, existing)
            if hit:
                results.append(_duplicate_assignment(act, hit))
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

        avail = [
            r for r in big if not _room_occupied(r, campus, act.date, a1, a2, used)
        ]
        if not avail:
            # 候选全被占：若其中某间正是已有申请（同日期/校区/节次/教室），报「重复」更有用
            hits = [
                hit
                for r in big
                if not allow_overlap
                and (hit := _match_existing(campus, act.date, a1, a2, r.room_name, existing))
            ]
            hit = next((h for h in hits if h[1]), None) or (hits[0] if hits else None)
            if hit:
                results.append(_duplicate_assignment(act, hit))
            else:
                results.append(
                    Assignment(
                        activity=act,
                        status="no_room",
                        note="候选教室已被本批次或已有申请占用",
                    )
                )
            continue

        chosen: FreeRoomSlot | None = None
        pref_missed = False
        if act.preferred_room:
            wanted = room_key(act.preferred_room)
            chosen = next((r for r in avail if room_key(r.room_name) == wanted), None)
            pref_missed = chosen is None
        if chosen is None:
            # 容量刚好够用的优先，避免占用大教室
            chosen = sorted(avail, key=lambda r: (_capacity(r), r.room_name))[0]

        if not allow_overlap:
            hit = _match_existing(campus, act.date, a1, a2, chosen.room_name, existing)
            if hit:
                results.append(_duplicate_assignment(act, hit))
                continue

        used.setdefault((str(campus), room_key(chosen.room_name), act.date), []).append((a1, a2))
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
    submit: bool = False,
    contract: tuple[str, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """把方案批量保存为草稿（或直接提交），返回逐条结果。

    借用类型按账号契约解析：活动 > 计划 defaults > 档案 > 契约默认值
    （学生端 02 / 教师端 09），并校验代码属于当前账号的字典，
    避免把学生端代码提交到教师端（同名字段两套字典）。
    """
    term = api.current_term(session)
    role, codes = contract if contract else api.borrow_contract(session)
    if not applicant.JSJYLXDM:
        applicant.JSJYLXDM = api.default_borrow_type(role)
    week_cache: dict[str, dict[str, Any]] = {}
    out: list[dict[str, Any]] = []

    for a in assignments:
        if a.status != "ok":
            out.append({"title": a.activity.title, "ok": False, "msg": a.note or a.status})
            continue
        problem = api.check_borrow_type(
            a.activity.JSJYLXDM or applicant.JSJYLXDM, role, codes
        )
        if problem:
            out.append({"title": a.activity.title, "ok": False, "msg": problem})
            continue
        try:
            req = to_request(session, a, applicant, term, week_cache, room_in_purpose)
        except Exception as exc:  # noqa: BLE001
            out.append({"title": a.activity.title, "ok": False, "msg": f"生成申请失败：{exc}"})
            continue
        res = api.save_borrow(session, req, submit=submit)
        a.request = req.as_payload()  # 在 save_borrow 之后取，TYPE 才是实际发送值
        out.append({"title": a.activity.title, "ok": res.ok, "msg": res.msg or str(res.code)})

    return out
