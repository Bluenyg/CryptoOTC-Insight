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
    NLP Agent (清洗/打标) 分析后的结构化数据
    """
    raw_content: str
    source: str
    summary: str
    sentiment: Literal["BULLISH", "BEARISH", "NEUTRAL"]

    market_impact: Literal["HIGH", "MEDIUM", "LOW"] = Field(
        ...,
        description="该消息对市场的预期冲击力。HIGH: 重大宏观/黑天鹅; MEDIUM: 项目进展/常规利好; LOW: 噪音/小道消息"
    )

    long_short_score: float = Field(
        ...,
        ge=-1.0,
        le=1.0,
        description="范围 -1.0 (极度看空) 到 1.0 (极度看涨)，0 为完全中性"
    )

    object_id: str

class TradingSignal(BaseModel):
    """Large Agent生成的最终信号"""
    # 【新增】强制思考字段 (必须放在第一位！)
    chain_of_thought: str = Field(
        ...,
        description="【深度思考区】在给出结论前，请先在此处进行逐步推演。\n"
                    "1. 分析多空力量对比 (Bullish vs Bearish count)。\n"
                    "2. 检查时间权重 (Time Decay) 和量价配合。\n"
                    "3. 模拟反方观点 (Counter-argument)，以此验证你的结论是否稳固。\n"
                    "请写出一段不少于 100 字的内部推演过程。"
    )
    timestamp: float
    # 1. 趋势方向 (修改版：仅定义方向含义)
    trend_24h: Literal["BULLISH", "BEARISH", "NEUTRAL"] = Field(
        ...,
        description="预测的市场趋势方向。BULLISH: 看涨(价格预期上涨); BEARISH: 看跌(价格预期下跌); NEUTRAL: 中性(震荡盘整或方向不明)。"
    )
    confidence: float
    # 3. 分析理由 (最关键的字段，强制模型通过描述进行思考)
    reasoning: str = Field(
        ...,
        description="详细的分析逻辑摘要 (200字以内)。\n"
                    "必须明确包含以下要素：\n"
                    "1. 【情绪阶段】: 判定当前处于爆发期、消化期还是衰退期。\n"
                    "2. 【核心驱动】: 指出最关键的那条新闻或事件。\n"
                    "3. 【风险提示】: 如果存在量价背离或旧闻干扰，必须在此指出。"
    )