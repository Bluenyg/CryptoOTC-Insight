# src/main.py
import sys
import os
import asyncio
import time
import json
import uvicorn
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import httpx

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Form, Response
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from src.schemas.data_models import RawDataInput
# ==========================================
# 🛠️ [修改 1] 导入单次运行的逻辑函数
# ==========================================
# 注意：你需要确保这些文件里有 run_xxx 并且它们不是 while True 循环
# 如果它们是 while True，请参照 collectors.py 的方式把循环去掉
from src.agents.large_agents.trend_agent import run_trend_analysis
from src.agents.large_agents.anomaly_agent import run_anomaly_detection
from src.agents.large_agents.short_term_agent import run_short_term_analysis
from src.core.collectors import run_news_collector

# --- 配置 ---
ACCESS_PASSWORD = "admin"
COOKIE_NAME = "mas_quant_session"
FETCH_API_URL = "http://api.ibyteai.com:15008/10Ai/dataCenter/crypto/fetchCryptoPanic"
HEADERS = {'Content-Type': 'application/json'}

# 缓存配置
GLOBAL_DATA_CACHE = {
    "data": [],
    "last_updated": 0,
    "lock": asyncio.Lock()
}
CACHE_DURATION = 10

if sys.platform.startswith("win"):
    try:
        current_policy = asyncio.get_event_loop_policy()
        if not isinstance(current_policy, asyncio.WindowsProactorEventLoopPolicy):
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


# ==========================================
# 🧠 [修改] 中央主控调度器 (Master Orchestrator)
# ==========================================
async def master_scheduler():
    """
    负责严格按照时间轴调度任务：
    - XX:02 -> 采集(重试3次) -> 1H预测 -> 24H预测
    - XX:12 -> 1H预测
    - XX:22 -> 采集(重试3次) -> 1H预测
    - XX:32 -> 1H预测
    - XX:42 -> 采集(重试3次) -> 1H预测
    - XX:52 -> 1H预测
    """
    print("⏳ [Master] 调度器已启动，正在等待下一个时间槽...")

    while True:
        now = datetime.now()
        minute = now.minute
        second = now.second

        # 定义任务触发点
        # 采集点: 02, 22, 42
        is_collection_slot = (minute in [2, 22, 42])
        # 仅预测点: 12, 32, 52
        is_prediction_slot = (minute in [12, 32, 52])
        # 24H 大周期点: 仅在 02 分 (且采集完成后)
        is_macro_slot = (minute == 2)

        # 这里的判断逻辑是：只要当前分钟符合，且秒数较小，就执行
        if (is_collection_slot or is_prediction_slot) and second < 5:
            print(f"\n======== [Cycle Start] {now.strftime('%H:%M:%S')} ========")

            # --- 阶段 1: 采集 (仅在 02, 22, 42 执行) ---
            if is_collection_slot:
                print("📡 [Step 1] 启动新闻采集 (Collector) - 3轮重试模式...")

                # [新增] 循环 3 次，对抗 API 延迟
                for i in range(3):
                    try:
                        print(f"   🔄 [Attempt {i + 1}/3] 正在拉取并清洗数据...")
                        # 运行一轮完整的采集+清洗
                        await run_news_collector()

                        # 如果不是最后一次，就稍微等一下 (例如 15秒)，给 API 一点缓冲时间让新数据冒出来
                        if i < 2:
                            wait_time = 15
                            print(f"   ⏳ 等待 {wait_time}秒 后进行下一次补录...")
                            await asyncio.sleep(wait_time)

                    except Exception as e:
                        print(f"❌ [Attempt {i + 1}] 采集器出错: {e}")

                print("✅ [Step 1] 3轮采集全部完成。")
            else:
                print("⏭️ [Step 1] 非采集时间点，跳过。")

            # --- 阶段 2: 1H 短线预测 (每10分钟都要执行) ---
            # 逻辑：如果是采集点，这里会在 3轮采集 全部结束后才运行 (大约 XX:03 分左右)
            print("⚡ [Step 2] 启动 1H 短线预测 (ShortTermAgent)...")
            try:
                await run_short_term_analysis()
            except Exception as e:
                print(f"❌ 1H Agent出错: {e}")

            # --- 阶段 3: 24H 趋势预测 (仅在 02 执行) ---
            if is_macro_slot:
                print("🌊 [Step 3] 启动 24H 趋势预测 (TrendAgent)...")
                try:
                    await run_trend_analysis()
                except Exception as e:
                    print(f"❌ 24H Agent出错: {e}")

            # --- 阶段 4: 异常检测 (挂在周期末尾) ---
            asyncio.create_task(run_anomaly_detection())

            print(f"✅ [Cycle End] 本轮任务全部完成。等待下一周期...")

            # 强制休眠 60秒，跳过当前分钟，防止重复触发
            await asyncio.sleep(60)

        else:
            # 如果不是目标分钟，或者秒数不对，稍微睡一下检查下一次
            await asyncio.sleep(1)


