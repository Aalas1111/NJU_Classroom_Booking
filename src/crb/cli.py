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

from . import __version__, api, auth, planner, roomview
from . import profile as profile_mod
from . import skill as skill_mod
from .browser import BROWSER_CHOICES
from .config import CAMPUSES, ROLE_LABELS
from .models import BorrowRequest, FreeRoomSlot, PeriodSpan, RoomInfo
from .session import NotLoggedInError, Session, WafBlockedError
from .utils import is_iso_date, parse_period, room_key_loose

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
skill_app = typer.Typer(no_args_is_help=True, help="内置 AI Skill：查看 / 安装")
app.add_typer(skill_app, name="skill")

#: 一次最多查几个日期 —— 一天一发请求，但别让一句「查这学期」把学校扫一遍。
MAX_QUERY_DATES = 31

console = Console()
err_console = Console(stderr=True)


# ---------------------------------------------------------------- 工具函数
def _dump(obj: Any) -> None:
    console.print_json(json.dumps(obj, ensure_ascii=False, default=str))


def _emit_result(res: api.SaveResult, json_out: bool) -> None:
    """统一输出写操作结果（--json 时只输出 JSON）。"""
    if json_out:
        _dump({"ok": res.ok, "code": res.code, "msg": res.msg})
        return
    mark = "[green]✓[/green]" if res.ok else "[red]✗[/red]"
    console.print(f"{mark} {res.msg or res.code}")


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


# ---------------------------------------------------------------- 全局选项
def _version_callback(value: bool) -> None:
    if value:
        console.print(f"crb {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="显示版本并退出",
        is_eager=True,
        callback=_version_callback,
    ),
) -> None:
    """CRB — 南京大学教室借用自动化工具（默认只保存草稿，不正式提交）。"""
    del version  # 由 _version_callback 处理


# ---------------------------------------------------------------- Skill
@skill_app.command("path")
def skill_path_cmd() -> None:
    """打印内置 SKILL.md 的路径。"""
    console.print(str(skill_mod.skill_path()))


@skill_app.command("show")
def skill_show_cmd() -> None:
    """原样打印内置 SKILL.md 内容（便于重定向到文件）。"""
    text = skill_mod.skill_text()
    sys.stdout.write(text if text.endswith("\n") else f"{text}\n")


@skill_app.command("install")
def skill_install_cmd(
    directory: Path = typer.Option(
        Path(".pi/skills"),
        "--dir",
        "-d",
        help="AI harness 的 skills 根目录（如 .pi/skills、~/.claude/skills）",
    ),
    force: bool = typer.Option(False, "--force", "-f", help="已存在时覆盖"),
) -> None:
    """把内置 skill 安装到 <dir>/crb/SKILL.md。"""
    try:
        dest = skill_mod.install(directory, force=force)
    except FileExistsError as exc:
        err_console.print(f"[red]已存在：{exc}（加 --force 覆盖）[/red]")
        raise typer.Exit(2) from exc
    console.print(f"[green]✓[/green] skill 已安装：{dest}")


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
    if browser not in BROWSER_CHOICES:
        err_console.print(f"[red]--browser 只能是：{' / '.join(BROWSER_CHOICES)}[/red]")
        raise typer.Exit(2)
    auth.login(timeout=timeout, browser=browser)
    _collect_profile(phone, name)


def _contract_line(role: str, codes: dict[str, str]) -> str:
    """账号契约的一句话描述，如 ``教师端（借用类型默认 09 团学活动）``。"""
    label = ROLE_LABELS.get(role, role)
    default = api.default_borrow_type(role)
    if not default:
        return label
    name = codes.get(default, "")
    suffix = f" {name}" if name else ""
    return f"{label}（借用类型默认 {default}{suffix}）"


