# 南京大学教室借用 Agent — 可行性探测记录

> 结论先行：**方案可行**。登录态可持久化；空闲教室查询和教室借用申请均为可直连的 `.do` 接口；保存草稿、正式提交、撤回、删除均已通过真实 POST 验证成功（测试数据已清理）。

---

## 1. 入口与登录

### 统一身份认证
- 所有 ehall 页面都先跳转到：`https://authserver.nju.edu.cn/authserver/login`
- 登录方式：账号密码 / 微信或南京大学 APP 扫码。
- 扫码登录后，authserver 会下发 `CASTGC` Cookie（会话级，关浏览器即失效）。
- 我们通过 Playwright `context.storageState()` 保存整个登录态到 `nju-auth-state.json`，之后用 `state-load` 恢复即可免登录访问（已验证）。

### NJUAlwaysLogin 脚本（https://github.com/lyc8503/NJUUtils/blob/main/NJUAlwaysLogin.user.js）
- 原理：
  1. 访问登录页时重定向到 `authserver/login?service=.../authserver/a`；
  2. 把隐藏字段 `#dllt` 设为 `mobileLogin`，走**移动端登录**，从而拿到有效期更长的 `CASTGC`；
  3. 登录后访问 `/authserver/a`，读取 `CASTGC`，重新写回 Cookie，`expirationDate` 设为约 1 年。
- 对本项目的价值：
  - 它解决的是“关浏览器后登录态丢失”的问题。我们用 Playwright 持久化 profile + `state-save/state-load` 已经能达到同样效果。
  - 更关键的启发：**登录时用 `mobileLogin`（`dllt=mobileLogin`）能让 `CASTGC` 更长效**。如果后续做成 CLI，可以复刻这个思路，或直接用 `NJUlogin`（Python 包，含扫码/账号密码/导出 cookies）来获取一个长效会话。
  - 我们不一定要用 Tampermonkey 注入；可以把它当“参考实现”。

### 桌面版门户
- `https://ehall.nju.edu.cn/`（网上办事服务大厅）也可登录，同样走统一认证，且与 ehallapp 会话互通（自动免密登录）。
- 但 **`/jwapp/sys/jsjy` 在桌面版门户域下是 404**（该应用只部署在 `ehallapp.nju.edu.cn`）。
- 门户搜索“教室借用”会新开标签，跳转到 `ehallapp.nju.edu.cn/jwapp/sys/jsjy/*default/index.do?...`，这才是能正常加载的入口。

---

## 2. 空闲教室查询（kxjas）

### 可访问的页面
- `https://ehallapp.nju.edu.cn/jwapp/sys/kxjas/*default/index.do?...#/kxjscx` → 空闲教室查询
- `#/kxjas` → 教室占用情况（不是查询页）

### 关键后端接口（POST，需带登录 Cookie）
| 接口 | 用途 | 入参 |
|---|---|---|
| `/jwapp/sys/kxjas/zd/getXxxqdqx.do` | 校区字典 | 空 |
| `/jwapp/sys/kxjas/modules/kxjas/dqxnxqcx.do` | 当前学年学期 | 空 |
| `/jwapp/sys/kxjas/modules/kxjas/jxlcx.do` | 教学楼列表（需先选校区） | 校区代码 |
| `/jwapp/sys/kxjas/modules/kxjas/cxjsqk.do` | **主查询（空闲教室列表，实测通过）** | `XNXQDM/ZC/XQ/RQ/querySetting/pageSize/pageNumber/*order` |
| `/jwapp/sys/kxjas/modules/kxjas/cxkxjsxq.do` | 某个教室的空闲详情 | `ylxdm/XNXQDM/XQ` 等 |

- 校区字典返回示例：
  ```json
  {"datas":{"code":{"rows":[{"id":"1","name":"鼓楼校区"},{"id":"2","name":"浦口校区"},{"id":"3","name":"仙林校区"},{"id":"4","name":"苏州校区"}]}},"code":"0"}
  ```

### 主查询载荷（已实测通过）

