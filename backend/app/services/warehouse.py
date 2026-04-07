# backend/app/services/warehouse.py

"""
DuckDB 本地数据仓库管理服务。

职责：
- 管理 warehouse.duckdb 文件
- 提供 DataFrame 写入（物化）、查询、表管理功能
- 所有 DuckDB 操作在此集中，避免散落各处
"""

import asyncio
import json
import re
# import logging
from datetime import datetime
from typing import Any

import duckdb
import pandas as pd

from app.config import WAREHOUSE_PATH

# logger = logging.getLogger(__name__)

# 合法表名正则（字母/下划线开头，仅允许字母数字下划线）
_VALID_TABLE_NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,127}$")


def _sanitize_table_name(name: str) -> str:
    """清洗表名：转小写、替换非法字符、确保有效"""
    name = name.strip().lower()
    name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    if not name or name[0].isdigit():
        name = "t_" + name
    if len(name) > 128:
        name = name[:128]
    return name


def validate_table_name(name: str) -> tuple[bool, str]:
    """验证表名是否合法，返回 (is_valid, error_message)"""
    if not name:
        return False, "Table name cannot be empty"
    if not _VALID_TABLE_NAME.match(name):
        return False, (
            f"Invalid table name '{name}'. Must start with a letter or underscore, "
            "contain only letters, digits, and underscores, max 128 chars."
        )
    # DuckDB 保留字检查（简化版）
    reserved = {
        "select", "from", "where", "table", "create", "drop", "insert",
        "update", "delete", "index", "view", "database", "schema",
        "order", "group", "by", "having", "limit", "offset", "union",
        "join", "on", "as", "and", "or", "not", "null", "true", "false",
    }
    if name.lower() in reserved:
        return False, f"'{name}' is a SQL reserved word. Please choose a different name."
    return True, ""


def write_dataframe(
    df: pd.DataFrame,
    table_name: str,
    strategy: str = "replace",
    upsert_key: str | None = None,
) -> dict[str, Any]:
    """
    将 DataFrame 写入 DuckDB 仓库。

    Args:
        df: 要写入的 DataFrame
        table_name: 目标表名（已验证过）
        strategy: "replace" | "append" | "upsert"
        upsert_key: upsert 模式下的主键列名

    Returns:
        {"rows_written": int, "total_rows": int, "schema": list[dict]}
    """
    db_path = str(WAREHOUSE_PATH)
    con = duckdb.connect(db_path)
    try:
        if strategy == "replace":
            con.execute(f"DROP TABLE IF EXISTS \"{table_name}\"")
            con.execute(f"CREATE TABLE \"{table_name}\" AS SELECT * FROM df")

        elif strategy == "append":
            # 表不存在则创建
            tables = [row[0] for row in con.execute("SHOW TABLES").fetchall()]
            if table_name not in tables:
                con.execute(f"CREATE TABLE \"{table_name}\" AS SELECT * FROM df")
            else:
                con.execute(f"INSERT INTO \"{table_name}\" SELECT * FROM df")

        elif strategy == "upsert":
            if not upsert_key:
                raise ValueError("upsert_key is required for upsert strategy")
            tables = [row[0] for row in con.execute("SHOW TABLES").fetchall()]
            if table_name not in tables:
                con.execute(f"CREATE TABLE \"{table_name}\" AS SELECT * FROM df")
            else:
                # DELETE matching rows, then INSERT all
                con.execute(
                    f"DELETE FROM \"{table_name}\" WHERE \"{upsert_key}\" IN "
                    f"(SELECT \"{upsert_key}\" FROM df)"
                )
                con.execute(f"INSERT INTO \"{table_name}\" SELECT * FROM df")
        else:
            raise ValueError(f"Unknown write strategy: {strategy}")

        # 获取写入结果
        total_rows_result = con.execute(f"SELECT COUNT(*) FROM \"{table_name}\"").fetchone()
        total_rows = total_rows_result[0] if total_rows_result and total_rows_result[0] is not None else 0
        schema = _get_table_schema(con, table_name)

        return {
            "rows_written": len(df),
            "total_rows": total_rows,
            "schema": schema,
        }
    finally:
        con.close()


def query(sql: str, limit: int = 10000) -> pd.DataFrame:
    """只读查询 DuckDB 仓库"""
    db_path = str(WAREHOUSE_PATH)
    con = duckdb.connect(db_path, read_only=True)
    try:
        # 安全限制：自动追加 LIMIT（如果用户没写）
        sql_upper = sql.strip().upper()
        if "LIMIT" not in sql_upper:
            sql = f"{sql.rstrip(';')} LIMIT {limit}"
        return con.execute(sql).fetchdf()
    finally:
        con.close()


