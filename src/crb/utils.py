"""通用小工具。"""

from __future__ import annotations

import re
import unicodedata

from .config import PERIOD_TIMES

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_iso_date(text: str) -> bool:
    """``2026-09-30`` 这种形状 —— 送到学校之前先挡一道，别让它去猜。"""
    return bool(_ISO_DATE.match(str(text or "").strip()))


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


def slot_time(period: int) -> str:
    """单节的起止时间：``7`` -> ``16:10-17:00``。"""
    span = PERIOD_TIMES.get(period)
    return f"{span[0]}-{span[1]}" if span else ""


def span_label(a1: int, a2: int) -> str:
    """节次区间的短标签：``(1, 2)`` -> ``1-2``；``(7, 7)`` -> ``7``。"""
    return f"{a1}-{a2}" if a2 != a1 else str(a1)


def span_time(a1: int, a2: int) -> str:
    """节次区间的起止时间：``(3, 4)`` -> ``10:10-12:00``。"""
    start = PERIOD_TIMES.get(a1)
    end = PERIOD_TIMES.get(a2)
    if not start or not end:
        return ""
    return f"{start[0]}-{end[1]}"


_ROOM_SEP = re.compile(r"[\s\-—_·]+")
#: 教室名里的「数字变体」。注意：**必须在 NFKC 之前**换 —— NFKC 会把罗马数字 Ⅰ
#: 拆成字母 I（`仙Ⅰ` → `仙i`），而 Ⅱ 会变成 II（两个字母），再想还原成 2 就晚了。
_NUM_VARIANTS = {
    "一": "1",
    "二": "2",
    "三": "3",
    "四": "4",
    "五": "5",
    "六": "6",
    "七": "7",
    "八": "8",
    "九": "9",
    "十": "10",
    "Ⅰ": "1",
    "Ⅱ": "2",
    "Ⅲ": "3",
    "Ⅳ": "4",
    "Ⅴ": "5",
    "Ⅵ": "6",
    "Ⅶ": "7",
    "Ⅷ": "8",
    "Ⅸ": "9",
    "Ⅹ": "10",
}


def room_key(text: str | None) -> str:
    """教室名归一化后用于比对（与教师侧脚本同口径）。

    全角/罗马数字统一、去掉分隔符与空白、小写：
    ``仙Ⅰ-102`` / ``仙I_102`` / ``仙i102`` → ``仙i102``
    """
    s = unicodedata.normalize("NFKC", str(text or ""))
    return _ROOM_SEP.sub("", s).lower()


def room_key_loose(text: str | None) -> str:
    """更宽的教室名口径：再把罗马/中文数字压成阿拉伯数字。

    ``仙Ⅰ-501`` / ``仙一501`` / ``仙I501``（NFKC 后是 ``仙i501``）→ ``仙1501``。
    只在严格口径对不上时才用它 —— 口语里的「仙一」和系统里的「仙Ⅰ」是同一个。
    """
    s = "".join(_NUM_VARIANTS.get(ch, ch) for ch in str(text or ""))
    return room_key(s)
