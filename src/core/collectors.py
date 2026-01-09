# src/core/collectors.py
import asyncio
import httpx
import time
import traceback
from typing import Set, List, Dict, Any
from datetime import datetime, timezone, timedelta

# 导入可以直接调用的组件
from src.agents.small_agents.pipeline import small_agent_graph
from src.schemas.data_models import RawDataInput

# --- 配置 ---
FETCH_API_URL = "http://api.ibyteai.com:15008/10Ai/dataCenter/crypto/fetchCryptoPanic"
UPDATE_API_URL = "http://api.ibyteai.com:15008/10Ai/dataCenter/crypto/updatePanicNews"
HEADERS = {'Content-Type': 'application/json'}

# 全局去重集合 (只要程序不重启，这个 set 一直有效)
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
        "analysis": f"System Error: {reason[:100]}"
    }
    try:
        async with httpx.AsyncClient() as client:
            await client.post(UPDATE_API_URL, json=payload, headers=HEADERS, timeout=5.0)
            print(f"🚫 [ErrorHandler] 已将 ID {obj_id} 标记为 Tag 4 (Failed).")
    except Exception as e:
        print(f"❌ [ErrorHandler] 标记失败 ID {obj_id}: {e}")


async def fetch_crypto_news_from_api(client: httpx.AsyncClient, coin_type: int) -> List[Dict[str, Any]]:
    """
    调用 fetchCryptoPanic 接口获取新闻 (保留原有逻辑)
    """
    end_time = datetime.utcnow()
    # 既然每20分钟跑一次，查过去 12小时 足够了，不用查24小时，减少数据量
    start_time = end_time - timedelta(hours=12)

    start_str = start_time.strftime("%Y-%m-%dT%H:%M:%S")
    end_str = end_time.strftime("%Y-%m-%dT%H:%M:%S")

    json_data = {
        "type": coin_type,
        "startTime": start_str,
        "endTime": end_str
    }

    try:
        response = await client.post(FETCH_API_URL, headers=HEADERS, json=json_data, timeout=15.0)
        if response.status_code != 200:
            print(f"⚠️ [NewsCollector] API 请求失败 (Type {coin_type}) Code: {response.status_code}")
            return []
        return response.json()
    except Exception as e:
        print(f"❌ [NewsCollector] 请求异常 (Type {coin_type}): {e}")
        return []


def parse_api_timestamp(time_str: str) -> float:
    if not time_str: return time.time()
    try:
        clean_str = time_str.replace("Z", "").strip()
        if "T" in clean_str:
            dt = datetime.strptime(clean_str, "%Y-%m-%dT%H:%M:%S")
        else:
            dt = datetime.strptime(clean_str, "%Y-%m-%d %H:%M:%S")
        dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return time.time()


# ==========================================
# ⚡ 核心修改：去除 While True 循环
# ==========================================
async def run_news_collector():
    """
    执行一次完整的采集清洗流程，然后立即返回。
    由 main.py 的 master_scheduler 定时调用。
    """
    print(f"📥 [Collector] 开始新一轮采集任务...")

    # 记录本轮处理数量
    processed_count = 0
    loop_start = time.time()

    try:
        async with httpx.AsyncClient() as client:
            # 1. 拉取数据
            btc_news = await fetch_crypto_news_from_api(client, 1)
            eth_news = await fetch_crypto_news_from_api(client, 2)

            all_news_items = []
            if isinstance(btc_news, list): all_news_items.extend(btc_news)
            if isinstance(eth_news, list): all_news_items.extend(eth_news)

            if not all_news_items:
                print("💓 [Collector] 本轮未获取到原始数据。")
                return  # 直接结束

            # 2. 排序
            all_news_items.sort(
                key=lambda x: parse_api_timestamp(x.get('time')),
                reverse=True
            )

            # 3. 遍历处理
            for item in all_news_items:
                obj_id = item.get('objectId')
                current_tag = item.get('newsTag')

                # A. 过滤已处理的
                if current_tag is not None and current_tag != 0:
                    continue

                # B. 内存去重 (依赖全局变量 seen_object_ids)
                if obj_id in seen_object_ids:
                    continue

                if obj_id:
                    seen_object_ids.add(obj_id)
                    processed_count += 1

                    # --- 准备 Pipeline ---
                    title = item.get('title') or "No Title"
                    target_url = item.get('link') or ""

                    print(f"⚙️ [Pipeline] Processing ID: {obj_id} | {title[:30]}...")

                    raw_data = RawDataInput(
                        source=target_url,
                        timestamp=parse_api_timestamp(item.get('time')),
                        content=f"Title: {title}\nDescription: {item.get('description') or ''}",
                        object_id=obj_id
                    )

                    try:
                        # 调用 LangGraph 进行清洗
                        # 这里依然是 await，保证必须清洗完这一条，才算完成
                        await small_agent_graph.ainvoke({"raw_data": raw_data})

                        # 短暂停顿，防止并发过高
                        await asyncio.sleep(0.2)

                    except Exception as agent_e:
                        print(f"❌ [Pipeline Error] ID: {obj_id}")
                        traceback.print_exc()
                        # 出错标记，防止下次卡住
                        await mark_as_failed(obj_id, str(agent_e))

    except Exception as e:
        print(f"🔥 [Collector Critical] 本轮采集发生严重错误: {e}")
        traceback.print_exc()

    duration = time.time() - loop_start
    print(f"✅ [Collector] 本轮结束。新增处理: {processed_count} 条。耗时: {duration:.2f}s")
    # 函数自然结束，返回控制权给 Master Scheduler