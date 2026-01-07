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
UPDATE_API_URL = "http://api.ibyteai.com:15008/10Ai/dataCenter/crypto/updatePanicNews"
HEADERS = {'Content-Type': 'application/json'}

llm = ChatOpenAI(
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.OPENAI_BASE_URL,
    model="qwen3-max"
)

structured_trend_llm = llm.with_structured_output(
    TradingSignal,
    method="function_calling"
)

# 【优化】Prompt 模板：引入 "叙事聚类" 和 "加权评分" 机制，解决输出不稳定的问题
prompt_template = ChatPromptTemplate.from_messages([
    ("system", """
    你是一位**机构级加密货币宏观策略师 (Institutional Crypto Macro Strategist)**。
    你的任务是基于碎片化的新闻流，推演未来24小时的主流趋势。

    你必须严格执行以下**思维链协议 (Chain of Thought Protocol)**，并将过程写入 `chain_of_thought` 字段：

    ### 第一步：时间加权清洗 (Time-Weighted Cleaning)
    遍历新闻，根据 `[x.xh ago]` 标签进行分层：
    1. **核心驱动 (0h-6h)**: 权重 100%。这是当前市场的定价核心。
    2. **背景噪音 (6h-24h)**: 权重 30%。除非是由于重大监管/宏观事件（如ETF批准、美联储决议），否则视为已消化的历史。
    *规则：如果【核心驱动】与【背景噪音】方向相反，必须判定为“趋势反转”，以【核心驱动】为准。*

    ### 第二步：叙事聚类 (Narrative Clustering)
    不要简单统计 BULLISH/BEARISH 的数量。请将新闻归类为以下叙事主线，并判断哪条主线在主导市场：
    - **A类 (强宏观)**: 监管政策(SEC)、央行流动性、战争/地缘政治。 -> 影响力：极高
    - **B类 (市场结构)**: 交易所资金流、大额清算、鲸鱼异动。 -> 影响力：高
    - **C类 (项目噪音)**: 某代币解锁、小交易所上币、黑客攻击小项目。 -> 影响力：低 (应过滤)

    ### 第三步：多空博弈推演 (Scenario Simulation)
    - 询问自己：“当前看涨逻辑是否依赖于过时的消息？”
    - 检查是否存在“利好出尽” (Sell the news) 的迹象。

    ---
    **输出要求**：
    1. **chain_of_thought**: 必须包含上述三个步骤的完整推演过程（至少 150 字）。必须明确指出哪条叙事主线（Narrative）正在主导市场。
    2. **trend_24h**: 基于推演得出的最终方向。
    3. **confidence**: 
       - >0.8: 多条【核心驱动】新闻共振，且无重大利空。
       - 0.5-0.7: 多空消息冲突，或仅有旧闻支撑。
       - <0.5: 市场处于混沌期。
    4. **reasoning**: 给用户看的最终摘要（精简版），直接点明核心驱动事件。
    """),
    ("human", """
    当前时间锚点：T-0 (Now)。
    以下是过去24小时的宏观新闻流（包含时间偏差）：

    {news_data}

    请执行深度宏观分析并生成 TradingSignal。
    """)
])

trend_agent_chain = prompt_template | structured_trend_llm


def parse_news_time(time_str: str) -> datetime:
    if not time_str: return datetime.utcnow()
    try:
        clean_str = time_str.replace("T", " ").replace("Z", "").strip()
        if "." in clean_str: clean_str = clean_str.split(".")[0]
        return datetime.strptime(clean_str, "%Y-%m-%d %H:%M:%S")
    except:
        return datetime.utcnow()


async def write_signal_back_to_api(latest_news: dict, signal: TradingSignal):
    if not latest_news: return

    obj_id = latest_news.get('objectId')
    current_tag = latest_news.get('newsTag')
    current_summary = latest_news.get('summary', '')
    current_analysis = latest_news.get('analysis') or ""

    # 【修改后】将深度思考 (CoT) 也拼接到后面，或者让它显示在前端能看到的地方
    # 这里我用换行符分隔，展示给用户看
    full_content = f"{signal.reasoning}\n\n【深度推演】\n{signal.chain_of_thought}"

    # 注意：如果你的数据库字段有长度限制，可能需要截断，但通常 text 字段够用
    signal_str = f"【MACRO_SIGNAL】:{signal.confidence}|{signal.trend_24h}|{full_content}"

    # 【核心修改】替换逻辑
    parts = current_analysis.split(" || ")
    # 过滤旧的 MACRO_SIGNAL
    clean_parts = [p for p in parts if "【MACRO_SIGNAL】" not in p and p.strip()]
    # 插入新的
    clean_parts.insert(0, signal_str)

    new_analysis = " || ".join(clean_parts)

    trend_map = {"BULLISH": 1, "NEUTRAL": 2, "BEARISH": 3}
    trend_int = trend_map.get(signal.trend_24h, 2)

    payload = {
        "objectId": obj_id,
        "newsTag": current_tag,
        "summary": current_summary,
        "analysis": new_analysis,
        "trendTag": trend_int
    }

    try:
        async with httpx.AsyncClient() as client:
            await client.post(UPDATE_API_URL, json=payload, headers=HEADERS, timeout=10.0)
            print(f"✅ [TrendAgent] Signal UPDATED/SAVED to External DB (News ID: {obj_id}) | Trend: {trend_int}")
    except Exception as e:
        print(f"❌ [TrendAgent] Save Request Error: {e}")


