# Buglist — Code Review 记录

> **审查对象**: `039d33b` (discovery) + `5c09866` (audit_logs)
> **审查日期**: 2026-08-18 (第五轮更新: 2026-08-22)
> **方式**: 只读审查 + 修复; 附文件:行号证据
> **结论**: 无 P1/P2; 所有已知问题已修复或确认不存在

---

## 0. 严重度分布

| 级别 | 数量 | 说明 |
|---|---|---|
| P1 | 0 | — |
| P2 | 0 | — |
| P3 | 1 | 记录在案, 本地可接受 |
| Fixed | 18 | 全部已修复 |

---

## 1. P3 — 记录在案, 本地可接受

| ID | 位置 | 问题 |
|---|---|---|
| BUG-08 | 审计 detail (register/login) | 明文存 username/email (PII); 若将来对外需脱敏+保留策略。**已核验: 无密码/hash/token 入审计** |

---

## 2. 已修复项

| ID | 修复位置 | 修复内容 | 状态 |
|---|---|---|---|
| CORS-1 | `main.py:78-84`, `config.py:103-108`, `.env.example` | `allow_origins` 从 `.env` `IB_CORS_ORIGINS` 读取逗号分隔域名列表; 未配置时 fallback `["*"]` | Fixed |
| SEC-1 | `Client/js/api.js:8-12,35` | `toast()` 添加 `_escHtml()` 转义, innerHTML 不再注入原始 msg | Fixed |
| BUG-01 | `tasks.py:202`, `briefs.py:149` | cancel 端点改用 `require_admin` | Fixed |
| BUG-02 | `discovery.py:203` | `_in_ad_container` 改用 `ancestor-or-self::*[@class]` | Fixed |
| BUG-04 | `security.py:44-49` | bcrypt 超 72 字节抛 `ValueError`, 不再静默截断 | Fixed |
| BUG-05 | `config.py:84-85` | admin 凭据从 `.env` 读取, `_env_required()` 缺失则启动失败, 无硬编码默认值 | Fixed |
| BUG-06 | `audit_logs/__init__.py:23-37` | XFF 仅在 `peer_ip in trusted_proxy_ips` 时读取, 正确防伪造 | 正确实现 |
| BUG-07 | `auth.py:120`, `security.py:74-80` | 不存在用户执行 `verify_dummy_password()` 真 bcrypt, 消除计时侧信道 | Fixed |
| BUG-09 | `discovery.py:195-198` | `" ad"` 子串改为 `_AD_HINT_RE` 正则 + 词边界断言 | Fixed |
| BUG-10 | `discovery.py:233-253` | URL 同时出现在新闻区和广告区时从 `ad_urls` 集合剔除 | Fixed |
| BUG-11 | `auth.py:77-91` | `IntegrityError` 捕获兜底返回 409 | Fixed |
| BUG-12 | `discovery.py:236` | parsel/lxml 自动解码 HTML 实体, `@href` 已是 `&`, 无需手动处理 | 不存在 |
| BUG-13 | `briefs.py:71-85` | dispatch 异常兜底改为 `except Exception`, 审计始终写入 | Fixed |
| BUG-14 | `audit_logs.py:35` | 改为 `if user_id is not None:` | Fixed |
| BUG-15 | cancel 端点 | `requested=False` 时不写审计, 无噪音 | 不存在 |
| BUG-16 | `user.py:52`, `f7a8b9c0d1e2` | `action` 索引已存在于 ORM 模型和迁移; write_audit 调用点约 30 处 | Fixed |
| PERF-1 | `Client/js/api.js` | 无 `fetchJSON`, 无 monkey-patch, 直接调用原生 `fetch()` | Fixed |
| ADM-3 | `admin.py:207` | User 只有 `role_id` 无 `role_name` 列, 检查一致 | 正确 |
| CFG-1 | `config.py:142-162` | Redis 密码从 `IB_REDIS_PASSWORD` 读取注入, db.json 不含密码 | Fixed |
| ADM-2 | `admin_settings.py:102-112` | LLM 写入后清除 `get_llm_provider` 缓存 | Fixed |

---

## 3. 已核验安全/正确的项

- 无 SQL 注入: 全部 ORM 参数化
- 无 SSRF 面扩大: discovery 只抓配置内 column_url
- 无 secrets 泄漏: register/login 审计 detail 只含 `{}`
- 无 CSRF 风险: Bearer header 认证
- FastAPI 参数顺序: 所有 `request` 均置于 Depends 之前
- PageParams 分页有界 (page_size <= 100)
- JWT sub 每请求查库校验 is_active
- AuditLog 表已含 user_id + action 索引
- write_audit 独立会话 + 异常吞掉, 审计不炸主业务
