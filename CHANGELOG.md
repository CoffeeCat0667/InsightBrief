# Changelog

本仓库所有值得记录的变更均按时间倒序记录于此。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/),版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Ver0.1.1] - 2026-08-15

配置抽取重构:硬编码配置收归 `Config/` 目录,全平台全源改由唯一加载器供给。

### 变更

- **配置数据与加载器统一入 `Config/`**:`Core.json`(代理/UA/超时重试/路径/playwright/generic 阈值)、`Clawer.json`(25 平台 base_url/xpath/UA/fetch 策略覆盖)、`Services.json`(27 源注册表 + translator 参数)、`config.py`(唯一加载器:lru_cache、必填校验、`CRAWL_PROXY` 等 env 覆盖)
- 加载器从 `Core/config.py` 迁至 `Config/config.py`,全仓配置引用统一为 `from Config.config import ...`,不再从 `Core.fetchers` re-export
- 25 个平台爬虫类属性(含 4 个自定义平台的 UA 与 `get_base_url`)改由 `platform_config(pid)` 注入
- `Services/discovery.py` 源注册表(platform_patterns/link_patterns/sources/domestic_source_ids)全部改由配置构建;CNN 首页内嵌 JSON 提取保留为代码 custom 源
- `Services/translator.py` 翻译 provider/source/target/chunk_size 配置化

### 修复

- Ars Technica 直连返回 HTTP 202 反爬质询页时不再直接失败:非 200 状态码同样触发一次代理回退(代理可取得完整正文)

### 验证

- 全量 26 平台真实抓取 26/26 通过(合计 235s);25 平台 import/属性一致性校验通过
- 端点:新华网 116 链接、guardian RSS 45 条、bbc_rss 33 条(www.bbc.co.uk→www.bbc.com 替换生效)、arstechnica 202→代理回退成功

## [Ver0.1.0] - 2026-08-15

首个可运行版本发布。

### 新增

- **CLI 主程序入口** (`main.py`):分类菜单选择媒体 → 自动发现最新新闻 → 抓取展示;中文直显,外文自动翻译为简体中文
- **通用核心** (`Core/`):
  - `models.py`:NewsItem / NewsMetaInfo / ContentItem 等 pydantic 数据模型
  - `fetchers.py`:`CurlCffiFetcher`(Chrome TLS 指纹抓取,直连失败自动代理重试)、`PlaywrightFetcher`(CSR 渲染站)、`CRAWL_PROXY` 代理配置
  - `base.py`:`BaseNewsCrawler` 抽象基类(重试/校验/JSON 持久化管线)
  - `generic.py`:`GenericArticleCrawler` 通用解析(JSON-LD → og:meta → 容器探测 → 块提取),支持 `content_xpath` / `block_xpath` 自定义
- **25 个平台爬虫**(`Clawer/`):国内综合 2 + 国内官媒 3 + 外媒综合 8 + 外媒财经 5 + 外媒科技 7
- **文章链接自动发现** (`Services/discovery.py`):26 个媒体源注册表,RSS / 栏目页两种发现模式,平台 URL 识别
- **翻译服务** (`Services/translator.py`):deep-translator(Google 免费接口),复用代理配置,失败降级显示原文
- **RSS 摘要模式**:付费墙站点(Washington Post)不走文章页,直接展示 RSS 标题/摘要
- 版本标记 `__version__ = "0.1.0"`

### 修复

- 正文提取混入内嵌 `<script>/<style>/<template>` 文本噪声(如人民网 `showPlayer(...)` 视频脚本)
- `block_xpath` 模式下非标准标签(如 NYT 的 `div.article-paragraph`)被默认标签集过滤导致正文丢失
- NYT 中文版正文容器错配(`section[articleBody]` → `section.article-body`)

### 已知限制

- www.nytimes.com 英文站受 DataDome 反爬保护,正文不可抓(以 cn.nytimes.com 中文版替代)
- Washington Post / 部分外媒为硬付费墙,仅提供 RSS 摘要
- Ars Technica 存在反爬 challenge(HTTP 202)风险
- CNN live-blog 直播页(时间线流)无正文结构,通用解析器无法提取