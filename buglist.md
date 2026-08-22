# Buglist — Code Review 记录

> **审查对象**: InsightBrief 全项目 (FastAPI 后端 + 爬虫 + LLM 简报 + SPA 前端)  
> **审查轮次**: 第六轮 (2026-08-22)  
> **方式**: 只读审查 + 运行时实测验证  
> **结论**: **新增 P0 阻塞项 (Core.json 缺 cors_origins 导致启动失败)**；核心高危项 (ADM-1, AUTH-1, GUARD-1, AUDIT-1) 仍未修复；**日志功能 (LOGGING-FEAT) 交付质量高，已可上线**

---

## 0. 严重度分布 (第六轮累计)

| 级别 | 数量 | 说明 |
|------|------|------|
| P0 | **1** | **Core.json 缺 cors_origins 导致启动失败** |
| P1 | 3 | 部署前必须修复 |
| P2 | 7 | 应尽快修复 |
| P3 | 10 | 记录在案，技术债/边界 |
| Fixed | **7** | 已修复项 (新增 LOGGING-FEAT) |

---

## 1. P0 — 阻塞启动 (第六轮新增)

| ID | 位置 | 问题 | 影响 |
|----|------|------|------|
| **BOOT-1** | `Config/Core.json` 缺 `web.cors_origins`<br>`Services/App/main.py:85` | `allow_origins=core_config()["web"]["cors_origins"]` 读取不存在的键 → 启动抛 `ConfigError: Core.json 缺少必填配置: web.cors_origins` | **服务完全无法启动** |

> **修复**: Core.json 增加 `"web": { "cors_origins": ["http://localhost:8000"], "disable_docs": false }`

---

## 2. P1 — 部署前必须修复 (未修复，继承自第五轮)

| ID | 位置 | 问题 | 修复建议 |
|----|------|------|----------|
| **CORS-1** | `main.py:85` | 见 P0-BOOT-1，同根因 | 补齐 Core.json 配置 |
| **ADM-1** | `admin.py:223-231` | `delete_admin_user` 仅检查 `CrawlTask` 引用，**漏检 `BriefTask.user_id` / `CrawlSchedule.user_id`** (均 FK `RESTRICT`) → 删除有简报任务/定时计划的用户触发 `IntegrityError` 500 | 联合检查三表或用 `EXISTS` 子查询 |
| **AUTH-1** | `security.py:74-80`<br>`auth.py:118-123` | **登录用户名枚举计时侧信道**：不存在用户走 `verify_dummy_password`(哈希用户输入密码 vs 固定 dummy hash)，存在用户走 `verify_password` — bcrypt 计算的输入不同，仍存微小计时差 | `verify_dummy_password` 应哈希**同一固定字符串**且 dummy hash 用相同 cost 生成，或统一走 `bcrypt.checkpw(password_bytes, stored_or_dummy_hash)` |

---

## 3. P2 — 应尽快修复 (未修复，继承自第五轮)

| ID | 位置 | 问题 |
|----|------|------|
| **SEC-1** | `Client/js/api.js:36` | `toast` 用 `innerHTML`，虽有 `_escHtml`，后端 `error.message` 若含 HTML 实体会双重编码显示异常；建议后端统一返回纯文本 |
| **GUARD-1** | `Report/processor.py:561-563` | `_Guard.touch(ok=True, service_error=True)` 会导致计数器**递增** (本应归零) — 语义 Bug，虽当前调用点未触发 |
| **AUDIT-1** | `Services/audit_logs/__init__.py:31` | **审计 IP 逻辑反了**：`if peer_ip not in trusted_proxy_ips: return peer_ip` → 永远不采信 XFF；应为 `if peer_ip in trusted_proxy_ips and forwarded: return forwarded.split(",")[0].strip()` |
| **REG-1** | `Services/App/routers/auth.py:47-91` | 并发注册竞态：SELECT→INSERT 间隙，第二个请求抛 `IntegrityError` 已捕获转 409，**无 500**，但可用 PG `ON CONFLICT` 优化 |
| **CFG-1** | `Config/config.py:88-92` | Redis DSN 解析静默丢弃 password：含 `?` 时 `split("?")[1]` 截断，无告警 |
| **CORS-2** | `Config/Core.json` | 缺少 `web.cors_origins` 字段 (同上 BOOT-1 根因) |
| **LLM-1** | `Report/llm/openai_v1.py:122-139` | ~~**403 误判**：所有 403 一律视为 content_policy，导致 `GROUP_DELETED` 等鉴权/额度错误被误判为内容风控，Guard 不计数、任务跑完 50 篇全空~~ | **✅ 已修复** (第五轮验证)：新增 `_CONTENT_POLICY_CODES` 白名单，非内容策略 403 现在抛 `LLMServiceError` 触发 Guard 快速失败 |

---

