# Changelog

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)，
变更记录遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式。

## 0.0.0 - 2026-02-21

首个公开版本。学生端 CLI + 内置 AI Skill 打通：登录态复用 → 查空闲教室 →
批量规划 → 生成 / 提交 / 撤回 / 编辑 / 删除借用申请。

### Added

- **登录态复用**：`crb login` 用 Playwright 有头登录完成一次统一身份认证，
  登录态持久化到 `~/.crb/auth.json`；浏览器自动回退 Chromium → Edge → Chrome。
- **自检**：`crb doctor` 检查登录态、当前学期、借用开关与所在单位。
- **借用人档案**：`crb profile` 管理姓名 / 手机号 / 单位 / 默认校区，登录时顺带采集。
- **字典查询**：`crb campus`、`crb buildings`。
- **空闲教室**：`crb free` 走权威接口 `kxjscx/cxkxjs.do`，节次过滤由服务端完成。
- **批量规划**：`crb plan` 查空闲 → 容量过滤 → 批次内 + 跨批次冲突检测 → 分配教室，
  默认 dry-run，`--save` 批量存草稿，`--submit` 批量正式提交。
- **申请管理**：`crb borrow list / draft / submit / withdraw / edit / delete`。
- **内置 Skill**：`SKILL.md` 随 wheel 分发，`crb skill path / show / install` 查看与安装。
- **机器可读输出**：所有命令支持 `--json`；写操作统一返回 `{"ok","code","msg"}`。
- **版本号**：`crb --version`。
- **工程化**：uv 管理依赖与构建，ruff 静态检查，pytest 单元测试，GitHub Actions CI，
  MIT License，CHANGELOG，CONTRIBUTING。

### Security

- 默认只保存草稿（`TYPE=save`），正式提交必须显式使用 `--submit`。
- 登录态与档案文件默认不入库（`.gitignore`），Skill 中明确禁止读取 / 上传其内容。
- 不绕过任何权限：能申请到什么，取决于登录账号本身的权限。
