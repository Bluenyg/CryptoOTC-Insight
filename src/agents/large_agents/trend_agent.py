# src/agents/large_agents/trend_agent.py
import time
import httpx
import json
import statistics
from datetime import datetime, timedelta

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from config.settings import settings
from src.schemas.data_models import TradingSignal
# 【新增】引入 JSON 助手
from src.utils.json_helper import append_signal_to_structure

# --- 配置 ---
FETCH_API_URL = "http://api.ibyteai.com:15008/10Ai/dataCenter/crypto/fetchCryptoPanic"
UPDATE_API_URL = "http://api.ibyteai.com:15008/10Ai/dataCenter/crypto/updatePanicNews"
# 币安公共接口 (无需鉴权，用于获取辅助K线数据)
BINANCE_KLINE_URL = "https://api.binance.com/api/v3/klines"
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

# 【优化 Ver 2.0】Prompt 模板 (保持原有逻辑不变)
prompt_template = ChatPromptTemplate.from_messages([
    ("system", """
    你是一位**高频宏观策略师 (HFT Macro Strategist)**，专注于分析新闻流的**时效性衰减 (Time Decay)** 与 **盘面定价状态 (Priced-in Status)**。

    请严格执行以下 **动态加权思维链 (Dynamic Weighted Chain of Thought)**：

    ### 第一步：精细化时效衰减 (Fine-grained Time Decay)
    **注意参考【Market Data】中的“新闻滞后时长”指标。**
    - 如果最新新闻滞后 > 30分钟，且 K 线已经出现大幅波动，说明市场已经**消化 (Digested)** 了该信息。
    - 此时若价格回调，可能是“利好出尽”，而非“趋势反转”。

    ### 第二步：精细化时效衰减 (Fine-grained Time Decay)
    加密货币市场是半强有效市场，新闻影响随时间呈指数衰减。请按以下层级处理新闻：
    1. **冲击期 (Shock Phase, 0h - 2h)**: 权重 **120%**。这是目前尚未完全被市场消化的Alpha。重点关注。
    2. **发酵期 (Digestion Phase, 2h - 8h)**: 权重 **80%**。市场正在博弈，方向确立中。
    3. **衰退期 (Decay Phase, 8h - 24h)**: 权重 **20%**。除非是结构性改变（如ETF获批），否则视为"已定价 (Priced-in)"的噪音。

    *关键判断：如果【冲击期】新闻与【衰退期】新闻矛盾，必须以【冲击期】为准，并判定为“趋势反转”。*

    ### 第三步：边际惊奇度检测 (Marginal Surprise Check)
    - 检查最新的新闻是否只是对旧闻的**重复 (Echo)**？
    - 例如：如果 12小时前有"SEC起诉"，而 0.5小时前新闻是"SEC起诉细节曝光"，这属于**延续**；如果是"SEC撤诉"，这属于**反转 (High Surprise)**。
    - **规则**：仅重复旧观点的近期新闻，不应给予高权重。

    ### 第四步：量价与时效的互证 (Time-Price Verification)
    结合提供的 Market Data (Price & RSI) 进行最终确认：
    - **滞后陷阱**: 如果新闻是【衰退期 (10h ago)】的利好，且当前价格已经大涨并回落，RSI > 70，这大概率是 "利好出尽 (Sell the news)"。
    - **即时共振**: 如果新闻是【冲击期 (0.5h ago)】的利好，且价格刚刚启动 (RSI 50-60)，这是最佳 **BULLISH** 信号。

    ---
    **输出要求**：
    1. **chain_of_thought**: 必须包含上述时效衰减和边际惊奇的分析过程。**必须明确指出最新新闻是否已经被 K 线走势消化 (Priced-in)。**
    2. **trend_24h**: 最终方向 (BULLISH/BEARISH/NEUTRAL)。
    3. **confidence**: 
       - >0.8: 【冲击期】发生重大事件 + 盘面配合。
       - <0.5: 主要是【衰退期】旧闻，或新旧消息冲突。
    4. **reasoning**: 面向用户的简报。直接指出核心驱动事件及其发生的时间距今多久（时效性）。
    """),
    ("human", """
    当前时间锚点：T-0 (Now)。

    【实时盘面数据 (Market Data)】
    {market_context}

    【宏观新闻流 (News Stream - 按时间倒序)】
    {news_data}

    请执行基于时效性的深度分析并生成 TradingSignal。
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


# --- 技术指标计算模块 ---
def calculate_rsi(prices, period=14):
    """计算 RSI 指标"""
    if len(prices) < period + 1:
        return 50.0

    deltas = [prices[i + 1] - prices[i] for i in range(len(prices) - 1)]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(prices) - 1):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


async def fetch_market_data() -> str:
    """
    [使用 Taapi.io] 获取 BTC/ETH 实时价格与技术形态
    文档参考: https://taapi.io/indicators/candles/
    """
    # Taapi 需要带斜杠的 symbol 格式 (如 BTC/USDT)
    symbols = ["BTC/USDT", "ETH/USDT"]
    report = []

    # 请确保你在 settings 中配置了 TAAPI_API_KEY
    # 或者直接写死: api_key = "你的_taapi_secret_key"
    api_key = settings.TAAPI_API_KEY
    base_url = "https://api.taapi.io/candles"

    async with httpx.AsyncClient() as client:
        for symbol in symbols:
            try:
                # 构造请求参数
                params = {
                    "secret": api_key,
                    "exchange": "binance",  # 指定交易所
                    "symbol": symbol,
                    "interval": "1h",  # 1小时 K线
                    "results": 25  # 获取最近 25 根 (Taapi limit max=300)
                }

                # 发送 GET 请求
                resp = await client.get(base_url, params=params, timeout=10.0)

                if resp.status_code != 200:
                    print(f"⚠️ [TrendAgent] Taapi Error {symbol}: {resp.text}")
                    continue

                # Taapi 返回格式: [{"timestamp": 161..., "open": 30000, "close": 30100, ...}, ...]
                # 数据通常是按时间倒序或正序，Taapi 返回通常是时间正序 (旧->新)，但在 results 参数下可能相反
                # 根据文档，results 返回的是"historical values"，通常最新的在最后。
                # 我们可以通过 sort 确保一下顺序
                klines_data = resp.json()

                if not isinstance(klines_data, list):
                    continue

                # 按时间戳排序：旧 -> 新
                klines_data.sort(key=lambda x: x['timestamp'])

                if not klines_data: continue

                # 提取 Close Price 列表用于计算 RSI
                close_prices = [float(k['close']) for k in klines_data]

                current_price = close_prices[-1]
                # 获取 24小时前的价格 (索引 -24 或者 0，取决于由多少数据)
                # 假设拿到了 25 根，第 0 根就是 24小时前
                open_price_24h = close_prices[0]

                price_change_pct = ((current_price - open_price_24h) / open_price_24h) * 100

                # 复用你原有的 calculate_rsi 函数
                rsi_val = calculate_rsi(close_prices)

                rsi_status = "Neutral"
                if rsi_val > 70:
                    rsi_status = "Overbought"
                elif rsi_val < 30:
                    rsi_status = "Oversold"

                display_symbol = symbol.replace("/", "")
                report.append(
                    f"- **{display_symbol} (Taapi)**: ${current_price:,.2f} | "
                    f"24h Change: {price_change_pct:+.2f}% | "
                    f"RSI(1h): {rsi_val:.1f} ({rsi_status})"
                )

            except Exception as e:
                print(f"⚠️ [TrendAgent] Fetch failed for {symbol}: {e}")
                continue

    if not report:
        return "Market data unavailable (using news only)."

    return "\n".join(report)


# --- 修改后的 write_signal_back_to_api ---

async def fetch_latest_analysis_state(news_item: dict) -> str:
    """
    【新增辅助函数】在写入前强制重新拉取最新的 analysis 字段，防止覆盖其他 Agent 的写入。
    由于不知道 news_item 是 BTC(1) 还是 ETH(2)，我们需要尝试这两个池子来找到该 ID。
    """
    target_id = news_item.get('objectId')
    news_time_str = news_item.get('time')

    # 构造一个极小的时间窗口 (前后1分钟) 来快速定位数据
    try:
        if not news_time_str: return ""
        # 简单解析时间用于查询
        clean_str = news_time_str.replace("T", " ").replace("Z", "").split(".")[0]
        dt = datetime.strptime(clean_str, "%Y-%m-%d %H:%M:%S")

        start_t = dt - timedelta(minutes=1)
        end_t = dt + timedelta(minutes=1)

        # 尝试从 Type 1 (BTC) and Type 2 (ETH) 中查找
        for coin_type in [1, 2]:
            # 复用已有的 fetch 逻辑，但查询极小窗口
            json_data = {
                "type": coin_type,
                "startTime": start_t.strftime("%Y-%m-%dT%H:%M:%S"),
                "endTime": end_t.strftime("%Y-%m-%dT%H:%M:%S")
            }
            async with httpx.AsyncClient() as client:
                resp = await client.post(FETCH_API_URL, headers=HEADERS, json=json_data, timeout=5.0)
                if resp.status_code == 200:
                    items = resp.json()
                    # 寻找匹配 ID 的项
                    target = next((x for x in items if x.get('objectId') == target_id), None)
                    if target:
                        # 找到了！返回数据库里最新的 analysis
                        print(f"🔄 [TrendAgent] Refetched latest state for ID: {target_id}")
                        return target.get('analysis') or ""
    except Exception as e:
        print(f"⚠️ [TrendAgent] Failed to refetch latest state: {e}")

    # 如果回查失败，只能降级使用内存里的旧数据 (虽然有风险)
    return news_item.get('analysis') or ""


async def write_signal_back_to_api(latest_news: dict, signal: TradingSignal):
    if not latest_news: return

    obj_id = latest_news.get('objectId')
    current_tag = latest_news.get('newsTag')
    current_summary = latest_news.get('summary', '')

    # ================= CRITICAL FIX =================
    # 1. 不要直接使用 latest_news['analysis']，因为它是旧的快照。
    # 2. 必须在此刻重新去数据库查一遍最新的 analysis 字符串。
    current_analysis = await fetch_latest_analysis_state(latest_news)
    # ================================================

    # "trend_signals" 用于存储 24h 趋势预测
    new_analysis_json_str = append_signal_to_structure(
        current_analysis,
        signal,
        "trend_signals"
    )

    trend_map = {"BULLISH": 1, "NEUTRAL": 2, "BEARISH": 3}
    trend_int = trend_map.get(signal.trend_24h, 2)

    payload = {
        "objectId": obj_id,
        "newsTag": current_tag,
        "summary": current_summary,
        "analysis": new_analysis_json_str,
        "trendTag": trend_int
    }

    try:
        async with httpx.AsyncClient() as client:
            await client.post(UPDATE_API_URL, json=payload, headers=HEADERS, timeout=10.0)
            print(f"✅ [TrendAgent] Signal JSON APPENDED (ID: {obj_id}) | Trend: {trend_int}")
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
    print(f"[{time.ctime()}] 🩺 Running Trend Agent (Optimized)...")

    try:
        # 1. 查找最新有效新闻 (查过去 24h 寻找锚点)
        search_end = datetime.utcnow()
        search_start = search_end - timedelta(hours=24)

        btc_raw = await fetch_news_window(1, search_start, search_end)
        eth_raw = await fetch_news_window(2, search_start, search_end)
        raw_all = btc_raw + eth_raw

        # 过滤有效新闻
        valid_candidates = [x for x in raw_all if int(x.get('newsTag') or 0) in [1, 2, 3]]

        if not valid_candidates:
            print("⚠️ [TrendAgent] No valid news found.")
            return

        valid_candidates.sort(key=lambda x: str(x.get('time', '0')), reverse=True)
        latest_valid_news = valid_candidates[0]

        # 2. 状态检查 (检查 JSON 中是否已有 trend_signals)
        current_analysis = latest_valid_news.get('analysis') or ""
        # 简单检查字符串，如果想更严谨可以 try json.loads
        if "trend_signals" in current_analysis or "【MACRO_SIGNAL】" in current_analysis:
            print(
                f"🔄 [TrendAgent] Signal exists for ID {latest_valid_news.get('objectId')}. Appending new prediction...")

        # 3. 时间锚定
        anchor_time = parse_news_time(latest_valid_news.get('time'))
        analysis_window_start = anchor_time - timedelta(hours=24)

        print(f"🎯 [TrendAgent] Anchoring to: {anchor_time}")

        # 重新拉取锚定窗口数据
        btc_context = await fetch_news_window(1, analysis_window_start, anchor_time)
        eth_context = await fetch_news_window(2, analysis_window_start, anchor_time)
        context_all = btc_context + eth_context

        final_list = [x for x in context_all if int(x.get('newsTag') or 0) in [1, 2, 3]]
        final_list.sort(key=lambda x: str(x.get('time', '0')), reverse=True)

        # 4. 准备新闻数据
        formatted_lines = []
        tag_map = {1: "BULLISH", 2: "NEUTRAL", 3: "BEARISH"}
        base_time = anchor_time

        for item in final_list[:50]:
            tag_val = int(item.get('newsTag', 0))
            tag_str = tag_map.get(tag_val, "UNKNOWN")
            content = item.get('summary') or item.get('title')

            # 计算准确的时间差
            item_time = parse_news_time(item.get('time'))
            time_diff = base_time - item_time
            hours_ago = time_diff.total_seconds() / 3600

            # 格式化: 显式标记时间，方便 LLM 识别 "Shock Phase"
            time_label = f"{hours_ago:.1f}h ago"
            formatted_lines.append(f"- [{time_label}] [{tag_str}] {content}")

        if not formatted_lines:
            return

        news_data_str = "\n".join(formatted_lines)

        # 5. 获取辅助盘面数据
        print("📈 [TrendAgent] Fetching Market Context for Verification...")
        base_market_str = await fetch_market_data()

        # 计算针对最新一条新闻的滞后时间
        now_utc = datetime.utcnow()
        latest_news_time = parse_news_time(latest_valid_news.get('time'))
        lag_minutes = int((now_utc - latest_news_time).total_seconds() / 60)

        # 注入时间差信息
        time_context_str = (
            f"【时间同步状态】\n"
            f"- 最新一条宏观新闻距今已过去: **{lag_minutes} 分钟**。\n"
            f"- 请基于此滞后时间判断当前 K 线形态是否已经完成了对该新闻的定价 (Priced-in)。\n\n"
        )

        final_market_context = time_context_str + base_market_str

        # 6. LLM 分析
        print("🤖 [TrendAgent] Asking LLM with Time-Decay Logic...")
        signal: TradingSignal = await trend_agent_chain.ainvoke({
            "market_context": final_market_context,
            "news_data": news_data_str
        })

        # 7. 写回结果
        await write_signal_back_to_api(latest_valid_news, signal)

    except Exception as e:
        print(f"❌ [TrendAgent] Critical Error: {e}")