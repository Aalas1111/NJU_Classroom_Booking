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

from . import api, auth, planner
from . import profile as profile_mod
from .config import CAMPUSES
from .models import BorrowRequest
from .session import NotLoggedInError, Session, WafBlockedError
from .utils import parse_period

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


def _parse_period(text: str) -> tuple[int, int]:
    """兼容旧调用，已统一到 utils.parse_period。"""
    return parse_period(text)


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
    phone: str | None = typer.Option(None, "--phone", help="手机号（借用申请联系方式）"),
    name: str | None = typer.Option(None, "--name", help="借用人姓名"),
) -> None:
    """打开浏览器完成一次统一身份认证，并持久化登录态；顺便采集借用人档案。"""
    if browser not in auth.BROWSER_CHOICES:
        err_console.print(f"[red]--browser 只能是：{' / '.join(auth.BROWSER_CHOICES)}[/red]")
        raise typer.Exit(2)
    auth.login(timeout=timeout, browser=browser)
    _collect_profile(phone, name)


def _collect_profile(phone: str | None, name: str | None) -> None:
    """登录后采集姓名 / 手机号 / 单位，存入本地档案。"""
    prof = profile_mod.load()
    data: dict[str, Any] = {}
    try:
        s = Session()
        s.load()
        org = api.my_org(s)
        if org.get("SZDWDM"):
            data["JYDWDM"] = org["SZDWDM"]
    except Exception:  # noqa: BLE001
        pass

    name = name or prof.get("JYRXM") or ""
    phone = phone or prof.get("JYRDH") or ""
    if sys.stdin.isatty():
        if not phone:
            phone = typer.prompt(
                "手机号（教室借用申请的联系方式，可留空稍后填）",
                default="",
                show_default=False,
            )
        if not name:
            name = typer.prompt("姓名（回车用系统默认）", default="", show_default=False)
    if name:
        data["JYRXM"] = name
    if phone:
        data["JYRDH"] = phone
    if data:
        p = profile_mod.save(data)
        console.print(f"✓ 档案已保存：{p}")
        console.print(
            f"  姓名={data.get('JYRXM', '')}  手机={data.get('JYRDH', '')}  单位={data.get('JYDWDM', '')}"
        )


