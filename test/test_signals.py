import asyncio
import httpx
import json
from datetime import datetime, timedelta

# --- 配置 (与你的项目保持一致) ---
FETCH_API_URL = "http://api.ibyteai.com:15008/10Ai/dataCenter/crypto/fetchCryptoPanic"
HEADERS = {'Content-Type': 'application/json'}


async def fetch_data(coin_type, coin_name):
    """拉取最近 48 小时的数据"""
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(hours=48)

    json_data = {
        "type": coin_type,
        "startTime": start_time.strftime("%Y-%m-%dT%H:%M:%S"),
        "endTime": end_time.strftime("%Y-%m-%dT%H:%M:%S")
    }

    print(f"🔄 Fetching {coin_name} data...")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(FETCH_API_URL, headers=HEADERS, json=json_data, timeout=20.0)
            if resp.status_code == 200:
                return resp.json()
            else:
                print(f"❌ Error {resp.status_code}")
                return []
        except Exception as e:
            print(f"❌ Exception: {e}")
            return []


async def main():
    # 1. 获取数据
    btc_data = await fetch_data(1, "BTC")
    eth_data = await fetch_data(2, "ETH")
    all_data = btc_data + eth_data

    # 按时间倒序
    all_data.sort(key=lambda x: x.get('time', ''), reverse=True)

    print(f"\n📊 Total News Items Fetched: {len(all_data)}")
    print("-" * 60)

    total_24h_signals = 0
    items_with_signals = 0

    # 2. 遍历检查
    for item in all_data:
        raw_analysis = item.get('analysis')
        title = item.get('title') or item.get('summary') or "No Title"
        title = title[:50].replace('\n', ' ') + "..."
        news_time = item.get('time')

        has_signal = False
        signal_count = 0
        latest_trend = "N/A"

        if raw_analysis:
            try:
                # 尝试解析 JSON
                if raw_analysis.strip().startswith("{"):
                    data = json.loads(raw_analysis)

                    # 检查 trend_signals (24H)
                    if "trend_signals" in data and isinstance(data["trend_signals"], list):
                        signals = data["trend_signals"]
                        signal_count = len(signals)
                        if signal_count > 0:
                            has_signal = True
                            total_24h_signals += signal_count
                            items_with_signals += 1
                            # 获取最新的一条方向
                            latest_trend = signals[-1].get('trend_24h', 'Unknown')

                    # 顺便检查一下 1H 信号
                    short_count = 0
                    if "short_term_signals" in data:
                        short_count = len(data["short_term_signals"])

                    if has_signal or short_count > 0:
                        print(f"✅ [{news_time}] ID:{item.get('objectId')}")
                        print(f"   Title: {title}")
                        if has_signal:
                            print(f"   🎯 24H Signals: {signal_count} 个 (Latest: {latest_trend})")
                            # 打印所有 24H 信号的时间戳，看看有没有覆盖
                            for idx, s in enumerate(data["trend_signals"]):
                                print(f"      - [{idx + 1}] TS: {s.get('timestamp')} | {s.get('trend_24h')}")
                        else:
                            print(f"   ⚠️ 24H Signals: 0")

                        if short_count > 0:
                            print(f"   ⚡ 1H  Signals: {short_count} 个")
                        print("-" * 40)

            except json.JSONDecodeError:
                # 旧数据可能是纯文本
                pass
            except Exception as e:
                print(f"Error parsing analysis: {e}")

    print("\n" + "=" * 60)
    print(f"📈 统计结果 (Past 48H):")
    print(f"   - 包含 24H 信号的新闻条数: {items_with_signals}")
    print(f"   - 系统中存储的 24H 信号总数: {total_24h_signals}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())