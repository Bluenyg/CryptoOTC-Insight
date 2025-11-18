# src/schemas/data_models.py
from pydantic import BaseModel, Field
from typing import Optional, Literal

class RawDataInput(BaseModel):
    """通过MCP或WebSocket传入的原始数据"""
    source: str
    timestamp: float
    content: str

class ProcessedData(BaseModel):
    """NLP Agent分析后的结构化数据"""
    raw_content: str
    source: str
    summary: str
    sentiment: Literal["BULLISH", "BEARISH", "NEUTRAL"]
    market_impact: Literal["HIGH", "MEDIUM", "LOW"]
    # 你提到的“多空影响力”
    long_short_score: float = Field(..., description="范围 -1.0 (极度看空) 到 1.0 (极度看涨)")

class TradingSignal(BaseModel):
    """Large Agent生成的最终信号"""
    timestamp: float
    trend_24h: Literal["BULLISH", "BEARISH", "NEUTRAL"]
    confidence: float
    reasoning: str