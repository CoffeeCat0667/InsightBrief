# Buglist — Code Review 记录

> **审查对象**: InsightBrief 全项目 (FastAPI 后端 + 爬虫 + LLM 简报 + SPA 前端)  
> **审查轮次**: 第五轮 (2026-08-22)  
> **方式**: 只读审查 + 运行时实测验证  
> **结论**: 无 P0 阻塞；核心风险集中在 **用户删除外键漏检、登录枚举侧信道、CORS 配置缺失、Guard 语义、审计 IP 逻辑反转**；前序高危项 (403 误判、登录限流、cancel 提权) **已修复**

---

## 0. 严重度分布 (第五轮累计)

| 级别 | 数量 | 说明 |
|------|------|------|
| P0 | 0 | — |
| P1 | 3 | 部署前必须修复 |
| P2 | 7 | 应尽快修复 |
| P3 | 10 | 记录在案，技术债/边界 |
| Fixed | 6 | 已修复项 |

---

## 1. P1 — 部署前必须修复

| ID | 位置 | 问题 | 建议 |
|----|------|------|------|
| **CORS-1** | `Services/App/main.py:85` | `allow_origins=core_config()["web"]["cors_origins"]` 但 `Config/Core.json` 缺少 `web.cors_origins` 字段 → 启动抛 `ConfigError`，服务不可用 | Core.json 增加 `web.cors_origins: ["http://localhost:8000"]` 开发默认；生产通过 `.env` 注入 |
| **ADM-1** | `Services/App/routers/admin.py:223-231` | `delete_admin_user` 仅检查 `CrawlTask` 引用，**漏检 `BriefTask.user_id` / `CrawlSchedule.user_id`** (均 FK `RESTRICT`) → 删除有简报任务/定时计划的用户触发 `IntegrityError` 500 | 联合检查三表 (`CrawlTask`/`BriefTask`/`CrawlSchedule`)，或统一用 `EXISTS` 子查询 |
| **AUTH-1** | `Services/App/security.py:74-80`<br>`Services/App/routers/auth.py:118-123` | **登录用户名枚举计时侧信道**：不存在用户走 `verify_dummy_password`(哈希固定串)，存在用户走 `verify_password`(哈希用户输入) → bcrypt 成本差异可枚举用户名 | `verify_dummy_password` 必须哈希**传入的同一密码**；dummy hash 用相同 cost 生成 |

---

## 2. P2 — 应尽快修复

| ID | 位置 | 问题 |
|----|------|------|
| **SEC-1** | `Client/js/api.js:36` | `toast` 用 `innerHTML`，虽已加 `_escHtml` 转义，但后端 `error.message` 若含 HTML 实体会双重编码显示异常；建议后端统一返回纯文本 |
| **GUARD-1** | `Report/processor.py:527-529` | `_Guard.touch(ok=True, service_error=True)` 会导致计数器**递增** (本应归零)；当前调用点无此组合但语义错误 | 修正：`ok` 时归零，仅 `service_error=True` 且 `ok=False` 时递增 |
| **AUDIT-1** | `Services/audit_logs/__init__.py:23-37` | **审计 IP 逻辑与注释反了**：代码 `if peer_ip not in trusted_proxy_ips: return peer_ip` 导致永远不采信 XFF；反代场景下审计 IP 全为反代服务器 IP | 修正为 `if peer_ip in trusted_proxy_ips and forwarded: return forwarded.split(",")[0].strip()` |
| **REG-1** | `Services/App/routers/auth.py:47-57, 78-91` | **并发注册竞态**：两并发同用户名请求均通过 SELECT，后者 commit 抛 `IntegrityError` → 已捕获转 409，**无 500**，但多一轮查询 | 可改用 PG `INSERT ... ON CONFLICT DO NOTHING` 或 `session.merge` 优化 |
| **CFG-1** | `Config/config.py:88-92` | **Redis DSN 解析静默丢弃 password**：DSN 含 `?` 时 `split("?")[1]` 截断，无告警，连接失败难排查 | 增加解析校验，失败时抛明确错误 |
| **CORS-2** | `Config/Core.json` | 缺少 `web.cors_origins` 字段 (同上 CORS-1 根因) | 补齐默认值 |
| **LLM-1** | `Report/llm/openai_v1.py:122-139` | ~~**403 误判**：所有 403 一律视为 content_policy，导致 `GROUP_DELETED` 等鉴权/额度错误被误判为内容风控，Guard 不计数、任务跑完 50 篇全空~~ | **✅ 已修复** (第五轮验证)：新增 `_CONTENT_POLICY_CODES` 白名单，非内容策略 403 现在抛 `LLMServiceError` 触发 Guard 快速失败 |

