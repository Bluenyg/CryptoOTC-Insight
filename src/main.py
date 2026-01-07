# src/main.py
import sys
import os
import asyncio
import time  # [新增] 引入 time 模块用于缓存计时
import uvicorn
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import httpx

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Form, Response
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# 保持原有引用 (请确保这些文件存在)
from src.agents.large_agents.scheduler import schedule_trend_agent, schedule_anomaly_agent, schedule_short_term_agent
from src.agents.small_agents.pipeline import small_agent_graph
from src.schemas.data_models import RawDataInput
from src.core.collectors import run_news_collector

# --- 配置 ---
ACCESS_PASSWORD = "admin"
COOKIE_NAME = "mas_quant_session"
FETCH_API_URL = "http://api.ibyteai.com:15008/10Ai/dataCenter/crypto/fetchCryptoPanic"
HEADERS = {'Content-Type': 'application/json'}

# ==========================================
# 🛡️ [新增] 全局内存缓存配置
# ==========================================
# 作用：防止前端频繁刷新把外部 API 打挂。
# 逻辑：在 CACHE_DURATION 秒内，直接返回内存里的数据，不发送网络请求。
GLOBAL_DATA_CACHE = {
    "data": [],
    "last_updated": 0,
    "lock": asyncio.Lock()  # 线程锁，防止高并发下多个请求同时穿透缓存
}
CACHE_DURATION = 10  # 缓存有效期 10 秒

# --- Windows Loop Fix ---
if sys.platform.startswith("win"):
    try:
        current_policy = asyncio.get_event_loop_policy()
        if not isinstance(current_policy, asyncio.WindowsProactorEventLoopPolicy):
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


# --- Lifecycle ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Application starting up...")
    asyncio.create_task(schedule_trend_agent())
    asyncio.create_task(schedule_anomaly_agent())
    # [新增] 启动短线预测 Agent
    asyncio.create_task(schedule_short_term_agent())
    asyncio.create_task(run_news_collector())
    print("All Background Tasks scheduled.")
    yield
    print("Application shutting down...")


