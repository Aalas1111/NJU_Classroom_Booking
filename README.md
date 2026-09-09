# CRB — 南京大学教室借用工具

**CRB = ClassRoom Booking**（教室借用）。

一个 CLI + Skill 工具：复用一次性登录态，直连南京大学办事大厅后端接口，完成
**空闲教室查询 / 批量生成教室借用申请草稿 / 查询与删除申请**。

> ⚠️ 默认只保存草稿（`TYPE=save`），**不会自动正式提交**。正式提交需用户显式授权。
> ⚠️ 登录态（`~/.crb/auth.json`）是敏感文件，请勿提交到 git 或分享给他人。

---

## 环境要求

| 依赖 | 版本 | 说明 |
|---|---|---|
| Python | ≥ 3.12 | 由 `uv` 自动管理，无需手动安装 |
| [uv](https://docs.astral.sh/uv/) | 最新 | Python 包 / 虚拟环境 / 项目管理 |
| Playwright Chromium | — | 仅登录时需要 |

Windows + Git Bash 下已验证。Linux / macOS 同理。

### 1. 安装 uv

```bash
# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. 安装项目依赖

```bash
uv sync --extra login          # 含 Playwright（登录用）
# 或只装核心功能、不做登录：
uv sync
```

`uv sync` 会自动创建 `.venv/` 并按 `pyproject.toml` 安装依赖。

### 3. 浏览器（仅登录需要，可跳过）

`crb login` 会**自动按顺序尝试**：Playwright 自带的 Chromium → 系统 Edge → 系统 Chrome。
只要电脑上装了 Edge 或 Chrome（Windows 一般自带 Edge），就**无需下载**。

如果三者都没有，再下载 Playwright Chromium：

```bash
uv run playwright install chromium
```

也可手动指定：`uv run crb login --browser msedge`（可选 `auto`/`chromium`/`msedge`/`chrome`）。

### 4. 首次登录

```bash
uv run crb login                   # 自动选浏览器（Chromium -> Edge -> Chrome）
uv run crb login --browser msedge  # 指定用系统 Edge
```

会弹出一个有头浏览器，请在官方页面完成南京大学统一身份认证（扫码或账号密码）。
成功后登录态保存到 `~/.crb/auth.json`，之后所有命令都不再需要登录。

> 登录态默认有效期取决于学校统一认证策略；失效时命令会提示重新 `crb login`。
> 自定义保存位置：`export CRB_AUTH_FILE=/path/to/auth.json`

---

## 使用

```bash
uv run crb doctor                                  # 自检
uv run crb campus                                  # 校区
uv run crb buildings --campus 3                    # 仙林教学楼
uv run crb free --campus 3 --date 2026-09-10 -p 1-2 --json   # 查空闲教室
uv run crb plan --file examples/plan.example.json             # 批量规划（只出方案）
uv run crb plan --file examples/plan.example.json --save      # 批量规划并存草稿
uv run crb borrow list --json                      # 我的申请
uv run crb borrow draft --file reqs.json --json    # 批量存草稿
uv run crb borrow delete --sqbh <SQBH>             # 删除申请/草稿
```

所有命令都支持 `--json`，便于脚本和 AI 消费。

### 批量申请数据格式

推荐用 `crb plan`（自动查空闲教室 + 分配 + 冲突检测）：

```bash
uv run crb plan --file examples/plan.example.json          # 先看方案
uv run crb plan --file examples/plan.example.json --save   # 确认后存草稿
```

`plan` 文件格式见 [examples/plan.example.json](examples/plan.example.json) 与
[docs/批量规划设计.md](docs/批量规划设计.md)。

也可以跳过规划，直接给 `borrow draft` 喂申请数组：

`reqs.json` 是一个数组，每个元素是一条申请，字段见
[`.pi/skills/crb/SKILL.md`](.pi/skills/crb/SKILL.md)。最小示例：

```json
[
  {
    "JYYTMS": "学生社团例会",
    "JYDWDM": "400760",
    "JYRXM": "李赫",
    "JYRDH": "13800000000",
    "JSJYLXDM": "02",
    "XXXQDM": "3",
    "KSRQ": "2026-09-10",
    "JSRQ": "2026-09-10",
    "ZC": "3",
    "XQ": "4",
    "KSJC": "1",
    "JSJC": "2",
    "ZRS": "30"
  }
]
```

---

## 目录结构

```
NJU_Classroom_Booking/
├── src/crb/
│   ├── cli.py        # 命令行入口（typer）
│   ├── api.py        # 学校后端接口封装
│   ├── session.py    # 登录态 + httpx 会话
│   ├── auth.py       # Playwright 有头登录
│   ├── models.py     # 数据结构
│   └── config.py     # 接口地址 / 字典常量
├── .pi/skills/crb/   # 供 AI harness 使用的 skill
├── docs/
│   ├── 思维过程1.md
│   └── reference/    # 前期探测记录
└── pyproject.toml
```

---

## 开发

```bash
uv run ruff check .        # 静态检查
uv run pytest              # 测试（待补充）
```

## 参考文档

- [docs/思维过程1.md](docs/思维过程1.md) —— 项目定位与核心困境
- [docs/reference/nju-classroom-agent-findings.md](docs/reference/nju-classroom-agent-findings.md) —— 接口探测完整记录
- [docs/reference/方案与老师反馈.md](docs/reference/方案与老师反馈.md) —— 给老师的方案（含批注）

## 安全与合规

- 本工具只做「自动化重复操作」，不绕过任何权限：能申请到什么，取决于登录账号本身的权限。
- 测试时一律保存草稿，并清理测试数据，避免在学校系统留下垃圾。
- 请遵守学校信息系统使用规范；批量操作前建议先小规模验证。
