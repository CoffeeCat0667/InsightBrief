# Changelog

本仓库所有值得记录的变更均按时间倒序记录于此。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/),版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 新增

- **管理面板**:
  - 顶栏在明/暗切换旁新增“管理面板”按钮，仅管理员可见；非管理员不显示。
  - 用户管理：查看全部注册用户，可修改任意用户的用户名/密码/角色（admin/user），并阻止移除最后一个管理员。
  - 注册入口开关：管理员可开/关公开注册；关闭后注册接口返回 403，前端隐藏注册选项卡。
  - LLM 配置：前端可修改 `base_url/api_key/model_id`；保存前先连通性检查（最小 chat 请求），可用才同时写回 `Config/LLM.json` 与 PG `system_settings` 并清缓存，不可用则不改写并返回错误。
  - 非管理员可见选项卡：管理员可配置非管理员可见的文章/简报/抓取任务/新闻源；审计/管理面板始终对非管理员隐藏；登录及 `/me` 返回 `visible_tabs`，前端按此过滤导航。
  - 新增 `/api/admin/*` 与 `/api/auth/registration` 端点（admin 写操作审计，LLM 审计不含 api_key，用户审计不含密码）。

### 修复

- **鉴权、审计与任务权限加固**:
  - 抓取/简报任务取消端点改为 admin-only，普通用户不再能中断管理员任务；终态任务的无效取消不再写入噪音审计。
  - 登录失败按客户端 IP 执行 Redis 共享滑动窗口限流（Redis 不可用时进程内降级），达到阈值返回 429 与 `Retry-After`；不存在用户仍执行 dummy bcrypt 校验，减少用户名计时枚举。
  - bcrypt 密码改为拒绝超过 72 个 UTF-8 字节的输入，取消静默截断；空库初始化必须显式设置 `ADMIN_PASSWORD`，不再创建默认密码管理员。
  - 认证审计 detail 不再写 username/email；迁移会清洗既有认证审计 PII，并为 `audit_logs.action` 新建索引。
  - 仅当 socket 对端在 `trusted_proxy_ips` 配置中时才采信 `X-Forwarded-For`，防止直连客户端伪造审计来源 IP。
  - 注册唯一键并发冲突改为 409；worker submit 失败时任务落为 failed，避免 pending 残留与成功创建审计不一致。
- **栏目页广告过滤稳健化**: 广告识别覆盖链接自身及祖先的 class，采用边界匹配避免 `advanced` 等正常 class 被误伤；先完整收集广告 URL 再过滤候选，消除同 URL 出现顺序造成的漏网。

### 新增

- **抓取任务国内源新闻数最大占比**:
  - 抓取页新增 `0–100%` 输入框，默认 100%（不限制）；任务历史与实时面板展示配置及实时国内占比。
  - 后端以 `Source.is_domestic` 为唯一分类依据，先抓外源，按成功新闻数（新增 + 已存在）计算国内共享硬配额：`floor(外源成功数 × 比例 / (100 - 比例))`；配额耗尽的国内源记为 `skipped` 并通过 SSE 推送。
  - 任务持久化 `domestic_max_ratio`，新增 Alembic 迁移 `g8b9c0d1e2f3`；比例小于 100% 时，纯国内源任务返回 422。