关键点：前端 `emapdatatable` 不会用 `?action=xxx`，而是通过 `WIS_EMAP_SERV.joinActionIdToDoUrl(pagePath, action)` 把 `.do` 替换成 `/action.do`，即：
```
pagePath  /modules/kxjscx.do  +  action=cxkxjs
真实 URL  /jwapp/sys/kxjas/modules/kxjscx/cxkxjs.do
```
> 更正：旧记录里的 `/modules/kxjas/cxjsqk.do` 也能返回数据，但它不按节次过滤（要自己解析 `JC1..JC20`）。
> 前端「空闲教室查询 - 按日期」真正用的是 **`kxjscx/cxkxjs.do`**，节次由服务端过滤，**推荐用这个**。

实测成功的请求（服务端按节次过滤，结果权威）：
```
POST /jwapp/sys/kxjas/modules/kxjscx/cxkxjs.do
Content-Type: application/x-www-form-urlencoded

KXRQ=2026-09-10
KSJC=1
JSJC=2
XXXQDM=3
pageSize=999
pageNumber=1
querySetting=[]
# 可选过滤（顶层参数，实测有效）：
# JXLDM=11      教学楼
# JASLXDM=14    教室类型
```
返回 `{"datas":{"cxkxjs":{"totalSize":147,...}}}`，字段：
`JASMC` 教室名、`JXLDM(_DISPLAY)` 教学楼、`JASLXDM(_DISPLAY)` 教室类型、
`XXXQDM(_DISPLAY)` 校区、`KXRQ` 日期、`KSJC/JSJC` 节次、`KXJC`（如 "1-2节"）、
`KXSJ`（如 "08:00-08:50,09:00-09:50"）、`SKZWS` 上课座位、`KSZWS` 考试座位。

实测数据（2026-09-10 仙林 第1-2节）：无过滤 223 间，`KSJC/JSJC=1-2` → **147 间**，
`JXLDM=11` → 44 间，`JASLXDM=14` → 37 间，两者叠加 → 12 间。

- datatable 参数：`pageSize`、`pageNumber`（前端从 0 开始，发请求时 +1）、`querySetting`。
- `querySetting` 是数组 JSON 字符串，元素格式：`{"name":<字段名>,"value":<值>,"builder":<操作符>,"linkOpt":"AND"}`。
- 操作符（builder）只使用模型里合法的值：字符串用 `equal`/`include`；数值用 `equal`。**不要用 `ge`/`gt`**（会报 `Not found object [ge]`）。
- 前端搜索表单字段名与后端参数不同：表单用 `KXRQ/KXJC/KSZWS/SKZWS`，`createQueryParam()` 会转换成 `KXRQ/KSJC/JSJC/KSKSZWS/...` 再发给后端。

教学楼/教室类型字典：
- `POST /jwapp/sys/kxjas/modules/kxjas/jxlcx.do`，body `XXXQDM=3` → 返回仙林教学楼：仙I区(`11`)、仙II区(`12`)、逸夫楼A区(`15`)、逸夫楼B区(`16`) 等。
- 教室类型字典：`POST /jwapp/code/79ee3ac8-c638-442b-ba24-15d6f5e79797.do` → 返回智慧研讨教室(`11`)、智慧阶梯教室(`12`)、普通多媒体教室(`05`)、普通多媒体（研讨）(`01`) 等。
- 用户提示：**先选校区，再选教学楼**；教学楼接口用 `XXXQDM`（不是 `XQDM`，后者会忽略过滤返回全部）。

日期→周次/星期的映射（供查询和借用共用）：
- `POST /jwapp/sys/jsjy/modules/jsjysq/cxrqdydzcxq.do`，body `XN=2026-2027&XQ=1&RQ=2026-09-10` → 返回 `ZC=3, XQJ=4`（第3周 星期4）。
- 注意参数是 `XN`/`XQ`/`RQ`，不是 `XNXQDM`。



---

## 3. 教室借用申请（jsjy）

### 可访问的页面（关键）
- 正确入口：
  `https://ehallapp.nju.edu.cn/jwapp/sys/jsjy/*default/index.do?t_s=<新时间戳>&_sec_version_=1&gid_=...&EMAP_LANG=zh&THEME=magenta#/jsjysq`
- 注意：从门户搜索“教室借用”点进去会自动带一个**新的 `t_s`**，这个入口能正常加载；直接用手动拼的旧 `t_s` 有时会去请求 `modules/jsjy/jsjysq/...` 而 404，导致空白页。
- 页面功能：
  - 主列表：我的教室借用申请（审核状态、借用人、校区、日期、节次等）
  - 顶部有 **“临时借用（仅借1天）”** 链接，点击进入申请表单。
  - 表单底部有 **“保存为草稿 / 提交 / 取消”**。

