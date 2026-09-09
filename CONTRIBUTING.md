# 贡献指南

感谢参与 CRB（南京大学教室借用工具）。提交代码前请先读一遍本文。

## 环境准备

```bash
uv sync --extra login      # 含 Playwright（登录相关改动用得上）
uv run crb --help
```

## 提交前自检（必须全绿）

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run python scripts/sync_skill.py && git diff --exit-code -- .pi/skills/crb/SKILL.md
```

## 分支与提交信息

- 从 `master` 切分支，命名建议：`feat/xxx`、`fix/xxx`、`docs/xxx`。
- 提交信息使用 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/)：
  `feat(plan): ...`、`fix(login): ...`、`docs(skill): ...`、`chore: ...`。
- 一个提交只做一件事；避免把格式化与功能改动混在一起。

## 代码约定

- Python ≥ 3.12，类型标注尽量完整（`from __future__ import annotations`）。
- 行宽 100，ruff 规则见 `pyproject.toml`。
- **网络 / 登录态相关的逻辑不要写进单元测试**：测试必须离线可跑。
  需要构造的请求体、解析逻辑，抽成纯函数再测（参考 `tests/test_planner.py`）。
- 新增命令必须支持 `--json`，写操作统一返回 `{"ok", "code", "msg"}`。

## Skill 的修改

`SKILL.md` 的**唯一事实来源**是 `src/crb/data/SKILL.md`（随 wheel 分发），
仓库内 `.pi/skills/crb/SKILL.md` 只是同步副本。

改完跑：

```bash
uv run python scripts/sync_skill.py
```

`tests/test_skill.py::test_repo_copy_in_sync` 会校验两者一致。

## 安全红线

- **绝不**提交 `auth.json`、`profile.json` 或任何真实 Cookie / 手机号。
- 测试请使用草稿（`--save`）并及时用 `crb borrow delete --sqbh` 清理；
  不要为了测试向学校系统灌垃圾数据。
- 不要引入绕过权限、伪造身份、批量轰炸接口的代码。

## 发布

见 README 的[发布流程](README.md#发布流程)。
