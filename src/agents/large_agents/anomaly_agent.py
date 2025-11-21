# src/agents/large_agents/anomaly_agent.py
import time
import httpx
from datetime import datetime, timedelta

# [变更] 移除本地数据库依赖
# from src.core.database import async_session
# from src.core.models import SentimentMetrics, TradingSignals

# --- 配置 ---
FETCH_API_URL = "http://api.ibyteai.com:15008/10Ai/dataCenter/crypto/fetchCryptoPanic"
UPDATE_API_URL = "http://api.ibyteai.com:15008/10Ai/dataCenter/crypto/updatePanicNews"
HEADERS = {'Content-Type': 'application/json'}

ASSETS_TO_TRACK = ["BTC", "ETH"]  # 这里主要用于日志，实际API调用通过 type 1/2 区分
# 异常阈值设置
MIN_NEWS_COUNT = 3  # 过去1小时至少要有3条新闻才触发分析
DOMINANCE_THRESHOLD = 0.7  # 如果某种情绪占比超过 70%，视为异常脉冲


async def fetch_recent_processed_news(coin_type: int, minutes: int = 60) -> list:
    """
    获取过去 X 分钟内的已处理新闻 (Tag != 0)
    """
    end_time = datetime.now()
    start_time = end_time - timedelta(minutes=minutes)

    json_data = {
        "type": coin_type,
        "startTime": start_time.strftime("%Y-%m-%d %H:%M:%S"),
        "endTime": end_time.strftime("%Y-%m-%d %H:%M:%S")
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(FETCH_API_URL, headers=HEADERS, json=json_data, timeout=15.0)
            if response.status_code != 200:
                return []

            raw_list = response.json()
            # 筛选出已处理的 (newsTag 不为 0)
            #
            return [item for item in raw_list if item.get('newsTag', 0) != 0]
    except Exception as e:
        print(f"[AnomalyAgent] Fetch Error: {e}")
        return []


async def write_anomaly_back_to_api(latest_news_item: dict, anomaly_msg: str):
    """
    将异常信号追加到最新一条新闻的 analysis 字段中并回传
    """
    # 提取原有字段，防止覆盖
    obj_id = latest_news_item.get('objectId')
    current_tag = latest_news_item.get('newsTag')
    current_summary = latest_news_item.get('summary', '')
    # 获取原有的 analysis (可能是 'None' 或空字符串)
    current_analysis = latest_news_item.get('analysis') or ""

    # 构造新的 analysis 内容，追加警报
    new_analysis = f"{current_analysis} || ⚠️【ANOMALY SIGNAL】: {anomaly_msg}"

    payload = {
        "objectId": obj_id,
        "tag": current_tag,
        "summary": current_summary,
        "analysis": new_analysis,
        # "content": ... (不传 content 以免覆盖原始内容)
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(UPDATE_API_URL, json=payload, headers=HEADERS, timeout=10.0)
            if response.status_code == 200:
                print(f"[AnomalyAgent] Signal written back to News ID: {obj_id}")
            else:
                print(f"[AnomalyAgent] Write back failed: {response.status_code}")
    except Exception as e:
        print(f"[AnomalyAgent] Write back error: {e}")


async def run_anomaly_detection():
    print(f"[{time.ctime()}] Running Anomaly Agent (Checking API News Flow)...")

    # 映射 type: 1=BTC, 2=ETH
    coin_map = {1: "Bitcoin", 2: "Ethereum"}

    for coin_type, coin_name in coin_map.items():
        # 1. 获取过去 60 分钟的数据
        news_list = await fetch_recent_processed_news(coin_type, minutes=60)

        count = len(news_list)
        if count < MIN_NEWS_COUNT:
            # 新闻太少，不足以构成脉冲
            continue

        # 2. 统计情绪分布
        # Tag: 1=Bullish, 2=Neutral, 3=Bearish
        bullish_count = sum(1 for n in news_list if n.get('newsTag') == 1)
        bearish_count = sum(1 for n in news_list if n.get('newsTag') == 3)

        bullish_ratio = bullish_count / count
        bearish_ratio = bearish_count / count

        anomaly_detected = False
        anomaly_msg = ""

        # 3. 检测 FUD (恐慌) 或 FOMO (贪婪)
        if bullish_ratio >= DOMINANCE_THRESHOLD:
            anomaly_detected = True
            anomaly_msg = f"FOMO ALERT: {bullish_ratio:.0%} of recent news is BULLISH."
            print(f"[AnomalyAgent] !!! {coin_name} {anomaly_msg} !!!")

        elif bearish_ratio >= DOMINANCE_THRESHOLD:
            anomaly_detected = True
            anomaly_msg = f"FUD ALERT: {bearish_ratio:.0%} of recent news is BEARISH."
            print(f"[AnomalyAgent] !!! {coin_name} {anomaly_msg} !!!")

        # 4. 如果有异常，回写到最新的一条新闻上
        if anomaly_detected and news_list:
            # 取列表中的第一条（假设 API 返回是按时间倒序，如果不是，可能需要按 time 排序）
            # 通常 fetch 接口返回的是最新的在前面，或者我们可以手动 sort
            latest_news = news_list[0]
            await write_anomaly_back_to_api(latest_news, anomaly_msg)