---

## 3. P3 — 技术债/观测性/边界情况

| ID | 位置 | 问题 |
|----|------|------|
| **PERF-1** | `Client/js/api.js:63-91` | `fetch` 封装每次调用重建 headers/body 序列化逻辑；可提取工具函数 |
| **ADM-3** | `Services/App/routers/admin.py` (推测) | 角色删除仅检查 `role_name`，未检 `role_id`；FK `RESTRICT` 兜底，实际无泄露 |
| **CFG-2** | `Config/config.py` | Redis DSN 解析同上 |
| **JWT-1** | `Services/App/security.py:28-30` | `JWT_SECRET` 等模块级常量化，`lru_cache` 无热刷新；修改 `.env` 需重启 (符合设计，需文档化) |
| **BCRYPT-1** | `Services/App/security.py:52-54` | `hash_password` 拒绝超长密码 (抛 `ValueError` 422) 但**不写审计**；建议记 `user.register_failed` / `user.update` |
| **TRANS-1** | `Report/processor.py:542-559` | 翻译器单例 double-checked locking 已正确实现，**无竞态** (第四轮误报) |
| **PROBE-1** | `Services/App/sync.py:159` vs `main.py:47` | `probe_llm_on_startup` 导出但 `main.py` 调用；需确认实现是否存在 |
| **ADM-2** | `Services/App/admin_settings.py:140-145` | ~~LLM 写入未清理 `get_llm_provider` 缓存~~ | **✅ 已修复** (第四轮)：写入后 `llm_config.cache_clear()` + `get_llm_provider.cache_clear()` |
| **BUG-01** | `Services/App/routers/tasks.py:202`<br>`Services/App/routers/briefs.py:149` | ~~cancel 端点仅 `get_current_user`，普通用户可取消任务~~ | **✅ 已修复**：均改为 `require_admin` |
| **BUG-02** | `Services/discovery.py:203` | ~~`_in_ad_container` 只查 `ancestor::*[@class]`，漏查 `<a>` 自身 class~~ | **✅ 已修复**：改为 `ancestor-or-self::*[@class]` |

---

## 4. 已修复项 (第五轮验证确认)

| ID | 修复位置 | 修复内容 | 验证状态 |
|----|----------|----------|----------|
| BUG-01 | `tasks.py:202`, `briefs.py:149` | cancel 端点改用 `require_admin` | ✅ |
| BUG-02 | `discovery.py:203` | `_in_ad_container` 改用 `ancestor-or-self::*[@class]` | ✅ |
| ADM-2 | `admin_settings.py:140-145` | LLM 写入后清除 `get_llm_provider` 缓存 (try/except 包裹) | ✅ |
| LLM-1 | `openai_v1.py:122-139` | 403 误判修复：区分 content_policy 与 auth/quota 错误 | ✅ 实测 `GROUP_DELETED` 走 `LLMServiceError` |
| RATE-1 | `login_rate_limit.py` | 登录限流实现：滑动窗口 + Redis/内存降级 | ✅ 已集成 `auth.py:111-117` |
| CANCEL-1 | `tasks.py:202`, `briefs.py:149` | cancel 提权修复 (同上 BUG-01) | ✅ |

