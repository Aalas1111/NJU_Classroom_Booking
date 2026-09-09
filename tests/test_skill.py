"""Skill 打包 / 安装 / 仓库副本一致性测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from crb import __version__, skill
from crb.cli import app

ROOT = Path(__file__).resolve().parents[1]
REPO_SKILL = ROOT / ".pi" / "skills" / "crb" / "SKILL.md"


def test_skill_text_has_frontmatter() -> None:
    text = skill.skill_text()
    assert text.startswith("---\n")
    assert "name: crb" in text.split("---")[1]
    assert "description:" in text.split("---")[1]


def test_skill_path_exists() -> None:
    assert skill.skill_path().is_file()


def test_repo_copy_in_sync() -> None:
    """仓库内的 .pi 副本必须与包内事实来源一致（跑 scripts/sync_skill.py 修复）。"""
    assert REPO_SKILL.read_text(encoding="utf-8") == skill.skill_text()


def test_install_and_overwrite(tmp_path: Path) -> None:
    dest = skill.install(tmp_path)
    assert dest == tmp_path / "crb" / "SKILL.md"
    assert dest.read_text(encoding="utf-8") == skill.skill_text()

    with pytest.raises(FileExistsError):
        skill.install(tmp_path)

    dest.write_text("stale", encoding="utf-8")
    assert skill.install(tmp_path, force=True) == dest
    assert dest.read_text(encoding="utf-8") == skill.skill_text()


def test_cli_version() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_cli_skill_show() -> None:
    result = CliRunner().invoke(app, ["skill", "show"])
    assert result.exit_code == 0
    assert result.output.startswith("---")


def test_cli_skill_install(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["skill", "install", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "crb" / "SKILL.md").is_file()

    again = CliRunner().invoke(app, ["skill", "install", "--dir", str(tmp_path)])
    assert again.exit_code == 2
