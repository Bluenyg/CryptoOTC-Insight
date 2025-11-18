# src/core/collectors.py
import asyncio
# import websockets  <-- [FIX] 不再需要 websocket 库
import json
import time
from typing import Set

from fastmcp import Client
from fastmcp.client.transports import SSETransport

from src.core.database import async_session
from src.core.models import SentimentMetrics

# --- [FIX] 导入需要直接调用的组件 ---
from src.agents.small_agents.pipeline import small_agent_graph
from src.schemas.data_models import RawDataInput
# ----------------------------------

from config.settings import settings

# --- 配置 ---
NEWS_MCP_URL = "http://localhost:8001/sse"
SENTIMENT_MCP_URL = "http://localhost:8002/sse"
# MAIN_SERVER_WS = "ws://localhost:8000/ws/data_ingest"  <-- [FIX] 不再需要

NEWS_POLL_INTERVAL = 300
SENTIMENT_POLL_INTERVAL = 300

# 1. 新闻采集器
seen_article_titles: Set[str] = set()


async def run_news_collector():
    """
    后台任务:轮询 News MCP, 并直接调用 Small Agent 进行处理 (不再走 WebSocket)。
    """
    await asyncio.sleep(10)
    print(f"[NewsCollector]: 启动... (轮询 News MCP at {NEWS_MCP_URL})")

    while True:
        try:
            news_transport = SSETransport(url=NEWS_MCP_URL, sse_read_timeout=60.0)
            news_client = Client(news_transport, timeout=15.0)

            async with news_client:
                print("[NewsCollector]: 正在拉取新闻...")
                result = await news_client.call_tool(
                    "get_latest_news",
                    arguments={}
                )

                news_blob = ""
                if hasattr(result, 'content') and result.content:
                    for item in result.content:
                        if hasattr(item, 'text'):
                            news_blob += item.text

                if news_blob and news_blob != "No recent news available.":
                    articles = news_blob.strip().split('\n')
                    new_articles_count = 0

                    for article_line in articles:
                        if " (Published: " in article_line:
                            title = article_line.split(" (Published: ")[0]
                            if title not in seen_article_titles:
                                new_articles_count += 1
                                seen_article_titles.add(title)

                                # --- [FIX] 直接构造数据对象 ---
                                raw_data = RawDataInput(
                                    source="mcp-news",
                                    timestamp=time.time(),
                                    content=article_line
                                )

                                # --- [FIX] 直接调用 Agent (内部函数调用) ---
                                # 这里的 ainvoke 是异步的，会在后台处理
                                asyncio.create_task(
                                    small_agent_graph.ainvoke({"raw_data": raw_data})
                                )

                    if new_articles_count > 0:
                        print(f"[NewsCollector]: 已将 {new_articles_count} 条新新闻发送给 SmallAgent。")
                    else:
                        print("[NewsCollector]: 没有新新闻。")

        except Exception as e:
            print(f"[NewsCollector] 错误: {e}")
            import traceback
            traceback.print_exc()
            print("[NewsCollector]: 等待60秒后重试...")
            await asyncio.sleep(60)
            continue

        await asyncio.sleep(NEWS_POLL_INTERVAL)


# 2. 情绪采集器
ASSETS_TO_TRACK = ["bitcoin", "ethereum"]
DATA_OFFSET_DAYS = 35


async def run_sentiment_collector():
    """
    后台任务:轮询 Sentiment MCP, 将原始指标 *直接* 写入数据库。
    """
    await asyncio.sleep(25)
    print(f"[SentimentCollector]: 启动... (轮询 Sentiment MCP at {SENTIMENT_MCP_URL})")

    while True:
        try:
            sentiment_transport = SSETransport(url=SENTIMENT_MCP_URL, sse_read_timeout=60.0)
            sentiment_client = Client(sentiment_transport, timeout=60.0)

            async with sentiment_client:
                print(f"[SentimentCollector]: 正在拉取 {DATA_OFFSET_DAYS} 天前的指标...")
                metrics_data = []

                for asset in ASSETS_TO_TRACK:
                    try:
                        volume_result = await asyncio.wait_for(
                            sentiment_client.call_tool(
                                "get_social_volume",
                                arguments={"asset": asset, "days": 1, "offset_days": DATA_OFFSET_DAYS}
                            ),
                            timeout=30.0
                        )

                        volume_text = ""
                        if hasattr(volume_result, 'content') and volume_result.content:
                            for item in volume_result.content:
                                if hasattr(item, 'text'):
                                    volume_text += item.text
                        if volume_text:
                            metrics_data.append((asset, "social_volume", volume_text))

                        balance_result = await asyncio.wait_for(
                            sentiment_client.call_tool(
                                "get_sentiment_balance",
                                arguments={"asset": asset, "days": 1, "offset_days": DATA_OFFSET_DAYS}
                            ),
                            timeout=30.0
                        )

                        balance_text = ""
                        if hasattr(balance_result, 'content') and balance_result.content:
                            for item in balance_result.content:
                                if hasattr(item, 'text'):
                                    balance_text += item.text
                        if balance_text:
                            metrics_data.append((asset, "sentiment_balance", balance_text))

                    except asyncio.TimeoutError:
                        print(f"[SentimentCollector] 工具调用超时 ({asset})")
                    except Exception as tool_error:
                        print(f"[SentimentCollector] 调用工具出错 ({asset}): {tool_error}")

                entries_to_add = []
                for asset, metric_type, result_str in metrics_data:
                    if not result_str:
                        print(f"[SentimentCollector] {asset} 的 {metric_type} 返回空结果")
                        continue

                    try:
                        if " is " in result_str:
                            value_part = result_str.split(" is ")[1]
                            value_str = value_part.split()[0].replace(",", "").rstrip(".")
                            value_float = float(value_str)

                            entries_to_add.append(
                                SentimentMetrics(
                                    asset=asset,
                                    metric_name=f"{metric_type}_{asset}",
                                    value=value_float
                                )
                            )
                            print(f"[SentimentCollector] 准备写入: {asset} - {metric_type} = {value_float}")
                        else:
                            print(f"[SentimentCollector] 无法解析格式 (API返回错误?): {result_str}")
                    except (ValueError, IndexError) as parse_error:
                        print(f"[SentimentCollector] 无法解析值: {result_str} - {parse_error}")

                if entries_to_add:
                    try:
                        async with async_session() as session:
                            async with session.begin():
                                session.add_all(entries_to_add)
                        print(f"[SentimentCollector]: {len(entries_to_add)} 个指标批量写入数据库完成。")
                    except Exception as db_error:
                        print(f"[SentimentCollector] 数据库批量写入错误: {db_error}")
                else:
                    print("[SentimentCollector]: 没有可写入数据库的新指标。")

        except Exception as e:
            print(f"[SentimentCollector] 错误: {e}")
            import traceback
            traceback.print_exc()
            print("[SentimentCollector]: 等待60秒后重试...")
            await asyncio.sleep(60)
            continue

        await asyncio.sleep(SENTIMENT_POLL_INTERVAL)


async def start_all_collectors():
    """启动所有采集器"""
    await asyncio.gather(
        run_news_collector(),
        run_sentiment_collector()
    )


if __name__ == "__main__":
    # 用于测试
    asyncio.run(start_all_collectors())