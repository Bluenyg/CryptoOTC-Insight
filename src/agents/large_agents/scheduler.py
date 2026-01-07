# src/agents/large_agents/scheduler.py
import asyncio
from config.settings import settings

# 导入你的两个大 Agent 的运行函数
from .trend_agent import run_trend_analysis
from .anomaly_agent import run_anomaly_detection
from .short_term_agent import run_short_term_analysis
# [FIX] 定义一个“启动延迟”，确保采集器先运行
# 我们的采集器在 10s 和 15s 启动，所以我们等到 30s
INITIAL_STARTUP_DELAY_SECONDS = 30


async def schedule_trend_agent():
    """
    按计划重复运行 24h趋势分析 Agent
    """
    # --- [FIX] 在循环开始前添加一次性延迟 ---
    print(f"[TrendAgentScheduler]: 启动... 将在 {INITIAL_STARTUP_DELAY_SECONDS} 秒后运行第一次分析。")
    await asyncio.sleep(INITIAL_STARTUP_DELAY_SECONDS)
    # ---

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
    # --- [FIX] 在循环开始前添加一次性延迟 ---
    print(f"[AnomalyAgentScheduler]: 启动... 将在 {INITIAL_STARTUP_DELAY_SECONDS} 秒后运行第一次分析。")
    await asyncio.sleep(INITIAL_STARTUP_DELAY_SECONDS)
    # ---

    while True:
        try:
            await run_anomaly_detection()
        except Exception as e:
            print(f"Anomaly Scheduler error: {e}")

        await asyncio.sleep(settings.ANOMALY_AGENT_SCHEDULE_SECONDS)


# [新增] 短线 Agent 调度器
async def schedule_short_term_agent():
    """
    每 15 分钟运行一次 1H 短线预测
    """
    # 稍微错开一点启动时间，避免和 Trend Agent 同时抢资源
    delay = INITIAL_STARTUP_DELAY_SECONDS + 15
    print(f"[ShortTermScheduler]: 启动... 延迟 {delay}秒。")
    await asyncio.sleep(delay)

    while True:
        try:
            await run_short_term_analysis()
        except Exception as e:
            print(f"ShortTerm Scheduler error: {e}")

        await asyncio.sleep(settings.SHORT_TERM_INTERVAL)