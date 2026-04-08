# backend/app/services/pipeline_executor.py

"""
Data Pipeline 执行引擎。

职责：
- 在沙箱中执行 Pipeline 的 transform_code
- 将产出的 result_df 写入 DuckDB
- 更新 DuckDBTable / DataPipeline 元数据
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import UPLOADS_DIR, WAREHOUSE_PATH
from app.models import DuckDBTable, DataPipeline
from app.services import warehouse as wh
from app.services.sandbox import execute_code_in_sandbox

logger = logging.getLogger(__name__)


@dataclass
class PipelineExecutionResult:
    """Pipeline 执行结果"""
    success: bool
    message: str
    rows_written: int = 0
    total_rows: int = 0
    latest_data_date: str | None = None
    execution_time: float = 0.0
    error: str | None = None


def _build_pipeline_wrapper(
    transform_code: str,
    source_config: str,
    freshness_policy_json: str,
) -> str:
    """
    包装 Pipeline 的 transform_code，注入辅助函数和参数。

    约定：
    - transform_code 中可使用 `warehouse_query(sql)` 查询已有 DuckDB 表
    - transform_code 中可使用 `pipeline_params` 获取源配置参数
    - transform_code 中可使用 `freshness_policy` 获取新鲜度策略
    - transform_code 必须将最终结果赋给 `result_df` (pd.DataFrame)
    - transform_code 可选地赋值 `latest_data_date` (str) 标识数据截止日期
    """
    try:
        params = json.loads(source_config) if source_config else {}
    except (json.JSONDecodeError, TypeError):
        params = {}

    try:
        policy = json.loads(freshness_policy_json) if freshness_policy_json else {}
    except (json.JSONDecodeError, TypeError):
        policy = {}

    params_repr = repr(params)
    policy_repr = repr(policy)

    wrapper = f"""\
import duckdb as _duckdb

# ── Pipeline 辅助函数 ──────────────────────────────────────
def warehouse_query(sql, limit=100000):
    \"\"\"查询 DuckDB 仓库已有表（只读）\"\"\"
    _wh_path = getenv('WAREHOUSE_PATH', '')
    if not _wh_path:
        raise RuntimeError("WAREHOUSE_PATH not set")
    _con = _duckdb.connect(_wh_path, read_only=True)
    try:
        _sql = sql.rstrip(';')
        if 'LIMIT' not in sql.upper():
            _sql = _sql + f' LIMIT {{limit}}'
        return _con.execute(_sql).fetchdf()
    finally:
        _con.close()

# ── Pipeline 参数 ──────────────────────────────────────────
pipeline_params = {params_repr}
freshness_policy = {policy_repr}

