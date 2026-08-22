# [Bug] BBC 中国专题抓取失败:跨源同稿触发 URL 唯一约束后会话中毒,级联致整批失败

> 状态:未修复(2026-08-20)
> 类型:Bug / 抓取
> 影响范围:所有多源同稿(URL 相同)的抓取源,首当其冲 `bbc_china`(与 `bbc_rss` 内容高度重叠)

## 现象

- 抓取任务中 `bbc_china` 源被整体判为「抓取失败」,无任何文章入库;
- 日志出现大量形如:

```
[bbc_china] 落库失败 https://www.bbc.com/news/articles/cp9e2ex3ekyo?...:
  This Session's transaction has been rolled back due to a previous exception during flush.
  Original exception was: (psycopg.errors.UniqueViolation)
  duplicate key value violates unique constraint "uq_articles_url"
  DETAIL:  Key (url)=(https://www.bbc.com/news/articles/cd0x9mjjmgjo?...) already exists.
[task 4] 源 bbc_china 抓取失败: This Session's transaction has been rolled back ...
```

- 注意:报错正文指向的 URL(`cd0x9mjjmgjo`)与「落库失败」的 URL(`cp9e2ex3ekyo`、`cx27mjvxgg1o`)**不是同一篇**——后者只是被前者的失败连带拖垮。

## 复现步骤

1. 先抓取 `bbc_rss`(已包含恒大庆典报道 `cd0x9mjjmgjo`),入库成功;
2. 再抓取 `bbc_china`(RSS 内容与 bbc_rss 高度重叠,同一篇文章重复出现);
3. 批次内第一篇与 `bbc_rss` 相同的文章触发 `uq_articles_url` 唯一冲突;
4. 异常被单篇捕获后继续循环,但 SQLAlchemy 会话未回滚 → 批次内后续所有文章级联失败;
5. 任务管理器将整源判为失败。

## 根因分析(两个独立缺陷叠加)

### 缺陷 1:应用层去重键与数据库约束不一致

- 模型层:`Article` 的唯一约束是 `(source_id, external_id)`(`uq_articles_source_external`);
- 数据库层:`url` 列另有 `unique=True`,全局唯一(`uq_articles_url`,alembic 初始迁移 `bd1d9d7a28fa`);
- `upsert_article` 的预检查只按 `(source_id, external_id)` 查重,**不查全局 URL**;
- 跨源同稿(`bbc_rss` 与 `bbc_china` 相同 URL,但 source_id 不同)通过预检查 → flush 时撞上数据库 URL 唯一约束。

### 缺陷 2:flush 失败后未回滚,会话中毒级联

- `insert_articles_from_links` 的异常分支只做 `stats["failed"] += 1` 与日志,**未调用 `session.rollback()`**;
- SQLAlchemy 中,一次 flush 失败后会话进入「失败事务态」,后续任何 flush 都会抛
  `PendingRollbackError`("transaction has been rolled back due to a previous exception during flush");
- 于是批次内剩余文章(即使完全正常)全部落库失败 → 单篇失败演变为整源失败。

## 修复

`Services/App/ingest.py`,两处改动:

```python
# upsert_article: 预检查追加 URL 全局查重(跨源同稿视为已存在,不触发 DB 冲突)
existing = session.scalar(
    select(Article).where(
        Article.source_id == source_id, Article.external_id == ext
    )
)
if existing is not None:
    return existing, False
existing = session.scalar(select(Article).where(Article.url == news_item.news_url))
if existing is not None:
    return existing, False
```

```python
# insert_articles_from_links 异常分支: 重置失败事务, 防止会话中毒级联失败
except Exception as exc:  # 单篇失败不影响批次
    session.rollback()
    logger.warning("[%s] 落库失败 %s: %s", source_id, link.url, exc)
    stats["failed"] += 1
```

## 验证

修复后对 `bbc_china` 单独重抓(任务 5):

| 指标 | 结果 |
|---|---|
| 任务状态 | completed |
| 发现 / 插入 / 已存在 / 失败 | 9 / 8 / 1 / 0 |
| 此前级联失败的 URL | 全部正常入库 |
| 冲突文章 | 正确计为「已存在」跳过 |
| 日志错误数 | 0 |

## 遗留备注

- 跨源同稿现在只保留首次抓取的结果(跳过策略,与同源已存在的语义一致),跨源不会重复占库;
- `CrawlTaskArticle` 关联仍会写入,抓取任务的源文章计数不受影响;
- 建议后续在巡检中关注其它「RSS 源之间内容重叠」的组合(如各语种 BBC 子源)