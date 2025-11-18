# src/agents/small_agents/pipeline.py
from typing_extensions import TypedDict
from typing import Literal, Optional
from langgraph.graph import StateGraph, END

from src.schemas.data_models import RawDataInput, ProcessedData
# --- [FIX] 导入新的会话 和 模型 ---
from src.core.database import async_session
from src.core.models import ProcessedNews
# ---

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
        # 如果分析失败，当作不相关处理
        return {"is_relevant": False}


# --- [FIX] 重写 db_write_node ---
async def db_write_node(state: SmallAgentState):
    """将处理结果异步写入数据库"""
    data = state['processed_data']

    if data is None:
        print("[Pipeline]: No data to write.")
        return {}

    try:
        # 将 Pydantic (ProcessedData) 模式转换为 SQLAlchemy (ProcessedNews) 模型
        news_entry = ProcessedNews(
            raw_content=data.raw_content,
            source=data.source,
            summary=data.summary,
            sentiment=data.sentiment.value,
            market_impact=data.market_impact.value,
            long_short_score=data.long_short_score
        )

        # 使用新的 'async_session'
        async with async_session() as session:
            async with session.begin():
                session.add(news_entry)
            # 'await session.commit()' 在 'async with session.begin()' 中自动完成

        print(f"[Pipeline]: Saved to DB: {data.summary[:30]}...")

    except Exception as e:
        print(f"[Pipeline] CRITICAL DB ERROR: {e}")

    return {}


async def log_noise_node(state: SmallAgentState):
    """（可选）记录噪音，以便未来训练"""
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

    # 添加所有节点
    graph.add_node("filter", filter_node)
    graph.add_node("analysis", analysis_node)
    graph.add_node("db_write", db_write_node)
    graph.add_node("log_noise", log_noise_node)

    # 设定入口
    graph.set_entry_point("filter")

    # 添加边
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

    # 编译
    return graph.compile()


# 创建一个可调用的实例
small_agent_graph = create_small_agent_graph()