- **前端单页应用 `Client/`(原生 JS, 用户批准重启前端实现)**:
  - 零构建零依赖(ES Modules + hash 路由),FastAPI 静态挂载至 `/`(main.py 一行, 注册于 API 路由之后, 不遮挡 `/api` 与 `/docs`);启动服务后直接访问 `http://127.0.0.1:8000/`
  - 7 视图: 登录/注册、文章(搜索/分类筛选/详情抽屉: 摘要/全文翻译/内容片段)、抓取任务(源多选 + max_items + **SSE 实时进度**: 进度条/runs 徽章链/事件日志/取消)、简报(分类/源/时间窗 + **SSE 阶段进度** + 存档卡片阅读)、新闻源管理(admin CRUD + 启用开关 + config 三类模板)、审计日志(admin 筛选 + detail JSON 展开)、平台(26 卡片)
  - **SSE 客户端自研**: fetch + ReadableStream 手写解析(原生 EventSource 无法携带 Authorization 头, 规避 token 进 URL/日志);兼容心跳 `: ping`、多行 data、终态关流
  - 视觉: 双主题跟随系统 `prefers-color-scheme`(顶栏可手动覆盖 auto/light/dark)、CSS 变量主题、状态徽章语义色、卡片悬浮动效、skeleton 加载、toast、响应式(移动端侧栏抽屉)
  - 验证: node --check 11 个 JS 文件 + 服务重启后静态/API/docs 冒烟 + 鉴权/权限(401/403)回归全绿;测试用户已清理
  - 前端走查全链通过(playwright): 登录→7 导航、抓取 SSE 实时进度(100%/runs 徽章/历史刷新/幂等)、文章列表/详情抽屉/搜索、简报 SSE completed 4/4、源管理 CRUD(API 级)、审计筛选 + detail JSON、平台 26 卡片、主题三态切换、无 JS 控制台错误;测试数据已清理

### 修复

- **简报任务 failed: 文章脱离 Session 后懒加载 `contents` 崩溃**(`Parent instance <Article ...> is not bound to a Session`): `Report/processor.py::_load_articles` 查询补 `joinedload(Article.contents)` 预加载 + `.unique()` 去重 — session 关闭后 `_article_text` 访问全文片段不再抛 DetachedInstanceError; 摘要型源(article.content 为空)此前必触发, 现实测简报 completed 4/4
- **前端登录 422 "请求参数校验失败"**: 登录/注册两 tab 同名 `username`/`password` 控件使 `form.username` 返回 RadioNodeList(无 `.value`)→ 请求体字段为空; auth.js 改按 tab 选择器取值, sources.js 同步规避 `form.name` 固有属性陷阱, api.js 过滤 undefined/null 表单值
- **前端 SSE 字段错读**: crawl.js `run_finished` 原读不存在的 `stats.ok`, 改读 `stats.inserted/existed/failed`; crawl/brief 两视图终态事件后自动刷新历史/存档列表
- **分页计数 "第 1 / NaN 页"**: `Page.pages` 原为普通 `@property`, Pydantic v2 序列化默认不含 → 响应缺 `pages` 字段; 改 `@computed_field`(schemas/common.py), 全部分页端点一次性修复, 前端 `第 ${page} / ${pages} 页 · 共 ${total} 条` 恢复正确
- **抓取页实时面板改进**: run 徽章链改本地状态驱动(run_started 立即显示"xx 抓取中", run_finished 即更新计数, 不再等 task_update); 历史行 source_ids 为空(全源任务)显示"全部源"而非"源 0 个"; task_update 的 stage 输出到事件日志 — 全量 27 源任务首源完成前不再"看起来卡死"(首源耗时可达 10 分钟+)
- **抓取页双进度条 + 最新动作行**(0e1a911 后续批次):
  - 进度条拆二: 「当前源文章进度」(done/total, run_progress 事件每篇更新)与「源进度」(已完成源数/总数, task_update 更新)
  - 后端: `ingest.insert_articles_from_links/crawl_and_ingest` 新增 `on_progress(processed, total)` 回调(每篇处理含失败/跳过均触发), `task_manager._execute` 传回调发布 `run_progress` 事件(载荷含 source_id/index/total_sources/done/total)
  - 实时面板新增最新动作行(`.now-line`): "正在抓取 搜狐新闻: 12/25 篇 (第 2/27 源)" 随事件实时刷新
  - **移除「平台」选项卡**: 导航 7 视图 → 6 视图, `Client/js/views/platforms.js` 删除(后端 /api/platforms 保留)
