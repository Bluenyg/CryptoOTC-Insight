# src/agents/large_agents/trend_agent.py
import time
import httpx
import json
from datetime import datetime, timedelta

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from config.settings import settings
from src.schemas.data_models import TradingSignal

# --- 配置 ---
FETCH_API_URL = "http://api.ibyteai.com:15008/10Ai/dataCenter/crypto/fetchCryptoPanic"
# [新增] 更新接口地址，用于回传信号
UPDATE_API_URL = "http://api.ibyteai.com:15008/10Ai/dataCenter/crypto/updatePanicNews"
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

            # 客户端筛选：只保留 update 过的（带有 newsTag）新闻
            for item in raw_list:
                tag = item.get('newsTag', 0)
                if tag and tag != 0:
                    processed_list.append(item)

            return processed_list

    except Exception as e:
        print(f"[TrendAgent] Fetch Error (Type {coin_type}): {e}")
        return []


async def write_signal_back_to_api(latest_news: dict, signal: TradingSignal):
    """
    [新增函数] 将生成的趋势信号回传到外部数据库。
    """
    if not latest_news:
        return

    obj_id = latest_news.get('objectId')

    # 获取原有的字段值
    current_tag = latest_news.get('newsTag')
    current_summary = latest_news.get('summary', '')
    current_analysis = latest_news.get('analysis') or ""

    # 1. 构造信号字符串
    signal_str = f"【MACRO_SIGNAL】:{signal.confidence}|{signal.trend_24h}|{signal.reasoning}"

    # 2. 追加到 analysis 字段
    new_analysis = f"{signal_str} || {current_analysis}"

    # --- 【关键修复】文本转数字映射 ---
    # 定义映射关系：BULLISH->1, NEUTRAL->2, BEARISH->3
    trend_map = {
        "BULLISH": 1,
        "NEUTRAL": 2,
        "BEARISH": 3
    }
    # 获取对应的数字，如果没有匹配到则默认给 2 (Neutral)
    trend_int = trend_map.get(signal.trend_24h, 2)
    # --------------------------------

    # 3. 构造 Payload
    payload = {
        "objectId": obj_id,
        "newsTag": current_tag,
        "summary": current_summary,
        "analysis": new_analysis,
        "trendTag": trend_int  # <--- 这里必须传转换后的数字 (trend_int)，不能传字符串
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(UPDATE_API_URL, json=payload, headers=HEADERS, timeout=10.0)

            if response.status_code == 200:
                print(f"✅ [TrendAgent] Signal saved to External DB (News ID: {obj_id}) | Trend: {trend_int}")
            else:
                # 打印详细错误信息以便调试
                print(f"❌ [TrendAgent] Save Failed [{response.status_code}]: {response.text}")
    except Exception as e:
        print(f"❌ [TrendAgent] Save Request Error: {e}")


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

        # [关键步骤] 按时间倒序排序，确保第一个元素是最新的新闻
        # API 返回的 time 格式可能是 '2025-08-14...' 或 '20250423...'，字符串排序通常足够
        all_news.sort(key=lambda x: x.get('time', ''), reverse=True)

        latest_news_item = all_news[0]  # 最新的数据点

        # 2. 格式化数据供 LLM 阅读
        formatted_lines = []
        tag_map = {1: "BULLISH", 2: "NEUTRAL", 3: "BEARISH"}

        for item in all_news:
            tag_str = tag_map.get(item.get('newsTag'), "UNKNOWN")
            content = item.get('summary') if item.get('summary') else item.get('title')
            formatted_lines.append(f"- [{tag_str}] {content}")

        news_data_str = "\n".join(formatted_lines)
        print(f"[TrendAgent] Loaded {len(formatted_lines)} processed items. Analyzing...")

        # 3. 调用 LLM 生成信号
        signal: TradingSignal = await trend_agent_chain.ainvoke({
            "news_data": news_data_str
        })

        print("=" * 50)
        print(f"🚀 [TrendAgent Signal Generated]")
        print(f"Trend:      {signal.trend_24h}")
        print(f"Confidence: {signal.confidence}")
        print(f"Reasoning:  {signal.reasoning}")
        print("=" * 50)

        # 4. [核心] 将信号回写到外部数据库 (挂载在最新的一条新闻上)
        await write_signal_back_to_api(latest_news_item, signal)

    except Exception as e:
        print(f"Error in Trend Agent: {e}")
        import traceback
        traceback.print_exc()