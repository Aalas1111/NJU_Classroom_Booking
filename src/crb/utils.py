"""通用小工具。"""

from __future__ import annotations


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
