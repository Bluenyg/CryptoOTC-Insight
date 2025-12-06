# src/core/collectors.py
import asyncio
import httpx
import time
from typing import Set, List, Dict, Any
from datetime import datetime, timezone,timedelta  # [新增] 引入 timezone
# 导入可以直接调用的组件
from src.agents.small_agents.pipeline import small_agent_graph
from src.schemas.data_models import RawDataInput

# --- 配置 ---
FETCH_API_URL = "http://api.ibyteai.com:15008/10Ai/dataCenter/crypto/fetchCryptoPanic"
HEADERS = {'Content-Type': 'application/json'}

NEWS_POLL_INTERVAL = 60
seen_object_ids: Set[str] = set()


async def fetch_crypto_news_from_api(client: httpx.AsyncClient, coin_type: int) -> List[Dict[str, Any]]:
    """
    调用 fetchCryptoPanic 接口获取新闻
    """
    end_time = datetime.now()
    start_time = end_time - timedelta(hours=24)

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
        return response.json()
    except Exception as e:
        print(f"[NewsCollector] 请求异常 (Type {coin_type}): {e}")
        return []



def parse_api_timestamp(time_str: str) -> float:
    """
    [新增] 将 API 的 '2025-11-18T23:00:12Z' 格式转换为 float 时间戳
    """
    if not time_str:
        return time.time()
    try:
        # 处理 Z 结尾的 UTC 时间
        if time_str.endswith("Z"):
            dt = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%SZ")
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            # 处理可能的其他格式，或者直接使用 fromisoformat
            dt = datetime.fromisoformat(time_str)
        return dt.timestamp()
    except Exception as e:
        print(f"[Time Parse Error] {time_str}: {e}")
        return time.time()


async def run_news_collector():
    await asyncio.sleep(5)
    print(f"[NewsCollector]: 启动... (Target API: {FETCH_API_URL})")

    async with httpx.AsyncClient() as client:
        while True:
            try:
                all_news_items = []
                btc_news = await fetch_crypto_news_from_api(client, 1)
                eth_news = await fetch_crypto_news_from_api(client, 2)

                if isinstance(btc_news, list): all_news_items.extend(btc_news)
                if isinstance(eth_news, list): all_news_items.extend(eth_news)

                # --- [优化点 1] LIFO: 按时间倒序排序 (最新的在最前面) ---
                # 确保优先处理最新消息
                all_news_items.sort(
                    key=lambda x: parse_api_timestamp(x.get('time')),
                    reverse=True
                )

                new_count = 0

                for item in all_news_items:
                    obj_id = item.get('objectId')
                    current_tag = item.get('newsTag')


                    # 严格跳过已处理消息 (Tag != 0 且 Tag != None)
                    if current_tag is not None and current_tag != 0:
                        continue

                    # 防止本轮重复或历史重复
                    if obj_id in seen_object_ids:
                        continue

                    if obj_id:
                        seen_object_ids.add(obj_id)
                        new_count += 1

                        # --- [优化点 2] 获取 Link 并传入 source ---
                        title = item.get('title') or "No Title"
                        # 只有 title 和 description 用于初步过滤，节省资源
                        desc = item.get('description') or ""

                        # [关键] 获取链接字段 'link'
                        target_url = item.get('link') or ""

                        # 构造初始内容给 Filter Agent 判断相关性
                        initial_content = f"Title: {title}\nDescription: {desc}"

                        raw_time_str = item.get('time')
                        timestamp_float = parse_api_timestamp(raw_time_str)

                        # 将 target_url 放入 source 字段，供 pipeline 中的 crawler 读取
                        raw_data = RawDataInput(
                            source=target_url,  # <--- 这里存链接
                            timestamp=timestamp_float,
                            content=initial_content,
                            object_id=obj_id
                        )

                        try:
                            # 启动 Pipeline
                            await small_agent_graph.ainvoke({"raw_data": raw_data})
                            # 控制并发频率
                            await asyncio.sleep(0.5)
                        except Exception as agent_e:
                            print(f"[NewsCollector] Pipeline Error (ID: {obj_id}): {agent_e}")

                if new_count > 0:
                    print(f"[NewsCollector]: 本轮触发处理了 {new_count} 条最新新闻。")

            except Exception as e:
                print(f"[NewsCollector] Global Error: {e}")
                await asyncio.sleep(10)

            await asyncio.sleep(NEWS_POLL_INTERVAL)


async def start_all_collectors():
    await asyncio.gather(
        run_news_collector(),
    )


if __name__ == "__main__":
    asyncio.run(start_all_collectors())