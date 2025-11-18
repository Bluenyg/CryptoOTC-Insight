# src/core/database.py
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from config.settings import settings
from src.core.models import Base  # 导入你的模型 Base

# 1. 根据 .env 文件创建引擎
# 它会自动知道是 SQLite 还是 PostgreSQL
engine = create_async_engine(settings.DATABASE_URL)

# 2. 创建一个异步会话 "工厂"
# 我们将在代码中用它来与数据库通信
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def create_db_pool():
    # 这个函数现在只是为了兼容，我们可以在 main.py 中直接调用 create_tables
    print("SQLAlchemy Engine created.")

async def close_db_pool():
    print("Closing SQLAlchemy Engine.")
    await engine.dispose()

async def create_tables():
    """
    (新) 在启动时创建所有 SQLAlchemy 模型对应的表
    """
    async with engine.begin() as conn:
        # 这会查看所有继承自 Base 的类并创建它们
        # 'IF NOT EXISTS' 是隐式包含的
        await conn.run_sync(Base.metadata.create_all)
    print("SQLAlchemy tables checked/created successfully.")