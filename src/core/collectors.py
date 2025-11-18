import asyncio
import websockets
import json
import time
from typing import Set

from fastmcp import Client
from fastmcp.client.transports import SSETransport

from src.core.database import async_session
from src.core.models import SentimentMetrics

from config.settings import settings

# --- 配置 ---
NEWS_MCP_URL = "http://localhost:8001/sse"
SENTIMENT_MCP_URL = "http://localhost:8002/sse"
MAIN_SERVER_WS = "ws://localhost:8000/ws/data_ingest"

NEWS_POLL_INTERVAL = 300
SENTIMENT_POLL_INTERVAL = 300

# 1. 新闻采集器
seen_article_titles: Set[str] = set()


async def run_news_collector():
    """
    后台任务:轮询 News MCP, 将新新闻推送到 WebSocket 进行NLP处理。
    """
    await asyncio.sleep(10)
    print("[NewsCollector]: 启动... (轮询 News MCP at port 8001)")

    while True:
        try:
            # 创建 SSETransport,只传递 url 参数
            news_transport = SSETransport(url=NEWS_MCP_URL)

            # 创建 Client,设置超时参数
            news_client = Client(news_transport, timeout=60.0)

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
                    new_articles_found = 0

                    try:
                        async with websockets.connect(
                                MAIN_SERVER_WS,
                                timeout=10,
                                ping_timeout=20
                        ) as websocket:
                            for article_line in articles:
                                if " (Published: " in article_line:
                                    title = article_line.split(" (Published: ")[0]
                                    if title not in seen_article_titles:
                                        new_articles_found += 1
                                        seen_article_titles.add(title)
                                        raw_data = {
                                            "source": "mcp-news",
                                            "timestamp": time.time(),
                                            "content": article_line
                                        }
                                        await websocket.send(json.dumps(raw_data))
                                        await asyncio.wait_for(websocket.recv(), timeout=5.0)

                            print(f"[NewsCollector]: 拉取完成。发现 {new_articles_found} 条新新闻。")
                    except Exception as ws_error:
                        print(f"[NewsCollector] WebSocket连接错误: {ws_error}")
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


async def run_sentiment_collector():
    """
    后台任务:轮询 Sentiment MCP, 将原始指标 *直接* 写入数据库。
    """
    await asyncio.sleep(15)
    print("[SentimentCollector]: 启动... (轮询 Sentiment MCP at port 8002)")

    while True:
        try:
            # 创建 SSETransport,只传递 url 参数
            sentiment_transport = SSETransport(url=SENTIMENT_MCP_URL)

            # 创建 Client,设置超时参数
            sentiment_client = Client(sentiment_transport, timeout=60.0)

            async with sentiment_client:
                print("[SentimentCollector]: 正在拉取情绪指标...")
                metrics_data = []

                for asset in ASSETS_TO_TRACK:
                    try:
                        volume_result = await asyncio.wait_for(
                            sentiment_client.call_tool(
                                "get_social_volume",
                                arguments={"asset": asset, "days": 1}
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
                                arguments={"asset": asset, "days": 1}
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

                # 处理数据库写入逻辑
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
                            print(f"[SentimentCollector] 无法解析格式: {result_str}")
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