- **文章详情临时翻译按钮**(外文文章): 「查看原文」旁新增「翻译」— 点击调用新端点 `POST /api/translate`(登录即可, title+text 分开翻译, 结果不落库), 标题与正文区切换为中文译文, 按钮变「显示原文」可来回切换; **关闭重开同一篇文章始终显示原文**(翻译纯临时, PG 仍存原始外文); 失败判定: Translator 降级返回原文时以 `is_chinese` 判失败返回 502; 中文文章不显示按钮
- **审计日志「收起」按钮失效**: 根因 `insertAdjacentHTML("afterend")` 在 `<td>` 内 button 后插入 `<tr>` — tr 不能作为 td 子节点, 浏览器不将其变为按钮兄弟 → 收起判断永远失败, 每次点击反而再插入一行; 修复: 插入到按钮所在 `<tr>` 之后并基于行检测展开态; 实测 展开 21 行 → 收起 20 行 → 连点不再堆积

### 其他

- **决策 (2026-08-18)**: **LLM api_key 管理不做改造, 保持现状** — `Config/LLM.json` 明文 + 可选 `LLM_API_KEY` env 覆盖(启动同步生效); 本地单机可接受, 生产部署时再评估密钥方案(记录于 DECISIONS §15-9)

### 修复

- **栏目页发现误提取推广横幅**(81.cn 中国军网): `discovery._extract_column` 由整 HTML 裸正则改为 **DOM 解析 (parsel)** — 只取 `<a href>` 精确链接,跳过广告/推广容器(`banner`/`ad`/`ads`/`advert`/`adbox`/`promo`/`tui`/`gg` 类名),且广告容器内出现过的 URL 记入全局跳过集合(同横幅多处引用一并排除);`//` 前缀补 `https:`,相对路径经 `urljoin` 兼容,保留 link_pattern `?`/`#` 截断语义。回归:6 个 column 源实测全绿, jfjb 首条由横幅变真实新闻

### 新增

- **audit_logs 写入落地**(关键操作留痕):
  - `Services/audit_logs/` 独立包: `write_audit`(独立会话提交 + detail 深拷贝; 任何异常只告警返回 False, **审计绝不炸主业务**) + `client_ip`(client.host 优先, X-Forwarded-For 首段兜底)
  - 13 个调用点: `user.register`/`user.register_failed`/`user.login`/`user.login_failed`(含禁用 403)/`source.create`/`source.update`/`source.delete`/`source.disable`(软禁用)/`crawl_task.create`/`crawl_task.cancel`/`brief_task.create`/`brief_task.cancel`; action 命名 `{object}.{verb}`(失败加 `_failed`), detail 记录变更内容 + 客户端 IP
  - `GET /api/audit-logs`(admin-only): action/user_id 筛选 + 分页, 按时间倒序; 无 token 401 / 非 admin 403
  - 验证: import 冒烟 + e2e 20/20 全绿(含软禁用分支/401/403/筛选/12 种 action 全集/ip 采集)+ psql 核对 JSONB 落库 + write_audit 异常容错冒烟; 测试数据已清理

### 回滚

- **前端已回滚** (revert eec51a9, 撤销 eec5241): 单页前端(登录/文章浏览/抓取触发+SSE/简报面板)整块撤销 — **用户拍板不做前端**;Web 后端功能继续经 REST API + `/docs` 使用。`Services/App/static/` 已删除, 版本字段回到 0.1.2。

### 修复

- `bfb01c5` **code review 修复批次**:
  - SSE 按任务类型拆独立端点: `/api/brief-tasks/{id}/events` 专属 brief, `/api/tasks/{id}/events` 恢复仅 crawl, 消除两表 id 各自自增的歧义(错表互查 404)
  - `parse_classify` 对 malformed idx(如 `"0.0"`)容错跳过, 缺项判定走二分拆批/单篇降级, 不再 internal_error
  - LLM 配置接线: 删除 LLM.json 顶层冗余 `batch_size`; `operators.classify.max_batch` 生效; summarize/translate_title/compose_overview 三个 `max_tokens` 透传生效; `BriefTaskCreate.max_items`(1-500)可用
  - `brief_items.source_name` 写真名(Source id→name 映射); `BriefItemRead.meta` 暴露单篇降级标记
  - 综述提示词中文化("其他" 不再传英文 other); source_ids 空字符串 422 validation_error(crawl+brief)
  - `sync_llm_config` 支持 `LLM_API_KEY` 环境变量覆盖 api_key, `.env.example` 补文档

