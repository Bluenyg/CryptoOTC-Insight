# src/agents/small_agents/filter_agent.py
import asyncio  # [新增] 用于 sleep
from src.schemas.data_models import RawDataInput
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from config.settings import settings


# 2. 定义过滤链的Pydantic输出
class FilterOutput(BaseModel):
    """判断信息是否相关。"""
    is_relevant: bool = Field(...,
                              description="该新闻信息是否与比特币(BTC)或以太坊(ETH)的价格、技术或市场情绪相关，而且对市场价格会造成影响")
    reason: str = Field(..., description="简要说明为什么相关或不相关。")


# 1. 定义一个轻量级的LLM，专门用于过滤
filter_llm = ChatOpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL, model="gemini-3-flash-preview-nothinking")

# 3. 创建一个专门的过滤链
# --- [FIX] 添加 method="function_calling" 来消除警告 ---
structured_filter_llm = filter_llm.with_structured_output(
    FilterOutput,
    method="function_calling"
)

filter_prompt = ChatPromptTemplate.from_messages([
    ("system", "你是一个新闻过滤器，你的唯一工作是判断信息是否与'BTC'或'ETH'相关。"),
    ("human", "信息: {content}\n来源: {source}\n\n是否相关?")
])

filter_chain = filter_prompt | structured_filter_llm


async def run_filter_agent(raw_data: RawDataInput) -> bool:
    """
    运行价值判断Agent。
    返回 True (相关) 或 False (噪音/不相关)。
    [新增] 增加 3 次重试机制
    """
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # 尝试调用 LLM
            response: FilterOutput = await filter_chain.ainvoke({
                "content": raw_data.content,
                "source": raw_data.source
            })

            if response.is_relevant:
                print(f"[FilterAgent]: RELEVANT. Reason: {response.reason}")
                return True
            else:
                print(f"[FilterAgent]: NOISE. Reason: {response.reason}")
                return False

        except Exception as e:
            # 如果是最后一次尝试，打印错误并放弃
            if attempt == max_retries - 1:
                print(f"❌ [FilterAgent] Failed after {max_retries} attempts: {e}")
                return False  # 宁可错杀，不放过（噪音）

            # 否则打印警告并等待重试
            wait_time = 2 * (attempt + 1)  # 2s, 4s...
            print(f"⚠️ [FilterAgent] Error: {e}. Retrying ({attempt + 1}/{max_retries}) in {wait_time}s...")
            await asyncio.sleep(wait_time)

    return False