def _collect_profile(phone: str | None, name: str | None) -> None:
    """登录后采集姓名 / 手机号 / 单位 / 账号契约，存入本地档案。

    姓名/单位落**账号档案段**（`profile.save_identity`）—— 它们是账号自带的，
    也就是 plan 的全局默认；手机号/契约落通用字段。
    """
    prof = profile_mod.load()
    data: dict[str, Any] = {}
    contract_line = ""
    org_code = ""
    try:
        s = Session()
        s.load()
        org = api.my_org(s)
        if org.get("SZDWDM"):
            org_code = str(org["SZDWDM"])
            data["JYDWDM"] = org_code
        role, codes = api.borrow_contract(s)
        if api.default_borrow_type(role):
            data["borrow_role"] = role
            data["JSJYLXDM"] = api.default_borrow_type(role)
            contract_line = _contract_line(role, codes)
    except Exception:  # noqa: BLE001
        pass

    # 姓名：命令行给了 > 学校账号里那个 > 档案里旧的 > 问用户。
    # 学校账号里本来就有（应用页的 `_JW_INIT_CONFIG.username`）—— 能读就不问。
    identity = {}
    try:
        identity = api.account_identity(s)
    except Exception:  # noqa: BLE001 - 读不到就问，不该因此中断登录
        identity = {}
    name = name or identity.get("name") or profile_mod.identity(prof)["name"] or ""
    phone = phone or prof.get("JYRDH") or ""
    if sys.stdin.isatty():
        try:
            if not phone:
                phone = typer.prompt(
                    "手机号（教室借用申请的联系方式，可留空稍后填）",
                    default="",
                    show_default=False,
                )
            if not name:
                name = typer.prompt("姓名（回车用系统默认）", default="", show_default=False)
        except typer.Abort:  # 非交互环境（stdin 到 EOF）：跳过提问，保留已采集字段
            pass
    if name:
        data["JYRXM"] = name
    if phone:
        data["JYRDH"] = phone
    if name or org_code:
        # 账号档案段：只有采集这条路能写（见 profile 模块 docstring）
        profile_mod.save_identity(
            account=str(identity.get("account") or ""), name=name or "", org=org_code
        )
    if data:
        p = profile_mod.save(data)
        console.print(f"✓ 档案已保存：{p}")
        line = (
            f"  姓名={data.get('JYRXM', '')}  手机={data.get('JYRDH', '')}"
            f"  单位={data.get('JYDWDM', '')}"
        )
        if contract_line:
            line += f"  契约={contract_line}"
        console.print(line)


def _identity_decision(ident: dict[str, str], account: str) -> str:
    """账号档案段要不要动：``skip`` / ``adopt``（认下账号号，姓名不动）/ ``refresh``。

    这是「plan 前自动重采」（`_ensure_profile_identity`）与「显式改档」
    （`crb profile --name`）**不打架**的那条线：

    * 账号号一致、档案里有姓名 → ``skip`` —— 显式改档就靠这条活着
      （`--name` 写的就是账号档案段，自动重采绝不能把它抹回账号真名）；
    * 账号号变了 → ``refresh`` —— 旧档案是**上一个账号**的，本来就该重学；
    * 档案里没姓名 → ``refresh``（还没采过，或升级前的老档案）；
    * 有姓名、但双方都没记账号号（老档案，或 `crb profile --name` 是在登录之前
      改的）→ ``adopt``：只把账号号认下来、**姓名不动** —— 否则第一次 plan
      就会把手工改档静默抹掉（这就是会打架的那种情形）。
    """
    if not account:
        return "skip"
    if ident["account"] and ident["account"] != account:
        return "refresh"
    if not ident["name"]:
        return "refresh"
    if not ident["account"]:
        return "adopt"
    return "skip"


def _ensure_profile_identity(s: Session) -> dict[str, Any]:
    """`plan` 之前核对**账号档案段**：换过账号 / 没采过 → 现取一份写回去。

    姓名/单位是**账号自带**的（学校表单也是前端自动填的），它就是 plan 的
    全局默认；档案通用字段里别人留下的值顶不掉它（见 `profile` 模块 docstring）。
    读不到（风控 / 接口变了）就用档案里那份，**不猜**；显式改过档的姓名
    也不会被自动重采抹掉（见 :func:`_identity_decision`）。
    """
    prof = profile_mod.load()
    ident = profile_mod.identity(prof)
    try:
        live = api.account_identity(s)
    except Exception:  # noqa: BLE001 - 取不到就不动档案
        return prof
    account = str(live.get("account") or "")
    decision = _identity_decision(ident, account)
    if decision == "skip":
        return prof
    if decision == "adopt":
        # 姓名/单位是显式改档（或老档案）给的那份，只把账号号认下来。
        profile_mod.save_identity(account=account)
        return profile_mod.load()
    org = ident["org"]
    try:
        org = str((api.my_org(s) or {}).get("SZDWDM") or "") or org
    except Exception:  # noqa: BLE001
        pass
    name = str(live.get("name") or "") or ident["name"]
    profile_mod.save_identity(account=account, name=name, org=org)
    profile_mod.save({"JYRXM": name, "JYDWDM": org})  # 通用字段的兼容投影
    return profile_mod.load()


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
        if name is not None or org is not None:
            # 显式改档 = 改**账号档案段**（外加通用字段那份兼容投影）：
            # 这是「以某人名义借」在引擎里的正当入口，别拿它当默认值来用。
            profile_mod.save_identity(name=name or "", org=org or "")
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
    if prof.get("borrow_role"):
        console.print(f"  契约: {ROLE_LABELS.get(prof['borrow_role'], prof['borrow_role'])}")


