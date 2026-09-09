"""基础单元测试（不依赖网络 / 登录态）。"""

from __future__ import annotations

from crb import api
from crb.cli import _parse_period, _period_free, _slot_occupied
from crb.models import BorrowRequest, FreeRoom


def test_term_parts() -> None:
    assert api.term_parts("2026-2027-1") == ("2026-2027", "1")
    assert api.term_parts("2026-2027-2") == ("2026-2027", "2")


def test_query_setting_format() -> None:
    s = api._query_setting([api._cond("XXXQDM", "3")])
    assert s == '[{"name":"XXXQDM","value":"3","builder":"equal","linkOpt":"AND"}]'


def test_parse_period() -> None:
    assert _parse_period(None) is None
    assert _parse_period("1") == (1, 1)
    assert _parse_period("1-2") == (1, 2)


def test_slot_occupied_heuristic() -> None:
    assert _slot_occupied("") is False
    assert _slot_occupied("0_01_课程A,0_01_课程B") is False
    assert _slot_occupied("0_01_课程A,1_01_课程B") is True


def test_period_free() -> None:
    room = FreeRoom.model_validate(
        {"JASDM": "X-101", "JASMC": "仙Ⅰ-101", "JC1": "0_01_课A", "JC2": "1_01_课B"}
    )
    room.periods = {"JC1": "0_01_课A", "JC2": "1_01_课B"}
    assert _period_free(room, 1, 1) is True
    assert _period_free(room, 1, 2) is False


def test_borrow_request_defaults() -> None:
    req = BorrowRequest(JYYTMS="测试", XXXQDM="3")
    payload = req.as_payload()
    assert payload["JYLYDM"] == "02"
    assert payload["JSJYSQLX"] == 2
    assert payload["TYPE"] == "save"