---

## 5. 修复优先级建议 (第五轮更新)

| 优先级 | 任务 | 预估工时 |
|--------|------|----------|
| **P0-部署前** | 1. Core.json 补 `web.cors_origins` 默认值 | 5min |
| | 2. `delete_admin_user` 联合检查 3 张表 (`CrawlTask`/`BriefTask`/`CrawlSchedule`) | 15min |
| | 3. `verify_dummy_password` 哈希传入密码而非固定串 | 10min |
| **P1-上线前** | 4. Guard `touch` 语义修正 (`ok` 归零优先) | 5min |
| | 5. 审计 IP `trusted_proxy_ips` 逻辑修正 | 10min |
| | 6. 超长密码拒绝写审计 (`user.register_failed` / `user.update`) | 10min |
| **P2-迭代中** | 7. 并发注册 `ON CONFLICT` 优化 | 20min |
| | 8. `api.js` `request` 提取工具函数 | 15min |
| | 9. JWT/配置热刷新机制设计 (可选) | — |

---

## 6. 验收清单 (第五轮)

- [ ] 启动服务不报 `ConfigError: cors_origins`
- [ ] 创建用户 A → 建简报任务/定时计划 → 删除 A → 软禁用非报错
- [ ] 登录不存在用户 / 存在用户，计时差 < 2ms (侧信道修复验证)
- [ ] Nginx 反代后 `X-Forwarded-For` 正确写入审计表
- [ ] 无效 Key 触发 `GROUP_DELETED` → 任务快速 failed (非 completed 空简报)
- [ ] 超长密码注册/改密 → 审计表有 `user.register_failed` 记录

---

## 7. 配置管理审计 (第五轮补充)

| 检查项 | 状态 | 位置/备注 |
|--------|------|-----------|
| `.env` 包含敏感字段 | ✅ | JWT_SECRET / ADMIN_PASSWORD / DB_DSN / LLM_API_KEY |
| `.gitignore` 排除 `.env` | ✅ | `.gitignore` 已含 |
| `Config/*.json` 无敏感值 | ✅ | Core.json / Clawer.json / Services.json / LLM.json / db.json |
| `.env` 加载机制 | ✅ | `config.py` python-dotenv 加载到 os.environ |
| 必填字段校验 | ✅ | `_env_required()` 启动时检查 |
| 登录限流实现 | ✅ | `login_rate_limit.py` 滑动窗口 + Redis/内存降级 |
| 审计 IP 提取 | ⚠️ 逻辑反了 | `audit_logs/__init__.py:31` 需修正 |
| JWT 配置 | ✅ | `Core.json` HS256 + 7200s 过期，模块常量化需重启生效 |
| LLM 配置同步 | ✅ | `sync_llm_config` 启动写入 PG，`admin_settings.write_llm_fields` 更新并清缓存 |
| CORS 配置 | ❌ 缺失 | `Core.json` 无 `web.cors_origins`，启动会失败 |

---

## 8. 历史轮次记录

| 轮次 | 日期 | 重点 | 关键产出 |
|------|------|------|----------|
| 第 1 轮 | 2026-08-18 | discovery 栏目页 DOM 化 + audit_logs | BUG-01..16 初始记录 |
| 第 2 轮 | 2026-08-18 | 后续跟进 | 无新增 |
| 第 3 轮 | 2026-08-19 | 敏感字段迁移 `.env` | 配置管理验证通过 |
| 第 4 轮 | 2026-08-19 | 全项目安全/bug 审计 | ADM-1/2, CORS-1, SEC-1 等新增 |
| **第 5 轮** | **2026-08-22** | **全项目安全/bug 审计 + 实测验证** | **ADM-1/ AUTH-1/ GUARD-1/ AUDIT-1 等新增；LLM-1/BUG-01/02/ADM-2/RATE-1 确认修复** |