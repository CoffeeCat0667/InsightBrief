# InsightBrief

> 多源新闻智能抓取与翻译阅读 —— CLI + **Web 后端**(FastAPI / PostgreSQL / Redis / SSE)

![Version](https://img.shields.io/badge/version-0.2.5-blue)
![License](https://img.shields.io/badge/license-Apache_2.0-green)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)

采集外媒/官媒新闻并自动翻译成简体中文展示;支持**人工或定时抓取任务**(SSE 实时进度)与 **LLM 简报生成**(自动分类/摘要/综述)。

## 特性

- **25+ 媒体源**,分类:国内综合 / 国内官媒 / 外媒综合 / 外媒财经 / 外媒科技,源注册表配置化(`Config/Services.json`,27 源)
- **自动发现**:RSS / 栏目页 / 自定义(CNN 首页内嵌 JSON)三种模式
- **管理面板**:管理员管理用户(新增/编辑/删除或软禁用)、注册入口、LLM 三字段连通性检查与双写、非管理员可见选项卡、日志配置(等级/大小即时生效)
- **定时抓取**:每 N 小时循环、最多执行次数(0=无限)、首次启用立即执行、可选抓取完成后自动简报;服务重启后从 PG 恢复计划
- **Web 后端 API**:登录鉴权(JWT + 角色)、管理面板、任务运行时(ThreadPoolExecutor 4 并发)、定时抓取、统一 `{success, data, error}` 契约、`/docs` 交互文档
- **SSE 进度通道**:抓取/简报任务实时进度,Redis 历史事件断线重放(无轮询降级);前端使用 fetch + ReadableStream 解析 SSE
- **简报系统**:LLM 分类(政治/经济/文化/科技)+ 中文标题 + 摘要 + 分类综述;抓取完成可仅针对本次新增文章自动生成简报;降级链路(403 风控/服务错误两分)、取消=原子不落库、全挂 failed 残料保留;支持批量为所有未简报文章生成简报
- **统计信息**:抓取任务页文章按天/按源统计;简报任务页简报概览/按天/按源统计;横向柱状图可视化
- **敏感字段 `.env` 管理**:JWT secret、管理员凭据、DB DSN、Redis password、LLM 凭据、CORS origins 等全部从 `.env` 加载,`Config/*.json` 不含敏感值

## 架构

```
InsightBrief/
├── Services/
│   ├── CLI/main.py             # CLI 主程序入口 (python -m Services.CLI.main, 菜单 1-26)
├── Core/                       # 抓取核心(fetchers / base / generic / models)
├── Clawer/                     # 各平台爬虫 (按类别分组, 25 平台薄子类)
├── Services/
│   ├── discovery.py            # 源注册表 + 链接发现 (DB 懒加载)
│   ├── translator.py           # 中文判断 + deep-translator 翻译
│   ├── audit_logs/             # 审计写入 (write_audit 独立会话, 失败不炸主业务)
│   └── App/                    # Web 后端
│       ├── main.py             # FastAPI 入口 (uvicorn Services.App.main:app)
│       ├── routers/            # auth / admin / sources / articles / tasks / schedules / briefs / audit-logs (+ SSE)
│       ├── models/             # 15 张表 SQLAlchemy 2.0 ORM
│       ├── schemas/            # API 契约 (统一响应/分页/状态机)
│       ├── task_manager.py     # 任务运行时 + Redis 事件总线 (crawl/brief kind 隔离)
│       ├── schedule_manager.py # 定时计划调度线程
│       ├── auto_brief.py       # 抓取新增文章的自动简报触发
│       ├── admin_settings.py   # 注册/LLM/可见选项卡设置
│       ├── ingest.py           # 抓取落库中间层 (sha256 external_id, 幂等)
│       ├── security.py         # bcrypt + JWT + 角色 (seed 幂等)
│       └── sync.py             # 配置→DB 同步 (源/LLM 配置, 启动覆盖)
├── Client/                     # 前端单页应用 (原生 JS, 静态挂载至 /)
│   ├── index.html              # SPA 骨架 + 图标
│   ├── css/style.css           # 双主题样式 (跟随系统 + 手动覆盖)
│   └── js/                     # api 封装 / SSE 流解析 / History 路由 / 文章/简报/抓取/源/审计/管理视图
├── Report/                     # 简报系统
│   ├── llm/                    # Provider 抽象 + OpenAI V1 客户端 + 错误两分
│   ├── prompts.py              # 分类/摘要/标题/综述 prompt + extract_json
│   ├── operators.py            # 4 算子 (分类二分拆批降级)
│   └── processor.py            # BriefProcessor 编排
├── Config/                     # 唯一配置来源 (JSON 数据 + config.py 加载器)
│   ├── Core.json / Clawer.json / Services.json / LLM.json / db.json
├── Tools/                       # 运维工具
│   └── measure_fetch_timeout.py # 平台超时实测写回 (换环境重调优)
├── alembic/                    # 迁移 (0001~0003 + timeout/audit/quota/schedule 迁移)
├── data/                       # 只读历史 JSON 档案 (不再写入)
├── requirements.txt
├── CHANGELOG.md
└── LICENSE                     # Apache-2.0
```

## 快速开始

要求:Python 3.10+ (开发环境 3.14), PostgreSQL, Redis 兼容服务(Memurai)。

```bash
pip install -r requirements.txt
python -m playwright install chromium   # CSR 站点浏览器内核

# 1) 复制 .env.example 为 .env 并填入实际值 (DB DSN / JWT secret / 管理员密码 / LLM api_key 等)
# 2) 建库 + 迁移 (DSN 从 .env 读取; 密码 @ 须写 %40)
alembic upgrade head

# 2) 启动 Web 服务 (端口 8000; 启动时自动: 建表兜底 + 27 源同步 + LLM 配置同步 + 注册设置初始化 + admin 种子)
python -m uvicorn Services.App.main:app --host 127.0.0.1 --port 8000
```

`alembic upgrade head` 当前迁移链包括 0001~0003、平台超时/审计/国内源配额和定时任务迁移，当前版本为 `h9c0d1e2f3a4`。

- 交互 API 文档: http://127.0.0.1:8000/docs
- 初始管理员: 空库启动时使用 `.env` 中的 `IB_ADMIN_USERNAME`/`IB_ADMIN_PASSWORD`; 若配置缺失服务拒绝初始化,避免默认凭据风险。
- CLI 仍可用: `python -m Services.CLI.main` 或 `python Services/CLI/main.py`(菜单输入媒体编号抓取最新一条)

## API 概览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/auth/login` (OAuth2 表单) / `/register` / `GET /me` | 登录/注册/当前用户 (401/403) |
| GET/POST | `/api/sources`、PATCH/DELETE `/api/sources/{id}` | 源 CRUD (写操作 admin) |
| GET | `/api/articles`、`/search`、`/{id}` | 文章列表/搜索/详情 (正文片段+全文译文) |
| GET | `/api/platforms` | 平台聚合列表 |
| POST | `/api/crawl-tasks`、`GET` 列表/`/{id}`、`POST /{id}/cancel` | 抓取任务 (409 源重叠幂等; source_ids 省略=全部启用源; 支持 `domestic_max_ratio`) |
| GET/POST/PATCH/DELETE | `/api/crawl-schedules`、`/{id}/enable`、`/{id}/disable`、`/{id}/run-now` | 定时抓取计划(admin); interval_hours / max_runs(0=无限) / 自动简报 |
| GET | `/api/tasks/{id}/events` | 抓取任务 SSE 进度 (crawl) |
| POST/GET | `/api/brief-tasks`、`GET /{id}`、`POST /{id}/cancel`、`GET /{id}/events` | 简报任务 + SSE (brief 独立端点) |
| GET | `/api/briefs(/{id})` | 简报列表/详情 |
| GET | `/api/articles/stats-by-day`、`/stats-by-source` | 文章按天/按源统计 |
| GET | `/api/brief-tasks/stats-by-day`、`/stats-by-source`、`/stats-overview` | 简报按天/按源/概览统计 |
| GET/PUT | `/api/admin/logging` | 日志配置(admin; 等级/大小即时生效) |
| GET | `/api/audit-logs` | 审计日志 (admin; action/user_id 筛选 + 分页) |
| GET/POST/PATCH/DELETE | `/api/admin/users`、`/api/admin/users/{id}` | 管理用户(admin; 新增/编辑/删除或软禁用) |
| GET/PUT | `/api/admin/registration`、`/api/admin/llm`、`/api/admin/tabs` | 注册入口、LLM 连通性检查双写、非管理员选项卡可见性(admin) |

统一响应 `{success, data, error}`,错误码:bad_request/unauthorized/forbidden/not_found/conflict/validation_error/rate_limited/internal_error/upstream_error。

**前端**:`Client/` 原生 HTML/CSS/JS 单页应用(零构建),由 FastAPI 静态挂载并提供 SPA fallback — 可直接访问 `http://127.0.0.1:8000/articles`、`/brief`、`/crawl`、`/sources`、`/admin`(无需另起静态服务器, URL 不含 `#`)。功能:登录/注册、文章浏览与搜索、抓取任务(SSE 实时进度/定时计划/国内源比例/自动简报)、简报生成与阅读、新闻源管理(admin)、审计日志(admin)、管理面板(admin);双主题跟随系统(prefers-color-scheme),顶栏可手动覆盖。

## [Ver0.2.0] 功能摘要

| 能力 | 说明 |
|---|---|
| History SPA | `/articles` 等真实路径，无 `#`；FastAPI 深链 fallback |
| 定时抓取 | 每 N 小时、max_runs（0=无限）、冲突顺延、重启恢复 |
| 自动简报 | 仅本次抓取 inserted 新文章，避免重复 LLM 处理 |
| 国内源配额 | `domestic_max_ratio` 0–100，外源优先、共享硬配额 |
| 管理面板 | 用户 CRUD、注册开关、LLM probe 双写、非管理员导航权限 |
## 配置与密钥

**Ver0.2.5 起**：敏感字段全部从 `.env` 加载（通过 `python-dotenv`），非敏感配置保留在 `Config/*.json`。`.env` 已加入 `.gitignore`，不纳入版本控制。模板见 `.env.example`。

| 配置来源 | 内容 |
|---|---|
| `.env` (敏感) | `IB_JWT_SECRET`、`IB_ADMIN_USERNAME`、`IB_ADMIN_PASSWORD`、`IB_POSTGRES_DSN`、`IB_REDIS_PASSWORD`、`IB_LLM_BASE_URL`、`IB_LLM_API_KEY`、`IB_LLM_MODEL_ID`、`IB_PROXY_DEFAULT`、`IB_CORS_ORIGINS` |
| `Config/Core.json` | UA、重试、Playwright、rate limit、trusted proxies、`web.disable_docs` |
| `Config/Clawer.json` | 25 平台 base_url / xpath / UA / fetch_strategy / **`fetch_timeout`(超时唯一来源)** |
| `Config/Services.json` | 27 源注册表 + platform/link 正则 + translator + domestic_source_ids |
| `Config/LLM.json` | timeout、retry、operator params（base_url/api_key/model_id 已迁移至 `.env`） |
| `Config/db.json` | pool_size、max_overflow、Redis host/port/db（DSN 已迁移至 `.env`） |

LLM 配置双向同步：`.env` → `sync_llm_config()` → PG `system_settings("llm")` → `get_llm_provider()`（读 PG）。管理面板修改 LLM 时仅写 PG + 回写 `.env`。

### 管理面板与权限

管理面板只对管理员显示，提供用户管理、注册入口开关、LLM 配置、非管理员选项卡可见性和日志配置。非管理员默认只显示“文章”、“简报”和“简报任务”；管理员可以在 `/admin` 中调整为文章/简报/简报任务/抓取任务/新闻源的任意非空子集。审计日志和管理面板始终不对非管理员开放。

> 敏感配置从 `.env` 加载（lru_cache + 必填校验）；启动时 Config 会同步覆盖 DB（sources 与 system_settings），运行中修改 `.env` 或 JSON 需重启生效；管理面板更新 LLM 时仅写 PG + 回写 `.env` 并清理进程内 LLM 配置缓存。

### 定时抓取与自动简报

定时计划由数据库持久化、FastAPI lifespan 启动的后台线程每 15 秒检查一次。创建或重新启用后立即执行首次抓取；`max_runs=0` 无限循环，达到正数上限自动暂停；上一轮或其它任务存在源冲突时本轮顺延而不并发。开启自动简报后，仅本轮新插入（`inserted`）的文章进入简报，已存在文章不会重复生成。
### 超时调优

超时**唯一来源** = 各平台 `Config/Clawer.json` 条目 `fetch_timeout`(无全局 timeout;`Core/base.py` 常量 30 仅兜底 CLI/未知平台)。换服务器或网络环境变化后重调优:

```bash
python Tools/measure_fetch_timeout.py             # 全量实测并自动写回 Clawer.json
python Tools/measure_fetch_timeout.py --dry-run   # 只预览建议值, 不写文件
python Tools/measure_fetch_timeout.py --platform zdnet --platform dw   # 只测指定平台
```

建议值规则:实测 t 秒 → `max(20, 向上取整到 5 的 t*1.5)`。修改后**重启服务**生效。

## History 路由与 Nginx 部署

前端使用 History API 路由，页面 URL 不带 `#`。FastAPI 已对非 `/api` 未命中的路径回退 `Client/index.html`，因此直接刷新 `/articles`、`/brief`、`/crawl`、`/admin` 可用。

若由 Nginx 直接托管 `Client/`，需要 SPA fallback：

```nginx
location / {
    root /path/to/InsightBrief/Client;
    try_files $uri $uri/ /index.html;
}

location /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_buffering off;
    proxy_read_timeout 3600s;
}
```

反代时把 Nginx 的地址加入 `Config/Core.json` 的 `auth.trusted_proxy_ips`，审计日志才会采信 `X-Forwarded-For` 的首个地址。

## 新增媒体源

1. **完整正文源**:`Clawer/<分类>/<平台>_news/` 下建薄子类(继承 `GenericArticleCrawler`,配置 `base_url` / `content_xpath`;非标准正文块用 `block_xpath`;CSR 站设 `fetch_strategy = PlaywrightFetcher`)
2. **RSS 摘要源**(付费墙站):在 `Config/Services.json` 的 sources 注册 rss 类型源,启动同步自动入库
3. 分类/正则/参数按 `Config/Services.json` 与 `Clawer.json` 结构补

## 测试惯例

仓库不引 pytest 套件,采用**验证式开发**:每批次交付后跑真实端到端(抓取/任务/SSE/简报)+ 全仓 import 冒烟,测试数据用完即清(详见 CHANGELOG 各版本"验证"小节)。

## 许可证

[Apache License 2.0](LICENSE) © 2026 CoffeeCat0667