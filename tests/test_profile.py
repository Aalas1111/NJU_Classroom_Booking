"""档案两层：账号档案段（全局默认）vs 通用字段（单次/显式覆盖）。

事故背景（2026-10-07，8787 申请口）：下游把某位访客点名的「卢佳铭」写进通用字段
``JYRXM``，把账号本人的姓名顶掉了；账号没换，所以「换账号重学」也不会救回来。
这里守住两件事：① 通用写路径碰不到账号档案段；② plan 的默认值以账号档案段为准。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crb import cli, profile


@pytest.fixture()
def archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "profile.json"
    monkeypatch.setenv("CRB_PROFILE_FILE", str(target))
    return target


def _read(target: Path) -> dict:
    return json.loads(target.read_text(encoding="utf-8"))


def test_save_cannot_overwrite_account_archive(archive: Path) -> None:
    """下游那笔「单次覆盖写入」不该动账号档案段，也不该改掉默认值。"""
    profile.save_identity(account="0412007", name="郭亚敏", org="200300")
    profile.save({"JYRXM": "卢佳铭", "JYDWDM": "999999", "campus": "3", "account_name": "卢佳铭"})

    data = _read(archive)
    assert data["account_name"] == "郭亚敏"
    assert data["account_org"] == "200300"
    assert data["account"] == "0412007"
    # 通用字段照旧落地（兼容旧读法），但默认层用的是账号档案段
    assert data["JYRXM"] == "卢佳铭"
    assert data["campus"] == "3"
    assert profile.defaults()["JYRXM"] == "郭亚敏"
    assert profile.defaults()["JYDWDM"] == "200300"


def test_save_identity_keeps_known_values(archive: Path) -> None:
    profile.save_identity(account="0412007", name="郭亚敏", org="200300")
    profile.save_identity(account="0412007")  # 只给账号：姓名/单位不能被抹掉
    assert profile.identity() == {"account": "0412007", "name": "郭亚敏", "org": "200300"}


def test_defaults_fall_back_to_generic_for_legacy_file(archive: Path) -> None:
    """老档案（没有账号档案段）：行为不变，仍旧用 JYRXM / JYDWDM。"""
    archive.write_text(
        json.dumps({"JYRXM": "李赫", "JYDWDM": "400760", "JYRDH": "138"}), encoding="utf-8"
    )
    defaults = profile.defaults()
    assert defaults["JYRXM"] == "李赫"
    assert defaults["JYDWDM"] == "400760"
    assert defaults["JYRDH"] == "138"


def test_save_skips_empty_values(archive: Path) -> None:
    profile.save_identity(name="郭亚敏")
    profile.save({"JYRXM": "", "JYRDH": None, "campus": "4"})
    data = _read(archive)
    assert data["account_name"] == "郭亚敏"
    assert "JYRXM" not in data
    assert data["campus"] == "4"


def test_plan_defaults_keep_account_identity(archive: Path) -> None:
    """plan 那条链：没写 defaults 的字段用账号档案段；显式覆盖仍旧生效。"""
    from crb import planner
    from crb.models import Applicant

    profile.save_identity(account="0412007", name="郭亚敏", org="200300")
    profile.save({"JYRXM": "卢佳铭"})  # 上一场事故留下的尾巴

    applicant = Applicant()
    planner.apply_profile(applicant, profile.defaults())
    assert applicant.JYRXM == "郭亚敏"
    assert applicant.JYDWDM == "200300"

    applicant = Applicant.model_validate({"JYRXM": "卢佳铭"})  # 显式单次覆盖
    planner.apply_profile(applicant, profile.defaults())
    assert applicant.JYRXM == "卢佳铭"
    assert applicant.JYDWDM == "200300"  # 没点名的照旧用账号档案段


def test_ensure_profile_identity_relearns_on_account_switch(
    archive: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile.save_identity(account="0412007", name="郭亚敏", org="200300")
    calls: list[str] = []

    monkeypatch.setattr(cli.api, "account_identity", lambda _s: {"name": "李赫", "account": "123"})
    monkeypatch.setattr(cli.api, "my_org", lambda _s: calls.append("org") or {"SZDWDM": "400760"})

    cli._ensure_profile_identity(object())  # type: ignore[arg-type]

    assert calls == ["org"]
    assert profile.identity() == {"account": "123", "name": "李赫", "org": "400760"}
    assert _read(archive)["JYRXM"] == "李赫"  # 兼容投影跟着走


def test_ensure_profile_identity_is_quiet_when_account_matches(
    archive: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile.save_identity(account="0412007", name="郭亚敏", org="200300")

    def boom(_s: object) -> dict[str, str]:
        raise AssertionError("档案已是当前账号，不该再打学校接口")

    monkeypatch.setattr(
        cli.api, "account_identity", lambda _s: {"name": "郭亚敏", "account": "0412007"}
    )
    monkeypatch.setattr(cli.api, "my_org", boom)

    cli._ensure_profile_identity(object())  # type: ignore[arg-type]
    assert profile.identity()["name"] == "郭亚敏"


def test_ensure_profile_identity_survives_probe_failure(
    archive: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """取不到账号信息（风控/接口变了）→ 保留档案里那份，不猜。"""
    profile.save_identity(account="0412007", name="郭亚敏", org="200300")

    def boom(_s: object) -> dict[str, str]:
        raise RuntimeError("403")

    monkeypatch.setattr(cli.api, "account_identity", boom)
    prof = cli._ensure_profile_identity(object())  # type: ignore[arg-type]
    assert profile.identity(prof)["name"] == "郭亚敏"
