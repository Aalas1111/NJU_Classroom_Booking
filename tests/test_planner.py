"""批量规划相关测试（不联网）。"""

from __future__ import annotations

from crb import planner
from crb.models import Activity, Applicant, Assignment, BorrowRecord, FreeRoomSlot


def _slot(name: str, cap: int) -> FreeRoomSlot:
    return FreeRoomSlot.model_validate({"JASMC": name, "SKZWS": cap, "KXRQ": "2026-09-10"})


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


def test_capacity_and_conflict() -> None:
    assert planner._capacity(_slot("A", 50)) == 50
    used = {("仙Ⅰ-101", "2026-09-10"): [(1, 2)]}
    assert planner._is_conflict(_slot("仙Ⅰ-101", 50), "2026-09-10", 2, 3, used) is True
    assert planner._is_conflict(_slot("仙Ⅰ-101", 50), "2026-09-10", 3, 4, used) is False
    assert planner._is_conflict(_slot("仙Ⅰ-101", 50), "2026-09-11", 1, 2, used) is False


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
                "FJ": "南雍-西108",
                "SHZT_DISPLAY": "待审核",
            }
        )
    ]
    monkeypatch.setattr(planner.api, "list_borrows", lambda *a, **k: rows)
    slots, rooms = planner.existing_usage(None, "2026-2027-1")  # type: ignore[arg-type]
    assert slots == [("2026-09-11", 7, 8, "1(待审核)")]
    assert rooms[("南雍-西108", "2026-09-11")] == [(7, 8)]


def test_build_plan_flags_duplicate(monkeypatch) -> None:
    monkeypatch.setattr(planner.api, "free_rooms", lambda *a, **k: [_slot("A", 50)])
    acts = [Activity(title="x", date="2026-09-10", period="1-2", people=10)]
    res = planner.build_plan(
        None,  # type: ignore[arg-type]
        acts,
        Applicant(campus="3"),
        existing_slots=[("2026-09-10", 1, 2, "SQBH1(待审核)")],
    )
    assert res[0].status == "duplicate"
    assert "重叠" in res[0].note


def test_build_plan_avoids_existing_room(monkeypatch) -> None:
    monkeypatch.setattr(planner.api, "free_rooms", lambda *a, **k: [_slot("A", 50), _slot("B", 60)])
    acts = [Activity(title="x", date="2026-09-10", period="1-2", people=10)]
    res = planner.build_plan(
        None,  # type: ignore[arg-type]
        acts,
        Applicant(campus="3"),
        existing_rooms={("A", "2026-09-10"): [(1, 2)]},
    )
    assert res[0].status == "ok"
    assert res[0].room is not None and res[0].room.room_name == "B"


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
