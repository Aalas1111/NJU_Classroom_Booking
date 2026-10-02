"""学校后端接口封装。

全部接口都通过 :class:`crb.session.Session` 携带登录态调用，
不依赖浏览器 UI（学校前端的下拉框有 bug，直连接口更稳）。

对应探测记录：docs/reference/nju-classroom-agent-findings.md
"""

from __future__ import annotations

import json
import re
from datetime import date as _date
from typing import Any

import httpx

from .config import (
    CAMPUSES,
    DEFAULT_BORROW_TYPE,
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
    EP_WITHDRAW,
    JY_ENTRY,
    ROLE_LABELS,
    ROLE_STUDENT,
    ROLE_TEACHER,
    ROLE_UNKNOWN,
    STUDENT_BORROW_TYPES,
    TEACHER_BORROW_TYPES,
)
from .models import BorrowRecord, BorrowRequest, Building, Campus, FreeRoomSlot, SaveResult
from .session import Session

# 列表记录字段名 -> 申请表字段名（学校列表用的是另一套别名）
_ALIASES = {"JASJYLXDM": "JSJYLXDM"}


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


def buildings(session: Session, campus_id: str | None = None) -> list[Building]:
    """教学楼字典。

    ``campus_id`` 为空时把四个校区都查一遍（接口本身按校区过滤，必须逐个来），
    返回的每行都带上 ``XXXQDM`` —— 省得调用方再猜这栋楼在哪个校区。
    """
    if campus_id:
        return _buildings_of(session, campus_id)
    out: list[Building] = []
    for cid in CAMPUSES:
        out.extend(_buildings_of(session, cid))
    return out


def _buildings_of(session: Session, campus_id: str) -> list[Building]:
    rows = _rows(session.post_form(EP_BUILDING, {"XXXQDM": campus_id}), "jxlcx")
    out: list[Building] = []
    for r in rows:
        item = Building.model_validate(r)
        if not item.campus_id:
            item.campus_id = campus_id
        out.append(item)
    return out


def room_types(session: Session) -> list[dict[str, Any]]:
    resp = session.post_form(EP_ROOM_TYPE)
    rows = _rows(resp, "code") or _rows(resp, "rows")
    return rows


def system_params(session: Session) -> dict[str, Any]:
    """系统参数：当前学期、借用开关、可借日期范围等。

    `cxxtcs.do` 返回的是键值表：每行 `ZCSDM` 是参数代码，`CSZA` 是参数值。
    """
    rows = _rows(session.post_form(EP_SYS_PARAMS), "cxxtcs")
    return {str(r.get("ZCSDM")): r.get("CSZA") for r in rows if r.get("ZCSDM")}


def current_term(session: Session) -> str:
    """当前学年学期，例如 2026-2027-1。"""
    params = system_params(session)
    if params.get("DQXNXQDM"):
        return str(params["DQXNXQDM"])
    rows = _rows(session.post_form(EP_TERM), "cxdqxnxq")
    if rows:
        r = rows[0]
        return str(r.get("DM") or r.get("XNXQDM") or r.get("DQXNXQDM") or "")
    return ""


def my_org(session: Session) -> dict[str, Any]:
    """当前账号所在单位。`cxyhszdw.do` 返回 SZDWDM（即借用申请里的 JYDWDM）。"""
    rows = _rows(session.post_form(EP_ORG), "cxyhszdw")
    if not rows:
        return {}
    r = dict(rows[0])
    if r.get("SZDWDM") and not r.get("DWDM"):
        r["DWDM"] = r["SZDWDM"]
    return r


#: 应用页里那段前端初始化配置：姓名、用户号都在里头。
_JW_CONFIG_RE = re.compile(r"_JW_INIT_CONFIG\s*=\s*(\{.*?\});", re.S)


def account_identity(session: Session, path: str = JY_ENTRY) -> dict[str, str]:
    """当前账号的**姓名**与用户号 —— 学校页面上带着，`cxyhszdw.do` 只给单位。

    为什么需要它：借用申请里的「借用人」「借用单位」是**要填**的。实测（2026-09-28）：
    什么都不填去提交，学校**照样收，但存成空**（回读 JYRXM/JYDWDM 都是 null）——
    学校表单里那两份是**前端**拿账号信息自动填好的，我们直连接口就得自己填。
    名字藏在应用页的 `_JW_INIT_CONFIG.username` 里（学生号实测 `李赫`）。

    读不到就回空串（**别猜**）：这只是把账号信息搬过来，不是必填项，
    调用方该怎么兜底由它自己决定。
    """
    try:
        resp = session.client.get(path)
    except httpx.HTTPError:
        return {}
    if resp.status_code != 200:
        return {}
    found = _JW_CONFIG_RE.search(resp.text or "")
    if not found:
        return {}
    try:
        data = json.loads(found.group(1))
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        "name": str(data.get("username") or "").strip(),
        "account": str(data.get("userid") or "").strip(),
    }