### 关键后端接口（POST，需登录 Cookie）
| 接口 | 用途 |
|---|---|
| `/jwapp/sys/jsjy/modules/jsjysq/cxdqxnxq.do` | 当前学年学期 |
| `/jwapp/sys/jsjy/modules/jsjysq/cxyhszdw.do` | 借用人所在单位 |
| `/jwapp/sys/jsjy/modules/jsjysq/cxjsjylx.do` | 教室借用类型字典 |
| `/jwapp/sys/jsjy/modules/jsjysq/cxrqdydzcxq.do` | 日期→周次/星期 |
| `/jwapp/sys/jsjy/modules/jsjysq/cxxljxjszc.do` | 校历/教学周次 |
| `/jwapp/sys/jsjy/modules/jsjysq/cxxtcs.do` | 系统参数（借用窗口等） |
| `/jwapp/sys/jsjy/modules/jsjysq/cxjsjysq.do` | **列表查询**（同 `joinActionIdToDoUrl` 规律，实测通过，返回 `datas.cxjsjysq.rows`） |
| `/jwapp/sys/jsjy/modules/jsjysq/xzjasjysq.do` | **新增/保存/提交借用申请** |
| `/jwapp/sys/jsjy/modules/jsjysq/scjssq.do` | 删除借用申请 |
| `/jwapp/sys/jsjy/modules/jsjysq/shjsjysq.do` | 撤回/审核（撤回：`SQBH`+`SHZT=1`+`JSJYSQLX=6`+`CQDQJY`） |
| `/jwapp/sys/jsjy/modules/jsjysq/scjsdj.do` | 删除教室登记 |
| `/jwapp/sys/jsjy/modules/gg/cxjskjxq.do` | 查询空闲教室（选择教室用） |

### 保存草稿 / 提交接口（核心）
- 接口：`POST /jwapp/sys/jsjy/modules/jsjysq/xzjasjysq.do`
- 参数（form-urlencoded）：`param=<JSON.stringify([data])>`
- `data.TYPE`：
  - `'save'` → **保存草稿**（测试用）
  - `'TJ'` → **正式提交**
- `data` 字段（来自前端 `xsq.js`）：
  ```
  JYDWDM    借用人单位代码      JYRXM    借用人姓名
  JYRDH    联系电话            JYYTMS   借用用途描述
  JSJYLXDM 教室借用类型代码      FZLS     附则
  XXXQDM   校区代码            JSRL     教室容量
  KSRS     考试座位数?          JYSL     教室借用数量
  SFHDJS   是否活动教室         JYFSDM   借用方式代码 (0=按节次)
  XNXQDM   学年学期代码         KSRQ     开始日期
  JSRQ     结束日期            XQ       星期 (1-7)
  ZC       周次              KSJC     开始节次
  JSJC     结束节次           KSSJ     开始时间
  JSSJ     结束时间           SQBH     申请编号
  JYLYDM   '02' (固定)        JSJYSQLX 2 (固定)
  CQDQJY   '1'长期 / '2'短期   TYPE     save / TJ
  ZRS      总人数             SFYYKS   是否用于考试
  SFXHDZY  是否需活动桌椅       SJD      时间段
  FJ       备注/房间
  ```

### 已获得的字典值
- `JYDWDM = "400760"`（账号 251880503 的所在单位代码，智能科学与技术学院）
- `XNXQDM = "2026-2027-1"`（2026-2027 学年 第1学期）
- `JSJYLXDM` 可选：
  - `01` 辅导员
  - `02` 学生社团管理部
  - `03` 就业指导中心
  - `04` 国际合作与交流处
  - `05` 学生工作处
  - `06` 校团委
  - `13` 待悦读课程管理
- 校区代码：`1=鼓楼, 2=浦口, 3=仙林, 4=苏州`
- 节次示例：`第1节(08:00-08:50)`、`第2节(09:00-09:50)`，对应 `KSJC/JSJC = "1"/"2"`

### 提交正式版（`TYPE='TJ'`）校验逻辑（来自前端 `xsq.js`）

