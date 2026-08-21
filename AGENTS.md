# AGENTS.md — InsightBrief

## Startup

```bash
pip install -r requirements.txt
python -m playwright install chromium       # CSR site crawler needs Chromium
alembic upgrade head                        # DSN from Config/db.json; @ → %40
python -m uvicorn Services.App.main:app --host 127.0.0.1 --port 8000
```

API docs: `http://127.0.0.1:8000/docs` (disabled if `Config/Core.json` `web.disable_docs=true`).

CLI (legacy/test only): `python -m Services.CLI.main`

## Verification

No pytest suite. Verification is manual E2E:

```bash
python -m compileall -q .                   # Python syntax + import smoke
for f in Client/js/*.js Client/js/views/*.js; do node --check "$f"; done  # JS syntax
git diff --check                            # whitespace
```

After code changes, also verify: health endpoint, OpenAPI routes, SPA fallback deep-links, auth 401/403.

## Architecture

- **FastAPI** entry: `Services/App/main.py`. Lifespan bootstraps DB, syncs config→DB, seeds roles/admin, starts schedule thread.
- **SPA frontend**: `Client/` — vanilla HTML/CSS/JS, zero build. FastAPI serves static files with SPA fallback for History routes. URLs have no `#`.
- **Config is JSON-only** (`Config/*.json` loaded by `Config/config.py` with `lru_cache`). No env vars read at runtime. Changing config files requires process restart.
- **Alembic** migrations in `alembic/versions/`. DSN injected from `Config/db.json` in `alembic/env.py`. Current head: `h9c0d1e2f3a4`.
- **15 ORM models** in `Services/App/models/`. API contract: `{success, data, error}` via `schemas/common.py`.
- **SSE** is the only progress channel (no polling fallback). Client uses fetch+ReadableStream (not EventSource, to carry auth header).
- **ThreadPoolExecutor(4)** runs crawl/brief tasks. Task manager pushes events to Redis for SSE replay.
- **Schedule manager**: daemon thread (15s poll) in `Services/App/schedule_manager.py`. Persists in `crawl_schedules` table, restored on restart.
- **Crawler hierarchy**: `Core/base.py` (ABC) → `Core/generic.py` (GenericArticleCrawler) → `Clawer/<category>/<platform>_news/` (thin subclasses).
- **LLM brief pipeline**: `Report/processor.py` orchestrates classify→summarize/translate→compose. Providers in `Report/llm/openai_v1.py` (OpenAI V1 compatible, reads PG `system_settings`).

## Gotchas

- **No env vars at runtime.** `Config/*.json` are the sole config source. `.env.example` is documentation only.
- **`lru_cache` on config loaders.** Modified JSON files require restart to take effect.
- **`buglist.md` is untracked.** Do not commit or push it.
- **`CONTEXT.md`, `DEPENDENCIES.md`, `GAP_ANALYSIS.md`** are gitignored session-memory files. Do not commit.
- **History routes need SPA fallback.** If adding frontend routes, they must work with `Client/index.html` as catch-all. Unknown `/api/*` must remain 404.
- **LLM `api_key` stored plaintext** in `Config/LLM.json` and `system_settings` DB. Manager probe writes both JSON+PG on success only. api_key never written to audit logs.
- **`domestic_max_ratio`**: 0–100, 100 = no limit. Foreign sources crawled first; domestic quota = `floor(F*R/(100-R))`.
- **Crawl task idempotency**: overlapping source sets with a running task → 409.
- **Auto brief**: only `inserted` (new) articles from the current crawl. No brief on empty/failed/cancelled crawl.
- **Admin-only endpoints**: task cancel, all `/api/admin/*`, `/api/audit-logs`.
- **`Config/db.json` DSN**: `@` in password must be URL-encoded as `%40`.
- **`Core/base.py` timeout constant 30** is only a fallback for CLI/unknown platforms. Real timeout = per-platform `fetch_timeout` in `Config/Clawer.json`.

## File Ownership

| Directory | Purpose |
|---|---|
| `Services/App/` | FastAPI backend — routers, models, schemas, security, task/schedule managers |
| `Services/audit_logs/` | Audit write helper (independent session, failure-safe) |
| `Services/discovery.py` | Source registry (DB-backed), link discovery |
| `Services/translator.py` | Google Translate fallback (deep-translator) |
| `Core/` | Crawler core — fetchers, generic parser, base ABC, pydantic models |
| `Clawer/` | 25 platform crawlers (thin subclasses of GenericArticleCrawler) |
| `Client/` | SPA frontend (vanilla JS, no build step) |
| `Report/` | LLM brief system — provider, prompts, operators, processor |
| `Config/` | JSON config files + `config.py` loader |
| `Tools/` | Ops tools (timeout measurement) |
| `alembic/` | Database migrations (6 versions) |

## Code Conventions

- Python 3.10+. Uses `from __future__ import annotations` throughout.
- SQLAlchemy 2.0 style ORM (`Services/App/models/`).
- API responses use `schemas/common.py` helpers: `ok()`, `fail()`, `Page[T]`.
- Frontend: `Client/js/api.js` wraps all HTTP; `sse.js` parses SSE via fetch ReadableStream; `router.js` handles History API routing.
- Security: bcrypt + JWT (HS256) + role-based auth. Login rate-limiting by IP. Dummy bcrypt for non-existent users.
- All config is validated at load time (`_require()` in `config.py`). Missing keys → `ConfigError` at startup.

## Config Files

| File | Purpose |
|---|---|
| `Config/Core.json` | Proxy, UA, retry, Playwright, JWT secret, admin credentials, rate limit, trusted proxies, docs toggle |
| `Config/Clawer.json` | Per-platform base_url, xpaths, UA, fetch_strategy, `fetch_timeout` |
| `Config/Services.json` | 27 source registry, platform link patterns, translator settings, `domestic_source_ids` |
| `Config/LLM.json` | base_url, api_key, model_id, timeout, retry, operator params |
| `Config/db.json` | PostgreSQL DSN + pool, Redis host/port/db |

## Next Planned Work

See `TODO.md` — migrate sensitive fields from `Config/*.json` to `.env`:
- `Core.json`: proxy.default, auth.jwt_secret, auth.admin_username, auth.admin_password
- `db.json`: postgres.dsn, redis.password
- `LLM.json`: base_url, api_key, model_id
- Requires changes in `config.py`, `security.py`, `db.py`, `alembic/env.py`, `sync.py`, `admin_settings.py`
