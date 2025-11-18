# src/agents/large_agents/scheduler.py
import asyncio
from config.settings import settings

# 导入我们新创建的Agent逻辑
from .trend_agent import run_trend_analysis
from .anomaly_agent import run_anomaly_detection


async def schedule_trend_agent():
    """
    按计划重复运行 24h趋势分析 Agent
    """
    while True:
        try:
            await run_trend_analysis()
        except Exception as e:
            print(f"Trend Scheduler error: {e}")

        await asyncio.sleep(settings.TREND_AGENT_SCHEDULE_SECONDS)


async def schedule_anomaly_agent():
    """
    按计划重复运行 异常检测 Agent
    """
    while True:
        try:
            await run_anomaly_detection()
        except Exception as e:
            print(f"Anomaly Scheduler error: {e}")

        await asyncio.sleep(settings.ANOMALY_AGENT_SCHEDULE_SECONDS)