import asyncio
import httpx
from datetime import datetime, timedelta
import json

# --- 配置 (与你的项目保持一致) ---
FETCH_API_URL = "http://api.ibyteai.com:15008/10Ai/dataCenter/crypto/fetchCryptoPanic"
HEADERS = {'Content-Type': 'application/json'}


async def fetch_and_find_trend_signals(coin_type: int, coin_name: str):
    """
    获取数据并查找 Trend Agent 留下的痕迹
    """
    print(f"\n🔍 正在获取 {coin_name} (Type {coin_type}) 的数据...")

    # 1. 构造时间范围 (保持与 main.py 一致)
    end_time = datetime.now() + timedelta(hours=8)
    start_time = end_time - timedelta(hours=72)  # 获取过去72小时

    json_data = {
        "type": coin_type,
        "startTime": start_time.strftime("%Y-%m-%d %H:%M:%S"),
        "endTime": end_time.strftime("%Y-%m-%d %H:%M:%S")
    }

    async with httpx.AsyncClient() as client:
        try:
            # 2. 发起请求
            response = await client.post(FETCH_API_URL, headers=HEADERS, json=json_data, timeout=15.0)

            if response.status_code != 200:
                print(f"❌ API 请求失败: {response.status_code}")
                return

            data = response.json()
            print(f"📦 API 返回了 {len(data)} 条原始数据")

            found_count = 0

            # 3. 筛选 Trend Agent 信号
            # Trend Agent 的特征是：analysis 字段包含 "MACRO_SIGNAL"
            for item in data:
                analysis_text = item.get('analysis', '')

                # [关键判断] 检查是否有宏观信号标记
                if analysis_text and "MACRO_SIGNAL" in analysis_text:
                    found_count += 1
                    obj_id = item.get('objectId')
                    news_tag = item.get('newsTag')
                    title = item.get('title', 'No Title')

                    print("-" * 60)
                    print(f"✅ 找到 Trend Agent 信号! (ID: {obj_id})")
                    print(f"   📅 时间: {item.get('time')}")
                    print(f"   🏷️ Tag: {news_tag} (1=Bullish, 2=Neutral, 3=Bearish)")
                    print(f"   📝 标题: {title[:50]}...")

                    # 解析分析字段，提取信号详情
                    # 格式通常是: ... || 【MACRO_SIGNAL】:0.85|BULLISH|Reasoning...
                    try:
                        # 简单的文本切割展示
                        parts = analysis_text.split("【MACRO_SIGNAL】:")
                        if len(parts) > 1:
                            signal_content = parts[1].split("||")[0].strip()  # 取信号部分
                            print(f"   🔮 [信号详情]: {signal_content}")
                        else:
                            print(f"   📄 [原始分析]: {analysis_text[:100]}...")
                    except Exception:
                        pass

            if found_count == 0:
                print(f"⚠️ 在 {coin_name} 的最近数据中未找到 Trend Agent 的预测记录。")
                print("   可能原因: 1. Agent还未运行; 2. 运行了但没有更新到最新新闻上; 3. 时间窗口内无数据。")
            else:
                print(f"\n🎉 总结: 在 {coin_name} 中共找到 {found_count} 条包含 Trend Agent 预测的新闻。")

        except Exception as e:
            print(f"❌ 发生错误: {e}")


async def main():
    # 测试 BTC (Type 1)
    await fetch_and_find_trend_signals(1, "BTC")

    # 测试 ETH (Type 2)
    await fetch_and_find_trend_signals(2, "ETH")


if __name__ == "__main__":
    # Windows 上的 asyncio 策略修复 (如果需要)
    import sys

    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    asyncio.run(main())