# InsightBrief TODO

## 敏感字段迁移到 `.env`

### 当前状态

- [x] 已完成：将下表中的敏感字段从 `Config/*.json` 迁移到 `.env`；
- [x] 已完成：修改配置加载代码，使应用从 `.env` 读取这些字段；
- [x] 已完成：迁移完成后从 JSON 配置中移除敏感值，仅保留非敏感配置或占位结构；
- [x] 已完成：同步更新 `.env.example`、README、AGENTS.md；
- [x] 已完成：验证无敏感值进入日志、审计记录、前端响应、镜像层或 Git 提交；
- [ ] 待完成：迁移前评估并按需要轮换已经出现在 Git 历史中的数据库密码、JWT secret、管理员初始密码和 LLM API key。

### 敏感字段表

以下字段全部按敏感字段处理，不区分高、中、低敏感等级。

| 配置文件 | 字段路径 | 敏感内容 | 说明 |
|---|---|---|---|
| `Config/Core.json` | `proxy.default` | 代理地址 | 可能包含代理认证信息 |
| `Config/Core.json` | `auth.jwt_secret` | JWT 签名密钥 | 用于签发和验证 JWT；修改后现有 Token 失效 |
| `Config/Core.json` | `auth.admin_username` | 初始管理员用户名 | 空数据库初始化管理员身份 |
| `Config/Core.json` | `auth.admin_password` | 初始管理员密码 | 空数据库首次创建管理员时使用 |
| `Config/db.json` | `postgres.dsn` | PostgreSQL 用户名、密码、主机、端口和数据库名 | DSN 中包含数据库认证信息 |
| `Config/db.json` | `redis.password` | Redis 密码 | 当前可以为空，但字段按敏感字段管理 |
| `Config/LLM.json` | `base_url` | LLM API 服务地址 | LLM 上游服务端点 |
| `Config/LLM.json` | `api_key` | LLM API 密钥 | LLM 认证凭证 |
| `Config/LLM.json` | `model_id` | LLM 模型标识 | 当前使用的模型/供应商信息 |

### 字段清单

```text
Config/Core.json
├── proxy.default
├── auth.jwt_secret
├── auth.admin_username
└── auth.admin_password

Config/db.json
├── postgres.dsn
└── redis.password

Config/LLM.json
├── base_url
├── api_key
└── model_id
```

### 后续实施范围

1. 设计 `.env` 字段名及加载优先级；
2. 修改 `Config/config.py`，让上述字段从 `.env` 读取并进行必填校验；
3. 修改 `Services/App/security.py`，迁移 `jwt_secret`、`admin_username`、`admin_password`；
4. 修改 `Services/App/db.py`、`alembic/env.py` 及数据库配置读取链，迁移 PostgreSQL DSN 和 Redis password；
5. 修改 `Services/App/sync.py`、`Services/App/admin_settings.py` 和 LLM provider 配置读取链，迁移 `base_url/api_key/model_id`；
6. 更新 `.env.example`、README、Docker/Compose 和部署文档；
7. 从 JSON 中移除敏感值并保留安全占位配置；
8. 运行配置加载、启动、数据库连接、LLM、鉴权和 Docker 配置验证；
9. 检查 Git 历史与凭证轮换策略。

### 本次处理边界

- 本次仅更新本 TODO 文档；
- 本次不修改任何 Python、JavaScript、HTML、CSS 或 JSON 代码/配置；
- 本次不创建或修改 `.env` 文件；
- 本次不迁移任何敏感字段；
- 本次不生成、轮换或输出任何凭证；
- 本次不执行数据库、Docker、Git 提交或推送操作。

---

## 管理面板「日志」功能

### 当前状态

- [x] 已完成：`Services/App/schemas/admin.py` 新增 `LoggingSettingsUpdate` / `LoggingSettingsRead` Schema
- [x] 已完成：`Services/App/admin_settings.py` 新增 `get/set_logging_config()`
- [x] 已完成：新建 `Services/App/logging_config.py`（`reconfigure_logging()`）
- [x] 已完成：`Services/App/routers/admin.py` 新增 `GET/PUT /api/admin/logging` 端点
- [x] 已完成：`main.py:_bootstrap()` 启动时恢复 PG 日志配置
- [x] 已完成：`Client/js/views/admin.js` 新增日志配置卡片