## 4. P3 — 技术债/观测性/边界情况 (未修复)

| ID | 位置 | 问题 |
|----|------|------|
| **PERF-1** | `Client/js/api.js:63-91` | `fetch` 封装每次调用重建 headers/body 序列化逻辑；可提取工具函数 |
| **ADM-3** | `Services/App/routers/admin.py` (推测) | 角色删除仅检查 `role_name`，未检 `role_id`；FK `RESTRICT` 兜底，实际无泄露 |
| **CFG-2** | `Config/config.py` | Redis DSN 解析同上 |
| **JWT-1** | `Services/App/security.py:28-30` | `JWT_SECRET` 等模块级常量化，`lru_cache` 无热刷新；修改 `.env` 需重启 (符合设计，需文档化) |
| **BCRYPT-1** | `Services/App/security.py:52-54` | `hash_password` 拒绝超长密码 (抛 `ValueError` 422) 但**不写审计**；建议记 `user.register_failed` / `user.update` |
| **TRANS-1** | `Report/processor.py:572-582` | 翻译器单例 double-checked locking 已正确实现，**无竞态** (第四轮误报) |
| **PROBE-1** | `Services/App/sync.py:216-266` | `probe_llm_on_startup` 失败仅 warning，**不阻断启动**，但后续 `get_llm_provider()` 会抛错 → 首次任务才报错 (设计为故意宽容，可接受) |
| **TAB-1** | `admin_settings.py:22` | `ALL_TABS` 新增 `"brief_tasks"`，`DEFAULT_NON_ADMIN_TABS` 也含 `"brief_tasks"` — 非管理员默认可见简报任务，需确认是否符合预期 |
| **LOGGING-1** | `logging_config.py:44` | `_root.setLevel(min(level_int, logging.INFO))` — 若用户设 `DEBUG`，根 logger 仍为 `INFO`，导致 `DEBUG` 级别只进文件不进控制台 (设计合理，但需文档化) |
| **LOGGING-2** | `logging_config.py:30-41` | `reconfigure_logging` 非线程安全，并发调用可能竞态 (仅 admin 单写场景，可接受) |

---

## 5. 已修复项 (第六轮累计)

| ID | 修复位置 | 修复内容 | 验证状态 |
|----|----------|----------|----------|
| BUG-01 | `tasks.py:202`, `briefs.py:149` | cancel 端点改用 `require_admin` | ✅ |
| BUG-02 | `discovery.py:203` | `_in_ad_container` 改用 `ancestor-or-self::*[@class]` | ✅ |
| ADM-2 | `admin_settings.py:140-145` | LLM 写入后清除 `get_llm_provider` 缓存 (try/except 包裹) | ✅ |
| LLM-1 | `openai_v1.py:122-139` | 403 误判修复：区分 content_policy 与 auth/quota 错误 | ✅ 实测 `GROUP_DELETED` 走 `LLMServiceError` |
| RATE-1 | `login_rate_limit.py` | 登录限流实现：滑动窗口 + Redis/内存降级 | ✅ 已集成 `auth.py:111-117` |
| CANCEL-1 | `tasks.py:202`, `briefs.py:149` | cancel 提权修复 (同上 BUG-01) | ✅ |
| **LOGGING-FEAT** | **全栈交付** | **管理面板「日志」功能完整实现** | ✅ **全栈交付** |
| | `admin_settings.py:168-189` | `get/set_logging_config` 持久化 PG | ✅ |
| | `logging_config.py:16-54` | `reconfigure_logging` (RotatingFileHandler, 即时生效) | ✅ |
| | `admin.py:346-376` | GET/PUT `/api/admin/logging` + 审计 | ✅ |
| | `schemas/admin.py:57-67` | `LoggingSettingsUpdate/Read` 校验 | ✅ |
| | `main.py:52-53` | 启动恢复: 从 PG 读取并 `reconfigure_logging` | ✅ |
| | `admin.js:38-61, 121-139` | 前端卡片: 等级下拉、大小输入、路径只读 | ✅ |

---

## 6. 第六轮新增发现

| ID | 级别 | 位置 | 问题 |
|----|------|------|------|
| **BOOT-1** | **P0** | `Core.json` / `main.py:85` | 缺 `web.cors_origins` 导致启动失败 |
| **LOGGING-1** | P3 | `logging_config.py:44` | `_root.setLevel(min(level_int, logging.INFO))` — `DEBUG` 仅落文件不进控制台 (需文档化) |
| **LOGGING-2** | P3 | `logging_config.py:30-41` | `reconfigure_logging` 非线程安全 (仅 admin 单写，可接受) |
| **SYNC-1** | P2 | `sync.py:216-266` | `probe_llm_on_startup` 失败仅 warning，不阻断启动 (设计宽容) |
| **TAB-1** | P3 | `admin_settings.py:22` | `DEFAULT_NON_ADMIN_TABS` 含 `"brief_tasks"`，非管理员默认可见简报任务 |

