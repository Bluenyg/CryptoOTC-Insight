# src/schemas/data_models.py
from pydantic import BaseModel, Field
from typing import Optional, Literal

class RawDataInput(BaseModel):
    """
    从 API 获取的原始数据
    """
    source: str
    timestamp: float
    content: str
    # [新增] 外部系统的唯一ID，用于后续回传更新
    object_id: str = Field(..., description="来自 fetchCryptoPanic 接口的 objectId")

class ProcessedData(BaseModel):
    """
    NLP Agent分析后的结构化数据
    """
    raw_content: str
    source: str
    summary: str
    sentiment: Literal["BULLISH", "BEARISH", "NEUTRAL"]
    market_impact: Literal["HIGH", "MEDIUM", "LOW"]
    long_short_score: float = Field(..., description="范围 -1.0 (极度看空) 到 1.0 (极度看涨)")
    # [新增] 传递 object_id 到处理结果中
    object_id: str

class TradingSignal(BaseModel):
    """Large Agent生成的最终信号"""
    timestamp: float
    trend_24h: Literal["BULLISH", "BEARISH", "NEUTRAL"]
    confidence: float
    reasoning: str