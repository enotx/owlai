# backend/app/services/execution/types.py

"""执行上下文数据类"""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class ExecutionContext:
    """代码执行请求的完整上下文"""
    code: str
    task_id: str = ""

    # 数据注入：{var_name: local_file_path}
    data_var_map: dict[str, str] = field(default_factory=dict)

    # 上一轮持久化的中间变量：{var_name: .parquet/.json path}
    persisted_var_map: dict[str, str] = field(default_factory=dict)

    # 环境变量（Skill envs + __allowed_modules__ 等）
    injected_envs: dict[str, str] = field(default_factory=dict)

    # 捕获目录（DataFrame / chart / artifact 写入位置）
    capture_dir: str = ""

    # 超时（秒）
    timeout: int = 7200

    # 安全级别
    security_level: Literal["strict", "lenient", "off"] = "strict"