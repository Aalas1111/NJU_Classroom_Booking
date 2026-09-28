"""教室视角（``crb rooms`` / ``crb room``）：名字匹配 + 逐节空闲。

两个拿事故换来的点必须钉住：

1. **名字对不上时绝不猜** —— 返回候选（``ambiguous``/``not_found``），由 LLM 去问用户；
2. 学校接口的区间语义是「**整个区间都空闲**」，所以逐节状态只能靠单节查询问出来；
   整天全空的那种（最常见的问法）要能用 1 次查询答掉。
"""

from __future__ import annotations

from typer.testing import CliRunner

from crb import roomview
from crb.cli import app
from crb.models import FreeRoomSlot
from crb.utils import room_key_loose, slot_time, span_label, span_time

ROOMS = [
    {
        "JASMC": "仙Ⅰ-501",
        "JXLDM": "11",
        "JXLDM_DISPLAY": "仙I区",
        "XXXQDM": "3",
        "XXXQDM_DISPLAY": "仙林校区",
        "SKZWS": 96,
        "JASLXDM_DISPLAY": "多媒体教室",
    },
    {
        "JASMC": "仙Ⅰ-502",
        "JXLDM": "11",
        "JXLDM_DISPLAY": "仙I区",
        "XXXQDM": "3",
        "XXXQDM_DISPLAY": "仙林校区",
        "SKZWS": 96,
    },
    {
        "JASMC": "逸B-501",
        "JXLDM": "16",
        "JXLDM_DISPLAY": "逸夫楼B区",
        "XXXQDM": "3",
        "XXXQDM_DISPLAY": "仙林校区",
        "SKZWS": 60,
    },
]

#: 各教室「哪些节空闲」——假接口按这个回答。
FREE = {
    "仙Ⅰ-501": {1, 2, 7, 8, 9, 10, 11, 12},
    "仙Ⅰ-502": set(range(1, 13)),
    "逸B-501": {5, 6},
}


class FakeSession:
    """假学校接口：语义与实测一致（区间 = 每一节都空闲）。"""

    def __init__(self, rooms: list[dict], free: dict[str, set[int]]) -> None:
        self.rooms = rooms
        self.free = free
        self.calls: list[dict] = []

    def post_form(self, path, data=None):
        data = dict(data or {})
        self.calls.append(data)
        if "KSJC" not in data:  # 不带节次 = 教室清单
            rows = self.rooms
        else:
            a, b = int(data["KSJC"]), int(data["JSJC"])
            rows = [
                r for r in self.rooms if all(p in self.free[r["JASMC"]] for p in range(a, b + 1))
            ]
        return {"datas": {"cxkxjs": {"rows": rows, "totalSize": len(rows)}}}


def slot(**kw) -> FreeRoomSlot:
    return FreeRoomSlot.model_validate(kw)


# ---------------------------------------------------------------- 名字匹配
def test_match_exact_and_loose_names():
    rooms = [slot(**r) for r in ROOMS]
    hit, candidates = roomview.match_room(rooms, "仙Ⅰ-501")
    assert hit is not None and hit.room_name == "仙Ⅰ-501" and not candidates
    # 「仙一501」是口语写法：罗马数字/中文数字要能对上（仙Ⅰ → 仙一 → 仙1）
    hit, _ = roomview.match_room(rooms, "仙一501")
    assert hit is not None and hit.room_name == "仙Ⅰ-501"
    hit, _ = roomview.match_room(rooms, "仙I501")
    assert hit is not None and hit.room_name == "仙Ⅰ-501"


def test_match_returns_candidates_instead_of_guessing():
    rooms = [slot(**r) for r in ROOMS]
    hit, candidates = roomview.match_room(rooms, "501")
    assert hit is None
    assert [c.room_name for c in candidates] == ["仙Ⅰ-501", "逸B-501"]

    # 楼名对不上、号码能对上 → 只能给候选，不许自己挑一间（哪怕只对上一间）
    hit, candidates = roomview.match_room(rooms, "新教501")
    assert hit is None
    assert [c.room_name for c in candidates] == ["仙Ⅰ-501", "逸B-501"]


def test_match_not_found_is_not_a_guess():
    rooms = [slot(**r) for r in ROOMS]
    hit, candidates = roomview.match_room(rooms, "火星楼")
    assert hit is None and candidates == []


# ---------------------------------------------------------------- 逐节空闲
def test_room_day_spans():
    sess = FakeSession(ROOMS, FREE)
    view = roomview.room_day(sess, campus_id="3", day="2026-09-30", room="仙一501")
    assert view.status == "ok"
    assert view.room is not None
    assert view.room.name == "仙Ⅰ-501"
    assert view.room.capacity == 96
    assert view.weekday == "周三"
    assert [s.label for s in view.free_spans] == ["1-2", "7-12"]
    assert [s.label for s in view.occupied_spans] == ["3-6"]
    assert view.occupied_spans[0].time == "10:10-15:50"
    assert [p.free for p in view.periods[:3]] == [True, True, False]
    # 1 次教室清单 + 1 次整段（没命中）+ 12 次逐节
    assert len(sess.calls) == 1 + 1 + 12


def test_room_day_all_free_room_costs_one_query():
    """整天全空：整段查询命中即定论，不再逐节问。"""
    sess = FakeSession(ROOMS, FREE)
    view = roomview.room_day(sess, campus_id="3", day="2026-09-30", room="仙Ⅰ-502")
    assert view.occupied_spans == []
    assert len(view.free_spans) == 1 and view.free_spans[0].label == "1-12"
    assert len(sess.calls) == 1 + 1


