# 南京大学教室借用 Agent — 可行性探测记录

> 结论先行：**方案可行**。登录态可持久化；空闲教室查询和教室借用申请均为可直连的 `.do` 接口；保存草稿已通过真实 POST 验证成功（未正式提交）。

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
pagePath  /modules/kxjas.do  +  action=cxjsqk
真实 URL  /jwapp/sys/kxjas/modules/kxjas/cxjsqk.do
```

实测成功的请求：
```
POST /jwapp/sys/kxjas/modules/kxjas/cxjsqk.do
Content-Type: application/x-www-form-urlencoded

pageSize=10
pageNumber=1
XNXQDM=2026-2027-1
ZC=3
XQ=4
RQ=2026-09-10
querySetting=[{"name":"XXXQDM","value":"3","builder":"equal","linkOpt":"AND"},{"name":"JXLDM","value":"11","builder":"include","linkOpt":"AND"}]
*order=+LC,+JASMC
```
返回 `{"datas":{"cxjsqk":{"totalSize":73,...}}}`，含 `JASMC/JASDM/JXLDM/LC/SKZWS/KSZWS/JASLXDM/JC1..JC20` 等字段。

- `/modules/kxjas/cxjsqk.do` 是**真实查询接口**（不是 `/modules/kxjas.do?action=...`）。
- datatable 参数：`pageSize`、`pageNumber`（前端从 0 开始，发请求时 +1）、`querySetting`。
- `querySetting` 是数组 JSON 字符串，元素格式：`{"name":<字段名>,"value":<值>,"builder":<操作符>,"linkOpt":"AND"}`。
- 操作符（builder）只使用模型里合法的值：字符串用 `equal`/`include`；数值用 `equal`。**不要用 `ge`/`gt`**（会报 `Not found object [ge]`）。
- 搜索模型字段（`WIS_EMAP_SERV.getModel('/modules/kxjas.do','cxjsqk','search')`）里可见字段（简化）：
  - `JASMC` 教室名称、`JASDM` 教室代码（hidden）、`JASLXDM` 教室类型（select）、`JXLDM` 教学楼、`XXXQDM` 学校校区、`LC` 楼层、`SKZWS` 上课座位数、`KSZWS` 考试座位数、`JC1..JC20` 第1~20节。

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
| `/jwapp/sys/jsjy/modules/jsjysq/shjsjysq.do` | 审核 |
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

### 删除接口确认
- 前端行渲染（`jsjysq.js` 的 `cellsRenderer`）：
  - `SHZT == '00'`（草稿）→ 只显示 `提交 | 编辑`，**没有“删除”按钮**。
  - `SHZT == '1'`（撤回状态）→ 显示 `撤回 | 删除 | 提交 | 编辑`，其中 **“删除”按钮**：`data-x-wid = rowData.SQBH`、`data-action="删除"`。
  - `actionDelete` 实现：`bs.deleteJssq({param:'[{SQBH: ' + sqbh + '}]'})`，对应接口 **`POST /jwapp/sys/jsjy/modules/jsjysq/scjssq.do`**，body `param=[{SQBH:<申请编号>}]`。
- **实测**：对草稿也直接调了 `scjssq.do`，返回 `msg:"操作成功"`，重新加载 jsjy 列表后 `totalSize:0`，**草稿确实被删除**。（此前“刷不出来”是页面刷新/缓存时机问题。）

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
5. **勿真正提交**：测试一律 `TYPE='save'`；正式提交前需人工审核用途、时间等。
6. **datatable 请求格式**：所有列表接口都要用 `pagePath` + `action` 拼成 `/modules/xxx/action.do`，且带 `pageSize/pageNumber`（pageNumber 从 0 开始+1）和 `querySetting`。

---

## 6. 已保存的本地文件
- 登录态快照：`D:\Coding\CursorProjects\pi_workspace\nju-auth-state.json`
- Playwright 持久化 profile：`D:\Coding\CursorProjects\pi_workspace\.nju-playwright-profile`
- 截图（登录页）：`D:\Coding\CursorProjects\pi_workspace\nju-login.png`
