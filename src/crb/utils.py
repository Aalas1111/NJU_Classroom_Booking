"""通用小工具。"""

from __future__ import annotations

import re
import unicodedata


def parse_period(text: str) -> tuple[int, int]:
    """``"1"`` -> (1, 1)；``"1-2"`` -> (1, 2)。"""
    if "-" in text:
        a, b = text.split("-", 1)
    else:
        a = b = text
    return int(a), int(b)


def periods_overlap(a1: int, a2: int, b1: int, b2: int) -> bool:
    """两个节次区间是否重叠（闭区间）。"""
    return a1 <= b2 and b1 <= a2


_ROOM_SEP = re.compile(r"[\s\-—_·]+")


def room_key(text: str | None) -> str:
    """教室名归一化后用于比对（与教师侧脚本同口径）。

    全角/罗马数字统一、去掉分隔符与空白、小写：
    ``仙Ⅰ-102`` / ``仙I_102`` / ``仙i102`` → ``仙i102``
    """
    s = unicodedata.normalize("NFKC", str(text or ""))
    return _ROOM_SEP.sub("", s).lower()