### 变更

- `84cc01e` + `e23577b` **timeout 唯一来源 = 平台级 `fetch_timeout`**:
  - 删除 `Config/Core.json` 全部全局 timeout(`timeout` / `generic_timeout` / `request_timeout`), 只留 attempts/wait_seconds/generic_impersonate
  - 25 平台条目全配 `fetch_timeout`, `Tools/measure_fetch_timeout.py` 全量实测写回(本机值: 慢平台 bbc/guardian/nytimes/aljazeera/dw/forbes 35 / businessinsider 40 / 其余 20); `Core/base.py` 常量 30 仅兜底 CLI 直接实例化/未知平台路径
  - `Core/base.py`: 爬虫 `__init__` 增加 `platform_id` 参数, `build_fetch_request` 以平台级值为唯一超时; netease/sohu/bbc/cnn 4 个自写 `__init__` 平台同步转发(防 TypeError); `Core/fetchers.py` `FetchRequest.timeout` 默认改常量 30(仅非爬虫直连路径); `Core/generic.py` 删除 generic_timeout 硬覆盖逻辑

### 工具

- `Tools/measure_fetch_timeout.py`(e23577b): 自动化测速写回工具 — 逐平台真实抓取计时, 建议值 `max(20, ceil(t*1.5/5)*5)` 自动写回 Clawer.json; TTY 下进度动画(序号/抓取中已用时/即时结果行), 非 TTY 自动干净输出; 支持 `--dry-run` 预览与 `--platform` 单/多平台筛选

### 其他

- `6e172cf` **CLI 主程序入口迁移**: `main.py` git mv 至 `Services/CLI/main.py`(自插根路径, 支持 `python -m Services.CLI.main` 与 `python Services/CLI/main.py` 双调用); **CLI 定位仅测试使用, 不再维护新功能**

## [Ver0.1.5] - 2026-08-16

**简报生成系统**(commit 6bacfb4): LLM 配置落库 + 算子编排 + 端点/迁移 + kind 命名空间。

### 新增

- `Config/LLM.json` + `llm_config()`: LLM 唯一真相源(base_url/api_key/model_id, 换厂商只改 json; timeout/retry/quarantine_consecutive/concurrency); `sync_llm_config` 幂等 upsert `system_settings` key="llm"
- `Report/` 包: `llm/`(Provider ABC + ChatMessage + 错误两分 `LLMServiceError`/`ArticleContentError` + OpenAI V1 统一客户端: requests + 指数退避, 403 风控不重试)、`prompts.py`(分类/摘要/标题/综述 4 组 prompt + extract_json)、`operators.py`(4 算子; 分类二分拆批递归; ArticleDegraded/OverviewDegraded 信号)、`processor.py`(BriefProcessor 编排: 分类→摘要/标题并发→综述→落库+文章回写)
- 端点: `POST/GET /api/brief-tasks` + `/{id}` + `/{id}/cancel` + `GET /api/briefs(/{id})`; 事件走 kind 命名空间隔离的 SSE
- `alembic` 0003: `brief_items.meta` + `brief_tasks.stats` JSONB(已执行)

### 语义(用户拍板)

- 错误两分: 403 内容风控 = 单篇降级不计全挂; LLMServiceError(超时/连接/5xx/429) = 计入
- 连续失败 ≥ quarantine_consecutive(3) → 立即 failed + upstream_error; 收尾全服务级降级(success=0 且全部 service 类) → failed 兜底
- 降级路径: title_cn=普通翻译 + 非中文全文翻译写 articles.translated_content + summary=None + meta={degraded: type}
- 取消 = 阶段间生效, 半成品不落库(原子); 全挂 failed = 残料保留(与取消区分)
- 分类输出中文 → CATEGORY_CN_EN 归一英文枚举(politics/economy/culture/technology/other)

### 验证

- 真实 key 端到端 10 篇(中英源混合): completed, 4 份 brief 综述质量合格, 文章回写全绿
- SSE 实时 + 终态重放 6 事件纯 brief 序列, crawl/brief 不串流
- 降级实测(不可达 base_url): 分类降级继续 → 摘要连续 3 次失败 → **failed upstream_error**
- 取消实测: running 中 cancel → brief_cancelled, briefs 0 份