# ── 用户 transform_code 开始 ──────────────────────────────
{transform_code}
# ── 用户 transform_code 结束 ──────────────────────────────
"""
    return wrapper


async def execute_pipeline(
    pipeline: DataPipeline,
    table: DuckDBTable,
    db: AsyncSession,
) -> PipelineExecutionResult:
    """
    执行 Pipeline 的完整流程：

    1. 包装 transform_code，注入 warehouse_query / pipeline_params
    2. 在沙箱中执行，提取 result_df
    3. 将 result_df 写入 DuckDB（按 write_strategy）
    4. 更新 DuckDBTable 元数据
    5. 更新 DataPipeline 执行记录

    Args:
        pipeline: 要执行的 DataPipeline
        table: 目标 DuckDBTable
        db: 异步数据库会话

    Returns:
        PipelineExecutionResult
    """
    now = datetime.now()

    # 标记表状态为 refreshing
    table.status = "refreshing"
    await db.commit()

    # ── Step 1: 构建沙箱代码 ──────────────────────────────
    wrapped_code = _build_pipeline_wrapper(
        transform_code=pipeline.transform_code,
        source_config=pipeline.source_config,
        freshness_policy_json=pipeline.freshness_policy_json,
    )

    # 创建临时捕获目录
    capture_dir = os.path.join(
        UPLOADS_DIR, "_pipelines", pipeline.id, "captures"
    )
    os.makedirs(capture_dir, exist_ok=True)

    # ── Step 2: 沙箱执行 ─────────────────────────────────
    # Pipeline 沙箱允许的额外模块（从 source_config 或 pipeline 自身声明）
    extra_envs: dict[str, str] = {}
    try:
        src_cfg = json.loads(pipeline.source_config) if pipeline.source_config else {}
        extra_modules = src_cfg.get("allowed_modules", [])
        if extra_modules:
            extra_envs["__allowed_modules__"] = json.dumps(extra_modules)
    except (json.JSONDecodeError, TypeError):
        pass

    try:
        exec_result = await execute_code_in_sandbox(
            code=wrapped_code,
            data_var_map={},  # Pipeline 不加载 CSV，数据通过 warehouse_query 获取
            timeout=600,  # Pipeline 允许更长时间（10 分钟）
            capture_dir=capture_dir,
            injected_envs=extra_envs if extra_envs else None,
        )
    except Exception as e:
        error_msg = f"Pipeline sandbox execution error: {str(e)}"
        logger.error(error_msg)
        await _update_pipeline_status(pipeline, table, db, success=False, error=error_msg)
        return PipelineExecutionResult(
            success=False,
            message=error_msg,
            error=error_msg,
        )

    execution_time = exec_result.get("execution_time", 0.0)

    if not exec_result.get("success"):
        error_msg = exec_result.get("error", "Unknown pipeline execution error")
        logger.error(f"Pipeline '{pipeline.name}' failed: {error_msg}")
        await _update_pipeline_status(pipeline, table, db, success=False, error=error_msg)
        return PipelineExecutionResult(
            success=False,
            message=f"Pipeline execution failed: {error_msg}",
            error=error_msg,
            execution_time=execution_time,
        )

    # ── Step 3: 从沙箱 persist/ 提取 result_df ──────────
    result_df = await _extract_result_df(capture_dir)

    if result_df is None:
        error_msg = (
            "Pipeline transform_code did not produce a 'result_df' DataFrame. "
            "Make sure your code assigns the final result to `result_df`."
        )
        logger.error(f"Pipeline '{pipeline.name}': {error_msg}")
        await _update_pipeline_status(pipeline, table, db, success=False, error=error_msg)
        return PipelineExecutionResult(
            success=False,
            message=error_msg,
            error=error_msg,
            execution_time=execution_time,
        )

    if result_df.empty:
        # 空 DataFrame 不写入，但不算失败
        logger.warning(f"Pipeline '{pipeline.name}' produced empty result_df")
        await _update_pipeline_status(pipeline, table, db, success=True, error=None)
        return PipelineExecutionResult(
            success=True,
            message="Pipeline produced empty result — no data written.",
            rows_written=0,
            total_rows=table.row_count,
            execution_time=execution_time,
        )

    # ── Step 4: 写入 DuckDB ──────────────────────────────
    try:
        write_result = await wh.async_write_dataframe(
            df=result_df,
            table_name=pipeline.target_table_name,
            strategy=pipeline.write_strategy,
            upsert_key=pipeline.upsert_key,
        )
    except Exception as e:
        error_msg = f"DuckDB write failed: {str(e)}"
        logger.error(f"Pipeline '{pipeline.name}': {error_msg}")
        await _update_pipeline_status(pipeline, table, db, success=False, error=error_msg)
        return PipelineExecutionResult(
            success=False,
            message=error_msg,
            error=error_msg,
            execution_time=execution_time,
        )

    # ── Step 5: 提取 latest_data_date ────────────────────
    latest_date = await _extract_latest_date(capture_dir, pipeline, result_df)

    # ── Step 6: 更新元数据 ────────────────────────────────
    table.row_count = write_result["total_rows"]
    table.table_schema_json = json.dumps(write_result["schema"], ensure_ascii=False)
    table.data_updated_at = now
    table.status = "ready"
    if latest_date:
        table.latest_data_date = latest_date

    pipeline.last_run_at = now
    pipeline.last_run_status = "success"
    pipeline.last_run_error = None

    await db.commit()

    message = (
        f"Pipeline '{pipeline.name}' completed: "
        f"{write_result['rows_written']:,} rows written "
        f"(total: {write_result['total_rows']:,})"
    )
    if latest_date:
        message += f", latest date: {latest_date}"

    logger.info(message)

    return PipelineExecutionResult(
        success=True,
        message=message,
        rows_written=write_result["rows_written"],
        total_rows=write_result["total_rows"],
        latest_data_date=latest_date,
        execution_time=execution_time,
    )


async def _extract_result_df(capture_dir: str) -> pd.DataFrame | None:
    """
    从沙箱 persist/ 目录提取 result_df。

    优先 Parquet，回退 JSON。
    """
    import pyarrow.parquet as pq

    persist_dir = os.path.join(capture_dir, "persist")

    # 优先 parquet
    parquet_path = os.path.join(persist_dir, "result_df.parquet")
    if os.path.exists(parquet_path):
        try:
            table = pq.read_table(parquet_path)
            return table.to_pandas()
        except Exception as e:
            logger.warning(f"Failed to read result_df.parquet: {e}")

    # 回退 JSON
    json_path = os.path.join(persist_dir, "result_df.json")
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                blob = json.load(f)
            ptype = blob.get("__persist_type__")
            if ptype not in (None, "dataframe"):
                return None
            cols = blob.get("columns", [])
            rows = blob.get("rows", [])
            return pd.DataFrame(rows, columns=cols) if cols else pd.DataFrame(rows)
        except Exception as e:
            logger.warning(f"Failed to read result_df.json: {e}")

    return None


async def _extract_latest_date(
    capture_dir: str,
    pipeline: DataPipeline,
    result_df: pd.DataFrame,
) -> str | None:
    """
    提取数据的 latest_data_date。

    优先级：
    1. 沙箱中显式赋值的 `latest_data_date` 变量
    2. 从 freshness_policy 中指定的 time_column 自动推断
    """
    # 方式 1：从 persist/ 读取 latest_data_date 变量
    persist_dir = os.path.join(capture_dir, "persist")
    for ext in (".json",):
        fpath = os.path.join(persist_dir, f"latest_data_date{ext}")
        if os.path.exists(fpath):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    blob = json.load(f)
                val = blob.get("value")
                if val is not None:
                    return str(val)
            except Exception:
                pass

    # 方式 2：从 freshness_policy 的 time_column 推断
    try:
        policy = json.loads(pipeline.freshness_policy_json) if pipeline.freshness_policy_json else {}
    except (json.JSONDecodeError, TypeError):
        policy = {}

    time_column = policy.get("time_column")
    time_format = policy.get("time_format", "%Y%m%d")

    if time_column and time_column in result_df.columns:
        try:
            col = result_df[time_column]
            # 转为字符串取 max
            max_val = str(col.max())
            if max_val and max_val != "nan" and max_val != "NaT":
                return max_val
        except Exception:
            pass

    return None


async def _update_pipeline_status(
    pipeline: DataPipeline,
    table: DuckDBTable,
    db: AsyncSession,
    success: bool,
    error: str | None,
) -> None:
    """更新 Pipeline 和 Table 的状态（失败场景）"""
    now = datetime.now()

    pipeline.last_run_at = now
    pipeline.last_run_status = "success" if success else "error"
    pipeline.last_run_error = error

    if not success:
        table.status = "stale"
    else:
        table.status = "ready"

    try:
        await db.commit()
    except Exception as e:
        logger.error(f"Failed to update pipeline/table status: {e}")
