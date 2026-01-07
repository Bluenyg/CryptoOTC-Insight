# config/settings.py
from pydantic_settings import BaseSettings, SettingsConfigDict
import os


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')

    SANTIMENT_API_KEY: str  # <-- [FIX] 添加此行
    NEWS_API_KEY: str  # <-- [FIX] 添加此行

    OPENAI_API_KEY: str
    OPENAI_BASE_URL:str
    DATABASE_URL: str
    #MCP_SERVER_COMMAND: str

    # 24h趋势分析 (大Agent - 趋势)
    TREND_AGENT_SCHEDULE_SECONDS: int = 900  # 15 分钟

    # 异常脉冲检测 (大Agent - 异常) - 运行更频繁
    ANOMALY_AGENT_SCHEDULE_SECONDS: int = 300  # 5 分钟

    # [新增] 短线 Agent 运行间隔：15分钟 (900秒)
    SHORT_TERM_INTERVAL : int = 300


settings = Settings()