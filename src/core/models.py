# src/core/models.py
from sqlalchemy import create_engine, Column, Integer, String, Float, Text, DateTime, func
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.ext.asyncio import create_async_engine


# 1. 定义所有模型的基础类
class Base(DeclarativeBase):
    pass


# 2. 定义你的表结构
class ProcessedNews(Base):
    __tablename__ = "processed_news"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, server_default=func.now())
    raw_content = Column(Text)
    source = Column(String(100))
    summary = Column(Text)
    sentiment = Column(String(20))
    market_impact = Column(String(20))
    long_short_score = Column(Float)


class SentimentMetrics(Base):
    __tablename__ = "sentiment_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, server_default=func.now())
    asset = Column(String(50))
    metric_name = Column(String(100))
    value = Column(Float)


class TradingSignals(Base):
    __tablename__ = "trading_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, server_default=func.now())
    trend_24h = Column(String(20))
    confidence = Column(Float)
    reasoning = Column(Text)
    agent_type = Column(String(50))