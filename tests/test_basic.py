"""基础单元测试（不依赖网络 / 登录态）。"""

from __future__ import annotations

from typer.testing import CliRunner

from crb import api
from crb.cli import _parse_period
from crb.models import BorrowRecord, BorrowRequest, FreeRoomSlot


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


def test_login_rejects_bad_browser_option() -> None:
    """回归：BROWSER_CHOICES 定义在 browser.py，cli 曾经误从 auth 取导致 AttributeError。"""
    from ansi_text import plain

    from crb.browser import BROWSER_CHOICES
    from crb.cli import app

    result = CliRunner().invoke(app, ["login", "--browser", "not-a-browser"])
    assert result.exit_code == 2
    for name in BROWSER_CHOICES:
        assert name in plain(result.output)


class _DictSession:
    """只回借用类型字典的假会话（cxjsjylx.do）。"""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def post_form(self, path, data=None):
        assert path == api.EP_BORROW_TYPE
        return {"datas": {"cxjsjylx": {"rows": self._rows}}}


def test_borrow_contract_detects_student() -> None:
    sess = _DictSession(
        [
            {"JSJYLXDM": "01", "JSJYLXMC": "辅导员"},
            {"JSJYLXDM": "02", "JSJYLXMC": "学生社团管理部"},
        ]
    )
    role, codes = api.borrow_contract(sess)  # type: ignore[arg-type]
    assert role == "student"
    assert api.default_borrow_type(role) == "02"
    assert api.check_borrow_type("02", role, codes) == ""


def test_borrow_contract_detects_teacher_and_rejects_student_code() -> None:
    """同名字段两套字典：教师端不认学生端代码 02。"""
    sess = _DictSession(
        [
            {"JSJYLXDM": "07", "JSJYLXMC": "教师教学、补课"},
            {"JSJYLXDM": "09", "JSJYLXMC": "团学活动"},
            {"JSJYLXDM": "40", "JSJYLXMC": "讲座"},
        ]
    )
    role, codes = api.borrow_contract(sess)  # type: ignore[arg-type]
    assert role == "teacher"
    assert api.default_borrow_type(role) == "09"
    problem = api.check_borrow_type("02", role, codes)
    assert "02" in problem and "教师端" in problem and "09 团学活动" in problem
    assert api.check_borrow_type("09", role, codes) == ""


def test_borrow_contract_unknown_dict_skips_check() -> None:
    sess = _DictSession([{"JSJYLXDM": "88", "JSJYLXMC": "??? "}])
    role, codes = api.borrow_contract(sess)  # type: ignore[arg-type]
    assert role == "unknown"
    assert api.default_borrow_type(role) == ""
    assert api.check_borrow_type("02", role, codes) != ""  # 字典可用就仍校验
