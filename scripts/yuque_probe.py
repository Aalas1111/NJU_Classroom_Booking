"""语雀（Yuque）自动化能力探测脚本 — 只读、可复现。

用途：验证「agent 操作语雀」的上限——能读到什么、表格能不能解析、
官方 OpenAPI 的字段长什么样。默认只发 GET 请求，绝不做任何写操作。

用法::

    export YUQUE_TOKEN=<团队/个人访问令牌>
    uv run python scripts/yuque_probe.py hello
    uv run python scripts/yuque_probe.py repos
    uv run python scripts/yuque_probe.py docs   --repo 79635820
    uv run python scripts/yuque_probe.py search 教室申请
    uv run python scripts/yuque_probe.py doc    --repo ghxd00/mrge27 --slug bbf1n662v36gd85q
    uv run python scripts/yuque_probe.py table  --repo ghxd00/pxeuoa --slug xh6wvp1yb78ztg40 --csv
    uv run python scripts/yuque_probe.py toc    --repo ghxd00/mrge27
    uv run python scripts/yuque_probe.py members
    uv run python scripts/yuque_probe.py scopes

``happy`` 会按顺序跑完前 2 项 + scopes 自检。

关于表格：官方接口返回的 ``body`` 是 ``{"format":"lakesheet", ...}``，
其中 ``sheet`` 字段是「zlib 压缩后的 JSON，但被当成 latin-1 字符串」，
解压后得到 sheets -> sheets[i]["data"][行][列] = {"v": 单元格值}。
本脚本把这一步固化成 ``table`` 子命令。
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import zlib
from typing import Any

import httpx

# ---------------------------------------------------------------- 配置
DEFAULT_HOST = "https://nova.yuque.com"
DEFAULT_GROUP = "ghxd00"


def _client(args: argparse.Namespace) -> tuple[httpx.Client, str]:
    token = args.token or os.environ.get("YUQUE_TOKEN") or os.environ.get("YQ_TOKEN")
    if not token:
        sys.exit("缺少令牌：设置 YUQUE_TOKEN 环境变量，或传 --token")
    host = (args.host or os.environ.get("YUQUE_HOST") or DEFAULT_HOST).rstrip("/")
    client = httpx.Client(
        base_url=host,
        headers={"X-Auth-Token": token, "User-Agent": "nju-yuque-probe/0.1"},
        timeout=30,
    )
    return client, host


def _get(client: httpx.Client, path: str, **params: Any) -> Any:
    resp = client.get(path, params={k: v for k, v in params.items() if v is not None})
    if resp.status_code >= 400:
        sys.exit(f"HTTP {resp.status_code} {path}: {resp.text[:300]}")
    return resp.json()


def _data(payload: Any) -> Any:
    return payload["data"] if isinstance(payload, dict) and "data" in payload else payload


def _out(obj: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
        return
    print(json.dumps(obj, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------- 各子命令
def cmd_hello(client: httpx.Client, args: argparse.Namespace) -> None:
    print(json.dumps(_data(_get(client, "/api/v2/hello")), ensure_ascii=False))


def cmd_scopes(client: httpx.Client, args: argparse.Namespace) -> None:
    """打印令牌 scope 与限流响应头（判定「这个 token 能干什么」）。"""
    resp = client.get("/api/v2/hello")
    keys = ("x-oauth-scopes", "x-ratelimit-limit", "x-ratelimit-remaining", "x-readtime")
    print(json.dumps({k: resp.headers.get(k) for k in keys}, ensure_ascii=False, indent=2))


def cmd_user(client: httpx.Client, args: argparse.Namespace) -> None:
    print(json.dumps(_data(_get(client, "/api/v2/user")), ensure_ascii=False, indent=2))


def cmd_repos(client: httpx.Client, args: argparse.Namespace) -> None:
    group = args.group or DEFAULT_GROUP
    items = _data(_get(client, f"/api/v2/groups/{group}/repos", limit=100))
    for r in items:
        print(
            f"{r['id']:<10} {r['slug']:<8} {r['name']:<20} docs={r['items_count']:<5} ns={r['namespace']}"
        )


def cmd_docs(client: httpx.Client, args: argparse.Namespace) -> None:
    if not args.repo:
        sys.exit("--repo 必填（知识库 id 或 group/slug）")
    out, offset = [], 0
    while True:
        page = _data(_get(client, f"/api/v2/repos/{args.repo}/docs", limit=100, offset=offset))
        out.extend(page)
        if len(page) < 100 or len(out) >= args.limit:
            break
        offset += len(page)
    out = out[: args.limit]
    for d in out:
        print(f"{d['id']:<10} {d['type']:<6} {d['updated_at']}  {d['title']}  (slug={d['slug']})")
    print(f"-- 共 {len(out)} 条", file=sys.stderr)


def cmd_search(client: httpx.Client, args: argparse.Namespace) -> None:
    res = _get(
        client, "/api/v2/search", q=args.query, type=args.type, page=args.page, scope=args.scope
    )
    meta = res.get("meta", {})
    print(
        f"total={meta.get('total')} page={meta.get('pageNo')}/{meta.get('pageSize')}",
        file=sys.stderr,
    )
    for d in res.get("data", []):
        print(f"[{d.get('type')}] {d['title']}\n    {d.get('info')}\n    {d.get('url')}")


def cmd_doc(client: httpx.Client, args: argparse.Namespace) -> None:
    if not args.repo or not args.slug:
        sys.exit("--repo 与 --slug 必填")
    d = _data(_get(client, f"/api/v2/repos/{args.repo}/docs/{args.slug}", raw=1))
    if args.json:
        print(
            json.dumps(
                {
                    k: d.get(k)
                    for k in ("id", "slug", "title", "format", "word_count", "updated_at")
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    body = d.get("body") or ""
    if d.get("format") == "lakesheet":
        print("[!] 这是表格(Sheet)，请用 table 子命令；下面是原始 body 片段：", file=sys.stderr)
    print(body[: args.max_chars])


def _decode_lakesheet(body: str) -> list[dict[str, Any]]:
    """把 lakesheet 的 body 解成 [{name, rows:[[cell,...],...]}, ...]。"""
    j = json.loads(body)
    raw = j["sheet"].encode("latin-1")
    sheets = json.loads(zlib.decompress(raw).decode("utf-8"))
    out = []
    for s in sheets:
        grid: list[list[str]] = []
        data = s.get("data") or {}
        height = max((int(r) for r in data), default=-1) + 1
        width = 0
        for cells in data.values():
            width = max(width, max((int(c) for c in cells), default=-1) + 1)
        for r in range(height):
            cells = data.get(str(r), {})
            row = []
            for c in range(width):
                cell = cells.get(str(c))
                row.append("" if cell is None else str(cell.get("v", "")))
            if any(v.strip() for v in row):
                grid.append(row)
        out.append({"name": s.get("name"), "rows": grid})
    return out


def cmd_table(client: httpx.Client, args: argparse.Namespace) -> None:
    """读取语雀表格(Sheet)并结构化输出（--csv 输出 CSV）。"""
    if not args.repo or not args.slug:
        sys.exit("--repo 与 --slug 必填")
    d = _data(_get(client, f"/api/v2/repos/{args.repo}/docs/{args.slug}", raw=1))
    if d.get("format") != "lakesheet":
        sys.exit(f"不是表格文档（format={d.get('format')}）")
    sheets = _decode_lakesheet(d["body"])
    if args.csv:
        buf = io.StringIO()
        w = csv.writer(buf)
        for s in sheets:
            w.writerows(s["rows"])
        sys.stdout.write(buf.getvalue())
        return
    for s in sheets:
        print(f"# sheet={s['name']} rows={len(s['rows'])}")
        for row in s["rows"][: args.limit]:
            print(json.dumps(row, ensure_ascii=False))


def cmd_toc(client: httpx.Client, args: argparse.Namespace) -> None:
    if not args.repo:
        sys.exit("--repo 必填")
    items = _data(_get(client, f"/api/v2/repos/{args.repo}/toc"))
    by_uuid = {t["uuid"]: t for t in items}

    def depth(t: dict) -> int:
        n, p = 0, t.get("parent_uuid")
        while p and p in by_uuid:
            n, p = n + 1, by_uuid[p].get("parent_uuid")
        return n

    for t in items:
        print(f"{'  ' * depth(t)}[{t['type']}] {t['title']}  url={t.get('url')}")


def cmd_members(client: httpx.Client, args: argparse.Namespace) -> None:
    group = args.group or DEFAULT_GROUP
    out, offset = {}, 0
    while True:
        page = _data(_get(client, f"/api/v2/groups/{group}/users", offset=offset, limit=100))
        if not page:
            break
        for u in page:
            user = u.get("user") or {}
            out[user.get("id")] = user.get("name") or user.get("login")
        if len(page) < 100:
            break
        offset += len(page)
    print(f"成员 {len(out)} 人", file=sys.stderr)
    for uid, name in out.items():
        print(f"{uid}\t{name}")


def cmd_happy(client: httpx.Client, args: argparse.Namespace) -> None:
    cmd_hello(client, args)
    cmd_scopes(client, args)


COMMANDS = {
    "hello": cmd_hello,
    "happy": cmd_happy,
    "scopes": cmd_scopes,
    "user": cmd_user,
    "repos": cmd_repos,
    "docs": cmd_docs,
    "search": cmd_search,
    "doc": cmd_doc,
    "table": cmd_table,
    "toc": cmd_toc,
    "members": cmd_members,
}


def main(argv: list[str] | None = None) -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass

    p = argparse.ArgumentParser(description="语雀只读能力探测（不做写操作）")
    p.add_argument("cmd", choices=COMMANDS)
    p.add_argument("query", nargs="?", default=None, help="search 的关键字")
    p.add_argument("--host", default=None, help=f"语雀域名（默认 {DEFAULT_HOST}）")
    p.add_argument("--token", default=None, help="访问令牌（也可用 YUQUE_TOKEN 环境变量）")
    p.add_argument("--group", default=None, help=f"团队 login（默认 {DEFAULT_GROUP}）")
    p.add_argument("--repo", default=None, help="知识库 id 或 group/slug")
    p.add_argument("--slug", default=None, help="文档 slug 或 id")
    p.add_argument("--limit", type=int, default=50, help="条数上限")
    p.add_argument("--max-chars", type=int, default=4000, help="doc 正文截断长度")
    p.add_argument("--page", type=int, default=1, help="search 页码")
    p.add_argument("--type", default="doc", choices=["doc", "repo"], help="search 类型")
    p.add_argument("--scope", default=None, help="search 限定知识库（group/slug）")
    p.add_argument("--csv", action="store_true", help="table 输出 CSV")
    p.add_argument("--json", action="store_true", help="JSON 输出")
    args = p.parse_args(argv)

    if args.cmd == "search" and not args.query:
        sys.exit("search 需要关键字")
    client, _ = _client(args)
    with client:
        COMMANDS[args.cmd](client, args)


if __name__ == "__main__":
    main()