## [Ver0.1.4] - 2026-08-16

**抓取任务运行时 + SSE 进度通道**(commit 3de86c4 + c994eba + a26cd6c)。

### 新增

- `task_manager.py`: ThreadPoolExecutor(4) 并发执行; 事件总线(内存尾缓冲 + Redis 链/快照 + asyncio 订阅队列); `recover_stale_tasks` 启动恢复孤儿任务; `request_cancel`(源间生效)
- 端点: `POST /api/crawl-tasks`(409 幂等, 源集合重叠即拒; source_ids 省略 = 全部启用源)、列表/详情(含 runs)、`.../{id}/cancel`、`GET /api/tasks/{id}/events`(SSE)
- `alembic` 0002: `crawl_tasks.max_items`(server_default 30, 已执行)
- 修复: CLI 菜单空回归(懒加载原地更新 + ensure_sources_loaded); 并发 P1-P4(重复入库/任务状态/清理)修复

### 关键设计

- SSE 唯一进度通道: 先重放 Redis 历史事件再订阅实时; 15s 心跳 `: ping`; 终态事件发出即关流
- 事件序列: `task_update → run_started → run_finished → task_update(每源) → task_completed/failed/cancelled`
- cancel 语义: 已在跑的源跑完即停, 未开始的源跳过, 最终 cancelled
- 注意: 源级抓取可能很慢(bbc 2 篇 ~90s), SSE 客户端超时须 > 单源最坏耗时

### 验证

- 实时 SSE 与终态重放事件齐全; 同源重复创建 409; cancel → cancelled; 列表 status 过滤/404/401 全绿
- 孤儿任务恢复: 杀进程重启后滞留 running 任务被标记 failed
- 全仓 import 冒烟 0 失败

## [Ver0.1.3] - 2026-08-16

**Web 后端化: FastAPI 骨架 + 登录鉴权 + SQLAlchemy 接线**(commit 0e17129)。

### 新增

- `Services/discovery.py` 源注册表改 DB 懒加载(只取 enabled=True, 工厂逻辑保留); import 不连库
- `Services/App/ingest.py`: make_external_id(SHA256(url[:512])[:16])、upsert_article(按 source+external 幂等)、crawl_and_ingest
- `Services/App/security.py`: bcrypt + PyJWT(HS256, 24h) + get_current_user + require_admin + seed_all(幂等角色/初始 admin)
- 路由: auth(register/login/me)、sources(CRUD, admin 写)、articles(列表/搜索/详情 joinedload)、platforms(聚合 Clawer 目录 26 平台)
- `main.py`: FastAPI 入口 + lifespan 引导(建表/源同步/种子) + CORS + 统一错误包装; requirements 增补 fastapi/uvicorn/sqlalchemy/alembic/psycopg/redis/bcrypt/PyJWT

### 验证

- HTTP 全链路 15 项全绿(health/401/403/409/404/422/搜索/删除等)
- 真实抓取落库: bbc_rss 2 篇(42 片段+2 媒体)、washingtonpost 摘要型 2 篇、二跑幂等 existed=2
- 全仓 import 冒烟 0 失败

## [Ver0.1.2] - 2026-08-16

**Web 后端化: 数据模型 + API 契约**(commit 5c0b114)。

### 新增

- `Services/App/models/`: 13 张表 SQLAlchemy 2.0 ORM(sources/crawl_tasks/crawl_runs/articles/article_contents/article_media/brief_tasks/briefs/brief_items/users/roles/system_settings/audit_logs), `UNIQUE(source_id, external_id)` + url 唯一, JSONB 配置列
- `Services/App/schemas/`: 11 端点 API 契约(统一 `ApiResponse{success,data,error}` + ErrorCode 9 枚举 + `Page[T]` 分页)
- `Services/App/sync.py`: 配置→DB 同步(插/改/软禁用三分支, 幂等); `Config/db.json` + `db_config()`(PG/Redis DSN, env 覆盖)
- `alembic` 0001: 13 表全量迁移, 已在真实 PG 执行成功

