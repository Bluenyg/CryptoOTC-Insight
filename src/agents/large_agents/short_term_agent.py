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
# 【新增】引入 JSON 助手
from src.utils.json_helper import append_signal_to_structure
import ccxt.async_support as ccxt
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
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

# 【优化】Prompt 模板：引入消息分级与预期差博弈
prompt_template = ChatPromptTemplate.from_messages([
    ("system", """
    你是一个专精于加密货币微观市场结构的**高频Alpha分析师**。
    你的任务是利用**新闻情绪**与**实时价格行为 (Price Action)** 的背离来捕捉未来 1小时 的交易机会。

    你必须严格遵循以下思维链 (Chain of Thought) 进行推演：

    ### Phase 0: 时间同步与新鲜度检查 (CRITICAL)
    **首先检查传入的【时间同步信息】中新闻距今的时长 (Time Lag)。**
    - **Lag < 15m**: 属于“冲击期”。价格可能尚未反应完全，重点博弈瞬间动能。
    - **Lag > 45m**: 属于“尾部期”。新闻发布已久，当前价格极大概率已经**Priced-in (已计入预期)**。
      *警告*：如果是滞后 > 45m 的利好，且当前价格高位横盘，警惕利好兑现后的回调，**不要当作新利好去追涨**。

    ### Phase 1: 信息量级与衰减评估 (Impact Assessment)
    不要只看时间，要看新闻的**权重**。
    - **Tier 1 (核弹级)**: 监管政策、交易所上市/被黑、宏观经济数据(CPI/Rates)。衰减期 > 4小时。
    - **Tier 2 (普通级)**: 项目合作、巨鲸转账、主流媒体报道。衰减期 ≈ 30-60分钟。
    - **Tier 3 (噪音)**: KOL言论、非实质性利好、谣言。衰减期 < 15分钟。
    *任务*：判断当前主导新闻的 Tier，并结合 `[xm ago]` 判断该消息是处于“爆发期”、“发酵期”还是“衰退期”。

    ### Phase 2: 量价博弈分析 (Price Action Interaction)
    对比【新闻情绪】与【当前市场价格反应】：
    - **一致性 (Trend Following)**: 
      Tier 1/2 利好 + 价格显著上涨 = **Strong BULLISH** (情绪共振，追涨)。
    - **背离/陷阱 (Divergence/Trap)**: 
      Tier 1/2 利好 + 价格下跌 = **BEARISH (Bull Trap)** (主力借利好出货)。
    - **衰竭/已计入 (Exhaustion)**: 
      Tier 2/3 利好 + 价格横盘/微跌 (发布已过15m+) = **BEARISH** (利好兑现，多头乏力)。
    - **恐惧 (Panic)**: 
      利空 + 价格暴跌 = **BEARISH** (恐慌蔓延)。

    ### Phase 3: 历史修正 (Self-Correction)
    参考传入的【历史表现回测】。如果你之前的准确率低于 50%：
    - 是否对“噪音”反应过度？
    - 是否忽视了价格已经包含预期的事实？

    ---
    **输出约束**：
    1. `chain_of_thought` 必须包含对 News Tier 的定义和 Phase 2 的具体场景判断。
    2. **特别注意**：尽管输出字段名为 `trend_24h`，但你必须**严格预测未来 1小时 (1H)** 的走势。
    3. `reasoning` 需精炼总结核心逻辑，例如：“Tier 1 利好发布 10分钟，价格尚未启动，存在巨大预期差，看涨。”
    """),
    ("human", """
    【当前市场微观数据】
    {market_context}

    【你的近期战绩 (Feedback)】
    {feedback_context}

    【实时新闻流 (Timeline)】
    {news_data}

    请给出基于上述信息的 1H 超短线交易信号。
    """)
])

short_term_chain = prompt_template | structured_llm


