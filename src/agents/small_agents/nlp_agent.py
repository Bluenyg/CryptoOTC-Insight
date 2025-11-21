# src/agents/small_agents/nlp_agent.py
from src.schemas.data_models import RawDataInput, ProcessedData
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from config.settings import settings
from typing import Literal

# 1. 定义一个更强大的LLM，用于分析
analysis_llm = ChatOpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL,model="qwen-flash")

# 2. 定义分析链的 LLM 输出结构 (注意：这里不需要 object_id，因为这是 LLM 生成的内容)
class NLPAnalysisOutput(BaseModel):
    """分析加密货币新闻或社交媒体帖子。"""
    summary: str = Field(..., description="用中文总结的核心信息，150字以内。")
    sentiment: Literal["BULLISH", "BEARISH", "NEUTRAL"]
    market_impact: Literal["HIGH", "MEDIUM", "LOW"]
    long_short_score: float = Field(..., description="范围 -1.0 (极度看空) 到 1.0 (极度看涨)")

# 3. 创建分析链
structured_analysis_llm = analysis_llm.with_structured_output(
    NLPAnalysisOutput,
    method="function_calling"
)

analysis_prompt = ChatPromptTemplate.from_messages([
    ("system", "你是一个专业的加密货币量化分析师。你正在分析一条*已确认相关*的场外信息。请使用提供的JSON格式进行回复。"),
    ("human", "请分析以下信息：\n\n[信息开始]\n{content}\n[信息结束]\n\n来源: {source}")
])

analysis_chain = analysis_prompt | structured_analysis_llm


async def run_nlp_agent(raw_data: RawDataInput) -> ProcessedData | None:
    """
    运行NLP分析Agent，将原始数据转换为结构化数据。
    """
    try:
        # 1. 调用 LLM 获取分析结果
        response: NLPAnalysisOutput = await analysis_chain.ainvoke({
            "content": raw_data.content,
            "source": raw_data.source
        })

        # 2. [FIX] 在这里实例化 ProcessedData 时，必须传入 object_id
        processed = ProcessedData(
            object_id=raw_data.object_id,  # <--- [关键修复] 必须在这里传入！
            raw_content=raw_data.content,
            source=raw_data.source,
            summary=response.summary,
            sentiment=response.sentiment,
            market_impact=response.market_impact,
            long_short_score=response.long_short_score
        )
        return processed

    except Exception as e:
        print(f"Error in NLP Analysis Agent: {e}")
        return None