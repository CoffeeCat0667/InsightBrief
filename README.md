# InsightBrief

> 多源新闻智能抓取与翻译阅读 CLI —— **Ver0.1.0**

选择媒体即抓取最新新闻:中文直显,外文自动翻译成简体中文。

## 特性

- **25+ 媒体源**,分五大类:国内综合 / 国内官媒 / 外媒综合 / 外媒财经 / 外媒科技
- **自动发现**:RSS / 栏目页两种发现模式,无需手工提供文章链接
- **智能抓取**:
  - 主流站点用 `curl_cffi`(Chrome TLS 指纹),直连失败自动走代理重试
  - CSR 前端渲染站点(如 The Verge)自动切换 `Playwright` 真实浏览器渲染
  - 付费墙摘要型站点(如 Washington Post)走 RSS 摘要模式
- **自动翻译**:外文新闻经 deep-translator(Google 免费接口)翻译为简体中文,中文新闻原样显示
- **结构化输出**:正文/图片/视频分段提取,pydantic 模型规范化,支持 JSON 落盘

## 安装

要求:Python 3.10+ (开发环境 3.14 验证通过)

```bash
pip install -r requirements.txt
python -m playwright install chromium   # CSR 站点浏览器内核
```

## 使用

```bash
python main.py
```

按菜单输入媒体编号,即抓取该媒体**最新一条**新闻并展示。`q` 退出。

自定义代理(默认 `http://127.0.0.1:7897`,空值禁用):

```bash
set CRAWL_PROXY=http://127.0.0.1:7897   # Windows
export CRAWL_PROXY=http://127.0.0.1:7897  # Linux/macOS
```

## 目录结构

```
InsightBrief/
├── main.py                     # CLI 主程序入口
├── Core/                       # 通用核心
│   ├── models.py               # pydantic 数据模型
│   ├── fetchers.py             # CurlCffiFetcher / PlaywrightFetcher / 代理配置
│   ├── base.py                 # BaseNewsCrawler 抽象基类
│   └── generic.py              # GenericArticleCrawler 通用解析基类
├── Services/
│   ├── discovery.py            # 媒体源注册表 + 文章链接自动发现 (RSS/栏目页)
│   └── translator.py           # 中文判断 + deep-translator 翻译服务
├── Clawer/                     # 各平台爬虫 (按类别分组, 薄子类)
│   ├── domesticGeneral/        # 国内综合: 网易 / 搜狐
│   ├── domesticOfficialMedia/  # 国内官媒: 新华网 / 人民网 / 军事网
│   ├── foreignGeneral/         # 外媒综合: BBC / CNN / AP / 卫报 ...
│   ├── foreignFinance/         # 外媒财经: CNBC / Forbes / Fortune ...
│   └── foreignTechnology/      # 外媒科技: TechCrunch / Verge / Wired ...
├── requirements.txt
├── CHANGELOG.md
└── LICENSE                     # Apache-2.0
```

## 新增媒体源

1. **完整正文源**:`Clawer/<分类>/<平台>_news/` 下建薄子类(继承 `GenericArticleCrawler`,配置 `base_url` / `content_xpath`;非标准正文块用 `block_xpath`;CSR 站设 `fetch_strategy = PlaywrightFetcher`)
2. **RSS 摘要源**(付费墙站):仅需在 `Services/discovery.py` 注册 RSS 源,菜单自动并入
3. `main.py` 的 `MEDIA_CN_NAMES` 补中文名(可选)

详见 `CHANGELOG.md` 与代码注释。

## 许可证

[Apache License 2.0](LICENSE) © 2026 CoffeeCat0667