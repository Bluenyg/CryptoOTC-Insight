# src/agents/small_agents/pipeline.py
from typing_extensions import TypedDict
from typing import Literal, Optional
from langgraph.graph import StateGraph, END
import httpx

from src.schemas.data_models import RawDataInput, ProcessedData
# [变更] 移除了本地数据库依赖
# from src.core.database import async_session
# from src.core.models import ProcessedNews

from .filter_agent import run_filter_agent
from .nlp_agent import run_nlp_agent

# --- 配置 ---
UPDATE_API_URL = "http://api.ibyteai.com:15008/10Ai/dataCenter/crypto/updatePanicNews"
HEADERS = {
    'Content-Type': 'application/json',
    'User-Agent': 'Mozilla/5.0'
}


# --- 1. State ---
class SmallAgentState(TypedDict):
    raw_data: RawDataInput
    processed_data: Optional[ProcessedData]
    is_relevant: bool


# --- 2. Nodes ---

async def filter_node(state: SmallAgentState) -> dict:
    raw_data = state['raw_data']
    is_relevant = await run_filter_agent(raw_data)
    return {"is_relevant": is_relevant, "raw_data": raw_data}


async def analysis_node(state: SmallAgentState) -> dict:
    raw_data = state['raw_data']
    processed_data = await run_nlp_agent(raw_data)

    if processed_data:
        # 传递 object_id
        processed_data.object_id = raw_data.object_id
        return {"processed_data": processed_data}
    else:
        return {"is_relevant": False}


# --- [核心修改] 仅回传分析结果，不覆盖原始内容 ---
async def db_write_node(state: SmallAgentState):
    data = state['processed_data']
    if data is None: return {}

    # 1. 准备回传数据
    # tag: 1-正向, 2-中性, 3-负向
    tag_map = {"BULLISH": 1, "NEUTRAL": 2, "BEARISH": 3}

    # 健壮性处理：如果是 Enum 取 value，如果是 str 直接用
    sentiment_str = data.sentiment.value if hasattr(data.sentiment, 'value') else data.sentiment
    tag_value = tag_map.get(sentiment_str, 2)

    # [核心修改点] 构造 payload
    # 我们只发送我们要更新的字段：Tag, Summary, Analysis
    # 不要发送 'content'，以免覆盖掉数据库里原有的完整新闻内容
    payload = {
        "objectId": data.object_id,
        "tag": tag_value,
        "summary": data.summary,
        "analysis": f"Impact: {data.market_impact}. Score: {data.long_short_score}"
        # "content": data.raw_content  <-- [已移除] 防止覆盖原始内容
    }

    # 2. 调用 API 回写
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(UPDATE_API_URL, json=payload, headers=HEADERS, timeout=10.0)

            if response.status_code == 200:
                print(f"[Pipeline]: API Update SUCCESS for {data.object_id} (Tag: {tag_value})")
            else:
                print(f"[Pipeline]: API Update FAILED [{response.status_code}]: {response.text}")

    except Exception as e:
        print(f"[Pipeline] API Request Error: {e}")

    # [变更] 本地数据库写入代码已彻底删除
    return {}


async def log_noise_node(state: SmallAgentState):
    print(f"[Pipeline]: Filtered noise (ID: {state['raw_data'].object_id})")
    return {}


# --- 3. Graph 构建 ---
def decide_to_process(state: SmallAgentState) -> Literal["run_analysis", "log_noise"]:
    if state["is_relevant"]:
        return "run_analysis"
    else:
        return "log_noise"


def create_small_agent_graph():
    graph = StateGraph(SmallAgentState)
    graph.add_node("filter", filter_node)
    graph.add_node("analysis", analysis_node)
    graph.add_node("db_write", db_write_node)
    graph.add_node("log_noise", log_noise_node)

    graph.set_entry_point("filter")

    graph.add_conditional_edges("filter", decide_to_process, {"run_analysis": "analysis", "log_noise": "log_noise"})
    graph.add_edge("analysis", "db_write")
    graph.add_edge("db_write", END)
    graph.add_edge("log_noise", END)

    return graph.compile()


small_agent_graph = create_small_agent_graph()