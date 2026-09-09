---
name: crb
description: 南京大学教室借用自动化（CRB = ClassRoom Booking）。当用户提到「nju / 南京大学 / 教室借用 / 借教室 / 空闲教室 / 教室申请 / 社团活动场地 / 训练营场地 / 撤回申请」等词，或需要查询空闲教室、批量提交教室借用申请、查看/撤回/修改申请时，强烈建议使用本 skill。通过本地 `crb` CLI 复用登录态直连学校办事大厅；默认只存草稿，正式提交必须用户明确授权。
---

# CRB — 南京大学教室借用

## 何时使用（触发词）

出现以下任一意图时注入本 skill：
`nju` / `南京大学` / `教室借用` / `借教室` / `空闲教室` / `教室申请` / `社团活动场地` / `训练营场地` / `借用申请` / `撤回申请`。

## 前置条件（一次性）

```bash
uv tool install "crb[login]"   # 或 pipx install "crb[login]"
crb login                      # 打开浏览器扫码；顺便会问手机号，存进档案
```

- 登录态 `~/.crb/auth.json`、档案 `~/.crb/profile.json`：**敏感文件，不要读取内容、不要上传、不要入库**。
- 浏览器自动回退 Chromium → Edge → Chrome；都没有才需 `playwright install chromium`。
- 从源码跑：`uv sync --extra login && uv run crb login`（下文命令的 `crb` 换成 `uv run crb`）。
- 找不到本 skill 时：`crb skill install --dir <harness 的 skills 目录>`。

## 命令

一律加 `--json`，AI 读结构化结果。

| 命令 | 作用 |
|---|---|
| `crb doctor --json` | 自检：登录态、当前学期、借用开关、单位 |
| `crb campus --json` | 校区：`1` 鼓楼 / `2` 浦口 / `3` 仙林 / `4` 苏州 |
| `crb buildings --campus 4 --json` | 教学楼字典（返回 `JXLDM` + 名称） |
| `crb free --campus 4 --date 2026-09-11 --period 7-8 --json` | 查空闲教室（可加 `-b <教学楼>`、`-t <教室类型>`） |
| `crb plan --file plan.json --json` | 批量规划：查教室 + 分配 + 冲突检测（只出方案） |
| `crb plan --file plan.json --save` | 批量存草稿 |
| `crb plan --file plan.json --submit` | ⚠️ 批量正式提交 |
| `crb borrow list --json` | 我的申请（`SQBH` / `SHZT`） |
| `crb borrow withdraw --sqbh <SQBH> --json` | 撤回 |
| `crb borrow edit --sqbh <SQBH> --data '{"ZRS":"35"}' --json` | 修改并重新提交 |
| `crb borrow submit --sqbh <SQBH> --json` | 草稿/已撤回 → 提交 |
| `crb borrow draft --file reqs.json --json` | 直接按申请数组存草稿（不走规划） |
| `crb borrow delete --sqbh <SQBH> --json` | 删除 |

> 所有命令都支持 `--json`（写操作返回 `{"ok":bool,"code":int,"msg":str}`）。
> **不确定参数时加 `--help`**，例如 `crb borrow edit --help`。

## 节次时间（全校统一）

| 节 | 时间 | 节 | 时间 |
|---|---|---|---|
| 1 | 08:00-08:50 | 7 | 16:10-17:00 |
| 2 | 09:00-09:50 | 8 | 17:10-18:00 |
| 3 | 10:10-11:00 | 9 | 18:30-19:20 |
| 4 | 11:10-12:00 | 10 | 19:30-20:20 |
| 5 | 14:00-14:50 | 11 | 20:30-21:20 |
| 6 | 15:00-15:50 | 12 | 21:30-22:20 |

「下午 4 点后」→ 第 7 节起；「晚上 7 点」→ 第 9 节；以此类推。

## 完整范例

> 用户：「周五下午 4 点后在苏州校区南雍楼借两间教室，社团分享，30 人和 20 人各一场」

**1) 确认登录态 / 学期 / 单位**

```bash
crb doctor --json
# {"ok":true,"term":"2026-2027-1","JSJYSFKT":"1","JYSJFW":"2026-08-21,2026-12-28","org":"400760"}
```

**2) 查教学楼代码**

```bash
crb buildings --campus 4 --json
# [{"JXLDM":"S06","JXLMC":"南雍楼"},{"JXLDM":"S01","JXLMC":"公共教学楼"}]
```

**3) （可选）先探该时段教室**

```bash
crb free --campus 4 --date 2026-09-11 --period 7-8 -b S06 --json
# [{"JASMC":"南雍-西108","KXJC":"7-8节","KXSJ":"16:10-17:00,17:10-18:00","SKZWS":58}, ...]
```

**4) 写 `plan.json`**（「周五」→ `2026-09-11`；「下午4点后」→ `period 7-8`；人数 → `people`）

> `title` 会成为申请的**用途描述**，并自动追加「（意向：教室）」；不想要可加 `--no-room-in-purpose`。

```json
{
  "defaults": { "campus": "4", "building": "S06", "JSJYLXDM": "02" },
  "activities": [
    { "title": "社团分享（第一场）", "date": "2026-09-11", "period": "7-8", "people": 30 },
    { "title": "社团分享（第二场）", "date": "2026-09-11", "period": "7-8", "people": 20 }
  ]
}
```

**5) 出方案，汇报给用户确认**（两场会自动分到不同教室，防重合）

```bash
crb plan --file plan.json --json
```

**6) 用户确认后落库**

```bash
crb plan --file plan.json --save --json     # 草稿（默认）
crb plan --file plan.json --submit --json   # ⚠️ 正式提交，需用户明确授权
```

**7) 提醒用户**：提交后需联系指导老师初审（使用日期前至少 1 个工作日；周末教室需周五 16:00 前完成初审）。

## 关键字典

- 校区：`1` 鼓楼 / `2` 浦口 / `3` 仙林 / `4` 苏州
- 借用类型 `JSJYLXDM`：`01` 辅导员、`02` 学生社团管理部、`03` 就业指导中心、`04` 国际合作与交流处、`05` 学生工作处、`06` 校团委、`13` 待悦读课程管理
- 状态 `SHZT`：`00` 草稿、`65` 待审核、`1` 已撤回、`99` 已通过。
  （已通过（`99`）后的撤回/修改是否允许由学校规则决定，未实测。）

## 硬性规则

1. **默认只存草稿**；正式提交必须用户明确要求并再次确认（`--submit` / `crb borrow submit`）。
2. 不制造垃圾数据；测试草稿用 `crb borrow delete --sqbh` 清理。
   **删除/撤回前先在 `crb borrow list --json` 里核对 `SQBH`**，切勿误删真实申请。
3. 批量操作前先 `crb doctor --json`；登录失效就提示用户 `crb login`。
4. `crb plan` 自动做跨批次防重合：与自己已有申请时间重叠 → `duplicate` 跳过；从备注 `FJ` 读取已用教室避免重复选同一间。确需重叠用 `--allow-overlap`。
5. 学生端不能指定教室，`preferred_room` 只写进用途描述（「意向：xxx」），不保证借到。
6. 不要输出 `auth.json` / `profile.json` 的内容。

## 限制

- 仅覆盖学生端（教师端入口不同）。
- 空闲教室只返回教室名，没有楼层/教室代码。
