# backend/app/services/warehouse.py

"""
DuckDB 本地数据仓库管理服务。

职责：
- 管理 warehouse.duckdb 文件
- 提供 DataFrame 写入（物化）、查询、表管理功能
- 元数据按需同步（reconcile）
- 所有 DuckDB 操作在此集中，避免散落各处
"""

import asyncio
import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

import duckdb
import pandas as pd

from app.config import WAREHOUSE_PATH

def _get_warehouse_path() -> str:
    """获取当前租户的 warehouse 路径"""
    try:
        from app.tenant_context import get_warehouse_path
        return str(get_warehouse_path())
    except RuntimeError:
        # Fallback：非请求上下文中（如启动时），使用全局路径
        from app.config import WAREHOUSE_PATH
        return _get_warehouse_path()
def _warehouse_exists() -> bool:
    """检查 warehouse 文件是否存在"""
    from pathlib import Path
    return Path(_get_warehouse_path()).exists()


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
    db_path = _get_warehouse_path()
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


def query(sql: str, limit: int = 100000) -> pd.DataFrame:
    """只读查询 DuckDB 仓库"""
    db_path = _get_warehouse_path()
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
    db_path = _get_warehouse_path()
    if not _warehouse_exists():
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
    db_path = _get_warehouse_path()
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
    db_path = _get_warehouse_path()
    con = duckdb.connect(db_path, read_only=True)
    try:
        return _get_table_schema(con, table_name)
    finally:
        con.close()


def drop_table(table_name: str) -> bool:
    """删除 DuckDB 中的表"""
    db_path = _get_warehouse_path()
    con = duckdb.connect(db_path)
    try:
        con.execute(f"DROP TABLE IF EXISTS \"{table_name}\"")
        return True
    finally:
        con.close()


def table_exists(table_name: str) -> bool:
    """检查表是否存在"""
    db_path = _get_warehouse_path()
    if not _warehouse_exists():
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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 元数据同步（新增）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def reconcile_metadata(db: AsyncSession) -> dict[str, Any]:
    """
    轻量级元数据同步：对比 DuckDB 物理表和 SQLite 元数据。
    
    策略：
    - DuckDB 有、SQLite 没有 → 自动创建元数据记录
    - SQLite 有、DuckDB 没有 → 标记为 error 状态（不删除，保留血缘）
    - 已存在的记录不强刷 schema/row_count（避免性能开销）
    
    适用场景：列表页加载时调用
    
    Returns:
        {"created": int, "marked_error": int, "skipped": int}
    """
    from app.models import DuckDBTable
    
    # 获取 DuckDB 物理表列表
    physical_tables = await async_list_tables()
    physical_table_names = {t["table_name"] for t in physical_tables}
    
    # 获取 SQLite 元数据记录
    result = await db.execute(select(DuckDBTable))
    metadata_records = {t.table_name: t for t in result.scalars().all()}
    
    created = 0
    marked_error = 0
    skipped = 0
    
    # 处理新增表（DuckDB 有，SQLite 没有）
    for table_name in physical_table_names:
        if table_name not in metadata_records:
            # 创建元数据记录
            table_info = next(t for t in physical_tables if t["table_name"] == table_name)
            new_record = DuckDBTable(
                table_name=table_name,
                display_name=table_name.replace("_", " ").title(),
                description="Auto-detected from DuckDB warehouse",
                table_schema_json=json.dumps(table_info["schema"], ensure_ascii=False),
                row_count=table_info["row_count"],
                source_type="code_execution",
                data_updated_at=datetime.now(),
                status="ready",
            )
            db.add(new_record)
            created += 1
        else:
            skipped += 1
    
    # 处理孤立元数据（SQLite 有，DuckDB 没有）
    for table_name, record in metadata_records.items():
        if table_name not in physical_table_names:
            if record.status != "error":
                record.status = "error"
                marked_error += 1
    
    await db.commit()
    
    return {
        "created": created,
        "marked_error": marked_error,
        "skipped": skipped,
    }


