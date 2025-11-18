# src/main.py
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import asyncio
import sys
from contextlib import asynccontextmanager

from src.core.database import create_db_pool, close_db_pool, create_tables
from src.agents.large_agents.scheduler import schedule_trend_agent, schedule_anomaly_agent
from src.agents.small_agents.pipeline import small_agent_graph
from src.schemas.data_models import RawDataInput
from src.core.collectors import run_news_collector, run_sentiment_collector


# --- lifespan 保持不变 (它正确地启动了 Agent 和 Collector) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    print("Application starting up...")
    # 1. 初始化数据库
    await create_db_pool()
    # 2. 确保表已创建
    await create_tables()

    # 3. 启动 "大智能体" 的后台分析器 (只读DB)
    asyncio.create_task(schedule_trend_agent())
    asyncio.create_task(schedule_anomaly_agent())
    print("Large Agent Schedulers (Trend, Anomaly) started.")

    # 4. 启动 "小智能体" 的后台采集器 (轮询MCP并写入DB)
    asyncio.create_task(run_news_collector())
    asyncio.create_task(run_sentiment_collector())
    print("Collector Tasks (News, Sentiment) started.")

    yield

    # --- Shutdown ---
    print("Application shutting down...")
    await close_db_pool()


# --- 你的主应用 (传入 lifespan) ---
app = FastAPI(
    title="MAS-Quant 系统",
    description="运行 FastAPI,  2个采集器, 2个大Agent",
    lifespan=lifespan
)

print("Main API server running on port 8000.")


# --- WebSocket 和 HTTP 路由保持不变 ---
@app.websocket("/ws/data_ingest")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            json_data = await websocket.receive_json()

            try:
                raw_data = RawDataInput(**json_data)
            except Exception as e:
                await websocket.send_text(f"Invalid data format: {e}")
                continue

            # 异步调用 "小智能体" LangGraph
            asyncio.create_task(
                small_agent_graph.ainvoke({"raw_data": raw_data})
            )

            await websocket.send_text(f"Received and processing: {raw_data.content[:20]}...")

    except WebSocketDisconnect:
        print("Collector client disconnected from WebSocket.")
    except Exception as e:
        print(f"WebSocket Error: {e}")


@app.post("/http/data_ingest")
async def http_endpoint(raw_data: RawDataInput):
    asyncio.create_task(
        small_agent_graph.ainvoke({"raw_data": raw_data})
    )
    return {"message": "Data received and processing started."}