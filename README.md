# CRB — 南京大学教室借用工具

> **CRB = ClassRoom Booking**（教室借用）。
> 一个 **CLI + Skill**：复用一次性登录态，直连南京大学办事大厅后端接口，完成
> **空闲教室查询 / 批量生成教室借用申请草稿 / 申请查询 · 提交 · 撤回 · 编辑 · 删除**。

![version](https://img.shields.io/badge/version-0.0.0-orange)
![python](https://img.shields.io/badge/python-3.12%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![code style](https://img.shields.io/badge/code%20style-ruff-000000)
[![CI](https://github.com/Aalas1111/NJU_Classroom_Booking/actions/workflows/ci.yml/badge.svg)](https://github.com/Aalas1111/NJU_Classroom_Booking/actions/workflows/ci.yml)

---

## ⚠️ 先读这段

- **默认只保存草稿**（`TYPE=save`），**不会自动正式提交**；正式提交必须显式使用
  `--submit` / `crb borrow submit`。
- 登录态 `~/.crb/auth.json` 与档案 `~/.crb/profile.json` 是**敏感文件**：
  不要提交到 git、不要分享、不要让 AI 读取其内容。
- 本工具**不绕过任何权限**：能申请到什么，取决于登录账号本身的权限。
  请遵守学校信息系统使用规范，批量操作前先小规模验证，并及时清理测试数据。

---

## 目录

- [特性](#特性)
- [环境要求](#环境要求)
- [安装](#安装)
- [快速开始](#快速开始)
- [安装 AI Skill](#安装-ai-skill)
- [命令速查](#命令速查)
- [输出格式](#输出格式)
- [配置](#配置)
- [字典与节次](#字典与节次)
- [批量规划 `plan.json`](#批量规划-planjson)
- [开发](#开发)
- [常见问题](#常见问题)
- [免责声明](#免责声明)
- [License](#license)

---

## 特性

| 能力 | 说明 |
|---|---|
| 🔑 登录态复用 | `crb login` 打开有头浏览器完成一次统一身份认证，之后所有命令免登录 |
| 🩺 自检 | `crb doctor` 检查登录态、当前学期、借用开关、所在单位 |
| 🏫 空闲教室 | `crb free` 走权威接口 `kxjscx/cxkxjs.do`，节次过滤由服务端完成 |
| 🔍 教室视角 | `crb rooms` 教室索引（名称/容量/类型）+ `crb room` 某间教室某天的逐节空闲/占用；名字对不上时给候选，**不猜** |
| 🧠 批量规划 | `crb plan` 查空闲 → 容量过滤 → 批次内 + 跨批次冲突检测 → 自动分配教室 |
| 📝 申请管理 | 列表 / 存草稿 / 正式提交 / 撤回 / 编辑 / 删除 |
| 🤖 AI 友好 | 所有命令支持 `--json`；内置 `SKILL.md` 随包分发，`crb skill install` 一键装到 harness |
| 🧰 工程化 | uv 管理依赖与构建，ruff 静态检查，pytest 单元测试，GitHub Actions CI |

---

## 环境要求

| 依赖 | 版本 | 说明 |
|---|---|---|
| Python | ≥ 3.12 | 由 `uv` 自动管理，无需手动安装 |
| [uv](https://docs.astral.sh/uv/) | 最新 | Python 包 / 虚拟环境 / 项目管理 |
| 浏览器 | Edge 或 Chrome 任一 | 仅 `crb login` 需要，系统自带即可 |

已在 **Windows + Git Bash** 下验证；Linux / macOS 同理。

### 安装 uv

```bash
# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## 安装

> 当前版本**未发布到 PyPI**。发行物见 [Releases](https://github.com/Aalas1111/NJU_Classroom_Booking/releases/latest)
> （`crb-0.0.0-py3-none-any.whl` / `crb-0.0.0.tar.gz`），也可从源码安装或自行 `uv build`。

### 方式一：从源码安装为全局命令（推荐）

```bash
git clone https://github.com/Aalas1111/NJU_Classroom_Booking.git
cd NJU_Classroom_Booking
uv tool install ".[login]"     # 安装 `crb` 命令 + 登录所需的 Playwright
crb --version                  # crb 0.0.0
```

### 方式二：pipx

```bash
pipx install ".[login]"
```

### 方式三：直接用 wheel

```bash
# 从 https://github.com/Aalas1111/NJU_Classroom_Booking/releases/latest 下载后
uv tool install "dist/crb-0.0.0-py3-none-any.whl"
# 登录功能需要额外装 Playwright：
uv tool install "dist/crb-0.0.0-py3-none-any.whl" --with playwright
```

### 方式四：只在仓库内运行（开发用，不改全局环境）

```bash
uv sync --extra login          # 含 Playwright；只做查询可省 --extra login
uv run crb --help
```

> 下文示例统一写 `crb ...`；若用方式四，请替换为 `uv run crb ...`。

### 浏览器（仅登录需要，通常可跳过）

`crb login` 会**自动按顺序尝试**：Playwright 自带的 Chromium → 系统 Edge → 系统 Chrome。
只要电脑上装了 Edge 或 Chrome（Windows 一般自带 Edge），就**无需下载**。

如果三者都没有：

```bash
playwright install chromium            # 方式一 / 二 / 三
uv run playwright install chromium     # 方式四
```

也可手动指定：`crb login --browser msedge`（可选 `auto` / `chromium` / `msedge` / `chrome`）。

---

## 快速开始

```bash
# 1. 首次登录（弹出浏览器，扫码或账号密码完成统一身份认证）
crb login

# 2. 自检：登录态 / 当前学期 / 借用开关 / 单位
crb doctor --json

# 3. 查空闲教室（校区 3 = 仙林，第 1-2 节）
crb free --campus 3 --date 2026-09-10 --period 1-2 --json

# 3b. 反过来问某一间教室：先列教室索引，再看它这天各节的空闲/占用
crb rooms --campus 3 --match 501 --json
crb room  --campus 3 --date 2026-09-30 --room 仙Ⅰ-501 --json

# 4. 批量规划：先出方案（不写系统）
crb plan --file examples/plan.example.json

# 5. 确认后存草稿（默认就是草稿；正式提交才加 --submit）
crb plan --file examples/plan.example.json --save
```

登录态失效时命令会提示重新 `crb login`。

---

## 安装 AI Skill

内置的 `SKILL.md` 随 wheel 一起分发，可直接安装到 AI harness 的 skills 目录：

```bash
crb skill path                                  # 打印内置 SKILL.md 的路径
crb skill show                                  # 原样打印内容
crb skill install --dir .pi/skills              # → .pi/skills/crb/SKILL.md
crb skill install --dir ~/.claude/skills        # Claude Code
crb skill install --dir .cursor/skills --force  # 已存在时覆盖
```

Skill 里写明了触发词、完整范例与**硬性规则**（默认只存草稿、不输出敏感文件等）。

---

## 命令速查

```bash
crb login                                   # 首次登录（可选 --browser / --phone / --name）
crb doctor        --json                    # 自检
crb profile       --phone 138xxxxxxxx --name 李赫 --org 400760   # 借用人档案
crb campus        --json                    # 校区字典
crb buildings     --json                    # 教学楼字典（不填 --campus 就四个校区一起列）
crb free          --campus 3 --date 2026-09-10 --period 1-2 --json   # 空闲教室（区间 = 整段都空；日期可逗号分隔）
crb rooms         --campus 3 --json         # 教室索引（--match 501 按关键词筛）
crb room          --campus 3 --date 2026-09-30 --room 仙Ⅰ-501 --json  # 某教室这天的逐节空闲/占用
crb day           --campus 4 --building S06 --date 2026-09-30 --json   # 整栋楼所有教室的空档（一次问全）
crb plan          --file examples/plan.example.json                  # 批量规划（只出方案）
crb plan          --file examples/plan.example.json --save           # 批量规划 + 存草稿
crb plan          --file examples/plan.example.json --submit         # ⚠️ 批量正式提交
crb borrow list   --json                    # 我的申请
crb borrow draft  --file reqs.json --json   # 按申请数组存草稿
crb borrow submit --sqbh <SQBH>             # 草稿 / 已撤回 → 正式提交
crb borrow withdraw --sqbh <SQBH>           # 撤回已提交申请
crb borrow edit   --sqbh <SQBH> --data '{"ZRS":"35"}'   # 修改并重新提交
crb borrow delete --sqbh <SQBH>             # 删除申请 / 草稿
crb skill         show | path | install     # 内置 AI Skill
crb --version                               # 版本号
```

所有命令都支持 `--json`，便于脚本和 AI 消费。不确定参数时加 `--help`，
例如 `crb borrow edit --help`。

### 申请状态（`SHZT`）

| `SHZT` | 含义 | 可做的操作 |
|---|---|---|
| `00` | 草稿 | 提交 / 编辑 |
| `65` 等 | 待审核（如待学生社团管理部审核） | 查看 / 撤回 |
| `1` | 已撤回 | 删除 / 提交 / 编辑 |
| `99` | 已通过 | 查看 / 打印 |

---

## 输出格式

- 默认输出人类可读文本（rich 表格 / 彩色提示）。
- 加 `--json` 输出结构化 JSON：
  - 读操作：数组或对象，字段名与学校接口一致（如 `JASMC`、`SKZWS`、`SQBH`）。
  - 写操作：统一为 `{"ok": bool, "code": int, "msg": str}`。
- 退出码：`0` 成功；`1` 部分失败 / 运行错误；`2` 未登录或参数错误；`3` 被风控拦截。

---

## 配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `CRB_AUTH_FILE` | `~/.crb/auth.json` | 登录态保存位置 |
| `CRB_PROFILE_FILE` | `~/.crb/profile.json` | 借用人档案保存位置（**账号档案段 + 通用字段**两层，见上） |

```bash
export CRB_AUTH_FILE=/path/to/auth.json
```

> 两个文件都会以 `0600` 权限写入（Windows 上尽力而为），且已在 `.gitignore` 中屏蔽。

---

## 字典与节次

### 校区

| 代码 | 校区 |
|---|---|
| `1` | 鼓楼 |
| `2` | 浦口 |
| `3` | 仙林 |
| `4` | 苏州 |

### 借用类型 `JSJYLXDM`

同一个字段，**学生端与教师端是两套字典**（服务端按登录账号返回，`crb` 自动识别并走对应契约；
也可以省略，缺省时学生端补 `02`、教师端补 `09`）。填了不属于当前账号的代码会直接报错并列出可用值。

学生端（表单标签是「指导教师所在单位」）：

| 代码 | 类型 |
|---|---|
| `01` | 辅导员 |
| `02` | 学生社团管理部 |
| `03` | 就业指导中心 |
| `04` | 国际合作与交流处 |
| `05` | 学生工作处 |
| `06` | 校团委 |
| `13` | 待悦读课程管理 |

教师端（表单标签是「借用类型」；教师端没有「指导教师所在单位」字段）：

| 代码 | 类型 |
|---|---|
| `07` | 教师教学、补课 |
| `09` | 团学活动 |
| `21` | 长期借用 |
| `39` | 考试 |
| `40` | 讲座 |

### 节次时间（全校统一）

| 节 | 时间 | 节 | 时间 |
|---|---|---|---|
| 1 | 08:00-08:50 | 7 | 16:10-17:00 |
| 2 | 09:00-09:50 | 8 | 17:10-18:00 |
| 3 | 10:10-11:00 | 9 | 18:30-19:20 |
| 4 | 11:10-12:00 | 10 | 19:30-20:20 |
| 5 | 14:00-14:50 | 11 | 20:30-21:20 |
| 6 | 15:00-15:50 | 12 | 21:30-22:20 |

「下午 4 点后」→ 第 7 节起；「晚上 7 点」→ 第 9 节；以此类推。

---

## 批量规划 `plan.json`

```json
{
  "defaults": { "campus": "3", "JSJYLXDM": "02" },
  "activities": [
    { "title": "学生社团例会", "date": "2026-09-10", "period": "1-2", "people": 30 },
    { "title": "小型讨论", "date": "2026-09-10", "period": "5-6", "people": 10,
      "preferred_room": "仙Ⅰ-102" }
  ]
}
```

- 也可直接写活动数组（省略 `defaults`）；单条活动可覆盖
  `campus / building / room_type / JYDWDM / JYRXM / JYRDH / JSJYLXDM`。
- `JSJYLXDM` 可省略：按当前账号契约补默认值（学生端 `02` / 教师端 `09`）。
- 选教室规则：容量刚好够用优先；防重口径是「日期 + 校区 + 节次 + 教室」四项（与教师侧脚本一致），
  时段重叠但教室不同不算重复；本批次内与**自己已有申请**都会做冲突检测。
- `preferred_room` 只写进用途描述（「意向：xxx」）——**不能指定具体教室**。
- 完整算法与限制见 [docs/批量规划设计.md](docs/批量规划设计.md)。

---

## 开发

```bash
uv sync --extra login       # 准备开发环境
uv run ruff check .         # 静态检查
uv run ruff format .        # 格式化
uv run pytest               # 单元测试（不依赖网络 / 登录态）
uv run python scripts/sync_skill.py   # 同步内置 SKILL.md 到 .pi/skills
uv build                    # 构建 sdist + wheel 到 dist/
```

- 唯一事实来源：skill 内容在 `src/crb/data/SKILL.md`，仓库内 `.pi/skills/crb/SKILL.md`
  是同步副本（测试会校验一致性，不一致跑 `scripts/sync_skill.py` 修复）。
- 贡献流程见 [CONTRIBUTING.md](CONTRIBUTING.md)，变更记录见 [CHANGELOG.md](CHANGELOG.md)。

### 项目结构

```
NJU_Classroom_Booking/
├── src/crb/
│   ├── cli.py        # 命令行入口（typer）
│   ├── api.py        # 学校后端接口封装
│   ├── session.py    # 登录态 + httpx 会话
│   ├── auth.py       # Playwright 有头登录
│   ├── planner.py    # 批量规划算法
│   ├── models.py     # 数据结构
│   ├── skill.py      # 内置 skill 读取 / 安装
│   ├── data/SKILL.md # 随包分发的 AI Skill（事实来源）
│   └── config.py     # 接口地址 / 字典常量
├── tests/            # 单元测试
├── scripts/          # 开发脚本（sync_skill）
├── examples/         # plan.json 示例
├── docs/             # 设计与接口探测记录
└── pyproject.toml
```

### 发布流程

1. 更新 `pyproject.toml` / `src/crb/__init__.py` 的版本号与 `CHANGELOG.md`。
2. `uv run ruff check . && uv run pytest`。
3. `uv build`，确认 `dist/` 下 sdist 与 wheel 内容（wheel 应包含 `crb/data/SKILL.md`）。
4. `git commit -m "chore(release): vX.Y.Z" && git tag -a vX.Y.Z -m "vX.Y.Z"`。
5. 用 `CHANGELOG.md` 对应小节作为 GitHub Release 说明，上传 `dist/` 产物。

---

## 常见问题

<details>
<summary>登录后命令仍提示未登录 / 登录态失效？</summary>

统一身份认证的会话有效期由学校策略决定。重新执行 `crb login` 即可；
也可用 `CRB_AUTH_FILE` 指定其它位置。
</details>

<details>
<summary>提示无法启动浏览器？</summary>

`crb login` 会依次尝试 Chromium → Edge → Chrome。都失败时安装系统 Edge/Chrome，
或执行 `playwright install chromium`；也可用 `--browser` 显式指定。
</details>

<details>
<summary>为什么 `plan` 选的教室和我想要的不一样？</summary>

学生端**不能指定教室**，学校按申请统一分配（教师端同样只写意向，正式教室由本科生院审核后分配，
记录里的 `JASMC`）。`preferred_room` 只会写进用途描述，
不保证借到。
</details>

<details>
<summary>教师账号能用吗？借用类型填什么？</summary>

能。`crb` 按登录账号的 `cxjsjylx.do` 字典自动识别学生端 / 教师端契约：教师端默认
`JSJYLXDM=09`（团学活动），也可显式用 `07` 教师教学、补课 / `21` 长期借用 / `39` 考试 / `40` 讲座。
把学生端的 `02` 填到教师端会被拦下并列出可用值。`crb doctor` 会显示当前账号契约。
用 `CRB_AUTH_FILE` / `CRB_PROFILE_FILE` 可以让教师身份与学生身份各用独立登录态和档案。
</details>

<details>
<summary>申请里的借用人姓名是谁？能以别人名义借吗？</summary>

默认是**账号本人**（学校表单也是这么自动填的）：`crb login` / `crb plan` 会把账号自带的
姓名与单位采集进档案的**账号档案段**（`account` / `account_name` / `account_org`），
它就是 plan 的全局默认；通用写路径（`profile.save()`）改不动它，所以下游程序
「顺手把某人写进 `JYRXM`」再也没法把账号本人顶掉。

要以别人名义借，走**单次覆盖**：plan 文件里写 `{"defaults": {"JYRXM": "某某"}}`
（`apply_profile` 只补缺，所以给了就用给的），或显式改档 `crb profile --name 某某`
（写的就是账号档案段本身）。`crb borrow edit --data '{"JYRXM":"某某"}'` 也能改已有申请。
</details>

<details>
<summary>能查出全校教室占用吗？</summary>

不能。工具只能拿到「空闲教室」接口的结果，以及**自己账号**已有的申请；
无法做跨用户、全校范围的冲突检测。
</details>

<details>
<summary>提交后会怎样？</summary>

提交后需联系指导老师初审：使用日期前至少 **1 个工作日**；周末教室需**周五 16:00 前**
完成初审。
</details>

---

## 免责声明

本项目为个人/社团自用的效率工具，**非南京大学官方项目**，与学校无隶属或授权关系。
使用前请确认符合学校信息系统使用规范；因使用本工具产生的一切后果由使用者自行承担。

## 参考文档

- [docs/思维过程1.md](docs/思维过程1.md) —— 项目定位与核心困境
- [docs/批量规划设计.md](docs/批量规划设计.md) —— `crb plan` 算法与限制
- [docs/reference/nju-classroom-agent-findings.md](docs/reference/nju-classroom-agent-findings.md) —— 接口探测完整记录
- [docs/reference/方案与老师反馈.md](docs/reference/方案与老师反馈.md) —— 给老师的方案（含批注）

## License

[MIT](LICENSE) © 2026 CRB Contributors
