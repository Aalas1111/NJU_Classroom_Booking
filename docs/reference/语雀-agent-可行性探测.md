# 语雀（Yuque）Agent 自动化 — 可行性探测记录

> 起草：2026-02-21 · 目标：搞清楚「agent 操作语雀」的上限在哪，为「语雀填表 → agent 整理 → crb 提交 → 退回通知」这条链路选型。
>
> 结论先行：**读的能力完全够用，写/评论/通知要靠 cookie 模式补，事件触发可以靠 webhook。**
> 官方 OpenAPI 的只读团队 token 已经实测跑通「列出知识库 → 列/搜文档 → 读正文 → 解表格」；
> 但要「建知识库、配 webhook、发评论 @人」这些动作，官方 API 覆盖不到，需要 cookie（网页内部接口）或人工一次性配置。
>
> 复现脚本：`scripts/yuque_probe.py`（**只读**，不做任何写操作）。

---

## 0. 探测对象与凭据

| 项 | 值 |
|---|---|
| 团队域名 | `https://nova.yuque.com`（团队 login = `ghxd00`，名称 `NOVA2026秋`） |
| 凭据 | 团队级访问令牌（`X-Auth-Token`），**只读** |
| token scope（服务端返回） | `group:read,repo:read,doc:read,statistic:read,private_search` |
| 团队规模 | 8 个知识库 / 约 1000+ 文档 / 成员接口可见 89 人 |
| 限流响应头 | `x-ratelimit-limit: 0`（未观测到 429；30 次连续请求全部 200） |

> ⚠️ token 不要写进仓库、不要贴进文档。实际使用放环境变量 `YUQUE_TOKEN`。
> 本文所有示例令牌一律打码。

实测命令：

```bash
export YUQUE_TOKEN=<团队令牌>
uv run python scripts/yuque_probe.py happy     # 心跳 + scope
uv run python scripts/yuque_probe.py repos
```

---

## 1. 路线 A：官方 OpenAPI（`/api/v2/*`，`X-Auth-Token`）

**已 100% 跑通，且不需要超级会员**——团队 token 直接可用（社区流传的「OpenAPI 要超级会员」指的是个人 token；团队/空间 token 走的是团队套餐）。

### 1.1 官方能力清单（来自官方 OpenAPI 2.0.1 规范，共 26 个操作）

