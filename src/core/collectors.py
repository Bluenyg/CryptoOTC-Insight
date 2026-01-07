# src/core/collectors.py
import asyncio
import httpx
import time
import traceback  # [新增] 用于打印详细报错堆栈
from typing import Set, List, Dict, Any
from datetime import datetime, timezone, timedelta

# 导入可以直接调用的组件
from src.agents.small_agents.pipeline import small_agent_graph
from src.schemas.data_models import RawDataInput

# --- 配置 ---
FETCH_API_URL = "http://api.ibyteai.com:15008/10Ai/dataCenter/crypto/fetchCryptoPanic"
# [新增] 更新接口，用于标记处理失败的新闻
UPDATE_API_URL = "http://api.ibyteai.com:15008/10Ai/dataCenter/crypto/updatePanicNews"
HEADERS = {'Content-Type': 'application/json'}

NEWS_POLL_INTERVAL = 60
seen_object_ids: Set[str] = set()


async def mark_as_failed(obj_id: str, reason: str):
    """
    [新增] 辅助函数：当处理出错时，将新闻标记为 Noise (Tag 4)，
    防止程序下次重启时卡在同一个错误的 ID 上。
    """
    payload = {
        "objectId": obj_id,
        "newsTag": 4,  # 4 = 处理失败/噪音
        "summary": "Processing Failed",
        "analysis": f"System Error: {reason[:100]}"  # 截断一下防止太长
    }
    try:
        async with httpx.AsyncClient() as client:
            await client.post(UPDATE_API_URL, json=payload, headers=HEADERS, timeout=5.0)
            print(f"🚫 [ErrorHandler] 已将 ID {obj_id} 标记为 Tag 4 (Failed).")
    except Exception as e:
        print(f"❌ [ErrorHandler] 标记失败 ID {obj_id}: {e}")


async def fetch_crypto_news_from_api(client: httpx.AsyncClient, coin_type: int) -> List[Dict[str, Any]]:
    """
    调用 fetchCryptoPanic 接口获取新闻
    """
    # 使用 UTC 时间，并保留 24小时窗口
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(hours=24)

    # 打印一下请求的时间范围，方便调试
    start_str = start_time.strftime("%Y-%m-%dT%H:%M:%S")
    end_str = end_time.strftime("%Y-%m-%dT%H:%M:%S")

    # print(f"🔍 [Debug API] Requesting Type {coin_type} | Range: {start_str} -> {end_str}")

    json_data = {
        "type": coin_type,
        "startTime": start_str,
        "endTime": end_str
    }

    try:
        req_start = time.time()
        response = await client.post(FETCH_API_URL, headers=HEADERS, json=json_data, timeout=15.0)
        duration = time.time() - req_start

        if response.status_code != 200:
            print(f"⚠️ [NewsCollector] API 请求失败 (Type {coin_type}) Code: {response.status_code}")
            return []

        data = response.json()
        # print(f"✅ [Debug API] Type {coin_type} Success ({duration:.2f}s) | Items: {len(data)}")
        return data
    except Exception as e:
        print(f"❌ [NewsCollector] 请求异常 (Type {coin_type}): {e}")
        return []


def parse_api_timestamp(time_str: str) -> float:
    """
    将 API 的时间字符串转换为 float 时间戳
    """
    if not time_str:
        return time.time()
    try:
        # 预处理：有些 API 返回可能带 T 但不带 Z，或者中间有空格
        clean_str = time_str.replace("Z", "").strip()

        # 尝试带 T 的格式
        if "T" in clean_str:
            dt = datetime.strptime(clean_str, "%Y-%m-%dT%H:%M:%S")
        else:
            # 尝试空格格式
            dt = datetime.strptime(clean_str, "%Y-%m-%d %H:%M:%S")

        # 假设 API 返回的是 UTC，加上 timezone info
        dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        # print(f"⚠️ [Time Parse Warning] Raw: {time_str} | Error: {e}")
        return time.time()


async def run_news_collector():
    print(f"Waiting 5s to start collector...")
    await asyncio.sleep(5)
    print(f"[NewsCollector]: 🚀 启动成功! (API: {FETCH_API_URL})")

    async with httpx.AsyncClient() as client:
        while True:
            try:
                loop_start = time.time()

                # 1. 拉取数据
                btc_news = await fetch_crypto_news_from_api(client, 1)
                eth_news = await fetch_crypto_news_from_api(client, 2)

                all_news_items = []
                if isinstance(btc_news, list): all_news_items.extend(btc_news)
                if isinstance(eth_news, list): all_news_items.extend(eth_news)

                # 2. 排序 (最新的优先处理)
                all_news_items.sort(
                    key=lambda x: parse_api_timestamp(x.get('time')),
                    reverse=True
                )

                total_items = len(all_news_items)
                processed_count = 0

                # print(f"📊 [Loop Debug] Total Items fetched: {total_items}")

                for item in all_news_items:
                    obj_id = item.get('objectId')
                    current_tag = item.get('newsTag')

                    # 跳过已处理 (Tag != 0)
                    if current_tag is not None and current_tag != 0:
                        continue

                    # 内存去重
                    if obj_id in seen_object_ids:
                        continue

                    if obj_id:
                        seen_object_ids.add(obj_id)
                        processed_count += 1

                        # --- 准备处理 ---
                        title = item.get('title') or "No Title"
                        target_url = item.get('link') or ""

                        # 打印详细日志：开始处理
                        print(f"⏳ [Processing Start] ID: {obj_id} | Title: {title[:30]}... | URL: {target_url[:40]}...")

                        raw_data = RawDataInput(
                            source=target_url,
                            timestamp=parse_api_timestamp(item.get('time')),
                            content=f"Title: {title}\nDescription: {item.get('description') or ''}",
                            object_id=obj_id
                        )

                        # --- 核心处理逻辑 (串行) ---
                        try:
                            task_start = time.time()

                            # 这里依然是阻塞的 await，处理完一条才会走下一条
                            await small_agent_graph.ainvoke({"raw_data": raw_data})

                            task_duration = time.time() - task_start
                            print(f"✅ [Processing Done] ID: {obj_id} | Cost: {task_duration:.2f}s")

                            # 稍作休息，防止把接口打挂
                            await asyncio.sleep(0.5)

                        except Exception as agent_e:
                            print(f"❌ [Pipeline Error] ID: {obj_id} Failed!")
                            # 打印详细堆栈，方便你看具体的报错位置
                            traceback.print_exc()

                            # 【新增】关键：报错后尝试标记为 Failed，避免死循环
                            await mark_as_failed(obj_id, str(agent_e))

                # 3. 本轮总结
                loop_duration = time.time() - loop_start
                if processed_count > 0:
                    print(
                        f"🚀 [NewsCollector] 本轮循环结束，共处理 {processed_count} 条新新闻。耗时: {loop_duration:.2f}s")
                else:
                    # 心跳日志：证明程序还在跑
                    print(f"💓 [Heartbeat] No new items. (Sleeping {NEWS_POLL_INTERVAL}s)")

            except Exception as e:
                print(f"🔥 [NewsCollector Global Error]: {e}")
                traceback.print_exc()
                await asyncio.sleep(10)

            await asyncio.sleep(NEWS_POLL_INTERVAL)


async def start_all_collectors():
    await asyncio.gather(
        run_news_collector(),
    )


if __name__ == "__main__":
    asyncio.run(start_all_collectors())