def parse_news_time(time_str: str) -> datetime:
    """
    解析时间，并强制确立为 UTC 时间对象。
    """
    if not time_str: return datetime.now(timezone.utc)
    try:
        clean_str = time_str.replace("T", " ").replace("Z", "").strip()
        if "." in clean_str: clean_str = clean_str.split(".")[0]
        dt = datetime.strptime(clean_str, "%Y-%m-%d %H:%M:%S")
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
    【优化版】支持解析 JSON 列表，回测所有历史预测记录。
    """
    symbol = "BTCUSDT" if coin_type == 1 else "ETHUSDT"

    # 1. 获取过去 24 小时的新闻 (以确保覆盖足够的历史预测)
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=24)
    news_history = await fetch_news_window(coin_type, start_time, end_time)

    # 2. 获取高精度 K 线 (15m, 足够覆盖24h)
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

    # 3. 逐条新闻 -> 逐个预测信号 进行比对
    for item in news_history:
        analysis = item.get('analysis') or ""

        # 跳过空分析
        if not analysis: continue

        # 容器：存放所有提取出来的 (预测时间, 预测方向)
        predictions_to_eval = []

        try:
            # A. 尝试 JSON 解析 (新格式)
            data = json.loads(analysis)
            # 获取 1H 信号列表
            signals_list = data.get("short_term_signals", [])

            for sig in signals_list:
                pred_ts_str = sig.get("timestamp")
                direction = sig.get("direction")
                if pred_ts_str and direction:
                    predictions_to_eval.append((pred_ts_str, direction))

        except (json.JSONDecodeError, TypeError):
            # B. 兼容旧格式 (String 解析)
            if "【1H_PREDICTION】" in analysis:
                try:
                    pred_part = analysis.split("【1H_PREDICTION】:")[1].split("||")[0]
                    trend_pred = pred_part.split("|")[1].strip().upper()
                    # 旧格式没有单独记录预测时间，只能近似使用新闻发布时间
                    news_time_str = item.get('time')
                    predictions_to_eval.append((news_time_str, trend_pred))
                except:
                    pass

        # 4. 评估提取出的预测
        for ts_str, pred_direction in predictions_to_eval:
            try:
                # 解析预测产生的时间 (UTC)
                pred_dt = parse_news_time(ts_str)
                pred_ts = pred_dt.timestamp()

                # 对齐到 15m K线 (找到预测发生时的那一根)
                # 比如预测在 12:05 产生，我们取 12:00 的K线作为起点
                start_kline_ts = int(pred_ts // 900) * 900

                # 目标时间：预测后 1小时 (3600秒)
                target_kline_ts = start_kline_ts + 3600

                # 确保起止 K 线都在我们获取的数据范围内
                if start_kline_ts in kline_map and target_kline_ts in kline_map:
                    start_price = kline_map[start_kline_ts]["open"]  # 预测时的价格
                    end_price = kline_map[target_kline_ts]["close"]  # 1小时后的价格

                    price_change = end_price - start_price

                    actual_trend = "NEUTRAL"
                    if price_change > 0:
                        actual_trend = "BULLISH"
                    elif price_change < 0:
                        actual_trend = "BEARISH"

                    # 只有当预测不是 NEUTRAL 时才计入考核 (NEUTRAL 很难界定对错)
                    if pred_direction != "NEUTRAL":
                        total_eval += 1
                        is_correct = (pred_direction == actual_trend)
                        if is_correct: correct_count += 1
            except Exception:
                continue

    if total_eval == 0:
        return "过去24小时无有效预测记录。"

    accuracy = correct_count / total_eval

    feedback_str = f"【系统回测报告】过去24小时共评估 {total_eval} 次历史预测(含追加更新)，准确率为 {accuracy:.0%}。"

    if accuracy < 0.5:
        feedback_str += "\n⚠️ 警告：准确率偏低。请反思是否存在过度看多/看空的情绪，更加关注实际价格动能。"
    elif accuracy > 0.7:
        feedback_str += "\n🎉 表现优异：预测逻辑与市场走势高度吻合，请保持。"

    print(f"📊 [FeedbackLoop] {symbol} Accuracy: {accuracy:.2f} ({correct_count}/{total_eval})")
    return feedback_str


# --- 修改后的 write_short_term_signal ---

async def fetch_latest_analysis_state_short(news_item: dict) -> str:
    """
    【新增辅助函数】回查最新状态，防止覆盖 TrendAgent 的数据。
    """
    target_id = news_item.get('objectId')
    news_time_str = news_item.get('time')

    try:
        if not news_time_str: return ""
        clean_str = news_time_str.replace("T", " ").replace("Z", "").split(".")[0]
        dt = datetime.strptime(clean_str, "%Y-%m-%d %H:%M:%S")

        # 缩小查找范围
        start_t = dt - timedelta(minutes=1)
        end_t = dt + timedelta(minutes=1)

        for coin_type in [1, 2]:
            json_data = {
                "type": coin_type,
                "startTime": start_t.strftime("%Y-%m-%dT%H:%M:%S"),
                "endTime": end_t.strftime("%Y-%m-%dT%H:%M:%S")
            }
            async with httpx.AsyncClient() as client:
                resp = await client.post(FETCH_API_URL, headers=HEADERS, json=json_data, timeout=5.0)
                if resp.status_code == 200:
                    items = resp.json()
                    target = next((x for x in items if x.get('objectId') == target_id), None)
                    if target:
                        print(f"🔄 [ShortTermAgent] Refetched latest state for ID: {target_id}")
                        return target.get('analysis') or ""
    except Exception as e:
        print(f"⚠️ [ShortTermAgent] Failed to refetch latest state: {e}")

    return news_item.get('analysis') or ""


async def write_short_term_signal(latest_news: dict, signal: TradingSignal):
    if not latest_news: return

    obj_id = latest_news.get('objectId')
    current_tag = latest_news.get('newsTag')
    current_summary = latest_news.get('summary', '')

    # ================= CRITICAL FIX =================
    # 在写入前，强制同步最新的数据库状态
    current_analysis = await fetch_latest_analysis_state_short(latest_news)
    # ================================================

    # "short_term_signals" 用于 1H 预测
    new_analysis_json_str = append_signal_to_structure(
        current_analysis,
        signal,
        "short_term_signals"
    )

    payload = {
        "objectId": obj_id,
        "newsTag": current_tag,
        "summary": current_summary,
        "analysis": new_analysis_json_str,
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(UPDATE_API_URL, json=payload, headers=HEADERS, timeout=10.0)
            if response.status_code == 200:
                print(f"✅ [ShortTermAgent] 1H Signal JSON APPENDED for ID: {obj_id}")
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
        # 检查 JSON key 是否存在
        if "short_term_signals" in current_analysis or "【1H_PREDICTION】" in current_analysis:
            print(f"🔄 [ShortTermAgent] Signal exists. Appending new prediction with Feedback Loop...")

        # =======================================================
        # 3. 生成高精度反馈 (已更新为支持 JSON 列表回测)
        # =======================================================
        feedback_report = await generate_feedback_report(1)

        # 获取 15m K线 (limit=3)
        klines_15m = await fetch_binance_klines("BTCUSDT", "15m", limit=3)

        # 1. 计算时间滞后 (Time Lag)
        now_utc = datetime.now(timezone.utc)
        news_time_utc = parse_news_time(latest_valid_news.get('time'))

        # 计算分钟差 (防止负数)
        lag_seconds = (now_utc - news_time_utc).total_seconds()
        lag_minutes = int(lag_seconds / 60)
        if lag_minutes < 0: lag_minutes = 0

        # 2. 构建包含时间差的市场上下文
        market_context = "数据不可用"
        if klines_15m:
            current_k = klines_15m[-1]
            prev_k = klines_15m[-2]
            open_p = float(current_k[1])
            close_p = float(current_k[4])
            pct_change = ((close_p - open_p) / open_p) * 100

            # 显式告诉 LLM 这个时间差
            time_sync_info = (
                f"⚠️【时间同步警报】\n"
                f"- 当前系统时间: {now_utc.strftime('%H:%M')} (UTC)\n"
                f"- 最新新闻时间: {news_time_utc.strftime('%H:%M')} (UTC)\n"
                f"- **新闻滞后时长 (Time Lag)**: {lag_minutes} 分钟\n"
                f"- 下方 K 线数据为: **实时最新数据** (包含了这 {lag_minutes} 分钟内的市场反应)\n"
                f"-----------------------------\n"
            )

            curr_vol = float(current_k[5])
            prev_vol = float(prev_k[5])
            vol_status = "放量" if curr_vol > prev_vol else "缩量"

            market_context = (
                f"{time_sync_info}"
                f"1. 价格走势: {'📈' if pct_change > 0 else '📉'} {pct_change:.2f}% (现价: {close_p})\n"
                f"2. 成交量态势: 较上一根15mK线呈现【{vol_status}】状态。\n"
                f"3. 趋势强度: 只有在高波动(>0.3%)配合放量时，信号才有效，否则视为噪音。"
            )
        else:
            market_context = f"当前市场价格数据不可用 (新闻滞后: {lag_minutes}m)。"

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