"""登录：驱动一次有头浏览器完成统一身份认证，然后把登录态持久化。

设计取舍
--------
* 不接触用户密码/二维码内容，用户在自己熟悉的官方登录页扫码或输密码；
* 登录完成后我们只保存 Cookie（storage_state），后续全部走 httpx 直连接口；
* 浏览器优先用 Playwright 自带的 Chromium，没有就自动回退到系统已装的
  Edge / Chrome（免去下载 ~150MB 的浏览器）；
* **登录完成的判据是真实认证 Cookie（CASTGC / MOD_AUTH_CAS），不是 URL**，
  否则刚打开页面就会误判为已登录。

后续可扩展：把二维码直接抓取到应用内展示（见 docs/思维过程1.md）。
"""

from __future__ import annotations

import re
import time
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


def _auth_cookies(context) -> tuple[bool, bool]:
    """返回 (是否有统一认证 TGT, 是否有办事大厅会话)。

    - CASTGC：authserver 下发的 CAS 票据（登录成功才会出现）
    - MOD_AUTH_CAS：ehallapp 校验票据后下发的应用会话
    """
    has_tgc = has_app = False
    for c in context.cookies():
        name, domain = c.get("name", ""), c.get("domain", "")
        if name == "CASTGC":
            has_tgc = True
        if name == "MOD_AUTH_CAS" and "ehallapp" in domain:
            has_app = True
    return has_tgc, has_app


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
        raise SystemExit("缺少 Playwright，请先安装：\n  uv sync --extra login") from exc

    session = Session(state_file)
    session.auth_file.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser_obj, used = _launch(p, browser)
        context = browser_obj.new_context()
        page = context.new_page()
        print(f"→ 已用 {used} 打开浏览器，请完成南京大学统一身份认证（扫码或账号密码）。")
        print(f"  等待登录完成，最多 {timeout} 秒……")
        page.goto(JY_ENTRY, wait_until="domcontentloaded")

        deadline = time.monotonic() + timeout
        ok = False
        while time.monotonic() < deadline:
            try:
                has_tgc, has_app = _auth_cookies(context)
            except Exception:  # 浏览器被用户关掉了
                break
            if has_tgc and has_app:
                ok = True
                break
            page.wait_for_timeout(500)

        if not ok:
            browser_obj.close()
            raise SystemExit(
                "未检测到登录成功（超时或浏览器被关闭）。\n"
                "提示：需要在弹出的浏览器里完成扫码/密码登录，直到页面回到办事大厅。"
            )

        # 认证已通过，等页面回到 ehallapp 并让应用 Cookie 写全
        try:
            page.wait_for_url(_EHALL_RE, timeout=20_000)
            page.wait_for_load_state("domcontentloaded")
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(1000)

        state = context.storage_state()
        browser_obj.close()

    session.save(state)
    print(f"✓ 登录态已保存到：{session.auth_file}")
    return session.auth_file
