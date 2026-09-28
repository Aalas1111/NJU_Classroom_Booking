"""批量规划相关测试（不联网）。"""

from __future__ import annotations

import json

from crb import planner
from crb.models import (
    Activity,
    Applicant,
    Assignment,
    BorrowRecord,
    ExistingBooking,
    FreeRoomSlot,
    SaveResult,
)
from crb.utils import room_key


def _slot(name: str, cap: int) -> FreeRoomSlot:
    return FreeRoomSlot.model_validate({"JASMC": name, "SKZWS": cap, "KXRQ": "2026-09-10"})


def _booking(
    day: str = "2026-09-10",
    campus: str = "3",
    a1: int = 1,
    a2: int = 2,
    room: str = "仙Ⅰ-101",
    label: str = "SQBH1(待审核)",
) -> ExistingBooking:
    return ExistingBooking(
        date=day,
        campus=campus,
        start_period=a1,
        end_period=a2,
        room=room,
        room_key=room_key(f"{room}例会"),
        label=label,
    )


def test_load_plan_bare_array(tmp_path) -> None:
    f = tmp_path / "p.json"
    f.write_text('[{"title":"A","date":"2026-09-10","period":"1-2","people":10}]', encoding="utf-8")
    applicant, acts = planner.load_plan(f)
    assert applicant.campus == ""  # 默认空，由档案/回退补齐
    assert len(acts) == 1 and acts[0].title == "A"


def test_load_plan_with_defaults(tmp_path) -> None:
    f = tmp_path / "p.json"
    f.write_text(
        '{"defaults":{"campus":"1","JYDWDM":"400760"},'
        '"activities":[{"title":"A","date":"2026-09-10"}]}',
        encoding="utf-8",
    )
    applicant, acts = planner.load_plan(f)
    assert applicant.campus == "1"
    assert applicant.JYDWDM == "400760"
    assert acts[0].period == "1-2"  # 默认节次


def test_capacity_and_room_occupancy() -> None:
    assert planner._capacity(_slot("A", 50)) == 50
    used = {("3", room_key("仙Ⅰ-101"), "2026-09-10"): [(1, 2)]}
    room = _slot("仙I-101", 50)  # 归一化后与 仙Ⅰ-101 同名
    assert planner._room_occupied(room, "3", "2026-09-10", 2, 3, used) is True
    assert planner._room_occupied(room, "3", "2026-09-10", 3, 4, used) is False
    assert planner._room_occupied(room, "3", "2026-09-11", 1, 2, used) is False
    assert planner._room_occupied(room, "4", "2026-09-10", 1, 2, used) is False  # 不同校区


def test_apply_profile() -> None:
    a = Applicant()
    planner.apply_profile(a, {"JYDWDM": "400760", "JYRXM": "李赫", "JYRDH": "173", "campus": "4"})
    assert a.JYDWDM == "400760"
    assert a.JYRXM == "李赫"
    assert a.JYRDH == "173"
    assert a.campus == "4"


def test_existing_usage(monkeypatch) -> None:
    rows = [
        BorrowRecord.model_validate(
            {
                "SQBH": "1",
                "KSRQ": "2026-09-11",
                "KSJC": "7",
                "JSJC": "8",
                "XXXQDM": "4",
                "FJ": "南雍-西108",
                "JYYTMS": "例会",
                "SHZT_DISPLAY": "待审核",
            }
        ),
        # FJ 为空（教师侧脚本/校内前端提交）：改用学校分配后的 JASMC
        BorrowRecord.model_validate(
            {
                "SQBH": "2",
                "KSRQ": "2026-09-11",
                "KSJC": "3",
                "JSJC": "4",
                "XXXQDM": "3",
                "JASMC": "仙Ⅰ-303",
            }
        ),
    ]
    monkeypatch.setattr(planner.api, "list_borrows", lambda *a, **k: rows)
    out = planner.existing_usage(None, "2026-2027-1")  # type: ignore[arg-type]
    assert len(out) == 2
    assert (out[0].date, out[0].campus, out[0].start_period, out[0].end_period) == (
        "2026-09-11",
        "4",
        7,
        8,
    )
    assert out[0].room == "南雍-西108"
    assert room_key("南雍-西108") in out[0].room_key
    assert out[0].label == "1(待审核)"
    assert out[1].room == "仙Ⅰ-303"


