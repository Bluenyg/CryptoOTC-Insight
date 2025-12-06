# src/agents/small_agents/pipeline.py
from typing_extensions import TypedDict
from typing import Literal, Optional
from langgraph.graph import StateGraph, END
import httpx
import asyncio
from datetime import datetime, timedelta

from src.schemas.data_models import RawDataInput, ProcessedData
from .filter_agent import run_filter_agent
from .nlp_agent import run_nlp_agent
from .crawler_agent import run_crawler_agent

# --- 配置 ---
UPDATE_API_URL = "http://api.ibyteai.com:15008/10Ai/dataCenter/crypto/updatePanicNews"
# [新增] 读取接口，用于回读验证
FETCH_API_URL = "http://api.ibyteai.com:15008/10Ai/dataCenter/crypto/fetchCryptoPanic"
HEADERS = {'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}


# --- 1. State ---
class SmallAgentState(TypedDict):
    raw_data: RawDataInput
    processed_data: Optional[ProcessedData]
    is_relevant: bool
    full_content: Optional[str]


# --- 2. Nodes ---

async def filter_node(state: SmallAgentState) -> dict:
    # ... (保持不变) ...
    raw_data = state['raw_data']
    is_relevant = await run_filter_agent(raw_data)
    return {"is_relevant": is_relevant, "raw_data": raw_data, "full_content": raw_data.content}


async def crawler_node(state: SmallAgentState) -> dict:
    # ... (保持不变) ...
    raw_data = state['raw_data']
    target_url = raw_data.source
    scraped_text = None
    if target_url and target_url.startswith("http"):
        print(f"🕷️ [Crawler] Fetching: {target_url}")
        scraped_text = await run_crawler_agent(target_url)
    if scraped_text:
        print(f"✅ [Crawler] Success ({len(scraped_text)} chars)")
        enriched_content = f"【Web Scraped Content】\n{scraped_text}\n\n【Original Meta】\n{raw_data.content}"
        raw_data.content = enriched_content
        return {"full_content": scraped_text, "raw_data": raw_data}
    else:
        print(f"⚠️ [Crawler] Skipped or Failed: {target_url}")
        return {}


async def analysis_node(state: SmallAgentState) -> dict:
    # ... (保持不变) ...
    raw_data = state['raw_data']
    processed_data = await run_nlp_agent(raw_data)
    if processed_data:
        processed_data.object_id = raw_data.object_id
        return {"processed_data": processed_data}
    else:
        return {"is_relevant": False}


# --- [新增] 验证辅助函数 ---
async def verify_db_write(client: httpx.AsyncClient, object_id: str, expected_tag: int) -> bool:
    """
    辅助函数：尝试从数据库回读刚才写入的数据，验证 Tag 是否更新成功。
    """
    # 获取过去 24 小时的数据范围
    end_time = datetime.now()
    start_time = end_time - timedelta(hours=24)

    # 因为不知道该新闻是 BTC(1) 还是 ETH(2)，我们两个都查一下
    for coin_type in [1, 2]:
        try:
            payload = {
                "type": coin_type,
                "startTime": start_time.strftime("%Y-%m-%d %H:%M:%S"),
                "endTime": end_time.strftime("%Y-%m-%d %H:%M:%S")
            }
            # 调用 fetch 接口
            response = await client.post(FETCH_API_URL, json=payload, headers=HEADERS, timeout=10.0)

            if response.status_code == 200:
                items = response.json()
                # 在列表中查找我们的 object_id
                target_item = next((item for item in items if str(item.get('objectId')) == str(object_id)), None)

                if target_item:
                    # 找到了！检查字段
                    # 兼容读取 newsTag, newTag, tag
                    actual_tag = target_item.get('newsTag')
                    if actual_tag is None: actual_tag = target_item.get('newTag')
                    if actual_tag is None: actual_tag = target_item.get('tag')

                    # 强转 int 对比
                    try:
                        actual_tag = int(actual_tag)
                    except:
                        actual_tag = 0

                    print(
                        f"   🔍 [Verify] Found ID {object_id} in Type {coin_type}. DB Tag: {actual_tag} | Expected: {expected_tag}")

                    if actual_tag == expected_tag:
                        return True
                    else:
                        print(f"   ⚠️ [Verify Mismatch] DB has {actual_tag}, expected {expected_tag}")
                        return False
        except Exception as e:
            print(f"   ⚠️ [Verify Error] Type {coin_type}: {e}")

    print(f"   ❌ [Verify Failed] Object ID {object_id} not found in recent API data.")
    return False


async def db_write_node(state: SmallAgentState):
    """写入节点 (包含回读验证逻辑)"""
    data = state['processed_data']
    final_content = state.get('full_content') or ""

    if data is None: return {}

    tag_map = {"BULLISH": 1, "NEUTRAL": 2, "BEARISH": 3}
    sentiment_str = data.sentiment.value if hasattr(data.sentiment, 'value') else str(data.sentiment)
    tag_value = tag_map.get(sentiment_str, 2)
    impact_str = data.market_impact.value if hasattr(data.market_impact, 'value') else str(data.market_impact)

    # 构造全字段 Payload
    payload = {
        "objectId": data.object_id,
        "tag": tag_value,
        "newsTag": tag_value,  # 双重保险
        "newTag": tag_value,  # 三重保险
        "summary": data.summary,
        "analysis": f"Impact:{impact_str}|Score:{data.long_short_score}",
        "content": final_content
    }

    try:
        async with httpx.AsyncClient() as client:
            # 1. 执行写入
            response = await client.post(UPDATE_API_URL, json=payload, headers=HEADERS, timeout=10.0)

            if response.status_code == 200:
                print(f"✅ [Pipeline] Write OK. Tag:{tag_value}. Now Verifying...")

                # 2. 等待 1 秒，给数据库一点时间落盘
                await asyncio.sleep(1.0)

                # 3. 执行回读验证
                is_verified = await verify_db_write(client, data.object_id, tag_value)

                if is_verified:
                    print(f"🎉 [Pipeline] DOUBLE CHECK PASSED! Data is strictly consistent.")
                else:
                    print(f"💊 [Pipeline] Write 200 OK, but Read-Back check failed (Might be latency).")
            else:
                print(f"❌ [Pipeline] API Error: {response.status_code}")

    except Exception as e:
        print(f"❌ [Pipeline] Connection Error: {e}")

    return {}


# --- (log_noise_node, decide_to_process, create_small_agent_graph 保持不变) ---
# ... (复制您原来的代码即可) ...
async def log_noise_node(state: SmallAgentState):
    """记录噪音节点"""
    raw_data = state['raw_data']
    payload = {
        "objectId": raw_data.object_id,
        "newsTag": 4,
        "summary": "Filtered as Noise",
        "analysis": "Status:Ignored"
    }
    try:
        async with httpx.AsyncClient() as client:
            await client.post(UPDATE_API_URL, json=payload, headers=HEADERS, timeout=5.0)
            print(f"🗑️ [Pipeline] Marked as NOISE: {raw_data.object_id}")
    except Exception:
        pass
    return {}


def decide_to_process(state: SmallAgentState) -> Literal["crawler", "log_noise"]:
    if state["is_relevant"]:
        return "crawler"
    else:
        return "log_noise"


def create_small_agent_graph():
    graph = StateGraph(SmallAgentState)
    graph.add_node("filter", filter_node)
    graph.add_node("crawler", crawler_node)
    graph.add_node("analysis", analysis_node)
    graph.add_node("db_write", db_write_node)
    graph.add_node("log_noise", log_noise_node)

    graph.set_entry_point("filter")

    graph.add_conditional_edges("filter", decide_to_process, {
        "crawler": "crawler",
        "log_noise": "log_noise"
    })

    graph.add_edge("crawler", "analysis")
    graph.add_edge("analysis", "db_write")
    graph.add_edge("db_write", END)
    graph.add_edge("log_noise", END)

    return graph.compile()


small_agent_graph = create_small_agent_graph()