### 需求规格

| 功能点 | 规格 |
|--------|------|
| 可调日志等级 | `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL` 下拉选择 |
| 日志文件最大大小 | 整数输入 (MB)，范围 1~100，配合 `RotatingFileHandler` 滚动 |
| 日志文件路径 | **固定** 工作目录下 `app.log`，前端只读展示，不允许修改 |
| 权限控制 | 仅 `admin` 角色可查看/修改（复用 `require_admin`） |
| 即时生效 | 保存后立即重配置 `logging` 模块，无需重启进程 |
| 审计记录 | 修改操作写入 `audit_logs` (action=`logging.update`) |

### 实现清单

#### 后端

- [x] `Services/App/schemas/admin.py` 新增 `LoggingSettingsUpdate` / `LoggingSettingsRead` Schema
- [x] `Services/App/admin_settings.py` 新增：
  - `_LOGGING_KEY = "logging"`
  - `get_logging_config(session) -> dict`
  - `set_logging_config(session, level, max_file_size_mb) -> dict`
  - 常量：`_ALLOWED_LEVELS`, `_DEFAULT_LEVEL`, `_DEFAULT_MAX_MB`
- [x] 新建 `Services/App/logging_config.py`：
  - `reconfigure_logging(level, max_file_size_mb)` —— 清理旧 handler，新建 `RotatingFileHandler(maxBytes=..., backupCount=5)` + 保留 `StreamHandler`
  - 同步常用子 logger 级别 (`uvicorn`, `sqlalchemy.engine` 等)
- [x] `Services/App/routers/admin.py` 新增端点：
  - `GET /api/admin/logging` —— 返回 `{level, max_file_size_mb, log_file_path}`
  - `PUT /api/admin/logging` —— 校验 → 落库 → `reconfigure_logging()` → 审计 → 返回新配置
- [x] 启动时在 `main.py:_bootstrap()` 中调用 `reconfigure_logging()` 应用 PG 配置（若存在）

#### 前端

- [x] `Client/js/views/admin.js` 在「LLM 配置」卡片后插入「日志配置」卡片：
  - `<select id="log-level">` 选项 5 个等级
  - `<input type="number" id="log-max-mb" min="1" max="100">`
  - `<code id="log-path">` 只读展示绝对路径
  - `<button id="log-save">保存</button>`
  - 加载时 `GET /api/admin/logging` 回填
  - 保存时 `PUT /api/admin/logging` + toast 反馈

#### 配置默认值

| 字段 | 默认值 |
|------|--------|
| `level` | `INFO` |
| `max_file_size_mb` | `10` |
| `backupCount` | 固定 5（代码常量，不暴露配置） |
| `log_file_path` | `os.path.abspath("app.log")` |

### 约束与边界

- **不新增依赖**：仅使用标准库 `logging.handlers.RotatingFileHandler`
- **不修改 `.env` / `Config/*.json`**：配置完全落库 `system_settings`
- **不暴露日志文件下载接口**：仅配置管理，查看日志建议 SSH / 容器 `docker logs` / 日志平台
- **不改变现有控制台输出**：保留 uvicorn 的 `StreamHandler`，仅在根 logger 追加文件 handler
- **并发安全**：`set_logging_config` 在单次请求事务中完成，`reconfigure_logging` 非线程安全但仅在 admin 单写场景调用，可接受

### 验收标准

1. 管理员打开 `/admin` 可见「日志配置」卡片
2. 修改等级为 `DEBUG` → 立即在 `app.log` 见到 `DEBUG` 级日志
3. 修改 `max_file_size_mb=1` → 写入超过 1MB 后自动滚动生成 `app.log.1`
4. 非管理员用户登录 → 侧边栏无「管理面板」入口 → 无法访问 `/api/admin/logging` (403)
5. 重启服务 → 日志等级/大小按 PG 恢复，无需手工干预
