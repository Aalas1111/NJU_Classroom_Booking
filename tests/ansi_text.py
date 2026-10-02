"""测试用的 ANSI 去色小工具。

**为什么需要**（2026-10-02，CI 连续红了 4 次推送）：在会强制 ANSI 的环境
（GitHub Actions）里，rich 会把 `--room` 这类 token 拆成 `-` + `-room` 两段样式，
中间夹着 `\\x1b[0m`——直接对**原始输出**做子串断言会「在 CI 上断、在本地过」。
凡是断言 CLI 输出文本的测试，一律先过 :func:`plain`。
"""

from __future__ import annotations

import re

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(text: str) -> str:
    """去掉 ANSI 样式序列（SGR）。"""
    return _ANSI.sub("", text)
