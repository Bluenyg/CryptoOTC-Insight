# src/main.py
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse  # <--- [新增] 导入重定向响应
import asyncio
import sys
from contextlib import asynccontextmanager

from src.core.database import create_db_pool, close_db_pool, create_tables
from src.agents.large_agents.scheduler import schedule_trend_agent, schedule_anomaly_agent
from src.agents.small_agents.pipeline import small_agent_graph
from src.schemas.data_models import RawDataInput
from src.core.collectors import run_news_collector


# --- lifespan 保持不变 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    print("Application starting up...")
    # 1. 初始化数据库

    # 2. 启动 "大智能体" 的后台分析器 (只读DB)
    asyncio.create_task(schedule_trend_agent())
    asyncio.create_task(schedule_anomaly_agent())
    print("Large Agent Schedulers (Trend, Anomaly) started.")

    # 3.. 启动 "小智能体" 的后台采集器
    asyncio.create_task(run_news_collector())
    print("Collector Tasks (News, Sentiment) started.")

    yield

    # --- Shutdown ---
    print("Application shutting down...")



# --- 你的主应用 ---
app = FastAPI(
    title="MAS-Quant 系统",
    description="基于多智能体架构的加密货币量化分析系统 API 文档",
    version="1.0.0",
    lifespan=lifespan,
    # [说明] 显式开启文档路径 (虽然默认就是这些，写出来更清晰)
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

print("Main API server running on port 8000.")


# --- [新增] 根路径重定向到 /docs ---
# 这样你打开 http://localhost:8000 就会直接跳转到文档
@app.get("/", include_in_schema=False)
async def root():
    """访问根路径时自动跳转到 API 文档"""
    return RedirectResponse(url="/docs")


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
    """
    手动通过 HTTP 推送数据给 Agent 处理
    """
    asyncio.create_task(
        small_agent_graph.ainvoke({"raw_data": raw_data})
    )
    return {"message": "Data received and processing started."}