# src/agents/small_agents/pipeline.py
from typing_extensions import TypedDict
from typing import Literal, Optional
from langgraph.graph import StateGraph, END
from enum import Enum  # 导入 Enum 以进行类型检查

from src.schemas.data_models import RawDataInput, ProcessedData
from src.core.database import async_session
from src.core.models import ProcessedNews

from .filter_agent import run_filter_agent
from .nlp_agent import run_nlp_agent


# --- 1. 定义 LangGraph State ---
class SmallAgentState(TypedDict):
    raw_data: RawDataInput
    processed_data: Optional[ProcessedData]
    is_relevant: bool


# --- 2. 定义 Graph 节点 ---

async def filter_node(state: SmallAgentState) -> dict:
    """调用 Filter Agent"""
    raw_data = state['raw_data']
    is_relevant = await run_filter_agent(raw_data)
    return {"is_relevant": is_relevant, "raw_data": raw_data}


async def analysis_node(state: SmallAgentState) -> dict:
    """调用 NLP Agent"""
    raw_data = state['raw_data']
    processed_data = await run_nlp_agent(raw_data)
    if processed_data:
        return {"processed_data": processed_data}
    else:
        return {"is_relevant": False}


# --- [FIX] 修复数据库写入错误 ---
async def db_write_node(state: SmallAgentState):
    """将处理结果异步写入数据库"""
    data = state['processed_data']

    if data is None:
        print("[Pipeline]: No data to write.")
        return {}

    try:
        # [FIX] 这里的逻辑更健壮：
        # 如果它是 Enum，取 .value；如果已经是 str，直接使用。
        sentiment_val = data.sentiment.value if hasattr(data.sentiment, 'value') else data.sentiment
        market_impact_val = data.market_impact.value if hasattr(data.market_impact, 'value') else data.market_impact

        news_entry = ProcessedNews(
            raw_content=data.raw_content,
            source=data.source,
            summary=data.summary,
            sentiment=sentiment_val,      # [FIX] 使用处理后的值
            market_impact=market_impact_val, # [FIX] 使用处理后的值
            long_short_score=data.long_short_score
        )

        async with async_session() as session:
            async with session.begin():
                session.add(news_entry)

        print(f"[Pipeline]: Saved to DB: {data.summary[:30]}...")

    except Exception as e:
        print(f"[Pipeline] CRITICAL DB ERROR: {e}")
        # 打印更多信息以便调试
        import traceback
        traceback.print_exc()

    return {}


async def log_noise_node(state: SmallAgentState):
    """（可选）记录噪音"""
    print(f"[Pipeline]: Logged noise: {state['raw_data'].content[:30]}...")
    return {}


# --- 3. 定义条件边 ---
def decide_to_process(state: SmallAgentState) -> Literal["run_analysis", "log_noise"]:
    """检查是否相关"""
    if state["is_relevant"]:
        return "run_analysis"
    else:
        return "log_noise"


# --- 4. 构建 Graph ---
def create_small_agent_graph():
    graph = StateGraph(SmallAgentState)

    graph.add_node("filter", filter_node)
    graph.add_node("analysis", analysis_node)
    graph.add_node("db_write", db_write_node)
    graph.add_node("log_noise", log_noise_node)

    graph.set_entry_point("filter")

    graph.add_conditional_edges(
        "filter",
        decide_to_process,
        {
            "run_analysis": "analysis",
            "log_noise": "log_noise"
        }
    )
    graph.add_edge("analysis", "db_write")
    graph.add_edge("db_write", END)
    graph.add_edge("log_noise", END)

    return graph.compile()


small_agent_graph = create_small_agent_graph()