@app.command()
def doctor(json_out: bool = typer.Option(False, "--json")) -> None:
    """自检：登录态是否有效、能否取到当前学期与系统参数。"""
    s = _session()
    term = api.current_term(s)
    params = api.system_params(s)
    org = api.my_org(s)
    role, codes = api.borrow_contract(s)
    identity = api.account_identity(s)
    info = {
        "ok": bool(term),
        "term": term,
        "JSJYSFKT": params.get("JSJYSFKT"),
        "JYSJFW": params.get("JYSJFW"),
        "org": org.get("DWDM") or org.get("SZDWDM"),
        # 账号本人的姓名/用户号 —— 填申请时要用（学校表单也是拿它们自动填的）
        "name": identity.get("name", ""),
        "account": identity.get("account", ""),
        "role": role,
        "borrow_type_default": api.default_borrow_type(role),
        "borrow_types": codes,
    }
    if json_out:
        _dump(info)
        return
    console.print("[green]✓ 登录态可用[/green]")
    if info.get("name"):
        console.print(
            f"  账号：{info['name']}" + (f"（{info['account']}）" if info.get("account") else "")
        )
    console.print(f"  当前学期：{term or '[red]获取失败[/red]'}")
    console.print(f"  借用开关 JSJYSFKT：{params.get('JSJYSFKT', '?')}")
    console.print(f"  可借日期 JYSJFW：{params.get('JYSJFW', '?')}")
    if org:
        console.print(f"  所在单位代码：{org.get('DWDM') or org.get('SZDWDM', '?')}")
    console.print(f"  账号契约：{_contract_line(role, codes)}")
    if codes:
        console.print(f"  可用借用类型：{api.borrow_type_hint(codes)}")
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
    campus_id: str | None = typer.Option(
        None, "--campus", "-c", help="校区代码（不填=四个校区一起列，见 `crb campus`）"
    ),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """列出教学楼（字典）：不填校区就四个校区一起列。"""
    rows = api.buildings(_session(), campus_id)
    if json_out:
        _dump([r.model_dump(by_alias=True) for r in rows])
        return
    for r in rows:
        campus = CAMPUSES.get(str(r.campus_id), str(r.campus_id or ""))
        console.print(f"  {r.id}  {r.name}  [dim]({campus})[/dim]")


