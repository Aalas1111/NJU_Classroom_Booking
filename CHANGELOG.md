# Changelog

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)，
变更记录遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式。

## Unreleased

### Added

- `crb free --date` 支持**逗号分隔的多天**（一天一发请求、互不影响）：
  「这几天哪天有空教室」一次问完，不用调用方自己循环（每多一次调用就多一整轮模型往返）。
- **`crb day`：一次问全一栋楼的空档**（教室名/容量/类型 + 空闲段/占用段）。
  请求数只跟节次数有关（1 + 12 发），**跟教室数无关**：苏州南雍楼 42 间 / 一楼东区 11 间
  都是一样的开销 —— 逐间调 `crb room` 则是每间 13 发（一层楼二十几秒）。
  `crb room`（单间）与它共用同一套逐节逻辑。
- **教师端契约自动识别**：`JSJYLXDM` 是同名字段两套字典（学生端=指导教师所在单位，
  教师端=活动类型）。`crb` 现在按登录账号的 `cxjsjylx.do` 字典判定 `role`
  （`student` / `teacher`），缺省借用类型随之取值（学生端 `02` / 教师端 `09` 团学活动）。
- `crb plan --save/--submit` 与 `borrow draft` 会用当前账号字典校验 `JSJYLXDM`，
  跨端代码直接报错并列出可用值；`plan --json` 输出带 `contract` 信息。
- `crb doctor` 显示账号契约与可用借用类型；登录采集档案时一并记录 `borrow_role` / `JSJYLXDM`。
- **教室视角查询**（把「时段 → 空闲教室」翻过来，回答「某间教室某天各节空不空」）：
  - `crb rooms`：教室索引（教室名 / 教学楼 / 容量 / 类型），`--match` 按关键词筛；
  - `crb room`：某一间教室在某天的逐节空闲/占用 + 空闲时间段汇总（`-p` 可只看某段）；
    名字对不上或对上多间时**不猜**——返回 `status=ambiguous`/`not_found` 与候选，
    交给调用方去确认。
  - 实现口径：学校只有「按时段查空闲教室」是权威的（`cxkxjs.do`），且**区间语义是
    「整个区间都空闲」**（实测 `1-2` = `1` ∩ `2`），所以逐节状态靠单节查询问出来；
    整天全空的最多问 1 发，其余最多 1 + 节次个数发。占用网格 `cxjsqk.do` 与单教室
    详情 `cxkxjsxq.do` 都不完整（列语义混乱 / 只回一部分占用），未采用。
- `crb buildings` 的 `--campus` 变为可选：不填就四个校区一起列（每行带 `XXXQDM`）。
- `crb free --json` 之外的新命令统一输出**友好字段名**（`name`/`building`/`capacity`…），
  不再直接把学校字段（`JASMC`/`SKZWS`）丢给调用方。

### Changed

- `crb plan` 的防重口径改为「日期 + 校区 + 节次 + 教室」四项（对齐教师侧脚本）：
  四项一致（节次区间有重叠也算）才判 `duplicate`；**时段重叠但教室不同不再判重复**
  （并行活动是正常需求，此前的实现会误拦）。已有申请的教室证据优先取 `FJ`，
  没有则取学校分配后的 `JASMC`；教室名比对做了归一化（`仙I-102` / `仙Ⅰ-102` 视为同一间）。
  `--allow-overlap` 语义不变（强制放行重复）。

### Fixed

- 登录后采集档案时，交互环境 stdin 提前 EOF（如 AI harness / CI）不再中断整个 `crb login`，
  已采集到的单位与契约照常入库。
- `plan --json` 回执里的 `request.TYPE` 过去固定显示 `save`（快照早于 TYPE 改写），
  现与实际发送值（`save` / `TJ`）一致。

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