# --- Lifecycle ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Application starting up...")

    # 启动唯一的主控调度器，不再分别启动多个后台任务
    asyncio.create_task(master_scheduler())

    print("✅ [Lifespan] Master Scheduler 已启动。")
    yield
    print("Application shutting down...")


app = FastAPI(title="MAS-Quant Pro Dashboard", version="2.3.0", lifespan=lifespan)

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
# 📡 数据接口 (修复了时间转换逻辑 + 增加缓存 + JSON结构化解析)
# ==========================================

async def fetch_coin_data(client: httpx.AsyncClient, coin_type: int, coin_name: str):
    # 【修改后】使用 UTC 时间，并添加 'T' 分隔符
    end_time = datetime.utcnow()  # 建议统一用 UTC 请求
    start_time = end_time - timedelta(hours=72)

    json_data = {
        "type": coin_type,
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
                # --- 1. Tag 过滤逻辑 ---
                final_tag = 0
                candidate_keys = ['newsTag', 'newTag', 'tag', 'trendTag']
                for key in candidate_keys:
                    raw_val = item.get(key)
                    if raw_val is None or raw_val == "null" or str(raw_val).strip() == "": continue
                    try:
                        val_int = int(float(raw_val))
                        # 假设我们只关心有意义的 Tag (根据你的业务逻辑调整)
                        if val_int in [1, 2, 3]:
                            final_tag = val_int
                            break
                    except (ValueError, TypeError):
                        continue

                # 如果有有效 Tag，计数加一
                if final_tag != 0: found_tags_count += 1

                # --- 2. 基础字段赋值 ---
                item['coin_type'] = coin_name
                item['newsTag'] = final_tag
                item['summary'] = item.get('summary') or ""

                # 设置列表显示的简略内容
                content_display = item.get('summary')
                if not content_display: content_display = item.get('title')
                item['display_content'] = content_display

                # --- 3. Analysis 字段 JSON 解析与提取 (核心修改) ---
                raw_analysis = item.get('analysis') or ""
                structured_analysis = {}
                item['latest_trend'] = None  # 存放最新的 24H 趋势对象
                item['latest_short_term'] = None  # 存放最新的 1H 短线对象

                try:
                    # 尝试解析 JSON
                    if raw_analysis.strip().startswith("{"):
                        structured_analysis = json.loads(raw_analysis)
                    else:
                        raise ValueError("Not JSON")

                    # A. 提取最新的 24h 趋势 (Trend Agent)
                    # 逻辑：取 trend_signals 列表的最后一个元素
                    if "trend_signals" in structured_analysis and \
                            isinstance(structured_analysis["trend_signals"], list) and \
                            len(structured_analysis["trend_signals"]) > 0:
                        item['latest_trend'] = structured_analysis["trend_signals"][-1]

                    # B. 提取最新的 1h 短线 (Short Term Agent)
                    # 逻辑：取 short_term_signals 列表的最后一个元素
                    if "short_term_signals" in structured_analysis and \
                            isinstance(structured_analysis["short_term_signals"], list) and \
                            len(structured_analysis["short_term_signals"]) > 0:
                        item['latest_short_term'] = structured_analysis["short_term_signals"][-1]

                except (json.JSONDecodeError, ValueError, TypeError):
                    # 兼容旧数据格式 (非 JSON)
                    structured_analysis = {
                        "base_analysis": raw_analysis,
                        "trend_signals": [],
                        "short_term_signals": []
                    }

                # 将结构化后的对象挂载到 item 上，方便前端调用详情
                item['structured_analysis'] = structured_analysis
                # 保留原始 string 以备不时之需
                item['analysis'] = raw_analysis

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