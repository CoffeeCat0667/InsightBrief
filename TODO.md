# InsightBrief Docker 部署 TODO

> 目标版本：Ver0.2.0
> 当前状态：项目尚未新增 Docker 部署文件；本清单记录从本地原生运行迁移到 Docker/Compose 的完整步骤。
> 安全要求：不要把真实密码、JWT secret 或 LLM API key 写入镜像、Git 仓库或公开日志。

---

## 0. 部署拓扑

推荐生产拓扑：

```text
公网
  ↓
Nginx（可选公网入口 / TLS / History fallback / SSE 反代）
  ↓
InsightBrief app（FastAPI + Uvicorn + 原生 JS SPA）
  ↓                 ↓
PostgreSQL 16       Redis 7
```

当前定时调度器运行在 app 进程内，首次部署建议 app 保持单实例。

---

## 1. 准备 Docker 文件

在仓库根目录新增以下文件（本 TODO 不自动创建）：

- [ ] `Dockerfile`
- [ ] `.dockerignore`
- [ ] `compose.yaml`
- [ ] 本地私有环境文件 `.env.docker`（不要提交）
- [ ] 公网部署时新增 `docker/nginx.conf`

---

## 2. 创建 Dockerfile

建议使用 Python 3.12，先保证依赖和 Playwright 的兼容性：

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install --with-deps chromium

COPY . .

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn Services.App.main:app --host 0.0.0.0 --port 8000"]
```

检查点：

- [ ] 容器监听 `0.0.0.0:8000`，不能使用 `127.0.0.1`；
- [ ] 镜像包含 Playwright Chromium 及系统依赖；
- [ ] 启动前执行 `alembic upgrade head`；
- [ ] 生产部署时确认 migration 是预期版本 `h9c0d1e2f3a4`。

---

## 3. 创建 `.dockerignore`

```gitignore
.git
.gitignore
__pycache__
*.py[cod]
.venv
venv
.env
.env.*
buglist.md
data
*.log
.pytest_cache
.mypy_cache
```

检查点：

- [ ] `.env`、`.env.docker`、真实配置文件没有被复制进镜像；
- [ ] 不把真实 `Config/LLM.json` API key 烘焙进公开镜像；
- [ ] `buglist.md` 不进入镜像和发布提交。

---

## 4. 创建 Compose 文件

创建 `compose.yaml`：

```yaml
services:
  postgres:
    image: postgres:16
    restart: unless-stopped
    environment:
      POSTGRES_DB: insightbrief
      POSTGRES_USER: insightbrief
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U insightbrief -d insightbrief"]
      interval: 5s
      timeout: 5s
      retries: 20

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 20

  app:
    build:
      context: .
      dockerfile: Dockerfile
    image: insightbrief:0.2.0
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    environment:
      DB_DSN: postgresql+psycopg://insightbrief:${POSTGRES_PASSWORD}@postgres:5432/insightbrief
      REDIS_HOST: redis
      REDIS_PORT: 6379
      REDIS_DB: 0
      JWT_SECRET: ${JWT_SECRET}
      ADMIN_USERNAME: ${ADMIN_USERNAME}
      ADMIN_PASSWORD: ${ADMIN_PASSWORD}
      LLM_API_KEY: ${LLM_API_KEY}
      CRAWL_PROXY: ${CRAWL_PROXY:-}
      TRUSTED_PROXY_IPS: ${TRUSTED_PROXY_IPS:-}
      IB_DISABLE_DOCS: ${IB_DISABLE_DOCS:-1}
    ports:
      - "127.0.0.1:8000:8000"

volumes:
  postgres_data:
  redis_data:
```

检查点：

- [ ] app 使用服务名 `postgres` 和 `redis`，不能使用容器内的 `127.0.0.1`；
- [ ] PostgreSQL、Redis 不直接暴露公网端口；
- [ ] `postgres_data`、`redis_data` 已配置持久卷；
- [ ] app 首次部署保持单实例，避免重复运行进程内调度器。

---

## 5. 准备私有环境变量

创建本地 `.env.docker`，不要提交：

```dotenv
POSTGRES_PASSWORD=change_to_a_strong_password
JWT_SECRET=generate_a_long_random_secret
ADMIN_USERNAME=admin
ADMIN_PASSWORD=change_to_a_strong_admin_password
LLM_API_KEY=your_llm_api_key

# 没有代理时留空
CRAWL_PROXY=

# 不使用 Nginx 时留空；使用 Nginx 时填写 app 看到的可信反代地址
TRUSTED_PROXY_IPS=

# 生产建议关闭交互文档
IB_DISABLE_DOCS=1
```

检查点：

- [ ] `POSTGRES_PASSWORD`、`ADMIN_PASSWORD`、`JWT_SECRET` 已替换占位符；
- [ ] 密码中如包含 `@ : / ? # %`，已考虑 DSN URL 编码；
- [ ] `.env.docker` 已被 `.gitignore` 忽略；
- [ ] LLM key 未写入 Dockerfile、Compose 固定文本或镜像层。

---

## 6. LLM 配置持久化选择

当前管理面板更新 LLM 会写入：

```text
Config/LLM.json
PostgreSQL system_settings（key=llm）
```

容器重建时，容器内文件修改可能丢失。选择一种持久化策略：

### 方案 A：环境变量

- [ ] 使用 `LLM_API_KEY` 提供 key；
- [ ] 确认每次重新部署仍加载同一环境文件；
- [ ] 接受容器内 `LLM.json` 修改不作为长期文件存储。

