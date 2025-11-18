# MAS-Quant: 多智能体加密货币量化场外信息分析系统

<div align="center">

![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)
![LangChain](https://img.shields.io/badge/LangChain-latest-red.svg)

**基于多智能体架构和 MCP 协议的智能化加密货币场外信息分析平台**

[English](./README_EN.md) | 简体中文

</div>

---

## 📖 目录

- [项目简介](#-项目简介)
- [系统架构](#-系统架构)
- [核心特性](#-核心特性)
- [快速开始](#-快速开始)
- [详细文档](#-详细文档)
- [数据库结构](#-数据库结构)
- [常见问题](#-常见问题)
- [部署指南](#-部署指南)
- [贡献指南](#-贡献指南)
- [许可证](#-许可证)
- [致谢](#-致谢)

---

## 🎯 项目简介

**MAS-Quant** 是一个先进的、基于**多智能体系统 (Multi-Agent System)** 和 **MCP (Model Context Protocol)** 的量化分析平台。系统自动从链下数据源获取海量信息，通过分层智能体网络进行清洗、分析和决策，最终生成针对 Bitcoin 和 Ethereum 的宏观交易信号。

### 为什么选择 MAS-Quant?

- 🤖 **智能化分析**: 集成多个 AI Agent 协同工作，自动化处理海量数据
- 🔄 **实时数据流**: 基于 SSE 协议的 MCP 服务器提供实时数据推送
- 🏗️ **模块化架构**: 采集、处理、分析完全解耦，易于扩展和维护
- 📊 **多维度分析**: 综合新闻情感、社交声量、链上指标等多维度数据
- ⚡ **高性能**: 异步架构支持高并发数据处理
- 🛡️ **生产就绪**: 完善的错误处理、日志记录和健康检查机制

---

## 🏗️ 系统架构

### 核心组件说明

#### 1. MCP 服务器层 (数据源)

**News MCP (Port 8001)**
- 功能: 对接 NewsData.io API，实时拉取加密货币新闻
- 技术: 基于 FastMCP，提供 SSE (Server-Sent Events) 数据流
- 工具:
  - `get_latest_news`: 获取最新新闻头条
  - `get_crypto_news`: 搜索特定关键词新闻

**Sentiment MCP (Port 8002)**
- 功能: 对接 Santiment API，获取社交媒体和链上指标
- 提供指标:
  - `social_volume`: 社交媒体讨论量
  - `sentiment_balance`: 正负情绪平衡
  - `social_dominance`: 社交话语权占比
  - `trending_words`: 热门讨论词汇

#### 2. 数据采集层 (Collectors)

运行在主进程中，作为 MCP 客户端轮询数据:

**NewsCollector**
- 轮询间隔: 5 分钟
- 流程: 获取新闻 → 去重 → 推送到 WebSocket → 触发小智能体处理
- 防重复: 维护 `seen_article_titles` 集合

**SentimentCollector**
- 轮询间隔: 5 分钟
- 流程: 获取数值指标 → 解析 → 直接存入数据库
- 跟踪资产: Bitcoin, Ethereum

#### 3. 微观处理层 (Small Agents)

基于 LangGraph 构建的智能体流水线:

**Filter Agent** (过滤智能体)
- 职责: 判断新闻是否与 BTC/ETH 价格相关
- 输出: `relevant: true/false`
- 优势: 减少无效数据处理，节省 LLM 调用成本

**NLP Agent** (分析智能体)
- 职责: 
  - 生成中文摘要
  - 情感分析 (BULLISH/BEARISH/NEUTRAL)
  - 市场影响力评估 (HIGH/MEDIUM/LOW)
  - 计算多空得分 (-1.0 到 1.0)
- 输出: 结构化数据存入 `processed_news` 表

#### 4. 宏观分析层 (Large Agents)

定时调度的高级分析智能体:

**Trend Agent** (趋势分析)
- 运行频率: 每 15 分钟
- 数据源: 过去 24 小时的新闻摘要 + 情绪指标
- 输出: 综合趋势判断 + 详细分析理由
- 置信度: 0.0 - 1.0

**Anomaly Agent** (异常检测)
- 运行频率: 每 5 分钟
- 检测目标: 社交声量异常脉冲、情绪剧烈波动
- 应用场景: 恐慌抛售、FOMO 暴涨等极端市场情绪
- 输出: 紧急交易信号

---

## ✨ 核心特性

### 技术特性

- ⚡ **异步架构**: 基于 FastAPI + asyncio，高性能并发处理
- 🔌 **MCP 协议**: 标准化的模型上下文协议，易于集成新数据源
- 🌊 **流式数据**: SSE 协议支持实时数据推送
- 🤖 **LangGraph**: 灵活的智能体工作流编排
- 🗄️ **ORM 支持**: SQLAlchemy 2.0，支持 SQLite/PostgreSQL
- 📝 **类型安全**: 完整的 Pydantic 数据验证
- 🔄 **自动重连**: 采集器内置重试和错误恢复机制
- 📊 **可观测性**: 详细的日志记录和性能监控

### 业务特性

- 📰 **多源数据融合**: 整合新闻、社交媒体、链上数据
- 🎯 **智能过滤**: 自动识别价格相关信息，降低噪音
- 💬 **情感分析**: NLP 模型提取市场情绪
- 📈 **趋势预测**: 基于历史数据的宏观趋势判断
- 🚨 **异常预警**: 实时检测市场异常波动
- 🔢 **量化信号**: 输出标准化的交易信号供策略使用

---

## 🚀 快速开始

### 前置要求

- Python 3.10 或更高版本
- pip 或 uv (包管理器)
- 稳定的网络连接 (用于访问外部 API)

### 安装步骤

#### 1. 克隆仓库

```bash
git clone https://github.com/yourusername/mas-quant.git
cd mas-quant
```

#### 2. 创建虚拟环境

```bash
# 使用 venv
python -m venv venv

# Windows 激活
venv\Scripts\activate

# macOS/Linux 激活
source venv/bin/activate
```

#### 3. 安装依赖

```bash
# 方式 1: 使用 pip
pip install -r requirements.txt

# 方式 2: 使用 uv (推荐，更快)
uv pip install -r requirements.txt
```

**核心依赖列表**:
```txt
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
sqlalchemy>=2.0.0
aiosqlite>=0.20.0
httpx>=0.27.0
mcp>=1.0.0
fastmcp>=0.2.0
langchain>=0.3.0
langchain-openai>=0.2.0
python-dotenv>=1.0.0
websockets>=13.0
pydantic>=2.0.0
```

#### 4. 配置环境变量

在项目根目录创建 `.env` 文件:

```bash
# 复制模板
cp .env.example .env

# 编辑配置
nano .env  # 或使用你喜欢的编辑器
```

#### 5. 初始化数据库

```bash
# 数据库会在首次启动时自动创建，也可以手动初始化
python -c "from src.core.database import create_tables; import asyncio; asyncio.run(create_tables())"
```

### 启动系统

MAS-Quant 需要**三个独立进程**协同工作。建议使用三个终端窗口:

#### 终端 1: News MCP 服务器

```bash
python -m src.core.mcp_server.crypto_news_mcp
```

#### 终端 2: Sentiment MCP 服务器

```bash
python -m src.core.mcp_server.crypto_sentiment_mcp
```

#### 终端 3: 主应用程序

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

### 验证安装

#### 1. 健康检查

```bash
curl http://localhost:8000/health
```

**期望响应**:
```json
{
  "status": "healthy",
  "services": {
    "database": "connected",
    "mcp_news": "running",
    "mcp_sentiment": "running"
  }
}
```

#### 2. 访问 API 文档

在浏览器中打开: [http://localhost:8000/docs](http://localhost:8000/docs)

你将看到交互式 API 文档 (Swagger UI)。

#### 3. 查看数据库

```bash
# 使用 sqlite3
sqlite3 test.db

# 查看表
.tables

# 查看最新新闻
SELECT * FROM processed_news ORDER BY created_at DESC LIMIT 5;

# 查看交易信号
SELECT * FROM trading_signals ORDER BY timestamp DESC LIMIT 5;
```

---

## 📚 详细文档

### API 端点

#### 核心端点

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/` | 系统状态和信息 |
| GET | `/health` | 健康检查 |
| GET | `/docs` | API 交互式文档 |
| POST | `/http/data_ingest` | HTTP 数据推送接口 |
| WebSocket | `/ws/data_ingest` | WebSocket 数据推送接口 |

#### MCP 端点 (内部)

| 服务 | 端点 | 描述 |
|------|------|------|
| News MCP | `http://localhost:8001/sse` | 新闻数据流 |
| Sentiment MCP | `http://localhost:8002/sse` | 情绪指标数据流 |

---

## 🗄️ 数据库结构

### 表结构说明

#### 1. `processed_news` - 处理后的新闻

存储经过 NLP 分析的新闻数据。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer | 主键 |
| raw_content | Text | 原始新闻内容 |
| summary | Text | 中文摘要 |
| sentiment | String | 情感倾向 (BULLISH/BEARISH/NEUTRAL) |
| market_impact | String | 影响力等级 (HIGH/MEDIUM/LOW) |
| long_short_score | Float | 多空得分 (-1.0 到 1.0) |
| created_at | DateTime | 创建时间 |

**示例数据**:
```json
{
  "id": 1,
  "raw_content": "Bitcoin breaks $50,000 resistance level...",
  "summary": "比特币突破5万美元关键阻力位，市场情绪乐观",
  "sentiment": "BULLISH",
  "market_impact": "HIGH",
  "long_short_score": 0.85,
  "created_at": "2025-11-18T14:30:00"
}
```

#### 2. `sentiment_metrics` - 情绪指标

存储从 Santiment 采集的原始时序数据。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer | 主键 |
| asset | String | 资产名称 (bitcoin/ethereum) |
| metric_name | String | 指标名称 |
| value | Float | 指标值 |
| timestamp | DateTime | 数据时间戳 |

**指标类型**:
- `social_volume_bitcoin`: Bitcoin 社交讨论量
- `sentiment_balance_bitcoin`: Bitcoin 情绪平衡
- `social_dominance_ethereum`: Ethereum 社交话语权
- 等等...

#### 3. `trading_signals` - 交易信号

系统的最终输出，供交易执行模块读取。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer | 主键 |
| trend_24h | String | 24小时趋势 (BULLISH/BEARISH/NEUTRAL) |
| confidence | Float | 置信度 (0.0 - 1.0) |
| reasoning | Text | 详细分析理由 |
| agent_type | String | 信号来源 (TREND_DB/ANOMALY_DB) |
| timestamp | DateTime | 信号生成时间 |

**示例数据**:
```json
{
  "id": 1,
  "trend_24h": "BULLISH",
  "confidence": 0.78,
  "reasoning": "过去24小时内,Bitcoin相关新闻情绪普遍积极,社交媒体讨论量激增45%...",
  "agent_type": "TREND_DB",
  "timestamp": "2025-11-18T15:00:00"
}
```

### 数据库查询示例

#### 查询最新交易信号
```sql
SELECT 
    trend_24h,
    confidence,
    reasoning,
    timestamp
FROM trading_signals
WHERE agent_type = 'TREND_DB'
ORDER BY timestamp DESC
LIMIT 1;
```

#### 统计情绪分布
```sql
SELECT 
    sentiment,
    COUNT(*) as count,
    AVG(long_short_score) as avg_score
FROM processed_news
WHERE created_at >= datetime('now', '-24 hours')
GROUP BY sentiment;
```

#### 检测异常信号
```sql
SELECT *
FROM trading_signals
WHERE 
    agent_type = 'ANOMALY_DB'
    AND timestamp >= datetime('now', '-1 hour')
ORDER BY timestamp DESC;
```

---

## ❓ 常见问题

### 安装和配置

<details>
<summary><b>Q: 如何获取 API Keys?</b></summary>

**Santiment API**:
1. 访问 [https://app.santiment.net/](https://app.santiment.net/)
2. 注册账号
3. 在 Account Settings → API Keys 中生成

**NewsData.io API**:
1. 访问 [https://newsdata.io/](https://newsdata.io/)
2. 注册免费账号 (每日 200 次请求)
3. 在 Dashboard 中获取 API Key

**OpenAI API** (或兼容接口):
- OpenAI: [https://platform.openai.com/api-keys](https://platform.openai.com/api-keys)
- Dashscope (阿里云): [https://dashscope.console.aliyun.com/](https://dashscope.console.aliyun.com/)
- Ollama (本地): 无需 API Key
</details>

<details>
<summary><b>Q: 支持哪些数据库?</b></summary>

- **SQLite** (默认): 适合开发和测试，无需额外配置
- **PostgreSQL**: 推荐生产环境使用，性能更好
- **MySQL**: 理论支持，需修改连接字符串

修改 `.env` 中的 `DATABASE_URL` 即可切换。
</details>

### 启动和运行

<details>
<summary><b>Q: 为什么需要三个终端?</b></summary>

MAS-Quant 采用微服务架构:
1. **MCP 服务器 (8001/8002)**: 独立的数据源服务，可单独扩展
2. **主应用 (8000)**: 业务逻辑和智能体调度

这样设计的好处:
- ✅ 解耦: 数据源和业务逻辑分离
- ✅ 可扩展: 可以轻松添加新的 MCP 服务器
- ✅ 容错: 一个服务崩溃不影响其他服务
- ✅ 调试: 每个服务的日志独立，便于排查问题
</details>

<details>
<summary><b>Q: 502 Bad Gateway 或连接超时怎么办?</b></summary>

**原因分析**:
1. MCP 服务器未启动
2. 端口被占用
3. 防火墙阻止连接

**解决步骤**:
```bash
# 1. 检查端口是否被占用
netstat -ano | findstr :8001  # Windows
lsof -i :8001                 # Linux/Mac

# 2. 确保 MCP 服务器正在运行
curl http://localhost:8001/sse

# 3. 检查 collectors.py 中的 URL
# 必须包含 /sse 后缀: http://localhost:8001/sse

# 4. 查看详细日志
# 主应用启动日志中会显示 MCP 连接状态
```
</details>

<details>
<summary><b>Q: 启动后长时间没有日志输出?</b></summary>

**这是正常的!** 系统设计了错峰启动机制:

- NewsCollector: 等待 10 秒后启动
- SentimentCollector: 等待 15 秒后启动  
- Trend Agent: 等待 30 秒后首次运行
- Anomaly Agent: 等待 30 秒后首次运行

**目的**: 防止启动时大量并发请求导致事件循环阻塞。

**耐心等待 1-2 分钟**,你会看到:
```
[NewsCollector]: 启动 (连接到 http://localhost:8001/sse)
[NewsCollector]: 正在拉取新闻...
[SentimentCollector]: 启动 (连接到 http://localhost:8002/sse)
[SentimentCollector]: 正在拉取情绪指标...
```
</details>

<details>
<summary><b>Q: Santiment API 报错 "Free Tier Limit"?</b></summary>

**免费版限制**:
- 只能获取 30 天前的历史数据
- 每日 API 调用次数有限

**解决方案**:

方案 1: 修改数据偏移 (已内置)
```python
# crypto_sentiment_mcp.py 中已配置
DATA_OFFSET_DAYS = 35  # 获取 35 天前的数据进行测试
```

方案 2: 升级到付费计划
- 访问 [Santiment Pricing](https://app.santiment.net/pricing)
- 升级后将 `DATA_OFFSET_DAYS` 设为 0 即可获取实时数据

方案 3: 使用模拟数据
- 系统支持在缺少 API Key 时返回测试数据
- 适合开发和演示
</details>

<details>
<summary><b>Q: 如何停止所有服务?</b></summary>

在每个终端窗口按 `Ctrl+C` 即可优雅停止。

或者使用脚本:
```bash
# Linux/Mac
./scripts/stop_all.sh

# Windows  
python scripts/stop_all_windows.py
```
</details>

### 数据和分析

<details>
<summary><b>Q: 多久能看到第一个交易信号?</b></summary>

**时间线**:
- 0-10 分钟: 采集器开始收集数据
- 10-30 分钟: 小智能体处理新闻，写入数据库
- 30-45 分钟: Trend Agent 首次运行，生成信号

**加速方法**:
- 修改 `.env` 中的调度间隔:
  ```env
  TREND_AGENT_SCHEDULE_SECONDS=60   # 改为 1 分钟
  ANOMALY_AGENT_SCHEDULE_SECONDS=30  # 改为 30 秒
  ```
- 手动触发 (开发模式):
  ```python
  from src.agents.large_agents.trend_agent import run_trend_agent
  import asyncio
  asyncio.run(run_trend_agent())
  ```
</details>

<details>
<summary><b>Q: 如何解读交易信号?</b></summary>

**信号字段说明**:

```python
{
  "trend_24h": "BULLISH",      # 趋势方向
  "confidence": 0.78,           # 置信度 (0-1)
  "reasoning": "详细分析...",   # LLM 生成的理由
  "agent_type": "TREND_DB"      # 信号来源
}
```

**交易建议**:
- `BULLISH` + 高置信度 (>0.7): 考虑做多
- `BEARISH` + 高置信度 (>0.7): 考虑做空  
- `NEUTRAL` 或 低置信度 (<0.5): 观望

**注意**: 
- ⚠️ 本系统仅供参考，不构成投资建议
- ⚠️ 建议结合其他技术指标和风险管理策略
- ⚠️ 加密货币市场波动大，请谨慎投资
</details>

<details>
<summary><b>Q: 如何查看历史数据和统计?</b></summary>

**方法 1: 使用 SQL**
```bash
sqlite3 test.db

# 查看过去 24 小时的新闻情感分布
SELECT 
    sentiment, 
    COUNT(*) as count,
    AVG(long_short_score) as avg_score
FROM processed_news 
WHERE created_at >= datetime('now', '-24 hours')
GROUP BY sentiment;
```

**方法 2: 使用 Python**
```python
from src.core.database import async_session
from src.core.models import ProcessedNews, TradingSignal
from sqlalchemy import select

async with async_session() as session:
    # 查询最新信号
    result = await session.execute(
        select(TradingSignal)
        .order_by(TradingSignal.timestamp.desc())
        .limit(10)
    )
    signals = result.scalars().all()
```

**方法 3: 可视化面板 (规划中)**
- 未来版本将提供 Web 界面
- 实时监控采集状态、信号生成、数据统计
</details>

### 扩展和定制

<details>
<summary><b>Q: 如何添加新的数据源?</b></summary>

**步骤**:

1. 创建新的 MCP 服务器:
```python
# src/core/mcp_server/my_custom_mcp.py
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("MyCustomDataSource")

@mcp.tool()
async def get_my_data() -> str:
    # 实现数据获取逻辑
    return "data"

if __name__ == "__main__":
    mcp.run(transport="sse", port=8003)
```

2. 创建对应的 Collector:
```python
# src/core/collectors.py
async def run_my_custom_collector():
    transport = SSETransport(url="http://localhost:8003/sse")
    client = Client(transport, timeout=30.0)
    
    async with client:
        result = await client.call_tool("get_my_data", arguments={})
        # 处理数据...
```

3. 在 main.py 中启动:
```python
asyncio.create_task(run_my_custom_collector())
```
</details>

<details>
<summary><b>Q: 如何修改智能体的分析逻辑?</b></summary>

智能体的核心逻辑在 `src/agents/` 目录:

**修改 NLP 分析**:
- 编辑 `src/agents/small_agents/nlp_agent.py`
- 修改 prompt 或添加新的分析维度

**修改趋势判断**:
- 编辑 `src/agents/large_agents/trend_agent.py`  
- 调整时间窗口、权重计算等

**修改异常检测**:
- 编辑 `src/agents/large_agents/anomaly_agent.py`
- 调整阈值、检测算法等

**示例 - 修改情感分析 prompt**:
```python
# src/agents/small_agents/nlp_agent.py

SYSTEM_PROMPT = """
你是一个专业的加密货币市场分析师。
请分析以下新闻，并给出:
1. 简短摘要 (50字以内)
2. 情感倾向 (BULLISH/BEARISH/NEUTRAL)
3. 市场影响力 (HIGH/MEDIUM/LOW)
4. 多空得分 (-1.0 到 1.0)

# 添加自定义规则
- 如果提到"监管"相关，倾向 BEARISH
- 如果提到"采用"相关，倾向 BULLISH
...
"""
```
</details>

<details>
<summary><b>Q: 如何集成到实际交易系统?</b></summary>

MAS-Quant 设计为**信号生成器**,不直接执行交易。集成方式:

**方案 1: 轮询数据库**
```python
# 你的交易系统
import asyncio
from src.core.database import async_session
from src.core.models import TradingSignal
from sqlalchemy import select

async def check_signals():
    async with async_session() as session:
        result = await session.execute(
            select(TradingSignal)
            .where(TradingSignal.timestamp >= datetime.now() - timedelta(minutes=5))
            .order_by(TradingSignal.timestamp.desc())
        )
        latest_signal = result.scalars().first()
        
        if latest_signal and latest_signal.confidence > 0.7:
            if latest_signal.trend_24h == "BULLISH":
                # 执行做多逻辑
                place_long_order()
            elif latest_signal.trend_24h == "BEARISH":
                # 执行做空逻辑
                place_short_order()

# 每分钟检查一次
while True:
    await check_signals()
    await asyncio.sleep(60)
```

**方案 2: WebSocket 推送 (需实现)**
```python
# 在 main.py 中添加
@app.websocket("/ws/signals")
async def signal_websocket(websocket: WebSocket):
    await websocket.accept()
    # 当有新信号时推送
    await websocket.send_json(signal)
```

**方案 3: 消息队列**
- 使用 RabbitMQ/Redis 发布信号
- 交易系统订阅消息队列
</details>

---

## 🚀 部署指南

### 生产环境部署

#### 使用 PostgreSQL

1. 安装 PostgreSQL:
```bash
# Ubuntu/Debian
sudo apt-get install postgresql postgresql-contrib

# macOS
brew install postgresql
```

2. 创建数据库:
```sql
CREATE DATABASE masquant;
CREATE USER masquant_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE masquant TO masquant_user;
```

3. 更新 `.env`:
```env
DATABASE_URL=postgresql+asyncpg://masquant_user:your_password@localhost:5432/masquant
```




## 🤝 贡献指南

我们欢迎所有形式的贡献!

### 如何贡献

1. **Fork 仓库**
2. **创建功能分支** (`git checkout -b feature/AmazingFeature`)
3. **提交更改** (`git commit -m 'Add some AmazingFeature'`)
4. **推送到分支** (`git push origin feature/AmazingFeature`)
5. **创建 Pull Request**

### 贡献类型

- 🐛 Bug 修复
- ✨ 新功能
- 📝 文档改进
- 🎨 代码优化
- 🧪 测试用例
- 🌐 翻译

### 代码规范

- 遵循 PEP 8 风格指南
- 使用 Black 格式化代码: `black src/`
- 使用 mypy 类型检查: `mypy src/`
- 添加必要的文档字符串
- 为新功能添加测试

### 提交规范

使用语义化的提交信息:

```
feat: 添加新的数据源支持
fix: 修复采集器连接超时问题
docs: 更新 API 文档
refactor: 重构智能体调度逻辑
test: 添加数据库模型测试
```

---

## 📄 许可证

本项目采用 **MIT License** 许可证。详见 [LICENSE](LICENSE) 文件。

```
MIT License

Copyright (c) 2025 MAS-Quant Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## 🙏 致谢

### 开源项目

感谢以下优秀的开源项目:

- [FastAPI](https://fastapi.tiangolo.com/) - 现代化的 Python Web 框架
- [LangChain](https://www.langchain.com/) - LLM 应用开发框架
- [SQLAlchemy](https://www.sqlalchemy.org/) - Python SQL 工具包
- [FastMCP](https://github.com/jlowin/fastmcp) - MCP 协议实现
- [Uvicorn](https://www.uvicorn.org/) - ASGI 服务器

### 数据提供商

- [NewsData.io](https://newsdata.io/) - 新闻 API 服务
- [Santiment](https://santiment.net/) - 加密货币分析平台



## ⚠️ 免责声明

**重要提示**: 

1. 本软件仅供**教育和研究目的**使用
2. **不构成任何投资建议**,请勿直接用于实际交易
3. 加密货币市场**高度波动**,投资有风险
4. 使用本软件进行交易的所有后果由用户自行承担
5. 开发者不对任何投资损失负责

**在使用本系统进行任何实际交易之前,请**:
- 充分理解加密货币市场的风险
- 咨询专业的财务顾问
- 进行充分的回测和模拟交易
- 建立完善的风险管理策略

---

<div>

**如果这个项目对你有帮助,请给我们一个 ⭐ Star!**

Made with ❤️ by MAS-Quant Team

[⬆ 回到顶部](#mas-quant-多智能体加密货币量化场外信息分析系统)

</div>