app = FastAPI(title="MAS-Quant Pro Dashboard", version="2.2.3", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if not os.path.exists("static"):
    os.makedirs("static")
app.mount("/static", StaticFiles(directory="static"), name="static")

# ==========================================
# 🔐 认证
# ==========================================
LOGIN_HTML = """
<!DOCTYPE html>
<html lang="zh-CN" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>System Access</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>body { background-color: #0b0e14; color: #e2e8f0; }</style>
</head>
<body class="h-screen flex items-center justify-center">
    <div class="w-full max-w-sm p-8 bg-slate-900 border border-slate-800 rounded-lg shadow-2xl">
        <div class="text-center mb-8">
            <div class="w-12 h-12 bg-indigo-600 rounded mx-auto flex items-center justify-center text-white font-bold text-xl mb-3">M</div>
            <h1 class="text-lg font-bold tracking-wide">MAS-QUANT PRO</h1>
            <p class="text-xs text-slate-500 mt-1">SECURE ACCESS REQUIRED</p>
        </div>
        <form action="/login" method="post" class="space-y-5">
            <div>
                <input type="password" name="password" required placeholder="ENTER ACCESS CODE"
                       class="w-full bg-slate-950 border border-slate-700 rounded px-4 py-3 text-sm focus:border-indigo-500 outline-none text-center tracking-widest transition-all placeholder:text-slate-600">
            </div>
            <button type="submit" class="w-full bg-indigo-600 hover:bg-indigo-500 text-white font-bold py-3 px-4 rounded transition-all text-xs tracking-wider">
                INITIALIZE SESSION
            </button>
        </form>
    </div>
</body>
</html>
"""


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/dashboard")


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.cookies.get(COOKIE_NAME) == "granted":
        return RedirectResponse(url="/dashboard")
    return LOGIN_HTML


@app.post("/login")
async def login_action(response: Response, password: str = Form(...)):
    if password == ACCESS_PASSWORD:
        redirect = RedirectResponse(url="/dashboard", status_code=303)
        redirect.set_cookie(key=COOKIE_NAME, value="granted", max_age=60 * 60 * 24 * 7, httponly=True)
        return redirect
    else:
        return HTMLResponse(
            content=LOGIN_HTML.replace("SECURE ACCESS REQUIRED", "<span class='text-red-500'>ACCESS DENIED</span>"),
            status_code=401)


@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login")
    response.delete_cookie(COOKIE_NAME)
    return response


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_view(request: Request):
    if request.cookies.get(COOKIE_NAME) != "granted":
        return RedirectResponse(url="/login")

    file_path = os.path.join("static", "index.html")
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    else:
        return HTMLResponse("Error: static/index.html not found.", status_code=404)


# ==========================================
# 📡 数据接口 (修复了时间转换逻辑 + 增加缓存)
# ==========================================

async def fetch_coin_data(client: httpx.AsyncClient, coin_type: int, coin_name: str):
    # 【修改前】使用的是本地时间且中间是空格
    # end_time = datetime.now()
    # start_time = end_time - timedelta(hours=72)
    # json_data = {
    #     "type": coin_type,
    #     "startTime": start_time.strftime("%Y-%m-%d %H:%M:%S"),
    #     "endTime": end_time.strftime("%Y-%m-%d %H:%M:%S")
    # }

    # 【修改后】使用 UTC 时间，并添加 'T' 分隔符
    end_time = datetime.utcnow()  # 建议统一用 UTC 请求
    start_time = end_time - timedelta(hours=72)

    json_data = {
        "type": coin_type,
        # 这里加上 T
        "startTime": start_time.strftime("%Y-%m-%dT%H:%M:%S"),
        "endTime": end_time.strftime("%Y-%m-%dT%H:%M:%S")
    }
    try:
        response = await client.post(FETCH_API_URL, headers=HEADERS, json=json_data, timeout=15.0)
        if response.status_code == 200:
            data = response.json()
            cleaned_data = []
            found_tags_count = 0
            for item in data:
                final_tag = 0
                candidate_keys = ['newsTag', 'newTag', 'tag', 'trendTag']
                for key in candidate_keys:
                    raw_val = item.get(key)
                    if raw_val is None or raw_val == "null" or str(raw_val).strip() == "": continue
                    try:
                        val_int = int(float(raw_val))
                        if val_int in [1, 2, 3]:
                            final_tag = val_int
                            break
                    except (ValueError, TypeError):
                        continue

                if final_tag != 0: found_tags_count += 1

                item['coin_type'] = coin_name
                item['newsTag'] = final_tag
                item['analysis'] = item.get('analysis') or ""
                item['summary'] = item.get('summary') or ""
                content_display = item.get('summary')
                if not content_display: content_display = item.get('title')
                item['display_content'] = content_display
                cleaned_data.append(item)

            if found_tags_count > 0:
                print(f"✅ [API] {coin_name}: Fetched {found_tags_count} valid Tags")
            return cleaned_data
        else:
            print(f"API Error fetching {coin_name}: Status {response.status_code}")
    except Exception as e:
        print(f"Error fetching {coin_name}: {e}")
    return []


@app.get("/api/dashboard/data")
async def get_dashboard_data(response: Response, request: Request):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"

    current_time = time.time()

    # ========================================================
    # 🛡️ 缓存检查层 (Cache Layer)
    # ========================================================
    async with GLOBAL_DATA_CACHE["lock"]:  # 加锁
        # 如果距离上次更新不足 CACHE_DURATION 秒，且缓存里有数据
        if current_time - GLOBAL_DATA_CACHE["last_updated"] < CACHE_DURATION:
            if GLOBAL_DATA_CACHE["data"]:
                # 直接返回缓存的数据，不请求外部 API
                # print("🛡️ [Cache] Serving cached data (Skipping API call)")

                # 计算当前的显示时间 (UTC+8)
                utc_now = datetime.utcnow()
                beijing_time = utc_now + timedelta(hours=8)

                return {
                    "updated_at": beijing_time.strftime("%H:%M:%S"),
                    "total_count": len(GLOBAL_DATA_CACHE["data"]),
                    "data": GLOBAL_DATA_CACHE["data"]
                }
    # ========================================================

    # 如果缓存过期或为空，执行真实的 API 请求
    # print("🔄 [API] Cache expired, fetching new data...")

    try:
        async with httpx.AsyncClient() as client:
            results = await asyncio.gather(
                fetch_coin_data(client, 1, "BTC"),
                fetch_coin_data(client, 2, "ETH")
            )

        all_news = []
        for res in results:
            if res: all_news.extend(res)

        all_news.sort(key=lambda x: str(x.get('time', '0')), reverse=True)

        # --- 【增强版】调试与多格式兼容时间转换 ---
        # print(f"DEBUG: Processing {len(all_news)} items...")  # 调试信息

        for item in all_news:
            raw_time = item.get('time')
            if raw_time and isinstance(raw_time, str):
                try:
                    # 1. 预处理：不管是 "2025-12-18T12:00:00Z" 还是 "2025-12-18 12:00:00"
                    # 先把 T 换成空格，把 Z 去掉，这样下面 strptime 就能统一用空格格式处理
                    clean_time = raw_time.replace("T", " ").replace("Z", "").strip()

                    # 2. 去除毫秒
                    if "." in clean_time:
                        clean_time = clean_time.split(".")[0]

                    # 3. 解析 (因为上面replace了T，这里只用匹配空格格式即可)
                    dt_obj = datetime.strptime(clean_time, "%Y-%m-%d %H:%M:%S")

                    # 4. 加上 8 小时 (UTC -> 北京时间)
                    dt_bj = dt_obj + timedelta(hours=8)

                    # 5. 存回
                    item['time'] = dt_bj.strftime("%Y-%m-%d %H:%M:%S")

                except Exception as e:
                    # 如果解析失败，保留原样，方便调试
                    print(f"⚠️ 时间解析错误 [{raw_time}]: {e}")
                    pass
        # --------------------------------------------------------

        # ========================================================
        # 💾 更新缓存 (Update Cache)
        # ========================================================
        async with GLOBAL_DATA_CACHE["lock"]:
            GLOBAL_DATA_CACHE["data"] = all_news
            GLOBAL_DATA_CACHE["last_updated"] = time.time()
        # ========================================================

        # Header 上次更新时间 (UTC+8)
        utc_now = datetime.utcnow()
        beijing_time = utc_now + timedelta(hours=8)

        return {
            "updated_at": beijing_time.strftime("%H:%M:%S"),
            "total_count": len(all_news),
            "data": all_news
        }

    except Exception as e:
        print(f"❌ [Dashboard Error] {e}")
        # 如果 API 请求失败，尝试返回旧的缓存兜底，防止前端白屏
        return {
            "updated_at": "Error (Cache Served)",
            "total_count": len(GLOBAL_DATA_CACHE["data"]),
            "data": GLOBAL_DATA_CACHE["data"]
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


# ==========================================
# 📈 [新增] K线数据代理接口 (用于前端绘图验证)
# ==========================================
@app.get("/api/market/history")
async def get_market_history(symbol: str = "BTCUSDT", interval: str = "1h", limit: int = 24):
    """
    代理币安 K 线数据，用于前端绘制价格走势图
    """
    binance_url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(binance_url, params=params, timeout=10.0)
            if resp.status_code == 200:
                raw_data = resp.json()
                # 简化数据，只返回 [时间戳(ms), 开盘, 最高, 最低, 收盘]
                # 币安返回格式: [Open time, Open, High, Low, Close, Volume, ...]
                cleaned = []
                for item in raw_data:
                    cleaned.append({
                        "time": item[0],
                        "open": float(item[1]),
                        "high": float(item[2]),
                        "low": float(item[3]),
                        "close": float(item[4])
                    })
                return {"symbol": symbol, "data": cleaned}
            else:
                return {"error": "Binance API Error", "data": []}
    except Exception as e:
        print(f"❌ [MarketAPI] Error: {e}")
        return {"error": str(e), "data": []}

if __name__ == "__main__":
    print(f"🚀 System Starting. Login Password: {ACCESS_PASSWORD}")
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=15288,
        reload=False,
        loop="asyncio"
    )