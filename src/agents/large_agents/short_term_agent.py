# src/agents/large_agents/short_term_agent.py
import time
import httpx
import json
import statistics
from datetime import datetime, timedelta, timezone

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from config.settings import settings
from src.schemas.data_models import TradingSignal

# --- 配置 ---
FETCH_API_URL = "http://api.ibyteai.com:15008/10Ai/dataCenter/crypto/fetchCryptoPanic"
UPDATE_API_URL = "http://api.ibyteai.com:15008/10Ai/dataCenter/crypto/updatePanicNews"
HEADERS = {'Content-Type': 'application/json'}

# 币安 K线接口 (无需API Key)
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

llm = ChatOpenAI(
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.OPENAI_BASE_URL,
    model="qwen3-max"
)

structured_llm = llm.with_structured_output(
    TradingSignal,
    method="function_calling"
)

# 【优化】Prompt 模板：强化量价背离的 CoT 推演
prompt_template = ChatPromptTemplate.from_messages([
    ("system", """
     你是一个加密货币**高频情绪算法 (High-Frequency Sentiment Algo)**。
     你的目标是捕捉市场微观结构中的**“情绪冲击”**。
     
     你必须严格按照以下步骤填充 `chain_of_thought` 字段：

     ### 第一步：情绪半衰期计算 (Sentiment Half-Life)
     查看数据中的 `[xm ago]` 标签：
     - **[0m-15m]**：这是“冲击波”。如果是利好，价格应该已经在涨。
     - **[45m+]**：这是“余波”。如果此时才有利好，往往是诱多陷阱。

     ### 第二步：量价一致性验证 (关键！)
     对比【新闻方向】与传入的【当前市场价格反应】：
     - 场景 A (共振)：新闻 BULLISH + 价格上涨 (+0.5%) -> **Strong BULLISH** (追涨信号)。
     - 场景 B (背离)：新闻 BULLISH + 价格下跌 (-0.3%) -> **BEARISH (Bull Trap)** (主力借利好出货)。
     - 场景 C (无视)：新闻 BULLISH + 价格横盘 (0.0%) -> **NEUTRAL** (市场不买账)。

     ### 第三步：自我反思
     在 `chain_of_thought` 中写下：如果我预测错误，最可能的原因是什么？（例如：是否过于依赖了一条 50分钟前的旧闻？）

     ---
     **输出规则**：
     1. 先在 `chain_of_thought` 里把上面三步想清楚。
     2. 再基于此填写 `trend_24h` (实际指未来1小时趋势)。
     3. `reasoning` 字段只需总结“当前处于情绪爆发期还是衰退期”以及“量价是否配合”。
     """),
    ("human", """
     【当前市场价格反应】
     {market_context}
     
     【重要：你的历史表现回测】
     {feedback_context}

     请分析以下过去1小时的实时数据 (精确到分钟):
     {news_data}

     结合以上的内容给出你的未来1小时超短线预测结果。
     """)
])

short_term_chain = prompt_template | structured_llm


def parse_news_time(time_str: str) -> datetime:
    """
    解析新闻时间，并强制确立为 UTC 时间对象。
    """
    if not time_str: return datetime.now(timezone.utc)
    try:
        clean_str = time_str.replace("T", " ").replace("Z", "").strip()
        if "." in clean_str: clean_str = clean_str.split(".")[0]
        dt = datetime.strptime(clean_str, "%Y-%m-%d %H:%M:%S")
        # 假设 API 返回的是 UTC 时间，加上 timezone 信息
        return dt.replace(tzinfo=timezone.utc)
    except:
        return datetime.now(timezone.utc)


# ==============================================================================
# 📊 行情与回测模块
# ==============================================================================

async def fetch_binance_klines(symbol: str, interval: str = "15m", limit: int = 96):
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(BINANCE_KLINES_URL, params=params, timeout=10)
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        print(f"⚠️ [MarketData] Failed to fetch klines for {symbol}: {e}")
    return []