def test_build_plan_flags_four_item_duplicate(monkeypatch) -> None:
    """日期 + 校区 + 节次 + 教室 四项一致 → duplicate。"""
    monkeypatch.setattr(planner.api, "free_rooms", lambda *a, **k: [_slot("A", 50)])
    acts = [Activity(title="x", date="2026-09-10", period="1-2", people=10)]
    res = planner.build_plan(
        None,  # type: ignore[arg-type]
        acts,
        Applicant(campus="3"),
        existing=[_booking(room="A")],
    )
    assert res[0].status == "duplicate"
    assert "重复" in res[0].note and "SQBH1" in res[0].note


def test_build_plan_flags_overlapping_same_room(monkeypatch) -> None:
    """节次有重叠、其余三项一致 → 同样算重复。"""
    acts = [Activity(title="x", date="2026-09-10", period="2-3", people=10, preferred_room="A")]
    res = planner.build_plan(
        None,  # type: ignore[arg-type]
        acts,
        Applicant(campus="3"),
        existing=[_booking(a1=1, a2=2, room="A")],
    )
    assert res[0].status == "duplicate"
    assert "重叠" in res[0].note


def test_build_plan_allows_parallel_activities(monkeypatch) -> None:
    """时段重叠但教室不同 / 校区不同 ≠ 重复：并行活动是正常需求。"""
    monkeypatch.setattr(planner.api, "free_rooms", lambda *a, **k: [_slot("A", 50), _slot("B", 60)])
    acts = [Activity(title="x", date="2026-09-10", period="1-2", people=10)]
    other_room = planner.build_plan(
        None,  # type: ignore[arg-type]
        acts,
        Applicant(campus="3"),
        existing=[_booking(room="仙Ⅰ-999")],
    )
    assert other_room[0].status == "ok"

    other_campus = planner.build_plan(
        None,  # type: ignore[arg-type]
        acts,
        Applicant(campus="3"),
        existing=[_booking(campus="4", room="A")],
    )
    assert other_campus[0].status == "ok"


def test_build_plan_preferred_room_duplicate(monkeypatch) -> None:
    """意向教室写法不同（仙I / 仙Ⅰ）也要能认出是已有申请的那间。"""

    def _boom(*a, **k):  # 判重在查询空闲教室之前，不应触发查询
        raise AssertionError("不应查询空闲教室")

    monkeypatch.setattr(planner.api, "free_rooms", _boom)
    acts = [
        Activity(
            title="x", date="2026-09-10", period="1-2", people=10, preferred_room="仙I-101"
        )
    ]
    res = planner.build_plan(
        None,  # type: ignore[arg-type]
        acts,
        Applicant(campus="3"),
        existing=[_booking(room="仙Ⅰ-101")],
    )
    assert res[0].status == "duplicate"


def test_build_plan_avoids_existing_room(monkeypatch) -> None:
    """已有申请占用的教室不再重复选（本工具创建的申请靠 FJ，教师侧靠 JASMC）。"""
    monkeypatch.setattr(planner.api, "free_rooms", lambda *a, **k: [_slot("A", 50), _slot("B", 60)])
    acts = [Activity(title="x", date="2026-09-10", period="1-2", people=10)]
    res = planner.build_plan(
        None,  # type: ignore[arg-type]
        acts,
        Applicant(campus="3"),
        existing=[_booking(room="A")],
    )
    assert res[0].status == "ok"
    assert res[0].room is not None and res[0].room.room_name == "B"


