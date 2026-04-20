# backend/app/services/script_runner.py

"""Script 执行器 - 执行通用 Script（完全旁路 LLM）"""

import json
import os
import logging
from typing import Any, AsyncGenerator, Mapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import UPLOADS_DIR
from app.services.data_processor import (
    sanitize_variable_name
)
from app.models import Asset, Step, Visualization
from app.services.sandbox import (
    SandboxExecutionResult,
    execute_code_in_sandbox,
    is_sandbox_execution_result,
)
from app.services.execution_helpers import (
    HeartbeatEvent,
    is_heartbeat_event,
    run_with_heartbeat,
)

logger = logging.getLogger(__name__)


def _sse(data: Mapping[str, Any]) -> str:
    """生成 SSE 事件格式"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

ScriptRunnerEvent = dict[str, Any] | HeartbeatEvent


def _step_to_dict(step: Step) -> dict:
    """Step ORM → 可序列化 dict"""
    return {
        "id": step.id,
        "task_id": step.task_id,
        "role": step.role,
        "step_type": step.step_type,
        "content": step.content,
        "code": step.code,
        "code_output": step.code_output,
        "created_at": step.created_at.isoformat() if step.created_at else None,
    }

def _empty_sandbox_result() -> SandboxExecutionResult:
    return {
        "success": False,
        "output": None,
        "error": "Script execution returned no result",
        "execution_time": 0.0,
        "dataframes": [],
        "persisted_vars": {},
        "artifacts": [],
        "charts": [],
        "maps": [],
    }


# ============================================================
# 新增：原生 dict event 版本
# ============================================================
async def run_script_events(
    task_id: str,
    asset: Asset,
    db: AsyncSession,
    env_vars_override: dict[str, str] | None = None,
    data_source_ids: list[str] | None = None,
) -> AsyncGenerator[ScriptRunnerEvent, None]:
    """
    执行通用 Script，返回原生 dict event（不是 SSE 字符串）
    
    事件类型：
    - {"type": "text", "content": str}
    - {"type": "tool_start", "code": str, "purpose": str}
    - {"type": "tool_result", "success": bool, "output": str, "error": str, "time": float, "dataframes": list}
    - {"type": "step_saved", "step": dict}
    - {"type": "done"}
    - {"type": "error", "content": str}
    """
    yield {"type": "text", "content": f"🚀 Executing script: **{asset.name}**\n"}
    # 1. 读取 Asset 配置
    code = asset.code
    if not code:
        yield {"type": "error", "content": "Script code is empty"}
        yield {"type": "done"}
        return
    # 合并环境变量
    env_vars = json.loads(asset.env_vars_json) if asset.env_vars_json else {}
    if env_vars_override:
        env_vars.update(env_vars_override)
    allowed_modules = json.loads(asset.allowed_modules_json) if asset.allowed_modules_json else []
    # 2. 构建沙箱环境变量
    extra_envs = dict(env_vars)
    if allowed_modules:
        extra_envs["__allowed_modules__"] = json.dumps(allowed_modules)
    # 注入 ARTIFACT_DIR（指向 asset 专属 artifact 目录）
    asset_artifact_dir = os.path.join(UPLOADS_DIR, "assets", asset.id, "artifacts")
    if os.path.isdir(asset_artifact_dir):
        extra_envs["ARTIFACT_DIR"] = asset_artifact_dir
    capture_dir = os.path.join(UPLOADS_DIR, task_id, "captures")
    os.makedirs(capture_dir, exist_ok=True)
    # 3. 构建 data_var_map
    from app.models import Knowledge
    from sqlalchemy import select
    data_var_map: dict[str, str] = {}
    if data_source_ids:
        from app.models import DuckDBTable
        from sqlalchemy import select as sa_select
        for ds_id in data_source_ids:
            # 尝试作为 Knowledge 加载
            k = await db.get(Knowledge, ds_id)
            if k and k.type in ("csv", "excel") and k.file_path and os.path.exists(k.file_path):
                var_name = sanitize_variable_name(k.name)
                data_var_map[var_name] = os.path.abspath(k.file_path)
                continue
            
            # 尝试作为 DuckDB table 预加载
            query_result = await db.execute(
                sa_select(DuckDBTable).where(DuckDBTable.id == ds_id)
            )
            duckdb_table = query_result.scalar_one_or_none()
            if duckdb_table and duckdb_table.status == "ready":
                try:
                    temp_path = await _preload_duckdb_table(
                        table_name=duckdb_table.table_name,
                        display_name=duckdb_table.display_name,
                        capture_dir=capture_dir,
                    )
                    if temp_path:
                        var_name = sanitize_variable_name(duckdb_table.display_name)
                        data_var_map[var_name] = temp_path
                        yield {
                            "type": "text",
                            "content": f"📊 Preloaded DuckDB table `{duckdb_table.table_name}` as `{var_name}`\n",
                        }
                except Exception as e:
                    logger.warning(f"Failed to preload DuckDB table {duckdb_table.table_name}: {e}")
                    yield {
                        "type": "text",
                        "content": f"⚠️ Could not preload table `{duckdb_table.table_name}`: {e}\n",
                    }
                continue
    # 4. 发送 tool_start 事件
    yield {
        "type": "tool_start",
        "code": code,
        "purpose": f"Script: {asset.name}",
    }
    # 5. 执行代码（带心跳）
    try:
        result: SandboxExecutionResult | None = None
        async for item in run_with_heartbeat(
            execute_code_in_sandbox(
                code=code,
                data_var_map=data_var_map,
                capture_dir=capture_dir,
                injected_envs=extra_envs if extra_envs else None,
                timeout=1800,
            ),
            interval=15.0,
            message="script_running",
        ):
            if is_heartbeat_event(item):
                yield item
                continue
            if is_sandbox_execution_result(item):
                result = item
    except Exception as e:
        error_msg = f"Script execution error: {str(e)}"
        logger.error(error_msg)
        yield {
            "type": "tool_result",
            "success": False,
            "output": None,
            "error": error_msg,
            "time": 0,
        }
        # 保存失败记录
        step = Step(
            task_id=task_id,
            role="assistant",
            step_type="tool_use",
            content=f"Script execution: {asset.name}",
            code=code,
            code_output=json.dumps({
                "success": False, "output": None,
                "error": error_msg, "execution_time": 0.0,
            }, ensure_ascii=False),
        )
        db.add(step)
        await db.commit()
        await db.refresh(step)
        yield {"type": "step_saved", "step": _step_to_dict(step)}
        # 更新 Task 状态
        from app.models import Task
        from datetime import datetime
        task = await db.get(Task, task_id)
        if task:
            task.last_run_at = datetime.now()
            task.last_run_status = "failed"
            await db.commit()
        yield {"type": "text", "content": f"\n❌ Script failed: {error_msg}"}
        yield {"type": "done"}
        return
    # 6. 发送 tool_result 事件
    safe_result: SandboxExecutionResult = result or _empty_sandbox_result()

    yield {
        "type": "tool_result",
        "success": safe_result.get("success", False),
        "output": safe_result.get("output"),
        "error": safe_result.get("error"),
        "time": safe_result.get("execution_time", 0),
        "dataframes": safe_result.get("dataframes", []),
    }
    # 7. 处理沙箱内捕获的图表
    from app.tools import validate_echarts_option
    from app.tools.visualization import validate_map_config
    for chart_meta in safe_result.get("charts", []):
        chart_title = chart_meta.get("title", "Untitled Chart")
        chart_type = chart_meta.get("chart_type", "bar")
        chart_option = chart_meta.get("option", {})
        ok, err = validate_echarts_option(chart_option)
        if not ok:
            logger.warning(f"Invalid ECharts option in script replay: {err}")
            continue
        viz = Visualization(
            task_id=task_id,
            subtask_id=None,
            step_id=None,
            title=chart_title,
            chart_type=chart_type,
            option_json=json.dumps(chart_option, ensure_ascii=False),
        )
        db.add(viz)
        await db.flush()
        step = Step(
            task_id=task_id,
            role="assistant",
            step_type="visualization",
            content=chart_title,
            code=None,
            code_output=json.dumps({
                "visualization_id": viz.id,
                "title": chart_title,
                "chart_type": chart_type,
                "option": chart_option,
            }, ensure_ascii=False),
        )
        db.add(step)
        await db.flush()
        viz.step_id = step.id
        await db.commit()
        await db.refresh(step)
        yield {"type": "step_saved", "step": _step_to_dict(step)}
    for map_meta in safe_result.get("maps", []):
        map_title = map_meta.get("title", "Untitled Map")
        map_config = map_meta.get("config", {})
        ok, err = validate_map_config(map_config)
        if not ok:
            logger.warning(f"Invalid map config in script replay: {err}")
            continue
        viz = Visualization(
            task_id=task_id,
            subtask_id=None,
            step_id=None,
            title=map_title,
            chart_type="map",
            option_json=json.dumps(map_config, ensure_ascii=False),
        )
        db.add(viz)
        await db.flush()
        step = Step(
            task_id=task_id,
            role="assistant",
            step_type="visualization",
            content=map_title,
            code=None,
            code_output=json.dumps({
                "visualization_id": viz.id,
                "title": map_title,
                "chart_type": "map",
                "option": map_config,
            }, ensure_ascii=False),
        )
        db.add(step)
        await db.flush()
        viz.step_id = step.id
        await db.commit()
        await db.refresh(step)
        yield {"type": "step_saved", "step": _step_to_dict(step)}
    # 8. 保存执行结果为 Step
    step = Step(
        task_id=task_id,
        role="assistant",
        step_type="tool_use",
        content=f"Script execution: {asset.name}",
        code=code,
        code_output=json.dumps({
            "success": safe_result.get("success", False),
            "output": safe_result.get("output"),
            "error": safe_result.get("error"),
            "execution_time": safe_result.get("execution_time", 0),
            "dataframes": safe_result.get("dataframes", []),
        }, ensure_ascii=False),
    )
    db.add(step)
    await db.commit()
    await db.refresh(step)
    yield {"type": "step_saved", "step": _step_to_dict(step)}
    # 9. 更新 Task 状态
    from app.models import Task
    from datetime import datetime
    task = await db.get(Task, task_id)
    if task:
        task.last_run_at = datetime.now()
        task.last_run_status = "success" if safe_result.get("success", False) else "failed"
        await db.commit()
    # 10. 总结
    if safe_result.get("success", False):
        yield {
            "type": "text",
            "content": f"\n✅ Script completed successfully in {safe_result.get('execution_time', 0):.2f}s",
        }
    else:
        yield {
            "type": "text",
            "content": f"\n❌ Script failed: {safe_result.get('error', 'Unknown error')}",
        }
    yield {"type": "done"}

# ============================================================
# 保留：兼容层（SSE 版本）
# ============================================================
async def run_script(
    task_id: str,
    asset: Asset,
    db: AsyncSession,
    env_vars_override: dict[str, str] | None = None,
    data_source_ids: list[str] | None = None,
) -> AsyncGenerator[str, None]:
    """
    兼容层：包装 run_script_events() 为 SSE 字符串输出
    
    保留此函数是为了向后兼容，但新代码应优先使用 run_script_events()
    """
    async for event in run_script_events(
        task_id=task_id,
        asset=asset,
        db=db,
        env_vars_override=env_vars_override,
        data_source_ids=data_source_ids,
    ):
        yield _sse(event)


# ============================================================
# 辅助函数
# ============================================================
async def _preload_duckdb_table(
    table_name: str,
    display_name: str,
    capture_dir: str,
    row_limit: int = 100_000,
) -> str | None:
    """
    从 DuckDB warehouse 预加载表数据为临时 CSV 文件。
    返回临时文件路径，供 sandbox 的 data_var_map 加载。
    """
    import duckdb
    from app.config import WAREHOUSE_PATH

    if not WAREHOUSE_PATH or not os.path.exists(WAREHOUSE_PATH):
        logger.warning("WAREHOUSE_PATH not set or not found")
        return None

    preload_dir = os.path.join(capture_dir, "_preloaded")
    os.makedirs(preload_dir, exist_ok=True)

    safe_name = sanitize_variable_name(display_name)
    temp_csv_path = os.path.join(preload_dir, f"{safe_name}.csv")

    con = duckdb.connect(WAREHOUSE_PATH, read_only=True)
    try:
        df = con.execute(
            f"SELECT * FROM \"{table_name}\" LIMIT {row_limit}"
        ).fetchdf()
        df.to_csv(temp_csv_path, index=False)
        logger.info(
            f"Preloaded DuckDB table '{table_name}' → {temp_csv_path} "
            f"({len(df)} rows)"
        )
        return temp_csv_path
    except Exception as e:
        logger.error(f"DuckDB preload failed for '{table_name}': {e}")
        return None
    finally:
        con.close()