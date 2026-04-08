# backend/app/services/freshness.py

"""
DuckDB 表新鲜度评估引擎（精简版）。

核心逻辑：
- 有 Pipeline 且 is_auto 的表，检查 data_updated_at 距今是否超过阈值
- 超过 → 返回 stale，由 Agent 层决定是否触发 HITL
- 阈值可在 Pipeline 的 freshness_policy_json 中自定义，默认 24h
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DuckDBTable, DataPipeline

logger = logging.getLogger(__name__)


@dataclass
class FreshnessResult:
    """新鲜度评估结果"""
    is_fresh: bool
    reason: str
    staleness_hours: float | None = None  # 距上次更新的小时数
    max_staleness_hours: float | None = None  # 配置的阈值
    latest_data_date: str | None = None  # 表中记录的最新数据日期
    can_refresh: bool = False  # 是否有可执行的 Pipeline


def _parse_policy(policy_json: str) -> dict[str, Any]:
    """安全解析 freshness_policy_json"""
    try:
        policy = json.loads(policy_json)
        return policy if isinstance(policy, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


async def check_table_freshness(
    table_name: str,
    db: AsyncSession,
) -> FreshnessResult:
    """
    主入口：检查某张表的新鲜度。

    判定规则（极简）：
    1. 无表 / 无 Pipeline / Pipeline 非 auto → 视为 fresh（不主动管理）
    2. data_updated_at 为空 → stale
    3. now - data_updated_at > max_staleness_hours → stale
    4. 其余 → fresh

    max_staleness_hours 取自 freshness_policy_json:
        {"max_staleness_hours": 24}   # 默认 24
    """
    # 查找表元数据
    result = await db.execute(
        select(DuckDBTable).where(DuckDBTable.table_name == table_name)
    )
    table = result.scalar_one_or_none()

    if table is None:
        return FreshnessResult(
            is_fresh=True,
            reason=f"Table '{table_name}' not registered.",
            can_refresh=False,
        )

    # 查找关联 Pipeline
    pipeline: DataPipeline | None = None
    if table.pipeline_id:
        p_result = await db.execute(
            select(DataPipeline).where(DataPipeline.id == table.pipeline_id)
        )
        pipeline = p_result.scalar_one_or_none()

    if pipeline is None or not pipeline.is_auto:
        return FreshnessResult(
            is_fresh=True,
            reason="No auto-refresh pipeline — freshness not managed.",
            latest_data_date=table.latest_data_date,
            can_refresh=pipeline is not None,
        )

    # 解析阈值
    policy = _parse_policy(pipeline.freshness_policy_json)
    max_hours = float(policy.get("max_staleness_hours", 24))

    # 从未更新过
    if table.data_updated_at is None:
        return FreshnessResult(
            is_fresh=False,
            reason="Table has never been refreshed.",
            staleness_hours=None,
            max_staleness_hours=max_hours,
            latest_data_date=table.latest_data_date,
            can_refresh=True,
        )

    # 计算年龄
    age_seconds = (datetime.now() - table.data_updated_at).total_seconds()
    age_hours = age_seconds / 3600

    if age_hours <= max_hours:
        return FreshnessResult(
            is_fresh=True,
            reason=f"Updated {age_hours:.1f}h ago (threshold: {max_hours}h).",
            staleness_hours=round(age_hours, 2),
            max_staleness_hours=max_hours,
            latest_data_date=table.latest_data_date,
            can_refresh=True,
        )

    return FreshnessResult(
        is_fresh=False,
        reason=f"Data is {age_hours:.1f}h old (threshold: {max_hours}h).",
        staleness_hours=round(age_hours, 2),
        max_staleness_hours=max_hours,
        latest_data_date=table.latest_data_date,
        can_refresh=True,
    )


async def check_stale_tables(
    db: AsyncSession,
) -> dict[str, FreshnessResult]:
    """
    批量检查所有 is_auto Pipeline 关联的表，返回过期的。
    {table_name: FreshnessResult}
    """
    result = await db.execute(
        select(DuckDBTable, DataPipeline)
        .outerjoin(DataPipeline, DuckDBTable.pipeline_id == DataPipeline.id)
        .where(DataPipeline.is_auto == True)
    )
    rows = result.all()

    stale: dict[str, FreshnessResult] = {}
    for table, pipeline in rows:
        policy = _parse_policy(pipeline.freshness_policy_json)
        max_hours = float(policy.get("max_staleness_hours", 24))

        if table.data_updated_at is None:
            stale[table.table_name] = FreshnessResult(
                is_fresh=False,
                reason="Never refreshed.",
                max_staleness_hours=max_hours,
                latest_data_date=table.latest_data_date,
                can_refresh=True,
            )
            continue

        age_hours = (datetime.now() - table.data_updated_at).total_seconds() / 3600
        if age_hours > max_hours:
            stale[table.table_name] = FreshnessResult(
                is_fresh=False,
                reason=f"Data is {age_hours:.1f}h old (threshold: {max_hours}h).",
                staleness_hours=round(age_hours, 2),
                max_staleness_hours=max_hours,
                latest_data_date=table.latest_data_date,
                can_refresh=True,
            )

    return stale