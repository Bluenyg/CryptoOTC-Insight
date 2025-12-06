import requests
import json
import time
from datetime import datetime, timedelta

# --- 配置 ---
FETCH_URL = "http://api.ibyteai.com:15008/10Ai/dataCenter/crypto/fetchCryptoPanic"
UPDATE_URL = "http://api.ibyteai.com:15008/10Ai/dataCenter/crypto/updatePanicNews"

HEADERS = {
    'Content-Type': 'application/json',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36'
}


def fetch_news_dynamic(coin_type=1):
    """使用动态时间窗口获取最近数据"""
    end_time = datetime.now()
    # 获取过去 72 小时的数据，确保能找到数据
    start_time = end_time - timedelta(hours=72)

    payload = {
        "type": coin_type,
        "startTime": start_time.strftime("%Y-%m-%d %H:%M:%S"),
        "endTime": end_time.strftime("%Y-%m-%d %H:%M:%S")
    }
    try:
        print(f"📡 (Fetch) 拉取范围: {payload['startTime']} ~ {payload['endTime']}")
        response = requests.post(FETCH_URL, headers=HEADERS, json=payload, timeout=15)
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ 拉取成功，获取到 {len(data)} 条数据")
            return data
        else:
            print(f"   ❌ 拉取失败: {response.status_code} {response.text}")
            return []
    except Exception as e:
        print(f"   ❌ 请求异常: {e}")
        return []


def inspect_field(data, key):
    """检查字段在 MongoDB 返回结果中的状态"""
    if key in data:
        value = data[key]
        return f"✅ 存在 (值: {value}, 类型: {type(value).__name__})"
    else:
        return "❌ 不存在 (MongoDB 未返回此字段)"


def run_test():
    print("=" * 60)
    print("🚀 MongoDB API 字段持久化深度测试")
    print("=" * 60)

    # 1. 第一次拉取
    news_list = fetch_news_dynamic(1)  # BTC
    if not news_list:
        news_list = fetch_news_dynamic(2)  # ETH

    if not news_list:
        print("⚠️ 无法获取数据，测试终止。")
        return

    # 锁定第一条数据
    target = news_list[0]
    target_id = target.get('objectId')

    if not target_id:
        print("❌ 数据没有 objectId，无法进行测试。")
        print(target)
        return

    print(f"\n🎯 锁定测试对象 ID: {target_id}")
    print("   [原始状态检查]")
    print(f"   - newsTag: {inspect_field(target, 'newsTag')}")
    print(f"   - summary: {inspect_field(target, 'summary')}")
    print(f"   - comment: {inspect_field(target, 'comment')}")
    print("-" * 60)

    # 2. 准备更新
    # 如果原始没有 tag，我们就设为 1；如果有，就换一个值
    current_tag = target.get('newsTag', 0)
    new_tag = 2 if current_tag == 1 else 1

    timestamp = datetime.now().strftime("%H:%M:%S")
    new_summary = f"【测试摘要】{timestamp} 写入"
    new_analysis = f"【测试分析】{timestamp} 写入"

    update_payload = {
        "objectId": target_id,
        "tag": new_tag,
        "summary": new_summary,
        "analysis": new_analysis
    }

    # 3. 执行更新
    print(f"📝 (Update) 发送更新请求...")
    print(f"   Payload: {json.dumps(update_payload, ensure_ascii=False)}")

    try:
        update_res = requests.post(UPDATE_URL, headers=HEADERS, json=update_payload, timeout=10)
        print(f"   Update 响应: {update_res.status_code} {update_res.text}")
    except Exception as e:
        print(f"   ❌ 更新请求异常: {e}")
        return

    # 4. 等待同步
    print("\n⏳ 等待 5 秒让 MongoDB 完成写入...")
    time.sleep(5)

    # 5. 第二次拉取验证
    print("\n🔄 (Fetch) 再次拉取数据验证...")
    news_list_v2 = fetch_news_dynamic(1) + fetch_news_dynamic(2)

    target_v2 = next((item for item in news_list_v2 if item.get('objectId') == target_id), None)

    if not target_v2:
        print("❌ 致命错误：第二次拉取找不到该 ID 的数据！")
        return

    print(f"\n📍 验证对象 ID: {target_id}")
    print("   [新状态检查]")
    print(f"   - newsTag: {inspect_field(target_v2, 'newsTag')}")
    print(f"   - summary: {inspect_field(target_v2, 'summary')}")
    print(f"   - comment: {inspect_field(target_v2, 'comment')} (Update接口的 analysis 对应这里的 comment)")

    # 6. 最终判定
    final_tag = target_v2.get('newsTag')
    final_summary = target_v2.get('summary')
    final_comment = target_v2.get('comment')

    print("-" * 60)
    if final_tag == new_tag and final_summary == new_summary and final_comment == new_analysis:
        print("🎉 测试通过！API 读写闭环正常。")
        print("   说明：字段已成功写入 MongoDB 并能被读出。")
    else:
        print("❌ 测试失败！写入的数据没有被读出。")
        print("   可能原因：")
        print("   1. 字段名称不匹配 (如后端存成了 analysis 而不是 comment)")
        print("   2. 接口有缓存，读到了旧数据")
        print("   3. MongoDB 写入被静默失败")


if __name__ == "__main__":
    run_test()