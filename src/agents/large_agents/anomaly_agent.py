# src/agents/large_agents/anomaly_agent.py
import time
import asyncio
from sqlalchemy.future import select
from sqlalchemy import func, text
from datetime import datetime, timedelta
# --- [FIX] 导入 ---
from src.core.database import async_session
from src.core.models import SentimentMetrics, TradingSignals

# ---

# ... (配置保持不变) ...
ASSETS_TO_TRACK = ["bitcoin", "ethereum"]
ALERT_THRESHOLD_PERCENT = 50.0
DAYS_FOR_BASELINE = 7


async def run_anomaly_detection():
    print(f"[{time.ctime()}] Running Anomaly Agent (Reading DB)...")

    try:
        async with async_session() as session:
            for asset in ASSETS_TO_TRACK:
                metric_name = f"social_volume_{asset}"

                # 1. [FIX] 重写查询
                # SQLAlchemy 不像原始SQL那样容易处理“最新”和“次新”
                # 我们将获取所有数据并在Python中处理
                query = select(
                    SentimentMetrics.value,
                    SentimentMetrics.timestamp
                ).where(
                    SentimentMetrics.metric_name == metric_name,
                    SentimentMetrics.timestamp >= (datetime.now() - timedelta(days=DAYS_FOR_BASELINE + 1))
                ).order_by(SentimentMetrics.timestamp.desc())

                result = await session.execute(query)
                rows = result.all()  # 获取 (value, timestamp) 元组

                if not rows or len(rows) < 2:
                    print(f"[AnomalyAgent]: Insufficient data for {asset}")
                    continue

                # 2. 在本地实现警报逻辑 (保持不变)
                latest_volume = rows[0][0]  # 最新值
                previous_values = [r[0] for r in rows[1:]]

                if not previous_values:
                    continue

                prev_avg_volume = sum(previous_values) / len(previous_values)
                if prev_avg_volume == 0:
                    continue

                change_percent = ((latest_volume - prev_avg_volume) / prev_avg_volume) * 100
                abs_change = abs(change_percent)

                # 3. 检查是否触发阈值
                if abs_change >= ALERT_THRESHOLD_PERCENT:
                    direction = "spiked" if change_percent > 0 else "dropped"
                    reasoning = (
                        f"{asset.capitalize()}'s social volume {direction} by {abs_change:.1f}% "
                        f"(from {prev_avg_volume:,.0f} to {latest_volume:,.0f})."
                    )

                    print(f"[AnomalyAgent] !!! ANOMALY DETECTED !!!: {reasoning}")

                    # 4. [FIX] 写入数据库
                    signal_entry = TradingSignals(
                        trend_24h="BULLISH" if direction == "spiked" else "BEARISH",
                        confidence=0.9,
                        reasoning=reasoning,
                        agent_type="ANOMALY_DB"
                    )
                    # 因为我们在循环内，所以要在这里的子会话中添加
                    async with async_session() as inner_session:
                        async with inner_session.begin():
                            inner_session.add(signal_entry)
                else:
                    print(f"[AnomalyAgent]: No significant shift for {asset} ({change_percent:.1f}%)")

    except Exception as e:
        print(f"Error in Anomaly Agent (DB): {e}")