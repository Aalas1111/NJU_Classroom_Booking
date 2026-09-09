"""CRB 命令行入口。

命名：CRB = ClassRoom Booking（教室借用）。
所有命令默认输出人类可读文本，加 ``--json`` 输出结构化 JSON，方便 AI / 脚本消费。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from . import api, auth
from .config import CAMPUSES
from .models import BorrowRequest, FreeRoom
from .session import NotLoggedInError, Session

# Windows 控制台默认 GBK，会导致中文乱码；强制 UTF-8 输出。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="CRB — 南京大学教室借用自动化工具（默认只保存草稿，不正式提交）",
)
borrow_app = typer.Typer(no_args_is_help=True, help="教室借用申请：草稿 / 查询 / 删除")
app.add_typer(borrow_app, name="borrow")

console = Console()
err_console = Console(stderr=True)


# ---------------------------------------------------------------- 工具函数
def _dump(obj: Any) -> None:
    console.print_json(json.dumps(obj, ensure_ascii=False, default=str))


def _session() -> Session:
    s = Session()
    try:
        s.load()
    except NotLoggedInError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc
    return s


def _slot_occupied(value: str) -> bool:
    """判断某个 JC{n} 字符串是否代表「被占用」。

    ⚠️ 启发式：JC 字段形如 ``0_01_课程A,1_01_课程B``，
    前导数字疑似占用标记（1=占用）。待实测确认后再固化。
    """
    if not value:
        return False
    return any(part.strip().startswith("1_") for part in value.split(","))


def _period_free(room: FreeRoom, start: int, end: int) -> bool:
    return all(not _slot_occupied(room.periods.get(f"JC{n}", "")) for n in range(start, end + 1))


def _parse_period(text: str | None) -> tuple[int, int] | None:
    if not text:
        return None
    if "-" in text:
        a, b = text.split("-", 1)
    else:
        a = b = text
    return int(a), int(b)


# ---------------------------------------------------------------- 登录 / 自检
@app.command()
def login(
    browser: str = typer.Option(
        "auto",
        "--browser",
        "-b",
        help="浏览器：auto / chromium / msedge / chrome",
    ),
    timeout: int = typer.Option(300, "--timeout", help="等待登录完成的秒数"),
) -> None:
    """打开浏览器完成一次统一身份认证，并持久化登录态。"""
    if browser not in auth.BROWSER_CHOICES:
        err_console.print(f"[red]--browser 只能是：{' / '.join(auth.BROWSER_CHOICES)}[/red]")
        raise typer.Exit(2)
    auth.login(timeout=timeout, browser=browser)


@app.command()
def doctor() -> None:
    """自检：登录态是否有效、能否取到当前学期与系统参数。"""
    s = _session()
    term = api.current_term(s)
    params = api.system_params(s)
    org = api.my_org(s)
    console.print("[green]✓ 登录态可用[/green]")
    console.print(f"  当前学期：{term or '[red]获取失败[/red]'}")
    console.print(f"  借用开关 JSJYSFKT：{params.get('JSJYSFKT', '?')}")
    console.print(f"  可借日期 JYSJFW：{params.get('JYSJFW', '?')}")
    if org:
        console.print(f"  所在单位：{org.get('DWMC', '?')}（{org.get('DWDM', '?')}）")
    if not term:
        err_console.print("[yellow]警告：拿不到学期信息，可能登录态已过期。[/yellow]")


# ---------------------------------------------------------------- 字典
@app.command()
def campus(json_out: bool = typer.Option(False, "--json", help="输出 JSON")) -> None:
    """列出校区。"""
    rows = api.campuses(_session())
    if json_out:
        _dump([r.model_dump() for r in rows])
        return
    for r in rows:
        console.print(f"  {r.id}  {r.name}")


@app.command()
def buildings(
    campus_id: str = typer.Option(..., "--campus", "-c", help="校区代码，见 `crb campus`"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """列出某校区的教学楼。"""
    rows = api.buildings(_session(), campus_id)
    if json_out:
        _dump([r.model_dump(by_alias=True) for r in rows])
        return
    for r in rows:
        console.print(f"  {r.id}  {r.name}")


# ---------------------------------------------------------------- 空闲教室
@app.command()
def free(
    campus_id: str = typer.Option(..., "--campus", "-c", help="校区代码"),
    day: str = typer.Option(..., "--date", "-d", help="日期 YYYY-MM-DD"),
    building_id: str | None = typer.Option(None, "--building", "-b", help="教学楼代码（可选）"),
    period: str | None = typer.Option(None, "--period", "-p", help="节次，如 1-2"),
    term: str | None = typer.Option(None, "--term", help="学年学期，默认自动获取"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """查询某天某校区的空闲教室。"""
    s = _session()
    term = term or api.current_term(s)
    if not term:
        err_console.print("[red]拿不到当前学期，请用 --term 指定，或重新 `crb login`。[/red]")
        raise typer.Exit(2)

    rooms = api.free_rooms(
        s,
        campus_id=campus_id,
        day=day,
        term=term,
        building_id=building_id,
    )

    rng = _parse_period(period)
    if rng:
        err_console.print(
            "[yellow]提示：节次过滤目前为启发式（JC 字段语义待实测确认），结果仅供参考。[/yellow]"
        )
        rooms = [r for r in rooms if _period_free(r, *rng)]

    if json_out:
        _dump([r.model_dump(by_alias=True) for r in rooms])
        return

    title = f"{CAMPUSES.get(campus_id, campus_id)} {day}"
    if period:
        title += f" 第{period}节"
    table = Table(title=title)
    table.add_column("教室", style="cyan")
    table.add_column("类型")
    table.add_column("楼层", justify="right")
    table.add_column("容量", justify="right")
    for r in rooms:
        table.add_row(
            r.room_name or r.room_code,
            r.room_type_name or "",
            str(r.floor or ""),
            str(r.seat_class or ""),
        )
    console.print(table)
    console.print(f"共 {len(rooms)} 间")


# ---------------------------------------------------------------- 借用申请
@borrow_app.command("list")
def borrow_list(
    term: str | None = typer.Option(None, "--term", help="学年学期，默认自动获取"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """查看我的教室借用申请。"""
    s = _session()
    term = term or api.current_term(s)
    rows = api.list_borrows(s, term)
    if json_out:
        _dump([r.model_dump() for r in rows])
        return
    if not rows:
        console.print("（暂无申请记录）")
        return
    table = Table(title=f"我的申请 {term}")
    for col in ("SQBH", "SHZT", "JYYTMS", "XXXQDM", "KSRQ", "KSJC", "JSJC"):
        table.add_column(col)
    for r in rows:
        table.add_row(
            str(r.get("SQBH", "")),
            str(r.get("SHZT", "")),
            str(r.get("JYYTMS", ""))[:20],
            str(r.get("XXXQDM", "")),
            str(r.get("KSRQ", "")),
            str(r.get("KSJC", "")),
            str(r.get("JSJC", "")),
        )
    console.print(table)


def _load_requests(file: Path | None, data: str | None) -> list[BorrowRequest]:
    if file:
        raw = json.loads(file.read_text(encoding="utf-8"))
    elif data:
        raw = json.loads(data)
    else:
        raise typer.BadParameter("需要 --file 或 --data 提供申请数据")
    if isinstance(raw, dict):
        raw = [raw]
    return [BorrowRequest.model_validate(x) for x in raw]


@borrow_app.command("draft")
def borrow_draft(
    file: Path | None = typer.Option(None, "--file", "-f", help="申请数据 JSON 文件（数组）"),
    data: str | None = typer.Option(None, "--data", help="单条申请 JSON 字符串"),
    submit: bool = typer.Option(
        False, "--submit", help="⚠️ 正式提交（默认关闭，仅保存草稿）"
    ),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """批量保存教室借用申请草稿（默认不提交）。"""
    s = _session()
    reqs = _load_requests(file, data)
    results: list[dict[str, Any]] = []
    for i, req in enumerate(reqs, 1):
        res = api.save_borrow(s, req, submit=submit)
        results.append({"index": i, "ok": res.ok, "code": res.code, "msg": res.msg})
        mark = "[green]✓[/green]" if res.ok else "[red]✗[/red]"
        console.print(f"{mark} #{i} {req.JYYTMS[:24]} -> {res.msg or res.code}")
    if json_out:
        _dump(results)
    if not submit:
        console.print("[dim]（以上均为草稿，未正式提交）[/dim]")
    if any(not r["ok"] for r in results):
        raise typer.Exit(1)


@borrow_app.command("delete")
def borrow_delete(
    sqbh: str = typer.Option(..., "--sqbh", help="申请编号（列表里的 SQBH）"),
) -> None:
    """删除一条申请/草稿。"""
    res = api.delete_borrow(_session(), sqbh)
    mark = "[green]✓[/green]" if res.ok else "[red]✗[/red]"
    console.print(f"{mark} {res.msg or res.code}")


def main() -> None:
    try:
        app()
    except NotLoggedInError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise SystemExit(2) from exc
    except RuntimeError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