def test_save_plan_follows_account_contract(monkeypatch) -> None:
    """教师端契约：缺省补 09、显式 07 生效、学生端代码 02 直接拦下。"""
    saved: list = []

    def _fake_save(session, req, submit=False):
        saved.append(req)
        return SaveResult(ok=True, code=1, msg="ok")

    monkeypatch.setattr(planner.api, "current_term", lambda *a, **k: "2026-2027-1")
    monkeypatch.setattr(
        planner.api,
        "borrow_contract",
        lambda *a, **k: ("teacher", {"07": "教师教学、补课", "09": "团学活动"}),
    )
    monkeypatch.setattr(planner.api, "date_to_week", lambda *a, **k: {"ZC": 3, "XQJ": 4})
    monkeypatch.setattr(planner.api, "save_borrow", _fake_save)

    def _assignment(title: str, code: str | None = None) -> Assignment:
        act = Activity(
            title=title, date="2026-09-10", period="1-2", people=10, JSJYLXDM=code
        )
        return Assignment(activity=act, room=_slot("仙Ⅰ-203", 96), status="ok")

    res = planner.save_plan(
        None,  # type: ignore[arg-type]
        [_assignment("默认"), _assignment("显式07", "07"), _assignment("学生码", "02")],
        Applicant(JYDWDM="200300", JYRXM="郭亚敏", campus="3"),
    )
    assert [r["ok"] for r in res] == [True, True, False]
    assert [r.JSJYLXDM for r in saved] == ["09", "07"]
    assert "02" in res[2]["msg"] and "教师端" in res[2]["msg"]


def test_save_plan_reports_actual_type(monkeypatch) -> None:
    """回归：--json 回执里的 request.TYPE 要与实际发送值一致（save / TJ）。"""
    sent: list[dict] = []

    class _Session:
        def post_form(self, path, data=None):
            assert path == planner.api.EP_SAVE
            sent.append(json.loads(data["param"])[0])
            return {"datas": {"xzjasjysq": {"extParams": {"code": 1, "msg": "ok"}}}}

    monkeypatch.setattr(planner.api, "current_term", lambda *a, **k: "2026-2027-1")
    monkeypatch.setattr(
        planner.api, "borrow_contract", lambda *a, **k: ("student", {"02": "学生社团管理部"})
    )
    monkeypatch.setattr(planner.api, "date_to_week", lambda *a, **k: {"ZC": 3, "XQJ": 4})

    for submit, expected in ((False, "save"), (True, "TJ")):
        assignment = Assignment(
            activity=Activity(title="例会", date="2026-09-10", period="1-2", people=10),
            room=_slot("仙Ⅰ-203", 96),
            status="ok",
        )
        planner.save_plan(
            _Session(),  # type: ignore[arg-type]
            [assignment],
            Applicant(JYDWDM="400760", JYRXM="李赫", campus="3"),
            submit=submit,
        )
        assert sent[-1]["TYPE"] == expected
        assert assignment.request is not None
        assert assignment.request["TYPE"] == expected


def test_to_request_fills_borrow_fields() -> None:
    act = Activity(title="例会", date="2026-09-10", period="1-2", people=30)
    assignment = Assignment(activity=act, room=_slot("仙Ⅰ-203", 96), status="ok")
    applicant = Applicant(
        JYDWDM="400760", JYRXM="李赫", JYRDH="13800000000", JSJYLXDM="02", campus="3"
    )
    req = planner.to_request(
        None,  # type: ignore[arg-type]  # week_cache 命中，不会用到 session
        assignment,
        applicant,
        term="2026-2027-1",
        week_cache={"2026-09-10": {"ZC": 3, "XQJ": 4}},
    )
    payload = req.as_payload()
    assert payload["JYDWDM"] == "400760"
    assert payload["XXXQDM"] == "3"
    assert payload["ZC"] == "3"
    assert payload["XQ"] == "4"
    assert payload["KSJC"] == "1" and payload["JSJC"] == "2"
    assert payload["ZRS"] == "30"
    assert payload["JSRL"] == "96"
    assert payload["TYPE"] == "save"
    assert "仙Ⅰ-203" in payload["JYYTMS"]
    assert payload["FJ"] == "仙Ⅰ-203"