`actionSave`（保存草稿）只是把 `type='save'` 后调用 `actionSubmit`；`actionSubmit` 内部流程：
1. `$('.sq-form').emapValidate("validate")` —— 表单必填校验（不通过直接 return）。
2. 取表单值 `sqForm = $('.sq-form').emapForm("getValue")`。
3. `JYYTMS` 不能等于默认提示文案（否则提示“请输入借用用途说明”）。
4. `JYDWDM` 非空（否则“该账号无所属院系单位，无法提交教室借用申请”）。
5. 若 `JYFSDM == '2'`（按时间/天数）→ `checkrq(sqForm)`：
   - 通过 `cxxtcs.do` 取 `JYSJFW`（可借开始/结束日期，默认 `2026-08-21,2026-12-28`），`KSZJSJYQXSZ`（开室周次）等；
   - 校验开始日期/结束日期在可借窗口内（至少提前 N 天、最多借 N 天）。
6. `KSJC`(开始节次) 不能大于 `JSJC`(结束节次)。
7. `getGudge()`：拉取系统参数，若 `JSJYSFKT == '0'` → “当前教室借用未开启”并拦截；若 `JQSFJZJYJS == '1' && checkSfjq()` → 同样拦截。
8. 构造 `data` 对象（字段见上），设 `TYPE` 为当前 `type`（保存= `'save'` / 提交= `'TJ'`），`params.push(data)`。
9. `bs.addJasJysq({'param': JSON.stringify(params)})` → `POST /modules/jsjysq/xzjasjysq.do`。
10. 响应 `datas.xzjasjysq.extParams.code == 1` → 成功；`-1` → 显示 `msg` 警告。

系统参数（`cxxtcs.do`）关键值（实测）：
- `DQXNXQDM` → `2026-2027-1`
- `JSJYSFKT` → `1`（教室借用总开关已开）
- `JQSFJZJYJS` → `0`（假期不禁借用）
- `JYSJFW` → `2026-08-21,2026-12-28`
- `KSZJSJYQXSZ` → 考试周借用权限单位列表

> 更正：`cxxtcs.do` 返回的是**键值表**（763 行），每行 `ZCSDM`=参数代码、`CSZA`=参数值、`CSSM`=说明。
> `cxdqxnxq.do` 的学期字段是 `DM`（不是 `XNXQDM`）；`cxyhszdw.do` 的单位字段是 `SZDWDM`（即申请里的 `JYDWDM`）。

### 删除接口确认
- 前端行渲染（`jsjysq.js` 的 `cellsRenderer`）：
  - `SHZT == '00'`（草稿）→ 只显示 `提交 | 编辑`，**没有“删除”按钮**。
  - `SHZT == '1'`（撤回状态）→ 显示 `撤回 | 删除 | 提交 | 编辑`，其中 **“删除”按钮**：`data-x-wid = rowData.SQBH`、`data-action="删除"`。
  - `actionDelete` 实现：`bs.deleteJssq({param:'[{SQBH: ' + sqbh + '}]'})`，对应接口 **`POST /jwapp/sys/jsjy/modules/jsjysq/scjssq.do`**，body `param=[{SQBH:<申请编号>}]`。
- **实测**：对草稿也直接调了 `scjssq.do`，返回 `msg:"操作成功"`，重新加载 jsjy 列表后 `totalSize:0`，**草稿确实被删除**。（此前“刷不出来”是页面刷新/缓存时机问题。）

### 正式提交 / 撤回 / 编辑（均已实测）

| 操作 | 接口 | 参数 | 说明 |
|---|---|---|---|
| 正式提交 | `POST /modules/jsjysq/xzjasjysq.do` | `param=[data]`，`TYPE='TJ'` | 保存草稿是同一接口 `TYPE='save'` |
| 撤回 | `POST /modules/jsjysq/shjsjysq.do` | `SQBH`、`SHZT=1`、`JSJYSQLX=6`、`CQDQJY` | 撤回后 `SHZT` 变 `1` |
| 删除 | `POST /modules/jsjysq/scjssq.do` | `param=[{SQBH:...}]` | |
| 编辑 | `POST /modules/jsjysq/xzjasjysq.do` | 带上原记录 `WID`+`SQBH` 的完整表单 | **更新**而非新增，`TYPE` 决定草稿/提交 |

状态机（`SHZT`）：`00` 草稿 → 提交 → `65` 待学生社团管理部审核 → 撤回 → `1` 已撤回 → 提交 → `65` …；`99` 已通过。
前端按钮可见性：`SHZT=='00'` → 提交/编辑；`SHZT=='1'` → 删除/提交/编辑；未审核（非 00/1/999）→ 撤回/查看。

