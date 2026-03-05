# backend/app/services/data_processor.py

"""CSV 元数据解析服务：读取 CSV → 提取 columns、dtypes、shape、head(5)、describe()"""

import json
import pandas as pd
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
    返回格式：{ columns: [...], rows: [...], total_rows: int }
    """
    df = pd.read_csv(file_path)
    return {
        "columns": df.columns.tolist(),
        "rows": json.loads(df.head(n_rows).to_json(orient="records", force_ascii=False)),
        "total_rows": len(df),
    }
