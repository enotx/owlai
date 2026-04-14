# backend/app/services/token_counter.py
"""Token 计数工具 - 使用 tiktoken 精确计算"""

import tiktoken
from typing import Any

_encoding = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """计算文本的 token 数量"""
    if not text:
        return 0
    return len(_encoding.encode(text))


def count_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """
    计算 OpenAI messages 列表的 token 数量
    
    参考 OpenAI 官方计数规则：
    - 每条消息有 3 个固定 token 的开销
    - 整个对话有 3 个固定 token 的开销
    """
    total = 3  # 对话开始标记
    
    for msg in messages:
        total += 3  # 每条消息的固定开销
        
        if "role" in msg:
            total += count_tokens(str(msg["role"]))
        
        if "content" in msg and msg["content"]:
            total += count_tokens(str(msg["content"]))
        
        if "tool_calls" in msg:
            for tc in msg["tool_calls"]:
                if isinstance(tc, dict):
                    total += count_tokens(tc.get("id", ""))
                    if "function" in tc:
                        func = tc["function"]
                        total += count_tokens(func.get("name", ""))
                        total += count_tokens(func.get("arguments", ""))
        
        if "tool_call_id" in msg:
            total += count_tokens(str(msg["tool_call_id"]))
    
    return total