### 真实测试结果（更新）
- 用 `TYPE='save'` 直接 POST `xzjasjysq.do`，服务端返回：
  ```json
  {"datas":{"xzjasjysq":{"totalSize":0,"rows":[],"extParams":{"logId":"...","code":1,"msg":"操作成功"}}}}
  ```
- 返回后刷新列表，出现一条**暂存/草稿**记录：
  ```
  提交 | 编辑  暂存  智能科学与技术学院  李赫  13800000000  学生社团管理部  仙林校区  2026-09-10  第1节-第2节  2026-09-07 22:29:58.0
  ```
- 删除接口 `scjssq.do`（`param=[{SQBH:<WID>}]`）**实测成功**，刷新列表后 `totalSize:0`，草稿已从系统删除。前端草稿行不显示“删除”按钮（只在撤回状态显示），但直接调接口可删除草稿。

---

## 4. 技术方案建议（CLI + Skill）

### 总体形态
- 一个命令行工具（建议 Node.js 或 Python）：
  - 登录：首次由用户手动扫码/密码登录，工具用 Playwright（或 `NJUlogin`）保存会话到本地文件（等同于 `nju-auth-state.json`）。
  - 之后所有功能只依赖“会话 Cookie”直接调用上述 `.do` 接口，**不依赖浏览器 UI**。
- 一个 skill 文档：告诉 AI 如何调用该 CLI、命令参数、接口映射、字段说明书。

### 功能
1. `nju-cli login` —— 扫码/账号密码登录，保存登录态。
2. `nju-cli free-rooms --campus 3 --date YYYY-MM-DD --period 1-2 [--building X]` —— 查询空闲教室。
3. `nju-cli borrow draft --from ...` —— 生成/保存草稿（`TYPE=save`）。
4. `nju-cli borrow submit --wid ...` —— 提交（`TYPE=TJ`）。
5. `nju-cli borrow list` —— 查看我的申请。
6. （后续）`nju-cli borrow delete` —— 删除（需进一步确认草稿删除后端行为）。

### Skill 需要固化的知识
- 正确的 base path：`https://ehallapp.nju.edu.cn/jwapp/sys/jsjy/modules/...`
- 必须的请求头：POST + form-urlencoded，带会话 Cookie。
- `param` 是 JSON 字符串化后的数组。
- 字段字典（如上）。

---

## 5. 风险 / 待确认

1. **jsjy 前端部署路径不稳定**：直接访问 `#/jsjysq` 有时会解析到不存在的 `modules/jsjy/jsjysq/...` 而空白；必须用门户搜索生成的带新 `t_s` 的 URL，或**直接调后端接口绕过前端**。
2. **校历/日期转换已解决**：`cxrqdydzcxq.do` 正确参数是 `XN=2026-2027&XQ=1&RQ=YYYY-MM-DD`（不是 `XNXQDM`）。实测 2026-09-10 → 第3周 星期4。CLI 可直接用此接口把日期转为 `ZC/XQ`。
3. **删除接口可用**：`scjssq.do` 能删除草稿（实测成功）；但前端 UI 只为撤回状态（`SHZT='1'`）显示“删除”按钮。开发时删除功能可直接调接口。
4. **账号权限/角色**：当前账号为“本科学生组”，所在单位 `400760`（智能科学与技术学院），部分功能（如浦口校区借用）可能受限。
5. **测试数据要及时清理**：默认用 `TYPE='save'` 造草稿；确需验证正式提交时，测完立刻用 `scjssq.do` 删除，不要在系统里留下垃圾申请。
6. **datatable 请求格式**：所有列表接口都要用 `pagePath` + `action` 拼成 `/modules/xxx/action.do`，且带 `pageSize/pageNumber`（pageNumber 从 0 开始+1）和 `querySetting`。

---

## 6. 已保存的本地文件
- 登录态快照：`D:\Coding\CursorProjects\pi_workspace\nju-auth-state.json`
- Playwright 持久化 profile：`D:\Coding\CursorProjects\pi_workspace\.nju-playwright-profile`
- 截图（登录页）：`D:\Coding\CursorProjects\pi_workspace\nju-login.png`

---

## 7. 教师端账号探测（2026-09-28，实测）

借教师账号（工号 `0412007`，姓名 郭亚敏，所在单位 `200300` = 本科生院，`RZLBDM=99999`）
用 `crb login` + 独立登录态文件跑通，接口与字段结构与学生端完全一致，差异只在**字典**：

