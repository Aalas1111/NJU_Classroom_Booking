"""登录态管理 + HTTP 会话。

登录态来自 Playwright 的 storage_state（含 NJU 统一认证 Cookie）。
我们用 httpx 复用它，直接调用学校后端接口，不再驱动浏览器。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx

from .config import EHALL_HOST, state_path


class NotLoggedInError(RuntimeError):
    """本地没有登录态，或登录态已失效。"""


class WafBlockedError(RuntimeError):
    """请求被学校 WAF（风控）拦截。"""


class Session:
    """带登录态的 httpx 客户端。

    用法::

        s = Session()
        s.load()                       # 从本地读 Cookie
        rooms = api.free_rooms(s, ...) # 直接调接口
    """

    def __init__(self, auth_file: Path | None = None, timeout: float = 60.0) -> None:
        self.auth_file = auth_file or state_path()
        self.timeout = timeout
        self._client: httpx.Client | None = None

    # ---- 登录态读写 ----
    def exists(self) -> bool:
        return self.auth_file.is_file()

    def load(self) -> dict[str, Any]:
        if not self.exists():
            raise NotLoggedInError(
                f"未找到登录态：{self.auth_file}\n先运行 `crb login` 完成一次扫码登录。"
            )
        state = json.loads(self.auth_file.read_text(encoding="utf-8"))
        names = {c.get("name") for c in state.get("cookies", [])}
        if not ({"CASTGC", "MOD_AUTH_CAS"} & names):
            raise NotLoggedInError(
                f"登录态文件里没有认证 Cookie（可能是一次未完成的登录）：{self.auth_file}\n"
                "请重新运行 `crb login` 并完成扫码/密码登录。"
            )
        cookies = httpx.Cookies()
        for c in state.get("cookies", []):
            cookies.set(
                c["name"],
                c["value"],
                domain=c.get("domain"),
                path=c.get("path", "/"),
            )
        self._client = httpx.Client(
            base_url=EHALL_HOST,
            cookies=cookies,
            timeout=self.timeout,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
                ),
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{EHALL_HOST}/jwapp/sys/jsjy/*default/index.do",
            },
        )
        return state

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self.load()
        assert self._client is not None
        return self._client

    def save(self, state: dict[str, Any]) -> Path:
        self.auth_file.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(state)
        payload.setdefault("saved_at", time.time())
        self.auth_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        try:  # 尽量收紧权限（Windows 上可能无效，忽略即可）
            self.auth_file.chmod(0o600)
        except OSError:
            pass
        return self.auth_file

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    # ---- 风控 Cookie 刷新 ----
    def refresh(self, browser: str = "auto", wait_ms: int = 2500) -> bool:
        """用无头浏览器加载一次应用页，刷新 _WEU 等风控 Cookie，并写回登录态。

        学校 WAF 的 `_WEU` Cookie 会过期；浏览器一加载页面就会重新下发。
        返回是否成功（未安装 Playwright / 无登录态时返回 False）。
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return False
        if not self.exists():
            return False

        from .browser import launch
        from .config import JY_ENTRY

        state = json.loads(self.auth_file.read_text(encoding="utf-8"))
        with sync_playwright() as p:
            browser_obj, _ = launch(p, browser, headless=True)
            context = browser_obj.new_context(storage_state=state)
            page = context.new_page()
            page.goto(JY_ENTRY, wait_until="domcontentloaded")
            page.wait_for_timeout(wait_ms)
            new_state = context.storage_state()
            browser_obj.close()
        self.save(new_state)
        self.close()  # 强制用新 Cookie 重建客户端
        return True

    # ---- 请求封装 ----
    def _with_retry(self, fn, attempts: int = 3):
        """对瞬时网络错误（超时/连接失败）重试。首次请求冷启动可能较慢。"""
        last: Exception | None = None
        for i in range(attempts):
            try:
                return fn()
            except httpx.TransportError as exc:
                last = exc
                if i < attempts - 1:
                    time.sleep(1.5 * (i + 1))
        assert last is not None
        raise last

    def _request(self, method: str, path: str, *, data=None, params=None) -> Any:
        def call() -> httpx.Response:
            if method == "post":
                return self.client.post(path, data=data or {})
            return self.client.get(path, params=params or {})

        resp = self._with_retry(call)
        if resp.status_code == 403 and self.refresh():
            # 风控 Cookie 过期：刷新后重建客户端再试一次
            resp = self._with_retry(call)
        return self._parse(resp)

    def post_form(self, path: str, data: dict[str, Any] | None = None) -> Any:
        """POST form 并解析 JSON；若返回 HTML 则视为登录失效。"""
        return self._request("post", path, data=data)

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._request("get", path, params=params)

    @staticmethod
    def _parse(resp: httpx.Response) -> Any:
        ctype = resp.headers.get("content-type", "")
        text = resp.text
        if "json" in ctype or text.lstrip().startswith(("{", "[")):
            try:
                return resp.json()
            except json.JSONDecodeError:
                pass
        if resp.status_code == 403:
            raise WafBlockedError(
                "请求被学校 WAF 拦截（403）。已尝试自动刷新风控 Cookie；"
                "若仍失败，请重新运行 `crb login`。"
            )
        if "authserver" in text or "<title>登录" in text or "统一身份认证" in text:
            raise NotLoggedInError("登录态已失效，请重新运行 `crb login`。")
        raise RuntimeError(f"接口返回了非 JSON 内容（HTTP {resp.status_code}）：{text[:300]}")
