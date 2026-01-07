# src/agents/small_agents/crawler_agent.py
import asyncio
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

# 定义一组高优先级的正文选择器
MAIN_CONTENT_SELECTORS = "article, main, .post-content, .entry-content, .article-body, #content"

# 定义需要强制排除的噪音选择器
EXCLUDED_SELECTORS = (
    "nav, footer, header, aside, script, style, noscript, "
    ".cookie-banner, .gdpr-banner, #onetrust-banner-sdk, "
    ".sidebar, .widget, .advertisement, .ad-container, "
    ".related-posts, .comments-area, .share-buttons"
)


async def run_crawler_agent(url: str) -> str | None:
    """
    使用 Crawl4AI 智能抓取网页核心内容，自动去除导航和弹窗噪音。
    [新增] 增加 3 次重试机制
    """
    if not url or not url.startswith("http"):
        return None

    print(f"🕷️ [Crawler] Intelligent Fetching: {url}")

    browser_config = BrowserConfig(
        headless=True,
        verbose=False,
        java_script_enabled=True,
        text_mode=True
    )

    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        css_selector=MAIN_CONTENT_SELECTORS,
        excluded_selector=EXCLUDED_SELECTORS,
        word_count_threshold=10,
    )

    # [新增] 重试循环
    max_retries = 3

    # 注意：我们将 AsyncWebCrawler 上下文管理器放在重试外面，复用浏览器实例
    # 如果遇到浏览器崩溃等严重错误，可能需要把它放里面，但通常这样够了
    try:
        async with AsyncWebCrawler(config=browser_config) as crawler:
            for attempt in range(max_retries):
                try:
                    result = await crawler.arun(url=url, config=run_config)

                    if result.success:
                        markdown_content = result.markdown

                        # 【兜底策略】
                        if not markdown_content or len(markdown_content) < 100:
                            print(f"⚠️ [Crawler] Main selector failed, trying fallback... ({url})")
                            fallback_config = CrawlerRunConfig(
                                cache_mode=CacheMode.BYPASS,
                                excluded_selector=EXCLUDED_SELECTORS,
                                word_count_threshold=20
                            )
                            fallback_result = await crawler.arun(url=url, config=fallback_config)
                            markdown_content = fallback_result.markdown

                        if markdown_content and len(markdown_content) >= 50:
                            print(f"✅ [Crawler] Scraped length: {len(markdown_content)}")
                            return markdown_content[:6000]
                        else:
                            raise ValueError("Content too short or empty after fallback")
                    else:
                        raise ValueError(f"Crawl failed: {result.error_message}")

                except Exception as e:
                    if attempt == max_retries - 1:
                        print(f"❌ [Crawler] Failed after {max_retries} attempts: {e}")
                        return None

                    print(f"⚠️ [Crawler] Retry ({attempt + 1}/{max_retries}) for {url}: {e}")
                    await asyncio.sleep(2)  # 等待2秒重试

    except Exception as e:
        print(f"❌ [Crawler] Browser Init Error: {e}")
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