def test_room_day_period_window():
    """只看下午/晚上（7-12 节）时不该去问上午。"""
    sess = FakeSession(ROOMS, FREE)
    view = roomview.room_day(
        sess, campus_id="3", day="2026-09-30", room="仙Ⅰ-501", start_period=7, end_period=12
    )
    assert [s.label for s in view.free_spans] == ["7-12"]
    assert view.occupied_spans == []
    assert [c.get("KSJC") for c in sess.calls[1:]][:1] == ["7"]
    assert all(int(c["KSJC"]) >= 7 for c in sess.calls[1:])


def test_room_day_ambiguous_does_not_query_occupancy():
    sess = FakeSession(ROOMS, FREE)
    view = roomview.room_day(sess, campus_id="3", day="2026-09-30", room="501")
    assert view.status == "ambiguous"
    assert [c.name for c in view.candidates] == ["仙Ⅰ-501", "逸B-501"]
    assert view.periods == []
    assert len(sess.calls) == 1  # 只查了教室清单，没去猜着查占用


# ---------------------------------------------------------------- 批量（一层楼一次问）
def test_day_view_costs_one_plus_period_count():
    """整栋楼的空档：1 发教室清单 + 12 发（每节一次），**与教室数无关**。

    对照：逐间问 `crb room` 是 3 间 × 13 发。批量是这条命令存在的唯一理由。
    """
    sess = FakeSession(ROOMS, FREE)
    view = roomview.day_view(sess, campus_id="3", day="2026-09-30")
    assert len(sess.calls) == 1 + 12
    assert view.total == 3
    by_name = {row.room.name: row for row in view.rooms}
    assert [s.label for s in by_name["仙Ⅰ-501"].free_spans] == ["1-2", "7-12"]
    assert [s.label for s in by_name["仙Ⅰ-501"].occupied_spans] == ["3-6"]
    # 整天空的教室：没有占用段
    assert by_name["仙Ⅰ-502"].occupied_spans == []
    assert by_name["逸B-501"].free_spans[0].time == "14:00-15:50"


def test_day_view_includes_rooms_that_are_never_free():
    """整天全占的教室也要在列 —— 只问「哪节空」会漏掉它，用户会以为没这间。"""
    rooms = [
        *ROOMS,
        {
            "JASMC": "仙Ⅰ-999",
            "JXLDM": "11",
            "JXLDM_DISPLAY": "仙I区",
            "XXXQDM": "3",
            "SKZWS": 30,
        },
    ]
    free = {**FREE, "仙Ⅰ-999": set()}
    view = roomview.day_view(FakeSession(rooms, free), campus_id="3", day="2026-09-30")
    row = next(r for r in view.rooms if r.room.name == "仙Ⅰ-999")
    assert row.free_spans == []
    assert len(row.occupied_spans) == 1 and row.occupied_spans[0].label == "1-12"


def test_day_view_match_filter_narrows_without_extra_requests():
    sess = FakeSession(ROOMS, FREE)
    view = roomview.day_view(sess, campus_id="3", day="2026-09-30", match="逸")
    assert [row.room.name for row in view.rooms] == ["逸B-501"]
    assert view.total == 1
    assert len(sess.calls) == 1 + 12  # 筛选在本地做，不多打学校


def test_cli_day_help():
    result = CliRunner().invoke(app, ["day", "--help"])
    assert result.exit_code == 0
    assert "--building" in result.output and "--match" in result.output


# ---------------------------------------------------------------- 小工具
def test_period_time_helpers():
    assert slot_time(7) == "16:10-17:00"
    assert span_label(1, 2) == "1-2" and span_label(7, 7) == "7"
    assert span_time(3, 4) == "10:10-12:00"
    assert room_key_loose("仙Ⅰ-501") == room_key_loose("仙一501") == "仙1501"


def test_cli_room_help_mentions_options():
    result = CliRunner().invoke(app, ["room", "--help"])
    assert result.exit_code == 0
    assert "--room" in result.output and "--date" in result.output
    result = CliRunner().invoke(app, ["rooms", "--help"])
    assert result.exit_code == 0
    assert "--match" in result.output


# ---------------------------------------------------------------- 多日期（「这几天哪天有空」）
def test_free_command_validates_dates_before_touching_the_session():
    """参数错就是参数错 —— 别让人以为是登录态的问题（所以先验参再读登录态）。"""
    from crb.cli import app as crb_app

    result = CliRunner().invoke(crb_app, ["free", "-c", "3", "-d", "2026-09-30,明天", "-p", "1-2"])
    assert result.exit_code == 2
    assert "YYYY-MM-DD" in result.output


def test_free_command_caps_the_number_of_dates():
    from crb.cli import app as crb_app

    many = ",".join(f"2026-{m:02d}-{d:02d}" for m in (9, 10) for d in range(1, 32))
    result = CliRunner().invoke(crb_app, ["free", "-c", "3", "-d", many, "-p", "1-2"])
    assert result.exit_code == 2
    assert "最多" in result.output


def test_is_iso_date():
    from crb.utils import is_iso_date

    assert is_iso_date("2026-09-30")
    for bad in ("2026/09/30", "明天", "09-30", "", None):
        assert not is_iso_date(bad)