async def generate_feedback_report(coin_type: int) -> str:
    """
    生成反馈报告。
    判定逻辑：只要方向正确即为 Correct。
    """
    symbol = "BTCUSDT" if coin_type == 1 else "ETHUSDT"

    # 1. 获取过去 24 小时的新闻
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=24)
    news_history = await fetch_news_window(coin_type, start_time, end_time)

    # 2. 获取高精度 K 线 (15m)
    klines = await fetch_binance_klines(symbol, "15m", 100)
    if not klines or not news_history:
        return "尚无足够的历史数据进行回测，请按常规策略分析。"

    # K线字典: { timestamp_sec: {open, close} }
    kline_map = {}
    for k in klines:
        ts_sec = int(k[0]) / 1000
        kline_map[ts_sec] = {"open": float(k[1]), "close": float(k[4])}

    correct_count = 0
    total_eval = 0

    # 3. 逐条比对
    for item in news_history:
        analysis = item.get('analysis') or ""
        if "【1H_PREDICTION】" not in analysis:
            continue

        try:
            # 解析预测方向
            pred_part = analysis.split("【1H_PREDICTION】:")[1].split("||")[0]
            trend_pred = pred_part.split("|")[1].strip().upper()

            # 解析新闻时间 (UTC)
            news_dt = parse_news_time(item.get('time'))
            news_ts = news_dt.timestamp()

            # 对齐到 15m K线 (新闻发生时的那一根)
            start_kline_ts = int(news_ts // 900) * 900

            # 目标时间：新闻发生后 1小时 (3600秒) 对应的 K 线
            target_kline_ts = start_kline_ts + 3600

            # 确保 K 线数据存在
            if start_kline_ts in kline_map and target_kline_ts in kline_map:
                start_price = kline_map[start_kline_ts]["open"]
                end_price = kline_map[target_kline_ts]["close"]

                price_change = end_price - start_price

                actual_trend = "NEUTRAL"
                if price_change > 0:
                    actual_trend = "BULLISH"
                elif price_change < 0:
                    actual_trend = "BEARISH"

                # 只有当预测不是 NEUTRAL 时才计入考核
                if trend_pred != "NEUTRAL":
                    total_eval += 1
                    is_correct = (trend_pred == actual_trend)
                    if is_correct: correct_count += 1

        except Exception:
            continue

    if total_eval == 0:
        return "过去24小时无有效预测记录。"

    accuracy = correct_count / total_eval

    feedback_str = f"【系统回测报告】过去24小时共评估 {total_eval} 次预测，准确率为 {accuracy:.0%}。"

    if accuracy < 0.5:
        feedback_str += "\n⚠️ 警告：准确率偏低。请反思是否存在过度看多/看空的情绪，更加关注实际价格动能。"
    elif accuracy > 0.7:
        feedback_str += "\n🎉 表现优异：预测逻辑与市场走势高度吻合，请保持。"

    print(f"📊 [FeedbackLoop] {symbol} Accuracy: {accuracy:.2f} ({correct_count}/{total_eval})")
    return feedback_str


# ==============================================================================


async def write_short_term_signal(latest_news: dict, signal: TradingSignal):
    if not latest_news: return

    obj_id = latest_news.get('objectId')
    current_tag = latest_news.get('newsTag')
    current_summary = latest_news.get('summary', '')
    current_analysis = latest_news.get('analysis') or ""

    # 【修改后】拼接 CoT
    full_content = f"{signal.reasoning}\n\n【思维链】\n{signal.chain_of_thought}"

    signal_str = f"⚡【1H_PREDICTION】:{signal.confidence}|{signal.trend_24h}|{full_content}"

    parts = current_analysis.split(" || ")
    clean_parts = [p for p in parts if "【1H_PREDICTION】" not in p and p.strip()]
    clean_parts.insert(0, signal_str)
    new_analysis = " || ".join(clean_parts)

    payload = {
        "objectId": obj_id,
        "newsTag": current_tag,
        "summary": current_summary,
        "analysis": new_analysis,
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(UPDATE_API_URL, json=payload, headers=HEADERS, timeout=10.0)
            if response.status_code == 200:
                print(f"✅ [ShortTermAgent] 1H Signal UPDATED for ID: {obj_id}")
            else:
                print(f"❌ [ShortTermAgent] Save Failed: {response.status_code}")
    except Exception as e:
        print(f"❌ [ShortTermAgent] Error: {e}")


async def fetch_news_window(coin_type: int, start_time: datetime, end_time: datetime) -> list:
    json_data = {
        "type": coin_type,
        "startTime": start_time.strftime("%Y-%m-%dT%H:%M:%S"),
        "endTime": end_time.strftime("%Y-%m-%dT%H:%M:%S")
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(FETCH_API_URL, headers=HEADERS, json=json_data, timeout=15.0)
            if response.status_code == 200:
                return response.json()
            return []
    except Exception as e:
        print(f"❌ [ShortTermAgent] Fetch Error: {e}")
        return []


async def run_short_term_analysis():
    print(f"[{time.ctime()}] ⚡ Running Short-Term (1H) Agent...")

    try:
        # 1. 寻找锚点 (过去12小时)
        search_end = datetime.now(timezone.utc)
        search_start = search_end - timedelta(hours=12)

        btc_raw = await fetch_news_window(1, search_start, search_end)
        eth_raw = await fetch_news_window(2, search_start, search_end)
        raw_all = btc_raw + eth_raw

        valid_candidates = []
        for item in raw_all:
            tag = item.get('newsTag')
            if tag and int(tag) in [1, 2, 3]:
                valid_candidates.append(item)

        if not valid_candidates:
            print("⚠️ [ShortTermAgent] No valid news found in last 12h.")
            return

        valid_candidates.sort(key=lambda x: str(x.get('time', '0')), reverse=True)
        latest_valid_news = valid_candidates[0]

        # 2. 防重复/更新检查
        current_analysis = latest_valid_news.get('analysis') or ""
        if "【1H_PREDICTION】" in current_analysis:
            print(f"🔄 [ShortTermAgent] Signal exists. Updating with 15m-Precision Feedback Loop...")

        # =======================================================
        # 3. 生成高精度反馈
        # =======================================================
        feedback_report = await generate_feedback_report(1)

        # 【优化】获取当前实时价格动能 (Price Action) 用于 Prompt 上下文
        klines_15m = await fetch_binance_klines("BTCUSDT", "15m", limit=3)
        if klines_15m:
            latest_k = klines_15m[-1]
            open_p = float(latest_k[1])
            close_p = float(latest_k[4])
            pct_change = ((close_p - open_p) / open_p) * 100
            market_context = f"当前BTC 15mK线走势: {'📈' if pct_change > 0 else '📉'} {pct_change:.2f}% (收盘价: {close_p})"
        else:
            market_context = "当前市场价格数据不可用。"
        # =======================================================

        # 4. 时间锚定
        anchor_time = parse_news_time(latest_valid_news.get('time'))
        # 【优化】窗口放宽到 75分钟 以防边界丢失，但在 Prompt 里依靠分钟数判断
        analysis_window_start = anchor_time - timedelta(minutes=75)

        print(f"🎯 [ShortTermAgent] Anchoring to: {anchor_time} (UTC)")

        btc_context = await fetch_news_window(1, analysis_window_start, anchor_time)
        eth_context = await fetch_news_window(2, analysis_window_start, anchor_time)
        context_all = btc_context + eth_context

        final_news_list = [x for x in context_all if x.get('newsTag') and int(x.get('newsTag')) in [1, 2, 3]]
        final_news_list.sort(key=lambda x: str(x.get('time', '0')), reverse=True)

        formatted_lines = []
        tag_map = {1: "BULLISH", 2: "NEUTRAL", 3: "BEARISH", 4: "NOISE"}

        # 【优化】计算精确到分钟的时间差
        base_time = anchor_time

        for item in final_news_list[:25]:
            tag_val = int(item.get('newsTag', 0))
            tag_str = tag_map.get(tag_val, "UNKNOWN")
            content = item.get('summary') or item.get('title')

            # 计算分钟差
            item_time = parse_news_time(item.get('time'))
            time_diff = base_time - item_time
            minutes_ago = int(time_diff.total_seconds() / 60)
            if minutes_ago < 0: minutes_ago = 0  # 修正未来时间数据异常

            time_str = f"{minutes_ago}m ago"

            formatted_lines.append(f"- [{time_str}] [{tag_str}] {content}")

        news_data_str = "\n".join(formatted_lines)

        # 5. LLM 分析
        print(f"🤖 [ShortTermAgent] Analyzing with Feedback & Price Action...")
        signal: TradingSignal = await short_term_chain.ainvoke({
            "news_data": news_data_str,
            "feedback_context": feedback_report,
            "market_context": market_context
        })

        print(f"⚡ [ShortTermResult] {signal.trend_24h} (Conf: {signal.confidence})")

        # 6. 写回
        await write_short_term_signal(latest_valid_news, signal)

    except Exception as e:
        print(f"❌ [ShortTermAgent] Error: {e}")
        import traceback
        traceback.print_exc()