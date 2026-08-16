# InsightBrief

> 多源新闻智能抓取与翻译阅读 —— CLI + **Web 后端**(FastAPI / PostgreSQL / Redis / SSE)

![Version](https://img.shields.io/badge/version-0.1.5-blue)
![License](https://img.shields.io/badge/license-Apache_2.0-green)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)

采集外媒/官媒新闻并自动翻译成简体中文展示;支持**人工触发抓取任务**(SSE 实时进度)与 **LLM 简报生成**(自动分类/摘要/综述)。

## 特性

- **25+ 媒体源**,分类:国内综合 / 国内官媒 / 外媒综合 / 外媒财经 / 外媒科技,源注册表配置化(`Config/Services.json`,27 源)
- **自动发现**:RSS / 栏目页 / 自定义(CNN 首页内嵌 JSON)三种模式
- **智能抓取**:`curl_cffi`(Chrome TLS 指纹)直连失败自动代理重试;CSR 站(The Verge)自动切 Playwright 渲染;付费墙摘要型(Washington Post)走 RSS 摘要
- **自动翻译**:外文经 deep-translator 译为简体中文,中文原样显示
- **Web 后端 API**:登录鉴权(JWT + 角色)、任务运行时(ThreadPoolExecutor 4 并发)、统一 `{success, data, error}` 契约、`/docs` 交互文档
- **SSE 进度通道**:抓取/简报任务实时进度,Redis 历史事件断线重放(无轮询降级)
- **简报系统**:LLM 分类(政治/经济/文化/科技)+ 中文标题 + 摘要 + 分类综述;降级链路(403 风控/服务错误两分)、取消=原子不落库、全挂 failed 残料保留

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
│   └── App/                    # Web 后端
│       ├── main.py             # FastAPI 入口 (uvicorn Services.App.main:app)
│       ├── routers/            # auth / sources / articles / tasks / briefs (+ SSE)
│       ├── models/             # 13 张表 SQLAlchemy 2.0 ORM
│       ├── schemas/            # API 契约 (统一响应/分页/状态机)
│       ├── task_manager.py     # 任务运行时 + Redis 事件总线 (crawl/brief kind 隔离)
│       ├── ingest.py           # 抓取落库中间层 (sha256 external_id, 幂等)
│       ├── security.py         # bcrypt + JWT + 角色 (seed 幂等)
│       └── sync.py             # 配置→DB 同步 (源/LLM 配置, 启动覆盖)
├── Report/                     # 简报系统
│   ├── llm/                    # Provider 抽象 + OpenAI V1 客户端 + 错误两分
│   ├── prompts.py              # 分类/摘要/标题/综述 prompt + extract_json
│   ├── operators.py            # 4 算子 (分类二分拆批降级)
│   └── processor.py            # BriefProcessor 编排
├── Config/                     # 唯一配置来源 (JSON 数据 + config.py 加载器)
│   ├── Core.json / Clawer.json / Services.json / LLM.json / db.json
├── alembic/                    # 迁移 (0001 13表 / 0002 max_items / 0003 brief meta/stats)
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

# 1) 建库 + 迁移 (DSN 在 Config/db.json; 密码 @ 须写 %40)
alembic upgrade head

# 2) 启动 Web 服务 (端口 8000; 启动时自动: 建表兜底 + 27 源同步 + LLM 配置同步 + admin 种子)
python -m uvicorn Services.App.main:app --host 127.0.0.1 --port 8000
```

- 交互 API 文档: http://127.0.0.1:8000/docs
- 初始管理员: `ADMIN_USERNAME`/`ADMIN_PASSWORD` 环境变量, 默认 `admin` / `admin123456`(生产必须配置 `JWT_SECRET`)
- CLI 仍可用: `python -m Services.CLI.main` 或 `python Services/CLI/main.py`(菜单输入媒体编号抓取最新一条)

## API 概览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/auth/login` (OAuth2 表单) / `/register` / `GET /me` | 登录/注册/当前用户 (401/403) |
| GET/POST | `/api/sources`、PATCH/DELETE `/api/sources/{id}` | 源 CRUD (写操作 admin) |
| GET | `/api/articles`、`/search`、`/{id}` | 文章列表/搜索/详情 (正文片段+全文译文) |
| GET | `/api/platforms` | 平台聚合列表 |
| POST | `/api/crawl-tasks`、`GET` 列表/`/{id}`、`POST /{id}/cancel` | 抓取任务 (409 源重叠幂等; source_ids 省略=全部启用源) |
| GET | `/api/tasks/{id}/events` | 抓取任务 SSE 进度 (crawl) |
| POST/GET | `/api/brief-tasks`、`GET /{id}`、`POST /{id}/cancel`、`GET /{id}/events` | 简报任务 + SSE (brief 独立端点) |
| GET | `/api/briefs(/{id})` | 简报列表/详情 |

统一响应 `{success, data, error}`,错误码:bad_request/unauthorized/forbidden/not_found/conflict/validation_error/rate_limited/internal_error/upstream_error。

**前端说明**:无 Web 前端(用户拍板不做)。所有功能经 REST API 使用;操作类接口建议以 curl / `/docs` 触发,长任务用对应 SSE 端点订阅实时进度。

## 配置与密钥

所有配置只从 `Config/config.py` 加载(`Config/*.json` + lru_cache + 必填校验):

- `Config/Core.json`:代理(默认 127.0.0.1:7897,`CRAWL_PROXY` 覆盖,空串禁用)、UA、超时/重试、playwright、阈值
- `Config/Clawer.json`:25 平台 base_url / xpath / UA / fetch_strategy
- `Config/Services.json`:27 源注册表 + platform/link 正则 + translator + domestic_source_ids
- `Config/LLM.json`:LLM 三字段(base_url/api_key/model_id)+ 算子参数;`LLM_API_KEY` 环境变量可覆盖 api_key(启动同步生效)
- `Config/db.json`:PG/Redis DSN(`DB_DSN`/`REDIS_*` 覆盖);`.env.example` 为覆盖模板

> 配置在进程启动时定型(lru_cache);启动时 Config 会同步覆盖 DB(sources 与 system_settings),运行中改 DB 无效。

## 新增媒体源

1. **完整正文源**:`Clawer/<分类>/<平台>_news/` 下建薄子类(继承 `GenericArticleCrawler`,配置 `base_url` / `content_xpath`;非标准正文块用 `block_xpath`;CSR 站设 `fetch_strategy = PlaywrightFetcher`)
2. **RSS 摘要源**(付费墙站):在 `Config/Services.json` 的 sources 注册 rss 类型源,启动同步自动入库
3. 分类/正则/参数按 `Config/Services.json` 与 `Clawer.json` 结构补

## 测试惯例

仓库不引 pytest 套件,采用**验证式开发**:每批次交付后跑真实端到端(抓取/任务/SSE/简报)+ 全仓 import 冒烟,测试数据用完即清(详见 CHANGELOG 各版本"验证"小节)。

## 许可证

[Apache License 2.0](LICENSE) © 2026 CoffeeCat0667