| 分组 | 操作 | 实测 |
|---|---|---|
| user | `GET /hello`、`GET /user` | ✅ |
| search | `GET /search`（`q`/`type=doc,repo`/`page`/**`scope=group/slug`**） | ✅ |
| group | 成员列表、改成员角色、删成员 | ✅（列表） |
| doc | 列表、创建、详情、更新、删除、历史版本、目录(TOC) 读/写 | ✅（读）/ 写需写权限 |
| repo | 列表、创建、详情、更新、删除 | ✅（读）/ 写需写权限 |
| statistic | 团队汇总 / 成员 / 知识库 / 文档统计 | ✅ |
| notes | 小记列表 / 详情 | ✅ |
| yfm | 看板（需 `resource_id`） | 部分 |

### 1.2 实测样例

```bash
$ uv run python scripts/yuque_probe.py repos
79635809   pxeuoa   思维训练营        docs=414   ns=ghxd00/pxeuoa
79635820   mrge27   社团大型活动组织    docs=26
79639932   bd2rhd   新手的晋升之路      docs=234
79635817   sswiog   CAC有约          docs=7
79639944   cmkfi2   碎碎念           docs=43
79646253   swi096   通知公告区         docs=8
79635788   sqr5i3   认知课程-周五仙林&苏州 docs=278
82507684   hac37y   青年讲师团         docs=2
```

- **搜索**：`/api/v2/search?q=教室申请&type=doc&scope=ghxd00/mrge27` → `total=10`，
  返回 `title / summary / url / target{id,slug,book_id,...}`，可直接拿 `url` 反解出 `group/book_slug/doc_slug`。
- **列文档**：`/api/v2/repos/{book_id}/docs?limit=100&offset=N`，`limit>100` 报 422；
  每条含 `id/slug/title/type/updated_at/content_updated_at/word_count/comments_count`，**足以做增量检测**。
- **读文档**：`/api/v2/repos/{book_id|group/slug}/docs/{id|slug}?raw=1`，
  返回 `format`（`lake` / `markdown` / `lakesheet`）、`body`（正文 **Markdown**）、
  `body_draft`、`body_html`、`body_lake`、`tags`、`creator`、`book`。
  → **正文直接是 Markdown，agent 零成本消费**。路径参数同时接受数字 id 和 slug（都实测通过）。
- **目录**：`/api/v2/repos/{id}/toc` → 层级树（`uuid / parent_uuid / type=DOC|TITLE / title / url`），
  能还原「某个父文档下面挂了一堆子文档」的结构。
- **成员**：`/api/v2/groups/{login}/users` → `user_id → name` 映射（可用来把退回意见指名到人）。

### 1.3 ⭐ 表格（Sheet）也能读：lakesheet 解码

这是原本最担心的点——「社员填表」如果用的是语雀表格，官方 API 会给一整块二进制。
实测结论：**可以解**。

- 表格文档的 `format=lakesheet`，`body` 是 JSON：
  `{"format":"lakesheet","version":"3.5.5","larkJson":true,"sheet":"<latin-1 化的 zlib 流>",...}`
- `sheet` 字段前 4 字节是 `78 9c`（zlib 魔数），说明是 **压缩后的 JSON 被当成 latin-1 字符串塞进 JSON**。
- 解码链：`json.loads(body) → j["sheet"].encode("latin-1") → zlib.decompress → json.loads`
  → 得到 `sheets[i]["data"][行]["列"] = {"v": <单元格值>}`。
- 实测两张表都成功：`数据表` 101 行 × 多列、`最终产出` 101 行 × 13 列，
  表头/长文本/换行全部还原，可直接导出 CSV。

```bash
uv run python scripts/yuque_probe.py table --repo ghxd00/pxeuoa --slug xh6wvp1yb78ztg40 --csv
```

### 1.4 只读 token 做不到的（实测报错）

| 操作 | 结果 |
|---|---|
| 删除一个**不存在**的文档 | `401 {"message":"请给此 Token 添加 doc 权限"}` |

即：**任何写操作都会被 scope 拦截**。要写就必须换「写权限 token」或走 cookie 模式。
另外，官方 OpenAPI **完全没有评论接口**，也**没有站内通知/私信接口**。

---

## 2. 路线 B：Cookie + 网页内部接口（`/api/*`）

「官方 API 做不到的」基本都在这里。社区成熟项目（`yuque-cli` v3.5.0、`yuque-mcp`、
`yuque-cookie-mcp`）已在生产使用，端点清单如下：

| 能力 | 端点 |
|---|---|
| 身份 / 知识库 | `GET /api/mine`、`GET /api/mine/books`、`GET /api/mine/group_quick_links`、`GET /api/books/{id}/overview` |
| 文档列表 / 正文 | `GET /api/docs?book_id=`、`GET /api/docs/{slug}?book_id=&mode=markdown`（正文在 `sourcecode`）、`GET /{space}/{repo}/{slug}/markdown?plain=true` |
| 文档增删改 | `POST /api/docs`、`PUT /api/docs/{id}`、`DELETE /api/docs/{id}`、`PUT /api/docs/{id}/publish` |
| **评论 CRUD** | `GET/POST /api/comments`、`DELETE /api/comments/{id}`、`POST /api/comments/finish` |
| **@ 人（可触发通知）** | `GET /api/users/complete` 搜人 → 正文插 mention 卡片 |
| 审核/审批 | `POST /api/reviews`、`POST /api/reviews/{id}/approval`、`/cancel`、`GET /api/getReviewsByTarget` |
| 附件 | `POST /api/upload/attach` |

写操作四要素（踩坑记录，社区实测）：

1. Cookie 里必须有 `_yuque_session`（登录态）**和** `yuque_ctoken`（CSRF）；
2. 请求头带 `X-CSRF-Token: <yuque_ctoken>`；
3. 请求头带 `X-Requested-With: XMLHttpRequest`，body 必须是 **JSON**（不是表单）；
4. 带正确的 `Referer`（`https://<host>/<space>/<repo>`）。

风险：这些是**非公开接口**，语雀改版可能需要适配；cookie 有效期社区经验约 2 周。

---

## 3. 路线 C：Playwright 浏览器自动化（已实测）

| 项 | 结果 |
|---|---|
| 系统 Edge + Playwright headless | ✅ 能打开 `https://nova.yuque.com/login`，标题 `登录 · NOVA` |
| 未登录时的 cookie | ✅ 下发 `_yuque_session` / `yuque_ctoken` / `acw_tc` / `aliyungf_tc` 等 8 个 |
| `context.storage_state()` 持久化 | ✅ 正常写出（cookies + origins） |
| 登录方式 | 手机验证码 / 密码登录 / 其他登录方式（页面 JS 渲染） |

结论：**「第一次弹有头浏览器让用户自己登录，之后复用登录态」这条 crb 走过的路，语雀同样走得通**。
浏览器路线的上限最低（有什么 DOM 就能点什么）也最稳，适合作为内部接口失效时的兜底；
但慢、脆，不建议当主路径。备选：让用户直接粘贴 cookie 串（`--cookie`），零浏览器依赖。

---

## 4. 路线 D：Webhook 事件驱动（官方功能）

- 入口：`知识库 → 设置 → 开发者 / 消息推送`（团队级在 `空间管理 → 设置 → 消息推送`）。
- 可订阅事件：**发布文档 / 更新文档 / 删除文档 / 新增评论 / 更新评论 / 删除评论 / 回复增删改**。
- 推送方式是 **HTTP POST + JSON**，`data` 里直接带 `body`（正文 Markdown）、`title`、`book`、
  `actor_id`、`action_type`、`path` 等——**触发即拿全文，不用再回调一次 API**。
- 约束：需要**公网可达的 URL**；接收端要快速响应（社区案例给了 3s 超时）。
- 语雀自带「测试」按钮，配好后可立刻验证。

→ 这正好解决「常驻 bot 检测新文档」的触发问题：**不必轮询**，语雀主动推。
代价是要有一个公网 endpoint（serverless 函数 / 内网穿透），仍然属于「要常驻一个东西」。

---

## 5. 能力上限总表

| 需求 | OpenAPI（read token） | OpenAPI（write token） | Cookie 内部接口 | Playwright |
|---|---|---|---|---|
| 列知识库 / 目录 / 文档列表 | ✅ | ✅ | ✅ | ✅ |
| 全文搜索（可限定知识库） | ✅ | ✅ | 走页面 | ✅ |
| 读文档正文（Markdown） | ✅ | ✅ | ✅ | ✅ |
| **读表格（Sheet）** | ✅（本仓库提供解码器） | ✅ | ⚠️（页面渲染） | ⚠️ |
| 读数据表（DataTable）/ 多维表格 | ❓未验证（无样本，官方无端点） | ❓ | ❓ | ✅（DOM） |
| 建 / 改 / 删文档 | ❌ 401 | ✅ | ✅ | ✅ |
| 建知识库 / 改目录 | ❌ | ✅ | ✅ | ✅ |
| **发评论 / 回复 / @人** | ❌ 无接口 | ❌ 无接口 | ✅ | ✅ |
| 审核（reviews） | ❌ | ❌ | ✅ | ✅ |
| 站内私信 / 群通知 | ❌ 无接口 | ❌ | ❌ | ❌ |
| 事件订阅（新文档触发） | — | — | — | ✅ webhook（需人工配置） |
| 成员 id → 姓名 | ✅ | ✅ | ✅ | ✅ |
| 统计（阅读/写作量） | ✅ | ✅ | ✅ | — |

**上限一句话**：语雀能给到「读全文 + 读表格 + 发评论 @人 + 文档 CRUD + 审核」，
但**没有站内通知/私信**——所有「通知社员」最终只能落在「评论 + @」或「CAC 人工转达」。

---

## 6. 对既定流程的映射建议

### 6.1 社员怎么「填表」

上学期「填表」的载体在团队里已经找不到表格证据（全团队仅 2 个 Sheet，都在思维训练营、
是听感调研数据），现存模式是 **父文档下挂每人一份子文档**（见 `课表汇总统计（申请已结束）`
→ `廖宇强/开发、构思`；`教室借用申请任务（申请已结束）` → `王恩成`）。

两条都可用的方案：

| 方案 | 优点 | 缺点 |
|---|---|---|
| **A. 一个 Sheet，每人一行** | 结构化、一眼看全、天然适合批量 | 需要解码 lakesheet；不能按行加评论 @人 |
| **B. 父文档 + 每人一份子文档**（上学期同款） | 每份文档可单独评论/退回/回复；模板固定 | 要按 TOC 聚合；条数多时噪声大 |

建议：**B 为主**（退回通知能精确落到个人），如果只求快就用 A（解码器已就绪）。

### 6.2 agent 整理 + 提交

- 取数：`yq` 读文档/表格 → 归一成 `{活动名, 日期, 节次, 人数, 意向教学楼, 申请人}`。
- 提交：交给已有的 `crb plan --file plan.json --save` / `--submit`。
- 去重/冲突：`crb` 已自带跨批次防重合，不需要语雀侧重复实现。

### 6.3 退回与通知

三条可选（按推荐度排序）：

1. **评论 + @当事人**（cookie 模式）：直接在子文档/表格下留「退回意见」，@ 对方会触发语雀通知。
   精确、可追溯、留痕，不依赖 QQ 群。
2. **汇总给 CAC**：用 `members` 接口把 `user_id → 姓名` 映射好，agent 输出「待修改名单 + 意见」，
   CAC 统一转达。实现最省事，但 CAC 仍要花时间。
3. **webhook + 常驻服务**：真正的「CAC 当甩手掌柜」形态，但需要一个公网 endpoint，
   且设计上必须处理「没填完就提交」的误判（例如教室留空）。

### 6.4 关于「误判半成品」

用户提的坑很真实。建议**在文档模板里加一个显式状态开关**，例如正文首行写：

```
状态：草稿 | 待提交
```

agent 只处理 `待提交` 的；`草稿` 一律忽略。这比猜「教室留空是不是默认值」可靠得多，
也不需要常驻监控。

---

## 7. 风险与待确认

1. **只读 token 不能建知识库 / 配 webhook**：这两步需要老师或 CAC 用管理员身份做一次
   （或者提供写权限 token）。
2. **写权限来源**：要么让老师签一个带 `doc:write` 的 token，要么走 cookie 模式（2 周要重登）。
   建议 CLI 设计成「能力按 scope 降级」：读能力用 token，评论/写能力没权限就明确报错并提示登录。
3. **未发布草稿的可见性**：语雀未发布的文档对他人默认不可见，可能读不到——需要实测一次
   （「状态：待提交」的机制可以规避一半）。
4. **搜索索引延迟**：新发布文档未必立刻可搜。**做增量检测请用「列文档 + 比 `updated_at`」**，
   不要依赖 search。
5. **数据表(DataTable)**：官方 API 无端点、团队里也没有样本，没验证；如果最后决定用「数据表」
   而不是「表格」，需要补测。
6. **内部接口稳定性**：cookie 路线属非公开接口，语雀改版会失效，需要留 Playwright 兜底。
7. **限流**：`x-ratelimit-limit: 0` 语义未知；批量拉 414 个文档时未见 429。真要全量拉取建议限速。
8. **表格单元格格式**：`{"v": ...}` 之外还有 `s`(样式) `t`(类型) / 公式 / 合并单元格，
   简单文本已够用，复杂格式要另做适配。

---

## 8. 结论与下一步

**可行性成立。** 而且比预期好：一份**只读** token 就能覆盖「读知识库 + 搜文档 + 读正文 + 读表格」，
这恰好是「agent 读社员填的表」的全部需求。

推荐的 CLI 形态（对应「login 可选 apikey / 无 apikey」的设想）：

```
yq login --token <团队令牌>     # 路线 A：只读，零浏览器，最省事
yq login                        # 路线 B：弹有头浏览器登录，抓 cookie，解锁评论/写
yq doctor                       # 报告当前模式 + scope + 能力矩阵
yq repos / docs / search / doc / table / toc / members
yq comment add / yq doc create  # 仅 cookie/写权限模式可用
```

下一步要做的事：

1. [ ] 让老师/CAC 在语雀建一个「教室申请」知识库（或确认用哪个），并定好文档模板。
2. [ ] 定「填表载体」：Sheet 一行一人，还是父文档 + 每人子文档。
3. [ ] 若要做自动退回通知：需要 cookie 模式，或至少确认评论功能由谁执行。
4. [ ] 把 `scripts/yuque_probe.py` 升级成正式的 `yq` CLI + `SKILL.md`。
5. [ ] （可选）验证数据表(DataTable)与未发布草稿的可见性。

---

## 9. 复现

```bash
git clone https://github.com/Aalas1111/NJU_Classroom_Booking.git
cd NJU_Classroom_Booking
export YUQUE_TOKEN=<团队令牌>

uv run python scripts/yuque_probe.py happy                 # 心跳 + scope
uv run python scripts/yuque_probe.py repos                 # 8 个知识库
uv run python scripts/yuque_probe.py toc --repo ghxd00/mrge27
uv run python scripts/yuque_probe.py search 教室申请 --scope ghxd00/mrge27
uv run python scripts/yuque_probe.py docs  --repo 79635820 --limit 10
uv run python scripts/yuque_probe.py doc   --repo ghxd00/mrge27 --slug bbf1n662v36gd85q
uv run python scripts/yuque_probe.py table --repo ghxd00/pxeuoa --slug xh6wvp1yb78ztg40 --csv
uv run python scripts/yuque_probe.py members
```

脚本只发 GET，不会修改任何语雀内容。