@app.command("profile")
def profile_cmd(
    phone: str | None = typer.Option(None, "--phone", help="设置手机号"),
    name: str | None = typer.Option(None, "--name", help="设置姓名"),
    org: str | None = typer.Option(None, "--org", help="设置单位代码 JYDWDM"),
    campus: str | None = typer.Option(None, "--campus", help="设置默认校区代码"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """查看 / 修改本地借用人档案。"""
    changes = {
        "JYRDH": phone,
        "JYRXM": name,
        "JYDWDM": org,
        "campus": campus,
    }
    if any(v is not None for v in changes.values()):
        profile_mod.save(changes)
    prof = profile_mod.load()
    if json_out:
        _dump(prof)
        return
    console.print(f"档案文件：{profile_mod.path()}")
    for key, label in (
        ("JYRXM", "姓名"),
        ("JYRDH", "手机"),
        ("JYDWDM", "单位"),
        ("campus", "默认校区"),
        ("JSJYLXDM", "借用类型"),
    ):
        console.print(f"  {label}: {prof.get(key, '')}")


@app.command()
def doctor(json_out: bool = typer.Option(False, "--json")) -> None:
    """自检：登录态是否有效、能否取到当前学期与系统参数。"""
    s = _session()
    term = api.current_term(s)
    params = api.system_params(s)
    org = api.my_org(s)
    info = {
        "ok": bool(term),
        "term": term,
        "JSJYSFKT": params.get("JSJYSFKT"),
        "JYSJFW": params.get("JYSJFW"),
        "org": org.get("DWDM") or org.get("SZDWDM"),
    }
    if json_out:
        _dump(info)
        return
    console.print("[green]✓ 登录态可用[/green]")
    console.print(f"  当前学期：{term or '[red]获取失败[/red]'}")
    console.print(f"  借用开关 JSJYSFKT：{params.get('JSJYSFKT', '?')}")
    console.print(f"  可借日期 JYSJFW：{params.get('JYSJFW', '?')}")
    if org:
        console.print(f"  所在单位代码：{org.get('DWDM') or org.get('SZDWDM', '?')}")
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
    period: str = typer.Option(..., "--period", "-p", help="节次区间，如 1-2"),
    building_id: str | None = typer.Option(None, "--building", "-b", help="教学楼代码（可选）"),
    room_type: str | None = typer.Option(None, "--room-type", "-t", help="教室类型代码（可选）"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """查询某天、某节次区间的空闲教室（服务端按节次过滤）。"""
    s = _session()
    start, end = _parse_period(period)
    rooms = api.free_rooms(
        s,
        campus_id=campus_id,
        day=day,
        start_period=start,
        end_period=end,
        building_id=building_id,
        room_type=room_type,
    )

    if json_out:
        _dump([r.model_dump(by_alias=True) for r in rooms])
        return

    title = f"{CAMPUSES.get(campus_id, campus_id)} {day} 第{period}节 空闲教室"
    table = Table(title=title)
    table.add_column("教室", style="cyan")
    table.add_column("教学楼")
    table.add_column("类型")
    table.add_column("容量", justify="right")
    table.add_column("空闲时间")
    for r in rooms:
        table.add_row(
            r.room_name,
            r.building_name or "",
            r.room_type_name or "",
            str(r.seat_class or ""),
            r.time_label or r.period_label or "",
        )
    console.print(table)
    console.print(f"共 {len(rooms)} 间")


# ---------------------------------------------------------------- 批量规划
@app.command()
def plan(
    file: Path = typer.Option(..., "--file", "-f", help="活动列表 JSON 文件"),
    save: bool = typer.Option(False, "--save", help="把方案批量保存为草稿（默认只出方案）"),
    submit: bool = typer.Option(False, "--submit", help="⚠️ 直接正式提交（默认只存草稿）"),
    room_in_purpose: bool = typer.Option(
        True,
        "--room-in-purpose/--no-room-in-purpose",
        help="是否把意向教室写进用途描述",
    ),
    allow_overlap: bool = typer.Option(
        False, "--allow-overlap", help="允许与已有申请时间重叠（默认拦截）"
    ),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """批量规划：查空闲教室 → 分配 → 冲突检测 →（可选）批量存草稿。"""
    s = _session()
    applicant, activities = planner.load_plan(file)
    planner.apply_profile(applicant, profile_mod.load())
    if not activities:
        err_console.print("[red]活动列表为空[/red]")
        raise typer.Exit(2)

    term = api.current_term(s)
    slots, rooms = planner.existing_usage(s, term)
    if slots:
        console.print(f"[dim]已有申请 {len(slots)} 条，已纳入防重合检测[/dim]")
    assignments = planner.build_plan(
        s,
        activities,
        applicant,
        existing_slots=slots,
        existing_rooms=rooms,
        allow_overlap=allow_overlap,
    )

    if json_out and not save:
        _dump([a.model_dump(mode="json") for a in assignments])
    else:
        table = Table(title=f"教室借用方案（{len(assignments)} 条）")
        for col in ("活动", "日期", "节次", "人数", "教室", "容量", "状态"):
            table.add_column(col)
        for a in assignments:
            room = a.room.room_name if a.room else ""
            cap = (a.room.seat_class or a.room.seat_exam) if a.room else ""
            mark = {
                "ok": "[green]OK[/green]",
                "no_room": "[red]无教室[/red]",
                "too_small": "[yellow]容量不足[/yellow]",
                "duplicate": "[yellow]时间重叠[/yellow]",
                "error": "[red]错误[/red]",
            }.get(a.status, a.status)
            if a.note:
                mark += f" {a.note}"
            table.add_row(
                a.activity.title,
                a.activity.date,
                a.activity.period,
                str(a.activity.people),
                room,
                str(cap or ""),
                mark,
            )
        console.print(table)

    if not save and not submit:
        console.print("[dim]（仅方案，未写入；加 --save 存草稿 / --submit 正式提交）[/dim]")
        return

    results = planner.save_plan(
        s, assignments, applicant, room_in_purpose=room_in_purpose, submit=submit
    )
    for r in results:
        mark = "[green]✓[/green]" if r["ok"] else "[red]✗[/red]"
        console.print(f"{mark} {r['title']} -> {r['msg']}")
    if json_out:
        _dump(results)
    if any(not r["ok"] for r in results):
        raise typer.Exit(1)


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


@borrow_app.command("withdraw")
def borrow_withdraw(
    sqbh: str = typer.Option(..., "--sqbh", help="申请编号 SQBH"),
    cqdqjy: str | None = typer.Option(None, "--cqdqjy", help="长期(1)/短期(2)，默认自动识别"),
) -> None:
    """撤回一条已提交的申请（撤回后可编辑再提交）。"""
    s = _session()
    rec = api.find_borrow(s, api.current_term(s), sqbh)
    if rec is None:
        err_console.print(f"[red]未找到申请：{sqbh}[/red]")
        raise typer.Exit(2)
    cq = cqdqjy or str(rec.get("CQDQJY") or "2")
    res = api.withdraw_borrow(s, sqbh, cqdqjy=cq)
    mark = "[green]✓[/green]" if res.ok else "[red]✗[/red]"
    console.print(f"{mark} {res.msg or res.code}")


@borrow_app.command("submit")
def borrow_submit(
    sqbh: str = typer.Option(..., "--sqbh", help="申请编号 SQBH"),
) -> None:
    """把草稿/已撤回的申请正式提交（TYPE=TJ）。"""
    s = _session()
    rec = api.find_borrow(s, api.current_term(s), sqbh)
    if rec is None:
        err_console.print(f"[red]未找到申请：{sqbh}[/red]")
        raise typer.Exit(2)
    res = api.update_borrow(s, rec, submit=True)
    mark = "[green]✓[/green]" if res.ok else "[red]✗[/red]"
    console.print(f"{mark} {res.msg or res.code}")


@borrow_app.command("edit")
def borrow_edit(
    sqbh: str = typer.Option(..., "--sqbh", help="申请编号 SQBH"),
    data: str = typer.Option(
        ..., "--data", help='要修改的字段 JSON，如 {"ZRS":"35","JYYTMS":"..."}'
    ),
    draft: bool = typer.Option(False, "--draft", help="只保存草稿，不提交"),
) -> None:
    """修改一条已有申请（默认修改后重新提交）。"""
    try:
        changes = json.loads(data)
    except json.JSONDecodeError as exc:
        err_console.print(f"[red]--data 不是合法 JSON：{exc}[/red]")
        raise typer.Exit(2) from exc
    if not isinstance(changes, dict):
        err_console.print("[red]--data 必须是 JSON 对象[/red]")
        raise typer.Exit(2)
    s = _session()
    rec = api.find_borrow(s, api.current_term(s), sqbh)
    if rec is None:
        err_console.print(f"[red]未找到申请：{sqbh}[/red]")
        raise typer.Exit(2)
    res = api.update_borrow(s, rec, submit=not draft, **changes)
    mark = "[green]✓[/green]" if res.ok else "[red]✗[/red]"
    console.print(f"{mark} {res.msg or res.code}")


def main() -> None:
    try:
        app()
    except NotLoggedInError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise SystemExit(2) from exc
    except WafBlockedError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise SystemExit(3) from exc
    except RuntimeError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
