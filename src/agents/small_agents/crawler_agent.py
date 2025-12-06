# src/agents/small_agents/crawler_agent.py
import asyncio
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

# 定义一组高优先级的正文选择器
# 大多数新闻网站的内容都在这些标签里
MAIN_CONTENT_SELECTORS = "article, main, .post-content, .entry-content, .article-body, #content"

# 定义需要强制排除的噪音选择器 (包括 Cookie 弹窗、侧边栏、推荐阅读)
EXCLUDED_SELECTORS = (
    "nav, footer, header, aside, script, style, noscript, "
    ".cookie-banner, .gdpr-banner, #onetrust-banner-sdk, "  # Cookie 弹窗
    ".sidebar, .widget, .advertisement, .ad-container, "  # 广告侧边栏
    ".related-posts, .comments-area, .share-buttons"  # 推荐和评论
)


async def run_crawler_agent(url: str) -> str | None:
    """
    使用 Crawl4AI 智能抓取网页核心内容，自动去除导航和弹窗噪音。
    """
    if not url or not url.startswith("http"):
        return None

    print(f"🕷️ [Crawler] Intelligent Fetching: {url}")

    browser_config = BrowserConfig(
        headless=True,
        verbose=False,
        java_script_enabled=True,
        text_mode=True  # 优化文本提取模式
    )

    # 配置运行参数：核心是 css_selector 和 excluded_tags
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        # 【关键修改 1】指定抓取范围：只抓取页面中的正文区域
        # 如果网站包含 <article> 标签，Crawl4AI 将只返回该标签内的 Markdown
        css_selector=MAIN_CONTENT_SELECTORS,

        # 【关键修改 2】排除 CSS 选择器：强力去除导航和无关元素
        excluded_selector=EXCLUDED_SELECTORS,

        # 移除太短的文本块 (防止保留 'Read more' 这种按钮文字)
        word_count_threshold=10,
    )

    try:
        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(
                url=url,
                config=run_config
            )

            if result.success:
                # 检查抓取结果是否为空 (有时候选择器太严格可能导致抓空)
                markdown_content = result.markdown

                # 【兜底策略】如果指定选择器抓不到内容（比如网站结构很特殊），则尝试抓取全文但排除噪音
                if not markdown_content or len(markdown_content) < 100:
                    print(f"⚠️ [Crawler] Main selector failed, falling back to body crawl for {url}")
                    fallback_config = CrawlerRunConfig(
                        cache_mode=CacheMode.BYPASS,
                        excluded_selector=EXCLUDED_SELECTORS,  # 依然保持排除噪音
                        word_count_threshold=20
                    )
                    fallback_result = await crawler.arun(url=url, config=fallback_config)
                    markdown_content = fallback_result.markdown

                # 截断过长内容，保留前 6000 字符（足以包含核心新闻）
                print(f"✅ [Crawler] Scraped length: {len(markdown_content)}")
                return markdown_content[:6000]
            else:
                print(f"[Crawler] Failed: {result.error_message}")
                return None

    except Exception as e:
        print(f"[Crawler] Error: {e}")
        return None


# 本地测试代码
if __name__ == "__main__":
    async def test():
        # 使用链接进行测试
        url = " https://www.cryptointelligence.co.uk/bitcoin-mirrors-2022-market-patterns-as-correlation-nears-100/"
        content = await run_crawler_agent(url)
        print("\n--- Final Cleaned Content ---\n")
        print(content)


    asyncio.run(test())