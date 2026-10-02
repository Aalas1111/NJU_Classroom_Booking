"""申请列表「翻页早停」（``api.list_borrows_window``）的行为测试。

列表在累积，所以默认只关心最近一段：服务端按提交日期（SQRQ）倒序，
翻页一旦越过窗口起点就停——这里用假 session 把这几条边界钉住。
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


def test_stops_after_seeing_older_than_since() -> None:
    session = FakeSession(
        pages={
            1: [_row("a" * 32, "2026-10-03 10:00"), _row("b" * 32, "2026-10-02 09:00")],
            2: [_row("c" * 32, "2026-10-01 08:00"), _row("d" * 32, "2026-09-30 08:00")],
            3: [_row("e" * 32, "2026-09-20 08:00")],
        },
        total=57,
    )
    rows, meta = api.list_borrows_window(session, "2026-2027-1", since="2026-10-01", page_size=2)
    assert [c["pageNumber"] for c in session.calls] == [1, 2]  # 第二页见 09-30 就停
    assert len(rows) == 4
    assert meta == {"total": 57, "pages": 2, "exhausted": False}


def test_short_page_means_exhausted() -> None:
    session = FakeSession(pages={1: [_row("a" * 32, "2026-10-03 10:00")]}, total=1)
    rows, meta = api.list_borrows_window(session, "2026-2027-1", since="2026-10-01", page_size=2)
    assert len(rows) == 1
    assert meta["exhausted"] is True
    assert meta["pages"] == 1


def test_max_pages_cap() -> None:
    full = [_row(f"{i:032x}", "2026-10-03 10:00") for i in range(2)]
    session = FakeSession(pages={1: full, 2: full, 3: full}, total=99)
    rows, meta = api.list_borrows_window(
        session, "2026-2027-1", since="2026-01-01", page_size=2, max_pages=2
    )
    assert meta["pages"] == 2  # 到上限就停，不无限翻
    assert len(rows) == 4


def test_empty_since_is_single_page() -> None:
    full = [_row(f"{i:032x}", "2026-10-03 10:00") for i in range(2)]
    session = FakeSession(pages={1: full, 2: full}, total=99)
    rows, meta = api.list_borrows_window(session, "2026-2027-1", page_size=2)
    assert meta["pages"] == 1
    assert len(rows) == 2
