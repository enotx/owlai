# backend/app/services/data_processor.py

"""数据处理服务：CSV 元数据解析、CSV 预览、TXT 全文读取"""

import json
import pandas as pd

# TXT 注入 prompt 的大小上限（约 12k tokens）
TEXT_MAX_BYTES = 50 * 1024  # 50KB


def parse_csv_metadata(file_path: str) -> str:
    """
    读取 CSV 文件，提取元数据并返回 JSON 字符串。
    包含：columns, dtypes, shape, head(5), describe()
    """
    df = pd.read_csv(file_path)
    metadata = {
        "columns": df.columns.tolist(),
        "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
        "shape": list(df.shape),  # [rows, cols]
        "head": json.loads(df.head(5).to_json(orient="records", force_ascii=False)),
        "describe": json.loads(df.describe(include="all").to_json(force_ascii=False)),
    }
    return json.dumps(metadata, ensure_ascii=False)


def get_csv_preview(file_path: str, n_rows: int = 50) -> dict:
    """
    返回 CSV 前 N 行数据，供前端 Table 展示。
    """
    df = pd.read_csv(file_path)
    return {
        "columns": df.columns.tolist(),
        "rows": json.loads(df.head(n_rows).to_json(orient="records", force_ascii=False)),
        "total_rows": len(df),
    }


def get_csv_sample_rows(file_path: str, n_rows: int = 200) -> str:
    """
    返回 CSV 前 N 行的 to_string() 表示，用于注入 Agent 上下文。
    """
    df = pd.read_csv(file_path, nrows=n_rows)
    return df.to_string(index=False, max_rows=n_rows, max_cols=30)


def read_text_content(file_path: str, max_bytes: int = TEXT_MAX_BYTES) -> str:
    """
    读取 TXT/文本文件全文，超过 max_bytes 截断并附加警告。
    """
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read(max_bytes)
    if len(content.encode("utf-8")) >= max_bytes:
        content += "\n\n[⚠️ Text truncated at 50KB limit]"
    return content


def sanitize_variable_name(filename: str) -> str:
    """
    将文件名转换为合法的 Python 变量名。
    例: 'sales-data (2024).csv' → 'df_sales_data_2024'
    """
    import re
    name = filename.rsplit(".", 1)[0]  # 去扩展名
    name = re.sub(r"[^a-zA-Z0-9_]", "_", name)  # 非法字符替换
    name = re.sub(r"_+", "_", name).strip("_")  # 合并连续下划线
    if not name or name[0].isdigit():
        name = "data_" + name
    return "df_" + name.lower()