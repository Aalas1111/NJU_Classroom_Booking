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


class Session:
    """带登录态的 httpx 客户端。

    用法::

        s = Session()
        s.load()                       # 从本地读 Cookie
        rooms = api.free_rooms(s, ...) # 直接调接口
    """

    def __init__(self, auth_file: Path | None = None, timeout: float = 30.0) -> None:
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

    # ---- 请求封装 ----
    def post_form(self, path: str, data: dict[str, Any] | None = None) -> Any:
        """POST form 并解析 JSON；若返回 HTML 则视为登录失效。"""
        resp = self.client.post(path, data=data or {})
        return self._parse(resp)

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        resp = self.client.get(path, params=params or {})
        return self._parse(resp)

    @staticmethod
    def _parse(resp: httpx.Response) -> Any:
        ctype = resp.headers.get("content-type", "")
        text = resp.text
        if "json" in ctype or text.lstrip().startswith(("{", "[")):
            try:
                return resp.json()
            except json.JSONDecodeError:
                pass
        if "authserver" in text or "<title>登录" in text or "统一身份认证" in text:
            raise NotLoggedInError("登录态已失效，请重新运行 `crb login`。")
        raise RuntimeError(f"接口返回了非 JSON 内容（HTTP {resp.status_code}）：{text[:300]}")
