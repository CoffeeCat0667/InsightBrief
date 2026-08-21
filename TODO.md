# InsightBrief TODO

## 敏感字段迁移到 `.env`

### 当前状态

- [ ] 待完成：将下表中的敏感字段从 `Config/*.json` 迁移到 `.env`；
- [ ] 待完成：修改配置加载代码，使应用从 `.env` 读取这些字段；
- [ ] 待完成：迁移完成后从 JSON 配置中移除敏感值，仅保留非敏感配置或占位结构；
- [ ] 待完成：同步更新 Docker/Compose、README、`.env.example` 和部署说明；
- [ ] 待完成：验证无敏感值进入日志、审计记录、前端响应、镜像层或 Git 提交；
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
