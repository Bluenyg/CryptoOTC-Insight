# src/agents/large_agents/trend_agent.py
import time
from sqlalchemy.future import select
from sqlalchemy import func, text
from datetime import datetime, timedelta
from src.core.database import async_session
from src.core.models import ProcessedNews, SentimentMetrics, TradingSignals
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from config.settings import settings
from src.schemas.data_models import TradingSignal

llm = ChatOpenAI(api_key=settings.OPENAI_API_KEY, base_url = settings.OPENAI_BASE_URL,model="qwen-flash")

# --- [FIX] 在这里添加 method="function_calling" ---
structured_trend_llm = llm.with_structured_output(
    TradingSignal,
    method="function_calling"
)
# ---

# 2. 定义新的Prompt
prompt_template = ChatPromptTemplate.from_messages([
    ("system", """
     你是一个宏观量化分析师。你正在查看过去24小时内所有已处理的数据。
     你的工作是合成 "新闻摘要" 和 "社交指标" 这两类数据，
     总结出一个**总体的、24小时跨度**的宏观趋势，并给出置信度。
     请使用你被提供的工具来返回你的分析结果。
     """),
    ("human", """
     请分析以下过去24小时的数据:

     --- 1. 新闻摘要数据 (来自 processed_news) ---
     {news_data}

     --- 2. 社交情绪指标 (来自 sentiment_metrics) ---
     {sentiment_data}

     请提供你的分析结果。
     """)
])

# 3. 创建链
trend_agent_chain = prompt_template | structured_trend_llm


async def run_trend_analysis():
    """
    执行24h宏观趋势分析 (只读本地数据库)
    """
    print(f"[{time.ctime()}] Running Trend Agent (Reading DB)...")

    news_data_str = "No news data."
    sentiment_data_str = "No sentiment metrics."

    try:
        # --- (这部分查询逻辑是正确的，保持不变) ---
        async with async_session() as session:
            # 1. 查询新闻数据
            news_query = select(
                ProcessedNews.summary,
                ProcessedNews.sentiment,
                ProcessedNews.long_short_score,
                ProcessedNews.market_impact
            ).where(
                ProcessedNews.timestamp >= (datetime.now() - timedelta(hours=24))
            )
            news_result = await session.execute(news_query)
            news_rows = news_result.mappings().all()
            if news_rows:
                news_data_str = str(news_rows)

            # 2. 查询情绪指标
            sentiment_query = select(
                SentimentMetrics.asset,
                SentimentMetrics.metric_name,
                func.avg(SentimentMetrics.value).label("average_value")
            ).where(
                SentimentMetrics.timestamp >= (datetime.now() - timedelta(hours=24))
            ).group_by(SentimentMetrics.asset, SentimentMetrics.metric_name)

            sentiment_result = await session.execute(sentiment_query)
            sentiment_rows = sentiment_result.mappings().all()
            if sentiment_rows:
                sentiment_data_str = str(sentiment_rows)
        # --- 查询结束 ---

        # 3. 调用LLM
        signal: TradingSignal = await trend_agent_chain.ainvoke({
            "news_data": news_data_str,
            "sentiment_data": sentiment_data_str
        })

        # 4. 将结果写入数据库
        signal_entry = TradingSignals(
            trend_24h=signal.trend_24h,
            confidence=signal.confidence,
            reasoning=signal.reasoning,
            agent_type="TREND_DB"
        )
        async with async_session() as session:
            async with session.begin():
                session.add(signal_entry)

        print(f"[TrendAgent]: Signal Generated: {signal.trend_24h}, Confidence: {signal.confidence}")

    except Exception as e:
        print(f"Error in Trend Agent (DB): {e}")