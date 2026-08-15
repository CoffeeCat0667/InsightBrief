# Changelog

本仓库所有值得记录的变更均按时间倒序记录于此。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/),版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

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