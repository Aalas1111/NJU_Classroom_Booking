"""基础单元测试（不依赖网络 / 登录态）。"""

from __future__ import annotations

from crb import api
from crb.cli import _parse_period
from crb.models import BorrowRequest, FreeRoomSlot


def test_term_parts() -> None:
    assert api.term_parts("2026-2027-1") == ("2026-2027", "1")
    assert api.term_parts("2026-2027-2") == ("2026-2027", "2")


def test_query_setting_format() -> None:
    s = api._query_setting([api._cond("XXXQDM", "3")])
    assert s == '[{"name":"XXXQDM","value":"3","builder":"equal","linkOpt":"AND"}]'


def test_parse_period() -> None:
    assert _parse_period("1") == (1, 1)
    assert _parse_period("1-2") == (1, 2)


def test_free_room_slot_aliases() -> None:
    slot = FreeRoomSlot.model_validate(
        {
            "JASMC": "仙Ⅰ-102",
            "JXLDM_DISPLAY": "仙I区",
            "JASLXDM_DISPLAY": "普通多媒体（阶梯）",
            "SKZWS": 96,
            "KXRQ": "2026-09-10",
            "KSJC": 1,
            "JSJC": 2,
            "KXSJ": "08:00-08:50,09:00-09:50",
        }
    )
    assert slot.room_name == "仙Ⅰ-102"
    assert slot.building_name == "仙I区"
    assert slot.seat_class == 96
    assert slot.start_period == 1
    assert slot.time_label == "08:00-08:50,09:00-09:50"


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


class _FakeSession:
    def __init__(self) -> None:
        self.last: tuple | None = None

    def post_form(self, path, data=None):
        self.last = (path, data)
        return {"datas": {"xzjasjysq": {"extParams": {"code": 1, "msg": "ok"}}}}


def test_update_borrow_maps_list_aliases() -> None:
    """列表记录用 JASJYLXDM，申请表要 JSJYLXDM；缺失字段用默认值兜底。"""
    import json

    from crb import api

    sess = _FakeSession()
    rec = BorrowRecord.model_validate(
        {"WID": "w1", "SQBH": "s1", "JASJYLXDM": "02", "JYYTMS": "x", "ZRS": "30"}
    )
    res = api.update_borrow(sess, rec, submit=True, ZRS="35")
    assert res.ok
    payload = json.loads(sess.last[1]["param"])[0]  # type: ignore[index]
    assert payload["JSJYLXDM"] == "02"  # 别名映射
    assert payload["ZRS"] == "35"  # 修改生效
    assert payload["TYPE"] == "TJ"
    assert payload["WID"] == "w1" and payload["SQBH"] == "s1"
    assert payload["JSJYSQLX"] == 2  # 默认值兜底


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
