"""登录：驱动一次有头浏览器完成统一身份认证，然后把登录态持久化。

设计取舍
--------
* 不接触用户密码/二维码内容，用户在自己熟悉的官方登录页扫码或输密码；
* 登录完成后我们只保存 Cookie（storage_state），后续全部走 httpx 直连接口；
* 浏览器优先用 Playwright 自带的 Chromium，没有就自动回退到系统已装的
  Edge / Chrome（免去下载 ~150MB 的浏览器）。

后续可扩展：把二维码直接抓取到应用内展示（见 docs/思维过程1.md）。
"""

from __future__ import annotations

import re
from pathlib import Path

from .config import JY_ENTRY
from .session import Session

_EHALL_RE = re.compile(r"ehallapp\.nju\.edu\.cn")

# auto = 依次尝试自带 Chromium -> Edge -> Chrome
BROWSER_CHOICES = ("auto", "chromium", "msedge", "chrome")


def _launch(p, browser: str):
    """按需启动浏览器，返回 (browser 实例, 实际使用的名字)。"""
    from playwright.sync_api import Error as PWError

    order = ["chromium", "msedge", "chrome"] if browser == "auto" else [browser]
    errors: list[str] = []
    for name in order:
        try:
            if name == "chromium":
                return p.chromium.launch(headless=False), name
            return p.chromium.launch(headless=False, channel=name), name
        except PWError as exc:  # 该浏览器不存在/无法启动，继续尝试下一个
            errors.append(f"{name}: {str(exc).splitlines()[0]}")
    raise SystemExit(
        "无法启动任何浏览器，请任选其一：\n"
        "  1) 安装系统 Edge / Chrome（推荐，免下载）；\n"
        "  2) 下载 Playwright Chromium：`uv run playwright install chromium`\n"
        "已尝试：\n  " + "\n  ".join(errors)
    )


def login(
    state_file: Path | None = None,
    timeout: int = 300,
    browser: str = "auto",
) -> Path:
    """打开浏览器让用户登录，成功后保存登录态并返回文件路径。

    Args:
        state_file: 登录态保存位置，默认 ``~/.crb/auth.json``。
        timeout: 等待登录完成的最长秒数。
        browser: ``auto`` / ``chromium`` / ``msedge`` / ``chrome``。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "缺少 Playwright，请先安装：\n  uv sync --extra login"
        ) from exc

    session = Session(state_file)
    session.auth_file.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser_obj, used = _launch(p, browser)
        context = browser_obj.new_context()
        page = context.new_page()
        print(f"→ 已用 {used} 打开浏览器，请完成南京大学统一身份认证（扫码或账号密码）。")
        print(f"  等待登录完成，最多 {timeout} 秒……")
        page.goto(JY_ENTRY, wait_until="domcontentloaded")
        try:
            # 登录成功后会被重定向回 ehallapp
            page.wait_for_url(_EHALL_RE, timeout=timeout * 1000)
            page.wait_for_load_state("domcontentloaded")
        except Exception as exc:  # noqa: BLE001
            browser_obj.close()
            raise SystemExit(f"登录未在限定时间内完成：{exc}") from exc

        state = context.storage_state()
        browser_obj.close()

    session.save(state)
    print(f"✓ 登录态已保存到：{session.auth_file}")
    return session.auth_file
