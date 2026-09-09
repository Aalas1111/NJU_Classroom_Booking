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


class _FakeContext:
    def __init__(self, cookies: list[dict]) -> None:
        self._cookies = cookies

    def cookies(self) -> list[dict]:
        return self._cookies


def test_auth_cookies_detects_real_login() -> None:
    from crb.auth import _auth_cookies

    real = _FakeContext(
        [
            {"name": "CASTGC", "domain": "authserver.nju.edu.cn"},
            {"name": "MOD_AUTH_CAS", "domain": "ehallapp.nju.edu.cn"},
        ]
    )
    assert _auth_cookies(real) == (True, True)


def test_auth_cookies_rejects_unauthenticated() -> None:
    from crb.auth import _auth_cookies

    fake = _FakeContext([{"name": "JSESSIONID", "domain": "authserver.nju.edu.cn"}])
    assert _auth_cookies(fake) == (False, False)


def test_session_rejects_incomplete_state(tmp_path) -> None:
    from crb.session import NotLoggedInError, Session

    f = tmp_path / "auth.json"
    f.write_text('{"cookies":[{"name":"JSESSIONID","value":"x"}]}', encoding="utf-8")
    s = Session(f)
    try:
        s.load()
    except NotLoggedInError:
        pass
    else:  # pragma: no cover
        raise AssertionError("应当拒绝没有认证 Cookie 的登录态")
