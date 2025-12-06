# src/main.py
import sys
import os
import asyncio
import uvicorn  # 导入 uvicorn

# --- 【关键修复】必须放在所有其他 asyncio 导入之前 ---
# 强制 Windows 使用支持子进程的 ProactorEventLoop
if sys.platform.startswith("win"):
    try:
        # 获取当前策略，如果不是 Proactor 则强制设置
        current_policy = asyncio.get_event_loop_policy()
        if not isinstance(current_policy, asyncio.WindowsProactorEventLoopPolicy):
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        # 如果获取失败，直接强制设置
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
# -------------------------------------------------------------

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import httpx

from src.agents.large_agents.scheduler import schedule_trend_agent, schedule_anomaly_agent
from src.agents.small_agents.pipeline import small_agent_graph
from src.schemas.data_models import RawDataInput
from src.core.collectors import run_news_collector

# --- 配置 ---
FETCH_API_URL = "http://api.ibyteai.com:15008/10Ai/dataCenter/crypto/fetchCryptoPanic"
HEADERS = {'Content-Type': 'application/json'}


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Application starting up...")
    # 确保在启动时只运行一次
    asyncio.create_task(schedule_trend_agent())
    asyncio.create_task(schedule_anomaly_agent())
    asyncio.create_task(run_news_collector())
    print("All Background Tasks scheduled.")
    yield
    print("Application shutting down...")


app = FastAPI(title="MAS-Quant Pro Dashboard", version="2.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if not os.path.exists("static"): os.makedirs("static")
app.mount("/dashboard", StaticFiles(directory="static", html=True), name="static")


@app.get("/", include_in_schema=False)
async def root(): return RedirectResponse(url="/dashboard")


# src/main.py

async def fetch_coin_data(client: httpx.AsyncClient, coin_type: int, coin_name: str):
    # 获取过去 72 小时数据
    end_time = datetime.now()
    start_time = end_time - timedelta(hours=72)

    json_data = {
        "type": coin_type,
        "startTime": start_time.strftime("%Y-%m-%d %H:%M:%S"),
        "endTime": end_time.strftime("%Y-%m-%d %H:%M:%S")
    }

    try:
        response = await client.post(FETCH_API_URL, headers=HEADERS, json=json_data, timeout=15.0)

        if response.status_code == 200:
            data = response.json()
            cleaned_data = []

            # 调试计数
            found_tags_count = 0

            for item in data:
                # --- 【终极清洗逻辑】 ---
                final_tag = 0

                # 扫描所有可能的字段
                candidate_keys = ['newsTag', 'newTag', 'tag', 'trendTag']

                for key in candidate_keys:
                    raw_val = item.get(key)

                    # 1. 过滤无效空值
                    if raw_val is None or raw_val == "null" or str(raw_val).strip() == "":
                        continue

                    try:
                        # 2. 【关键修复】先转 float，再转 int
                        # 这可以同时处理 3, "3", "3.0", 3.0
                        val_float = float(raw_val)
                        val_int = int(val_float)

                        # 3. 验证业务有效性 (1=Bullish, 2=Neutral, 3=Bearish)
                        if val_int in [1, 2, 3]:
                            final_tag = val_int
                            break  # 找到了就停止
                    except (ValueError, TypeError):
                        # 如果完全无法转换（比如是 "abc"），就继续看下一个字段
                        continue

                if final_tag != 0:
                    found_tags_count += 1
                # -----------------------

                # 赋值回标准字段
                item['coin_type'] = coin_name
                item['newsTag'] = final_tag

                # 兜底处理
                item['analysis'] = item.get('analysis') or ""
                item['summary'] = item.get('summary') or ""
                content_display = item.get('summary')
                if not content_display:
                    content_display = item.get('title')
                item['display_content'] = content_display

                cleaned_data.append(item)

            # 打印一次日志，确认这次请求里到底有几个有效的 Tag
            if found_tags_count > 0:
                print(f"✅ [API-FIX] {coin_name}: 成功清洗并读取到 {found_tags_count} 个有效 Tag")

            return cleaned_data
        else:
            print(f"API Error fetching {coin_name}: Status {response.status_code}")

    except Exception as e:
        print(f"Error fetching {coin_name}: {e}")

    return []


from fastapi import Response  # 需要在顶部导入 Response


@app.get("/api/dashboard/data")
async def get_dashboard_data(response: Response):
    # [核心修复] 告诉浏览器不要缓存此接口的数据
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"

    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            fetch_coin_data(client, 1, "BTC"),
            fetch_coin_data(client, 2, "ETH")
        )

    all_news = []
    for res in results:
        if res: all_news.extend(res)

    # 按时间倒序
    all_news.sort(key=lambda x: str(x.get('time', '0')), reverse=True)

    return {
        "updated_at": datetime.now().strftime("%H:%M:%S"),
        "total_count": len(all_news),
        "data": all_news
    }


@app.websocket("/ws/data_ingest")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.receive_json()
            await websocket.send_text("Received")
    except WebSocketDisconnect:
        pass


@app.post("/http/data_ingest")
async def http_endpoint(raw_data: RawDataInput):
    asyncio.create_task(small_agent_graph.ainvoke({"raw_data": raw_data}))
    return {"message": "Processing started."}


# --- 【必须这样运行】 ---
if __name__ == "__main__":
    print("🚀 System Starting with forced ProactorEventLoop...")

    # 1. 显式指定 loop="asyncio"，防止 Uvicorn 内部重置 Loop
    # 2. 建议先将 reload 设置为 False 测试一次，确认是否是 reload 机制导致的
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8088,
        reload=False,  # 🔴 改成 False
        loop="asyncio"  # <--- 【关键新增】强制使用 asyncio 标准库循环
    )