- `cxyhszdw.do` → `SZDWDM=200300`（借用单位，即 `JYDWDM`）；教师记录里 `JYDWDM=200300` 显示为「本科生院」。
- `cxjsjylx.do`（借用类型）返回**教师端字典**，与学生端是两套：
  - 教师端：`07` 教师教学、补课 / `09` 团学活动 / `21` 长期借用 / `39` 考试 / `40` 讲座
  - 学生端：`01` 辅导员 / `02` 学生社团管理部 / `03` 就业指导中心 / `04` 国际合作与交流处 /
    `05` 学生工作处 / `06` 校团委 / `13` 待悦读课程管理
- 同一个 `JSJYLXDM` 字段，两端的表单标签也不同：学生端是「指导教师所在单位」（字典=单位名），
  教师端是「借用类型」（字典=活动类型）；教师端没有「指导教师所在单位」这个字段。
- `crb plan` 只读链路在教师账号下全部可用：`cxkxjs.do` 查空闲教室（仙林 09-30 1-2 节 165 间）、
  `cxrqdydzcxq.do` 日期→周次、`cxjsjysq.do` 我的申请（19 条，含已通过/不通过）。

教师端一条已通过记录的关键字段（`cxjsjysq.do`）：

```
JYDWDM=200300(本科生院)  JYRXM=郭亚敏  SQR=0412007  JASJYLXDM=09(团学活动)
XXXQDM=4(苏州校区)  KSRQ=JSRQ=2026-09-26  KSJC=5  JSJC=7  JYFSDM=0  JYLYDM=02
CQDQJY=2  JSRL=20  ZRS=20  JYSL=1  FJ=null  FZLS=null  KSRS=null  XQ=null  ZC=null
JASMC=南雍-东122（审核通过后由管理员分配，申请时不填）
```

结论（已落到 `crb` 代码）：

- 契约按 `cxjsjylx.do` 返回的字典判定（`api.borrow_contract`），不猜账号属性：
  字典含教师端代码 → 教师端契约，默认 `JSJYLXDM=09`（团学活动）；否则学生端契约，默认 `02`。
- `plan --save/--submit` 与 `borrow draft` 都会用当前账号字典校验 `JSJYLXDM`，
  把学生端代码提交到教师端会直接报错并列出可用值，不会静默改写。
- 教师端「指定教室」同样只是意向（`JYYTMS` 里写教室名），正式教室由本科生院审核后分配（`JASMC`）。
- 端到端验证（2026-09-28，教师账号）：
  - 草稿：`plan --save` → 回读 `SHZT=暂存` / `JASJYLXDM=09 团学活动` / `JYDWDM=200300` /
    `FJ=意向教室` → `borrow delete` 删除；
  - 正式提交：`plan --submit` → 回读 `SHZT=70 待本科生院审核` → `shjsjysq.do` 撤回
    （`SHZT=1 已撤回`）→ `scjssq.do` 删除；
  - 记录数 19 → 20 → 19，无残留；撤回参数 `JSJYSQLX=6` + `CQDQJY=2` 在教师端同样适用。

> 参照物：教师自研的油猴脚本「教室借用自动填写 v0.14.5」也按字典前后缀填表，
> 但它的 `BORROW_TYPE_CODE` 是 `01 教师教学、补课 / 09 团学活动 / 10 考试 / 11 讲座`，
> 与实测字典只有 `09` 对得上（其余为陈旧值）；其直连提交路径会用到这套码，需留意。
> 它判定重复的口径是「日期+校区+节次+教室」四项（`recordMatchEvidence`，
> 教室证据取用途 + `JASMC`，名字做了归一化）；`crb` 已按同一口径重写（2026-09-28）：
> 四项一致（节次区间有重叠也算）才判 `duplicate`，**时段重叠但教室不同不算重复**。

---

## 8. 教室视角：「这一间教室这天哪几节空」（2026-09-28，只读探针）

需求：`crb free` 只能「给时段 → 找教室」，没法反过来问「某间教室某天各节空不空」。
探针（教师号 `auth-teacher.json`，只读 POST）结论如下。

### 8.1 权威口径只有一条：`cxkxjs.do`，且区间是「每一节都空闲」