## [Ver0.1.1] - 2026-08-15

配置抽取重构:硬编码配置收归 `Config/` 目录,全平台全源改由唯一加载器供给。

### 变更

- **配置数据与加载器统一入 `Config/`**:`Core.json`(代理/UA/超时重试/路径/playwright/generic 阈值)、`Clawer.json`(25 平台 base_url/xpath/UA/fetch 策略覆盖)、`Services.json`(27 源注册表 + translator 参数)、`config.py`(唯一加载器:lru_cache、必填校验、`CRAWL_PROXY` 等 env 覆盖)
- 加载器从 `Core/config.py` 迁至 `Config/config.py`,全仓配置引用统一为 `from Config.config import ...`,不再从 `Core.fetchers` re-export
- 25 个平台爬虫类属性(含 4 个自定义平台的 UA 与 `get_base_url`)改由 `platform_config(pid)` 注入
- `Services/discovery.py` 源注册表(platform_patterns/link_patterns/sources/domestic_source_ids)全部改由配置构建;CNN 首页内嵌 JSON 提取保留为代码 custom 源
- `Services/translator.py` 翻译 provider/source/target/chunk_size 配置化

### 修复

- Ars Technica 直连返回 HTTP 202 反爬质询页时不再直接失败:非 200 状态码同样触发一次代理回退(代理可取得完整正文)

### 验证

- 全量 26 平台真实抓取 26/26 通过(合计 235s);25 平台 import/属性一致性校验通过
- 端点:新华网 116 链接、guardian RSS 45 条、bbc_rss 33 条(www.bbc.co.uk→www.bbc.com 替换生效)、arstechnica 202→代理回退成功

## [Ver0.1.0] - 2026-08-15

首个可运行版本发布。

### 新增

- **CLI 主程序入口** (`main.py`):分类菜单选择媒体 → 自动发现最新新闻 → 抓取展示;中文直显,外文自动翻译为简体中文
- **通用核心** (`Core/`):
  - `models.py`:NewsItem / NewsMetaInfo / ContentItem 等 pydantic 数据模型
  - `fetchers.py`:`CurlCffiFetcher`(Chrome TLS 指纹抓取,直连失败自动代理重试)、`PlaywrightFetcher`(CSR 渲染站)、`CRAWL_PROXY` 代理配置
  - `base.py`:`BaseNewsCrawler` 抽象基类(重试/校验/JSON 持久化管线)
  - `generic.py`:`GenericArticleCrawler` 通用解析(JSON-LD → og:meta → 容器探测 → 块提取),支持 `content_xpath` / `block_xpath` 自定义
- **25 个平台爬虫**(`Clawer/`):国内综合 2 + 国内官媒 3 + 外媒综合 8 + 外媒财经 5 + 外媒科技 7
- **文章链接自动发现** (`Services/discovery.py`):26 个媒体源注册表,RSS / 栏目页两种发现模式,平台 URL 识别
- **翻译服务** (`Services/translator.py`):deep-translator(Google 免费接口),复用代理配置,失败降级显示原文
- **RSS 摘要模式**:付费墙站点(Washington Post)不走文章页,直接展示 RSS 标题/摘要
- 版本标记 `__version__ = "0.1.0"`

### 修复

- 正文提取混入内嵌 `<script>/<style>/<template>` 文本噪声(如人民网 `showPlayer(...)` 视频脚本)
- `block_xpath` 模式下非标准标签(如 NYT 的 `div.article-paragraph`)被默认标签集过滤导致正文丢失
- NYT 中文版正文容器错配(`section[articleBody]` → `section.article-body`)

### 已知限制

- www.nytimes.com 英文站受 DataDome 反爬保护,正文不可抓(以 cn.nytimes.com 中文版替代)
- Washington Post / 部分外媒为硬付费墙,仅提供 RSS 摘要
- Ars Technica 存在反爬 challenge(HTTP 202)风险
- CNN live-blog 直播页(时间线流)无正文结构,通用解析器无法提取