async def fetch_news_window(coin_type: int, start_time: datetime, end_time: datetime) -> list:
    json_data = {
        "type": coin_type,
        "startTime": start_time.strftime("%Y-%m-%dT%H:%M:%S"),
        "endTime": end_time.strftime("%Y-%m-%dT%H:%M:%S")
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(FETCH_API_URL, headers=HEADERS, json=json_data, timeout=20.0)
            if response.status_code == 200:
                return response.json()
            return []
    except Exception as e:
        print(f"❌ [TrendAgent] Fetch Exception: {e}")
        return []


async def run_trend_analysis():
    print(f"[{time.ctime()}] 🩺 Running Trend Agent...")

    try:
        # 1. 查找最新有效新闻 (查过去 24h 寻找锚点)
        search_end = datetime.utcnow()
        search_start = search_end - timedelta(hours=24)

        btc_raw = await fetch_news_window(1, search_start, search_end)
        eth_raw = await fetch_news_window(2, search_start, search_end)
        raw_all = btc_raw + eth_raw

        # 过滤有效新闻 (Tag 1,2,3)
        valid_candidates = [x for x in raw_all if int(x.get('newsTag') or 0) in [1, 2, 3]]

        if not valid_candidates:
            print("⚠️ [TrendAgent] No valid news found.")
            return

        valid_candidates.sort(key=lambda x: str(x.get('time', '0')), reverse=True)
        latest_valid_news = valid_candidates[0]

        # 2. 状态检查（不再跳过，改为提示）
        current_analysis = latest_valid_news.get('analysis') or ""
        if "【MACRO_SIGNAL】" in current_analysis:
            print(f"🔄 [TrendAgent] Signal exists for ID {latest_valid_news.get('objectId')}. Updating/Overwriting...")

        # =======================================================
        # 3. 时间锚定 (Time Anchoring)
        # =======================================================
        anchor_time = parse_news_time(latest_valid_news.get('time'))
        analysis_window_start = anchor_time - timedelta(hours=24)

        print(f"🎯 [TrendAgent] Anchoring to: {anchor_time}")

        # 重新拉取锚定窗口数据
        btc_context = await fetch_news_window(1, analysis_window_start, anchor_time)
        eth_context = await fetch_news_window(2, analysis_window_start, anchor_time)
        context_all = btc_context + eth_context

        # 过滤并排序
        final_list = [x for x in context_all if int(x.get('newsTag') or 0) in [1, 2, 3]]
        final_list.sort(key=lambda x: str(x.get('time', '0')), reverse=True)

        # 4. 准备数据给 LLM
        formatted_lines = []
        tag_map = {1: "BULLISH", 2: "NEUTRAL", 3: "BEARISH"}

        # 获取锚定时间 (通常是最新那条新闻的时间，或者是当前时间)
        base_time = anchor_time

        for item in final_list[:50]:  # 限制数量，防止上下文溢出
            tag_val = int(item.get('newsTag', 0))
            tag_str = tag_map.get(tag_val, "UNKNOWN")
            content = item.get('summary') or item.get('title')

            # --- 新增：计算时间差 ---
            item_time = parse_news_time(item.get('time'))
            time_diff = base_time - item_time
            hours_ago = time_diff.total_seconds() / 3600
            time_str = f"{hours_ago:.1f}h ago"
            # ---------------------

            # 格式化为： [0.5h ago] [BULLISH] 币安宣布上市新币...
            formatted_lines.append(f"- [{time_str}] [{tag_str}] {content}")

        if not formatted_lines:
            return

        news_data_str = "\n".join(formatted_lines)

        # 5. LLM 分析
        print("🤖 [TrendAgent] Asking LLM...")
        signal: TradingSignal = await trend_agent_chain.ainvoke({
            "news_data": news_data_str
        })

        # 6. 写回
        await write_signal_back_to_api(latest_valid_news, signal)

    except Exception as e:
        print(f"❌ [TrendAgent] Critical Error: {e}")