- **不传 `KSJC/JSJC`**：学校忽略节次过滤，返回该校区**全部教室**
  （仙林 223 间 / 鼓楼 169 间 / 苏州 48 间 / 浦口 22 间，共 462 间，与占用网格的
  教室总数一致）。`KXJC` 会给 `null-null节`、`KXSJ` 为空 —— 没有占用信息。
- **传区间**：结果是「**区间内每一节都空闲**」的教室，是**交集**不是并集。实测对拍：
  `KSJC=1,JSJC=2` 的集合 == `KSJC=1,JSJC=1` ∩ `KSJC=2,JSJC=2`（165 == 191 ∩ 165）。
  所以「逐节状态」只能靠**单节查询**（`KSJC=JSJC=p`）问出来。
- `querySetting`（datatable 高级查询）在这个接口上**不生效**：带 `JASMC include` 过滤
  与不带返回同一批行 —— 名字过滤得在本地做。

### 8.2 弃用：占用网格 `cxjsqk.do` 与单教室详情 `cxkxjsxq.do`

- `POST /jwapp/sys/kxjas/modules/kxjas/cxjsqk.do`（`XNXQDM/ZC/XQ/RQ`）
  返回 462 行 ×（`JASDM`/`JASLXDM`/`LC`/`SKZWS`/`JC1..JC20`）。看着像逐节网格，
  实际不是：同一行的 20 个 `JC` 列常常**内容全同**，且「`JC` 全空」的教室恰好等于
  「整天全空」的那 46 间 —— 只能当「这间教室这周有没有课」的粗粒度看板。
  按校区/楼的参数（`XXXQDM`/`JXLDM`）**过滤无效**，一次拉全校。**不用**。
- `POST /jwapp/sys/kxjas/modules/kxjas/cxkxjsxq.do`（必填 `XNXQDM/XQ/ZC/KSJC/JSJC/
  JASDM/ZYLXDM`，`ZYLXDM=01`）会返回 `JYXQ` 字符串（如
  `排课占用: 物理化学;课序号: 01; 占用节次: 3,4; 上课教师: 吕路,张炜铭;`），
  但对实测教室只回了 4 条占用里的 1 条（权威口径说 3-8 节占用，它只说 3,4）——
  **不完整**，不能用它当"这件事的答案"。

### 8.3 落地方式（`crb rooms` / `crb room`）

- 教室索引 = 8.1 的「不传节次」查询，一次拿全校区教室（名称/教学楼/容量/类型）。
- 单间详情 = 先按整段（默认 1-12）问一次：命中即「整天全空」（1 发，最常见的问法）；
  没命中再逐节问，最多 1 + 节次个数发。
- **批量（`crb day`）= 1 发教室清单 + 逐节各 1 发，一次拿整栋楼每间教室的空档**。
  请求数**与教室数无关**（苏州南雍楼 42 间与一层 11 间同价，实测 1.5s）；
  逐间调单间那条约 13 发/间 —— 一层楼要二十几秒。
- 名字匹配（`roomview.match_room`）：严格同名 → 宽松同名（`仙Ⅰ`/`仙一`/`仙I` 归一）→
  包含 → **末三位房号兜底**。前三条对上一间才敢直接答；末三位兜底**只给候选**，
  绝不替用户拍板（实测踩过：用户说「新教501」其实是鼓楼新教学楼的 `新教-501`，
  仙林那是 `仙Ⅱ-501`）。

### 8.4 顺带取回的教学楼字典（2026-09-28，`jxlcx.do`）

| 校区 | 教学楼（`JXLDM`） |
|---|---|
| 1 鼓楼 | 教学楼(1)、逸夫馆(8)、逸夫管理科学楼(10)、**新教学楼(20)**、费彝民楼(31)、南教(32) |
| 2 浦口 | 思源图书馆(30) |
| 3 仙林 | 仙I区(11)、仙II区(12)、逸夫楼A区(15)、逸夫楼B区(16)、逸夫楼C区(17)、图书馆(18)、环科楼(111) |
| 4 苏州 | 公共教学楼(S01)、南雍楼(S06) |

房间名写法：鼓楼 `教101` / `新教-101` / `馆1-102` / `费A-201` / `逸科楼-1203`，
仙林 `仙Ⅰ-101` / `逸B-506（翻转）` / `环科楼B-105`，苏州 `苏教A207` / `南雍-东101`，
浦口 `图东302/303`。名字会重（鼓楼有 2 间都叫「专用教室」）。