def borrow_types(session: Session) -> list[dict[str, Any]]:
    return _rows(session.post_form(EP_BORROW_TYPE), "cxjsjylx")


def borrow_contract(session: Session) -> tuple[str, dict[str, str]]:
    """判定当前账号走哪套借用类型契约，返回 ``(角色, {代码: 名称})``。

    ``JSJYLXDM`` 是同名字段两套字典：学生端是「指导教师所在单位」口径，
    教师端是活动类型口径。服务端按登录账号返回对应字典，以此判定。
    """
    codes = {
        str(r["JSJYLXDM"]): str(r.get("JSJYLXMC") or "")
        for r in borrow_types(session)
        if r.get("JSJYLXDM")
    }
    if not codes:
        return ROLE_UNKNOWN, {}
    student_hit = len(codes.keys() & STUDENT_BORROW_TYPES.keys())
    teacher_hit = len(codes.keys() & TEACHER_BORROW_TYPES.keys())
    if teacher_hit > student_hit:
        return ROLE_TEACHER, codes
    if student_hit:
        return ROLE_STUDENT, codes
    return ROLE_UNKNOWN, codes


def default_borrow_type(role: str) -> str:
    """契约对应的默认借用类型：学生端 02（学生社团管理部）、教师端 09（团学活动）。"""
    return DEFAULT_BORROW_TYPE.get(role, "")


def check_borrow_type(code: str, role: str, codes: dict[str, str]) -> str:
    """校验借用类型是否属于当前账号的字典；通过返回空串，否则返回错误文案。"""
    if not codes or code in codes:
        return ""
    available = "、".join(f"{k} {v}" for k, v in sorted(codes.items()))
    return (
        f"借用类型 {code or '（空）'} 不在当前账号字典（{ROLE_LABELS.get(role, role)}）内；"
        f"可用：{available}"
    )


def borrow_type_hint(codes: dict[str, str]) -> str:
    """字典的可读形式，如 ``09 团学活动 / 07 教师教学、补课``。"""
    return " / ".join(f"{k} {v}" for k, v in sorted(codes.items()))


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
def _free_query(
    session: Session,
    *,
    day: str,
    campus_id: str,
    start_period: int | None = None,
    end_period: int | None = None,
    building_id: str | None = None,
    room_type: str | None = None,
    page_size: int = 999,
) -> list[FreeRoomSlot]:
    data: dict[str, Any] = {
        "KXRQ": day,
        "XXXQDM": campus_id,
        "pageSize": page_size,
        "pageNumber": 1,
        "querySetting": "[]",
    }
    # 不给 KSJC/JSJC 时学校会忽略节次过滤，返回该校区**全部**教室（实测 2026-09-28）。
    if start_period is not None and end_period is not None:
        data["KSJC"] = str(start_period)
        data["JSJC"] = str(end_period)
    if building_id:
        data["JXLDM"] = building_id
    if room_type:
        data["JASLXDM"] = room_type

    resp = session.post_form(EP_FREE_ROOMS, data)
    return [FreeRoomSlot.model_validate(r) for r in _rows(resp, "cxkxjs")]


def free_rooms(
    session: Session,
    *,
    campus_id: str,
    day: str,
    start_period: int,
    end_period: int,
    building_id: str | None = None,
    room_type: str | None = None,
    page_size: int = 999,
) -> list[FreeRoomSlot]:
    """查询某天、某节次区间、某校区的空闲教室。

    对应前端「按日期」页：`pagePath=/modules/kxjscx.do, action=cxkxjs`。
    **区间语义是「整个区间都空闲」**（实测：`1-2` 的结果 = `1` 与 `2` 的交集），
    不是「区间内任意一节空闲」——所以逐节状态要用单节查询来问。
    """
    return _free_query(
        session,
        day=day,
        campus_id=campus_id,
        start_period=start_period,
        end_period=end_period,
        building_id=building_id,
        room_type=room_type,
        page_size=page_size,
    )


def all_rooms(
    session: Session,
    *,
    campus_id: str,
    building_id: str | None = None,
    room_type: str | None = None,
    day: str | None = None,
    page_size: int = 999,
) -> list[FreeRoomSlot]:
    """某校区的教室清单（教室索引/字典）。

    走的是同一个接口，只是**不带节次**：学校返回该校区全部教室
    （仙林 223 间 / 鼓楼 169 间，实测 2026-09-28），节次字段为空。
    """
    return _free_query(
        session,
        day=day or today(),
        campus_id=campus_id,
        building_id=building_id,
        room_type=room_type,
        page_size=page_size,
    )


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


def _total_of(resp: Any, key: str) -> int | None:
    """列表接口带的 ``totalSize``（没有就 None）——「本学期共 N 条」要个诚实的数。"""
    try:
        total = _datas(resp).get(key, {}).get("totalSize")
        return int(total) if total is not None else None
    except (TypeError, ValueError):
        return None


