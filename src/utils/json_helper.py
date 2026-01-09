# src/utils/json_helper.py
import json
from datetime import datetime, timezone
from src.schemas.data_models import TradingSignal


def append_signal_to_structure(current_text: str, new_signal: TradingSignal, signal_type: str) -> str:
    """
    将新的信号追加到 analysis 字段的列表中，保留历史记录。

    :param current_text: 数据库当前存储的 analysis 字符串
    :param new_signal: 新生成的 TradingSignal 对象
    :param signal_type: 列表名称，例如 'trend_signals' 或 'short_term_signals' (建议用复数)
    :return: 更新后的 JSON 字符串
    """
    data = {}

    # 1. 解析现有数据
    try:
        if current_text:
            data = json.loads(current_text)
    except (json.JSONDecodeError, TypeError):
        # 兼容旧格式：将旧字符串存为 base_analysis
        raw_text = current_text if current_text else ""
        parts = raw_text.split(" || ")
        clean_parts = [
            p for p in parts
            if "【MACRO_SIGNAL】" not in p
               and "【1H_PREDICTION】" not in p
               and p.strip()
        ]
        if clean_parts:
            data["base_analysis"] = " || ".join(clean_parts)

    # 2. 确保 data 是字典
    if not isinstance(data, dict):
        data = {"base_analysis": str(data)}

    # 3. 构造本次信号对象
    # 使用 UTC 时间
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    signal_entry = {
        "timestamp": now_utc,
        "direction": new_signal.trend_24h,
        "confidence": new_signal.confidence,
        "reasoning": new_signal.reasoning,
        "chain_of_thought": new_signal.chain_of_thought
    }

    # 4. 关键修改：处理列表追加逻辑
    # 如果该 key 不存在，初始化为空列表
    if signal_type not in data:
        data[signal_type] = []

    # 确保它确实是一个列表 (防止旧数据中它是一个对象)
    if not isinstance(data[signal_type], list):
        # 如果旧数据是单个对象，把它包进列表里，实现平滑迁移
        old_obj = data[signal_type]
        data[signal_type] = [old_obj]

    # 5. 追加新信号
    data[signal_type].append(signal_entry)

    # (可选) 可以在这里限制最大长度，比如保留最近10条，防止无限膨胀
    # if len(data[signal_type]) > 10:
    #     data[signal_type] = data[signal_type][-10:]

    # 6. 返回 JSON 字符串
    return json.dumps(data, ensure_ascii=False)