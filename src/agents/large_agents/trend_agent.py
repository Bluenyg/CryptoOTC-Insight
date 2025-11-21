# src/agents/large_agents/trend_agent.py
import time
import httpx
import json
from datetime import datetime, timedelta

# [变更] 移除了所有本地数据库相关的导入 (database, models)
# from src.core.database import async_session
# from src.core.models import TradingSignals

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from config.settings import settings
from src.schemas.data_models import TradingSignal

# --- 配置 ---
FETCH_API_URL = "http://api.ibyteai.com:15008/10Ai/dataCenter/crypto/fetchCryptoPanic"
HEADERS = {'Content-Type': 'application/json'}

llm = ChatOpenAI(
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.OPENAI_BASE_URL,
    model="qwen-flash"
)

structured_trend_llm = llm.with_structured_output(
    TradingSignal,
    method="function_calling"
)

prompt_template = ChatPromptTemplate.from_messages([
    ("system", """
     你是一个加密货币宏观量化分析师。你正在查看过去24小时内**经过人工/AI清洗和标记**的市场新闻。

     数据说明：
     - Tag 1: 看涨 (Bullish)
     - Tag 2: 中性 (Neutral)
     - Tag 3: 看跌 (Bearish)

     你的任务是：
     1. 统计分析这些已标记新闻的多空分布。
     2. 结合新闻摘要(Summary)和原始内容，总结过去24小时的核心叙事。
     3. 给出一个明确的**24小时跨度**的趋势信号 (BULLISH/BEARISH/NEUTRAL) 和置信度。
     """),
    ("human", """
     请分析以下过去24小时的已清洗数据:

     {news_data}

     请提供你的分析结果。
     """)
])

trend_agent_chain = prompt_template | structured_trend_llm


async def fetch_processed_news_from_api(coin_type: int, hours: int = 24) -> list:
    """
    从外部 API 获取过去 24 小时的数据，并筛选出已处理（有 Tag）的新闻
    """
    end_time = datetime.now()
    start_time = end_time - timedelta(hours=hours)

    json_data = {
        "type": coin_type,  # 1=BTC, 2=ETH
        "startTime": start_time.strftime("%Y-%m-%d %H:%M:%S"),
        "endTime": end_time.strftime("%Y-%m-%d %H:%M:%S")
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(FETCH_API_URL, headers=HEADERS, json=json_data, timeout=20.0)

            if response.status_code != 200:
                print(f"[TrendAgent] API Error {response.status_code}")
                return []

            raw_list = response.json()
            processed_list = []

            # [关键逻辑] 客户端筛选：只保留 update 过的（带有 newsTag）新闻
            # 假设 updatePanicNews 写入后，fetch 接口返回的 newsTag 会变化
            # newsTag: 0 (默认/未处理), 1, 2, 3
            for item in raw_list:
                tag = item.get('newsTag', 0)
                # 过滤掉 tag 为 0 (未处理) 或 None 的数据
                if tag and tag != 0:
                    processed_list.append(item)

            return processed_list

    except Exception as e:
        print(f"[TrendAgent] Fetch Error (Type {coin_type}): {e}")
        return []


async def run_trend_analysis():
    """
    执行24h宏观趋势分析 (从外部 API 读取已 Tag 的数据)
    """
    print(f"[{time.ctime()}] Running Trend Agent (Fetching from External API)...")

    try:
        # 1. 并行获取 BTC 和 ETH 的 24h 数据
        btc_news_list = await fetch_processed_news_from_api(1)
        eth_news_list = await fetch_processed_news_from_api(2)

        all_news = btc_news_list + eth_news_list

        if not all_news:
            print("[TrendAgent] No processed (tagged) news found in the last 24h. Skipping.")
            return

        # 2. 格式化数据供 LLM 阅读
        # 字段：title, summary, newsTag
        formatted_lines = []
        tag_map = {1: "BULLISH", 2: "NEUTRAL", 3: "BEARISH"}

        for item in all_news:
            tag_str = tag_map.get(item.get('newsTag'), "UNKNOWN")
            # 优先使用 update 进去的 summary，如果没有则使用 title
            content = item.get('summary') if item.get('summary') else item.get('title')
            line = f"- [{tag_str}] {content}"
            formatted_lines.append(line)

        news_data_str = "\n".join(formatted_lines)
        print(f"[TrendAgent] Loaded {len(formatted_lines)} processed items for analysis.")

        # 3. 调用 LLM 生成信号
        signal: TradingSignal = await trend_agent_chain.ainvoke({
            "news_data": news_data_str
        })

        # 4. [变更] 仅输出结果 (移除了本地数据库写入)
        # 如果你需要将此信号发送给交易机器人，可以在这里添加 webhook 调用
        print("="*50)
        print(f"🚀 [TrendAgent Signal Generated]")
        print(f"Trend:      {signal.trend_24h}")
        print(f"Confidence: {signal.confidence}")
        print(f"Reasoning:  {signal.reasoning}")
        print("="*50)

    except Exception as e:
        print(f"Error in Trend Agent: {e}")
        import traceback
        traceback.print_exc()