def list_borrows_window(
    session: Session,
    term: str,
    *,
    since: str = "",
    page_size: int = 100,
    max_pages: int = 10,
) -> tuple[list[BorrowRecord], dict[str, Any]]:
    """**按提交日期倒序翻页**取申请，翻到出现早于 ``since`` 的记录就停。

    列表在一个学期里会不断累积（几百条不稀奇），全量拉既慢、又会把工具的返回撑爆——
    而绝大多数问题只关心最近一段（默认近一周）。因为服务端已按 ``-SQRQ``（提交日期）
    倒序，翻页可以在「翻到比窗口起点更早的那条」时立刻停：通常一页就够。
    ``since`` 为空 = 只取第一页（与 :func:`list_borrows` 行为一致）。

    返回 ``(records, meta)``；``meta = {"total": totalSize|None, "pages": 翻了几页,
    "exhausted": 是否翻到了头}``。
    """
    collected: list[BorrowRecord] = []
    total: int | None = None
    pages = 0
    exhausted = False
    page = 1
    while page <= max_pages:
        resp = session.post_form(
            EP_LIST,
            {
                "pageSize": page_size,
                "pageNumber": page,
                "XNXQDM": term,
                "*order": "-SQRQ",
                "querySetting": "[]",
            },
        )
        if total is None:
            total = _total_of(resp, "cxjsjysq")
        page_rows = _rows(resp, "cxjsjysq")
        pages += 1
        collected.extend(BorrowRecord.model_validate(r) for r in page_rows)
        if len(page_rows) < page_size:
            exhausted = True  # 这页不满 = 没有下一页了
            break
        if not since:
            break
        oldest = str((page_rows[-1] or {}).get("SQRQ") or "")[:10]
        if oldest and oldest < since:
            break  # 已越过窗口起点：后面的只会更旧，收工
        page += 1
    return collected, {"total": total, "pages": pages, "exhausted": exhausted}


def delete_borrow(session: Session, sqbh: str) -> SaveResult:
    """删除申请/草稿（scjssq.do）。实测对草稿也生效。"""
    resp = session.post_form(EP_DELETE, {"param": json.dumps([{"SQBH": sqbh}], ensure_ascii=False)})
    ext = _datas(resp).get("scjssq", {}).get("extParams", {}) or {}
    code = ext.get("code")
    return SaveResult(ok=(code == 1), code=code, msg=str(ext.get("msg", "")), raw=resp)


def withdraw_borrow(
    session: Session, sqbh: str, cqdqjy: str = "2", jsjysqlx: str = "6"
) -> SaveResult:
    """撤回申请（shjsjysq.do）。撤回后状态变为 SHZT='1'，可编辑后重新提交。"""
    resp = session.post_form(
        EP_WITHDRAW,
        {"SQBH": sqbh, "SHZT": "1", "JSJYSQLX": jsjysqlx, "CQDQJY": cqdqjy},
    )
    ext = _datas(resp).get("shjsjysq", {}).get("extParams", {}) or {}
    code = ext.get("code")
    return SaveResult(ok=(code == 1), code=code, msg=str(ext.get("msg", "")), raw=resp)


def find_borrow(session: Session, term: str, sqbh: str) -> BorrowRecord | None:
    for r in list_borrows(session, term, page_size=999):
        if str(r.get("SQBH")) == str(sqbh):
            return r
    return None


def update_borrow(
    session: Session,
    record: BorrowRecord | dict[str, Any],
    *,
    submit: bool = True,
    **changes: Any,
) -> SaveResult:
    """基于已有记录修改并（默认）重新提交。

    实测：带上原记录的 `WID`/`SQBH` 调 `xzjasjysq.do` 会**更新**而不是新增。
    """
    base: dict[str, Any] = record.model_dump() if hasattr(record, "model_dump") else dict(record)
    # 先用申请表默认值兜底，再用记录里有的字段覆盖（含别名映射），
    # 否则缺失字段（如 JSJYLXDM）会导致后端“新增失败”
    data = BorrowRequest().as_payload()
    for k, v in base.items():
        key = _ALIASES.get(k, k)
        if key in data and v not in (None, ""):
            data[key] = v
    data.update({k: v for k, v in changes.items() if v is not None})
    data["WID"] = base.get("WID")
    data["SQBH"] = base.get("SQBH")
    data["TYPE"] = "TJ" if submit else "save"
    resp = session.post_form(EP_SAVE, {"param": json.dumps([data], ensure_ascii=False)})
    ext = _datas(resp).get("xzjasjysq", {}).get("extParams", {}) or {}
    code = ext.get("code")
    return SaveResult(ok=(code == 1), code=code, msg=str(ext.get("msg", "")), raw=resp)


# ---------------------------------------------------------------- 便捷函数
def today() -> str:
    return _date.today().isoformat()
