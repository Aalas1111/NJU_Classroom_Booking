"""批量规划相关测试（不联网）。"""

from __future__ import annotations

from crb import planner
from crb.models import Activity, Applicant, Assignment, FreeRoomSlot


def _slot(name: str, cap: int) -> FreeRoomSlot:
    return FreeRoomSlot.model_validate({"JASMC": name, "SKZWS": cap, "KXRQ": "2026-09-10"})


def test_load_plan_bare_array(tmp_path) -> None:
    f = tmp_path / "p.json"
    f.write_text('[{"title":"A","date":"2026-09-10","period":"1-2","people":10}]', encoding="utf-8")
    applicant, acts = planner.load_plan(f)
    assert applicant.campus == "3"  # 默认值
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
