# src/core/mcp_server/crypto_sentiment_mcp.py
import httpx  # <-- [FIX] 导入 httpx
from mcp.server.fastmcp import FastMCP
from datetime import datetime, timedelta, UTC
# --- [FIX] 从中央配置导入 settings ---
from config.settings import settings

# ---

mcp = FastMCP("CryptoSentiment")

# --- [FIX] 直接使用导入的 settings 对象 ---
SANTIMENT_API_KEY = settings.SANTIMENT_API_KEY
# ---

if not SANTIMENT_API_KEY:
    raise ValueError("SANTIMENT_API_KEY not found in config/settings.py.")

SANTIMENT_API_URL = "https://api.santiment.net/graphql"
HEADERS = {"Authorization": f"Apikey {SANTIMENT_API_KEY}"}


# --- [FIX] 重写为异步函数 ---
async def fetch_santiment_data(metric: str, asset: str, days: int) -> dict:
    now = datetime.now(UTC)
    to_date = now
    from_date = to_date - timedelta(days=days)

    query = f"""
    {{
      getMetric(metric: "{metric}") {{
        timeseriesData(
          slug: "{asset}"
          from: "{from_date.isoformat()}"
          to: "{to_date.isoformat()}"
          interval: "1d"
        ) {{
          datetime
          value
        }}
      }}
    }}
    """
    # 使用 httpx.AsyncClient
    async with httpx.AsyncClient() as client:
        response = await client.post(SANTIMENT_API_URL, json={"query": query}, headers=HEADERS)

    result = response.json()
    if result.get("errors"):
        raise Exception(f"API error: {result.get('errors')}")
    return result


async def fetch_trending_words(days: int = 7) -> dict:
    now = datetime.now(UTC)
    to_date = now
    from_date = to_date - timedelta(days=days)

    query = f"""
    {{
      getTrendingWords(size: 10, from: "{from_date.isoformat()}", to: "{to_date.isoformat()}", interval: "1d") {{
        datetime
        topWords {{
          word
          score
        }}
      }}
    }}
    """
    # 使用 httpx.AsyncClient
    async with httpx.AsyncClient() as client:
        response = await client.post(SANTIMENT_API_URL, json={"query": query}, headers=HEADERS)

    result = response.json()
    if result.get("errors"):
        raise Exception(f"API error: {result.get('errors')}")
    return result


# --- [FIX] 所有的 tool 都必须是 async def ---

@mcp.tool()
async def get_sentiment_balance(asset: str, days: int = 7) -> str:
    """
    (异步) 检索给定资产的情绪平衡。
    """
    try:
        # [FIX] 使用 await 调用
        data = await fetch_santiment_data("sentiment_balance_total", asset, days)
        timeseries = data.get("data", {}).get("getMetric", {}).get("timeseriesData", [])
        if not timeseries:
            return f"Unable to fetch sentiment data for {asset}. Check subscription limits or asset availability."
        avg_balance = sum(float(d["value"]) for d in timeseries) / len(timeseries)
        return f"{asset.capitalize()}'s sentiment balance over the past {days} days is {avg_balance:.1f}."
    except Exception as e:
        return f"Error fetching sentiment balance for {asset}: {str(e)}"


@mcp.tool()
async def get_social_volume(asset: str, days: int = 7) -> str:
    """
    (异步) 检索给定资产的社交总量。
    """
    try:
        # [FIX] 使用 await 调用
        data = await fetch_santiment_data("social_volume_total", asset, days)
        timeseries = data.get("data", {}).get("getMetric", {}).get("timeseriesData", [])
        if not timeseries:
            return f"Unable to fetch social volume for {asset}. Check subscription limits or asset availability."
        total_volume = sum(int(d["value"]) for d in timeseries)
        return f"{asset.capitalize()}'s social volume over the past {days} days is {total_volume:,} mentions."
    except Exception as e:
        return f"Error fetching social volume for {asset}: {str(e)}"


@mcp.tool()
async def alert_social_shift(asset: str, threshold: float = 50.0, days: int = 7) -> str:
    """
    (异步) 检测社交总量的重大变化。
    """
    try:
        # [FIX] 使用 await 调用
        data = await fetch_santiment_data("social_volume_total", asset, days)
        timeseries = data.get("data", {}).get("getMetric", {}).get("timeseriesData", [])

        if not timeseries or len(timeseries) < 2:
            return f"Unable to detect social volume shift for {asset}, insufficient data."

        latest_volume = int(timeseries[-1]["value"])
        prev_avg_volume = sum(int(d["value"]) for d in timeseries[:-1]) / (
                len(timeseries) - 1)

        # 避免除零错误
        if prev_avg_volume == 0:
            return f"No baseline social volume for {asset.capitalize()} to detect shift."

        change_percent = ((latest_volume - prev_avg_volume) / prev_avg_volume) * 100

        abs_change = abs(change_percent)
        if abs_change >= threshold:
            direction = "spiked" if change_percent > 0 else "dropped"
            return f"{asset.capitalize()}'s social volume {direction} by {abs_change:.1f}% in the last 24 hours, from an average of {prev_avg_volume:,.0f} to {latest_volume:,}."
        return f"No significant shift detected for {asset.capitalize()}, change is {change_percent:.1f}%."
    except Exception as e:
        return f"Error detecting social volume shift for {asset}: {str(e)}"


@mcp.tool()
async def get_trending_words(days: int = 7, top_n: int = 5) -> str:
    """
    (异步) 检索热门词汇。
    """
    try:
        # [FIX] 使用 await 调用
        data = await fetch_trending_words(days)
        trends = data.get("data", {}).get("getTrendingWords", [])
        if not trends:
            return "Unable to fetch trending words. Check API subscription limits or connectivity."

        word_scores = {}
        for day in trends:
            for word_data in day["topWords"]:
                word = word_data["word"]
                score = word_data["score"]
                if word in word_scores:
                    word_scores[word] += score
                else:
                    word_scores[word] = score

        if not word_scores:
            return "No trending words data available for the specified period."

        top_words = sorted(word_scores.items(), key=lambda x: x[1], reverse=True)[:top_n]
        top_words_list = [word for word, _ in top_words]

        return f"Top {top_n} trending words over the past {days} days: {', '.join(top_words_list)}."
    except Exception as e:
        return f"Error fetching trending words: {str(e)}"


@mcp.tool()
async def get_social_dominance(asset: str, days: int = 7) -> str:
    """
    (异步) 检索社交主导地位。
    """
    try:
        # [FIX] 使用 await 调用
        data = await fetch_santiment_data("social_dominance_total", asset, days)
        timeseries = data.get("data", {}).get("getMetric", {}).get("timeseriesData", [])
        if not timeseries:
            return f"Unable to fetch social dominance for {asset}. Check subscription limits or asset availability."
        avg_dominance = sum(float(d["value"]) for d in timeseries) / len(timeseries)
        return f"{asset.capitalize()}'s social dominance over the past {days} days is {avg_dominance:.1f}%."
    except Exception as e:
        return f"Error fetching social dominance for {asset}: {str(e)}"

# [FIX] 移除 mcp.run()。它在被 main.py 导入时不需要
# if __name__ == "__main__":
#     mcp.run(transport="sse", port=8002)