"""申请列表「区间 + limit」（``api.list_borrows_window``）的行为测试。

列表在一个学期里会累积；调用方一般只要「某区间内的最新 N 条」。
服务端按提交日期（SQRQ）倒序，所以翻页可以在「凑够 limit」「见到早于下界的记录」
「翻到头」这三种情况停下来——这里用假 session 把边界钉住。
"""

from __future__ import annotations

from crb import api


class FakeSession:
    def __init__(self, pages: dict[int, list[dict]], total: int | None) -> None:
        self.pages = pages
        self.total = total
        self.calls: list[dict] = []

    def post_form(self, path: str, data: dict | None = None) -> dict:
        data = dict(data or {})
        self.calls.append(data)
        rows = self.pages.get(int(data.get("pageNumber", 1)), [])
        return {"datas": {"cxjsjysq": {"totalSize": self.total, "rows": rows}}}


def _row(sqbh: str, sqrq: str) -> dict:
    return {"SQBH": sqbh, "SQRQ": sqrq, "JYYTMS": "例会", "SHZT": "65"}


def test_limit_caps_and_flags_truncated() -> None:
    session = FakeSession(
        pages={
            1: [_row("a" * 32, "2026-10-03 10:00"), _row("b" * 32, "2026-10-02 09:00")],
            2: [_row("c" * 32, "2026-10-01 08:00"), _row("d" * 32, "2026-09-30 08:00")],
        },
        total=57,
    )
    rows, meta = api.list_borrows_window(session, "2026-2027-1", limit=3, page_size=2)
    assert len(rows) == 3
    assert meta == {"total": 57, "pages": 2, "truncated": True}
    assert [c["pageNumber"] for c in session.calls] == [1, 2]


def test_range_filters_both_ends() -> None:
    session = FakeSession(
        pages={
            1: [_row("a" * 32, "2026-10-05 10:00"), _row("b" * 32, "2026-10-04 10:00")],
            2: [_row("c" * 32, "2026-10-02 10:00"), _row("d" * 32, "2026-10-01 10:00")],
            3: [_row("e" * 32, "2026-09-30 10:00"), _row("f" * 32, "2026-09-29 10:00")],
        },
        total=57,
    )
    rows, meta = api.list_borrows_window(
        session, "2026-2027-1", since="2026-10-01", until="2026-10-03", limit=10, page_size=2
    )
    assert [r.get("SQBH") for r in rows] == ["c" * 32, "d" * 32]
    assert meta["pages"] == 3  # 翻到下界之外那一页才停
    assert meta["truncated"] is False


def test_short_page_means_end() -> None:
    session = FakeSession(pages={1: [_row("a" * 32, "2026-10-03 10:00")]}, total=1)
    rows, meta = api.list_borrows_window(session, "2026-2027-1", limit=10, page_size=2)
    assert len(rows) == 1
    assert meta == {"total": 1, "pages": 1, "truncated": False}


def test_since_stops_early() -> None:
    session = FakeSession(
        pages={
            1: [_row("a" * 32, "2026-10-03 10:00"), _row("b" * 32, "2026-10-02 09:00")],
            2: [_row("c" * 32, "2026-10-01 08:00"), _row("d" * 32, "2026-09-30 08:00")],
            3: [_row("e" * 32, "2026-09-20 08:00"), _row("f" * 32, "2026-09-19 08:00")],
        },
        total=57,
    )
    rows, meta = api.list_borrows_window(
        session, "2026-2027-1", since="2026-10-01", limit=10, page_size=2
    )
    assert len(rows) == 3  # 03 / 02 / 01；09-30 及以后被下界挡掉
    assert meta["pages"] == 2  # 第二页见到 09-30 就停，不翻第三页
    assert meta["truncated"] is False