### 方案 B：挂载宿主机配置

- [ ] 在宿主机准备 `docker-config/LLM.json`；
- [ ] 将真实配置文件加入 `.gitignore`；
- [ ] Compose 的 app 增加：

```yaml
volumes:
  - ./docker-config/LLM.json:/app/Config/LLM.json
```

- [ ] 限制宿主机配置文件权限；
- [ ] 公开发布镜像前轮换旧 API key。

---

## 7. 构建镜像

```bash
docker compose --env-file .env.docker build app
```

或：

```bash
docker build -t insightbrief:0.2.0 .
```

检查：

```bash
docker images insightbrief
```

- [ ] 镜像构建成功；
- [ ] Chromium 安装成功；
- [ ] 镜像层中没有私有环境文件和真实密钥。

---

## 8. 启动基础服务与应用

```bash
docker compose --env-file .env.docker up -d postgres redis
docker compose ps
docker compose --env-file .env.docker up -d app
docker compose logs -f app
```

检查日志中的：

- [ ] PostgreSQL health check 通过；
- [ ] Redis health check 通过；
- [ ] Alembic migration 成功；
- [ ] 27 个源同步完成；
- [ ] LLM 配置同步完成；
- [ ] 管理员种子完成；
- [ ] app 启动成功。

---

## 9. 基础健康检查

```bash
curl http://127.0.0.1:8000/api/health
```

预期版本：

```json
{
  "success": true,
  "data": {
    "status": "ok",
    "version": "0.2.0"
  }
}
```

检查 History 路由：

```text
http://127.0.0.1:8000/articles
http://127.0.0.1:8000/brief
http://127.0.0.1:8000/crawl
http://127.0.0.1:8000/sources
http://127.0.0.1:8000/admin
```

- [ ] 上述路径返回前端 HTML；
- [ ] 刷新深层路径不返回 404；
- [ ] URL 不含 `#`；
- [ ] `/api/health` 返回 JSON 200；
- [ ] 未知 `/api/*` 返回 404，而不是 HTML。

检查迁移：

```bash
docker compose exec app alembic current
```

预期：

```text
h9c0d1e2f3a4
```

---

## 10. 定时抓取与自动简报验证

- [ ] 管理员创建定时计划；
- [ ] 首次启用立即创建抓取任务；
- [ ] `max_runs=0` 表示无限循环；
- [ ] 正数 `max_runs` 达到后自动暂停；
- [ ] 与其它抓取任务源冲突时顺延、不并发；
- [ ] 抓取完成后只对本次 `inserted` 文章生成自动简报；
- [ ] 无新增文章时不创建空简报；
- [ ] 服务重启后计划仍存在；
- [ ] 服务重启不会重复生成同一自动简报。

---

## 11. Nginx 公网部署（可选）

创建 `docker/nginx.conf`：

```nginx
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://app:8000;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

Compose 增加：

```yaml
  nginx:
    image: nginx:1.27-alpine
    restart: unless-stopped
    depends_on:
      - app
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./docker/nginx.conf:/etc/nginx/conf.d/default.conf:ro
```

检查点：

- [ ] 公网只暴露 Nginx；
- [ ] PostgreSQL/Redis 没有公网端口映射；
- [ ] History 路由刷新正常；
- [ ] SSE `proxy_buffering off`；
- [ ] SSE `proxy_read_timeout` 足够长；
- [ ] HTTPS/TLS 证书已配置；
- [ ] Nginx 容器地址加入 `TRUSTED_PROXY_IPS`；
- [ ] 审计日志记录真实客户端 IP。

如果 Nginx 直接托管前端静态文件，而不是全部反代给 FastAPI，必须使用：

```nginx
location / {
    root /path/to/InsightBrief/Client;
    try_files $uri $uri/ /index.html;
}
```

---

## 12. 备份与升级

备份 PostgreSQL：

```bash
docker compose exec -T postgres \
  pg_dump -U insightbrief -d insightbrief > insightbrief-backup.sql
```

保留数据停止服务：

```bash
docker compose down
```

不要在没有备份时使用：

```bash
docker compose down -v
```

因为 `-v` 可能删除 PostgreSQL 和 Redis 数据卷。

升级步骤：

```bash
git pull
docker compose --env-file .env.docker build app
docker compose --env-file .env.docker up -d

docker compose logs -f app
docker compose exec app alembic current
curl http://127.0.0.1:8000/api/health
```

- [ ] 先备份数据库；
- [ ] 检查 migration SQL；
- [ ] 再重建 app；
- [ ] 验证 health、History 深链和 SSE；
- [ ] 必要时按 migration 设计执行回滚，不直接删除数据卷。

---

## 13. 推荐首次部署顺序

```bash
# 1. 检查 Docker
docker --version
docker compose version

# 2. 准备 .env.docker（不要提交）

# 3. 构建镜像
docker compose --env-file .env.docker build

# 4. 启动 PostgreSQL 与 Redis
docker compose --env-file .env.docker up -d postgres redis

# 5. 查看服务状态
docker compose ps

# 6. 启动 app
docker compose --env-file .env.docker up -d app

# 7. 查看日志
docker compose logs -f app

# 8. 健康检查
curl http://127.0.0.1:8000/api/health

# 9. 浏览器访问
# http://127.0.0.1:8000/articles
```

- [ ] 所有检查项完成；
- [ ] 真实密钥未进入 Git/镜像/日志；
- [ ] `buglist.md` 未提交；
- [ ] 生产公网部署已单独配置 Nginx、HTTPS、SSE 和可信代理。
