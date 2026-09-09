"""内置 Skill 的读取与安装。

Skill（``SKILL.md``）随 wheel 一起分发，位于 ``crb/data/SKILL.md``。
本模块只负责把它读出来 / 装到 AI harness 的 skills 目录里，不涉及网络。
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

SKILL_NAME = "crb"
SKILL_FILENAME = "SKILL.md"
_DATA_PACKAGE = "crb.data"


def skill_text() -> str:
    """返回内置 SKILL.md 的完整文本。"""
    return resources.files(_DATA_PACKAGE).joinpath(SKILL_FILENAME).read_text(encoding="utf-8")


def skill_path() -> Path:
    """返回内置 SKILL.md 的磁盘路径（安装后指向 site-packages 内）。"""
    with resources.as_file(resources.files(_DATA_PACKAGE).joinpath(SKILL_FILENAME)) as path:
        return Path(path)


def install(target_root: Path | str, *, force: bool = False) -> Path:
    """把内置 skill 安装到 ``<target_root>/crb/SKILL.md``。

    Args:
        target_root: AI harness 的 skills 根目录，例如 ``.pi/skills``。
        force: 已存在时是否覆盖。

    Returns:
        实际写入的文件路径。

    Raises:
        FileExistsError: 目标已存在且 ``force=False``。
    """
    dest = Path(target_root).expanduser() / SKILL_NAME / SKILL_FILENAME
    if dest.exists() and not force:
        raise FileExistsError(str(dest))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(skill_text(), encoding="utf-8")
    return dest
