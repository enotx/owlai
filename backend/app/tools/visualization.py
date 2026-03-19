# backend/app/tools/visualization.py

"""
ECharts 可视化 tool 的验证与归一化逻辑。
从 analyst_agent.py 抽离，方便复用和测试。
"""

import json
from typing import Any


def validate_echarts_option(option: dict) -> tuple[bool, str]:
    """基础校验 ECharts option 结构，返回 (is_valid, error_message)"""
    if not isinstance(option, dict):
        return False, "option must be a JSON object"
    if "series" not in option:
        return False, "option must contain 'series'"
    series = option["series"]
    if not isinstance(series, list) or len(series) == 0:
        return False, "option.series must be a non-empty array"
    for i, s in enumerate(series):
        if not isinstance(s, dict):
            return False, f"series[{i}] must be an object"
        if "type" not in s:
            return False, f"series[{i}] must have a 'type' field"
    return True, ""


def normalize_echarts_option(raw_option: Any) -> tuple[dict[str, Any] | None, str]:
    """
    归一化 LLM 传入的 ECharts option，兼容以下情况：
    1) option 是 dict（正常）
    2) option 是 JSON 字符串（需要 json.loads）
    3) option 外层被包了一层 {"option": {...}}（自动解包）
    4) series 被错误给成 dict（自动转为 list）

    Returns:
        (option_dict_or_none, err_msg)
    """
    option_obj: Any = raw_option

    # case: option 是字符串
    if isinstance(option_obj, str):
        s = option_obj.strip()
        if not s:
            return None, "option is empty string"
        try:
            option_obj = json.loads(s)
        except json.JSONDecodeError as e:
            return None, (
                "option is a string but not valid JSON. "
                "Please provide strict JSON (double quotes, true/false/null). "
                f"json error: {e}"
            )

    if not isinstance(option_obj, dict):
        return None, "option must be a JSON object"

    # case: 被包裹了一层 {"option": {...}}
    if "series" not in option_obj and "option" in option_obj and isinstance(option_obj["option"], dict):
        option_obj = option_obj["option"]

    # case: series 给成了对象（容错）
    if "series" in option_obj and isinstance(option_obj["series"], dict):
        option_obj["series"] = [option_obj["series"]]

    return option_obj, ""


def merge_top_level_keys(option: dict, args: dict) -> dict:
    """
    兼容 LLM 把 series/xAxis 等放在 tool args 顶层而非 option 内的情况。
    将它们合并进 option。
    """
    merge_keys = (
        "series", "xAxis", "yAxis", "legend",
        "grid", "dataset", "tooltip", "title",
    )
    for key in merge_keys:
        if key not in option and key in args:
            option[key] = args[key]
    return option