def list_tables() -> list[dict[str, Any]]:
    """列出 DuckDB 仓库中的所有表"""
    db_path = str(WAREHOUSE_PATH)
    if not WAREHOUSE_PATH.exists():
        return []
    con = duckdb.connect(db_path, read_only=True)
    try:
        tables = []
        rows = con.execute("SHOW TABLES").fetchall()
        for (tname,) in rows:
            try:
                count_result = con.execute(f"SELECT COUNT(*) FROM \"{tname}\"").fetchone()
                count = count_result[0] if count_result is not None else -1
                schema = _get_table_schema(con, tname)
                tables.append({
                    "table_name": tname,
                    "row_count": count,
                    "schema": schema,
                })
            except Exception:
                tables.append({
                    "table_name": tname,
                    "row_count": -1,
                    "schema": [],
                })
        return tables
    finally:
        con.close()


def get_table_preview(table_name: str, limit: int = 50) -> dict[str, Any]:
    """获取表的数据预览"""
    db_path = str(WAREHOUSE_PATH)
    con = duckdb.connect(db_path, read_only=True)
    try:
        total_result = con.execute(f"SELECT COUNT(*) FROM \"{table_name}\"").fetchone()
        total = total_result[0] if total_result and total_result[0] is not None else 0
        df = con.execute(f"SELECT * FROM \"{table_name}\" LIMIT {limit}").fetchdf()
        # 处理 NaN → None
        df = df.where(pd.notnull(df), None)
        columns = [str(c) for c in df.columns.tolist()]
        rows = json.loads(df.to_json(orient="records", default_handler=str))
        return {
            "columns": columns,
            "rows": rows,
            "total_rows": total,
        }
    finally:
        con.close()


def get_table_schema(table_name: str) -> list[dict[str, str]]:
    """获取单张表的 schema"""
    db_path = str(WAREHOUSE_PATH)
    con = duckdb.connect(db_path, read_only=True)
    try:
        return _get_table_schema(con, table_name)
    finally:
        con.close()


def drop_table(table_name: str) -> bool:
    """删除 DuckDB 中的表"""
    db_path = str(WAREHOUSE_PATH)
    con = duckdb.connect(db_path)
    try:
        con.execute(f"DROP TABLE IF EXISTS \"{table_name}\"")
        return True
    finally:
        con.close()


def table_exists(table_name: str) -> bool:
    """检查表是否存在"""
    db_path = str(WAREHOUSE_PATH)
    if not WAREHOUSE_PATH.exists():
        return False
    con = duckdb.connect(db_path, read_only=True)
    try:
        tables = [row[0] for row in con.execute("SHOW TABLES").fetchall()]
        return table_name in tables
    finally:
        con.close()


def _get_table_schema(con: duckdb.DuckDBPyConnection, table_name: str) -> list[dict[str, str]]:
    """内部函数：获取表 schema（需已打开连接）"""
    result = con.execute(f"DESCRIBE \"{table_name}\"").fetchall()
    schema = []
    for row in result:
        schema.append({
            "name": row[0],
            "type": row[1],
        })
    return schema


async def async_write_dataframe(
    df: pd.DataFrame,
    table_name: str,
    strategy: str = "replace",
    upsert_key: str | None = None,
) -> dict[str, Any]:
    """异步包装：在线程池中执行 DuckDB 写入"""
    return await asyncio.to_thread(write_dataframe, df, table_name, strategy, upsert_key)


async def async_query(sql: str, limit: int = 10000) -> pd.DataFrame:
    """异步包装：在线程池中执行 DuckDB 查询"""
    return await asyncio.to_thread(query, sql, limit)


async def async_list_tables() -> list[dict[str, Any]]:
    """异步包装"""
    return await asyncio.to_thread(list_tables)


async def async_get_table_preview(table_name: str, limit: int = 50) -> dict[str, Any]:
    """异步包装"""
    return await asyncio.to_thread(get_table_preview, table_name, limit)


async def async_drop_table(table_name: str) -> bool:
    """异步包装"""
    return await asyncio.to_thread(drop_table, table_name)


async def async_table_exists(table_name: str) -> bool:
    """异步包装"""
    return await asyncio.to_thread(table_exists, table_name)