# ---------------------------------------------------------------- 空闲教室
@app.command()
def free(
    campus_id: str = typer.Option(..., "--campus", "-c", help="校区代码"),
    day: str = typer.Option(
        ..., "--date", "-d", help="日期 YYYY-MM-DD；要问好几天就逗号分隔（一天一发请求）"
    ),
    period: str = typer.Option(..., "--period", "-p", help="节次区间，如 1-2"),
    building_id: str | None = typer.Option(None, "--building", "-b", help="教学楼代码（可选）"),
    room_type: str | None = typer.Option(None, "--room-type", "-t", help="教室类型代码（可选）"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """查询某天（或某几天）、某节次区间的空闲教室（服务端按节次过滤）。

    区间语义是「**整个区间都空闲**」。给多个日期时**一天一发请求**、互不影响 ——
    用来回答「这几天哪天有空的教室」，省得让调用方自己循环。
    """
    # 参数先验完再碰登录态：参数错就是参数错，别让人以为是自己没登录。
    start, end = _parse_period(period)
    days = [d.strip() for d in day.split(",") if d.strip()]
    if not days:
        raise typer.BadParameter("--date 至少要给一个日期")
    if len(days) > MAX_QUERY_DATES:
        raise typer.BadParameter(f"--date 一次最多 {MAX_QUERY_DATES} 个日期（收到 {len(days)} 个）")
    for d in days:
        if not is_iso_date(d):
            raise typer.BadParameter(f"--date 必须是 YYYY-MM-DD，收到 {d!r}")

    s = _session()

    results: list[tuple[str, list[FreeRoomSlot]]] = []
    for d in days:
        results.append(
            (
                d,
                api.free_rooms(
                    s,
                    campus_id=campus_id,
                    day=d,
                    start_period=start,
                    end_period=end,
                    building_id=building_id,
                    room_type=room_type,
                ),
            )
        )

    if json_out:
        if len(results) == 1:
            _dump([r.model_dump(by_alias=True) for r in results[0][1]])
        else:
            _dump(
                [
                    {
                        "date": d,
                        "weekday": roomview.weekday_label(d),
                        "count": len(rooms),
                        "rooms": [r.model_dump(by_alias=True) for r in rooms],
                    }
                    for d, rooms in results
                ]
            )
        return

    where = CAMPUSES.get(campus_id, campus_id)
    if len(results) == 1:
        d, rooms = results[0]
        table = Table(title=f"{where} {d} 第{period}节 空闲教室")
        _free_table(table, [(d, rooms)])
        console.print(table)
        console.print(f"共 {len(rooms)} 间")
        return
    table = Table(title=f"{where} 第{period}节 空闲教室（{len(results)} 天）")
    _free_table(table, results)
    console.print(table)
    for d, rooms in results:
        console.print(f"  {d} {roomview.weekday_label(d)}：{len(rooms)} 间")


def _free_table(table: Table, results: list[tuple[str, list[FreeRoomSlot]]]) -> None:
    multi = len(results) > 1
    if multi:
        table.add_column("日期", style="cyan")
    for col in ("教室", "教学楼", "类型", "容量", "空闲时间"):
        table.add_column(col, justify="right" if col == "容量" else None)
    for d, rooms in results:
        for r in rooms:
            row = [d] if multi else []
            row += [
                r.room_name,
                r.building_name or "",
                r.room_type_name or "",
                str(r.seat_class or ""),
                r.time_label or r.period_label or "",
            ]
            table.add_row(*row)


# ---------------------------------------------------------------- 教室（索引 / 单间）
@app.command()
def rooms(
    campus_id: str = typer.Option(..., "--campus", "-c", help="校区代码"),
    building_id: str | None = typer.Option(None, "--building", "-b", help="教学楼代码（可选）"),
    room_type: str | None = typer.Option(None, "--room-type", "-t", help="教室类型代码（可选）"),
    match: str | None = typer.Option(
        None, "--match", "-m", help="按名字筛：给「501」「仙一」这种关键词即可"
    ),
    day: str | None = typer.Option(None, "--date", "-d", help="按哪天取清单，默认今天"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """列出某校区的教室清单（索引）：教室名 / 教学楼 / 容量 / 类型。

    这是「先索引、再筛选」里的索引：用户嘴里的「501」「新教」先在这里对到真实教室名，
    再用 `crb room` 查它某天的空闲情况。
    """
    s = _session()
    rows = api.all_rooms(
        s, campus_id=campus_id, building_id=building_id, room_type=room_type, day=day
    )
    infos = [RoomInfo.of(r) for r in rows]
    if match:
        wanted = room_key_loose(match)
        infos = [
            i for i in infos if wanted in room_key_loose(i.name) or room_key_loose(i.name) in wanted
        ]
    if json_out:
        _dump(
            {
                "campus": campus_id,
                "campus_name": CAMPUSES.get(campus_id, campus_id),
                "total": len(infos),
                "rooms": [i.model_dump() for i in infos],
            }
        )
        return

    title = f"{CAMPUSES.get(campus_id, campus_id)} 教室清单（{len(infos)} 间）"
    if match:
        title += f"｜匹配「{match}」"
    table = Table(title=title)
    for col in ("教室", "教学楼", "类型", "容量"):
        table.add_column(col)
    for i in infos[:60]:
        table.add_row(i.name, i.building, i.room_type, str(i.capacity or ""))
    console.print(table)
    if len(infos) > 60:
        console.print("[dim]（只显示前 60 间；用 --match 缩小范围）[/dim]")
    elif not match:
        counter: dict[str, int] = {}
        for i in infos:
            counter[i.building or "（未知）"] = counter.get(i.building or "（未知）", 0) + 1
        summary = " / ".join(f"{k} {v}" for k, v in counter.items())
        console.print(f"[dim]按教学楼：{summary}[/dim]")


@app.command()
def room(
    room_name: str = typer.Option(
        ..., "--room", "-r", help="教室名；给关键词也行（501 / 仙一501）"
    ),
    campus_id: str = typer.Option(..., "--campus", "-c", help="校区代码"),
    day: str = typer.Option(..., "--date", "-d", help="日期 YYYY-MM-DD"),
    building_id: str | None = typer.Option(
        None, "--building", "-b", help="教学楼代码（可选；给了只会在这栋楼里找）"
    ),
    period: str = typer.Option("1-12", "--period", "-p", help="节次区间，如 7-12；默认全天"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """查**某一间教室**在某天各节的空闲情况（学校权威口径）。

    认不出或多间候选时**不猜**：把候选列出来（`status=ambiguous`），交给用户确认。
    """
    s = _session()
    start, end = _parse_period(period)
    view = roomview.room_day(
        s,
        campus_id=campus_id,
        day=day,
        room=room_name,
        building_id=building_id,
        start_period=start,
        end_period=end,
    )
    if json_out:
        _dump(view.model_dump())
        return

    if view.status != "ok" or view.room is None:
        reason = "没找到这间教室" if view.status == "not_found" else "这个名字对上了不止一间"
        err_console.print(f"[yellow]{reason}：{room_name}[/yellow]")
        for c in view.candidates:
            console.print(f"  {c.name}  [dim]{c.building}（{c.campus_name}）[/dim]")
        if not view.candidates:
            console.print("[dim]用 `crb rooms -c <校区> --match <关键词>` 看看有哪些教室。[/dim]")
        return

    info = view.room
    console.print(
        f"[bold]{info.name}[/bold]  [dim]{info.building}（{info.campus_name}）"
        f" 容量 {info.capacity or '?'} {info.room_type}[/dim]"
    )
    console.print(f"{view.date} {view.weekday}")
    table = Table()
    for col in ("节次", "时间", "状态"):
        table.add_column(col)
    for slot in view.periods:
        mark = "[green]空闲[/green]" if slot.free else "[red]占用[/red]"
        table.add_row(str(slot.period), slot.time, mark)
    console.print(table)
    console.print(f"空闲：{_spans_text(view.free_spans) or '（无）'}")
    console.print(f"占用：{_spans_text(view.occupied_spans) or '（无）'}")


def _spans_text(spans: list[PeriodSpan]) -> str:
    return "、".join(f"{s.label} 节（{s.time}）" for s in spans)


@app.command()
def day(
    campus_id: str = typer.Option(..., "--campus", "-c", help="校区代码"),
    day_arg: str = typer.Option(..., "--date", "-d", help="日期 YYYY-MM-DD"),
    building_id: str | None = typer.Option(
        None, "--building", "-b", help="教学楼代码；**强烈建议给**（不给就整个校区）"
    ),
    match: str | None = typer.Option(None, "--match", "-m", help="按教室名筛，如「东1」「501」"),
    room_type: str | None = typer.Option(None, "--room-type", "-t", help="教室类型代码（可选）"),
    period: str = typer.Option("1-12", "--period", "-p", help="节次区间，如 7-12；默认全天"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """某天、**一栋楼**（或整个校区）所有教室的空档 —— 一次问全，别逐间问。

    请求数只跟节次数有关（默认 12 发），跟教室数无关：42 间教室逐间问要 42×13 发，
    这里 12 发就够。问「这栋楼这层有哪些空档」用它，不要一间一间调 `crb room`。
    """
    s = _session()
    start, end = _parse_period(period)
    view = roomview.day_view(
        s,
        campus_id=campus_id,
        day=day_arg,
        building_id=building_id,
        room_type=room_type,
        match=match,
        start_period=start,
        end_period=end,
    )
    if json_out:
        _dump(view.model_dump())
        return

    where = CAMPUSES.get(campus_id, campus_id)
    if view.building:
        where += f" {view.building}"
    title = f"{where} {view.date} {view.weekday} 各教室空档（{view.total} 间）"
    table = Table(title=title)
    for col in ("教室", "容量", "类型", "空闲", "占用"):
        table.add_column(col)
    for row in view.rooms[:60]:
        table.add_row(
            row.room.name,
            str(row.room.capacity or ""),
            row.room.room_type,
            "、".join(s.label for s in row.free_spans) or "—",
            "、".join(s.label for s in row.occupied_spans) or "—",
        )
    console.print(table)
    if view.total > 60:
        console.print("[dim]（只显示前 60 间；用 --building / --match 缩小范围）[/dim]")


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
        False,
        "--allow-overlap",
        help="允许与已有申请重复（四项：日期/校区/节次/教室，默认拦截）",
    ),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """批量规划：查空闲教室 → 分配 → 冲突检测 →（可选）批量存草稿。"""
    s = _session()
    applicant, activities = planner.load_plan(file)
    if not activities:
        err_console.print("[red]活动列表为空[/red]")
        raise typer.Exit(2)
    # 姓名/单位：**账号档案段（账号本人）是全局默认**；plan 文件里的
    # defaults 是单次覆盖（apply_profile 只补缺，所以覆盖仍然生效）。
    planner.apply_profile(applicant, profile_mod.defaults(_ensure_profile_identity(s)))

    term = api.current_term(s)
    role, codes = api.borrow_contract(s)
    if not json_out:
        console.print(f"[dim]账号契约：{_contract_line(role, codes)}[/dim]")
    existing = planner.existing_usage(s, term)
    if existing and not json_out:
        console.print(f"[dim]已有申请 {len(existing)} 条，已纳入防重检测[/dim]")
    assignments = planner.build_plan(
        s,
        activities,
        applicant,
        existing=existing,
        allow_overlap=allow_overlap,
    )

    if not json_out:
        table = Table(title=f"教室借用方案（{len(assignments)} 条）")
        for col in ("活动", "日期", "节次", "人数", "教室", "容量", "状态"):
            table.add_column(col)
        for a in assignments:
            room = "、".join(r.room_name for r in a.rooms)
            cap = sum((r.seat_class or r.seat_exam or 0) for r in a.rooms)
            mark = {
                "ok": "[green]OK[/green]",
                "no_room": "[red]无教室[/red]",
                "too_small": "[yellow]容量不足[/yellow]",
                "duplicate": "[yellow]重复[/yellow]",
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

    if not (save or submit):
        if json_out:
            _dump([a.model_dump(mode="json") for a in assignments])
        else:
            console.print("[dim]（仅方案，未写入；加 --save 存草稿 / --submit 正式提交）[/dim]")
        return

    results = planner.save_plan(
        s,
        assignments,
        applicant,
        room_in_purpose=room_in_purpose,
        submit=submit,
        contract=(role, codes),
    )
    if json_out:
        _dump(
            {
                "contract": {
                    "role": role,
                    "borrow_type_default": api.default_borrow_type(role),
                    "borrow_types": codes,
                },
                "assignments": [a.model_dump(mode="json") for a in assignments],
                "results": results,
            }
        )
    else:
        for r in results:
            mark = "[green]✓[/green]" if r["ok"] else "[red]✗[/red]"
            console.print(f"{mark} {r['title']} -> {r['msg']}")
    if any(not r["ok"] for r in results):
        raise typer.Exit(1)


# ---------------------------------------------------------------- 借用申请
@borrow_app.command("list")
def borrow_list(
    term: str | None = typer.Option(None, "--term", help="学年学期，默认自动获取"),
    from_date: str | None = typer.Option(
        None, "--from", help="起始日期 YYYY-MM-DD（按提交时间；不填 = 不限）"
    ),
    to_date: str | None = typer.Option(None, "--to", help="截止日期 YYYY-MM-DD（不填 = 不限）"),
    limit: int = typer.Option(100, "--limit", help="最多返回几条（从最新往回取）"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """查看我的教室借用申请（默认最新 100 条；可给 --from/--to 区间）。"""
    s = _session()
    term = term or api.current_term(s)
    rows, meta = api.list_borrows_window(
        s, term, since=from_date or "", until=to_date or "", limit=limit
    )
    if json_out:
        _dump(
            {
                "total": meta.get("total"),
                "count": len(rows),
                "pages": meta.get("pages"),
                "truncated": meta.get("truncated"),
                "rows": [
                    {k: v for k, v in r.model_dump().items() if v not in (None, "")} for r in rows
                ],
            }
        )
        return
    if not rows:
        console.print("（这个范围里没有申请记录）")
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
    if meta.get("truncated"):
        console.print(f"[dim]（只取了最新 {limit} 条；更早的用 --from/--to 收窄）[/dim]")


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
    submit: bool = typer.Option(False, "--submit", help="⚠️ 正式提交（默认关闭，仅保存草稿）"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """批量保存教室借用申请草稿（默认不提交）；借用类型按当前账号字典校验。"""
    s = _session()
    reqs = _load_requests(file, data)
    role, codes = api.borrow_contract(s)
    results: list[dict[str, Any]] = []
    for i, req in enumerate(reqs, 1):
        problem = api.check_borrow_type(req.JSJYLXDM, role, codes)
        if problem:
            results.append({"index": i, "ok": False, "code": None, "msg": problem})
            if not json_out:
                console.print(f"[red]✗[/red] #{i} {req.JYYTMS[:24]} -> {problem}")
            continue
        res = api.save_borrow(s, req, submit=submit)
        results.append({"index": i, "ok": res.ok, "code": res.code, "msg": res.msg})
        if not json_out:
            mark = "[green]✓[/green]" if res.ok else "[red]✗[/red]"
            console.print(f"{mark} #{i} {req.JYYTMS[:24]} -> {res.msg or res.code}")
    if json_out:
        _dump(results)
    elif not submit:
        console.print("[dim]（以上均为草稿，未正式提交）[/dim]")
    if any(not r["ok"] for r in results):
        raise typer.Exit(1)


@borrow_app.command("delete")
def borrow_delete(
    sqbh: str = typer.Option(..., "--sqbh", help="申请编号（列表里的 SQBH）"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """删除一条申请/草稿。"""
    _emit_result(api.delete_borrow(_session(), sqbh), json_out)


@borrow_app.command("withdraw")
def borrow_withdraw(
    sqbh: str = typer.Option(..., "--sqbh", help="申请编号 SQBH"),
    cqdqjy: str | None = typer.Option(None, "--cqdqjy", help="长期(1)/短期(2)，默认自动识别"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """撤回一条已提交的申请（撤回后可编辑再提交）。"""
    s = _session()
    rec = api.find_borrow(s, api.current_term(s), sqbh)
    if rec is None:
        err_console.print(f"[red]未找到申请：{sqbh}[/red]")
        raise typer.Exit(2)
    cq = cqdqjy or str(rec.get("CQDQJY") or "2")
    _emit_result(api.withdraw_borrow(s, sqbh, cqdqjy=cq), json_out)


@borrow_app.command("submit")
def borrow_submit(
    sqbh: str = typer.Option(..., "--sqbh", help="申请编号 SQBH"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """把草稿/已撤回的申请正式提交（TYPE=TJ）。"""
    s = _session()
    rec = api.find_borrow(s, api.current_term(s), sqbh)
    if rec is None:
        err_console.print(f"[red]未找到申请：{sqbh}[/red]")
        raise typer.Exit(2)
    _emit_result(api.update_borrow(s, rec, submit=True), json_out)


@borrow_app.command("edit")
def borrow_edit(
    sqbh: str = typer.Option(..., "--sqbh", help="申请编号 SQBH"),
    data: str = typer.Option(
        ..., "--data", help='要修改的字段 JSON，如 {"ZRS":"35","JYYTMS":"..."}'
    ),
    draft: bool = typer.Option(False, "--draft", help="只保存草稿，不提交"),
    json_out: bool = typer.Option(False, "--json"),
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
    _emit_result(api.update_borrow(s, rec, submit=not draft, **changes), json_out)


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
