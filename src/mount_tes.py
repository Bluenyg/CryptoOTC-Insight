"""
快速测试 FastAPI mount 的 MCP 服务器是否可访问
运行主应用后,在另一个终端运行此脚本
"""
import asyncio
import httpx


async def endpoints():
    print("=" * 60)
    print("🔍 测试 FastAPI 挂载的 MCP endpoints")
    print("=" * 60)

    urls_to_test = [
        "http://127.0.0.1:8000/",
        "http://localhost:8000/docs",
        "http://localhost:8000/news",
        "http://localhost:8000/news/sse",
        "http://localhost:8000/sentiment",
        "http://localhost:8000/sentiment/sse",
    ]

    async with httpx.AsyncClient(timeout=30.0) as client:
        for url in urls_to_test:
            print(f"\n测试: {url}")
            try:
                response = await client.get(url)
                print(f"  ✅ 状态码: {response.status_code}")
                print(f"  📄 Content-Type: {response.headers.get('content-type', 'N/A')}")
                if response.status_code == 200:
                    content_preview = response.text[:200]
                    print(f"  📝 响应预览: {content_preview}...")
                else:
                    print(f"  ⚠️  响应: {response.text[:200]}")
            except httpx.ConnectError:
                print(f"  ❌ 无法连接 (服务器可能未运行)")
            except httpx.TimeoutException:
                print(f"  ⏱️  超时")
            except Exception as e:
                print(f"  ❌ 错误: {e}")

    print("\n" + "=" * 60)
    print("💡 分析:")
    print("=" * 60)
    print("如果 /news 和 /sentiment 返回 404,说明 mount 没有成功")
    print("如果它们返回其他状态码,说明 mount 了但路径可能不对")
    print("=" * 60)


if __name__ == "__main__":
    print("\n⚠️  请确保你的主应用正在运行:")
    print("   uvicorn src.main:app --host 0.0.0.0 --port 8000\n")
    input("按 Enter 继续测试...")
    asyncio.run(endpoints())