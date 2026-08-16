# -*- coding: utf-8 -*-
"""InsightBrief Web 后端应用包 (FastAPI 骨架/鉴权/数据层/Worker 逐步接入)。

分层:
- App.models  SQLAlchemy ORM (13 张表, DB 唯一真相源)
- App.schemas pydantic API 契约 (统一响应/错误码/分页)
- App.db      engine/session
- App.sync    配置 -> sources 表同步 (启动时执行)
"""