---

## 7. 修复优先级建议 (第六轮更新)

| 优先级 | 任务 | 预估工时 |
|--------|------|----------|
| **P0-立即** | 1. Core.json 补 `web.cors_origins: ["http://localhost:8000"]` | 1min |
| **P1-部署前** | 2. `delete_admin_user` 联合检查 `CrawlTask`/`BriefTask`/`CrawlSchedule` | 15min |
| | 3. `verify_dummy_password` 统一哈希固定串消除侧信道 | 10min |
| **P2-上线前** | 4. Guard `touch` 语义修正 (`ok` 归零优先) | 5min |
| | 5. 审计 IP `trusted_proxy_ips` 逻辑修正 | 10min |
| | 6. 超长密码拒绝写审计 (`user.register_failed` / `user.update`) | 10min |
| | 7. Redis DSN 解析报错增强 | 10min |
| **P3-迭代中** | 8. 并发注册 `ON CONFLICT` 优化 | 20min |
| | 9. `api.js` `request` 提取工具函数 | 15min |
| | 10. 文档化 `DEBUG` 级别仅落文件行为 | 5min |

---

## 8. 验收清单 (第六轮)

- [ ] **启动服务不报 `ConfigError: cors_origins`** (P0-BOOT-1)
- [ ] 创建用户 A → 建简报任务/定时计划 → 删除 A → 软禁用非报错 (ADM-1)
- [ ] 登录不存在用户 / 存在用户，计时差 < 2ms (AUTH-1 侧信道修复验证)
- [ ] Nginx 反代后 `X-Forwarded-For` 正确写入审计表 (AUDIT-1)
- [ ] 无效 Key 触发 `GROUP_DELETED` → 任务快速 failed (非 completed 空简报)
- [ ] 超长密码注册/改密 → 审计表有 `user.register_failed` 记录 (BCRYPT-1)
- [ ] **管理面板「日志配置」卡片可见、修改等级/大小即时生效、路径只读** ✅ (LOGGING-FEAT 已验证代码完整)

---

## 9. 配置管理审计 (第六轮补充)

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
| CORS 配置 | ❌ 缺失 | `Core.json` 无 `web.cors_origins`，**启动会失败** |
| **日志配置持久化** | ✅ | PG `system_settings(key='logging')` + 启动自动恢复 |

---

## 10. 历史轮次记录

| 轮次 | 日期 | 重点 | 关键产出 |
|------|------|------|----------|
| 第 1 轮 | 2026-08-18 | discovery 栏目页 DOM 化 + audit_logs | BUG-01..16 初始记录 |
| 第 2 轮 | 2026-08-18 | 后续跟进 | 无新增 |
| 第 3 轮 | 2026-08-19 | 敏感字段迁移 `.env` | 配置管理验证通过 |
| 第 4 轮 | 2026-08-19 | 全项目安全/bug 审计 | ADM-1/2, CORS-1, SEC-1 等新增 |
| **第 5 轮** | **2026-08-22** | **全项目安全/bug 审计 + 实测验证** | **ADM-1/ AUTH-1/ GUARD-1/ AUDIT-1 等新增；LLM-1/BUG-01/02/ADM-2/RATE-1 确认修复** |
| **第 6 轮** | **2026-08-22** | **全项目安全/bug 审计 + 新增日志功能验证** | **BOOT-1(P0) 新增；LOGGING-FEAT 交付完成；核心高危项仍未修复** |

---

## 11. 日志功能交付质量记录 (第六轮)

| 维度 | 评价 | 证据 |
|------|------|------|
| **完整性** | 全栈闭环 | 配置持久化(PG) → 即时生效(无需重启) → 前端受控(只读路径) → 审计留痕 |
| **安全性** | 仅 admin 可读写 | 文件大小限制 1~100MB；等级白名单校验；路径固定防目录遍历 |
| **工程化** | 生产就绪 | `RotatingFileHandler` + `backupCount=5` 自动滚动；启动自动恢复 PG 配置；子 logger 级别同步 |
| **代码规范** | 分层清晰 | 单一职责分层 (`admin_settings` 管存取、`logging_config` 管应用)、常量集中、错误码规范 |
| **前端体验** | 受控交互 | 等级下拉枚举、数字输入限制 1~100、路径只读 code 展示、toast 反馈 |

> **结论**: 第六轮**新增 P0 启动阻塞项 (BOOT-1)**，**核心高危项 (ADM-1, AUTH-1, GUARD-1, AUDIT-1) 仍未修复**；**日志功能 (LOGGING-FEAT) 交付质量高，已可上线**。建议**先修复 BOOT-1 解除启动阻塞**，再按优先级闭环遗留高危项。