async def sync_table_metadata(
    table_name: str,
    db: AsyncSession,
) -> bool:
    """
    单表强校验：刷新指定表的 schema、row_count、data_updated_at。
    
    适用场景：预览表时调用
    
    Returns:
        是否成功同步（False 表示表不存在）
    """
    from app.models import DuckDBTable
    
    # 检查物理表是否存在
    exists = await async_table_exists(table_name)
    if not exists:
        # 标记元数据为 error
        result = await db.execute(
            select(DuckDBTable).where(DuckDBTable.table_name == table_name)
        )
        record = result.scalar_one_or_none()
        if record:
            record.status = "error"
            await db.commit()
        return False
    
    # 获取最新信息
    schema = await asyncio.to_thread(get_table_schema, table_name)
    
    db_path = _get_warehouse_path()
    con = await asyncio.to_thread(duckdb.connect, db_path, read_only=True)
    try:
        count_result = await asyncio.to_thread(
            con.execute(f"SELECT COUNT(*) FROM \"{table_name}\"").fetchone
        )
        row_count = count_result[0] if count_result else 0
    finally:
        await asyncio.to_thread(con.close)
    
    # 更新元数据
    result = await db.execute(
        select(DuckDBTable).where(DuckDBTable.table_name == table_name)
    )
    record = result.scalar_one_or_none()
    
    if record:
        record.table_schema_json = json.dumps(schema, ensure_ascii=False)
        record.row_count = row_count
        record.data_updated_at = datetime.now()
        record.status = "ready"
    else:
        # 不存在则创建
        record = DuckDBTable(
            table_name=table_name,
            display_name=table_name.replace("_", " ").title(),
            description="Auto-synced from DuckDB warehouse",
            table_schema_json=json.dumps(schema, ensure_ascii=False),
            row_count=row_count,
            source_type="code_execution",
            data_updated_at=datetime.now(),
            status="ready",
        )
        db.add(record)
    
    await db.commit()
    return True


async def full_sync_metadata(db: AsyncSession) -> dict[str, Any]:
    """
    显式全量同步：扫描所有 DuckDB 表，完整更新元数据。
    
    策略：
    - 更新所有表的 schema、row_count、data_updated_at
    - 删除孤立的元数据记录（物理表已不存在）
    - 创建新发现的表
    
    适用场景：用户点击"刷新"按钮时调用
    
    Returns:
        {"created": int, "updated": int, "deleted": int}
    """
    from app.models import DuckDBTable
    
    # 获取 DuckDB 物理表列表（含详细信息）
    physical_tables = await async_list_tables()
    physical_table_map = {t["table_name"]: t for t in physical_tables}
    physical_table_names = set(physical_table_map.keys())
    
    # 获取 SQLite 元数据记录
    result = await db.execute(select(DuckDBTable))
    metadata_records = {t.table_name: t for t in result.scalars().all()}
    
    created = 0
    updated = 0
    deleted = 0
    now = datetime.now()
    
    # 更新/创建物理表的元数据
    for table_name, table_info in physical_table_map.items():
        schema_json = json.dumps(table_info["schema"], ensure_ascii=False)
        row_count = table_info["row_count"]
        
        if table_name in metadata_records:
            # 更新现有记录
            record = metadata_records[table_name]
            record.table_schema_json = schema_json
            record.row_count = row_count
            record.data_updated_at = now
            record.status = "ready"
            updated += 1
        else:
            # 创建新记录
            new_record = DuckDBTable(
                table_name=table_name,
                display_name=table_name.replace("_", " ").title(),
                description="Synced from DuckDB warehouse",
                table_schema_json=schema_json,
                row_count=row_count,
                source_type="code_execution",
                data_updated_at=now,
                status="ready",
            )
            db.add(new_record)
            created += 1
    
    # 删除孤立的元数据（物理表已不存在）
    for table_name, record in metadata_records.items():
        if table_name not in physical_table_names:
            await db.delete(record)
            deleted += 1
    
    await db.commit()
    
    return {
        "created": created,
        "updated": updated,
        "deleted": deleted,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 异步包装（保持不变）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def async_write_dataframe(
    df: pd.DataFrame,
    table_name: str,
    strategy: str = "replace",
    upsert_key: str | None = None,
) -> dict[str, Any]:
    """异步包装：在线程池中执行 DuckDB 写入"""
    return await asyncio.to_thread(write_dataframe, df, table_name, strategy, upsert_key)


async def async_query(sql: str, limit: int = 100000) -> pd.DataFrame:
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


async def update_table_metadata(
    table_name: str,
    db: AsyncSession | None = None,
    **kwargs: Any,
) -> bool:
    """
    更新 DuckDBTable 元数据字段。

    可更新字段: display_name, description, row_count, table_schema_json,
    source_type, source_config, pipeline_id, data_updated_at,
    latest_data_date, query_transform_code, status

    Args:
        table_name: DuckDB 表名
        db: 异步会话（如果为 None，会自动创建）
        **kwargs: 要更新的字段

    Returns:
        是否成功找到并更新
    """
    from app.models import DuckDBTable

    async def _do_update(session: AsyncSession) -> bool:
        result = await session.execute(
            select(DuckDBTable).where(DuckDBTable.table_name == table_name)
        )
        table = result.scalar_one_or_none()
        if table is None:
            return False

        allowed_fields = {
            "display_name", "description", "row_count", "table_schema_json",
            "source_type", "source_config", "pipeline_id", "data_updated_at",
            "latest_data_date", "status",
        }
        for key, value in kwargs.items():
            if key in allowed_fields:
                setattr(table, key, value)

        await session.commit()
        return True

    if db is not None:
        return await _do_update(db)
    else:
        from app.database import async_session
        async with async_session() as session:
            return await _do_update(session)