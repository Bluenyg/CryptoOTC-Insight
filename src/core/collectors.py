# src/core/collectors.py
import asyncio
import httpx
import time
from datetime import datetime, timedelta
from typing import Set, List, Dict, Any

# 导入可以直接调用的组件 (本地直接调用，不走网络)
from src.agents.small_agents.pipeline import small_agent_graph
from src.schemas.data_models import RawDataInput

# --- 配置 ---
# 外部数据源 API
FETCH_API_URL = "http://api.ibyteai.com:15008/10Ai/dataCenter/crypto/fetchCryptoPanic"
HEADERS = {'Content-Type': 'application/json'}

# 轮询间隔 (秒)
NEWS_POLL_INTERVAL = 60

# 记录已处理的 objectId，防止重复处理
seen_object_ids: Set[str] = set()


async def fetch_crypto_news_from_api(client: httpx.AsyncClient, coin_type: int) -> List[Dict[str, Any]]:
    """
    调用 fetchCryptoPanic 接口获取新闻
    coin_type: 1 (BTC), 2 (ETH)
    """
    # 获取过去 24 小时的数据
    end_time = datetime.now()
    start_time = end_time - timedelta(hours=24)

    # 构造请求体
    json_data = {
        "type": coin_type,
        "startTime": start_time.strftime("%Y-%m-%d %H:%M:%S"),
        "endTime": end_time.strftime("%Y-%m-%d %H:%M:%S")
    }

    try:
        response = await client.post(FETCH_API_URL, headers=HEADERS, json=json_data, timeout=15.0)

        if response.status_code != 200:
            print(f"[NewsCollector] API 请求失败 (Type {coin_type}) Code: {response.status_code}")
            return []

        # 接口返回的是 JSON 列表
        return response.json()
    except Exception as e:
        print(f"[NewsCollector] 请求异常 (Type {coin_type}): {e}")
        return []


async def run_news_collector():
    """
    后台任务: 轮询外部 API 获取新闻，并直接发送给 Small Agent 进行处理。
    """
    # 启动延迟，等待其他组件加载
    await asyncio.sleep(5)
    print(f"[NewsCollector]: 启动... (Target API: {FETCH_API_URL})")

    async with httpx.AsyncClient() as client:
        while True:
            try:
                # 1. 拉取数据
                all_news_items = []

                # 并行拉取 BTC 和 ETH 新闻
                # (由于 API 是独立的，顺序调用或并发调用皆可，这里用顺序调用简单稳定)
                btc_news = await fetch_crypto_news_from_api(client, 1)
                eth_news = await fetch_crypto_news_from_api(client, 2)

                if isinstance(btc_news, list): all_news_items.extend(btc_news)
                if isinstance(eth_news, list): all_news_items.extend(eth_news)

                new_count = 0

                # 2. 处理数据
                for item in all_news_items:
                    # 获取唯一标识
                    obj_id = item.get('objectId')

                    # [优化] 检查 newsTag
                    # 如果 newsTag 已经不为 0 (说明已被处理过)，则跳过，避免重复消耗 Token
                    # 假设 API 返回的数据包含 newsTag 字段
                    current_tag = item.get('newsTag', 0)
                    if current_tag and current_tag != 0:
                        continue

                    # 如果是新数据
                    if obj_id and obj_id not in seen_object_ids:
                        seen_object_ids.add(obj_id)
                        new_count += 1

                        # 组合标题和内容
                        title = item.get('title', '')
                        content = item.get('content', '')  # 或者是 'description'，看具体返回
                        full_text = f"Title: {title}\nContent: {content}"

                        # 构造输入数据模型
                        raw_data = RawDataInput(
                            source="api-crypto-panic",
                            timestamp=time.time(),
                            content=full_text,
                            object_id=obj_id  # [关键] 传递 ID 给 Pipeline 以便回写
                        )

                        # 3. 直接调用 Pipeline (逐条处理，防止并发过高)
                        try:
                            # 使用 await 确保按顺序处理，减轻系统压力
                            await small_agent_graph.ainvoke({"raw_data": raw_data})
                            # 小睡一下，释放事件循环给其他任务
                            await asyncio.sleep(0.1)
                        except Exception as agent_e:
                            print(f"[NewsCollector] Agent处理错误 (ID: {obj_id}): {agent_e}")

                if new_count > 0:
                    print(f"[NewsCollector]: 本轮获取并处理了 {new_count} 条新新闻。")

            except Exception as e:
                print(f"[NewsCollector] 循环发生未知错误: {e}")
                # 发生错误时多等待一会儿
                await asyncio.sleep(10)

            # 等待下一次轮询
            await asyncio.sleep(NEWS_POLL_INTERVAL)


async def start_all_collectors():
    """启动所有采集器"""
    # 目前只运行新闻采集器，因为情绪 MCP 已被移除
    # 如果未来有新的 API 来源获取情绪数据，可以在这里添加 run_sentiment_collector()
    await asyncio.gather(
        run_news_collector(),
    )


if __name__ == "__main__":
    # 用于单独测试 collectors.py
    asyncio.run(start_all_collectors())