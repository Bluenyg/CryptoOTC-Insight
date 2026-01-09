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
FETCH_API_URL = "http://api.ibyteai.com:15008/10Ai/dataCenter/crypto/fetchCryptoPanic"
HEADERS = {'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}


# --- 1. State ---
class SmallAgentState(TypedDict):
    raw_data: RawDataInput
    processed_data: Optional[ProcessedData]
    is_relevant: bool
    full_content: Optional[str]


# --- 2. Nodes (保持其他 Node 不变，因为重试逻辑已内嵌到 Agent 函数中) ---

async def filter_node(state: SmallAgentState) -> dict:
    raw_data = state['raw_data']
    is_relevant = await run_filter_agent(raw_data)
    return {"is_relevant": is_relevant, "raw_data": raw_data, "full_content": raw_data.content}


async def crawler_node(state: SmallAgentState) -> dict:
    raw_data = state['raw_data']
    target_url = raw_data.source
    scraped_text = None
    if target_url and target_url.startswith("http"):
        # run_crawler_agent 内部已经有重试逻辑了
        scraped_text = await run_crawler_agent(target_url)

    if scraped_text:
        enriched_content = f"【Web Scraped Content】\n{scraped_text}\n\n【Original Meta】\n{raw_data.content}"
        raw_data.content = enriched_content
        return {"full_content": scraped_text, "raw_data": raw_data}
    else:
        return {}


async def analysis_node(state: SmallAgentState) -> dict:
    raw_data = state['raw_data']
    # run_nlp_agent 内部已经有重试逻辑了
    processed_data = await run_nlp_agent(raw_data)
    if processed_data:
        processed_data.object_id = raw_data.object_id
        return {"processed_data": processed_data}
    else:
        return {"is_relevant": False}


# --- 验证辅助函数 (保持不变) ---
async def verify_db_write(client: httpx.AsyncClient, object_id: str, expected_tag: int) -> bool:
    end_time = datetime.now()
    start_time = end_time - timedelta(hours=24)
    for coin_type in [1, 2]:
        try:
            payload = {
                "type": coin_type,
                "startTime": start_time.strftime("%Y-%m-%d %H:%M:%S"),
                "endTime": end_time.strftime("%Y-%m-%d %H:%M:%S")
            }
            response = await client.post(FETCH_API_URL, json=payload, headers=HEADERS, timeout=10.0)
            if response.status_code == 200:
                items = response.json()
                target_item = next((item for item in items if str(item.get('objectId')) == str(object_id)), None)
                if target_item:
                    actual_tag = target_item.get('newsTag') or target_item.get('newTag') or target_item.get('tag')
                    try:
                        actual_tag = int(actual_tag)
                    except:
                        actual_tag = 0
                    if actual_tag == expected_tag: return True
        except Exception:
            pass
    return False


async def db_write_node(state: SmallAgentState):
    """写入节点 (包含重试和回读验证逻辑)"""
    # 【新增】检查上一步是否成功生成了 processed_data
    if 'processed_data' not in state or state['processed_data'] is None:
        print("⚠️ [Pipeline] Skip writing: No processed data available.")
        return {"status": "skipped"}

    data = state['processed_data']
    final_content = state.get('full_content') or ""

    if data is None: return {}

    tag_map = {"BULLISH": 1, "NEUTRAL": 2, "BEARISH": 3}
    sentiment_str = data.sentiment.value if hasattr(data.sentiment, 'value') else str(data.sentiment)
    tag_value = tag_map.get(sentiment_str, 2)
    impact_str = data.market_impact.value if hasattr(data.market_impact, 'value') else str(data.market_impact)

    payload = {
        "objectId": data.object_id,
        "tag": tag_value,
        "newsTag": tag_value,
        "newTag": tag_value,
        "summary": data.summary,
        "analysis": f"Impact:{impact_str}|Score:{data.long_short_score}",
        "content": final_content
    }

    # [新增] 写入时的重试机制
    max_retries = 3

    async with httpx.AsyncClient() as client:
        for attempt in range(max_retries):
            try:
                # 1. 执行写入
                response = await client.post(UPDATE_API_URL, json=payload, headers=HEADERS, timeout=10.0)

                if response.status_code == 200:
                    print(f"✅ [Pipeline] Write OK. Tag:{tag_value}. Now Verifying...")

                    # 2. 等待并验证
                    await asyncio.sleep(2.0)
                    is_verified = await verify_db_write(client, data.object_id, tag_value)

                    if is_verified:
                        print(f"🎉 [Pipeline] DOUBLE CHECK PASSED!")
                    else:
                        print(f"💊 [Pipeline] Write OK but verify failed (Latency).")

                    # 成功后直接退出函数
                    return {}
                else:
                    raise Exception(f"API Code {response.status_code}")

            except Exception as e:
                if attempt == max_retries - 1:
                    print(f"❌ [Pipeline] Write Failed after {max_retries} attempts: {e}")
                else:
                    print(f"⚠️ [Pipeline] Write Retry ({attempt + 1}/{max_retries}): {e}")
                    await asyncio.sleep(2)

    return {}


# --- (以下保持不变) ---
async def log_noise_node(state: SmallAgentState):
    """记录噪音节点"""
    raw_data = state['raw_data']
    payload = {
        "objectId": raw_data.object_id,
        "newsTag": 4,
        "summary": "Filtered as Noise",
        "analysis": "Status:Ignored"
    }
    # 噪音记录偶尔失败也没关系，不需要重试太狠
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